"""Construye ``enso/data/limites-ign.json.gz``: polígonos de distritos, provincias y departamentos del Perú.

Fuente por omisión (``--indeci``): el servicio de límites administrativos del INDECI en GEOSINPAD (capas
``SDE.DISTRITOS``, ``SDE.PROVINCIAS`` y ``SDE.DEPARTAMENTOS``), con los 1 891 distritos vigentes y sus
UBIGEO del INEI: es la cartografía con la que el INDECI ubica los reportes del COEN y las emergencias del
SINPAD, y trae los distritos creados después de 2020 (Putis, Unión Asháninka, Boquerón, Alto Trujillo…).
Información pública del Estado peruano (Ley N° 27806).

Fuente anterior (``--zip`` o ``--src``): límites del Instituto Geográfico Nacional (IGN) publicados por OCHA
en el Humanitarian Data Exchange (``cod-ab-per``, CC BY-IGO), con los límites distritales de 2020: los
distritos creados después no tienen polígono y caen en el distrito del que se separaron; ``enso.limites`` lo
sabe y baja la confianza en esas provincias. Sobre 8 000 puntos al azar, ambas fuentes dan el mismo distrito
en el 98,8 %: la diferencia son los distritos nuevos (0,9 %) y límites interdepartamentales en controversia.

Formato: coordenadas en enteros (grados × 10⁴, unos 11 m), anillos simplificados (Douglas-Peucker) como
listas planas [x0, y0, x1, y1, …], y la caja de cada unidad para descartar rápido.

Uso:
    python -m tools.build_limites [--indeci | --indeci-dir DIR | --src DIR | --zip ARCHIVO]

``--indeci`` (por omisión) baja las tres capas del GEOSINPAD por páginas, respetando su robots.txt (RFC 9309;
el 27 de octubre de 2026 respondía 404: sin reglas); ``--indeci-dir`` usa las páginas ya bajadas
(``{distritos,provincias,departamentos}-*.geojson``). ``--src``: carpeta con per_admin{1,2,3}.geojson de HDX ya
descomprimidos; ``--zip``: el .geojson.zip de HDX bajado a mano (su robots.txt prohíbe la API). Los límites ya
están en el repositorio: esto solo hace falta para una versión nueva.
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
INDECI = "https://geosinpad.indeci.gob.pe/indeci/rest/services/LimitesAdministrativos/limitesAdministrativos/MapServer"
#: Capa del GEOSINPAD y campo con el UBIGEO, por nivel.
INDECI_LAYERS = {"districts": (0, "UBI_DIST", "distritos"), "provinces": (1, "UBI_PROV", "provincias"),
                 "departments": (2, "UBI_DEP", "departamentos")}
SOURCE_INDECI = ("INDECI, GEOSINPAD, límites administrativos (SDE.DISTRITOS, SDE.PROVINCIAS, SDE.DEPARTAMENTOS), "
                 "información pública del Estado peruano, " + INDECI)
#: Registros por página: el servicio admite 2 000, pero las geometrías de 200 distritos ya pesan unos 3 MB.
PAGE = 200


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


def build(src: dict[str, dict], source: str = SOURCE, fields: dict | None = None) -> dict:
    out: dict = {"source": source, "scale": SCALE}
    for level, (_, field, tol) in LEVELS.items():
        field = (fields or {}).get(level, field)
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


def _indeci_query(layer: int, field: str, offset: int) -> str:
    return (f"{INDECI}/{layer}/query?where=1%3D1&outFields={field}&returnGeometry=true&outSR=4326"
            f"&maxAllowableOffset=0.0001&geometryPrecision=5&orderByFields=OBJECTID"
            f"&resultOffset={offset}&resultRecordCount={PAGE}&f=geojson")


def _download_indeci(client: httpx.Client, keep: Path | None = None) -> dict[str, dict]:
    """Las tres capas del GEOSINPAD, por páginas, si su robots.txt lo permite. ``keep`` guarda cada página."""
    robots = Robots(client)
    out = {}
    for level, (layer, field, name) in INDECI_LAYERS.items():
        feats, offset = [], 0
        while True:
            url = _indeci_query(layer, field, offset)
            if robots.allowed(url) is not True:
                raise SystemExit(f"El robots.txt de {httpx.URL(url).host} no permite (o no se sabe si permite) {url}")
            r = client.get(url, timeout=300)
            page = r.raise_for_status().json()
            if keep:
                (keep / f"{name}-{offset:05d}.geojson").write_bytes(r.content)
            feats += page.get("features", [])
            if len(page.get("features", [])) < PAGE:
                break
            offset += PAGE
        out[level] = {"features": feats}
    return out


def _read_indeci(folder: Path) -> dict[str, dict]:
    return {level: {"features": [f for p in sorted(folder.glob(f"{name}-*.geojson"))
                                 for f in json.loads(p.read_text(encoding="utf-8"))["features"]]}
            for level, (_, _, name) in INDECI_LAYERS.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    how = ap.add_mutually_exclusive_group()
    how.add_argument("--indeci", action="store_true", help="bajar del GEOSINPAD del INDECI (por omisión)")
    how.add_argument("--indeci-dir", type=Path, help="páginas del GEOSINPAD ya bajadas")
    how.add_argument("--src", type=Path, help="carpeta con per_admin{1,2,3}.geojson")
    how.add_argument("--zip", type=Path, help=f"el .geojson.zip bajado a mano de {DATASET}")
    ap.add_argument("--keep", type=Path, help="con --indeci: carpeta donde guardar las páginas bajadas")
    a = ap.parse_args(argv)
    if a.src or a.zip:
        src = {k: json.loads((a.src / name).read_text(encoding="utf-8")) for k, (name, _, _) in LEVELS.items()} \
            if a.src else _unzip(a.zip.read_bytes())
        data = build(src)
    else:
        if a.indeci_dir:
            src = _read_indeci(a.indeci_dir)
        else:
            with httpx.Client(headers={"User-Agent": UA}) as client:
                src = _download_indeci(client, a.keep)
        data = build(src, SOURCE_INDECI, {k: f for k, (_, f, _) in INDECI_LAYERS.items()})
    raw = json.dumps(data, separators=(",", ":")).encode()
    OUT.write_bytes(gzip.compress(raw, 9, mtime=0))
    print(f"{OUT}: {len(data['districts'])} distritos, {len(data['provinces'])} provincias, "
          f"{len(data['departments'])} departamentos, {OUT.stat().st_size // 1024} KB comprimido")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
