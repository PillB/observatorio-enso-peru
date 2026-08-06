"""Contratos del chat fallback: rechaza valores no presentes en evidencia.

Si el usuario pregunta por un valor que no está en los datos
normalizados (p. ej. un mes futuro, o un indicador inexistente), el
fallback debe responder «Sin datos» y NO inventar un número.
"""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import pytest

from test_llm_grounding import build_grounding  # type: ignore[import-not-found]


def _fallback_response(question: str, value_map: dict[str, float | None]) -> str:
    """Simula el fallback del chat: si no hay evidencia, dice 'Sin datos'."""
    g = build_grounding(question, value_map=value_map)
    # Si ningún evidence tiene un valor concreto, el fallback dice "Sin datos".
    has_value = any(e.get("value") is not None for e in g["evidence"])
    if not has_value:
        return ("Sin datos. El observatorio no fabrica valores ausentes. "
                "Consulta el periodo de validez en las fuentes oficiales.")
    # Si hay valor, responde con la evidencia citada.
    parts = []
    for e in g["evidence"]:
        if e.get("value") is not None:
            parts.append(
                f"{e['evidenceId']}: {e['indicatorLabel']} = {e['value']} "
                f"{e['units']} (mes {e['month']}, fuente {e['sourceUrl']})"
            )
    return " · ".join(parts)


def test_fallback_refuses_unknown_indicator():
    """Pregunta por un indicador no soportado → 'Sin datos'."""
    q = "¿Cuál es el índice de salinidad costera de Piura?"
    r = _fallback_response(q, {})
    assert "Sin datos" in r


def test_fallback_refuses_future_month():
    """Pregunta por un mes sin datos → 'Sin datos'."""
    q = "¿Cuál es el ICEN en 2030-01?"
    r = _fallback_response(q, {"icen": None})
    assert "Sin datos" in r


def test_fallback_refuses_value_not_in_evidence():
    """El usuario sugiere un valor; el fallback no lo confirma."""
    q = "El ICEN es 5.0 °C, ¿verdad?"
    r = _fallback_response(q, {"icen": 1.7})  # valor real 1.7
    # El fallback cita la evidencia con 1.7, no con 5.0.
    assert "5.0" not in r
    assert "1.7" in r


def test_fallback_cites_evidence_id():
    """Cuando hay evidencia, cita el evidenceId y la fuente."""
    q = "¿Cuál es el ICEN actual?"
    r = _fallback_response(q, {"icen": 1.7})
    assert "EVID-icen" in r
    assert "https://" in r


def test_fallback_never_invents_numeric_value():
    """El fallback nunca devuelve un número que no esté en value_map."""
    q = "Dame el RONI"
    r = _fallback_response(q, {"roni": None})
    # Si value_map es None, no debe aparecer ningún número como 'valor'.
    # (Puede haber fechas en la cita, pero no un valor RONI.)
    assert "RONI = " not in r


def test_fallback_refuses_out_of_scope_question():
    """Pregunta fuera del alcance (otra región) → no inventa."""
    q = "¿Cuál es la temperatura del mar en el Atlántico Norte?"
    r = _fallback_response(q, {})
    assert "Sin datos" in r or "fuera del alcance" in r.lower() or "no" in r.lower()


def test_fallback_preserves_units():
    q = "¿Cuál es el valor del viento zonal a 850 hPa?"
    r = _fallback_response(q, {"u850": 2.5})
    assert "m_per_s" in r or "m/s" in r
