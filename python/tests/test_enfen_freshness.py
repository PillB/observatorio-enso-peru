"""El estado del ENFEN sigue al último comunicado aunque la API de WordPress se quede atrás.

Caso real (21-10-2026): la API devolvía como más reciente el comunicado N° 13-2026 (julio), porque desde el
N° 14 el ENFEN publica los comunicados solo como PDF en el listado del portal; el sitio mostraba el estado,
el resumen y la fecha del próximo comunicado de julio. Además, el PDF del N° 18 no se podía bajar: su
cabecera Content-Disposition trae «N°» y la respuesta no se podía rearmar.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pytest

from enso import observatory as obs
from enso.fetch import Fetcher, Response

REP = Path(__file__).parent / "fixtures" / "reports"
WP = (REP / "enfen-wp-posts-20261021.json").read_text(encoding="utf-8")
LISTING = (REP / "enfen-comunicados-20261021.html").read_text(encoding="utf-8")
PDF18 = (REP / "comunicado-enfen-18-2026.pdf").read_bytes()
WP_URL = obs.SOURCE_BY_ID["enfen-comunicados"].urls[0]


@pytest.fixture(autouse=True)
def _quiet(monkeypatch, tmp_path):
    import enso.fetch

    monkeypatch.setenv("ENSO_REGISTRY_FILE", str(tmp_path / "sin-registro.json"))
    monkeypatch.setattr(enso.fetch.time, "sleep", lambda s: None)


def _net(asked: list):
    def handler(req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        asked.append(u)
        if "wp-json" in u:
            return httpx.Response(200, text=WP, headers={"content-type": "application/json"})
        if u.rstrip("/").endswith("/comunicados"):
            return httpx.Response(200, text=LISTING, headers={"content-type": "text/html"})
        if "comunicado-oficial-enfen-n-18-2026" in u and "wpdmdl=" in u:
            # Cabecera real del portal, con «°» fuera de ASCII.
            return httpx.Response(200, content=PDF18, headers=[
                (b"content-type", b"application/pdf"),
                (b"content-disposition", 'attachment; filename="Comunicado Oficial N°18-2026.pdf"'.encode("utf-8"))])
        return httpx.Response(404)
    return handler


class _Prev:
    def __init__(self, latest=None):
        self.latest = latest

    def get(self, name):
        return {"data": {"latest": self.latest}} if self.latest else None


def _acquire_from_wp():
    acq = obs.Acquired(obs.SOURCE_BY_ID["enfen-comunicados"])
    parsed = obs._parse_enfen(Response(WP_URL, WP.encode("utf-8"), "direct", 200))
    acq.data, acq.ok, acq.url, acq.channel = parsed.data, True, WP_URL, "direct"
    return acq, parsed


def test_wp_entry_keeps_its_publication_date():
    _, parsed = _acquire_from_wp()
    latest = parsed.data["latest"]
    assert latest["id"] == "13-2026" and latest["issued"] == "2026-07-17"
    assert not any("fecha de emisión" in w for w in parsed.warnings)
    assert all("text" not in i for i in parsed.data["listing"])  # el texto completo no se publica


def test_stale_wp_api_is_checked_against_the_portal_listing():
    asked: list = []
    acq, _ = _acquire_from_wp()
    f = Fetcher(retries=1, polite_delay=0, allow_archive=False, max_seconds=60)  # pedido por partes, como en el pipeline
    f.client = httpx.Client(transport=httpx.MockTransport(_net(asked)))
    log = obs.EventLog()
    obs.enfen_latest(acq, f, None, _Prev(None), log, date(2026, 10, 21))
    latest = acq.data["latest"]
    assert latest["id"] == "18-2026", [e.message for e in log.events]
    assert latest["issued"] == "2026-10-16" and latest["next_issue"] == "2026-10-30"
    assert acq.data["listing"][0]["id"] == "18-2026"
    assert not any(e.code == "communique-unread" for e in log.events)


def test_communique_already_read_is_not_downloaded_again():
    asked: list = []
    acq, _ = _acquire_from_wp()
    prev = {"year": 2026, "number": 18, "id": "18-2026", "status": "Alerta de El Niño Costero"}
    f = Fetcher(retries=1, polite_delay=0, allow_archive=False)
    f.client = httpx.Client(transport=httpx.MockTransport(_net(asked)))
    obs.enfen_latest(acq, f, None, _Prev(prev), obs.EventLog(), date(2026, 10, 21))
    assert acq.data["latest"] == prev
    assert not any("wpdmdl=" in u for u in asked)


def test_probes_continue_while_communiques_keep_appearing():
    """Si el listado se atrasó varios números, los sondeos siguen hasta el último publicado."""
    asked: list = []

    def handler(req):
        u = str(req.url)
        asked.append(u)
        for n in (14, 15, 16):
            if f"comunicado-oficial-enfen-n-{n}-2026/" in u and "wpdmdl" not in u:
                return httpx.Response(200, text=f'<a href="https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-{n}-2026/?wpdmdl=9{n}">x</a>',
                                      headers={"content-type": "text/html"})
        return httpx.Response(404)

    acq, _ = _acquire_from_wp()
    acq.url = "https://example.invalid/listado"  # sin API: no se contrasta con el portal
    f = Fetcher(retries=1, polite_delay=0, allow_archive=False)
    f.client = httpx.Client(transport=httpx.MockTransport(handler))
    obs.enfen_latest(acq, f, None, _Prev(None), obs.EventLog(), date(2026, 10, 21))
    assert [i["id"] for i in acq.data["listing"][:3]] == ["16-2026", "15-2026", "14-2026"]
    assert any("n-18-2026" in u for u in asked) and not any("n-19-2026" in u for u in asked)


def test_merge_prefers_the_pdf_link():
    wp = [{"year": 2026, "number": 13, "id": "13-2026", "url": "https://enfen.imarpe.gob.pe/2026/07/17/x/"}]
    portal = [{"year": 2026, "number": 13, "kind": "oficial", "id": "13-2026",
               "url": "https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-13-2026/?wpdmdl=1"},
              {"year": 2026, "number": 18, "kind": "oficial", "id": "18-2026",
               "url": "https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-18-2026/?wpdmdl=2"}]
    out = obs.merge_enfen_listings(wp, portal)
    assert [i["id"] for i in out] == ["18-2026", "13-2026"]
    assert "wpdmdl=1" in out[1]["url"]


def test_non_ascii_header_survives_the_streamed_request():
    f = Fetcher(retries=1, polite_delay=0, allow_archive=False, max_seconds=60)
    f.client = httpx.Client(transport=httpx.MockTransport(_net([])))
    r = f.get(["https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-18-2026/?wpdmdl=2165"],
              archive=False, accept=("pdf",))
    assert r.body[:5] == b"%PDF-"
