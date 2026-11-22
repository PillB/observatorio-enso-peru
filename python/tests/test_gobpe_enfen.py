"""gob.pe como ruta directa de los documentos del ENFEN (``enso.feeds.gobpe_enfen``) y aviso ``listing-stale``.

Caso real (noviembre de 2026): la DHN manda cada ``/Archivos/...pdf`` a ``/human-check.php`` (Cloudflare Turnstile)
y el portal del ENFEN y el repositorio del IMARPE no responden fuera del Perú, así que el comunicado y el informe
técnico dependían solo de la copia del recolector del Perú (hasta 7 días). El SENAMHI publica los mismos PDF en
gob.pe el mismo día, en un CDN público sin verificación: el comunicado 20-2026 y el informe N° 20 de
``cdn.www.gob.pe`` tienen el mismo sha256 que las copias del Perú archivadas en data-archive
(``2026-11-14-ea588516a18f.pdf`` y ``2026-11-15-8eeec2b81028.pdf``).
"""

from __future__ import annotations

import gzip
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from enso import observatory as obs
from enso import reports
from enso.feeds import gobpe_enfen as G
from enso.fetch import Fetcher, FetchError, Response

REP = Path(__file__).parent / "fixtures" / "reports"
RSS = (REP / "gobpe-senamhi-enfen-20261121.xml").read_text(encoding="utf-8")
PDF18 = (REP / "comunicado-enfen-18-2026.pdf").read_bytes()
HUMAN_CHECK = (Path(__file__).parent / "fixtures" / "sources" / "blocked" /
               "dhn-human-check-informe-20-2026.html").read_bytes()
CDN = "https://cdn.www.gob.pe/uploads/document/file"
C18_PDF = f"{CDN}/10811983/8731950-comunicado_of_enfen-n-18-2026.pdf"
I18_PDF = f"{CDN}/10850844/8756067-informe-tecnico-del-enfen-n-18-2026.pdf"
INFORME18 = "https://enfen.imarpe.gob.pe/download/informe-tecnico-enfen-ano-12-n18-al-13-de-octubre-de-2026-2/?wpdmdl=2166"


@pytest.fixture(autouse=True)
def _quiet(monkeypatch, tmp_path):
    import enso.fetch

    monkeypatch.setenv("ENSO_REGISTRY_FILE", str(tmp_path / "sin-registro.json"))
    monkeypatch.setattr(enso.fetch.time, "sleep", lambda s: None)


def _rss(*items: tuple[str, str]) -> str:
    """RSS de la búsqueda de gob.pe con los ítems (título, PDF) dados."""
    body = "".join(f"<item><title>{t}</title><link>https://www.gob.pe/institucion/senamhi/informes-publicaciones/{k}-x"
                   f"</link><pubDate>Fri, 16 Oct 2026 20:00:00 -0500</pubDate><image>{pdf}</image></item>"
                   for k, (t, pdf) in enumerate(items))
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel><title>Gob.pe</title>{body}</channel></rss>'


RSS18 = _rss(("Informe Técnico del ENFEN N°18-2026", I18_PDF), ("Comunicado Oficial ENFEN N°18 - 2026", C18_PDF),
             ("Comunicado Oficial ENFEN N°17 - 2026", f"{CDN}/10703704/8654940-comunicado_of_enfen-n-17-2026.pdf"))


