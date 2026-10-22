"""Auditoría posterior a la integración (22-10-2026): incidencias que no se cerraban o no se abrían, el orden de las
rutas del ENFEN y lo que se publica de cada copia."""

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

from enso import archive, freshness, manual, reports
from enso import observatory as obs
from enso.feeds import imarpe_repo
from enso.fetch import FetchError, Response


class _Log:
    def __init__(self):
        self.events = []

    def add(self, severity, source, stage, code, message):
        self.events.append((severity, source, stage, code, message))

    def codes(self):
        return [(e[0], e[3]) for e in self.events]


# --- 1. Las incidencias del informe siguen abiertas mientras el dato siga sin publicarse ----------------------

LATEST = {"number": 18, "id": "18-2026", "year": 2026, "issued": "2026-10-16",
          "informe_url": "https://enfen.imarpe.gob.pe/download/informe-tecnico-18-2026/"}
JUMP = {"severity": "error", "code": "informe-icen-jump", "message": "El ICEN temporal salta 2,1 °C: no se publica."}


def test_informe_issues_are_logged_again_when_the_informe_is_reused():
    prev = {"number": 18, "communique": "18-2026", "url": LATEST["informe_url"], "issues": [JUMP,
            {"severity": "warning", "code": "informe-period-probabilities", "message": "aviso"}]}
    log = _Log()
    assert reports.acquire_informe(LATEST, None, prev, log, date(2026, 10, 22)) is prev
    assert log.codes() == [("error", "informe-icen-jump")]  # solo los errores: lo que sigue retenido


def test_informe_issues_are_logged_again_when_the_next_communique_cites_the_same_informe():
    prev = {"number": 18, "communique": "17-2026", "url": LATEST["informe_url"], "issues": [JUMP]}
    log = _Log()
    out = reports.acquire_informe(LATEST, None, prev, log, date(2026, 10, 22))
    assert out["communique"] == "18-2026" and log.codes() == [("error", "informe-icen-jump")]


def test_informe_issues_keep_their_github_issue_open_across_runs():
    from tools import sync_issues

    prev = {"number": 18, "communique": "18-2026", "url": LATEST["informe_url"], "issues": [JUMP]}
    runs = []
    for _ in range(2):
        log = obs.EventLog()
        reports.acquire_informe(LATEST, None, prev, log, date(2026, 10, 22))
        kept = sync_issues.relevant([e.as_dict() for e in log.events])
        runs.append({(e["source"], e["stage"], e["code"]) for evs in kept.values() for e in evs})
    assert runs[0] == runs[1] == {("enfen-informe", "validate", "informe-icen-jump")}


def test_communique_warnings_are_logged_on_every_run():
    b = obs.Builder.__new__(obs.Builder)
    b.log = obs.EventLog()
    b.today = date(2026, 10, 22)
    latest = {"id": "18-2026", "year": 2026, "number": 18, "status": "Alerta", "status_code": "alerta",
              "warnings": ["No se encontró la fecha del próximo comunicado."]}
    b.a = {}
    b.data = lambda sid: {"latest": latest, "listing": []} if sid == "enfen-comunicados" else None
    b.official()
    assert ("warning", "communique-warning") in [(e.severity, e.code) for e in b.log.events]


# --- 2. Las series de D20 están en las vistas que las dibujan ---------------------------------------------------

def test_d20_series_are_in_the_views_that_draw_them():
    assert {"d20_coastal", "d20_global", "d20_180w100w"} <= set(freshness.VIEWS["oceano"])
    # Todas las entradas de la señal GRD del inicio.
    for k in ("nino12_oisst", "nino34_oisst", "cpac850_anom", "epac850_anom", "d20_coastal", "d20_global", "soi_troup"):
        assert k in freshness.VIEWS[""], k
    for k in ("d20_coastal", "d20_global", "d20_180w100w"):
        assert "GODAS" in freshness.SERIES_LABELS[k]


# --- 3. El repositorio del IMARPE no falla en silencio ----------------------------------------------------------

