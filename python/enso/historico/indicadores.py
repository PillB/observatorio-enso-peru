"""Indicadores de recurrencia y riesgo por área a partir del catálogo histórico.

Definiciones (``docs/memoria-desastres.md`` las explica con ejemplos). Con T = años hidrológicos
(julio–junio) del periodo de cobertura homogénea y Y = años con al menos un registro en el área:

* **Frecuencia anual** p = Y/T, con intervalo de Wilson al 95 % (válido con muestras pequeñas).
  Se cuentan años con evento y no registros, porque un mismo Niño deja decenas de fichas en un
  distrito.
* **Periodo de retorno empírico** T/Y: «en promedio, un año con daños cada X años». Es frecuencia
  histórica, no pronóstico: supone clima y exposición constantes.
* **Probabilidad en los próximos 5 años** 1 − (1 − p)^5, con la misma salvedad.
* **Distrito-años con daños** DA: pares distintos (lugar, año hidrológico) con registros. En un distrito es
  Y; en una provincia o un departamento mide cuántos de sus distritos sufren daños cada año (la
  frecuencia anual de un departamento grande es casi siempre 1 y no distingue nada).
* **Razón de tasas en El Niño** RR = (DA_niño/T_niño) / (DA_otros/T_otros): cuántas veces más daños por
  año hay cuando hay Niño costero en la temporada de lluvias (diciembre–abril) que en los demás años.
  Intervalo al 95 % de Poisson (logarítmico). Sin registros en uno de los dos grupos, no se calcula.
* **Grandes Niños**: cuáles de los eventos históricos (``enso.GREAT``) dejaron registros en el área.
* **Impactos**: sumas de lo que las fuentes reportan (vacío ≠ cero).
* **Fuente homogénea**: frecuencia, periodo de retorno, distrito-años y razón de tasas se calculan solo con
  los registros de la fuente sistemática del periodo de cobertura (``homogeneous``: DesInventar). Las
  demás fuentes (SINPAD 2016-18, IDMC, curados) suman registros, impactos y grandes Niños, pero no
  cambian la frecuencia: tienen otra densidad y la mezclarían.
* **Muestra pequeña**: Y < 5: el sitio muestra la cifra, pero marcada y sin calificarla.
* **Nivel de atención** (solo distritos y provincias; regla transparente, no es un índice oficial de
  riesgo): muy alto = golpeado en ≥ 2 grandes Niños y p ≥ 0,25; alto = una de las dos condiciones;
  medio = 1 gran Niño o p ≥ 0,10; bajo = otros con registros.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Iterable, Optional

from .enso import GREAT

Z = 1.959964
INTENSIVE_DEATHS, INTENSIVE_HOUSES = 30, 600  # UNDRR, GAR 2015: umbral de riesgo intensivo


def wilson(y: int, t: int) -> tuple[Optional[float], Optional[float]]:
    if t <= 0:
        return None, None
    p = y / t
    den = 1 + Z * Z / t
    centre = (p + Z * Z / (2 * t)) / den
    half = Z * math.sqrt(p * (1 - p) / t + Z * Z / (4 * t * t)) / den
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


def rate_ratio(a: int, t1: int, b: int, t0: int) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Razón de tasas de Poisson (a/t1)/(b/t0) con IC 95 % logarítmico; None si un grupo no tiene casos."""
    if not (a and b and t1 and t0):
        return None, None, None
    rr = (a / t1) / (b / t0)
    se = math.sqrt(1 / a + 1 / b)
    return round(rr, 3), round(rr * math.exp(-Z * se), 3), round(rr * math.exp(Z * se), 3)


def hydro_start(r: dict) -> Optional[int]:
    h = r.get("AnioHidrologico") or ""
    return int(h[:4]) if h[:4].isdigit() else None


def level_of(r: dict) -> int:
    return len(r["Ubigeo"])


def area_codes(r: dict, territory=None) -> list[tuple[str, str]]:
    """(nivel, código) de todas las áreas a las que cuenta un registro: un registro distrital cuenta para
    su distrito, su provincia, su departamento y su macrorregión; uno departamental, solo para los dos
    últimos."""
    code = r["Ubigeo"]
    out = [("departamento", code[:2])]
    if len(code) >= 4:
        out.append(("provincia", code[:4]))
    if len(code) == 6:
        out.append(("distrito", code))
    if r.get("Region"):
        out.append(("region", r["Region"]))
    out.append(("pais", "PE"))
    return out


