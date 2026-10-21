"""Las mismas fuentes por los tres canales (Actions, n8n, Perú): canales por URL, copias y avisos."""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from enso import observatory as obs
from enso import registry, sourcefeed
from enso.fetch import Fetcher, Relay
from tools import probe_sources

NOW = datetime.now(timezone.utc)
AT = (NOW - timedelta(hours=2)).isoformat(timespec="seconds")
ENFEN = "https://enfen.imarpe.gob.pe/wp-json/wp/v2/posts?per_page=10&search=comunicado"
ENFEN_HTML = "https://enfen.imarpe.gob.pe/comunicados/"
DHN = "https://www.dhn.mil.pe/portal/comunicados-oficiales-enfen"


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    import enso.fetch

    monkeypatch.setattr(enso.fetch.time, "sleep", lambda s: None)


def _rec(cls: str, vantage: str) -> dict:
    return {"class": cls, "at": "2026-10-21T03:00:00+00:00", "vantage": vantage}


def _enfen_reach() -> dict:
    """Lo medido el 21 de octubre: el portal del ENFEN no resuelve desde Azure ni AWS; la réplica de la DHN sí responde."""
    dns = {"actions": {"github-actions": _rec("dns", "github-actions")}, "n8n": {"n8n-aws": _rec("dns", "n8n-aws")}}
    return {ENFEN: dns, ENFEN_HTML: dns,
            DHN: {"actions": {"github-actions": _rec("ok", "github-actions")}, "n8n": {"n8n-aws": _rec("ok", "n8n-aws")}}}


def test_channels_are_decided_per_url():
    reg = registry.build(reach=_enfen_reach())
    assert registry.validate(reg) == []
    enfen = next(s for s in reg["sources"] if s["id"] == "enfen-comunicados")
    assert enfen["by_url"][ENFEN]["channels"] == ["peru-server"]
    assert enfen["by_url"][ENFEN_HTML]["channels"] == ["peru-server"]
    assert enfen["by_url"][DHN]["channels"] == ["actions", "n8n"]
    # La fuente la piden los tres: el portal desde el Perú y la réplica desde EE. UU.
    assert enfen["channels"] == ["actions", "n8n", "peru-server"] and enfen["geoblocked"] is True
    plan = registry.url_channels(reg)
    assert plan[ENFEN] == ["peru-server"] and plan[DHN] == ["actions", "n8n"]


def test_validate_requires_channels_to_be_the_union_of_its_urls():
    reg = registry.build(reach=_enfen_reach())
    enfen = next(s for s in reg["sources"] if s["id"] == "enfen-comunicados")
    enfen["channels"] = ["actions", "n8n"]
    errs = "\n".join(registry.validate(reg))
    assert "unión" in errs
    enfen["channels"] = ["actions", "n8n", "peru-server"]
    enfen["by_url"][DHN]["channels"] = ["peru-server"]  # abierta, pero asignada al Perú
    assert any("si y solo si" in e for e in registry.validate(reg))


def test_n8n_aborted_is_not_a_measurement():
    """«aborted» lo corta el nodo HTTP de n8n: desde el mismo ejecutor curl y Node reciben 200 en segundos."""
    url = "https://elcomercio.pe/arcio/rss/"
    aborted = {"class": "timeout", "detail": "aborted", "at": "2026-10-21T03:24:51+00:00"}
    reach = {url: {"actions": {"github-actions": _rec("ok", "github-actions"),
                               "n8n-actions-azure": {**aborted, "vantage": "n8n-actions-azure"}},
                   "n8n": {"n8n-aws": {**aborted, "vantage": "n8n-aws"}}}}
    g = registry.geoblock(url, reach)
    assert g["status"] == "open" and g["n8n"] is None and "n8n-aws" not in g["from"]
    assert registry.channels_for(g["status"], g["open_from"], [k for k in ("actions", "n8n") if g.get(k)]) == [
        "actions", "n8n"]
    # Solo «aborted» de n8n: un timeout del pipeline sigue contando.
    assert not registry.unmeasured({**aborted, "vantage": "github-actions"})
    assert not registry.unmeasured({"class": "timeout", "detail": "ReadTimeout", "vantage": "n8n-aws"})


def test_probe_measures_with_the_pipeline_user_agent():
    """Un WAF que decide por User-Agent (GDACS respondió 403 a la sonda y 200 a curl desde el mismo Azure)
    debe ver lo mismo que verá el pipeline."""
    import enso.fetch

    assert probe_sources.UA == enso.fetch.UA


