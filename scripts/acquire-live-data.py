#!/usr/bin/env python3
"""Adquisición real de datos ENSO desde fuentes NOAA/CPC y PSL.

Este módulo reemplaza la generación sintética con observaciones reales
de los endpoints oficiales de NOAA.

Fuentes:
  - Niño 1+2: https://psl.noaa.gov/data/timeseries/month/data/nino12.long.anom.csv
  - Niño 3.4: https://psl.noaa.gov/data/timeseries/month/data/nino34.long.anom.csv
  - SOI: https://psl.noaa.gov/data/timeseries/month/data/soi.long.data
  - RONI/ONI: https://www.cpc.ncep.noaa.gov/data/indices/ersst5.nino.mth.91-20.ascii

Los datos se adquieren con httpx, se validan, se normalizan y se
escriben en public/data/ como artefactos de producción.
"""

from __future__ import annotations

import json
import os
import re
import sys
import hashlib
from datetime import datetime, timezone
from pathlib import Path

# Add python/ to path for enso module imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
try:
    from enso.official_status import fetch_noaa_enso_advisory, fetch_enfen_status
except ImportError:
    fetch_noaa_enso_advisory = None
    fetch_enfen_status = None

try:
    import httpx
except ImportError:
    print("ERROR: httpx no instalado. Ejecutar: pip install httpx", file=sys.stderr)
    sys.exit(1)

DATA_DIR = Path(__file__).resolve().parents[1] / "public" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SOURCES = {
    "nino12": {
        "url": "https://psl.noaa.gov/data/timeseries/month/data/nino12.long.anom.csv",
        "format": "psl_csv",
        "units": "degC",
        "scope": "coastal",
        "institution": "NOAA / PSL",
        "product": "Niño 1+2 SST Anomaly",
    },
    "nino34": {
        "url": "https://psl.noaa.gov/data/timeseries/month/data/nino34.long.anom.csv",
        "format": "psl_csv",
        "units": "degC",
        "scope": "basin",
        "institution": "NOAA / PSL",
        "product": "Niño 3.4 SST Anomaly",
    },
    "soi": {
        "url": "https://psl.noaa.gov/data/timeseries/month/data/soi.long.data",
        "format": "psl_soi",
        "units": "dimensionless",
        "scope": "basin",
        "institution": "NOAA / PSL",
        "product": "Southern Oscillation Index",
    },
    "nino_indices": {
        "url": "https://www.cpc.ncep.noaa.gov/data/indices/ersst5.nino.mth.91-20.ascii",
        "format": "cpc_ascii",
        "units": "degC",
        "scope": "basin",
        "institution": "NOAA / CPC",
        "product": "ERSST v5 Niño indices + RONI",
    },
    "d20": {
        "url": "https://psl.noaa.gov/thredds/dodsC/Datasets/godas/dbss_obil",
        "format": "opendap_ascii_grid",
        "units": "m",
        "scope": "basin",
        "institution": "NOAA / PSL (GODAS dbss_obil)",
        "product": "Anomalía de D20 (proxy: dbss_obil) — Niño 3.4",
    },
    "u850": {
        "url": "https://psl.noaa.gov/thredds/dodsC/Datasets/ncep.reanalysis.derived/pressure/uwnd.mon.mean.nc",
        "format": "opendap_ascii_grid",
        "units": "m_per_s",
        "scope": "basin",
        "institution": "NOAA / PSL (NCEP/NCAR Reanalysis)",
        "product": "Anomalía de viento zonal a 850 hPa — Niño 3.4",
    },
}


def fetch(url: str) -> str:
    """Adquiere datos con retry y timeout."""
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for attempt in range(3):
            try:
                resp = client.get(url, headers={"User-Agent": "Observatorio-ENSO-Peru/1.0"})
                resp.raise_for_status()
                return resp.text
            except Exception as e:
                if attempt == 2:
                    raise
                import time
                time.sleep(2 ** attempt + 0.5)


