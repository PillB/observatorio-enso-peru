"""Repositorio del IMARPE (DSpace 8): búsqueda, archivos, validación del PDF y su uso como ruta del ENFEN."""

import json
import ssl
from urllib.parse import parse_qs, urlparse

from enso import fetch
from enso.feeds import imarpe_repo as R

C18 = "a1b2c3d4-0000-0000-0000-000000000018"
I18 = "e5f6a7b8-0000-0000-0000-000000000018"
C18_PDF = f"{R.API}/core/bitstreams/c18/content"
I18_PDF = f"{R.API}/core/bitstreams/i18/content"


def _item(uuid, title, issued, handle):
    return {"_embedded": {"indexableObject": {
        "uuid": uuid, "handle": handle,
        "metadata": {"dc.title": [{"value": title}], "dc.date.issued": [{"value": issued}]}}}}


def _search(*items):
    return json.dumps({"_embedded": {"searchResult": {"_embedded": {"objects": list(items)}}}}).encode()


def _bundles(*files, bundle="ORIGINAL"):
    bits = [{"name": n, "sizeBytes": 1000, "_links": {"content": {"href": u}}} for n, u in files]
    return json.dumps({"_embedded": {"bundles": [
        {"name": "THUMBNAIL", "_embedded": {"bitstreams": {"_embedded": {"bitstreams": [
            {"name": "x.jpg", "_links": {"content": {"href": "thumb"}}}]}}}},
        {"name": bundle, "_embedded": {"bitstreams": {"_embedded": {"bitstreams": bits}}}},
    ]}}).encode()


SEARCH_C = _search(_item(C18, "Comunicado Oficial ENFEN N° 18-2026", "2026-10-16", "20.500.12958/5001"),
                   _item("other", "Comunicado Oficial ENFEN N° 17-2026", "2026-10-02", "20.500.12958/5000"),
                   _item("noise", "Boletín del ENFEN", "2026-10-01", None))
SEARCH_I = _search(_item(I18, "Informe Técnico ENFEN Año 12 N°18, 2026", "2026-10-16", "20.500.12958/5002"))


class _Fetcher:
    """Responde según la ruta y la búsqueda (``query``) de la URL."""

    def __init__(self, routes: dict):
        self.routes, self.asked = routes, []

    def get(self, urls, **kw):
        from enso.fetch import FetchError, Response

        for u in urls:
            self.asked.append(u)
            p = urlparse(u)
            key = p.path + ("?" + parse_qs(p.query)["query"][0].split('"')[1] if "query=" in p.query else "")
            for k, body in self.routes.items():
                if k == u or k == key:
                    return Response(u, body, "direct", 200)
        raise FetchError("sin respuesta", [])


def _routes(pdf=b"%PDF-1.7 c18"):
    return {
        "/server/api/discover/search/objects?Comunicado Oficial ENFEN": SEARCH_C,
        "/server/api/discover/search/objects?Informe Técnico ENFEN": SEARCH_I,
        f"/server/api/core/items/{C18}/bundles": _bundles(("Comunicado Oficial ENFEN N 18-2026.pdf", C18_PDF)),
        f"/server/api/core/items/{I18}/bundles": _bundles(
            ("Informe Tecnico ENFEN Año 12 N°18 al 13 octubre 2026.pdf", I18_PDF)),
        C18_PDF: pdf,
        I18_PDF: b"%PDF-1.7 i18",
    }


def test_search_reads_items_and_builds_pages():
    got = R.search(_Fetcher(_routes()), '"Comunicado Oficial ENFEN"')
    assert [g["uuid"] for g in got] == [C18, "other", "noise"]
    assert got[0]["page"] == f"{R.BASE}/handle/20.500.12958/5001" and got[0]["issued"] == "2026-10-16"
    assert got[2]["page"] == f"{R.BASE}/items/noise"


def test_search_and_pdfs_survive_odd_json():
    f = _Fetcher({"/server/api/discover/search/objects?Comunicado Oficial ENFEN": b"[]",
                  f"/server/api/core/items/{C18}/bundles": b"<html>error</html>"})
    assert R.search(f, '"Comunicado Oficial ENFEN"') == [] and R.pdfs(f, C18) == []


def test_pdfs_only_original_bundle_and_pdf_files():
    f = _Fetcher({f"/server/api/core/items/{C18}/bundles": _bundles(("a.pdf", "u1"), ("b.docx", "u2"))})
    assert R.pdfs(f, C18) == [{"name": "a.pdf", "size": 1000, "url": "u1"}]


def test_communiques_listing_format():
    got = R.communiques(_Fetcher(_routes()))
    assert [(c["year"], c["number"], c["id"]) for c in got] == [(2026, 18, "18-2026"), (2026, 17, "17-2026")]
    assert got[0]["kind"] == "oficial" and got[0]["repository"] == C18


def test_communique_pdf_exact_number_and_channel():
    got = R.communique_pdf(_Fetcher(_routes()), 2026, 18)
    assert got.body.startswith(b"%PDF-") and got.channel == "mirror" and got.url == C18_PDF
    # El 19 no está depositado: la búsqueda devuelve el 18 y el 17, y ninguno es el pedido.
    assert R.communique_pdf(_Fetcher(_routes()), 2026, 19) is None


def test_fetch_pdf_rejects_non_pdf():
    assert R.communique_pdf(_Fetcher(_routes(pdf=b"<html>login</html>")), 2026, 18) is None


def test_informes_take_data_to_from_file_name():
    got = R.informes(_Fetcher(_routes()))
    assert got == [{"url": I18_PDF, "year": 2026, "n": 18, "dataTo": "2026-10-13",
                    "page": f"{R.BASE}/handle/20.500.12958/5002"}]
    assert R.informe_pdf(_Fetcher(_routes()), 2026, 18).body == b"%PDF-1.7 i18"
    assert R.informe_pdf(_Fetcher(_routes()), 2026, 17) is None


def test_data_to_variants():
    assert R._data_to("Informe Tecnico ENFEN Año 12 N°18 al 13 octubre 2026.pdf") == "2026-10-13"
    assert R._data_to("Informe ENFEN al 2 de setiembre de 2026.pdf") == "2026-09-02"
    assert R._data_to("Informe ENFEN al 31 febrero 2026.pdf") is None
    assert R._data_to("Informe ENFEN N°18.pdf") is None


def test_ssl_context_loads_the_bundled_intermediate():
    assert fetch.INTERMEDIATES.exists() and "BEGIN CERTIFICATE" in fetch.INTERMEDIATES.read_text()
    ctx = fetch.ssl_context()
    assert isinstance(ctx, ssl.SSLContext) and ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    subjects = [dict(x[0] for x in c["subject"]).get("commonName") for c in ctx.get_ca_certs()]
    assert "Sectigo Public Server Authentication CA DV R36" in subjects


def test_communique_falls_back_to_the_repository(monkeypatch):
    from enso import observatory as O

    monkeypatch.setattr(fetch, "archive_prefix", lambda *a, **k: None)
    item = {"year": 2026, "number": 18, "kind": "oficial", "id": "18-2026",
            "url": "https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-18-2026/"}
    got = O._get_communique(_Fetcher(_routes()), item)
    assert got.body == b"%PDF-1.7 c18" and got.attempts[-1]["channel"] == "repositorio IMARPE"
