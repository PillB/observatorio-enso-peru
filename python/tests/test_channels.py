"""Las mismas fuentes por los tres canales (Actions, n8n, Perú): canales por URL, copias y avisos."""

from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from enso import observatory as obs
from enso import registry, sourcefeed
from enso.fetch import FetchError, Fetcher, Relay
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
    f = Fetcher(retries=3, polite_delay=0, allow_archive=False)  # otra corrida: sin los fallos de esta
    f.client = httpx.Client(transport=httpx.MockTransport(net))
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
    # Se deja para el job «archive», que lo une a la copia de data-archive sin quitarle notas.
    assert gzip.decompress((raw / "news" / "items.jsonl.gz").read_bytes()).decode() == got["jsonl"]
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
    assert got["feeds"]["history"]["restarted"] is True
    # Con un error, para que la incidencia siga abierta mientras el histórico esté incompleto.
    assert any(e.code == "news-history-missing" and e.severity == "error" and "sigue incompleto" in e.message
               for e in log.events)


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
    tool = str(obs.REPO / "python" / "tools" / "merge_history.py")
    return run[start:end].replace("python/tools/merge_history.py", tool) + "cp -rn raw/. ../archive/sources/\n"


def test_archive_adds_each_runs_notes_and_never_shrinks_the_full_copy(tmp_path):
    """Dos corridas el mismo día suman sus notas (antes «cp -rn» dejaba solo las de la primera) y el
    histórico de cada corrida se une a la copia sin quitarle notas; las respuestas crudas no se pisan."""
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
    # Una corrida sin histórico no toca la copia; una con un histórico incompleto («restarted», o que no pudo
    # bajar la copia) solo le agrega lo que le falte.
    (work / "raw" / "news").mkdir()
    (work / "raw" / "news" / "2026-10-22.jsonl").write_text('{"id":"c"}\n', encoding="utf-8")
    subprocess.run(["bash", "-e", "-c", _archive_news_script()], cwd=work, check=True)
    assert gzip.decompress((arch / "news" / "items.jsonl.gz").read_bytes()) == b'{"id":"a"}\n{"id":"b"}\n'
    (work / "raw" / "news").mkdir()
    (work / "raw" / "news" / "items.jsonl.gz").write_bytes(gzip.compress(b'{"id":"c"}\n{"id":"b"}\n'))
    out = subprocess.run(["bash", "-e", "-c", _archive_news_script()], cwd=work, check=True, capture_output=True,
                         text=True).stdout
    assert gzip.decompress((arch / "news" / "items.jsonl.gz").read_bytes()) == b'{"id":"a"}\n{"id":"b"}\n{"id":"c"}\n'
    assert "3 notas (1 nuevas)" in out


def _archive_step(tmp_path, seed_files: dict | None = None) -> Path:
    """Un «origin» con main (y data-archive con ``seed_files``, si se dan) y su clon, como lo deja actions/checkout."""
    import subprocess

    def git(*a, cwd):
        subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)

    origin, seed, work = tmp_path / "origin.git", tmp_path / "seed", tmp_path / "work"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    git("config", "uploadpack.allowFilter", "true", cwd=origin)
    git("init", "-q", "-b", "main", str(seed), cwd=tmp_path)
    for k, v in (("user.name", "t"), ("user.email", "t@example.org")):
        git("config", k, v, cwd=seed)
    (seed / "README.md").write_text("main\n", encoding="utf-8")
    git("add", "-A", cwd=seed)
    git("commit", "-q", "-m", "main", cwd=seed)
    git("push", "-q", str(origin), "main", cwd=seed)
    if seed_files is not None:
        git("switch", "-q", "--orphan", "data-archive", cwd=seed)
        for name, body in seed_files.items():
            (seed / name).parent.mkdir(parents=True, exist_ok=True)
            (seed / name).write_bytes(body)
        git("add", "-A", cwd=seed)
        git("commit", "-q", "-m", "archive", cwd=seed)
        git("push", "-q", str(origin), "data-archive", cwd=seed)
    git("clone", "-q", "--depth", "1", f"file://{origin}", str(work), cwd=tmp_path)
    return work


def _raw_name(day: str, body: bytes, ext: str) -> str:
    """Como archive_raw: fecha y los 12 primeros caracteres del sha256 del cuerpo."""
    import hashlib

    return f"{day}-{hashlib.sha256(body).hexdigest()[:12]}.{ext}"


def _run_archive_step(work: Path, before_add: str = "", outcome: str = "success") -> str:
    import subprocess

    import yaml

    wf = yaml.safe_load((obs.REPO / ".github" / "workflows" / "observatory.yml").read_text(encoding="utf-8"))
    run = next(s["run"] for s in wf["jobs"]["archive"]["steps"] if "data-archive" in s.get("name", ""))
    run = run.replace("python/tools/merge_history.py", str(obs.REPO / "python" / "tools" / "merge_history.py"))
    run = run.replace("git add --sparse sources\n", f"git add --sparse sources\n{before_add}\n")
    # Como el shell de Actions: bash -e -o pipefail.
    return subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", run], cwd=work, check=True,
                          capture_output=True, text=True, env={**os.environ, "RAW_OUTCOME": outcome}).stdout


