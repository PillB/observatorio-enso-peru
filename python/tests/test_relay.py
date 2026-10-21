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
    ok = [e for e in idx["entries"] if pc.usable(e)]
    assert ok and all((out / e["file"]).is_file() and e["class"] == "ok" for e in ok)
    # Un 200 que no es lo esperado (la página de error del DHN en lugar del PDF) no se guarda.
    soft = [e for e in idx["entries"] if e["url"].endswith("/18-2026.pdf")]
    assert soft and soft[0]["status"] == 200 and "file" not in soft[0] and soft[0]["class"] == "empty"
    assert soft[0]["error"] == "se esperaba un PDF y llegó html"
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
        # Su robots.txt no lo permite: tampoco se pide la copia de SOURCES.
        {"id": "imarpe-seccion", "group": "imarpe", "channels": [], "geoblock": {"status": "robots-disallowed"},
         "url": "https://www.imarpe.gob.pe/imarpe/index.php?id_seccion=I0178070000000000000000"},
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
    assert not any("id_seccion" in u for u in urls) and "https://www.imarpe.gob.pe/" in urls
    linked = [e for e in idx["entries"] if e["group"] == "enlaces"]
    assert [e["url"] for e in linked] == ["https://www.indeci.gob.pe/docs/alerta-1.pdf",
                                          "https://www.indeci.gob.pe/docs/alerta-2.pdf"]
    assert all(e["parent"] == "https://www.indeci.gob.pe/alertas/" and e["file"].endswith(".pdf") for e in linked)
    assert idx["registry"] == {"origin": "archivo", "generated_at": "2026-10-21T00:00:00+00:00", "sources": 5,
                               "peru_server": 2, "age_days": idx["registry"]["age_days"]}
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


def test_probes_of_unpublished_communiques_do_not_ask_save_page_now():
    """Revisión 8: los sondeos de los dos números siguientes (que casi nunca existen todavía) le pedían una copia
    nueva al Internet Archive, que el ENFEN no atiende (523): unos 200 s por corrida del tiempo de las fuentes
    oficiales, y fallos de Save Page Now antes de capturar el comunicado que sí hay que leer."""
    from datetime import date

    asked = []
    base = _actions_view()

    def handler(req):
        asked.append(str(req.url))
        return base(req)

    acq = _dhn_acquired()
    top = acq.data["listing"][0]
    f = Fetcher(retries=1, polite_delay=0, allow_save=True)
    f.client = httpx.Client(transport=httpx.MockTransport(handler))
    obs.enfen_latest(acq, f, None, _Prev(None), obs.EventLog(), date(2026, 10, 20))
    saves = [u for u in asked if "/save/" in u]
    for n in (top["number"] + 1, top["number"] + 2):
        page = f"comunicado-oficial-enfen-n-{n:02d}-{top['year']}"
        assert any(page in u for u in asked), page  # se sondea (directo y copia existente del archivo)
        assert not any(page in u for u in saves), page
    assert saves  # el comunicado del listado sí se pide al archivo


# --- Control del contenido, alternativas, copias conservadas y mediciones ---------

CHALLENGE = ("<html><head><title>Just a moment...</title></head><body>"
             "<script src='https://challenges.cloudflare.com/turnstile/v0/api.js'></script></body></html>")


def _collect(tmp_path, monkeypatch, handler, registry: dict | None = None, name: str = "out", **kw) -> dict:
    if registry is not None:
        reg = tmp_path / "registro.json"
        reg.write_text(json.dumps(registry), encoding="utf-8")
        monkeypatch.setenv("ENSO_REGISTRY_FILE", str(reg))
    real = httpx.Client
    monkeypatch.setattr(pc.httpx, "Client", lambda **k: real(**{"transport": httpx.MockTransport(handler), **k}))
    monkeypatch.setattr(pc.time, "sleep", lambda s: None)
    return pc.collect(tmp_path / name, **kw)


