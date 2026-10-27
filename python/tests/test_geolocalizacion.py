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
from enso.limites import limits

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
        if c not in ("150712", "250201"):  # «SAN PEDRO DE LARAOS», «RAIMONDI»: alias de territorio.NAME_ALIASES
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
