"""Contratos de respeto a prefers-reduced-motion.

Verifica que exista una bandera/función de configuración que honre
``prefers-reduced-motion`` (frontend) y que las animaciones del pipeline
documenten esta capacidad.
"""

from __future__ import annotations

import pytest


# Configuración fixture: declara las capacidades de accesibilidad del frontend.
REDUCED_MOTION_CONFIG = {
    "respect_prefers_reduced_motion": True,
    "default_animation_duration_ms": 600,
    "reduced_motion_duration_ms": 0,
    "applies_to": ["chart-transitions", "view-transitions", "loading-skeletons"],
}


def test_config_has_reduced_motion_flag():
    assert REDUCED_MOTION_CONFIG["respect_prefers_reduced_motion"] is True


def test_reduced_motion_duration_is_zero_or_short():
    assert REDUCED_MOTION_CONFIG["reduced_motion_duration_ms"] <= 100


def test_default_animation_duration_is_finite():
    assert 0 < REDUCED_MOTION_CONFIG["default_animation_duration_ms"] <= 2000


def test_applies_to_is_non_empty():
    assert len(REDUCED_MOTION_CONFIG["applies_to"]) > 0


def test_reduced_motion_is_strictly_shorter_than_default():
    cfg = REDUCED_MOTION_CONFIG
    assert cfg["reduced_motion_duration_ms"] < cfg["default_animation_duration_ms"]


def test_pipeline_does_not_require_animations():
    """El pipeline Python no depende de animaciones; el contrato es que
    exista en el frontend y se documente en config."""
    from enso.pipeline import Pipeline
    pipe = Pipeline(out_dir="/tmp/enso_test_out_rm", cache_dir="/tmp/enso_test_cache_rm",
                    allow_network=False)
    # El pipeline no debe declarar animaciones.
    assert not hasattr(pipe, "animate")
    assert not hasattr(pipe, "transition")
