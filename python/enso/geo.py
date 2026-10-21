"""Ubica cada noticia en el Perú: departamento, provincia y distrito (UBIGEO del INEI).

Busca en el titular y el resumen los nombres de los 25 departamentos, 196
provincias y 1893 distritos (y las capitales de provincia, p. ej.
«Pucallpa» → Callería). Muchos nombres se repiten, son palabras comunes
(«Santa Rosa», «Independencia», «Mala») o nombran otra cosa (el río Rímac,
el jirón Ica, la Comisión de Constitución, el club Alianza Lima), así que:

* El nombre debe aparecer con mayúscula inicial (es un nombre propio). En los
  titulares en MAYÚSCULAS o en Formato Título eso no dice nada, y se exige un
  respaldo más fuerte.
* No cuenta si va después de una palabra que lo convierte en otra cosa: río,
  quebrada, jirón, avenida, club, comisión, proyecto especial, sector, anexo…
  ni si es la data de un comunicado («Lima, 20 de octubre de 2026») o parte
  de un nombre de persona o de institución («Santiago Ojeda», «María
  Auxiliadora», «Lomas de Lachay»).
* Una palabra de nivel («distrito de», «provincia de», «ciudad de»,
  «región», «Municipalidad Provincial de», «Gobierno Regional de») indica
  además qué nivel se nombra.
* Un nombre repetido en varios lugares solo se asigna si el texto menciona
  también su provincia o departamento (o es el del medio regional).
* Un nombre de la lista ``WEAK`` (palabras comunes, apellidos, santos,
  ciudades de otros países) solo se acepta con una palabra de nivel.
* Un distrito sin ese respaldo solo se acepta si su nombre es único en el
  país, va precedido de una preposición («en», «de», «desde», …), encabeza el
  titular («Sullana: …») o sigue en una enumeración a otro lugar aceptado, y
  el texto no nombra otro departamento.
* En medios internacionales se exige además que el texto hable del Perú; si
  el texto nombra otro país y no al Perú, solo cuentan los departamentos.

Si nada coincide y el medio es regional, la noticia queda en el
departamento del medio (``source: "medio"``), salvo que el texto hable de
otro país.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

DATA = Path(__file__).resolve().parent / "data" / "ubigeo.json"

#: Nombres que también son palabras comunes, apellidos, santos o lugares de otros
#: países: se aceptan solo con una palabra de nivel («distrito de Independencia»).
WEAK = {w.strip() for w in """
arma, caja, chalaco, el descanso, independencia, la banda, la matanza, la punta, la victoria, lagunas, llama,
los organos, mala, marca, marcas, marco, punos, quinua, recta, santa, santa rosa, santa maria, santa ana,
santa cruz, santiago, san juan, san pedro, san pablo, san luis, san miguel, san jose, san antonio,
san francisco, san marcos, san isidro, san lorenzo, san rafael, san ramon, san martin, la libertad, amazonas,
grau, bolivar, sucre, castilla, bolognesi, sanchez carrion, leoncio prado, daniel alcides carrion,
ramon castilla, mariscal castilla, jose galvez, ricardo palma, tupac amaru, florida, la florida, belen, victoria,
esperanza, la esperanza, progreso, el progreso, union, la union, paz, la paz, pueblo nuevo, carmen, el carmen,
colonia, morales, castillo, chavez, vega, huerta, salas, pinto, rio grande, mexico, chile, colombia, paris,
tambo, el tambo, pampas, santo domingo, santo tomas, concepcion, asuncion, trinidad, calvario, putumayo,
requena, nueva arica, general san martin, jorge basadre, dos de mayo, manu, sama, pira, inclan, ite,
magdalena, yura, moro, supe, canta,
cocha, huanca, quilca, palca, cochas, pucara, nueva, alianza, libertad, providencia, porvenir,
el porvenir, sorochuco, lucre, luya, ocros, acos, tinta, frias, vilca, ilave, ayo, yanque, pampa, montero,
maria, constitucion, choco, balsas, granada, manta, el alto, montevideo, las lomas, lomas, huaca, puerto,
tres unidos, la merced, los baños del inca, banos, la cruz, cruz, rioja, mariscal caceres, padre abad,
asia, gamarra, jorge chavez, mosca, habana, rosario
""".replace("\n", " ").split(",") if w.strip()}
#: Departamentos de ``WEAK`` que se aceptan también tras una preposición («lluvias en La Libertad»).
WEAK_DEPARTMENTS = {"la libertad", "amazonas", "san martin"}

SMALL = {"de", "del", "la", "las", "los", "el", "y", "en"}
#: Preposición antes del nombre: indica un lugar.
CUE_RE = re.compile(
    r"\b(?:en|de|del|a|al|desde|hacia|hasta|para|por|entre|sobre|v[ií]a|carretera|tramo|ruta|in|near|at|from|across)"
    r"\s+(?:la\s+|el\s+|los\s+|las\s+)?$",
    re.I)
#: Palabra de nivel antes del nombre; el grupo indica el nivel.
LEVEL_RE = re.compile(
    r"\b(?:(?P<dep>regi[oó]n(?:es)?|departamentos?|gobierno regional|gore|diresa|geresa|coer)|"
    r"(?P<prov>provincias?|municipalidad provincial|mpp?)|"
    r"(?P<dist>distritos?|municipalidad distrital)|"
    r"(?P<city>ciudad(?:es)?|localidad(?:es)?|municipalidad|alcald[ií]a))"
    r"\s+(?:(?:de|del|de la|de los|de las)\s+)?$", re.I)
#: Palabras que convierten el nombre siguiente en otra cosa (un río, una calle, una institución…).
ANTI_RE = re.compile(
    r"\b(?:r[ií]os?|quebradas?|lagunas?|lagos?|nevados?|cerros?|volc[aá]n|cordillera|valles?|cuencas?|bah[ií]a|"
    r"jir[oó]n|jr|av|avenida|calle|pasaje|psje|plaza|parque|malec[oó]n|ovalo|estadio|coliseo|club|alianza|sport|"
    r"sporting|deportivo|atl[eé]tico|proyecto especial|comisi[oó]n|junta de usuarios|comit[eé]|"
    r"placas?|tect[oó]nicas?|vientos?|combate|batalla|h[eé]roe|monumento|se[ñn]or|virgen|santuario|"
    r"sectore?s?|barrio|urbanizaci[oó]n|urb|asentamiento humano|aa\.?\s?hh|anexos?|caser[ií]os?|"
    r"centros? poblados?|comunidad(?:es)?(?: campesinas?| nativas?)?|diario|radio|canal|revista|banco|caja|"
    r"aeropuerto|emporio|galer[ií]as?|mercados?|hospital|colegio|instituci[oó]n educativa|i\.?e\.?)"
    r"\.?\s+(?:(?:de|del|la|el|los|las|a|usuarios de|campesina de|nativa de)\s+){0,2}$", re.I)
#: Palabras que, después del nombre, lo vuelven otra cosa: «pisco sour» es un cóctel.
NOT_PLACE_AFTER_RE = re.compile(r"^\s+(?:sour|acholado|quebranta|mosto verde)\b", re.I)
DATELINE_RE = re.compile(r"^\s*,\s*\d{1,2}\s+de\s+[a-z]+", re.I)
SEP_RE = re.compile(r"^\s*(?:,|y|e|,\s*y|,\s*e|-|–|/|and|,\s*and)\s*$")
HEAD_PREFIX_RE = re.compile(r"^(?:[A-ZÁÉÍÓÚÑ ]{2,20}\s*\|\s*|[\"“«'‘]\s*)?")
HEAD_END_RE = re.compile(r"^\s*(?:[:,|”\"»]|\.\s?-|\s-\s|\s?[–—]\s)")
#: Palabras que pueden ir después del nombre sin que sea el de una persona o institución.
QUALIFIERS = {"norte", "sur", "este", "oeste", "centro", "metropolitana", "provincias", "alto", "bajo", "medio",
              "region", "regional", "provincia", "ciudad", "cercado"}
#: Palabras con mayúscula que pueden preceder al nombre (no forman con él un nombre propio).
PRE_OK = {"regional", "provincial", "distrital", "region", "provincia", "distrito", "departamento", "ciudad",
          "municipalidad", "gore", "diresa", "geresa", "ugel", "coer", "essalud", "hoy", "ayer", "manana",
          "sedapal", "senamhi", "indeci"}
PERU_RE = re.compile(r"\b(per[uú]|peruan[oa]s?|peruvian|peru's)\b", re.I)
_FOREIGN = """España, Andalucía, Cataluña, Madrid, Barcelona, Galicia, Murcia, Europa, Italia, Francia,
Alemania, Portugal, Grecia, Reino Unido, Estados Unidos, EE.UU., EEUU, Texas, California, México, Guatemala,
Honduras, El Salvador, Nicaragua, Costa Rica, Panamá, Cuba, Haití, República Dominicana, Puerto Rico, Venezuela,
Colombia, Ecuador, Bolivia, Chile, Argentina, Brasil, Uruguay, Paraguay, China, India, Japón, Filipinas, Indonesia,
Pakistán, Australia, África, Gaza, Israel, Ucrania, Rusia, Irán, Guayaquil, Bogotá, Quito, Buenos Aires, Caracas,
Santiago de Chile, Puntarenas, Acapulco, Spain, Brazil, United States"""
_FOREIGN_NAMES = [n.strip() for n in _FOREIGN.replace("\n", " ").split(",") if n.strip()]
#: Otro país o una ciudad extranjera, con mayúscula inicial o en mayúsculas.
FOREIGN_RE = re.compile(r"(?<![\w-])(" + "|".join(sorted({re.escape(v) for n in _FOREIGN_NAMES for v in (
    n, n.upper(), unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode(),
    unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode().upper())}, key=len, reverse=True)) + r")(?![\w-])")
#: Capitales de distrito muy conocidas que no son capital de provincia.
NOTABLE_CAPITALS = {"chosica"}
#: Nombres de uso común que el INEI escribe de otra forma, o que la prensa usa para otro distrito.
ALIASES = {"surco": {"150140"}, "tambogrande": {"200114"}, "pichanaki": {"120303"},
           "carmen de la legua": {"070103"}, "nasca": {"1103", "110301"}, "nazca": {"1103", "110301"},
           "banos del inca": {"060108"}, "cuzco": {"08"}, "ciudad imperial": {"0801"}, "lima metropolitana": {"1501"}, "lima provincias": {"15"},
           # «Lima» y «Callao»: la provincia (Lima Metropolitana, Callao) y no el departamento ni el distrito.
           "lima": {"1501"}, "callao": {"0701"}}


def fold(s: str) -> str:
    """Quita tildes conservando la longitud del texto (para ubicar las coincidencias)."""
    out = []
    for ch in s:
        if ch == "ı":
            out.append("i")
            continue
        d = unicodedata.normalize("NFKD", ch)
        out.append(d[0] if d and not unicodedata.combining(d[0]) else ch)
    return "".join(out)


def key(s: str) -> str:
    return re.sub(r"\s+", " ", fold(s).lower()).strip()




@dataclass
class Match:
    name: str
    codes: set[str]
    cue: Optional[str]  # "level" | "prep" | "head" | "start" | None
    hint: Optional[str]  # "dep" | "prov" | "dist" | "city" | None
    informative: bool
    pos: int = 0  # orden de aparición (texto y posición)


class Gazetteer:
    def __init__(self, data: dict):
        self.deps = {d["ubigeo"]: d for d in data["departments"]}
        self.provs = {p["ubigeo"]: p for p in data["provinces"]}
        self.dists = {d["ubigeo"]: d for d in data["districts"]}
        names: dict[str, set[str]] = {}

        def add(name: str, code: str) -> None:
            name = re.sub(r"\s*\(.*?\)", "", name).strip()
            if len(name) >= 3:
                names.setdefault(key(name), set()).add(code)

        for c, d in self.deps.items():
            add(d["name"], c)
        for c, p in self.provs.items():
            add(p["name"], c)
        for c, d in self.dists.items():
            add(d["name"], c)
        official = set(names)
        prov_capitals = {key(p["capital"]) for p in self.provs.values()}
        for c, d in self.dists.items():
            add(d["capital"], c)
        names.update(ALIASES)
        #: Capitales de distrito que no son nombre oficial ni capital de provincia (Leticia, Mosca, Angamos…):
        #: solo cuentan con el respaldo de su departamento o del medio regional.
        self.minor_alias = {k for k in names if k not in official and k not in prov_capitals
                            and k not in NOTABLE_CAPITALS and k not in ALIASES}
        self.names = names
        alts = sorted(names, key=len, reverse=True)
        self.regex = re.compile(r"(?<!\w)(" + "|".join(re.escape(a) for a in alts) + r")(?!\w)", re.I)

    def _case_informative(self, text: str) -> bool:
        """False en textos en MAYÚSCULAS o en Formato Título, donde la mayúscula no distingue nombres propios.

        Se miran las palabras que no son nombres de lugar (una enumeración de distritos no es Formato Título)."""
        letters = [c for c in text if c.isalpha()]
        if letters and sum(c.isupper() for c in letters) / len(letters) > 0.8:
            return False
        words = [w for w in re.findall(r"[^\W\d_]{4,}", text)[1:] if key(w) not in self.names]
        if len(words) < 4:
            return True
        return sum(w[0].isupper() for w in words) / len(words) <= 0.7

    # -- utilidades ---------------------------------------------------------
    def label(self, code: str) -> dict:
        level = {2: "departamento", 4: "provincia", 6: "distrito"}[len(code)]
        src = {2: self.deps, 4: self.provs, 6: self.dists}[len(code)][code]
        out = {"code": code, "level": level, "name": src["name"], "department": self.deps[code[:2]]["name"]}
        if len(code) == 6:
            out["province"] = self.provs[code[:4]]["name"]
        return out

    # -- etiquetado ---------------------------------------------------------
    def _matches(self, text: str) -> list[Match]:
        text = unicodedata.normalize("NFC", text)
        folded = fold(text)
        informative = self._case_informative(text)
        head_at = HEAD_PREFIX_RE.match(folded).end()
        #: comienzos de oración: «Fenómeno El Niño: Chosica no tiene…», «… en Lima. Chosica…»
        starts = {head_at} | {m.end() for m in re.finditer(r"(?:[:.!?]|\s[-–—|])\s+(?:[\"“«'‘]\s*)?", folded)}
        out: list[Match] = []
        prev: Optional[tuple[int, Optional[str], Optional[str]]] = None  # (fin, señal, nivel) del anterior
        pos = 0
        while True:
            m = self.regex.search(folded, pos)
            if not m:
                break
            start, end = m.start(), m.end()
            raw = text[start:end]
            words = raw.split()
            pos = end
            if words[0].lower() in SMALL and words[0][:1].islower():
                # «el Alto Amazonas»: el artículo en minúscula no es parte del nombre; se busca otra vez después.
                pos = start + len(words[0]) + 1
                continue
            if not all(w[:1].isupper() for w in words if w.lower() not in SMALL):
                continue  # «mala», «santa rosa» en minúsculas: no es un nombre propio
            name = key(raw)
            codes = self.names.get(name)
            if not codes:
                continue
            before = folded[max(0, start - 60):start]
            after = folded[end:end + 40]
            chain = prev if prev is not None and SEP_RE.match(folded[prev[0]:start]) else None
            if ANTI_RE.search(before) or (chain and chain[1] == "anti"):
                prev = (end, "anti", None)  # «ríos Chira y Piura»: la enumeración sigue siendo de ríos
                continue
            prev = None
            if DATELINE_RE.match(after):
                continue  # «Lima, 20 de octubre de 2026»: lugar de emisión del comunicado
            if NOT_PLACE_AFTER_RE.match(after):
                continue
            if informative and self._part_of_longer_name(folded, start, end, codes):
                continue
            cue, hint = None, None
            lv = LEVEL_RE.search(before)
            if lv:
                cue, hint = "level", lv.lastgroup
            elif CUE_RE.search(before):
                cue = "prep"
            elif start == head_at and HEAD_END_RE.match(after):
                cue = "head"  # «Sullana: …», «Chosica – …»
            elif start in starts:
                cue = "start"  # el nombre abre la oración: «Chosica en peligro por…»
            elif chain and chain[1]:
                cue, hint = chain[1], chain[2]  # «en Chosica, Chaclacayo y Cieneguilla»
            out.append(Match(name, set(codes), cue, hint, informative, start))
            prev = (end, cue, hint)
        return out

    @staticmethod
    def _part_of_longer_name(folded: str, start: int, end: int, codes: set[str]) -> bool:
        """«Santiago Ojeda», «María Auxiliadora», «Lomas de Lachay», «Evo Morales»: no es el lugar."""
        nxt = re.match(r"\s+([A-Z][a-z]+)", folded[end:end + 30])
        if nxt and nxt.group(1).lower() not in QUALIFIERS and nxt.group(1).lower() not in SMALL:
            return True
        if not any(len(c) == 2 for c in codes) and re.match(r"\s+(?:de|del|de la|de los|de las)\s+[A-Z]", folded[end:end + 20]):
            return True
        pre = re.search(r"([A-Z][a-z]+)\s+$", folded[max(0, start - 30):start])
        if pre and pre.group(1).lower() not in PRE_OK:
            i = start - len(pre.group(0))
            sentence_start = i == 0 or folded[:i].rstrip()[-1:] in (".", ":", "!", "?", "¿", "¡", '"', "“", "«", "|")
            word = pre.group(1).lower()
            if not sentence_start and not CUE_RE.search(word + " ") and not LEVEL_RE.search(word + " "):
                return True
        return False

    @staticmethod
    def _resolve(codes: set[str], hint: Optional[str]) -> set[str]:
        """El nivel nombrado («provincia de Santa») o, sin palabra de nivel, el más amplio que corresponda:
        «Piura» = departamento, provincia y distrito → departamento; «Sullana» = provincia y su capital → provincia."""
        if hint == "dep" and any(len(c) == 2 for c in codes):
            return {c for c in codes if len(c) == 2}
        if hint == "prov" and any(len(c) == 4 for c in codes):
            return {c for c in codes if len(c) == 4}
        if hint == "dist" and any(len(c) == 6 for c in codes):
            return {c for c in codes if len(c) == 6}
        if hint == "city":
            provs = {c for c in codes if len(c) == 4}
            if provs:
                return provs
            if any(len(c) == 6 for c in codes):
                return {c for c in codes if len(c) == 6}
        deps = {c for c in codes if len(c) == 2}
        if deps:
            return deps
        p4 = {c[:4] for c in codes}
        if len(p4) == 1 and next(iter(p4)) in codes:
            return p4
        return codes

    def tag(self, texts: Iterable[str], peru_context: bool, default_dep: Optional[str] = None) -> Optional[dict]:
        texts = [t for t in texts if t]
        joined = " ".join(texts)
        found = [m for i, t in enumerate(texts) for m in self._matches(t)]
        for i, m in enumerate(found):
            m.pos = i
        named_peru = bool(PERU_RE.search(joined))
        if not (peru_context or named_peru):
            return None
        foreign = not named_peru and bool(FOREIGN_RE.search(unicodedata.normalize("NFC", joined)))
        # 1) departamentos y provincias inequívocos
        deps: list[str] = []
        provs: list[str] = []
        named: set[str] = set()
        for m in found:
            codes = self._resolve(m.codes, m.hint)
            if len(codes) != 1:
                continue
            c = next(iter(codes))
            if len(c) == 6:
                continue
            if foreign and (len(c) != 2 or m.name in WEAK):
                continue  # nombra otro país y no al Perú: solo cuentan los departamentos
            if m.name in WEAK:
                if len(c) == 2:
                    ok = m.cue in ("level", "head") or (m.cue == "prep" and m.informative and m.name in WEAK_DEPARTMENTS)
                else:  # «Grau», «Jorge Basadre»: provincia de nombre común, con palabra de nivel o su departamento
                    ok = m.cue == "level" or (m.cue == "prep" and any(d == c[:2] for d in deps))
                if not ok:
                    continue
            (deps if len(c) == 2 else provs).append(c)
            named.add(m.name)
        # «Lima» junto a otros departamentos («Áncash, Junín y Lima») es el departamento.
        if "1501" in provs and len({d for d in deps if d != "15"} | {p[:2] for p in provs if p[:2] != "15"}) >= 2:
            provs = [p for p in provs if p != "1501"]
            deps.append("15")
        mentioned = set(deps) | {p[:2] for p in provs}
        # 2) distritos y nombres repetidos, con el respaldo del resto del texto
        picked: list[str] = list(provs)
        for m in found:
            if foreign:
                break
            cands = sorted(self._resolve(m.codes, m.hint))
            if len(cands) == 1 and len(cands[0]) <= 4:
                continue  # ya considerado arriba
            weak = m.name in WEAK
            if weak and m.cue != "level":
                continue
            if m.name in named:
                continue  # «Chota» ya es la provincia: no el homónimo de otro departamento
            if m.name in self.minor_alias and not m.informative and m.cue != "level":
                continue  # en un titular en mayúsculas «DE MOSCA» no es el pueblo de Mosca
            by_prov = [c for c in cands if c[:4] in provs and c not in provs]
            by_dep = [c for c in cands if c[:2] in mentioned and c not in provs]
            backed = by_prov or by_dep
            if backed:
                if len(backed) == 1:
                    picked.append(backed[0])
                elif len({c[:4] for c in backed}) == 1:
                    picked.append(backed[0][:4])
                continue
            if m.name in self.minor_alias and m.cue != "level":
                local = [c for c in cands if default_dep and c[:2] == default_dep]
                if len(local) == 1 and m.cue:
                    picked.append(local[0])
                continue
            local = [c for c in cands if default_dep and c[:2] == default_dep]
            if len(local) == 1 and m.cue:
                picked.append(local[0])  # medio regional: el homónimo de su departamento
                continue
            if len(cands) != 1 or not m.cue:
                continue
            c = cands[0]
            if mentioned and c[:2] not in mentioned:
                continue  # el texto nombra otro departamento: es un homónimo (un anexo, un estadio…)
            if m.cue != "level":
                if default_dep and c[:2] != default_dep:
                    continue
                if not m.informative and m.cue in ("prep", "start"):
                    continue  # «DAMNIFICADOS CRUZAN EL RÍO EN BALSAS»
            picked.append(c)
        if not picked and not deps:
            if default_dep and not foreign:
                return {"places": [self.label(default_dep)], "departments": [default_dep], "source": "medio"}
            return None
        order = {}
        for m in found:
            for c in self._resolve(m.codes, m.hint) | m.codes:
                order.setdefault(c, m.pos)
        codes = sorted(dict.fromkeys(picked + deps), key=lambda c: order.get(c, order.get(c[:4], order.get(c[:2], 99))))
        codes = [c for c in codes if c in self.deps or c in self.provs or c in self.dists]
        # «provincia de Calca» y «distrito de Calca»: con la provincia basta.
        codes = [c for c in codes if not (len(c) == 6 and c[:4] in codes and key(self.dists[c]["name"]) == key(self.provs[c[:4]]["name"]))]
        if not codes:
            return None
        # El departamento implícito en algo más específico sobra (Piura si ya está Sullana); las provincias
        # nombradas se conservan («Paracas y Pisco»).
        specific = [c for c in codes if not (len(c) == 2 and any(o != c and o.startswith(c) for o in codes))
                    and not (len(c) == 4 and c not in provs and any(o != c and o.startswith(c) for o in codes))]
        return {"places": [self.label(c) for c in specific[:6]],
                "departments": list(dict.fromkeys(c[:2] for c in codes)), "source": "texto"}


@lru_cache(maxsize=1)
def gazetteer() -> Gazetteer:
    return Gazetteer(json.loads(DATA.read_text(encoding="utf-8")))


def department_names() -> dict[str, str]:
    return {c: d["name"] for c, d in gazetteer().deps.items()}
