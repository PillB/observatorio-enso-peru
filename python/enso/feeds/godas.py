"""Profundidad de la isoterma de 20 °C (D20) a partir de NCEP GODAS.

Fuente: archivos GRIB1 mensuales de GODAS que NOAA/CPC publica en
``https://ftp.cpc.ncep.noaa.gov/godas/monthly/godas.M.AAAAMM.grb``. Cada
archivo trae la temperatura potencial (POT, en K) en 40 niveles; solo se piden por rango HTTP los niveles de 5 a 303 m, que
contienen la isoterma de 20 °C en todo el Pacífico tropical.

Cálculo (el mismo para el dato actual y para la climatología):

* En cada punto de grilla, D20 es la profundidad donde el perfil cruza
  20 °C por primera vez desde la superficie, interpolando linealmente
  entre niveles. Si el agua ya está por debajo de 20 °C a 5 m (la isoterma
  aflora, frecuente en el afloramiento costero peruano), D20 = 0 m.
* Promedio de área (peso cos(lat)) sobre los puntos de mar de la región.
* Anomalía = D20 regional del mes − media 1991–2020 del mismo mes,
  calculada con este mismo código (``python/tools/godas_d20_climatology.py``).

GODAS da temperatura potencial; en los primeros 300 m difiere de la
temperatura in situ en menos de 0,05 °C, lo que mueve D20 en menos de 1 m.

El decodificador GRIB1 es mínimo y sin dependencias: solo cubre la
grilla latitud/longitud con empaquetado simple y mapa de bits que usa
GODAS. Cualquier otra cosa lanza ``FormatChanged``.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import FormatChanged, Parsed, check_series, fingerprint

BASE = "https://ftp.cpc.ncep.noaa.gov/godas/monthly"
DOCS = "https://www.cpc.ncep.noaa.gov/products/GODAS/"
MAX_DEPTH = 303  # último nivel pedido (m)
ISOTHERM = 20.0

#: Regiones de la señal GRD. Longitudes en grados este (0–360).
REGIONS = {
    "d20_nino12": {"label": "Niño 1+2 (0°–10°S, 90°O–80°O)", "lat": (-10.0, 0.0), "lon": (270.0, 280.0)},
    "d20_nino34": {"label": "Niño 3.4 (5°N–5°S, 170°O–120°O)", "lat": (-5.0, 5.0), "lon": (190.0, 240.0)},
    # Franja del índice de temperatura subsuperficial de CPC (180°–100°O), como referencia.
    "d20_180w100w": {"label": "Pacífico ecuatorial (5°N–5°S, 180°–100°O)", "lat": (-5.0, 5.0), "lon": (180.0, 260.0)},
}


def url(year: int, month: int) -> str:
    return f"{BASE}/godas.M.{year:04d}{month:02d}.grb"


# ---------------------------------------------------------------------------
# Registros POT del archivo (sin depender del índice .inv: CPC responde 403
# a algunos .inv, p. ej. los de 2024-09 y 2024-10, aunque el .grb está)
# ---------------------------------------------------------------------------
POT_PARAM = 13  # tabla de parámetros NCEP del archivo: temperatura potencial (K)
DEPTH_LEVEL = 160  # tipo de nivel GRIB1: profundidad bajo el nivel del mar (m)
#: Bytes que se piden de cada archivo: los 26 primeros registros (POT de 5 a 303 m) ocupan ≈5,7 MB.
RANGE_BYTES = 6_500_000


def pot_records(raw: bytes, max_depth: int = MAX_DEPTH) -> list[tuple[int, bytes]]:
    """[(profundidad, mensaje)] de temperatura potencial hasta ``max_depth`` m, leyendo los mensajes
    GRIB1 consecutivos del comienzo del archivo (basta un pedido parcial por rango)."""
    out: list[tuple[int, bytes]] = []
    pos = 0
    while pos + 8 <= len(raw):
        if raw[pos:pos + 4] != b"GRIB":
            raise FormatChanged(f"godas: no hay un mensaje GRIB en el byte {pos}")
        n = _u(raw[pos + 4:pos + 7])
        if raw[pos + 7] != 1:
            raise FormatChanged("godas: el archivo no es GRIB edición 1")
        if pos + n > len(raw):
            break  # mensaje cortado por el rango pedido
        msg = raw[pos:pos + n]
        param, ltype, level = msg[16], msg[17], _u(msg[18:20])
        if param == POT_PARAM and ltype == DEPTH_LEVEL:
            if level > max_depth:
                break
            out.append((level, msg))
        elif out:
            break
        pos += n
    depths = [d for d, _ in out]
    if len(out) < 20 or depths[0] > 10 or depths[-1] < 250 or depths != sorted(depths):
        raise FormatChanged(f"godas: niveles POT inesperados ({depths})")
    return out


# ---------------------------------------------------------------------------
# GRIB1 mínimo
# ---------------------------------------------------------------------------
def _u(b: bytes) -> int:
    return int.from_bytes(b, "big")


def _s(b: bytes) -> int:
    v = _u(b)
    sign = 1 << (8 * len(b) - 1)
    return -(v & (sign - 1)) if v & sign else v


def _ibm(b: bytes) -> float:
    sign = -1.0 if b[0] & 0x80 else 1.0
    exp = (b[0] & 0x7F) - 64
    mant = _u(b[1:4])
    return sign * mant * 16.0 ** (exp - 6)


@dataclass
class Field:
    ni: int
    nj: int
    lat1: float
    lon1: float
    lat2: float
    lon2: float
    values: dict  # índice lineal (j*ni + i) → valor, solo los puntos pedidos

    def lat(self, j: int) -> float:
        return self.lat1 + (self.lat2 - self.lat1) * j / (self.nj - 1)

    def lon(self, i: int) -> float:
        return self.lon1 + (self.lon2 - self.lon1) * i / (self.ni - 1)


def grid_of(msg: bytes) -> tuple[int, int, float, float, float, float]:
    f = decode(msg, want=())
    return f.ni, f.nj, f.lat1, f.lon1, f.lat2, f.lon2


def decode(msg: bytes, want) -> Field:
    """Decodifica un mensaje GRIB1 y devuelve solo los puntos ``want`` (índices lineales)."""
    if msg[:4] != b"GRIB" or msg[7] != 1:
        raise FormatChanged("godas: el registro no es GRIB edición 1")
    pos = 8
    pds_len = _u(msg[pos:pos + 3])
    pds = msg[pos:pos + pds_len]
    flags = pds[7]
    has_gds, has_bms = bool(flags & 0x80), bool(flags & 0x40)
    dscale = _s(pds[26:28])
    pos += pds_len
    if not has_gds:
        raise FormatChanged("godas: registro sin GDS")
    gds_len = _u(msg[pos:pos + 3])
    gds = msg[pos:pos + gds_len]
    if gds[5] != 0:
        raise FormatChanged(f"godas: tipo de grilla {gds[5]} no soportado")
    ni, nj = _u(gds[6:8]), _u(gds[8:10])
    lat1, lon1 = _s(gds[10:13]) / 1000, _s(gds[13:16]) / 1000
    lat2, lon2 = _s(gds[17:20]) / 1000, _s(gds[20:23]) / 1000
    if gds[27] & 0x20:
        raise FormatChanged("godas: orden de barrido por columnas no soportado")
    pos += gds_len
    bitmap = None
    if has_bms:
        bms_len = _u(msg[pos:pos + 3])
        if _u(msg[pos + 4:pos + 6]) != 0:
            raise FormatChanged("godas: mapa de bits predefinido no soportado")
        bitmap = msg[pos + 6:pos + bms_len]
        pos += bms_len
    bds_len = _u(msg[pos:pos + 3])
    bds = msg[pos:pos + bds_len]
    if bds[3] & 0xF0:
        raise FormatChanged("godas: empaquetado distinto del simple")
    escale = _s(bds[4:6])
    ref = _ibm(bds[6:10])
    nbits = bds[10]
    data = bds[11:]
    values = {}
    if want:
        want = sorted(set(want))
        # Posición de cada punto en el arreglo empaquetado: puntos con bit 1 antes de él.
        if bitmap is not None:
            ranks, count, last = {}, 0, 0
            for k in want:
                # popcount incremental del mapa de bits entre «last» y «k».
                count += _popcount(bitmap, last, k)
                last = k
                if bitmap[k >> 3] & (0x80 >> (k & 7)):
                    ranks[k] = count
        else:
            ranks = {k: k for k in want}
        fe, fd = 2.0 ** escale, 10.0 ** dscale
        for k, r in ranks.items():
            if nbits == 0:
                x = 0
            else:
                bit = r * nbits
                byte, off = bit >> 3, bit & 7
                chunk = _u(data[byte:byte + (off + nbits + 7) // 8])
                x = (chunk >> ((off + nbits + 7) // 8 * 8 - off - nbits)) & ((1 << nbits) - 1)
            values[k] = (ref + x * fe) / fd
    return Field(ni, nj, lat1, lon1, lat2, lon2, values)


def _popcount(bitmap: bytes, a: int, b: int) -> int:
    """Bits en 1 del mapa en el intervalo [a, b)."""
    n = 0
    while a < b and a & 7:
        n += (bitmap[a >> 3] >> (7 - (a & 7))) & 1
        a += 1
    while a + 8 <= b:
        n += bin(bitmap[a >> 3]).count("1")
        a += 8
    while a < b:
        n += (bitmap[a >> 3] >> (7 - (a & 7))) & 1
        a += 1
    return n


# ---------------------------------------------------------------------------
# D20
# ---------------------------------------------------------------------------
def d20_profile(depths: list[float], temps: list[float], iso: float = ISOTHERM) -> Optional[float]:
    """Profundidad del primer cruce de ``iso`` °C desde la superficie (m).

    0 si el primer nivel ya está por debajo; ``None`` si todo el perfil
    pedido está por encima (no ocurre en el Pacífico tropical hasta 303 m)."""
    if not temps:
        return None
    if temps[0] < iso:
        return 0.0
    for k in range(1, len(temps)):
        if temps[k] < iso:
            z0, z1, t0, t1 = depths[k - 1], depths[k], temps[k - 1], temps[k]
            return z0 + (t0 - iso) * (z1 - z0) / (t0 - t1)
    return None


def region_points(grid: tuple, lat: tuple, lon: tuple) -> list[tuple[int, float]]:
    """Índices lineales de la grilla dentro de la caja y su peso cos(lat)."""
    ni, nj, lat1, lon1, lat2, lon2 = grid
    out = []
    for j in range(nj):
        la = lat1 + (lat2 - lat1) * j / (nj - 1)
        if not (lat[0] <= la <= lat[1]):
            continue
        for i in range(ni):
            lo = (lon1 + (lon2 - lon1) * i / (ni - 1)) % 360
            if lon[0] <= lo <= lon[1]:
                out.append((j * ni + i, math.cos(math.radians(la))))
    return out


def regional_d20(records: list[tuple[int, bytes]], regions: dict = REGIONS) -> dict:
    """``records``: [(profundidad, mensaje GRIB POT)] ordenados por profundidad.

    Devuelve ``{clave: {"d20": m, "points": n, "outcrop": fracción}}``."""
    if not records:
        raise FormatChanged("godas: sin registros POT")
    grid = grid_of(records[0][1])
    pts = {k: region_points(grid, r["lat"], r["lon"]) for k, r in regions.items()}
    want = sorted({p for v in pts.values() for p, _ in v})
    depths = [float(d) for d, _ in records]
    fields = []
    for _, msg in records:
        f = decode(msg, want)
        if (f.ni, f.nj, f.lat1, f.lon1, f.lat2, f.lon2) != grid:
            raise FormatChanged("godas: la grilla cambia entre niveles")
        fields.append(f.values)
    out = {}
    for key, plist in pts.items():
        tot = wsum = 0.0
        n = outcrop = 0
        for p, w in plist:
            if p not in fields[0]:
                continue  # tierra
            prof = []
            for fv in fields:
                if p not in fv:
                    break
                prof.append(fv[p] - 273.15)
            d = d20_profile(depths[:len(prof)], prof)
            if d is None:
                continue
            n += 1
            outcrop += d == 0.0
            tot += d * w
            wsum += w
        if not n:
            raise FormatChanged(f"godas: sin puntos de mar con D20 en {key}")
        out[key] = {"d20": round(tot / wsum, 2), "points": n, "outcrop": round(outcrop / n, 3)}
    return out


# ---------------------------------------------------------------------------
# Serie publicada: histórico versionado + meses leídos en la corrida
# ---------------------------------------------------------------------------
HISTORY_PATH = Path(__file__).resolve().parents[1] / "data" / "godas-d20.json"
#: Meses posteriores al histórico versionado que una corrida intenta leer como máximo.
MAX_LIVE_MONTHS = 24


def load_history(path: Path = HISTORY_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def months_to_fetch(history: dict, today, max_months: int = MAX_LIVE_MONTHS) -> list[tuple[int, int]]:
    """Meses posteriores al último del histórico, hasta el mes en curso (los que aún no existen dan 404).
    Siempre incluye el último mes del histórico, por si CPC lo reemplazó."""
    last = max(p["period"] for pts in history["monthly"].values() for p in pts)
    y, m = int(last[:4]), int(last[5:])
    out = []
    while (y, m) <= (today.year, today.month) and len(out) < max_months:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def build_series(live: dict, history: dict) -> Parsed:
    """Une el histórico con los meses leídos y calcula la anomalía respecto de la climatología 1991–2020.

    ``live``: ``{"months": {"AAAA-MM": {clave: {"d20", "points", "outcrop"}}}, ...}``. Devuelve
    ``data = {clave: [{period, value (anomalía, m), d20 (m), outcrop}]}``."""
    clim = history["climatology"]
    data, warnings = {}, []
    for key in REGIONS:
        if key not in clim or len(clim[key]) != 12:
            raise FormatChanged(f"godas: climatología de {key} incompleta")
        by = {p["period"]: {"d20": p["d20"], "outcrop": p.get("outcrop", 0.0)}
              for p in history["monthly"].get(key, [])}
        for per, res in (live.get("months") or {}).items():
            if key in res:
                by[per] = {"d20": res[key]["d20"], "outcrop": res[key].get("outcrop", 0.0)}
        pts = []
        for per in sorted(by):
            d = by[per]["d20"]
            if d is None or not 0 <= d <= MAX_DEPTH:
                warnings.append(f"{key}: D20 implausible descartado {per}={d}")
                continue
            pts.append({"period": per, "value": round(d - clim[key][int(per[5:]) - 1], 1),
                        "d20": round(d, 1), "outcrop": by[per]["outcrop"]})
        warnings += check_series(pts, lo=-150, hi=150, name=key)
        data[key] = pts
    meta = {"climatology": history.get("base_period", ""), "liveMonths": sorted(live.get("months") or {}),
            "errors": live.get("errors") or {}}
    return Parsed(data, fingerprint("godas-d20", *sorted(REGIONS), str(MAX_DEPTH)), warnings, meta)
