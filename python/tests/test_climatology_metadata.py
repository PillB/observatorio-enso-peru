"""Contratos de metadatos de climatología.

Cada indicador debe tener una climatología registrada y no vacía.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from enso.methodology import INDICATORS, INDICATOR_BY_ID
from enso.pipeline import Pipeline


def test_every_indicator_has_climatology():
    for ind in INDICATORS:
        assert ind.climatology, f"{ind.id}: climatología vacía"
        assert isinstance(ind.climatology, str)
        assert len(ind.climatology) >= 4  # no es un placeholder de un char


def test_csv_header_records_climatology(tmp_path):
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
    csv_text = (tmp_path / "out" / "nino12.csv").read_text()
    expected = INDICATOR_BY_ID["nino12"].climatology
    assert f"# climatology={expected}" in csv_text


def test_climatology_lines_are_documented_per_indicator():
    """Cada indicador menciona baseline o metodología reconocida."""
    for ind in INDICATORS:
        c = ind.climatology.lower()
        assert "tbd" not in c
        assert "pendiente" not in c
        # Debe mencionar un periodo o una metodología reconocida.
        assert any(kw.lower() in c for kw in (
            "1981", "1991", "30", "móvil", "movil",
            "adaptativa", "ENFEN", "GODAS",
            "NCEP", "estandarizada", "Reanalysis",
        )), f"{ind.id}: {c}"


def test_threshold_indicators_document_baseline():
    """ICEN y RONI deben declarar umbrales y baseline en sus notas."""
    for ind_id in ("icen", "roni"):
        ind = INDICATOR_BY_ID[ind_id]
        assert ind.thresholds, f"{ind_id} sin umbrales"
        # La metodología menciona el baseline.
        combined = (ind.climatology + " " + ind.notes).lower()
        assert any(kw in combined for kw in ("baseline", "móvil", "movil",
                                              "30 año", "adaptativa")), ind_id
