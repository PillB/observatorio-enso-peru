"""Ríos, quebradas, lagunas y nevados de la Carta Nacional (``enso.aguas``): la referencia, el buscador y la verdad de
campo del SINPAD."""

from __future__ import annotations

import csv
import io
import re
import statistics
import zipfile
from collections import Counter
from pathlib import Path

import pytest

from enso.aguas import (BASIN_SHARE, MARGIN_KM, POINT_MAX_KM, PREFIX, WaterMatch, aguas, district_radius_km, water_key,
                        waters)
from enso.historico.territorio import territory
from enso.limites import limits
from enso.lugares import _km, basins

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def catalog() -> list[dict]:
    with zipfile.ZipFile(ROOT / "public" / "assets" / "historico" / "eventos.zip") as z:
        return list(csv.DictReader(io.TextIOWrapper(z.open("eventos.csv"), encoding="utf-8-sig")))


# --- La referencia ------------------------------------------------------------------------------------------------

def test_reference_rows_are_valid():
    A, B = aguas(), basins()
    official = set(limits().levels[6])
    assert set(A.rows) <= official and len(A.rows) >= 1800
    kinds = Counter()
    for code, rows in A.rows.items():
        for name, clase, x, y, radius, length, basin, share in rows:
            kinds[clase] += 1
            assert clase in ("curso", "laguna", "nevado", "volcan", "abra"), (code, name)
            # Un nombre de verdad: no «s/n» ni la clase sola, y con algo más que la clase.
            assert len(water_key(name)) >= 3 and not PREFIX.fullmatch(name.lower()), (code, name)
            assert name == name.strip() and "  " not in name and name[:1].isupper(), (code, name)
            assert -82 * A.scale < x < -68 * A.scale and -18.5 * A.scale < y < 0.1 * A.scale, (code, name)
            assert 0.3 <= radius and 0 <= length and 0 <= share <= 1, (code, name)
            assert not basin or basin in B.units, (code, name, basin)
    assert kinds["curso"] > 30_000 and kinds["laguna"] > 5_000 and kinds["nevado"] > 300
    assert sum(kinds.values()) > 40_000


@pytest.mark.parametrize("raw,want", [
    ("Qda.Honda", ("Quebrada Honda", [])),
    ("QUEBRADA SECA", ("Quebrada Seca", [])),
    ("Quellhuacocha", ("Quellhuacocha", [])),
    ("LAGUNAS CHICAS", ("Lagunas Chicas", [])),
    ("Rí0 Cascas", ("Río Cascas", [])),
    (":quebrada Puyhuan", ("Quebrada Puyhuan", [])),
    ('Quebrada Pirhuata"', ("Quebrada Pirhuata", [])),
    ("Quebrada Le¥a", ("Quebrada Leña", [])),
    ("Quebrada R¡o Blanco", ("Quebrada Río Blanco", [])),
    ("Quebrada M,achuyoc", ("Quebrada Machuyoc", [])),
    ("Quebrada FundiciÓn Huayccoc", ("Quebrada Fundición Huayccoc", [])),
    ("RioTirutaña", ("Río Tirutaña", [])),
    ("ILaguna nocunca", ("Laguna Nocunca", [])),
    ("Quebrada UnchuQuebrada Unchu", ("Quebrada Unchu", [])),
    ("Río JancoJanco", ("Río Janco Janco", ["Río Jancojanco"])),
    ("Quebrada PaRíona", ("Quebrada Pa Ríona", ["Quebrada Paríona"])),
    ("RíoParcotica", ("Río Parcotica", [])),
    ("Río Chili (Sumbay)", ("Río Chili", ["Sumbay"])),
    ("Rio Salla o Cotacucho", ("Río Salla", ["Cotacucho"])),
    ("Quebrada Bicua / Cunía", ("Quebrada Bicua", ["Cunía"])),
    ("Nevado Misti (Ver Volcán Misti)", ("Nevado Misti", [])),
    ("Volcán Puca Mauras (Ver Cerro Puca Mauras)", ("Volcán Puca Mauras", [])),
    ("Quebrada Pozo Blanco (mina)", ("Quebrada Pozo Blanco", [])),
    ("San Salvador, Contamana", ("San Salvador", [])),
    ("Vvvvvvvvvvvvvvvvvv", ("", [])),
])
def test_carta_names_are_cleaned_and_split(raw, want):
    """Las erratas de la Carta que cambiarían la clave del nombre, y sus nombres alternativos."""
    from tools.build_aguas import names

    assert names(raw) == want


