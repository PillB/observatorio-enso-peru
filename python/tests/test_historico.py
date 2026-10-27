"""Memoria de desastres: lectores, clasificación, atribución ENSO, catálogo publicado y paridad con el navegador.

Los lectores se prueban con filas reales de cada fuente (``tests/fixtures/historico``: SINPAD, IDMC, NASA, ANA,
INGEMMET, salud 2023, recortadas de las descargas de octubre de 2026). El catálogo publicado
(``public/assets/historico``) se revisa entero.
"""

from __future__ import annotations

import csv
import io
import json
import re
import subprocess
import zipfile
from collections import Counter
from pathlib import Path

import pytest

from conftest import FIX
from enso.historico import desinventar, esquema as E, fuentes as F
from enso.historico.enso import GREAT, PIRCC_2017, EnsoCalendar
from enso.historico.indicadores import rate_ratio, summarize, wilson
from enso.historico.territorio import territory
from test_geo_console import JS, _need_node
from tools import build_historico as B

ROOT = Path(__file__).resolve().parents[2]
HF = Path(__file__).parent / "fixtures" / "historico"
OUT = ROOT / "public" / "assets" / "historico"


@pytest.fixture(scope="module")
def cal() -> EnsoCalendar:
    return EnsoCalendar.from_files(FIX / "igp-icen.txt", FIX / "cpc-oni.txt")


@pytest.fixture(scope="module")
def T():
    return territory()


# ---------------------------------------------------------------------------
# Clasificación
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,cause,expected", [
    (["Desborde del río Piura inunda Catacaos"], "", ("Desborde de rio", "texto")),
    (["Colapso de defensas ribereñas en el sector La Legua"], "", ("Desborde de rio", "texto")),
    (["Crecida de la quebrada afecta viviendas"], "", ("Inundacion fluvial", "texto")),
    (["Lluvias intensas ocasionan inundación en vivienda"], "", ("Inundacion pluvial", "texto")),
    (["Inundación en el distrito de Pólvora"], "", ("Inundacion", "por-omision")),
    (["Inundación en el caserío"], "Desbordamiento", ("Desborde de rio", "causa")),
])
def test_classify_flood(text, cause, expected):
    assert E.classify_flood(text, cause) == expected


def test_danger_types_have_group_and_irdr_code():
    for dt, (group, code) in E.DANGER_TYPES.items():
        assert group and (code.startswith(("HY", "MET", "CLI", "BIO"))), dt
    assert E.COLUMNS[:13] == E.TEAM_COLUMNS
    assert len(set(E.COLUMNS)) == len(E.COLUMNS)


def test_desinventar_cite_keeps_the_original():
    assert desinventar.cite("ElC 12.03.98") == "El Comercio 12/03/1998 (cita original: ElC 12.03.98)"
    assert desinventar.cite("INDECI") == "INDECI"


def test_territory_resolves_codes_names_and_legacy(T):
    assert T.resolve("Piura", "Piura", "Catacaos") == "200105"
    assert T.resolve("LAMBAYEQUE", "CHICLAYO", "JOSE LEONARDO ORTIZ") == "140105"
    assert T.resolve(code="160109") == "160801"  # Putumayo pasó a su propia provincia
    assert T.resolve("LA LIBERTAD", "STGO. DE CHUCO", "STGO. DE CHUCO") == "13"  # abreviado: solo el departamento
    assert T.names("200105") == ("Piura", "Piura", "Catacaos")


def test_territory_disambiguates_by_province_and_spelling(T):
    # Un nombre repetido en el departamento se decide por la provincia.
    assert T.resolve("PUNO", "MELGAR", "SANTA ROSA") == "210808"
    assert T.resolve("PUNO", "EL COLLAO", "SANTA ROSA") == "210504"
    # Grafías del SINPAD: «Lima Provincia» y «Lima Metropolitana», guion bajo, paréntesis, nombres truncados.
    assert T.resolve("LIMA PROVINCIA", "CANTA", "CANTA") == "150401"
    assert T.resolve("LIMA METROPOLITANA", "LIMA METROPOLITANA", "LURIGANCHO-CHOSICA") == "150118"
    assert T.resolve("APURÍMAC", "CHINCHEROS", "ANCO_HUALLO") == "030602"
    assert T.resolve("HUÁNUCO", "HUÁNUCO", "QUISQUI (KICHKI)") == "100106"
    assert T.resolve("CAJAMARCA", "CONTUMAZÁ", "SANTA CRUZ DE TOLED") == "060506"
    # Un truncado que coincide con dos distritos de la provincia se queda en la provincia.
    assert T.resolve("LIMA", "LIMA", "SAN JUAN DE") == "1501"


