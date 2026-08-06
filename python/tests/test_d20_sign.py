"""Contratos de signo de D20 (profundidad de la isoterma de 20 °C).

- Anomalía positiva ⇒ termoclina más profunda.
- Anomalía negativa ⇒ termoclina más somera.
"""

from __future__ import annotations

import pytest

from enso.derived import d20_interpretation
from enso.methodology import INDICATOR_BY_ID
from enso.normalize import verify_d20_sign


def test_positive_d20_means_deeper():
    s = d20_interpretation(10.0)
    assert "profunda" in s.lower()


def test_negative_d20_means_shallower():
    s = d20_interpretation(-10.0)
    assert "somera" in s.lower()


def test_zero_d20_is_near_normal():
    s = d20_interpretation(0.0)
    assert "normal" in s.lower()


def test_none_d20_is_sin_datos():
    assert d20_interpretation(None) == "Sin datos"


def test_d20_thresholds():
    """|D20| > 5 m → señal; ≤ 5 m → normal."""
    assert "profunda" in d20_interpretation(6.0).lower()
    assert "somera" in d20_interpretation(-6.0).lower()
    assert "normal" in d20_interpretation(5.0).lower()
    assert "normal" in d20_interpretation(-5.0).lower()


def test_d20_definition_documents_sign():
    ind = INDICATOR_BY_ID["d20"]
    text = (ind.signConvention + " " + ind.positiveMeans + " " + ind.negativeMeans).lower()
    assert "profund" in text
    assert "somer" in text


def test_d20_units_are_meters():
    assert INDICATOR_BY_ID["d20"].units == "m"


def test_verify_d20_sign_accepts_finite():
    assert verify_d20_sign([10.0, -10.0, 0.0])


def test_verify_d20_sign_rejects_non_finite():
    import math
    # NaN se salta (no invalida), pero Inf sí invalida.
    assert verify_d20_sign([1.0, math.nan, 2.0])  # NaN no invalida
    assert not verify_d20_sign([1.0, math.inf, 2.0])  # Inf invalida
