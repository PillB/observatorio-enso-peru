"""Contratos ante fallos de descarga.

Verifica que ante HTTPError/Timeout el pipeline NO fabrique datos y
preserva el último conjunto válido (marcado stale).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from enso.fetchers import (
    FetchError,
    PslNino12Fetcher,
    SchemaValidationError,
)
from enso.pipeline import Pipeline


def test_schema_validation_failure_preserves_last_valid(tmp_path, nino12_csv_bytes):
    """Si el contenido no valida, no se sobrescribe el último válido."""
    cache = tmp_path / "cache"
    out = tmp_path / "out"
    pipe = Pipeline(out_dir=out, cache_dir=cache, allow_network=False)

    # Preescribe un último válido sintético.
    from enso.models import MonthlyPoint, Series, SeriesFlag
    last_valid = Series(
        indicatorId="nino12",
        label="TSM Niño 1+2",
        units="degC",
        scope="coastal",
        points=[MonthlyPoint(month="2026-06", value=1.50, flag=SeriesFlag.FINAL)],
        sourceId="noaa-psl-nino12-anom",
        checksum="fnv1a:dummy",
    )
    pipe._save_last_valid("nino12", last_valid)

    # Crea un fetcher con contenido inválido.
    fetcher = PslNino12Fetcher(cache_dir=cache)
    # Forzamos validate() a fallar inyectando contenido basura.
    with pytest.raises(SchemaValidationError):
        fetcher.validate(b"NOT A VALID CSV")

    # El pipeline no debe fabricar datos; debe preservar el último válido.
    # Lo simulamos invocando directamente la rama de SchemaValidationError.
    from enso.methodology import INDICATOR_BY_ID
    ind = INDICATOR_BY_ID["nino12"]

    # Monkeypatch fetcher.fetch para que lance SchemaValidationError.
    class _BadFetcher(PslNino12Fetcher):
        def fetch(self, allow_network=True):
            raise SchemaValidationError("invalid content")

    pipe._fetcher_for = lambda source_id: _BadFetcher(cache_dir=cache)  # type: ignore[method-assign]
    run_result = pipe._process_indicator(ind)
    assert run_result.ok is True
    assert run_result.stale is True
    assert run_result.series is not None
    assert run_result.series.points[0].value == 1.50


def test_no_fabricated_values_on_total_failure(tmp_path):
    """Si no hay red ni caché, el resultado no es OK y no hay serie."""
    pipe = Pipeline(out_dir=tmp_path / "out", cache_dir=tmp_path / "cache",
                    allow_network=False)
    from enso.methodology import INDICATOR_BY_ID
    ind = INDICATOR_BY_ID["nino12"]
    # Limpia cualquier caché previo.
    cache_file = pipe._last_valid_path("nino12")
    if cache_file.exists():
        cache_file.unlink()
    res = pipe._process_indicator(ind)
    assert res.ok is False
    assert res.series is None
    assert res.error is not None


def test_run_produces_manifest_even_on_failure(tmp_path):
    """El pipeline siempre produce manifest, incluso si todo falla."""
    pipe = Pipeline(out_dir=tmp_path / "out", cache_dir=tmp_path / "cache",
                    allow_network=False)
    run = pipe.run()
    assert (tmp_path / "out" / "manifest.json").exists()
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text())
    assert "indicators" in manifest
    assert len(manifest["indicators"]) > 0
    # Ningún indicador debe reportar un valor fabricado: si no hay caché,
    # ok=False.
    for ind in manifest["indicators"]:
        if ind["ok"] is False:
            assert ind["last_value"] is None
