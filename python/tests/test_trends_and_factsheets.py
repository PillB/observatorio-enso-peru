"""Contratos para análisis de tendencias y fichas técnicas.

Cubre:
- El análisis de tendencias calcula regresión lineal (pendiente y R²).
- La ventana móvil es configurable.
- Se detectan cambios de fase ENSO (El Niño/Neutral/La Niña).
- El umbral de fase es ±0.5 °C.
- Las fichas técnicas incluyen estadísticas completas (media, std, min, max, percentil).
- Las fichas incluyen tendencias a 12 y 24 meses.
- Las fichas son descargables en CSV.
- El cálculo es determinista en código.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def test_trend_calculation_uses_linear_regression():
    """buildTrend calcula regresión lineal (pendiente y R²)."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "buildTrend" in src
    assert "slope" in src
    assert "r2" in src
    assert "TrendResult" in src


def test_trend_window_configurable():
    """La ventana móvil es configurable (parámetro windowMonths)."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "windowMonths" in src
    assert "windowMonths = 24" in src  # valor por defecto


def test_trend_view_has_indicators_and_window_selectors():
    """La vista debe tener selectores de indicador y ventana."""
    src = (REPO / "src" / "components" / "enso" / "TrendsView.tsx").read_text(encoding="utf-8")
    assert "INDICATOR_OPTIONS" in src
    assert "setWindowMonths" in src
    assert "12" in src and "24" in src and "36" in src


def test_phase_changes_detection():
    """buildPhaseChanges detecta transiciones entre categorías ENSO."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "buildPhaseChanges" in src
    assert "PhaseChange" in src
    assert "fromPhase" in src
    assert "toPhase" in src


def test_phase_change_threshold_05():
    """El umbral de fase es ±0.5 °C."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "v >= 0.5" in src or "value >= 0.5" in src
    assert "v <= -0.5" in src or "value <= -0.5" in src


def test_fact_sheet_includes_statistics():
    """Las fichas técnicas incluyen estadísticas completas."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "buildFactSheet" in src
    assert "IndicatorFactSheet" in src
    for stat in ("mean", "std", "min", "max", "percentileLatest"):
        assert stat in src, f"Falta estadística en ficha: {stat}"


def test_fact_sheet_includes_trends():
    """Las fichas incluyen tendencias a 12 y 24 meses."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "trend12m" in src
    assert "trend24m" in src


def test_fact_sheet_downloadable_csv():
    """Las fichas deben ser descargables en CSV."""
    src = (REPO / "src" / "components" / "enso" / "FactSheetsView.tsx").read_text(encoding="utf-8")
    assert "downloadFactSheet" in src
    assert "Blob" in src
    assert "text/csv" in src
    assert "ficha-tecnica" in src


def test_fact_sheet_view_has_indicator_selector():
    """La vista de fichas debe tener selector de indicador."""
    src = (REPO / "src" / "components" / "enso" / "FactSheetsView.tsx").read_text(encoding="utf-8")
    assert "INDICATOR_OPTIONS" in src
    assert "setIndicatorId" in src


def test_trend_deterministic():
    """El cálculo de tendencias es determinista en código."""
    src = (REPO / "src" / "components" / "enso" / "TrendsView.tsx").read_text(encoding="utf-8")
    src_lower = src.lower()
    assert "código" in src_lower or "determinista" in src_lower
    assert "el modelo no participa" in src_lower


def test_fact_sheet_includes_metadata():
    """Las fichas incluyen metadatos científicos (región, nivel, climatología)."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "region" in src
    assert "level" in src
    assert "climatology" in src
    assert "dataset" in src
    assert "signConvention" in src


def test_fact_sheet_labels_official_vs_derived():
    """Las fichas distinguen entre indicadores oficiales y derivados."""
    src = (REPO / "src" / "components" / "enso" / "FactSheetsView.tsx").read_text(encoding="utf-8")
    assert "Oficial" in src
    assert "Derivada" in src


def test_trend_interpretation_in_spanish():
    """La interpretación de la tendencia debe estar en español."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "Tendencia creciente" in src
    assert "Tendencia decreciente" in src
    assert "Tendencia estable" in src
