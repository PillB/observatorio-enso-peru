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
        dk, pk, sk = key(dep), key(prov), key(dist)
        if dist:
            if c and len(c) >= 4:
                hit = self._by_name.get(("dist-prov", c[:4], sk))
                if hit and len(hit) == 1:
                    return hit[0]
            hit = self._by_name.get(("dist", dk, sk))
            if hit and len(hit) == 1:
                return hit[0]
        if c and len(c) == 4:
            return c
        if prov:
            hit = self._by_name.get(("prov", dk, pk))
            if hit and len(hit) == 1:
                return hit[0]
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
        """Coordenadas de la capital del nivel más fino conocido (lat, lon, precisión)."""
        for table, label in ((self.dist, "capital-distrito"), (self.prov, "capital-provincia"),
                             (self.dep, "capital-departamento")):
            rec = table.get(code)
            if rec and rec.get("lat") is not None:
                return rec["lat"], rec["lon"], label
        return None, None, ""

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
