"""Regression tests for failures observed in the production acquisition run."""

from __future__ import annotations

import json

import httpx
import pytest

import enso.unified_acquisition as acquisition_module
from enso.unified_acquisition import AcquisitionOrchestrator, HttpClient


def test_http_client_classifies_connect_error_as_retryable(monkeypatch):
    """A transport failure must exhaust the bounded budget, not crash the handler."""

    class FailingClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url, **_kwargs):
            raise httpx.ConnectError("connection refused", request=httpx.Request("GET", url))

    monkeypatch.setattr(acquisition_module.httpx, "Client", FailingClient)
    client = HttpClient(timeout=1, max_retries=0)

    with pytest.raises(RuntimeError, match="fallo tras 0 reintentos"):
        client.get("https://data.pmel.noaa.gov/example.csv", "pmel-test")


def test_partial_run_loads_existing_weekly_and_rapid_artifacts(tmp_path):
    """Source-specific refreshes must preserve unrelated validated observations."""
    publication = tmp_path / "public"
    publication.mkdir()
    weekly = [{"month": "2026-08-06", "nino34Anom": 0.5}]
    rapid = [{"metricId": "oisst_daily_nino34", "month": "2026-08-06", "value": 0.4}]
    (publication / "weekly-sst.json").write_text(json.dumps({"points": weekly}))
    (publication / "rapid-observations.json").write_text(json.dumps({"points": rapid}))

    orchestrator = AcquisitionOrchestrator(publication, tmp_path / "staging")

    assert orchestrator._load_existing_weekly() == weekly
    assert orchestrator._load_existing_rapid() == rapid
