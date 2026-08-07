"""Parsers estrictos para observaciones ENSO de alta frecuencia.

Este módulo no redefine índices operacionales. OISST diario y las boyas
TAO/TRITON se publican en una capa observacional separada, con su cobertura y
calidad explícitas.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import quote


class RapidSourceSchemaError(ValueError):
    """La respuesta cambió de contrato o no es científicamente utilizable."""


def _parse_utc(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RapidSourceSchemaError(f"invalid UTC date: {value}") from exc


def _fingerprint(columns: Iterable[str], units: Iterable[str]) -> str:
    contract = "|".join(columns) + "\n" + "|".join(units)
    return "sha256:" + hashlib.sha256(contract.encode("utf-8")).hexdigest()[:16]


def build_oisst_griddap_url(
    dataset: str,
    variable: str,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    time_selector: str = "last",
) -> str:
    """Construye una consulta ERDDAP regional y de un solo tiempo.

    El selector ``last`` evita descargar el archivo histórico o la grilla
    mundial. OISST usa longitudes 0–360.
    """
    allowed = {
        "ncdc_oisst_v2_avhrr_by_time_zlev_lat_lon",
        "ncdc_oisst_v2_avhrr_prelim_by_time_zlev_lat_lon",
    }
    if dataset not in allowed:
        raise ValueError(f"unsupported OISST dataset: {dataset}")
    if variable not in {"sst", "anom", "err"}:
        raise ValueError(f"unsupported OISST variable: {variable}")
    if not (-90 <= lat_min < lat_max <= 90 and 0 <= lon_min < lon_max < 360):
        raise ValueError("invalid OISST region")
    return (
        "https://www.ncei.noaa.gov/erddap/griddap/"
        f"{dataset}.csv?{variable}[({time_selector})][(0.0)]"
        f"[({lat_min:g}):({lat_max:g})][({lon_min:g}):({lon_max:g})]"
    )


def _read_erddap_csv(text: str) -> tuple[list[str], list[str], list[dict[str, str]]]:
    if "<html" in text[:500].lower() or "<!doctype" in text[:500].lower():
        raise RapidSourceSchemaError("HTML substituted the ERDDAP CSV")
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 3:
        raise RapidSourceSchemaError("truncated ERDDAP CSV")
    columns, units = rows[0], rows[1]
    if len(columns) != len(units):
        raise RapidSourceSchemaError("column/unit shape mismatch")
    data = [dict(zip(columns, row)) for row in rows[2:] if len(row) == len(columns)]
    if not data:
        raise RapidSourceSchemaError("ERDDAP CSV has no usable rows")
    return columns, units, data


def parse_erddap_grid_csv(
    text: str,
    variable: str,
    expected_units: str,
    *,
    now: str | None = None,
    future_tolerance_days: int = 2,
) -> dict[str, Any]:
    """Valida una grilla OISST y calcula una media coseno-latitudinal."""
    columns, units, data = _read_erddap_csv(text)
    required = ["time", "depth", "latitude", "longitude", variable]
    if any(name not in columns for name in required):
        raise RapidSourceSchemaError(f"missing required column for {variable}")
    unit_map = dict(zip(columns, units))
    if unit_map.get(variable) != expected_units:
        raise RapidSourceSchemaError(
            f"unexpected unit for {variable}: {unit_map.get(variable)!r}"
        )
    if unit_map.get("latitude") != "degrees_north" or unit_map.get("longitude") != "degrees_east":
        raise RapidSourceSchemaError("coordinate units changed")

    current = _parse_utc(now) if now else datetime.now(timezone.utc)
    seen: set[tuple[str, float, float, float]] = set()
    parsed: list[tuple[datetime, float, float, float]] = []
    for row in data:
        dt = _parse_utc(row["time"])
        if dt > current + timedelta(days=future_tolerance_days):
            raise RapidSourceSchemaError(f"future observation: {row['time']}")
        try:
            depth = float(row["depth"])
            lat = float(row["latitude"])
            lon = float(row["longitude"])
        except ValueError as exc:
            raise RapidSourceSchemaError("malformed OISST coordinate") from exc
        if abs(depth) > 0.01 or not -90 <= lat <= 90 or not 0 <= lon < 360:
            raise RapidSourceSchemaError("OISST coordinate outside contract")
        key = (row["time"], depth, lat, lon)
        if key in seen:
            raise RapidSourceSchemaError("duplicate OISST grid cell")
        seen.add(key)
        raw = row[variable].strip()
        if raw.lower() in {"nan", "na", "", "-999", "-999.0"}:
            continue
        try:
            value = float(raw)
        except ValueError as exc:
            raise RapidSourceSchemaError(f"malformed {variable} value") from exc
        if not math.isfinite(value):
            continue
        bounds = {"sst": (-3.0, 45.0), "anom": (-15.0, 15.0), "err": (0.0, 10.0)}
        lo, hi = bounds[variable]
        if not lo <= value <= hi:
            raise RapidSourceSchemaError(f"implausible {variable} value: {value}")
        parsed.append((dt, lat, value, math.cos(math.radians(lat))))
    if not parsed:
        raise RapidSourceSchemaError("all OISST cells are missing")
    times = {item[0] for item in parsed}
    if len(times) != 1:
        raise RapidSourceSchemaError("mixed OISST valid times")
    total_weight = sum(item[3] for item in parsed)
    mean = sum(item[2] * item[3] for item in parsed) / total_weight
    valid_time = next(iter(times))
    return {
        "value": round(mean, 4),
        "valid_period": valid_time.date().isoformat(),
        "valid_time": valid_time.isoformat().replace("+00:00", "Z"),
        "units": expected_units,
        "point_count": len(parsed),
        "weighting": "cosine_latitude",
        "schema_fingerprint": _fingerprint(columns, units),
    }


def parse_pmel_table_csv(
    text: str,
    *,
    value_column: str,
    expected_units: str,
    quality_column: str,
    accepted_quality: set[int],
    now: str | None = None,
    future_tolerance_days: int = 2,
) -> dict[str, Any]:
    """Parsea un subconjunto TAO/TRITON sin convertirlo en promedio de cuenca."""
    columns, units, data = _read_erddap_csv(text)
    required = {"station", "longitude", "latitude", "time", value_column, quality_column}
    if not required.issubset(columns):
        raise RapidSourceSchemaError("missing PMEL station/value/quality column")
    unit_map = dict(zip(columns, units))
    if unit_map.get(value_column) != expected_units:
        raise RapidSourceSchemaError(f"unexpected unit for {value_column}")
    current = _parse_utc(now) if now else datetime.now(timezone.utc)
    accepted: list[tuple[str, datetime, float]] = []
    seen: set[tuple[str, str]] = set()
    for row in data:
        station = row["station"].strip()
        if not station:
            raise RapidSourceSchemaError("missing PMEL station identity")
        dt = _parse_utc(row["time"])
        if dt > current + timedelta(days=future_tolerance_days):
            raise RapidSourceSchemaError("future PMEL observation")
        key = (station, row["time"])
        if key in seen:
            raise RapidSourceSchemaError("duplicate PMEL station timestamp")
        seen.add(key)
        try:
            quality = int(float(row[quality_column]))
            value = float(row[value_column])
            lon = float(row["longitude"])
            lat = float(row["latitude"])
        except ValueError as exc:
            raise RapidSourceSchemaError("malformed PMEL numeric value") from exc
        if not (0 <= lon < 360 and -90 <= lat <= 90):
            raise RapidSourceSchemaError("PMEL coordinate outside contract")
        if quality in accepted_quality and math.isfinite(value):
            accepted.append((station, dt, value))
    if not accepted:
        raise RapidSourceSchemaError("no PMEL observations passed quality control")
    latest = max(dt for _, dt, _ in accepted)
    latest_rows = [(station, value) for station, dt, value in accepted if dt.date() == latest.date()]
    stations = {station for station, _ in latest_rows}
    return {
        "value": round(sum(v for _, v in latest_rows) / len(latest_rows), 4),
        "valid_period": latest.date().isoformat(),
        "units": expected_units,
        "station_count": len(stations),
        "stations": sorted(stations),
        "quality_filter": sorted(accepted_quality),
        "recommended_role": "CORROBORATION_ONLY",
        "schema_fingerprint": _fingerprint(columns, units),
    }


def build_pmel_tabledap_url(
    *, dataset: str, columns: list[str], start_date: str,
    lat_min: float = -5, lat_max: float = 5,
    lon_min: float = 190, lon_max: float = 240,
) -> str:
    """Construye un subconjunto PMEL acotado y una fila reciente por estación."""
    allowed = {"pmelTaoDyIso", "pmelTaoDyW"}
    if dataset not in allowed:
        raise ValueError("unsupported PMEL dataset")
    if not columns or any(not re_name.replace("_", "").isalnum() for re_name in columns):
        raise ValueError("invalid PMEL column")
    # Validar fecha sin confiar en texto remoto.
    try:
        date.fromisoformat(start_date)
    except ValueError as exc:
        raise ValueError("invalid PMEL start date") from exc
    constraints = (
        f"&time>={start_date}T00:00:00Z"
        f"&latitude>={lat_min:g}&latitude<={lat_max:g}"
        f"&longitude>={lon_min:g}&longitude<={lon_max:g}"
        '&orderByMax("station,time")'
    )
    return (
        f"https://data.pmel.noaa.gov/pmel/erddap/tabledap/{dataset}.csv?"
        + ",".join(columns) + quote(constraints, safe=",&")
    )
