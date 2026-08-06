"""Contratos de paridad CSV ↔ serie en memoria.

El CSV escrito por el pipeline debe contener exactamente los mismos
valores (al redondeo declarado) que la serie en memoria.
"""

from __future__ import annotations

import csv
import io
import json

import pytest

from enso.models import MonthlyPoint, Series, SeriesFlag
from enso.pipeline import Pipeline


def _read_csv_values(path) -> list[tuple[str, float | None, str]]:
    rows: list[tuple[str, float | None, str]] = []
    in_data = False
    for ln in path.read_text().splitlines():
        if ln.startswith("# "):
            continue
        if not in_data:
            if ln.strip() == "month,value,flag":
                in_data = True
            continue
        if not ln.strip():
            continue
        r = next(csv.reader(io.StringIO(ln)))
        month, raw, flag = r
        val = None if raw == "" else float(raw)
        rows.append((month, val, flag))
    return rows


def test_csv_matches_in_memory_series(tmp_path):
    pipe = Pipeline(out_dir=tmp_path / "out", cache_dir=tmp_path / "cache",
                    allow_network=False)
    points = [
        MonthlyPoint(month="2026-05", value=1.30, flag=SeriesFlag.FINAL),
        MonthlyPoint(month="2026-06", value=1.50, flag=SeriesFlag.PRELIMINARY),
        MonthlyPoint(month="2026-07", value=1.70, flag=SeriesFlag.PRELIMINARY),
        MonthlyPoint(month="2026-08", value=None, flag=SeriesFlag.PRELIMINARY),
    ]
    series = Series(
        indicatorId="nino12", label="TSM Niño 1+2", units="degC", scope="coastal",
        points=points, sourceId="noaa-psl-nino12-anom", checksum="fnv1a:dummy",
    )
    pipe._save_last_valid("nino12", series)
    pipe.run()

    rows = _read_csv_values(tmp_path / "out" / "nino12.csv")
    assert len(rows) >= len(points)
    for (m, v, f), p in zip(rows, points):
        assert m == p.month
        if p.value is None:
            assert v is None
        else:
            assert v == pytest.approx(p.value, abs=1e-4)
        assert f == p.flag.value


def test_csv_checksum_header_matches_series_checksum(tmp_path):
    pipe = Pipeline(out_dir=tmp_path / "out", cache_dir=tmp_path / "cache",
                    allow_network=False)
    points = [
        MonthlyPoint(month="2026-06", value=1.50, flag=SeriesFlag.FINAL),
        MonthlyPoint(month="2026-07", value=1.70, flag=SeriesFlag.PRELIMINARY),
        MonthlyPoint(month="2026-08", value=None, flag=SeriesFlag.PRELIMINARY),
    ]
    series = Series(
        indicatorId="nino12", label="TSM Niño 1+2", units="degC", scope="coastal",
        points=points, sourceId="noaa-psl-nino12-anom", checksum="fnv1a:dummy",
    )
    pipe._save_last_valid("nino12", series)
    pipe.run()
    csv_text = (tmp_path / "out" / "nino12.csv").read_text()
    # El checksum FNV-1a debe estar en la cabecera.
    assert "# checksum=fnv1a:" in csv_text
    # Y coincide con el recalculado a partir de la serie persistida.
    from enso.pipeline import _checksum
    recomputed = _checksum("nino12", points)
    assert f"# checksum={recomputed}" in csv_text


def test_csv_file_sha256_trailer_present(tmp_path):
    pipe = Pipeline(out_dir=tmp_path / "out", cache_dir=tmp_path / "cache",
                    allow_network=False)
    series = Series(
        indicatorId="nino12", label="TSM Niño 1+2", units="degC", scope="coastal",
        points=[MonthlyPoint(month="2026-06", value=1.50, flag=SeriesFlag.FINAL)],
        sourceId="noaa-psl-nino12-anom", checksum="fnv1a:dummy",
    )
    pipe._save_last_valid("nino12", series)
    pipe.run()
    csv_text = (tmp_path / "out" / "nino12.csv").read_text()
    assert "# file_sha256=" in csv_text


def test_csv_metadata_headers_present(tmp_path):
    pipe = Pipeline(out_dir=tmp_path / "out", cache_dir=tmp_path / "cache",
                    allow_network=False)
    series = Series(
        indicatorId="nino12", label="TSM Niño 1+2", units="degC", scope="coastal",
        points=[MonthlyPoint(month="2026-06", value=1.50, flag=SeriesFlag.FINAL)],
        sourceId="noaa-psl-nino12-anom", checksum="fnv1a:dummy",
    )
    pipe._save_last_valid("nino12", series)
    pipe.run()
    csv_text = (tmp_path / "out" / "nino12.csv").read_text()
    for header in (
        "# indicator_id=",
        "# label=",
        "# units=",
        "# scope=",
        "# source_id=",
        "# checksum=",
        "# data_version=",
        "# as_of_month=",
        "# climatology=",
        "# sign_convention=",
    ):
        assert header in csv_text
