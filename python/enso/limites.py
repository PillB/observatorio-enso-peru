"""Ubica un punto (latitud, longitud) en el distrito, la provincia o el departamento del Perú que lo contiene.

Usa los límites del IGN (``data/limites-ign.json.gz``, construido por ``tools.build_limites``) y responde
con el nivel más fino que el punto permite afirmar:

- Si la fuente da la incertidumbre del punto (``accuracy_km``: el epicentro de un sismo se conoce con
  unos km de error), y el punto está más cerca que eso del borde del distrito, se sube a la provincia;
  si también está cerca del borde de la provincia, al departamento.
- Los distritos creados después de los límites de la fuente no tienen polígono: el punto cae en el
  distrito del que se separaron. En esas provincias el distrito sale con confianza menor y una nota.
- Donde la fuente une distritos (``120699`` Mazamari - Pangoa) se devuelve la provincia.
- Los sismos frente a la costa no caen en ningún polígono: si el punto está en el mar (al oeste o
  suroeste de la costa) a menos de ``max_km``, se devuelve el departamento más cercano con la distancia.
  En el lago Titicaca, del lado peruano, se devuelve Puno.
"""

from __future__ import annotations

import gzip
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Optional

DATA = Path(__file__).resolve().parent / "data" / "limites-ign.json.gz"
CONF_DISTRICT = 0.95
CONF_DISTRICT_NEWER = 0.75  # la provincia tiene distritos más nuevos que los límites
CONF_PROVINCE = 0.9
CONF_DEPARTMENT = 0.9
CONF_OFFSHORE = 0.75
#: Caja del Perú con margen: lo que cae afuera ni se busca.
PERU_BOX = (-82.5, -19.5, -68.0, 0.5)
#: Lago Titicaca, del lado peruano (la frontera cruza el lago cerca de 69.3° O).
TITICACA = (-70.1, -16.4, -69.3, -15.2)
#: Departamentos con costa: solo frente a ellos un punto fuera de los límites puede estar en el mar.
COASTAL = {"24", "20", "14", "13", "02", "15", "07", "11", "04", "18", "23"}
#: Error de los bordes simplificados (``tools.build_limites``): más cerca que esto, el distrito es dudoso.
EDGE_KM = 0.15


def _inside(x: float, y: float, ring: list[int]) -> bool:
    """Regla par-impar sobre un anillo plano [x0, y0, x1, y1, …]."""
    inside = False
    n = len(ring)
    jx, jy = ring[n - 2], ring[n - 1]
    for k in range(0, n, 2):
        ix, iy = ring[k], ring[k + 1]
        if (iy > y) != (jy > y) and x < (jx - ix) * (y - iy) / (jy - iy) + ix:
            inside = not inside
        jx, jy = ix, iy
    return inside


def _in_polys(x: float, y: float, polys: list[list[list[int]]]) -> bool:
    return any(_inside(x, y, rings[0]) and not any(_inside(x, y, h) for h in rings[1:]) for rings in polys)


def _in_bbox(x: float, y: float, b: list[int], pad: float = 0) -> bool:
    return b[0] - pad <= x <= b[2] + pad and b[1] - pad <= y <= b[3] + pad


