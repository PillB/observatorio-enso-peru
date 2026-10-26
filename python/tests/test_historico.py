"""Memoria de desastres: lectores, clasificación, atribución ENSO, catálogo publicado y paridad con el navegador.

Los lectores se prueban con filas reales de cada fuente (``tests/fixtures/historico``: SINPAD, IDMC, NASA, ANA,
INGEMMET, salud 2023, recortadas de las descargas de octubre de 2026). El catálogo publicado
(``public/assets/historico``) se revisa entero.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
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
        if s.get("archivo"):
            assert re.fullmatch(r"[0-9a-f]{64}", s.get("sha256", "")), s["id"]
            assert s.get("obtenido"), s["id"]
    assert m["cobertura"]["origenes"] == ["desinventar"]


def test_published_catalog():
    with (OUT / "eventos.csv").open(encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
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
