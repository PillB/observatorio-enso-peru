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
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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

    def __init__(self, timeout: float = 30.0, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
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
                with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                    resp = client.get(
                        url,
                        headers={
                            "User-Agent": "Observatorio-ENSO-Peru/2.0 (pipeline; +https://github.com/PillB/observatorio-enso-peru)",
                            "Accept": "text/plain, text/html, */*",
                        },
                    )
                    resp.raise_for_status()
                    return resp.text, dict(resp.headers)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    # Rate limited — honor Retry-After
                    retry_after = e.response.headers.get("Retry-After", "5")
                    try:
                        wait = float(retry_after)
                    except ValueError:
                        wait = 5.0
                    time.sleep(max(0.5, wait))
                    last_exc = e
                    continue
                if e.response.status_code >= 500:
                    # Server error — retry
                    last_exc = e
                    time.sleep(2 ** attempt + 0.5)
                    continue
                # Client error — don't retry
                raise
            except (httpx.TimeoutException, httpx.ConnectionError) as e:
                last_exc = e
                time.sleep(2 ** attempt + 0.5)
                continue
        raise RuntimeError(
            f"{source_id or url}: fallo tras {self.max_retries} reintentos: {last_exc}"
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


def parse_monthly_ascii(text: str, fill_value: float = -999.0) -> list[dict]:
    """Parsea formato mensual CPC: YEAR + 12 valores mensuales.

    Usado para SOI, wpac850, cpac850, epac850.
    """
    points = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("YEAR") or not line[0].isdigit():
            continue
        parts = line.split()
        if len(parts) < 13:
            continue
        try:
            year = int(parts[0])
        except ValueError:
            continue
        for m_idx in range(12):
            try:
                val = float(parts[m_idx + 1])
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
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.client = HttpClient(timeout=60.0, max_retries=3)
        self.retrieval_ledger: list[dict] = []
        self.sources_status: dict[str, dict] = {}

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

    def acquire_roni(self) -> list[dict]:
        """Adquiere RONI oficial (NO calculado como rolling mean)."""
        source_id = "noaa-cpc-roni"
        profile = SOURCES[source_id]
        try:
            text, headers = self.client.get(profile.access_url, source_id)
            points = parse_roni_ascii(text)
            h = hashlib.sha256(text.encode()).hexdigest()[:16]
            self._record(source_id, True, f"HTTP 200, {len(points)} seasons, sha256:{h}", h, len(points))
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
            self._record(source_id, True, f"HTTP 200, {len(points)} weekly points, sha256:{h}", h, len(points))
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
            self._record(source_id, True, f"HTTP 200, {len(points)} points, sha256:{h}", h, len(points))
            return points
        except Exception as e:
            self._record(source_id, False, str(e))
            return []

    def acquire_monthly_cpc(self, source_id: str) -> list[dict]:
        """Adquiere índice mensual CPC (SOI, wpac850, cpac850, epac850)."""
        profile = SOURCES[source_id]
        try:
            text, headers = self.client.get(profile.access_url, source_id)
            points = parse_monthly_ascii(text)
            h = hashlib.sha256(text.encode()).hexdigest()[:16]
            self._record(source_id, True, f"HTTP 200, {len(points)} points, sha256:{h}", h, len(points))
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
                        h, 1)
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
                        h, 1)
        except Exception as e:
            self._record("enfen-imarpe-status", False, str(e))

        return noaa_advisory, enfen_status

    def acquire_d20_u850(self) -> tuple[list[dict], list[dict]]:
        """Adquiere D20 (GODAS) y u850 (NCEP Reanalysis) via OPeNDAP."""
        d20 = []
        u850 = []
        # D20
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
                        f"OPeNDAP, {len(d20)} points, sha256:{h}", h, len(d20))
        except Exception as e:
            self._record("noaa-cpc-godas-d20", False, str(e))

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

    def run_all(self) -> dict[str, Any]:
        """Ejecuta la adquisición completa y devuelve un resumen."""
        print("=== Adquisición unificada de datos ENSO ===")

        # Rapid observational layer
        weekly_sst = self.acquire_weekly_sst()

        # Operational index layer
        n12 = self.acquire_psl_csv("noaa-psl-nino12")
        n34 = self.acquire_psl_csv("noaa-psl-nino34")
        roni = self.acquire_roni()  # Official, NOT computed
        soi = self.acquire_monthly_cpc("noaa-cpc-soi")
        wpac850 = self.acquire_monthly_cpc("noaa-cpc-wpac850")
        cpac850 = self.acquire_monthly_cpc("noaa-cpc-cpac850")
        epac850 = self.acquire_monthly_cpc("noaa-cpc-epac850")
        d20, _u850 = self.acquire_d20_u850()

        # ICEN: computed as 3-month rolling mean of Niño 1+2 (ENFEN methodology)
        icen = self._compute_icen(n12) if n12 else []

        # Official authority layer
        noaa_advisory, enfen_status = self.acquire_official_status()

        # Write all artifacts to staging
        self._write_artifacts(
            n12=n12, n34=n34, roni=roni, soi=soi, icen=icen,
            d20=d20, u850=cpac850,
            wpac850=wpac850, cpac850=cpac850, epac850=epac850,
            weekly_sst=weekly_sst,
            noaa_advisory=noaa_advisory, enfen_status=enfen_status,
        )

        # Summary
        summary = {
            "sources": self.sources_status,
            "total_sources": len(self.sources_status),
            "successful": sum(1 for s in self.sources_status.values() if s["success"]),
            "failed": sum(1 for s in self.sources_status.values() if not s["success"]),
        }
        print(f"\n=== Resumen: {summary['successful']}/{summary['total_sources']} fuentes exitosas ===")
        for sid, info in self.sources_status.items():
            status = "✅" if info["success"] else "❌"
            print(f"  {status} {sid}: {info['evidence'][:80]}")
        return summary

    def _compute_icen(self, n12: list[dict]) -> list[dict]:
        """ICEN = media móvil de 3 meses de anomalías de TSM Niño 1+2.

        Esto SÍ es metodológicamente correcto para ICEN (definición ENFEN).
        NO se aplica a RONI (que se obtiene del producto oficial).
        """
        result = []
        for i in range(len(n12)):
            window = n12[max(0, i - 2):i + 1]
            vals = [p["value"] for p in window if p["value"] is not None]
            if len(vals) == 3:
                mean = round(sum(vals) / 3, 2)
            else:
                mean = None
            result.append({"month": n12[i]["month"], "value": mean, "flag": n12[i].get("flag", "final")})
        return result

    def _write_artifacts(self, **data):
        """Escribe todos los artefactos al directorio de staging."""
        pub = self.staging_dir
        now = datetime.now(timezone.utc).isoformat()

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
            write_csv("icen", data["icen"], "degC", "ENFEN/IMARPE (calculado desde Niño 1+2 PSL)")
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

        # Write status.json
        self._write_status_json(pub, data, now)

        # Write health.json from real evidence
        self._write_health_json(pub, now)

        # Write manifest.json
        self._write_manifest_json(pub, now)

    def _write_status_json(self, pub: Path, data: dict, now: str):
        """Escribe status.json con valores reales más recientes."""
        def latest(points):
            if not points:
                return {"month": "", "value": None}
            for p in reversed(points):
                if p.get("value") is not None:
                    return p
            return {"month": "", "value": None}

        ln12 = latest(data.get("n12", []))
        ln34 = latest(data.get("n34", []))
        licen = latest(data.get("icen", []))
        lroni = latest(data.get("roni", []))
        lsoi = latest(data.get("soi", []))
        ld20 = latest(data.get("d20", []))
        lu850 = latest(data.get("u850", []))
        noaa = data.get("noaa_advisory")
        enfen = data.get("enfen_status")

        status = {
            "asOf": now.split("T")[0],
            "dataVersion": "3.0.0",
            "generatedAt": now,
            "dataSource": "LIVE_OBSERVED",
            "publicationId": hashlib.sha256(now.encode()).hexdigest()[:12],
            "coastal": {
                "alert": enfen["alert"] if enfen else "Consulte ENFEN en siofen.imarpe.gob.pe",
                "alertSource": "ENFEN / IMARPE",
                "alertOfficialUrl": "https://siofen.imarpe.gob.pe/nivel2/indice-costero-el-nino-icen",
                "alertDate": enfen.get("month", "") if enfen else "",
                "alertSourceMethod": enfen.get("source", "unavailable") if enfen else "unavailable",
                "nino12Anom": ln12["value"],
                "nino12Month": ln12["month"],
                "icen": licen["value"],
                "icenWindow": licen["month"],
                "icenCategory": self._icen_category(licen["value"]),
                "freshness": f"Dato observado · adquirido {now}",
            },
            "basin": {
                "alert": noaa["alert"] if noaa else "Consulte NOAA/CPC en cpc.ncep.noaa.gov",
                "alertSource": "NOAA / CPC",
                "alertOfficialUrl": "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml",
                "alertDate": noaa.get("date", "") if noaa else "",
                "nino34Anom": ln34["value"],
                "nino34Month": ln34["month"],
                "roni": lroni["value"],
                "roniWindow": lroni["month"],
                "roniCategory": self._roni_category(lroni["value"]),
                "roniSource": "NOAA/CPC RONI.ascii.txt (official, NOT computed)",
                "freshness": f"Dato observado · adquirido {now}",
            },
            "winds": {
                "u850Anom": lu850["value"],
                "u850Month": lu850["month"],
                "u850Source": "NOAA/CPC cpac850 (actual wind, Central Pacific 175°W-140°W)",
                "direction": self._u850_direction(lu850["value"]),
                "signMeaning": "Valores positivos = viento hacia el este (westerly); negativos = hacia el oeste (easterly). Nota: CPC trade wind index es viento real (no anomalía).",
            },
            "thermocline": {
                "d20Anom": ld20["value"],
                "d20Month": ld20["month"],
                "interpretation": self._d20_interpretation(ld20["value"]),
            },
            "soi": {
                "value": lsoi["value"],
                "month": lsoi["month"],
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
            "dataVersion": "3.0.0",
            "dataSource": "LIVE_OBSERVED",
            "publicationId": hashlib.sha256(now.encode()).hexdigest()[:12],
            "sources": [],
        }
        for sid, info in self.sources_status.items():
            profile = SOURCES.get(sid)
            health["sources"].append({
                "id": sid,
                "institution": info.get("institution", ""),
                "product": info.get("product", ""),
                "status": "HEALTHY" if info["success"] else "FAILED",
                "freshnessState": "FRESH" if info["success"] else "STALE",
                "lastUpdate": info.get("retrieved_at", now),
                "retrievedAt": info.get("retrieved_at", now),
                "retrievalEvidence": info.get("evidence", ""),
                "contentHash": info.get("hash", ""),
                "pointsRetrieved": info.get("points", 0),
                "cadence": profile.temporal_resolution if profile else "",
                "authorityLevel": profile.authority_level.value if profile else "",
                "freshnessSlo": profile.freshness_slo if profile else "",
                "riskTier": "LOW" if info["success"] else "HIGH",
            })
        (pub / "health.json").write_text(json.dumps(health, indent=2, ensure_ascii=False))

    def _write_manifest_json(self, pub: Path, now: str):
        """Escribe manifest.json con metadatos de publicación."""
        # List all files in staging
        files = sorted([f.name for f in pub.iterdir() if f.is_file() and not f.name.startswith(".")])
        manifest = {
            "name": "Observatorio ENSO Perú",
            "dataVersion": "3.0.0",
            "generatedAt": now,
            "asOf": now.split("T")[0],
            "dataSource": "LIVE_OBSERVED",
            "publicationId": hashlib.sha256(now.encode()).hexdigest()[:12],
            "pipelineVersion": "3.0.0",
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
                {"id": "nino12", "label": "Niño 1+2", "scope": "coastal", "units": "degC", "file": "nino12.csv"},
                {"id": "nino34", "label": "Niño 3.4", "scope": "basin", "units": "degC", "file": "nino34.csv"},
                {"id": "icen", "label": "ICEN", "scope": "coastal", "units": "degC", "file": "icen.csv"},
                {"id": "roni", "label": "RONI", "scope": "basin", "units": "degC", "file": "roni.csv"},
                {"id": "soi", "label": "SOI", "scope": "basin", "units": "dimensionless", "file": "soi.csv"},
                {"id": "d20", "label": "D20", "scope": "basin", "units": "m", "file": "d20.csv"},
                {"id": "u850", "label": "u850 (cpac850)", "scope": "basin", "units": "m/s", "file": "u850.csv"},
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
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[2]
    staging = repo / args.staging_dir
    publication = repo / args.publication_dir

    orchestrator = AcquisitionOrchestrator(publication, staging)
    summary = orchestrator.run_all()

    if not args.dry_run:
        # Copy staging to publication (atomic-ish)
        import shutil
        publication.mkdir(parents=True, exist_ok=True)
        for f in staging.iterdir():
            if f.is_file():
                shutil.copy2(f, publication / f.name)
        print(f"\nArtefactos publicados en {publication}")

    # Exit code: 0 if all critical sources succeeded
    critical = ["noaa-psl-nino12", "noaa-psl-nino34", "noaa-cpc-roni", "noaa-cpc-soi"]
    all_critical_ok = all(orchestrator.sources_status.get(c, {}).get("success", False) for c in critical)
    return 0 if all_critical_ok else 1


if __name__ == "__main__":
    sys.exit(main())
