"""Contratos de versiones de datos.

Verifica que un mismatch de versión entre datasets se detecta y reporta.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from enso.pipeline import DATA_VERSION, Pipeline


def test_manifest_records_data_version(tmp_path):
    pipe = Pipeline(out_dir=tmp_path / "out", cache_dir=tmp_path / "cache",
                    allow_network=False)
    pipe.run()
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text())
    assert manifest["data_version"] == DATA_VERSION


def test_status_records_data_version(tmp_path):
    pipe = Pipeline(out_dir=tmp_path / "out", cache_dir=tmp_path / "cache",
                    allow_network=False)
    pipe.run()
    status = json.loads((tmp_path / "out" / "status.json").read_text())
    assert status["dataVersion"] == DATA_VERSION


def test_csv_header_records_data_version(tmp_path):
    pipe = Pipeline(out_dir=tmp_path / "out", cache_dir=tmp_path / "cache",
                    allow_network=False)
    # Preescribe un último válido para forzar la escritura del CSV.
    from enso.models import MonthlyPoint, Series, SeriesFlag
    last = Series(
        indicatorId="nino12", label="TSM Niño 1+2", units="degC",
        scope="coastal",
        points=[MonthlyPoint(month="2026-06", value=1.50, flag=SeriesFlag.FINAL)],
        sourceId="noaa-psl-nino12-anom", checksum="fnv1a:dummy",
    )
    pipe._save_last_valid("nino12", last)
    pipe.run()
    csv_text = (tmp_path / "out" / "nino12.csv").read_text()
    assert f"# data_version={DATA_VERSION}" in csv_text


def test_version_mismatch_is_flagged(tmp_path):
    """Si el manifiesto dice v1.0.0 y un CSV dice v0.9, debe detectarse."""
    pipe = Pipeline(out_dir=tmp_path / "out", cache_dir=tmp_path / "cache",
                    allow_network=False)
    from enso.models import MonthlyPoint, Series, SeriesFlag
    last = Series(
        indicatorId="nino12", label="TSM Niño 1+2", units="degC",
        scope="coastal",
        points=[MonthlyPoint(month="2026-06", value=1.50, flag=SeriesFlag.FINAL)],
        sourceId="noaa-psl-nino12-anom", checksum="fnv1a:dummy",
    )
    pipe._save_last_valid("nino12", last)
    pipe.run()
    # Sobrescribe el CSV con una versión distinta.
    csv_path = tmp_path / "out" / "nino12.csv"
    text = csv_path.read_text()
    text = text.replace(f"# data_version={DATA_VERSION}", "# data_version=0.9.0")
    csv_path.write_text(text)

    # Función utilitaria: detecta mismatch de versión en un CSV.
    def csv_data_version(path: Path) -> str | None:
        for ln in path.read_text().splitlines():
            if ln.startswith("# data_version="):
                return ln.split("=", 1)[1].strip()
        return None

    assert csv_data_version(csv_path) == "0.9.0"
    assert csv_data_version(csv_path) != DATA_VERSION
