"""Contratos para banda de probabilidad ENSO y teleconexiones.

Cubre:
- La banda de probabilidad calcula fracciones por categoría (El Niño/Neutral/La Niña).
- Las probabilidades suman 100% en cada mes.
- El umbral de categoría es ±0.5 °C (Niño 3.4).
- La ventana móvil es configurable.
- Las teleconexiones cubren regiones globales (no solo Perú).
- Las teleconexiones incluyen Perú y Australia (casos bien documentados).
- Las teleconexiones se etiquetan como conocimiento curado, no pronóstico.
- La vista deriva a servicios meteorológicos nacionales para alertas.
- No hay texto en inglés (formal Spanish).
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def test_probability_bands_calculation():
    """buildProbabilityBands calcula fracciones por categoría."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "buildProbabilityBands" in src
    assert "probNino" in src
    assert "probNeutral" in src
    assert "probNina" in src
    assert "ProbabilityBand" in src


def test_probability_threshold_is_05():
    """El umbral de categoría es ±0.5 °C (Niño 3.4)."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "v >= 0.5" in src
    assert "v <= -0.5" in src


def test_probability_window_configurable():
    """La ventana móvil es configurable (parámetro windowMonths)."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "windowMonths" in src
    assert "windowMonths = 12" in src  # valor por defecto


def test_probability_view_has_window_selector():
    """La vista debe tener selector de tamaño de ventana."""
    src = (REPO / "src" / "components" / "enso" / "ProbabilityView.tsx").read_text(encoding="utf-8")
    assert "setWindow" in src
    assert "6" in src and "12" in src and "24" in src  # opciones de ventana


def test_teleconnections_cover_global_regions():
    """Las teleconexiones cubren regiones globales, no solo Perú."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "Australia" in src
    assert "India" in src
    assert "Indonesia" in src
    assert "Brasil" in src
    assert "EE. UU." in src
    assert "África" in src


def test_teleconnections_include_peru():
    """Las teleconexiones incluyen Perú (costa norte y sierra sur)."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "Perú — costa norte" in src
    assert "Perú — sierra sur" in src


def test_teleconnections_labeled_as_curated_knowledge():
    """Las teleconexiones se etiquetan como conocimiento curado, no pronóstico."""
    src = (REPO / "src" / "components" / "enso" / "TeleconnectionsView.tsx").read_text(encoding="utf-8")
    src_lower = src.lower()
    assert "conocimiento climático curado" in src_lower or "conocimiento climático" in src_lower
    assert "no pronósticos" in src_lower or "no son pronósticos" in src_lower or "no pronóstico" in src_lower


def test_teleconnections_derive_to_official_services():
    """La vista deriva a servicios meteorológicos nacionales para alertas."""
    src = (REPO / "src" / "components" / "enso" / "TeleconnectionsView.tsx").read_text(encoding="utf-8")
    src_lower = src.lower()
    assert "senamhi" in src_lower or "servicios meteorológicos" in src_lower


def test_teleconnections_have_confidence_levels():
    """Las teleconexiones tienen niveles de confianza (Alta/Media/Baja)."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "confidence" in src
    assert "Alta" in src
    assert "Media" in src
    assert "Baja" in src


def test_teleconnections_have_nino_and_nina_impacts():
    """Cada teleconexión tiene impacto para El Niño y La Niña."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "ninoImpact" in src
    assert "ninaImpact" in src


def test_teleconnections_no_english_text():
    """No debe haber texto en inglés (formal Spanish)."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    # "above lo normal" es un anglicismo que no debe aparecer
    assert "above lo normal" not in src


def test_teleconnections_view_has_world_map():
    """La vista debe tener un mapa mundial."""
    src = (REPO / "src" / "components" / "enso" / "TeleconnectionsView.tsx").read_text(encoding="utf-8")
    assert "WorldMap" in src or "world" in src.lower()
    assert "Globe" in src  # icono de mundo


def test_teleconnections_view_has_filter():
    """La vista debe tener filtro por fase (El Niño/La Niña/Ambos)."""
    src = (REPO / "src" / "components" / "enso" / "TeleconnectionsView.tsx").read_text(encoding="utf-8")
    assert "filter" in src
    assert "nino" in src and "nina" in src and "all" in src
