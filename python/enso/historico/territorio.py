"""Distritos, provincias y departamentos del Perú para el catálogo histórico.

Nombres y coordenadas de la capital: ``enso/data/ubigeo.json`` (INEI, el mismo nomenclátor del ubicador
de noticias). Atributos para el análisis de riesgo (macrorregión, superficie, densidad 2020, altitud,
IDH 2019, pobreza): ``data/historico/ref/distritos.csv``, extraído de ``ubigeo-peru-aumentado``
(J. M. Castagnetto, MIT), que los compila del INEI y del PNUD.

Las fuentes antiguas usan códigos de su época: un distrito que luego pasó a una provincia nueva cambia
de código (Putumayo, 160109 → 160801). ``LEGACY`` los traduce; lo demás se resuelve por nombre.
"""

from __future__ import annotations

import csv
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

from ..geo import key

ROOT = Path(__file__).resolve().parents[3]
UBIGEO = Path(__file__).resolve().parents[1] / "data" / "ubigeo.json"
ATTRS = ROOT / "data" / "historico" / "ref" / "distritos.csv"

#: Códigos de distrito que cambiaron (código antiguo → actual).
LEGACY = {
    "160109": "160801",  # Putumayo: de Maynas a la provincia de Putumayo (Ley 30186, 2014)
}

#: Nombres que usan las fuentes para un departamento (en ``key``): el SINPAD separa «Lima Metropolitana» y
#: «Lima Provincia» (las provincias fuera de Lima), que en el UBIGEO son el mismo departamento.
DEP_ALIASES = {"lima provincia": "lima", "lima provincias": "lima", "lima region": "lima", "region lima": "lima",
               "lima metropolitana": "lima"}
#: Otras grafías de provincias y distritos (en ``key``, sin lo que va entre paréntesis).
NAME_ALIASES = {"nasca": "nazca", "kimbiri": "quimbiri", "daniel alomia robles": "daniel alomias robles",
                "ihuayllo": "huayllo", "pampas grande": "pampas", "hualla": "huaya", "allauca": "ayauca",
                "san juan de iscos": "san juan de yscos", "caspizapa": "caspisapa", "lima metropolitana": "lima",
                "lurigancho-chosica": "lurigancho", "lurigancho chosica": "lurigancho", "echarati": "echarate",
                "ccatcca": "ccatca", "mariscal gamarra": "gamarra", "la encanada": "encanada",
                "san francisco de asis yarusyacan": "san francisco de asis de yarusyacan", "zana": "sana",
                "el arenal": "arenal", "raimondi": "raymondi", "antonio raimondi": "antonio raymondi",
                "san miguel del faique": "san miguel de el faique", "ccapacmarca": "capacmarca",
                "san pedro de laraos": "laraos"}


def _name(s: str) -> str:
    k = key(re.sub(r"\(.*?\)", " ", s or ""))
    return NAME_ALIASES.get(k, k)


def _loose(k: str) -> str:
    """Sin espacios, guiones ni signos: «anco_huallo» y «anco-huallo» son lo mismo."""
    return re.sub(r"[^a-z0-9]", "", k)


#: Macrorregiones del INEI con su nombre legible.
REGIONS = {"NORTE": "Norte", "CENTRO": "Centro", "SUR": "Sur", "ORIENTE": "Oriente",
           "LIMA METROPOLITANA": "Lima Metropolitana"}


