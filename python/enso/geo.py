"""Ubica cada noticia en el Perú: departamento, provincia y distrito (UBIGEO del INEI).

Busca en el titular, el resumen y las categorías del feed los nombres de los
25 departamentos, 196 provincias y 1893 distritos (y las capitales de
distrito, p. ej. «Chosica» → Lurigancho). Muchos nombres se repiten o son
palabras comunes («Santa Rosa», «Independencia», «Mala»), así que:

* El nombre debe aparecer con mayúscula inicial (es un nombre propio).
* Un nombre repetido en varios lugares solo se asigna si el texto menciona
  también su provincia o departamento.
* Un distrito o provincia sin ese respaldo solo se acepta si su nombre es
  único en el país, no está en la lista de nombres ambiguos ``WEAK`` y va
  precedido de una preposición o palabra de lugar («en», «de», «distrito
  de», …) o encabeza el titular («Sullana: …»).
* En medios internacionales se exige además que el texto hable del Perú.

Si nada coincide y el medio es regional, la noticia queda en el
departamento del medio (``source: "medio"``).
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

DATA = Path(__file__).resolve().parent / "data" / "ubigeo.json"

#: Nombres que también son palabras comunes, apellidos o lugares de otros
#: países: se aceptan solo si el texto menciona su provincia o departamento.
WEAK = {w.strip() for w in """
arma, caja, chalaco, el descanso, independencia, la banda, la matanza, la punta, la victoria, lagunas, llama,
los organos, mala, marca, marcas, marco, punos, quinua, recta, santa, santa rosa, santa maria, santa ana,
santa cruz, santiago, san juan, san pedro, san pablo, san luis, san miguel, san jose, san antonio,
san francisco, san marcos, san isidro, san lorenzo, san rafael, san ramon, san martin, la libertad, amazonas,
grau, bolivar, sucre, castilla, bolognesi, sanchez carrion, leoncio prado, daniel alcides carrion,
ramon castilla, mariscal castilla, jose galvez, ricardo palma, tupac amaru, florida, belen, victoria,
esperanza, la esperanza, progreso, el progreso, union, la union, paz, la paz, pueblo nuevo, carmen, el carmen,
colonia, morales, castillo, chavez, vega, huerta, salas, pinto, rio grande, mexico, chile, colombia, paris,
tambo, el tambo, pampas, santo domingo, santo tomas, concepcion, asuncion, trinidad, calvario, putumayo,
requena, nueva arica, general san martin, jorge basadre, dos de mayo, manu, sama, pira, inclan, ite,
pueblo libre, magdalena, bellavista, la perla, miraflores, barranco, comas, ate, yura, moro, supe, canta,
alto amazonas, cocha, huanca, quilca, palca, cochas, pucara, nueva, alianza, libertad, providencia, porvenir,
el porvenir, sorochuco, lucre, luya, ocros, acos, tinta, frias, vilca, ilave, ayo, yanque, pampa, montero
""".replace("\n", " ").split(",") if w.strip()}

SMALL = {"de", "del", "la", "las", "los", "el", "y", "en"}
CUE_RE = re.compile(
    r"(?:\b(?:en|de|del|a|al|desde|hacia|hasta|para|por|entre|y|e|regi[oó]n|provincia|distrito|ciudad|"
    r"departamento|localidad|centro poblado|caser[ií]o|anexo|zona|sector|r[ií]o|quebrada)\s+(?:la\s+|el\s+|los\s+|las\s+)?)$",
    re.I)
PERU_RE = re.compile(r"\b(per[uú]|peruan[oa]s?)\b", re.I)


def fold(s: str) -> str:
    """Quita tildes conservando la longitud del texto (para ubicar las coincidencias)."""
    out = []
    for ch in s:
        d = unicodedata.normalize("NFKD", ch)
        out.append(d[0] if d and not unicodedata.combining(d[0]) else ch)
    return "".join(out)


def key(s: str) -> str:
    return re.sub(r"\s+", " ", fold(s).lower()).strip()


class Gazetteer:
    def __init__(self, data: dict):
        self.deps = {d["ubigeo"]: d for d in data["departments"]}
        self.provs = {p["ubigeo"]: p for p in data["provinces"]}
        self.dists = {d["ubigeo"]: d for d in data["districts"]}
        self.capital_dist = {p["ubigeo"]: next((d for c, d in self.dists.items() if c[:4] == p["ubigeo"]
                                                and key(d["capital"]) == key(p["capital"])), None)
                             for p in data["provinces"]}
        names: dict[str, set[str]] = {}

        def add(name: str, code: str) -> None:
            name = re.sub(r"\s*\(.*?\)", "", name).strip()
            if len(name) >= 3:
                names.setdefault(key(name), set()).add(code)

        for c, d in self.deps.items():
            add(d["name"], c)
        add("Cuzco", "08")
        add("Lima Metropolitana", "1501")
        add("Lima Provincias", "15")
        for c, p in self.provs.items():
            add(p["name"], c)
        for c, d in self.dists.items():
            add(d["name"], c)
            add(d["capital"], c)
        # «Lima» y «Callao»: la provincia (Lima Metropolitana, Callao) y no el departamento ni el distrito.
        names["lima"] = {"1501"}
        names["callao"] = {"0701"}
        self.names = names
        alts = sorted(names, key=len, reverse=True)
        self.regex = re.compile(r"(?<![\w-])(" + "|".join(re.escape(a) for a in alts) + r")(?![\w-])", re.I)

    # -- utilidades ---------------------------------------------------------
    def dep_of(self, code: str) -> str:
        return code[:2]

    def label(self, code: str) -> dict:
        level = {2: "departamento", 4: "provincia", 6: "distrito"}[len(code)]
        src = {2: self.deps, 4: self.provs, 6: self.dists}[len(code)][code]
        out = {"code": code, "level": level, "name": src["name"], "department": self.deps[code[:2]]["name"]}
        if len(code) == 6:
            out["province"] = self.provs[code[:4]]["name"]
        return out

    # -- etiquetado ---------------------------------------------------------
    def _matches(self, text: str) -> list[tuple[str, set[str], bool]]:
        folded = fold(text)
        out = []
        for m in self.regex.finditer(folded):
            raw = text[m.start():m.end()]
            words = [w for w in raw.split() if w.lower() not in SMALL]
            if not words or not all(w[:1].isupper() for w in words):
                continue  # «mala», «santa rosa» en minúsculas: no es un nombre propio
            before = folded[max(0, m.start() - 40):m.start()]
            cue = bool(CUE_RE.search(before)) or m.start() == 0 and folded[m.end():m.end() + 1] in (":", ",", " -")
            if m.start() == 0 and folded[m.end():m.end() + 2].strip()[:1] in (":", ",", "-", "|"):
                cue = True
            out.append((key(raw), self.names[key(raw)], cue))
        return out

    @staticmethod
    def _collapse(codes: set[str]) -> set[str]:
        """«Piura» = departamento, provincia y distrito: vale como departamento.
        «Sullana» = provincia y su distrito capital: vale como provincia."""
        deps = {c for c in codes if len(c) == 2}
        if deps:
            return deps
        p4 = {c[:4] for c in codes}
        if len(p4) == 1 and next(iter(p4)) in codes:
            return p4
        return codes

    def tag(self, texts: Iterable[str], peru_context: bool, default_dep: Optional[str] = None) -> Optional[dict]:
        texts = [t for t in texts if t]
        found = [(n, self._collapse(c), cue) for t in texts for n, c, cue in self._matches(t)]
        peru = peru_context or bool(PERU_RE.search(" ".join(texts)))
        if not peru:
            return None
        # 1) departamentos y provincias inequívocos
        deps, provs = [], []
        for name, codes, cue in found:
            if len(codes) == 1 and (name not in WEAK or cue):
                c = next(iter(codes))
                (deps if len(c) == 2 else provs if len(c) == 4 else []).append(c)
        mentioned = set(deps) | {p[:2] for p in provs}
        # 2) distritos y nombres repetidos, con el respaldo del resto del texto
        picked: list[str] = list(provs)
        for name, codes, cue in found:
            cands = sorted(codes)
            if len(cands) == 1 and len(cands[0]) <= 4:
                continue  # ya considerado arriba
            backed = [c for c in cands if c[:2] in mentioned and c not in provs]
            if backed:
                in_prov = [c for c in backed if c[:4] in provs] or backed
                if len(in_prov) == 1:
                    picked.append(in_prov[0])
                elif len({c[:4] for c in in_prov}) == 1:
                    picked.append(in_prov[0][:4])
                continue
            local = [c for c in cands if default_dep and c[:2] == default_dep]
            if len(local) == 1 and (cue or name not in WEAK):
                picked.append(local[0])  # medio regional: el homónimo de su departamento
            elif len(cands) == 1 and cue and name not in WEAK:
                picked.append(cands[0])
        if not picked and not deps:
            if default_dep:
                return {"places": [self.label(default_dep)], "departments": [default_dep], "source": "medio"}
            return None
        codes = list(dict.fromkeys(picked + deps))
        # Lo implícito en algo más específico sobra (Piura si ya está Sullana).
        specific = [c for c in codes if not any(o != c and o.startswith(c) for o in codes)]
        return {"places": [self.label(c) for c in specific[:6]],
                "departments": list(dict.fromkeys(c[:2] for c in codes)), "source": "texto"}


@lru_cache(maxsize=1)
def gazetteer() -> Gazetteer:
    return Gazetteer(json.loads(DATA.read_text(encoding="utf-8")))


def department_names() -> dict[str, str]:
    return {c: d["name"] for c, d in gazetteer().deps.items()}
