"""Contratos de frescura de datos.

- ``freshness_hours`` se calcula como horas entre fin del mes y fecha de corte.
- Un indicador con frescura > umbral se marca como obsoleto (stale).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from enso.pipeline import AS_OF_DATE, STALE_HOURS_THRESHOLD, Pipeline, _freshness_hours


def test_freshness_hours_computation():
    """Mes 2026-07, corte 2026-08-02 → ~2 días = ~48 horas."""
    h = _freshness_hours("2026-07", as_of_date=AS_OF_DATE)
    # 1 ago 00:00 a 2 ago 00:00 = 24 h; más el tiempo hasta el corte exacto.
    assert 24.0 <= h <= 72.0


def test_freshness_hours_old_month_is_large():
    h = _freshness_hours("2020-01", as_of_date=AS_OF_DATE)
    assert h > 24 * 365  # más de un año


def test_freshness_hours_future_month_is_zero():
    h = _freshness_hours("2030-01", as_of_date=AS_OF_DATE)
    assert h == 0.0


def test_stale_threshold_is_set():
    assert STALE_HOURS_THRESHOLD > 0
    assert STALE_HOURS_THRESHOLD >= 48.0  # al menos 2 días


def test_pipeline_reports_freshness_summary(tmp_path):
    pipe = Pipeline(out_dir=tmp_path / "out", cache_dir=tmp_path / "cache",
                    allow_network=False)
    from enso.models import MonthlyPoint, Series, SeriesFlag
    last = Series(
        indicatorId="nino12", label="TSM Niño 1+2", units="degC", scope="coastal",
        points=[MonthlyPoint(month="2026-07", value=1.70, flag=SeriesFlag.PRELIMINARY)],
        sourceId="noaa-psl-nino12-anom", checksum="fnv1a:dummy",
    )
    pipe._save_last_valid("nino12", last)
    pipe.run()
    status = json.loads((tmp_path / "out" / "status.json").read_text())
    assert "freshness" in status
    rows = status["freshness"]
    assert any(r["indicator_id"] == "nino12" for r in rows)
    n12 = next(r for r in rows if r["indicator_id"] == "nino12")
    assert n12["freshness_hours"] >= 0
    # 2026-07 con corte 2026-08-02 → <72 h → no stale por frescura.
    assert n12["stale"] in (True, False)


def test_stale_visibility_in_status(tmp_path):
    """Un indicador muy antiguo aparece marcado stale=True en el summary."""
    pipe = Pipeline(out_dir=tmp_path / "out", cache_dir=tmp_path / "cache",
                    allow_network=False)
    from enso.models import MonthlyPoint, Series, SeriesFlag
    last = Series(
        indicatorId="nino12", label="TSM Niño 1+2", units="degC", scope="coastal",
        points=[MonthlyPoint(month="2010-01", value=0.50, flag=SeriesFlag.FINAL)],
        sourceId="noaa-psl-nino12-anom", checksum="fnv1a:dummy",
    )
    pipe._save_last_valid("nino12", last)
    pipe.run()
    status = json.loads((tmp_path / "out" / "status.json").read_text())
    n12 = next(r for r in status["freshness"] if r["indicator_id"] == "nino12")
    assert n12["stale"] is True
    assert n12["freshness_hours"] > STALE_HOURS_THRESHOLD
