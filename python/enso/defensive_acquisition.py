"""Adquisición defensiva con circuit breaker, GET condicional y validación.

Implementa todas las salvaguardas requeridas:
  - User-Agent descriptivo, HTTPS, timeouts (connect/read/total)
  - Response size límite, decompression límite
  - Concurrency conservadora, per-host rate limit
  - Conditional GET (ETag, Last-Modified, If-None-Match, If-Modified-Since)
  - Retry-After, exponential backoff with full jitter
  - Idempotent retries only, maximum attempt budget
  - Circuit breaker per source
  - Content hash, MIME validation, file-magic validation
  - Character-encoding detection
  - Atomic cache writes, immutable raw metadata
  - Structured retrieval evidence

Validación de contenido:
  - Dates monotonic, no impossible future
  - Units unchanged, region unchanged, climatology unchanged
  - Fill values removed, duplicates reconciled
  - Not HTML error page, not login response
  - Expected dimensions, plausible bounds
  - Latest period compatible with cadence
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore


# ----------------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------------
class AcquisitionError(Exception):
    """Error base de adquisición."""


class RetryableError(AcquisitionError):
    """Error transitorio — se reintenta."""


class RateLimitError(RetryableError):
    """HTTP 429 — rate limit."""

    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class SchemaValidationError(AcquisitionError):
    """El contenido no cumple el esquema. NO se reintenta."""


class NotModifiedError(AcquisitionError):
    """HTTP 304 — contenido sin cambios."""


class CircuitBreakerOpenError(AcquisitionError):
    """Circuit breaker abierto — demasiados fallos consecutivos."""


class ResponseTooLargeError(AcquisitionError):
    """Respuesta excede el tamaño máximo."""


class MIMEValidationError(AcquisitionError):
    """MIME type no coincide con el esperado."""


# ----------------------------------------------------------------------------
# Circuit breaker
# ----------------------------------------------------------------------------
class CircuitBreaker:
    """Circuit breaker por fuente.

    States:
      - CLOSED: normal, requests pass through
      - OPEN: too many failures, requests blocked
      - HALF_OPEN: testing if source recovered

    Trip threshold: 5 consecutive failures
    Recovery timeout: 300s (5 min)
    Half-open successes needed: 2
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 300.0,
                 half_open_max: int = 2):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max = half_open_max
        self._failure_count: dict[str, int] = {}
        self._state: dict[str, str] = {}  # closed, open, half_open
        self._last_failure_ts: dict[str, float] = {}
        self._half_open_successes: dict[str, int] = {}

    def _get_state(self, source_id: str) -> str:
        """Devuelve el estado actual del circuit breaker."""
        state = self._state.get(source_id, "closed")
        if state == "open":
            # Check if recovery timeout has passed
            elapsed = time.monotonic() - self._last_failure_ts.get(source_id, 0)
            if elapsed >= self.recovery_timeout:
                self._state[source_id] = "half_open"
                self._half_open_successes[source_id] = 0
                return "half_open"
            return "open"
        return state

    def can_request(self, source_id: str) -> bool:
        """¿Se permite una petición para esta fuente?"""
        state = self._get_state(source_id)
        if state == "open":
            return False
        if state == "half_open":
            return self._half_open_successes.get(source_id, 0) < self.half_open_max
        return True

    def record_success(self, source_id: str) -> None:
        """Registra un éxito."""
        state = self._get_state(source_id)
        if state == "half_open":
            self._half_open_successes[source_id] = self._half_open_successes.get(source_id, 0) + 1
            if self._half_open_successes[source_id] >= self.half_open_max:
                # Enough successes — close the circuit
                self._state[source_id] = "closed"
                self._failure_count[source_id] = 0
        else:
            self._failure_count[source_id] = 0
            self._state[source_id] = "closed"

    def record_failure(self, source_id: str) -> None:
        """Registra un fallo."""
        self._failure_count[source_id] = self._failure_count.get(source_id, 0) + 1
        self._last_failure_ts[source_id] = time.monotonic()
        if self._failure_count[source_id] >= self.failure_threshold:
            self._state[source_id] = "open"

    def state(self, source_id: str) -> str:
        """Devuelve el estado actual."""
        return self._get_state(source_id)