def _offshore(rss: str = RSS18, gob: str = "ok", asked: list | None = None):
    """GitHub Actions hoy: el ENFEN y el IMARPE no resuelven, la DHN manda los PDF a su verificación humana, gob.pe
    responde (``gob="challenge"``: gob.pe también pide verificación; ``"down"``: no responde)."""
    def handler(req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        if asked is not None:
            asked.append(u)
        host = req.url.host
        if host in ("enfen.imarpe.gob.pe", "repositorio.imarpe.gob.pe"):
            raise httpx.ConnectError("Temporary failure in name resolution")
        if host == "www.dhn.mil.pe":
            if "/Archivos/" in u:
                return httpx.Response(302, headers={"location": "/human-check.php?return=" + req.url.path})
            if "human-check" in u:
                return httpx.Response(200, content=HUMAN_CHECK, headers={"content-type": "text/html"})
            return httpx.Response(404)
        if host.endswith("gob.pe") and gob == "down":
            raise httpx.ConnectError("Connection refused")
        if host.endswith("gob.pe") and gob == "challenge":
            return httpx.Response(200, content=HUMAN_CHECK, headers={"content-type": "text/html"})
        if host == "www.gob.pe" and req.url.path == "/busquedas.rss":
            return httpx.Response(200, text=rss, headers={"content-type": "application/rss+xml"})
        if u == C18_PDF:
            return httpx.Response(200, content=PDF18, headers={"content-type": "application/pdf"})
        if u == I18_PDF:
            return httpx.Response(200, content=b"%PDF-1.7 informe 18", headers={"content-type": "application/pdf"})
        return httpx.Response(404)
    return handler


def _fetcher(**kw) -> Fetcher:
    f = Fetcher(retries=1, polite_delay=0, allow_archive=False)
    f.client = httpx.Client(transport=httpx.MockTransport(_offshore(**kw)))
    return f


class _Log:
    def __init__(self):
        self.events = []

    def add(self, *a):
        self.events.append(a)

    def codes(self):
        return [(e[0], e[3]) for e in self.events]


# --- Lectura del RSS -----------------------------------------------------------------------------------------

def test_parse_listing_real_rss():
    got = G.parse_listing(RSS)
    com = [(i["number"], i["year"]) for i in got if i["kind"] == "comunicado"]
    inf = [(i["number"], i["year"]) for i in got if i["kind"] == "informe"]
    assert com[:4] == [(20, 2026), (19, 2026), (18, 2026), (17, 2026)]
    assert inf[:4] == [(20, 2026), (19, 2026), (18, 2026), (17, 2026)]
    c20 = next(i for i in got if i["kind"] == "comunicado" and i["number"] == 20)
    assert c20["pdf"] == f"{CDN}/10965414/8827660-comunicado-oficial-enfen-n-20-2026.pdf"
    assert c20["page"].startswith("https://www.gob.pe/institucion/senamhi/informes-publicaciones/8827660-")
    assert c20["published"] == "2026-11-13"
    # Los boletines climáticos y las colecciones del SENAMHI no son documentos del ENFEN.
    assert not any("Boletín" in i["title"] or "Climático" in i["title"] for i in got)


@pytest.mark.parametrize("title,kind,ident", [
    ("Comunicado Oficial ENFEN N°20 - 2026", "comunicado", (20, 2026)),
    ("Comunicado Oficial ENFEN N° 01-2026", "comunicado", (1, 2026)),
    ("Comunicado Oficial ENFEN Nº 01-2025", "comunicado", (1, 2025)),
    ("Comunicado ENFEN N° 15 - 2023", "comunicado", (15, 2023)),
    ("Informe Técnico del ENFEN N°20-2026", "informe", (20, 2026)),
    ("Informe Técnico ENFEN Nº11-2024", "informe", (11, 2024)),
    ("Informe Técnico ENFEN N°08 -2024", "informe", (8, 2024)),
    ("Informe Técnico del ENFEN N° 9 - 2023", "informe", (9, 2023)),
])
def test_title_variants(title, kind, ident):
    (got,) = G.parse_listing(_rss((title, f"{CDN}/1/x.pdf")))
    assert (got["kind"], (got["number"], got["year"])) == (kind, ident)


def test_extraordinary_and_non_pdf_images():
    got = G.parse_listing(_rss(("Comunicado Oficial Extraordinario ENFEN N°01-2026", f"{CDN}/1/x.pdf"),
                               ("Comunicado Oficial ENFEN N°18 - 2026", f"{CDN}/2/COM-ENFEN_GOBPE.png.png")))
    assert [(i["number"], i["pdf"]) for i in got] == [(18, None)]  # sin PDF en el RSS: se busca en su página


def test_not_rss_is_a_format_problem():
    with pytest.raises(ValueError):
        G.parse_listing("<html><body>Mantenimiento</body></html>")


# --- Rutas y causas --------------------------------------------------------------------------------------------

def test_communique_pdf_from_gobpe_is_a_mirror_with_its_page():
    f = _fetcher()
    got = G.communique_pdf(f, 2026, 18)
    assert got.body == PDF18 and got.channel == "mirror" and got.url == C18_PDF
    assert got.page.startswith("https://www.gob.pe/institucion/senamhi/")


def test_listing_is_read_once_per_run():
    asked: list = []
    f = Fetcher(retries=1, polite_delay=0, allow_archive=False)
    f.client = httpx.Client(transport=httpx.MockTransport(_offshore(asked=asked)))
    G.communiques(f)
    G.informes(f)
    G.communique_pdf(f, 2026, 17)
    assert sum("busquedas.rss" in u for u in asked) == 1


def test_wrong_attachment_is_not_used():
    """Un ítem «N° 19» con el PDF de otro comunicado (gob.pe ya lo hizo en 2023) no se da por el 19."""
    rss = _rss(("Comunicado Oficial ENFEN N°19 - 2026", C18_PDF))
    problems: list = []
    assert G.communique_pdf(_fetcher(rss=rss), 2026, 19, problems) is None
    assert problems == ["otro documento"]
    log = _Log()
    G.log_problems(log, problems, "los comunicados del ENFEN")
    assert log.codes() == [("warning", "gobpe-format")]


@pytest.mark.parametrize("gob,cause", [("challenge", "verificación antirobots"), ("down", "conexión")])
def test_gobpe_failure_is_logged_with_its_cause(gob, cause):
    problems: list = []
    assert G.communiques(_fetcher(gob=gob), problems=problems) == []
    assert problems == [cause]
    log = _Log()
    G.log_problems(log, problems, "los comunicados del ENFEN")
    assert log.codes() == [("warning", "gobpe-unreachable")] and cause in log.events[0][4]


def test_get_communique_uses_gobpe_when_dhn_asks_for_human_check(monkeypatch):
    from enso import fetch

    monkeypatch.setattr(fetch, "archive_prefix", lambda *a, **k: None)
    item = {"year": 2026, "number": 18, "kind": "oficial", "id": "18-2026",
            "url": f"{obs.peru.DHN_BASE}/Archivos/oceanografia/enfen/comunicado-oficial/18-2026.pdf"}
    got = obs._get_communique(_fetcher(), item, [], [])
    assert got.body == PDF18 and got.attempts[-1]["channel"] == "gob.pe"
    # La DHN quedó anotada como verificación (no se evade), no como PDF.
    assert any(a.get("class") == "challenge" for a in got.attempts)


# --- El recolector del Perú se detuvo hace 4 días ----------------------------------------------------------------

class _Prev:
    def __init__(self, latest=None, informe=None):
        self.latest, self.informe = latest, informe

    def get(self, name, carry=False):
        return {"data": {"latest": self.latest, "informe": self.informe}} if self.latest else None


def _stale_relay_acq(days: float = 4):
    """El listado de la fuente salió de la copia del Perú de hace ``days`` días (lo que hace ``acquire``)."""
    at = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    return obs.Acquired(obs.SOURCE_BY_ID["enfen-comunicados"], ok=True, channel="relay-peru", archived_at=at,
                        data={"listing": [{"year": 2026, "number": 17, "kind": "oficial", "id": "17-2026",
                                           "url": "https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-17-2026/"}]})


PREV17 = {"year": 2026, "number": 17, "id": "17-2026", "status": "Alerta de El Niño Costero", "status_code": "alerta",
          "issued": "2026-10-02", "next_issue": "2026-10-16"}


def test_new_communique_is_read_from_gobpe_without_the_peru_collector(monkeypatch):
    from enso import fetch

    monkeypatch.setattr(fetch, "archive_prefix", lambda *a, **k: None)
    monkeypatch.setattr(obs, "portal_enfen_listing", lambda f, log, seen=None: [])  # DHN sin cambios
    acq, log = _stale_relay_acq(), obs.EventLog()
    obs.enfen_latest(acq, _fetcher(), None, _Prev(PREV17), log, date(2026, 10, 18))
    latest = acq.data["latest"]
    assert latest["id"] == "18-2026" and latest["channel"] == "mirror", [e.message for e in log.events]
    assert latest["issued"] == "2026-10-16" and latest["source"] == C18_PDF
    codes = {e.code for e in log.events}
    assert not codes & {"communique-unread", "listing-stale", "gobpe-unreachable"}


def test_blind_listing_warns_when_only_a_stale_relay_copy_is_left(monkeypatch):
    """Sin gob.pe (verificación) ni la DHN, con la copia del Perú de hace 4 días: el sitio no puede saber si salió un
    comunicado nuevo. Antes de este cambio no había aviso hasta ``official-overdue`` (4 días después de la fecha
    prevista); ahora queda ``listing-stale`` en la misma corrida y la causa de gob.pe."""
    monkeypatch.setattr(obs, "portal_enfen_listing", lambda f, log, seen=None: [])
    acq, log = _stale_relay_acq(), obs.EventLog()
    obs.enfen_latest(acq, _fetcher(gob="challenge"), None, _Prev(PREV17), log, date(2026, 10, 18))
    assert acq.data["latest"]["id"] == "17-2026"
    got = [(e.severity, e.code) for e in log.events]
    assert ("warning", "listing-stale") in got and ("warning", "gobpe-unreachable") in got
    msg = next(e.message for e in log.events if e.code == "listing-stale")
    assert "96 h" in msg or "95 h" in msg


@pytest.mark.parametrize("seen,warn", [
    ([], True),
    ([("relay-peru", (datetime.now(timezone.utc) - timedelta(hours=80)).isoformat())], True),
    ([("relay-peru", (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat())], False),
    ([("relay-peru", (datetime.now(timezone.utc) - timedelta(hours=80)).isoformat()), ("direct", None)], False),
    ([("mirror", None)], False),
    ([("archive", "2026-10-01T00:00:00+00:00")], True),  # el Internet Archive no cuenta como lectura en vivo
])
def test_listing_freshness(seen, warn):
    log = obs.EventLog()
    obs._listing_freshness(seen, log)
    assert any(e.code == "listing-stale" for e in log.events) is warn


# --- Informe técnico --------------------------------------------------------------------------------------------

def _pages18():
    return json.loads(gzip.open(REP / "informe-tecnico-enfen-ano-12-n18-al-13-de-octubre-de-2026.pages.json.gz",
                                "rt").read())["pages"]


def test_informe_from_gobpe_when_portal_dhn_and_relay_fail(monkeypatch):
    pages = _pages18()
    monkeypatch.setattr(reports, "pdf_pages", lambda b: pages)
    latest = {"id": "18-2026", "number": 18, "year": 2026, "issued": "2026-10-16", "informe_url": INFORME18}
    log = _Log()
    res = reports.acquire_informe(latest, _fetcher(), None, log, date(2026, 10, 21))
    assert res["channel"] == "mirror" and res["communique"] == "18-2026" and not res.get("carried")
    assert res["url"] == INFORME18 and res["icenProvisional"]["icen"] == 4.15  # la procedencia sigue siendo el portal
    assert ("warning", "informe-unread") not in log.codes()


def test_informe_without_link_is_picked_from_gobpe_and_validated(monkeypatch):
    pages = _pages18()
    monkeypatch.setattr(reports, "pdf_pages", lambda b: pages)
    latest = {"id": "18-2026", "number": 18, "year": 2026, "issued": "2026-10-16", "informe_url": None}
    res = reports.acquire_informe(latest, _fetcher(), None, _Log(), date(2026, 10, 21))
    assert res["number"] == 18 and res["url"] == I18_PDF and res["channel"] == "mirror"


def test_informe_keeps_the_last_one_and_says_why_when_gobpe_also_fails(monkeypatch):
    monkeypatch.setattr(reports, "pdf_pages", lambda b: pytest.fail("no hay PDF que leer"))
    prev = {"number": 17, "communique": "17-2026", "url": "u17", "icenProvisional": {"period": "2026-08", "icen": 3.97}}
    latest = {"id": "18-2026", "number": 18, "year": 2026, "issued": "2026-10-16", "informe_url": INFORME18}
    log = _Log()
    res = reports.acquire_informe(latest, _fetcher(gob="challenge"), prev, log, date(2026, 10, 21))
    assert res["carried"] and res["icenProvisional"]["icen"] == 3.97
    assert ("warning", "informe-unread") in log.codes() and ("warning", "gobpe-unreachable") in log.codes()


def _fetcher_with_dhn_listing(*numbers: int, **kw) -> Fetcher:
    """Como ``_fetcher``, pero la página de informes de la réplica de la DHN (que Actions sí lee) lista ``numbers``."""
    base = _offshore(**kw)
    page = "".join(f'<a href="/Archivos/oceanografia/enfen/informe-tecnico/{n:02d}-2026.pdf">N° {n}</a>' for n in numbers)

    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url) == reports.DHN_INFORMES_PAGE:
            return httpx.Response(200, text=f"<html><body>{page}</body></html>", headers={"content-type": "text/html"})
        return base(req)
    f = Fetcher(retries=1, polite_delay=0, allow_archive=False)
    f.client = httpx.Client(transport=httpx.MockTransport(handler))
    return f


def test_informe_without_link_a_lagging_gobpe_does_not_pick_the_previous_one(monkeypatch):
    # El comunicado 19 no enlaza su informe; la DHN ya lista el N° 19 y gob.pe todavía solo el N° 18 (el SENAMHI lo
    # sube después): se busca el 19, no se elige el 18 de gob.pe para descartarlo luego por el periodo.
    asked = []
    monkeypatch.setattr(reports, "_informe_pdf", lambda f, url, *a, **k: asked.append(url))
    latest = {"id": "19-2026", "number": 19, "year": 2026, "issued": "2026-10-30", "informe_url": None}
    reports.acquire_informe(latest, _fetcher_with_dhn_listing(17, 18, 19), None, _Log(), date(2026, 10, 31))
    assert asked == [reports.DHN_INFORME.format(n=19, year=2026)]


def test_informe_without_link_same_number_keeps_the_dhn_url_and_reads_gobpe(monkeypatch):
    pages = _pages18()
    monkeypatch.setattr(reports, "pdf_pages", lambda b: pages)
    latest = {"id": "18-2026", "number": 18, "year": 2026, "issued": "2026-10-16", "informe_url": None}
    res = reports.acquire_informe(latest, _fetcher_with_dhn_listing(17, 18), None, _Log(), date(2026, 10, 21))
    assert res["url"] == reports.DHN_INFORME.format(n=18, year=2026) and res["channel"] == "mirror"
    assert res["number"] == 18 and not res.get("carried")
