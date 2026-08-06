"""Contratos de manejo de observaciones faltantes (NaN).

Los huecos deben preservarse a través del cálculo de ICEN (media móvil
de 3 meses), NO rellenarse con valores fabricados.
"""

from __future__ import annotations

import math

import pytest

from enso.derived import rolling_mean_3
from enso.models import MonthlyPoint, SeriesFlag
from enso.normalize import preserve_nan


def _points(values: list[float | None]) -> list[MonthlyPoint]:
    return [
        MonthlyPoint(month=f"2026-{i + 1:02d}", value=v, flag=SeriesFlag.FINAL)
        for i, v in enumerate(values)
    ]


def test_nan_preserved_through_3_month_window():
    """Un hueco en la ventana de 3 meses ⇒ resultado NaN (no se rellena)."""
    pts = _points([1.0, None, 1.0, 1.0, 1.0])
    out = rolling_mean_3(pts)
    # Mes 3 (2026-03): ventana 1.0, None, 1.0 → no hay 3 valores → None.
    assert out[2].value is None
    # Mes 4 (2026-04): ventana None, 1.0, 1.0 → no hay 3 valores → None.
    assert out[3].value is None
    # Mes 5 (2026-05): ventana 1.0, 1.0, 1.0 → 1.0.
    assert out[4].value == pytest.approx(1.0)


def test_no_fabricated_values_at_start():
    """Al inicio de la serie, sin ventana completa, el resultado es None."""
    pts = _points([1.0, 2.0, 3.0, 4.0])
    out = rolling_mean_3(pts)
    assert out[0].value is None  # solo 1 valor
    assert out[1].value is None  # solo 2 valores
    assert out[2].value == pytest.approx(2.0)  # (1+2+3)/3


def test_nan_at_end_preserved():
    pts = _points([1.0, 2.0, 3.0, None, None])
    out = rolling_mean_3(pts)
    assert out[2].value == pytest.approx(2.0)
    assert out[3].value is None
    assert out[4].value is None


def test_preserve_nan_utility():
    out = preserve_nan([1.0, None, float("nan"), 2.0])
    assert out == [1.0, None, None, 2.0]


def test_icen_window_requires_full_3_months():
    """ICEN requiere exactamente 3 meses; 2 meses no bastan."""
    pts = _points([1.5, 1.7])  # sólo 2 meses
    out = rolling_mean_3(pts)
    assert all(p.value is None for p in out)


def test_rolling_mean_does_not_smooth_over_large_gaps():
    """Si hay un hueco grande, no se promedian puntos separados por él."""
    pts = _points([1.0, 2.0, 3.0, None, None, None, None, None, 4.0, 5.0, 6.0])
    out = rolling_mean_3(pts)
    # Los puntos después del hueco, antes de tener 3 valores, son None.
    assert out[8].value is None
    assert out[9].value is None
    assert out[10].value == pytest.approx(5.0)