def test_judge_uses_the_shared_classifier_and_the_expected_type():
    assert pc.judge(200, CHALLENGE.encode(), "text/html")[0] == "challenge"
    assert pc.judge(200, b"<html>" + b"x" * 600 + b"</html>", "text/html", "pdf") == (
        "empty", "html", "se esperaba un PDF y llegó html")
    assert pc.judge(200, b"{roto", "application/json", "json") == ("empty", "json", "JSON inválido")
    assert pc.judge(200, b"\xef\xbb\xbf{\"a\": 1}", "", "json")[:2] == ("ok", "json")
    # Un PDF o un feed que menciona «captcha» no es una verificación.
    assert pc.judge(200, PDF[:2000] + b" g-recaptcha ", "application/pdf", "pdf")[0] == "ok"
    assert pc.judge(200, b'<?xml version="1.0"?><rss><channel><item>turnstile</item></channel></rss>', "", "rss")[0] == "ok"
    assert pc.judge(200, b"<html><body>noticias</body></html>" * 30, "text/html", "rss")[0] == "empty"
    assert pc.judge(200, b"<html><body>casi nada</body></html>", "text/html", "html")[2] == "HTML casi vacío"
    assert pc.judge(403, b"Forbidden")[0] == "http-403"
    assert pc.detect(b'<?xml version="1.0"?><wfs:WFS_Capabilities>') == "xml"
    assert pc.detect(b'<feed xmlns="http://www.w3.org/2005/Atom">') == "atom"
    assert pc.detect(b"YYYY MM SST\n2026 09 25.1\n") == "text"


def test_antibot_pages_are_not_saved_and_do_not_count(tmp_path, monkeypatch):
    def peru(req):
        if "aviso-meteorologico" in str(req.url):
            return httpx.Response(200, text=CHALLENGE, headers={"content-type": "text/html"})
        return _peru_only(req)

    idx = _collect(tmp_path, monkeypatch, peru)
    e = next(e for e in idx["entries"] if e["url"].endswith("aviso-meteorologico"))
    assert e["status"] == 200 and e["class"] == "challenge" and "file" not in e and "antirobots" in e["error"]
    assert not pc.usable(e) and {"url": e["url"], "status": 200, "class": "challenge",
                                 "error": e["error"]} in pc.heartbeat(idx, "ok")["failures"]
    # Los JSON de IDESEP y del CENEPRED se esperan como JSON: una página HTML no sirve.
    idesep = next(e for e in idx["entries"] if "g_aviso" in e["url"])
    assert idesep["expect"] == "json" and idesep["class"] == "empty" and "file" not in idesep


ALT_REGISTRY = {
    "schema": "enso-source-registry/1", "generated_at": "2026-10-21T00:00:00+00:00",
    "sources": [
        {"id": "dhn-avisos", "group": "dhn", "url": "https://www.dhn.mil.pe/portal/avisos-especiales",
         "expect": "html", "channels": ["actions", "n8n", "peru-server"], "geoblocked": True,
         "alt_urls": ["https://www.dhn.mil.pe/abierto", "https://www.dhn.mil.pe/espejo/avisos",
                      "https://www.dhn.mil.pe/avisos.json"],
         "alt_expect": ["html", "html", "json"],
         "by_url": {"https://www.dhn.mil.pe/portal/avisos-especiales": {"status": "geoblocked", "channels": ["peru-server"]},
                    "https://www.dhn.mil.pe/abierto": {"status": "open", "channels": ["actions", "n8n"]},
                    "https://www.dhn.mil.pe/espejo/avisos": {"status": "unknown", "channels": ["actions", "n8n"]},
                    "https://www.dhn.mil.pe/avisos.json": {"status": "down", "channels": ["actions", "n8n"]}}},
        # Por URL: la principal responde a Actions y la réplica https solo desde el Perú.
        {"id": "igp-icen", "group": "igp", "url": "http://met.igp.gob.pe/datos/ICEN.txt", "expect": "text",
         "channels": ["actions", "n8n", "peru-server"], "geoblocked": True,
         "alt_urls": ["https://met.igp.gob.pe/datos/ICEN.txt"], "alt_expect": ["text"],
         "by_url": {"http://met.igp.gob.pe/datos/ICEN.txt": {"status": "open", "channels": ["actions", "n8n"]},
                    "https://met.igp.gob.pe/datos/ICEN.txt": {"status": "geoblocked", "channels": ["peru-server"]}}},
    ],
}


