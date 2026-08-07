"""Source-contract canaries: real endpoint probes that fetch, parse, and validate schema.

These are NOT just registry field checks — they actually:
  1. Fetch the endpoint
  2. Validate HTTP status, headers, MIME type
  3. Parse representative data
  4. Verify observation dates are within cadence
  5. Check units and schema fingerprints
  6. Detect schema changes
  7. Report structured evidence

Run as: python -m enso.source_canaries
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "python"))

from enso.source_profiles import SOURCES, SourceProfile, AuthorityLevel


@dataclass
class CanaryResult:
    """Result of a single source-contract canary probe."""
    source_id: str
    endpoint: str
    timestamp: str
    http_status: Optional[int] = None
    content_length: int = 0
    content_hash: str = ""
    mime_type: str = ""
    schema_valid: bool = False
    observation_date: str = ""
    within_cadence: bool = False
    error: str = ""
    notes: dict[str, Any] = field(default_factory=dict)
    blocking: bool = True

    @property
    def passed(self) -> bool:
        return (
            self.http_status == 200
            and self.schema_valid
            and self.within_cadence
            and not self.error
        )

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "endpoint": self.endpoint,
            "timestamp": self.timestamp,
            "http_status": self.http_status,
            "content_length": self.content_length,
            "content_hash": self.content_hash,
            "mime_type": self.mime_type,
            "schema_valid": self.schema_valid,
            "observation_date": self.observation_date,
            "within_cadence": self.within_cadence,
            "passed": self.passed,
            "error": self.error,
            "notes": self.notes,
            "blocking": self.blocking,
        }


def fetch_endpoint(url: str, timeout: float = 30.0,
                   max_bytes: int = 2_000_000) -> tuple[Optional[int], str, dict[str, str]]:
    """Fetch an endpoint and return (status, content, headers)."""
    if httpx is None:
        return None, "", {}
    try:
        original_host = (urlparse(url).hostname or "").lower()
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream(
                "GET", url,
                headers={
                    "User-Agent": "Observatorio-ENSO-Peru/3.0 (canary; +https://github.com/PillB/observatorio-enso-peru)",
                    "Accept": "text/plain, text/csv, application/json, text/html, */*",
                },
            ) as resp:
                final_host = (urlparse(str(resp.url)).hostname or "").lower()
                if final_host != original_host:
                    return resp.status_code, f"redirected to unexpected domain {final_host}", dict(resp.headers)
                body = bytearray()
                for chunk in resp.iter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        return resp.status_code, "response exceeded bounded canary size", dict(resp.headers)
                encoding = resp.encoding or "utf-8"
                return resp.status_code, bytes(body).decode(encoding, errors="replace"), dict(resp.headers)
    except Exception as e:
        return None, str(e), {}


def validate_roni_schema(content: str) -> tuple[bool, str]:
    """Validate RONI.ascii.txt schema: SEAS YR ANOM format."""
    if "SEAS" not in content and "DJF" not in content:
        return False, "Missing SEAS/DJF header"
    lines = [ln for ln in content.strip().split("\n") if ln.strip() and not ln.startswith("#")]
    if len(lines) < 100:
        return False, f"Too few lines: {len(lines)}"
    # Check last line has valid format
    parts = lines[-1].split()
    if len(parts) < 3:
        return False, "Last line malformed"
    try:
        int(parts[1])  # year
        float(parts[2])  # anomaly
    except (ValueError, IndexError):
        return False, "Last line values not numeric"
    return True, f"{len(lines)} seasons"


def validate_psl_csv_schema(content: str) -> tuple[bool, str]:
    """Validate PSL CSV schema: Date,Value format."""
    lines = [ln for ln in content.strip().split("\n") if ln.strip() and not ln.startswith("#")]
    if len(lines) < 100:
        return False, f"Too few lines: {len(lines)}"
    if "Date" not in lines[0] and "," not in lines[0]:
        return False, "Missing Date header or comma delimiter"
    parts = lines[-1].split(",")
    if len(parts) < 2:
        return False, "Last line has no comma"
    try:
        float(parts[1])
    except (ValueError, IndexError):
        return False, "Last line value not numeric"
    return True, f"{len(lines)} points"


def validate_monthly_ascii_schema(content: str, min_lines: int = 50) -> tuple[bool, str]:
    """Validate CPC monthly ASCII format: YEAR + 12 monthly values.
    
    Handles the CPC format where negative values can be concatenated
    without spaces (e.g. '-2.4-999.9-999.9').
    """
    import re as _re
    lines = [ln for ln in content.strip().split("\n") if ln.strip() and ln[0].isdigit()]
    if len(lines) < min_lines:
        return False, f"Too few data lines: {len(lines)}"
    # Use regex to split: year is first token, then values are split on
    # boundaries between a digit and a minus sign, or on whitespace
    last_line = lines[-1]
    # Extract year
    year_match = _re.match(r"(\d{4})\s*(.*)", last_line)
    if not year_match:
        return False, "Cannot parse year from last line"
    year = year_match.group(1)
    rest = year_match.group(2).strip()
    # Split on whitespace first
    parts = rest.split()
    if len(parts) >= 12:
        return True, f"{len(lines)} months"
    # If split didn't work, try regex split on value boundaries
    # Values are like: -999.0, 2.5, -1.3, etc.
    values = _re.findall(r"-?\d+\.\d+", rest)
    if len(values) >= 12:
        return True, f"{len(lines)} months ({len(values)} values parsed)"
    return False, f"Last line has {len(values)} values (need >= 12)"


def validate_weekly_sst_schema(content: str) -> tuple[bool, str]:
    """Validate weekly SST format."""
    if "Weekly SST" not in content and "Nino" not in content:
        return False, "Missing expected header"
    if "JAN" not in content:
        return False, "No month markers"
    return True, "Valid weekly SST"


def validate_html_advisory_schema(content: str) -> tuple[bool, str]:
    """Validate NOAA ENSO advisory HTML."""
    if "Alert System Status" not in content:
        return False, "Missing 'Alert System Status'"
    if "ENSO" not in content and "El Niño" not in content and "La Niña" not in content:
        return False, "No ENSO mention"
    return True, "Valid advisory HTML"


def validate_enfen_wp_schema(content: str) -> tuple[bool, str]:
    try:
        posts = json.loads(content)
    except json.JSONDecodeError:
        return False, "Response is not JSON"
    if not isinstance(posts, list) or not posts:
        return False, "No ENFEN posts returned"
    post = posts[0]
    required = ("date", "link", "title", "content")
    if any(key not in post for key in required):
        return False, "Missing WordPress post fields"
    if not isinstance(post.get("title", {}).get("rendered"), str):
        return False, "Invalid title.rendered"
    return True, "Valid ENFEN WordPress post"


def check_within_cadence(observation_date: str, stale_after_days: int) -> tuple[bool, str]:
    """Check if observation date is within the cadence SLO."""
    if not observation_date:
        return False, "No observation date"
    try:
        parts = observation_date.split("-")
        if len(parts) >= 3:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            obs_dt = datetime(y, m, d, tzinfo=timezone.utc)
        elif len(parts) >= 2:
            y, m = int(parts[0]), int(parts[1])
            obs_dt = datetime(y, m, 1, tzinfo=timezone.utc)
        else:
            return False, f"Cannot parse date: {observation_date}"
        age_days = (datetime.now(timezone.utc) - obs_dt).days
        if age_days > stale_after_days:
            return False, f"Observation {age_days}d old (SLO: {stale_after_days}d)"
        return True, f"Within SLO ({age_days}d old)"
    except (ValueError, IndexError):
        pass
    return False, f"Cannot parse date: {observation_date}"


def run_canary(source_id: str) -> CanaryResult:
    """Run a single source-contract canary probe."""
    profile = SOURCES.get(source_id)
    if not profile:
        return CanaryResult(
            source_id=source_id,
            endpoint="",
            timestamp=datetime.now(timezone.utc).isoformat(),
            error=f"Source profile not found: {source_id}",
        )

    now = datetime.now(timezone.utc).isoformat()
    endpoint = profile.access_url
    blocking = source_id not in {
        "pmel-tao-daily-d20", "pmel-tao-daily-wind",
        "imarpe-siofen-bdo", "imarpe-siofen-bs-tlp",
        "enfen-imarpe-document-assets",
    }
    if source_id in {"noaa-ncei-oisst-daily-preliminary", "noaa-ncei-oisst-daily-final"}:
        from enso.rapid_sources import build_oisst_griddap_url
        dataset = (
            "ncdc_oisst_v2_avhrr_prelim_by_time_zlev_lat_lon"
            if "preliminary" in source_id else
            "ncdc_oisst_v2_avhrr_by_time_zlev_lat_lon"
        )
        endpoint = build_oisst_griddap_url(dataset, "anom", -5, 5, 190, 191)
    elif source_id == "pmel-tao-daily-d20":
        endpoint = "https://data.pmel.noaa.gov/pmel/erddap/info/pmelTaoDyIso/index.json"
    elif source_id == "pmel-tao-daily-wind":
        endpoint = "https://data.pmel.noaa.gov/pmel/erddap/info/pmelTaoDyW/index.json"
    status, content, headers = fetch_endpoint(endpoint, timeout=profile.timeout)

    result = CanaryResult(
        source_id=source_id,
        endpoint=endpoint,
        timestamp=now,
        http_status=status,
        content_length=len(content) if content else 0,
        mime_type=headers.get("content-type", ""),
        blocking=blocking,
    )

    if status != 200:
        result.error = f"HTTP {status}: {content[:300]}" if content else f"HTTP {status}"
        return result

    if not content:
        result.error = "Empty response"
        return result

    # Content hash
    import hashlib
    result.content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

    # Schema validation based on source
    schema_valid = False
    obs_date = ""
    schema_msg = ""

    if source_id == "noaa-cpc-roni":
        schema_valid, schema_msg = validate_roni_schema(content)
        # Extract latest observation date
        lines = [ln for ln in content.strip().split("\n") if ln.strip() and not ln.startswith("SEAS") and not ln.startswith("#")]
        if lines:
            parts = lines[-1].split()
            if len(parts) >= 2:
                season_to_month = {"DJF":"01","JFM":"02","FMA":"03","MAM":"04","AMJ":"05","MJJ":"06",
                                    "JJA":"07","JAS":"08","ASO":"09","SON":"10","OND":"11","NDJ":"12"}
                m = season_to_month.get(parts[0], "01")
                obs_date = f"{parts[1]}-{m}"

    elif source_id in ("noaa-psl-nino12", "noaa-psl-nino34"):
        schema_valid, schema_msg = validate_psl_csv_schema(content)
        lines = [ln for ln in content.strip().split("\n") if ln.strip() and not ln.startswith("#") and not ln.startswith("Date")]
        if lines:
            parts = lines[-1].split(",")
            if parts:
                obs_date = parts[0].strip()[:7]  # YYYY-MM

    elif source_id in ("noaa-cpc-soi", "noaa-cpc-wpac850", "noaa-cpc-cpac850", "noaa-cpc-epac850"):
        schema_valid, schema_msg = validate_monthly_ascii_schema(content)
        import re as _re3
        # Find lines with real data (not all -999.9)
        for line in reversed([ln for ln in content.strip().split("\n") if ln.strip() and ln[0].isdigit()]):
            year_match = _re3.match(r"(\d{4})\s*(.*)", line)
            if not year_match:
                continue
            yr_str = year_match.group(1)
            rest = year_match.group(2).strip()
            values = _re3.findall(r"-?\d+\.\d+", rest)
            if len(values) >= 12:
                # Find the latest non-fill value
                for m_idx in range(11, -1, -1):
                    try:
                        val = float(values[m_idx])
                        if val > -900:
                            obs_date = f"{yr_str}-{m_idx + 1:02d}"
                            break
                    except (ValueError, IndexError):
                        pass
                if obs_date:
                    break

    elif source_id == "noaa-cpc-wksst":
        schema_valid, schema_msg = validate_weekly_sst_schema(content)
        import re as _re
        # Find ALL dates in format DDMMMYYYY and take the LAST one
        dates = _re.findall(r"(\d{2})([A-Z]{3})(\d{4})", content)
        if dates:
            day, mon, yr = dates[-1]
            month_map = {"JAN":"01","FEB":"02","MAR":"03","APR":"04","MAY":"05","JUN":"06",
                        "JUL":"07","AUG":"08","SEP":"09","OCT":"10","NOV":"11","DEC":"12"}
            m = month_map.get(mon, "01")
            obs_date = f"{yr}-{m}-{day}"

    elif source_id == "noaa-cpc-enso-advisory":
        schema_valid, schema_msg = validate_html_advisory_schema(content)
        # Extract date from HTML and convert to YYYY-MM
        import re as _re2
        import html as _html_mod
        decoded = _html_mod.unescape(content)
        m = _re2.search(r"\b(\d{1,2})\s+(\w+)\s+(202\d)\b", decoded)
        if m:
            day, mon_name, yr = m.groups()
            month_map2 = {"January":"01","February":"02","March":"03","April":"04","May":"05","June":"06",
                         "July":"07","August":"08","September":"09","October":"10","November":"11","December":"12"}
            m_num = month_map2.get(mon_name, "01")
            obs_date = f"{yr}-{m_num}"

    elif source_id == "enfen-imarpe-status":
        try:
            from enso.document_sources import parse_enfen_wordpress_posts
            discovered = parse_enfen_wordpress_posts(content)
            schema_valid, schema_msg = True, "Valid official ENFEN post"
            obs_date = discovered["publication_date"]
        except Exception as exc:
            schema_valid, schema_msg = False, str(exc)

    elif source_id == "enfen-imarpe-document-assets":
        try:
            from enso.document_sources import parse_enfen_wordpress_posts
            discovered = parse_enfen_wordpress_posts(content)
            schema_valid, schema_msg = True, "Valid official communiqué discovery"
            obs_date = discovered["publication_date"]
            result.notes["document_count"] = len(discovered["document_urls"])
            result.notes["post_id"] = discovered["post_id"]
        except Exception as exc:
            schema_valid, schema_msg = False, str(exc)

    elif source_id in {"noaa-ncei-oisst-daily-preliminary", "noaa-ncei-oisst-daily-final"}:
        try:
            from enso.rapid_sources import parse_erddap_grid_csv
            parsed = parse_erddap_grid_csv(content, "anom", "Celsius")
            schema_valid, schema_msg = True, parsed["schema_fingerprint"]
            obs_date = parsed["valid_period"]
            result.notes["point_count"] = parsed["point_count"]
        except Exception as exc:
            schema_valid, schema_msg = False, str(exc)

    elif source_id in {"pmel-tao-daily-d20", "pmel-tao-daily-wind"}:
        try:
            metadata = json.loads(content).get("table", {}).get("rows", [])
            required_variable = "ISO_6" if source_id.endswith("d20") else "WU_422"
            variables = {row[1] for row in metadata if row and row[0] == "variable"}
            expected = {"time", "latitude", "longitude", "station", required_variable}
            if not expected.issubset(variables):
                raise ValueError(f"missing PMEL variables: {sorted(expected - variables)}")
            time_ranges = [row[4] for row in metadata if row[0] == "attribute" and row[1] == "time" and row[2] == "actual_range"]
            if not time_ranges:
                raise ValueError("missing PMEL time actual_range")
            latest_epoch = float(str(time_ranges[-1]).split(",")[-1].strip())
            obs_date = datetime.fromtimestamp(latest_epoch, tz=timezone.utc).date().isoformat()
            schema_valid, schema_msg = True, f"PMEL variables include {required_variable}"
        except Exception as exc:
            schema_valid, schema_msg = False, str(exc)

    elif source_id in {"imarpe-siofen-bdo", "imarpe-siofen-bs-tlp"}:
        lower = content.lower()
        expected_text = "bolet" in lower and ("temperatura" in lower or "oceanogr" in lower)
        substituted = "cloudflare" in lower or "just a moment" in lower or "bad gateway" in lower
        schema_valid = bool(expected_text and not substituted)
        schema_msg = "Official bulletin index reachable" if schema_valid else "blocked/error page substituted for bulletin index"
        # El índice no expone de manera estable una fecha estructurada. Un
        # canario correcto registra UNKNOWN, no inventa una fecha actual.
        obs_date = ""

    result.schema_valid = schema_valid
    result.observation_date = obs_date
    result.notes["schema_message"] = schema_msg

    # Cadence check
    stale_days_map = {
        "noaa-cpc-roni": 75, "noaa-psl-nino12": 60, "noaa-psl-nino34": 60,
        "noaa-cpc-soi": 60, "noaa-cpc-wpac850": 60, "noaa-cpc-cpac850": 60,
        "noaa-cpc-epac850": 60, "noaa-cpc-wksst": 35,
        "noaa-cpc-enso-advisory": 60, "enfen-imarpe-status": 120,
        "noaa-ncei-oisst-daily-preliminary": 7,
        "noaa-ncei-oisst-daily-final": 30,
        "pmel-tao-daily-d20": 35, "pmel-tao-daily-wind": 35,
        "enfen-imarpe-document-assets": 75,
    }
    stale_days = stale_days_map.get(source_id, 60)
    within, cadence_msg = check_within_cadence(obs_date, stale_days)
    result.within_cadence = within
    result.notes["cadence_message"] = cadence_msg

    return result


def run_all_canaries() -> dict:
    """Run all source-contract canaries and return structured results."""
    # Only check sources that have direct HTTP endpoints (not OPeNDAP or fallback)
    canary_sources = [
        "noaa-ncei-oisst-daily-preliminary", "noaa-ncei-oisst-daily-final",
        "noaa-cpc-wksst", "noaa-psl-nino12", "noaa-psl-nino34",
        "noaa-cpc-roni", "noaa-cpc-soi", "noaa-cpc-wpac850",
        "noaa-cpc-cpac850", "noaa-cpc-epac850", "noaa-cpc-enso-advisory",
        "enfen-imarpe-status", "enfen-imarpe-document-assets",
        "pmel-tao-daily-d20", "pmel-tao-daily-wind",
        "imarpe-siofen-bdo", "imarpe-siofen-bs-tlp",
    ]

    results = []
    for source_id in canary_sources:
        # Rate limit: 1s between requests
        time.sleep(1.0)
        result = run_canary(source_id)
        results.append(result.to_dict())
        status = "✅" if result.passed else "❌"
        print(f"  {status} {source_id}: HTTP {result.http_status}, schema={result.schema_valid}, cadence={result.within_cadence}")

    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed
    blocking_failed = sum(1 for r in results if not r["passed"] and r["blocking"])

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "total_sources": len(results),
        "passed": passed,
        "failed": failed,
        "blocking_failed": blocking_failed,
        "results": results,
    }


def main():
    """Entry point for running canaries."""
    print("=== Source-Contract Canaries ===")
    report = run_all_canaries()
    print(f"\n=== Summary: {report['passed']}/{report['total_sources']} passed ===")

    # Write report
    report_path = REPO / "audit" / "freshness-and-automation" / "source-canary-results.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"Report written to: {report_path}")

    return 0 if report["blocking_failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
