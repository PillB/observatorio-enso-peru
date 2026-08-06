"""Contratos para historial de alertas y diagrama de fases ENSO.

Cubre:
- El historial de alertas reconstruye periodos ENSO a partir de las series.
- Distingue costero (ICEN ±0.4) y cuenca (Niño 3.4 ±0.5).
- Cada periodo tiene fase, intensidad, pico y duración.
- El historial se etiqueta como reconstrucción derivada, no oficial.
- El diagrama de fases usa Niño 3.4 y SOI.
- Los puntos tienen etiqueta de fase (El Niño/Neutral/La Niña).
- La ventana del diagrama es configurable.
- El cálculo es determinista en código.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def test_alert_history_reconstructs_periods():
    """buildAlertHistory reconstruye periodos ENSO a partir de las series."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "buildAlertHistory" in src
    assert "AlertPeriod" in src
    assert "extractPeriods" in src


def test_alert_history_distinguishes_coastal_and_basin():
    """El historial distingue costero (ICEN ±0.4) y cuenca (Niño 3.4 ±0.5)."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert 'extractPeriods(all.nino34.points, "cuenca")' in src
    assert 'extractPeriods(all.icen.points, "costero", 0.4)' in src
    assert "0.5" in src  # umbral de cuenca por defecto


def test_alert_period_has_required_fields():
    """Cada periodo tiene fase, intensidad, pico, mes pico y duración."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    for field in ("startMonth", "endMonth", "phase", "peakValue", "peakMonth", "durationMonths", "intensity"):
        assert field in src, f"Falta campo en AlertPeriod: {field}"


def test_alert_history_labeled_as_derived():
    """El historial se etiqueta como reconstrucción derivada, no oficial."""
    src = (REPO / "src" / "components" / "enso" / "AlertHistoryView.tsx").read_text(encoding="utf-8")
    src_lower = src.lower()
    assert "reconstrucción derivada del observatorio" in src_lower
    assert "no oficial" in src_lower or "no son oficiales" in src_lower or "declaraciones oficiales" in src_lower


def test_alert_history_has_timeline_visual():
    """La vista debe tener una línea de tiempo visual."""
    src = (REPO / "src" / "components" / "enso" / "AlertHistoryView.tsx").read_text(encoding="utf-8")
    assert "Timeline" in src
    assert "svg" in src.lower()


def test_alert_history_has_tables():
    """La vista debe tener tablas de periodos costeros y de cuenca."""
    src = (REPO / "src" / "components" / "enso" / "AlertHistoryView.tsx").read_text(encoding="utf-8")
    assert "PeriodTable" in src
    assert "Periodos costeros" in src
    assert "Periodos de cuenca" in src


def test_phase_diagram_uses_nino34_and_soi():
    """El diagrama de fases usa Niño 3.4 y SOI."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "buildPhaseSpace" in src
    assert "PhasePoint" in src
    assert "nino34" in src
    assert "soi" in src


def test_phase_points_have_phase_label():
    """Los puntos del diagrama tienen etiqueta de fase."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "El Niño" in src
    assert "Neutral" in src
    assert "La Niña" in src
    assert "phase" in src


def test_phase_diagram_window_configurable():
    """La ventana del diagrama es configurable."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "windowMonths" in src
    assert "windowMonths = 60" in src


def test_phase_diagram_view_has_window_selector():
    """La vista debe tener selector de ventana."""
    src = (REPO / "src" / "components" / "enso" / "PhaseDiagramView.tsx").read_text(encoding="utf-8")
    assert "setWindowMonths" in src
    assert "24" in src and "60" in src and "120" in src


def test_phase_diagram_deterministic():
    """El cálculo del diagrama es determinista en código."""
    src = (REPO / "src" / "components" / "enso" / "PhaseDiagramView.tsx").read_text(encoding="utf-8")
    src_lower = src.lower()
    assert "código" in src_lower or "determinista" in src_lower
    assert "el modelo no participa" in src_lower


def test_phase_diagram_has_quadrant_analysis():
    """El diagrama debe tener análisis de cuadrantes."""
    src = (REPO / "src" / "components" / "enso" / "PhaseDiagramView.tsx").read_text(encoding="utf-8")
    assert "cuadrante" in src.lower()
    assert "QuadrantStats" in src
    assert "coherente" in src.lower()


def test_phase_diagram_has_scatter_plot():
    """El diagrama debe tener un gráfico de dispersión."""
    src = (REPO / "src" / "components" / "enso" / "PhaseDiagramView.tsx").read_text(encoding="utf-8")
    assert "PhaseScatter" in src
    assert "svg" in src.lower()


def test_intensity_labels_in_spanish():
    """Las etiquetas de intensidad deben estar en español."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "débil" in src
    assert "moderado" in src
    assert "fuerte" in src
    assert "muy fuerte" in src
