"""Indicadores de recurrencia y riesgo por área a partir del catálogo histórico.

Definiciones (``docs/memoria-desastres.md`` las explica con ejemplos). Con T = años hidrológicos
(julio–junio) del periodo de cobertura homogénea y Y = años con al menos un registro en el área:

* **Frecuencia anual** p = Y/T, con intervalo de Wilson al 95 % (válido con muestras pequeñas).
  Se cuentan años con evento y no registros, porque un mismo Niño deja decenas de fichas en un
  distrito.
* **Periodo de retorno empírico** T/Y: «en promedio, un año con daños cada X años». Es frecuencia
  histórica, no pronóstico: supone clima y exposición constantes. Su intervalo es [1/p_sup, 1/p_inf], con los
  extremos del de Wilson (sin cota superior si Y = 0).
* **Probabilidad en los próximos 5 años** 1 − (1 − p)^5, con la misma salvedad y el intervalo que sale de aplicar
  la fórmula a los extremos del de Wilson. Supone años independientes; los Niños agrupan años malos, así que es
  una aproximación.
* **Distrito-años con daños** DA: pares distintos (lugar, año hidrológico) con registros. En un distrito es
  Y; en una provincia o un departamento mide cuántos de sus distritos sufren daños cada año (la
  frecuencia anual de un departamento grande es casi siempre 1 y no distingue nada).
* **Razón de tasas en El Niño** RR = (DA_niño/T_niño) / (DA_otros/T_otros): cuántas veces más lugares con daños por
  año hay en las temporadas con Niño costero que en las demás. Una temporada es «con Niño» si el ICEN medio de enero a
  marzo (el pico de lluvias de la costa norte; Lavado-Casimiro y Espinoza, 2014) supera +0,5 °C, el umbral de
  condición cálida del ENFEN (Nota Técnica 01-2024). Las demás (neutras y con La Niña) son la referencia.
  Intervalo al 95 % logarítmico de Poisson corregido por sobredispersión (cuasi-Poisson: la varianza se
  multiplica por φ, el estadístico de Pearson de los conteos anuales sobre sus grados de libertad, con mínimo 1;
  Wedderburn, 1974; McCullagh y Nelder, 1989). Sin la corrección el intervalo sale demasiado estrecho, porque los
  distritos de un mismo año no son independientes: el mismo temporal los golpea juntos. Sin registros en uno de
  los dos grupos, no se calcula.
* **Grandes Niños**: cuáles de los eventos históricos (``enso.GREAT``) dejaron registros en el área.
* **Impactos**: sumas de lo que las fuentes reportan (vacío ≠ cero). Las cifras de personas y viviendas de una fila
  con ``AreaCifras`` (la cifra es de la provincia o del departamento: ``conciliacion``) cuentan en esa área y en las
  que la contienen, no en las menores.
* **Fuente homogénea**: frecuencia, periodo de retorno, distrito-años y razón de tasas se calculan solo con
  los registros de la fuente sistemática del periodo de cobertura (``homogeneous``: DesInventar). Las
  demás fuentes (SINPAD desde 2016, IDMC, curados) suman registros, impactos y grandes Niños, pero no
  cambian la frecuencia: tienen otra densidad y la mezclarían.
* **Muestra pequeña**: Y < 5: el sitio muestra la cifra, pero marcada y sin calificarla.
* **Respuesta a la intensidad** (``dose_response``, solo en la validación): cuánto cambian los lugares con daños por
  año por cada grado más de ICEN medio de enero a marzo, sin cortar en un umbral.

Hasta octubre de 2026 había además un «nivel de atención» (grandes Niños y frecuencia); la revisión independiente
mostró que no distinguía (93 % de las provincias quedaban en alto o muy alto) y mezclaba fuentes de densidad
distinta, así que se quitó (``docs/memoria-desastres.md``, «Validación»).
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Iterable, Optional

from .conciliacion import AREA_COLUMNS, counts_at
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


def rate_ratio(a: int, t1: int, b: int, t0: int,
               phi: float = 1.0) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Razón de tasas (a/t1)/(b/t0) con IC 95 % logarítmico, con la varianza multiplicada por el factor de
    sobredispersión ``phi`` (1 = Poisson); None si un grupo no tiene casos."""
    if not (a and b and t1 and t0):
        return None, None, None
    rr = (a / t1) / (b / t0)
    se = math.sqrt(phi * (1 / a + 1 / b))
    return round(rr, 3), round(rr * math.exp(-Z * se), 3), round(rr * math.exp(Z * se), 3)