def test_registry_file_routes_measured_peru_only_sources():
    """El registro publicado: lo que no responde desde ninguna red de EE. UU. lo pide solo el servidor del Perú."""
    reg = json.loads(registry.REGISTRY.read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in reg["sources"]}
    for sid in ("ana-onrh", "senamhi-www-senamhi-gob-pe-p-aviso-meteorologico"):
        assert by_id[sid]["channels"] == ["peru-server"], (sid, by_id[sid]["geoblock"])
    enfen = by_id["enfen-comunicados"]
    assert enfen["by_url"][ENFEN]["channels"] == ["peru-server"] and "peru-server" in enfen["channels"]
    # Lo que el pipeline lee a diario no pasa al Perú solo porque n8n no lo alcanzó: hace falta la
    # medición del propio pipeline en GitHub Actions (probe-sources.yml).
    daily = {s.id for s in obs.SOURCES} | {f"news-{f.id}" for f in __import__("enso.news").news.FEEDS}
    wrong = [s["id"] for s in reg["sources"] if s["id"] in daily and s["channels"] == ["peru-server"]
             and "github-actions" not in s["geoblock"]["from"]]
    assert wrong == [], "medir desde Actions: python -m tools.probe_sources (o probe-sources.yml)"


def _relay(root: Path, url: str, body: bytes, kind: str = "n8n", ctype: str = "application/json") -> Relay:
    import hashlib

    root.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(body).hexdigest()
    (root / "files").mkdir(exist_ok=True)
    (root / "files" / f"{sha[:16]}.json").write_bytes(body)
    (root / "index.json").write_text(json.dumps({
        "schema": "enso-relay/1", "collected_at": AT, "collector": {"kind": kind},
        "entries": [{"url": url, "status": 200, "file": f"files/{sha[:16]}.json", "sha256": sha,
                     "content_type": ctype, "fetched_at": AT}]}), encoding="utf-8")
    return Relay(root)


def test_geoblocked_url_is_read_from_the_copy_without_asking_the_server(tmp_path):
    asked = []

    def net(req):
        asked.append(str(req.url))
        return httpx.Response(200, json={"ok": True})

    relay = _relay(tmp_path / "peru", ENFEN, b'[{"id": 1}]', kind="peru")
    f = Fetcher(retries=3, polite_delay=0, allow_archive=False, relay=[relay], plan={ENFEN: ["peru-server"]})
    f.client = httpx.Client(transport=httpx.MockTransport(net))
    r = f.get([ENFEN], accept=("json",))
    assert r.channel == "relay-peru" and asked == []
    assert "peru-server" in r.attempts[-1]["note"]
    # Lo que Actions sí alcanza se pide directo aunque haya copia.
    f.plan = {ENFEN: ["actions", "n8n"]}
    assert f.get([ENFEN], accept=("json",)).channel == "direct" and asked == [ENFEN]


def test_geoblocked_url_without_copy_is_tried_once(tmp_path):
    asked = []

    def net(req):
        asked.append(str(req.url))
        raise httpx.ConnectError("Temporary failure in name resolution")

    f = Fetcher(retries=3, polite_delay=0, allow_archive=False, plan={ENFEN: ["peru-server"]})
    f.client = httpx.Client(transport=httpx.MockTransport(net))
    with pytest.raises(Exception):
        f.get([ENFEN])
    assert asked == [ENFEN]  # una vez, por si volvió a responder; no tres
    f.plan = {}
    asked.clear()
    with pytest.raises(Exception):
        f.get([ENFEN])
    assert len(asked) == 3


def test_robots_disallowed_url_is_never_requested():
    asked = []

    def net(req):
        asked.append(str(req.url))
        return httpx.Response(200, text="x")

    f = Fetcher(retries=2, polite_delay=0, allow_archive=False, plan={"https://a.pe/api": []})
    f.client = httpx.Client(transport=httpx.MockTransport(net))
    r = f.get(["https://a.pe/api", "https://b.pe/espejo"])
    assert r.channel == "mirror" and asked == ["https://b.pe/espejo"]


def test_n8n_index_is_a_measurement_from_n8n():
    index = {"schema": "enso-relay/1", "collected_at": AT,
             "collector": {"kind": "n8n", "host": "n8n", "egress": "aws"},
             "entries": [
                 {"url": "https://a.pe/feed", "status": 200, "bytes": 900, "reach": "ok", "fetched_at": AT},
                 {"url": "https://b.pe/x", "status": 200, "carried": True, "fetched_at": AT,
                  "last_attempt": {"at": AT, "verdict": "error", "status": None, "note": "timeout of 60000ms exceeded"}},
                 {"url": "https://c.pe/y", "status": 200, "bytes": 2000, "reach": "challenge", "fetched_at": AT}]}
    got = probe_sources.from_n8n_index(index)
    assert got["https://a.pe/feed"]["class"] == "ok" and got["https://a.pe/feed"]["vantage"] == "n8n-aws"
    # Una copia conservada no es una respuesta de hoy: cuenta el intento que falló.
    assert got["https://b.pe/x"]["class"] == "timeout"
    assert got["https://c.pe/y"]["class"] == "challenge"
    assert registry.vantage_group(got["https://a.pe/feed"]["vantage"]) == "n8n"


