"""Contratos de datos preliminares vs finales.

- La marca preliminar fluye desde el dato fuente hasta el CSV/estado.
- Una revisión posterior actualiza la marca a 'final'.
"""

from __future__ import annotations

import json

import pytest

from enso.models import MonthlyPoint, Series, SeriesFlag
from enso.derived import rolling_mean_3


def test_preliminary_flag_flows_through_rolling_mean():
    pts = [
        MonthlyPoint(month="2026-05", value=1.0, flag=SeriesFlag.FINAL),
        MonthlyPoint(month="2026-06", value=2.0, flag=SeriesFlag.PRELIMINARY),
        MonthlyPoint(month="2026-07", value=3.0, flag=SeriesFlag.PRELIMINARY),
    ]
    out = rolling_mean_3(pts)
    # El último punto conserva la marca preliminar.
    assert out[2].flag == SeriesFlag.PRELIMINARY


def test_revision_updates_preliminary_to_final():
    """Una revisión que llegue con flag 'final' actualiza la marca."""
    pts = [
        MonthlyPoint(month="2026-05", value=1.0, flag=SeriesFlag.FINAL),
        MonthlyPoint(month="2026-06", value=2.0, flag=SeriesFlag.FINAL),  # revisado
        MonthlyPoint(month="2026-07", value=3.0, flag=SeriesFlag.PRELIMINARY),
    ]
    out = rolling_mean_3(pts)
    assert out[1].flag == SeriesFlag.FINAL
    assert out[2].flag == SeriesFlag.PRELIMINARY


def test_csv_records_preliminary_flag(tmp_path):
    from enso.pipeline import Pipeline
    pipe = Pipeline(out_dir=tmp_path / "out", cache_dir=tmp_path / "cache",
                    allow_network=False)
    last = Series(
        indicatorId="nino12", label="TSM Niño 1+2", units="degC", scope="coastal",
        points=[
            MonthlyPoint(month="2026-06", value=1.50, flag=SeriesFlag.PRELIMINARY),
        ],
        sourceId="noaa-psl-nino12-anom", checksum="fnv1a:dummy",
    )
    pipe._save_last_valid("nino12", last)
    pipe.run()
    csv_text = (tmp_path / "out" / "nino12.csv").read_text()
    assert "preliminary" in csv_text


def test_status_records_preliminary_flag(tmp_path):
    from enso.pipeline import Pipeline
    pipe = Pipeline(out_dir=tmp_path / "out", cache_dir=tmp_path / "cache",
                    allow_network=False)
    last = Series(
        indicatorId="nino12", label="TSM Niño 1+2", units="degC", scope="coastal",
        points=[
            MonthlyPoint(month="2026-07", value=1.70, flag=SeriesFlag.PRELIMINARY),
        ],
        sourceId="noaa-psl-nino12-anom", checksum="fnv1a:dummy",
    )
    pipe._save_last_valid("nino12", last)
    # ICEN deriva de nino12.
    from enso.derived import rolling_mean_3
    icen_pts = rolling_mean_3(last.points * 3) if len(last.points) == 1 else rolling_mean_3(last.points)
    icen = Series(
        indicatorId="icen", label="ICEN", units="degC", scope="coastal",
        points=icen_pts or [MonthlyPoint(month="2026-07", value=None, flag=SeriesFlag.PRELIMINARY)],
        sourceId="enfen-imarpe-icen", checksum="fnv1a:dummy",
    )
    pipe._save_last_valid("icen", icen)
    pipe.run()
    status = json.loads((tmp_path / "out" / "status.json").read_text())
    assert status["coastal"]["preliminary"] is True


def test_flag_enum_values():
    assert SeriesFlag.FINAL.value == "final"
    assert SeriesFlag.PRELIMINARY.value == "preliminary"
