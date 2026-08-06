"""Fetchers OPeNDAP para datos grilleados de NOAA/PSL.

Estos fetchers acceden al endpoint ASCII de OPeNDAP de PSL
(``https://psl.noaa.gov/thredds/dodsC/.../*.nc.ascii``) que devuelve
texto plano parseable sin necesidad de librerías NetCDF.

Fuentes soportadas:
  - **u850 mensual** (NCEP/NCAR Reanalysis1, nivel 850 hPa):
    ``https://psl.noaa.gov/thredds/dodsC/Datasets/ncep.reanalysis.derived/pressure/uwnd.mon.mean.nc``
    Promedio espacial sobre Niño 3.4 (5°S–5°N, 120°W–170°W).
    Anomalía con climatología 1991–2020.

  - **D20 mensual** (GODAS, ``dbss_obil`` = "ocean isothermal layer depth
    below sea surface", proxy de la profundidad de la isoterma de 20 °C):
    ``https://psl.noaa.gov/thredds/dodsC/Datasets/godas/dbss_obil.{year}.nc``
    Promedio espacial sobre Niño 3.4 (5°S–5°N, 120°W–170°W).
    Anomalía con climatología 1991–2020.

Diseño:
  - Sin xarray/netcdf4: parseo manual del ASCII OPeNDAP.
  - Reintentos y timeout vía httpx.
  - NUNCA fabrica valores: si el parseo falla, se levanta excepción.
  - Climatología 1991–2020 calculada in-situ desde los propios datos.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore

from .models import MonthlyPoint, SeriesFlag


# ----------------------------------------------------------------------------
# Constantes de región Niño 3.4 (5°S–5°N, 120°W–170°W = 190°E–240°E)
# ----------------------------------------------------------------------------
NINO34_LAT_MIN = -5.0
NINO34_LAT_MAX = 5.0
NINO34_LON_MIN = 190.0  # 170°W
NINO34_LON_MAX = 240.0  # 120°W
CLIM_BASELINE_YEARS = (1991, 2020)  # climatología estándar WMO


# ----------------------------------------------------------------------------
# Excepciones
# ----------------------------------------------------------------------------
class OpendapError(Exception):
    """Error base de parseo OPeNDAP."""


# ----------------------------------------------------------------------------
# Parser ASCII OPeNDAP
# ----------------------------------------------------------------------------
def parse_opendap_ascii(text: str, var_name: str) -> tuple[list, list]:
    """Parsea la respuesta ASCII de OPeNDAP para una variable Grid.

    Devuelve ``(data_block, time_values)`` donde:
      - ``data_block`` es una lista anidada de floats con la forma
        ``[time][...dims...]`` tal como la devuelve OPeNDAP.
      - ``time_values`` es la lista de valores del eje tiempo (horas
        desde 1800-01-01).

    Formato esperado (ejemplo)::

        Dataset { ... } ...;
        ---------------------------------------------
        varname.varname[T][...][...]
        [0][0][0], v, v, v, ...
        [0][0][1], v, v, v, ...
        ...
        varname.time[T]
        t0, t1, t2, ...
    """
    # Localiza el bloque de datos de la variable.
    header = f"{var_name}.{var_name}["
    idx = text.find(header)
    if idx < 0:
        raise OpendapError(f"No se encontró el bloque de datos para {var_name!r}")
    # Recorta desde el header hasta el final.
    rest = text[idx:]
    # El bloque termina antes del siguiente bloque "varname.<axis>[" o "---"
    end_match = re.search(r"\n\s*[\w]+(?:\.\w+)?\.\w+\[", rest[1:])
    if end_match:
        rest = rest[: end_match.start() + 1]
    data_lines: list[list[float]] = []
    index_re = re.compile(r"^\[\d+(?:\]\[\d+)*\],\s*(.+)$")
    for line in rest.splitlines():
        m = index_re.match(line.strip())
        if not m:
            continue
        values_str = m.group(1)
        try:
            values = [
                float(v) if v not in ("NaN", "nan", "-NaN") else None
                for v in re.split(r"\s*,\s*", values_str.strip())
            ]
        except ValueError as e:
            raise OpendapError(f"Valor numérico inválido en línea: {line!r}: {e}")
        data_lines.append(values)
    if not data_lines:
        raise OpendapError(f"No se parsearon líneas de datos para {var_name!r}")
    # Localiza el eje tiempo.
    time_header = f"{var_name}.time["
    tidx = text.find(time_header)
    time_values: list[float] = []
    if tidx >= 0:
        trest = text[tidx:]
        # La primera línea tras el header contiene los valores.
        for line in trest.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            if line.startswith("[") or not re.match(r"^[\d\.\-,\s]+$", line):
                break
            try:
                time_values = [float(v) for v in re.split(r"\s*,\s*", line)]
            except ValueError:
                break
            break
    return data_lines, time_values


def hours_since_1800_to_iso(hours: float) -> str:
    """Convierte 'hours since 1800-01-01' a 'YYYY-MM'."""
    return time_since_1800_to_iso(hours, unit="hours")


def time_since_1800_to_iso(value: float, unit: str = "hours") -> str:
    """Convierte 'value since 1800-01-01' a 'YYYY-MM'.

    ``unit`` puede ser ``'hours'`` o ``'days'``.
    """
    from datetime import timedelta

    base = datetime(1800, 1, 1, tzinfo=timezone.utc)
    try:
        if unit == "hours":
            delta = timedelta(hours=float(value))
        elif unit == "days":
            delta = timedelta(days=float(value))
        else:
            raise ValueError(f"Unidad no soportada: {unit!r}")
        dt = base + delta
        return f"{dt.year:04d}-{dt.month:02d}"
    except (OverflowError, ValueError):
        return ""


# ----------------------------------------------------------------------------
# Helpers de cálculo
# ----------------------------------------------------------------------------
def spatial_average_nino34(
    data_lines: list[list[float]],
    lat_values: list[float],
    lon_values: list[float],
    lat_min: float = NINO34_LAT_MIN,
    lat_max: float = NINO34_LAT_MAX,
    lon_min: float = NINO34_LON_MIN,
    lon_max: float = NINO34_LON_MAX,
) -> Optional[float]:
    """Calcula el promedio espacial sobre la región Niño 3.4.

    ``data_lines`` se asume de la forma ``[lat][lon]`` (un paso temporal).
    """
    # Máscaras de lat/lon dentro del bounding box.
    lat_mask = [
        i for i, v in enumerate(lat_values) if lat_min <= v <= lat_max
    ]
    lon_mask = [
        j for j, v in enumerate(lon_values) if lon_min <= v <= lon_max
    ]
    if not lat_mask or not lon_mask:
        return None
    # Colecta valores no-NaN.
    vals: list[float] = []
    for i in lat_mask:
        if i >= len(data_lines):
            continue
        row = data_lines[i]
        for j in lon_mask:
            if j >= len(row):
                continue
            v = row[j]
            if v is not None and not (v != v):  # NaN check
                vals.append(v)
    if not vals:
        return None
    return sum(vals) / len(vals)


def compute_monthly_anomaly(
    points: list[MonthlyPoint], baseline_years: tuple[int, int] = CLIM_BASELINE_YEARS
) -> list[MonthlyPoint]:
    """Calcula anomalías respecto a la climatología mensual del periodo dado.

    Para cada mes (1–12), calcula la media del periodo ``baseline_years``
    y la resta a cada punto.
    """
    # Agrupa por mes calendario.
    clim: dict[int, list[float]] = {m: [] for m in range(1, 13)}
    for p in points:
        try:
            y_str, m_str = p.month.split("-")
            y, m = int(y_str), int(m_str)
        except (ValueError, AttributeError):
            continue
        if (
            baseline_years[0] <= y <= baseline_years[1]
            and p.value is not None
        ):
            clim[m].append(p.value)
    clim_mean = {
        m: (sum(v) / len(v)) if v else None for m, v in clim.items()
    }
    # Resta la climatología.
    out: list[MonthlyPoint] = []
    for p in points:
        try:
            m = int(p.month.split("-")[1])
        except (ValueError, IndexError):
            out.append(p)
            continue
        base = clim_mean.get(m)
        if p.value is None or base is None:
            out.append(
                MonthlyPoint(month=p.month, value=None, flag=p.flag)
            )
        else:
            out.append(
                MonthlyPoint(
                    month=p.month, value=round(p.value - base, 3), flag=p.flag
                )
            )
    return out


# ----------------------------------------------------------------------------
# Fetcher OPeNDAP base
# ----------------------------------------------------------------------------
class OpendapFetcher:
    """Base para fetchers OPeNDAP de PSL.

    Subclases deben definir ``base_url`` y ``variable``.
    """

    base_url: str = ""
    variable: str = ""
    timeout: float = 120.0  # OPeNDAP puede ser lento para rangos grandes
    max_retries: int = 3
    user_agent: str = "Observatorio-ENSO-Peru/2.0 (opendap; +https://github.com/)"

    def fetch_ascii(self, url: str) -> str:
        """Descarga y devuelve el texto ASCII."""
        if httpx is None:
            raise OpendapError("httpx no disponible")
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                    resp = client.get(
                        url, headers={"User-Agent": self.user_agent}
                    )
                    resp.raise_for_status()
                    return resp.text
            except Exception as e:  # noqa: BLE001
                last_exc = e
                import time

                time.sleep(2 ** attempt + 0.5)
        raise OpendapError(f"Fallo tras {self.max_retries} reintentos: {last_exc}")


# ----------------------------------------------------------------------------
# u850 — NCEP/NCAR Reanalysis1 monthly mean
# ----------------------------------------------------------------------------
class NcepU850Fetcher(OpendapFetcher):
    """Fetcher de anomalía mensual del viento zonal a 850 hPa (NCEP Reanalysis).

    Endpoint: ``https://psl.noaa.gov/thredds/dodsC/Datasets/ncep.reanalysis.derived/pressure/uwnd.mon.mean.nc``

    La variable ``uwnd`` es un Grid ``[time=938][level=17][lat=73][lon=144]``.
    Indices:
      - ``level[2] = 850 mb``
      - ``lat[34..38] = 5°N..5°S`` (step 2.5°)
      - ``lon[76..96] = 190°E..240°E`` (step 2.5°)
    """

    source_id = "noaa-cpc-u850-anom"
    base_url = (
        "https://psl.noaa.gov/thredds/dodsC/Datasets/ncep.reanalysis.derived/"
        "pressure/uwnd.mon.mean.nc"
    )
    variable = "uwnd"
    # Indices fijos (verificados contra DDS/DAS de PSL).
    LEVEL_IDX = 2  # 850 mb
    LAT_START, LAT_STOP = 34, 38  # 5°N..5°S
    LON_START, LON_STOP = 76, 96  # 190°E..240°E

    def fetch_all(self) -> list[MonthlyPoint]:
        """Descarga la serie completa de u850 sobre Niño 3.4 (en paralelo)."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Primero, pide el tamaño del eje tiempo.
        dds_url = f"{self.base_url}.dds"
        dds = self.fetch_ascii(dds_url)
        m = re.search(r"time\s*=\s*(\d+)", dds)
        if not m:
            raise OpendapError(f"No se pudo determinar el tamaño de time en DDS: {dds[:200]}")
        n_time = int(m.group(1))
        # Pide la serie completa en lotes (para evitar timeouts).
        # Usamos lotes de 120 meses y los fetchamos en paralelo.
        batches: list[tuple[int, int]] = []
        batch = 120  # meses por lote (~10 años)
        for start in range(0, n_time, batch):
            stop = min(start + batch - 1, n_time - 1)
            batches.append((start, stop))

        def fetch_batch(start_stop: tuple[int, int]) -> list[MonthlyPoint]:
            start, stop = start_stop
            url = (
                f"{self.base_url}.ascii?"
                f"{self.variable}%5B{start}:1:{stop}%5D"
                f"%5B{self.LEVEL_IDX}:1:{self.LEVEL_IDX}%5D"
                f"%5B{self.LAT_START}:1:{self.LAT_STOP}%5D"
                f"%5B{self.LON_START}:1:{self.LON_STOP}%5D"
            )
            text = self.fetch_ascii(url)
            data_lines, time_values = parse_opendap_ascii(text, self.variable)
            n_lat = self.LAT_STOP - self.LAT_START + 1
            n_lon = self.LON_STOP - self.LON_START + 1
            batch_points: list[MonthlyPoint] = []
            for t_idx in range(len(time_values)):
                start_line = t_idx * n_lat
                end_line = start_line + n_lat
                if end_line > len(data_lines):
                    break
                matrix = data_lines[start_line:end_line]
                lat_vals = [90.0 - (self.LAT_START + i) * 2.5 for i in range(n_lat)]
                lon_vals = [(self.LON_START + j) * 2.5 for j in range(n_lon)]
                mean = spatial_average_nino34(matrix, lat_vals, lon_vals)
                month = hours_since_1800_to_iso(time_values[t_idx])
                now = datetime.now(timezone.utc)
                flag = SeriesFlag.FINAL
                try:
                    y, m = int(month.split("-")[0]), int(month.split("-")[1])
                    if (y == now.year and m >= now.month - 1) or (
                        y == now.year - 1 and m == 12 and now.month == 1
                    ):
                        flag = SeriesFlag.PRELIMINARY
                except (ValueError, IndexError):
                    pass
                batch_points.append(
                    MonthlyPoint(month=month, value=mean, flag=flag)
                )
            return batch_points

        # Fetch batches in parallel (max 4 workers).
        points_by_batch: dict[int, list[MonthlyPoint]] = {}
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(fetch_batch, b): b[0] for b in batches}
            for future in as_completed(futures):
                start_idx = futures[future]
                points_by_batch[start_idx] = future.result()
        # Concatena en orden.
        points: list[MonthlyPoint] = []
        for start_idx in sorted(points_by_batch.keys()):
            points.extend(points_by_batch[start_idx])
        return points

    def fetch_anomaly_series(self) -> list[MonthlyPoint]:
        """Devuelve la serie de anomalías (respecto a 1991–2020)."""
        raw = self.fetch_all()
        return compute_monthly_anomaly(raw)