def _archive_tree(work: Path) -> dict:
    import subprocess

    origin = work.parent / "origin.git"
    names = subprocess.run(["git", "ls-tree", "-r", "--name-only", "data-archive"], cwd=origin, check=True,
                           capture_output=True, text=True).stdout.split()
    return {n: subprocess.run(["git", "show", f"data-archive:{n}"], cwd=origin, check=True, capture_output=True).stdout
            for n in names}


def test_archive_job_downloads_only_the_news_history_and_never_deletes(tmp_path):
    """Revisión: el job bajaba data-archive entera, que crece cada día, y volvía a agregar con la fecha de hoy
    las respuestas que no cambian. Ahora baja la lista de archivos y solo sources/news, no repite una respuesta
    que ya tiene (mismo sha256, misma fuente) y no borra nada de lo que no bajó."""
    same, pdf = _raw_name("2026-10-20", b"igual", "txt"), _raw_name("2026-10-19", b"%PDF-1", "pdf")
    old = {f"sources/usgs/{same}": b"igual", f"sources/igp/{pdf}": b"%PDF-1",
           "sources/news/2026-10-20.jsonl": b'{"id":"a"}\n', "sources/news/items.jsonl.gz": gzip.compress(b'{"id":"a"}\n')}
    work = _archive_step(tmp_path, old)
    raw = work / "raw"
    (raw / "usgs").mkdir(parents=True)
    (raw / "usgs" / _raw_name("2026-10-21", b"igual", "txt")).write_bytes(b"igual")  # ya está, con otra fecha
    new = _raw_name("2026-10-21", b"nuevo", "txt")
    (raw / "usgs" / new).write_bytes(b"nuevo")
    (raw / "usgs" / _raw_name("2026-10-21", b"entero", "txt")).write_bytes(b"ent")  # llegó cortado
    (raw / "news").mkdir()
    (raw / "news" / "2026-10-21.jsonl").write_text('{"id":"b"}\n', encoding="utf-8")
    (raw / "news" / "items.jsonl.gz").write_bytes(gzip.compress(b'{"id":"b"}\n'))
    out = _run_archive_step(work)
    tree = _archive_tree(work)
    assert sorted(tree) == sorted([*old, "sources/news/2026-10-21.jsonl", f"sources/usgs/{new}"])
    assert gzip.decompress(tree["sources/news/items.jsonl.gz"]) == b'{"id":"a"}\n{"id":"b"}\n' and "2 notas" in out
    assert tree[f"sources/igp/{pdf}"] == b"%PDF-1" and "llegó incompleto" in out
    assert not (tmp_path / "archive" / "sources" / "igp").exists()  # no se bajó al disco
    assert (tmp_path / "archive" / "sources" / "news" / "2026-10-20.jsonl").exists()
    # Un commit que borrara algo no se sube.
    import subprocess

    subprocess.run(["git", "worktree", "remove", "--force", "../archive"], cwd=work, check=True, capture_output=True)
    (raw / "usgs" / _raw_name("2026-10-22", b"otro", "txt")).write_bytes(b"otro")
    with pytest.raises(subprocess.CalledProcessError) as err:
        _run_archive_step(work, f"git rm -q --sparse --cached sources/igp/{pdf}")
    assert "borraría archivos" in err.value.stdout and _archive_tree(work) == tree
    # Si la descarga del artefacto falló (a medias o del todo), no se archiva nada.
    subprocess.run(["git", "worktree", "remove", "--force", "../archive"], cwd=work, check=True, capture_output=True)
    assert "no se actualiza" in _run_archive_step(work, outcome="failure") and _archive_tree(work) == tree


def test_archive_job_starts_the_branch_when_it_does_not_exist(tmp_path):
    work = _archive_step(tmp_path)
    (work / "raw" / "usgs").mkdir(parents=True)
    name = _raw_name("2026-10-21", b"x", "txt")
    (work / "raw" / "usgs" / name).write_bytes(b"x")
    (work / "raw" / "news").mkdir()
    (work / "raw" / "news" / "items.jsonl.gz").write_bytes(gzip.compress(b'{"id":"a"}\n'))
    _run_archive_step(work)
    assert sorted(_archive_tree(work)) == ["sources/news/items.jsonl.gz", f"sources/usgs/{name}"]


