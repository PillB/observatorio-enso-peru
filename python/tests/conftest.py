"""Fixtures compartidas para las pruebas del pipeline ENSO."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"

# Asegura que `python/` esté en sys.path para que `import enso` funcione.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ----------------------------------------------------------------------------
# Fixtures de contenido
# ----------------------------------------------------------------------------
@pytest.fixture
def nino12_csv_bytes() -> bytes:
    return (FIXTURES / "nino12_sample.csv").read_bytes()


@pytest.fixture
def nino34_csv_bytes() -> bytes:
    return (FIXTURES / "nino34_sample.csv").read_bytes()


@pytest.fixture
def soi_txt_bytes() -> bytes:
    return (FIXTURES / "soi_sample.txt").read_bytes()


@pytest.fixture
def enfen_icen_html_bytes() -> bytes:
    return (FIXTURES / "enfen_icen_sample.html").read_bytes()


# ----------------------------------------------------------------------------
# Series sintéticas
# ----------------------------------------------------------------------------
@pytest.fixture
def sample_nino12_points():
    """Lista de MonthlyPoint representativa (3 meses)."""
    from enso.models import MonthlyPoint, SeriesFlag

    return [
        MonthlyPoint(month="2026-05", value=1.30, flag=SeriesFlag.FINAL),
        MonthlyPoint(month="2026-06", value=1.50, flag=SeriesFlag.PRELIMINARY),
        MonthlyPoint(month="2026-07", value=1.70, flag=SeriesFlag.PRELIMINARY),
    ]


@pytest.fixture
def sample_series(sample_nino12_points):
    from enso.models import Series

    return Series(
        indicatorId="nino12",
        label="TSM Niño 1+2",
        units="degC",
        scope="coastal",
        points=sample_nino12_points,
        sourceId="noaa-psl-nino12-anom",
        checksum="fnv1a:00000000",
    )


# ----------------------------------------------------------------------------
# Fetcher falso (no red)
# ----------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, status_code: int, content: bytes, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


class _FakeTransport:
    """Transporte httpx falso que devuelve respuestas programadas."""

    def __init__(self, responses: list[_FakeResponse] | _FakeResponse | None = None,
                 cycle: bool = True):
        if isinstance(responses, _FakeResponse):
            responses = [responses]
        self._responses = responses or []
        self._cycle = cycle
        self.calls: list[dict[str, Any]] = []

    def add(self, status_code: int, content: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self._responses.append(_FakeResponse(status_code, content, headers or {}))

    def handle_request(self, method: str, url: str, headers, stream, extensions):
        self.calls.append({"method": method, "url": url, "headers": dict(headers)})
        if not self._responses:
            raise AssertionError("transporte falso sin respuestas programadas")
        idx = min(len(self.calls) - 1, len(self._responses) - 1) if self._cycle else min(len(self.calls) - 1, len(self._responses) - 1)
        resp = self._responses[min(len(self.calls) - 1, len(self._responses) - 1)]
        return resp.status_code, resp.headers, resp.content, []


@pytest.fixture
def fake_transport():
    return _FakeTransport()


@pytest.fixture
def offline_pipeline(tmp_path):
    """Pipeline aislado en tmp_path, sin red."""
    from enso.pipeline import Pipeline

    return Pipeline(
        out_dir=tmp_path / "out",
        cache_dir=tmp_path / "cache",
        allow_network=False,
    )


# ----------------------------------------------------------------------------
# Marcadores
# ----------------------------------------------------------------------------
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: pruebas que pueden tardar más de 1 segundo"
    )
    config.addinivalue_line(
        "markers", "net: pruebas que requieren acceso a red (deshabilitadas por defecto)"
    )


def pytest_collection_modifyitems(config, items):
    skip_net = pytest.mark.skip(reason="pruebas de red deshabilitadas por defecto")
    for item in items:
        if "net" in item.keywords:
            item.add_marker(skip_net)
