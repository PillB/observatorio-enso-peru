"""Ubica un evento más fino que su distrito: el centro poblado que nombra la fuente y la cuenca.

Se usa **después** de saber el distrito y solo busca dentro de él, así que nunca cambia el distrito de un evento.

- ``Lugares.find(distrito, texto)``: centros poblados del distrito (INEI 2017, IGN y SDOT, ver
  ``tools.build_lugares``) que el texto nombra. En el texto libre (la descripción, un titular) el nombre debe
  ir tras una palabra que lo presenta como lugar («caserío Cachaquito», «sector de Panamá», «C.P. Pampamarca»,
  «localidades de Puerto Roca y Quimarotipiari»); en un campo de lugar (la columna «Ubicación» de una fuente,
  la del cuadro de ubicación del COEN) basta el nombre. No cuentan el nombre del departamento, de la provincia
  ni del distrito (no agregan nada), palabras genéricas («zona urbana», «cercado») ni un nombre que en el
  distrito tienen dos lugares a más de 2 km uno del otro (homónimos: no se adivina).
- ``basin_at(lat, lon)``: la unidad hidrográfica de la ANA que contiene el punto. ``district_basin(código)``:
  la del distrito si el 80 % o más de él está en una sola.

Cada lugar sale con su **radio** de incertidumbre: 1 km para un centro poblado (la mediana de la distancia
entre el punto del INEI y el del IGN para un mismo código es 0,8 km), 5 km si el INEI y el IGN lo ubican a
más de 5 km uno del otro.
"""

from __future__ import annotations

import gzip
import json
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .geo import key
from .limites import _in_bbox, _in_polys

DATA = Path(__file__).resolve().parent / "data"
PLACE_RADIUS_KM = 1.0
#: Dos lugares del mismo nombre en un distrito a más de esto son homónimos; más cerca, el mismo lugar.
SAME_PLACE_KM = 2.0
#: Varios lugares más dispersos que esto no dan un punto (el evento abarca buena parte del distrito).
MAX_SPREAD_KM = 10.0
#: Fracción del distrito que debe caer en una cuenca para dar la cuenca de un registro de distrito.
DISTRICT_BASIN_SHARE = 0.8

#: Palabras que presentan un lugar poblado (texto ya sin tildes ni mayúsculas, ver ``geo.key``).
CUE = (r"(?:localidad(?:es)?|caserios?|sector(?:es)?|centros?\s+poblados?(?:\s+menor(?:es)?)?|"
       r"c\s?\.\s?p\s?\.?(?:\s?m\s?\.?)?|cp|cpm|anexos?|comunidad(?:es)?(?:\s+(?:campesinas?|nativas?))?|"
       r"cc\s?\.?\s?(?:cc|nn)\s?\.?|c\s?\.\s?[cn]\s?\.|barrios?|urbanizacion(?:es)?|urb\s?\.|aa\s?\.?\s?hh\s?\.?|"
       r"a\s?\.\s?h\s?\.|asentamientos?\s+humanos?|pueblos?\s+jovenes|pueblo\s+joven|p\s?\.\s?j\s?\.|parajes?|"
       r"pagos?|fundos?|haciendas?|centros?\s+de\s+poblacion|poblados?|ccpp|villa|zonas?(?=\s+de\s))")
_CUE = re.compile(r"(?<![a-z0-9])" + CUE + r"(?![a-z0-9])\s*(?:(?:de|del|de\s+la|de\s+los|de\s+las|denominad[oa]s?|"
                  r"llamad[oa]s?)\s+)?[:\-]?\s*")
#: Dónde termina el nombre del lugar.
_STOP = re.compile(r"[.;:()\[\]«»\"]|\s-\s|\s(?:(?:distrito|dist|provincia|prov|region|departamento|dpto|dep|"
                   r"jurisdiccion|perteneciente|km|kilometros?|en|que|donde|por|con|cerca|frente|margen|ante|producto|"
                   r"debido|se|a|al|hacia|desde|entre|sobre|tras|del\s+distrito|de\s+la\s+provincia)\b|"
                   r"(?:ubicad|afect|ocasion|caus|dej|registr|provoc|origin|sufr|soport)\w*)")