def _num(v) -> float:
    try:
        return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def summarize(records: Iterable[dict], years: range, nino_years: set[int], with_level: bool = True,
              homogeneous: Optional[set[str]] = None) -> dict:
    """Indicadores de un conjunto de registros de una misma área (ya filtrados)."""
    recs = list(records)
    hom = [r for r in recs if homogeneous is None or r.get("Origen") in homogeneous]
    T = len(years)
    tn = sum(1 for y in years if y in nino_years)
    to = T - tn
    ys = {hydro_start(r) for r in hom} - {None}
    ys_in = {y for y in ys if y in years}
    Y = len(ys_in)
    da = {(r["Ubigeo"], hydro_start(r)) for r in hom if hydro_start(r) in years}
    dn = sum(1 for _, y in da if y in nino_years)
    do = len(da) - dn
    p = Y / T if T else None
    lo, hi = wilson(Y, T)
    rr, rr_lo, rr_hi = rate_ratio(dn, tn, do, to)
    great = [g for g in GREAT if any(r.get("TipoEvento") == g for r in recs)]
    imp = defaultdict(float)
    intensive = 0
    for r in recs:
        if r.get("ImpactoEnTotales", "si") != "si":
            continue
        for k in ("Fallecidos", "Desaparecidos", "Afectados", "Damnificados", "Desplazados", "ViviendasDestruidas",
                  "ViviendasAfectadas", "HectareasCultivo", "KmVias"):
            imp[k] += _num(r.get(k))
        if _num(r.get("Fallecidos")) >= INTENSIVE_DEATHS or _num(r.get("ViviendasDestruidas")) >= INTENSIVE_HOUSES:
            intensive += 1
    hazards = Counter(r["DangerType"] for r in recs)
    last = max(recs, key=lambda r: r["Date"]) if recs else None
    decades = Counter(f"{int(r['Anio']) // 10 * 10}s" for r in recs)
    big = len(great)
    level = ""
    if recs and with_level:
        hi_freq = p is not None and p >= 0.25
        level = ("muy alto" if big >= 2 and hi_freq else "alto" if big >= 2 or hi_freq
                 else "medio" if big == 1 or (p or 0) >= 0.10 else "bajo")
    return {
        "registros": len(recs), "aniosConEvento": Y, "aniosCobertura": T,
        "frecuenciaAnual": round(p, 4) if p is not None else None, "frecuenciaIC": [lo, hi],
        "periodoRetorno": round(T / Y, 1) if Y else None,
        "prob5Anios": round(1 - (1 - p) ** 5, 4) if p is not None else None,
        "distritoAnios": len(da), "distritoAniosPorAnio": round(len(da) / T, 2) if T else None,
        "razonNino": rr, "razonNinoIC": [rr_lo, rr_hi], "distritoAniosNino": [dn, tn], "distritoAniosOtros": [do, to],
        "grandesNinos": great, "muestraPequena": Y < 5,
        "impactos": {k: round(v) for k, v in imp.items()}, "registrosIntensivos": intensive,
        "peligros": hazards.most_common(), "decadas": dict(sorted(decades.items())),
        "ultimo": {"Date": last["Date"], "DangerType": last["DangerType"], "TipoEvento": last["TipoEvento"]} if last else None,
        "nivelAtencion": level,
    }


def by_area(records: list[dict], years: range, nino_years: set[int],
            homogeneous: Optional[set[str]] = None) -> dict[str, dict[str, dict]]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in records:
        for lvl, code in area_codes(r):
            groups[(lvl, code)].append(r)
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for (lvl, code), rs in groups.items():
        out[lvl][code] = summarize(rs, years, nino_years, with_level=lvl in ("distrito", "provincia"),
                                   homogeneous=homogeneous)
    return out


def nino_hydro_years(calendar, years: range) -> set[int]:
    """Años hidrológicos (por su año de inicio) con Niño costero en algún mes de diciembre a abril."""
    out = set()
    for y in years:
        months = [f"{y}-12"] + [f"{y + 1}-{m:02d}" for m in (1, 2, 3, 4)]
        if any(calendar.phase(m).phase == "El Niño costero" for m in months):
            out.add(y)
    return out