def test_merge_history_keeps_every_note_and_its_order(tmp_path):
    from tools import merge_history as M

    old, new = tmp_path / "old.jsonl.gz", tmp_path / "new.jsonl.gz"
    new.write_bytes(gzip.compress(b'{"id":"b"}\n{"id":"c"}\nroto\n[1]\n{"id":7}\n'))
    assert "2 notas (2 nuevas)" in M.merge(new, old)  # sin copia todavía
    first = old.read_bytes()
    assert M.merge(new, old) and old.read_bytes() == first  # mismos datos, mismos bytes: sin commit vacío
    old.write_bytes(gzip.compress(b'{"id":"a"}\n{"id":"b"}\n'))
    M.merge(new, old)
    assert gzip.decompress(old.read_bytes()) == b'{"id":"a"}\n{"id":"b"}\n{"id":"c"}\n'
    # Copia rota: se reemplaza, con aviso. Histórico de la corrida roto: la copia queda como estaba.
    old.write_bytes(b"no es gzip")
    assert M.merge(new, old).startswith("::warning::") and gzip.decompress(old.read_bytes()) == b'{"id":"b"}\n{"id":"c"}\n'
    keep = old.read_bytes()
    new.write_bytes(gzip.compress(b'{"id":"x"}\n')[:-6])
    assert M.merge(new, old).startswith("::warning::") and old.read_bytes() == keep
    # Por encima del límite queda la copia anterior.
    new.write_bytes(gzip.compress(b'{"id":"y"}\n'))
    assert "no cabe" in M.merge(new, old, limit=10) and old.read_bytes() == keep
    assert M.main(["solo-uno"]) == 2


def test_history_backup_is_fetched_every_run():
    """La decisión de usar la copia la toma el pipeline al leer el histórico, no una consulta previa."""
    import yaml

    wf = yaml.safe_load((obs.REPO / ".github" / "workflows" / "observatory.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["build"]["steps"]
    step = next(s for s in steps if s.get("id") == "history")
    assert "curl" not in step["run"] and "sources/news/items.jsonl.gz?ref=data-archive" in step["run"]
    # Con «raw+json», gh trata la respuesta como JSON y daña el gzip.
    assert 'Accept: application/vnd.github.raw"' in step["run"]
    assert not any("raw+json" in line for line in step["run"].splitlines() if not line.strip().startswith("#"))
    # 404 (no hay copia) no es lo mismo que una descarga fallida (carpeta vacía).
    assert "(HTTP 404)" in step["run"] and "absent=true" in step["run"] and "gzip -t" in step["run"]
    pipeline = next(s for s in steps if s.get("id") == "pipeline")
    assert "--history-absent" in pipeline["run"] and "--reader-state" in pipeline["run"]
    # El estado de los feeds «reader» se guarda aunque la corrida falle después de leerlos.
    names = [s.get("uses", "") for s in steps]
    restore, save = names.index("actions/cache/restore@v4"), names.index("actions/cache/save@v4")
    assert restore < steps.index(pipeline) < save and steps[save]["if"].startswith("always()")
    # Solo en main: la caché de otra rama no la ve main, que volvería a pedir los feeds antes de 20 h.
    main = "github.ref == 'refs/heads/main'"
    assert main in steps[restore]["if"] and main in steps[save]["if"] and main in pipeline["env"]["READER_STATE"]
    assert '${READER_STATE:+--reader-state "$READER_STATE"}' in pipeline["run"]
    # Si falla el archivo, se abre la incidencia de corrida fallida (el sitio pudo quedar por delante de la copia).
    inc = wf["jobs"]["incidents"]
    assert "archive" in inc["needs"]
    opener = next(st for st in inc["steps"] if st.get("name") == "Open an issue when the run itself failed")
    # «cancelled» también: así termina un job que pasa su límite de tiempo.
    assert "needs.archive.result" in opener["if"] and '["failure","cancelled"]' in opener["if"]
    # Solo en main (también al fusionar): la copia del histórico vuelve al sitio publicado.
    assert wf["jobs"]["archive"]["if"] == "success() && github.ref == 'refs/heads/main'"
    # Aunque falle la sincronización de incidencias, la falla de la corrida se avisa (y se cierra).
    for name in ("Open an issue when the run itself failed", "Close the run-failure issue after a good run"):
        assert next(st for st in inc["steps"] if st.get("name") == name)["if"].startswith("always() && ")
    # El pipeline tiene su propio límite, por debajo del del job: si se pasa, el estado de los feeds «reader» se
    # guarda igual. Las subidas auxiliares no detienen el despliegue.
    assert pipeline["timeout-minutes"] <= wf["jobs"]["build"]["timeout-minutes"] - 10
    # El pipeline deja tiempo de sobra a sus propias fuentes: oficiales, noticias, y la publicación.
    assert (obs.OFFICIAL_BUDGET_S + obs.NEWS_DEADLINE_S + 3 * obs.NEWS_REQUEST_MAX_S) / 60 < pipeline["timeout-minutes"] - 4
    archive = wf["jobs"]["archive"]["steps"]
    assert next(st for st in archive if st.get("uses", "").startswith("actions/download-artifact"))["id"] == "raw"
    for name in ("run-report", "raw-sources"):
        assert next(st for st in steps if (st.get("with") or {}).get("name") == name)["continue-on-error"] is True


def test_the_publishing_run_checks_only_what_it_installs_and_reports_every_failure():
    """Revisión 7: el build instalaba solo Chromium, pero la prueba de los dispositivos falla en CI si WebKit o
    Firefox no arrancan: ninguna corrida habría desplegado. Y la corrida al fusionar en main (que publica y
    archiva) no avisaba si fallaba. La salida de n8n se lee de un archivo, no de la salida estándar del
    contenedor, que la cortaba."""
    import yaml

    wf = yaml.safe_load((obs.REPO / ".github" / "workflows" / "observatory.yml").read_text(encoding="utf-8"))
    run = next(s for s in wf["jobs"]["build"]["steps"] if s.get("name") == "Browser checks against the built site")["run"]
    install = next(line for line in run.splitlines() if "playwright install" in line)
    for engine in ("webkit", "firefox"):
        assert engine in install or f"not {engine}" in run, engine
    assert "event_name" not in wf["jobs"]["incidents"]["if"]
    for path in (obs.REPO / "n8n" / "test" / "e2e.sh", obs.REPO / ".github" / "workflows" / "n8n.yml"):
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if "--rawOutput" in line]
        assert lines and all("--rawOutput > /w/" in line for line in lines), path.name


def test_feeds_read_like_a_feed_reader_are_asked_at_most_once_a_day(tmp_path, monkeypatch):
    """Un feed «reader» pedido hace menos de 20 h no se vuelve a pedir, haya respondido o no (como un lector
    de feeds), y queda el estado de ese pedido; uno pedido hace más o uno que antes se omitía sí se pide."""
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
    assert sorted(asked) == sorted([feeds[1].url, feeds[3].url])
    st = {s["id"]: s for s in got["feeds"]["feeds"]}
    assert st[feeds[0].id]["carried"] is True and st[feeds[0].id]["items"] == 7
    assert st[feeds[0].id]["checkedAt"] == ago(3)  # conserva la hora de la lectura: el plazo no se renueva
    assert st[feeds[2].id]["carried"] is True and st[feeds[2].id]["ok"] is False  # falló hace 3 h: no se insiste
    assert not any(s.get("carried") for fid, s in st.items() if fid not in (feeds[0].id, feeds[2].id))
    assert any(e.code == "feeds-reader" and "2 pedidos" in e.message and "2 con la lectura anterior" in e.message
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
    log = obs.EventLog()
    got = obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), log,
                           NOW + timedelta(hours=5), None, reader=reader, reader_state=state)
    assert asked == [] and all(s["carried"] for s in got["feeds"]["feeds"])
    # Las notas de aquella lectura, que no llegó a publicarse, salen del estado: no se pierden.
    kept = json.loads(state.read_text())["feeds"]
    assert got["items"] and len(got["items"]) == len({i["id"] for v in kept.values() for i in v["items"]})
    assert any(e.code == "news-reader-restored" for e in log.events)
    obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), obs.EventLog(),
                     NOW + timedelta(hours=21), None, reader=reader, reader_state=state)
    assert len(asked) == 2
    # Un estado ilegible no detiene nada: se vuelve a la publicación anterior.
    state.write_text("{roto", encoding="utf-8")
    assert obs.read_reader_state(state) == {}
    # Una lectura que se arrastra de la publicación anterior también queda en el estado, con su hora: si
    # después esa publicación no se puede leer, el plazo se sigue respetando.
    st = {**N._status(feeds[0], NOW), "checkedAt": (NOW - timedelta(hours=2)).isoformat(timespec="seconds"),
          "ok": True, "active": True, "items": 3, "httpStatus": 200}
    site = _history_site(tmp_path, [], {"feeds": [st], "history": {"items": 0}})
    asked.clear()
    obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), obs.EventLog(), NOW, None,
                     reader=reader, reader_state=state)
    saved = json.loads(state.read_text())["feeds"][feeds[0].url]
    assert asked == [feeds[1].url] and saved["status"]["checkedAt"] == st["checkedAt"] and saved["items"] == []
    asked.clear()
    obs.acquire_news(fetcher, None, obs.PreviousPublication(str(tmp_path / "no-hay"), fetcher), obs.EventLog(),
                     NOW + timedelta(hours=3), None, reader=reader, reader_state=state)
    assert asked == []


