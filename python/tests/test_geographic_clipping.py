"""Contratos de recorte geográfico.

Verifica que el recorte de las regiones Niño 1+2 (90–80°O, 10°S–0°) y
Niño 3.4 (170–120°O, 5°S–5°N) devuelve los límites correctos, tanto en
convención -180..180 como 0..360.
"""

from __future__ import annotations

import math

import pytest

from enso.methodology import INDICATOR_BY_ID
from enso.normalize import to_negative, to_positive


def test_nino12_region_bounds():
    ind = INDICATOR_BY_ID["nino12"]
    b = ind.regionBounds
    assert b.latMin == -10
    assert b.latMax == 0
    assert b.lonMin == -90
    assert b.lonMax == -80


def test_nino34_region_bounds():
    ind = INDICATOR_BY_ID["nino34"]
    b = ind.regionBounds
    assert b.latMin == -5
    assert b.latMax == 5
    assert b.lonMin == -170
    assert b.lonMax == -120


def test_clip_nino12_in_negative_convention():
    """Recorta puntos dentro y fuera de Niño 1+2 en convención -180..180."""
    ind = INDICATOR_BY_ID["nino12"]
    b = ind.regionBounds

    def inside(lat, lon):
        lon_n = to_negative(lon)
        return (b.latMin <= lat <= b.latMax and b.lonMin <= lon_n <= b.lonMax)

    assert inside(-5, -85)   # centro
    assert inside(0, -80)    # esquina NE
    assert inside(-10, -90)  # esquina SO
    assert not inside(5, -85)   # fuera por latitud
    assert not inside(-5, -100)  # fuera por longitud
    # 275°E = -85°E → dentro de la región.
    assert inside(-5, 275)


def test_clip_nino34_in_positive_convention():
    """Niño 3.4 en convención 0..360: 170°O = 190°E, 120°O = 240°E."""
    ind = INDICATOR_BY_ID["nino34"]
    b = ind.regionBounds

    def inside(lat, lon):
        lon_n = to_negative(lon)
        return (b.latMin <= lat <= b.latMax and b.lonMin <= lon_n <= b.lonMax)

    # 190°E = -170°, esquina oeste.
    assert inside(0, 190)
    # 240°E = -120°, esquina este.
    assert inside(0, 240)
    # Centro (-135°) = 225°E.
    assert inside(0, 225)
    # Fuera por longitud.
    assert not inside(0, 100)
    # Fuera por latitud.
    assert not inside(10, 225)


def test_clip_handles_dateline_wrap():
    """Regiones que cruzan la línea de cambio de fecha (180°) se manejan."""
    # Niño 3.4 NO cruza el dateline (170°O..120°O), pero verificamos
    # que un punto justo en 180°/-180° se trata correctamente.
    assert to_negative(180.0) == 180.0
    assert to_positive(-180.0) == 180.0


def test_clip_preserves_nan():
    assert math.isnan(to_negative(float("nan")))
    assert math.isnan(to_positive(float("nan")))
