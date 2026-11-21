"""Informe de los experimentos A/B del sitio, a partir de ``GET /api/ab/stats``.

Uso (desde ``python/``)::

    python -m tools.ab_report                                   # lee https://enso-peru.pages.dev/api/ab/stats?days=60
    python -m tools.ab_report --file tests/fixtures/ab/stats-2026-11-21.json --merges-from-git
    python -m tools.ab_report --url https://<sitio>/api/ab/stats?days=60

Imprime, en Markdown, por experimento: visitas, cuántas vinieron del sorteo y cuántas de una versión elegida, la tasa
de uso con su intervalo de Wilson al 95 %, la prueba de desbalance de la muestra (SRM, Kohavi, Tang y Xu,
*Trustworthy Online Controlled Experiments*, cap. 21) frente al reparto que el sitio quiere, las comprobaciones de
coherencia de los contadores, el tráfico por día y cuántos días faltan para la regla de 200 visitas por versión, y la
potencia de esa regla (cuánto tiene que diferir una versión para que la regla la declare ganadora 8 de cada 10 veces).

Lo que el servidor cuenta (``functions/_lib/ab.js``): por día UTC, experimento, versión y evento, cuántos *avisos de
salida* de una página llevaban ese evento. No hay identificador de persona, así que la unidad del análisis es la
visita y no la persona: lo que un navegador hace en diez visitas pesa diez veces (ver el informe).

Salida: 0 informe impreso · 2 no se pudo leer la estadística (red, HTTP, JSON inválido o ``available: false``):
«no se pudo medir» nunca se informa como «no hay diferencias».
"""

from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import math
import os
import random
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://enso-peru.pages.dev/api/ab/stats?days=60"
Z95 = 1.959964  # el mismo z que functions/_lib/ab.js
Z80 = 0.841621  # cuantil 0,80 de la normal (potencia del 80 %)
MIN_VIEWS = 200  # MIN_VIEWS de functions/_lib/ab.js
DECIDE_DAYS = 60  # DECIDE_DAYS de functions/_lib/ab.js
EXPLOIT = 0.8  # EXPLOIT de public/assets/js/ab.js: parte de las primeras visitas que recibe la ganadora

# Día UTC en que cada experimento empezó a mandar «use» (tabla ab_exp), por el merge que lo publicó:
# mapa/memoria/noticias 9a8dd198 (#69, 2026-10-28 05:27 UTC), boletin 111027bc (#103, 2026-11-10 21:45 UTC),
# sitio dfad571a (#105, 2026-11-11 04:22 UTC). El mapa A–D contaba desde 17b0a7ab (2026-10-21) en ab_daily, sin «use».
TRACKED_SINCE = {"mapa": "2026-10-28", "memoria": "2026-10-28", "noticias": "2026-10-28",
                 "boletin": "2026-11-10", "sitio": "2026-11-11"}


class Unavailable(Exception):
    """La estadística no se pudo leer: el informe no puede decir nada."""


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

