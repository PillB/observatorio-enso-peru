"""Normalización de coordenadas y verificación de convenciones de signos.

Funciones puras usadas por los fetchers y por la capa de derivados. No
producen efectos secundarios y son deterministas.
"""

from __future__ import annotations

import math
from typing import Iterable

NaN = float("nan")


# ----------------------------------------------------------------------------
# Longitud
# ----------------------------------------------------------------------------
def to_negative(lon: float) -> float:
    """Convierte una longitud 0..360 a -180..180.

    270°E  ⇒  -90° (90°O).
    180°E  ⇒  180° (convención frontera, se mantiene 180).
    90°E   ⇒  90°.
    0°     ⇒  0°.
    """
    if math.isnan(lon):
        return NaN
    lon = lon % 360.0
    if lon > 180.0:
        lon -= 360.0
    # Normaliza -180..180 manteniendo el cero sin signo.
    if lon == 180.0:
        return 180.0
    if lon == -180.0:
        return 180.0  # convención frontera
    return lon


def to_positive(lon: float) -> float:
    """Convierte una longitud -180..180 a 0..360.

    -90° (90°O)  ⇒  270°.
    -180°        ⇒  180°.
    90°E         ⇒  90°.
    0°           ⇒  0°.
    """
    if math.isnan(lon):
        return NaN
    return lon % 360.0


def is_negative_convention(values: Iterable[float]) -> bool:
    """True si la mayoría de valores están en -180..180."""
    cnt_neg = 0
    cnt_total = 0
    for v in values:
        if math.isnan(v):
            continue
        cnt_total += 1
        if -180.0 <= v <= 180.0:
            cnt_neg += 1
    if cnt_total == 0:
        return True
    return cnt_neg / cnt_total > 0.5


# ----------------------------------------------------------------------------
# Tiempo
# ----------------------------------------------------------------------------
def iso_to_fractional_year(iso: str) -> float:
    """``'2026-03'`` → ``2026 + (3-1)/12`` = ``2026.1666…``."""
    y, m = iso.split("-")
    y = int(y)
    m = int(m)
    return y + (m - 1) / 12.0


def month_range(start_iso: str, end_iso: str) -> list[str]:
    """Lista de meses ISO ``YYYY-MM`` entre ``start`` y ``end`` inclusive."""
    sy, sm = (int(x) for x in start_iso.split("-"))
    ey, em = (int(x) for x in end_iso.split("-"))
    out: list[str] = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def next_month(iso: str) -> str:
    """Mes siguiente al dado en formato ISO ``YYYY-MM``."""
    y, m = (int(x) for x in iso.split("-"))
    m += 1
    if m > 12:
        m = 1
        y += 1
    return f"{y:04d}-{m:02d}"


def month_end_iso(iso: str) -> str:
    """Último día del mes ISO, en formato ``YYYY-MM-DD``."""
    y, m = (int(x) for x in iso.split("-"))
    nm = next_month(iso)
    ny, nmm = (int(x) for x in nm.split("-"))
    # El día 1 del mes siguiente menos un día = último día del mes actual.
    import datetime as _dt

    last = _dt.date(ny, nmm, 1) - _dt.timedelta(days=1)
    return last.strftime("%Y-%m-%d")


# ----------------------------------------------------------------------------
# Verificación de signos
# ----------------------------------------------------------------------------
def verify_wind_sign(values: Iterable[float]) -> bool:
    """Verifica que la convención del viento zonal sea consistente.

    No impone un signo particular (la anomalía puede ser de cualquier
    signo), pero verifica que los valores sean numéricos y finitos. La
    convención se documenta en ``IndicatorDef.signConvention``.
    """
    for v in values:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        if not math.isfinite(v):
            return False
    return True


def verify_d20_sign(values: Iterable[float]) -> bool:
    """Verifica que D20 (+ = más profundo) sea numérico y finito."""
    return verify_wind_sign(values)


def wind_direction_label(u_anom: float | None) -> str:
    """Etiqueta de dirección del viento zonal.

    - u > 0.5 ⇒ «componente del oeste (westerly)» (hacia el este).
    - u < -0.5 ⇒ «componente del este (easterly)» (hacia el oeste).
    - |u| ≤ 0.5 ⇒ «zonal débil / neutral».
    """
    if u_anom is None or (isinstance(u_anom, float) and math.isnan(u_anom)):
        return "Sin datos"
    if u_anom > 0.5:
        return "componente del oeste (westerly)"
    if u_anom < -0.5:
        return "componente del este (easterly)"
    return "zonal débil / neutral"


def d20_interpretation(d20_anom: float | None) -> str:
    """Interpreta la anomalía de D20 (+ = más profunda)."""
    if d20_anom is None or (isinstance(d20_anom, float) and math.isnan(d20_anom)):
        return "Sin datos"
    if d20_anom > 5:
        return "Termoclina más profunda (señal de El Niño de cuenca)"
    if d20_anom < -5:
        return "Termoclina más somera (señal de La Niña de cuenca)"
    return "Profundidad de la termoclina cerca de lo normal"


def preserve_nan(values: Iterable[float | None]) -> list[float | None]:
    """Devuelve la lista preservando ``None`` y ``NaN`` (sin rellenar)."""
    out: list[float | None] = []
    for v in values:
        if v is None:
            out.append(None)
        elif isinstance(v, float) and math.isnan(v):
            out.append(None)
        else:
            out.append(float(v))
    return out