def test_a_reader_feed_that_failed_is_not_asked_again_within_a_day(tmp_path, monkeypatch):
    """Un 429 o un 5xx también cuentan como pedido: un lector de feeds vuelve a la hora que le toca, no en la
    corrida siguiente. Se pide una sola vez (sin reintento) y el estado conserva las notas de la última lectura
    buena. El plazo tiene un margen de 30 min: la hora anotada es la de inicio de la corrida."""
    from enso import news as N

    feed = next(f for f in N.FEEDS if "news.google.com" in f.url)
    monkeypatch.setattr(N, "FEEDS", [feed])
    body = (Path(__file__).parent / "fixtures" / "sources" / feed.fixture).read_bytes()
    asked, mode = [], {"code": 200}

    def net(req):
        asked.append(str(req.url))
        return httpx.Response(mode["code"], content=body if mode["code"] == 200 else b"")

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(**{**kw, "transport": httpx.MockTransport(net)}))
    site = _history_site(tmp_path, [])
    fetcher = Fetcher(polite_delay=0, plan={feed.url: ["actions"]})
    state, reader = tmp_path / "state.json", {feed.url}

    def run(hours):
        log = obs.EventLog()
        got = obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), log,
                               NOW + timedelta(hours=hours), None, reader=reader, reader_state=state)
        return got, log

    run(0)
    good = json.loads(state.read_text())["feeds"][feed.url]["items"]
    assert len(asked) == 1 and good
    mode["code"] = 429
    asked.clear()
    got, _ = run(20.6)
    assert len(asked) == 1  # una sola vez, sin reintento ante 429
    saved = json.loads(state.read_text())["feeds"][feed.url]
    assert saved["status"]["httpStatus"] == 429 and saved["items"] == good  # las notas buenas siguen ahí
    asked.clear()
    got, _ = run(25)
    assert asked == [] and got["feeds"]["feeds"][0]["carried"] is True and got["feeds"]["feeds"][0]["ok"] is False
    got, _ = run(20.6 + 20.2)  # 20,2 h después del 429: dentro del margen
    assert asked == []
    mode["code"] = 200
    run(20.6 + 21)
    assert len(asked) == 1


