"""Adquisición unificada de datos ENSO desde fuentes oficiales.

Este módulo reemplaza la lógica fragmentada anterior con un único
orquestador que:

  1. Adquiere datos de todas las fuentes registradas en source_profiles.py
  2. Usa el RONI oficial (RONI.ascii.txt) — NO calcula como rolling mean
  3. Genera health.json desde evidencia real de adquisición
  4. Escribe todos los artefactos a un único directorio de publicación

Fuentes soportadas:
  - Weekly: wksst8110.for (Niño 1+2, 3, 3.4, 4 SST/SSTA)
  - Monthly: PSL Niño 1+2, Niño 3.4, CPC SOI, CPC trade winds (wpac/cpac/epac 850)
  - Seasonal: RONI.ascii.txt (official, NOT computed)
  - Monthly grid: GODAS D20, NCEP u850 (via OPeNDAP)
  - Official: NOAA ENSO Advisory, ENFEN status
"""

from __future__ import annotations

import hashlib
import calendar
import json
import os
import random
import re
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

# Add python/ to path
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "python"))

from enso.source_profiles import SOURCES, SourceProfile, AuthorityLevel


# ----------------------------------------------------------------------------
# Cliente HTTP defensivo
# ----------------------------------------------------------------------------
class HttpClient:
    """Cliente HTTP con reintentos, timeout y rate limiting."""

    def __init__(self, timeout: float = 30.0, max_retries: int = 3,
                 max_response_bytes: int = 10_000_000):
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_response_bytes = max_response_bytes
        self._last_request_ts: dict[str, float] = {}
        self._min_interval = 1.0  # per-host rate limit

    def get(self, url: str, source_id: str = "") -> tuple[str, dict[str, str]]:
        """GET con reintentos. Devuelve (text, headers). Lanza en fallo."""
        if httpx is None:
            raise RuntimeError("httpx no disponible")
        # Per-host rate limit
        host = re.sub(r"https?://([^/]+)/.*", r"\1", url)
        now = time.monotonic()
        elapsed = now - self._last_request_ts.get(host, 0)
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_ts[host] = time.monotonic()

        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                timeout = httpx.Timeout(self.timeout, connect=min(15.0, self.timeout))
                with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                    resp = client.get(
                        url,
                        headers={
                            "User-Agent": "Observatorio-ENSO-Peru/2.0 (pipeline; +https://github.com/PillB/observatorio-enso-peru)",
                            "Accept": "text/plain, text/html, */*",
                        },
                    )
                    resp.raise_for_status()
                    original_host = (urlparse(url).hostname or "").lower()
                    final_host = (urlparse(str(resp.url)).hostname or "").lower()
                    if final_host != original_host:
                        raise RuntimeError(
                            f"{source_id}: redirección fuera del dominio permitido: {final_host}"
                        )
                    body_size = len(resp.content)
                    if body_size > self.max_response_bytes:
                        raise RuntimeError(
                            f"{source_id}: respuesta excede {self.max_response_bytes} bytes"
                        )
                    content_type = resp.headers.get("content-type", "").lower()
                    profile = SOURCES.get(source_id)
                    if profile and profile.format == "wordpress_rest_json" and "json" not in content_type:
                        raise RuntimeError(f"{source_id}: MIME inesperado {content_type}")
                    if profile and profile.format.startswith("ascii") and "html" in content_type:
                        raise RuntimeError(f"{source_id}: página HTML sustituyó el producto ASCII")
                    return resp.text, dict(resp.headers)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    # Rate limited — honor Retry-After
                    retry_after = e.response.headers.get("Retry-After", "5")
                    try:
                        wait = float(retry_after)
                    except ValueError:
                        wait = 5.0
                    time.sleep(min(60.0, max(0.5, wait)))
                    last_exc = e
                    continue
                if e.response.status_code >= 500:
                    # Server error — retry
                    last_exc = e
                    time.sleep(min(30.0, 2 ** attempt + random.uniform(0, 1)))
                    continue
                # Client error — don't retry
                raise
            except (httpx.TimeoutException, httpx.ConnectionError) as e:
                last_exc = e
                time.sleep(min(30.0, 2 ** attempt + random.uniform(0, 1)))
                continue
        raise RuntimeError(
            f"{source_id or url}: fallo tras {self.max_retries} reintentos: {last_exc}"
        )

    def get_bytes(
        self, url: str, source_id: str, *, expected_mime: str,
        allowed_hosts: set[str], max_bytes: Optional[int] = None,
    ) -> tuple[bytes, dict[str, str]]:
        """GET binario acotado para activos documentales no confiables."""
        if httpx is None:
            raise RuntimeError("httpx no disponible")
        limit = max_bytes or self.max_response_bytes
        host = (urlparse(url).hostname or "").lower()
        now = time.monotonic()
        elapsed = now - self._last_request_ts.get(host, 0)
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_ts[host] = time.monotonic()
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                timeout = httpx.Timeout(self.timeout, connect=min(15.0, self.timeout))
                with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                    with client.stream(
                        "GET", url,
                        headers={
                            "User-Agent": "Observatorio-ENSO-Peru/3.1 (document-pipeline; +https://github.com/PillB/observatorio-enso-peru)",
                            "Accept": expected_mime,
                        },
                    ) as resp:
                        if resp.status_code == 429:
                            retry_after = resp.headers.get("Retry-After", "5")
                            try:
                                wait = float(retry_after)
                            except ValueError:
                                wait = 5.0
                            last_exc = RuntimeError("HTTP 429")
                            time.sleep(min(60.0, max(0.5, wait)))
                            continue
                        if resp.status_code >= 500:
                            last_exc = RuntimeError(f"HTTP {resp.status_code}")
                            time.sleep(min(30.0, 2 ** attempt + random.uniform(0, 1)))
                            continue
                        if resp.status_code >= 400:
                            raise RuntimeError(f"HTTP {resp.status_code} non-retryable")
                        final_host = (urlparse(str(resp.url)).hostname or "").lower()
                        if final_host not in allowed_hosts:
                            raise RuntimeError(f"redirect to disallowed host: {final_host}")
                        content_type = resp.headers.get("content-type", "").lower()
                        if expected_mime not in content_type and "octet-stream" not in content_type:
                            raise RuntimeError(f"unexpected MIME: {content_type}")
                        body = bytearray()
                        for chunk in resp.iter_bytes():
                            body.extend(chunk)
                            if len(body) > limit:
                                raise RuntimeError(f"response exceeds {limit} bytes")
                        return bytes(body), dict(resp.headers)
            except (httpx.TimeoutException, httpx.ConnectionError) as exc:
                last_exc = exc
                time.sleep(min(30.0, 2 ** attempt + random.uniform(0, 1)))
                continue
        raise RuntimeError(
            f"{source_id}: binary retrieval failed after bounded retries: {last_exc}"
        )


# ----------------------------------------------------------------------------
# Parsers
# ----------------------------------------------------------------------------
def parse_roni_ascii(text: str) -> list[dict]:
    """Parsea RONI.ascii.txt (formato seasonal: DJF, JFM, ...).

    NO calcula RONI como rolling mean — usa el producto oficial directamente.
    Formato:
        SEAS   YR  ANOM
        DJF  1950 -1.19
        JFM  1950 -1.08
    """
    points = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("SEAS") or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        seas, yr_str, anom_str = parts[0], parts[1], parts[2]
        try:
            yr = int(yr_str)
            anom = float(anom_str)
            if anom <= -99.0:
                anom = None
        except ValueError:
            continue
        # Map season to center month: DJF→01, JFM→02, FMA→03, ..., NDJ→12
        season_to_month = {
            "DJF": "01", "JFM": "02", "FMA": "03", "MAM": "04",
            "AMJ": "05", "MJJ": "06", "JJA": "07", "JAS": "08",
            "ASO": "09", "SON": "10", "OND": "11", "NDJ": "12",
        }
        month_str = season_to_month.get(seas, "01")
        month = f"{yr:04d}-{month_str}"
        # Mark latest 1-2 seasons as preliminary
        now = datetime.now(timezone.utc)
        flag = "preliminary" if yr >= now.year - 1 and yr >= now.year else "final"
        points.append({"month": month, "value": anom, "flag": flag, "season": seas})
    return points