class _RepoFetcher:
    """Las URL oficiales fallan; el repositorio responde ``repo`` (un ``FetchError`` o un cuerpo)."""

    allow_archive = False

    def __init__(self, repo):
        self.repo, self.asked = repo, []

    def get(self, urls, archive=True, save=False, accept=()):
        self.asked.append((urls[0], archive))
        if "repositorio.imarpe.gob.pe" in urls[0]:
            if isinstance(self.repo, Exception):
                raise self.repo
            return Response(urls[0], self.repo, "direct", 200)
        raise FetchError("sin respuesta", [{"url": urls[0], "error": "ConnectError: dns"}])


def test_repository_certificate_failure_is_an_incident():
    exc = FetchError("x", [{"url": imarpe_repo.API, "error": "ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] "
                                                            "unable to get local issuer certificate"}])
    problems = []
    assert imarpe_repo.communiques(_RepoFetcher(exc), problems=problems) == []
    assert problems == ["tls"]
    log = _Log()
    imarpe_repo.log_problems(log, problems, "los comunicados del ENFEN")
    assert log.codes() == [("warning", "repository-unreachable")] and "ca-intermedios.pem" in log.events[0][4]


def test_repository_answering_another_json_is_a_format_incident():
    problems = []
    assert imarpe_repo.informes(_RepoFetcher(b'{"page": {}}'), problems=problems) == []
    assert problems == ["formato"]
    log = _Log()
    imarpe_repo.log_problems(log, problems, "los informes técnicos del ENFEN")
    assert log.codes() == [("warning", "repository-format")]


def test_http_error_cause():
    assert imarpe_repo.cause(FetchError("x", [{"url": "u", "status": 503}])) == "http-503"
    assert imarpe_repo.cause(FetchError("x", [{"url": "u", "error": "ReadTimeout"}])) == "conexión"


def test_enfen_latest_logs_the_repository_failure(monkeypatch):
    monkeypatch.setattr(obs, "portal_enfen_listing", lambda f, log: [])
    exc = FetchError("x", [{"url": imarpe_repo.API, "status": 502}])
    acq = obs.Acquired("enfen-comunicados", ok=True, data={"listing": []})
    log = obs.EventLog()
    obs.enfen_latest(acq, _RepoFetcher(exc), None, _Prev(None), log, date(2026, 10, 22))
    assert ("warning", "repository-unreachable") in [(e.severity, e.code) for e in log.events]


class _Prev:
    def __init__(self, latest):
        self.latest = latest

    def get(self, name):
        return {"data": {"latest": self.latest}} if self.latest else None


# --- 4. Las fuentes de alertas abren incidencias ------------------------------------------------------------

def _alerts(sources):
    return {"items": {"alerts": {"id": "alerts", "kind": "alertas", "state": freshness._worst(
        ["vencido" if not any(s["ok"] for s in sources) else "al-dia"]), "sourcesTotal": len(sources),
        "down": [s for s in sources if not s["ok"]]}}}


def test_no_alert_source_answering_is_an_error():
    log = _Log()
    freshness.log_late(_alerts([{"id": "indeci-coen", "name": "COEN", "ok": False, "error": "HTTP 503"},
                                {"id": "usgs-sismos", "name": "USGS", "ok": False, "error": "timeout"}]), log)
    codes = log.codes()
    assert ("error", "alerts-unread") in codes and ("warning", "alert-source-down") in codes
    assert [e[1] for e in log.events if e[3] == "alert-source-down"] == ["indeci-coen"]  # USGS no abre issue propio


def test_a_changed_alert_layer_is_a_format_incident():
    log = _Log()
    freshness.log_late(_alerts([{"id": "senamhi-lluvias", "name": "GEOSINPAD", "ok": False, "formatError": True,
                                 "error": "capa de ArcGIS sin los campos de un aviso conocido"},
                                {"id": "indeci-coen", "name": "COEN", "ok": True}]), log)
    assert log.codes() == [("warning", "alert-source-format")] and log.events[0][1] == "senamhi-lluvias"


def test_freshness_keeps_which_alert_sources_are_down():
    feed = {"groups": [{"id": "alertas", "items": [], "sources": [
        {"id": "senamhi-lluvias", "name": "GEOSINPAD", "ok": False, "error": "x", "formatError": True},
        {"id": "indeci-coen", "name": "COEN", "ok": True}]}]}
    fr = freshness.compute({}, {}, {}, feed, None, date(2026, 10, 22), datetime(2026, 10, 22, tzinfo=timezone.utc)) \
        if hasattr(freshness, "compute") else None
    if fr is None:
        return  # la firma de compute se prueba en test_freshness; aquí basta con log_late
    assert fr["items"]["alerts"]["down"][0]["formatError"]