class Limits:
    def __init__(self, data: dict, district_codes: Optional[set[str]] = None):
        self.scale = data["scale"]
        self.source = data.get("source", "")
        self.levels = {6: data["districts"], 4: data["provinces"], 2: data["departments"]}
        known = district_codes or set()
        #: Provincias con distritos que no tienen polígono propio.
        self.newer = {c[:4] for c in known if c not in data["districts"]}

    # -- geometría ----------------------------------------------------------------
    def _xy_km(self, lat: float) -> tuple[float, float]:
        """km por unidad de coordenada (x, y) a esa latitud."""
        return 111.32 * math.cos(math.radians(lat)) / self.scale, 110.57 / self.scale

    def _edge(self, x: float, y: float, polys: list[list[list[int]]]) -> tuple[float, float, float]:
        """(km al borde más cercano, x, y de ese punto del borde)."""
        kx, ky = self._xy_km(y / self.scale)
        best = (math.inf, x, y)
        for rings in polys:
            for r in rings:
                n = len(r)
                ax, ay = r[n - 2], r[n - 1]
                for k in range(0, n, 2):
                    bx, by = r[k], r[k + 1]
                    dx, dy = (bx - ax) * kx, (by - ay) * ky
                    px, py = (x - ax) * kx, (y - ay) * ky
                    seg = dx * dx + dy * dy
                    t = 0.0 if seg == 0 else max(0.0, min(1.0, (px * dx + py * dy) / seg))
                    d = math.hypot(px - t * dx, py - t * dy)
                    if d < best[0]:
                        best = (d, ax + t * (bx - ax), ay + t * (by - ay))
                    ax, ay = bx, by
        return best

    def containing(self, level: int, x: float, y: float, prefix: str = "") -> Optional[str]:
        for code, d in self.levels[level].items():
            if code.startswith(prefix) and _in_bbox(x, y, d["bbox"]) and _in_polys(x, y, d["polys"]):
                return code
        return None

    # -- consulta -----------------------------------------------------------------
    def locate(self, lat: float, lon: float, accuracy_km: float = 0.0, max_km: float = 100.0) -> Optional[dict]:
        """{code, confidence, note} del lugar más fino que se puede afirmar, o ``None`` fuera del Perú."""
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            return None
        if not (math.isfinite(lat) and math.isfinite(lon)):
            return None
        if not (PERU_BOX[0] <= lon <= PERU_BOX[2] and PERU_BOX[1] <= lat <= PERU_BOX[3]):
            return None
        x, y = lon * self.scale, lat * self.scale
        acc = max(EDGE_KM, accuracy_km or 0.0)
        dist = self.containing(6, x, y)
        if dist and not dist.endswith("99"):
            km = self._edge(x, y, self.levels[6][dist]["polys"])[0]
            if km >= acc:
                if dist[:4] in self.newer:
                    return {"code": dist, "confidence": CONF_DISTRICT_NEWER,
                            "note": "la provincia tiene distritos más nuevos que los límites"}
                return {"code": dist, "confidence": CONF_DISTRICT, "note": ""}
        prov = dist[:4] if dist else self.containing(4, x, y)
        if prov:
            note = f"a menos de {acc:g} km del límite distrital" if dist and not dist.endswith("99") else \
                "límite distrital no disponible"
            if prov in self.levels[4] and self._edge(x, y, self.levels[4][prov]["polys"])[0] >= acc:
                return {"code": prov, "confidence": CONF_PROVINCE, "note": note}
            return {"code": prov[:2], "confidence": CONF_DEPARTMENT, "note": f"a menos de {acc:g} km del límite provincial"}
        dep = self.containing(2, x, y)
        if dep:
            return {"code": dep, "confidence": CONF_DEPARTMENT, "note": ""}
        if _in_bbox(x, y, [round(v * self.scale) for v in TITICACA]):
            return {"code": "21", "confidence": CONF_OFFSHORE, "offshore": True, "note": "lago Titicaca"}
        return self._offshore(x, y, max_km)

    def _offshore(self, x: float, y: float, max_km: float) -> Optional[dict]:
        pad = max_km / 100 * self.scale
        best = (math.inf, None, x, y)
        for code, d in self.levels[2].items():
            if code in COASTAL and _in_bbox(x, y, d["bbox"], pad):
                km, ex, ey = self._edge(x, y, d["polys"])
                if km < best[0]:
                    best = (km, code, ex, ey)
        km, code, ex, ey = best
        if code is None or km > max_km:
            return None
        # El mar está al oeste o suroeste de la costa; al norte (Ecuador), al sur (Chile) y al este, tierra.
        dx, dy = x - ex, y - ey
        if not (dx < 0 and -dx >= 0.5 * abs(dy)):
            return None
        return {"code": code, "confidence": CONF_OFFSHORE, "offshore": True,
                "note": f"en el mar, a {round(km)} km de la costa"}


@lru_cache(maxsize=1)
def limits() -> Limits:
    from .geo import gazetteer

    return Limits(json.loads(gzip.decompress(DATA.read_bytes())), set(gazetteer().dists))


def locate(lat: float, lon: float, accuracy_km: float = 0.0, max_km: float = 100.0) -> Optional[dict]:
    return limits().locate(lat, lon, accuracy_km, max_km)