def parse_weekly_sst(text: str) -> list[dict]:
    """Parsea wksst8110.for (weekly Niño region SST/SSTA).

    Formato:
        Weekly SST data starts week centered on 3Jan1990
                        Nino1+2      Nino3        Nino34        Nino4
         Week          SST SSTA     SST SSTA     SST SSTA     SST SSTA
         03JAN1990     23.4-0.4     25.1-0.3     26.6-0.0     28.6 0.3
    """
    points = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("Weekly") or line.startswith("Week") or "Nino" in line:
            continue
        # Parse: DDMMMYYYY followed by 4 pairs of SST SSTA
        m = re.match(r"(\d{2})([A-Z]{3})(\d{4})\s+(.+)", line)
        if not m:
            continue
        day, mon, yr = m.group(1), m.group(2), m.group(3)
        data_str = m.group(4)
        # Split into 4 regions, each with SST and SSTA
        # Values can be like "23.4-0.4" or "28.6 0.3"
        # Split by looking for the pattern
        nums = re.findall(r"[-+]?\d+\.?\d*", data_str)
        if len(nums) < 8:
            continue
        try:
            n12_sst, n12_ssta = float(nums[0]), float(nums[1])
            n3_sst, n3_ssta = float(nums[2]), float(nums[3])
            n34_sst, n34_ssta = float(nums[4]), float(nums[5])
            n4_sst, n4_ssta = float(nums[6]), float(nums[7])
        except (ValueError, IndexError):
            continue
        month_map = {
            "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
            "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
            "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
        }
        month_num = month_map.get(mon, "01")
        week_id = f"{yr}-{month_num}-{day}"
        # Niño 1+2 weekly anomaly
        if n12_ssta > -90:
            points.append({"month": week_id, "value": round(n12_ssta, 2), "flag": "final",
                          "region": "nino12", "type": "weekly"})
        # Niño 3.4 weekly anomaly
        if n34_ssta > -90:
            points.append({"month": week_id, "value": round(n34_ssta, 2), "flag": "final",
                          "region": "nino34", "type": "weekly"})
    return points


def parse_monthly_ascii(text: str, fill_value: float = -999.0,
                        section_marker: Optional[str] = None) -> list[dict]:
    """Parsea formato mensual CPC: YEAR + 12 valores mensuales.

    Usado para SOI, wpac850, cpac850, epac850.
    """
    if section_marker:
        marker_index = text.upper().find(section_marker.upper())
        if marker_index < 0:
            raise ValueError(f"required section not found: {section_marker}")
        text = text[marker_index:]
    points = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("YEAR") or not line[0].isdigit():
            continue
        year_match = re.match(r"^(\d{4})\s*(.*)$", line)
        if not year_match:
            continue
        year = int(year_match.group(1))
        # CPC usa ancho fijo y puede concatenar negativos, por ejemplo
        # ``-2.4-999.9``. ``split()`` pierde entonces todo el año. Extraer
        # los 12 campos numéricos conserva tanto valores reales como fill.
        values = re.findall(
            r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", year_match.group(2)
        )
        if len(values) < 12:
            continue
        for m_idx in range(12):
            try:
                val = float(values[m_idx])
                if val <= fill_value or abs(val) > 1e6:
                    val = None
            except (ValueError, IndexError):
                val = None
            month = f"{year:04d}-{m_idx + 1:02d}"
            now = datetime.now(timezone.utc)
            flag = "preliminary" if year == now.year and m_idx + 1 >= now.month - 1 else "final"
            points.append({"month": month, "value": val, "flag": flag})
    return points