def test_place_uses_the_point_when_names_are_abbreviated(T):
    doc = json.loads((HF / "sinpad.json").read_text(encoding="utf-8"))
    a, g = next((f["attributes"], f["geometry"]) for f in doc["features"] if f["attributes"]["DES_DIST"] == "STGO. DE CHUCO")
    code, latlon, how = F.place(T, a["DES_DPTO"], a["DES_PROV"], a["DES_DIST"], g["y"], g["x"])
    assert how == "punto" and code.startswith("13") and len(code) == 6 and latlon
    # Un punto que no cae en el distrito que dicen los nombres no reemplaza a los nombres.
    code, latlon, how = F.place(T, "Piura", "Piura", "Catacaos", -12.05, -77.04)
    assert (code, latlon, how) == ("200105", None, "nombre")


# ---------------------------------------------------------------------------
# Atribución ENSO
# ---------------------------------------------------------------------------
def test_named_events_only_in_their_zone_and_for_rain_hazards(cal):
    assert len(PIRCC_2017) == 13
    assert cal.tipo_evento("2017-03-20", True, "Lluvias intensas", "20", "") == ("Niño Costero 2017", "curado")
    # Puno no está en el Plan de Reconstrucción: queda con el Niño costero del ICEN, que no es un gran Niño.
    tipo, how = cal.tipo_evento("2017-02-19", True, "Lluvias intensas", "21", "")
    assert tipo != "Niño Costero 2017" and how == "ventana-icen"
    # Una helada en mayo de 2017 en Junín (dentro de la zona) no es parte del Niño Costero.
    assert cal.tipo_evento("2017-05-20", True, "Helada/Friaje", "12", "")[0] == "Temporada de heladas y friaje"
    assert cal.tipo_evento("2023-03-10", True, "Huayco/Alud", "15", "")[0] == "Ciclón Yaku 2023"
    assert cal.tipo_evento("2023-03-10", True, "Incendio forestal", "15", "")[0] != "Ciclón Yaku 2023"
    assert cal.tipo_evento("1998-02-01", True, "Inundacion fluvial", "20", "")[0] == "FEN 1997-98"


# ---------------------------------------------------------------------------
# Lectores (filas reales)
# ---------------------------------------------------------------------------
def test_sinpad_reader(T, cal):
    doc = json.loads((HF / "sinpad.json").read_text(encoding="utf-8"))
    skipped = Counter()
    rows = {r["IdFuente"]: r for r in F.sinpad(doc, T, cal, skipped=skipped)}
    assert skipped["no climático"] == 2  # incendios urbanos
    assert not any(r["Date"] < "2016-01-01" for r in rows.values())  # 2015 ya está en DesInventar
    nauta = rows["00087516"]
    assert (nauta["Ubigeo"], nauta["DangerType"], nauta["Date"]) == ("160301", "Lluvias intensas", "2017-04-11")
    assert nauta["TipoEvento"] == "Niño Costero 2017"  # Loreto está en el Plan de Reconstrucción
    assert nauta["Fuente"].startswith(F.SINPAD_URL + "/query?where=COD_EMERGE%3D%2700087516%27")
    assert rows["00080357"]["Ubicacion"] == ""  # «sector agropecuario» no es un lugar
    for r in rows.values():
        assert set(r) == set(E.COLUMNS) and r["Origen"] == "sinpad" and r["Latitud"] and r["Longitud"]
    puno = next(r for r in rows.values() if r["Distrito"] == "Ilave")
    assert puno["TipoEvento"] != "Niño Costero 2017"