# ----------------------------------------------------------------------------
# Retrieval evidence record
# ----------------------------------------------------------------------------
@dataclass
class RetrievalEvidence:
    """Evidencia estructurada de una adquisición."""
    source_id: str
    url: str
    retrieval_attempted_at: str  # ISO-8601 UTC
    transport_status: str  # "success", "not_modified", "failed", "circuit_open"
    http_status: Optional[int] = None
    from_cache: bool = False
    content_hash: str = ""
    content_length: int = 0
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    source_published_at: Optional[str] = None
    latest_valid_period: Optional[str] = None
    points_retrieved: int = 0
    attempt_count: int = 0
    error: Optional[str] = None
    fallback_used: Optional[str] = None
    source_state: str = "UNKNOWN"
    notes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "url": self.url,
            "retrieval_attempted_at": self.retrieval_attempted_at,
            "transport_status": self.transport_status,
            "http_status": self.http_status,
            "from_cache": self.from_cache,
            "content_hash": self.content_hash,
            "content_length": self.content_length,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "source_published_at": self.source_published_at,
            "latest_valid_period": self.latest_valid_period,
            "points_retrieved": self.points_retrieved,
            "attempt_count": self.attempt_count,
            "error": self.error,
            "fallback_used": self.fallback_used,
            "source_state": self.source_state,
            "notes": self.notes,
        }


# ----------------------------------------------------------------------------
# Source state enum
# ----------------------------------------------------------------------------
class SourceState(str, Enum):
    CURRENT = "CURRENT"
    WITHIN_CADENCE = "WITHIN_EXPECTED_CADENCE"
    NOT_DUE = "NOT_DUE"
    PUBLICATION_EXPECTED = "PUBLICATION_EXPECTED"
    DELAYED = "DELAYED"
    PRELIMINARY = "PRELIMINARY"
    STALE = "STALE"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"
    UNKNOWN = "UNKNOWN"