def test_alternative_urls_are_tried_only_when_the_main_one_fails(tmp_path, monkeypatch):
    asked = []

    def peru(req):
        u = str(req.url)
        asked.append(u)
        if u.endswith("/portal/avisos-especiales"):
            return httpx.Response(503, text="mantenimiento")
        if u.endswith("/espejo/avisos"):
            return httpx.Response(200, text=CHALLENGE, headers={"content-type": "text/html"})
        if u.endswith("/avisos.json"):
            return httpx.Response(200, json={"avisos": [1]})
        if u.endswith("ICEN.txt"):
            return httpx.Response(200, text="2026 9 0.85\n")
        return _peru_only(req)

    idx = _collect(tmp_path, monkeypatch, peru, ALT_REGISTRY)
    dhn = [e for e in idx["entries"] if e["group"] == "dhn"]
    # La réplica que responde a EE. UU. no se pide: ya la bajan Actions y n8n.
    assert [(e["url"].rsplit("/", 1)[-1], e["class"]) for e in dhn] == [
        ("avisos-especiales", "http-5xx"), ("avisos", "challenge"), ("avisos.json", "ok")]
    assert not any(u.endswith("/abierto") for u in asked)
    assert all(e["source"] == "dhn-avisos" for e in dhn) and dhn[2]["alt_of"] == ALT_REGISTRY["sources"][0]["url"]
    assert dhn[2]["file"].endswith(".json") and dhn[2]["expect"] == "json"
    # Canales por URL: del ICEN se pide solo la URL asignada al Perú.
    assert [e["url"] for e in idx["entries"] if e["group"] == "igp"] == ["https://met.igp.gob.pe/datos/ICEN.txt"]
    assert next(e for e in idx["entries"] if e["group"] == "igp")["file"].endswith(".txt")

    asked.clear()
    idx = _collect(tmp_path, monkeypatch, _peru_only, ALT_REGISTRY, name="otra")
    assert not any("espejo" in u or "avisos.json" in u for u in asked)  # la principal respondió


def _branch_file(bare: Path, name: str) -> bytes:
    import subprocess

    return subprocess.run(["git", "--git-dir", str(bare), "show", f"{pc.BRANCH}:{name}"],
                          capture_output=True, check=True).stdout


def test_last_good_copy_is_kept_when_a_source_fails_tonight(tmp_path, monkeypatch):
    import subprocess

    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    monkeypatch.setenv("ENSO_RELAY_REMOTE", str(bare))
    first = _collect(tmp_path, monkeypatch, _peru_only, name="noche1")
    pc.push(tmp_path / "noche1", "tok")
    good = next(e for e in first["entries"] if e["url"].endswith("aviso-meteorologico"))
    pdf17 = next(e for e in first["entries"] if "n-17-2026/?wpdmdl" in e["url"])

    def peru(req):
        u = str(req.url)
        if "aviso-meteorologico" in u:
            return httpx.Response(200, text=CHALLENGE, headers={"content-type": "text/html"})
        if "enfen.imarpe.gob.pe" in u:  # sin listado: esta noche no se piden los PDF
            raise httpx.ConnectTimeout("timed out")
        return _peru_only(req)

    second = _collect(tmp_path, monkeypatch, peru, name="noche2")
    (tmp_path / "noche2" / pc.HEARTBEAT).write_text(json.dumps(pc.heartbeat(second, "ok")), encoding="utf-8")
    pc.push(tmp_path / "noche2", "tok")
    idx = json.loads(_branch_file(bare, "index.json"))
    kept = next(e for e in idx["entries"] if e["url"] == good["url"])
    assert kept["carried"] is True and kept["fetched_at"] == good["fetched_at"] and kept["file"] == good["file"]
    assert kept["last_attempt"]["class"] == "challenge" and kept["last_attempt"]["status"] == 200
    assert _branch_file(bare, kept["file"]) == (tmp_path / "noche1" / good["file"]).read_bytes()
    doc = next(e for e in idx["entries"] if e["url"] == pdf17["url"])  # no se pidió esta noche
    assert doc["carried"] and doc["last_attempt"] == {"note": "no se pidió esta noche"}
    assert idx["carried"] >= 2 and json.loads(_branch_file(bare, pc.HEARTBEAT))["carried"] == idx["carried"]
    log = subprocess.run(["git", "--git-dir", str(bare), "log", "-1", "--format=%s", pc.BRANCH],
                         capture_output=True, text=True, check=True).stdout
    assert "conservadas" in log
    # El sitio la usa con la fecha de la copia original.
    tree = tmp_path / "rama"
    subprocess.run(["git", "clone", "-q", "--branch", pc.BRANCH, str(bare), str(tree)], check=True)
    r = Relay(tree).get(good["url"])
    assert r is not None and r.archived_at == good["fetched_at"]
    # La medición de esta noche es la antirobots, no la copia conservada.
    from tools import probe_sources

    assert probe_sources.from_peru_index(idx)[good["url"]]["class"] == "challenge"
    assert pdf17["url"] not in probe_sources.from_peru_index(idx)


