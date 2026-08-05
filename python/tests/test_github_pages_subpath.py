"""Contratos de URLs de assets bajo un subpath de GitHub Pages.

``asset_url(base_path, name)`` produce URLs relativas correctas bajo un
subpath del proyecto (p. ej. ``/repo/data/x.csv``).
"""

from __future__ import annotations

import pytest

from enso.pipeline import asset_url


def test_base_path_with_name():
    assert asset_url("/repo", "data/nino12.csv") == "/repo/data/nino12.csv"


def test_empty_base_path():
    assert asset_url("", "data/x.csv") == "/data/x.csv"


def test_trailing_slash_stripped():
    assert asset_url("/repo/", "data/x.csv") == "/repo/data/x.csv"


def test_leading_slash_in_name_stripped():
    assert asset_url("/repo", "/data/x.csv") == "/repo/data/x.csv"


def test_nested_name():
    assert asset_url("/obs-enso", "data/csv/2026/nino12.csv") == \
        "/obs-enso/data/csv/2026/nino12.csv"


def test_no_secret_in_url():
    """La URL no debe contener tokens tipo credenciales."""
    url = asset_url("/repo", "data/x.csv")
    assert "token" not in url.lower()
    assert "key" not in url.lower()
    assert "secret" not in url.lower()


def test_newline_rejected():
    """Una nueva línea en base_path o name es sospechosa de inyección."""
    with pytest.raises(ValueError):
        asset_url("/repo\n", "data/x.csv")
    with pytest.raises(ValueError):
        asset_url("/repo", "data/x.csv\n#")


def test_empty_name_rejected():
    with pytest.raises(ValueError):
        asset_url("/repo", "")
    with pytest.raises(ValueError):
        asset_url("/repo", "   ")


def test_non_string_rejected():
    with pytest.raises(ValueError):
        asset_url(123, "data/x.csv")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        asset_url("/repo", None)  # type: ignore[arg-type]
