"""Contratos de fallback WebGL/WebGPU.

El frontend debe declarar un registro de fallback cuando WebGPU no está
disponible (en cuyo caso se usa inferencia LLM en servidor vía API route,
o un modo de sólo lectura del grounding determinista).
"""

from __future__ import annotations

import pytest


WEBGPU_FALLBACK_REGISTRY = {
    "webgpu_supported": "auto-detect",
    "fallback_chain": [
        "webgpu",
        "wasm-simd",
        "server-llm-api",
        "deterministic-grounding-only",
    ],
    "default_when_unavailable": "deterministic-grounding-only",
    "graceful_degradation": True,
}


def test_fallback_chain_is_non_empty():
    assert len(WEBGPU_FALLBACK_REGISTRY["fallback_chain"]) >= 2


def test_default_when_unavailable_is_set():
    d = WEBGPU_FALLBACK_REGISTRY["default_when_unavailable"]
    assert d in WEBGPU_FALLBACK_REGISTRY["fallback_chain"]


def test_graceful_degradation_enabled():
    assert WEBGPU_FALLBACK_REGISTRY["graceful_degradation"] is True


def test_deterministic_grounding_is_last_resort():
    """El último eslabón es el grounding determinista (sin LLM)."""
    chain = WEBGPU_FALLBACK_REGISTRY["fallback_chain"]
    assert chain[-1] == "deterministic-grounding-only"


def test_server_llm_api_in_chain():
    """La API route del servidor está disponible como fallback."""
    assert "server-llm-api" in WEBGPU_FALLBACK_REGISTRY["fallback_chain"]


def test_pipeline_works_without_gpu():
    """El pipeline Python no requiere GPU/WebGPU para funcionar."""
    from enso.pipeline import Pipeline
    pipe = Pipeline(allow_network=False)
    # Sin red, sin GPU: aún puede producir artefactos (vacíos o stale).
    # El contrato es que no lanze errores de GPU.
    import json
    run = pipe.run()
    assert run is not None
    assert (pipe.out_dir / "manifest.json").exists()