def test_carried_copies_expire_and_yield_to_another_url_of_the_same_source(tmp_path):
    prev, snap = tmp_path / "prev", tmp_path / "snap"
    (prev / "files").mkdir(parents=True)
    snap.mkdir()
    old_at = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat(timespec="seconds")

    def entry(url, body, **kw):
        sha = __import__("hashlib").sha256(body).hexdigest()
        (prev / f"files/{sha[:16]}.html").write_bytes(body)
        return {"url": url, "status": 200, "file": f"files/{sha[:16]}.html", "sha256": sha, "fetched_at": old_at, **kw}

    old = [entry("https://a.pe/1", b"uno", source="s1"), entry("https://a.pe/2", b"dos", source="s2"),
           entry("https://a.pe/3", b"tres"), {**entry("https://a.pe/4", b"cuatro"), "sha256": "0" * 64}]
    (prev / "index.json").write_text(json.dumps({"schema": "enso-relay/1", "entries": old}), encoding="utf-8")
    tonight = [{"url": "https://a.pe/1", "status": None, "source": "s1", "class": "timeout", "group": "g"},
               {"url": "https://a.pe/1b", "status": 200, "file": "files/x.html", "source": "s1", "group": "g"},
               {"url": "https://a.pe/2", "status": 503, "class": "http-5xx", "source": "s2", "group": "g"},
               {"url": "https://a.pe/3", "status": None, "class": "robots", "skipped": "robots", "group": "g"},
               {"url": "https://a.pe/4", "status": 404, "class": "http-4xx", "group": "g"}]
    (snap / "index.json").write_text(json.dumps({"schema": "enso-relay/1", "entries": tonight}), encoding="utf-8")
    assert pc.carry_forward(snap, prev) == 1  # solo la 2: la 1 respondió por otra URL, robots, sha alterado
    idx = json.loads((snap / "index.json").read_text(encoding="utf-8"))
    assert [e["url"] for e in idx["entries"] if e.get("carried")] == ["https://a.pe/2"]
    later = datetime.now(timezone.utc) + timedelta(hours=pc.CARRY_HOURS)
    (snap / "index.json").write_text(json.dumps({"schema": "enso-relay/1", "entries": tonight}), encoding="utf-8")
    assert pc.carry_forward(snap, prev, now=later) == 0  # más de 72 horas desde la descarga original


