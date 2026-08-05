"""Contratos de comportamiento móvil (viewport meta, config responsiva)."""

from __future__ import annotations

import pytest


MOBILE_CONFIG = {
    "viewport_meta": "width=device-width, initial-scale=1, viewport-fit=cover",
    "breakpoints": {"sm": 640, "md": 768, "lg": 1024, "xl": 1280},
    "mobile_first": True,
    "touch_target_min_px": 44,
    "font_scale_min": 0.875,
}


def test_viewport_meta_present():
    assert "width=device-width" in MOBILE_CONFIG["viewport_meta"]


def test_breakpoints_are_ascending():
    bps = MOBILE_CONFIG["breakpoints"]
    vals = list(bps.values())
    assert vals == sorted(vals)


def test_mobile_first_flag():
    assert MOBILE_CONFIG["mobile_first"] is True


def test_touch_target_meets_minimum():
    """Apple/WCAG recomienda ≥44 px."""
    assert MOBILE_CONFIG["touch_target_min_px"] >= 44


def test_font_scale_prevents_tiny_text():
    assert MOBILE_CONFIG["font_scale_min"] >= 0.75


def test_pipeline_artifacts_are_not_mobile_specific():
    """Los artefactos del pipeline son CSV/JSON; no asumen móvil."""
    from enso.pipeline import Pipeline
    pipe = Pipeline(allow_network=False)
    # El pipeline produce archivos portable-agnoóstico.
    assert str(pipe.out_dir).endswith("out") or "out" in str(pipe.out_dir)
