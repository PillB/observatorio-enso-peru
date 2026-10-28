"""Ubica un evento por el río, la quebrada, la laguna, el nevado o el abra que nombra la fuente, dentro de su distrito.

Es el peldaño siguiente al centro poblado (``enso.lugares``): un registro del SINPAD o del COEN que dice «crecida del
río Chiguata» o «huaico en la quebrada Pedregal» y no nombra un caserío se ubica sobre ese cauce, con un radio que
cubre su tramo dentro del distrito. Como los centros poblados, se busca **después** de saber el distrito y solo
dentro de él: nunca cambia el distrito de un evento.

Reglas (las mismas ideas que ``enso.lugares``):

- El nombre debe ir tras la palabra que dice qué es («río», «quebrada», «qda.», «riachuelo», «laguna», «nevado»,
  «volcán», «abra»…) y existir en el distrito con esa clase (Carta Nacional 1:100 000 del IGN,
  ``tools.build_aguas``). Un río y una quebrada se tratan como un mismo curso de agua.
- Un nombre que también es un adjetivo («Seca», «Grande», «Honda», «Negra»…) solo cuenta en un campo de lugar o
  escrito con mayúscula en un texto que no está todo en mayúsculas: «la quebrada seca» describe, «la quebrada
  Seca» nombra.
- De un nombre de varias palabras se toma el más largo que existe en el distrito, y uno más corto solo si lo que
  sigue no puede ser parte del nombre («río Santa Eulalia» no es el río Santa).
- El punto es el del cauce más cercano al centro de su tramo en el distrito; se usa como punto solo si su radio es
  de ``POINT_MAX_KM`` o menos y menor que tres cuartos del radio del distrito (un río que cruza el distrito de punta
  a punta no dice dónde fue). Si no, el nombre igual da la **cuenca** (la de la mayor parte de su tramo, si es el
  ``BASIN_SHARE`` o más).
"""

from __future__ import annotations

import gzip
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .lugares import _LIST, _km, _norm, loose_key, name_key

DATA = Path(__file__).resolve().parent / "data"
#: Radio máximo de un tramo de cauce (o de varios) para usarlo como punto.
POINT_MAX_KM = 10.0
#: Fracción del radio equivalente del distrito (el de un círculo de su misma área) que el radio no debe pasar.
DISTRICT_SHARE = 0.75
#: Fracción del tramo que debe caer en una cuenca para que el nombre dé la cuenca.
BASIN_SHARE = 0.6
#: Lo que se suma al radio del tramo: el daño está cerca del cauce, no sobre él, y la Carta no nombra todos los tramos
#: de un río. Con esto, contra los puntos de campo del SINPAD que nombran un río o una quebrada, el 73 % cae dentro
#: del radio (sin el margen, el 56 %; ver ``tests/test_aguas.py``).
MARGIN_KM = {"curso": 2.0, "laguna": 1.0, "nevado": 1.0, "volcan": 1.0, "abra": 1.0}

#: Palabra que presenta el nombre → clases del IGN que puede ser.
CUES = {
    "curso": r"rios?|riachuelos?|quebradas?|qdas?|q|arroyos?|esteros?|canal(?:es)?|cauces?\s+del?\s+rio",
    "laguna": r"lagunas?|lagos?|cochas?|represas?\s+(?:de\s+la\s+)?laguna",
    "nevado": r"nevados?|glaciar(?:es)?(?:\s+del?\s+nevado)?|volcan(?:es)?",
    "abra": r"abras?",
}
CLASSES = {"curso": ("curso",), "laguna": ("laguna",), "nevado": ("nevado", "volcan"), "abra": ("abra",)}
_CUE = re.compile(r"(?<![a-z0-9])(?P<cue>" + "|".join(f"(?P<{k}>{v})" for k, v in CUES.items()) +
                  r")(?![a-z0-9])\s*\.?\s*(?:(?:de\s+la|de\s+los|de\s+las|del|de|la|el|los|las|denominad[oa]s?|"
                  r"llamad[oa]s?)\s+)?")