def test_registry_origin_and_version_are_logged_and_reported(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ENSO_REGISTRY_FILE")
    monkeypatch.delenv("ENSO_RELAY_REMOTE", raising=False)
    monkeypatch.setattr(pc.httpx, "get", lambda url, **kw: httpx.Response(500, request=httpx.Request("GET", url)))
    reg, info = pc.load_registry_info("github_pat_x")
    assert info["origin"] == "kit" and info["note"] == "GitHub respondió HTTP 500"
    assert info["generated_at"] == reg["generated_at"] and info["sources"] == len(reg["sources"])
    assert "copia del kit" in pc.describe_registry(info) and "HTTP 500" in pc.describe_registry(info)
    _, info = pc.load_registry_info("")
    assert info["note"].startswith("sin token")
    idx = _collect(tmp_path, monkeypatch, _peru_only, budget_min=0)
    assert pc.heartbeat(idx, "ok")["registry"] == idx["registry"]
    assert "registro de fuentes: copia del kit" in capsys.readouterr().out


PROBE_REGISTRY = {
    "schema": "enso-source-registry/1", "generated_at": "2026-10-21T00:00:00+00:00",
    "sources": [
        {"id": "news-indeci-coen", "group": "indeci", "url": "https://portal.indeci.gob.pe/emergencias/feed/?paged=1",
         "expect": "rss", "channels": ["actions", "n8n"], "geoblock": {"status": "unknown"}},
        {"id": "news-andina", "group": "andina", "url": "https://andina.pe/agencia/rss/3.xml",
         "expect": "rss", "channels": ["actions", "n8n"], "geoblock": {"status": "open"}},
        {"id": "plantilla", "group": "x", "url": "https://x.gob.pe/{year}/a.pdf", "channels": ["actions", "n8n"],
         "geoblock": {"status": "unknown"}},
    ],
}


def test_unmeasured_registry_urls_are_measured_from_peru(tmp_path, monkeypatch):
    def peru(req):
        u = str(req.url)
        if u.endswith("/robots.txt"):
            return httpx.Response(404)
        if "indeci" in u:
            return httpx.Response(200, text="<rss><channel><item>sismo</item></channel></rss>")
        return _peru_only(req)

    idx = _collect(tmp_path, monkeypatch, peru, PROBE_REGISTRY)
    coen = PROBE_REGISTRY["sources"][0]["url"]
    assert set(idx["probes"]) == {coen}  # ni la que ya responde desde EE. UU. ni la plantilla
    assert idx["probes"][coen]["class"] == "ok" and idx["probes"][coen]["vantage"] == "peru-server"
    assert coen not in {e["url"] for e in idx["entries"]}  # se mide, no se guarda
    assert pc.heartbeat(idx, "ok")["probes"] == {"ok": 1}
    from enso import registry
    from tools import probe_sources

    got = probe_sources.from_peru_index(idx)
    assert got[coen]["class"] == "ok" and registry.vantage_group(got[coen]["vantage"]) == "peru"
    monkeypatch.setenv("ENSO_PERU_PROBES", "0")
    assert "probes" not in _collect(tmp_path, monkeypatch, peru, PROBE_REGISTRY, name="sin")


def test_dead_servers_and_the_time_budget_end_the_run_early(tmp_path, monkeypatch):
    calls = []

    def peru(req):
        if "senamhi.gob.pe" in req.url.host:
            calls.append(str(req.url))
            raise httpx.ConnectTimeout("timed out")
        return _peru_only(req)

    idx = _collect(tmp_path, monkeypatch, peru)
    www = [e for e in idx["entries"] if e["url"].startswith("https://www.senamhi.gob.pe")]
    # robots.txt no responde: no se pide nada más a ese servidor (RFC 9309 §2.3.1.4), y cada URL
    # queda medida desde el Perú con la clase de ese intento, como en tools.probe_sources.
    assert len(www) == 4 and {e.get("skipped") for e in www} == {"robots-sin-respuesta"}
    assert {e["class"] for e in www} == {"timeout"} and "robots.txt sin respuesta" in www[0]["error"]
    assert [c for c in calls if "www.senamhi" in c] == ["https://www.senamhi.gob.pe/robots.txt"]
    assert {e["url"] for e in www} <= probe_sources_urls(idx)
    assert any(f["class"] == "timeout" and "robots.txt" in f["error"] for f in pc.heartbeat(idx, "ok")["failures"])

    calls.clear()

    def pages_dead(req):
        if req.url.host == "www.senamhi.gob.pe":
            if req.url.path == "/robots.txt":
                return httpx.Response(404)
            calls.append(str(req.url))
            raise httpx.ConnectTimeout("timed out")
        return _peru_only(req)

    idx = _collect(tmp_path, monkeypatch, pages_dead, name="paginas")
    www = [e for e in idx["entries"] if e["url"].startswith("https://www.senamhi.gob.pe")]
    # Tres intentos a la primera URL, uno a la segunda y se omite el resto del servidor.
    assert [e.get("skipped") for e in www] == [None, None, "servidor", "servidor"] and len(calls) == 4
    measured = probe_sources_urls(idx)  # lo omitido no es una medición
    assert {e["url"] for e in www[:2]} <= measured and not any(e["url"] in measured for e in www[2:])
    idx = _collect(tmp_path, monkeypatch, _peru_only, name="sin-plazo", budget_min=0)
    assert idx["entries"] and all(e.get("skipped") == "plazo" for e in idx["entries"] if e["group"] != "enfen-docs")
    assert not any(pc.usable(e) for e in idx["entries"])


def probe_sources_urls(idx: dict) -> set[str]:
    from tools import probe_sources

    return set(probe_sources.from_peru_index(idx))


def test_robots_txt_is_respected_from_peru(tmp_path, monkeypatch):
    asked = []

    def peru(req):
        u = str(req.url)
        asked.append(u)
        if u == "https://www.imarpe.gob.pe/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /imarpe/\n")
        return _peru_only(req)

    idx = _collect(tmp_path, monkeypatch, peru)
    e = next(e for e in idx["entries"] if "id_seccion" in e["url"])
    assert e["class"] == "robots" and e["skipped"] == "robots" and not any("id_seccion" in u for u in asked)
    assert probe_sources_urls(idx) >= {e["url"]}  # el registro la marcará «robots-disallowed»