def dispersion(per_year: dict[int, int], years: Iterable[int], nino_years: set[int]) -> float:
    """Factor de sobredispersión φ de los conteos por año (``per_year``) con una media para los años con Niño y
    otra para los demás: estadístico de Pearson Σ (y − μ)² / μ entre sus grados de libertad (años − grupos), con
    mínimo 1 (nunca estrecha el intervalo de Poisson). Redondeado a 4 decimales, igual que en el sitio."""
    groups: dict[bool, list[int]] = {True: [], False: []}
    for y in years:
        groups[y in nino_years].append(per_year.get(y, 0))
    chi, n, k = 0.0, 0, 0
    for v in (groups[True], groups[False]):
        if not v:
            continue
        n, k = n + len(v), k + 1
        mu = sum(v) / len(v)
        if mu > 0:
            chi += sum((x - mu) ** 2 for x in v) / mu
    return round(max(1.0, chi / (n - k)), 4) if n > k else 1.0


def return_period_ci(lo: Optional[float], hi: Optional[float]) -> list[Optional[float]]:
    """Intervalo del periodo de retorno a partir del de la frecuencia anual: [1/p_sup, 1/p_inf]."""
    return [round(1 / hi, 1) if hi else None, round(1 / lo, 1) if lo else None]


def prob5_ci(lo: Optional[float], hi: Optional[float]) -> list[Optional[float]]:
    return [round(1 - (1 - lo) ** 5, 4) if lo is not None else None,
            round(1 - (1 - hi) ** 5, 4) if hi is not None else None]


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


#: Dígitos de UBIGEO de cada nivel (la macrorregión y el país contienen cualquier área).
LEVEL_DIGITS = {"departamento": 2, "provincia": 4, "distrito": 6}


def summarize(records: Iterable[dict], years: range, nino_years: set[int],
              homogeneous: Optional[set[str]] = None, level: Optional[int] = None) -> dict:
    """Indicadores de un conjunto de registros de una misma área (ya filtrados). ``level``: dígitos de UBIGEO del área
    (None: macrorregión o país), para no sumar en ella las cifras de un área mayor (``conciliacion.counts_at``)."""
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
    phi = dispersion(Counter(y for _, y in da), years, nino_years)
    rr, rr_lo, rr_hi = rate_ratio(dn, tn, do, to, phi)
    great = [g for g in GREAT if any(r.get("TipoEvento") == g for r in recs)]
    imp = defaultdict(float)
    intensive = 0
    for r in recs:
        if r.get("ImpactoEnTotales") == "no":  # solo «no» excluye (resumen curado que otra fila ya detalla)
            continue
        here = counts_at(r, level)
        for k in ("Fallecidos", "Desaparecidos", "Afectados", "Damnificados", "Desplazados", "ViviendasDestruidas",
                  "ViviendasAfectadas", "HectareasCultivo", "KmVias"):
            if here or k not in AREA_COLUMNS:
                imp[k] += _num(r.get(k))
        if _num(r.get("Fallecidos")) >= INTENSIVE_DEATHS or \
                (here and _num(r.get("ViviendasDestruidas")) >= INTENSIVE_HOUSES):
            intensive += 1
    hazards = Counter(r["DangerType"] for r in recs)
    last = max(recs, key=lambda r: r["Date"]) if recs else None
    decades = Counter(f"{int(r['Anio']) // 10 * 10}s" for r in recs)
    return {
        "registros": len(recs), "aniosConEvento": Y, "aniosCobertura": T,
        "frecuenciaAnual": round(p, 4) if p is not None else None, "frecuenciaIC": [lo, hi],
        "periodoRetorno": round(T / Y, 1) if Y else None, "periodoRetornoIC": return_period_ci(lo, hi),
        "prob5Anios": round(1 - (1 - p) ** 5, 4) if p is not None else None, "prob5AniosIC": prob5_ci(lo, hi),
        "distritoAnios": len(da), "distritoAniosPorAnio": round(len(da) / T, 2) if T else None,
        "razonNino": rr, "razonNinoIC": [rr_lo, rr_hi], "dispersionNino": phi, "distritoAniosNino": [dn, tn], "distritoAniosOtros": [do, to],
        "grandesNinos": great, "muestraPequena": Y < 5,
        "impactos": {k: round(v) for k, v in imp.items()}, "registrosIntensivos": intensive,
        "peligros": hazards.most_common(), "decadas": dict(sorted(decades.items())),
        "ultimo": {"Date": last["Date"], "DangerType": last["DangerType"], "TipoEvento": last["TipoEvento"]} if last else None,
    }


