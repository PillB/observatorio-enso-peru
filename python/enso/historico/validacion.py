"""Validación fuera de muestra: ¿lo que dice la historia de 1970-2015 se cumplió después?

Los indicadores usan solo DesInventar de 1970-71 a 2014-15. Las emergencias del SINPAD de las temporadas siguientes
(2016-17 en adelante, completas) no entran a ningún indicador, así que sirven para ponerlos a prueba (validación
temporal fuera de muestra, la forma habitual de verificar un pronóstico: Wilks, 2011, cap. 8).

* **Discriminación de la frecuencia histórica.** Para cada nivel (distrito, provincia) y grupo de peligros, el área
  bajo la curva ROC (AUC, la probabilidad de que un área-temporada con emergencias tenga más frecuencia histórica que
  una sin emergencias; Hanley y McNeil, 1982). 0,5 es azar y 1 es perfecto; de 0,7 a 0,8 se considera aceptable y
  desde 0,8 excelente (Hosmer y Lemeshow, 2000). El intervalo al 95 % sale de remuestrear áreas (bootstrap por
  conglomerados: las temporadas de una misma área no son independientes). No se mide la calibración: el SINPAD
  registra muchas más emergencias por año que DesInventar, así que solo el orden de las áreas es comparable.
* **Réplica del efecto de El Niño.** La razón de tasas de El Niño de las temporadas de prueba (mismo método, con el
  SINPAD) en las áreas donde la de 1970-2015 fue claramente mayor que 1, compatible con 1 o claramente menor; y la
  correlación de rangos de Spearman entre ambas razones, área por área.
* **Calibración con la misma fuente** (``calibration``). La probabilidad de al menos un año con daños en 5 años que
  muestra el sitio, calculada con DesInventar 1970-1999, frente a lo que DesInventar registró en 2000-04, 2005-09 y
  2010-14: puntaje de Brier y su habilidad frente a la tasa base (Brier, 1950; Murphy, 1973), AUC y diagrama de
  confiabilidad (Jolliffe y Stephenson, 2012). Se compara con la frecuencia suavizada por Bayes empírico
  (beta-binomial; Clayton y Kaldor, 1987), que corrige el exceso de confianza de las frecuencias de pocos años.
* **Repetición de los grandes Niños** (``great_repeat``). Qué parte de los distritos golpeados en 1982-83 y 1997-98
  volvió a tener registros en el Niño Costero 2017, frente a los que no lo fueron: la base de «si se repite un gran
  Niño».
* **Sensibilidad de la razón de El Niño** (``sensitivity``). La razón con la regla anterior para decidir qué temporada
  es «con Niño» (algún mes de diciembre a abril dentro de un evento) y la respuesta a la intensidad (razón por cada
  +1 °C de ICEN medio de enero a marzo, sin umbral), por departamento.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Iterable, Optional

from .enso import PIRCC_2017
from .indicadores import dispersion, dose_response, hydro_start, rate_ratio

#: Grupos de peligros que se prueban por separado (None = todos).
HAZARD_GROUPS = {
    "todos": None,
    "inundaciones": {"Inundacion", "Inundacion fluvial", "Inundacion pluvial", "Desborde de rio"},
    "huaycos y deslizamientos": {"Huayco/Alud", "Deslizamiento"},
    "heladas, friaje y nevadas": {"Helada/Friaje", "Nevada"},
}
LEVEL_LEN = {"distrito": 6, "provincia": 4, "departamento": 2}
BOOTSTRAP, SEED = 500, 20261027


def auc(pos: list[float], neg: list[float]) -> Optional[float]:
    """AUC de Mann-Whitney (empates cuentan 1/2)."""
    if not pos or not neg:
        return None
    return _auc_weighted([(s, 1, 0) for s in pos] + [(s, 0, 1) for s in neg])


def _auc_weighted(items: Iterable[tuple[float, float, float]]) -> Optional[float]:
    """AUC con pesos: (puntaje, peso de positivos, peso de negativos)."""
    by: dict[float, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for s, w1, w0 in items:
        by[s][0] += w1
        by[s][1] += w0
    W1 = sum(v[0] for v in by.values())
    W0 = sum(v[1] for v in by.values())
    if not W1 or not W0:
        return None
    below = acc = 0.0
    for s in sorted(by):
        w1, w0 = by[s]
        acc += w1 * (below + 0.5 * w0)
        below += w0
    return acc / (W1 * W0)


def _quantile(v: list[float], q: float) -> float:
    s = sorted(v)
    i = q * (len(s) - 1)
    lo = math.floor(i)
    return s[lo] + (s[min(lo + 1, len(s) - 1)] - s[lo]) * (i - lo)


def discrimination(scores: dict[str, float], hits: dict[str, int], seasons: int,
                   rng: Optional[random.Random] = None) -> dict:
    """AUC de ``scores`` (frecuencia histórica por área) para las temporadas con emergencia (``hits``: cuántas de las
    ``seasons`` tuvieron al menos una), con IC 95 % por bootstrap de áreas."""
    areas = sorted(scores)
    items = [(scores[a], hits.get(a, 0), seasons - hits.get(a, 0)) for a in areas]
    point = _auc_weighted(items)
    rng = rng or random.Random(SEED)
    boot = []
    for _ in range(BOOTSTRAP):
        sample = [items[rng.randrange(len(items))] for _ in items]
        v = _auc_weighted(sample)
        if v is not None:
            boot.append(v)
    pos = sum(h for _, h, _ in items)
    return {
        "areas": len(areas), "temporadas": seasons, "tasaBase": round(pos / (len(areas) * seasons), 3) if areas else None,
        "auc": round(point, 3) if point is not None else None,
        "aucIC": [round(_quantile(boot, 0.025), 3), round(_quantile(boot, 0.975), 3)] if boot else [None, None],
    }


def spearman(a: list[float], b: list[float]) -> Optional[float]:
    if len(a) < 3:
        return None

    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r

    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va, vb = sum((x - ma) ** 2 for x in ra), sum((y - mb) ** 2 for y in rb)
    return round(cov / math.sqrt(va * vb), 3) if va and vb else None


def validate(records: list[dict], districts: Iterable[str], train: range, test: range, nino_test: set[int],
             ind: dict[str, dict[str, dict]], names: Optional[dict[str, dict[str, str]]] = None,
             train_origins: frozenset = frozenset({"desinventar"}), test_origin: str = "sinpad") -> dict:
    """Las dos pruebas para el catálogo. ``ind`` son los indicadores por área (``indicadores.by_area``) y ``names``,
    los nombres por nivel y código."""
    districts = sorted(districts)
    T = len(train)
    out: dict = {"entrenamiento": [train.start, train.stop - 1], "prueba": [test.start, test.stop - 1],
                 "fuenteEntrenamiento": sorted(train_origins), "fuentePrueba": test_origin,
                 "aniosNinoPrueba": sorted(y for y in test if y in nino_test), "discriminacion": [], "nino": {}}
    # Años con daños (entrenamiento) y temporadas con emergencias (prueba), por área y grupo de peligros.
    train_years: dict[tuple, set] = defaultdict(set)
    test_seasons: dict[tuple, set] = defaultdict(set)
    test_dy: dict[tuple, set] = defaultdict(set)  # (nivel, área) → {(ubigeo, temporada)} en la prueba, todos los peligros
    for r in records:
        y, u, o = hydro_start(r), r.get("Ubigeo") or "", r.get("Origen")
        if y is None:
            continue
        groups = [g for g, hz in HAZARD_GROUPS.items() if hz is None or r.get("DangerType") in hz]
        for lvl, n in LEVEL_LEN.items():
            if len(u) < n:  # un registro provincial cuenta para su provincia y su departamento, como en by_area
                continue
            a = u[:n]
            if o in train_origins and y in train:
                for g in groups:
                    train_years[(lvl, g, a)].add(y)
            elif o == test_origin and y in test:
                for g in groups:
                    test_seasons[(lvl, g, a)].add(y)
                test_dy[(lvl, a)].add((u, y))
    rng = random.Random(SEED)
    for lvl in ("distrito", "provincia"):
        areas = sorted({d[:LEVEL_LEN[lvl]] for d in districts})
        for g in HAZARD_GROUPS:
            scores = {a: len(train_years.get((lvl, g, a), ())) / T for a in areas}
            hits = {a: len(test_seasons.get((lvl, g, a), ())) for a in areas}
            out["discriminacion"].append({"nivel": lvl, "peligros": g, **discrimination(scores, hits, len(test), rng)})
    tn = sum(1 for y in test if y in nino_test)
    to = len(test) - tn
    for lvl in ("departamento", "provincia"):
        rows, pooled = [], defaultdict(lambda: defaultdict(int))
        for a, st in sorted(ind.get(lvl, {}).items()):
            rr, (lo, hi) = st.get("razonNino"), st.get("razonNinoIC") or (None, None)
            if rr is None:
                continue
            cls = "mayor" if lo > 1 else "menor" if hi < 1 else "sin diferencia clara"
            per_year = defaultdict(int)
            for _, y in test_dy.get((lvl, a), ()):
                per_year[y] += 1
            dn = sum(v for y, v in per_year.items() if y in nino_test)
            do = sum(v for y, v in per_year.items() if y not in nino_test)
            for y in test:
                pooled[cls][y] += per_year.get(y, 0)
            rr_t = rate_ratio(dn, tn, do, to, dispersion(per_year, test, nino_test))[0]
            rows.append({"codigo": a, "nombre": (names or {}).get(lvl, {}).get(a, a), "clase": cls, "rrHistorico": rr,
                         "rrPrueba": rr_t})
        groups = []
        for cls in ("mayor", "sin diferencia clara", "menor"):
            per_year = pooled.get(cls)
            if not per_year:
                continue
            dn = sum(v for y, v in per_year.items() if y in nino_test)
            do = sum(v for y, v in per_year.items() if y not in nino_test)
            rr_t, lo_t, hi_t = rate_ratio(dn, tn, do, to, dispersion(per_year, test, nino_test))
            groups.append({"clase": cls, "areas": sum(1 for r in rows if r["clase"] == cls), "rrPrueba": rr_t,
                           "rrPruebaIC": [lo_t, hi_t]})
        both = [r for r in rows if r["rrPrueba"] is not None]
        out["nino"][lvl] = {"grupos": groups,
                            "spearman": spearman([r["rrHistorico"] for r in both], [r["rrPrueba"] for r in both]),
                            "areasComparadas": len(both),
                            "areas": rows if lvl == "departamento" else []}
    return out


def _district_years(records: list[dict], origins, years) -> dict[str, set]:
    out: dict[str, set] = defaultdict(set)
    for r in records:
        y, u = hydro_start(r), r.get("Ubigeo") or ""
        if y is not None and len(u) == 6 and r.get("Origen") in origins and y in years:
            out[u].add(y)
    return out


def calibration(records: list[dict], districts: Iterable[str], origins: frozenset = frozenset({"desinventar"}),
                train: range = range(1970, 2000), blocks: tuple = ((2000, 2004), (2005, 2009), (2010, 2014)),
                rng: Optional[random.Random] = None) -> dict:
    """La «probabilidad en 5 años» por distrito con ``train`` frente a lo ocurrido en cada bloque de 5 temporadas de la
    misma fuente: Brier, habilidad frente a la tasa base, AUC y confiabilidad, cruda y suavizada."""
    districts = sorted(districts)
    T = len(train)
    seen = _district_years(records, origins, range(train.start, blocks[-1][1] + 1))
    Y = {d: len([y for y in seen.get(d, ()) if y in train]) for d in districts}
    hits = {d: sum(1 for a, b in blocks if any(a <= y <= b for y in seen.get(d, ()))) for d in districts}
    ps = [Y[d] / T for d in districts]
    m = sum(ps) / len(ps)
    v = sum((p - m) ** 2 for p in ps) / (len(ps) - 1)
    # Beta-binomial por momentos: var(p̂) = m(1 − m)/T · (1 + (T − 1)ρ), con ρ = 1/(α + β + 1).
    rho = min(1.0, max(1e-6, (v * T / (m * (1 - m)) - 1) / (T - 1)))
    ab = 1 / rho - 1
    alpha, beta = m * ab, (1 - m) * ab
    out: dict = {"entrenamiento": [train.start, train.stop - 1], "bloques": [list(b) for b in blocks],
                 "distritos": len(districts), "betaBinomial": [round(alpha, 3), round(beta, 3)]}
    nb = len(blocks)
    obs = sum(hits.values()) / (len(districts) * nb)
    ref = obs * (1 - obs)
    for key, prob in (("cruda", {d: Y[d] / T for d in districts}),
                      ("suavizada", {d: (Y[d] + alpha) / (T + ab) for d in districts})):
        pred = {d: 1 - (1 - prob[d]) ** 5 for d in districts}
        brier = sum(hits[d] * (1 - pred[d]) ** 2 + (nb - hits[d]) * pred[d] ** 2 for d in districts) / (len(districts) * nb)
        bins = []
        for lo, hi, label in ((0, 1e-9, "0 %"), (1e-9, 0.2, "hasta 20 %"), (0.2, 0.4, "20-40 %"), (0.4, 0.6, "40-60 %"),
                              (0.6, 0.8, "60-80 %"), (0.8, 1.01, "80 % o más")):
            ds = [d for d in districts if lo <= pred[d] < hi]
            if ds:
                bins.append({"rango": label, "n": len(ds) * nb, "predicha": round(sum(pred[d] for d in ds) / len(ds), 3),
                             "observada": round(sum(hits[d] for d in ds) / (len(ds) * nb), 3)})
        out[key] = {"brier": round(brier, 4), "habilidad": round(1 - brier / ref, 3) if ref else None,
                    "predichaMedia": round(sum(pred.values()) / len(pred), 3), "confiabilidad": bins,
                    **{k: v for k, v in discrimination(pred, hits, nb, rng).items() if k in ("auc", "aucIC")}}
    out["tasaBase"] = round(obs, 3)
    return out


def great_repeat(records: list[dict], districts: Iterable[str], before: tuple = ("FEN 1982-83", "FEN 1997-98"),
                 after: str = "Niño Costero 2017",
                 regions: Optional[dict] = None) -> list[dict]:
    """Distritos golpeados en los dos grandes Niños de ``before``, en uno o en ninguno, y qué parte de cada grupo tuvo
    registros en ``after``."""
    regions = regions or {"costa norte (Tumbes, Piura, Lambayeque, La Libertad)": {"24", "20", "14", "13"},
                          "13 departamentos del Plan de Reconstrucción": PIRCC_2017}
    hit: dict[str, set] = defaultdict(set)
    for r in records:
        u = r.get("Ubigeo") or ""
        if len(u) == 6 and r.get("TipoEvento") in (*before, after):
            hit[u].add(r["TipoEvento"])
    out = []
    for name, deps in regions.items():
        ds = [d for d in districts if d[:2] in deps]
        groups = []
        for label, k in (("en los dos", 2), ("en uno", 1), ("en ninguno", 0)):
            g = [d for d in ds if sum(1 for e in before if e in hit[d]) == k]
            groups.append({"golpeados": label, "distritos": len(g),
                           "conRegistros": round(sum(1 for d in g if after in hit[d]) / len(g), 3) if g else None})
        out.append({"region": name, "antes": list(before), "despues": after, "distritos": len(ds),
                    "tasaBase": round(sum(1 for d in ds if after in hit[d]) / len(ds), 3) if ds else None,
                    "grupos": groups})
    return out


def sensitivity(records: list[dict], years: range, nino: set[int], nino_any: set[int], peak: dict[int, float],
                ind: dict[str, dict[str, dict]], names: Optional[dict[str, dict[str, str]]] = None,
                origins: frozenset = frozenset({"desinventar"})) -> list[dict]:
    """Por departamento (y para el país): la razón de El Niño publicada, la que daría la regla anterior y la respuesta a
    la intensidad del ICEN."""
    per: dict[str, dict[int, set]] = defaultdict(lambda: defaultdict(set))
    for r in records:
        y, u = hydro_start(r), r.get("Ubigeo") or ""
        if y in years and r.get("Origen") in origins and u:
            for a in (u[:2], "PE"):
                per[a][y].add(u)
    rows = []
    for a in sorted(per, key=lambda c: (c == "PE", c)):
        counts = {y: len(v) for y, v in per[a].items()}
        st = ind.get("pais" if a == "PE" else "departamento", {}).get(a, {})
        tn, ta = len([y for y in years if y in nino]), len([y for y in years if y in nino_any])
        dn_any = sum(c for y, c in counts.items() if y in nino_any)
        rr_any = rate_ratio(dn_any, ta, sum(counts.values()) - dn_any, len(years) - ta, dispersion(counts, years, nino_any))
        irr = dose_response(counts, {y: peak[y] for y in years if y in peak})
        rows.append({"codigo": a, "nombre": "Perú" if a == "PE" else (names or {}).get("departamento", {}).get(a, a),
                     "razon": st.get("razonNino"), "razonIC": st.get("razonNinoIC"), "temporadasNino": tn,
                     "razonReglaAnterior": rr_any[0], "razonReglaAnteriorIC": list(rr_any[1:]), "temporadasNinoAnterior": ta,
                     "porGradoICEN": irr[0], "porGradoICENIC": list(irr[1:])})
    return rows