def test_missing_relay_branches_are_reported(tmp_path):
    log = obs.EventLog()
    plan = {"https://www.senamhi.gob.pe/?p=boletines": ["peru-server"], "https://snirh.ana.gob.pe/": ["peru-server"],
            "https://andina.pe/agencia/rss": ["actions", "n8n"]}
    assert obs.load_relay(tmp_path / "relay", log, plan) is None
    ev = log.events[-1]
    assert ev.code == "relay-missing" and ev.severity == "warning"
    assert "rama data-peru" in ev.message and "no se pudo bajar" in ev.message
    assert "2 URL" in ev.message and "senamhi.gob.pe" in ev.message
    assert obs.load_n8n_relay(tmp_path / "n8n", log) is None
    assert log.events[-1].code == "relay-n8n-missing" and "rama data-n8n" in log.events[-1].message


def test_n8n_heartbeat_without_sources_is_a_warning(tmp_path):
    root = tmp_path / "n8n"
    _relay(root, "https://a.pe/feed", b"{}")
    (root / "heartbeat.json").write_text(json.dumps({
        "schema": "enso-relay-heartbeat/1", "at": AT, "result": "sin-fuentes", "reachable": "0/185"}), encoding="utf-8")
    log = obs.EventLog()
    assert obs.load_n8n_relay(root, log) is not None
    assert [e.code for e in log.events] == ["relay-n8n-sources-down"]
    (root / "heartbeat.json").write_text(json.dumps({
        "schema": "enso-relay-heartbeat/1", "at": AT, "result": "ok", "reachable": "154/185"}), encoding="utf-8")
    log = obs.EventLog()
    obs.load_n8n_relay(root, log)
    assert [e.code for e in log.events] == ["relay-n8n-ok"]


def test_news_history_is_rebuilt_from_the_archive_branch(tmp_path):
    d = tmp_path / "news"
    d.mkdir()
    a = {"id": "a1", "first_seen": "2026-10-19T05:00:00+00:00", "title": "Huaico en Chosica"}
    b = {"id": "b2", "first_seen": "2026-10-20T05:00:00+00:00", "title": "Oleaje fuerte"}
    (d / "2026-10-19.jsonl").write_text(json.dumps(a) + "\n", encoding="utf-8")
    (d / "2026-10-20.jsonl").write_text(json.dumps(b) + "\n" + json.dumps(a) + "\nroto\n", encoding="utf-8")
    text = obs.read_history_backup(d)
    assert [json.loads(x)["id"] for x in text.splitlines()] == ["a1", "b2"]
    assert obs.read_history_backup(None) == "" and obs.read_history_backup(tmp_path / "no") == ""


def test_alert_sources_say_when_they_were_read_from_a_copy():
    status = [{"id": "senamhi-telegram", "ok": True, "latest": AT, "channel": "relay-n8n", "copyAt": AT},
              {"id": "usgs-sismos", "ok": True, "latest": AT}]
    rows = {r["id"]: r for r in sourcefeed.alert_sources(status)}
    assert rows["senamhi-telegram"]["channel"] == "relay-n8n" and rows["senamhi-telegram"]["copyAt"] == AT
    assert "channel" not in rows["usgs-sismos"]


def test_news_status_records_the_copy_channel():
    from enso import news as N

    f = N.FEED_BY_ID["usgs-sismos"]
    body = (Path(__file__).parent / "fixtures" / "sources" / f.fixture).read_bytes()
    st, _, _ = N._read_feed(f, lambda url: (200, body, "application/json", "", {"channel": "relay-n8n", "copyAt": AT}), NOW)
    assert st["ok"] and st["channel"] == "relay-n8n" and st["copyAt"] == AT
    st, _, _ = N._read_feed(f, lambda url: (200, body, "application/json", ""), NOW)
    assert "channel" not in st


