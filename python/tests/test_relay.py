"""Recolector desde el Perú y su uso como canal «relay-peru»."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from conftest import FIX
from enso import observatory as obs
from enso.fetch import Fetcher, Relay
from tools import peru_collector as pc

LISTING = (FIX / "history" / "enfen-comunicados-20261014125242.html").read_text(encoding="utf-8")
PDF = next((FIX.parent / "live-run" / "raw" / "enfen-comunicados").glob("*.pdf")).read_bytes()


def _peru_only(req: httpx.Request) -> httpx.Response:
    """Respuestas que vería una máquina en el Perú."""
    u = str(req.url)
    if "wp-json" in u:
        return httpx.Response(404)
    if u.rstrip("/").endswith("/comunicados"):
        return httpx.Response(200, text=LISTING, headers={"content-type": "text/html"})
    if "wpdmdl=" in u:
        return httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"})
    if "/download/comunicado-oficial-enfen-n-18-2026/" in u:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=(
            '<a href="https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-18-2026/'
            '?wpdmdl=2190&amp;refresh=abc">Descargar</a>'))
    if "/download/" in u:
        return httpx.Response(404)
    return httpx.Response(200, text="<html>" + "x" * 600 + "</html>", headers={"content-type": "text/html"})


@pytest.fixture(autouse=True)
def _no_registry(monkeypatch, tmp_path):
    """Sin registro de fuentes salvo que la prueba lo ponga (y sin consultar GitHub)."""
    monkeypatch.setenv("ENSO_REGISTRY_FILE", str(tmp_path / "sin-registro.json"))


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    import enso.fetch

    monkeypatch.setattr(enso.fetch.time, "sleep", lambda s: None)


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    real = httpx.Client
    monkeypatch.setattr(pc.httpx, "Client", lambda **kw: real(**{"transport": httpx.MockTransport(_peru_only), **kw}))
    monkeypatch.setattr(pc.time, "sleep", lambda s: None)
    out = tmp_path / "relay"
    return out, pc.collect(out)


def test_collector_writes_index_and_bodies(snapshot):
    out, idx = snapshot
    assert idx["schema"] == "enso-relay/1"
    assert json.loads((out / "index.json").read_text(encoding="utf-8")) == idx
    ok = [e for e in idx["entries"] if e.get("status") == 200]
    assert ok and all((out / e["file"]).is_file() for e in ok)
    docs = [e for e in idx["entries"] if e["group"] == "enfen-docs"]
    # PDF del 17-2026, sondeo del 18 (página y PDF enlazado, con alias) y del 19.
    assert any(e["url"].endswith("/comunicado-oficial-enfen-n-18-2026/") and e["status"] == 200 for e in docs)
    pdf18 = [e for e in docs if e.get("aliases")]
    assert pdf18 and "refresh" not in pdf18[0]["url"] and pdf18[0]["file"].endswith(".pdf")
    assert idx["summary"]["enfen"] == "2/3"


def test_fetcher_uses_relay_when_source_is_unreachable(snapshot):
    out, _ = snapshot

    def offshore(req):  # GitHub Actions: el ENFEN no resuelve
        if "enfen.imarpe.gob.pe" in req.url.host:
            raise httpx.ConnectError("Temporary failure in name resolution")
        return httpx.Response(404)

    f = Fetcher(retries=1, polite_delay=0, allow_archive=False, relay=Relay(out))
    f.client = httpx.Client(transport=httpx.MockTransport(offshore))
    src = obs.SOURCE_BY_ID["enfen-comunicados"]
    r = f.get(src.urls, accept=src.accept)
    assert r.channel == "relay-peru" and r.url == "https://enfen.imarpe.gob.pe/comunicados/"
    assert obs.peru.parse_enfen_listing(r.text).data[0]["id"] == "17-2026"
    # El sondeo del 18 encuentra la página y luego el PDF, como en la corrida diaria.
    page = f.get([f"{obs.ENFEN_BASE}/download/comunicado-oficial-enfen-n-18-2026/"], accept=("html",))
    assert page.channel == "relay-peru"
    pdf = f.get([f"{obs.ENFEN_BASE}/download/comunicado-oficial-enfen-n-18-2026/"], accept=("pdf",))
    assert pdf.body[:5] == b"%PDF-"
    with pytest.raises(Exception):
        f.get([f"{obs.ENFEN_BASE}/download/comunicado-oficial-enfen-n-19-2026/"], accept=("html",))


def test_relay_rejects_tampered_and_old_copies(snapshot):
    out, idx = snapshot
    e = next(e for e in idx["entries"] if e.get("file", "").endswith(".html"))
    (out / e["file"]).write_bytes(b"alterado")
    assert Relay(out).get(e["url"]) is None
    idx["collected_at"] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat(timespec="seconds")
    (out / "index.json").write_text(json.dumps(idx), encoding="utf-8")
    pdf = next(x for x in idx["entries"] if x.get("file", "").endswith(".pdf"))
    assert Relay(out).get(pdf["url"]) is None
    idx["entries"].append({"url": "https://x/", "status": 200, "file": "../../etc/passwd", "sha256": ""})
    (out / "index.json").write_text(json.dumps(idx), encoding="utf-8")
    assert Relay(out, max_age_hours=1e9).get("https://x/") is None


def test_stale_or_missing_relay_is_logged(tmp_path, snapshot):
    out, idx = snapshot
    log = obs.EventLog()
    assert obs.load_relay(tmp_path / "nada", log) is None
    assert log.events[-1].code == "relay-missing"
    idx["collected_at"] = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat(timespec="seconds")
    (out / "index.json").write_text(json.dumps(idx), encoding="utf-8")
    assert obs.load_relay(out, log) is not None
    assert log.events[-1].code == "relay-stale" and log.events[-1].severity == "warning"


def _beat(out: Path, hours_ago: float, result: str = "sin-fuentes") -> None:
    at = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat(timespec="seconds")
    (out / "heartbeat.json").write_text(json.dumps({
        "schema": "enso-relay-heartbeat/1", "at": at, "result": result, "reachable": "0/11",
        "collector": {"token_expires_at": "2099-01-01T00:00:00+00:00"}}), encoding="utf-8")


def test_heartbeat_tells_sources_down_from_collector_down(tmp_path, snapshot):
    out, idx = snapshot
    idx["collected_at"] = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat(timespec="seconds")
    (out / "index.json").write_text(json.dumps(idx), encoding="utf-8")
    # Latido reciente sin fuentes: el equipo funciona, las instituciones no responden.
    _beat(out, 2)
    log = obs.EventLog()
    assert obs.load_relay(out, log) is not None
    codes = [e.code for e in log.events]
    assert "relay-sources-down" in codes and "relay-stale" not in codes
    # Latido viejo también: el recolector no está corriendo.
    _beat(out, 48)
    log = obs.EventLog()
    obs.load_relay(out, log)
    stale = [e for e in log.events if e.code == "relay-stale"]
    assert stale and "último latido" in stale[0].message
    # Sin copia buena todavía, pero con latido: tampoco es «relay-missing».
    empty = tmp_path / "solo-latido"
    empty.mkdir()
    _beat(empty, 1)
    log = obs.EventLog()
    assert obs.load_relay(empty, log) is None and log.events[-1].code == "relay-sources-down"


REGISTRY = {
    "schema": "enso-source-registry/1",
    "generated_at": "2026-10-21T00:00:00+00:00",
    "sources": [
        # Geobloqueada y con documentos enlazados: la baja este equipo.
        {"id": "indeci-alertas", "group": "INDECI", "url": "https://www.indeci.gob.pe/alertas/",
         "channels": ["peru-server"], "geoblocked": True,
         "follow": {"pattern": r"[^\"'\s<>]+\.pdf", "max": 2}},
        # Ya está en SOURCES: no se repite.
        {"id": "senamhi-avisos", "group": "senamhi", "url": "https://www.senamhi.gob.pe/?p=aviso-meteorologico",
         "channels": ["peru-server"], "geoblocked": True},
        # Responde desde fuera: no es para este equipo.
        {"id": "news-andina", "group": "andina", "url": "https://andina.pe/agencia/rss/3.xml",
         "channels": ["actions", "n8n"], "geoblocked": False},
        {"id": "roto", "url": "javascript:alert(1)", "channels": ["peru-server"]},
    ],
}


def test_collector_adds_peru_only_sources_from_the_registry(tmp_path, monkeypatch):
    reg = tmp_path / "sources.json"
    reg.write_text(json.dumps(REGISTRY), encoding="utf-8")
    monkeypatch.setenv("ENSO_REGISTRY_FILE", str(reg))

    def peru(req: httpx.Request) -> httpx.Response:
        if str(req.url) == "https://www.indeci.gob.pe/alertas/":
            return httpx.Response(200, headers={"content-type": "text/html"}, text=(
                '<a href="/docs/alerta-1.pdf">1</a> <a href="/docs/alerta-1.pdf">otra vez</a> '
                '"https:\\/\\/www.indeci.gob.pe\\/docs\\/alerta-2.pdf" <a href="/docs/alerta-3.pdf">3</a>'))
        if str(req.url).endswith(".pdf") and "indeci" in str(req.url):
            return httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"})
        return _peru_only(req)

    real = httpx.Client
    monkeypatch.setattr(pc.httpx, "Client", lambda **kw: real(**{"transport": httpx.MockTransport(peru), **kw}))
    monkeypatch.setattr(pc.time, "sleep", lambda s: None)
    idx = pc.collect(tmp_path / "out")
    urls = [e["url"] for e in idx["entries"]]
    assert "https://www.indeci.gob.pe/alertas/" in urls and "https://andina.pe/agencia/rss/3.xml" not in urls
    assert urls.count("https://www.senamhi.gob.pe/?p=aviso-meteorologico") == 1
    linked = [e for e in idx["entries"] if e["group"] == "enlaces"]
    assert [e["url"] for e in linked] == ["https://www.indeci.gob.pe/docs/alerta-1.pdf",
                                          "https://www.indeci.gob.pe/docs/alerta-2.pdf"]
    assert all(e["parent"] == "https://www.indeci.gob.pe/alertas/" and e["file"].endswith(".pdf") for e in linked)
    assert idx["registry"] == {"origin": "archivo", "generated_at": "2026-10-21T00:00:00+00:00", "peru_server": 2}
    assert idx["summary"]["indeci"] == "1/1"


def test_registry_comes_from_github_with_the_token_then_the_kit(monkeypatch, tmp_path):
    monkeypatch.delenv("ENSO_REGISTRY_FILE")
    monkeypatch.delenv("ENSO_RELAY_REMOTE", raising=False)
    asked = []

    def get(url, **kw):
        asked.append((url, kw["headers"].get("Authorization")))
        return httpx.Response(200, json=REGISTRY, request=httpx.Request("GET", url))

    monkeypatch.setattr(pc.httpx, "get", get)
    reg, origin = pc.load_registry("github_pat_x")
    assert origin == "github" and reg["sources"] and asked[0][1] == "Bearer github_pat_x"
    assert asked[0][0].endswith("/contents/registry/sources.json")
    monkeypatch.setattr(pc.httpx, "get", lambda url, **kw: (_ for _ in ()).throw(httpx.ConnectError("sin red")))
    reg, origin = pc.load_registry("github_pat_x")  # sin GitHub: la copia del kit/repositorio, si existe
    assert origin in ("kit", "") and (bool(reg) == (origin == "kit"))


def test_next_run_is_9pm_lima():
    lima = pc.LIMA
    assert pc.next_run("21:00", datetime(2026, 10, 20, 15, 0, tzinfo=lima)) == datetime(2026, 10, 20, 21, 0, tzinfo=lima)
    nxt = pc.next_run("21:00", datetime(2026, 10, 20, 21, 0, 30, tzinfo=lima))
    assert nxt == datetime(2026, 10, 21, 21, 0, tzinfo=lima)
    assert nxt.utcoffset() == timedelta(hours=-5)


def test_collector_sources_match_pipeline_catalog():
    """El recolector debe pedir las mismas URL que la corrida diaria."""
    assert set(pc.SOURCES["enfen"]) <= set(obs.SOURCE_BY_ID["enfen-comunicados"].urls)


def test_push_creates_then_updates_branch(snapshot, tmp_path, monkeypatch):
    import subprocess

    out, _ = snapshot
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    monkeypatch.setenv("ENSO_RELAY_REMOTE", str(bare))
    pc.push(out, "tok")
    pc.push(out, "tok")  # sin cambios: no crea otro commit
    log = subprocess.run(["git", "--git-dir", str(bare), "log", "--format=%s", pc.BRANCH],
                         capture_output=True, text=True, check=True).stdout.splitlines()
    assert len(log) == 1 and log[0].startswith("relay: fuentes peruanas")
    files = subprocess.run(["git", "--git-dir", str(bare), "ls-tree", "-r", "--name-only", pc.BRANCH],
                           capture_output=True, text=True, check=True).stdout.split()
    assert "index.json" in files and any(f.endswith(".pdf") for f in files)


HUMAN_CHECK = "<html><title>Verificación de seguridad</title>Complete la verificación para acceder</html>"


def _actions_view(relay_pdf: bytes | None = None):
    """Como desde GitHub Actions: el ENFEN no resuelve y los PDF de la DHN
    redirigen a una verificación humana (visto el 20 de octubre de 2026)."""
    def handler(req):
        u = str(req.url)
        if "enfen.imarpe.gob.pe" in req.url.host:
            raise httpx.ConnectError("Temporary failure in name resolution")
        if "/cdx/" in u:
            return httpx.Response(200, json=[])
        if "dhn.mil.pe" in req.url.host and u.endswith(".pdf"):
            return httpx.Response(200, text=HUMAN_CHECK, headers={"content-type": "text/html; charset=UTF-8"})
        return httpx.Response(404)
    return handler


class _Prev:
    def __init__(self, latest):
        self.latest = latest

    def get(self, name):
        return {"data": {"latest": self.latest}} if self.latest else None


def _dhn_acquired():
    from enso.fetch import Response

    body = (FIX / "dhn-comunicados-enfen.html").read_bytes()
    acq = obs.Acquired(obs.SOURCE_BY_ID["enfen-comunicados"])
    acq.data = obs._parse_enfen(Response("https://www.dhn.mil.pe/portal/comunicados-oficiales-enfen", body, "mirror", 200)).data
    acq.ok = True
    return acq


def test_dhn_human_check_is_not_taken_for_a_pdf():
    """La verificación humana no se toma por un comunicado: se conserva el
    último estado leído y la incidencia queda registrada."""
    from datetime import date

    acq = _dhn_acquired()
    top = acq.data["listing"][0]
    prev = {"year": top["year"], "number": top["number"] - 1, "id": f"{top['number'] - 1:02d}-{top['year']}",
            "status": "Alerta de El Niño Costero"}
    f = Fetcher(retries=1, polite_delay=0)
    f.client = httpx.Client(transport=httpx.MockTransport(_actions_view()))
    log = obs.EventLog()
    obs.enfen_latest(acq, f, None, _Prev(prev), log, date(2026, 10, 20))
    assert acq.data["latest"] == prev
    unread = [e for e in log.events if e.code == "communique-unread"]
    assert unread and top["id"] in unread[0].message
    assert not acq.documents or all(not d.startswith(b"%PDF") for d in acq.documents)


def test_dhn_pdf_from_relay_is_read(tmp_path):
    """Con la copia del recolector del Perú, el PDF se lee aunque la DHN pida verificación."""
    from datetime import date

    acq = _dhn_acquired()
    top = acq.data["listing"][0]
    url = obs._communique_urls(top)[0]
    root = tmp_path / "relay"
    (root / "files").mkdir(parents=True)
    import hashlib
    sha = hashlib.sha256(PDF).hexdigest()
    (root / "files" / f"{sha[:16]}.pdf").write_bytes(PDF)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (root / "index.json").write_text(json.dumps({"schema": "enso-relay/1", "collected_at": now, "entries": [
        {"url": url, "status": 200, "content_type": "application/pdf", "file": f"files/{sha[:16]}.pdf",
         "sha256": sha, "fetched_at": now}]}), encoding="utf-8")
    f = Fetcher(retries=1, polite_delay=0, relay=Relay(root))
    f.client = httpx.Client(transport=httpx.MockTransport(_actions_view()))
    obs.enfen_latest(acq, f, None, _Prev(None), obs.EventLog(), date(2026, 10, 20))
    latest = acq.data["latest"]
    assert latest["channel"] == "relay-peru" and latest["status_code"] == "alerta_nino"


def test_communique_found_by_archive_prefix_when_dhn_and_enfen_fail():
    """Primera corrida sin publicación anterior: el PDF del ENFEN guardado en
    el Internet Archive (con su parámetro de descarga) evita quedarse sin estado."""
    from datetime import date

    base = _actions_view()

    def handler(req):
        u = str(req.url)
        if "/cdx/" in u and "matchType=prefix" in u and "n-18-2026" not in u:
            return httpx.Response(200, json=[["urlkey", "timestamp", "original", "mimetype"],
                                             ["x", "20261001000000", "https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-17-2026/?wpdmdl=2161", "application/force-download"],
                                             ["x", "20261002000000", "https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-17-2026/", "text/html"]])
        if "/web/20261001000000id_/" in u:
            return httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"})
        return base(req)

    acq = _dhn_acquired()
    f = Fetcher(retries=1, polite_delay=0)
    f.client = httpx.Client(transport=httpx.MockTransport(handler))
    log = obs.EventLog()
    obs.enfen_latest(acq, f, None, _Prev(None), log, date(2026, 10, 20))
    latest = acq.data["latest"]
    assert latest["id"] == "17-2026" and latest["channel"] == "archive"
    assert any(e.code == "communique-unread" and "18-2026" in e.message for e in log.events)
