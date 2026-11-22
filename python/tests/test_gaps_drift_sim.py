"""Huecos de cobertura del simulador de deriva (``tools/drift_sim.py``) que dejaban vivas mutaciones del propio
simulador. Cada prueba cierra uno:

* ``test_header_reorder_moves_*``: la mutación «header-reorder» debe mover cabecera **y** datos a la vez. Si las filas
  de datos quedaran sin mover (``_swap_data_rows`` con otro número de columnas), la mutación dejaría de conservar el
  contenido y nada lo notaba. Se comprueba contra las filas reales de ``cpc-soi.txt`` y ``cpc-oni.txt`` corridas a
  mano. Esta prueba encontró un error del simulador: en los archivos con varias tablas (SOI, Tahití, Darwin, vientos
  en 850 hPa) solo se movía la cabecera de la última, y las filas de las demás quedaban corridas bajo su cabecera
  sin mover (un cambio de contenido, no una mutación que lo conserva).
* ``test_header_reorder_verdict_positional_month_tables y test_header_reorder_verdict_tables_read_by_column_name``: fija el veredicto de «header-reorder» por fuente, con su razón: los
  lectores de tablas mensuales leen los meses por posición (la guardia de regresión ve la historia reescrita); los de
  ONI, SSTOI, semanal y contenido de calor leen por nombre de columna (publican lo mismo; solo cambia la huella).
* ``test_rss_to_atom_keeps_dc_subject_as_category``: el paso de RSS a Atom lleva ``<dc:subject>`` a
  ``<category>`` (GDACS no trae ``<category>``: su tipo de evento va solo en ``dc:subject``).
* ``test_diff_reads_json_text_items``: el informe de un SILENT-WRONG compara ya leídas las entradas que son texto JSON
  (así nombra el campo que cambió y no la entrada entera).
* ``test_arcgis_web_mercator_projects_every_vertex``: la mutación «arcgis-web-mercator» proyecta los vértices
  ``[lon, lat]`` de los polígonos reales del SENAMHI; sin la proyección de puntos la mutación no cambiaba nada.
"""

from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET

import pytest

from enso import news as N
from tools import drift_sim as D

TABLE = {"family": "table"}


def _line_tokens(body: bytes, startswith: str) -> list[str]:
    """Tokens de la primera línea que empieza (sin sangría) con ``startswith``."""
    return next(l.split() for l in body.decode().splitlines() if l.strip().startswith(startswith))


def _all_line_tokens(body: bytes, startswith: str) -> list[list[str]]:
    """Tokens de cada línea que empieza (sin sangría) con ``startswith``."""
    return [l.split() for l in body.decode().splitlines() if l.strip().startswith(startswith)]


def test_header_reorder_moves_header_and_data_on_real_soi():
    body = (D.FIXTURES / "cpc-soi.txt").read_bytes()
    out = D.MUTATIONS["header-reorder"].apply(body, TABLE)
    # 12 columnas (par, ≥ 4): se intercambian de a dos las dos primeras con las dos últimas.
    # Cabecera real: YEAR JAN FEB MAR … OCT NOV DEC → YEAR NOV DEC MAR … OCT JAN FEB, en las dos tablas del archivo
    # (anomalía y anomalía estandarizada): cada tabla mueve su cabecera con sus datos.
    swapped = ["YEAR", "NOV", "DEC", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "JAN", "FEB"]
    assert _all_line_tokens(out, "YEAR") == [swapped, swapped]
    # Filas reales 1951 de las dos tablas, movidas a mano:
    #    2.5  1.5 -0.2 -0.5 -1.1 0.3 -1.7 -0.4 -1.8 -1.6 -1.3 -1.2 → -1.3 -1.2 -0.2 … -1.6  2.5  1.5
    #    1.5  0.9 -0.1 -0.3 -0.7 0.2 -1.0 -0.2 -1.1 -1.0 -0.8 -0.7 → -0.8 -0.7 -0.1 … -1.0  1.5  0.9
    assert _all_line_tokens(out, "1951") == [
        ["1951", "-1.3", "-1.2", "-0.2", "-0.5", "-1.1", "0.3", "-1.7", "-0.4", "-1.8", "-1.6", "2.5", "1.5"],
        ["1951", "-0.8", "-0.7", "-0.1", "-0.3", "-0.7", "0.2", "-1.0", "-0.2", "-1.1", "-1.0", "1.5", "0.9"]]


def test_header_reorder_moves_single_columns_on_real_oni():
    body = (D.FIXTURES / "cpc-oni.txt").read_bytes()
    out = D.MUTATIONS["header-reorder"].apply(body, TABLE)
    # 2 columnas de valores: se intercambian de a una. «SEAS YR TOTAL ANOM» → «SEAS YR ANOM TOTAL».
    assert _line_tokens(out, "SEAS") == ["SEAS", "YR", "ANOM", "TOTAL"]
    # Fila real «DJF 1950 25.01 -1.32» → «DJF 1950 -1.32 25.01».
    assert _line_tokens(out, "DJF 1950") == ["DJF", "1950", "-1.32", "25.01"]