def test_publication_runs_are_serialized():
    """El recolector del Perú (y n8n, si se activa) piden una actualización al subir su copia; la corrida
    diaria y el vigilante también. Todas van al mismo grupo, sin cancelar la que está corriendo: una copia
    tardía no se cruza con la publicación en curso, la espera."""
    import yaml

    wf = yaml.safe_load((obs.REPO / ".github" / "workflows" / "observatory.yml").read_text(encoding="utf-8"))
    assert wf["concurrency"] == {"group": "enso-production-publication", "cancel-in-progress": False}
    on = wf[True] if True in wf else wf["on"]  # PyYAML lee «on» como verdadero
    assert on["repository_dispatch"]["types"] == ["enso-refresh"] and "workflow_dispatch" in on
    steps = {s.get("id"): s for s in wf["jobs"]["build"]["steps"] if s.get("id")}
    # Las carpetas de copias se pasan siempre: si falta una rama, el pipeline lo registra como incidencia.
    for sid in ("relay", "n8n"):
        assert 'echo "dir=' in steps[sid]["run"].split("if ")[0]


ROBOTS = Path(__file__).parent / "fixtures" / "scrape-ladder"


def _rules(name: str):
    from enso.reach import RobotRules

    return RobotRules((ROBOTS / f"robots-{name}.http.txt").read_text(encoding="utf-8"), agent="Observatorio-ENSO-Peru")


def test_gobpe_feeds_respect_its_robots_txt():
    """gob.pe prohíbe «?sheet=» y «&sheet=» (la paginación de sus búsquedas), no sus RSS: los feeds van sin «sheet»."""
    from enso import news as N

    rules = _rules("gob-pe")
    gobpe = [f for f in N.FEEDS if "gob.pe/busquedas.rss" in f.url]
    assert len(gobpe) > 25
    assert all(rules.allowed(f.url) for f in gobpe), [f.id for f in gobpe if not rules.allowed(f.url)]
    assert not rules.allowed("https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=indeci&sheet=1&sort_by=recent")


def test_gobpe_rss_without_sheet_still_lists_news():
    """Lo bajado desde Actions el 21 de octubre sin «sheet»: el RSS trae sus 25 notas más recientes."""
    from enso import news as N

    for inst in ("indeci", "regionpiura"):
        body = (ROBOTS / f"gobpe-rss-{inst}.http.xml").read_bytes()
        items = N.parse_feed(body, "https://www.gob.pe/")
        assert len(items) == 25 and all(i["link"].startswith("https://www.gob.pe/") for i in items), inst


def test_google_news_and_un_news_disallow_their_rss_to_generic_agents():
    """Lo que dicen hoy sus robots.txt (21 de octubre de 2026). Pablo eligió leerlos igual, como un lector de
    feeds: el registro los asigna solo a Actions y marca «reader»."""
    from enso import news as N

    gn = _rules("google-news")
    assert not gn.allowed("https://news.google.com/rss/search?q=huaico&hl=es-419&gl=PE&ceid=PE:es-419")
    assert gn.allowed("https://news.google.com/home?hl=es-419")
    un = _rules("un-news")
    assert not un.allowed("https://news.un.org/feed/subscribe/es/news/topic/climate-change/feed/rss.xml")
    assert not _rules("sinrodeos").allowed("https://sinrodeoscajamarca.com/feed/")
    barred = {f.id for f in N.FEEDS if "news.google.com" in f.url and not gn.allowed(f.url)}
    assert len(barred) > 25
    reg = {s["id"]: s for s in json.loads(registry.REGISTRY.read_text(encoding="utf-8"))["sources"]}
    for fid in barred:
        r = reg[f"news-{fid}"]["by_url"][N.FEED_BY_ID[fid].url]
        assert r["status"] == "robots-disallowed" and r["channels"] == ["actions"] and r["reader"], fid


def test_feeds_barred_by_robots_are_not_requested_and_not_counted_as_down(tmp_path, monkeypatch):
    from enso import news as N

    one = next(f for f in N.FEEDS if f.id == "usgs-sismos")
    two = next(f for f in N.FEEDS if f.id == "andina")
    monkeypatch.setattr(N, "FEEDS", [one, two])
    body = (Path(__file__).parent / "fixtures" / "sources" / one.fixture).read_bytes()
    asked = []

    def net(req):
        asked.append(str(req.url))
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(**{**kw, "transport": httpx.MockTransport(net)}))
    fetcher = Fetcher(polite_delay=0, plan={two.url: []})
    log = obs.EventLog()
    prev = obs.PreviousPublication(None, fetcher)
    got = obs.acquire_news(fetcher, None, prev, log, NOW, None)
    st = {s["id"]: s for s in got["feeds"]["feeds"]}
    assert asked == [one.url]
    assert st["andina"]["skipped"] == "robots" and "robots.txt" in st["andina"]["error"]
    codes = [e.code for e in log.events]
    assert "feeds-robots" in codes and not any(e.code == "feed-down" and "Andina" in e.message for e in log.events)


