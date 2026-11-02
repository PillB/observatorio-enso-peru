"""Las notas y avisos del histórico de noticias en el esquema del equipo de prevención.

Una fila por nota y lugar (UBIGEO) con las 13 columnas del tablero del equipo (``historico.esquema.TEAM_COLUMNS``,
con sus nombres exactos), luego los metadatos del catálogo histórico y, al final, los de la nota. Así el archivo
se carga en el mismo tablero que ``eventos.csv`` del catálogo. Nada se inventa: una nota sin lugar o sin un
peligro hidrometeorológico no tiene fila, y la duración, el punto fino y la dirección quedan vacíos (una nota no
los da).
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from typing import Iterable, Optional

from .historico import esquema as E
from .geo import key
from .historico.registro import make
from .news import hazards

NEWS_EXTRA = ["NoticiaId", "Medio", "Relevancia", "PeligrosNota", "MetodoLugar", "ConfianzaLugar", "Primera_vez"]
FIELDS = E.COLUMNS + NEWS_EXTRA
#: Una nota que nombra todo el país no debe llenar el archivo de filas iguales.
MAX_PLACES = 30
#: Peligro de la nota (``news.HAZARDS``) → DangerType. Sismos, volcanes, salud y «emergencia» sin otro peligro
#: no son peligros de clima y no entran (el catálogo histórico tampoco los incluye).
HAZARD_DANGER = {
    "inundacion": None,  # fluvial, pluvial o desborde: lo decide ``classify_flood`` con el texto
    "huaico": "Huayco/Alud",
    "lluvias": "Lluvias intensas",
    "oleaje": "Oleaje anomalo",
    "sequia": "Sequias",
    "calor": "Ola de calor",
    "frio": "Helada/Friaje",
    "viento": "Vientos fuertes",
    "incendio": "Incendio forestal",
}
#: Orden de prioridad cuando una nota trae varios (el más dañino primero).
PRIORITY = ("huaico", "inundacion", "lluvias", "oleaje", "viento", "frio", "calor", "sequia", "incendio")
LICENSE = "Titular y resumen citados con enlace a la nota; los derechos son del medio"


_FOREST_RE = re.compile(r"forestal|pastizal|vegetacion|bosque|quema agricola|quemas agricolas|cobertura vegetal|wildfire")
_FROST_RE = re.compile(r"helada|friaje|bajas temperaturas|ola de frio|descenso de (?:la )?temperatura")
_HAIL_RE = re.compile(r"granizo|granizada|aguanieve")
_SNOW_RE = re.compile(r"nevada|nieve")
_DEBRIS_RE = re.compile(r"huaico|huayco|aluvi|lloclla|flujo de (?:lodo|detritos)|quebrada")
_SLIDE_RE = re.compile(r"deslizamiento|derrumbe|landslide|mudslide")


def _specific(h: str, text: str) -> Optional[str]:
    """DangerType de un peligro de la nota. Las etiquetas de ``news.HAZARDS`` son más anchas que las del catálogo
    (los deslizamientos van con los huaicos, el granizo y la nieve con las heladas, todo incendio con los forestales),
    así que el tipo fino sale del texto; ``None`` si la nota no es de un peligro de clima (un incendio de vivienda)."""
    if h == "incendio":
        return "Incendio forestal" if _FOREST_RE.search(text) else None
    if h == "huaico":
        return "Deslizamiento" if _SLIDE_RE.search(text) and not _DEBRIS_RE.search(text) else "Huayco/Alud"
    if h == "frio":
        return ("Helada/Friaje" if _FROST_RE.search(text) else "Granizada" if _HAIL_RE.search(text)
                else "Nevada" if _SNOW_RE.search(text) else "Helada/Friaje")
    return HAZARD_DANGER[h]


def danger_of(item: dict) -> Optional[tuple[str, str, str]]:
    """(DangerType, método, peligro de la nota) de una nota, o ``None`` si no trae un peligro de clima.

    Las notas guardadas antes de que existiera ``hazards`` no lo traen: se calcula del titular y el resumen."""
    title, summary = item.get("title") or "", item.get("summary") or ""
    tags = item["hazards"] if "hazards" in item else hazards(title, summary)
    text = key(f"{title} {summary}")
    for h in PRIORITY:
        if h not in tags:
            continue
        if h == "inundacion":
            dt, method = E.classify_flood([title, summary], "")
            return dt, method, h
        dt = _specific(h, text)
        if dt:
            return dt, "texto", h
    return None


def _day(item: dict) -> str:
    return (item.get("published") or item.get("first_seen") or "")[:10]


def rows(items: Iterable[dict], territory, calendar) -> list[dict]:
    """Filas del esquema del equipo para ``items`` (más recientes primero)."""
    out: list[dict] = []
    for it in sorted(items, key=lambda i: i.get("published") or i.get("first_seen") or "", reverse=True):
        if it.get("feed") == "firms":
            continue  # focos de calor del satélite: detecciones, no eventos reportados
        d = danger_of(it)
        day = _day(it)
        places = (it.get("geo") or {}).get("places") or []
        if not d or not day or not places:
            continue
        try:
            datetime.strptime(day, "%Y-%m-%d")
        except ValueError:
            continue
        dt, method, hz = d
        geo = it["geo"]
        text = " ".join(x for x in (it.get("title"), it.get("summary")) if x)
        seen_codes: set[str] = set()
        for p in places[:MAX_PLACES]:
            code = str(p.get("code") or "")
            if len(code) not in (2, 4, 6) or code in seen_codes:
                continue
            seen_codes.add(code)
            rec = make(territory, calendar, code=code, day=day, precision="dia", danger=dt, origin="noticias",
                       source_id=f"{it['id']}-{code}", url=it.get("link") or "", license=LICENSE,
                       cite=f"{it.get('outlet') or it.get('feed') or ''}, {day}".strip(", "),
                       description=text[:400], danger_method=method, icen=False)
            rec["FechaTipo"] = "publicacion"  # la fecha es la de la nota, no la del evento
            rec["Confianza"] = "baja" if (p.get("confidence") or 0) < 0.6 else rec["Confianza"]
            rec.update({"NoticiaId": it["id"], "Medio": it.get("outlet") or "", "Relevancia": it.get("relevance") or "",
                        "PeligrosNota": "; ".join(it.get("hazards") or []), "MetodoLugar": p.get("method") or geo.get("method") or "",
                        "ConfianzaLugar": p.get("confidence") or "", "Primera_vez": it.get("first_seen") or ""})
            out.append(rec)
    return out


def _safe(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def to_csv(items: Iterable[dict], territory, calendar) -> str:
    """CSV con BOM y los códigos como texto, como ``eventos.csv`` del catálogo."""
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.DictWriter(buf, fieldnames=FIELDS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows(items, territory, calendar):
        w.writerow({k: _safe(r.get(k)) for k in FIELDS})
    return buf.getvalue()
