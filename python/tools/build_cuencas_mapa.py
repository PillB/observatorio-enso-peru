"""Construye ``public/assets/cuencas-mapa.json``: las 231 unidades hidrográficas de la ANA para los dos mapas (el de
alertas y el de la memoria de desastres).

Sale de ``enso/data/cuencas.json.gz`` (``tools.build_lugares``: ANA, metodología Pfafstetter, vía el geoportal de la
IDEP) con la misma proyección que ``public/assets/peru-map.json`` (``tools.build_peru_map``), así las capas se
superponen. Cada unidad trae su trazo SVG (simplificado a 0,02°, unos 2 km), un punto interior para su nombre y su
nivel Pfafstetter; ``districts`` dice la cuenca de cada distrito que tiene el 80 % o más de su área en una sola
(``enso.lugares.district_basin``).

Uso:
    python -m tools.build_cuencas_mapa
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

from enso.lugares import DATA, DISTRICT_BASIN_SHARE
from tools.build_historico_mapa import _short
from tools.build_peru_map import K, _area, _dp, _ring, interior

ROOT = Path(__file__).resolve().parents[2]
SRC = DATA / "cuencas.json.gz"
OUT = ROOT / "public" / "assets" / "cuencas-mapa.json"
TOL = 0.02
MIN_AREA = 0.3


def build(src: Path = SRC) -> dict:
    data = json.loads(gzip.decompress(src.read_bytes()))
    scale = data["scale"]
    units = {}
    for code, u in sorted(data["units"].items()):
        rings, biggest = [], None
        for poly in u["polys"]:
            for i, flat in enumerate(poly):
                ring = _dp(_ring(flat, scale), TOL * K)
                if len(ring) < 4 or (_area(ring) < MIN_AREA and (i or rings)):
                    continue
                rings.append(ring)
                if i == 0 and (biggest is None or _area(ring) > _area(biggest)):
                    biggest = ring
        if not rings:  # unidad diminuta (la intercuenca 13933, 6 km²): un cuadradito en su lugar
            ring = _ring(max(u["polys"], key=lambda p: len(p[0]))[0], scale)
            x, y = sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)
            rings = [[(x - .6, y - .6), (x + .6, y - .6), (x + .6, y + .6), (x - .6, y + .6)]]
        units[code] = {"n": u["name"], "l": u["level"], "d": _short(rings), "c": list(interior(biggest or rings[0], 6))}
    districts = {c: parts[0][0] for c, parts in sorted(data.get("districts", {}).items())
                 if parts and parts[0][1] >= DISTRICT_BASIN_SHARE and parts[0][0] in units}
    return {"source": data.get("source", ""), "generatedBy": "python -m tools.build_cuencas_mapa",
            "districtShare": DISTRICT_BASIN_SHARE, "units": units, "districts": districts}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    out = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{args.out}: {args.out.stat().st_size / 1024:.0f} KB, {len(out['units'])} unidades, "
          f"{len(out['districts'])} distritos con su cuenca")


if __name__ == "__main__":
    main()