def _reader_feed(monkeypatch, bodies):
    """Un feed «reader» que responde con ``bodies[0]`` (se puede cambiar) y anota cada pedido."""
    from enso import news as N

    feed = next(f for f in N.FEEDS if "news.google.com" in f.url)
    monkeypatch.setattr(N, "FEEDS", [feed])
    asked = []

    def net(req):
        asked.append(str(req.url))
        b = bodies[0]
        if isinstance(b, BaseException):
            raise b
        return httpx.Response(200, content=b, headers={"content-type": "application/rss+xml"})

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(**{**kw, "transport": httpx.MockTransport(net)}))
    return feed, asked, Fetcher(polite_delay=0, plan={feed.url: ["actions"]})


def _split_feed(feed) -> tuple[bytes, bytes]:
    import re

    body = (Path(__file__).parent / "fixtures" / "sources" / feed.fixture).read_bytes()
    items = re.findall(rb"<item>.*?</item>", body, re.S)
    head, tail = body[:body.index(items[0])], body[body.index(items[-1]) + len(items[-1]):]
    half = len(items) // 2
    return head + b"".join(items[:half]) + tail, head + b"".join(items[half:]) + tail


def test_reader_notes_survive_several_runs_that_did_not_publish(tmp_path, monkeypatch):
    """Revisión: cada lectura buena reemplazaba las notas del estado, y dos corridas seguidas sin publicar perdían
    las de la primera. Ahora se suman a las que ninguna publicación tiene todavía, y dejan el estado cuando una
    publicación las tiene."""
    from enso import news as N

    bodies = [b""]
    feed, asked, fetcher = _reader_feed(monkeypatch, bodies)
    a, b = _split_feed(feed)
    site, state, reader = _history_site(tmp_path, []), tmp_path / "state.json", {feed.url}

    def run(hours, site=site):
        return obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), obs.EventLog(),
                                NOW + timedelta(hours=hours), None, reader=reader, reader_state=state)

    bodies[0] = a
    first = {i["id"] for i in run(0)["items"]}
    bodies[0] = b
    second = run(24)  # tampoco publica: el sitio sigue igual
    saved = {i["id"] for i in json.loads(state.read_text())["feeds"][feed.url]["items"]}
    assert first and first <= {i["id"] for i in second["items"]} and first <= saved
    assert {i["id"] for i in second["items"]} <= saved
    # Publicadas: dejan el estado (solo queda la última lectura).
    published = _history_site(tmp_path, second["items"])
    bodies[0] = a
    run(48, published)
    saved = {i["id"] for i in json.loads(state.read_text())["feeds"][feed.url]["items"]}
    assert saved == first
    assert all(i["feed"] == feed.id for i in N.read_jsonl(published.joinpath("news", "items.jsonl").read_text()))


def test_a_reader_request_is_noted_before_it_is_made(tmp_path, monkeypatch):
    """Revisión: el pedido se anotaba en el estado al terminar la recolección. Si la corrida se cortaba antes
    (límite de tiempo, cancelación), la siguiente lo volvía a pedir a las pocas horas."""

    class Killed(BaseException):
        pass

    bodies = [Killed()]
    feed, asked, fetcher = _reader_feed(monkeypatch, bodies)
    site, state = _history_site(tmp_path, []), tmp_path / "state.json"
    with pytest.raises(Killed):
        obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), obs.EventLog(), NOW, None,
                         reader={feed.url}, reader_state=state)
    saved = json.loads(state.read_text())["feeds"][feed.url]["status"]
    assert len(asked) == 1 and saved["httpStatus"] is None and saved["checkedAt"] == NOW.isoformat(timespec="seconds")
    asked.clear()
    got = obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), obs.EventLog(),
                           NOW + timedelta(hours=7), None, reader={feed.url}, reader_state=state)
    assert asked == [] and got["feeds"]["feeds"][0]["carried"] is True


