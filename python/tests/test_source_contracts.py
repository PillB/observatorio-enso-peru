"""Contratos sobre el registro de fuentes.

Verifica que cada fuente tenga los campos requeridos, URL HTTPS, estado
válido y fuente de respaldo.
"""

from __future__ import annotations

import re

import pytest

from enso.sources import SOURCES, SOURCE_BY_ID, get_source
from enso.models import SourceStatus

VALID_STATUSES = {SourceStatus.VERIFIED, SourceStatus.ASSUMED,
                  SourceStatus.UNRESOLVED, SourceStatus.REJECTED}
REQUIRED_FIELDS = (
    "id", "institution", "product", "url", "retrievalDate", "format",
    "updateFrequency", "latency", "license", "attribution", "status",
    "notes", "fallbackSourceId",
)


def test_every_source_has_required_fields():
    assert len(SOURCES) > 0
    for s in SOURCES:
        for field in REQUIRED_FIELDS:
            v = getattr(s, field)
            assert v is not None and v != "", f"{s.id}: campo vacío {field}"


def test_urls_are_https_or_explicit_http():
    """Todas las URLs deben ser HTTPS, salvo excepción documentada (IGP)."""
    for s in SOURCES:
        if s.id == "igp-indices-clim":
            # IGP publica sólo por HTTP; se documenta en el catálogo.
            assert s.url.startswith("http://"), s.id
            continue
        assert s.url.startswith("https://"), f"{s.id}: URL no HTTPS: {s.url}"


def test_status_in_valid_set():
    for s in SOURCES:
        assert s.status in VALID_STATUSES, f"{s.id}: estado inválido {s.status}"


def test_fallback_source_exists():
    for s in SOURCES:
        assert s.fallbackSourceId, f"{s.id}: sin fallbackSourceId"
        # El fallback debe existir en el registro y ser distinto del propio.
        assert s.fallbackSourceId != s.id, f"{s.id}: fallback apunta a sí mismo"
        assert s.fallbackSourceId in SOURCE_BY_ID, (
            f"{s.id}: fallbackSourceId '{s.fallbackSourceId}' no existe"
        )


def test_no_duplicate_ids():
    ids = [s.id for s in SOURCES]
    assert len(ids) == len(set(ids)), "IDs duplicados"


def test_get_source_returns_by_id():
    for s in SOURCES:
        assert get_source(s.id) is s
    assert get_source("does-not-exist") is None


def test_verified_sources_match_ts_registry():
    """Conjunto mínimo de fuentes verificadas esperadas (espejo de TS)."""
    expected = {
        "noaa-cpc-enso-discussion",
        "noaa-cpc-reroni",
        "noaa-cpc-enso-evolution-pdf",
        "noaa-psl-nino34-ersst",
        "noaa-psl-nino12-anom",
        "noaa-psl-soi",
        "noaa-cpc-godas",
        "noaa-cpc-u850",
        "pmel-tao-triton",
        "enfen-imarpe-icen",
        "senamhi-fenomeno-el-nino",
        "igp-indices-clim",
    }
    actual = {s.id for s in SOURCES}
    missing = expected - actual
    assert not missing, f"faltan fuentes: {missing}"
    for sid in expected:
        assert SOURCE_BY_ID[sid].status == SourceStatus.VERIFIED