_LIST = re.compile(r"\s*,\s*|\s+y\s+|\s+e\s+|\s*/\s*")
#: Nombres que no ubican nada por sí solos.
GENERIC = frozenset(
    "urbana rural centro cercado capital comunidad alto bajo alta baja zona sector localidad anexo caserio barrio "
    "pueblo ciudad villa valle norte sur este oeste central principal agricola agropecuario agropecuaria vivienda "
    "viviendas vial quebrada rio carretera via puente parte zona urbana zona rural centro poblado varios varias "
    "diversos diversas otros otras distrito provincia region todo toda todos todas mismo misma afectado afectada "
    "afectados afectadas nuevo nueva".split())
_GENERIC_PHRASE = re.compile(r"^(?:zona|parte|sector)\s+(?:alta|baja|urbana|rural|norte|sur|este|oeste|central)$")


def _norm(text: str) -> str:
    t = key(text or "")
    t = re.sub(r"[´`’‘']", "", t)
    t = re.sub(r"[^a-z0-9 .,;:()/\-\[\]«»\"ñ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def name_key(name: str) -> str:
    """Clave de un nombre de lugar: sin tildes, signos ni espacios dobles («C.P. Ñaña» → «c p nana»)."""
    t = re.sub(r"[^a-z0-9 ]", " ", key(name or "").replace("ñ", "n"))
    return re.sub(r"\s+", " ", t).strip()


def title(name: str) -> str:
    small = {"de", "del", "la", "las", "los", "el", "y", "e", "en"}
    words = (name or "").lower().split()
    return " ".join(w if (i and w in small) else w[:1].upper() + w[1:] for i, w in enumerate(words))


@dataclass
class Place:
    name: str
    lat: float
    lon: float
    category: str
    code: str  # código de centro poblado del INEI (10 dígitos) o vacío
    population: int
    layer: str  # inei | ign
    radius_km: float
    evidence: str = ""
    district: str = ""
    basin: Optional[dict] = None

    def as_dict(self) -> dict:
        out = {"name": self.name, "lat": round(self.lat, 5), "lon": round(self.lon, 5), "radiusKm": self.radius_km,
               "rung": "centro-poblado", "layer": self.layer}
        if self.code:
            out["code"] = self.code
        if self.category:
            out["category"] = self.category
        if self.evidence:
            out["evidence"] = self.evidence
        if self.basin:
            out["basin"] = self.basin
        return out


@dataclass
class Match:
    places: list[Place] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)  # nombres con homónimos en el distrito

    @property
    def place(self) -> Optional[Place]:
        return self.places[0] if self.places else None

    def point(self) -> Optional[tuple[float, float, float]]:
        """(lat, lon, radio en km) de los lugares: el del único, o el punto medio de varios con el radio que los
        cubre; None si no hay lugares o están a más de ``MAX_SPREAD_KM`` del punto medio."""
        if not self.places:
            return None
        if len(self.places) == 1:
            p = self.places[0]
            return p.lat, p.lon, p.radius_km
        lat = sum(p.lat for p in self.places) / len(self.places)
        lon = sum(p.lon for p in self.places) / len(self.places)
        radius = max(_km(lat, lon, p.lat, p.lon) + p.radius_km for p in self.places)
        return (lat, lon, round(radius, 1)) if radius <= MAX_SPREAD_KM else None


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return math.hypot((lat1 - lat2) * 110.57, (lon1 - lon2) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2)))