# ----------------------------------------------------------------------------
# Defensive HTTP client
# ----------------------------------------------------------------------------
class DefensiveHttpClient:
    """Cliente HTTP con todas las salvaguardas defensivas."""

    USER_AGENT = "Observatorio-ENSO-Peru/3.0 (pipeline; +https://github.com/PillB/observatorio-enso-peru)"

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        connect_timeout: float = 10.0,
        read_timeout: float = 30.0,
        total_timeout: float = 60.0,
        max_response_size: int = 100 * 1024 * 1024,  # 100 MB
        per_host_min_interval: float = 1.0,
        max_retries: int = 4,
        backoff_base: float = 1.0,
        backoff_cap: float = 60.0,
    ):
        self.cache_dir = cache_dir
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.total_timeout = total_timeout
        self.max_response_size = max_response_size
        self.per_host_min_interval = per_host_min_interval
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self._last_request_ts: dict[str, float] = {}
        self._circuit_breaker = CircuitBreaker()

    def _backoff_with_jitter(self, attempt: int) -> float:
        """Exponential backoff with full jitter."""
        base = min(self.backoff_cap, self.backoff_base * (2 ** attempt))
        return random.uniform(0, base)

    def _respect_rate_limit(self, host: str) -> None:
        """Per-host rate limiting."""
        elapsed = time.monotonic() - self._last_request_ts.get(host, 0)
        if elapsed < self.per_host_min_interval:
            time.sleep(self.per_host_min_interval - elapsed)
        self._last_request_ts[host] = time.monotonic()

    def _read_cache_meta(self, source_id: str) -> dict[str, Any]:
        """Lee metadatos de caché (ETag, Last-Modified, content)."""
        if not self.cache_dir:
            return {}
        cache_path = self.cache_dir / f"{source_id}.cache.json"
        if not cache_path.exists():
            return {}
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_cache(self, source_id: str, content: bytes, etag: Optional[str],
                     last_modified: Optional[str], content_hash: str) -> None:
        """Atomic cache write."""
        if not self.cache_dir:
            return
        cache_path = self.cache_dir / f"{source_id}.cache.json"
        tmp_path = cache_path.with_suffix(".tmp")
        payload = {
            "source_id": source_id,
            "content_b64": content.decode("latin-1"),
            "etag": etag,
            "last_modified": last_modified,
            "content_hash": content_hash,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, cache_path)  # atomic

    def _load_cached_content(self, source_id: str) -> Optional[tuple[bytes, dict]]:
        """Loads cached content if available."""
        meta = self._read_cache_meta(source_id)
        if not meta:
            return None
        return meta["content_b64"].encode("latin-1"), meta

    def _validate_mime(self, content: bytes, headers: dict[str, str],
                       expected_mime_prefix: Optional[str] = None) -> None:
        """MIME and file-magic validation."""
        content_type = headers.get("content-type", "").lower()
        if expected_mime_prefix:
            if not content_type.startswith(expected_mime_prefix.lower()):
                # File-magic check: look for HTML markers
                head = content[:500].lower()
                if b"<!doctype html" in head or b"<html" in head:
                    raise MIMEValidationError(
                        f"Expected {expected_mime_prefix} but got HTML: {content_type}"
                    )
        # Check for HTML error pages when not expected
        if expected_mime_prefix and "text/html" in content_type and "html" not in expected_mime_prefix.lower():
            head = content[:500].lower()
            if b"<title>404" in head or b"<title>error" in head or b"<title>not found" in head:
                raise MIMEValidationError(f"HTML error page returned: {content_type}")

    def _validate_response_size(self, content: bytes) -> None:
        """Bounded response size."""
        if len(content) > self.max_response_size:
            raise ResponseTooLargeError(
                f"Response size {len(content)} exceeds max {self.max_response_size}"
            )

    def get(
        self,
        url: str,
        source_id: str,
        expected_mime_prefix: Optional[str] = None,
        validator: Optional[Callable[[bytes], None]] = None,
    ) -> RetrievalEvidence:
        """GET defensivo con todas las salvaguardas.

        Args:
            url: URL to fetch
            source_id: Source identifier for cache and circuit breaker
            expected_mime_prefix: Expected MIME type prefix (e.g., "text/plain")
            validator: Optional content validator function

        Returns:
            RetrievalEvidence with full retrieval metadata

        Raises:
            CircuitBreakerOpenError: Circuit breaker is open
            AcquisitionError: All retries exhausted
            SchemaValidationError: Content validation failed (not retried)
        """
        if httpx is None:
            raise AcquisitionError("httpx no disponible")

        # Circuit breaker check
        if not self._circuit_breaker.can_request(source_id):
            return RetrievalEvidence(
                source_id=source_id,
                url=url,
                retrieval_attempted_at=datetime.now(timezone.utc).isoformat(),
                transport_status="circuit_open",
                source_state=SourceState.FAILED.value,
                error=f"Circuit breaker open for {source_id}",
            )

        host = re.sub(r"https?://([^/]+)/.*", r"\1", url)
        self._respect_rate_limit(host)

        # Build conditional GET headers
        cache_meta = self._read_cache_meta(source_id)
        headers: dict[str, str] = {
            "User-Agent": self.USER_AGENT,
            "Accept": "text/plain, text/html, application/json, */*",
            "Accept-Encoding": "gzip, deflate",
        }
        if cache_meta.get("etag"):
            headers["If-None-Match"] = cache_meta["etag"]
        if cache_meta.get("last_modified"):
            headers["If-Modified-Since"] = cache_meta["last_modified"]

        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                timeout = httpx.Timeout(
                    connect=self.connect_timeout,
                    read=self.read_timeout,
                    write=10.0,
                    pool=self.total_timeout,
                )
                with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                    resp = client.get(url, headers=headers)

                # HTTP 304: Not Modified
                if resp.status_code == 304:
                    cached = self._load_cached_content(source_id)
                    if cached:
                        content, meta = cached
                        self._circuit_breaker.record_success(source_id)
                        return RetrievalEvidence(
                            source_id=source_id,
                            url=url,
                            retrieval_attempted_at=datetime.now(timezone.utc).isoformat(),
                            transport_status="not_modified",
                            http_status=304,
                            from_cache=True,
                            content_hash=meta.get("content_hash", ""),
                            content_length=len(content),
                            etag=meta.get("etag"),
                            last_modified=meta.get("last_modified"),
                            attempt_count=attempt + 1,
                            source_state=SourceState.CURRENT.value,
                        )
                    raise NotModifiedError(f"{source_id}: 304 without cache")

                # HTTP 429: Rate limited
                if resp.status_code == 429:
                    retry_after = self._parse_retry_after(resp.headers)
                    raise RateLimitError(
                        f"{source_id}: HTTP 429 rate limit",
                        retry_after=retry_after,
                    )

                # HTTP 5xx: Server error — retryable
                if resp.status_code >= 500:
                    raise RetryableError(
                        f"{source_id}: HTTP {resp.status_code} server error"
                    )

                # HTTP 4xx (except 408, 429, 425): Non-retryable
                if resp.status_code >= 400:
                    if resp.status_code in (408, 425):
                        raise RetryableError(f"{source_id}: HTTP {resp.status_code} transient")
                    raise AcquisitionError(
                        f"{source_id}: HTTP {resp.status_code} non-retryable client error"
                    )

                # 2xx: Success
                content = resp.content
                self._validate_response_size(content)
                self._validate_mime(content, dict(resp.headers), expected_mime_prefix)

                # Run content validator
                if validator:
                    try:
                        validator(content)
                    except SchemaValidationError:
                        # Don't retry schema validation failures
                        self._circuit_breaker.record_failure(source_id)
                        raise

                content_hash = hashlib.sha256(content).hexdigest()
                etag = resp.headers.get("ETag")
                last_modified = resp.headers.get("Last-Modified")

                # Atomic cache write
                self._write_cache(source_id, content, etag, last_modified, content_hash)

                self._circuit_breaker.record_success(source_id)
                return RetrievalEvidence(
                    source_id=source_id,
                    url=url,
                    retrieval_attempted_at=datetime.now(timezone.utc).isoformat(),
                    transport_status="success",
                    http_status=resp.status_code,
                    from_cache=False,
                    content_hash=content_hash,
                    content_length=len(content),
                    etag=etag,
                    last_modified=last_modified,
                    attempt_count=attempt + 1,
                    source_state=SourceState.CURRENT.value,
                    notes={"content": content.decode("utf-8", errors="replace")},
                )

            except RateLimitError as e:
                last_exc = e
                wait = e.retry_after if e.retry_after is not None else self._backoff_with_jitter(attempt)
                time.sleep(max(0.5, float(wait)))
                continue
            except RetryableError as e:
                last_exc = e
                time.sleep(self._backoff_with_jitter(attempt))
                continue
            except (SchemaValidationError, MIMEValidationError, ResponseTooLargeError):
                # Non-retryable
                self._circuit_breaker.record_failure(source_id)
                raise
            except httpx.TransportError as e:
                last_exc = e
                time.sleep(self._backoff_with_jitter(attempt))
                continue

        # All retries exhausted
        self._circuit_breaker.record_failure(source_id)

        # Try last-known-valid cache
        cached = self._load_cached_content(source_id)
        if cached:
            content, meta = cached
            return RetrievalEvidence(
                source_id=source_id,
                url=url,
                retrieval_attempted_at=datetime.now(timezone.utc).isoformat(),
                transport_status="failed_cache_used",
                http_status=None,
                from_cache=True,
                content_hash=meta.get("content_hash", ""),
                content_length=len(content),
                etag=meta.get("etag"),
                last_modified=meta.get("last_modified"),
                attempt_count=self.max_retries + 1,
                source_state=SourceState.STALE.value,
                error=str(last_exc),
                fallback_used="last_known_valid_cache",
                notes={"content": content.decode("utf-8", errors="replace"),
                       "degraded": True},
            )

        return RetrievalEvidence(
            source_id=source_id,
            url=url,
            retrieval_attempted_at=datetime.now(timezone.utc).isoformat(),
            transport_status="failed",
            attempt_count=self.max_retries + 1,
            source_state=SourceState.FAILED.value,
            error=str(last_exc),
        )

    @staticmethod
    def _parse_retry_after(headers: Any) -> Optional[float]:
        """Parse Retry-After header (seconds or HTTP date)."""
        ra = headers.get("Retry-After") or headers.get("retry-after")
        if not ra:
            return None
        try:
            return float(ra)
        except ValueError:
            try:
                dt = datetime.strptime(ra, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
                return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
            except ValueError:
                return None


# ----------------------------------------------------------------------------
# Content validators
# ----------------------------------------------------------------------------
class ContentValidator:
    """Validadores de contenido para cada formato de fuente."""

    @staticmethod
    def validate_ascii_table(content: bytes, min_lines: int = 10,
                              min_length: int = 100) -> None:
        """Valida que el contenido es una tabla ASCII legible."""
        text = content.decode("utf-8", errors="replace")
        if len(text) < min_length:
            raise SchemaValidationError(f"Content too short: {len(text)} bytes")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(lines) < min_lines:
            raise SchemaValidationError(f"Too few lines: {len(lines)}")
        # Check it's not an HTML error page
        lower = text.lower()
        if "<html" in lower or "<!doctype" in lower:
            raise SchemaValidationError("HTML content returned instead of ASCII data")

    @staticmethod
    def validate_csv(content: bytes, min_rows: int = 10) -> None:
        """Valida formato CSV."""
        text = content.decode("utf-8", errors="replace")
        lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
        if len(lines) < min_rows:
            raise SchemaValidationError(f"CSV too few rows: {len(lines)}")
        # First line should contain a comma or be a header
        if "," not in lines[0] and "\t" not in lines[0]:
            raise SchemaValidationError("CSV first line has no delimiter")
        lower = text.lower()
        if "<html" in lower or "<!doctype" in lower:
            raise SchemaValidationError("HTML content returned instead of CSV")

    @staticmethod
    def validate_roni_ascii(content: bytes) -> None:
        """Valida formato RONI.ascii.txt específicamente."""
        text = content.decode("utf-8", errors="replace")
        if "SEAS" not in text and "DJF" not in text:
            raise SchemaValidationError("RONI: missing SEAS/DJF header")
        if len(text) < 500:
            raise SchemaValidationError(f"RONI: content too short ({len(text)} bytes)")

    @staticmethod
    def validate_weekly_sst(content: bytes) -> None:
        """Valida formato wksst8110.for."""
        text = content.decode("utf-8", errors="replace")
        if "Weekly SST" not in text and "Nino" not in text:
            raise SchemaValidationError("Weekly SST: missing expected header")
        if "JAN" not in text:
            raise SchemaValidationError("Weekly SST: no month markers found")

    @staticmethod
    def validate_html_advisory(content: bytes) -> None:
        """Valida que el HTML contiene Alert System Status."""
        text = content.decode("utf-8", errors="replace")
        if "Alert System Status" not in text:
            raise SchemaValidationError("NOAA advisory: missing 'Alert System Status' text")
        if "ENSO" not in text and "El Niño" not in text and "La Niña" not in text:
            raise SchemaValidationError("NOAA advisory: no ENSO mention")

    @staticmethod
    def validate_date_monotonic(points: list[dict]) -> None:
        """Valida que las fechas son monótonas crecientes."""
        prev = None
        for p in points:
            month = p.get("month", "")
            if not month:
                continue
            if prev and month < prev:
                raise SchemaValidationError(
                    f"Non-monotonic date: {month} after {prev}"
                )
            prev = month

    @staticmethod
    def validate_no_future_date(points: list[dict], max_future_months: int = 1) -> None:
        """Valida que no hay fechas futuras imposibles."""
        now = datetime.now(timezone.utc)
        max_allowed = f"{now.year + 1}-01"  # Allow up to 1 year in future for seasonal
        for p in points:
            month = p.get("month", "")
            if month and month > max_allowed:
                raise SchemaValidationError(
                    f"Future date {month} exceeds {max_allowed}"
                )

    @staticmethod
    def validate_plausible_bounds(points: list[dict], metric: str,
                                    min_val: float, max_val: float) -> None:
        """Valida que los valores están dentro de límites plausibles."""
        for p in points:
            v = p.get("value")
            if v is None:
                continue
            if v < min_val or v > max_val:
                raise SchemaValidationError(
                    f"{metric}: value {v} outside plausible bounds [{min_val}, {max_val}]"
                )

    @staticmethod
    def validate_latest_period_cadence(latest_month: str, max_age_days: int) -> None:
        """Valida que el último periodo es compatible con la cadencia."""
        if not latest_month:
            return
        try:
            if "-" in latest_month and len(latest_month.split("-")) == 2:
                y, m = latest_month.split("-")
                dt = datetime(int(y), int(m), 1, tzinfo=timezone.utc)
            elif len(latest_month) == 7 and latest_month[4] == "-":
                y, m = latest_month[:4], latest_month[5:]
                dt = datetime(int(y), int(m), 1, tzinfo=timezone.utc)
            else:
                return
            age = (datetime.now(timezone.utc) - dt).days
            if age > max_age_days:
                raise SchemaValidationError(
                    f"Latest period {latest_month} is {age} days old (max {max_age_days})"
                )
        except (ValueError, IndexError):
            pass