def test_registry_sources_are_fetched_once_and_enfen_pdfs_are_followed(tmp_path, monkeypatch):
    """Con el registro del repositorio: ninguna URL se pide dos veces (lista fija, registro, documentos
    del ENFEN y enlaces ``follow``) y la regla ``follow`` del ENFEN baja los PDF de la API de WordPress."""
    from collections import Counter

    monkeypatch.setenv("ENSO_REGISTRY_FILE", str(Path(pc.__file__).resolve().parents[2] / "registry" / "sources.json"))
    monkeypatch.setenv("ENSO_PERU_PROBES", "0")
    pdf_up = "https://enfen.imarpe.gob.pe/wp-content/uploads/2026/10/CO-17-2026.pdf"
    dhn17 = "https://www.dhn.mil.pe/Archivos/oceanografia/enfen/comunicado-oficial/17-2026.pdf"
    posts = [{"title": {"rendered": "Comunicado Oficial ENFEN N° 17-2026"}, "date": "2026-10-14T00:00:00",
              "link": "https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-17-2026/",
              "content": {"rendered": f'<p>Comunicado oficial <a href="{pdf_up}">PDF</a> <a href="{dhn17}">DHN</a></p>'}}]
    asked: Counter = Counter()

    def peru(req):
        u = str(req.url)
        if u.endswith("/robots.txt"):
            return httpx.Response(404)
        asked[u] += 1
        if "wp-json" in u:
            return httpx.Response(200, json=posts)
        if u in (pdf_up, dhn17):
            return httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"})
        if u.endswith("/download/comunicado-oficial-enfen-n-17-2026/"):
            return httpx.Response(200, headers={"content-type": "text/html"}, text=(
                '<a href="https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-17-2026/'
                f'?wpdmdl=2161&amp;refresh=x">Descargar</a> <a href="{dhn17}">DHN</a>'))
        return _peru_only(req)

    idx = _collect(tmp_path, monkeypatch, peru)
    assert [u for u, n in asked.items() if n > 1] == []
    linked = [e for e in idx["entries"] if e["group"] == "enlaces"]
    assert [e["url"] for e in linked] == [pdf_up] and pc.usable(linked[0])
    assert linked[0]["parent"] == "https://enfen.imarpe.gob.pe/wp-json/wp/v2/posts?per_page=10&search=comunicado"
    assert any(e["url"] == dhn17 and pc.usable(e) for e in idx["entries"])