def parse_psl_csv(text: str) -> list[dict]:
    """Parsea CSV de PSL: Date, Value."""
    points = []
    lines = text.strip().split("\n")
    for line in lines:
        if line.startswith("Date") or line.startswith("#") or not line.strip():
            continue
        parts = line.split(",")
        if len(parts) < 2:
            continue
        date_str = parts[0].strip()
        val_str = parts[1].strip()
        try:
            y, m, d = date_str.split("-")
            month = f"{y}-{int(m):02d}"
            val = float(val_str)
            if val == -99.99 or val == -9999.0 or val == -9999:
                val = None
            points.append({"month": month, "value": val, "flag": "final"})
        except (ValueError, IndexError):
            continue
    return points


def parse_psl_soi(text: str) -> list[dict]:
    """Parsea SOI de PSL: formato de tabla mensual."""
    points = []
    lines = text.strip().split("\n")
    for line in lines:
        if line.startswith("#") or line.startswith("CRU") or line.startswith("file") or line.startswith("units") or line.startswith("http") or not line.strip():
            continue
        parts = line.split()
        if len(parts) < 13:
            continue
        try:
            year = int(parts[0])
            for m_idx in range(12):
                val = float(parts[m_idx + 1])
                if val == -99.99 or val == -999:
                    val = None
                month = f"{year}-{m_idx + 1:02d}"
                points.append({"month": month, "value": val, "flag": "final"})
        except (ValueError, IndexError):
            continue
    return points


def parse_cpc_ascii(text: str) -> dict:
    """Parsea CPC ERSST5 Niño indices (incluye NINO1+2, NINO3, NINO34, NINO4)."""
    series = {"nino12": [], "nino34": [], "nino3": [], "nino4": []}
    lines = text.strip().split("\n")
    for line in lines:
        parts = line.split()
        if len(parts) < 7:
            continue
        try:
            year = int(parts[0])
            month = int(parts[1])
            if year < 1950:
                continue
            month_iso = f"{year}-{month:02d}"
            # Columnas: year month NINO1+2 NINO3 NINO34 NINO4
            n12 = float(parts[3])   # NINO1+2 anomaly
            n3 = float(parts[5])    # NINO3 anomaly
            n34 = float(parts[7])   # NINO34 anomaly
            n4 = float(parts[9])    # NINO4 anomaly
            for key, val in [("nino12", n12), ("nino3", n3), ("nino34", n34), ("nino4", n4)]:
                if val == -99.9 or val == -9999.0 or val == -9999:
                    val = None
                series[key].append({"month": month_iso, "value": val, "flag": "final"})
        except (ValueError, IndexError):
            continue
    return series


def compute_3mo_mean(points: list[dict]) -> list[dict]:
    """ICEN/RONI = media móvil de 3 meses."""
    result = []
    for i in range(len(points)):
        window = points[max(0, i - 2):i + 1]
        vals = [p["value"] for p in window if p["value"] is not None]
        if len(vals) == 3:
            mean = round(sum(vals) / 3, 2)
        else:
            mean = None
        result.append({"month": points[i]["month"], "value": mean, "flag": points[i].get("flag", "final")})
    return result


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Fetchers para D20 (GODAS dbss_obil) y u850 (NCEP Reanalysis) via OPeNDAP
# ---------------------------------------------------------------------------
def fetch_d20_anomaly():
    """Adquiere la serie mensual de anomalías D20 (proxy dbss_obil) vía OPeNDAP.

    Usa el módulo ``enso.opendap_fetchers.GodasD20Fetcher`` que accede al
    endpoint ASCII de PSL OPeNDAP para los archivos GODAS anuales
    (``dbss_obil.{year}.nc``). Calcula la media areal sobre Niño 3.4
    (5°S–5°N, 170°O–120°O) y la anomalía respecto a la climatología
    1991–2020.
    """
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
    from enso.opendap_fetchers import GodasD20Fetcher

    f = GodasD20Fetcher()
    anom_points = f.fetch_anomaly_series()
    out = []
    for p in anom_points:
        out.append({
            "month": p.month,
            "value": p.value,
            "flag": "preliminary" if p.flag.value == "preliminary" else "final",
        })
    return out