def test_history_backup_reads_the_full_copy_first(tmp_path):
    """items.jsonl es el histórico entero de la última corrida archivada; las notas de cada día completan."""
    d = tmp_path / "news"
    d.mkdir()
    a, b, c = ({"id": i, "first_seen": f"2026-10-{n}T05:00:00+00:00"} for i, n in (("a1", 18), ("b2", 19), ("c3", 20)))
    (d / "2026-10-20.jsonl").write_text(json.dumps(c) + "\n", encoding="utf-8")
    (d / "items.jsonl").write_text(json.dumps(a) + "\n" + json.dumps(b) + "\n", encoding="utf-8")
    assert [json.loads(x)["id"] for x in obs.read_history_backup(d).splitlines()] == ["a1", "b2", "c3"]
    # La copia actual va comprimida; una cortada no se usa (reemplazaría al histórico entero con una parte).
    (d / "items.jsonl").unlink()
    (d / "items.jsonl.gz").write_bytes(gzip.compress((json.dumps(b) + "\n" + json.dumps(a) + "\n").encode()))
    assert [json.loads(x)["id"] for x in obs.read_history_backup(d).splitlines()] == ["b2", "a1", "c3"]
    (d / "items.jsonl.gz").write_bytes(gzip.compress(("".join(json.dumps({**a, "id": f"n{i}"}) + "\n"
                                                              for i in range(500))).encode())[:-40])
    assert obs.read_history_backup(d) == ""
    (d / "items.jsonl.gz").write_bytes(b"no es gzip")
    assert obs.read_history_backup(d) == ""


def _one_feed(monkeypatch):
    from enso import news as N

    one = next(f for f in N.FEEDS if f.id == "usgs-sismos")
    monkeypatch.setattr(N, "FEEDS", [one])
    body = (Path(__file__).parent / "fixtures" / "sources" / one.fixture).read_bytes()
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(**{**kw, "transport": httpx.MockTransport(
        lambda req: httpx.Response(200, content=body, headers={"content-type": "application/json"}))}))
    return Fetcher(polite_delay=0)


def test_a_restarted_history_is_flagged_and_completed_from_the_copy(tmp_path, monkeypatch):
    """Si no se leyó ni el histórico publicado ni la copia, se publica con las notas de hoy, se marca
    «restarted» y no se pisa la copia de data-archive; la corrida siguiente lo completa con esa copia."""
    fetcher = _one_feed(monkeypatch)
    old = [{"id": f"old{i}", "first_seen": "2026-10-01T05:00:00+00:00", "title": f"Nota {i}",
            "link": f"https://andina.pe/nota-{i}"} for i in range(3)]
    site = tmp_path / "site"
    (site / "news").mkdir(parents=True)
    (site / "news" / "feeds.json").write_text(json.dumps({"history": {"items": 3}}), encoding="utf-8")
    raw, log = tmp_path / "raw", obs.EventLog()
    got = obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), log, NOW, raw)
    assert got["feeds"]["history"]["restarted"] is True
    assert any(e.code == "news-history-missing" and e.severity == "error" for e in log.events)
    assert not (raw / "news" / "items.jsonl.gz").exists()  # la copia buena de data-archive queda como estaba
    today = got["jsonl"]

    (site / "news" / "items.jsonl").write_text(today, encoding="utf-8")
    (site / "news" / "feeds.json").write_text(json.dumps(got["feeds"]), encoding="utf-8")
    backup = tmp_path / "history"
    backup.mkdir()
    (backup / "items.jsonl.gz").write_bytes(gzip.compress("".join(json.dumps(i) + "\n" for i in old).encode()))
    raw2, log2 = tmp_path / "raw2", obs.EventLog()
    got2 = obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), log2, NOW, raw2, backup)
    assert got2["jsonl"].startswith(today)  # solo se agrega al final
    assert {"old0", "old1", "old2"} <= {i["id"] for i in got2["items"]}
    assert "restarted" not in got2["feeds"]["history"]
    assert any(e.code == "news-history-restored" for e in log2.events)
    assert gzip.decompress((raw2 / "news" / "items.jsonl.gz").read_bytes()).decode() == got2["jsonl"]


