"""Las mismas fuentes por los tres canales (Actions, n8n, Perú): canales por URL, copias y avisos."""

from __future__ import annotations

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
    assert "data-peru no existe" in ev.message and "2 URL" in ev.message and "senamhi.gob.pe" in ev.message
    assert obs.load_n8n_relay(tmp_path / "n8n", log) is None
    assert log.events[-1].code == "relay-n8n-missing" and "data-n8n no existe" in log.events[-1].message


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