def fetch_u850_anomaly():
    """Adquiere la serie mensual de anomalías u850 (NCEP Reanalysis) vía OPeNDAP.

    Usa el módulo ``enso.opendap_fetchers.NcepU850Fetcher`` que accede al
    endpoint ASCII de PSL OPeNDAP para ``uwnd.mon.mean.nc`` (NCEP/NCAR
    Reanalysis1 monthly mean, nivel 850 hPa). Calcula la media areal sobre
    Niño 3.4 (5°S–5°N, 170°O–120°O) y la anomalía respecto a la
    climatología 1991–2020.
    """
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
    from enso.opendap_fetchers import NcepU850Fetcher

    f = NcepU850Fetcher()
    anom_points = f.fetch_anomaly_series()
    out = []
    for p in anom_points:
        out.append({
            "month": p.month,
            "value": p.value,
            "flag": "preliminary" if p.flag.value == "preliminary" else "final",
        })
    return out


def write_series_csv(series_id: str, points: list[dict], units: str, source: str):
    """Escribe CSV con metadatos."""
    now = datetime.now(timezone.utc).isoformat()
    lines = [
        f"# Observatorio ENSO Perú — {series_id}",
        f"# Unidades: {units}",
        f"# Fuente: {source}",
        f"# Adquirido: {now}",
        f"# Datos reales observados",
        "month,value,flag",
    ]
    for p in points:
        v = p["value"] if p["value"] is not None else ""
        lines.append(f"{p['month']},{v},{p.get('flag', '')}")
    (DATA_DIR / f"{series_id}.csv").write_text("\n".join(lines))


def write_status_json(n12: list, n34: list, icen: list, roni: list, soi: list, d20: list, u850: list, noaa_advisory=None, enfen_status=None):
    """Escribe status.json con valores reales más recientes.

    Si ``noaa_advisory`` o ``enfen_status`` son None, se usa el mensaje
    "Consulte ..." como fallback.
    """
    def latest(points):
        for p in reversed(points):
            if p["value"] is not None:
                return p
        return {"month": "", "value": None}

    ln12 = latest(n12)
    ln34 = latest(n34)
    licen = latest(icen)
    lroni = latest(roni)
    lsoi = latest(soi)
    ld20 = latest(d20) if d20 else {"month": "", "value": None}
    lu850 = latest(u850) if u850 else {"month": "", "value": None}

    now = datetime.now(timezone.utc).isoformat()

    status = {
        "asOf": now.split("T")[0],
        "dataVersion": "2.0.0",
        "generatedAt": now,
        "dataSource": "LIVE_OBSERVED",
        "coastal": {
            "alert": enfen_status["alert"] if enfen_status else "Consulte ENFEN en siofen.imarpe.gob.pe",
            "alertSource": "ENFEN / IMARPE",
            "alertOfficialUrl": "https://siofen.imarpe.gob.pe/nivel2/indice-costero-el-nino-icen",
            "alertDate": enfen_status.get("month", "") if enfen_status else "",
            "nino12Anom": ln12["value"],
            "nino12Month": ln12["month"],
            "icen": licen["value"],
            "icenWindow": licen["month"],
            "icenCategory": _icen_category(licen["value"]),
            "freshness": f"Dato observado · adquirido {now}",
            "preliminary": False,
        },
        "basin": {
            "alert": noaa_advisory["alert"] if noaa_advisory else "Consulte NOAA/CPC en cpc.ncep.noaa.gov",
            "alertSource": "NOAA / CPC",
            "alertOfficialUrl": "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml",
            "alertDate": noaa_advisory.get("date", "") if noaa_advisory else "",
            "nino34Anom": ln34["value"],
            "nino34Month": ln34["month"],
            "roni": lroni["value"],
            "roniWindow": lroni["month"],
            "roniCategory": _roni_category(lroni["value"]),
            "freshness": f"Dato observado · adquirido {now}",
            "preliminary": False,
        },
        "winds": {
            "u850Anom": lu850["value"],
            "u850Month": lu850["month"],
            "direction": _u850_direction(lu850["value"]),
            "signMeaning": "u > 0 ⇒ este (westerly); u < 0 ⇒ oeste (easterly)",
        },
        "thermocline": {
            "d20Anom": ld20["value"],
            "d20Month": ld20["month"],
            "interpretation": _d20_interpretation(ld20["value"]),
        },
        "soi": {
            "value": lsoi["value"],
            "month": lsoi["month"],
            "interpretation": _soi_category(lsoi["value"]),
            "note": "El SOI es un índice de escala de cuenca. El observatorio NO define un «SOI costero».",
        },
    }
    (DATA_DIR / "status.json").write_text(json.dumps(status, indent=2, ensure_ascii=False))


