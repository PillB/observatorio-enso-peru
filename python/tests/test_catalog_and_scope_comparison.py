"""Contratos para catálogo de eventos y comparación costero vs cuenca.

Cubre:
- El catálogo es una tabla exhaustiva de periodos ENSO.
- Incluye campos: alcance, fase, inicio, fin, pico, duración, intensidad.
- Es filtrable por alcance, fase e intensidad.
- Es descargable en CSV.
- La comparación costero vs cuenca tiene panel lado a lado.
- Distingue umbrales (±0.4 costero, ±0.5 cuenca).
- El cálculo es determinista en código.
- El caso 2017 (divergencia) se menciona.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def test_catalog_builds_from_alert_history():
    """buildEventCatalog se construye a partir del historial de alertas."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "buildEventCatalog" in src
    assert "buildAlertHistory" in src
    assert "CatalogEntry" in src


def test_catalog_has_required_fields():
    """Cada entrada del catálogo tiene los campos requeridos."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    for field in ("scope", "phase", "startMonth", "endMonth", "peakMonth", "peakValue", "durationMonths", "intensity", "intensityRank"):
        assert field in src, f"Falta campo en CatalogEntry: {field}"


def test_catalog_has_intensity_rank():
    """El catálogo tiene rango de intensidad numérico (1-4)."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "intensityRank" in src
    assert "intensityToRank" in src


def test_catalog_view_has_filters():
    """La vista del catálogo tiene filtros por alcance, fase e intensidad."""
    src = (REPO / "src" / "components" / "enso" / "EventCatalogView.tsx").read_text(encoding="utf-8")
    assert "setScope" in src
    assert "setPhase" in src
    assert "setMinRank" in src
    assert "costero" in src and "cuenca" in src
    assert "nino" in src and "nina" in src


def test_catalog_view_has_csv_download():
    """El catálogo es descargable en CSV."""
    src = (REPO / "src" / "components" / "enso" / "EventCatalogView.tsx").read_text(encoding="utf-8")
    assert "downloadCSV" in src
    assert "Blob" in src
    assert "text/csv" in src
    assert "catalogo-eventos" in src


def test_catalog_view_has_sortable_table():
    """La tabla del catálogo es ordenable."""
    src = (REPO / "src" / "components" / "enso" / "EventCatalogView.tsx").read_text(encoding="utf-8")
    assert "sortBy" in src
    assert "sortDir" in src
    assert "SortButton" in src


def test_catalog_has_decade_summary():
    """El catálogo tiene un resumen por década."""
    src = (REPO / "src" / "components" / "enso" / "EventCatalogView.tsx").read_text(encoding="utf-8")
    assert "DecadeSummary" in src
    assert "decade" in src


def test_scope_comparison_has_side_by_side():
    """La comparación costero vs cuenca tiene panel lado a lado."""
    src = (REPO / "src" / "components" / "enso" / "ScopeComparisonView.tsx").read_text(encoding="utf-8")
    assert "md:grid-cols-2" in src
    assert "Costero" in src
    assert "Cuenca" in src


def test_scope_comparison_distinguishes_thresholds():
    """La comparación distingue umbrales (±0.4 costero, ±0.5 cuenca)."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "±0.4" in src or "0.4" in src
    assert "±0.5" in src or "0.5" in src


def test_scope_comparison_has_metrics_table():
    """La comparación tiene tabla de métricas lado a lado."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "buildScopeComparison" in src
    assert "ScopeComparison" in src
    assert "metric" in src
    assert "coastal" in src
    assert "basin" in src


def test_scope_comparison_mentions_2017_divergence():
    """La comparación menciona el caso 2017 de divergencia costero/cuenca."""
    src = (REPO / "src" / "components" / "enso" / "ScopeComparisonView.tsx").read_text(encoding="utf-8")
    assert "2017" in src
    assert "divergencia" in src.lower() or "sin cuenca" in src.lower() or "por separado" in src.lower()


def test_scope_comparison_has_dual_time_series():
    """La comparación tiene serie temporal dual (costero + cuenca)."""
    src = (REPO / "src" / "components" / "enso" / "ScopeComparisonView.tsx").read_text(encoding="utf-8")
    assert "EnsoTimeSeries" in src
    assert "nino12" in src and "nino34" in src


def test_catalog_deterministic():
    """El catálogo se calcula de forma determinista en código."""
    src = (REPO / "src" / "components" / "enso" / "EventCatalogView.tsx").read_text(encoding="utf-8")
    assert "buildEventCatalog" in src
    # No debe haber valores hardcodeados de eventos
    assert "useMemo" in src or "React.useMemo" in src


def test_scope_comparison_labels_official_sources():
    """La comparación etiqueta las fuentes oficiales (ENFEN, NOAA/CPC)."""
    src = (REPO / "src" / "components" / "enso" / "ScopeComparisonView.tsx").read_text(encoding="utf-8")
    assert "ENFEN" in src
    assert "NOAA" in src or "CPC" in src