def _history_site(tmp_path, items, feeds=None):
    site = tmp_path / "site"
    (site / "news").mkdir(parents=True, exist_ok=True)
    (site / "news" / "items.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items), encoding="utf-8")
    (site / "news" / "feeds.json").write_text(json.dumps(feeds or {"history": {"items": len(items)}}), encoding="utf-8")
    return site


def _notes(prefix, n):
    return [{"id": f"{prefix}{i}", "first_seen": "2026-10-01T05:00:00+00:00", "title": f"Nota {i}",
             "link": f"https://andina.pe/{prefix}-{i}"} for i in range(n)]


def test_a_site_that_does_not_answer_is_not_a_first_publication(tmp_path, monkeypatch):
    """Con el sitio caído (503) y sin poder bajar la copia, el histórico no se da por vacío: se marca
    «restarted», es un error y la copia de data-archive no se reemplaza."""
    real = httpx.Client
    fetcher = _one_feed(monkeypatch)
    monkeypatch.setattr(obs.time, "sleep", lambda s: None)
    down = Fetcher(polite_delay=0)
    down.client = real(transport=httpx.MockTransport(lambda req: httpx.Response(503)))
    raw, log = tmp_path / "raw", obs.EventLog()
    unavailable = tmp_path / "history"
    unavailable.mkdir()  # el flujo deja la carpeta vacía si la descarga falló
    got = obs.acquire_news(fetcher, None, obs.PreviousPublication("https://sitio.example/data", down), log, NOW, raw,
                           unavailable)
    assert got["feeds"]["history"]["restarted"] is True
    err = next(e for e in log.events if e.code == "news-history-missing")
    assert err.severity == "error" and "no respondió" in err.message and "no se pudo bajar" in err.message
    assert not (raw / "news" / "items.jsonl.gz").exists()
    # Sin copia en data-archive (404) y sin histórico publicado (404): primera publicación, sin incidencias.
    gone = Fetcher(polite_delay=0)
    gone.client = real(transport=httpx.MockTransport(lambda req: httpx.Response(404)))
    raw2, log2 = tmp_path / "raw2", obs.EventLog()
    got2 = obs.acquire_news(fetcher, None, obs.PreviousPublication("https://sitio.example/data", gone), log2, NOW,
                            raw2, tmp_path / "vacia", history_absent=True)
    assert "restarted" not in got2["feeds"]["history"]
    assert not any(e.code.startswith("news-history") for e in log2.events)
    assert gzip.decompress((raw2 / "news" / "items.jsonl.gz").read_bytes()).decode() == got2["jsonl"]


def test_history_takes_the_notes_of_a_run_that_did_not_publish(tmp_path, monkeypatch):
    """La copia de data-archive puede tener notas que el sitio no (la corrida que las leyó no llegó a
    desplegar): se agregan al final. Si una corrida marcó «restarted» y data-archive no tiene copia (404),
    se acepta lo publicado: no hay con qué completarlo."""
    fetcher = _one_feed(monkeypatch)
    site = _history_site(tmp_path, _notes("pub", 2))
    backup = tmp_path / "history"
    backup.mkdir()
    (backup / "items.jsonl.gz").write_bytes(gzip.compress(
        "".join(json.dumps(i) + "\n" for i in _notes("pub", 2) + _notes("lost", 2)).encode()))
    log = obs.EventLog()
    got = obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), log, NOW, tmp_path / "raw",
                           backup)
    ids = [i["id"] for i in got["items"]]
    assert ids[:4] == ["pub0", "pub1", "lost0", "lost1"]
    assert any(e.code == "news-history-restored" and "2 notas" in e.message for e in log.events)

    site = _history_site(tmp_path, _notes("pub", 2), {"history": {"items": 2, "restarted": True}})
    log = obs.EventLog()
    got = obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), log, NOW, tmp_path / "raw3",
                           tmp_path / "vacia", history_absent=True)
    assert "restarted" not in got["feeds"]["history"]
    assert any(e.code == "news-history-restored" and e.severity == "warning" for e in log.events)
    # Copia que no se pudo bajar: el «restarted» sigue hasta que se lea.
    log = obs.EventLog()
    empty = tmp_path / "vacia2"
    empty.mkdir()
    got = obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), log, NOW, tmp_path / "raw4",
                           empty)
    assert got["feeds"]["history"]["restarted"] is True and not (tmp_path / "raw4" / "news" / "items.jsonl.gz").exists()


def test_large_history_warns_before_the_hosting_limit(tmp_path, monkeypatch):
    fetcher = _one_feed(monkeypatch)
    monkeypatch.setattr(obs, "NEWS_HISTORY_WARN_BYTES", 500)
    site = _history_site(tmp_path, _notes("pub", 10))
    log = obs.EventLog()
    obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), log, NOW, None)
    assert any(e.code == "news-history-large" and "25 MiB" in e.message for e in log.events)