POSITIONAL = ("cpc-soi", "cpc-tahiti", "cpc-darwin", "cpc-wpac850", "cpc-cpac850", "cpc-epac850")
BY_NAME = ("cpc-oni", "cpc-sstoi", "cpc-wksst", "cpc-heat")


@pytest.fixture(scope="module")
def reorder(tmp_path_factory):
    ts = D.build_targets(work=tmp_path_factory.mktemp("gaps-drift"), only=set(POSITIONAL + BY_NAME))
    ts = [t for t in ts if t.kind == "source"]
    return {r.target: r for r in D.simulate(ts, ["header-reorder"])}


@pytest.mark.parametrize("sid", POSITIONAL)
def test_header_reorder_verdict_positional_month_tables(reorder, sid):
    # Estos lectores leen los meses por posición: con la cabecera y los datos movidos, en «enero» queda el valor de
    # noviembre (SOI 1951: -1.3 en lugar de 2.5) y la guardia de regresión ve la historia reescrita. Es un aviso
    # (no un error): la fuente se publica con aviso, no se pierde.
    r = reorder[sid]
    assert (r.verdict, r.signals) == (D.NOISY, ("warning:history-rewritten",))


@pytest.mark.parametrize("sid", BY_NAME)
def test_header_reorder_verdict_tables_read_by_column_name(reorder, sid):
    # Estos lectores siguen los nombres de las columnas: publican exactamente lo mismo y solo cambia la huella del
    # formato (aviso format-drift). Si los datos no se movieran con la cabecera, el ONI leería «ANOM» = 25,01 y daría
    # un error de rango.
    r = reorder[sid]
    assert (r.verdict, r.signals) == (D.NOISY, ("warning:format-drift",))


def test_rss_to_atom_keeps_dc_subject_as_category():
    body = (D.FIXTURES / "news-gdacs.xml").read_bytes()
    assert b"<category" not in body  # GDACS no trae <category>: el tipo de evento va solo en <dc:subject>
    out = D.MUTATIONS["rss-to-atom"].apply(body, {"family": "xml"})
    A = "{http://www.w3.org/2005/Atom}"
    entries = ET.fromstring(out).findall(f"{A}entry")
    # 248 <item> reales, cada uno con un <dc:subject>; el primero es «EQ1» (sismo en Vanuatu, 20/10/2026).
    assert len(entries) == 248
    assert [c.get("term") for c in entries[0].findall(f"{A}category")] == ["EQ1"]
    assert all(len(e.findall(f"{A}category")) == 1 for e in entries)


def test_diff_reads_json_text_items():
    # Lo que ``feed_target`` publica: ``entries`` es una lista de textos JSON (``canon`` de cada entrada).
    base = D.canon({"entries": [D.canon({"id": "a", "title": "Huaico"})]})
    got = D.canon({"entries": [D.canon({"id": "a", "title": "Huayco"})]})
    # Leídas, la primera clave distinta (en orden) es «title» de la entrada 0.
    assert D._diff(base, got) == "$.entries[0].title: Huaico → Huayco"


def test_arcgis_web_mercator_projects_every_vertex():
    f = N.FEED_BY_ID["senamhi-lluvias"]
    body = (D.FIXTURES / f.fixture).read_bytes()
    out = json.loads(D.MUTATIONS["arcgis-web-mercator"].apply(body, {"adapter": "arcgis"}))
    first = out["features"][0]["geometry"]["coordinates"][0][0]
    # Vértice real [-78.11, -8.175], R = 6378137 m:
    #   x = radianes(-78.11) · R = -1.3632767 · 6378137 = -8695165.4
    #   y = ln(tan(45° + (-8.175°)/2)) · R = ln(tan(40.9125°)) · R = ln(0.8666091) · R = -0.1431673 · R = -913140.4
    assert first == [-8695165.4, -913140.4]
    # Ningún vértice queda en grados (todos en metros, lejos de ±180).
    rings = [ring for feat in out["features"] for ring in _rings(feat["geometry"])]
    assert rings and all(abs(p[0]) > 180 for ring in rings for p in ring)


def _rings(geom: dict) -> list:
    """Los anillos de un Polygon o MultiPolygon."""
    c = geom["coordinates"]
    return c if geom["type"] == "Polygon" else [ring for poly in c for ring in poly]


def test_mercator_formula_on_the_equator_and_greenwich():
    # Punto (0, 0): x = 0, y = ln(tan(45°)) · R = ln(1) · R = 0. Punto (180, 0): x = π · R = 20037508.3.
    assert D._mercator(0.0, 0.0) == (0.0, 0.0)
    assert D._mercator(180.0, 0.0) == (round(math.pi * 6378137.0, 1), 0.0)