def _fetch(url: str, timeout: float = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "observatorio-enso-peru/ab-report", "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (URL del propio sitio o dada a mano)
            return r.read().decode("utf-8")
    except (urllib.error.URLError, OSError, UnicodeDecodeError) as e:
        raise Unavailable(f"{url}: {e}") from e


def parse_stats(text: str, where: str = "estadística") -> dict:
    """El JSON de /api/ab/stats, o Unavailable si no es una estadística utilizable."""
    try:
        data = json.loads(text)
    except ValueError as e:
        raise Unavailable(f"{where}: no es JSON ({e}); empieza por {text[:80]!r}") from e
    if not isinstance(data, dict) or not isinstance(data.get("experiments"), dict):
        raise Unavailable(f"{where}: falta «experiments» (¿una página de desafío o un error del borde?)")
    if data.get("available") is not True:
        raise Unavailable(f"{where}: available={data.get('available')!r}: la base GEO_DB no está vinculada, no hay datos")
    return data


def load(file: str | None, url: str | None) -> dict:
    if file:
        try:
            return parse_stats(Path(file).read_text(encoding="utf-8"), file)
        except OSError as e:
            raise Unavailable(f"{file}: {e}") from e
    src = url or DEFAULT_URL
    return parse_stats(_fetch(src), src)


def snapshot_day(data: dict) -> dt.date:
    """El día UTC de la consulta: ``since`` es hoy − (days − 1)."""
    return dt.date.fromisoformat(data["since"]) + dt.timedelta(days=int(data["days"]) - 1)


# ---------------------------------------------------------------------------
# Estadística
# ---------------------------------------------------------------------------

def wilson(y: int, t: int, z: float = Z95) -> tuple[float, float]:
    """Intervalo de Wilson de y éxitos en t intentos (la misma fórmula que functions/_lib/ab.js)."""
    if not t:
        return 0.0, 1.0
    p = y / t
    den = 1 + z * z / t
    centre = (p + z * z / (2 * t)) / den
    half = z * math.sqrt(p * (1 - p) / t + z * z / (4 * t * t)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def _log_choose(n: int, k: int) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def binom_pmf(n: int, p: float) -> list[float]:
    """P(X = y) para y = 0…n, X ~ Binomial(n, p)."""
    if p <= 0 or p >= 1:
        return [1.0 if y == (0 if p <= 0 else n) else 0.0 for y in range(n + 1)]
    lp, lq = math.log(p), math.log1p(-p)
    return [math.exp(_log_choose(n, y) + y * lp + (n - y) * lq) for y in range(n + 1)]


def chi2_sf(x: float, df: int) -> float:
    """P(χ²_df ≥ x), por la serie de la gamma incompleta inferior regularizada."""
    if x <= 0:
        return 1.0
    a, h = df / 2, x / 2
    term = total = 1 / a
    n = 0
    while term > total * 1e-15 and n < 10000:
        n += 1
        term *= h / (a + n)
        total += term
    lower = math.exp(a * math.log(h) - h - math.lgamma(a)) * total
    return max(0.0, 1.0 - lower)


def _compositions(n: int, k: int):
    if k == 1:
        yield (n,)
        return
    for first in range(n + 1):
        for rest in _compositions(n - first, k - 1):
            yield (first, *rest)


def multinomial_exact_p(counts: list[int], probs: list[float], limit: int = 120) -> float | None:
    """Prueba exacta de bondad de ajuste: suma de P(x) sobre los x tan o menos probables que lo observado."""
    n = sum(counts)
    if n > limit or any(p <= 0 for p in probs):
        return None
    lf = [math.lgamma(i + 1) for i in range(n + 1)]
    logp = [math.log(p) for p in probs]

    def lpmf(x):
        return lf[n] + sum(xi * lp - lf[xi] for xi, lp in zip(x, logp))

    obs = lpmf(counts)
    return min(1.0, sum(math.exp(v) for v in map(lpmf, _compositions(n, len(counts))) if v <= obs + 1e-9))


def srm(counts: list[int], probs: list[float]) -> dict:
    """Desbalance de la muestra: χ² de bondad de ajuste y la prueba exacta, frente al reparto esperado."""
    n = sum(counts)
    if not n:
        return {"n": 0, "chi2": None, "df": len(counts) - 1, "p_chi2": None, "p_exact": None}
    exp = [n * p for p in probs]
    chi2 = sum((o - e) ** 2 / e for o, e in zip(counts, exp))
    df = len(counts) - 1
    return {"n": n, "chi2": chi2, "df": df, "p_chi2": chi2_sf(chi2, df), "p_exact": multinomial_exact_p(counts, probs),
            "min_expected": min(exp)}


def intended_allocation(variants: list[str], winner: str | None) -> list[float]:
    """El reparto de las primeras visitas que quiere ab.js assign(): parejo, o 4/5 a la ganadora y el resto parejo."""
    k = len(variants)
    if not winner:
        return [1 / k] * k
    return [EXPLOIT if v == winner else (1 - EXPLOIT) / (k - 1) for v in variants]


def fisher_greater(a: int, b: int, c: int, d: int) -> float:
    """Fisher exacta, una cola: P(X ≥ a) en la tabla [[a, b], [c, d]] con márgenes fijos (hipergeométrica)."""
    row, col, n = a + b, a + c, a + b + c + d
    hi = min(row, col)
    den = _log_choose(n, col)
    return min(1.0, sum(math.exp(_log_choose(row, x) + _log_choose(n - row, col - x) - den) for x in range(a, hi + 1)))


# ---------------------------------------------------------------------------
# La regla de decisión: «cada versión ≥ 200 visitas y el límite inferior de la mejor > el superior de las demás»
# ---------------------------------------------------------------------------

def _wins_given(n: int, k: int, pmf_lead: list[float], pmf_rest: list[float]) -> float:
    """P(una versión dada gana) = Σ_y P(y) · P(las otras k−1 tienen hi < lo(y)). Los sucesos «gana i» son disjuntos."""
    his = [wilson(y, n)[1] for y in range(n + 1)]  # crece con y
    cdf, acc = [], 0.0
    for q in pmf_rest:
        acc += q
        cdf.append(acc)
    total = 0.0
    for y, py in enumerate(pmf_lead):
        t = bisect.bisect_left(his, wilson(y, n)[0])  # cuántos y' tienen hi(y') < lo(y)
        if t:
            total += py * cdf[t - 1] ** (k - 1)
    return total


def rule_alpha(n: int, k: int, p: float) -> float:
    """Falsos positivos de la regla con n visitas por versión y todas iguales (tasa p): P(se declara alguna ganadora)."""
    pmf = binom_pmf(n, p)
    return k * _wins_given(n, k, pmf, pmf)


def rule_power(n: int, k: int, p0: float, p1: float) -> float:
    """P(la regla declara ganadora a la versión con tasa p1 cuando las otras k−1 tienen p0), n visitas por versión."""
    return _wins_given(n, k, binom_pmf(n, p1), binom_pmf(n, p0))


def rule_mde(n: int, k: int, p0: float, power: float = 0.8, step: float = 0.0025) -> float | None:
    """La menor diferencia absoluta p1 − p0 (en pasos de ``step``) que la regla detecta con esa potencia."""
    d = step
    while p0 + d < 1:
        if rule_power(n, k, p0, p0 + d) >= power:
            return d
        d += step
    return None


def rule_n(k: int, p0: float, p1: float, power: float = 0.8, cap: int = 20000) -> int | None:
    """Visitas por versión para que la regla detecte p1 frente a p0 con esa potencia (búsqueda por bisección)."""
    lo, hi = MIN_VIEWS // 2, MIN_VIEWS
    while rule_power(hi, k, p0, p1) < power:
        lo, hi = hi, hi * 2
        if hi > cap:
            return None
    while hi - lo > 10:  # la potencia de una regla discreta no crece de a uno: basta una precisión de 10 visitas
        mid = (lo + hi) // 2
        lo, hi = (lo, mid) if rule_power(mid, k, p0, p1) >= power else (mid, hi)
    return hi


def ztest_mde(n: int, p0: float, alpha_z: float = Z95, power_z: float = Z80) -> float:
    """La diferencia mínima detectable de la prueba z de dos proporciones (bilateral, α = 0,05, potencia 80 %)."""
    d = 0.0
    for _ in range(50):  # punto fijo: la varianza depende de p1
        p1 = min(p0 + d, 0.999)
        d = (alpha_z + power_z) * math.sqrt((p0 * (1 - p0) + p1 * (1 - p1)) / n)
    return d


def ztest_n(p0: float, p1: float, alpha_z: float = Z95, power_z: float = Z80) -> int:
    """Visitas por versión para una prueba z de dos proporciones (Fleiss, sin corrección de continuidad)."""
    pbar = (p0 + p1) / 2
    num = alpha_z * math.sqrt(2 * pbar * (1 - pbar)) + power_z * math.sqrt(p0 * (1 - p0) + p1 * (1 - p1))
    return math.ceil((num / abs(p1 - p0)) ** 2)


def _rule_decides(ys: list[int], n: int) -> bool:
    ints = [wilson(y, n) for y in ys]
    lead = max(range(len(ys)), key=lambda i: ys[i])
    return all(i == lead or ints[lead][0] > ints[i][1] for i in range(len(ys)))


def peeking_fpr(k: int, p: float, looks: list[int], sims: int = 2000, seed: int = 20261121) -> float:
    """Falsos positivos si la regla se mira en cada n de ``looks`` (acumulado, todas las versiones con tasa p)."""
    rng = random.Random(seed)
    hits = 0
    for _ in range(sims):
        ys, prev = [0] * k, 0
        for n in looks:
            ys = [y + sum(rng.random() < p for _ in range(n - prev)) for y in ys]
            prev = n
            if _rule_decides(ys, n):
                hits += 1
                break
    return hits / sims


# ---------------------------------------------------------------------------
# Lectura de los contadores
# ---------------------------------------------------------------------------

def arm_rows(exp: dict) -> list[dict]:
    """Por versión: totales del periodo y lo que usa la decisión (solo ab_exp, últimos 60 días)."""
    dec = {r["v"]: r for r in exp["decision"]["rows"]}
    rows = []
    for v in exp["variants"]:
        t, d = exp["totals"][v], dec[v]
        # decide() ya acota use ≤ view; una copia alterada no debe tumbar el informe (lo señala _bound_issues).
        lo, hi = wilson(min(d["use"], d["view"]), d["view"])
        rows.append({"v": v, "view": t["view"], "chosen": t["chosen"], "random": t["view"] - t["chosen"],
                     "dview": d["view"], "duse": d["use"], "rate": d["use"] / d["view"] if d["view"] else None,
                     "lo": lo, "hi": hi, **{e: t[e] for e in ("hover", "select", "detail", "use", "choose", "leave", "keep")}})
    return rows


def _use_bounds_issue(name: str, r: dict) -> str | None:
    # En una misma página «use» se marca junto con «select» o «detail» (ab.js mark), así que por versión
    # max(select, detail) ≤ use ≤ select + detail. El sitio marca «use» por su cuenta (abrió una 2.ª pestaña).
    if name == "sitio":
        return None
    if r["use"] > r["select"] + r["detail"]:
        return f"{r['v']}: use={r['use']} > select+detail={r['select'] + r['detail']}"
    if r["use"] < max(r["select"], r["detail"]):
        return f"{r['v']}: use={r['use']} < max(select, detail)={max(r['select'], r['detail'])}"
    return None


def _bound_issues(rows: list[dict]) -> list[str]:
    out = [f"{r['v']}: chosen={r['chosen']} > view={r['view']}" for r in rows if r["chosen"] > r["view"]]
    return out + [f"{r['v']}: use={r['duse']} > view={r['dview']} en la decisión" for r in rows if r["duse"] > r["dview"]]


def _legacy_issues(name: str, rows: list[dict], legacy_known: bool) -> list[str]:
    legacy = sum(r["view"] - r["dview"] for r in rows) if legacy_known else 0
    if legacy:
        return [f"{legacy} de {sum(r['view'] for r in rows)} visitas son de ab_daily (sin «use»): cuentan en los "
                "totales, no en la decisión; la tasa de los totales sale sesgada a 0"]
    return [m for m in (_use_bounds_issue(name, r) for r in rows) if m]


def _leave_issue(rows: list[dict]) -> list[str]:
    leave, choose = sum(r["leave"] for r in rows), sum(r["choose"] for r in rows)
    if leave <= choose:
        return []
    # choose() manda «leave» al instante, en su propio aviso, y deja «choose» (con view y chosen) para el aviso de
    # salida de la página: si ese aviso no llega (pestaña cerrada sin pagehide, o «No participar» marcado después
    # de elegir, que hace que flush() ya no mande nada), queda un «leave» sin su «choose».
    return [f"leave={leave} > choose={choose}: faltan al menos {leave - choose} avisos de salida posteriores a una "
            "elección (cada «leave» se manda al elegir; su «choose», con la visita, al salir de la página)"]


def consistency(name: str, exp: dict, legacy_known: bool) -> list[str]:
    """Contradicciones entre contadores de un experimento (cada una con lo esperado y lo obtenido).

    ``legacy_known``: la consulta cubre los mismos días que la decisión (days == decideDays), así que la diferencia
    entre los totales y las visitas de la decisión son las filas viejas de ab_daily.
    """
    rows = arm_rows(exp)
    out = _bound_issues(rows) + _legacy_issues(name, rows, legacy_known) + _leave_issue(rows)
    if name == "sitio":
        out.append("«use» del sitio = abrió una segunda pestaña (sitio.js), no select/detail: otra métrica, y la propia "
                   "versión B la afecta (las pestañas están dentro de submenús)")
    return out


def daily_views(data: dict) -> dict[str, dict[str, int]]:
    """{día: {experimento: visitas}} con el evento «view»."""
    out: dict[str, dict[str, int]] = {}
    for r in data.get("daily", []):
        if r["event"] == "view":
            day = out.setdefault(r["day"], {})
            day[r["exp"]] = day.get(r["exp"], 0) + r["n"]
    return out


def traffic(name: str, exp: dict, end: dt.date) -> dict:
    """Ritmo de las visitas que cuentan para la decisión, y si la regla de 200 por versión se alcanza en 60 días."""
    rows = arm_rows(exp)
    k = len(rows)
    start = max(dt.date.fromisoformat(TRACKED_SINCE.get(name, end.isoformat())), end - dt.timedelta(days=DECIDE_DAYS - 1))
    days = max(1, (end - start).days)  # el día de inicio (parcial) cuenta; el de la consulta (parcial) no
    tracked = sum(r["dview"] for r in rows)
    randomized = sum(r["random"] for r in rows) if name != "mapa" else None
    per_arm = tracked / days / k
    need = MIN_VIEWS * k / DECIDE_DAYS  # visitas por día para tener 200 por versión dentro de la ventana
    return {"days": days, "tracked": tracked, "per_day": tracked / days, "per_arm_day": per_arm,
            "need_per_day": need, "reachable": tracked / days >= need,
            "days_to_200": math.ceil(MIN_VIEWS / per_arm) if per_arm else None,
            "randomized_per_day": None if randomized is None else randomized / days}


def internal_share(views_by_day: dict[str, dict[str, int]], merge_days: set[str], first: str, last: str) -> dict:
    """Visitas en días con un PR fusionado, y la prueba de Fisher «hay visitas» × «hubo merge» por día."""
    d0, d1 = dt.date.fromisoformat(first), dt.date.fromisoformat(last)
    days = [(d0 + dt.timedelta(i)).isoformat() for i in range((d1 - d0).days + 1)]
    table = {(t, m): 0 for t in (True, False) for m in (True, False)}
    for day in days:
        table[(bool(views_by_day.get(day)), day in merge_days)] += 1
    total = sum(sum(v.values()) for v in views_by_day.values())
    on_merge = sum(sum(v.values()) for d, v in views_by_day.items() if d in merge_days)
    a, b, c, d = table[(True, True)], table[(True, False)], table[(False, True)], table[(False, False)]
    return {"views": total, "on_merge": on_merge, "days": len(days), "traffic_merge": a, "traffic_nomerge": b,
            "quiet_merge": c, "quiet_nomerge": d, "p_fisher": fisher_greater(a, b, c, d)}


def merge_days_from_git(repo: Path) -> set[str]:
    """Días UTC con un «Merge pull request» en la historia de primer padre de HEAD."""
    out = subprocess.run(["git", "-C", str(repo), "log", "--first-parent", "--grep=^Merge pull request",
                          "--format=%ad", "--date=format-local:%Y-%m-%d"], capture_output=True, text=True,
                         check=True, env={**os.environ, "TZ": "UTC"})
    return set(out.stdout.split())


# ---------------------------------------------------------------------------
# Informe
# ---------------------------------------------------------------------------

def _pct(x: float | None, nd: int = 1) -> str:
    return "—" if x is None else f"{100 * x:.{nd}f} %".replace(".", ",")


def _num(x: float | None, nd: int = 2) -> str:
    return "—" if x is None else f"{x:.{nd}f}".replace(".", ",")


def _p(x: float | None) -> str:
    if x is None:
        return "—"
    return "< 0,0001" if x < 1e-4 else _num(x, 4)


def table_arms(name: str, exp: dict) -> list[str]:
    out = [f"### {name}", "", "| Versión | Visitas | Elegida | Sorteo | Decisión: visitas | use | Tasa | IC 95 % (Wilson) |",
           "|---|---:|---:|---:|---:|---:|---:|---|"]
    for r in arm_rows(exp):
        out.append(f"| {r['v']} | {r['view']} | {r['chosen']} | {r['random']} | {r['dview']} | {r['duse']} | "
                   f"{_pct(r['rate'])} | {_pct(r['lo'])} – {_pct(r['hi'])} |")
    dec = exp["decision"]
    out.append(f"\nGanadora: {dec['winner'] or 'ninguna'} · lista para decidir: {'sí' if dec['ready'] else 'no'} "
               f"(mínimo {dec['minViews']} visitas por versión)")
    return out


def table_srm(data: dict) -> list[str]:
    out = ["| Experimento | Reparto previsto | Visitas del sorteo | χ² (gl) | p χ² | p exacta | Todas las visitas | p exacta |",
           "|---|---|---|---:|---:|---:|---|---:|"]
    for name, exp in data["experiments"].items():
        rows = arm_rows(exp)
        probs = intended_allocation(exp["variants"], exp["decision"]["winner"])
        rnd = srm([r["random"] for r in rows], probs)
        allv = srm([r["view"] for r in rows], probs)
        out.append(f"| {name} | {' / '.join(_pct(p, 0) for p in probs)} | {' / '.join(str(r['random']) for r in rows)} | "
                   f"{_num(rnd['chi2'])} ({rnd['df']}) | {_p(rnd['p_chi2'])} | {_p(rnd['p_exact'])} | "
                   f"{' / '.join(str(r['view']) for r in rows)} | {_p(allv['p_exact'])} |")
    return out


def table_mix(data: dict) -> list[str]:
    """Cuántas visitas vienen del sorteo y cuántas de una versión que la persona eligió (o que le dejó un «choose»)."""
    out = ["| Experimento | Visitas | Con versión elegida (chosen) | Del sorteo | % del sorteo | choose | ¿La decisión las mezcla? |",
           "|---|---:|---:|---:|---:|---:|---|"]
    tv = tc = 0
    for name, exp in data["experiments"].items():
        rows = arm_rows(exp)
        v, c = sum(r["view"] for r in rows), sum(r["chosen"] for r in rows)
        tv, tc = tv + v, tc + c
        out.append(f"| {name} | {v} | {c} | {v - c} | {_pct((v - c) / v if v else None)} | {sum(r['choose'] for r in rows)} | "
                   "sí: decide con todas las visitas |")
    out.append(f"| total | {tv} | {tc} | {tv - tc} | {_pct((tv - tc) / tv if tv else None)} | | |")
    return out


def table_traffic(data: dict) -> list[str]:
    end = snapshot_day(data)
    out = ["| Experimento | Desde | Días | Visitas medidas | Por día | Por versión y día | Hacen falta por día | "
           "Días hasta 200/versión | ¿Se llega en 60 días? |", "|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for name, exp in data["experiments"].items():
        t = traffic(name, exp, end)
        out.append(f"| {name} | {TRACKED_SINCE.get(name, '—')} | {t['days']} | {t['tracked']} | {_num(t['per_day'])} | "
                   f"{_num(t['per_arm_day'])} | {_num(t['need_per_day'])} | {t['days_to_200'] or '—'} | "
                   f"{'sí' if t['reachable'] else 'no'} |")
    return out


def table_power(p0s=(0.05, 0.15, 0.25), ks=(2, 3, 4), n: int = MIN_VIEWS) -> list[str]:
    out = [f"Con {n} visitas por versión. α: falsos positivos de la regla si todas son iguales. DMD: diferencia mínima "
           "detectable (puntos porcentuales) con potencia del 80 %.", "",
           "| Tasa base | Versiones | α de la regla | DMD de la regla | DMD prueba z (α = 0,05, 2 versiones) |",
           "|---:|---:|---:|---:|---:|"]
    for p0 in p0s:
        for k in ks:
            out.append(f"| {_pct(p0, 0)} | {k} | {_num(rule_alpha(n, k, p0), 4)} | "
                       f"{_num(100 * (rule_mde(n, k, p0) or float('nan')), 1)} | {_num(100 * ztest_mde(n, p0), 1)} |")
    return out


def table_sample_size(p0: float = 0.15, lifts=(0.03, 0.05, 0.10), ks=(2, 3, 4)) -> list[str]:
    out = [f"Visitas por versión para detectar la mejora con potencia del 80 % (tasa base {_pct(p0, 0)}).", "",
           "| Mejora (puntos) | Versiones | Regla del sitio | Prueba z, α = 0,05 (2 versiones) |", "|---:|---:|---:|---:|"]
    for d in lifts:
        for k in ks:
            out.append(f"| +{_num(100 * d, 0)} | {k} | {rule_n(k, p0, p0 + d) or '> 20 000'} | {ztest_n(p0, p0 + d)} |")
    return out


def table_internal(data: dict, merges: set[str]) -> list[str]:
    vd = daily_views(data)
    if not vd:
        return ["Sin visitas por día."]
    s = internal_share(vd, merges, min(vd), max(vd))
    out = ["| Día (UTC) | Visitas | Experimentos | ¿PR fusionado ese día? |", "|---|---:|---|---|"]
    for day in sorted(vd):
        out.append(f"| {day} | {sum(vd[day].values())} | {', '.join(f'{k} {v}' for k, v in sorted(vd[day].items()))} | "
                   f"{'sí' if day in merges else 'no'} |")
    out.append(f"\n{s['on_merge']} de {s['views']} visitas ({_pct(s['on_merge'] / s['views'])}) cayeron en días con un PR "
               f"fusionado. De {s['days']} días: con visitas y merge {s['traffic_merge']}, con visitas sin merge "
               f"{s['traffic_nomerge']}, sin visitas con merge {s['quiet_merge']}, sin nada {s['quiet_nomerge']} "
               f"(Fisher, una cola: p = {_p(s['p_fisher'])}).")
    return out


def report(data: dict, merges: set[str] | None = None) -> str:
    end = snapshot_day(data)
    legacy_known = int(data["days"]) == int(data.get("decideDays", DECIDE_DAYS))
    lines = [f"# Experimentos A/B: consulta del {end.isoformat()} (days={data['days']}, desde {data['since']})", ""]
    for name, exp in data["experiments"].items():
        lines += table_arms(name, exp)
        issues = consistency(name, exp, legacy_known)
        lines += [""] + [f"- {m}" for m in issues] + [""] if issues else [""]
    lines += ["## Sorteo o elección", ""] + table_mix(data)
    lines += ["", "## Desbalance de la muestra (SRM)", ""] + table_srm(data)
    lines += ["", "## Tráfico y regla de 200 visitas", ""] + table_traffic(data)
    lines += ["", "## Potencia de la regla", ""] + table_power() + [""] + table_sample_size()
    if merges is not None:
        lines += ["", "## Visitas y PR fusionados", ""] + table_internal(data, merges)
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--file", help="JSON guardado de /api/ab/stats")
    ap.add_argument("--url", help=f"URL de /api/ab/stats (por omisión {DEFAULT_URL})")
    ap.add_argument("--merges-from-git", action="store_true", help="cruza las visitas por día con los PR fusionados (git log)")
    args = ap.parse_args(argv)
    try:
        data = load(args.file, args.url)
    except Unavailable as e:
        print(f"ab_report: no se pudo leer la estadística: {e}. Sin datos no hay informe (salida 2); "
              "pruebe --file con una copia guardada o revise /api/ab/stats en el sitio.", file=sys.stderr)
        return 2
    merges = merge_days_from_git(Path(__file__).resolve().parents[2]) if args.merges_from_git else None
    sys.stdout.write(report(data, merges))
    return 0


if __name__ == "__main__":
    sys.exit(main())
