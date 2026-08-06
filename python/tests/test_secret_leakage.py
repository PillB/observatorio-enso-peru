"""Contratos de no-fuga de secretos.

Ningún artefacto del pipeline (manifest, status, CSVs) debe contener
strings de secretos (tokens, API keys, contraseñas).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from enso.pipeline import Pipeline


DUMMY_SECRET = "sk-dummy-test-secret-0xDEADBEEF-1234567890"


def _scan_text(text: str, secret: str) -> list[str]:
    """Devuelve las ocurrencias del secreto en el texto."""
    return [m.group(0) for m in re.finditer(re.escape(secret), text)]


def test_no_secret_in_manifest(tmp_path, monkeypatch):
    """Incluso con un secreto en el entorno, el manifest no lo filtra."""
    monkeypatch.setenv("DUMMY_API_TOKEN", DUMMY_SECRET)
    pipe = Pipeline(out_dir=tmp_path / "out", cache_dir=tmp_path / "cache",
                    allow_network=False)
    pipe.run()
    manifest_text = (tmp_path / "out" / "manifest.json").read_text()
    assert _scan_text(manifest_text, DUMMY_SECRET) == []


def test_no_secret_in_status(tmp_path, monkeypatch):
    monkeypatch.setenv("DUMMY_API_TOKEN", DUMMY_SECRET)
    pipe = Pipeline(out_dir=tmp_path / "out", cache_dir=tmp_path / "cache",
                    allow_network=False)
    pipe.run()
    status_text = (tmp_path / "out" / "status.json").read_text()
    assert _scan_text(status_text, DUMMY_SECRET) == []


def test_no_secret_in_csvs(tmp_path, monkeypatch):
    monkeypatch.setenv("DUMMY_API_TOKEN", DUMMY_SECRET)
    pipe = Pipeline(out_dir=tmp_path / "out", cache_dir=tmp_path / "cache",
                    allow_network=False)
    # Preescribe un último válido para generar CSV.
    from enso.models import MonthlyPoint, Series, SeriesFlag
    last = Series(
        indicatorId="nino12", label="TSM Niño 1+2", units="degC", scope="coastal",
        points=[MonthlyPoint(month="2026-06", value=1.50, flag=SeriesFlag.FINAL)],
        sourceId="noaa-psl-nino12-anom", checksum="fnv1a:dummy",
    )
    pipe._save_last_valid("nino12", last)
    pipe.run()
    out_dir = tmp_path / "out"
    for csv_file in out_dir.glob("*.csv"):
        text = csv_file.read_text()
        assert _scan_text(text, DUMMY_SECRET) == [], f"{csv_file.name} contiene el secreto"


def test_no_secret_in_sources_json(tmp_path, monkeypatch):
    monkeypatch.setenv("DUMMY_API_TOKEN", DUMMY_SECRET)
    pipe = Pipeline(out_dir=tmp_path / "out", cache_dir=tmp_path / "cache",
                    allow_network=False)
    pipe.run()
    sources_text = (tmp_path / "out" / "sources.json").read_text()
    assert _scan_text(sources_text, DUMMY_SECRET) == []


def test_no_secret_patterns_in_artifacts(tmp_path, monkeypatch):
    """Patrones comunes de secreto no aparecen en artefactos."""
    monkeypatch.setenv("GH_TOKEN", "ghp_abcdef1234567890")
    monkeypatch.setenv("AWS_KEY", "AKIAIOSFODNN7EXAMPLE")
    pipe = Pipeline(out_dir=tmp_path / "out", cache_dir=tmp_path / "cache",
                    allow_network=False)
    pipe.run()
    out_dir = tmp_path / "out"
    patterns = [r"ghp_[A-Za-z0-9]{10,}", r"AKIA[A-Z0-9]{12,}", r"sk-[A-Za-z0-9]{10,}"]
    for f in out_dir.iterdir():
        if not f.is_file():
            continue
        text = f.read_text()
        for p in patterns:
            assert not re.search(p, text), f"{f.name}: patrón {p} encontrado"


def test_pipeline_does_not_log_env(monkeypatch):
    """El pipeline no escribe el entorno completo en artefactos."""
    monkeypatch.setenv("PRIVATE_VAR", "ultra-private-value-xyz")
    import io
    from contextlib import redirect_stdout, redirect_stderr

    out_buf, err_buf = io.StringIO(), io.StringIO()
    pipe = Pipeline(out_dir="/tmp/enso_secret_test_out", cache_dir="/tmp/enso_secret_test_cache",
                    allow_network=False)
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        pipe.run()
    assert "ultra-private-value-xyz" not in out_buf.getvalue()
    assert "ultra-private-value-xyz" not in err_buf.getvalue()