def by_area(records: list[dict], years: range, nino_years: set[int],
            homogeneous: Optional[set[str]] = None) -> dict[str, dict[str, dict]]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in records:
        for lvl, code in area_codes(r):
            groups[(lvl, code)].append(r)
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for (lvl, code), rs in groups.items():
        out[lvl][code] = summarize(rs, years, nino_years, homogeneous=homogeneous, level=LEVEL_DIGITS.get(lvl))
    return out


#: Umbral de condición cálida del ICEN (ENFEN, Nota Técnica 01-2024) y meses del pico de lluvias.
WARM, PEAK = 0.5, (1, 2, 3)


def peak_icen(calendar, y: int) -> Optional[float]:
    """ICEN medio de enero a marzo de la temporada que empieza en julio de ``y`` (None si falta un mes)."""
    v = [calendar.phase(f"{y + 1}-{m:02d}").icen for m in PEAK]
    return None if None in v else sum(v) / len(v)


def nino_hydro_years(calendar, years: range) -> set[int]:
    """Temporadas (por su año de inicio) con Niño costero en el pico de lluvias: ICEN medio de enero a marzo > +0,5 °C."""
    return {y for y in years if (v := peak_icen(calendar, y)) is not None and v > WARM}


def nino_hydro_years_any(calendar, years: range) -> set[int]:
    """Regla anterior, para la prueba de sensibilidad: algún mes de diciembre a abril dentro de un Niño costero."""
    out = set()
    for y in years:
        months = [f"{y}-12"] + [f"{y + 1}-{m:02d}" for m in (1, 2, 3, 4)]
        if any(calendar.phase(m).phase == "El Niño costero" for m in months):
            out.add(y)
    return out


def dose_response(per_year: dict[int, int], x: dict[int, float]) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Razón de tasas por cada +1 de ``x`` (ICEN medio de enero a marzo de cada temporada): regresión de Poisson
    log μ = a + b·x ajustada por Newton-Raphson, con el IC 95 % de Wald ensanchado por la sobredispersión (cuasi-Poisson;
    McCullagh y Nelder, 1989). ``per_year`` son los conteos por temporada (0 si falta); solo cuentan las temporadas con
    ``x``. None si hay menos de 10 temporadas, ningún caso o el ajuste no converge."""
    pts = [(v, per_year.get(y, 0)) for y, v in sorted(x.items()) if v is not None]
    n, tot = len(pts), sum(c for _, c in pts)
    if n < 10 or not tot:
        return None, None, None
    a, b = math.log(tot / n), 0.0
    for _ in range(100):
        mu = [math.exp(a + b * v) for v, _ in pts]
        ua = sum(c - m for (_, c), m in zip(pts, mu))
        ub = sum(v * (c - m) for (v, c), m in zip(pts, mu))
        iaa, iab, ibb = sum(mu), sum(v * m for (v, _), m in zip(pts, mu)), sum(v * v * m for (v, _), m in zip(pts, mu))
        det = iaa * ibb - iab * iab
        if det <= 0:
            return None, None, None
        da, db = (ibb * ua - iab * ub) / det, (iaa * ub - iab * ua) / det
        a, b = a + da, b + db
        if abs(b) > 20:
            return None, None, None
        if abs(da) + abs(db) < 1e-10:
            break
    else:
        return None, None, None
    mu = [math.exp(a + b * v) for v, _ in pts]
    phi = max(1.0, sum((c - m) ** 2 / m for (_, c), m in zip(pts, mu)) / (n - 2))
    iaa, iab, ibb = sum(mu), sum(v * m for (v, _), m in zip(pts, mu)), sum(v * v * m for (v, _), m in zip(pts, mu))
    se = math.sqrt(phi * iaa / (iaa * ibb - iab * iab))
    return round(math.exp(b), 3), round(math.exp(b - Z * se), 3), round(math.exp(b + Z * se), 3)
