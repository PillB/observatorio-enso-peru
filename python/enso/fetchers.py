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
    "enfen-imarpe-icen": EnfenIcenFetcher,
}


def get_fetcher_class(source_id: str) -> Optional[type[Fetcher]]:
    """Devuelve la clase de fetcher asociada a un ``source_id``."""
    return FETCHERS.get(source_id)