# ----------------------------------------------------------------------------
# D20 — GODAS dbss_obil (isothermal layer depth, proxy de D20)
# ----------------------------------------------------------------------------
class GodasD20Fetcher(OpendapFetcher):
    """Fetcher de anomalía mensual de D20 (GODAS ``dbss_obil``).

    Endpoint: ``https://psl.noaa.gov/thredds/dodsC/Datasets/godas/dbss_obil.{year}.nc``

    La variable ``dbss_obil`` es un Grid ``[time=12][lat=418][lon=360]``.
    Indices para Niño 3.4 (5°S–5°N, 190°E–240°E):
      - ``lat``: GODAS lat[0] = -74.5, step ~0.3333 → lat[209..239] ≈ -5°..5°
      - ``lon``: GODAS lon[0] = 0.5, step 1.0 → lon[190..240] ≈ 190.5°..240.5°
    """

    source_id = "noaa-cpc-godas-d20"
    base_url_tpl = (
        "https://psl.noaa.gov/thredds/dodsC/Datasets/godas/dbss_obil.{year}.nc"
    )
    variable = "dbss_obil"
    # Indices para Niño 3.4 en GODAS (lat step ≈ 0.3333, lon step = 1.0)
    LAT_START, LAT_STOP = 209, 239  # ≈ -5°..5°
    LON_START, LON_STOP = 190, 240  # ≈ 190.5°..240.5°
    # Años disponibles en PSL (verificados en catálogo).
    FIRST_YEAR = 1980
    LAST_YEAR = datetime.now(timezone.utc).year

    def fetch_year(self, year: int) -> list[MonthlyPoint]:
        """Descarga un año completo de D20."""
        url_base = self.base_url_tpl.format(year=year)
        # Consulta el DDS para tamaño de tiempo.
        dds = self.fetch_ascii(f"{url_base}.dds")
        m = re.search(r"time\s*=\s*(\d+)", dds)
        if not m:
            raise OpendapError(f"No se pudo determinar el tamaño de time para {year}: {dds[:200]}")
        n_time = int(m.group(1))
        # Un solo lote por año (12 meses).
        url = (
            f"{url_base}.ascii?"
            f"{self.variable}%5B0:1:{n_time - 1}%5D"
            f"%5B{self.LAT_START}:1:{self.LAT_STOP}%5D"
            f"%5B{self.LON_START}:1:{self.LON_STOP}%5D"
        )
        text = self.fetch_ascii(url)
        data_lines, time_values = parse_opendap_ascii(text, self.variable)
        n_lat = self.LAT_STOP - self.LAT_START + 1
        # GODAS lat[0] = -74.5, step ~0.3333
        lat_vals = [-74.5 + (self.LAT_START + i) * (1.0 / 3.0) for i in range(n_lat)]
        # GODAS lon[0] = 0.5, step 1.0
        n_lon = self.LON_STOP - self.LON_START + 1
        lon_vals = [0.5 + (self.LON_START + j) * 1.0 for j in range(n_lon)]
        points: list[MonthlyPoint] = []
        for t_idx in range(len(time_values)):
            start_line = t_idx * n_lat
            end_line = start_line + n_lat
            if end_line > len(data_lines):
                break
            matrix = data_lines[start_line:end_line]
            mean = spatial_average_nino34(matrix, lat_vals, lon_vals)
            # GODAS time units are 'days since 1800-01-01' (not hours).
            month = time_since_1800_to_iso(time_values[t_idx], unit="days")
            now = datetime.now(timezone.utc)
            flag = SeriesFlag.FINAL
            try:
                y, m = int(month.split("-")[0]), int(month.split("-")[1])
                if y == now.year and m >= now.month - 2:
                    flag = SeriesFlag.PRELIMINARY
            except (ValueError, IndexError):
                pass
            points.append(MonthlyPoint(month=month, value=mean, flag=flag))
        return points

    def fetch_all(self) -> list[MonthlyPoint]:
        """Descarga todos los años disponibles (en paralelo)."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        years = list(range(self.FIRST_YEAR, self.LAST_YEAR + 1))
        points_by_year: dict[int, list[MonthlyPoint]] = {}
        # Fetch years in parallel (max 6 workers to be polite to PSL).
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(self.fetch_year, y): y for y in years}
            for future in as_completed(futures):
                year = futures[future]
                try:
                    year_points = future.result()
                    points_by_year[year] = year_points
                except OpendapError as e:
                    # Si el año actual aún no tiene archivo, lo saltamos.
                    if year == self.LAST_YEAR:
                        continue
                    # Para otros años, propagamos el error.
                    raise
        # Ordena por año y concatena.
        points: list[MonthlyPoint] = []
        for year in sorted(points_by_year.keys()):
            points.extend(points_by_year[year])
        return points

    def fetch_anomaly_series(self) -> list[MonthlyPoint]:
        """Devuelve la serie de anomalías (respecto a 1991–2020)."""
        raw = self.fetch_all()
        return compute_monthly_anomaly(raw)


# ----------------------------------------------------------------------------
# Helpers de interpretación
# ----------------------------------------------------------------------------
def u850_direction(anom: Optional[float]) -> str:
    """Devuelve la interpretación textual de la anomalía u850."""
    if anom is None:
        return "Sin datos"
    if anom > 0.5:
        return "Anomalía de westerlies (reforzada hacia el este)"
    if anom < -0.5:
        return "Anomalía de easterlies (reforzada hacia el oeste)"
    return "Anomalía neutral (cerca de cero)"


def d20_interpretation(anom: Optional[float]) -> str:
    """Devuelve la interpretación textual de la anomalía D20."""
    if anom is None:
        return "Sin datos"
    if anom > 10:
        return "Termoclina más profunda de lo normal (El Niño)"
    if anom < -10:
        return "Termoclina más somera de lo normal (La Niña)"
    return "Termoclina cerca de la profundidad normal"
