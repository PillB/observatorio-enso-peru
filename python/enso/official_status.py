"""Scrapers para el estado oficial de ENSO desde ENFEN y NOAA/CPC.

Fuentes:
  - **NOAA/CPC ENSO Diagnostic Discussion**:
    https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml
    Contiene la línea "Alert System Status: El Niño Advisory" (o La Niña
    Advisory / Final / Watch / ENSO-Neutral).

  - **ENFEN SIOFEN** (https://siofen.imarpe.gob.pe/):
    El panel de ICEN publica el estado oficial de El Niño Costero.
    Nota: el sitio está protegido por Cloudflare y puede bloquear
    peticiones automatizadas. En ese caso, se usa un archivo local
    ``config/enfen-status.json`` como fallback manual.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore

import html as html_mod


# ----------------------------------------------------------------------------
# NOAA/CPC ENSO Alert System Status
# ----------------------------------------------------------------------------
NOAA_ENSO_DISC_URL = (
    "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/"
    "enso_advisory/ensodisc.shtml"
)

#: Mapeo de los tipos de alerta ENSO de NOAA/CPC a etiquetas normalizadas.
NOAA_ALERT_PATTERNS = [
    ("Final El Niño Advisory", "Final El Niño Advisory"),
    ("Final La Niña Advisory", "Final La Niña Advisory"),
    ("El Niño Advisory", "El Niño Advisory"),
    ("La Niña Advisory", "La Niña Advisory"),
    ("El Niño Watch", "El Niño Watch"),
    ("La Niña Watch", "La Niña Watch"),
    ("ENSO-Neutral", "ENSO-Neutral"),
    ("ENSO Neutral", "ENSO-Neutral"),
]


def fetch_noaa_enso_advisory() -> dict:
    """Descarga y parsea el ENSO Diagnostic Discussion de NOAA/CPC.

    Devuelve un dict con:
      - ``alert``: str — el tipo de alerta (ej. "El Niño Advisory").
      - ``date``: str — fecha de publicación (ej. "9 July 2026").
      - ``synopsis``: str — texto del synopsis.
      - ``url``: str — URL fuente.
      - ``fetched_at``: str — timestamp ISO-8601 UTC.

    Lanza ``RuntimeError`` si no se puede parsear la alerta.
    """
    if httpx is None:
        raise RuntimeError("httpx no disponible")
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        resp = client.get(
            NOAA_ENSO_DISC_URL,
            headers={"User-Agent": "Observatorio-ENSO-Peru/2.0 (pipeline; +https://github.com/)"},
        )
        resp.raise_for_status()
        html = resp.text

    # Decodifica entidades HTML.
    text = html_mod.unescape(re.sub(r"<[^>]+>", " ", html))
    text = re.sub(r"\s+", " ", text).strip()

    # Busca "Alert System Status: <alerta>"
    alert: Optional[str] = None
    m = re.search(r"Alert System Status:\s*(.+?)(?:Synopsis|$)", text, re.IGNORECASE | re.DOTALL)
    if m:
        raw_alert = m.group(1).strip().rstrip(";&").strip()
        # Normaliza contra patrones conocidos.
        for pattern, label in NOAA_ALERT_PATTERNS:
            if pattern.lower() in raw_alert.lower():
                alert = label
                break
        if not alert:
            alert = raw_alert[:60]

    # Busca la fecha (formato "9 July 2026" o "July 9, 2026").
    date_str: Optional[str] = None
    m = re.search(r"\b(\d{1,2}\s+\w+\s+202\d)\b", text[:2000])
    if m:
        date_str = m.group(1)
    else:
        m = re.search(r"\b(\w+\s+\d{1,2},\s+202\d)\b", text[:2000])
        if m:
            date_str = m.group(1)

    # Busca el synopsis.
    synopsis: Optional[str] = None
    m = re.search(r"Synopsis:\s*(.+?)(?:\[\d+\]|Climate Prediction Center|$)", text, re.IGNORECASE | re.DOTALL)
    if m:
        synopsis = m.group(1).strip()[:500]

    if not alert:
        raise RuntimeError("No se pudo parsear el Alert System Status desde NOAA/CPC")

    return {
        "alert": alert,
        "date": date_str or "",
        "synopsis": synopsis or "",
        "url": NOAA_ENSO_DISC_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


# ----------------------------------------------------------------------------
# ENFEN SIOFEN — estado oficial de El Niño Costero
# ----------------------------------------------------------------------------
ENFEN_ICEN_URL = "https://siofen.imarpe.gob.pe/nivel2/indice-costero-el-nino-icen"

#: Patrones de alerta ENFEN en orden de precedencia.
ENFEN_ALERT_PATTERNS = [
    (r"Alerta de El Ni[ñn]o Costero", "Alerta de El Niño Costero"),
    (r"Vigilancia de El Ni[ñn]o Costero", "Vigilancia de El Niño Costero"),
    (r"Alerta de La Ni[ñn]a Costero", "Alerta de La Niña Costera"),
    (r"Vigilancia de La Ni[ñn]a Costero", "Vigilancia de La Niña Costera"),
    (r"Condici[óo]n Normal", "Condición Normal"),
    (r"Normal", "Condición Normal"),
]

#: Ruta al archivo de fallback manual para ENFEN.
ENFEN_FALLBACK_PATH = Path(__file__).resolve().parents[2] / "config" / "enfen-status.json"


def fetch_enfen_status() -> dict:
    """Intenta descargar el estado oficial de ENFEN desde SIOFEN.

    Si Cloudflare bloquea la petición, cae al archivo manual
    ``config/enfen-status.json``.

    Devuelve un dict con:
      - ``alert``: str — el estado de alerta (ej. "Alerta de El Niño Costero").
      - ``icen``: float | None — valor ICEN si se puede extraer.
      - ``month``: str | None — mes de referencia.
      - ``url``: str — URL fuente.
      - ``source``: "live" | "fallback" — origen del dato.
      - ``fetched_at``: str — timestamp ISO-8601 UTC.
    """
    # Intenta la descarga live.
    try:
        if httpx is None:
            raise RuntimeError("httpx no disponible")
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(
                ENFEN_ICEN_URL,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; Observatorio-ENSO-Peru/2.0)",
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "es-PE,es;q=0.9",
                },
            )
        # Si Cloudflare bloquea (403 o página de challenge), cae al fallback.
        if resp.status_code == 403 or "cf-challenge" in resp.text.lower() or "cloudflare" in resp.text.lower():
            return _load_enfen_fallback()
        resp.raise_for_status()
        html = resp.text
        text = html_mod.unescape(re.sub(r"<[^>]+>", " ", html))
        text = re.sub(r"\s+", " ", text).strip()

        # Busca el estado de alerta.
        alert = "Sin datos"
        for pattern, label in ENFEN_ALERT_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                alert = label
                break

        # Busca el valor ICEN.
        icen_value: Optional[float] = None
        m = re.search(r"ICEN[^0-9-+]*(-?\d+\.\d+)", text, re.IGNORECASE)
        if m:
            try:
                icen_value = round(float(m.group(1)), 2)
            except ValueError:
                pass

        # Busca el mes de referencia.
        month: Optional[str] = None
        m = re.search(r"\b(19\d{2}|20\d{2})-(0[1-9]|1[0-2])\b", text)
        if m:
            month = f"{m.group(1)}-{m.group(2)}"

        # Si no se encontró nada útil, cae al fallback.
        if alert == "Sin datos" and icen_value is None:
            return _load_enfen_fallback()

        return {
            "alert": alert,
            "icen": icen_value,
            "month": month,
            "url": ENFEN_ICEN_URL,
            "source": "live",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return _load_enfen_fallback()


def _load_enfen_fallback() -> dict:
    """Carga el estado de ENFEN desde el archivo de fallback manual."""
    if ENFEN_FALLBACK_PATH.exists():
        try:
            data = json.loads(ENFEN_FALLBACK_PATH.read_text(encoding="utf-8"))
            data["source"] = "fallback"
            data["url"] = ENFEN_ICEN_URL
            data["fetched_at"] = datetime.now(timezone.utc).isoformat()
            return data
        except (json.JSONDecodeError, OSError):
            pass
    # Si no hay fallback, devuelve "Consulte ENFEN".
    return {
        "alert": "Consulte ENFEN en siofen.imarpe.gob.pe",
        "icen": None,
        "month": None,
        "url": ENFEN_ICEN_URL,
        "source": "unavailable",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