def test_a_reader_feed_whose_reading_failed_after_the_request_counts_as_asked(tmp_path, monkeypatch):
    """Revisión: si el feed respondía y fallaba después (al procesar sus notas), el estado no tenía «httpStatus»
    y cada corrida en main lo volvía a pedir."""
    from enso import news as N

    def broken(*a, **kw):
        raise KeyError("departments")

    feed = next(f for f in N.FEEDS if "news.google.com" in f.url)
    feed, asked, fetcher = _reader_feed(monkeypatch, [_split_feed(feed)[0]])
    monkeypatch.setattr(N, "hazards", broken)
    site, state = _history_site(tmp_path, []), tmp_path / "state.json"
    for hours in (0, 1, 2):
        got = obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), obs.EventLog(),
                               NOW + timedelta(hours=hours), None, reader={feed.url}, reader_state=state)
    assert len(asked) == 1 and "error inesperado" in got["feeds"]["feeds"][0]["error"]
    assert json.loads(state.read_text())["feeds"][feed.url]["status"]["httpStatus"] is None
    # También en la publicación: sin la caché, la corrida siguiente tampoco lo pide antes de plazo.
    first = obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), obs.EventLog(),
                             NOW + timedelta(hours=25), None, reader={feed.url}, reader_state=state)
    assert len(asked) == 2 and first["feeds"]["feeds"][0]["httpStatus"] is None
    published = _history_site(tmp_path, [], first["feeds"])
    obs.acquire_news(fetcher, None, obs.PreviousPublication(str(published), fetcher), obs.EventLog(),
                     NOW + timedelta(hours=28), None, reader={feed.url}, reader_state=tmp_path / "vacio.json")
    assert len(asked) == 2


def test_a_request_that_trickles_in_is_cut_at_its_total_time(monkeypatch):
    """Revisión: el plazo del cliente es por lectura; un servidor que manda el cuerpo de a pocos bytes retenía la
    recolección (y la publicación) hasta el límite del build."""
    import threading
    import time

    class Slow(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(50):
                threading.Event().wait(0.02)  # time.sleep está anulado en estas pruebas
                yield b"x"

    f = Fetcher(polite_delay=0, retries=3, max_seconds=0.3)  # sin reintento: tardaría lo mismo
    f.client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=Slow())))
    t = time.monotonic()
    with pytest.raises(FetchError) as err:
        f.get(["https://lento.pe/feed"], archive=False)
    assert time.monotonic() - t < 0.9 and "TooSlow" in str(err.value.attempts) and len(err.value.attempts) == 1
    # Una respuesta normal llega entera, descomprimida, con su URL final.
    import gzip as gz

    f.client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(
        200, content=gz.compress(b"<rss/>"), headers={"content-encoding": "gzip", "content-type": "application/rss+xml"})))
    r = f.get(["https://rapido.pe/feed"], archive=False)
    assert r.body == b"<rss/>" and r.url == "https://rapido.pe/feed" and "rss" in r.content_type


def test_a_host_that_does_not_answer_stops_costing_time(monkeypatch):
    """Revisión: cada fuente oficial reintentaba tres veces un servidor caído (12 fuentes en el de CPC): media
    hora sin publicar. Ahora, tras tres fallos de red seguidos, una sola vez por URL, y tras cinco, nada."""
    asked = []

    def net(req):
        asked.append(str(req.url))
        if req.url.host == "caido.gov":
            raise httpx.ConnectTimeout("sin respuesta")
        return httpx.Response(200, text="ok")

    f = Fetcher(polite_delay=0, retries=3, allow_archive=False)
    f.client = httpx.Client(transport=httpx.MockTransport(net))
    for i in range(12):
        with pytest.raises(FetchError):
            f.get([f"https://caido.gov/datos-{i}.txt"])
    assert len(asked) == 5  # 3 + 1 + 1, y después ninguno
    assert f.get(["https://otro.gov/x.txt"]).body == b"ok"  # los demás servidores, como siempre


def test_a_host_that_answers_503_to_everything_stops_costing_time(monkeypatch):
    """Revisión 7: cada 429 o 5xx ponía la cuenta del servidor en cero, así que uno que respondía 503 a todo nunca
    dejaba de costar tres intentos y sus esperas por URL (con Retry-After: 60, tres minutos por fuente), y se esperaba
    también después del último intento. Ahora una URL que solo recibió 429/5xx es un fallo del servidor."""
    asked, slept = [], []
    monkeypatch.setattr("enso.fetch.time.sleep", lambda s: slept.append(s))

    def net(req):
        asked.append(str(req.url))
        if req.url.host == "saturado.gov":
            return httpx.Response(503, headers={"retry-after": "60"})
        return httpx.Response(200, text="ok")

    f = Fetcher(polite_delay=0, retries=3, allow_archive=False)
    f.client = httpx.Client(transport=httpx.MockTransport(net))
    for i in range(12):
        with pytest.raises(FetchError):
            f.get([f"https://saturado.gov/datos-{i}.txt"])
    assert len(asked) == 3 * 3 + 2  # tres URL con sus tres intentos, dos con uno, y después ninguno
    assert slept == [60, 60] * 3  # dos esperas por URL: ninguna tras el último intento
    assert f.get(["https://otro.gov/x.txt"]).body == b"ok"
    one = Fetcher(polite_delay=0, retries=1, allow_archive=False)  # como el de los feeds «reader»
    one.client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(429, headers={"retry-after": "30"})))
    slept.clear()
    with pytest.raises(FetchError):
        one.get(["https://news.example/rss"])
    assert slept == []
    back = Fetcher(polite_delay=0, retries=3, allow_archive=False)  # un 503 pasajero no cuenta
    replies = iter([503, 200, 503, 200, 503, 200, 503, 200])
    back.client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(next(replies), text="ok")))
    for i in range(4):
        assert back.get([f"https://pasajero.gov/{i}"]).body == b"ok"
    assert back._down.get("pasajero.gov", 0) == 0