def test_previous_history_is_retried_on_server_errors(monkeypatch):
    monkeypatch.setattr(obs.time, "sleep", lambda s: None)
    calls = []

    def net(req):
        calls.append(req.url.path)
        if req.url.path.endswith("missing.jsonl"):
            return httpx.Response(404)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, text='{"id":"a"}\n')

    fetcher = Fetcher(polite_delay=0)
    fetcher.client = httpx.Client(transport=httpx.MockTransport(net))
    prev = obs.PreviousPublication("https://sitio.example/data", fetcher)
    assert prev.get_text("news/items.jsonl", tries=3) == '{"id":"a"}\n' and len(calls) == 3
    calls.clear()
    assert prev.get_text("news/missing.jsonl", tries=3) is None and len(calls) == 1  # no existe: no se insiste


def _archive_news_script() -> str:
    import yaml

    wf = yaml.safe_load((obs.REPO / ".github" / "workflows" / "observatory.yml").read_text(encoding="utf-8"))
    run = next(s["run"] for s in wf["jobs"]["archive"]["steps"] if "data-archive" in s.get("name", ""))
    start, end = run.index("mkdir -p ../archive/sources/news"), run.index("cp -rn raw/. ../archive/sources/")
    return run[start:end] + "cp -rn raw/. ../archive/sources/\n"


def test_archive_adds_each_runs_notes_and_replaces_the_full_copy(tmp_path):
    """Dos corridas el mismo día suman sus notas (antes «cp -rn» dejaba solo las de la primera) y la copia
    completa del histórico se reemplaza; las respuestas crudas siguen sin pisarse."""
    import subprocess

    work, arch = tmp_path / "work", tmp_path / "archive" / "sources"
    (work / "raw" / "news").mkdir(parents=True)
    (arch / "news").mkdir(parents=True)
    (arch / "news" / "2026-10-21.jsonl").write_text('{"id":"a"}\n', encoding="utf-8")
    (arch / "news" / "items.jsonl.gz").write_bytes(gzip.compress(b'{"id":"a"}\n'))
    (arch / "usgs").mkdir()
    (arch / "usgs" / "x.json").write_text("viejo", encoding="utf-8")
    (work / "raw" / "news" / "2026-10-21.jsonl").write_text('{"id":"a"}\n{"id":"b"}\n', encoding="utf-8")
    (work / "raw" / "news" / "items.jsonl.gz").write_bytes(gzip.compress(b'{"id":"a"}\n{"id":"b"}\n'))
    (work / "raw" / "usgs").mkdir()
    (work / "raw" / "usgs" / "x.json").write_text("nuevo", encoding="utf-8")
    subprocess.run(["bash", "-e", "-c", _archive_news_script()], cwd=work, check=True)
    assert (arch / "news" / "2026-10-21.jsonl").read_text(encoding="utf-8") == '{"id":"a"}\n{"id":"b"}\n'
    assert gzip.decompress((arch / "news" / "items.jsonl.gz").read_bytes()) == b'{"id":"a"}\n{"id":"b"}\n'
    assert (arch / "usgs" / "x.json").read_text(encoding="utf-8") == "viejo"
    # Una corrida sin histórico entero no deja copia: queda la anterior.
    (work / "raw" / "news").mkdir()
    (work / "raw" / "news" / "2026-10-22.jsonl").write_text('{"id":"c"}\n', encoding="utf-8")
    subprocess.run(["bash", "-e", "-c", _archive_news_script()], cwd=work, check=True)
    assert gzip.decompress((arch / "news" / "items.jsonl.gz").read_bytes()) == b'{"id":"a"}\n{"id":"b"}\n'


