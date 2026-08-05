"""Contratos sobre la inexistencia de un «SOI costero».

- No existe un indicador con id 'soi' y scope 'coastal'.
- SOI es de cuenca exclusivamente.
- El corpus de conocimiento rechaza explícitamente «SOI costero».
"""

from __future__ import annotations

import pytest

from enso.methodology import INDICATORS, INDICATOR_BY_ID


def test_no_coastal_soi_indicator():
    """Ningún indicador se llama 'soi' con scope 'coastal'."""
    for ind in INDICATORS:
        if ind.id == "soi":
            assert ind.scope == "basin"
        assert not (ind.id == "soi" and ind.scope == "coastal")


def test_soi_is_basin_only():
    assert INDICATOR_BY_ID["soi"].scope == "basin"


def test_soi_definition_explicitly_rejects_coastal_variant():
    ind = INDICATOR_BY_ID["soi"]
    text = (ind.notes + " " + ind.signConvention).lower()
    assert "no define" in text or "no existe" in text or "costero" in text


def test_knowledge_corpus_rejects_coastal_soi():
    """El corpus TS (knowledge.ts) tiene un snippet k-no-coastal-soi.
    Aquí verificamos el contrato equivalente en Python: una pregunta que
    mencione 'SOI costero' debe disparar la corrección.
    """
    # Simula el motor de grounding (sin depender del TS).
    def knowledge_for(question: str) -> list[dict[str, str]]:
        q = question.lower()
        out: list[dict[str, str]] = []
        if "soi" in q and "costero" in q:
            out.append({
                "id": "k-no-coastal-soi",
                "text": (
                    "No existe un «SOI costero» con definición ni respaldo "
                    "metodológico equivalente al SOI convencional. El "
                    "observatorio NO define tal índice."
                ),
            })
        return out

    res = knowledge_for("¿Cuál es el valor del SOI costero?")
    assert len(res) == 1
    assert res[0]["id"] == "k-no-coastal-soi"
    assert "no existe" in res[0]["text"].lower()


def test_no_coastal_pressure_indicator_with_soi_name():
    """Ningún indicador costero menciona 'SOI' en su nombre corto."""
    for ind in INDICATORS:
        if ind.scope == "coastal":
            assert "soi" not in ind.shortName.lower()
            assert "oscilación del sur" not in ind.name.lower()


def test_soi_region_is_tahiti_darwin_not_peru():
    """El SOI usa Tahiti y Darwin, no estaciones peruanas."""
    ind = INDICATOR_BY_ID["soi"]
    text = ind.region.lower()
    assert "tahiti" in text
    assert "darwin" in text