#: Dónde termina, a lo sumo, lo que puede ser el nombre.
_CUT = re.compile(r"[.;:()\[\]«»\"!?]|\s-\s|,")
_CUT_LIST = re.compile(r"[.;:()\[\]«»\"!?]|\s-\s")
#: Nombres que también son adjetivos o palabras de lugar: solo con mayúscula (o en un campo de lugar).
ADJECTIVES = frozenset(
    "grande grandes chico chica chicos chicas seco seca secos secas hondo honda blanco blanca negro negra colorado "
    "colorada verde azul salado salada dulce mayor menor alto alta bajo baja nuevo nueva viejo vieja largo larga "
    "ancho ancha chiquito chiquita pequeno pequena profundo profunda principal caudaloso caudalosa crecido crecida "
    "arriba abajo adentro afuera cercano cercana aledano aledana mismo misma rojo roja amarillo amarilla oscuro "
    "oscura limpio limpia sucio sucia hermoso hermosa bravo brava manso mansa claro clara turbio turbia".split())
#: Lo que puede seguir a un nombre (y por eso no es parte de él): artículos, preposiciones, verbos.
_FOLLOW = frozenset(
    "se que en de del y e a al por con para ha han habia hubo el la los las lo le les un una sobre hacia desde entre "
    "cerca frente margen margenes aguas km sector sectores tramo altura cuenca caudal causo causando esta estan es "
    "fue son era eran viene vienen sigue siguen tiene tienen tuvo presenta presento alcanzo registra registro "
    "incremento aumento desborde desbordo desbordaron crecida crecio inundo inundaron arrastro afecto afectando "
    "colapso destruyo dejo ocasiono provoco origino genero bloqueo interrumpio corto activo activacion "
    "huaico huaicos huayco huaycos deslizamiento derrumbe inundacion lluvias lluvia y/o o u ni pero como "
    "cuando donde mientras durante tras ante bajo segun hasta zona zonas parte partes lado lados orilla orillas "
    "riberas ribera cauce cauces".split())
_VERBISH = re.compile(r"^[a-z]{3,}(?:aron|ieron|ando|iendo)$|^(?:activ|afect|ubic|situ|colmat|desbord|crec|inund|ocurr|"
                      r"produc|registr|report|caus|ocasion|provoc|gener|destru|colaps|bloque|interrump|arrastr|dan|"
                      r"increment|aument|carg|discurr|recorr|atraves|cruz|baj|arras|socav|eros|represa|embals|ingres|"
                      r"desliz|derrumb|aisl|anieg|cort|llev|romp|rebals|desemboc|nac)(?:ad[oa]s?|id[oa]s?|o|a|an|e|en|"
                      r"io|ieron|aron|ando|iendo)$")


