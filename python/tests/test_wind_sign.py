"""Contratos de convención de signos del viento zonal a 850 hPa.

- u > 0 ⇒ flujo hacia el este (componente del oeste / westerly).
- u < 0 ⇒ flujo hacia el oeste (componente del este / easterly).
- Anomalía ≠ valor observado.
- 850 hPa ≠ superficie (10 m).
"""

from __future__ import annotations

import pytest

from enso.derived import u850_direction
from enso.methodology import INDICATOR_BY_ID


def test_u_positive_means_westerly():
    """u > 0.5 ⇒ 'del oeste' / westerly (hacia el este)."""
    info = u850_direction(1.0)
    assert "oeste" in info["label"]
    assert "westerly" in info["signMeaning"].lower()
    assert "este" in info["signMeaning"]  # flujo hacia el este


def test_u_negative_means_easterly():
    """u < -0.5 ⇒ 'del este' / easterly (hacia el oeste)."""
    info = u850_direction(-1.0)
    assert "este" in info["label"]
    assert "easterly" in info["signMeaning"].lower()
    assert "oeste" in info["signMeaning"]  # flujo hacia el oeste


def test_u_zero_is_neutral():
    info = u850_direction(0.0)
    assert "neutral" in info["label"].lower()


def test_u_none_is_sin_datos():
    info = u850_direction(None)
    assert info["label"] == "Sin datos"


def test_anomaly_differs_from_observed():
    """La definición documenta que anomalía ≠ valor observado."""
    ind = INDICATOR_BY_ID["u850"]
    text = (ind.signConvention + " " + ind.variable).lower()
    assert "anomal" in text or "anomaly" in text
    # La unidad es m/s.
    assert ind.units == "m_per_s"


def test_850hpa_differs_from_surface():
    """La definición distingue 850 hPa de superficie (10 m)."""
    ind = INDICATOR_BY_ID["u850"]
    text = (ind.signConvention + " " + ind.level + " " + ind.notes).lower()
    assert "850" in text
    assert "10 m" in text or "superficie" in text


def test_wind_sign_verification_accepts_finite():
    from enso.normalize import verify_wind_sign
    assert verify_wind_sign([1.0, -1.0, 0.0, 5.5])


def test_wind_sign_verification_rejects_infinite():
    from enso.normalize import verify_wind_sign
    import math
    assert not verify_wind_sign([1.0, math.inf, -2.0])


def test_threshold_for_direction_label():
    """El umbral de dirección es |u| > 0.5 m/s."""
    assert "neutral" in u850_direction(0.4)["label"].lower()
    assert "neutral" in u850_direction(-0.4)["label"].lower()
    assert "oeste" in u850_direction(0.6)["label"]
    assert "este" in u850_direction(-0.6)["label"]
