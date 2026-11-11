"""Fase ENSO de cada mes y nombre del evento al que pertenece un registro histórico.

* Fase costera: ICEN oficial (ENFEN/IGP) con la definición operacional del ENFEN (Nota Técnica
  01-2024), los mismos eventos que muestra la pestaña Historia (``signals.icen_events``).
* Fase del Pacífico central: ONI de NOAA/CPC (±0,5 °C), como referencia para impactos en la sierra
  sur y la Amazonía, que responden más al Pacífico central que a la costa.

``TipoEvento`` usa el nombre con que el país conoce cada evento («FEN 1997-98», «Niño Costero 2017»,
«Ciclón Yaku 2023») y, fuera de ellos, la temporada («Temporada de lluvias»). La atribución es
temporal: que un registro caiga dentro de un Niño no prueba que el Niño lo causó (``AtribucionENSO``
dice de dónde sale: la fuente, un registro curado o la ventana del ICEN).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..feeds.cpc import parse_seasonal
from ..feeds.peru import parse_icen_txt
from ..signals import icen_events

#: Eventos con nombre propio: (inicio, fin, TipoEvento, departamentos o None para todo el país). Solo se
#: aplican a peligros de lluvia, inundación, oleaje y viento (``NAMED_TYPES``): una helada en Puno en mayo
#: de 2017 no es parte del Niño Costero.
#: * Yaku: ciclón de marzo de 2023 que golpeó la costa norte y Lima (SENAMHI lo nombró el 7 de marzo);
#:   el resto de 2023-24 queda en el Niño costero que lo siguió.
#: * Niño Costero 2017: los 13 departamentos del Plan Integral de Reconstrucción con Cambios (7 de la
#:   costa con inundaciones y 6 con movimientos en masa: Cajamarca, Ayacucho, Arequipa, Huancavelica,
#:   Junín y Loreto). En los demás, los registros de enero a abril de 2017 quedan como «FEN costero 2017»
#:   (ventana del ICEN), igual que cualquier otro Niño moderado.
PIRCC_2017 = {"24", "20", "14", "13", "02", "15", "11", "06", "05", "04", "09", "12", "16"}
PIRCC_2017_URL = "https://elregionalpiura.com.pe/web-pdf/Plan-Integral-de-Reconstruccion-con-Cambios-18082017.pdf"
NAMED = [
    ("2023-03-01", "2023-03-31", "Ciclón Yaku 2023", {"24", "20", "14", "13", "02", "15", "07", "06", "11"}),
    ("2017-01-01", "2017-05-31", "Niño Costero 2017", PIRCC_2017),
]
#: Nombres cortos para los grandes Niños costeros (año de inicio del evento del ICEN).
BIG_NAMES = {"1972": "FEN 1972-73", "1982": "FEN 1982-83", "1997": "FEN 1997-98", "2015": "FEN 2015-16",
             "2023": "FEN 2023-24", "2026": "FEN 2026"}
#: Eventos que el tablero compara como «grandes Niños» (los que hicieron historia en el Perú).
GREAT = ["FEN 1982-83", "FEN 1997-98", "Niño Costero 2017", "Ciclón Yaku 2023", "FEN 2023-24"]

RAIN_TYPES = {"Inundacion fluvial", "Inundacion pluvial", "Inundacion", "Desborde de rio", "Huayco/Alud",
              "Deslizamiento", "Lluvias intensas", "Erosion", "Granizada", "Tormenta electrica", "Tormenta"}
NAMED_TYPES = RAIN_TYPES - {"Granizada"} | {"Oleaje anomalo", "Erosion costera", "Vientos fuertes"}
COLD_TYPES = {"Helada/Friaje", "Nevada"}


@dataclass
class Phase:
    phase: str          # El Niño costero | La Niña costera | Neutro | ""
    event: str          # «El Niño costero 1997-98 (extraordinario)»
    short: str          # «FEN 1997-98»
    icen: Optional[float]
    oni: Optional[float]


def _label(e: dict) -> tuple[str, str]:
    y0, y1 = e["start"][:4], e["end"][:4]
    span = y0 if y0 == y1 else f"{y0}-{y1[2:]}"
    if e["phase"] == "warm":
        mag = {"débil": "débil", "moderada": "moderado", "fuerte": "fuerte", "extraordinaria": "extraordinario"}.get(e["magnitude"], e["magnitude"])
        long = f"El Niño costero {span} ({mag}{', en curso' if e.get('ongoing') else ''})"
        return long, BIG_NAMES.get(y0, f"FEN costero {span}")
    return f"La Niña costera {span} ({e['magnitude']})", f"La Niña costera {span}"


class EnsoCalendar:
    def __init__(self, icen_text: str, oni_text: str = ""):
        icen = parse_icen_txt(icen_text).data
        self.icen = {p["period"]: p["value"] for p in icen}
        self.oni = {p["period"]: p["value"] for p in parse_seasonal(oni_text, name="oni").data} if oni_text else {}
        self.events = icen_events(icen)
        self.month_event: dict[str, dict] = {}
        for e in self.events:
            y, m = int(e["start"][:4]), int(e["start"][5:7])
            while f"{y}-{m:02d}" <= e["end"]:
                self.month_event[f"{y}-{m:02d}"] = e
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        self.first = min(self.icen) if self.icen else ""

    @classmethod
    def from_files(cls, icen: Path, oni: Optional[Path] = None) -> "EnsoCalendar":
        return cls(icen.read_text(encoding="utf-8"), oni.read_text(encoding="utf-8") if oni and oni.exists() else "")

    def phase(self, period: str) -> Phase:
        """Fase del mes ``AAAA-MM`` (vacía si el ICEN no cubre ese mes)."""
        if period not in self.icen:
            return Phase("", "", "", None, self.oni.get(period))
        e = self.month_event.get(period)
        if not e:
            return Phase("Neutro", "", "", self.icen[period], self.oni.get(period))
        long, short = _label(e)
        return Phase("El Niño costero" if e["phase"] == "warm" else "La Niña costera", long, short,
                     self.icen[period], self.oni.get(period))

    def tipo_evento(self, date: str, month_known: bool, danger: str, dep: str, source_cause: str,
                    icen: bool = True) -> tuple[str, str]:
        """(TipoEvento, AtribucionENSO) de un registro. ``icen=False``: el registro no se atribuye a un Niño o una
        Niña solo porque su fecha cae en la ventana del ICEN (las emergencias menores del SINPAD)."""
        period = date[:7]
        for a, b, name, deps in NAMED:
            if month_known and a <= date <= b and (deps is None or dep in deps) and danger in NAMED_TYPES:
                return name, "curado"
        if month_known and self.icen and period > max(self.icen) and source_cause not in ("El Niño", "La Niña"):
            return "ICEN pendiente", "pendiente"  # el ICEN de ese mes aún no se publica: no es «sin asociación»
        ph = self.phase(period) if month_known else Phase("", "", "", None, None)
        climate = danger in RAIN_TYPES or danger in {"Sequias", "Oleaje anomalo", "Erosion costera", "Epidemia", "Plaga",
                                                     "Vientos fuertes", "Ola de calor", "Incendio forestal"}
        if ph.phase == "El Niño costero" and climate and icen:
            return ph.short, "ventana-icen"
        if source_cause == "El Niño":
            return (ph.short or "FEN (según la fuente)"), "fuente"
        if source_cause == "La Niña":
            return (ph.short or "La Niña (según la fuente)"), "fuente"
        if ph.phase == "La Niña costera" and climate and icen:
            return ph.short, "ventana-icen"
        month = int(date[5:7]) if month_known else 0
        if danger in RAIN_TYPES and month in (11, 12, 1, 2, 3, 4):
            return "Temporada de lluvias", "ninguna"
        if danger in COLD_TYPES and month in (5, 6, 7, 8, 9):
            return "Temporada de heladas y friaje", "ninguna"
        return "Sin asociación ENSO", "ninguna"