def test_idmc_idu_reader(T, cal):
    skipped = Counter()
    rows = list(F.idmc_idu((HF / "idmc-idu.csv").read_text(encoding="utf-8"), T, cal, skipped=skipped))
    assert skipped["Mixed disasters"] == 1 and skipped["Earthquake"] == 1 and skipped["triangulación (agregado departamental)"] == 1
    loreto = next(r for r in rows if r["IdFuente"] == "515835")
    assert loreto["Ubigeo"].startswith("1604") and loreto["DangerType"] == "Erosion" and loreto["Desplazados"] == 50
    assert loreto["Descripción"].startswith("Erosión en ") and "Texto del IDMC" in loreto["Descripción"]
    storm = next(r for r in rows if r["DangerType"] == "Tormenta")
    assert storm["ViviendasDestruidas"] == 3
    assert any(r["DangerType"] == "Deslizamiento" for r in rows)  # movimientos en masa «secos»: entran


def test_idmc_events_reader(T, cal):
    skipped = Counter()
    rows = list(F.idmc_events((HF / "idmc-eventos.csv").read_text(encoding="utf-8"), T, cal, skipped=skipped))
    by = {r["Descripción"].split(": ", 1)[1].split(" (IDMC")[0]: r for r in rows}
    assert by["Peru: Flood - Junin, Chanchamayo, Pichanaqui - (10/01/2019)"]["Ubigeo"] == "120303"
    assert by["Peru: Strong Winds - Loreto (Nauta) - 29/01/2020"]["DangerType"] == "Vientos fuertes"
    piura = by["Peru: Flood - Piura - 01/03/2023"]
    assert piura["Ubigeo"] == "20" and piura["PrecisionFecha"] == "mes" and piura["TipoEvento"] == "Ciclón Yaku 2023"
    assert piura["Confianza"] == "baja"
    assert skipped["varios departamentos o sin lugar"] == 1 and skipped["Earthquake"] == 1
    assert not any(r["Anio"] >= 2025 for r in rows)  # 2025 en adelante viene de la fuente IDU


def test_glc_reader_keeps_the_news_link_and_drops_quakes(T, cal):
    doc = json.loads((HF / "nasa-glc.json").read_text(encoding="utf-8"))
    skipped = Counter()
    rows = list(F.glc(doc, T, cal, skipped=skipped))
    assert rows and all(r["Date"] >= "2016-01-01" for r in rows)
    assert any(r["Fuente"].startswith(("http://", "https://")) and "nasa" not in r["Fuente"] for r in rows)


def test_context_readers(T):
    ana = F.ana_points(json.loads((HF / "ana.json").read_text(encoding="utf-8")), T)
    assert ana["200105"][0][:4] == ["Río Piura", "La Legua, Palo Parado, Paredones, Monte Castillo",
                                     "Inundación, Flujo de detritos, Erosión fluvial", "Muy Alto"]
    zc = F.ingemmet_critical(json.loads((HF / "ingemmet-criticas.json").read_text(encoding="utf-8")), T)
    assert zc["010203"][0][1] == "Derrumbe" and zc["010203"][0][3].startswith("https://hdl.handle.net/")
    ips = F.ipress_2023(json.loads((HF / "ipress.json").read_text(encoding="utf-8")), T)
    assert all("\n" not in x[0] for v in ips.values() for x in v)
    inv = F.ingemmet_inventory(json.loads((HF / "ingemmet-inventario.json").read_text(encoding="utf-8")), T)
    assert sum(c["total"] for c in inv.values()) >= 1


# ---------------------------------------------------------------------------
# Indicadores y revisiones
# ---------------------------------------------------------------------------
def test_wilson_and_rate_ratio():
    assert wilson(0, 46) == (0.0, 0.0771)
    rr, lo, hi = rate_ratio(20, 10, 20, 20)
    assert rr == 2 and lo < 2 < hi
    assert rate_ratio(0, 10, 5, 20) == (None, None, None)


def test_frequency_uses_only_the_homogeneous_source():
    def rec(origin, hy):
        return {"Origen": origin, "Ubigeo": "200105", "AnioHidrologico": hy, "TipoEvento": "", "DangerType": "Lluvias intensas",
                "Date": f"{hy[:4]}-12-01", "Anio": int(hy[:4])}
    recs = [rec("desinventar", "1997-98"), rec("sinpad", "2010-11")]
    s = summarize(recs, range(1970, 2015), {1997}, homogeneous={"desinventar"})
    assert (s["registros"], s["aniosConEvento"]) == (2, 1)


