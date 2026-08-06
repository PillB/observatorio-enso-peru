"""Contratos de fidelidad numérica.

- ICEN == media exacta de 3 meses de Niño 1+2.
- Percentil: proporción de valores estrictamente menores.
"""

from __future__ import annotations

import math

import pytest

from enso.derived import percentile, rolling_mean_3
from enso.models import MonthlyPoint, Series, SeriesFlag


def _pts(vals: list[float]) -> list[MonthlyPoint]:
    return [
        MonthlyPoint(month=f"2026-{i + 1:02d}", value=v, flag=SeriesFlag.FINAL)
        for i, v in enumerate(vals)
    ]


def test_icen_exact_3_month_mean():
    pts = _pts([1.0, 2.0, 3.0, 4.0, 5.0])
    out = rolling_mean_3(pts)
    assert out[2].value == pytest.approx((1.0 + 2.0 + 3.0) / 3.0)
    assert out[3].value == pytest.approx((2.0 + 3.0 + 4.0) / 3.0)
    assert out[4].value == pytest.approx((3.0 + 4.0 + 5.0) / 3.0)


def test_icen_rounding_to_two_decimals():
    """ICEN se redondea a 2 decimales (igual que series.ts)."""
    pts = _pts([1.005, 2.005, 3.005])
    out = rolling_mean_3(pts)
    assert out[2].value == pytest.approx(2.0, abs=0.01)


def test_icen_window_excludes_outside_three():
    """La ventana es exactamente 3 meses: no incluye el cuarto."""
    pts = _pts([0.0, 0.0, 0.0, 9.0, 0.0, 0.0, 0.0])
    out = rolling_mean_3(pts)
    # En el índice 5 (ventana 4,5,6 = 9,0,0), el 9 afecta; pero no en 6.
    assert out[6].value == pytest.approx(0.0)


def test_percentile_computation():
    """Percentil = (#valores < x) / total."""
    pts = _pts([1.0, 2.0, 3.0, 4.0, 5.0])
    s = Series(
        indicatorId="nino12", label="x", units="degC", scope="coastal",
        points=pts, sourceId="noaa-psl-nino12-anom", checksum="x",
    )
    # 3.0 → 2 valores menores (1,2) → 2/5 = 40.
    assert percentile(s, 3.0) == 40
    # 1.0 → 0 menores → 0.
    assert percentile(s, 1.0) == 0
    # 5.0 → 4 menores → 80.
    assert percentile(s, 5.0) == 80


def test_percentile_none_for_nan():
    pts = _pts([1.0, 2.0, 3.0])
    s = Series(
        indicatorId="x", label="x", units="degC", scope="coastal",
        points=pts, sourceId="x", checksum="x",
    )
    assert percentile(s, None) is None
    assert percentile(s, float("nan")) is None


def test_percentile_empty_series():
    s = Series(
        indicatorId="x", label="x", units="degC", scope="coastal",
        points=[], sourceId="x", checksum="x",
    )
    assert percentile(s, 1.0) is None


def test_icen_handles_negative_values():
    pts = _pts([-1.0, -2.0, -3.0])
    out = rolling_mean_3(pts)
    assert out[2].value == pytest.approx(-2.0)


def test_icen_does_not_smooth_when_window_incomplete():
    """Si faltan datos en la ventana, no se promedian menos de 3."""
    pts = [
        MonthlyPoint(month="2026-01", value=1.0, flag=SeriesFlag.FINAL),
        MonthlyPoint(month="2026-02", value=None, flag=SeriesFlag.FINAL),
        MonthlyPoint(month="2026-03", value=3.0, flag=SeriesFlag.FINAL),
    ]
    out = rolling_mean_3(pts)
    assert out[2].value is None  # no hay 3 valores
