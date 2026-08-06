"""Cálculos derivados — espejo de ``src/lib/enso/derived.ts``.

ICEN, RONI, categorías, dirección del viento, interpretación de D20 y
percentiles. Funciones puras y deterministas.
"""

from __future__ import annotations

import math
from typing import Optional

from .models import IndicatorDef, MonthlyPoint, Series, SeriesFlag
from .methodology import INDICATOR_BY_ID


# ----------------------------------------------------------------------------
# Media móvil de 3 meses (sin rellenar huecos)
# ----------------------------------------------------------------------------
def rolling_mean_3(points: list[MonthlyPoint]) -> list[MonthlyPoint]:
    """Media móvil de 3 meses centrada en el mes actual (m-2, m-1, m).

    Si la ventana no tiene los 3 valores, el resultado es ``None`` (los
    huecos se preservan, no se rellenan).
    """
    out: list[MonthlyPoint] = []
    for i, p in enumerate(points):
        window = points[max(0, i - 2) : i + 1]
        vals = [w.value for w in window if w.value is not None]
        if len(vals) == 3:
            mean = round(sum(vals) / 3.0, 2)
            out.append(MonthlyPoint(month=p.month, value=mean, flag=p.flag))
        else:
            out.append(MonthlyPoint(month=p.month, value=None, flag=p.flag))
    return out


# ----------------------------------------------------------------------------
# Categorías
# ----------------------------------------------------------------------------
def icen_category(icen: Optional[float]) -> str:
    """Categoría de intensidad del ICEN según umbrales ENFEN."""
    if icen is None or (isinstance(icen, float) and math.isnan(icen)):
        return "Sin datos"
    a = abs(icen)
    sign = "El Niño Costero" if icen >= 0 else "La Niña Costera"
    if a < 0.4:
        return "Normal"
    if a < 1.0:
        return f"{sign} débil"
    if a < 1.5:
        return f"{sign} moderado"
    if a < 2.0:
        return f"{sign} fuerte"
    return f"{sign} muy fuerte"


def roni_category(roni: Optional[float]) -> str:
    """Categoría del RONI (umbral operativo ±0.5 °C)."""
    if roni is None or (isinstance(roni, float) and math.isnan(roni)):
        return "Sin datos"
    if roni >= 0.5:
        return "El Niño (cuenca)"
    if roni <= -0.5:
        return "La Niña (cuenca)"
    return "ENSO Neutral (cuenca)"


def soi_category(soi: Optional[float]) -> str:
    """Categoría del SOI (componente atmosférica)."""
    if soi is None or (isinstance(soi, float) and math.isnan(soi)):
        return "Sin datos"
    if soi <= -0.5:
        return "Componente atmosférica de El Niño"
    if soi >= 0.5:
        return "Componente atmosférica de La Niña"
    return "Componente atmosférica neutral"


def u850_direction(u_anom: Optional[float]) -> dict[str, str]:
    """Etiqueta de dirección del viento zonal a 850 hPa.

    u > 0 ⇒ flujo hacia el este (componente del oeste / westerly).
    """
    if u_anom is None or (isinstance(u_anom, float) and math.isnan(u_anom)):
        return {"label": "Sin datos", "signMeaning": ""}
    if u_anom > 0.5:
        return {
            "label": "Anomalía del oeste (flujo hacia el este)",
            "signMeaning": (
                "u > 0 ⇒ componente del oeste (westerly), hacia el este. "
                "Típico de El Niño de cuenca."
            ),
        }
    if u_anom < -0.5:
        return {
            "label": "Anomalía del este (flujo hacia el oeste)",
            "signMeaning": (
                "u < 0 ⇒ componente del este (easterly), hacia el oeste. "
                "Típico de La Niña de cuenca."
            ),
        }
    return {
        "label": "Anomalía zonal débil / neutral",
        "signMeaning": "u ≈ 0 ⇒ sin anomalía zonal significativa.",
    }


def d20_interpretation(d20: Optional[float]) -> str:
    """Interpreta la anomalía de D20 (+ = más profunda)."""
    if d20 is None or (isinstance(d20, float) and math.isnan(d20)):
        return "Sin datos"
    if d20 > 5:
        return "Termoclina más profunda de lo normal (señal de El Niño de cuenca)"
    if d20 < -5:
        return "Termoclina más somera de lo normal (señal de La Niña de cuenca)"
    return "Profundidad de la termoclina cerca de lo normal"


# ----------------------------------------------------------------------------
# Percentiles
# ----------------------------------------------------------------------------
def percentile(series: Series, value: Optional[float]) -> Optional[int]:
    """Percentil (0..100) de ``value`` en la historia de ``series``.

    Método: proporción de valores estrictamente menores que ``value``.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    vals = sorted(
        p.value for p in series.points if p.value is not None and not math.isnan(p.value)
    )
    if not vals:
        return None
    below = sum(1 for v in vals if v < value)
    return round(below / len(vals) * 100)


# ----------------------------------------------------------------------------
# Clasificación por umbrales declarados
# ----------------------------------------------------------------------------
def classify_by_thresholds(
    ind: IndicatorDef, value: Optional[float]
) -> Optional[str]:
    """Clasifica ``value`` según los umbrales declarados del indicador."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if not ind.thresholds:
        return None
    for t in ind.thresholds:
        if t.min <= value < t.max:
            return t.classification
    # Caso de frontera superior exacta.
    for t in ind.thresholds:
        if value == t.max and t.max == float("inf"):
            return t.classification
    return None


# ----------------------------------------------------------------------------
# Estado consolidado
# ----------------------------------------------------------------------------
def latest_point(points: list[MonthlyPoint]) -> Optional[tuple[MonthlyPoint, int]]:
    """Último punto no nulo de una serie (point, index)."""
    for i in range(len(points) - 1, -1, -1):
        if points[i].value is not None:
            return points[i], i
    return None


def value_at(series: Series, month_iso: str) -> Optional[float]:
    """Valor de la serie en un mes ISO, o ``None``."""
    for p in series.points:
        if p.month == month_iso:
            return p.value
    return None


def window3_label(last_month_iso: str) -> str:
    """Etiqueta de la ventana móvil de 3 meses (p. ej. ``'May–Jun–Jul 2026'``)."""
    y, m = (int(x) for x in last_month_iso.split("-"))
    idx = (y - 1990) * 12 + (m - 1)
    months = [
        "Ene", "Feb", "Mar", "Abr", "May", "Jun",
        "Jul", "Ago", "Sep", "Oct", "Nov", "Dic",
    ]
    labels: list[str] = []
    for k in (2, 1, 0):
        i = idx - k
        yy = 1990 + i // 12
        mm = i % 12
        labels.append(f"{months[mm]} {yy}")
    return "–".join(labels)
