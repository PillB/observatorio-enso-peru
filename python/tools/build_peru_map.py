"""Construye ``public/assets/peru-map.json``: el mapa del Perú del panel de alertas.

Parte de los mismos límites del IGN que usa el ubicador (``enso/data/limites-ign.json.gz``, CC BY-IGO;
ver ``docs/atribucion-licencias.md``) y escribe, ya proyectado para un SVG:

* ``departments``: el contorno de cada departamento como trazo SVG (``d``) y un punto interior para su
  etiqueta y para los avisos que se ubican en todo el departamento.
* ``points``: un punto interior por provincia y por distrito (UBIGEO → [x, y]), para los avisos que la
  fuente ubica en ese lugar. No se dibujan sus límites: el mapa es de departamentos.

Proyección equirectangular con la escala horizontal corregida a la latitud media del Perú (9,5° S);
a esta escala la deformación es menor que el grosor del trazo. ``lonLat`` permite al sitio ubicar
coordenadas (sismos) con la misma proyección.

Uso:
    python -m tools.build_peru_map            # escribe public/assets/peru-map.json
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "python" / "enso" / "data" / "limites-ign.json.gz"
OUT = ROOT / "public" / "assets" / "peru-map.json"
#: Caja del mapa (lon oeste, lat sur, lon este, lat norte) y píxeles por grado de latitud.
BOX = (-81.45, -18.45, -68.6, 0.05)
K = 40.0
COS = math.cos(math.radians(9.5))
#: Tolerancia de simplificación de los contornos en grados (0,015° ≈ 1,7 km, medio píxel a esta escala).
TOL = 0.015
#: Anillos más pequeños que esto (en px²) no se dibujan: islotes que no se verían.
MIN_AREA = 0.6


def project(lon: float, lat: float) -> tuple[float, float]:
    return (lon - BOX[0]) * COS * K, (BOX[3] - lat) * K


def _ring(flat: list[int], scale: int) -> list[tuple[float, float]]:
    return [project(flat[i] / scale, flat[i + 1] / scale) for i in range(0, len(flat), 2)]


def _dp(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Douglas-Peucker iterativo (tolerancia en px)."""
    if len(pts) < 4:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy) or 1e-9
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            d = abs(dy * (px - ax) - dx * (py - ay)) / norm
            if d > best:
                best, idx = d, i
        if best > tol and idx > 0:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def _area(r: list[tuple[float, float]]) -> float:
    return abs(sum(r[i][0] * r[i - 1][1] - r[i - 1][0] * r[i][1] for i in range(len(r)))) / 2


def _inside(x: float, y: float, r: list[tuple[float, float]]) -> bool:
    inside, j = False, len(r) - 1
    for i in range(len(r)):
        (xi, yi), (xj, yj) = r[i], r[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _edge_dist(x: float, y: float, r: list[tuple[float, float]]) -> float:
    best = math.inf
    for i in range(len(r)):
        (ax, ay), (bx, by) = r[i - 1], r[i]
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        t = 0.0 if seg == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / seg))
        best = min(best, math.hypot(x - ax - t * dx, y - ay - t * dy))
    return best


def interior(r: list[tuple[float, float]], n: int = 14) -> tuple[float, float]:
    """Un punto bien adentro del anillo (el de mayor distancia al borde en una grilla, refinada una vez):
    el centroide de un departamento con forma de media luna puede caer afuera."""
    xs, ys = [p[0] for p in r], [p[1] for p in r]
    box = [min(xs), min(ys), max(xs), max(ys)]
    best = (-1.0, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    for _ in range(2):
        w, h = (box[2] - box[0]) / n, (box[3] - box[1]) / n
        for i in range(n + 1):
            for j in range(n + 1):
                x, y = box[0] + i * w, box[1] + j * h
                if _inside(x, y, r):
                    d = _edge_dist(x, y, r)
                    if d > best[0]:
                        best = (d, x, y)
        box = [best[1] - w, best[2] - h, best[1] + w, best[2] + h]
    return round(best[1], 1), round(best[2], 1)


def _path(rings: list[list[tuple[float, float]]]) -> str:
    out = []
    for r in rings:
        pts = [f"{x:.1f} {y:.1f}" for x, y in r]
        out.append("M" + "L".join(pts) + "Z")
    return "".join(out)


def build(src: Path = SRC) -> dict:
    from enso.geo import department_names

    data = json.loads(gzip.decompress(src.read_bytes()))
    scale = data["scale"]
    names = department_names()
    tol = TOL * K
    deps = []
    for code, d in sorted(data["departments"].items()):
        rings, biggest = [], []
        for poly in d["polys"]:
            outer = _dp(_ring(poly[0], scale), tol)
            if len(outer) < 4 or _area(outer) < MIN_AREA:
                continue
            rings.append(outer)
            if _area(outer) > _area(biggest or [(0, 0)] * 3):
                biggest = outer
            rings += [h for h in (_dp(_ring(x, scale), tol) for x in poly[1:]) if len(h) >= 4 and _area(h) >= MIN_AREA]
        deps.append({"code": code, "name": names.get(code, code), "d": _path(rings), "label": interior(biggest)})
    points = {}
    for level in ("provinces", "districts"):
        for code, d in data[level].items():
            outer = max((_ring(p[0], scale) for p in d["polys"]), key=_area)
            points[code] = list(interior(outer, 8))
    w, h = project(BOX[2], BOX[1])
    return {"source": data.get("source", ""), "generatedBy": "python -m tools.build_peru_map",
            "width": round(w, 1), "height": round(h, 1),
            "lonLat": {"lon0": BOX[0], "lat1": BOX[3], "k": K, "cos": round(COS, 6)},
            "departments": deps, "points": dict(sorted(points.items()))}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    out = build()
    args.out.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{args.out}: {args.out.stat().st_size / 1024:.0f} KB, {len(out['departments'])} departamentos, "
          f"{len(out['points'])} puntos")


if __name__ == "__main__":
    main()