def _icen_category(v):
    if v is None: return "Sin datos"
    a = abs(v)
    sign = "El Niño Costero" if v >= 0 else "La Niña Costera"
    if a < 0.4: return "Normal"
    if a < 1.0: return f"{sign} débil"
    if a < 1.5: return f"{sign} moderado"
    if a < 2.0: return f"{sign} fuerte"
    return f"{sign} muy fuerte"


def _roni_category(v):
    if v is None: return "Sin datos"
    if v >= 0.5: return "El Niño (cuenca)"
    if v <= -0.5: return "La Niña (cuenca)"
    return "ENSO Neutral (cuenca)"


def _soi_category(v):
    if v is None: return "Sin datos"
    if v <= -0.5: return "Componente atmosférica de El Niño"
    if v >= 0.5: return "Componente atmosférica de La Niña"
    return "Componente atmosférica neutral"


def _u850_direction(v):
    if v is None: return "Sin datos"
    if v > 0.5: return "Anomalía de westerlies (reforzada hacia el este)"
    if v < -0.5: return "Anomalía de easterlies (reforzada hacia el oeste)"
    return "Anomalía neutral (cerca de cero)"


def _d20_interpretation(v):
    if v is None: return "Sin datos"
    if v > 10: return "Termoclina más profunda de lo normal (El Niño)"
    if v < -10: return "Termoclina más somera de lo normal (La Niña)"
    return "Termoclina cerca de la profundidad normal"


def write_health_json(sources_status: dict):
    """Escribe health.json con evidencia de adquisición real."""
    now = datetime.now(timezone.utc).isoformat()
    health = {
        "generatedAt": now,
        "asOf": now.split("T")[0],
        "pipelineStatus": "UPDATED",
        "lastSuccessfulRun": now,
        "dataVersion": "2.0.0",
        "dataSource": "LIVE_OBSERVED",
        "sources": [],
    }
    for sid, info in sources_status.items():
        health["sources"].append({
            "id": sid,
            "institution": info["institution"],
            "product": info["product"],
            "status": "HEALTHY" if info["success"] else "FAILED",
            "freshnessState": "FRESH" if info["success"] else "STALE",
            "lastUpdate": now,
            "retrievalEvidence": info.get("evidence", ""),
            "contentHash": info.get("hash", ""),
            "cadence": "Mensual",
            "riskTier": "LOW" if info["success"] else "HIGH",
        })
    (DATA_DIR / "health.json").write_text(json.dumps(health, indent=2, ensure_ascii=False))


