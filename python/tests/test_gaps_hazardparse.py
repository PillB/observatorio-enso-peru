"""Huecos de cobertura de enso.hazardparse que dejaban vivas dos mutaciones.

- ``_firms_check_rows``: el umbral de focos fuera de Sudamérica (5 % de las filas numéricas) no se probaba en su
  borde; subirlo a 50 % no rompía ninguna prueba. ``test_firms_swapped_rows_threshold_edge`` lo prueba justo debajo
  y justo encima con la captura real del CSV de FIRMS (tests/fixtures/sources/news-firms-focos.csv) y filas con
  latitud y longitud intercambiadas.
- ``_in_box``: ninguna prueba ponía un punto justo al este de un recuadro, así que ensanchar el borde oriental en
  30° sobrevivía. ``test_firms_point_just_east_of_south_america_box_is_outside`` lo hace con el recuadro de FIRMS
  (borde este −30°) y ``test_arcgis_layer_shifted_east_of_peru_is_rejected`` con el recuadro holgado del Perú
  (borde este −66°) sobre la capa real de avisos de lluvia del SENAMHI. Lo mismo con el borde sur: bajar el límite
  sur del recuadro en 30° sobrevivía; ``test_firms_point_just_south_of_south_america_box_is_outside`` pone focos
  justo al sur de −60°.
"""

from __future__ import annotations

import json

import pytest

from conftest import FIX
from enso import hazardparse as H
from enso.feedparse import FeedError

FIRMS_CSV = FIX / "news-firms-focos.csv"
LLUVIAS = FIX / "news-senamhi-lluvias.json"


def _firms_lines():
    head, *rows = FIRMS_CSV.read_text().strip().split("\n")
    return head, rows


def _swap(row: str) -> str:
    lat, lon, rest = row.split(",", 2)
    return f"{lon},{lat},{rest}"


def _east(row: str, lon: str) -> str:
    lat, _, rest = row.split(",", 2)
    return f"{lat},{lon},{rest}"


def test_firms_fixture_is_all_inside_south_america():
    # Invariante de la captura real: sus 459 focos van de lat −17,93 a 0,90 y de lon −79,80 a −68,21 (Perú y
    # vecinos), dentro del recuadro de Sudamérica (−60…15, −95…−30). Si no, las cuentas de abajo no valen.
    head, rows = _firms_lines()
    assert len(rows) == 459
    assert H.parse((head + "\n" + "\n".join(rows)).encode(), "x", "firms").items


@pytest.mark.parametrize("swapped,fails", [(22, False), (23, True)])
def test_firms_swapped_rows_threshold_edge(swapped, fails):
    # 459 filas numéricas; el umbral es outside > 459 * 0,05 = 22,95. Una fila intercambiada queda con
    # lat = su longitud (≤ −68,2 < −60), fuera del recuadro. 22 fuera pasa; 23 fuera es «intercambiadas».
    head, rows = _firms_lines()
    rows = [_swap(r) for r in rows[:swapped]] + rows[swapped:]
    body = (head + "\n" + "\n".join(rows)).encode()
    if fails:
        with pytest.raises(FeedError, match="23 de 459 focos .* caen fuera de Sudamérica"):
            H.parse(body, "x", "firms")
    else:
        assert H.parse(body, "x", "firms").items


@pytest.mark.parametrize("lon,fails", [("-30.0", False), ("-29.9", True)])
def test_firms_point_just_east_of_south_america_box_is_outside(lon, fails):
    # 23 filas movidas al meridiano −30,0 (borde este, incluido) siguen dentro; a −29,9 (0,1° al este, en el
    # Atlántico) caen fuera: 23 > 22,95 (ver arriba) y el CSV se rechaza.
    head, rows = _firms_lines()
    rows = [_east(r, lon) for r in rows[:23]] + rows[23:]
    body = (head + "\n" + "\n".join(rows)).encode()
    if fails:
        with pytest.raises(FeedError, match="23 de 459 focos"):
            H.parse(body, "x", "firms")
    else:
        assert H.parse(body, "x", "firms").items


def _south(row: str, lat: str) -> str:
    _, rest = row.split(",", 1)
    return f"{lat},{rest}"


@pytest.mark.parametrize("lat,fails", [("-60.0", False), ("-60.1", True)])
def test_firms_point_just_south_of_south_america_box_is_outside(lat, fails):
    # 23 filas movidas al paralelo −60,0 (borde sur, incluido; su longitud real −79,8…−68,2 sigue dentro de
    # −95…−30) siguen dentro; a −60,1 (0,1° al sur, mar de Drake) caen fuera: 23 > 22,95 y el CSV se rechaza.
    head, rows = _firms_lines()
    rows = [_south(r, lat) for r in rows[:23]] + rows[23:]
    body = (head + "\n" + "\n".join(rows)).encode()
    if fails:
        with pytest.raises(FeedError, match="23 de 459 focos"):
            H.parse(body, "x", "firms")
    else:
        assert H.parse(body, "x", "firms").items


def _shift_x(c, dx):
    if isinstance(c[0], (int, float)):
        return [c[0] + dx, *c[1:]]
    return [_shift_x(x, dx) for x in c]


def test_arcgis_layer_shifted_east_of_peru_is_rejected():
    # La capa real tiene 920 puntos de lon −81,328 a −68,652. Corrida 16° al este queda en −65,328…−52,652:
    # todos al este del borde −66 del recuadro holgado del Perú (−65,328 > −66), 920 de 920 fuera (Brasil/Bolivia).
    data = json.loads(LLUVIAS.read_bytes())
    for feat in data["features"]:
        feat["geometry"]["coordinates"] = _shift_x(feat["geometry"]["coordinates"], 16.0)
    with pytest.raises(FeedError, match=r"no está en el Perú \(920 de 920 puntos fuera"):
        H.parse(json.dumps(data).encode(), "https://x/MapServer/5/query", "arcgis")