def test_history_backup_is_fetched_every_run():
    """La decisión de usar la copia la toma el pipeline al leer el histórico, no una consulta previa."""
    import yaml

    wf = yaml.safe_load((obs.REPO / ".github" / "workflows" / "observatory.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["build"]["steps"]
    step = next(s for s in steps if s.get("id") == "history")
    assert "curl" not in step["run"] and "sources/news/items.jsonl.gz?ref=data-archive" in step["run"]
    # 404 (no hay copia) no es lo mismo que una descarga fallida (carpeta vacía).
    assert "(HTTP 404)" in step["run"] and "absent=true" in step["run"] and "gzip -t" in step["run"]
    pipeline = next(s for s in steps if s.get("id") == "pipeline")
    assert "--history-absent" in pipeline["run"] and "--reader-state" in pipeline["run"]
    # El estado de los feeds «reader» se guarda aunque la corrida falle después de leerlos.
    names = [s.get("uses", "") for s in steps]
    restore, save = names.index("actions/cache/restore@v4"), names.index("actions/cache/save@v4")
    assert restore < steps.index(pipeline) < save and steps[save]["if"] == "always()"
    assert wf["jobs"]["archive"]["if"] == "success()"  # también al fusionar en main


def test_feeds_read_like_a_feed_reader_are_asked_at_most_once_a_day(tmp_path, monkeypatch):
    """Un feed «reader» con una lectura buena hace menos de 20 h no se vuelve a pedir y queda su estado; uno
    leído hace más, uno que falló la última vez o uno que antes se omitía por robots.txt sí se pide."""
    from enso import news as N

    feeds = [f for f in N.FEEDS if "news.google.com" in f.url][:4]
    monkeypatch.setattr(N, "FEEDS", feeds)
    body = (Path(__file__).parent / "fixtures" / "sources" / feeds[1].fixture).read_bytes()
    asked = []

    def net(req):
        asked.append(str(req.url))
        return httpx.Response(200, content=body, headers={"content-type": "application/rss+xml"})

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(**{**kw, "transport": httpx.MockTransport(net)}))
    ago = lambda h: (NOW - timedelta(hours=h)).isoformat(timespec="seconds")  # noqa: E731
    prev = [{**N._status(feeds[0], NOW), "checkedAt": ago(3), "ok": True, "active": True, "items": 7, "httpStatus": 200},
            {**N._status(feeds[1], NOW), "checkedAt": ago(25), "ok": True, "httpStatus": 200},
            {**N._status(feeds[2], NOW), "checkedAt": ago(3), "ok": False, "httpStatus": 503},
            {**N._status(feeds[3], NOW, "omitido: su robots.txt no permite pedir este feed"), "checkedAt": ago(1),
             "skipped": "robots"}]
    site = tmp_path / "site"
    (site / "news").mkdir(parents=True)
    (site / "news" / "feeds.json").write_text(json.dumps({"feeds": prev, "history": {"items": 0}}), encoding="utf-8")
    plan = {f.url: ["actions"] for f in feeds}
    fetcher = Fetcher(polite_delay=0, plan=plan)
    log = obs.EventLog()
    got = obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), log, NOW, None,
                           reader={f.url for f in feeds})
    assert sorted(asked) == sorted(f.url for f in feeds[1:])
    st = {s["id"]: s for s in got["feeds"]["feeds"]}
    assert st[feeds[0].id]["carried"] is True and st[feeds[0].id]["items"] == 7
    assert st[feeds[0].id]["checkedAt"] == ago(3)  # conserva la hora de la lectura: el plazo no se renueva
    assert not any(s.get("carried") for fid, s in st.items() if fid != feeds[0].id)
    assert any(e.code == "feeds-reader" and "3 pedidos" in e.message and "1 con la lectura anterior" in e.message
               for e in log.events)
    # Sin «reader» (otra fuente con canal Actions) se pide siempre.
    asked.clear()
    obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), obs.EventLog(), NOW, None)
    assert len(asked) == 4


def test_reader_feeds_are_not_asked_again_after_a_run_that_did_not_publish(tmp_path, monkeypatch):
    """La corrida que los leyó y no llegó a desplegar deja anotada la lectura (--reader-state): la siguiente,
    con la misma publicación anterior, no los vuelve a pedir antes de 20 h."""
    from enso import news as N

    feeds = [f for f in N.FEEDS if "news.google.com" in f.url][:2]
    monkeypatch.setattr(N, "FEEDS", feeds)
    body = (Path(__file__).parent / "fixtures" / "sources" / feeds[0].fixture).read_bytes()
    asked = []

    def net(req):
        asked.append(str(req.url))
        return httpx.Response(200, content=body, headers={"content-type": "application/rss+xml"})

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(**{**kw, "transport": httpx.MockTransport(net)}))
    site = _history_site(tmp_path, [])
    fetcher = Fetcher(polite_delay=0, plan={f.url: ["actions"] for f in feeds})
    state = tmp_path / "cache" / "reader-state.json"
    reader = {f.url for f in feeds}
    obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), obs.EventLog(), NOW, None,
                     reader=reader, reader_state=state)
    assert len(asked) == 2 and json.loads(state.read_text())["schema"] == "enso-reader-state/1"
    asked.clear()
    got = obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), obs.EventLog(),
                           NOW + timedelta(hours=5), None, reader=reader, reader_state=state)
    assert asked == [] and all(s["carried"] for s in got["feeds"]["feeds"])
    obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), obs.EventLog(),
                     NOW + timedelta(hours=21), None, reader=reader, reader_state=state)
    assert len(asked) == 2
    # Un estado ilegible no detiene nada: se vuelve a la publicación anterior.
    state.write_text("{roto", encoding="utf-8")
    assert obs.read_reader_state(state) == {}