# ----------------------------------------------------------------------------
# Orquestador de adquisición
# ----------------------------------------------------------------------------
class AcquisitionOrchestrator:
    """Orquesta la adquisición de todas las fuentes registradas."""

    def __init__(self, publication_dir: Path, staging_dir: Path):
        self.publication_dir = publication_dir
        self.staging_dir = staging_dir
        if self.staging_dir.exists():
            shutil.rmtree(self.staging_dir)
        if self.publication_dir.exists():
            shutil.copytree(self.publication_dir, self.staging_dir)
        else:
            self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.client = HttpClient(timeout=60.0, max_retries=3)
        self.retrieval_ledger: list[dict] = []
        self.sources_status: dict[str, dict] = {}
        self.publication_id = ""

    def _record(self, source_id: str, success: bool, evidence: str,
                content_hash: str = "", points: int = 0, **extra):
        """Registra evidencia de adquisición."""
        now = datetime.now(timezone.utc).isoformat()
        entry = {
            "source_id": source_id,
            "success": success,
            "evidence": evidence,
            "content_hash": content_hash,
            "points": points,
            "retrieved_at": now,
            **extra,
        }
        self.retrieval_ledger.append(entry)
        self.sources_status[source_id] = {
            "id": source_id,
            "institution": SOURCES[source_id].institution if source_id in SOURCES else "",
            "product": SOURCES[source_id].product if source_id in SOURCES else "",
            "success": success,
            "evidence": evidence,
            "hash": content_hash,
            "retrieved_at": now,
            "points": points,
            **extra,
        }

    @staticmethod
    def _latest_valid_period(points: list[dict]) -> str:
        for point in reversed(points):
            if point.get("value") is not None:
                return str(point.get("month", ""))
        return ""

    @staticmethod
    def _freshness_state(valid_period: str, profile: Optional[SourceProfile],
                         success: bool) -> str:
        if not success:
            return "FAILED"
        if not valid_period or profile is None:
            return "UNKNOWN"
        try:
            parts = valid_period[:10].split("-")
            year, month = int(parts[0]), int(parts[1])
            day = int(parts[2]) if len(parts) > 2 else calendar.monthrange(year, month)[1]
            valid_end = datetime(year, month, day, tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - valid_end).total_seconds() / 86400
            stale_days = int(re.search(r"\d+", profile.stale_after).group())
            slo_days = int(re.search(r"\d+", profile.freshness_slo).group())
            if age_days > stale_days:
                return "STALE"
            if age_days > slo_days:
                return "DELAYED"
            return "PRELIMINARY" if "prelim" in profile.preliminary_policy.lower() else "CURRENT"
        except (AttributeError, IndexError, TypeError, ValueError):
            return "UNKNOWN"

    def _load_existing_csv(self, name: str) -> list[dict]:
        """Carga el último artefacto válido para una corrida parcial."""
        path = self.publication_dir / f"{name}.csv"
        if not path.exists():
            return []
        points = []
        for line in path.read_text().splitlines():
            if not line or line.startswith("#") or line.startswith("month,"):
                continue
            parts = line.split(",")
            if len(parts) < 2:
                continue
            try:
                value = float(parts[1]) if parts[1].strip() else None
            except ValueError:
                value = None
            points.append({
                "month": parts[0], "value": value,
                "flag": parts[2] if len(parts) > 2 else "",
            })
        return points

    def _load_existing_weekly(self) -> list[dict]:
        path = self.publication_dir / "weekly-sst.json"
        if not path.exists():
            return []

    def _load_existing_rapid(self) -> list[dict]:
        path = self.publication_dir / "rapid-observations.json"
        if not path.exists():
            return []

    def _load_existing_bulletins(self) -> list[dict]:
        path = self.publication_dir / "coastal-bulletins.json"
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text())
            return payload.get("bulletins", []) if isinstance(payload, dict) else []
        except (json.JSONDecodeError, OSError):
            return []

    def acquire_siofen_bulletin(self, source_id: str) -> list[dict]:
        """Descubre y extrae el último BDO/BS-TLP de forma fail-closed."""
        from enso.document_sources import (
            DocumentQuarantined, extract_pdf_pages,
            parse_imarpe_bulletin_pages, parse_siofen_bulletin_index,
            validate_pdf_payload,
        )
        bulletin_type = "BDO" if source_id.endswith("bdo") else "BS-TLP"
        profile = SOURCES[source_id]
        try:
            index_html, _ = self.client.get(profile.access_url, source_id)
            assets = parse_siofen_bulletin_index(index_html, bulletin_type=bulletin_type)
            if not assets:
                raise DocumentQuarantined("official index exposed no validated PDF assets")
            asset = assets[0]
            content, headers = self.client.get_bytes(
                asset["url"], source_id,
                expected_mime="application/pdf",
                allowed_hosts={"siofen-admin.imarpe.gob.pe"},
                max_bytes=25 * 1024 * 1024,
            )
            validation = validate_pdf_payload(content, headers.get("content-type", ""))
            pages = extract_pdf_pages(content)
            parsed = parse_imarpe_bulletin_pages(
                pages, bulletin_type=bulletin_type, source_url=asset["url"]
            )
            parsed["sourceId"] = source_id
            parsed["contentHash"] = "sha256:" + validation["sha256"]
            parsed["pageCount"] = len(pages)
            self._record(
                source_id, True,
                f"official index + PDF native text, {len(pages)} pages, sha256:{validation['sha256'][:16]}",
                validation["sha256"][:16], 1,
                valid_period_end=parsed["valid_period"],
                source_published_at=asset.get("publication_date", ""),
                document_url=asset["url"],
            )
            return [parsed]
        except DocumentQuarantined as exc:
            self._record(source_id, False, str(exc), quarantined=True)
        except Exception as exc:
            self._record(source_id, False, str(exc))
        return []

    def _load_existing_official_documents(self) -> list[dict]:
        path = self.publication_dir / "official-documents.json"
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text())
            return payload.get("documents", []) if isinstance(payload, dict) else []
        except (json.JSONDecodeError, OSError):
            return []

    def acquire_enfen_documents(self, enfen_status: Optional[dict]) -> tuple[list[dict], list[dict]]:
        """Valida el adjunto ENFEN y extrae ICEN solo con evidencia explícita."""
        source_id = "enfen-imarpe-document-assets"
        from enso.document_sources import (
            DocumentQuarantined, extract_pdf_pages,
            parse_official_enfen_pages, validate_pdf_payload,
        )
        urls = (enfen_status or {}).get("document_urls", [])
        if not urls:
            self._record(source_id, False, "official WordPress post exposed no validated document URL")
            return [], []
        # Un solo activo por ejecución mantiene el presupuesto y evita una
        # cascada de descargas. Los demás quedan registrados en el descubrimiento.
        url = urls[0]
        try:
            content, headers = self.client.get_bytes(
                url, source_id, expected_mime="application/pdf",
                allowed_hosts={"enfen.imarpe.gob.pe"},
                max_bytes=25 * 1024 * 1024,
            )
            validation = validate_pdf_payload(content, headers.get("content-type", ""))
            pages = extract_pdf_pages(content)
            parsed = parse_official_enfen_pages(pages, source_url=url)
            parsed.update({
                "sourceId": source_id,
                "publicationDate": (enfen_status or {}).get("publication_date", ""),
                "contentHash": "sha256:" + validation["sha256"],
                "pageCount": len(pages),
            })
            icen = []
            if parsed.get("icen") is not None and parsed.get("icen_period"):
                icen = [{
                    "month": parsed["icen_period"], "value": parsed["icen"],
                    "flag": "final", "sourceId": source_id,
                    "evidence": parsed["evidence"]["icen"],
                }]
            self._record(
                source_id, True,
                f"PDF native text validated, {len(pages)} pages, sha256:{validation['sha256'][:16]}",
                validation["sha256"][:16], 1,
                valid_period_end=parsed.get("icen_period") or (enfen_status or {}).get("publication_date", ""),
                source_published_at=(enfen_status or {}).get("publication_date", ""),
                document_url=url,
                icen_extracted=bool(icen),
            )
            return [parsed], icen
        except DocumentQuarantined as exc:
            self._record(source_id, False, str(exc), quarantined=True, document_url=url)
        except Exception as exc:
            self._record(source_id, False, str(exc), document_url=url)
        return [], []
        try:
            payload = json.loads(path.read_text())
            return payload.get("observations", []) if isinstance(payload, dict) else []
        except (json.JSONDecodeError, OSError):
            return []

    def acquire_oisst_daily(self, source_id: str) -> list[dict]:
        """Adquiere medias regionales OISST diarias mediante subconsultas.

        El producto rápido permanece separado de los índices mensuales y de
        los estados oficiales. Nunca se usa para fabricar ICEN o RONI.
        """
        from enso.rapid_sources import build_oisst_griddap_url, parse_erddap_grid_csv

        dataset = {
            "noaa-ncei-oisst-daily-preliminary":
                "ncdc_oisst_v2_avhrr_prelim_by_time_zlev_lat_lon",
            "noaa-ncei-oisst-daily-final":
                "ncdc_oisst_v2_avhrr_by_time_zlev_lat_lon",
        }[source_id]
        regions = {
            "nino12_daily_observation": (-10.0, 0.0, 270.0, 280.0),
            "nino34_daily_observation": (-5.0, 5.0, 190.0, 240.0),
        }
        observations = []
        failures = []
        hashes = []
        published = ""
        for metric_id, (lat_min, lat_max, lon_min, lon_max) in regions.items():
            url = build_oisst_griddap_url(
                dataset, "anom", lat_min, lat_max, lon_min, lon_max
            )
            try:
                text, headers = self.client.get(url, source_id)
                parsed = parse_erddap_grid_csv(text, "anom", "Celsius")
                digest = hashlib.sha256(text.encode()).hexdigest()
                hashes.append(digest)
                published = headers.get("last-modified", published)
                observations.append({
                    "metricId": metric_id,
                    "month": parsed["valid_period"],
                    "value": parsed["value"],
                    "flag": "preliminary" if "preliminary" in source_id else "final",
                    "sourceId": source_id,
                    "sourceUrl": url,
                    "units": "degC",
                    "climatology": "1971-2000",
                    "pointCount": parsed["point_count"],
                    "weighting": parsed["weighting"],
                    "schemaFingerprint": parsed["schema_fingerprint"],
                    "contentHash": f"sha256:{digest}",
                })
            except Exception as exc:
                failures.append(f"{metric_id}: {exc}")
        if observations:
            combined = hashlib.sha256("".join(sorted(hashes)).encode()).hexdigest()[:16]
            self._record(
                source_id, not failures,
                f"ERDDAP regional subsets, {len(observations)}/2 valid, sha256:{combined}"
                + (f"; quarantined: {'; '.join(failures)}" if failures else ""),
                combined, len(observations),
                valid_period_end=max(item["month"] for item in observations),
                source_published_at=published,
                partial_failure=bool(failures),
            )
        else:
            self._record(source_id, False, "; ".join(failures) or "No valid OISST subset")
        return observations

    def acquire_pmel_daily(self, source_id: str) -> list[dict]:
        """Adquiere contexto diario TAO/TRITON con cobertura explícita."""
        from enso.rapid_sources import build_pmel_tabledap_url, parse_pmel_table_csv
        start_date = (datetime.now(timezone.utc) - timedelta(days=120)).date().isoformat()
        if source_id == "pmel-tao-daily-d20":
            dataset = "pmelTaoDyIso"
            columns = ["station", "longitude", "latitude", "time", "ISO_6", "QI_5006"]
            value_column, quality_column, units = "ISO_6", "QI_5006", "m"
            metric_id = "tao_d20_station_context"
        else:
            dataset = "pmelTaoDyW"
            columns = ["station", "longitude", "latitude", "time", "WU_422", "QWS_5401"]
            value_column, quality_column, units = "WU_422", "QWS_5401", "m s-1"
            metric_id = "tao_surface_zonal_wind_context"
        url = build_pmel_tabledap_url(
            dataset=dataset, columns=columns, start_date=start_date
        )
        try:
            text, headers = self.client.get(url, source_id)
            parsed = parse_pmel_table_csv(
                text, value_column=value_column, expected_units=units,
                quality_column=quality_column, accepted_quality={1, 2},
            )
            digest = hashlib.sha256(text.encode()).hexdigest()
            observation = {
                "metricId": metric_id,
                "month": parsed["valid_period"],
                "value": parsed["value"],
                "flag": "preliminary",
                "sourceId": source_id,
                "sourceUrl": url,
                "units": units,
                "stationCount": parsed["station_count"],
                "stations": parsed["stations"],
                "qualityFilter": parsed["quality_filter"],
                "recommendedRole": "CORROBORATION_ONLY",
                "schemaFingerprint": parsed["schema_fingerprint"],
                "contentHash": f"sha256:{digest}",
            }
            self._record(
                source_id, True,
                f"PMEL ERDDAP, {parsed['station_count']} stations, sha256:{digest[:16]}",
                digest[:16], parsed["station_count"],
                valid_period_end=parsed["valid_period"],
                source_published_at=headers.get("last-modified", ""),
                recommended_role="CORROBORATION_ONLY",
            )
            return [observation]
        except Exception as exc:
            self._record(source_id, False, str(exc))
            return []
        try:
            payload = json.loads(path.read_text())
            return payload.get("points", []) if isinstance(payload, dict) else []
        except (json.JSONDecodeError, OSError):
            return []

    def acquire_roni(self) -> list[dict]:
        """Adquiere RONI oficial (NO calculado como rolling mean)."""
        source_id = "noaa-cpc-roni"
        profile = SOURCES[source_id]
        try:
            text, headers = self.client.get(profile.access_url, source_id)
            points = parse_roni_ascii(text)
            h = hashlib.sha256(text.encode()).hexdigest()[:16]
            self._record(source_id, True, f"HTTP 200, {len(points)} seasons, sha256:{h}", h, len(points),
                         valid_period_end=self._latest_valid_period(points),
                         source_published_at=headers.get("last-modified", ""))
            return points
        except Exception as e:
            self._record(source_id, False, str(e))
            return []

    def acquire_weekly_sst(self) -> list[dict]:
        """Adquiere weekly Niño region SST/SSTA."""
        source_id = "noaa-cpc-wksst"
        profile = SOURCES[source_id]
        try:
            text, headers = self.client.get(profile.access_url, source_id)
            points = parse_weekly_sst(text)
            h = hashlib.sha256(text.encode()).hexdigest()[:16]
            self._record(source_id, True, f"HTTP 200, {len(points)} weekly points, sha256:{h}", h, len(points),
                         valid_period_end=self._latest_valid_period(points),
                         source_published_at=headers.get("last-modified", ""))
            return points
        except Exception as e:
            self._record(source_id, False, str(e))
            return []

    def acquire_psl_csv(self, source_id: str) -> list[dict]:
        """Adquiere CSV de PSL (Niño 1+2, Niño 3.4)."""
        profile = SOURCES[source_id]
        try:
            text, headers = self.client.get(profile.access_url, source_id)
            # PSL CSV: Date,Value format
            points = []
            for line in text.strip().split("\n"):
                if line.startswith("Date") or line.startswith("#") or not line.strip():
                    continue
                parts = line.split(",")
                if len(parts) < 2:
                    continue
                try:
                    y, m, d = parts[0].strip().split("-")
                    month = f"{y}-{int(m):02d}"
                    val = float(parts[1].strip())
                    if val <= -99.0:
                        val = None
                    points.append({"month": month, "value": val, "flag": "final"})
                except (ValueError, IndexError):
                    continue
            h = hashlib.sha256(text.encode()).hexdigest()[:16]
            self._record(source_id, True, f"HTTP 200, {len(points)} points, sha256:{h}", h, len(points),
                         valid_period_end=self._latest_valid_period(points),
                         source_published_at=headers.get("last-modified", ""))
            return points
        except Exception as e:
            self._record(source_id, False, str(e))
            return []

    def acquire_monthly_cpc(self, source_id: str) -> list[dict]:
        """Adquiere índice mensual CPC (SOI, wpac850, cpac850, epac850)."""
        profile = SOURCES[source_id]
        try:
            text, headers = self.client.get(profile.access_url, source_id)
            points = parse_monthly_ascii(
                text,
                section_marker="STANDARDIZED" if source_id == "noaa-cpc-soi" else None,
            )
            h = hashlib.sha256(text.encode()).hexdigest()[:16]
            self._record(source_id, True, f"HTTP 200, {len(points)} points, sha256:{h}", h, len(points),
                         valid_period_end=self._latest_valid_period(points),
                         source_published_at=headers.get("last-modified", ""))
            return points
        except Exception as e:
            self._record(source_id, False, str(e))
            return []

    def acquire_official_status(self) -> tuple[Optional[dict], Optional[dict]]:
        """Adquiere estados oficiales NOAA y ENFEN."""
        # NOAA ENSO Advisory
        noaa_advisory = None
        try:
            from enso.official_status import fetch_noaa_enso_advisory
            noaa_advisory = fetch_noaa_enso_advisory()
            h = hashlib.sha256(noaa_advisory["alert"].encode()).hexdigest()[:16]
            self._record("noaa-cpc-enso-advisory", True,
                        f"HTML parse, alert={noaa_advisory['alert']}, date={noaa_advisory['date']}",
                        h, 1, valid_period_end=noaa_advisory.get("date", ""))
        except Exception as e:
            self._record("noaa-cpc-enso-advisory", False, str(e))

        # ENFEN status
        enfen_status = None
        try:
            from enso.official_status import fetch_enfen_status
            enfen_status = fetch_enfen_status()
            h = hashlib.sha256(enfen_status["alert"].encode()).hexdigest()[:16]
            self._record("enfen-imarpe-status", True,
                        f"source={enfen_status['source']}, alert={enfen_status['alert']}",
                        h, 1, valid_period_end=enfen_status.get("month", ""))
        except Exception as e:
            self._record("enfen-imarpe-status", False, str(e))

        return noaa_advisory, enfen_status

    def acquire_d20(self) -> list[dict]:
        """Adquiere D20 GODAS sin disparar otra descarga de viento."""
        d20 = []
        try:
            from enso.opendap_fetchers import GodasD20Fetcher
            f = GodasD20Fetcher()
            raw = f.fetch_all()
            from enso.opendap_fetchers import compute_monthly_anomaly
            anom = compute_monthly_anomaly(raw)
            d20 = [{"month": p.month, "value": p.value,
                    "flag": "preliminary" if p.flag.value == "preliminary" else "final"}
                   for p in anom]
            h = hashlib.sha256(str(d20).encode()).hexdigest()[:16]
            self._record("noaa-cpc-godas-d20", True,
                        f"OPeNDAP, {len(d20)} points, sha256:{h}", h, len(d20),
                        valid_period_end=self._latest_valid_period(d20))
        except Exception as e:
            self._record("noaa-cpc-godas-d20", False, str(e))
        return d20

    def acquire_d20_u850(self) -> tuple[list[dict], list[dict]]:
        """Compatibilidad: adquiere D20 y el índice CPC cpac850."""
        d20 = self.acquire_d20()
        u850 = []

        # u850 — use CPC trade wind indices (official, structured) instead of OPeNDAP grid
        # The CPC epac850 (Eastern Pacific) is closest to Niño 1+2/coastal influence
        # The CPC cpac850 (Central Pacific) is closest to Niño 3.4
        # We use cpac850 as the primary u850 metric
        try:
            cpac = self.acquire_monthly_cpc("noaa-cpc-cpac850")
            if cpac:
                u850 = cpac
        except Exception as e:
            self._record("noaa-cpc-cpac850", False, str(e))

        return d20, u850

    def run_all(self, source_id: Optional[str] = None, force_refresh: bool = False) -> dict[str, Any]:
        """Ejecuta la adquisición completa y devuelve un resumen."""
        print("=== Adquisición unificada de datos ENSO ===")

        if source_id and source_id not in SOURCES:
            raise ValueError(f"Fuente desconocida: {source_id}")

        def selected(sid: str) -> bool:
            return source_id is None or source_id == sid

        def prior(name: str) -> list[dict]:
            return self._load_existing_csv(name)

        # Rapid observational layer
        weekly_sst = (self.acquire_weekly_sst() if selected("noaa-cpc-wksst")
                      else self._load_existing_weekly())
        prior_rapid = self._load_existing_rapid()
        if source_id is None:
            oisst_final = self.acquire_oisst_daily("noaa-ncei-oisst-daily-final")
            oisst_prelim = self.acquire_oisst_daily("noaa-ncei-oisst-daily-preliminary")
            pmel_d20 = self.acquire_pmel_daily("pmel-tao-daily-d20")
            pmel_wind = self.acquire_pmel_daily("pmel-tao-daily-wind")
            rapid_observations = oisst_final + oisst_prelim + pmel_d20 + pmel_wind
        elif source_id in {
            "noaa-ncei-oisst-daily-final", "noaa-ncei-oisst-daily-preliminary"
        }:
            replacement = self.acquire_oisst_daily(source_id)
            rapid_observations = [
                item for item in prior_rapid if item.get("sourceId") != source_id
            ] + replacement
        elif source_id in {"pmel-tao-daily-d20", "pmel-tao-daily-wind"}:
            replacement = self.acquire_pmel_daily(source_id)
            rapid_observations = [
                item for item in prior_rapid if item.get("sourceId") != source_id
            ] + (replacement or [
                item for item in prior_rapid if item.get("sourceId") == source_id
            ])
        else:
            rapid_observations = prior_rapid

        prior_bulletins = self._load_existing_bulletins()
        bulletin_source_ids = ("imarpe-siofen-bdo", "imarpe-siofen-bs-tlp")
        if source_id is None:
            coastal_bulletins = []
            for bulletin_source_id in bulletin_source_ids:
                acquired = self.acquire_siofen_bulletin(bulletin_source_id)
                if acquired:
                    coastal_bulletins.extend(acquired)
                else:
                    # Conservar únicamente como historial fechado; la UX de
                    # actualidad se decide con el SLO de cada fuente.
                    coastal_bulletins.extend([
                        item for item in prior_bulletins
                        if item.get("sourceId") == bulletin_source_id
                    ])
        elif source_id in bulletin_source_ids:
            acquired = self.acquire_siofen_bulletin(source_id)
            coastal_bulletins = [
                item for item in prior_bulletins if item.get("sourceId") != source_id
            ] + (acquired or [
                item for item in prior_bulletins if item.get("sourceId") == source_id
            ])
        else:
            coastal_bulletins = prior_bulletins

        # Operational index layer
        n12 = (self.acquire_psl_csv("noaa-psl-nino12") if selected("noaa-psl-nino12")
               else prior("nino12"))
        n34 = (self.acquire_psl_csv("noaa-psl-nino34") if selected("noaa-psl-nino34")
               else prior("nino34"))
        roni = self.acquire_roni() if selected("noaa-cpc-roni") else prior("roni")
        soi = (self.acquire_monthly_cpc("noaa-cpc-soi") if selected("noaa-cpc-soi")
               else prior("soi"))
        wpac850 = (self.acquire_monthly_cpc("noaa-cpc-wpac850") if selected("noaa-cpc-wpac850")
                   else prior("wpac850"))
        cpac850 = (self.acquire_monthly_cpc("noaa-cpc-cpac850") if selected("noaa-cpc-cpac850")
                   else prior("cpac850"))
        epac850 = (self.acquire_monthly_cpc("noaa-cpc-epac850") if selected("noaa-cpc-epac850")
                   else prior("epac850"))
        d20 = self.acquire_d20() if selected("noaa-cpc-godas-d20") else prior("d20")

        # Official authority layer
        if source_id is None or source_id in {
            "noaa-cpc-enso-advisory", "enfen-imarpe-status",
            "enfen-imarpe-document-assets",
        }:
            noaa_advisory, enfen_status = self.acquire_official_status()
        else:
            existing_status = {}
            status_path = self.publication_dir / "status.json"
            if status_path.exists():
                try:
                    existing_status = json.loads(status_path.read_text())
                except json.JSONDecodeError:
                    existing_status = {}
            coastal = existing_status.get("coastal", {})
            basin = existing_status.get("basin", {})
            noaa_advisory = {
                "alert": basin.get("alert", "Sin datos"),
                "date": basin.get("alertDate", ""),
            }
            enfen_status = {
                "alert": coastal.get("alert", "Sin datos"),
                "month": coastal.get("alertDate", ""),
                "source": coastal.get("alertSourceMethod", "last-known-valid"),
            }

        prior_documents = self._load_existing_official_documents()
        prior_validated_icen = [{
            "month": item.get("icen_period"),
            "value": item.get("icen"),
            "flag": "final",
            "sourceId": "enfen-imarpe-document-assets",
            "evidence": item.get("evidence", {}).get("icen"),
        } for item in prior_documents
            if item.get("sourceId") == "enfen-imarpe-document-assets"
            and item.get("icen") is not None and item.get("icen_period")
            and item.get("evidence", {}).get("icen")]
        if source_id is None or source_id == "enfen-imarpe-document-assets":
            official_documents, icen = self.acquire_enfen_documents(enfen_status)
            if not official_documents:
                official_documents = prior_documents
                icen = prior_validated_icen
        else:
            official_documents, icen = prior_documents, prior_validated_icen

        # Write all artifacts to staging
        self._write_artifacts(
            n12=n12, n34=n34, roni=roni, soi=soi, icen=icen,
            d20=d20, u850=cpac850,
            wpac850=wpac850, cpac850=cpac850, epac850=epac850,
            weekly_sst=weekly_sst,
            rapid_observations=rapid_observations,
            coastal_bulletins=coastal_bulletins,
            official_documents=official_documents,
            noaa_advisory=noaa_advisory, enfen_status=enfen_status,
        )

        # Summary
        summary = {
            "sources": self.sources_status,
            "total_sources": len(self.sources_status),
            "successful": sum(1 for s in self.sources_status.values() if s["success"]),
            "failed": sum(1 for s in self.sources_status.values() if not s["success"]),
            "selected_source": source_id,
            "force_refresh": force_refresh,
        }
        print(f"\n=== Resumen: {summary['successful']}/{summary['total_sources']} fuentes exitosas ===")
        for sid, info in self.sources_status.items():
            status = "✅" if info["success"] else "❌"
            print(f"  {status} {sid}: {info['evidence'][:80]}")
        return summary

    def _write_artifacts(self, **data):
        """Escribe todos los artefactos al directorio de staging."""
        pub = self.staging_dir
        now = datetime.now(timezone.utc).isoformat()
        self.publication_id = hashlib.sha256(now.encode()).hexdigest()[:12]

        # Helper to write CSV
        def write_csv(name: str, points: list[dict], units: str, source: str):
            lines = [
                f"# Observatorio ENSO Perú — {name}",
                f"# Unidades: {units}",
                f"# Fuente: {source}",
                f"# Adquirido: {now}",
                f"# Datos reales observados",
                "month,value,flag",
            ]
            for p in points:
                v = p["value"] if p["value"] is not None else ""
                lines.append(f"{p['month']},{v},{p.get('flag', '')}")
            (pub / f"{name}.csv").write_text("\n".join(lines))

        # Write series CSVs
        if data.get("n12"):
            write_csv("nino12", data["n12"], "degC", "NOAA/PSL")
        if data.get("n34"):
            write_csv("nino34", data["n34"], "degC", "NOAA/PSL")
        if data.get("roni"):
            write_csv("roni", data["roni"], "degC", "NOAA/CPC RONI (official)")
        if data.get("soi"):
            write_csv("soi", data["soi"], "dimensionless", "NOAA/CPC")
        if data.get("icen"):
            write_csv("icen", data["icen"], "degC", "ENFEN/IMARPE (official direct product)")
        else:
            # El staging parte del último snapshot; retirar expresamente una
            # estimación obsoleta impide que sobreviva por copia incremental.
            (pub / "icen.csv").unlink(missing_ok=True)
        if data.get("d20"):
            write_csv("d20", data["d20"], "m", "NOAA/PSL GODAS dbss_obil")
        if data.get("u850"):
            write_csv("u850", data["u850"], "m/s", "NOAA/CPC cpac850 (actual wind)")
        if data.get("wpac850"):
            write_csv("wpac850", data["wpac850"], "m/s", "NOAA/CPC wpac850 (actual wind)")
        if data.get("cpac850"):
            write_csv("cpac850", data["cpac850"], "m/s", "NOAA/CPC cpac850 (actual wind)")
        if data.get("epac850"):
            write_csv("epac850", data["epac850"], "m/s", "NOAA/CPC epac850 (actual wind)")
        if data.get("weekly_sst"):
            # Write weekly SST as JSON
            (pub / "weekly-sst.json").write_text(
                json.dumps({"generatedAt": now, "source": "NOAA/CPC wksst8110.for",
                           "points": data["weekly_sst"]}, indent=2, ensure_ascii=False)
            )
        (pub / "rapid-observations.json").write_text(json.dumps({
            "generatedAt": now,
            "layer": "RAPID_OBSERVATIONAL",
            "scientificBoundary": (
                "No sustituye ICEN, RONI ni los estados oficiales ENFEN/NOAA."
            ),
            "observations": data.get("rapid_observations", []),
        }, indent=2, ensure_ascii=False))
        (pub / "coastal-bulletins.json").write_text(json.dumps({
            "generatedAt": now,
            "layer": "RAPID_OBSERVATIONAL",
            "currentUsePolicy": (
                "Cada boletín conserva su período; un historial vencido no representa la condición actual."
            ),
            "bulletins": data.get("coastal_bulletins", []),
        }, indent=2, ensure_ascii=False))
        (pub / "official-documents.json").write_text(json.dumps({
            "generatedAt": now,
            "extractionPolicy": (
                "Texto nativo → extracción determinista; OCR/LLM no publican valores críticos sin corroboración."
            ),
            "documents": data.get("official_documents", []),
        }, indent=2, ensure_ascii=False))

        # Write status.json
        self._write_status_json(pub, data, now)

        # Write health.json from real evidence
        self._write_health_json(pub, now)

        # Ledger de adquisición de esta publicación. La inmutabilidad entre
        # ejecuciones queda preservada por el artefacto de Actions/Git y por el
        # hash del snapshot estampado en todos los JSON.
        (pub / "acquisition-ledger.json").write_text(json.dumps({
            "generatedAt": now,
            "publicationId": self.publication_id,
            "entries": self.retrieval_ledger,
        }, indent=2, ensure_ascii=False))

        # Gráficos, CSV combinado y artefactos de estado deben consumir la
        # misma adquisición real que las tarjetas.
        self._write_integrated_artifacts(pub, data, now)

        # Write manifest.json
        self._write_manifest_json(pub, now)

        # El navegador rechaza snapshots mezclados: todos los JSON de objeto
        # comparten un único ID de publicación y snapshot de fuentes.
        self._stamp_publication_json(pub)

    def _write_integrated_artifacts(self, pub: Path, data: dict, now: str):
        """Regenera consumidores públicos desde las series adquiridas."""
        specs = {
            "nino12": ("n12", "TSM Niño 1+2", "degC", "coastal", "noaa-psl-nino12"),
            "nino34": ("n34", "TSM Niño 3.4", "degC", "basin", "noaa-psl-nino34"),
            "icen": ("icen", "ICEN", "degC", "coastal", "enfen-imarpe-document-assets"),
            "roni": ("roni", "RONI", "degC", "basin", "noaa-cpc-roni"),
            "soi": ("soi", "SOI", "dimensionless", "basin", "noaa-cpc-soi"),
            "u850": ("u850", "Viento zonal 850 hPa", "m_per_s", "basin", "noaa-cpc-cpac850"),
            "d20": ("d20", "D20", "m", "basin", "noaa-cpc-godas-d20"),
        }
        series: dict[str, dict] = {}
        for sid, (data_key, label, units, scope, source_id) in specs.items():
            points = data.get(data_key, []) or []
            digest = hashlib.sha256(
                json.dumps(points, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()[:16]
            series[sid] = {
                "indicatorId": sid,
                "label": label,
                "units": units,
                "scope": scope,
                "sourceId": source_id,
                "checksum": f"sha256:{digest}",
                "points": points,
            }

        rapid_labels = {
            "nino12_daily_observation": ("TSM diaria Niño 1+2 (OISST)", "coastal"),
            "nino34_daily_observation": ("TSM diaria Niño 3.4 (OISST)", "basin"),
        }
        for metric_id, (label, scope) in rapid_labels.items():
            observations = [
                item for item in data.get("rapid_observations", [])
                if item.get("metricId") == metric_id
            ]
            observations.sort(key=lambda item: (
                str(item.get("month", "")), item.get("flag") == "preliminary"
            ))
            points = [{
                "month": item.get("month"),
                "value": item.get("value"),
                "flag": item.get("flag"),
                "sourceId": item.get("sourceId"),
            } for item in observations]
            digest = hashlib.sha256(
                json.dumps(points, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()[:16]
            series[metric_id] = {
                "indicatorId": metric_id,
                "label": label,
                "units": "degC",
                "scope": scope,
                "layer": "RAPID_OBSERVATIONAL",
                "sourceId": "noaa-ncei-oisst-daily-preliminary",
                "checksum": f"sha256:{digest}",
                "points": points,
            }

        (pub / "all-series.json").write_text(json.dumps({
            "asOf": now.split("T")[0],
            "generatedAt": now,
            "dataVersion": "3.1.0",
            "dataSource": "LIVE_OBSERVED",
            "publicationId": self.publication_id,
            "series": series,
        }, indent=2, ensure_ascii=False))

        # Contenido estrictamente numérico/ISO: no admite fórmulas de hoja de
        # cálculo introducidas por texto remoto.
        periods = sorted({
            p["month"] for item in series.values() for p in item["points"]
            if isinstance(p.get("month"), str)
        })
        lookup = {
            sid: {p["month"]: p.get("value") for p in item["points"]}
            for sid, item in series.items()
        }
        ids = list(specs)
        rows = [",".join(["month", *ids])]
        for period in periods:
            values = [period]
            for sid in ids:
                value = lookup[sid].get(period)
                values.append("" if value is None else str(value))
            rows.append(",".join(values))
        (pub / "observatorio-enso-todas-las-series.csv").write_text(
            "\n".join(rows), encoding="utf-8"
        )

        status = json.loads((pub / "status.json").read_text())
        (pub / "latest.json").write_text(json.dumps({
            "generatedAt": now,
            "asOf": status["asOf"],
            "dataSource": "LIVE_OBSERVED",
            "publicationId": self.publication_id,
            "coastal": status["coastal"],
            "basin": status["basin"],
            "winds": status["winds"],
            "thermocline": status["thermocline"],
            "soi": status["soi"],
        }, indent=2, ensure_ascii=False))

        (pub / "official-status.json").write_text(json.dumps({
            "generatedAt": now,
            "publicationId": self.publication_id,
            "coastal": {
                "authority": "ENFEN / IMARPE",
                "status": status["coastal"]["alert"],
                "publicationPeriod": status["coastal"]["alertDate"],
                "source": status["coastal"]["alertOfficialUrl"],
                "acquisitionMethod": status["coastal"]["alertSourceMethod"],
            },
            "basin": {
                "authority": "NOAA / CPC",
                "status": status["basin"]["alert"],
                "publicationPeriod": status["basin"]["alertDate"],
                "source": status["basin"]["alertOfficialUrl"],
            },
        }, indent=2, ensure_ascii=False))

        from enso.thresholds import (
            evaluate_basin_sst_expert, evaluate_coastal_sst_expert,
            evaluate_soi_expert, evaluate_thermocline_expert,
        )
        signal_inputs = [
            ("Niño 1+2 (costero)", status["coastal"]["nino12Anom"], evaluate_coastal_sst_expert),
            ("ICEN (costero)", status["coastal"]["icen"], evaluate_coastal_sst_expert),
            ("Niño 3.4 (cuenca)", status["basin"]["nino34Anom"], evaluate_basin_sst_expert),
            ("RONI (cuenca)", status["basin"]["roni"], evaluate_basin_sst_expert),
            ("D20 (termoclina)", status["thermocline"]["d20Anom"], evaluate_thermocline_expert),
            ("SOI", status["soi"]["value"], evaluate_soi_expert),
        ]
        signals = []
        for indicator, value, evaluator in signal_inputs:
            result = evaluator(value)
            signals.append({
                "indicator": indicator, "value": value,
                "classification": result.classification,
                "color": result.color.value,
                "isUnclassified": result.is_unclassified,
            })
        (pub / "operational-signals.json").write_text(json.dumps({
            "generatedAt": now,
            "policyId": "expert-grd-image-v1",
            "policyName": "Señal operativa del experto GRD (imagen v1)",
            "disclaimer": "Esta señal no equivale al sistema oficial de alertas de NOAA ni de ENFEN.",
            "signals": signals,
        }, indent=2, ensure_ascii=False))

        quality_sources = []
        for sid, item in series.items():
            last = next((p for p in reversed(item["points"]) if p.get("value") is not None), None)
            profile = SOURCES.get(item["sourceId"])
            freshness = self._freshness_state(
                last.get("month", "") if last else "", profile, bool(last)
            )
            quality_sources.append({
                "indicatorId": sid, "label": item["label"], "scope": item["scope"],
                "lastMonth": last.get("month") if last else None,
                "lastValue": last.get("value") if last else None,
                "units": item["units"], "freshnessState": freshness,
                "source": item["sourceId"],
            })
        bad_states = {"STALE", "FAILED", "QUARANTINED", "UNKNOWN"}
        (pub / "data-quality.json").write_text(json.dumps({
            "generatedAt": now,
            "overallQuality": "DEGRADED" if any(
                q["freshnessState"] in bad_states for q in quality_sources
            ) else "GOOD",
            "staleDataCount": sum(q["freshnessState"] == "STALE" for q in quality_sources),
            "missingDataCount": sum(q["lastValue"] is None for q in quality_sources),
            "sources": quality_sources,
        }, indent=2, ensure_ascii=False))

        unavailable = {
            "status": "UNAVAILABLE",
            "message": "Dato actual no disponible.",
            "reason": (
                "Este producto no cuenta todavía con un adaptador oficial, "
                "validado y conectado a la publicación canónica. Se retiró la "
                "estimación sintética para evitar presentarla como observación actual."
            ),
            "generatedAt": now,
        }
        for filename in ("forecasts.json", "regional-impact.json", "latest-grid.json"):
            (pub / filename).write_text(json.dumps(
                {**unavailable, "product": filename.removesuffix(".json")},
                indent=2, ensure_ascii=False,
            ))

    def _stamp_publication_json(self, pub: Path):
        """Estampa el ID coherente sin alterar contratos JSON de tipo lista."""
        source_snapshot_id = "sha256:" + hashlib.sha256(
            json.dumps(self.retrieval_ledger, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:20]
        git_sha = os.environ.get("GITHUB_SHA", "LOCAL_UNCOMMITTED")
        for path in pub.glob("*.json"):
            try:
                payload = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(payload, dict):
                continue
            payload["publicationId"] = self.publication_id
            payload["sourceSnapshotId"] = source_snapshot_id
            payload["pipelineVersion"] = "3.1.0"
            payload["schemaVersion"] = "3.1.0"
            payload["gitSha"] = git_sha
            payload["thresholdPolicyVersions"] = [
                "expert-grd-image-v1", "enfen-icen-official-v1"
            ]
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    def _write_status_json(self, pub: Path, data: dict, now: str):
        """Escribe status.json con valores reales más recientes."""
        def latest(points, source_id):
            if not points:
                return {"month": "", "value": None, "lastKnownValue": None,
                        "freshnessState": "UNKNOWN"}
            for p in reversed(points):
                if p.get("value") is not None:
                    state = self._freshness_state(
                        str(p.get("month", "")), SOURCES.get(source_id), True
                    )
                    return {
                        **p,
                        "lastKnownValue": p.get("value"),
                        "value": None if state == "STALE" else p.get("value"),
                        "freshnessState": state,
                    }
            return {"month": "", "value": None, "lastKnownValue": None,
                    "freshnessState": "UNKNOWN"}

        ln12 = latest(data.get("n12", []), "noaa-psl-nino12")
        ln34 = latest(data.get("n34", []), "noaa-psl-nino34")
        licen = latest(data.get("icen", []), "enfen-imarpe-document-assets")
        lroni = latest(data.get("roni", []), "noaa-cpc-roni")
        lsoi = latest(data.get("soi", []), "noaa-cpc-soi")
        ld20 = latest(data.get("d20", []), "noaa-cpc-godas-d20")
        lu850 = latest(data.get("u850", []), "noaa-cpc-cpac850")
        noaa = data.get("noaa_advisory")
        enfen = data.get("enfen_status")

        def latest_rapid(metric_id: str) -> dict:
            candidates = [
                item for item in data.get("rapid_observations", [])
                if item.get("metricId") == metric_id and item.get("value") is not None
            ]
            if not candidates:
                return {"value": None, "validPeriod": "", "sourceId": "",
                        "freshnessState": "UNKNOWN", "flag": ""}
            # En el mismo día, final prevalece. Una observación preliminar más
            # reciente sí puede mostrarse, siempre rotulada como tal.
            chosen = max(candidates, key=lambda item: (
                str(item.get("month", "")), item.get("flag") == "final"
            ))
            source_id = str(chosen.get("sourceId", ""))
            state = self._freshness_state(
                str(chosen.get("month", "")), SOURCES.get(source_id), True
            )
            if chosen.get("flag") == "preliminary" and state == "CURRENT":
                state = "PRELIMINARY"
            return {
                "value": None if state == "STALE" else chosen.get("value"),
                "lastKnownValue": chosen.get("value"),
                "validPeriod": chosen.get("month", ""),
                "sourceId": source_id,
                "sourceUrl": chosen.get("sourceUrl", ""),
                "freshnessState": state,
                "flag": chosen.get("flag", ""),
                "pointCount": chosen.get("pointCount", 0),
            }

        rapid_n12 = latest_rapid("nino12_daily_observation")
        rapid_n34 = latest_rapid("nino34_daily_observation")

        status = {
            "asOf": now.split("T")[0],
            "dataVersion": "3.1.0",
            "generatedAt": now,
            "dataSource": "LIVE_OBSERVED",
            "publicationId": self.publication_id,
            "coastal": {
                "alert": enfen["alert"] if enfen else "Consulte ENFEN en siofen.imarpe.gob.pe",
                "alertSource": "ENFEN / IMARPE",
                "alertOfficialUrl": "https://siofen.imarpe.gob.pe/nivel2/indice-costero-el-nino-icen",
                "alertDate": enfen.get("month", "") if enfen else "",
                "alertSourceMethod": enfen.get("source", "unavailable") if enfen else "unavailable",
                "nino12Anom": ln12["value"],
                "nino12Month": ln12["month"],
                "nino12FreshnessState": ln12["freshnessState"],
                "nino12LastKnownValue": ln12["lastKnownValue"],
                "icen": licen["value"],
                "icenWindow": licen["month"],
                "icenFreshnessState": licen["freshnessState"],
                "icenLastKnownValue": licen["lastKnownValue"],
                "icenCategory": self._icen_category(licen["value"]),
                "freshness": f"Dato observado · adquirido {now}",
            },
            "rapidObservations": {
                "scientificBoundary": (
                    "Contexto observacional; no sustituye índices ni estados oficiales."
                ),
                "nino12Daily": rapid_n12,
                "nino34Daily": rapid_n34,
            },
            "basin": {
                "alert": noaa["alert"] if noaa else "Consulte NOAA/CPC en cpc.ncep.noaa.gov",
                "alertSource": "NOAA / CPC",
                "alertOfficialUrl": "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml",
                "alertDate": noaa.get("date", "") if noaa else "",
                "nino34Anom": ln34["value"],
                "nino34Month": ln34["month"],
                "nino34FreshnessState": ln34["freshnessState"],
                "nino34LastKnownValue": ln34["lastKnownValue"],
                "roni": lroni["value"],
                "roniWindow": lroni["month"],
                "roniFreshnessState": lroni["freshnessState"],
                "roniLastKnownValue": lroni["lastKnownValue"],
                "roniCategory": self._roni_category(lroni["value"]),
                "roniSource": "NOAA/CPC RONI.ascii.txt (official, NOT computed)",
                "freshness": f"Dato observado · adquirido {now}",
            },
            "winds": {
                "u850Anom": lu850["value"],
                "u850Month": lu850["month"],
                "freshnessState": lu850["freshnessState"],
                "lastKnownValue": lu850["lastKnownValue"],
                "u850Source": "NOAA/CPC cpac850 (actual wind, Central Pacific 175°W-140°W)",
                "direction": self._u850_direction(lu850["value"]),
                "signMeaning": "Valores positivos = viento hacia el este (westerly); negativos = hacia el oeste (easterly). Nota: CPC trade wind index es viento real (no anomalía).",
            },
            "thermocline": {
                "d20Anom": ld20["value"],
                "d20Month": ld20["month"],
                "freshnessState": ld20["freshnessState"],
                "lastKnownValue": ld20["lastKnownValue"],
                "interpretation": self._d20_interpretation(ld20["value"]),
            },
            "soi": {
                "value": lsoi["value"],
                "month": lsoi["month"],
                "freshnessState": lsoi["freshnessState"],
                "lastKnownValue": lsoi["lastKnownValue"],
                "interpretation": self._soi_category(lsoi["value"]),
                "note": "El SOI es un índice de escala de cuenca (Tahiti-Darwin). El observatorio NO define un «SOI costero».",
            },
        }
        (pub / "status.json").write_text(json.dumps(status, indent=2, ensure_ascii=False))

    def _write_health_json(self, pub: Path, now: str):
        """Escribe health.json desde evidencia REAL de adquisición."""
        health = {
            "generatedAt": now,
            "asOf": now.split("T")[0],
            "pipelineStatus": "UPDATED" if any(s["success"] for s in self.sources_status.values()) else "FAILED",
            "lastSuccessfulRun": now,
            "dataVersion": "3.1.0",
            "dataSource": "LIVE_OBSERVED",
            "publicationId": self.publication_id,
            "sources": [],
        }
        prior_by_id = {}
        prior_path = self.publication_dir / "health.json"
        if prior_path.exists():
            try:
                prior = json.loads(prior_path.read_text())
                prior_by_id = {
                    s.get("id"): s for s in prior.get("sources", []) if s.get("id")
                }
            except (json.JSONDecodeError, OSError):
                prior_by_id = {}
        for sid, info in self.sources_status.items():
            profile = SOURCES.get(sid)
            valid_period = info.get("valid_period_end", "")
            freshness = self._freshness_state(valid_period, profile, info["success"])
            if info.get("quarantined"):
                freshness = "QUARANTINED"
            prior_by_id[sid] = {
                "id": sid,
                "institution": info.get("institution", ""),
                "product": info.get("product", ""),
                "status": "HEALTHY" if info["success"] else (
                    "QUARANTINED" if info.get("quarantined") else "FAILED"
                ),
                "freshnessState": freshness,
                "lastUpdate": valid_period or info.get("retrieved_at", now),
                "retrievedAt": info.get("retrieved_at", now),
                "sourcePublishedAt": info.get("source_published_at", ""),
                "validPeriodEnd": valid_period,
                "retrievalEvidence": info.get("evidence", ""),
                "contentHash": info.get("hash", ""),
                "pointsRetrieved": info.get("points", 0),
                "cadence": profile.temporal_resolution if profile else "",
                "authorityLevel": profile.authority_level.value if profile else "",
                "expectedCadence": profile.expected_cadence if profile else "",
                "expectedReleaseWindow": profile.expected_release_window if profile else "",
                "typicalLatency": profile.typical_lag if profile else "",
                "freshnessSlo": profile.freshness_slo if profile else "",
                "staleThreshold": profile.stale_after if profile else "",
                "revisionWindow": profile.revision_window if profile else "",
                "riskTier": "LOW" if freshness in {"CURRENT", "PRELIMINARY"} else "HIGH",
            }
        health["sources"] = sorted(prior_by_id.values(), key=lambda item: item["id"])
        states = {item.get("freshnessState") for item in health["sources"]}
        if "FAILED" in states or "STALE" in states:
            health["pipelineStatus"] = "PARTIAL_SOURCE_FAILURE_WITH_VALID_FALLBACK"
        (pub / "health.json").write_text(json.dumps(health, indent=2, ensure_ascii=False))

    def _write_manifest_json(self, pub: Path, now: str):
        """Escribe manifest.json con metadatos de publicación."""
        # List all files in staging
        files = sorted({
            f.name for f in pub.iterdir() if f.is_file() and not f.name.startswith(".")
        } | {"manifest.json"})
        def csv_checksum(filename: str) -> str:
            path = pub / filename
            return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""

        manifest = {
            "name": "Observatorio ENSO Perú",
            "dataVersion": "3.1.0",
            "generatedAt": now,
            "asOf": now.split("T")[0],
            "dataSource": "LIVE_OBSERVED",
            "publicationId": self.publication_id,
            "pipelineVersion": "3.1.0",
            "coverage": "Datos reales observados desde NOAA/PSL, NOAA/CPC, GODAS, ENFEN/IMARPE",
            "sources": list(self.sources_status.keys()),
            "files": {
                "combined": "observatorio-enso-todas-las-series.csv",
                "status": "status.json",
                "quality": "data-quality.json",
                "sources": "sources.json",
                "indicators": "indicators.json",
                "health": "health.json",
                "manifest": "manifest.json",
            },
            "indicators": [
                {"id": "nino12", "label": "Niño 1+2", "scope": "coastal", "units": "degC", "file": "nino12.csv", "checksum": csv_checksum("nino12.csv")},
                {"id": "nino34", "label": "Niño 3.4", "scope": "basin", "units": "degC", "file": "nino34.csv", "checksum": csv_checksum("nino34.csv")},
                {"id": "icen", "label": "ICEN", "scope": "coastal", "units": "degC", "file": "icen.csv", "checksum": csv_checksum("icen.csv")},
                {"id": "roni", "label": "RONI", "scope": "basin", "units": "degC", "file": "roni.csv", "checksum": csv_checksum("roni.csv")},
                {"id": "d20", "label": "D20", "scope": "basin", "units": "m", "file": "d20.csv", "checksum": csv_checksum("d20.csv")},
                {"id": "u850", "label": "u850 (cpac850)", "scope": "basin", "units": "m/s", "file": "u850.csv", "checksum": csv_checksum("u850.csv")},
            ],
            "allFiles": files,
        }
        (pub / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

    # ---- Category helpers ----
    @staticmethod
    def _icen_category(v):
        if v is None: return "Sin datos"
        a = abs(v)
        sign = "El Niño Costero" if v >= 0 else "La Niña Costera"
        if a < 0.4: return "Normal"
        if a < 1.0: return f"{sign} débil"
        if a < 1.5: return f"{sign} moderado"
        if a < 2.0: return f"{sign} fuerte"
        return f"{sign} muy fuerte"

    @staticmethod
    def _roni_category(v):
        if v is None: return "Sin datos"
        if v >= 0.5: return "El Niño (cuenca)"
        if v <= -0.5: return "La Niña (cuenca)"
        return "ENSO Neutral (cuenca)"

    @staticmethod
    def _soi_category(v):
        if v is None: return "Sin datos"
        if v <= -0.5: return "Componente atmosférica de El Niño"
        if v >= 0.5: return "Componente atmosférica de La Niña"
        return "Componente atmosférica neutral"

    @staticmethod
    def _u850_direction(v):
        if v is None: return "Sin datos"
        if v > 0: return "Viento hacia el este (westerly)"
        if v < 0: return "Viento hacia el oeste (easterly)"
        return "Calmo"

    @staticmethod
    def _d20_interpretation(v):
        if v is None: return "Sin datos"
        if v > 10: return "Termoclina más profunda de lo normal (El Niño)"
        if v < -10: return "Termoclina más somera de lo normal (La Niña)"
        return "Termoclina cerca de la profundidad normal"


# ----------------------------------------------------------------------------
# CLI entry point
# ----------------------------------------------------------------------------
def main():
    """Entry point para adquisición unificada."""
    import argparse
    parser = argparse.ArgumentParser(description="Adquisición unificada ENSO")
    parser.add_argument("--staging-dir", default="staging",
                       help="Directorio de staging (default: staging)")
    parser.add_argument("--publication-dir", default="public/data",
                       help="Directorio de publicación (default: public/data)")
    parser.add_argument("--dry-run", action="store_true",
                       help="No copiar al directorio de publicación")
    parser.add_argument("--force-refresh", action="store_true",
                       help="Omitir planificación por cadencia y consultar la fuente")
    parser.add_argument("--source", choices=sorted(SOURCES), default=None,
                       help="Actualizar únicamente esta fuente y preservar el resto")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[2]
    staging = repo / args.staging_dir
    publication = repo / args.publication_dir

    orchestrator = AcquisitionOrchestrator(publication, staging)
    summary = orchestrator.run_all(
        source_id=args.source, force_refresh=args.force_refresh
    )

    if not args.dry_run:
        # Promoción atómica con rollback local del último snapshot válido.
        publication.mkdir(parents=True, exist_ok=True)
        backup = publication.with_name(f".{publication.name}.previous")
        if backup.exists():
            shutil.rmtree(backup)
        # publication acaba de crearse arriba si no existía.
        os.replace(publication, backup)
        try:
            os.replace(staging, publication)
        except Exception:
            if publication.exists():
                shutil.rmtree(publication)
            os.replace(backup, publication)
            raise
        else:
            shutil.rmtree(backup)
        print(f"\nArtefactos publicados en {publication}")

    # Exit code: 0 if all critical sources succeeded
    critical = ["noaa-psl-nino12", "noaa-psl-nino34", "noaa-cpc-roni", "noaa-cpc-soi"]
    all_critical_ok = all(orchestrator.sources_status.get(c, {}).get("success", False) for c in critical)
    return 0 if all_critical_ok else 1


if __name__ == "__main__":
    sys.exit(main())
