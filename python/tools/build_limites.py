"""Construye ``enso/data/limites-inei.json.gz``: polígonos de distritos y provincias del Perú.

Fuente: límites distritales y provinciales del INEI (2007) publicados por el
Geoservidor del MINAM y convertidos a GeoJSON simplificado por Juan Eladio
Sánchez Rosas (https://github.com/juaneladio/peru-geojson, licencia MPL 2.0).
El archivo derivado conserva esa licencia (ver ``enso/data/LICENCIAS.md``).

Los límites son de 2007: los distritos creados después (unos 60) no tienen
polígono propio y caen dentro del distrito del que se separaron. ``enso.limites``
lo sabe y baja la confianza del distrito en esas provincias.

Formato: coordenadas en enteros (grados × 10⁴, unos 11 m), anillos como listas
planas [x0, y0, x1, y1, …], y la caja de cada polígono para descartar rápido.

Uso:
    python -m tools.build_limites [--src DIR]   # DIR con los GeoJSON ya descargados
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

import httpx

BASE = "https://raw.githubusercontent.com/juaneladio/peru-geojson/master/"
FILES = {"dist": "peru_distrital_simple.geojson", "prov": "peru_provincial_simple.geojson"}
OUT = Path(__file__).resolve().parents[1] / "enso" / "data" / "limites-inei.json.gz"
SCALE = 10_000


def _rings(geom: dict) -> list[list[list[int]]]:
    """Polígonos como listas de anillos (el primero es el borde exterior; los demás, huecos)."""
    if not geom:
        return []
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    out = []
    for poly in polys:
        rings = []
        for ring in poly:
            flat: list[int] = []
            last = None
            for lon, lat, *_ in ring:
                pt = (round(lon * SCALE), round(lat * SCALE))
                if pt != last:
                    flat.extend(pt)
                    last = pt
            if len(flat) >= 8:
                rings.append(flat)
        if rings:
            out.append(rings)
    return out


def _bbox(polys: list[list[list[int]]]) -> list[int]:
    xs = [v for p in polys for v in p[0][0::2]]
    ys = [v for p in polys for v in p[0][1::2]]
    return [min(xs), min(ys), max(xs), max(ys)]


def build(src: dict[str, dict]) -> dict:
    out = {"source": "INEI 2007 (Geoservidor MINAM) vía github.com/juaneladio/peru-geojson (MPL 2.0)",
           "scale": SCALE, "districts": {}, "provinces": {}}
    for f in src["dist"]["features"]:
        code = f["properties"]["IDDIST"]
        polys = _rings(f.get("geometry"))
        if polys:
            out["districts"][code] = {"bbox": _bbox(polys), "polys": polys}
    for f in src["prov"]["features"]:
        code = f["properties"].get("FIRST_IDPR") or f["properties"].get("IDPROV")
        polys = _rings(f.get("geometry"))
        if code and polys:
            out["provinces"][code] = {"bbox": _bbox(polys), "polys": polys}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", type=Path)
    a = ap.parse_args(argv)
    if a.src:
        src = {k: json.loads((a.src / f).read_text(encoding="utf-8")) for k, f in FILES.items()}
    else:
        src = {k: httpx.get(BASE + f, timeout=120).raise_for_status().json() for k, f in FILES.items()}
    data = build(src)
    raw = json.dumps(data, separators=(",", ":")).encode()
    OUT.write_bytes(gzip.compress(raw, 9, mtime=0))
    print(f"{OUT}: {len(data['districts'])} distritos, {len(data['provinces'])} provincias, "
          f"{len(raw) // 1024} KB sin comprimir, {OUT.stat().st_size // 1024} KB comprimido")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
