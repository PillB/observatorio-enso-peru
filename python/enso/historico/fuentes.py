"""Lectores de las fuentes de 2016 en adelante y de las capas de contexto distrital.

DesInventar (``desinventar.py``) es la serie homogénea 1970-2015. Después de 2015 no hay una base
pública equivalente con impactos, así que el catálogo junta las que se pueden descargar sin permisos especiales
(``docs/memoria-desastres.md``, «Fuentes»):

* **SINPAD 2016-2018**: emergencias del SINPAD (INDECI) en una copia pública de ArcGIS Online. Tiene el
  código SINPAD, el fenómeno, el distrito por nombre y un punto, pero no las cifras de daños. Cubre el
  Niño Costero 2017 con más de 7 000 emergencias.
* **SINPAD desde 2019**: la consulta pública del portal del SINPAD (INDECI): cada emergencia con su código, el
  peligro principal, el distrito por nombre, la fecha, el nivel y el estado. Sin descripción, punto ni daños.
* **IDMC, eventos de desplazamiento (IDU) 2025-2026**: el Observatorio de Desplazamiento Interno (IDMC)
  publica en HDX cada emergencia del INDECI que dejó viviendas destruidas o inhabitables, por distrito y
  con coordenadas. Cubre la temporada 2025 y el Niño costero de 2026.
* **IDMC, eventos por departamento y mes 2019-2024**: la misma fuente, más gruesa (casi siempre un
  departamento y un mes), con las personas desplazadas del ciclón Yaku y el Niño costero 2023-24.
* **NASA, catálogo global de deslizamientos (GLC)**: deslizamientos de 2016 a 2020 con la noticia que los
  reportó.

Y tres capas que no son eventos sino el peligro identificado hoy en cada distrito:

* **INGEMMET**: inventario de peligros geológicos (28 915 puntos) y zonas críticas (2 186).
* **ANA** (servicio COEN FEN del SIGRID/CENEPRED): puntos críticos en ríos y quebradas con su nivel de
  peligro, la población y las viviendas expuestas, y la acción recomendada con su costo.
* **CENEPRED / COE Salud**: establecimientos de salud afectados en la temporada de lluvias 2022-2023.

Cada lector recibe el documento ya descargado (las fuentes de ArcGIS se guardan como JSON canónico,
``tools.build_historico.fetch_arcgis``) y devuelve filas completas (``registro.make``).
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Iterator, Optional
from urllib.parse import quote

from . import esquema as E
from .registro import make

LIMA = timezone(timedelta(hours=-5))  # el Perú no usa horario de verano

SINPAD_URL = "https://services8.arcgis.com/2qDHoDLqu6VOlf1y/arcgis/rest/services/Emergencias/FeatureServer/0"
SINPAD_LICENSE = "Datos del SINPAD (INDECI), información pública; copia en ArcGIS Online de un tercero"
SINPAD_API_URL = "https://prod4.indeci.gob.pe/portal-sinpad/api/v1/public/emergencias"
SINPAD_API_LICENSE = "SINPAD (INDECI), información pública (Ley N° 27806)"
IDMC_PAGE = IDMC_EVENTS_PAGE ="https://www.internal-displacement.org/database/displacement-data/"
IDMC_LICENSE = "IDMC con datos del INDECI, CC BY-NC-SA 3.0 IGO"
#: Columnas de la API del IDMC con otro nombre en sus exportaciones CSV (las de HDX): el lector usa estas.
IDMC_ALIASES = {"standard_popup_text": "description", "hazard_sub_type_name": "hazard_subtype_name"}
GLC_PAGE = "https://gpm.nasa.gov/landslides/data.html"
GLC_LICENSE = "NASA Global Landslide Catalog (Kirschbaum et al. 2010, 2015), dominio público con cita"

#: Fenómeno del SINPAD → DangerType. ``None``: se decide por el texto de la emergencia. Lo que no está
#: (incendios urbanos, sismos, contaminación, explosiones…) no es de origen climático y no entra.
SINPAD_TYPES = {
    "PRECIPITACIONES - LLUVIA": "Lluvias intensas", "INUNDACION": "Inundacion",
    "HELADA": "Helada/Friaje", "DESCENSO DE TEMPERATURA": "Helada/Friaje", "FRIAJE": "Helada/Friaje",
    "VIENTOS FUERTES": "Vientos fuertes", "SEQUIA": "Sequias",
    "DESLIZAMIENTO": "Deslizamiento", "DERRUMBE": "Deslizamiento",
    "HUAYCO": "Huayco/Alud", "ALUVION": "Huayco/Alud", "ALUD": "Huayco/Alud", "AVALANCHA": "Huayco/Alud",
    "INCENDIO FORESTAL": "Incendio forestal", "PRECIPITACIONES - GRANIZO": "Granizada",
    "PRECIPITACIONES - NEVADA": "Nevada", "TORMENTA ELECTRICA (TEMPESTAD ELECTRICA)": "Tormenta electrica",
    "EROSION": "Erosion", "MAREJADA": "Oleaje anomalo",
    "OTROS DE GEODINAMICA EXTERNA": None, "OTRO FENOM. MET.  O HIDROL.": None,
    "EPIDEMIAS": "Epidemia", "PLAGAS": "Plaga",
}
#: Peligro principal del portal del SINPAD (desde 2019; los 89 nombres que usa, en ``esquema.key``) →
#: DangerType. ``None``: el peligro fue climático pero no se sabe cuál («otros», colapsos de estructuras «por
#: agente climático», deglaciación) y no entra. Epidemias y plagas tampoco: el portal no trae la descripción para
#: saber si las causó el clima. Lo que no está no es de origen climático: incendios urbanos e industriales,
#: sismos, vulcanismo y lahares, derrumbes y colapsos de viviendas o estructuras, aniegos (casi siempre de
#: tuberías), embalses, contaminación, derrames, accidentes, conflictos.
SINPAD_API_TYPES = {
    "lluvias intensas": "Lluvias intensas",
    "inundacion por desborde de rio": "Inundacion fluvial",
    "inundacion por colapso de defensa riberena": "Desborde de rio",
    "inundacion por saturacion del suelo para drenaje (pluvial)": "Inundacion pluvial",
    "inundacion por desborde de canales": "Inundacion",
    "inundacion por desborde lago o laguna": "Inundacion",
    "inundacion por desborde en la ruptura de diques": "Inundacion",
    "huaico": "Huayco/Alud", "aluvion": "Huayco/Alud", "aluviones": "Huayco/Alud", "alud": "Huayco/Alud",
    "aludes": "Huayco/Alud", "avalancha": "Huayco/Alud",
    "deslizamiento": "Deslizamiento", "derrumbe cerros": "Deslizamiento", "derrumbe de rocas": "Deslizamiento",
    "reptacion": "Deslizamiento",
    "erosion": "Erosion", "erosion fluvial": "Erosion",
    "oleaje anomalo": "Oleaje anomalo", "oleajes anomalos": "Oleaje anomalo", "maretazo (marejadas)": "Oleaje anomalo",
    "vientos fuertes": "Vientos fuertes", "temporales (vientos con lluvias)": "Tormenta",
    "tempestades electricas": "Tormenta electrica", "tormentas electricas": "Tormenta electrica",
    "granizadas": "Granizada", "nevadas": "Nevada", "nevada": "Nevada",
    "heladas": "Helada/Friaje", "helada": "Helada/Friaje", "friaje": "Helada/Friaje",
    "descenso de temperatura": "Helada/Friaje", "bajas temperaturas": "Helada/Friaje",
    "olas de calor": "Ola de calor",
    "sequias": "Sequias", "sequia": "Sequias", "deficit hidrico": "Sequias",
    "incendios forestales": "Incendio forestal",
    "epidemias": "Epidemia", "epidemia dengue": "Epidemia", "epidemia covid-19": "Epidemia",
    "plaga": "Plaga", "plagas": "Plaga",
    "otros": None, "colapso de estructura por agente climatico": None, "deglaciacion": None, "desglaciacion": None,
}
#: El portal registra cada emergencia, también las pequeñas de atención local. Para no confundir una temporada de
#: lluvias normal con un gran Niño, una emergencia cuenta para un Niño o una Niña del ICEN (por su fecha) solo
#: desde este nivel: atención regional o nacional. Los eventos con nombre (Ciclón Yaku 2023) cuentan siempre.
SINPAD_ICEN_LEVEL = 3
#: Niveles de emergencia del SINAGERD (Reglamento de la Ley N° 29664, art. 43): quién la atiende.
SINPAD_LEVELS = {1: "atención local", 2: "atención local", 3: "atención regional",
                 4: "intervención del gobierno nacional", 5: "gran magnitud"}
#: Subtipo del IDMC → DangerType. «Storm» junta lluvia, viento y rayos (el IDMC no dice cuál): queda
#: «Tormenta». «Mixed disasters» (varios peligros a la vez) y los sismos no entran.
IDMC_TYPES = {
    "Flood": "Inundacion", "Riverine flood": "Inundacion fluvial", "Flash flood": "Inundacion pluvial",
    "Storm": "Tormenta", "Hailstorm": "Granizada", "Winter storm/Blizzard": "Nevada",
    "Cold wave": "Helada/Friaje", "Extreme Temperature": "Helada/Friaje",
    "Dry mass movement": "Deslizamiento", "Landslide/Wet mass movement": "Deslizamiento",
    "Mass Movement": "Deslizamiento", "Wildfire": "Incendio forestal", "Erosion": "Erosion",
    "Drought": "Sequias",
}
GLC_TYPES = {"mudslide": "Huayco/Alud", "debris_flow": "Huayco/Alud", "lahar": "Huayco/Alud",
             "landslide": "Deslizamiento", "rock_fall": "Deslizamiento", "complex": "Deslizamiento",
             "riverbank_collapse": "Erosion"}
GLC_NOT_CLIMATE = {"earthquake", "construction", "mining", "leaking_pipe", "dam_embankment_collapse",
                   "volcano", "freeze_thaw"}

_CLIMATE_TEXT = re.compile(r"\blluvi|\bprecipitac|\bfriaje|\bhelad|\bbajas temperaturas|\bnino\b|\binundac|\bhuayc|\bhuaic")
_QUAKE = re.compile(r"\bsism|\bterremot|\btemblor")
_PLACE = re.compile(
    r"\b(?:localidad|caserio|sector|centro poblado|c\s?\.?\s?p\s?\.?|anexo|comunidad(?: campesina| nativa)?|barrio|"
    r"urbanizacion|aa\s?\.?\s?hh\s?\.?|asentamiento humano|pueblo joven|pj|paraje|quebrada|rio)\s+(?:de(?:l| la| los| las)?\s+)?"
    r"([a-z0-9][a-z0-9 .'\-]{2,40}?)(?=\s+(?:distrito|dist\b|provincia|prov\b|region|departamento|del distrito|en el|en la|y\b)|[,;.]|$)")


# ---------------------------------------------------------------------------
# Ubicación
# ---------------------------------------------------------------------------
def locate_point(lat, lon) -> tuple[Optional[dict], Optional[tuple]]:
    """(``limites.locate`` del punto, punto redondeado), o (None, None) si no hay coordenadas válidas."""
    from ..limites import locate

    try:
        if lat not in (None, "", 0) and lon not in (None, "", 0):
            loc = locate(float(lat), float(lon))
            if loc:
                return loc, (round(float(lat), 5), round(float(lon), 5))
    except (TypeError, ValueError):
        pass
    return None, None


def inside(territory, code: str, loc: Optional[dict]) -> bool:
    """Si el punto ubicado cae en el área ``code``. Un distrito sin polígono en los límites (uno más nuevo que ellos) no
    tiene polígono ni capital en el nomenclátor: su punto cae en el distrito del que se separó, y basta con que esté
    en la misma provincia."""
    if not loc or not code:
        return False
    if loc["code"].startswith(code):
        return True
    return len(code) == 6 and not territory.has_capital(code) and loc["code"][:4] == code[:4]


def newer_sibling(code: str, loc: Optional[dict]) -> Optional[str]:
    """El distrito creado después de 2020 en el que cae el punto de una fuente que nombró a otro distrito de la misma
    provincia (el SINPAD de 2017 dice Padre Abad y el punto está en lo que hoy es Boquerón): el UBIGEO vigente es el
    del punto."""
    from ..limites import CREATED_AFTER_2020

    c = (loc or {}).get("code", "")
    if len(code) == 6 and len(c) == 6 and c != code and c[:4] == code[:4] and c in CREATED_AFTER_2020:
        return c
    return None


def place(territory, dep: str, prov: str, dist: str, lat, lon, code: str = "") -> tuple[Optional[str], Optional[tuple], str]:
    """(UBIGEO, coordenadas de la fuente si son coherentes, método).

    Primero los nombres (o el código) de la fuente; si no alcanzan para el distrito, el punto de la fuente
    dentro de los límites del INDECI, siempre que caiga en la provincia o el departamento que dicen los
    nombres. Las coordenadas de la fuente se conservan solo si caen en el área asignada."""
    named = territory.resolve(dep or "", prov or "", dist or "", code or "")
    loc, pt = locate_point(lat, lon)
    if named and len(named) == 6:
        if newer_sibling(named, loc):
            return loc["code"], pt, "punto"
        return named, (pt if inside(territory, named, loc) else None), "nombre"
    if loc and len(loc["code"]) == 6 and (not named or loc["code"].startswith(named)):
        return loc["code"], pt, "punto"
    if named:
        return named, (pt if inside(territory, named, loc) else None), "nombre"
    if loc and not loc.get("offshore"):
        return loc["code"], pt, "punto"
    return None, None, ""


_NOT_PLACE = re.compile(r"^(?:agropecuario|agricola|salud|educacion|educativo|vivienda|transporte|urbano|rural|privado|publico)\b")


def _place_name(text: str) -> str:
    """El lugar más fino que nombra la descripción («localidad de Paucar», «caserío La Pared»)."""
    for m in _PLACE.finditer(E.key(text)):
        name = m.group(1).strip(" .-")
        if not _NOT_PLACE.match(name):
            return name.title()
    return ""


def _sentence(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return (text[:1].upper() + text[1:].lower()) if text.isupper() else text


# ---------------------------------------------------------------------------
# SINPAD 2016-2018 (copia de ArcGIS Online)
# ---------------------------------------------------------------------------
def sinpad_type(fen: str, desc: str) -> tuple[Optional[str], str]:
    """(DangerType, método) de una emergencia del SINPAD, o (None, motivo) si no entra."""
    if fen not in SINPAD_TYPES:
        return None, "no climático"
    t = E.key(desc)
    if _QUAKE.search(t):
        return None, "sismo"
    dt = SINPAD_TYPES[fen]
    if dt in ("Epidemia", "Plaga"):
        return (dt, "fuente") if _CLIMATE_TEXT.search(t) else (None, "sin causa climática")
    if dt == "Inundacion":
        return E.classify_flood([desc], "")
    if dt is None:
        if E.is_huayco_text(desc):
            return "Huayco/Alud", "texto"
        if re.search(r"\bdesliz|\bderrumb", t):
            return "Deslizamiento", "texto"
        if re.search(r"\boleaje|\bmarejad|\bmaretazo", t):
            return "Oleaje anomalo", "texto"
        if re.search(r"\bhelad|\bfriaje|\btemperatur", t):
            return "Helada/Friaje", "texto"
        if re.search(r"\bdesbord|\bcrecida|\bincremento del (?:caudal|rio)|\binundac", t):
            return E.classify_flood([desc], "")
        if re.search(r"\blluvi|\bprecipitac", t):
            return "Lluvias intensas", "texto"
        return None, "sin tipo"
    return dt, "fuente"


def _edan(n) -> str:
    return "" if not n else f", con {n} evaluación de daños" if n == 1 else f", con {n} evaluaciones de daños"


def sinpad(doc: dict, territory, calendar, since: str = "2016-01-01", until: str = "2018-12-31",
           skipped: Optional[Counter] = None) -> Iterator[dict]:
    """Emergencias de origen climático. Desde 2016: las de 2015 ya están en DesInventar."""
    skipped = skipped if skipped is not None else Counter()
    base = doc.get("source") or SINPAD_URL
    for f in doc["features"]:
        a, g = f["attributes"], f.get("geometry") or {}
        ms = a.get("FECHA_EMERGENCIA")
        if not ms:
            skipped["sin fecha"] += 1
            continue
        # La capa guarda la hora de Lima como si fuera UTC: convertirla a Lima movía al día anterior las emergencias de
        # 00:00 a 04:59 (comprobado con las fechas que cita la descripción).
        day = datetime.fromtimestamp(int(ms) / 1000, timezone.utc).date().isoformat()
        if not (since <= day <= until):
            continue
        fen, desc = (a.get("DES_FENOME") or "").strip(), (a.get("DES_EMERGE") or "").strip()
        dt, method = sinpad_type(fen, desc)
        if not dt:
            skipped[method] += 1
            continue
        code, latlon, how = place(territory, a.get("DES_DPTO"), a.get("DES_PROV"), a.get("DES_DIST"), g.get("y"), g.get("x"))
        if not code:
            skipped["sin lugar"] += 1
            continue
        cod = (a.get("COD_EMERGE") or str(a.get("OBJECTID"))).strip()
        url = f"{base}/query?where={quote(f'COD_EMERGE=' + chr(39) + cod + chr(39))}&outFields=*&f=html"
        names = " / ".join(x for x in (a.get("DES_DIST"), a.get("DES_PROV"), a.get("DES_DPTO")) if x)
        note = "" if how == "nombre" else " Distrito asignado por el punto de la emergencia (el nombre de la fuente está abreviado)."
        yield make(territory, calendar, code=code, day=day, precision="dia", danger=dt, origin="sinpad",
                   source_id=cod, url=url, license=SINPAD_LICENSE,
                   cite=f"SINPAD (INDECI), emergencia {cod}: «{desc}» ({fen.lower()}; {names})",
                   description=f"{_sentence(desc)}. Emergencia registrada en el SINPAD como «{fen.lower()}»{_edan(a.get('EDANOS'))}.{note}",
                   place=_place_name(desc), source_type=fen, danger_method=method, latlon=latlon)


# ---------------------------------------------------------------------------
# SINPAD desde 2019 (portal público del INDECI)
# ---------------------------------------------------------------------------
def sinpad_api_type(fen: str) -> tuple[Optional[str], str]:
    """(DangerType, método) del peligro principal de una emergencia del portal, o (None, motivo)."""
    k = E.key(fen)
    if k not in SINPAD_API_TYPES:
        return None, "no climático"
    dt = SINPAD_API_TYPES[k]
    if dt in ("Epidemia", "Plaga"):
        return None, "sin causa climática"
    return (dt, "fuente") if dt else (None, "sin tipo")


def _level(n) -> str:
    return f", nivel {n} ({SINPAD_LEVELS[n]})" if n in SINPAD_LEVELS else ", sin nivel asignado"


def sinpad_api(doc: dict, territory, calendar, since: str = "2019-01-01",
               skipped: Optional[Counter] = None) -> Iterator[dict]:
    """Emergencias de origen climático del portal público del SINPAD. Desde 2019, porque 2016-2018 viene de
    la copia de ArcGIS Online (con descripción y punto) y la consulta del portal empieza el 01-01-2019. El
    portal solo da el peligro, el distrito, la fecha, el nivel y el estado: sin descripción ni daños."""
    skipped = skipped if skipped is not None else Counter()
    base = doc.get("source") or SINPAD_API_URL
    for it in doc["items"]:
        when = (it.get("fechaHoraEvento") or "").strip()
        try:
            day = datetime.strptime(when[:10], "%d/%m/%Y").date().isoformat()
        except ValueError:
            skipped["sin fecha"] += 1
            continue
        if day < since:
            continue
        fen = re.sub(r"\s+", " ", it.get("peligroPrincipal") or "").strip()
        dt, method = sinpad_api_type(fen)
        if not dt:
            skipped[method] += 1
            continue
        names = (it.get("dptoProvDistr") or "").split("/")
        dep, prov, dist = (names + ["", "", ""])[:3] if len(names) <= 3 else (names[0], names[1], "/".join(names[2:]))
        code, _, _ = place(territory, dep, prov, dist, None, None)
        if not code:
            skipped["sin lugar"] += 1
            continue
        cod = str(it.get("codigoSinpad") or "").strip()
        state = (it.get("estado") or "").strip().lower()
        where = " / ".join(x.strip() for x in reversed(names) if x.strip())
        yield make(territory, calendar, code=code, day=day, precision="dia", danger=dt, origin="sinpad",
                   source_id=cod, url=f"{base}?codigoSinpad={cod}", license=SINPAD_API_LICENSE,
                   cite=f"SINPAD (INDECI), emergencia {cod}: {fen.lower()} en {where}, {when}",
                   description=(f"Emergencia por {fen.lower()} registrada en el SINPAD con el código {cod}"
                                f"{_level(it.get('nivel'))}." + (f" Estado en el SINPAD: {state}." if state else "")),
                   source_type=fen, danger_method=method, icen=(it.get("nivel") or 0) >= SINPAD_ICEN_LEVEL)


# ---------------------------------------------------------------------------
# IDMC
# ---------------------------------------------------------------------------
_HOUSES = re.compile(r"(destroyed|made uninhabitable or destroyed|made uninhabitable)\s+(one|\d[\d,]*)\s+(?:house|home)", re.I)


def _houses(desc: str) -> dict:
    out = {}
    for verb, n in _HOUSES.findall(desc or ""):
        k = "ViviendasDestruidas" if verb.lower() == "destroyed" else "ViviendasAfectadas"
        out[k] = out.get(k, 0) + (1 if n.lower() == "one" else int(n.replace(",", "")))
    return out


def _idmc_rows(text: str) -> Iterator[dict]:
    """Filas de un CSV del IDMC, venga de su API (``tools.build_historico.idmc_api``) o de una exportación."""
    for r in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        for api, name in IDMC_ALIASES.items():
            if not r.get(name):
                r[name] = r.get(api) or ""
        yield r


def idmc_idu(text: str, territory, calendar, skipped: Optional[Counter] = None) -> Iterator[dict]:
    """Eventos de desplazamiento por distrito (IDU, 2025 en adelante): «Recommended figure»."""
    skipped = skipped if skipped is not None else Counter()
    for r in _idmc_rows(text):
        if (r.get("iso3") or "PER") != "PER":
            continue
        if r.get("role") != "Recommended figure":
            skipped["triangulación (agregado departamental)"] += 1
            continue
        dt = IDMC_TYPES.get(r.get("subtype") or r.get("type") or "")
        # El IDMC clasifica los movimientos en masa «secos» como geofísicos, pero en el Perú casi todos ocurren
        # en la temporada de lluvias (derrumbes del INDECI): entran; los sismos y volcanes, no.
        if not dt or (r.get("type") or "") in ("Earthquake", "Volcanic activity"):
            skipped[r.get("subtype") or r.get("type") or "?"] += 1
            continue
        parts = [p.strip() for p in (r.get("locations_name") or "").split(",")]
        dist = parts[0] if len(parts) >= 4 else ""
        prov = re.sub(r"^Province of |\s+Province$", "", parts[1]) if len(parts) >= 4 else ""
        dep = parts[-2] if len(parts) >= 2 else ""
        code, latlon, how = place(territory, dep, prov, dist, r.get("latitude"), r.get("longitude"))
        if not code:
            skipped["sin lugar"] += 1
            continue
        day = r.get("displacement_start_date") or r.get("displacement_date")
        end = r.get("displacement_end_date") or day
        dur = (date.fromisoformat(end) - date.fromisoformat(day)).days + 1 if end >= day else None
        imp = {"Desplazados": int(float(r["figure"])) if r.get("figure") else None, **_houses(r.get("description", ""))}
        where = ", ".join(x for x in territory.names(code)[::-1] if x)
        facts = [f"{imp['Desplazados']} personas desplazadas" if imp["Desplazados"] else ""]
        if imp.get("ViviendasDestruidas"):
            facts.append(f"{imp['ViviendasDestruidas']} viviendas destruidas")
        if imp.get("ViviendasAfectadas"):
            facts.append(f"{imp['ViviendasAfectadas']} viviendas inhabitables o destruidas")
        summary = f"{E.DANGER_LABELS.get(dt, dt)} en {where}: {'; '.join(x for x in facts if x) or 'viviendas inhabitables'} (IDMC con datos del INDECI; tipo del IDMC: {r.get('subtype')})."
        yield make(territory, calendar, code=code, day=day, precision="dia", danger=dt, origin="idmc",
                   source_id=r["id"], url=IDMC_PAGE, license=IDMC_LICENSE,
                   cite=f"IDMC, evento {r.get('event_id')} «{r.get('event_name')}», con datos del INDECI",
                   description=f"{summary} Texto del IDMC: {r.get('description', '').strip()}",
                   place=", ".join(p for p in (re.sub(r"^Province of |\s+Province$", "", x) for x in parts) if p and p != "Peru"), duration=dur,
                   source_type=f"{r.get('type')} / {r.get('subtype')}", impacts=imp, latlon=latlon)


_EVENT = re.compile(r"^\s*Peru\s*:\s*(?P<haz>[^-–]+?)\s*[-–]\s*(?P<place>.+?)\s*(?:[-–]\s*)?\(?(?:\d{1,2}/\d{1,2}/\d{4}|[A-Z][a-z]+ \d{4})\)?\s*$")


def idmc_events(text: str, territory, calendar, since: int = 2019, until: int = 2024,
                skipped: Optional[Counter] = None) -> Iterator[dict]:
    """Eventos del IDMC por departamento (y a veces provincia o distrito) de 2019 a 2024."""
    skipped = skipped if skipped is not None else Counter()
    seen: Counter = Counter()
    for r in _idmc_rows(text):
        if not (r.get("year") or "")[:4].isdigit() or not (since <= int(r["year"]) <= until):
            continue
        m = _EVENT.match(r.get("event_name") or "")
        haz_name = (m.group("haz") if m else "").lower()
        dt = IDMC_TYPES.get(r.get("hazard_subtype_name") or "") or IDMC_TYPES.get(r.get("hazard_type_name") or "")
        if "wind" in haz_name:
            dt = "Vientos fuertes"
        elif "heavy rain" in haz_name:
            dt = "Lluvias intensas"
        elif "mudslide" in haz_name or "debris" in haz_name:
            dt = "Huayco/Alud"
        elif "riverine" in haz_name:
            dt = "Inundacion fluvial"
        elif "dam release" in haz_name:
            dt = None
        if not dt or (r.get("hazard_type_name") or "") in ("Earthquake", "Volcanic activity") or not m:
            skipped[r.get("hazard_type_name") or "sin tipo"] += 1
            continue
        tokens = [t.strip() for t in re.split(r"[,()]| and ", m.group("place")) if t.strip()]
        tokens = [re.sub(r"\s+(?:provinces?|districts?)$", "", t, flags=re.I) for t in tokens]
        dep = territory.resolve(tokens[0]) if tokens else None
        if not dep or len(dep) != 2:
            skipped["varios departamentos o sin lugar"] += 1
            continue
        finer, other_dep = [], False
        dists = {t: d for t in tokens[1:] if len(d := territory.resolve(tokens[0], "", t) or "") == 6}
        for t in tokens[1:]:
            prov = territory.resolve(tokens[0], t) or ""
            prov = prov if len(prov) == 4 else ""
            # «Junín, Chanchamayo, Pichanaqui»: la provincia que solo precisa a un distrito suyo no cuenta aparte.
            if prov and any(d[:4] == prov for u, d in dists.items() if u != t):
                continue
            c = dists.get(t) or prov
            if c:
                finer.append(c)
            elif (territory.resolve(t) or "") not in ("", dep):
                other_dep = True
        if other_dep:
            skipped["varios departamentos o sin lugar"] += 1
            continue
        # Un distrito o una provincia; si nombra varios de la misma provincia, la provincia.
        code = dep
        if len(set(finer)) == 1:
            code = finer[0]
        elif finer and len({c[:4] for c in finer}) == 1:
            code = finer[0][:4]
        day = r["start_date"]
        precision = "dia" if r.get("start_date_accuracy") == "Day" else "mes"
        day = day if precision == "dia" else day[:7] + "-01"
        imp = {"Desplazados": int(float(r["new_displacement"])) if r.get("new_displacement") else None}
        # El archivo no trae identificador: uno estable a partir del contenido (y un sufijo si se repite).
        sid = "evento-" + hashlib.sha1("|".join(r.get(k) or "" for k in ("event_name", "start_date", "hazard_type_name",
                                                                         "new_displacement")).encode()).hexdigest()[:10]
        seen[sid] += 1
        sid += f"-{seen[sid]}" if seen[sid] > 1 else ""
        yield make(territory, calendar, code=code, day=day, precision=precision, danger=dt, origin="idmc",
                   source_id=sid, url=IDMC_EVENTS_PAGE,
                   license=IDMC_LICENSE, cite=f"IDMC, «{r['event_name'].strip()}», con datos del INDECI",
                   description=f"{E.DANGER_LABELS.get(dt, dt)}: {r['event_name'].strip()} (IDMC, {r.get('new_displacement') or 'sin'} desplazamientos{', cifra del mes en el departamento' if precision == 'mes' else ''}).",
                   place=m.group("place"), source_type=f"{r.get('hazard_type_name')} / {r.get('hazard_subtype_name') or haz_name}",
                   impacts=imp, confidence="baja" if len(code) == 2 else None)


# ---------------------------------------------------------------------------
# NASA GLC
# ---------------------------------------------------------------------------
def glc(doc: dict, territory, calendar, since: str = "2016-01-01", skipped: Optional[Counter] = None) -> Iterator[dict]:
    skipped = skipped if skipped is not None else Counter()
    for f in doc["features"]:
        a = f["attributes"]
        if not a.get("ev_date"):
            continue
        day = datetime.fromtimestamp(a["ev_date"] / 1000, timezone.utc).date().isoformat()
        if day < since:
            continue
        if a.get("ls_trig") in GLC_NOT_CLIMATE:
            skipped[a["ls_trig"]] += 1
            continue
        dt = GLC_TYPES.get(a.get("ls_cat") or "", "Deslizamiento")
        code, latlon, _ = place(territory, a.get("div_name") or "", "", "", a.get("latitude"), a.get("longitude"))
        if not code:
            skipped["sin lugar"] += 1
            continue
        link = (a.get("src_link") or "").strip()
        dead = a.get("fatalities") or None
        yield make(territory, calendar, code=code, day=day, precision="dia", danger=dt, origin="nasa-glc",
                   source_id=str(a.get("ev_id")), url=link if link.startswith(("http://", "https://")) else GLC_PAGE,
                   license=GLC_LICENSE,
                   cite=f"{(a.get('src_name') or '').strip() or 'Noticia'} vía NASA Global Landslide Catalog (evento {a.get('ev_id')})",
                   description=f"{(a.get('ev_title') or '').strip()}. {(a.get('ev_desc') or '').strip()} (Detonante según la NASA: {a.get('ls_trig')}; tamaño: {a.get('ls_size')}.)",
                   place=(a.get("loc_desc") or "").strip(), source_type=f"{a.get('ls_cat')} ({a.get('ls_trig')})",
                   impacts={"Fallecidos": dead, "Heridos": a.get("injuries") or None}, latlon=latlon,
                   confidence="media")


# ---------------------------------------------------------------------------
# Contexto: peligro identificado hoy en cada distrito
# ---------------------------------------------------------------------------
INGEMMET_CLASSES = {"1000|1100": "caidas", "1000|1200": "caidas", "1000|1300": "deslizamientos",
                    "1000|1400": "deslizamientos", "1000|1500": "flujos", "1000|1600": "complejos",
                    "1000|1700": "reptacion"}


def ingemmet_inventory(doc: dict, territory) -> dict[str, Counter]:
    """Puntos del inventario de peligros geológicos por distrito y clase (solo los publicables)."""
    out: dict[str, Counter] = defaultdict(Counter)
    for f in doc["features"]:
        a = f["attributes"]
        if a.get("REGISTRO") not in ("Publicable", "Validado"):
            continue
        code = territory.normalize(str(a.get("UBIGEO") or "")) or territory.resolve(a.get("NM_DPTO") or "", a.get("NM_PROV") or "", a.get("NM_DIST") or "")
        if not code or len(code) != 6:
            continue
        out[code]["total"] += 1
        out[code][INGEMMET_CLASSES.get(a.get("TIP_PELIGRO") or "", "otros")] += 1
    return out


def ingemmet_critical(doc: dict, territory) -> dict[str, list]:
    """Zonas críticas por distrito: [paraje, peligro, elementos expuestos, boletín]."""
    out: dict[str, list] = defaultdict(list)
    for f in doc["features"]:
        a = f["attributes"]
        code = territory.normalize(str(a.get("CD_DIST") or "")) or territory.resolve(a.get("NM_DEPA") or "", a.get("NM_PROV") or "", a.get("NM_DIST") or "")
        if not code or len(code) != 6:
            continue
        url = (a.get("URL_BOLETIN") or "").strip()
        out[code].append([_t(a.get("PARAJE")), _t(a.get("PELIGROS_G")), _t(a.get("ELEMENTO")),
                          url if url.startswith("https://") else ""])
    return out


def _t(v) -> str:
    """Texto de una capa de ArcGIS sin saltos de línea ni espacios dobles."""
    return " ".join(str(v or "").split())


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return int(x) if x == int(x) else round(x, 2)


def ana_points(doc: dict, territory) -> dict[str, list]:
    """Puntos críticos de la ANA por distrito: [fuente y nombre, sector, peligro, nivel, población,
    viviendas, acción recomendada, costo S/]."""
    out: dict[str, list] = defaultdict(list)
    for f in doc["features"]:
        a = f["attributes"]
        code = territory.resolve(a.get("departamen") or "", a.get("provincia") or "", a.get("distrito") or "")
        if not code:
            continue
        peligro = re.sub(r"Inundació\b", "Inundación", re.sub(r"detrirtos", "detritos", a.get("peligro") or ""))
        out[code].append([_t(f"{a.get('fuente') or ''} {a.get('nombre') or ''}"), _t(a.get("sector")),
                          _t(peligro), _t(a.get("niv_peligr")), _f(a.get("poblacion")), _f(a.get("viviendas")),
                          _t(a.get("actividad")), _f(a.get("costo_act"))])
    return out


def ipress_2023(doc: dict, territory) -> dict[str, list]:
    """Establecimientos de salud afectados en las lluvias 2022-2023, por distrito: [nombre, categoría, estado]."""
    out: dict[str, list] = defaultdict(list)
    for f in doc["features"]:
        a = f["attributes"]
        if "LLUVIAS" not in (a.get("temporada") or ""):
            continue
        code = territory.normalize(str(a.get("ubigeo") or "").zfill(6)) or territory.resolve(a.get("región") or "", a.get("provincia") or "", a.get("distrito") or "")
        if not code:
            continue
        out[code].append([_t(a.get("nombre_ipr")).title(), _t(a.get("categoria")), _t(a.get("fecha_de_r")).capitalize()])
    return out
