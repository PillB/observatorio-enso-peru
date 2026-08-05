"""Contratos de conversión de longitud 0..360 <-> -180..180."""

from __future__ import annotations

import math

import pytest

from enso.normalize import to_negative, to_positive


@pytest.mark.parametrize("pos,neg", [
    (0.0, 0.0),
    (90.0, 90.0),
    (180.0, 180.0),
    (270.0, -90.0),   # 270°E == 90°O
    (360.0, 0.0),     # 360° == 0°
    (359.0, -1.0),
    (181.0, -179.0),
])
def test_to_negative_round_trip(pos, neg):
    assert to_negative(pos) == pytest.approx(neg)


@pytest.mark.parametrize("neg,pos", [
    (0.0, 0.0),
    (90.0, 90.0),
    (-90.0, 270.0),
    (-180.0, 180.0),
    (-1.0, 359.0),
    (180.0, 180.0),
])
def test_to_positive_round_trip(neg, pos):
    assert to_positive(neg) == pytest.approx(pos)


def test_round_trip_negative_to_positive_to_negative():
    for lon in [-179.0, -90.0, -1.0, 0.0, 90.0, 179.0, 180.0]:
        rt = to_negative(to_positive(lon))
        assert rt == pytest.approx(lon)


def test_round_trip_positive_to_negative_to_positive():
    for lon in [0.0, 1.0, 90.0, 180.0, 181.0, 270.0, 359.0, 360.0]:
        rt = to_positive(to_negative(lon))
        # Compara módulo 360.
        assert (rt - lon) % 360.0 == pytest.approx(0.0)


def test_270_east_equals_90_west():
    """Caso paradigmático: 270°E es exactamente 90°O."""
    assert to_negative(270.0) == -90.0
    assert to_positive(-90.0) == 270.0


def test_nan_preserved():
    assert math.isnan(to_negative(float("nan")))
    assert math.isnan(to_positive(float("nan")))


def test_overflow_wraps_modulo_360():
    """Longitudes fuera de [0, 360] se normalizan módulo 360."""
    assert to_negative(720.0) == 0.0
    assert to_negative(450.0) == 90.0
    assert to_positive(-450.0) == 270.0