class Lugares:
    def __init__(self, data: dict, basins: Optional["Basins"] = None):
        self.scale = data["scale"]
        self.rows = data["districts"]
        self.basins = basins
        self._index: dict[str, dict[str, list[list]]] = {}

    def index(self, district: str) -> dict[str, list[list]]:
        if district not in self._index:
            idx: dict[str, list[list]] = {}
            for row in self.rows.get(district, []):
                k = name_key(row[0])
                if len(k) >= 3:
                    idx.setdefault(k, []).append(row)
            self._index[district] = idx
        return self._index[district]

    def _place(self, rows: list[list], district: str, evidence: str) -> Optional[Place]:
        """El lugar de esas filas (un mismo nombre), o None si son homónimos a más de ``SAME_PLACE_KM``."""
        pts = [(r[2] / self.scale, r[1] / self.scale) for r in rows]
        if any(_km(*pts[0], *p) > SAME_PLACE_KM for p in pts[1:]):
            return None
        # Del INEI (Censo 2017) antes que del IGN; con código antes que sin él; el más poblado.
        r = sorted(rows, key=lambda r: (r[6] != "inei", not r[4], -(r[5] or 0)))[0]
        lat, lon = r[2] / self.scale, r[1] / self.scale
        return Place(name=title(r[0]), lat=lat, lon=lon, category=r[3], code=r[4], population=r[5] or 0, layer=r[6],
                     radius_km=max(PLACE_RADIUS_KM, r[7] or 0), evidence=evidence, district=district,
                     basin=self.basins.at(lat, lon) if self.basins else None)

    def find(self, district: str, text: str, field: bool = False, exclude: tuple[str, ...] = ()) -> Match:
        """Los centros poblados del distrito que nombra el texto, en el orden en que aparecen.

        ``field``: el texto es un campo de lugar de la fuente (sin palabra que presente el nombre).
        ``exclude``: nombres que no cuentan (el del departamento, la provincia y el distrito)."""
        out = Match()
        if len(district) != 6 or not text:
            return out
        idx = self.index(district)
        if not idx:
            return out
        skip = {name_key(n) for n in exclude if n}
        seen: set[str] = set()
        for cand, ev in candidates(text, field):
            k = name_key(cand)
            if k in seen or k in skip or k in GENERIC or _GENERIC_PHRASE.match(k) or len(k) < 3 or k.isdigit():
                continue
            seen.add(k)
            rows = idx.get(k)
            if not rows:
                continue
            p = self._place(rows, district, ev)
            if p is None:
                out.ambiguous.append(title(cand))
            elif all(q.code != p.code or q.name != p.name for q in out.places):
                out.places.append(p)
        return out


def candidates(text: str, field: bool = False) -> list[tuple[str, str]]:
    """(nombre, evidencia) de los lugares que el texto presenta como tales. En un campo de lugar, además, cada
    trozo separado por comas, «y» o barras."""
    t = _norm(text)
    out: list[tuple[str, str]] = []
    for m in _CUE.finditer(t):
        tail = t[m.end():]
        stop = _STOP.search(" " + tail)
        tail = tail[:max(0, stop.start() - 1)] if stop else tail
        cue = m.group(0)
        # «sector A y B», «localidades de A, B y C»: cada nombre de la lista (solo cuenta si está en el distrito).
        for p in _LIST.split(tail):
            p = " ".join(p.split()[:6]).strip(" ,.-")
            if p:
                out.append((p, (cue + p).strip()))
    if field:
        for p in _LIST.split(re.sub(r"[.;:()\[\]«»\"]", ",", t)):
            p = re.sub(r"^\s*(?:" + CUE + r"|distrito|provincia|dist|prov)\s*(?:(?:de|del|de\s+la|de\s+los|de\s+las)\s+)?",
                       "", p.strip())
            p = re.sub(r"\s+(?:dist|prov|distrito|provincia|del distrito|de la provincia)$", "", p).strip(" ,.-")
            p = " ".join(p.split()[:6])
            if p:
                out.append((p, p))
    return out


class Basins:
    """Unidades hidrográficas de la ANA (``tools.build_lugares``)."""

    def __init__(self, data: dict):
        self.scale = data["scale"]
        self.units = data["units"]
        self.districts = data.get("districts", {})

    def at(self, lat: float, lon: float) -> Optional[dict]:
        try:
            x, y = float(lon) * self.scale, float(lat) * self.scale
        except (TypeError, ValueError):
            return None
        for code, u in self.units.items():
            if _in_bbox(x, y, u["bbox"]) and _in_polys(x, y, u["polys"]):
                return {"code": code, "name": u["name"]}
        return None

    def of_district(self, code: str, share: float = DISTRICT_BASIN_SHARE) -> Optional[dict]:
        """La cuenca de un distrito si al menos ``share`` de él está en ella."""
        parts = self.districts.get(code) or []
        if parts and parts[0][1] >= share:
            b = parts[0][0]
            return {"code": b, "name": self.units[b]["name"], "share": parts[0][1]}
        return None


@lru_cache(maxsize=1)
def basins() -> Basins:
    return Basins(json.loads(gzip.decompress((DATA / "cuencas.json.gz").read_bytes())))


@lru_cache(maxsize=1)
def lugares() -> Lugares:
    return Lugares(json.loads(gzip.decompress((DATA / "lugares.json.gz").read_bytes())), basins())


def basin_at(lat: float, lon: float) -> Optional[dict]:
    return basins().at(lat, lon)


def district_basin(code: str) -> Optional[dict]:
    return basins().of_district(code) if len(code or "") == 6 else None