def _fold_keep_case(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()


@dataclass
class Water:
    name: str
    clase: str  # curso | laguna | nevado | volcan | abra
    lat: float
    lon: float
    radius_km: float
    length_km: float
    basin_code: str
    basin_share: float
    evidence: str = ""
    district: str = ""
    basin: Optional[dict] = None

    def as_dict(self) -> dict:
        out = {"name": self.name, "lat": round(self.lat, 5), "lon": round(self.lon, 5), "radiusKm": self.radius_km,
               "rung": "cuerpo-de-agua", "class": self.clase}
        if self.evidence:
            out["evidence"] = self.evidence
        if self.basin:
            out["basin"] = self.basin
        return out


@dataclass
class WaterMatch:
    waters: list[Water] = field(default_factory=list)
    #: Una lista («ríos Moche y Chicama») con algún nombre que no está en el distrito: el lugar no es solo el tramo
    #: que sí está.
    partial: bool = False

    @property
    def names(self) -> str:
        return " · ".join(dict.fromkeys(w.name for w in self.waters))

    def point(self, district_radius_km: float = math.inf) -> Optional[tuple[float, float, float]]:
        """(lat, lon, radio) de los nombres: el del único o el punto medio de varios con el radio que los cubre;
        None si el radio pasa de ``POINT_MAX_KM`` o de ``DISTRICT_SHARE`` del radio del distrito."""
        if not self.waters or self.partial:
            return None
        if len(self.waters) == 1:
            w = self.waters[0]
            lat, lon, radius = w.lat, w.lon, w.radius_km
        else:
            lat = sum(w.lat for w in self.waters) / len(self.waters)
            lon = sum(w.lon for w in self.waters) / len(self.waters)
            radius = round(max(_km(lat, lon, w.lat, w.lon) + w.radius_km for w in self.waters), 1)
        if radius > POINT_MAX_KM or radius >= DISTRICT_SHARE * district_radius_km:
            return None
        return lat, lon, radius

    def basin(self, units: Optional[dict] = None) -> Optional[dict]:
        """La cuenca común de los nombres, si cada uno tiene el ``BASIN_SHARE`` o más de su tramo en ella."""
        codes = {w.basin_code for w in self.waters if w.basin_code and w.basin_share >= BASIN_SHARE}
        if len(codes) != 1 or any(not w.basin_code or w.basin_share < BASIN_SHARE for w in self.waters):
            return None
        code = codes.pop()
        name = (units or {}).get(code, {}).get("name", "")
        return {"code": code, "name": name} if name else None


class Aguas:
    def __init__(self, data: dict):
        self.scale = data["scale"]
        self.rows = data["districts"]
        #: {UBIGEO: [[fila, otro nombre], …]}: «Río Chili (Sumbay)» también es el río Sumbay.
        self.alias = data.get("alias", {})
        self._index: dict[str, dict[str, list[list]]] = {}

    def index(self, district: str) -> dict[str, list[list]]:
        """{clave sin clase ni artículos: filas} del distrito, también por sus otros nombres (la fila lleva entonces
        el nombre que usó el texto entre paréntesis: «Quebrada Bicua (Cunía)»)."""
        if district not in self._index:
            rows = self.rows.get(district, [])
            idx: dict[str, list[list]] = {}
            for k, row in [(water_key(r[0]), r) for r in rows] + \
                    [(water_key(a), [f"{rows[i][0]} ({a})", *rows[i][1:]]) for i, a in self.alias.get(district, [])]:
                if len(k) >= 3 and row not in idx.get(k, []):
                    idx.setdefault(k, []).append(row)
            self._index[district] = idx
        return self._index[district]

    def find(self, district: str, text: str, field: bool = False, exclude: tuple[str, ...] = ()) -> WaterMatch:
        """Los cuerpos de agua del distrito que nombra el texto, en el orden en que aparecen. ``exclude``: nombres que
        no cuentan solos (el del departamento, la provincia y el distrito: «río Piura» en Piura sí cuenta, porque
        lleva la palabra «río»; esto evita solo el nombre suelto en un campo)."""
        out = WaterMatch()
        if len(district) != 6 or not text:
            return out
        idx = self.index(district)
        if not idx:
            return out
        original = _fold_keep_case(text)
        upper = original.upper() == original
        # Verbos en pretérito escritos con tilde («desbordó», «arrasó»): lo que sigue a un nombre, no parte de él.
        accented = {_fold_keep_case(w).lower() for w in re.findall(r"\w+ó\b", (text or "").lower())}
        seen: set[tuple[str, str]] = set()
        for cue_class, words, evidence, listed in _candidates(text):
            found = False
            for k, used in _prefixes(words, idx, accented):
                rows = [r for r in idx[k] if r[1] in CLASSES[cue_class]]
                if not rows:
                    continue
                if k in ADJECTIVES and not field and (upper or not _capitalized(original, used)):
                    continue
                found = True
                if (cue_class, k) in seen:
                    break
                seen.add((cue_class, k))
                r = max(rows, key=lambda r: r[5])
                out.waters.append(Water(name=r[0], clase=r[1], lat=r[3] / self.scale, lon=r[2] / self.scale,
                                        radius_km=round(r[4] + MARGIN_KM[r[1]], 1), length_km=r[5],
                                        basin_code=r[6], basin_share=r[7],
                                        evidence=evidence, district=district))
                break
            if listed and not found:
                out.partial = True
        return out


#: La clase al comienzo de un nombre del IGN («Rio Napo» → napo).
PREFIX = re.compile(r"^(?:rio|quebrada|qda|q|riachuelo|arroyo|estero|cano|canal|lagunas?|lago|cocha|nevado|volcan|"
                    r"abra)\b\.?\s*")
#: Nombres que no son nombres (la Carta los usa para un cauce sin nombre).
NOT_NAMES = frozenset({"unk", "n p", "s n", "sn", "np", "sin nombre", "nn", "charcos", "charcos intermitentes",
                       "lagunas", "laguna", "quebrada", "rio", "canal", "nombre no registrado"})


def water_key(name: str) -> str:
    """Clave de un nombre sin la clase ni artículos: «Río de la Virgen», «quebrada Virgen» → «virgen»."""
    k = name_key(name)
    if k in NOT_NAMES:
        return ""
    k = PREFIX.sub("", k).strip()
    return "" if k in NOT_NAMES else loose_key(k)




def _capitalized(original: str, words: list[str]) -> bool:
    """El nombre aparece en el texto original con mayúscula inicial («quebrada Seca»)."""
    pat = r"\b" + r"\s+".join(re.escape(w[:1].upper() + w[1:]) for w in words) + r"\b"
    return re.search(pat, original) is not None


def _candidates(text: str) -> list[tuple[str, list[str], str, bool]]:
    """(clase de la palabra que presenta, palabras que siguen, evidencia, si es parte de una lista) por cada nombre que
    el texto presenta; una lista («ríos Moche y Chicama») da un candidato por nombre."""
    t = _norm(text)
    out = []
    for m in _CUE.finditer(t):
        cue_class = next(k for k in CUES if m.group(k))
        tail = t[m.end():]
        plural = re.match(r"(?:rios|quebradas|qdas|lagunas|lagos|nevados|riachuelos|abras)\b", m.group("cue"))
        cut = (_CUT_LIST if plural else _CUT).search(tail)
        tail = tail[:cut.start()] if cut else tail
        parts = _LIST.split(tail) if plural else [tail]
        # Lo que sigue a la lista («…y del Loco, afectando viviendas») no es otro nombre.
        parts = [p for p in parts if p.split() and p.split()[0] not in _FOLLOW and not _VERBISH.match(p.split()[0])
                 or p.split()[:1] in (["de"], ["del"], ["la"], ["el"], ["los"], ["las"])]
        for p in parts:
            words = p.split()[:6]
            if words:
                out.append((cue_class, words, (m.group(0) + " ".join(words)).strip(), bool(plural) and len(parts) > 1))
    return out


def _prefixes(words: list[str], idx: dict[str, list[list]], accented: frozenset | set = frozenset()):
    """(clave, palabras usadas) de los prefijos de ``words`` que están en el índice, del más largo al más corto; uno
    más corto solo si la palabra que sigue no puede ser parte del nombre."""
    for n in range(len(words), 0, -1):
        used = words[:n]
        k = loose_key(" ".join(used))
        if len(k) < 3 or k not in idx:
            continue
        nxt = words[n] if n < len(words) else ""
        if nxt and nxt not in _FOLLOW and nxt not in accented and not _VERBISH.match(nxt) and not nxt.isdigit():
            continue
        yield k, used


def district_radius_km(code: str) -> float:
    """Radio de un círculo con el área del distrito (límites del INDECI)."""
    return _district_radii().get(code, math.inf)


@lru_cache(maxsize=1)
def _district_radii() -> dict[str, float]:
    from .limites import limits

    lim = limits()
    out = {}
    for code, d in lim.levels[6].items():
        kx, ky = lim._xy_km(((d["bbox"][1] + d["bbox"][3]) / 2) / lim.scale)
        area = 0.0
        for rings in d["polys"]:
            for i, r in enumerate(rings):
                a = sum(r[k] * r[k + 3] - r[k + 2] * r[k + 1] for k in range(0, len(r) - 2, 2))
                a += r[-2] * r[1] - r[0] * r[-1]
                area += (abs(a) / 2) * kx * ky * (1 if i == 0 else -1)
        out[code] = math.sqrt(max(area, 0.0) / math.pi)
    return out


@lru_cache(maxsize=1)
def aguas() -> Aguas:
    return Aguas(json.loads(gzip.decompress((DATA / "aguas.json.gz").read_bytes())))


def waters(codes: list[str], text: str, field: bool = False, limit: int = 3) -> list[dict]:
    """Los cuerpos de agua que el texto nombra en esos distritos (hasta ``limit`` distritos), como puntos para el mapa;
    solo los que se pueden usar como punto (ver ``WaterMatch.point``)."""
    from .lugares import basins

    out = []
    for code in [c for c in codes if len(c or "") == 6][:limit]:
        m = aguas().find(code, text, field=field)
        for w in m.waters:
            if WaterMatch([w]).point(district_radius_km(code)):
                w.basin = basins().at(w.lat, w.lon)
                out.append({**w.as_dict(), "kind": "cuerpo-de-agua", "district": code})
    return out