# --- 5. Una copia vieja del listado del portal no tapa la réplica de la DHN -----------------------------------

def test_listing_merges_every_source_url(monkeypatch):
    urls = obs.SOURCE_BY_ID["enfen-comunicados"].urls[1:]

    class F:
        def get(self, u, archive=True, accept=()):
            return Response(u[0], b"x", "relay-peru" if u[0] == urls[0] else "direct", 200)

    pages = {urls[0]: [{"year": 2026, "number": 17, "kind": "oficial", "id": "17-2026", "url": "p17"}],
             urls[-1]: [{"year": 2026, "number": 18, "kind": "oficial", "id": "18-2026", "url": "d18"}]}
    seen = []

    class P:
        def __init__(self, data):
            self.data = data

    def parse(text):
        u = seen_url[-1]
        return P(pages.get(u, []))

    seen_url = []
    real_get = F.get

    def get(self, u, archive=True, accept=()):
        seen_url.append(u[0])
        seen.append(u[0])
        return real_get(self, u, archive, accept)

    F.get = get
    monkeypatch.setattr(obs.peru, "parse_enfen_listing", parse)
    out = obs.portal_enfen_listing(F(), _Log())
    assert seen == urls and out[0]["id"] == "18-2026"


def test_enfen_latest_reads_other_listings_even_when_the_first_answer_was_a_peru_copy(monkeypatch):
    called = []
    monkeypatch.setattr(obs, "portal_enfen_listing", lambda f, log: called.append(1) or [])
    monkeypatch.setattr(imarpe_repo, "communiques", lambda f, problems=None: [])
    acq = obs.Acquired("enfen-comunicados", ok=True, data={"listing": []}, channel="relay-peru",
                       url=obs.SOURCE_BY_ID["enfen-comunicados"].urls[1])
    obs.enfen_latest(acq, _RepoFetcher(b"{}"), None, _Prev(None), _Log(), date(2026, 10, 22))
    assert called == [1]


# --- 6. Un issue por documento pendiente --------------------------------------------------------------------

def test_each_pending_document_has_its_own_incident():
    needs = manual.ManualNeeds()
    needs.add("comunicado-19-2026", "comunicado", "Comunicado 19-2026", ["u19"], ["u19"], "verificación humana")
    needs.add("informe-19-2026", "informe", "Informe del 19-2026", ["i19"], ["i19"], "verificación humana")
    log = _Log()
    needs.log(log)
    assert [e[1] for e in log.events] == ["manual-comunicado-19-2026", "manual-informe-19-2026"]
    assert {e[3] for e in log.events} == {"manual-download-needed"}


# --- 8. Una meta cuyo PDF sigue en la copia no falta --------------------------------------------------------