def test_reviews_must_match_something(tmp_path):
    p = tmp_path / "revisiones.yaml"
    p.write_text("revisiones:\n  - {id: no-existe, accion: excluir, motivo: prueba}\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="no coincide"):
        B.apply_reviews([{"Id": "desinventar-1", "Date": "1998-01-01", "Ubigeo": "200105"}], p)


def test_curated_records_need_a_known_place_and_a_source(T, cal):
    base = {"Id": "x", "Date": "2017-03", "DangerType": "Inundacion", "Fuente": "https://example.org/a", "FuenteCita": "cita"}
    r = B.normalize_curated({**base, "Departamento": "Piura", "Provincia": "Piura", "Distrito": "Catacaos"}, T, cal, "t.yaml")
    assert (r["Id"], r["Ubigeo"], r["PrecisionFecha"], r["TipoEvento"]) == ("curado-x", "200105", "mes", "Niño Costero 2017")
    with pytest.raises(SystemExit, match="lugar desconocido"):
        B.normalize_curated({**base, "Departamento": "Piura", "Distrito": "No existe"}, T, cal, "t.yaml")
    with pytest.raises(SystemExit, match="Fuente"):
        B.normalize_curated({**base, "Fuente": "ftp://x", "Ubigeo": "200105"}, T, cal, "t.yaml")


# ---------------------------------------------------------------------------
# Catálogo publicado
# ---------------------------------------------------------------------------
def test_manifest_records_provenance():
    m = json.loads(B.MANIFEST.read_text(encoding="utf-8"))
    for s in m["fuentes"]:
        assert s["licencia"] and s["url"].startswith("https://"), s["id"]
        if s.get("archivo") and s.get("parcial") != "pendiente":
            assert re.fullmatch(r"[0-9a-f]{64}", s.get("sha256", "")), s["id"]
            assert s.get("obtenido"), s["id"]
    assert m["cobertura"]["origenes"] == ["desinventar"]


def test_robots_txt_is_respected(monkeypatch, tmp_path):
    import httpx

    robots = {"datos.example": "User-agent: *\nDisallow: /*.csv$\nCrawl-delay: 5\n", "caido.example": None,
              "sigrid.cenepred.gob.pe": "User-agent: *\nDisallow: /arcgis/\n", "www.dhn.mil.pe": None,
              "caido.gob.pe": "<html><title>Just a moment...</title><body>cf-chl captcha</body></html>"}

    def handler(request):
        body = robots.get(request.url.host, "")
        if request.url.path == "/robots.txt":
            return httpx.Response(503) if body is None else httpx.Response(200, text=body)
        raise AssertionError(f"pidió {request.url} sin permiso")

    real = httpx.Client
    monkeypatch.setattr(B.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler),
                                                             **{k: v for k, v in kw.items() if k != "verify"}))
    with pytest.raises(SystemExit, match="no permite"):
        B.robots_check("https://datos.example/dataset/x/download/eventos.csv")
    with pytest.raises(SystemExit, match="no respondió"):
        B.robots_check("https://caido.example/capa/0")
    assert B.robots_check("https://datos.example/dataset/x") == 5
    # Instituciones públicas peruanas: su «Disallow» (o un robots.txt caído) no impide pedir, con al menos 5 s
    # entre pedidos; una verificación antirobots sí.
    assert B.robots_check("https://sigrid.cenepred.gob.pe/arcgis/rest/services/x/MapServer/25") == 5
    assert B.robots_check("https://www.dhn.mil.pe/Archivos/x.pdf") == 5
    with pytest.raises(SystemExit, match="antirobots"):
        B.robots_check("https://caido.gob.pe/datos")
    assert not B.peru_public("https://notgob.pe.example/x") and not B.peru_public("https://www.pucp.edu.pe/x")
    # Lo que el robots.txt no permite se descarga a mano y la construcción no lo pide.
    src = {"id": "x", "archivo": "x.csv", "descarga": "manual", "manual": "descárguelo desde la página",
           "url": "https://datos.example/x.csv"}
    with pytest.raises(SystemExit, match="a mano: descárguelo"):
        B.fetch(src, tmp_path, False, False)


