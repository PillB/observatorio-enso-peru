"""Fetchers con reintentos, HTTP condicional, validación, caché y degradación.

Diseño:
    - ``Fetcher``: clase base abstracta con reintentos (backoff exponencial
      + jitter), HTTP condicional (ETag / If-Modified-Since), validación de
      contenido antes de parsear, checksum SHA-256, caché en disco bajo
      ``python/cache/`` y preservación del último válido ante fallos.
    - Fetchers concretos para PSL (Niño 1+2, Niño 3.4, SOI), CPC (RONI,
      GODAS, u850) y ENFEN (ICEN, HTML con BeautifulSoup).

Políticas:
    - NUNCA fabricar valores: si el contenido no valida, se lanza
      ``SchemaValidationError`` y el orquestador preserva el último válido.
    - Los datos preliminares se marcan explícitamente en los metadatos.
    - Los huecos se preservan (NaN/None); no se rellenan.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

try:
    import httpx
except ImportError:  # pragma: no cover — httpx debería estar disponible.
    httpx = None  # type: ignore

from bs4 import BeautifulSoup  # type: ignore

from .models import MonthlyPoint, SeriesFlag


# ----------------------------------------------------------------------------
# Excepciones
# ----------------------------------------------------------------------------
class FetchError(Exception):
    """Error base de descarga."""


class RetryableFetchError(FetchError):
    """Error transitorio (timeout, 5xx, 429) — se reintenta."""


class RateLimitError(RetryableFetchError):
    """HTTP 429 — rate limit. Aplica backoff exponencial + jitter."""

    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class SchemaValidationError(FetchError):
    """El contenido descargado no cumple el esquema esperado.

    NO se debe fusionar silenciosamente: el orquestador debe preservar el
    último válido y registrar el fallo.
    """


class NotModified(FetchError):
    """HTTP 304 — el contenido no cambió desde la última descarga."""


# ----------------------------------------------------------------------------
# Resultado de descarga
# ----------------------------------------------------------------------------
@dataclass
class FetchResult:
    """Resultado de una descarga con metadatos completos."""

    source_id: str
    url: str
    content: bytes
    status_code: int
    fetched_at: str  # ISO-8601 UTC
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    sha256: str = ""
    preliminary: bool = False
    from_cache: bool = False
    notes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.sha256:
            self.sha256 = hashlib.sha256(self.content).hexdigest()


# ----------------------------------------------------------------------------
# Fetcher base
# ----------------------------------------------------------------------------
class Fetcher(ABC):
    """Base de descargadores con reintentos y HTTP condicional."""

    #: Identificador de la fuente (debe existir en ``SOURCES``).
    source_id: str = ""
    #: URL canónica.
    url: str = ""
    #: Timeout por defecto (segundos).
    timeout: float = 30.0
    #: Número máximo de reintentos.
    max_retries: int = 4
    #: Backoff base (segundos).
    backoff_base: float = 1.0
    #: Backoff máximo (segundos).
    backoff_cap: float = 60.0
    #: Tiempo entre llamadas a la misma fuente (rate-limit cortés).
    min_interval: float = 1.0

    def __init__(
        self,
        cache_dir: str | os.PathLike[str] = "python/cache",
        transport: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
        max_retries: int | None = None,
        timeout: float | None = None,
        backoff_base: float | None = None,
        backoff_cap: float | None = None,
        min_interval: float | None = None,
    ) -> None:
        self.cache_dir = os.fspath(cache_dir)
        self._transport = transport
        self._sleep = sleep
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._last_call_ts: float = 0.0
        if max_retries is not None:
            self.max_retries = max_retries
        if timeout is not None:
            self.timeout = timeout
        if backoff_base is not None:
            self.backoff_base = backoff_base
        if backoff_cap is not None:
            self.backoff_cap = backoff_cap
        if min_interval is not None:
            self.min_interval = min_interval
        os.makedirs(self.cache_dir, exist_ok=True)

    # ---- Propiedades ----
    @property
    def cache_path(self) -> str:
        """Ruta del archivo de caché para esta fuente."""
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", self.source_id or "unknown")
        return os.path.join(self.cache_dir, f"{safe}.json")

    # ---- Lógica de backoff ----
    def _backoff_seconds(self, attempt: int) -> float:
        """Backoff exponencial + jitter uniforme.

        attempt=0 → ~backoff_base; aumenta exponencialmente hasta backoff_cap.
        """
        base = min(self.backoff_cap, self.backoff_base * (2 ** attempt))
        jitter = random.uniform(0, base / 2)
        return base + jitter

    def _respect_rate_limit(self) -> None:
        """Espera si la última llamada fue demasiado reciente."""
        elapsed = time.monotonic() - self._last_call_ts
        if elapsed < self.min_interval:
            self._sleep(self.min_interval - elapsed)
        self._last_call_ts = time.monotonic()

    # ---- Caché ----
    def _read_cache_meta(self) -> dict[str, Any]:
        """Lee metadatos de caché (etag, last-modified, content)."""
        if not os.path.exists(self.cache_path):
            return {}
        try:
            with open(self.cache_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_cache(self, result: FetchResult) -> None:
        """Escribe el resultado (contenido + metadatos) en caché."""
        payload = {
            "source_id": result.source_id,
            "url": result.url,
            "content_b64": result.content.decode("latin-1"),
            "status_code": result.status_code,
            "fetched_at": result.fetched_at,
            "etag": result.etag,
            "last_modified": result.last_modified,
            "sha256": result.sha256,
            "preliminary": result.preliminary,
            "notes": result.notes,
        }
        tmp = self.cache_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.cache_path)

    def _load_cached_result(self) -> Optional[FetchResult]:
        meta = self._read_cache_meta()
        if not meta:
            return None
        return FetchResult(
            source_id=meta["source_id"],
            url=meta["url"],
            content=meta["content_b64"].encode("latin-1"),
            status_code=meta["status_code"],
            fetched_at=meta["fetched_at"],
            etag=meta.get("etag"),
            last_modified=meta.get("last_modified"),
            sha256=meta.get("sha256", ""),
            preliminary=meta.get("preliminary", False),
            from_cache=True,
            notes=meta.get("notes", {}),
        )

    # ---- Validación de contenido ----
    @abstractmethod
    def validate(self, content: bytes) -> None:
        """Valida el contenido descargado. Lanza ``SchemaValidationError`` si no cumple."""

    # ---- HTTP ----
    def _build_headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": "Observatorio-ENSO-Peru/1.0 (pipeline; +https://github.com/)",
            "Accept": "*/*",
        }
        meta = self._read_cache_meta()
        if meta.get("etag"):
            headers["If-None-Match"] = meta["etag"]
        if meta.get("last_modified"):
            headers["If-Modified-Since"] = meta["last_modified"]
        return headers

    def _do_request(self, client: Any) -> tuple[int, bytes, dict[str, str]]:
        """Ejecuta una petición HTTP. Devuelve (status, content, headers)."""
        resp = client.get(self.url, headers=self._build_headers(), timeout=self.timeout)
        return resp.status_code, resp.content, dict(resp.headers)

    # ---- Orquestación pública ----
    def fetch(self, allow_network: bool = True) -> FetchResult:
        """Descarga la fuente con reintentos, validación y caché.

        - Si la red falla tras todos los reintentos y existe un valor en
          caché, devuelve el caché marcado ``from_cache=True`` (no lanza).
        - Si la red falla y no hay caché, lanza ``FetchError``.
        - Si el contenido no valida, lanza ``SchemaValidationError`` (no se
          sobrescribe el caché).
        - Si HTTP 304 (Not Modified), devuelve el caché si existe, si no,
          lanza ``NotModified``.
        """
        last_error: Optional[Exception] = None
        if allow_network and httpx is not None:
            for attempt in range(self.max_retries + 1):
                try:
                    self._respect_rate_limit()
                    with httpx.Client(transport=self._transport) as client:
                        status, content, headers = self._do_request(client)
                    if status == 304:
                        cached = self._load_cached_result()
                        if cached is not None:
                            cached.from_cache = True
                            return cached
                        raise NotModified(f"{self.source_id}: 304 sin caché previo")
                    if status == 429:
                        retry_after = self._parse_retry_after(headers)
                        raise RateLimitError(
                            f"{self.source_id}: HTTP 429 rate limit", retry_after=retry_after
                        )
                    if status >= 500:
                        raise RetryableFetchError(
                            f"{self.source_id}: HTTP {status} (servidor)"
                        )
                    if status >= 400:
                        # Error de cliente: no se reintenta.
                        raise FetchError(f"{self.source_id}: HTTP {status}")
                    # 2xx: valida antes de cachear.
                    self.validate(content)
                    result = FetchResult(
                        source_id=self.source_id,
                        url=self.url,
                        content=content,
                        status_code=status,
                        fetched_at=self._now().isoformat(),
                        etag=headers.get("ETag"),
                        last_modified=headers.get("Last-Modified"),
                        preliminary=self._detect_preliminary(content, headers),
                        notes=self._extract_notes(content, headers),
                    )
                    self._write_cache(result)
                    return result
                except RateLimitError as e:
                    last_error = e
                    wait = (
                        e.retry_after
                        if e.retry_after is not None
                        else self._backoff_seconds(attempt)
                    )
                    self._sleep(max(0.5, float(wait)))
                    continue
                except RetryableFetchError as e:
                    last_error = e
                    self._sleep(self._backoff_seconds(attempt))
                    continue
                except SchemaValidationError:
                    # No se sobrescribe el caché. El orquestador decide.
                    raise
            # Agotados los reintentos: ¿hay caché?
            cached = self._load_cached_result()
            if cached is not None:
                cached.from_cache = True
                cached.notes = {**cached.notes, "degraded": True,
                                "last_error": str(last_error)}
                return cached
            raise FetchError(
                f"{self.source_id}: fallo tras {self.max_retries} reintentos: {last_error}"
            )
        # Sin red: usa caché si existe.
        cached = self._load_cached_result()
        if cached is not None:
            cached.from_cache = True
            cached.notes = {**cached.notes, "offline": True}
            return cached
        raise FetchError(f"{self.source_id}: sin red y sin caché disponible")

    # ---- Ganchos para subclases ----
    def _detect_preliminary(self, content: bytes, headers: dict[str, str]) -> bool:
        """Hook: devuelve True si el contenido es preliminar."""
        return False

    def _extract_notes(self, content: bytes, headers: dict[str, str]) -> dict[str, Any]:
        """Hook: extrae metadatos adicionales del contenido."""
        return {}

    @staticmethod
    def _parse_retry_after(headers: dict[str, str]) -> Optional[float]:
        """Parsea ``Retry-After`` (segundos o fecha HTTP)."""
        ra = headers.get("Retry-After") or headers.get("retry-after")
        if not ra:
            return None
        try:
            return float(ra)
        except ValueError:
            try:
                dt = datetime.strptime(ra, "%a, %d %b %Y %H:%M:%S %Z").replace(
                    tzinfo=timezone.utc
                )
                return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
            except ValueError:
                return None


# ----------------------------------------------------------------------------
# Fetchers concretos (PSL CSV / texto)
# ----------------------------------------------------------------------------
class PslCsvFetcher(Fetcher):
    """Fetcher para CSV de NOAA/PSL (Niño 1+2, Niño 3.4, SOI)."""

    #: Patrón de cabecera esperado (regex sobre la primera línea no vacía).
    expected_header_re: str = r"(year|Year|YEAR)"
    #: Número mínimo de columnas (year + 12 meses).
    min_columns: int = 13

    def validate(self, content: bytes) -> None:
        text = content.decode("utf-8", errors="replace")
        # Salta comentarios iniciales.
        lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
        if not lines:
            raise SchemaValidationError(f"{self.source_id}: contenido vacío")
        first = lines[0]
        if not re.search(self.expected_header_re, first, re.IGNORECASE):
            raise SchemaValidationError(
                f"{self.source_id}: cabecera inesperada: {first[:80]!r}"
            )
        # Verifica que al menos una fila tenga 13 columnas numéricas.
        # Soporta tanto CSV (coma) como texto ancho PSL (espacios).
        ok_rows = 0
        for ln in lines[1:40]:
            parts = re.split(r"[\s,]+", ln.strip())
            if len(parts) >= self.min_columns:
                try:
                    int(parts[0])
                    ok_rows += 1
                except ValueError:
                    continue
        if ok_rows == 0:
            raise SchemaValidationError(
                f"{self.source_id}: no se encontraron filas válidas"
            )

    def parse(self, result: FetchResult) -> list[MonthlyPoint]:
        """Parsea el CSV/texto a ``MonthlyPoint``. Devuelve NaN donde aplique."""
        text = result.content.decode("utf-8", errors="replace")
        points: list[MonthlyPoint] = []
        for ln in text.splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            parts = re.split(r"[\s,]+", ln.strip())
            if len(parts) < 13:
                continue
            try:
                year = int(parts[0])
            except ValueError:
                continue
            for m in range(12):
                raw = parts[m + 1]
                try:
                    val = float(raw)
                    if val <= -99.0 or val >= 9999.0:
                        val = None  # centinela de faltante común
                except ValueError:
                    val = None
                flag = SeriesFlag.PRELIMINARY if (
                    year == datetime.now(timezone.utc).year
                    and m + 1 >= datetime.now(timezone.utc).month - 1
                ) else SeriesFlag.FINAL
                points.append(
                    MonthlyPoint(
                        month=f"{year:04d}-{m + 1:02d}",
                        value=val,
                        flag=flag,
                    )
                )
        return points


class PslNino12Fetcher(PslCsvFetcher):
    source_id = "noaa-psl-nino12-anom"
    url = "https://psl.noaa.gov/data/timeseries/month/data/nino12.long.anom.csv"


class PslNino34Fetcher(PslCsvFetcher):
    source_id = "noaa-psl-nino34-ersst"
    url = "https://psl.noaa.gov/data/timeseries/month/Nino34_CPC"


class PslSoiFetcher(PslCsvFetcher):
    source_id = "noaa-psl-soi"
    url = "https://psl.noaa.gov/data/timeseries/month/data/soi.long.data"


# ----------------------------------------------------------------------------
# Fetcher HTML (CPC RONI, GODAS, u850) — extracción genérica
# ----------------------------------------------------------------------------
class CpcHtmlFetcher(Fetcher):
    """Fetcher para páginas HTML de NOAA/CPC (RONI, GODAS, u850).

    La validación verifica que el HTML contenga las palabras clave
    esperadas y un mínimo de tablas/números; la extracción real de tablas
    se hace en ``parse`` con BeautifulSoup.
    """

    expected_keywords: tuple[str, ...] = ("NOAA",)
    min_text_length: int = 200

    def validate(self, content: bytes) -> None:
        text = content.decode("utf-8", errors="replace")
        if len(text) < self.min_text_length:
            raise SchemaValidationError(
                f"{self.source_id}: contenido demasiado corto ({len(text)} bytes)"
            )
        lower = text.lower()
        for kw in self.expected_keywords:
            if kw.lower() not in lower:
                raise SchemaValidationError(
                    f"{self.source_id}: falta palabra clave esperada {kw!r}"
                )

    def parse_tables(self, result: FetchResult) -> list[list[list[str]]]:
        """Extrae todas las tablas HTML como listas de listas de strings."""
        soup = BeautifulSoup(result.content.decode("utf-8", errors="replace"), "html.parser")
        tables: list[list[list[str]]] = []
        for tbl in soup.find_all("table"):
            rows: list[list[str]] = []
            for tr in tbl.find_all("tr"):
                cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
                if cells:
                    rows.append(cells)
            if rows:
                tables.append(rows)
        return tables


class CpcRoniFetcher(CpcHtmlFetcher):
    source_id = "noaa-cpc-reroni"
    url = "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/"
    expected_keywords = ("RONI", "Niño")


class CpcGodasFetcher(CpcHtmlFetcher):
    source_id = "noaa-cpc-godas"
    url = "https://www.cpc.ncep.noaa.gov/products/GODAS/"
    expected_keywords = ("GODAS",)


class CpcU850Fetcher(CpcHtmlFetcher):
    source_id = "noaa-cpc-u850"
    url = "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_update/usswanim.shtml"
    expected_keywords = ("850",)


# ----------------------------------------------------------------------------
# GODAS D20 — Ocean Isothermal Layer Depth (dbss_obil) como proxy de D20
# ----------------------------------------------------------------------------
# GODAS no publica un archivo "D20" directo en PSL; el producto derivado más
# cercano es ``dbss_obil`` (Ocean Isothermal Layer Depth below sea surface),
# operación usado como proxy de la profundidad de la termoclina / isoterma de
# 20 °C en el Pacífico ecuatorial. Se adquiere vía OPeNDAP/ASCII del THREDDS
# de PSL. La climatología 1991-2020 se obtiene del archivo LTM derivado.
# ----------------------------------------------------------------------------
class GodasD20Fetcher(PslCsvFetcher):
    """Fetcher mensual de anomalías de D20 (proxy: dbss_obil) desde GODAS/PSL.

    Estrategia:
      1. Descarga la climatología mensual 1991-2020 desde
         ``Datasets/godas/Derived/dbss_obil.mon.ltm.nc`` (vía OPeNDAP/ASCII).
      2. Descarga, año por año desde 1980 hasta el año en curso, los
         archivos ``dbss_obil.<year>.nc`` subconjuntados a la región
         Niño 3.4 (5°S–5°N, 190°E–240°E).
      3. Calcula la media areal (ponderada por cos(lat)) por mes.
      4. Calcula anomalías vs la climatología 1991-2020.

    El contenido cacheado es un CSV sintético en formato PSL
    (``year m1 m2 ... m12``) que reutiliza ``validate``/``parse`` de
    ``PslCsvFetcher``.

    Notas científicas: ``dbss_obil`` es la profundidad de la capa isotermal
    (definida donde T = SST − 0.2 °C), no exactamente la profundidad de la
    isoterma de 20 °C (D20). En el Pacífico ecuatorial ambos son proxies
    operacionales equivalentes de la profundidad de la termoclina.
    """

    source_id = "noaa-cpc-godas-d20"
    url = "https://psl.noaa.gov/thredds/dodsC/Datasets/godas/dbss_obil"
    expected_header_re = r"(year|Year|YEAR)"

    # Región Niño 3.4 (5°S–5°N, 170°W–120°W = 190°E–240°E).
    # Resolución GODAS: lat 1/3° (418 pts), lon 1° (360 pts).
    # lat[i] = -74.5 + i/3  →  i(-5°) = 208.5, i(5°) = 238.5
    # lon[i] = 0.5 + i      →  i(190°) = 189.5, i(240°) = 239.5
    LAT_IDX_START = 209   # ≈ -4.83°
    LAT_IDX_END = 238     # ≈  4.83°
    LON_IDX_START = 190   # ≈ 190.5°E
    LON_IDX_END = 240     # ≈ 240.5°E

    GODAS_START_YEAR = 1980

    CLIMATOLOGY_URL = (
        "https://psl.noaa.gov/thredds/dodsC/Datasets/godas/Derived/"
        "dbss_obil.mon.ltm.nc.ascii"
    )
    ANNUAL_URL_TEMPLATE = (
        "https://psl.noaa.gov/thredds/dodsC/Datasets/godas/"
        "dbss_obil.{year}.nc.ascii"
    )

    def _subset_query(self, time_start: int = 0, time_end: int = 11) -> str:
        """Construye la query OPeNDAP/ASCII con subconjunto Niño 3.4."""
        return (
            f"dbss_obil%5B{time_start}:{time_end}%5D"
            f"%5B{self.LAT_IDX_START}:{self.LAT_IDX_END}%5D"
            f"%5B{self.LON_IDX_START}:{self.LON_IDX_END}%5D"
        )

    def _do_request(self, client: Any) -> tuple[int, bytes, dict[str, str]]:
        """Descarga climatología + años anuales, produce CSV sintético.

        NO fabrica valores: si un año falla, se omite (sin relleno).
        """
        from datetime import datetime as _dt, timezone as _tz

        # 1. Climatología (siempre 12 meses).
        clim_query = self._subset_query(0, 11)
        clim_url = f"{self.CLIMATOLOGY_URL}?{clim_query}"
        clim_resp = client.get(clim_url, headers=self._build_headers(),
                               timeout=self.timeout)
        clim_resp.raise_for_status()
        clim_text = clim_resp.text
        clim_monthly = _parse_opendap_grid_area_mean(
            clim_text, var_name="dbss_obil", lat_count=30, lon_count=51
        )
        if len(clim_monthly) != 12 or any(v is None for v in clim_monthly):
            raise SchemaValidationError(
                f"{self.source_id}: climatología incompleta "
                f"(meses={len(clim_monthly)})"
            )

        # 2. Años anuales. Para cada año, primero consultamos el .dds para
        #    conocer el número de meses disponibles (el año en curso puede
        #    estar incompleto) y luego pedimos el subconjunto correcto.
        current_year = _dt.now(_tz.utc).year
        by_year: dict[int, list[Optional[float]]] = {}
        for year in range(self.GODAS_START_YEAR, current_year + 1):
            base = self.ANNUAL_URL_TEMPLATE.format(year=year).replace(".ascii", "")
            dds_url = f"{base}.dds"
            try:
                self._respect_rate_limit()
                dds_resp = client.get(dds_url, headers=self._build_headers(),
                                      timeout=self.timeout)
                dds_resp.raise_for_status()
            except Exception:
                continue
            n_months = self._parse_time_dim(dds_resp.text, "dbss_obil")
            if n_months <= 0:
                continue
            data_url = (
                f"{self.ANNUAL_URL_TEMPLATE.format(year=year)}?"
                f"{self._subset_query(0, n_months - 1)}"
            )
            try:
                self._respect_rate_limit()
                resp = client.get(data_url, headers=self._build_headers(),
                                  timeout=self.timeout)
                resp.raise_for_status()
            except Exception:
                continue
            monthly_vals = _parse_opendap_grid_area_mean(
                resp.text, var_name="dbss_obil", lat_count=30, lon_count=51
            )
            if not monthly_vals:
                continue
            # Anomalías vs climatología
            anomalies: list[Optional[float]] = []
            for m, val in enumerate(monthly_vals):
                if val is None or m >= len(clim_monthly) or clim_monthly[m] is None:
                    anomalies.append(None)
                else:
                    anomalies.append(round(val - clim_monthly[m], 2))
            by_year[year] = anomalies

        # 3. Sintetiza CSV PSL-style. Se rellenan los meses faltantes del año
        #    en curso con -99.99 (centinela de faltante) para que el parser
        #    heredado de PslCsvFetcher (que exige 13 columnas) los acepte.
        lines = [
            "# GODAS dbss_obil — anomalía mensual (proxy D20)",
            "# Región: Niño 3.4 (5°S–5°N, 170°O–120°O)",
            "# Climatología: 1991-2020 (PSL ltm)",
            "# Fuente: NOAA/PSL THREDDS OPeNDAP ASCII",
            "# Unidades: m",
            "year Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec",
        ]
        for year in sorted(by_year.keys()):
            vals = by_year[year]
            # Rellena con None hasta 12 meses si el año está incompleto.
            padded = list(vals) + [None] * (12 - len(vals))
            row = [str(year)]
            for v in padded[:12]:
                row.append("-99.99" if v is None else f"{v:.2f}")
            lines.append(" ".join(row))
        content = "\n".join(lines).encode("utf-8") + b"\n"
        return 200, content, {}

    @staticmethod
    def _parse_time_dim(dds_text: str, var_name: str) -> int:
        """Extrae el tamaño de la dimensión time del DDS de OPeNDAP.

        Formato típico: ``Float32 dbss_obil[time = 12][lat = 30][lon = 51];``
        """
        # Busca el patrón ``var_name[time = N]``
        m = re.search(
            rf"{var_name}\[time\s*=\s*(\d+)\]", dds_text
        )
        if m:
            return int(m.group(1))
        # Alternativa: busca ``time = N`` en cualquier lugar.
        m = re.search(r"\[time\s*=\s*(\d+)\]", dds_text)
        return int(m.group(1)) if m else 0

    def _detect_preliminary(self, content: bytes, headers: dict[str, str]) -> bool:
        """Marca como preliminar si el último año está incompleto."""
        text = content.decode("utf-8", errors="replace")
        lines = [ln for ln in text.splitlines()
                 if ln.strip() and not ln.startswith("#")
                 and not ln.lower().startswith("year")]
        if not lines:
            return False
        last = lines[-1].split()
        if len(last) < 13:
            return True
        # Si hay -99.99 en los últimos meses del último año → preliminar
        return any(v == "-99.99" for v in last[-6:])


# ----------------------------------------------------------------------------
# NCEP u850 — Anomalía del viento zonal a 850 hPa
# ----------------------------------------------------------------------------
class NcepU850Fetcher(PslCsvFetcher):
    """Fetcher mensual de anomalías de u850 desde NCEP/NCAR Reanalysis (PSL).

    Estrategia:
      1. Descarga el ASCII del wizard de PSL (``timeseries.pl``) que devuelve
         la media areal mensual de u a 850 hPa en Niño 3.4 (5°S–5°N,
         170°O–120°O) desde 1948 hasta el presente.
      2. Calcula la climatología 1981-2010 desde la propia serie.
      3. Calcula anomalías mensuales.

    El contenido cacheado es el ASCII crudo del wizard (formato año + 12
    valores mensuales separados por espacios); ``validate``/``parse`` se
    heredan de ``PslCsvFetcher``. La anomalía se computa en ``parse``.

    Convención de signos: u > 0 ⇒ componente del oeste (westerly, hacia el
    este); u < 0 ⇒ componente del este (easterly, hacia el oeste).
    """

    source_id = "noaa-cpc-u850-anom"
    url = (
        "https://psl.noaa.gov/cgi-bin/data/timeseries/timeseries.pl"
        "?ntype=1&var=Zonal+Wind&level=850"
        "&lat1=-5&lat2=5&lon1=190&lon2=240"
        "&iseas=0&mon1=0&mon2=11&iarea=1&typeout=1"
        "&Submit=Create+Timeseries"
    )
    expected_header_re = r"(\d{4}|year|Year|YEAR)"

    #: Año base para la climatología (estándar NOAA actual).
    CLIM_START_YEAR = 1981
    CLIM_END_YEAR = 2010

    def validate(self, content: bytes) -> None:
        text = content.decode("utf-8", errors="replace")
        # El wizard PSL envuelve los datos en HTML; el bloque <pre> contiene
        # la tabla ASCII año + 12 valores mensuales separados por espacios.
        # Filtramos líneas HTML y buscamos filas válidas en todo el contenido.
        lines = [ln for ln in text.splitlines()
                 if ln.strip() and not ln.lstrip().startswith("<")
                 and not ln.lstrip().startswith("#")]
        if not lines:
            raise SchemaValidationError(
                f"{self.source_id}: contenido vacío o sólo HTML"
            )
        # Verifica que al menos una fila sea año + 12 valores numéricos.
        # Buscamos en TODAS las líneas (no sólo las primeras), porque el
        # wizard PSL inserta >800 líneas de HTML/JS antes del bloque <pre>.
        ok_rows = 0
        for ln in lines:
            parts = re.split(r"[\s,]+", ln.strip())
            if len(parts) >= 13:
                try:
                    int(parts[0])
                    ok_rows += 1
                except ValueError:
                    continue
        if ok_rows == 0:
            raise SchemaValidationError(
                f"{self.source_id}: no se encontraron filas válidas "
                f"(líneas no HTML: {len(lines)})"
            )

    def parse(self, result: FetchResult) -> list[MonthlyPoint]:
        """Parsea el ASCII del wizard PSL y calcula anomalías 1981-2010."""
        text = result.content.decode("utf-8", errors="replace")
        # Extrae sólo la tabla: líneas que empiezan con 4 dígitos (año).
        raw: list[tuple[int, list[Optional[float]]]] = []
        for ln in text.splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#") or ln.startswith("<"):
                continue
            parts = re.split(r"[\s,]+", ln.strip())
            if len(parts) < 13:
                continue
            try:
                year = int(parts[0])
            except ValueError:
                continue
            months: list[Optional[float]] = []
            for m in range(12):
                raw_v = parts[m + 1]
                try:
                    v = float(raw_v)
                    # Centinela de faltante del wizard PSL.
                    if v <= -999.0 or abs(v) > 1e6:
                        v = None
                except ValueError:
                    v = None
                months.append(v)
            raw.append((year, months))

        if not raw:
            return []

        # Climatología 1981-2010 (12 meses).
        clim: list[Optional[float]] = [None] * 12
        for month_idx in range(12):
            vals = [
                months[month_idx]
                for year, months in raw
                if self.CLIM_START_YEAR <= year <= self.CLIM_END_YEAR
                and months[month_idx] is not None
            ]
            if vals:
                clim[month_idx] = round(sum(vals) / len(vals), 3)

        # Anomalías
        points: list[MonthlyPoint] = []
        now = datetime.now(timezone.utc)
        for year, months in raw:
            for m, v in enumerate(months):
                if v is None or clim[m] is None:
                    anom = None
                else:
                    anom = round(v - clim[m], 2)
                flag = SeriesFlag.PRELIMINARY if (
                    year == now.year and m + 1 >= now.month - 1
                ) else SeriesFlag.FINAL
                points.append(
                    MonthlyPoint(
                        month=f"{year:04d}-{m + 1:02d}",
                        value=anom,
                        flag=flag,
                    )
                )
        return points


# ----------------------------------------------------------------------------
# Helpers OPeNDAP/ASCII
# ----------------------------------------------------------------------------
def _parse_opendap_grid_area_mean(
    text: str,
    var_name: str,
    lat_count: int,
    lon_count: int,
) -> list[Optional[float]]:
    """Parsea una respuesta OPeNDAP/ASCII de variable Grid 3D (time,lat,lon).

    Devuelve la media areal (ponderada por cos(lat)) para cada paso temporal.
    Si el contenido es un error OPeNDAP, devuelve lista vacía.
    """
    import math

    if not text or "Error {" in text:
        return []

    # Localiza la sección de datos: '<var_name>.<var_name>[T][L][Lo]'
    pattern = (
        rf"{var_name}\.{var_name}"
        r"\[(\d+)\]\[(\d+)\]\[(\d+)\]"
    )
    m = re.search(pattern, text)
    if not m:
        return []
    n_t, n_lat, n_lon = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if n_lat != lat_count or n_lon != lon_count:
        # La cuadrícula devuelta no coincide con la esperada.
        return []

    # Localiza la sección de latitudes (para ponderar por cos(lat)).
    lat_section_match = re.search(
        rf"{var_name}\.lat\[\d+\]\s*\n([^\[]*?)(?=\n\n|\Z)",
        text,
    )
    lats: list[float] = []
    if lat_section_match:
        for ln in lat_section_match.group(1).splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("Dataset"):
                continue
            try:
                lats = [float(v.strip()) for v in ln.split(",") if v.strip()]
                break
            except ValueError:
                continue
    if len(lats) != n_lat:
        # Sin latitudes confiables, no se puede ponderar.
        return []

    # Datos: filas "[t][lat], v1, v2, ..., vN"
    data: dict[tuple[int, int], list[float]] = {}
    for ln in text.splitlines():
        rm = re.match(r"\s*\[(\d+)\]\[(\d+)\],\s*(.*)", ln)
        if not rm:
            continue
        t = int(rm.group(1))
        lat_idx = int(rm.group(2))
        vals_str = rm.group(3).strip()
        try:
            vals = [float(v.strip()) for v in vals_str.split(",") if v.strip()]
        except ValueError:
            continue
        # Filtra centinelas de faltante típicos (-9.96921E36, etc.)
        vals = [v if abs(v) < 1e6 else float("nan") for v in vals]
        data[(t, lat_idx)] = vals

    # Media areal ponderada por cos(lat).
    results: list[Optional[float]] = []
    for t in range(n_t):
        lat_means: list[float] = []
        lat_weights: list[float] = []
        for lat_idx in range(n_lat):
            key = (t, lat_idx)
            if key not in data:
                continue
            vals = data[key]
            valid = [v for v in vals if not math.isnan(v)]
            if not valid:
                continue
            lat_means.append(sum(valid) / len(valid))
            lat_weights.append(math.cos(math.radians(lats[lat_idx])))
        if not lat_means:
            results.append(None)
            continue
        total_w = sum(lat_weights)
        weighted = sum(m * w for m, w in zip(lat_means, lat_weights))
        results.append(weighted / total_w if total_w > 0 else None)
    return results


# ----------------------------------------------------------------------------
# ENFEN ICEN — extracción desde HTML
# ----------------------------------------------------------------------------
class EnfenIcenFetcher(CpcHtmlFetcher):
    """Fetcher del panel ICEN de ENFEN/IMARPE (SIOFEN).

    El sitio publica el ICEN y el estado de alerta costera en un panel
    HTML. La validación verifica la presencia de las palabras clave ICEN y
    ENFEN, y la extracción devuelve tanto el valor numérico como el estado
    de alerta textual.
    """

    source_id = "enfen-imarpe-icen"
    url = "https://siofen.imarpe.gob.pe/nivel2/indice-costero-el-nino-icen"
    expected_keywords = ("ICEN",)

    def validate(self, content: bytes) -> None:
        text = content.decode("utf-8", errors="replace")
        if len(text) < self.min_text_length:
            raise SchemaValidationError(
                f"{self.source_id}: contenido demasiado corto ({len(text)} bytes)"
            )
        # ICEN debe aparecer en el HTML.
        if "ICEN" not in text and "icen" not in text.lower():
            raise SchemaValidationError(
                f"{self.source_id}: no se encuentra la referencia ICEN"
            )

    def parse(self, result: FetchResult) -> dict[str, Any]:
        """Extrae el valor ICEN más reciente y la alerta textual.

        Devuelve ``{"icen": float | None, "alert": str, "month": str | None}``.
        Si no se puede parsear un valor numérico, devuelve ``None`` (no
        fabrica).
        """
        text = result.content.decode("utf-8", errors="replace")
        soup = BeautifulSoup(text, "html.parser")
        # Busca números cerca de la palabra ICEN.
        icen_value: Optional[float] = None
        for node in soup.find_all(string=re.compile(r"ICEN", re.IGNORECASE)):
            tail = node.parent.get_text(" ", strip=True) if node.parent else str(node)
            m = re.search(r"ICEN[^0-9-+]*(-?\d+\.\d+)", tail, re.IGNORECASE)
            if m:
                try:
                    icen_value = round(float(m.group(1)), 2)
                    break
                except ValueError:
                    continue
        # Estado de alerta textual.
        alert = "Sin datos"
        for pattern in (
            r"Alerta de El Ni[ñn]o Costero",
            r"Vigilancia de El Ni[ñn]o Costero",
            r"Condici[óo]n Normal",
            r"La Ni[ñn]a Costero",
        ):
            m = re.search(pattern, text)
            if m:
                alert = m.group(0)
                break
        # Mes de referencia (busca YYYY-MM o Mes YYYY).
        month: Optional[str] = None
        m = re.search(r"\b(19\d{2}|20\d{2})-(0[1-9]|1[0-2])\b", text)
        if m:
            month = f"{m.group(1)}-{m.group(2)}"
        return {"icen": icen_value, "alert": alert, "month": month}


# ----------------------------------------------------------------------------
# Registro de fetchers
# ----------------------------------------------------------------------------
FETCHERS: dict[str, type[Fetcher]] = {
    "noaa-psl-nino12-anom": PslNino12Fetcher,
    "noaa-psl-nino34-ersst": PslNino34Fetcher,
    "noaa-psl-soi": PslSoiFetcher,
    "noaa-cpc-reroni": CpcRoniFetcher,
    "noaa-cpc-godas": CpcGodasFetcher,
    "noaa-cpc-u850": CpcU850Fetcher,
    "noaa-cpc-godas-d20": GodasD20Fetcher,
    "noaa-cpc-u850-anom": NcepU850Fetcher,
    "enfen-imarpe-icen": EnfenIcenFetcher,
}


def get_fetcher_class(source_id: str) -> Optional[type[Fetcher]]:
    """Devuelve la clase de fetcher asociada a un ``source_id``."""
    return FETCHERS.get(source_id)