def test_slow_save_page_now_does_not_turn_off_the_archive_reads(monkeypatch):
    """Revisión 7: Save Page Now compartía la cuenta de fallos con las búsquedas (CDX) y las copias del Internet
    Archive: las capturas lentas de las páginas que se sondean (el comunicado siguiente, que aún no existe) y un
    CDX que tardó apagaban todas las lecturas del archivo, y el PDF del comunicado nuevo no se leía."""
    monkeypatch.setattr("enso.fetch.time.sleep", lambda s: None)
    header = ["urlkey", "timestamp", "original"]
    cdx_18 = []

    def net(req):
        if req.url.path.startswith("/save/"):
            raise httpx.ReadTimeout("captura lenta")
        if req.url.path.startswith("/cdx/"):
            if "19.pdf" in str(req.url):
                return httpx.Response(200, json=[header])  # el comunicado siguiente aún no tiene copias
            cdx_18.append(1)
            if len(cdx_18) == 1:
                raise httpx.ReadTimeout("CDX lento")
            return httpx.Response(200, json=[header, ["k", "20261020120000", "https://enfen.example/18.pdf"]])
        if req.url.path.startswith("/web/"):
            return httpx.Response(200, content=b"%PDF-1.7 comunicado", headers={"content-type": "application/pdf"})
        return httpx.Response(404)

    f = Fetcher(polite_delay=0, retries=3, allow_save=True)
    f.client = httpx.Client(transport=httpx.MockTransport(net))
    with pytest.raises(FetchError):  # sondeo: sin copia y con capturas que no terminan
        f.get(["https://enfen.example/19.pdf"], save=True)
    assert f._down["web.archive.org/save"] == 3
    got = f.get(["https://enfen.example/18.pdf"], save=True)
    assert got.body.startswith(b"%PDF") and got.channel == "archive" and len(cdx_18) == 2
    assert f._down.get("web.archive.org", 0) == 0


def test_a_broken_answer_is_a_failed_url_not_a_crash():
    """Revisión: gzip roto o redirecciones sin fin no son errores de red y salían de Fetcher.get, deteniendo la
    publicación entera desde el sondeo de comunicados. Ahora son una URL fallida: se sigue con la siguiente."""
    def net(req):
        if req.url.path == "/gzip":
            return httpx.Response(200, content=b"%PDF-no comprimido", headers={"content-encoding": "gzip"})
        if req.url.path == "/bucle":
            return httpx.Response(302, headers={"location": "/bucle"})
        return httpx.Response(200, content=b"%PDF-bien")

    for limit in (None, 300):
        f = Fetcher(polite_delay=0, retries=3, allow_archive=False, max_seconds=limit)
        f.client = httpx.Client(transport=httpx.MockTransport(net), follow_redirects=True)
        r = f.get(["https://dhn.example/gzip", "https://dhn.example/bucle", "https://dhn.example/ok"])
        assert r.body == b"%PDF-bien" and r.channel == "mirror"
        assert [a["error"].split(":")[0] for a in r.attempts[:2]] == ["DecodingError", "TooManyRedirects"]


def test_requests_stop_when_the_time_budget_is_spent(monkeypatch):
    """Pasado el tiempo de las fuentes oficiales no se pide nada más (cada fuente sigue con su copia o su dato
    anterior), y un pedido en curso no lo sobrepasa."""
    import threading

    class Slow(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(100):
                threading.Event().wait(0.02)
                yield b"x"

    asked = []
    f = Fetcher(polite_delay=0, retries=3, allow_archive=False, max_seconds=60, budget_s=0.3)
    f.client = httpx.Client(transport=httpx.MockTransport(lambda req: asked.append(1) or httpx.Response(200, stream=Slow())))
    with pytest.raises(FetchError) as err:
        f.get(["https://lento.gov/a", "https://lento.gov/b"])
    assert len(asked) == 1 and "TooSlow" in err.value.attempts[0]["error"]
    assert "se agotó el tiempo" in err.value.attempts[1]["error"]


def test_reader_notes_are_kept_when_the_run_is_cut_after_their_read(tmp_path, monkeypatch):
    """Revisión: las notas de una lectura buena se guardaban al final de la recolección; una corrida cortada
    después (límite de tiempo, cancelación) las perdía, y el feed quedaba como pedido por 20 h."""
    from enso import news as N

    class Killed(BaseException):
        pass

    feeds = [f for f in N.FEEDS if "news.google.com" in f.url][:2]
    monkeypatch.setattr(N, "FEEDS", feeds)
    body = (Path(__file__).parent / "fixtures" / "sources" / feeds[0].fixture).read_bytes()

    def net(req):
        if str(req.url) == feeds[1].url:
            raise Killed()
        return httpx.Response(200, content=body, headers={"content-type": "application/rss+xml"})

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(**{**kw, "transport": httpx.MockTransport(net)}))
    fetcher = Fetcher(polite_delay=0, plan={f.url: ["actions"] for f in feeds})
    site, state = _history_site(tmp_path, []), tmp_path / "state.json"
    with pytest.raises(Killed):
        obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), obs.EventLog(), NOW, None,
                         reader={f.url for f in feeds}, reader_state=state)
    saved = json.loads(state.read_text())["feeds"]
    assert saved[feeds[0].url]["status"]["ok"] is True and saved[feeds[0].url]["items"]
    assert saved[feeds[1].url]["status"]["httpStatus"] is None  # el que estaba en curso: pedido, sin resultado