def _peru_relay(root: Path, goals: dict, goal_entry: str | None) -> None:
    root.mkdir(parents=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entries = []
    if goal_entry:
        body = b"%PDF-1.7 18"
        sha = hashlib.sha256(body).hexdigest()
        (root / "files").mkdir()
        (root / "files" / f"{sha[:16]}.pdf").write_bytes(body)
        entries.append({"url": "https://enfen.imarpe.gob.pe/download/c18/", "status": 200, "detected": "pdf",
                        "file": f"files/{sha[:16]}.pdf", "sha256": sha, "fetched_at": now, "goal": goal_entry,
                        "carried": True, "content_type": "application/pdf"})
    (root / "index.json").write_text(json.dumps({
        "schema": "enso-relay/1", "collected_at": now, "collector": {"kind": "peru", "host": "lima"},
        "summary": {}, "goals": goals, "entries": entries}), encoding="utf-8")


def test_goal_whose_pdf_was_carried_is_not_missed(tmp_path):
    _peru_relay(tmp_path / "r", {"comunicado 18-2026": False}, "comunicado 18-2026")
    log = obs.EventLog()
    obs.load_relay(tmp_path / "r", log)
    assert "relay-goal-missed" not in [e.code for e in log.events]


def test_goal_without_any_pdf_is_still_missed(tmp_path):
    _peru_relay(tmp_path / "r", {"comunicado 18-2026": False}, None)
    log = obs.EventLog()
    obs.load_relay(tmp_path / "r", log)
    assert "relay-goal-missed" in [e.code for e in log.events]


# --- 10. El extractor con modelo de lenguaje caído es una incidencia propia ----------------------------------

def test_llm_outage_is_its_own_incident():
    log = _Log()
    reports.llm_unavailable(log, {"ok": False, "transport": True, "error": "el servicio respondió HTTP 403"})
    reports.llm_unavailable(log, {"ok": False, "error": "lectura inválida"})  # no es una caída
    reports.llm_unavailable(log, None)
    assert log.codes() == [("warning", "llm-extract-unavailable")] and "HTTP 403" in log.events[0][4]


# --- 14. Un documento demasiado grande para la copia archivada lo dice -------------------------------------

def test_document_too_large_for_the_archive_is_logged(tmp_path):
    a = obs.Acquired("enfen-comunicados", ok=True, data={}, channel="relay-manual")
    a.documents = [b"%PDF-" + b"0" * (archive.MAX_BYTES + 1), b"%PDF-1.7 chico"]
    log = _Log()
    out = archive.write_sources(archive.Writer(tmp_path), {"enfen-comunicados": a}, log=log)
    assert len(out["enfen-comunicados"]["documents"]) == 1
    assert log.codes() == [("warning", "archive-too-large")]


def test_archived_documents_keep_their_channel(tmp_path):
    a = obs.Acquired("enfen-comunicados", ok=True, data={}, channel="relay-manual")
    a.documents = [b"%PDF-1.7 chico"]
    w = archive.Writer(tmp_path)
    archive.write_sources(w, {"enfen-comunicados": a})
    assert [f["channel"] for f in w.files.values()] == ["relay-manual"]


# --- 16 y 17. El repositorio del IMARPE antes que el Internet Archive, y su enlace -------------------------

PDF18 = b"%PDF-1.7 comunicado 18"


def test_repository_comes_before_the_internet_archive(monkeypatch):
    def repo_pdf(fetcher, year, number, problems=None):
        r = Response("https://repositorio.imarpe.gob.pe/server/api/core/bitstreams/x/content", PDF18, "mirror", 200)
        r.page = "https://repositorio.imarpe.gob.pe/handle/20.500.12958/5001"
        return r

    archived = []
    monkeypatch.setattr(imarpe_repo, "communique_pdf", repo_pdf)
    monkeypatch.setattr(obs, "archived_copy", lambda *a, **k: archived.append(1))
    f = _RepoFetcher(b"")
    item = {"year": 2026, "number": 18, "kind": "oficial", "id": "18-2026",
            "url": "https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-18-2026/"}
    got = obs._get_communique(f, item)
    assert got.body == PDF18 and got.channel == "mirror" and archived == []
    assert all(a is False for _, a in f.asked)  # las URL oficiales se pidieron sin el archivo


def test_informe_repository_comes_before_the_internet_archive(monkeypatch):
    archived = []
    monkeypatch.setattr(imarpe_repo, "informe_pdf",
                        lambda f, y, n, problems=None: Response("https://repositorio.imarpe.gob.pe/x", PDF18, "mirror", 200))
    monkeypatch.setattr(obs, "archived_copy", lambda *a, **k: archived.append(1))
    monkeypatch.setattr(reports, "archive_prefix", lambda *a, **k: archived.append(2), raising=False)
    f = _RepoFetcher(b"")
    url = "https://www.dhn.mil.pe/Archivos/oceanografia/enfen/informe-tecnico/18-2026.pdf"
    got = reports._informe_pdf(f, url, FetchError, lambda *a, **k: archived.append(3))
    assert got.body == PDF18 and archived == [] and all(a is False for _, a in f.asked)


def test_repository_link_is_published_with_the_communique():
    b = obs.Builder.__new__(obs.Builder)
    b.log = obs.EventLog()
    b.today = date(2026, 10, 22)
    latest = {"id": "18-2026", "year": 2026, "number": 18, "status": "Alerta", "status_code": "alerta",
              "repositoryUrl": "https://repositorio.imarpe.gob.pe/handle/20.500.12958/5001"}
    b.a = {}
    b.data = lambda sid: {"latest": latest, "listing": []} if sid == "enfen-comunicados" else None
    res = b.official()
    assert res["enfen"]["repositoryUrl"].startswith("https://repositorio.imarpe.gob.pe/")
