"""Construye ``enso/data/godas-d20.json``: D20 regional mensual de GODAS y su climatología 1991–2020.

Descarga, para cada mes desde enero de 1980, solo los registros POT de 5 a
303 m del archivo mensual de GODAS en NOAA/CPC (≈5,7 MB por mes, por rango
HTTP), calcula el D20 regional con ``enso.feeds.godas`` y guarda la serie y
la media 1991–2020 de cada mes. Se corre a mano (una vez, o si CPC
reprocesa GODAS); la corrida diaria del observatorio solo lee los meses
recientes y usa esta climatología.

Uso:
    python -m tools.godas_d20_climatology [--start 1980-01] [--end 2026-09] [--workers 4] [--cache DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Optional

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from enso.feeds import godas  # noqa: E402
from enso.fetch import UA  # noqa: E402
from enso.reach import Robots, get_checked  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "enso" / "data" / "godas-d20.json"
BASE_YEARS = (1991, 2020)


def months(start: str, end: str):
    y, m = map(int, start.split("-"))
    ye, me = map(int, end.split("-"))
    while (y, m) <= (ye, me):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _refused(url: str, verdict: Optional[bool], robots: Robots) -> SystemExit:
    why = "no permite" if verdict is False else f"no respondió ({robots.failure(url) or 'sin respuesta'}) y no se sabe si permite"
    return SystemExit(f"El robots.txt de {httpx.URL(url).host} {why} {url}: no se pide.")


def fetch_month(client: httpx.Client, y: int, m: int, cache: Optional[Path] = None,
                robots: Optional[Robots] = None) -> dict:
    """D20 regional de un mes. Con ``robots``, el GRIB y cada redirección solo si su robots.txt lo permite (un
    robots.txt sin respuesta detiene la corrida: no se sabe si permite)."""
    u = godas.url(y, m)
    hit = cache / f"{y:04d}{m:02d}.json" if cache else None
    if hit and hit.exists():
        return json.loads(hit.read_text())
    if robots is not None and (allowed := robots.allowed(u)) is not True:
        raise _refused(u, allowed, robots)
    err: Exception = RuntimeError("sin intentos")
    for attempt in range(6):
        if attempt:
            time.sleep(5 * 2 ** attempt)  # CPC responde 403 o 5xx a ráfagas de pedidos
        try:
            r, hop, verdict = get_checked(client, u, robots, headers={"Range": f"bytes=0-{godas.RANGE_BYTES - 1}"})
            if hop:
                raise _refused(hop, verdict, robots)
            if r.status_code == 404:
                return {}
            r.raise_for_status()
            res = godas.regional_d20(godas.pot_records(r.content))
            if hit:
                hit.write_text(json.dumps(res))
            return res
        except (httpx.HTTPError, godas.FormatChanged) as e:
            err = e
    raise RuntimeError(f"{y}-{m:02d}: {err}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="1980-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--cache", type=Path, default=None, help="carpeta para guardar cada mes ya calculado")
    a = ap.parse_args(argv)
    today = date.today()
    end = a.end or f"{today.year:04d}-{today.month:02d}"
    todo = list(months(a.start, end))
    with httpx.Client(timeout=120, headers={"User-Agent": UA}) as client, ThreadPoolExecutor(a.workers) as ex:
        if a.cache:
            a.cache.mkdir(parents=True, exist_ok=True)
        robots = Robots(client, tries=3, backoff_s=5.0)
        results = list(ex.map(lambda ym: fetch_month(client, *ym, cache=a.cache, robots=robots), todo))
    series = {k: [] for k in godas.REGIONS}
    for (y, m), res in zip(todo, results):
        for k in godas.REGIONS:
            if k in res:
                series[k].append({"period": f"{y:04d}-{m:02d}", "d20": res[k]["d20"], "outcrop": res[k]["outcrop"]})
    clim = {}
    for k, pts in series.items():
        by_month = {mm: [p["d20"] for p in pts if BASE_YEARS[0] <= int(p["period"][:4]) <= BASE_YEARS[1]
                         and int(p["period"][5:]) == mm] for mm in range(1, 13)}
        if any(len(v) != BASE_YEARS[1] - BASE_YEARS[0] + 1 for v in by_month.values()):
            raise SystemExit(f"{k}: climatología incompleta {[len(v) for v in by_month.values()]}")
        clim[k] = [round(sum(v) / len(v), 2) for v in by_month.values()]
    doc = {
        "product": "D20 regional mensual de NCEP GODAS (profundidad de la isoterma de 20 °C)",
        "source": godas.BASE,
        "docs": godas.DOCS,
        "method": ("Primer cruce de 20 °C desde la superficie en el perfil de temperatura potencial de cada punto de "
                   "grilla (interpolación lineal; 0 m si la isoterma aflora), promedio de área ponderado por cos(lat). "
                   "Calculado con python/enso/feeds/godas.py."),
        "base_period": f"{BASE_YEARS[0]}–{BASE_YEARS[1]}",
        "regions": {k: r["label"] for k, r in godas.REGIONS.items()},
        "built": today.isoformat(),
        "climatology": clim,
        "monthly": series,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{OUT}: {sum(len(v) for v in series.values())} puntos; último {series['d20_nino12'][-1]['period']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
