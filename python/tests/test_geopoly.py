"""Ubicación por departamento con los límites del INDECI, contra una referencia independiente."""

from __future__ import annotations

import csv

from conftest import FIX
from enso import geopoly as G
from enso.geo import department_names, key


def test_departments_load_with_their_ubigeo():
    areas = G.departments()
    assert sorted(a.code for a in areas) == sorted(department_names())  # los 25, Callao incluido
    assert G.department_at(-12.0464, -77.0428) == "15"  # Lima, plaza de armas
    assert G.department_at(-12.0566, -77.1181) == "07"  # Callao
    assert G.department_at(-3.7491, -73.2538) == "16"  # Iquitos
    assert G.department_at(-16.5, -68.15) is None  # La Paz, Bolivia
    assert G.department_at(-12.0, -79.5) is None  # mar adentro


def test_hotspots_match_inpe_departments():
    """El INPE (Brasil) asigna país y departamento a cada foco: una referencia que no usa estos límites."""
    by_name = {key(n): c for c, n in department_names().items()}
    ok = bad = foreign_in_peru = 0
    with open(FIX.parent / "geopoly" / "inpe-focos-20261020.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            got = G.department_at(float(r["lat"]), float(r["lon"]))
            if r["pais"] == "Peru":
                ok, bad = (ok + 1, bad) if got == by_name.get(key(r["estado"])) else (ok, bad + 1)
            elif got:
                foreign_in_peru += 1
    assert ok >= 395 and bad <= 6  # 399 de 401: los dos restantes están a 2 km de un límite
    assert foreign_in_peru == 0  # ninguno de Bolivia, Brasil, Colombia, Ecuador o Chile


def test_polygon_parts_go_to_their_department():
    sq = lambda lon, lat, d=0.05: [[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d]]
    geom = {"type": "MultiPolygon", "coordinates": [[sq(-77.0, -12.1)], [sq(-75.73, -14.06)], [sq(-75.73, -14.06, 0.01)]]}
    deps = G.polygon_departments(geom)
    assert set(deps) == {"15", "11"} and deps["11"] > deps["15"] * 1.0  # Lima e Ica, con sus áreas
