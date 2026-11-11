"""Ubicar coordenadas en un departamento del Perú con los límites oficiales.

Los focos de calor de FIRMS y las zonas de riesgo de incendio del SENAMHI solo
traen coordenadas o polígonos, sin nombres de lugares. Los límites son la capa
``SDE.DEPARTAMENTOS`` del servicio de límites administrativos del INDECI
(GEOSINPAD), simplificada a ~1 km (``data/departamentos.geojson``, ver
``data/LEEME-limites.md``). Con esa precisión un punto a menos de ~1 km de un
límite puede quedar en el departamento vecino; para contar focos por
departamento basta.

Sin dependencias: punto en polígono por paridad de cruces (anillos exteriores
y huecos), con un recuadro por departamento para descartar rápido.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .geo import department_names, key

DATA = Path(__file__).resolve().parent / "data" / "departamentos.geojson"
Ring = list[tuple[float, float]]  # (lon, lat)


@dataclass
class Area:
    code: str  # UBIGEO de 2 dígitos
    name: str
    polygons: list[list[Ring]]  # cada polígono: anillo exterior y huecos
    bbox: tuple[float, float, float, float]  # lon0, lat0, lon1, lat1

    def contains(self, lon: float, lat: float) -> bool:
        x0, y0, x1, y1 = self.bbox
        if not (x0 <= lon <= x1 and y0 <= lat <= y1):
            return False
        return any(_in_rings(lon, lat, rings) for rings in self.polygons)


def _in_ring(x: float, y: float, ring: Ring) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _in_rings(x: float, y: float, rings: list[Ring]) -> bool:
    return bool(rings) and _in_ring(x, y, rings[0]) and not any(_in_ring(x, y, h) for h in rings[1:])


def _polygons(geom: dict) -> list[list[Ring]]:
    coords = geom.get("coordinates") or []
    polys = [coords] if geom.get("type") == "Polygon" else coords if geom.get("type") == "MultiPolygon" else []
    return [[[(float(p[0]), float(p[1])) for p in ring] for ring in poly if len(ring) >= 4] for poly in polys]


def _code(props: dict, by_name: dict[str, str]) -> Optional[str]:
    for k in ("CCDD", "IDDPTO", "CODDEP", "UBIGEO", "IDDEP", "CD_DPTO"):
        v = str(props.get(k) or "").strip()
        if v[:2].isdigit():
            return v[:2]
    for k in ("NOMBDEP", "DEPARTAMEN", "NOMBDEPA", "DEPARTAMENTO", "NOMBRE", "NOM_DEP"):
        v = by_name.get(key(str(props.get(k) or "")))
        if v:
            return v
    return None


def load(data: dict) -> list[Area]:
    names = department_names()
    by_name = {key(n): c for c, n in names.items()}
    out = []
    for f in data.get("features") or []:
        code = _code(f.get("properties") or {}, by_name)
        polys = _polygons(f.get("geometry") or {})
        if not code or not polys:
            continue
        pts = [p for poly in polys for p in poly[0]]
        out.append(Area(code, names.get(code, code), polys,
                        (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))))
    return out


@lru_cache(maxsize=1)
def departments() -> list[Area]:
    return load(json.loads(DATA.read_text(encoding="utf-8")))


#: Distancia máxima (grados, ~2 km) a la que un punto fuera de todo polígono se asigna al límite más
#: cercano: la simplificación a ~1 km recorta orillas, como las del lago Titicaca, donde se queman totorales.
NEAR = 0.02


def _seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return ((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2) ** 0.5


def _edge_dist(a: Area, lon: float, lat: float) -> float:
    x0, y0, x1, y1 = a.bbox
    if not (x0 - NEAR <= lon <= x1 + NEAR and y0 - NEAR <= lat <= y1 + NEAR):
        return float("inf")
    return min(_seg_dist(lon, lat, *r[i - 1], *r[i]) for poly in a.polygons for r in poly for i in range(len(r)))


def department_at(lat: float, lon: float, areas: Optional[list[Area]] = None, near: float = NEAR) -> Optional[str]:
    """UBIGEO del departamento que contiene el punto (o cuyo límite está a menos de ``near`` grados),
    o None si cae fuera del Perú."""
    if areas is None:
        # Primero los límites del IGN a ~110 m (``enso.limites``); los de esta capa (~1 km) quedan para
        # los puntos que caen justo afuera (orilla, borde simplificado).
        from .limites import limits

        lim = limits()
        x, y = lon * lim.scale, lat * lim.scale
        hit = lim.containing(2, x, y)
        if hit:
            return hit
    areas = areas if areas is not None else departments()
    for a in areas:
        if a.contains(lon, lat):
            return a.code
    if near <= 0:
        return None
    d, code = min(((_edge_dist(a, lon, lat), a.code) for a in areas), default=(float("inf"), None))
    return code if d <= near else None


def ring_area(ring: Ring) -> float:
    """Área aproximada en grados² (fórmula del polígono); sirve para comparar partes."""
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]))) / 2


def ring_center(ring: Ring) -> tuple[float, float]:
    """Centroide de un anillo (lon, lat); si el anillo es degenerado, el promedio de sus puntos."""
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        c = x0 * y1 - x1 * y0
        a += c
        cx += (x0 + x1) * c
        cy += (y0 + y1) * c
    if abs(a) < 1e-12:
        return sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)
    return cx / (3 * a), cy / (3 * a)


def polygon_departments(geom: dict, areas: Optional[list[Area]] = None, sample: bool = False) -> dict[str, float]:
    """Departamentos que toca un (multi)polígono, con el área de las partes que caen en cada uno.
    Cada parte se ubica por su centroide (o, si queda fuera del Perú, por su primer vértice dentro).

    ``sample``: para partes grandes que cruzan varios departamentos (los avisos de lluvia del SENAMHI
    cubren media sierra con un solo polígono), el área de cada parte se reparte entre los departamentos
    con una grilla de hasta ``SAMPLE_POINTS`` puntos; una parte más chica que una celda va por su centroide."""
    areas = areas if areas is not None else departments()
    out: dict[str, float] = {}
    for rings in _polygons(geom):
        ext = rings[0]
        shares = _sampled(rings, areas) if sample else {}
        if shares:
            for code, a in shares.items():
                out[code] = out.get(code, 0.0) + a
            continue
        x, y = ring_center(ext)
        code = department_at(y, x, areas, near=0) if _in_rings(x, y, rings) else None
        code = code or next((c for c in (department_at(py, px, areas, near=0) for px, py in ext) if c), None)
        if code:
            out[code] = out.get(code, 0.0) + ring_area(ext)
    return out


#: Puntos de la grilla con que ``polygon_departments(sample=True)`` reparte una parte entre departamentos.
SAMPLE_POINTS = 400


def _sampled(rings: list[Ring], areas: list[Area]) -> dict[str, float]:
    ext = rings[0]
    x0, y0 = min(p[0] for p in ext), min(p[1] for p in ext)
    x1, y1 = max(p[0] for p in ext), max(p[1] for p in ext)
    step = max(0.02, ((x1 - x0) * (y1 - y0) / SAMPLE_POINTS) ** 0.5)
    hits: dict[str, int] = {}
    y = y0 + step / 2
    while y < y1:
        x = x0 + step / 2
        while x < x1:
            if _in_rings(x, y, rings):
                code = department_at(y, x, areas, near=0)
                if code:
                    hits[code] = hits.get(code, 0) + 1
            x += step
        y += step
    total = sum(hits.values())
    area = ring_area(ext)
    return {c: area * n / total for c, n in hits.items()} if total else {}


# --- Formas para el mapa de alertas ---------------------------------------------------------------------------------

#: Las formas de los avisos se publican con 2 decimales (~1 km), simplificadas a ``SHAPE_TOLERANCE`` grados, sin las
#: partes de menos de ``SHAPE_MIN_AREA`` grados² (~2 km²) y con hasta ``SHAPE_MAX_POINTS`` vértices por aviso.
SHAPE_TOLERANCE = 0.02
SHAPE_MIN_AREA = 0.0002
SHAPE_MAX_POINTS = 4000


def _simplify(ring: Ring, tol: float) -> Ring:
    """Douglas-Peucker sobre un anillo cerrado (sin recursión)."""
    if len(ring) <= 4:
        return ring
    keep = [False] * len(ring)
    keep[0] = keep[-1] = True
    stack = [(0, len(ring) - 1)]
    while stack:
        a, b = stack.pop()
        best, idx = 0.0, -1
        for i in range(a + 1, b):
            d = _seg_dist(*ring[i], *ring[a], *ring[b])
            if d > best:
                best, idx = d, i
        if idx >= 0 and best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(ring, keep) if k]


def shape_rings(geom: dict, tol: float = SHAPE_TOLERANCE, min_area: float = SHAPE_MIN_AREA) -> list[list[list[float]]]:
    """Los anillos de un (multi)polígono GeoJSON para dibujarlo: [[lon, lat], …] con 2 decimales, simplificados.
    Los huecos se conservan (el mapa los pinta con la regla par-impar)."""
    out = []
    for rings in _polygons(geom):
        for ring in rings:
            if ring_area(ring) < min_area:
                continue
            pts = []
            for x, y in _simplify(ring, tol):
                p = [round(x, 2), round(y, 2)]
                if not pts or p != pts[-1]:
                    pts.append(p)
            if len(pts) >= 4:
                out.append(pts)
    return out


def cap_rings(rings: list[list[list[float]]], max_points: int = SHAPE_MAX_POINTS) -> list[list[list[float]]]:
    """Los anillos más grandes que caben en ``max_points`` vértices (los chicos no se ven a la escala del mapa)."""
    out, n = [], 0
    for r in sorted(rings, key=lambda r: -ring_area([tuple(p) for p in r])):
        if n + len(r) > max_points:
            continue
        out.append(r)
        n += len(r)
    return out


def grid_points(points: list[tuple[float, float]], step: float = 0.1, limit: int = 400) -> list[dict]:
    """Puntos (lat, lon) agrupados en celdas de ``step`` grados (~11 km): el centro de cada celda y cuántos caen en
    ella, las ``limit`` celdas con más puntos."""
    cells: dict[tuple[int, int], int] = {}
    for lat, lon in points:
        k = (int((lat + 90) // step), int((lon + 180) // step))
        cells[k] = cells.get(k, 0) + 1
    top = sorted(cells.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return [{"lat": round((i + 0.5) * step - 90, 3), "lon": round((j + 0.5) * step - 180, 3), "n": n}
            for (i, j), n in top]
