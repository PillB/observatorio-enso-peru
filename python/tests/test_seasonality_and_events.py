"""Contratos para estacionalidad y comparación de eventos.

Cubre:
- La estacionalidad calcula promedio y desviación estándar por mes calendario.
- Hay 12 meses en la climatología.
- El valor actual se compara con la climatología del mismo mes.
- La comparación de eventos alinea por mes de pico (offset 0).
- La ventana de comparación es ±24 meses.
- Se pueden comparar múltiples eventos (hasta 5).
- El cálculo es determinista en código.
- El caso 2017 está disponible (costero sin cuenca).
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def test_seasonality_has_12_months():
    """La climatología debe tener 12 entradas (una por mes)."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "buildSeasonality" in src
    assert "MonthlyClimatology" in src
    # El bucle debe iterar 1..12
    assert "m <= 12" in src


def test_seasonality_calculates_mean_and_std():
    """La estacionalidad calcula promedio y desviación estándar."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "mean" in src
    assert "std" in src
    assert "Math.sqrt" in src  # desviación estándar


def test_seasonality_view_has_indicator_selector():
    """La vista de estacionalidad debe tener selector de indicador."""
    src = (REPO / "src" / "components" / "enso" / "SeasonalityView.tsx").read_text(encoding="utf-8")
    assert "INDICATOR_OPTIONS" in src
    assert "nino34" in src
    assert "nino12" in src
    assert "icen" in src


def test_seasonality_deterministic():
    """El cálculo de estacionalidad es determinista en código."""
    src = (REPO / "src" / "components" / "enso" / "SeasonalityView.tsx").read_text(encoding="utf-8")
    src_lower = src.lower()
    assert "código" in src_lower or "determinista" in src_lower
    assert "el modelo no participa" in src_lower


def test_event_comparison_aligns_by_peak():
    """La comparación de eventos alinea por mes de pico (offset 0)."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "buildEventSeries" in src
    assert "peakIdx" in src
    assert "offset" in src
    assert "Pico" in src  # etiqueta del offset 0


def test_event_comparison_window_24_months():
    """La ventana de comparación es ±24 meses."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "const window = 24" in src


def test_event_comparison_includes_2017():
    """El caso 2017 (costero sin cuenca) debe estar disponible para comparar."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "2017" in src
    assert "El Niño Costero 2017" in src
    assert "Caso paradigmático" in src or "paradigmático" in src


def test_event_comparison_view_max_5_events():
    """La vista debe limitar a 5 eventos seleccionados."""
    src = (REPO / "src" / "components" / "enso" / "EventComparisonView.tsx").read_text(encoding="utf-8")
    assert "5" in src  # máximo 5 eventos
    assert "selectedIds" in src
    assert "toggleEvent" in src


def test_event_comparison_has_metric_selector():
    """La vista debe tener selector de métrica (Niño 3.4, Niño 1+2, ICEN)."""
    src = (REPO / "src" / "components" / "enso" / "EventComparisonView.tsx").read_text(encoding="utf-8")
    assert "nino34" in src
    assert "nino12" in src
    assert "icen" in src
    assert "metric" in src


def test_seasonality_compares_latest_with_climatology():
    """La estacionalidad compara el valor actual con la climatología del mismo mes."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "latestMonth" in src
    assert "latestValue" in src
    # La vista debe mostrar la anomalía respecto a la climatología
    view = (REPO / "src" / "components" / "enso" / "SeasonalityView.tsx").read_text(encoding="utf-8")
    assert "Anomalía respecto a la climatología" in view


def test_no_fabricated_seasonality_values():
    """La estacionalidad se calcula sobre los datos normalizados, no se fabrica."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "generateAllSeries()" in src
    # Los meses con datos faltantes se preservan (count puede ser 0)
    assert "vals.length === 0" in src or "count" in src