def test_robots_restricted_sources():
    m = json.loads(B.MANIFEST.read_text(encoding="utf-8"))
    by = {s["id"]: s for s in m["fuentes"]}
    # El SIGRID prohíbe /arcgis/ en su robots.txt, pero es una institución pública peruana (ver robots_check).
    for sid in ("ana-puntos-criticos", "ipress-2023"):
        assert by[sid]["descarga"] == "arcgis" and B.peru_public(by[sid]["url"]), sid
    for sid in ("idmc-idu", "idmc-eventos"):
        assert by[sid]["descarga"] == "idmc-api" and by[sid]["url"].startswith("https://helix-tools-api.idmcdb.org/")
        assert "client_id" not in json.dumps(by[sid]["url"]) and "IDMC_CLIENT_ID" in by[sid]["clave"]
    # El portal del SINPAD (INDECI) no tiene robots.txt; igual va al menos a 5 s entre pedidos.
    assert by["sinpad-api"]["descarga"] == "sinpad-api" and B.peru_public(by["sinpad-api"]["url"])


def _emergency(code, hazard, place, when, nivel=1, estado="CERRADO"):
    return {"codigoSinpad": code, "peligroPrincipal": hazard, "dptoProvDistr": place, "fechaHoraEvento": when,
            "nivel": nivel, "estado": estado, "version": 0}