def test_reference_names_are_spelled_as_the_carta():
    """``build_aguas.display`` expande las abreviaturas de la Carta («Qda.», «Lag.», «Rio») sin romper los nombres
    que empiezan igual («Quellhuacocha», «Lagunillas»)."""
    names = {r[0] for rows in aguas().rows.values() for r in rows}
    assert not [n for n in names if n.startswith(("Qda", "Lag.", "Rio ", "Q. "))][:1]
    assert not [n for n in names if " unas" in n or n.startswith("Laguna unas")][:1]
    assert not [n for n in names if re.search(r"[¥¡\"(),;/]|[a-zñ][A-ZÁÉÍÓÚÑ]", n)][:5]
    assert any(n.startswith("Quebrada ") for n in names) and any(n.startswith("Lagunas ") for n in names)


def test_alternative_names_find_the_same_water_body():
    A = aguas()
    assert sum(len(v) for v in A.alias.values()) > 50
    m = A.find("040128", "crecida del río Sumbay")
    assert [w.name for w in m.waters] == ["Río Chili (Sumbay)"]
    assert A.find("040128", "crecida del río Chili").names == "Río Chili"


def test_sampled_points_lie_in_their_district():
    """Uno de cada 25: el punto de un tramo es un punto del cauce dentro del distrito (con la tolerancia de la
    simplificación de la Carta)."""
    A, lim = aguas(), limits()
    far, n = [], 0
    for code in sorted(A.rows):
        for i, (name, _c, x, y, *_rest) in enumerate(A.rows[code]):
            if i % 25:
                continue
            n += 1
            px, py = x / A.scale * lim.scale, y / A.scale * lim.scale
            if lim.containing(6, px, py, code) != code:
                km = lim._edge(px, py, lim.levels[6][code]["polys"])[0]
                if km > 0.5:
                    far.append((code, name, round(km, 2)))
    assert n > 1800
    assert not far, far[:20]


# --- El buscador ----------------------------------------------------------------------------------------------------

def test_find_names_a_water_body_after_its_class_word():
    A = aguas()
    m = A.find("150118", "Huaico en la quebrada Jicamarca afectó viviendas")
    assert m.names == "Quebrada Jicamarca" and not m.partial
    lat, lon, radius = m.point(district_radius_km("150118"))
    assert radius == round(A.find("150118", "quebrada Jicamarca").waters[0].radius_km, 1)
    assert radius <= POINT_MAX_KM and _km(lat, lon, -11.98, -76.90) < 1
    assert m.basin(basins().units) == {"code": "137554", "name": "Cuenca Rímac"}
    # El mismo nombre con otra palabra de clase no es ese cuerpo de agua.
    assert not A.find("150118", "laguna Jicamarca").waters
    # Sin la palabra que dice qué es, un nombre suelto en un texto no cuenta.
    assert not A.find("150118", "huaico en Jicamarca").waters


def test_a_list_gives_the_midpoint_and_a_name_outside_the_district_gives_no_point():
    A = aguas()
    one = A.find("150118", "huaico en las quebradas California y Santa María")
    assert one.names == "Quebrada California · Quebrada Santa María" and not one.partial
    lat, lon, radius = one.point(district_radius_km("150118"))
    a, b = one.waters
    assert (lat, lon) == ((a.lat + b.lat) / 2, (a.lon + b.lon) / 2)
    assert radius >= max(_km(lat, lon, w.lat, w.lon) + w.radius_km for w in one.waters) - 0.05
    # «ríos Moche y Chicama» en Trujillo: el Chicama no pasa por el distrito, el lugar no es solo el tramo del Moche.
    two = A.find("130101", "desborde de los ríos Moche y Chicama")
    assert two.names == "Río Moche" and two.partial and two.point() is None


