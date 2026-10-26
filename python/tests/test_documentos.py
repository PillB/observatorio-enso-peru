"""Del aviso a su documento: los PDF del COEN (``enso.documentos``) y los lugares de los avisos del SENAMHI
que llegan sin ellos (``sourcefeed._share_places``, ``senamhi_avisos.region_departments``).

Los textos de ``fixtures/documentos`` son lo que pypdf saca de PDF reales del COEN de octubre de 2026 (el
aviso 432 es el que adjuntaron quienes probaron el sitio); los reportes, sus primeras páginas."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from enso import documentos as D
from enso.geo import locate_item
from enso.hazardparse import parse_coen
from enso.news import FEED_BY_ID
from enso.senamhi_avisos import REGION_CONFIDENCE, region_departments, regions_named
from enso.severity import kind_of, validity
from enso.sourcefeed import _share_places, alerts

FIX = Path(__file__).parent / "fixtures" / "documentos"
SOURCES = Path(__file__).parent / "fixtures" / "sources"
NOW = datetime(2026, 10, 26, 14, 30, tzinfo=timezone.utc)


def text(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Lo que dice cada PDF
# ---------------------------------------------------------------------------
def test_aviso_432_lists_the_twenty_exposed_departments():
    # «B. PARA LAS AUTORIDADES Y POBLACIÓN DE LOS DEPARTAMENTOS EXPUESTOS: AMAZONAS, ÁNCASH, … TACNA Y TUMBES.»
    doc = D.read(text("aviso-432.txt"))
    assert doc["codes"] == ["01", "02", "03", "04", "05", "06", "08", "09", "10", "11", "12", "13", "14", "15",
                            "18", "19", "20", "21", "23", "24"]
    assert doc["basis"] == "departamentos expuestos del boletín del COEN"
    assert doc["num"] == 432 and doc["what"] == "PRECIPITACIONES EN LA COSTA NORTE Y SIERRA"
    assert doc["when"] == "DESDE EL VIERNES 23 AL DOMINGO 25 DE OCTUBRE"
    assert doc["body"].startswith("Del viernes 23 al domingo 25 de octubre, se presentarán precipitaciones")
    assert "Recomienda" not in doc["body"] and "Fuente" not in doc["body"]


def test_other_wordings_of_the_department_list():
    # 435: «… DEPARTAMENTOS EXPUESTOS: …»; 440: «… DEPARTAMENTOS DE POSIBLE AFECTACIÓN: ÁNCASH, …,CAJAMARCA,CUSCO, …»
    assert D.read(text("aviso-435.txt"))["codes"] == ["01", "02", "03", "05", "06", "08", "09", "10", "12", "13", "14",
                                                       "19", "20", "21", "22", "24"]
    doc = D.read(text("aviso-440.txt"))
    assert doc["codes"] == ["02", "03", "04", "06", "08", "10", "13", "14", "20", "21", "24"]
    assert doc["num"] == 440 and doc["when"] == "DESDE EL MARTES 27 AL JUEVES 29 DE OCTUBRE"
    # Un nombre que no es un departamento corta la lista; Lima Metropolitana y el Callao se reconocen.
    assert D.listed_departments("DEPARTAMENTOS EXPUESTOS: LIMA METROPOLITANA, CALLAO Y PIURA.") == ["15", "07", "20"]
    assert D.listed_departments("DEPARTAMENTOS EXPUESTOS: PIURA, LA COSTA NORTE.") == ["20"]
    assert D.listed_departments("Sin lista de departamentos.") == []
    # 439: el PDF pega «DEPARTAMENTOSEXPUESTOS».
    assert D.read(text("aviso-439.txt"))["codes"] == ["05", "08", "12", "17", "19", "21", "25"]


def test_short_term_warnings_list_exposed_provinces():
    doc = D.read(text("corto-plazo-lluvias-297.txt"), "Aviso de corto plazo ante lluvias intensas (boletín N° 297 del COEN)")
    assert doc["basis"] == "provincias expuestas del boletín del COEN"
    codes = doc["codes"]
    assert all(len(c) == 4 for c in codes) and len(codes) > 100
    assert {"0201", "0220", "1102", "1201"} <= set(codes)  # Huaraz, Yungay, Chincha (Ica), Huancayo
    assert doc["when"] == "25-10-2026 (13:00 h) al 26-10-2026 (13:00 h)"
    # Esa vigencia, en el resumen, es la que lee el mapa.
    v = validity("indeci-coen-boletines", "Aviso de corto plazo ante lluvias intensas", D.summary(doc), "2026-10-25T20:00:00Z")
    assert v == {"from": "2026-10-25T18:00:00Z", "until": "2026-10-26T18:00:00Z", "basis": "vigencia del boletín del COEN"}
    q = D.read(text("corto-plazo-quebradas-199.txt"), "Aviso de corto plazo ante posible activación de quebradas")
    assert {"0201", "0218"} <= set(q["codes"]) and "Activación de Quebradas" in q["source"]


def test_swell_bulletin_maps_the_coast():
    doc = D.read(text("oleaje-043.txt"), "Aviso especial de oleaje N° 043")
    assert doc["basis"] == "tramos del litoral del boletín de oleajes del COEN"
    assert set(doc["codes"]) == {"24", "20", "14", "13", "02", "15", "07", "11", "04", "18", "23"}
    assert doc["what"] == "OLEAJE DE LIGERA A MODERADA INTENSIDAD PROVENIENTE DEL SUROESTE"  # el RSS lo pega: «DELIGERAA»


def test_emergency_reports_give_the_exact_district():
    # La tabla «UBICACIÓN» sale desordenada del PDF («TALAVERAANDAHUAYLASAPURÍMAC SACHAPUNA»).
    cases = {"reporte-talavera.txt": ["030216"], "reporte-condebamba.txt": ["060203"],
             "reporte-independencia-lima.txt": ["150112"], "reporte-moquegua.txt": ["180101"],
             "reporte-14898-huaraz.txt": ["020101"],
             "reporte-puno.txt": ["210101"]}  # «CHIMUPUNOPUNOPUNO»  # «ÁNCASH HUARAZ HUARAZ VILLÓN»: el distrito, no la provincia
    for name, codes in cases.items():
        assert D.location_rows(text(name)) == codes, name
    # Varios distritos de varias provincias; «PIURA PIURA PIURA» es departamento, provincia y distrito.
    assert D.location_rows(text("reporte-piura-lluvias.txt")) == ["200101", "200104", "200105", "200107", "200115",
                                                                  "200209", "200401"]
    # El pie de página («Chorrillos, Lima – Perú») no es un lugar del reporte.
    assert "15" not in D.location_rows(text("reporte-14898-huaraz.txt"))


def test_region_names_are_no_substitute_for_the_document_but_cover_it():
    # Las regiones de «costa norte y sierra» cubren los departamentos expuestos del PDF del aviso 432 (salvo Ica, por
    # sus zonas altas) y no agregan otros: por eso sirven, marcadas «≈», cuando no hay PDF.
    names, phrase = region_departments("precipitaciones en la costa norte y sierra")
    assert phrase == "en la costa norte y sierra"
    from enso.geo import gazetteer
    gz = gazetteer()
    codes = {gz.find(n, "departamento")[0] for n in names}
    expected = set(D.read(text("aviso-432.txt"))["codes"])
    assert codes <= expected and expected - codes == {"11"}
    assert regions_named("incremento de temperatura en la costa y sierra norte y centro") == [
        ("costa", "norte"), ("costa", "centro"), ("sierra", "norte"), ("sierra", "centro")]
    assert regions_named("lluvia en la selva centro y sur (décimo tercer friaje)") == [("selva", "centro"), ("selva", "sur")]
    assert regions_named("Del 26 al 28 de octubre en Lima Metropolitana") == []


# ---------------------------------------------------------------------------
# De la portada al PDF
# ---------------------------------------------------------------------------
def test_landing_page_gives_the_bulletin_pdf_not_the_footer_one():
    page = text("pagina-aviso-435.html")
    url = D.pdf_link(page, "Aviso meteorológico N° 435 del SENAMHI")
    assert url == ("https://portal.indeci.gob.pe/wp-content/uploads/2026/10/"
                   "BOLETÍN-INFORMATIVO-DE-AVISO-METEOROLÓGICO-N°435-2026-DEL-24-10-2026-1.pdf")
    assert D.safe_url(url).endswith("/BOLET%C3%8DN-INFORMATIVO-DE-AVISO-METEOROL%C3%93GICO-N%C2%B0435-2026-DEL-24-10-2026-1.pdf")
    assert D.pdf_link("<a href='https://www.indeci.gob.pe/nota-de-prensa-n-054-2018-inei.pdf'>x</a>") is None


def _pdf(lines: list[str]) -> bytes:
    """Un PDF mínimo de una página con esas líneas (Helvetica, WinAnsi: admite tildes)."""
    ops = "BT /F1 9 Tf 40 800 Td 11 TL " + " ".join(
        "(" + ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") '" for ln in lines) + " ET"
    stream = ops.encode("cp1252")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)


PAGE = "https://portal.indeci.gob.pe/emergencias/boletin-informativo-de-aviso-meteorologico-n-435-2026-indeci-coen/"
PDF_URL = ("https://portal.indeci.gob.pe/wp-content/uploads/2026/10/"
           "BOLET%C3%8DN-INFORMATIVO-DE-AVISO-METEOROL%C3%93GICO-N%C2%B0435-2026-DEL-24-10-2026-1.pdf")
PDF_435 = _pdf(["B. PARA LAS AUTORIDADES Y POBLACIÓN DE LOS DEPARTAMENTOS EXPUESTOS: AMAZONAS, ÁNCASH, APURÍMAC,",
                "PIURA, PUNO, SAN MARTÍN Y TUMBES.", "Por precipitaciones fuertes:",
                "AVISO N°435: PRECIPITACIONES EN LA COSTA NORTE Y SIERRA", "(EXTENSIÓN DEL AVISO 432)",
                "VIGENCIA: LUNES 26 DE OCTUBRE",
                "Durante el 26 de octubre, continuarán las precipitaciones en la sierra.", "SOLO", "LLUVIA"])


def _coen_item(**kw) -> dict:
    base = {"id": "a435", "feed": "indeci-coen-boletines", "region": "peru", "link": PAGE, "outlet": "INDECI",
            "first_seen": "2026-10-25T04:40:00+00:00", "published": "2026-10-24T23:39:10+00:00",
            "title": "Aviso meteorológico N° 435 del SENAMHI",
            "summary": "BOLETÍN INFORMATIVO DE AVISO METEOROLÓGICO N° 435-2026 Difundido por el COEN del INDECI en su "
                       "boletín informativo de aviso meteorológico.",
            "hazards": ["emergencia"], "relevance": "impacto", "kind": "gobierno"}
    return {**base, **kw}


def test_follow_reads_the_pdf_once_and_apply_locates_the_aviso():
    asked = []

    def fetch(url):
        asked.append(url)
        if url == PAGE:
            return 200, text("pagina-aviso-435.html").encode(), "text/html", ""
        if url == PDF_URL:
            return 200, PDF_435, "application/pdf", ""
        return 404, b"", "", "HTTP 404"

    item = _coen_item()
    old = _coen_item(id="old", link="https://portal.indeci.gob.pe/emergencias/viejo/", published="2026-10-01T00:00:00Z")
    report = _coen_item(id="r", link="https://portal.indeci.gob.pe/emergencias/reporte-x/", title="Incendio forestal en el distrito de Tinta (Cusco)",
                        geo={"places": [{"code": "080608"}]})  # ya tiene su distrito: no se pide
    cache: dict = {}
    stats = D.follow([item, old, report], fetch, cache, FEED_BY_ID, NOW)
    assert stats == {"read": 1, "failed": 0, "pending": 0} and asked == [PAGE, PDF_URL]
    entry = cache[PAGE]
    assert entry["status"] == "ok" and entry["pdf"] == PDF_URL and entry["num"] == 435
    assert entry["codes"] == ["01", "02", "03", "20", "21", "22", "24"]
    # La corrida siguiente parte de lo publicado y no vuelve a pedirlo.
    cache = D.load_cache(json.loads(json.dumps(D.dump_cache(cache, NOW))))
    assert D.follow([item], fetch, cache, FEED_BY_ID, NOW + timedelta(hours=6))["read"] == 0 and len(asked) == 2

    assert D.apply([item], cache) == 1
    assert item["document"] == PDF_URL
    assert item["title"] == ("Aviso meteorológico N° 435 del SENAMHI: precipitaciones en la costa norte y sierra "
                             "(extensión del aviso 432) (vigencia: lunes 26 de octubre)")
    assert item["summary"].startswith("Aviso meteorológico N° 435: Precipitaciones en la costa norte y sierra")
    assert "Según el PDF del COEN (departamentos expuestos del boletín del COEN): Amazonas, Áncash" in item["summary"]
    assert item["summary"].endswith("Difundido por el COEN del INDECI en su boletín informativo de aviso meteorológico.")
    # La ubicación de la siguiente corrida (``geo_overrides.relocate``) sale de esos departamentos.
    g = locate_item({"title": item["title"], "summary": item["summary"], **item["geoHint"]},
                    FEED_BY_ID["indeci-coen-boletines"])
    assert [p["code"] for p in g["places"]] == ["01", "02", "03", "20", "21", "22", "24"]
    assert {p["method"] for p in g["places"]} == {"campo"} and g["confidence"] == 0.95


def test_follow_retries_failures_and_respects_its_budget():
    calls = []

    def down(url):
        calls.append(url)
        return None, b"", "", "ConnectTimeout"

    items = [_coen_item(id=str(n), link=f"{PAGE}{n}/") for n in range(5)]
    cache: dict = {}
    s = D.follow(items, down, cache, FEED_BY_ID, NOW, max_items=3)
    assert s == {"read": 0, "failed": 3, "pending": 2}
    assert cache[f"{PAGE}0/"]["error"] == "página: ConnectTimeout"
    for _ in range(D.MAX_TRIES):
        D.follow(items, down, cache, FEED_BY_ID, NOW)
    n = len(calls)
    assert D.follow(items, down, cache, FEED_BY_ID, NOW) == {"read": 0, "failed": 0, "pending": 0} and len(calls) == n
    # Una página sin PDF, o una descarga que no es un PDF, no rompe nada.
    cache = {}
    D.follow(items[:1], lambda u: (200, b"<html>sin enlaces</html>", "text/html", ""), cache, FEED_BY_ID, NOW)
    assert cache[f"{PAGE}0/"]["status"] == "sin-pdf"
    page = text("pagina-aviso-435.html").encode()
    D.follow(items[1:2], lambda u: (200, page if u.endswith("/") else b"<html>captcha</html>", "", ""), cache, FEED_BY_ID, NOW)
    assert cache[f"{PAGE}1/"] == {**cache[f"{PAGE}1/"], "status": "error", "error": "la descarga no es un PDF legible"}
    assert D.apply(items, cache) == 0 and "document" not in items[0]


def test_apply_publishes_departments_when_a_warning_names_a_hundred_provinces():
    item = _coen_item(title="Aviso de corto plazo ante lluvias intensas (boletín N° 297 del COEN)")
    doc = D.read(text("corto-plazo-lluvias-297.txt"), item["title"])
    D.apply([item], {PAGE: {"status": "ok", "pdf": PDF_URL, **doc}})
    geo = item["geoHint"]["geo"]
    assert len(geo) == len({c[:2] for c in doc["codes"]}) <= 25
    assert all(g.startswith("departamento de ") for g in geo)
    assert "VIGENCIA: 25-10-2026 (13:00 h) al 26-10-2026 (13:00 h)." in item["summary"]
    assert "y " in item["summary"] and "más." in item["summary"]  # nombra 12 provincias y cuenta las demás


# ---------------------------------------------------------------------------
# El feed de boletines del COEN
# ---------------------------------------------------------------------------
def test_bulletin_feed_titles_and_kinds():
    p = parse_coen((SOURCES / "news-indeci-coen-boletines.xml").read_bytes(), FEED_BY_ID["indeci-coen-boletines"].url)
    titles = [i["title"] for i in p.items]
    assert "Aviso meteorológico N° 440 del SENAMHI" in titles
    assert "Aviso de corto plazo ante lluvias intensas (boletín N° 297 del COEN)" in titles
    assert any(t.startswith("Aviso especial de oleaje N° 043: ") for t in titles)
    assert not any("SÍSMICO" in t.upper() or "MONITOREO" in t.upper() for t in titles)
    assert "5 boletines que no son avisos omitidos (sísmicos, monitoreo de peligros)" in p.repairs
    for t in titles:
        assert kind_of("indeci-coen-boletines", t) == "pronostico", t


# ---------------------------------------------------------------------------
# Avisos del SENAMHI sin lugar en el mapa
# ---------------------------------------------------------------------------
def _row(source, title, **kw):
    return {"source": source, "kind": "pronostico", "title": title, "text": "", "url": f"https://x/{title[:8]}",
            "geo": {"scope": "nacional", "places": []}, "where": [], **kw}


def test_telegram_aviso_takes_the_places_of_the_coen_bulletin_of_the_same_aviso():
    coen = _row("news-indeci-coen-boletines", "Aviso meteorológico N° 435 del SENAMHI: precipitaciones",
                document=PDF_URL, aviso={"num": 435, "year": 2026},
                geo={"scope": "nacional", "places": [{"code": "20", "level": "departamento", "name": "Piura",
                                                      "confidence": 0.95, "method": "campo"}], "method": "campo"})
    tg = _row("news-senamhi-telegram", "Aviso del SENAMHI: el 26 de octubre, continuarán las precipitaciones en la costa "
              "norte y sierra.", aviso={"num": 435, "year": 2026})
    other_year = _row("news-senamhi-telegram", "Aviso del SENAMHI: lluvias en la sierra sur.", aviso={"num": 435, "year": 2025})
    no_region = _row("news-senamhi-telegram", "Aviso del SENAMHI: temperaturas altas en Lima Metropolitana.")
    usgs = _row("news-usgs-sismos", "Sismo en la sierra sur", kind="reporte")
    _share_places([tg, coen, other_year, no_region, usgs])
    assert [p["code"] for p in tg["geo"]["places"]] == ["20"] and tg["where"] == ["Piura"]
    assert tg["geo"]["via"] == {"url": coen["url"], "document": PDF_URL,
                                "basis": "departamentos del boletín del COEN del aviso N° 435"}
    # El de otro año no es el mismo aviso: toma las regiones que nombra, como aproximación.
    g = other_year["geo"]
    assert g["method"] == "region" and g["confidence"] == REGION_CONFIDENCE
    assert {p["name"] for p in g["places"]} == {"Ayacucho", "Apurímac", "Cusco", "Arequipa", "Moquegua", "Tacna", "Puno"}
    assert all(p["confidence"] == 0.6 and p["method"] == "region" for p in g["places"])
    assert "«en la sierra sur»" in g["via"]["basis"]
    assert no_region["geo"]["places"] == [] and usgs["geo"]["places"] == []


def test_alerts_prefer_the_newer_copy_of_a_link_and_carry_the_document():
    old = _coen_item(id="old", title="BOLETÍN INFORMATIVO DE OLEAJES N°043-2026-INDECI/COEN", feed="indeci-coen",
                     first_seen="2026-10-25T00:00:00+00:00")
    new = _coen_item(id="new", title="Aviso especial de oleaje N° 043: oleaje ligero", feed="indeci-coen",
                     first_seen="2026-10-26T04:40:00+00:00", document=PDF_URL)
    rows = alerts([old, new], NOW)
    assert len(rows) == 1 and rows[0]["id"] == "alert-new" and rows[0]["document"] == PDF_URL
    assert rows[0]["kind"] == "pronostico"
