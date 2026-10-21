"""Mide la ubicación de las noticias contra un conjunto etiquetado a mano.

Cada línea de ``tests/geo/gold-*.jsonl`` trae el titular y el resumen tal como
se publicaron, el feed de origen y dos listas de códigos UBIGEO:

* ``must``: los lugares de los que trata la nota, al nivel más fino que el
  texto permite afirmar;
* ``ok``: lugares que no son obligatorios pero tampoco son un error (la
  provincia de un distrito nombrado, la capital de un departamento, las
  regiones de una alerta «en cuatro regiones de la costa»…).

Un lugar asignado es un error si su departamento no está en ninguna de las dos
listas, o si es una provincia o un distrito que no es uno de los etiquetados
ni el ancestro de uno de ellos. Una nota está mal ubicada si tiene al menos un
error; las demás métricas (cobertura, precisión por nivel) salen de lo mismo.

Uso:
    python -m tools.geo_eval [--gold tests/geo/gold-noticias.jsonl] [--errors]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable, Iterable, Optional

GOLD = Path(__file__).resolve().parents[1] / "tests" / "geo"


def load(paths: Optional[Iterable[Path]] = None) -> list[dict]:
    paths = list(paths) if paths else sorted(GOLD.glob("gold-*.jsonl"))
    out = []
    for p in paths:
        out.extend(json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip())
    return out


def predict(rec: dict) -> dict:
    """Ubica una nota del conjunto con el mismo camino que ``news._read_feed``."""
    from enso import geo
    from enso.news import FEED_BY_ID

    f = FEED_BY_ID.get(rec["feed"])
    region = rec.get("region") or (f.region if f else "peru")
    return geo.locate_item(rec, feed=f, region=region) or {}


def score(rec: dict, pred: dict) -> dict:
    # El Callao es a la vez departamento y su única provincia.
    norm = lambda cs: {"07" if c == "0701" else c for c in cs}  # noqa: E731
    must, ok = norm(rec["must"]), norm(rec["ok"])
    allowed = must | ok
    allowed_deps = {c[:2] for c in allowed}
    allowed_fine = {c for c in allowed if len(c) > 2} | {c[:4] for c in allowed if len(c) == 6}
    codes = list(norm(p["code"] for p in pred.get("places") or []))
    deps = set(pred.get("departments") or []) | {c[:2] for c in codes}
    fine = {c for c in codes if len(c) > 2}
    wrong = sorted({d for d in deps if d not in allowed_deps} | {c for c in fine if c not in allowed_fine})
    must_deps = {c[:2] for c in must}
    must_fine = {c for c in must if len(c) > 2}
    return {
        "wrong": wrong,
        "missed_deps": sorted(must_deps - deps),
        "missed_fine": sorted(c for c in must_fine if not any(p == c or p.startswith(c) for p in fine)),
        "n_deps": len(deps), "ok_deps": len(deps & allowed_deps),
        "n_fine": len(fine), "ok_fine": len(fine & allowed_fine),
        "must_deps": len(must_deps), "hit_deps": len(must_deps & deps),
        "must_fine": len(must_fine), "hit_fine": len(must_fine) - len([c for c in must_fine if not any(p == c or p.startswith(c) for p in fine)]),
        "placed": bool(deps), "should_place": bool(must),
    }


def evaluate(records: list[dict], predictor: Callable[[dict], dict] = predict) -> dict:
    rows = []
    for r in records:
        pred = predictor(r)
        s = score(r, pred)
        rows.append({**s, "id": r["id"], "title": r["title"], "label": r.get("label", ""),
                     "pred": [p["code"] + ":" + p["name"] for p in pred.get("places") or []],
                     "method": pred.get("method")})
    n = len(rows)
    placed = [x for x in rows if x["placed"]]

    def ratio(a: int, b: int) -> float:
        return round(a / b, 4) if b else 1.0

    return {
        "items": n,
        "placed": len(placed),
        "misplaced": sum(1 for x in rows if x["wrong"]),
        "misplacedRate": ratio(sum(1 for x in rows if x["wrong"]), len(placed)),
        "depPrecision": ratio(sum(x["ok_deps"] for x in rows), sum(x["n_deps"] for x in rows)),
        "depRecall": ratio(sum(x["hit_deps"] for x in rows), sum(x["must_deps"] for x in rows)),
        "finePrecision": ratio(sum(x["ok_fine"] for x in rows), sum(x["n_fine"] for x in rows)),
        "fineRecall": ratio(sum(x["hit_fine"] for x in rows), sum(x["must_fine"] for x in rows)),
        "falsePlaced": sum(1 for x in rows if x["placed"] and not x["should_place"] and x["wrong"]),
        "rows": rows,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--gold", type=Path, nargs="*")
    ap.add_argument("--errors", action="store_true", help="Listar las notas mal ubicadas y los lugares que faltan")
    a = ap.parse_args(argv)
    res = evaluate(load(a.gold))
    rows = res.pop("rows")
    print(json.dumps(res, ensure_ascii=False, indent=1))
    if a.errors:
        for x in rows:
            if x["wrong"] or x["missed_deps"] or x["missed_fine"]:
                print(f"- {x['title'][:110]}\n    predicho: {x['pred']} ({x['method']})\n    etiqueta: {x['label']}"
                      f"\n    error: {x['wrong']} faltan: {x['missed_deps'] + x['missed_fine']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
