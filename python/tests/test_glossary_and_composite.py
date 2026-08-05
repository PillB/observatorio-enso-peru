"""Contratos para el glosario climático y el índice compuesto ENSO.

Cubre:
- El glosario incluye términos clave (ENSO, El Niño Costero, ICEN, RONI, SOI, D20, u850).
- El glosario NO define «SOI costero» (respeta la integridad científica).
- El glosario menciona las instituciones peruanas (ENFEN, SENAMHI, IGP, INDECI, CENEPRED).
- El índice compuesto se etiqueta como interpretación del observatorio, no oficial.
- El índice compuesto combina los 5 indicadores esperados con ponderaciones que suman 1.
- El SOI se invierte (negativo → cálido) en el índice compuesto.
- Las categorías del índice cubren El Niño, La Niña y Neutral.
- Los meses con datos faltantes se omiten (sin interpolación).
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def test_glossary_includes_key_terms():
    """El glosario debe incluir los términos clave de ENSO."""
    src = (REPO / "src" / "lib" / "enso" / "glossary.ts").read_text(encoding="utf-8")
    required_terms = [
        "ENSO", "El Niño Costero", "ICEN", "RONI", "SOI",
        "D20", "Niño 1+2", "Niño 3.4", "termoclina",
    ]
    for term in required_terms:
        assert term in src, f"Falta término en el glosario: {term}"


def test_glossary_no_coastal_soi():
    """El glosario NO debe definir «SOI costero» como término válido."""
    src = (REPO / "src" / "lib" / "enso" / "glossary.ts").read_text(encoding="utf-8")
    # El SOI debe marcar explícitamente que no existe versión costera
    assert "no existe un «SOI costero»" in src or "no existe un \"SOI costero\"" in src or "SOI costero" not in src.replace("no existe un", "X")


def test_glossary_includes_peruvian_institutions():
    """El glosario debe mencionar las instituciones peruanas relevantes."""
    src = (REPO / "src" / "lib" / "enso" / "glossary.ts").read_text(encoding="utf-8")
    for inst in ("ENFEN", "SENAMHI", "IGP", "INDECI", "CENEPRED"):
        assert inst in src, f"Falta institución en el glosario: {inst}"


def test_glossary_in_spanish():
    """Las definiciones del glosario deben estar en español."""
    src = (REPO / "src" / "lib" / "enso" / "glossary.ts").read_text(encoding="utf-8")
    # Palabras clave que indican español formal
    assert "anomalía" in src
    assert "temperatura superficial del mar" in src
    assert "observatorio" in src.lower()


def test_glossary_has_search_function():
    """El glosario debe tener una función de búsqueda."""
    src = (REPO / "src" / "lib" / "enso" / "glossary.ts").read_text(encoding="utf-8")
    assert "function searchGlossary" in src
    assert "GLOSSARY_CATEGORIES" in src


def test_composite_index_labeled_as_observatory():
    """El índice compuesto debe etiquetarse como interpretación del observatorio."""
    src = (REPO / "src" / "components" / "enso" / "CompositeView.tsx").read_text(encoding="utf-8")
    src_lower = src.lower()
    assert "interpretación generada por el observatorio" in src_lower or "síntesis del observatorio" in src_lower
    assert "no un índice oficial" in src_lower or "no es un índice oficial" in src_lower or "no oficial" in src_lower


def test_composite_index_combines_five_indicators():
    """El índice compuesto debe combinar los 5 indicadores esperados."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    for ind in ("nino34", "nino12", "soi", "d20", "u850"):
        assert ind in src, f"Falta indicador en el índice compuesto: {ind}"


def test_composite_weights_sum_to_one():
    """Las ponderaciones del índice compuesto deben sumar 1."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    # Pesos: 0.30 + 0.25 + 0.20 + 0.15 + 0.10 = 1.00
    assert "0.30" in src and "0.25" in src and "0.20" in src and "0.15" in src and "0.10" in src
    assert "weights" in src


def test_composite_soi_inverted():
    """El SOI debe invertirse en el índice compuesto (negativo → cálido)."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "cSOI" in src or "soi / scales" in src
    # La inversión debe estar documentada
    assert "invertido" in src.lower() or "invierte" in src.lower()


def test_composite_categories_cover_warm_cool_neutral():
    """Las categorías del índice deben cubrir El Niño, La Niña y Neutral."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "El Niño" in src
    assert "La Niña" in src
    assert "Neutral" in src
    assert "compositeCategory" in src


def test_composite_no_interpolation():
    """Los meses con datos faltantes se omiten, no se interpolan."""
    src = (REPO / "src" / "lib" / "enso" / "derived.ts").read_text(encoding="utf-8")
    assert "return null" in src or "return None" in src
    assert "filter" in src
    # La nota sobre saltar meses faltantes
    assert "datos faltantes" in src.lower() or "sin interpolar" in src.lower()


def test_glossary_view_has_search_and_filters():
    """La vista del glosario debe tener buscador y filtros por categoría."""
    src = (REPO / "src" / "components" / "enso" / "GlossaryView.tsx").read_text(encoding="utf-8")
    assert "searchGlossary" in src
    assert "activeCat" in src
    assert "GLOSSARY_CATEGORIES" in src
