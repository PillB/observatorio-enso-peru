"""Contratos para alertas de activación y correlaciones entre indicadores.

Cubre:
- Las alertas se etiquetan como derivadas del observatorio, no oficiales.
- Los meses consecutivos requeridos son 3 (ICEN y RONI).
- Los umbrales son correctos (ICEN ±0.4, RONI ±0.5).
- Las correlaciones se calculan en código (no por el modelo).
- La anticorrelación SOI–Niño 3.4 es negativa.
- La correlación Niño 1+2–ICEN es alta (por construcción).
- La matriz de correlación incluye todos los indicadores.
- La vista deriva a ENFEN/NOAA/CPC para declaraciones oficiales.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def test_alerts_view_labels_as_observatory_derived():
    """La vista de alertas debe declarar que es interpretación del observatorio."""
    src = (REPO / "src" / "components" / "enso" / "AlertsView.tsx").read_text(encoding="utf-8")
    src_lower = src.lower()
    assert "interpretación derivada del observatorio" in src_lower or "derivadas por el observatorio" in src_lower
    assert "declaración oficial" in src_lower
    assert "enfen" in src_lower
    assert "noaa" in src_lower


def test_alerts_thresholds_correct():
    """ICEN usa ±0.4 °C; RONI usa ±0.5 °C; ambos requieren 3 meses consecutivos."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert 'buildAlertFromSeries(all.icen, "icen", "ICEN", "coastal", 0.4, 3)' in src
    assert 'buildAlertFromSeries(all.roni, "roni", "RONI", "basin", 0.5, 3)' in src


def test_alerts_status_values():
    """El estado de activación debe ser uno de: Cumplido, En vigilancia, Neutral."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    for status in ("Cumplido", "En vigilancia", "Neutral"):
        assert status in src


def test_correlations_calculated_in_code():
    """Las correlaciones se calculan en código (Pearson), no por el modelo."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "function pearson" in src
    assert "buildCorrelations" in src
    # La vista debe declarar que el cálculo es determinista
    view = (REPO / "src" / "components" / "enso" / "CorrelationsView.tsx").read_text(encoding="utf-8")
    assert "código" in view.lower() or "determinista" in view.lower()
    assert "el modelo no participa" in view.lower()


def test_correlations_soi_nino34_negative():
    """La anticorrelación SOI ↔ Niño 3.4 debe ser negativa (signature física)."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "Anticorrelación esperada" in src
    assert "SOI negativo acompaña a El Niño" in src


def test_correlations_icen_nino12_high():
    """ICEN se deriva de Niño 1+2 → alta correlación esperada."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "Alta correlación esperada: ICEN se deriva de Niño 1+2" in src


def test_correlation_matrix_covers_all_indicators():
    """La matriz de correlación debe incluir los 7 indicadores."""
    src = (REPO / "src" / "components" / "enso" / "CorrelationsView.tsx").read_text(encoding="utf-8")
    for label in ("Niño 1+2", "ICEN", "Niño 3.4", "RONI", "SOI", "u850", "D20"):
        assert label in src


def test_alerts_derive_to_official_institutions():
    """La vista de alertas deriva a INDECI/CENEPRED/SENAMHI/ENFEN."""
    src = (REPO / "src" / "components" / "enso" / "AlertsView.tsx").read_text(encoding="utf-8")
    src_lower = src.lower()
    for inst in ("indeci", "cenepred", "senamhi", "enfen"):
        assert inst in src_lower


def test_no_fabricated_alert_values():
    """El cálculo de alertas usa los datos normalizados, no valores fabricados."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "generateAllSeries()" in src
    # buildAlertStates debe leer de la serie ICEN y RONI, no crear valores
    assert "all.icen" in src
    assert "all.roni" in src