def test_adjective_names_need_a_capital_or_a_place_field():
    A = aguas()
    assert not A.find("040206", "la quebrada honda se activó").waters
    assert not A.find("040206", "LA QUEBRADA HONDA SE ACTIVO").waters
    assert A.find("040206", "la quebrada Honda se activó").names == "Quebrada Honda"
    assert A.find("040206", "QUEBRADA HONDA", field=True).names == "Quebrada Honda"


def test_a_longer_name_is_not_a_shorter_river():
    """«río Santa Eulalia» no es el río Santa; en un distrito sin río Santa Eulalia no hay nada."""
    assert not aguas().find("021801", "crecida del río Santa Eulalia").waters


def test_a_long_reach_gives_the_basin_but_no_point():
    A, B = aguas(), basins()
    m = A.find("130101", "desborde del río Moche")
    assert m.names == "Río Moche" and m.point(district_radius_km("130101")) is None
    assert m.basin(B.units) == {"code": "137716", "name": "Cuenca Moche"}
    # Dos cuencas distintas, o un tramo repartido, no dan cuenca.
    w = m.waters[0]
    assert WaterMatch([w, type(w)(**{**w.__dict__, "basin_code": "137554"})]).basin(B.units) is None
    assert WaterMatch([type(w)(**{**w.__dict__, "basin_share": BASIN_SHARE - 0.01})]).basin(B.units) is None


def test_alert_points_are_only_short_reaches():
    pts = waters(["150118", "130101"], "huaico en la quebrada Jicamarca y desborde del río Moche")
    assert [p["name"] for p in pts] == ["Quebrada Jicamarca"]
    assert pts[0]["kind"] == "cuerpo-de-agua" and pts[0]["district"] == "150118"
    assert pts[0]["basin"]["name"] == "Cuenca Rímac"


# --- La verdad de campo ---------------------------------------------------------------------------------------------

def test_water_points_land_near_where_sinpad_measured_them(catalog):
    """Los registros con punto de campo del SINPAD que nombran un río, una quebrada o una laguna con un tramo corto:
    el punto que da el nombre debe estar cerca del medido, y más cerca que la capital del distrito. En la medición del
    28 de octubre de 2026: 49 registros, mediana 2,6 km (la capital, 11,5 km), el 73 % dentro del radio (con
    ``MARGIN_KM``) y el 84 % más cerca que la capital."""
    from tools.build_historico import water_names

    A, t = aguas(), territory()
    ds, inside, closer = [], 0, 0
    for r in catalog:
        if r["PrecisionGeo"] != "coordenada-fuente":
            continue
        m = water_names(r, A)
        p = m.point(district_radius_km(r["Ubigeo"])) if m else None
        if not p:
            continue
        lat, lon = float(r["Latitud"]), float(r["Longitud"])
        d = _km(lat, lon, p[0], p[1])
        cap = t.dist[r["Ubigeo"]]
        ds.append(d)
        inside += d <= p[2]
        closer += d < _km(lat, lon, cap["lat"], cap["lon"])
    n = len(ds)
    assert n >= 40, n
    assert statistics.median(ds) <= 3.5, statistics.median(ds)
    assert inside / n >= 0.65 and closer / n >= 0.75, (inside / n, closer / n)
    assert set(MARGIN_KM) == {"curso", "laguna", "nevado", "volcan", "abra"}


def test_water_rows_in_the_catalog(catalog):
    kinds = Counter(r["PrecisionGeo"] for r in catalog)
    assert 300 <= kinds["cuerpo-de-agua"] <= 1000
    named = [r for r in catalog if r["CuerpoAgua"]]
    assert len(named) > kinds["cuerpo-de-agua"]
    for r in catalog:
        if r["PrecisionGeo"] == "cuerpo-de-agua":
            assert r["CuerpoAgua"] and not r["Lugar"] and r["Cuenca"], r["Id"]