def test_sinpad_api_pages_by_month_resumes_and_stops_politely(monkeypatch, tmp_path, T, cal):
    import httpx
    from datetime import date

    jan = [_emergency(30, "INUNDACIÓN POR DESBORDE DE RIO", "PIURA/PIURA/CASTILLA", "20/01/2019 06:00", 2),
           _emergency(20, "INCENDIOS URBANOS", "LIMA/LIMA/BREÑA", "12/01/2019 22:10"),
           _emergency(10, "LLUVIAS INTENSAS", "JUNÍN/CHANCHAMAYO/PICHANAQUI", "02/01/2019 15:00", 4, "ACTIVO")]
    feb = [_emergency(40, "OTROS", "CUSCO/CUSCO/CUSCO", "05/02/2019 10:00", 0)]
    calls, fail_once = [], {"503": True}

    def handler(request):
        q = dict(request.url.params)
        calls.append((q["fechaInicio"], q["pageNumber"]))
        assert q["pageSize"] == "2" and request.url.host == "prod4.indeci.gob.pe"
        if q["fechaInicio"] == "01/01/2019":
            if fail_once.pop("503", False):
                return httpx.Response(503)
            # Entre la página 1 y la 2 se registró una emergencia nueva: la 2 repite una fila.
            items = jan[:2] if q["pageNumber"] == "1" else jan[1:]
            total = 3
        else:
            assert (q["fechaInicio"], q["fechaFin"]) == ("01/02/2019", "10/02/2019")
            items, total = feb, 1
        return httpx.Response(200, json={"status": 200, "message": "OK", "data": {
            "items": items, "page": {"size": 2, "totalElements": total, "totalPages": -(-total // 2),
                                     "number": int(q["pageNumber"])}}})

    real = httpx.Client
    mock = lambda h: (lambda **kw: real(transport=httpx.MockTransport(h), **{k: v for k, v in kw.items() if k != "verify"}))  # noqa: E731
    monkeypatch.setattr(B.httpx, "Client", mock(handler))
    src = {**{s["id"]: s for s in json.loads(B.MANIFEST.read_text(encoding="utf-8"))["fuentes"]}["sinpad-api"],
           "parametros": {"desde": "2019-01-01", "pageSize": 2}}
    parts = tmp_path / "partes"
    doc = json.loads(B.sinpad_api(src, parts, delay=0, until=date(2019, 2, 10)))
    assert [x["codigoSinpad"] for x in doc["items"]] == [10, 20, 30, 40]
    assert (doc["desde"], doc["hasta"]) == ("2019-01-01", "2019-02-10") and not parts.exists()
    assert calls == [("01/01/2019", "1"), ("01/01/2019", "1"), ("01/01/2019", "2"), ("01/02/2019", "1")]

    # Una descarga cortada sigue donde quedó, con la misma fecha de corte.
    parts.mkdir()
    (parts / "corte.json").write_text('{"hasta": "2019-02-10"}', encoding="utf-8")
    (parts / "2019-01.json").write_text(json.dumps(jan), encoding="utf-8")
    calls.clear()
    assert json.loads(B.sinpad_api(src, parts, delay=0)) == doc
    assert calls == [("01/02/2019", "1")]

    sk = Counter()
    rows = list(F.sinpad_api(doc, T, cal, skipped=sk))
    assert [(r["IdFuente"], r["Ubigeo"], r["DangerType"]) for r in rows] == [
        ("10", "120303", "Lluvias intensas"), ("30", "200104", "Inundacion fluvial")]
    assert sk == {"no climático": 1, "sin tipo": 1}
    r = rows[0]
    assert (r["Date"], r["Origen"], r["Confianza"]) == ("2019-01-02", "sinpad", "alta")
    assert r["Fuente"] == "https://prod4.indeci.gob.pe/portal-sinpad/api/v1/public/emergencias?codigoSinpad=10"
    assert "nivel 4 (intervención del gobierno nacional)" in r["Descripción"] and "activo" in r["Descripción"]
    # Enero de 2019 cae en el Niño costero 2018-19 del ICEN: cuenta la emergencia de nivel 4, no la de nivel 2.
    assert [(x["TipoEvento"], x["AtribucionENSO"]) for x in rows] == [
        ("FEN costero 2018-19", "ventana-icen"), ("Temporada de lluvias", "ninguna")]

    # Si a un mes le faltan filas, se pide otra vez y luego se detiene; ante una página que no es JSON
    # (una verificación antirobots) no se insiste.
    def short(request):
        return httpx.Response(200, json={"status": 200, "data": {"items": jan[:1], "page": {"totalElements": 5, "totalPages": 1}}})

    monkeypatch.setattr(B.httpx, "Client", mock(short))
    with pytest.raises(SystemExit, match="anunció 5"):
        B.sinpad_api(src, tmp_path / "p2", delay=0, until=date(2019, 1, 31))
    calls.clear()

    def challenge(request):
        calls.append(1)
        return httpx.Response(200, text="<html>Just a moment...</html>")

    monkeypatch.setattr(B.httpx, "Client", mock(challenge))
    with pytest.raises(SystemExit, match="antirobots"):
        B.sinpad_api(src, tmp_path / "p3", delay=0, until=date(2019, 1, 31))
    assert calls == [1]


def test_idmc_api_pages_filters_peru_and_hides_the_key(monkeypatch, T, cal):
    import httpx

    seen = []

    def handler(request):
        seen.append(request.url)
        q = dict(request.url.params)
        assert q["client_id"] == "secreto"
        if request.url.path.endswith("/idus/all/disaster/"):
            return httpx.Response(200, json=[
                {"id": 2, "iso3": "PER", "role": "Recommended figure", "type": "Flood", "subtype": "Flood",
                 "figure": 12, "displacement_date": "2026-02-10", "displacement_start_date": "2026-02-10",
                 "displacement_end_date": "2026-02-11", "year": 2026, "event_id": 9, "event_name": "Peru: Flood - Piura",
                 "latitude": -5.1945, "longitude": -80.6328, "locations_name": "Piura, Province of Piura, Piura, Peru",
                 "standard_popup_text": "Peru: 12 displacements (destroyed housing): destroyed 3 houses.", "sources": None},
                {"id": 1, "iso3": "ECU", "role": "Recommended figure", "type": "Flood", "figure": 5}])
        if q.get("offset"):
            return httpx.Response(200, json={"next": None, "results": [
                {"iso3": "PER", "year": 2023, "start_date": "2023-03-10", "start_date_accuracy": "Day",
                 "event_name": "Peru: Flood - Lambayeque - 10/03/2023", "hazard_type_name": "Flood",
                 "hazard_sub_type_name": "Riverine flood", "new_displacement": 300}]})
        assert q["iso3__in"] == "PER"
        return httpx.Response(200, json={"next": str(request.url.copy_merge_params({"offset": 1})), "results": [
            {"iso3": "PER", "year": 2019, "start_date": "2019-01-10", "start_date_accuracy": "Day",
             "event_name": "Peru: Flood - Junin, Chanchamayo, Pichanaqui - (10/01/2019)", "hazard_type_name": "Flood",
             "hazard_sub_type_name": None, "new_displacement": 50}]})

    real = httpx.Client
    monkeypatch.setattr(B.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler),
                                                             **{k: v for k, v in kw.items() if k != "verify"}))
    m = {s["id"]: s for s in json.loads(B.MANIFEST.read_text(encoding="utf-8"))["fuentes"]}
    monkeypatch.delenv("IDMC_CLIENT_ID", raising=False)
    with pytest.raises(SystemExit, match="ch.datainfo@idmc.ch"):
        B.idmc_api(m["idmc-idu"])
    monkeypatch.setenv("IDMC_CLIENT_ID", "secreto")
    idu = B.idmc_api(m["idmc-idu"], delay=0).decode()
    rows = list(F.idmc_idu(idu, T, cal))
    assert [r["IdFuente"] for r in rows] == ["2"] and rows[0]["Ubigeo"] == "200101"
    assert rows[0]["ViviendasDestruidas"] == 3 and rows[0]["Desplazados"] == 12
    events = B.idmc_api(m["idmc-eventos"], delay=0)
    assert B.idmc_api(m["idmc-eventos"], delay=0) == events  # orden estable: el SHA-256 solo cambia con los datos
    rows = list(F.idmc_events(events.decode(), T, cal))
    assert sorted(r["Ubigeo"] for r in rows) == ["120303", "14"]
    assert next(r for r in rows if r["Ubigeo"] == "14")["DangerType"] == "Inundacion fluvial"

    def fail(request):
        return httpx.Response(403, json={"detail": "Client is not registered."})

    monkeypatch.setattr(B.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(fail),
                                                             **{k: v for k, v in kw.items() if k != "verify"}))
    with pytest.raises(SystemExit) as err:
        B.idmc_api(m["idmc-idu"])
    assert "HTTP 403" in str(err.value) and "secreto" not in str(err.value)


