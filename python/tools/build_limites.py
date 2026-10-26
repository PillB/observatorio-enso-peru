"""Construye ``enso/data/limites-ign.json.gz``: polígonos de distritos, provincias y departamentos del Perú.

Fuente: límites administrativos del Instituto Geográfico Nacional (IGN), publicados por OCHA en el
Humanitarian Data Exchange (conjunto ``cod-ab-per``, licencia CC BY-IGO; ver ``docs/atribucion-licencias.md``).
Los códigos son los UBIGEO del INEI con el prefijo ``PE``. La versión de 2026 trae los límites distritales
vigentes en 2020: los distritos creados después (una veintena) no tienen polígono y caen en el distrito
del que se separaron; ``enso.limites`` lo sabe y baja la confianza en esas provincias.

Formato: coordenadas en enteros (grados × 10⁴, unos 11 m), anillos simplificados (Douglas-Peucker) como
listas planas [x0, y0, x1, y1, …], y la caja de cada unidad para descartar rápido.

Uso:
    python -m tools.build_limites [--src DIR | --zip ARCHIVO]

``--src``: carpeta con per_admin{1,2,3}.geojson ya descomprimidos; ``--zip``: el .geojson.zip bajado a mano
de la página del conjunto. Sin ninguno de los dos se baja de HDX, respetando su robots.txt (RFC 9309), como
todo lo que pide el proyecto: prohíbe la API (``Disallow: /api/``, leído el 26 de octubre de 2026), así que el
archivo se baja a mano y se pasa con ``--zip``. Los límites ya están en el repositorio: esto solo hace falta
para una versión nueva.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import zipfile
from pathlib import Path

import httpx

from enso.fetch import UA
from enso.reach import Robots

PACKAGE = "https://data.humdata.org/api/3/action/package_show?id=cod-ab-per"
OUT = Path(__file__).resolve().parents[1] / "enso" / "data" / "limites-ign.json.gz"
SCALE = 10_000
#: Tolerancia de simplificación por nivel, en unidades de SCALE (10 ≈ 110 m).
LEVELS = {"districts": ("per_admin3.geojson", "adm3_pcode", 10),
          "provinces": ("per_admin2.geojson", "adm2_pcode", 20),
          "departments": ("per_admin1.geojson", "adm1_pcode", 40)}
DATASET = "https://data.humdata.org/dataset/cod-ab-per"
SOURCE = f"Instituto Geográfico Nacional (IGN), vía OCHA HDX «cod-ab-per» (CC BY-IGO), {DATASET}"


def _simplify(pts: list[tuple[int, int]], tol: int) -> list[tuple[int, int]]:
    """Douglas-Peucker iterativo sobre un anillo cerrado."""
    if len(pts) < 5:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    # El anillo empieza y termina en el mismo punto: se parte también en el punto más lejano.
    far = max(range(len(pts)), key=lambda i: (pts[i][0] - pts[0][0]) ** 2 + (pts[i][1] - pts[0][1]) ** 2)
    keep[far] = True
    stack = [(0, far), (far, len(pts) - 1)]
    tol2 = tol * tol
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        (ax, ay), (bx, by) = pts[a], pts[b]
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            if seg == 0:
                d2 = (px - ax) ** 2 + (py - ay) ** 2
            else:
                cross = dx * (py - ay) - dy * (px - ax)
                d2 = cross * cross / seg
            if d2 > best:
                best, idx = d2, i
        if best > tol2:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def _rings(geom: dict, tol: int) -> list[list[list[int]]]:
    """Polígonos como listas de anillos (el primero es el borde exterior; los demás, huecos)."""
    if not geom:
        return []
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    out = []
    for poly in polys:
        rings = []
        for n, ring in enumerate(poly):
            pts: list[tuple[int, int]] = []
            for lon, lat, *_ in ring:
                pt = (round(lon * SCALE), round(lat * SCALE))
                if not pts or pt != pts[-1]:
                    pts.append(pt)
            pts = _simplify(pts, tol)
            if len(pts) >= 4:
                rings.append([v for p in pts[:-1] for v in p])
            elif n == 0:
                break  # islote más chico que la tolerancia
        if rings:
            out.append(rings)
    return out


def _bbox(polys: list[list[list[int]]]) -> list[int]:
    xs = [v for p in polys for v in p[0][0::2]]
    ys = [v for p in polys for v in p[0][1::2]]
    return [min(xs), min(ys), max(xs), max(ys)]


def build(src: dict[str, dict]) -> dict:
    out: dict = {"source": SOURCE, "scale": SCALE}
    for level, (_, field, tol) in LEVELS.items():
        out[level] = {}
        for f in src[level]["features"]:
            code = f["properties"][field].removeprefix("PE")
            polys = _rings(f.get("geometry"), tol)
            if polys:
                out[level][code] = {"bbox": _bbox(polys), "polys": polys}
    return out


def _unzip(data: bytes) -> dict[str, dict]:
    z = zipfile.ZipFile(io.BytesIO(data))
    return {level: json.loads(z.read(name)) for level, (name, _, _) in LEVELS.items()}


def _download(client: httpx.Client) -> dict[str, dict]:
    """De HDX, solo lo que su robots.txt permite: la API del catálogo y luego el archivo del recurso (y cada
    redirección, que puede llevar a otro servidor)."""
    robots = Robots(client)

    def get(url: str, timeout: float) -> httpx.Response:
        for _ in range(6):
            allowed = robots.allowed(url)
            if allowed is not True:
                why = "no permite" if allowed is False else \
                    f"no respondió ({robots.failure(url) or 'sin respuesta'}) y no se sabe si permite"
                raise SystemExit(f"El robots.txt de {httpx.URL(url).host} {why} {url}: no se pide. Bajar a mano "
                                 f"el .geojson.zip de {DATASET} y pasarlo con --zip.")
            r = client.get(url, timeout=timeout, follow_redirects=False)  # cada salto con su robots.txt
            if not r.is_redirect:
                return r.raise_for_status()
            url = str(r.next_request.url)
        raise SystemExit(f"Demasiadas redirecciones desde {url}")

    meta = get(PACKAGE, 60).json()["result"]
    url = next(r["url"] for r in meta["resources"] if r["name"].endswith(".geojson.zip"))
    return _unzip(get(url, 600).content)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    how = ap.add_mutually_exclusive_group()
    how.add_argument("--src", type=Path, help="carpeta con per_admin{1,2,3}.geojson")
    how.add_argument("--zip", type=Path, help=f"el .geojson.zip bajado a mano de {DATASET}")
    a = ap.parse_args(argv)
    if a.src:
        src = {k: json.loads((a.src / name).read_text(encoding="utf-8")) for k, (name, _, _) in LEVELS.items()}
    elif a.zip:
        src = _unzip(a.zip.read_bytes())
    else:
        with httpx.Client(headers={"User-Agent": UA}) as client:
            src = _download(client)
    data = build(src)
    raw = json.dumps(data, separators=(",", ":")).encode()
    OUT.write_bytes(gzip.compress(raw, 9, mtime=0))
    print(f"{OUT}: {len(data['districts'])} distritos, {len(data['provinces'])} provincias, "
          f"{len(data['departments'])} departamentos, {OUT.stat().st_size // 1024} KB comprimido")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
