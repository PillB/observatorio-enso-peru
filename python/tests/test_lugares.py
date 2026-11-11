"""Ubicación más fina que el distrito: centros poblados (INEI, IGN, SDOT) y cuencas (ANA), y su uso en el catálogo.

La referencia sale de ``tools.build_lugares`` (``enso/data/lugares.json.gz`` y ``cuencas.json.gz``). Aquí se
comprueba contra los límites del INDECI, contra las estaciones hidrológicas del SENAMHI (que traen su cuenca) y
contra los puntos de campo del SINPAD: el centro poblado que nombra un registro, ¿está donde el SINPAD lo midió?
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from collections import Counter
from pathlib import Path

import pytest

from enso.historico.territorio import territory
from enso.limites import limits
from enso.lugares import (MAX_SPREAD_KM, Match, Place, _km, basin_at, basins, candidates, district_basin, lugares,
                          name_key)

ROOT = Path(__file__).resolve().parents[2]
UBIGEO = json.loads((ROOT / "python" / "enso" / "data" / "ubigeo.json").read_text(encoding="utf-8"))
FIXTURES = ROOT / "python" / "tests" / "fixtures" / "sources"


@pytest.fixture(scope="module")
def catalog() -> list[dict]:
    with zipfile.ZipFile(ROOT / "public" / "assets" / "historico" / "eventos.zip") as z:
        return list(csv.DictReader(io.TextIOWrapper(z.open("eventos.csv"), encoding="utf-8-sig")))


# --- La referencia ------------------------------------------------------------------------------------------------

def test_places_cover_the_districts_with_valid_rows():
    L = lugares()
    official = {d["ubigeo"] for d in UBIGEO["districts"]}
    assert set(L.rows) <= official and len(L.rows) >= 1880
    n = sum(len(v) for v in L.rows.values())
    assert n > 150_000
    for code, rows in L.rows.items():
        for name, x, y, cat, ccpp, pop, layer, radius in rows:
            assert name and layer in ("inei", "ign"), (code, name)
            assert not ccpp or (len(ccpp) == 10 and ccpp.isdigit()), (code, name, ccpp)
            assert -82 * L.scale < x < -68 * L.scale and -18.5 * L.scale < y < 0.1 * L.scale, (code, name)
            assert radius in (0, 0.0) or radius >= 1, (code, name, radius)


def test_sampled_places_lie_in_their_district():
    """Uno de cada 40 lugares: dentro de su distrito, o a menos de 1 km del límite (el radio de un centro
    poblado). El 5 % de los centros poblados del censo cae fuera del distrito de su código; ``build_lugares`` los
    deja en el distrito del punto si es de la misma provincia, y descarta el resto."""
    L, lim = lugares(), limits()
    far, n = [], 0
    for code in sorted(L.rows):
        for i, (name, x, y, *_rest) in enumerate(L.rows[code]):
            if i % 40:
                continue
            n += 1
            px, py = x / L.scale * lim.scale, y / L.scale * lim.scale
            if lim.containing(6, px, py, code) != code:
                km = lim._edge(px, py, lim.levels[6][code]["polys"])[0]
                if km > 1.15:
                    far.append((code, name, round(km, 2)))
    assert n > 4000
    assert not far, far[:20]


def test_watersheds_cover_peru_once():
    """Las 231 unidades hidrográficas de la ANA no se solapan y cubren el país: cada capital de distrito cae en
    exactamente una."""
    B = basins()
    assert len(B.units) == 231
    lim = limits()
    misses, doubles = [], []
    for d in UBIGEO["districts"]:
        if d.get("lat") is None:
            continue
        x, y = d["lon"] * B.scale, d["lat"] * B.scale
        hits = [c for c, u in B.units.items() if _bbox(x, y, u["bbox"]) and _polys(x, y, u["polys"])]
        if not hits:
            misses.append(d["ubigeo"])
        elif len(hits) > 1:
            doubles.append((d["ubigeo"], hits))
    assert not doubles, doubles[:10]
    # Una capital en la orilla del mar o de un lago puede quedar fuera por la simplificación de la costa.
    assert len(misses) <= 3, misses
    assert lim  # los límites cargan con la misma escala de trabajo


def _bbox(x, y, b):
    from enso.limites import _in_bbox
    return _in_bbox(x, y, b)


def _polys(x, y, p):
    from enso.limites import _in_polys
    return _in_polys(x, y, p)


def test_senamhi_stations_fall_in_the_watershed_senamhi_names():
    # Las estaciones hidrológicas del SENAMHI (capa AvisoHidrologico24H del GEOSINPAD, captura del 21 de octubre de
    # 2026) traen cada una la cuenca en que están: la de la ANA en ese punto debe ser la misma, en todas.
    rows = json.loads((FIXTURES / "news-senamhi-hidrologicos.json").read_text(encoding="utf-8"))["features"]
    seen = {}
    for f in rows:
        a = f["attributes"]
        seen[a["NOM_ESTACI"]] = (basin_at(a["LATITUD"], a["LONGITUD"]) or {}).get("code"), a["COD_CUENCA"]
    assert len(seen) >= 8 and all(got == want for got, want in seen.values()), seen


def test_district_watershed_only_when_most_of_the_district_is_in_one():
    assert district_basin("060203")["name"] == "Cuenca Crisnejas"  # Condebamba (Cajabamba)
    assert district_basin("150101")["name"] == "Cuenca Rímac"  # Lima
    assert district_basin("080910") is None  # Pichari: entre el Apurímac, el Ene y otras
    assert district_basin("") is None and district_basin("15") is None
    shared = sum(1 for c in basins().districts if district_basin(c))
    assert 1400 < shared < 1891


# --- El ubicador ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,field,want", [
    ("Lluvias afectaron el sector de Panamá, distrito de Condebamba", False, ["panama"]),
    ("caserío La Pared", False, ["la pared"]),
    ("en las localidades de Puerto Roca y Quimarotipiari", False, ["puerto roca", "quimarotipiari"]),
    ("C.P. Pampamarca del distrito de Yarumayo", False, ["pampamarca"]),
    ("Anexo de Huachipa; C.C. San Juan", False, ["huachipa", "san juan"]),
    ("A.H. Los Olivos, afectado por el huaico", False, ["los olivos"]),
    ("Lluvias intensas en Pampamarca", False, []),  # texto libre sin palabra que presente el lugar
    ("Huayllay, Cochamarca", True, ["huayllay", "cochamarca"]),
    ("Caserío Shiracmaca - distrito de Huamachuco", True, ["shiracmaca"]),
])
def test_candidates(text, field, want):
    got = [name_key(c) for c, _ in candidates(text, field)]
    assert all(w in got for w in want), got
    if not want:
        assert not got, got


def test_find_names_a_place_in_the_district_only():
    L = lugares()
    m = L.find("060203", "Lluvias afectaron el sector de Panamá, distrito de Condebamba")
    assert [p.code for p in m.places] == ["0602030021"] and m.places[0].basin["name"] == "Cuenca Crisnejas"
    lat, lon, radius = m.point()
    assert abs(lat + 7.5224) < 0.01 and abs(lon + 78.1432) < 0.01 and radius == 1.0
    # El mismo texto en otro distrito no encuentra nada: no busca fuera del distrito.
    assert not L.find("150101", "sector de Panamá").places
    # El nombre del distrito o de la capital no agrega nada si se excluye.
    assert not L.find("060203", "caserío Condebamba", exclude=("Cajamarca", "Cajabamba", "Condebamba")).places
    # Palabras genéricas.
    assert not L.find("060203", "sector zona alta; caserío centro poblado").places
    # Sin distrito o sin texto.
    assert not L.find("0602", "sector de Panamá").places and not L.find("060203", "").places


def test_homonyms_in_a_district_are_ambiguous_not_guessed():
    L = lugares()
    idx = L.index("010103")
    rows = idx["tuen"]
    pts = [(r[2] / L.scale, r[1] / L.scale) for r in rows]
    assert len(rows) >= 2 and _km(*pts[0], *pts[1]) > 2
    m = L.find("010103", "caserío Tuén")
    assert not m.places and m.ambiguous == ["Tuen"]


def test_several_places_give_their_midpoint_or_nothing_when_spread():
    near = [Place("A", -7.50, -78.10, "", "1", 0, "inei", 1.0), Place("B", -7.52, -78.12, "", "2", 0, "inei", 1.0)]
    lat, lon, radius = Match(near).point()
    assert (round(lat, 2), round(lon, 2)) == (-7.51, -78.11) and 2 < radius < 3
    far = near + [Place("C", -7.70, -78.10, "", "3", 0, "inei", 1.0)]
    assert Match(far).point() is None and MAX_SPREAD_KM == 10.0
    assert Match().point() is None


# --- El catálogo ----------------------------------------------------------------------------------------------------

def test_named_places_land_where_sinpad_measured_them(catalog):
    """Verdad de campo: los registros con punto de campo del SINPAD (no uno por defecto) que además nombran un
    centro poblado. El lugar que el ubicador da a ese nombre debe estar cerca del punto medido: en la medición
    del 27 de octubre de 2026, 1 028 registros, mediana 0,34 km, 81 % a menos de 2 km y 93 % a menos de 5 km."""
    from tools.build_historico import place_names

    t, L = territory(), lugares()
    ds = []
    for r in catalog:
        if r["PrecisionGeo"] != "coordenada-fuente" or not r["Lugar"]:
            continue
        m = place_names(r, t, L)
        assert m and m.places, r["Id"]
        p = m.places[0]
        ds.append(_km(float(r["Latitud"]), float(r["Longitud"]), p.lat, p.lon))
    ds.sort()
    n = len(ds)
    assert n >= 800, n
    assert ds[n // 2] <= 1.0, ds[n // 2]
    assert sum(d <= 2 for d in ds) / n >= 0.75
    assert sum(d <= 5 for d in ds) / n >= 0.90


def test_no_source_point_is_a_capital_or_a_repeated_default(catalog):
    """El SINPAD pone la capital (del distrito, la provincia o el departamento, o el centro poblado capital del
    distrito) cuando no hay punto de campo, y repite un mismo punto en muchas filas de un distrito: esos no son
    ``coordenada-fuente``."""
    t, L = territory(), lugares()
    caps = []
    rep: dict = {}
    for r in catalog:
        if r["PrecisionGeo"] != "coordenada-fuente":
            continue
        code, lat, lon = r["Ubigeo"], float(r["Latitud"]), float(r["Longitud"])
        rep.setdefault((code, round(lat, 4), round(lon, 4)), []).append((lat, lon))
        for table, k in ((t.dist, 6), (t.prov, 4), (t.dep, 2)):
            rec = table.get(code[:k])
            if rec and rec.get("lat") is not None and rec.get("point") != "interior" and \
                    _km(lat, lon, rec["lat"], rec["lon"]) <= 0.5:
                caps.append((r["Id"], code, k))
        for row in L.rows.get(code, []):
            if (row[3] == "capital de distrito" or row[4].endswith("0001")) and \
                    _km(lat, lon, row[2] / L.scale, row[1] / L.scale) <= 0.5:
                caps.append((r["Id"], code, row[0]))
    assert not caps, caps[:10]
    for (code, *_k), pts in rep.items():
        if len(pts) >= 5:  # repetido: solo si es un centro poblado (que no es la capital)
            lat, lon = pts[0]
            assert any(_km(lat, lon, row[2] / L.scale, row[1] / L.scale) <= 0.3 for row in L.rows.get(code, [])), \
                (code, lat, lon, len(pts))


def test_place_rows_carry_their_place_radius_and_watershed(catalog):
    from enso.aguas import aguas, district_radius_km
    from tools.build_historico import place_names, water_names

    t, L, A, B = territory(), lugares(), aguas(), basins()
    kinds = Counter(r["PrecisionGeo"] for r in catalog)
    assert kinds["centro-poblado"] > 1000 and kinds["coordenada-fuente"] > 5000 and kinds["cuerpo-de-agua"] > 300
    seen = 0
    for i, r in enumerate(catalog):
        geo = r["PrecisionGeo"]
        if geo == "centro-poblado":
            assert r["Lugar"] and float(r["RadioKm"]) >= 1.0, r["Id"]
            if i % 10 == 0:  # el punto es el de los lugares que nombra la fila
                lat, lon, radius = place_names(r, t, L).point()
                assert (round(lat, 5), round(lon, 5), radius) == \
                    (float(r["Latitud"]), float(r["Longitud"]), float(r["RadioKm"])), r["Id"]
        elif geo == "cuerpo-de-agua":
            # Sin centro poblado: el río o la quebrada que nombra, con un tramo corto en el distrito.
            assert r["CuerpoAgua"] and 0.5 <= float(r["RadioKm"]) <= 10 and not place_names(r, t, L), r["Id"]
            lat, lon, radius = water_names(r, A).point(district_radius_km(r["Ubigeo"]))
            assert (round(lat, 5), round(lon, 5), radius) == \
                (float(r["Latitud"]), float(r["Longitud"]), float(r["RadioKm"])), r["Id"]
        else:
            assert not r["RadioKm"], r["Id"]
        if geo in ("centro-poblado", "coordenada-fuente", "cuerpo-de-agua"):
            b = basin_at(float(r["Latitud"]), float(r["Longitud"]))
            seen += 1
        else:  # la del río que nombra (si su tramo cae casi entero en una) o la del distrito
            w = water_names(r, A) if r["CuerpoAgua"] else None
            b = (w.basin(B.units) if w else None) or district_basin(r["Ubigeo"])
        assert r["CuencaCodigo"] == (b["code"] if b else "") and r["Cuenca"] == (b["name"] if b else ""), r["Id"]
    assert seen > 6000
    with_basin = sum(1 for r in catalog if r["CuencaCodigo"])
    assert with_basin / len(catalog) > 0.8


def test_relocate_moves_to_the_named_place_and_drops_default_points():
    from tools.build_historico import relocate

    t = territory()
    lat0, lon0 = t.dist["060203"]["lat"], t.dist["060203"]["lon"]
    base = {"Ubigeo": "060203", "Departamento": "Cajamarca", "Provincia": "Cajabamba", "Distrito": "Condebamba",
            "Ubicacion": "", "Region": "", "AltitudCapital": ""}
    rows = [
        # Capital con un centro poblado en la descripción: el centro poblado.
        dict(base, PrecisionGeo="capital-distrito", Latitud=lat0, Longitud=lon0,
             **{"Descripción": "Huaico afectó viviendas en el sector de Panamá"}),
        # El punto de la fuente es la capital del distrito: por defecto, no es de campo.
        dict(base, PrecisionGeo="coordenada-fuente", Latitud=lat0 + 0.001, Longitud=lon0,
             **{"Descripción": "Lluvias intensas"}),
        # Punto de campo con un lugar en la columna de ubicación: queda el punto, el lugar va en Lugar.
        dict(base, PrecisionGeo="coordenada-fuente", Latitud=-7.53, Longitud=-78.14, Ubicacion="Panamá",
             **{"Descripción": ""}),
    ]
    q = Counter()
    relocate(rows, t, q)
    assert rows[0]["PrecisionGeo"] == "centro-poblado" and rows[0]["Lugar"] == "Panama"
    assert rows[0]["LugarCodigo"] == "0602030021" and rows[0]["RadioKm"] == 1.0
    assert rows[0]["Cuenca"] == "Cuenca Crisnejas" and rows[0]["CuencaCodigo"] == "49898"
    assert rows[1]["PrecisionGeo"] == "capital-distrito" and (rows[1]["Latitud"], rows[1]["Longitud"]) == (lat0, lon0)
    assert rows[1]["Lugar"] == "" and rows[1]["Cuenca"] == "Cuenca Crisnejas"
    assert rows[1]["PuntoFuente"] == "por-defecto-capital"
    assert rows[2]["PrecisionGeo"] == "coordenada-fuente" and rows[2]["Latitud"] == -7.53 and rows[2]["Lugar"] == "Panama"
    assert rows[2]["PuntoFuente"] == "en-el-lugar" and not rows[0].get("PuntoFuente")
    assert q["punto por defecto de la fuente (capital): no es el lugar del evento"] == 1
    before = [dict(r) for r in rows]
    again = Counter()
    relocate(rows, t, again)
    assert rows == before and not again