class Territory:
    def __init__(self, ubigeo: Path = UBIGEO, attrs: Path = ATTRS):
        u = json.loads(ubigeo.read_text(encoding="utf-8"))
        self.dep = {d["ubigeo"]: d for d in u["departments"]}
        self.prov = {d["ubigeo"]: d for d in u["provinces"]}
        self.dist = {d["ubigeo"]: d for d in u["districts"]}
        self.attrs: dict[str, dict] = {}
        if attrs.exists():
            with attrs.open(encoding="utf-8") as fh:
                self.attrs = {r["ubigeo"]: r for r in csv.DictReader(fh)}
        self._by_name: dict[tuple, list[str]] = {}
        for code, d in self.dist.items():
            self._by_name.setdefault(("dist", key(self.dep[code[:2]]["name"]), key(d["name"])), []).append(code)
            self._by_name.setdefault(("dist-prov", code[:4], key(d["name"])), []).append(code)
        for code, d in self.prov.items():
            self._by_name.setdefault(("prov", key(self.dep[code[:2]]["name"]), key(d["name"])), []).append(code)
        for code, d in self.dep.items():
            self._by_name.setdefault(("dep", key(d["name"])), []).append(code)

    # ------------------------------------------------------------------
    def normalize(self, code: str) -> Optional[str]:
        """Código vigente (2, 4 o 6 dígitos) o None si no existe."""
        code = (code or "").strip()
        code = LEGACY.get(code, code)
        if len(code) == 6 and code in self.dist:
            return code
        if len(code) == 4 and code in self.prov:
            return code
        if len(code) == 2 and code in self.dep:
            return code
        return None

    def resolve(self, dep: str = "", prov: str = "", dist: str = "", code: str = "") -> Optional[str]:
        """El UBIGEO más fino que respaldan el código y los nombres de la fuente.

        Si el código no existe pero los nombres sí (distritos renombrados o reubicados), gana el nombre;
        si el código existe, se acepta aunque el nombre esté abreviado («STA.CRUZ DE COCACHACRA»)."""
        c = self.normalize(code)
        if c and len(c) == 6:
            return c
        dk, pk, sk = key(dep), _name(prov), _name(dist)
        dk = DEP_ALIASES.get(dk, dk)
        pc = None
        if prov and not (c and len(c) >= 4):
            hit = self._by_name.get(("prov", dk, pk))
            pc = hit[0] if hit and len(hit) == 1 else None
        base = c[:4] if c and len(c) >= 4 else pc
        if dist:
            if base:
                hit = self._by_name.get(("dist-prov", base, sk))
                if hit and len(hit) == 1:
                    return hit[0]
            hit = self._by_name.get(("dist", dk, sk))
            if hit and len(hit) == 1:
                return hit[0]
            if pc:
                # Grafía distinta («ANCO_HUALLO») o nombre truncado por la fuente («SANTA CRUZ DE TOLED»), pero
                # solo si dentro de su provincia hay un único distrito que coincida.
                loose = _loose(sk)
                names = {code: _loose(key(d["name"])) for code, d in self.dist.items() if code[:4] == pc}
                hit = [code for code, n in names.items() if n == loose]
                if not hit and len(loose) >= 8:
                    hit = [code for code, n in names.items() if n.startswith(loose)]
                if len(hit) == 1:
                    return hit[0]
            if not pc and dk:
                # Sin provincia: grafía distinta («TAMBOGRANDE», «CAMPO VERDE») si en el departamento hay un único
                # distrito que coincida sin espacios ni guiones.
                loose = _loose(sk)
                hit = [code for code, d in self.dist.items()
                       if key(self.dep[code[:2]]["name"]) == dk and _loose(_name(d["name"])) == loose]
                if len(hit) == 1:
                    return hit[0]
        if c and len(c) == 4:
            return c
        if pc:
            return pc
        if c:
            return c
        hit = self._by_name.get(("dep", dk))
        return hit[0] if hit and len(hit) == 1 else None

    def names(self, code: str) -> tuple[str, str, str]:
        """(Departamento, Provincia, Distrito) con tildes; vacíos los niveles que el código no tiene."""
        d = self.dep.get(code[:2], {}).get("name", "")
        p = self.prov.get(code[:4], {}).get("name", "") if len(code) >= 4 else ""
        s = self.dist.get(code, {}).get("name", "") if len(code) == 6 else ""
        return d, p, s

    def point(self, code: str) -> tuple[Optional[float], Optional[float], str]:
        """Coordenadas de la capital del nivel más fino conocido (lat, lon, precisión). Un distrito creado
        después del nomenclátor (Kumpirushiato, 2016) no tiene capital ahí: va la de su provincia."""
        for n, table, label in ((6, self.dist, "capital-distrito"), (4, self.prov, "capital-provincia"),
                                (2, self.dep, "capital-departamento")):
            rec = table.get(code[:n]) if len(code) >= n else None
            if rec and rec.get("lat") is not None:
                # Un distrito sin capital en el nomenclátor lleva un punto dentro de su polígono («point»: «interior»).
                return rec["lat"], rec["lon"], "interior-distrito" if rec.get("point") == "interior" else label
        return None, None, ""

    def has_capital(self, code: str) -> bool:
        """Si el distrito tiene capital (y polígono) en el nomenclátor y los límites del IGN."""
        return self.dist.get(code, {}).get("lat") is not None

    def region(self, code: str) -> str:
        """Macrorregión del INEI; para provincia o departamento, la de su capital."""
        a = self.attrs.get(code if len(code) == 6 else self._capital_district(code), {})
        return REGIONS.get(a.get("macroregion", ""), "")

    def altitude(self, code: str) -> Optional[int]:
        a = self.attrs.get(code) if len(code) == 6 else None
        try:
            return int(float(a["altitud"])) if a and a.get("altitud") else None
        except ValueError:
            return None

    def _capital_district(self, code: str) -> str:
        """Primer distrito (el de la capital, sufijo 01) de una provincia o departamento."""
        return (code + "0101")[:6] if len(code) == 2 else (code + "01")[:6]

    def population(self, code: str) -> Optional[float]:
        """Población 2020 estimada (densidad × superficie) sumada sobre los distritos del código."""
        tot, seen = 0.0, False
        for c, a in self.attrs.items():
            if c.startswith(code):
                try:
                    tot += float(a["poblacion_2020"])
                    seen = True
                except (KeyError, ValueError):
                    pass
        return round(tot) if seen else None


@lru_cache(maxsize=1)
def territory() -> Territory:
    return Territory()
