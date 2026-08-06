"""Contratos para caja de bigotes y correlación móvil.

Cubre:
- La caja de bigotes agrupa valores por fase ENSO (El Niño/Neutral/La Niña).
- Calcula mediana, cuartiles Q1/Q3, bigotes (1.5×RIC) y atípicos.
- Usa Niño 3.4 ±0.5 como referencia de fase.
- La correlación móvil calcula Pearson en ventanas temporales.
- La ventana es configurable.
- El cálculo es determinista en código.
- Las vistas tienen selectores de indicador y ventana.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def test_box_plot_groups_by_phase():
    """buildBoxPlot agrupa valores por fase ENSO (El Niño/Neutral/La Niña)."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "buildBoxPlot" in src
    assert "BoxStats" in src
    assert "BoxPlotResult" in src
    assert "El Niño" in src
    assert "Neutral" in src
    assert "La Niña" in src


def test_box_plot_uses_nino34_as_phase_reference():
    """La caja de bigotes usa Niño 3.4 ±0.5 como referencia de fase."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "n34" in src
    assert "0.5" in src


def test_box_plot_calculates_quartiles():
    """La caja calcula mediana, Q1, Q3 y bigotes (1.5×RIC)."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "q1" in src
    assert "median" in src
    assert "q3" in src
    assert "whiskerMin" in src
    assert "whiskerMax" in src
    assert "1.5" in src  # 1.5×RIC
    assert "outliers" in src


def test_box_plot_view_has_indicator_selector():
    """La vista debe tener selector de indicador."""
    src = (REPO / "src" / "components" / "enso" / "BoxPlotView.tsx").read_text(encoding="utf-8")
    assert "INDICATOR_OPTIONS" in src
    assert "setIndicatorId" in src
    assert "nino34" in src and "nino12" in src and "icen" in src


def test_box_plot_view_has_svg_chart():
    """La vista debe tener un gráfico SVG de caja de bigotes."""
    src = (REPO / "src" / "components" / "enso" / "BoxPlotView.tsx").read_text(encoding="utf-8")
    assert "BoxPlotChart" in src
    assert "svg" in src.lower()


def test_box_plot_deterministic():
    """El cálculo de la caja de bigotes es determinista en código."""
    src = (REPO / "src" / "components" / "enso" / "BoxPlotView.tsx").read_text(encoding="utf-8")
    src_lower = src.lower()
    assert "código" in src_lower or "determinista" in src_lower
    assert "el modelo no participa" in src_lower


def test_rolling_correlation_uses_pearson():
    """buildRollingCorrelations calcula Pearson en ventanas móviles."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "buildRollingCorrelations" in src
    assert "RollingCorrelationPoint" in src
    assert "pearson" in src


def test_rolling_correlation_window_configurable():
    """La ventana de correlación móvil es configurable."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "windowMonths" in src
    assert "windowMonths = 36" in src  # valor por defecto


def test_rolling_correlation_view_has_window_selector():
    """La vista debe tener selector de ventana."""
    src = (REPO / "src" / "components" / "enso" / "RollingCorrelationView.tsx").read_text(encoding="utf-8")
    assert "setWindowMonths" in src
    assert "24" in src and "36" in src and "60" in src


def test_rolling_correlation_view_has_pair_selector():
    """La vista debe tener selector de pares de indicadores."""
    src = (REPO / "src" / "components" / "enso" / "RollingCorrelationView.tsx").read_text(encoding="utf-8")
    assert "selectedPairs" in src
    assert "togglePair" in src
    assert "nino34-soi" in src or "nino34-d20" in src


def test_rolling_correlation_has_line_chart():
    """La vista debe tener un gráfico de líneas de evolución."""
    src = (REPO / "src" / "components" / "enso" / "RollingCorrelationView.tsx").read_text(encoding="utf-8")
    assert "RollingChart" in src
    assert "svg" in src.lower()


def test_rolling_correlation_has_heatmap():
    """La vista debe tener un mapa de calor de correlación actual."""
    src = (REPO / "src" / "components" / "enso" / "RollingCorrelationView.tsx").read_text(encoding="utf-8")
    assert "CurrentHeatmap" in src
    assert "mapa de calor" in src.lower() or "heatmap" in src.lower()


def test_rolling_correlation_deterministic():
    """El cálculo de correlación móvil es determinista en código."""
    src = (REPO / "src" / "components" / "enso" / "RollingCorrelationView.tsx").read_text(encoding="utf-8")
    src_lower = src.lower()
    assert "código" in src_lower or "determinista" in src_lower
    assert "el modelo no participa" in src_lower


def test_box_plot_has_statistics_table():
    """La vista debe tener tabla de estadísticos por categoría."""
    src = (REPO / "src" / "components" / "enso" / "BoxPlotView.tsx").read_text(encoding="utf-8")
    assert "table" in src.lower()
    assert "Mediana" in src or "mediana" in src
    assert "Atípicos" in src or "atípicos" in src
