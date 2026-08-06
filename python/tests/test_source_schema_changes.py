"""Contratos de detección de cambios de esquema de fuente.

Si el payload de una fuente cambia de esquema, la validación debe fallar
de forma explícita (no fusionar silenciosamente).
"""

from __future__ import annotations

import pytest

from enso.fetchers import PslNino12Fetcher, PslNino34Fetcher, PslSoiFetcher, SchemaValidationError


def _csv(year_line: bytes, *rows: bytes) -> bytes:
    return b"\n".join((year_line, *rows)) + b"\n"


GOOD_PSL = _csv(
    b"year,1,2,3,4,5,6,7,8,9,10,11,12",
    b"1990,0.1,0.2,0.3,0.1,-0.1,-0.2,-0.3,-0.2,0.0,0.1,0.2,0.1",
)


def test_psl_valid_csv_passes(tmp_path):
    fetcher = PslNino12Fetcher(cache_dir=tmp_path)
    fetcher.validate(GOOD_PSL)  # no raises


def test_psl_missing_header_rejected(tmp_path):
    fetcher = PslNino12Fetcher(cache_dir=tmp_path)
    bad = _csv(b"foo,bar", b"1990,1,2,3,4,5,6,7,8,9,10,11,12")
    with pytest.raises(SchemaValidationError):
        fetcher.validate(bad)


def test_psl_empty_payload_rejected(tmp_path):
    fetcher = PslNino12Fetcher(cache_dir=tmp_path)
    with pytest.raises(SchemaValidationError):
        fetcher.validate(b"")


def test_psl_only_comments_rejected(tmp_path):
    fetcher = PslNino12Fetcher(cache_dir=tmp_path)
    with pytest.raises(SchemaValidationError):
        fetcher.validate(b"# comment\n# another\n")


def test_psl_no_numeric_rows_rejected(tmp_path):
    fetcher = PslNino12Fetcher(cache_dir=tmp_path)
    bad = _csv(b"year,1,2,3,4,5,6,7,8,9,10,11,12",
               b"foo,bar,baz,qux,5,6,7,8,9,10,11,12,13")
    with pytest.raises(SchemaValidationError):
        fetcher.validate(bad)


def test_psl_nino34_uses_same_validator(tmp_path):
    fetcher = PslNino34Fetcher(cache_dir=tmp_path)
    fetcher.validate(GOOD_PSL)
    with pytest.raises(SchemaValidationError):
        fetcher.validate(b"garbage")


def test_psl_soi_uses_same_validator(tmp_path):
    fetcher = PslSoiFetcher(cache_dir=tmp_path)
    fetcher.validate(GOOD_PSL)
    with pytest.raises(SchemaValidationError):
        fetcher.validate(b"nope")


def test_schema_change_does_not_silently_merge(tmp_path, nino12_csv_bytes):
    """Si el esquema cambia, el fetcher no debe aceptar el contenido nuevo.

    Simulamos un payload 'nuevo' que perdió la columna year: debe rechazarse.
    """
    fetcher = PslNino12Fetcher(cache_dir=tmp_path)
    # 'new' payload que ya no tiene la cabecera esperada.
    new_payload = b"value\n1.23\n1.45\n"
    with pytest.raises(SchemaValidationError):
        fetcher.validate(new_payload)
