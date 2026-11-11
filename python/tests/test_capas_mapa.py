"""Capas de las vistas de detalle de los mapas (``tools.build_capas_mapa``) y los archivos que leen del catálogo
(``finos.json`` e ``historia.json`` de ``tools.build_historico``): las funciones con datos de juguete y los archivos
publicados enteros, contra ``eventos.json``.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from collections import Counter
from pathlib import Path

import pytest

from enso.aguas import water_key
from enso.historico.enso import GREAT
from tools import build_capas_mapa as C
from tools import build_historico as B

ROOT = Path(__file__).resolve().parents[2]
PUB = ROOT / "public" / "assets"


def _load(rel: str):
    return json.loads((PUB / rel).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def eventos() -> dict:
    return _load("historico/eventos.json")


# --- Funciones ------------------------------------------------------------------------------------------------------

def test_norm_is_the_key_the_page_uses():
    assert C.norm("  Río   Rímac ") == "rio rimac"
    assert C.norm("Quebrada San Andrés") == C.norm("quebrada san andres")
    assert C.norm("Laguna Ñahuinpuquio") == "laguna nahuinpuquio"


def test_path_drops_degenerate_traces_and_keeps_one_decimal():
    assert C._path([(1.0, 2.0), (1.02, 2.01)]) == ""  # al redondear queda un punto
    assert C._path([(1.0, 2.0), (1.5, 2.3), (1.5, 2.3)]) == "M1 2l0.5 0.3"
    assert C._path([(0, 0), (1, 0), (0, 0)], close=True) == ""  # un anillo necesita tres puntos distintos
    assert C._path([(0, 0), (1, 0), (1, 1), (0, 0)], close=True) == "M0 0l1 0 0 1z"


def test_preferred_name_has_the_accents_then_the_most_uses():
    assert C._preferred(Counter({"Río Rimac": 9, "Río Rímac": 2})) == "Río Rímac"
    assert C._preferred(Counter({"Quebrada Honda": 1, "Quebrada honda": 3})) == "Quebrada honda"


def _catalog(tmp_path: Path, rows: list[dict]) -> Path:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["Ubigeo", "CuerpoAgua", "CuencaCodigo"])
    w.writeheader()
    w.writerows(rows)
    path = tmp_path / "eventos.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("eventos.csv", buf.getvalue())
    return path


def test_named_in_catalog_groups_by_district_and_takes_the_usual_basin(tmp_path):
    path = _catalog(tmp_path, [
        {"Ubigeo": "150118", "CuerpoAgua": "Río Rímac · Quebrada Huaycoloro (Cajamarquilla)", "CuencaCodigo": "137554"},
        {"Ubigeo": "150118", "CuerpoAgua": "Río Rimac", "CuencaCodigo": "137554"},
        {"Ubigeo": "150118", "CuerpoAgua": "Río Rímac", "CuencaCodigo": "137556"},
        {"Ubigeo": "150118", "CuerpoAgua": "Laguna Huacachina", "CuencaCodigo": ""},
        {"Ubigeo": "020101", "CuerpoAgua": "Nevado Huascarán", "CuencaCodigo": "1376"},  # un punto, no un trazo
        {"Ubigeo": "1501", "CuerpoAgua": "Río Rímac", "CuencaCodigo": "137554"},  # sin distrito
        {"Ubigeo": "150101", "CuerpoAgua": "", "CuencaCodigo": "137554"},
    ])
    got = C.named_in_catalog(path)
    rimac = got[("150118", water_key("Río Rímac"))]
    assert rimac["r"] == 3 and rimac["b"] == "137554" and rimac["clase"] == "curso"
    assert rimac["names"] == Counter({"Río Rímac": 2, "Río Rimac": 1})
    assert got[("150118", water_key("Quebrada Huaycoloro"))]["names"] == Counter({"Quebrada Huaycoloro": 1})
    lake = got[("150118", water_key("Laguna Huacachina"))]
    assert lake["clase"] == "laguna" and lake["b"] == ""
    assert not any(code == "020101" or len(code) != 6 for code, _ in got)


def _page(tmp_path: Path, feats: list[dict]) -> Path:
    folder = tmp_path / "manzanas"
    folder.mkdir()
    (folder / "capa57-00000.json").write_text(json.dumps({"features": feats}), encoding="utf-8")
    return folder


def test_blocks_keep_only_the_block_aggregates(tmp_path):
    square = [[[-80.0, -5.0], [-79.99, -5.0], [-79.99, -5.01], [-80.0, -5.01], [-80.0, -5.0]]]
    tiny = [[[-81, -6], [-81.0001, -6], [-81.0001, -6.0001], [-81, -6]]]
    folder = _page(tmp_path, [
        # Un campo de más (como los de las capas por persona del SIGRID) no pasa al archivo.
        {"attributes": {"objectid": 1, "ubigeo": "200101", "nomccpp": "SAN PEDRO DE LOS INCAS", "nriesgo": "MUY ALTO",
                        "pob_total": 12, "viv_part_p": 4, "dni": "00000000"}, "geometry": {"rings": tiny + square}},
        {"attributes": {"objectid": 2, "ubigeo": "200101", "nomccpp": "x", "nriesgo": "Sin evaluar", "pob_total": 3},
         "geometry": {"rings": square}},
        {"attributes": {"objectid": 3, "ubigeo": "240101", "nomccpp": "TUMBES", "nriesgo": "Bajo", "pob_total": None,
                        "viv_part_p": None}, "geometry": {"rings": square}},
        {"attributes": {"objectid": 4, "ubigeo": "200101", "nriesgo": "Alto"}, "geometry": {}},
    ])
    got = C.blocks(folder)
    assert got == [[-5.004, -79.996, "200101", "San Pedro de los Incas", 0, 12, 4],
                   [-5.004, -79.996, "240101", "Tumbes", 3, 0, 0]]
    assert set(C.BLOCK_FIELDS.split(",")) == {"objectid", "ubigeo", "nomccpp", "nriesgo", "pob_total", "viv_part_p"}


# --- Archivos publicados --------------------------------------------------------------------------------------------

def test_published_river_layer():
    doc = _load("capas/rios-mapa.json")
    units = _load("cuencas-mapa.json")["units"]
    districts = _load("historico/mapa.json")["districts"]
    reaches = doc["reaches"]
    assert len(reaches) >= 400
    assert len({(r["b"], r["k"]) for r in reaches}) == len(reaches)
    assert [r["r"] for r in reaches] == sorted((r["r"] for r in reaches), reverse=True)
    for r in reaches:
        assert set(r) <= {"b", "k", "n", "c", "r", "u", "d", "a"}
        assert r["k"] == C.norm(r["n"]) and r["c"] in ("curso", "laguna") and r["r"] >= 1
        assert not r["n"].startswith(("Nevado", "Volcán", "Abra"))
        assert r["b"] == "" or r["b"] in units
        assert r["u"] and all(u in districts for u in r["u"])
        assert re.fullmatch(r"(M-?[\d.]+ -?[\d.]+l[-\d. ]+z?)+", r["d"]), r["n"]
    # El río más nombrado es el Rímac, en su cuenca y por Lima.
    assert (reaches[0]["n"], reaches[0]["b"]) == ("Río Rímac", "137554") and "150101" in reaches[0]["u"]


def test_published_risk_blocks_are_aggregates_inside_the_three_departments():
    doc = _load("capas/manzanas-riesgo.json")
    assert doc["fields"] == ["lat", "lon", "ubigeo", "centroPoblado", "nivel", "poblacion", "viviendas"]
    assert doc["levels"] == C.RISK_LEVELS and doc["url"] == C.SIGRID
    shapes = _load("historico/mapa.json")["districts"]
    assert len(doc["blocks"]) > 500
    for lat, lon, ubigeo, ccpp, level, pob, viv in doc["blocks"]:
        assert ubigeo[:2] in ("14", "20", "24") and ubigeo in shapes
        assert -7.3 < lat < -3.3 and -81.4 < lon < -79.0
        assert 0 <= level < 4 and pob >= 0 and viv >= 0 and isinstance(ccpp, str)
    assert Counter(b[4] for b in doc["blocks"])[0] > 0


def test_fine_points_follow_the_catalogue(eventos):
    X = _load("historico/finos.json")
    n = len(eventos["rows"])
    assert len(X["cuenca"]) == n
    units = _load("cuencas-mapa.json")["units"]
    assert set(X["cuencas"]) <= set(units)
    assert all(0 <= c <= len(X["cuencas"]) for c in X["cuenca"])
    ids = [p[0] for p in X["puntos"]]
    assert ids == sorted(set(ids)) and ids[-1] < n
    assert {p[3] for p in X["puntos"]} <= {0, 1, 3}
    for kind in ("agua", "lugar"):
        assert all(i < n and ni < len(X["nombres"]) for i, ni in X[kind])
    # Lo que dice finos.json de un registro es lo que dice el catálogo de esa fila (eventos.zip).
    with zipfile.ZipFile(PUB / "historico" / "eventos.zip") as z:
        rows = list(csv.DictReader(io.TextIOWrapper(z.open("eventos.csv"), encoding="utf-8-sig")))
    assert len(rows) == n
    water = dict(X["agua"])
    for i in range(0, n, 997):
        r = rows[i]
        assert (X["cuencas"][X["cuenca"][i] - 1] if X["cuenca"][i] else "") == (r["CuencaCodigo"] or "")
        assert (X["nombres"][water[i]] if i in water else "") == r["CuerpoAgua"]
        assert r["Ubigeo"] == eventos["rows"][i][2]


def test_history_rows_count_the_catalogue(eventos):
    H = _load("historico/historia.json")
    assert H["cols"] == list(B.HISTORY_COLS)
    col = {c: i for i, c in enumerate(H["cols"])}
    rows = eventos["rows"]
    for level, n in (("distritos", 6), ("provincias", 4)):
        count = Counter(r[2][:n] for r in rows if len(r[2]) >= n)
        assert {k: v[col["registros"]] for k, v in H[level].items()} == {k: v for k, v in count.items() if k in H[level]}
        assert all(len(k) == n for k in H[level])
    X = _load("historico/finos.json")
    by_basin = Counter(X["cuencas"][c - 1] for c in X["cuenca"] if c)
    assert {k: v[col["registros"]] for k, v in H["cuencas"].items()} == dict(by_basin)
    for level in ("distritos", "provincias", "cuencas"):
        for code, v in H[level].items():
            row = dict(zip(H["cols"], v))
            if level == "cuencas":
                # Una cuenca no tiene años de DesInventar ni población: cuenta temporadas, y su nombre lo da el mapa.
                assert row["aniosCobertura"] is None and row["nombre"] == "" and row["desde"] >= 1500
                assert 1 <= row["aniosConEvento"] <= row["registros"]
            else:
                assert 0 <= row["aniosConEvento"] <= row["aniosCobertura"] <= 46, code
                assert row["nombre"]
            assert row["peligro"] == -1 or 0 <= row["peligro"] < len(H["peligros"])
            assert row["muertos"] >= 0 and row["grandesNinos"] <= len(GREAT)
            assert row["ultimo"] == "" or re.fullmatch(r"\d{4}(-\d{2}){0,2}", row["ultimo"])