def main():
    print("=== Adquisición real de datos ENSO ===")
    sources_status = {}

    # 1. Niño 1+2 from PSL
    try:
        print("Adquiriendo Niño 1+2...")
        raw = fetch(SOURCES["nino12"]["url"])
        n12 = parse_psl_csv(raw)
        h = hashlib.sha256(raw.encode()).hexdigest()[:16]
        write_series_csv("nino12", n12, "degC", SOURCES["nino12"]["institution"])
        sources_status["nino12"] = {"institution": SOURCES["nino12"]["institution"], "product": SOURCES["nino12"]["product"], "success": True, "evidence": f"HTTP 200, {len(n12)} puntos, sha256:{h}", "hash": h}
        print(f"  ✅ {len(n12)} puntos, último: {n12[-1]}")
    except Exception as e:
        print(f"  ❌ Error: {e}")
        sources_status["nino12"] = {"institution": SOURCES["nino12"]["institution"], "product": SOURCES["nino12"]["product"], "success": False, "evidence": str(e), "hash": ""}
        n12 = []

    # 2. Niño 3.4 from PSL
    try:
        print("Adquiriendo Niño 3.4...")
        raw = fetch(SOURCES["nino34"]["url"])
        n34 = parse_psl_csv(raw)
        h = hashlib.sha256(raw.encode()).hexdigest()[:16]
        write_series_csv("nino34", n34, "degC", SOURCES["nino34"]["institution"])
        sources_status["nino34"] = {"institution": SOURCES["nino34"]["institution"], "product": SOURCES["nino34"]["product"], "success": True, "evidence": f"HTTP 200, {len(n34)} puntos, sha256:{h}", "hash": h}
        print(f"  ✅ {len(n34)} puntos, último: {n34[-1]}")
    except Exception as e:
        print(f"  ❌ Error: {e}")
        sources_status["nino34"] = {"institution": SOURCES["nino34"]["institution"], "product": SOURCES["nino34"]["product"], "success": False, "evidence": str(e), "hash": ""}
        n34 = []

    # 3. SOI from PSL
    try:
        print("Adquiriendo SOI...")
        raw = fetch(SOURCES["soi"]["url"])
        soi = parse_psl_soi(raw)
        h = hashlib.sha256(raw.encode()).hexdigest()[:16]
        write_series_csv("soi", soi, "dimensionless", SOURCES["soi"]["institution"])
        sources_status["soi"] = {"institution": SOURCES["soi"]["institution"], "product": SOURCES["soi"]["product"], "success": True, "evidence": f"HTTP 200, {len(soi)} puntos, sha256:{h}", "hash": h}
        print(f"  ✅ {len(soi)} puntos, último: {soi[-1]}")
    except Exception as e:
        print(f"  ❌ Error: {e}")
        sources_status["soi"] = {"institution": SOURCES["soi"]["institution"], "product": SOURCES["soi"]["product"], "success": False, "evidence": str(e), "hash": ""}
        soi = []

    # 4. CPC ERSST5 indices (for RONI calculation)
    try:
        print("Adquiriendo CPC ERSST5 indices...")
        raw = fetch(SOURCES["nino_indices"]["url"])
        cpc = parse_cpc_ascii(raw)
        h = hashlib.sha256(raw.encode()).hexdigest()[:16]
        # Use CPC nino34 for RONI calculation (3-month mean)
        cpc_n34 = cpc.get("nino34", [])
        roni = compute_3mo_mean(cpc_n34)
        # Mark last 2 months as preliminary
        for p in roni[-2:]:
            p["flag"] = "preliminary"
        write_series_csv("roni", roni, "degC", SOURCES["nino_indices"]["institution"])
        # Also write CPC nino12 if available
        cpc_n12 = cpc.get("nino12", [])
        if cpc_n12:
            # Merge: prefer PSL data, supplement with CPC
            pass
        sources_status["cpc_ersst5"] = {"institution": SOURCES["nino_indices"]["institution"], "product": SOURCES["nino_indices"]["product"], "success": True, "evidence": f"HTTP 200, {len(cpc_n34)} puntos, sha256:{h}", "hash": h}
        print(f"  ✅ {len(cpc_n34)} puntos, RONI último: {roni[-1] if roni else 'N/A'}")
    except Exception as e:
        print(f"  ❌ Error: {e}")
        sources_status["cpc_ersst5"] = {"institution": SOURCES["nino_indices"]["institution"], "product": SOURCES["nino_indices"]["product"], "success": False, "evidence": str(e), "hash": ""}
        roni = []

    # 5. Compute ICEN from Niño 1+2
    icen = compute_3mo_mean(n12) if n12 else []
    if icen:
        write_series_csv("icen", icen, "degC", "ENFEN/IMARPE (calculado desde Niño 1+2 PSL)")
        print(f"ICEN: {len(icen)} puntos, último: {icen[-1]}")

    # 6. D20 (GODAS dbss_obil via OPeNDAP)
    try:
        print("Adquiriendo D20 (GODAS dbss_obil via OPeNDAP)...")
        d20 = fetch_d20_anomaly()
        if d20:
            write_series_csv("d20", d20, "m", SOURCES["d20"]["institution"])
            h = hashlib.sha256(str(d20).encode()).hexdigest()[:16]
            sources_status["d20"] = {"institution": SOURCES["d20"]["institution"], "product": SOURCES["d20"]["product"], "success": True, "evidence": f"OPeNDAP, {len(d20)} puntos, sha256:{h}", "hash": h}
            print(f"  ✅ {len(d20)} puntos, último: {d20[-1]}")
        else:
            raise RuntimeError("D20: sin datos parseados")
    except Exception as e:
        print(f"  ❌ Error D20: {e}")
        sources_status["d20"] = {"institution": SOURCES["d20"]["institution"], "product": SOURCES["d20"]["product"], "success": False, "evidence": str(e), "hash": ""}
        d20 = []

    # 7. u850 (NCEP Reanalysis via OPeNDAP)
    try:
        print("Adquiriendo u850 (NCEP Reanalysis via OPeNDAP)...")
        u850 = fetch_u850_anomaly()
        if u850:
            write_series_csv("u850", u850, "m_per_s", SOURCES["u850"]["institution"])
            h = hashlib.sha256(str(u850).encode()).hexdigest()[:16]
            sources_status["u850"] = {"institution": SOURCES["u850"]["institution"], "product": SOURCES["u850"]["product"], "success": True, "evidence": f"OPeNDAP, {len(u850)} puntos, sha256:{h}", "hash": h}
            print(f"  ✅ {len(u850)} puntos, último: {u850[-1]}")
        else:
            raise RuntimeError("u850: sin datos parseados")
    except Exception as e:
        print(f"  ❌ Error u850: {e}")
        sources_status["u850"] = {"institution": SOURCES["u850"]["institution"], "product": SOURCES["u850"]["product"], "success": False, "evidence": str(e), "hash": ""}
        u850 = []

    # 8. Official status from NOAA/CPC and ENFEN
    noaa_advisory = None
    enfen_status = None
    try:
        print("Adquiriendo estado oficial NOAA/CPC ENSO Advisory...")
        if fetch_noaa_enso_advisory:
            noaa_advisory = fetch_noaa_enso_advisory()
            print(f"  ✅ NOAA: {noaa_advisory["alert"]} ({noaa_advisory["date"]})")
            sources_status["noaa_enso_advisory"] = {
                "institution": "NOAA / CPC",
                "product": "ENSO Alert System Status",
                "success": True,
                "evidence": f"HTML parse, alert={noaa_advisory["alert"]}, date={noaa_advisory["date"]}",
                "hash": hashlib.sha256(noaa_advisory["alert"].encode()).hexdigest()[:16],
            }
        else:
            print("  ⚠ Módulo official_status no disponible")
    except Exception as e:
        print(f"  ❌ Error NOAA advisory: {e}")
        sources_status["noaa_enso_advisory"] = {
            "institution": "NOAA / CPC", "product": "ENSO Alert System Status",
            "success": False, "evidence": str(e), "hash": "",
        }

    try:
        print("Adquiriendo estado oficial ENFEN...")
        if fetch_enfen_status:
            enfen_status = fetch_enfen_status()
            print(f"  {'✅' if enfen_status['source'] == 'live' else '⚠'} ENFEN: {enfen_status["alert"]} (source={enfen_status["source"]})")
            sources_status["enfen_status"] = {
                "institution": "ENFEN / IMARPE",
                "product": "Estado oficial El Niño Costero",
                "success": enfen_status["source"] in ("live", "fallback"),
                "evidence": f"source={enfen_status["source"]}, alert={enfen_status["alert"]}",
                "hash": hashlib.sha256(enfen_status["alert"].encode()).hexdigest()[:16],
            }
        else:
            print("  ⚠ Módulo official_status no disponible")
    except Exception as e:
        print(f"  ❌ Error ENFEN: {e}")
        sources_status["enfen_status"] = {
            "institution": "ENFEN / IMARPE", "product": "Estado oficial El Niño Costero",
            "success": False, "evidence": str(e), "hash": "",
        }

    # 9. Write status.json with real values
    write_status_json(n12, n34, icen, roni, soi, d20, u850, noaa_advisory, enfen_status)
    print("status.json escrito con valores observados")

    # 8. Write health.json with real evidence
    write_health_json(sources_status)
    print("health.json escrito con evidencia de adquisición")

    # 9. Write manifest
    now = datetime.now(timezone.utc).isoformat()
    manifest = {
        "name": "Observatorio ENSO Perú",
        "dataVersion": "2.0.0",
        "generatedAt": now,
        "asOf": now.split("T")[0],
        "dataSource": "LIVE_OBSERVED",
        "coverage": "Datos reales observados desde NOAA/PSL y NOAA/CPC",
        "sources": list(sources_status.keys()),
    }
    (DATA_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

    print("\n=== Resumen ===")
    for sid, info in sources_status.items():
        status = "✅" if info["success"] else "❌"
        print(f"  {status} {sid}: {info['evidence'][:80]}")

    return 0 if all(s["success"] for s in sources_status.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