def test_reader_feeds_are_not_asked_when_nothing_says_when_they_were_last_asked(tmp_path, monkeypatch):
    """Revisión: sin estado (la caché no se pudo leer) y con el sitio caído no se sabía cuándo se habían pedido, y
    se volvían a pedir todos. Ahora no se piden en esa corrida; en una primera publicación (404) sí."""
    from enso import news as N

    feed, asked, fetcher = _reader_feed(monkeypatch, [_split_feed(next(f for f in N.FEEDS if "news.google.com" in f.url))[0]])
    client = type(fetcher.client)  # httpx.Client sin el transporte de _reader_feed
    monkeypatch.setattr(obs.time, "sleep", lambda s: None)
    down = Fetcher(polite_delay=0)
    down.client = client(transport=httpx.MockTransport(lambda req: httpx.Response(503)))
    log = obs.EventLog()
    got = obs.acquire_news(fetcher, None, obs.PreviousPublication("https://sitio.example/data", down), log, NOW, None,
                           reader={feed.url}, reader_state=tmp_path / "state.json")
    assert asked == [] and got["feeds"]["feeds"][0]["skipped"] == "reader-unknown"
    assert any(e.code == "feeds-reader-unknown" and e.severity == "warning" for e in log.events)
    # Revisión 7: esa corrida cuenta como el pedido, en el estado y en la publicación. Antes guardaba un estado
    # vacío y publicaba el feed sin hora de pedido, y la corrida siguiente lo pedía aunque el anterior fuera de
    # hacía una hora.
    saved = json.loads((tmp_path / "state.json").read_text())["feeds"][feed.url]["status"]
    assert saved["httpStatus"] is None and saved["skipped"] == "reader-unknown" and saved["checkedAt"] == NOW.isoformat(timespec="seconds")
    assert got["feeds"]["feeds"][0]["httpStatus"] is None
    feeds_json = json.dumps(got["feeds"]).encode()
    site = Fetcher(polite_delay=0)
    site.client = client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, content=feeds_json) if req.url.path.endswith("/news/feeds.json") else httpx.Response(404)))
    for hours, state, want in ((3, "state.json", []), (3, "otra.json", []), (21, "state.json", [feed.url])):
        log = obs.EventLog()
        later = obs.acquire_news(fetcher, None, obs.PreviousPublication("https://sitio.example/data", site), log,
                                 NOW + timedelta(hours=hours), None, reader={feed.url}, reader_state=tmp_path / state)
        assert asked == want, (hours, state)
        assert not any(e.code == "feeds-reader-unknown" for e in log.events)
        if not want:
            st = later["feeds"]["feeds"][0]
            assert st["carried"] and st["skipped"] == "reader-unknown" and st["checkedAt"] == NOW.isoformat(timespec="seconds")
    asked.clear()
    first = Fetcher(polite_delay=0)
    first.client = client(transport=httpx.MockTransport(lambda req: httpx.Response(404)))
    obs.acquire_news(fetcher, None, obs.PreviousPublication("https://sitio.example/data", first), obs.EventLog(), NOW,
                     None, reader={feed.url}, reader_state=tmp_path / "primera.json")
    assert asked == [feed.url]


def test_reader_feeds_are_only_read_by_the_daily_run(monkeypatch, tmp_path):
    """Sin --reader-state (pruebas de captura, una corrida a mano en otro equipo) no se sabe cuándo se leyeron:
    no se piden, como cualquier feed que robots.txt no permite."""
    seen = {}
    monkeypatch.setattr(obs, "run", lambda *a, **kw: seen.update(kw) or {"publicationId": "x", "worst": "info"})
    obs.main(["--out", str(tmp_path / "out"), "--previous", "", "--fail-on", "never"])
    reader = registry.reader_urls()
    assert seen["reader"] is None and all(seen["plan"][u] == [] for u in reader)
    assert sum(1 for ch in seen["plan"].values() if ch == []) == len(reader) + sum(
        1 for u, ch in registry.url_channels().items() if ch == [])
    obs.main(["--out", str(tmp_path / "out"), "--previous", "", "--fail-on", "never",
              "--reader-state", str(tmp_path / "state.json")])
    assert seen["reader"] == reader and seen["plan"] == registry.url_channels()
    obs.main(["--out", str(tmp_path / "out"), "--previous", "", "--fail-on", "never", "--offline"])
    assert seen["reader"] is None and seen["plan"] is None