def test_published_catalog():
    # El CSV completo va en un ZIP: cada archivo del sitio debe quedar bajo los 25 MiB de Cloudflare Pages.
    assert not (OUT / "eventos.csv").exists()
    assert all(f.stat().st_size < 25 * 2**20 for f in OUT.rglob("*") if f.is_file())
    with zipfile.ZipFile(OUT / "eventos.zip") as z:
        assert z.namelist() == ["eventos.csv"]
        reader = csv.DictReader(io.TextIOWrapper(z.open("eventos.csv"), encoding="utf-8-sig"))
        assert reader.fieldnames[:13] == E.TEAM_COLUMNS
        rows = list(reader)
    summary = json.loads((OUT / "resumen.json").read_text(encoding="utf-8"))
    assert len(rows) == summary["registros"] > 30_000
    ids = Counter(r["Id"] for r in rows)
    assert ids.most_common(1)[0][1] == 1
    T = territory()
    for r in rows:
        assert r["DangerType"] in E.DANGER_TYPES
        assert T.normalize(r["Ubigeo"]) == r["Ubigeo"]
        assert r["Fuente"].startswith(("https://", "http://"))
        assert -18.6 < float(r["Latitud"]) < 0.2 and -81.6 < float(r["Longitud"]) < -68.4
        # Las coordenadas de la fuente se publican solo si caen en el área asignada.
        if r["PrecisionGeo"] == "coordenada-fuente":
            assert F.inside(T, r["Ubigeo"], F.locate_point(r["Latitud"], r["Longitud"])[0]), r["Id"]
    origins = Counter(r["Origen"] for r in rows)
    assert {"desinventar", "sinpad", "idmc", "curado"} <= set(origins)
    hits = Counter(r["TipoEvento"] for r in rows if r["TipoEvento"] in GREAT)
    assert all(hits[g] for g in GREAT), hits
    # «Niño Costero 2017» solo en los 13 departamentos del Plan de Reconstrucción.
    assert {r["Ubigeo"][:2] for r in rows if r["TipoEvento"] == "Niño Costero 2017"} <= PIRCC_2017
    assert summary["eventoEnCurso"] == "FEN 2026"


def test_browser_model_matches_python_with_node():
    node = _need_node()
    r = subprocess.run([node, "--test", str(JS / "historico.test.mjs")], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
    assert re.search(r"# fail 0", r.stdout), r.stdout[-2000:]
