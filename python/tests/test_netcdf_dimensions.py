"""Contratos sobre dimensiones de NetCDF (lat, lon, time/level).

Usa un NetCDF sintético generado con scipy.io.netcdf si está disponible,
o se omite con razón explícita si netcdf4/xarray no están instalados.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("scipy")  # scipy.io.netcdf está disponible


def _make_synthetic_netcdf(path: Path) -> None:
    """Genera un NetCDF clásico con dims (time, lat, lon)."""
    try:
        from scipy.io import netcdf_file  # type: ignore
    except ImportError as e:  # pragma: no cover
        pytest.skip(f"scipy.io.netcdf no disponible: {e}")
    import numpy as np

    f = netcdf_file(str(path), "w")
    f.createDimension("time", 3)
    f.createDimension("lat", 5)
    f.createDimension("lon", 7)
    t = f.createVariable("time", "f4", ("time",))
    t[:] = [0.0, 1.0, 2.0]
    lat = f.createVariable("lat", "f4", ("lat",))
    lat[:] = [-2.0, -1.0, 0.0, 1.0, 2.0]
    lon = f.createVariable("lon", "f4", ("lon",))
    lon[:] = [180.0, 210.0, 240.0, 270.0, 300.0, 330.0, 360.0]
    sst = f.createVariable("sst", "f4", ("time", "lat", "lon"))
    sst[:] = np.arange(3 * 5 * 7, dtype="f4").reshape(3, 5, 7)
    f.close()


def test_synthetic_netcdf_has_expected_dims(tmp_path):
    path = tmp_path / "synthetic.nc"
    _make_synthetic_netcdf(path)

    try:
        import xarray as xr  # type: ignore
    except ImportError:
        pytest.skip("xarray no instalado — se omite con razón")

    ds = xr.open_dataset(str(path))
    try:
        assert "lat" in ds.dims
        assert "lon" in ds.dims
        assert "time" in ds.dims
        assert ds.dims["lat"] == 5
        assert ds.dims["lon"] == 7
        assert ds.dims["time"] == 3
        assert "sst" in ds.variables
        assert set(ds["sst"].dims) == {"time", "lat", "lon"}
    finally:
        ds.close()


def test_longitude_can_be_converted_to_negative_convention(tmp_path):
    """Tras leer el NetCDF, las longitudes 0..360 se convierten a -180..180."""
    path = tmp_path / "synthetic.nc"
    _make_synthetic_netcdf(path)
    try:
        import xarray as xr  # type: ignore
    except ImportError:
        pytest.skip("xarray no instalado — se omite con razón")
    from enso.normalize import to_negative

    ds = xr.open_dataset(str(path))
    try:
        lons = [float(x) for x in ds["lon"].values]
        converted = [to_negative(x) for x in lons]
        # 270° debe convertirse a -90°.
        assert -90.0 in converted
        # Todos en [-180, 180].
        for v in converted:
            assert -180.0 <= v <= 180.0
    finally:
        ds.close()


def test_netcdf_level_dimension_alternative(tmp_path):
    """Algunos productos (GODAS) usan 'level' además de time/lat/lon."""
    path = tmp_path / "synthetic.nc"
    _make_synthetic_netcdf(path)
    try:
        import xarray as xr  # type: ignore
    except ImportError:
        pytest.skip("xarray no instalado — se omite con razón")
    ds = xr.open_dataset(str(path))
    try:
        dims = set(ds.dims)
        # Acepta time o time+level como dimensión temporal/vertical.
        assert "time" in dims or "level" in dims
    finally:
        ds.close()
