"""Construye ``public/assets/historico/mapa.json``: provincias y distritos del Perú para la pestaña
«Memoria de desastres».

Usa los mismos límites del IGN (``enso/data/limites-ign.json.gz``, CC BY-IGO) y la misma proyección que
``public/assets/peru-map.json`` (``tools.build_peru_map``), así los dos mapas se superponen y los
departamentos se toman de aquel archivo. Los distritos se simplifican más (0,02°, unos 2 km): a la
escala del mapa un distrito pequeño mide pocos píxeles y lo que importa es su color, no su borde.

Uso:
    python -m tools.build_historico_mapa
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

from tools.build_peru_map import K, SRC, _area, _dp, _ring, interior

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "public" / "assets" / "historico" / "mapa.json"
TOL = {"provinces": 0.012, "districts": 0.02}
MIN_AREA = {"provinces": 0.5, "districts": 0.15}


def _short(rings: list[list[tuple[float, float]]]) -> str:
    """Trazo SVG con coordenadas relativas y un decimal: la mitad de bytes que el absoluto."""
    out = []
    for r in rings:
        x0, y0 = round(r[0][0] * 10), round(r[0][1] * 10)
        seg = [f"M{x0 / 10:g} {y0 / 10:g}"]
        px, py = x0, y0
        rel = []
        for x, y in r[1:]:
            ix, iy = round(x * 10), round(y * 10)
            if ix == px and iy == py:
                continue
            rel.append(f"{(ix - px) / 10:g} {(iy - py) / 10:g}")
            px, py = ix, iy
        out.append(seg[0] + "l" + " ".join(rel) + "z")
    return "".join(out)


def build(src: Path = SRC) -> dict:
    data = json.loads(gzip.decompress(src.read_bytes()))
    scale = data["scale"]
    out: dict = {"source": data.get("source", ""), "generatedBy": "python -m tools.build_historico_mapa"}
    for level in ("provinces", "districts"):
        tol = TOL[level] * K
        feats = {}
        for code, d in sorted(data[level].items()):
            rings, biggest = [], None
            for poly in d["polys"]:
                outer = _dp(_ring(poly[0], scale), tol)
                if len(outer) < 4:
                    continue
                if _area(outer) < MIN_AREA[level] and rings:
                    continue
                rings.append(outer)
                if biggest is None or _area(outer) > _area(biggest):
                    biggest = outer
            if not rings:  # distrito diminuto: un cuadradito en su punto interior para poder pintarlo
                ring = _ring(max(d["polys"], key=lambda p: len(p[0]))[0], scale)
                x, y = sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)
                rings = [[(x - .6, y - .6), (x + .6, y - .6), (x + .6, y + .6), (x - .6, y + .6)]]
                biggest = rings[0]
            feats[code] = {"d": _short(rings), "c": list(interior(biggest, 6))}
        out[level] = feats
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    out = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{args.out}: {args.out.stat().st_size / 1024:.0f} KB, {len(out['provinces'])} provincias, "
          f"{len(out['districts'])} distritos")


if __name__ == "__main__":
    main()
