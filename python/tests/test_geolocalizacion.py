"""Exactitud geográfica, contra la referencia oficial: el nomenclátor, los límites, los puntos y los homónimos.

La referencia es la lista de distritos del INDECI (``tests/geo/indeci-distritos.csv``: UBIGEO, departamento,
provincia, distrito y capital de la capa ``SDE.DISTRITOS`` del GEOSINPAD, bajada el 27 de octubre de 2026), la
misma cartografía con la que el INDECI ubica los reportes del COEN y las emergencias del SINPAD. Los polígonos
(``enso/data/limites-ign.json.gz``) salen del mismo servicio (``tools.build_limites``).
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

from enso.geo import gazetteer, key, locate_item
from enso.historico.territorio import territory
from enso.historico import fuentes as F
from enso.limites import CREATED_AFTER_2020, limits

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL = Path(__file__).parent / "geo" / "indeci-distritos.csv"
UBIGEO = json.loads((ROOT / "python" / "enso" / "data" / "ubigeo.json").read_text(encoding="utf-8"))

#: Capitales del nomenclátor a metros del límite de su distrito (los bordes se simplifican a unos 110 m), o
#: que el INEI ubica a unos 2 km del límite del INDECI (Trita): caen en el vecino; se toleran solo así de cerca.
EDGE = {"010523": 2.5, "080108": 0.1, "090118": 0.1, "100316": 0.1, "130102": 0.1}
#: Homónimos que el ubicador de textos resuelve a propósito por el más conocido, y nombres que no ubica.
KNOWN = {
    "150732": "Surco (Huarochirí): «Surco (Lima)» queda en el departamento; sin provincia, Surco es Santiago de Surco",
    "220702": "Buenos Aires (Picota): el nombre de la capital argentina marca la nota como extranjera; no se ubica",
}


def _official() -> list[dict]:
    with OFFICIAL.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# --- El nomenclátor frente a la lista oficial -------------------------------------------------------------------

def test_gazetteer_has_exactly_the_official_districts():
    official = {r["ubigeo"] for r in _official()}
    assert len(official) == 1891
    assert {d["ubigeo"] for d in UBIGEO["districts"]} == official
    # Y los límites tienen un polígono por cada uno, por provincia y por departamento.
    lim = limits()
    assert set(lim.levels[6]) == official
    assert set(lim.levels[4]) == {p["ubigeo"] for p in UBIGEO["provinces"]}
    assert set(lim.levels[2]) == {d["ubigeo"] for d in UBIGEO["departments"]}
    assert not lim.newer  # ninguna provincia con distritos sin polígono


def test_codes_nest_and_names_match_the_official_list():
    t = territory()
    for r in _official():
        c = r["ubigeo"]
        dep, prov, _ = t.names(c)
        assert key(dep) == key(r["departamento"]) or (c[:2] == "07"), r
        assert key(prov) == key(r["provincia"]) or key(r["provincia"]) in ("nasca", "prov const del callao"), r


def test_every_official_spelling_reaches_its_district():
    """El SINPAD y el COEN escriben como el INDECI («IHUAYLLO», «SAN PEDRO DE LARAOS», «HEROES ALBARRACIN»):
    el ubicador de textos y el de fuentes con columnas deben llevar cada grafía oficial a su código."""
    gz, t = gazetteer(), territory()
    for r in _official():
        c = r["ubigeo"]
        name = re.sub(r"\(.*?\)", " ", r["distrito"])
        if c not in ("060506", "070101", "150101"):  # truncado por la fuente («TOLED»); Callao y Lima: la provincia
            assert c in gz.names.get(key(name), ()), r
        assert t.resolve(r["departamento"], r["provincia"], r["distrito"]) == c, r


def test_non_districts_and_new_districts():
    codes = {d["ubigeo"]: d for d in UBIGEO["districts"]}
    assert "150144" not in codes  # Santa María de Huachipa: centro poblado de Lurigancho (Ley N° 30888 solo declara)
    assert codes["130112"]["name"] == "Alto Trujillo"  # Ley N° 31644 (2022)
    assert not any(d.get("provisional") for d in codes.values())


# --- Puntos dentro de su área -------------------------------------------------------------------------------------

@pytest.mark.parametrize("level,key_", [(6, "districts"), (4, "provinces"), (2, "departments")])
def test_every_point_of_the_gazetteer_lies_in_its_own_area(level, key_):
    """La capital (o el punto interior) de cada unidad cae dentro de su polígono: es el punto que el catálogo
    histórico publica cuando la fuente no trae coordenadas."""
    lim = limits()
    for d in UBIGEO[key_]:
        assert d["lat"] is not None, d  # todos los distritos tienen punto
        x, y = d["lon"] * lim.scale, d["lat"] * lim.scale
        got = lim.containing(level, x, y)
        if got != d["ubigeo"]:
            km = lim._edge(x, y, lim.levels[level][d["ubigeo"]]["polys"])[0]
            assert km <= EDGE.get(d["ubigeo"], 0), (d, got, km)


def test_interior_points_are_marked():
    for d in UBIGEO["districts"]:
        if d.get("point") == "interior":
            assert not d["capital"] or d["ubigeo"] == "130112", d


def test_map_points_lie_in_their_own_area():
    """Los puntos del mapa de alertas (versión B), deshecha la proyección, caen en su provincia o distrito."""
    m = json.loads((ROOT / "public" / "assets" / "peru-map.json").read_text(encoding="utf-8"))
    p, lim = m["lonLat"], limits()
    for code, (x, y) in m["points"].items():
        lon, lat = p["lon0"] + x / (p["k"] * p["cos"]), p["lat1"] - y / p["k"]
        assert lim.containing(len(code), lon * lim.scale, lat * lim.scale) == code, code
    for d in m["departments"]:
        x, y = d["label"]
        lon, lat = p["lon0"] + x / (p["k"] * p["cos"]), p["lat1"] - y / p["k"]
        assert lim.containing(2, lon * lim.scale, lat * lim.scale) == d["code"], d["code"]


# --- Homónimos: nunca otro distrito -------------------------------------------------------------------------------

def _ok(code: str, got: list[str]) -> bool:
    """El distrito, o solo unidades que lo contienen (más grueso, pero no equivocado)."""
    return bool(got) and all(code.startswith(g) for g in got)


def test_every_district_with_its_department_in_parentheses():
    """«Huaico en el distrito de X (Departamento)», como titula el COEN, para los 1 891 distritos: el distrito, o
    su provincia o departamento si el nombre se repite en el departamento (Santa Rosa, Sancos, Huallanca…),
    pero nunca otro lugar. «(Lima)» es el departamento, no Lima Metropolitana."""
    gz = gazetteer()
    wrong = []
    for c, d in gz.dists.items():
        got = [p["code"] for p in locate_item({"title": f"Huaico en el distrito de {d['name']} ({gz.deps[c[:2]]['name']})"})["places"]]
        if not _ok(c, got) and c not in KNOWN:
            wrong.append((c, d["name"], got))
    assert not wrong


def test_every_district_with_its_province_and_department():
    gz = gazetteer()
    wrong = []
    for c, d in gz.dists.items():
        title = (f"Lluvias intensas en el distrito de {d['name']}, provincia de {gz.provs[c[:4]]['name']} "
                 f"({gz.deps[c[:2]]['name']})")
        got = [p["code"] for p in locate_item({"title": title})["places"]]
        if not _ok(c, got) and c not in KNOWN:
            wrong.append((c, d["name"], got))
    assert not wrong


@pytest.mark.parametrize("title,code", [
    # Homónimos dentro del departamento: sin provincia, el departamento.
    ("Incendio forestal en el distrito de Santa Rosa (Puno)", "21"),
    ("Incendio forestal en el distrito de Sancos (Ayacucho)", "05"),
    ("Lluvias intensas en el distrito de Huallanca (Áncash)", "02"),
    ("Huaico en el distrito de San Antonio (Lima)", "15"),
    # Con la provincia, el distrito.
    ("Lluvias en el distrito de Santa Rosa, provincia de Melgar (Puno)", "210808"),
    ("Huaico en el distrito de Huallanca, provincia de Bolognesi", "020508"),
    ("Lluvias intensas en el distrito de Surco, provincia de Huarochirí (Lima)", "150732"),
    # «(Lima)» acota, no agrega Lima Metropolitana.
    ("Huaico en el distrito de Colonia (Lima)", "151011"),
    # Distritos nuevos y grafías del COEN.
    ("Lluvias intensas en el distrito de Alto Trujillo (La Libertad)", "130112"),
    ("Derrumbe de roca en el distrito de Boquerón (Ucayali)", "250307"),
    ("Deslizamiento en el distrito de Fidel Oliva Escudero (Áncash)", "021304"),
    ("Huaico afecta viviendas en Santa María de Huachipa", "150118"),
])
def test_known_homonyms_and_spellings(title, code):
    assert [p["code"] for p in locate_item({"title": title})["places"]] == [code]


# --- El catálogo de la memoria de desastres ------------------------------------------------------------------------

def _catalog() -> list[dict]:
    import io
    import zipfile

    with zipfile.ZipFile(ROOT / "public" / "assets" / "historico" / "eventos.zip") as z:
        return list(csv.DictReader(io.TextIOWrapper(z.open("eventos.csv"), encoding="utf-8-sig")))


def test_every_published_point_lies_in_its_area_and_names_match_the_code():
    """Cada fila del catálogo: nombres = los del UBIGEO, y su punto (de la fuente, capital o interior) dentro del
    área asignada. Antes, 1 117 filas de 16 distritos sin capital en el nomenclátor llevaban la capital de su
    provincia, hasta a 126 km de su distrito."""
    t, lim = territory(), limits()
    far = []
    for r in _catalog():
        code = r["Ubigeo"]
        assert t.normalize(code) == code, r["Id"]
        assert (r["Departamento"], r["Provincia"], r["Distrito"]) == t.names(code), r["Id"]
        x, y = float(r["Longitud"]) * lim.scale, float(r["Latitud"]) * lim.scale
        if lim.containing(len(code), x, y) != code:
            km = lim._edge(x, y, lim.levels[len(code)][code]["polys"])[0]
            if r["PrecisionGeo"] == "coordenada-fuente" or km > EDGE.get(code, 0.15):
                far.append((r["Id"], code, r["PrecisionGeo"], round(km, 2)))
    assert not far, far[:20]


def test_a_source_point_in_a_district_created_later_takes_its_code():
    loc = {"code": "250307"}  # Boquerón (2021), dentro de Padre Abad
    assert F.newer_sibling("250301", loc) == "250307"
    assert F.newer_sibling("250307", loc) is None
    assert F.newer_sibling("250101", loc) is None  # otra provincia: no
    assert F.newer_sibling("010509", {"code": "010523"}) is None  # vecino antiguo (Trita): no
    assert "130112" in CREATED_AFTER_2020 and not {"120604", "120606"} & CREATED_AFTER_2020
    t = territory()
    code, pt, how = F.place(t, "UCAYALI", "PADRE ABAD", "PADRE ABAD", -9.0152, -75.7691)
    assert (code, how) == ("250307", "punto") and pt


def test_relocate_is_idempotent_and_fixes_points():
    from tools.build_historico import relocate
    from collections import Counter

    t = territory()
    rows = [
        # Punto de la fuente en Boquerón con el distrito que nombró la fuente (Padre Abad).
        {"Ubigeo": "250301", "PrecisionGeo": "coordenada-fuente", "Latitud": "-9.0152", "Longitud": "-75.7691",
         "Departamento": "Ucayali", "Provincia": "Padre Abad", "Distrito": "Padre Abad", "Region": "", "AltitudCapital": ""},
        # Putis con la capital de su provincia (Huanta), como antes.
        {"Ubigeo": "050413", "PrecisionGeo": "capital-provincia", "Latitud": "-12.9394", "Longitud": "-74.2481"},
        # Punto de la fuente fuera de su distrito y no en un distrito nuevo: la capital.
        {"Ubigeo": "150101", "PrecisionGeo": "coordenada-fuente", "Latitud": "-13.5", "Longitud": "-71.9"},
    ]
    for r in rows[1:]:
        r["Departamento"], r["Provincia"], r["Distrito"] = t.names(r["Ubigeo"])
    q = Counter()
    relocate(rows, t, q)
    assert rows[0]["Ubigeo"] == "250307" and rows[0]["Distrito"] == "Boquerón" and rows[0]["PrecisionGeo"] == "coordenada-fuente"
    assert rows[1]["PrecisionGeo"] == "interior-distrito" and (rows[1]["Latitud"], rows[1]["Longitud"]) == t.point("050413")[:2]
    assert rows[2]["PrecisionGeo"] == "capital-distrito"
    assert sum(q.values()) == 3
    again = Counter()
    before = [dict(r) for r in rows]
    relocate(rows, t, again)
    assert rows == before and not again
