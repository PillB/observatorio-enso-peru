"""Lectores de las fuentes de peligros que no publican RSS: sismos, tsunamis, volcanes y avisos.

Cada lector convierte la respuesta de una institución al mismo formato que una
entrada de feed (título, enlace, fecha, resumen, categorías) para que pase por
el mismo proceso que las noticias: relevancia, ubicación, agrupación, archivo
y enlaces a la fuente en vivo y a la copia archivada. Se eligió, para cada
fuente, la vía más simple que trae el dato (``tools.scrape_ladder``):

* USGS: API FDSN en GeoJSON (``parse_geojson``, también lee GDACS).
* DHN: listados HTML de boletines de sismo y tsunami (``parse_dhn``) y de
  avisos especiales de oleaje y de viento (``parse_dhn_avisos``). Los PDF
  están tras una verificación antirobots y no se piden.
* PTWC: mensaje de texto WEPA40 (``parse_ptwc_text``); el Atom se lee como feed.
* IGP CENVUL: listados HTML de boletines y alertas (``parse_cenvul``).
* SENAMHI: su canal público de Telegram (``parse_telegram``), porque la web de
  avisos no responde desde fuera del Perú y su API está en una aplicación, y la
  copia de sus avisos que el INDECI publica en su servidor ArcGIS (GEOSINPAD,
  ``parse_arcgis``): activación de quebradas por lluvias y niveles de los ríos.
* INDECI: los reportes de emergencias del COEN (``parse_coen``, sobre su RSS),
  que también difunden los avisos meteorológicos e hidrológicos del SENAMHI.

Lo que es un simulacro no se publica como alerta.
"""

from __future__ import annotations

import html
import itertools
import json
import re
import unicodedata
from datetime import datetime, timezone
from typing import Iterator, Optional

from .feedparse import LIMA, FeedError, Parsed, clean_summary, clean_text, _finish, text_of

COMPASS = {"N": "N", "NNE": "NNE", "NE": "NE", "ENE": "ENE", "E": "E", "ESE": "ESE", "SE": "SE", "SSE": "SSE",
           "S": "S", "SSW": "SSO", "SW": "SO", "WSW": "OSO", "W": "O", "WNW": "ONO", "NW": "NO", "NNW": "NNO"}
_USGS_PLACE_RE = re.compile(r"^(\d+)\s*km\s+([NSEW]{1,3})\s+of\s+(.+)$")
SIMULACRO_RE = re.compile(r"\bsimulacros?\b|\bdrill\b|\bexercise\b", re.I)
#: «Monday, November 16, 2026» del CENVUL. Con tabla propia y no con ``strptime("%A, %B %d, %Y")``: los nombres de
#: ``%A`` y ``%B`` salen del ``LC_TIME`` del proceso, y en un recolector con el sistema en castellano (o si alguna
#: biblioteca llama a ``locale.setlocale``) la variante inglesa dejaba de leerse sin ningún error.
_EN_MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                          "september", "october", "november", "december"), 1)}
_EN_DATE_RE = re.compile(r"^(?:(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday),\s*)?"
                         r"([a-z]+)\s+(\d{1,2}),\s*(\d{4})$", re.I)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _place_es(place: str) -> str:
    """«71 km S of Camaná, Peru» → «a 71 km al S de Camaná, Perú»."""
    place = (place or "").replace(", Peru", ", Perú").replace("Peru-", "Perú-")
    m = _USGS_PLACE_RE.match(place)
    if m:
        return f"a {m.group(1)} km al {COMPASS.get(m.group(2), m.group(2))} de {m.group(3)}"
    place = re.sub(r"^near the coast of ", "frente a la costa de ", place, flags=re.I)
    place = re.sub(r"^off the coast of ", "frente a la costa de ", place, flags=re.I)
    return f"en {place}" if place else ""


def parse_geojson(data: dict, base_url: str = "") -> Parsed:
    """GeoJSON de sismos de USGS (FDSN o resúmenes) y de eventos de GDACS."""
    feats = data.get("features")
    if not isinstance(feats, list):
        raise FeedError("GeoJSON sin lista de elementos")
    items, skipped = [], 0
    for f in feats:
        p = (f or {}).get("properties") or {}
        coords = ((f or {}).get("geometry") or {}).get("coordinates") or []
        if "mag" in p and "place" in p:  # USGS
            if p.get("type") not in (None, "earthquake"):
                skipped += 1  # explosiones de canteras y otros eventos que no son sismos
                continue
            mag = p.get("mag")
            when = datetime.fromtimestamp(p["time"] / 1000, timezone.utc) if isinstance(p.get("time"), (int, float)) else None
            depth = coords[2] if len(coords) > 2 else None
            local = when.astimezone(LIMA).strftime("%d/%m/%Y %H:%M") if when else ""
            facts = [f"Magnitud {mag} ({p.get('magType') or 'M'})" if mag is not None else "",
                     f"profundidad {depth:.0f} km" if isinstance(depth, (int, float)) else "",
                     f"{local} (UTC−5)" if local else "",
                     "revisado por un sismólogo" if p.get("status") == "reviewed" else "cálculo automático preliminar",
                     "USGS indica posible tsunami: consulte a la DHN" if p.get("tsunami") else "",
                     f"alerta PAGER {p['alert']}" if p.get("alert") else ""]
            items.append({
                "title": clean_text(f"Sismo de magnitud {mag} {_place_es(p.get('place', ''))}", 300),
                "link": p.get("url") or "", "published": _iso(when) if when else None,
                "summary": clean_text(". ".join(x for x in facts if x) + ".", 600),
                "categories": ["sismo"] + (["tsunami"] if p.get("tsunami") else []),
                # [lat, lon, incertidumbre en km]: el epicentro preliminar puede moverse unos 10 km
                **({"coords": [[coords[1], coords[0], 5 if p.get("status") == "reviewed" else 10]],
                    "points": [{"name": "Epicentro", "lat": round(coords[1], 3), "lon": round(coords[0], 3), "kind": "epicentro",
                                "radiusKm": 5 if p.get("status") == "reviewed" else 10,
                                **({"mag": mag} if isinstance(mag, (int, float)) else {}),
                                **({"depthKm": round(depth)} if isinstance(depth, (int, float)) else {})}]}
                   if len(coords) >= 2 and all(isinstance(c, (int, float)) for c in coords[:2]) else {}),
            })
        elif "eventtype" in p:  # GDACS
            url = (p.get("url") or {}).get("report") if isinstance(p.get("url"), dict) else p.get("url")
            when = p.get("fromdate")
            items.append({
                "title": clean_text(f"GDACS · alerta {p.get('alertlevel', '')}: {p.get('name') or p.get('description', '')}", 300),
                "link": url or "", "published": (when + "Z") if when and len(when) == 19 else when,
                "summary": clean_summary(p.get("htmldescription") or ((p.get("severitydata") or {}).get("severitytext") or "")),
                "categories": [p.get("eventtype", "")],
            })
        else:
            skipped += 1
    out = _finish(Parsed("geojson", items))
    if skipped:
        out.repairs.append(f"{skipped} elementos sin el formato esperado")
    return out


# --- DHN: boletines de sismo y tsunami ----------------------------------------------

_DHN_BLOCK_RE = re.compile(
    r'class="accordion-title">\s*(?P<title>BOLET[ÍI]N[^<]*?N[°º]\s*(?P<num>[\w-]+))\s*</div>'
    r'(?P<body>.*?)(?=class="accordion-title"|</section>)', re.S | re.I)
_DHN_WHEN_RE = re.compile(r"El d[ií]a (\d{1,2}) (\w+) (\d{4}), a (\d{1,2}:\d{2}(?::\d{2})?) hora local", re.I)
_DHN_EVENT_RE = re.compile(r"localizado\s+(?P<where>.+?),\s*con una magnitud de\s*(?P<mag>\d+(?:[.,]\d+)?)\s*(?P<type>\w+)?"
                           r"(?:,\s*a una profundidad de\s*(?P<depth>\d+(?:[.,]\d+)?)\s*km)?", re.I | re.S)
_DHN_STATUS_RE = re.compile(r"se comunica que este evento\s+(?P<status>.+?)(?:\.\s|\.$|$)", re.I | re.S)
_ES_MONTHS = {m: i for i, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                          "septiembre", "octubre", "noviembre", "diciembre"], 1)} | {"setiembre": 9}


def parse_dhn(body: bytes, base_url: str = "https://www.dhn.mil.pe/portal/boletin-sismo-tsunami") -> Parsed:
    text = text_of(body)
    if "boletin-sismo-tsunami" not in text and "BOLETÍN DE SISMO" not in text.upper():
        raise FeedError("no es el listado de boletines de la DHN")
    items, drills = [], 0
    for m in _DHN_BLOCK_RE.finditer(text):
        body_txt = clean_text(m.group("body"), 3000)
        if SIMULACRO_RE.search(body_txt):
            drills += 1
            continue
        ev, st, wh = _DHN_EVENT_RE.search(body_txt), _DHN_STATUS_RE.search(body_txt), _DHN_WHEN_RE.search(body_txt)
        published = None
        if wh and wh.group(2).lower() in _ES_MONTHS:
            hms = wh.group(4) if wh.group(4).count(":") == 2 else wh.group(4) + ":00"
            published = _iso(datetime.strptime(f"{wh.group(3)}-{_ES_MONTHS[wh.group(2).lower()]:02d}-{int(wh.group(1)):02d} {hms}",
                                               "%Y-%m-%d %H:%M:%S").replace(tzinfo=LIMA))
        status = clean_text(st.group("status"), 160).rstrip(".") if st else ""
        if ev:
            where = re.sub(r"(\d)\s*Km\b", r"\1 km", ev.group("where").strip(), flags=re.I)
            title = f"Sismo de magnitud {ev.group('mag').replace(',', '.')} {ev.group('type') or ''}".strip() + f" a {where}"
        else:
            title = clean_text(m.group("title"), 200)
        if status:
            title += f": {status[:1].upper()}{status[1:].lower()}"
        items.append({"title": clean_text(title, 300), "link": f"{base_url.split('#')[0]}#{m.group('num')}",
                      "published": published, "summary": clean_text(body_txt, 600),
                      "categories": ["sismo", "tsunami", clean_text(m.group("title"), 80)]})
    if not items and not drills:
        raise FeedError("el listado de la DHN no tiene boletines con el formato esperado")
    out = _finish(Parsed("dhn-html", items))
    if drills:
        out.repairs.append(f"{drills} boletines de simulacro omitidos")
    return out


# --- DHN: avisos especiales de oleaje y de viento ------------------------------------

#: Títulos de 2026 («AVISO ESPECIAL DE OLEAJE NRO. 42-26 (Válido del…)») y anteriores
#: («AVISO ESPECIAL Nº 118 [Oleaje]», «… Nro. 7 (ACTUALIZACIÓN 2/3/2021)»): el tipo va entre corchetes.
_DHN_AV_TITLE_RE = re.compile(r"AVISO ESPECIAL(?: DE (?P<kind>[A-ZÁÉÍÓÚÑ]+))?\s+N(?:RO\.?|[°º]\.?)\s*(?P<num>\d+(?:\s*-\s*\d+)?)"
                              r"(?:\s*\((?P<valid>V[ÁA]LIDO[^)]*)\))?(?:.*?\[(?P<tag>[^\]]+)\])?", re.I)
_DHN_AV_ID_RE = re.compile(r"pdf-aviso-especial/(\d+)")
_DHN_AV_VALID_RE = re.compile(r"del (\d{1,2})(?: de (\w+))?(?: del? (\d{4}))? al (\d{1,2}) de (\w+)(?: del?)? (\d{4})", re.I)
_DHN_AV_ISSUED_RE = re.compile(r"Callao,?\s*(\d{1,2}) de (\w+)(?: del?)? (\d{4})", re.I)
_DHN_AV_LITORAL_RE = re.compile(r"Litoral (Norte|Centro|Sur)\b[^:]*:(?P<txt>[^\n]*)", re.I)
_DHN_AV_WIND_RE = re.compile(r"(?P<what>(?:brisa|viento)s? [a-záéíóú]+(?: [a-záéíóú]+)?) \(hasta (?P<kt>\d+) nudos\)"
                             r"(?:[^.;]*?entre las localidades de (?P<a>[^;,.]+?) (?:a|y) (?P<b>[^;,.]+?)(?=[;,.]))?", re.I)
#: Fórmula con que empieza cada aviso; se quita para que el resumen vaya al grano.
_DHN_AV_LEAD_RE = re.compile(r"^La Marina de Guerra del Per[uú],? a trav[eé]s de la Direcci[oó]n de Hidrograf[ií]a y Navegaci[oó]n,?\s*"
                             r"(?:informa|pone en conocimiento|comunica)\s*(?:a la opini[oó]n p[uú]blica)?,?\s*(?:que,?\s*)?", re.I)
_SWELL = ["ligero", "moderado", "fuerte", "muy fuerte"]
_SWELL_RE = re.compile(r"\b(muy fuerte|fuerte|moderado|ligero)\b", re.I)
#: Departamentos de cada tramo del litoral en los avisos de oleaje de la DHN
#: (norte: Tumbes a Salaverry; centro: hasta San Juan de Marcona; sur: hasta Tacna).
DHN_LITORAL = {"norte": ("Tumbes", "Piura", "Lambayeque", "La Libertad"),
               "centro": ("La Libertad", "Áncash", "Lima", "Callao", "Ica"),
               "sur": ("Ica", "Arequipa", "Moquegua", "Tacna")}


def _es_date(day: str, month: str, year: str) -> Optional[datetime]:
    mo = _ES_MONTHS.get((month or "").lower())
    return datetime(int(year), mo, int(day), 12, tzinfo=LIMA) if mo else None


def parse_dhn_avisos(body: bytes, base_url: str = "https://www.dhn.mil.pe/portal/avisos-especiales") -> Parsed:
    """Avisos especiales de la DHN: oleaje anómalo y vientos en el litoral y el mar peruano."""
    text = text_of(body)
    if "avisos-especiales" not in text or "AVISO ESPECIAL" not in text.upper():
        raise FeedError("no es el listado de avisos especiales de la DHN")
    items = []
    for chunk in text.split('class="position-relative"')[1:]:
        tm = re.search(r'class="accordion-title">(.*?)</div>', chunk, re.S)
        head = _DHN_AV_TITLE_RE.search(clean_text(tm.group(1), 300)) if tm else None
        if not head:
            continue
        num = re.sub(r"\s+", "", head.group("num"))
        kind = re.sub(r"s$", "", (head.group("kind") or head.group("tag") or "").strip().lower())  # «vientos»
        if not kind:
            continue
        content = chunk.split('class="accordion-content">', 1)[-1]
        lines = [clean_text(x, 1000) for x in re.split(r"<br\s*/?>|</h4>", content)]
        lines = [x for x in lines if x]
        body_txt = " ".join(lines)
        valid = clean_text(head.group("valid") or "", 120)
        vm, im = _DHN_AV_VALID_RE.search(valid), _DHN_AV_ISSUED_RE.search(body_txt)
        when = _es_date(*im.groups()) if im else None
        if not when and vm:
            when = _es_date(vm.group(1), vm.group(2) or vm.group(5), vm.group(3) or vm.group(6))
        period = f"válido {valid.split(' ', 1)[1]}" if valid.lower().startswith("válido ") else valid.lower()
        geo, what = [], ""
        if kind == "oleaje":
            level: dict[str, int] = {}
            for lm in _DHN_AV_LITORAL_RE.finditer("\n".join(lines)):
                found = [_SWELL.index(x.lower()) for x in _SWELL_RE.findall(lm.group("txt"))]
                if found:
                    level[lm.group(1).lower()] = max(found)
            if level:
                top = max(level.values())
                where = [k for k in ("norte", "centro", "sur") if level.get(k) == top]
                what = f"oleaje {_SWELL[top]} en el litoral {_join(where)}"
                geo = [f"departamento de {d}" for d in dict.fromkeys(x for k in level for x in DHN_LITORAL[k])]
        else:
            wm = _DHN_AV_WIND_RE.search(body_txt)
            if wm:
                what = f"{wm.group('what').lower()} (hasta {wm.group('kt')} nudos)"
                if wm.group("a"):
                    what += f" entre {wm.group('a').strip()} y {wm.group('b').strip()}"
        title = f"DHN · aviso especial de {kind} N° {num}" + (f": {what}" if what else "") + (f" ({period})" if period else "")
        summary = _DHN_AV_LEAD_RE.sub("", " ".join(x for x in lines if not re.match(r"^(?:[a-d]\.|Atentamente|DIRECCI|dihidronav)", x)))
        summary = summary[:1].upper() + summary[1:]
        aid = _DHN_AV_ID_RE.search(chunk)
        if when is None:
            # Todos los avisos dicen «Callao, 2 de julio de 2026» o su vigencia: sin fecha, la página cambió (otro idioma
            # u otro formato) y el aviso saldría sin fecha y sin poder ordenarse (``tools/drift_sim.py``).
            raise FeedError(f"el aviso especial N° {num} no tiene una fecha que se pueda leer "
                            f"(«{(im.group(0) if im else valid or body_txt[:60])[:80]}»)")
        item = {"title": clean_text(title, 300), "link": f"{base_url.split('#')[0]}#{aid.group(1) if aid else num}",
                "published": _iso(when), "summary": clean_text(summary, 600),
                "categories": [kind, f"aviso especial {num}"]}
        if geo:
            item["geo"] = [", ".join(geo)]
        items.append(item)
    if not items:
        raise FeedError("el listado de la DHN no tiene avisos especiales con el formato esperado")
    return _finish(Parsed("dhn-avisos-html", items))


# --- PTWC: mensaje de texto (WEPA40) ------------------------------------------------

_PTWC_ISSUED_RE = re.compile(r"^[ \t]*(\d{4}) UTC \w{3} (\w{3}) (\d{1,2}) (\d{4})[ \t]*$", re.M)
_PTWC_PARAM_RE = re.compile(r"\*\s+(MAGNITUDE|ORIGIN TIME|COORDINATES|DEPTH|LOCATION)\s+(.+)")
_PTWC_THREAT_RE = re.compile(r"TSUNAMI THREAT FORECAST.*?\n-+\n(?P<txt>.*?)(?:\n[A-Z][A-Z .]+\n-+\n|\Z)", re.S)
#: Nota de un mensaje del PTWC que es un simulacro: sin entradas a propósito (``news._read_feed`` no lo da por vacío).
PTWC_EXERCISE = "el último mensaje del PTWC es un simulacro: no hay mensajes vigentes"
_MON = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


_PTWC_TEST_RE = re.compile(r"\bTHIS IS A TEST\b|FOR TEST PURPOSES ONLY|\bDUMMY MESSAGE\b|^\s*TEST\.\.\.", re.M)


def parse_ptwc_text(body: bytes, base_url: str = "") -> Parsed:
    """Último mensaje del Centro de Alerta de Tsunamis del Pacífico (el filtro de relevancia
    deja solo los que nombran al Perú, como con su feed Atom)."""
    # Sin espacios al final de las líneas: «---- \n» cortaba la sección de la amenaza y el resumen la perdía.
    text = "\n".join(l.rstrip() for l in text_of(body).replace("\r", "").split("\n"))
    if "TSUNAMI" not in text or "PACIFIC TSUNAMI WARNING CENTER" not in text:
        raise FeedError("no es un mensaje del PTWC")
    if _PTWC_TEST_RE.search("\n".join(text.splitlines()[:15])):
        # Simulacro (PACWAVE26, noviembre de 2026: «TEST... DUMMY MESSAGE FOR PACWAVE26 EXERCISE... THIS IS A TEST»):
        # no es un aviso. Sin entradas, como una capa de avisos vacía: el último mensaje puede seguir siendo el del
        # simulacro semanas (no hay otro mensaje hasta el próximo sismo), y eso no es un feed vaciado.
        return Parsed("ptwc-text", [], [PTWC_EXERCISE])
    params = {k: v.strip() for k, v in _PTWC_PARAM_RE.findall(text)}
    num = re.search(r"TSUNAMI MESSAGE NUMBER\s+(\d+)", text)
    head = re.search(r"\.\.\.(PTWC [^.]+?)\.\.\.", text)
    iss = _PTWC_ISSUED_RE.search(text)
    published = None
    if iss and iss.group(2) in _MON:
        published = _iso(datetime(int(iss.group(4)), _MON[iss.group(2)], int(iss.group(3)),
                                  int(iss.group(1)[:2]), int(iss.group(1)[2:]), tzinfo=timezone.utc))
    threat = _PTWC_THREAT_RE.search(text)
    threat_txt = re.sub(r"\s+", " ", threat.group("txt")).strip(" *") if threat else ""
    title = (f"PTWC · sismo de magnitud {params.get('MAGNITUDE', '?')} en {params.get('LOCATION', '?').title()}: "
             f"{(head.group(1) if head else 'mensaje de tsunami').lower()}")
    peru = " Menciona al Perú." if re.search(r"\bPERU\b", text) else ""
    items = [{"title": clean_text(title, 300), "link": f"{base_url}#{(published or '')[:16]}-{num.group(1) if num else ''}",
              "published": published,
              "summary": clean_text(f"Mensaje N° {num.group(1) if num else '?'} del PTWC, en inglés y dirigido a las "
                                    f"autoridades nacionales.{peru} {threat_txt}", 600),
              "categories": ["tsunami"]}]
    return Parsed("ptwc-text", items)


# --- IGP CENVUL: boletines y alertas vulcanológicas --------------------------------

_CARD_FIELD_RE = re.compile(r'<span[^>]*>\s*(?P<k>[^<:]+?)\s*:\s*</span>\s*(?P<v>[^<]+)<', re.S)
_ALERT_COLOR_RE = re.compile(r'<span[^>]*>\s*Alerta\s*:\s*</span>.*?<span>\s*(Verde|Amarillo|Naranja|Rojo)\s*</span>', re.S)


def _cards(text: str) -> list[str]:
    """Las tarjetas de la vista de teléfono (la tabla de escritorio repite los mismos datos)."""
    start = text.find('class="block sm:hidden"')
    if start < 0:
        return []
    seg = text[start:text.find('class="hidden sm:block"', start) if 'class="hidden sm:block"' in text[start:] else None]
    return re.split(r"<!--\[--> # \d+<!--\]-->", seg)[1:]


#: El CENVUL (Nuxt) escribe las fechas con el idioma de la instancia que atiende la petición, no con el que se le pide
#: (``Accept-Language`` no cambia nada): la misma página llega, al azar, como «Monday, November 16, 2026 · 11:54:00 AM»
#: o como «lunes, 16 de noviembre de 2026 · 11:54:00 a. m.» (copias de data-archive del 21-10 al 21-11-2026, dos
#: variantes cada día). Hay que leer las dos: con solo la inglesa, la mitad de las lecturas salía sin fechas.
_ES_MONTHS = {m: i for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                          "septiembre", "octubre", "noviembre", "diciembre"), 1)} | {"setiembre": 9}
_ES_DATE_RE = re.compile(r"^(?:[a-záéíóúñ]+,\s*)?(\d{1,2})\s+de\s+([a-z]+)\s+(?:de|del)\s+(\d{4})$", re.I)
_HM_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(?:(a|p)\.?\s*m\.?)?$", re.I)


def _card_date(s: str, hm: str = "") -> Optional[str]:
    """Fecha (y hora) de una tarjeta del CENVUL, en inglés o en castellano; ``None`` si no se reconoce."""
    s = re.sub(r"\s+", " ", (s or "").replace("\u00a0", " ").replace("\u202f", " ")).strip()
    if not s:
        return None
    en = _EN_DATE_RE.match(s)
    es = None if en else _ES_DATE_RE.match(s)
    if en:
        month, day, year = _EN_MONTHS.get(en.group(1).lower()), en.group(2), en.group(3)
    elif es:
        month, day, year = _ES_MONTHS.get(es.group(2).lower()), es.group(1), es.group(3)
    else:
        return None
    if not month:
        return None
    try:
        d = datetime(int(year), month, int(day))
    except ValueError:
        return None
    t = _HM_RE.match(re.sub(r"\s+", " ", (hm or "").replace("\u00a0", " ").replace("\u202f", " ")).strip())
    if t:
        h, mi, sec = int(t.group(1)), int(t.group(2)), int(t.group(3) or 0)
        if t.group(4):  # 12 h: «AM»/«PM» o «a. m.»/«p. m.»
            h = h % 12 + (12 if t.group(4).lower() == "p" else 0)
        if h < 24 and mi < 60 and sec < 60:
            return _iso(d.replace(hour=h, minute=mi, second=sec, tzinfo=LIMA))
    return _iso(d.replace(hour=12, tzinfo=LIMA))  # sin hora: mediodía de Lima, para que la fecha no cambie al pasar a UTC


#: Dónde está cada volcán que vigila el IGP, para ubicar sus boletines y alertas.
VOLCANOES = {
    "sabancaya": "la provincia de Caylloma (Arequipa)", "ampato": "la provincia de Caylloma (Arequipa)",
    "misti": "la provincia de Arequipa (Arequipa)", "chachani": "la provincia de Arequipa (Arequipa)",
    # El Coropuna y el Sara Sara están en el límite de dos provincias (IGP); el Auquihuato, en Paucar del Sara Sara.
    "coropuna": "las provincias de Castilla y Condesuyos (Arequipa)",
    "ubinas": "la provincia de General Sánchez Cerro (Moquegua)",
    "huaynaputina": "la provincia de General Sánchez Cerro (Moquegua)", "ticsani": "la provincia de Mariscal Nieto (Moquegua)",
    "tutupaca": "la provincia de Candarave (Tacna)", "yucamane": "la provincia de Candarave (Tacna)",
    "casiri": "el departamento de Tacna", "purupuruni": "el departamento de Tacna",
    "sara sara": "las provincias de Parinacochas y Paucar del Sara Sara (Ayacucho)",
    "auquihuato": "la provincia de Paucar del Sara Sara (Ayacucho)",
    "quimsachata": "la provincia de Canchis (Cusco)",
}


#: Cumbre de cada volcán (lat, lon) según el catálogo Volcanoes of the World del Smithsonian (GVP, 2026), con su
#: número; el Ampato no tiene entrada propia y comparte la del Sabancaya (su complejo, a unos 6 km).
VOLCANO_POINTS = {
    "sabancaya": (-15.787, -71.857, 354006), "ampato": (-15.787, -71.857, 354006),
    "misti": (-16.2991, -71.4056, 354010), "chachani": (-16.1792, -71.5292, 354007),
    "coropuna": (-15.52, -72.65, 354003), "ubinas": (-16.345, -70.8972, 354020),
    "huaynaputina": (-16.6144, -70.8542, 354030), "ticsani": (-16.7586, -70.5981, 354031),
    "tutupaca": (-17.026, -70.372, 354040), "yucamane": (-17.184, -70.196, 354050),
    "casiri": (-17.4852, -69.7886, 354060), "purupuruni": (-17.2587, -69.8216, 354804),
    "sara sara": (-15.3299, -73.4456, 354002), "auquihuato": (-15.0726, -73.1914, 354001),
    "quimsachata": (-14.131, -71.363, 354000),
}


def _volcano_key(name: str) -> str:
    key = re.sub(r"\s+", " ", unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()).strip()
    return key.removeprefix("el ").removesuffix(" volcano")


def _volcano_place(name: str) -> str:
    where = VOLCANOES.get(_volcano_key(name))
    return f" El volcán {name} está en {where}." if where else ""


def _volcano_points(name: str) -> dict:
    pt = VOLCANO_POINTS.get(_volcano_key(name))
    if not pt:
        return {}
    return {"points": [{"name": f"Volcán {name}", "lat": pt[0], "lon": pt[1], "kind": "volcan",
                        "source": f"https://volcano.si.edu/volcano.cfm?vn={pt[2]}"}]}


def parse_cenvul(body: bytes, base_url: str) -> Parsed:
    text = text_of(body)
    if "CENVUL" not in text:
        raise FeedError("no es una página del CENVUL")
    alerts = "alertas-vulcanologicas" in base_url
    items, green, cards = [], 0, _cards(text)
    dated = undated = 0  # tarjetas con «Fecha de publicación», leída o no
    for card in cards:
        f = {k.strip().lower(): html.unescape(v).strip() for k, v in _CARD_FIELD_RE.findall(card)}
        volcano = f.get("volcán") or f.get("volcan")
        if not volcano:
            continue
        raw_date = f.get("fecha de publicación", "")
        when = _card_date(raw_date, f.get("hora de publicación", "") if alerts else "")
        if raw_date:
            dated, undated = dated + bool(when), undated + (not when)
        if alerts:
            kind = f.get("tipo de alerta", "")
            what = {"cenizas": "dispersión de cenizas", "lahares": "descenso de lahares"}.get(kind.lower(), kind.lower())
            items.append({"title": clean_text(f"Volcán {volcano}: alerta por {what} (IGP)", 300),
                          "link": f"{base_url}#{re.sub(r'[^a-z0-9]+', '-', f'{volcano} {kind} {when or ''}'.lower()).strip('-')}",
                          "published": when,
                          "summary": f"Alerta vulcanológica del CENVUL por {what} del volcán {volcano}." + _volcano_place(volcano),
                          "categories": ["volcan", kind], **_volcano_points(volcano)})
        else:
            code = f.get("código", "")
            color = _ALERT_COLOR_RE.search(card)
            level = color.group(1) if color else ""
            if level == "Verde":
                green += 1  # actividad normal: no es una alerta
                continue
            items.append({"title": clean_text(f"Volcán {volcano}: boletín {code}" + (f", alerta {level.lower()}" if level else ""), 300),
                          "link": f"{base_url}#{re.sub(r'[^A-Za-z0-9]+', '-', code).strip('-')}",
                          "published": when,
                          "summary": f"Boletín vulcanológico del CENVUL (IGP) sobre el volcán {volcano}"
                                     + (f". Nivel de alerta: {level.lower()}." if level else ".") + _volcano_place(volcano),
                          "categories": ["volcan", level], **_volcano_points(volcano)})
    if not cards:
        raise FeedError("la página del CENVUL no tiene tarjetas con el formato esperado")
    if undated and not dated:
        # Otra forma de escribir la fecha: sin fechas, las alertas se fundían en una por volcán y el feed parecía
        # «sin entradas con fecha» (un aviso informativo que nadie lee). Es un cambio de formato: se dice como tal.
        sample = next(iter(re.findall(r"Fecha de publicaci[oó]n\s*:\s*</span>\s*([^<]{1,60})", text)), "")
        raise FeedError(f"el CENVUL escribe las fechas de otra forma ({html.unescape(sample).strip()!r})")
    out = _finish(Parsed("cenvul-html", items))
    if undated:
        out.repairs.append(f"{undated} tarjetas con una fecha que no se pudo leer")
    if green:
        out.repairs.append(f"{green} boletines de volcanes en alerta verde omitidos")
    return out


# --- Telegram: vista pública de un canal (t.me/s/<canal>) -------------------------

_TG_MSG_RE = re.compile(r'data-post="(?P<post>[\w]+/\d+)"(?P<body>.*?)(?=data-post="|\Z)', re.S)
_TG_TEXT_RE = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(?P<t>.*?)</div>', re.S)
_TG_TIME_RE = re.compile(r'<time datetime="([^"]+)"')
_TG_LINK_RE = re.compile(r'href="(https?://(?!t\.me/)[^"]+)"')
_HASHTAG_RE = re.compile(r"#[\wÁÉÍÓÚÑáéíóúñ]+")


#: Etiquetas con que el SENAMHI marca sus mensajes: avisos, lo que ocurre ahora y notas de prensa.
TG_KINDS = {"aviso": "Aviso del SENAMHI", "ahora": "SENAMHI, en este momento"}


def _tg_more(url: str) -> str:
    """El enlace del mensaje, dicho en palabras: una URL larga no cabe en la pantalla de un teléfono
    (el mensaje en Telegram, enlazado, la tiene)."""
    m = re.search(r"senamhi\.gob\.pe/.*?avisos-(meteorologicos|hidrologicos|incendios-forestales)/(\d+)", url)
    if m:
        return f"Detalle en el sitio del SENAMHI (aviso {m.group(1).replace('-', ' ').replace('logicos', 'lógico')} {m.group(2)})."
    host = re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*$", r"\1", url))
    return f"Más información en {host}."


def parse_telegram(body: bytes, base_url: str = "") -> Parsed:
    """Vista pública del canal. Los avisos («#Aviso») y los reportes en curso («#Ahora») llevan
    un titular que los distingue (``TG_KINDS``); las notas de prensa, su propio titular."""
    text = text_of(body)
    if "tgme_widget_message" not in text:
        raise FeedError("no es la vista pública de un canal de Telegram")
    items = []
    for m in _TG_MSG_RE.finditer(text):
        tm = _TG_TEXT_RE.search(m.group("body"))
        if not tm:
            continue  # foto o video sin texto
        raw = re.sub(r"<i class=\"emoji\"[^>]*>.*?</i>", " ", tm.group("t"), flags=re.S)
        raw = re.sub(r"<br\s*/?>", "\n", raw)
        lines = [re.sub(r"https?://\S+", "", _HASHTAG_RE.sub(" ", clean_text(x, 2000))).strip(" |·-–—•\t")
                 for x in raw.split("\n")]
        lines = [x for x in lines if x]
        tags = [t[1:] for t in _HASHTAG_RE.findall(clean_text(raw, 4000))]
        if not lines:
            continue
        body_txt = re.sub(r"\s+", " ", " ".join(lines)).strip()
        first = re.split(r"(?<=[.!?])\s", lines[0], maxsplit=1)[0]
        kind = next((TG_KINDS[t.lower()] for t in tags if t.lower() in TG_KINDS), "")
        title = f"{kind}: {first[:1].lower() + first[1:]}" if kind else first
        links = [u for u in _TG_LINK_RE.findall(tm.group("t")) if "telegram.org" not in u]
        when = _TG_TIME_RE.search(m.group("body"))
        rest = body_txt[len(first):].strip() if body_txt.startswith(first) else body_txt
        rest = " ".join(dict.fromkeys(re.split(r"(?<=[.!?])\s+", rest)))  # el canal a veces repite el consejo
        if rest and not rest.endswith((".", "!", "?")):
            rest += "."
        items.append({"title": clean_text(title, 300), "link": f"https://t.me/{m.group('post')}",
                      "published": _iso(datetime.fromisoformat(when.group(1))) if when else None,
                      "summary": clean_text((rest or body_txt) + (f" {_tg_more(links[0])}" if links else ""), 600),
                      "categories": tags[:12]})
    if not items:
        raise FeedError("el canal de Telegram no tiene mensajes con texto")
    p = _finish(Parsed("telegram-html", items))
    p.items.sort(key=lambda i: i["published"] or "", reverse=True)
    return p


# --- ArcGIS (GEOSINPAD del INDECI): copia de los avisos del SENAMHI -----------------
# Las capas guardan solo los avisos vigentes y se sobrescriben cada día. Cada aviso
# enlaza a la consulta en vivo de esa capa en formato HTML (legible en el navegador).

_ORA_MONTHS = {"ENE": 1, "JAN": 1, "FEB": 2, "MAR": 3, "ABR": 4, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AGO": 8,
               "AUG": 8, "SET": 9, "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12, "DEC": 12}


def _day_ms(ms) -> Optional[datetime]:
    """Las fechas de estas capas son días a las 00:00 UTC que representan el día local."""
    if not isinstance(ms, (int, float)):
        return None
    d = datetime.fromtimestamp(ms / 1000, timezone.utc)
    return datetime(d.year, d.month, d.day, 12, tzinfo=LIMA)  # mediodía: la fecha no cambia al pasar a UTC


def _ora_day(s) -> Optional[datetime]:
    """«16-OCT-26» (Oracle, con meses en castellano o en inglés)."""
    m = re.match(r"^\s*(\d{1,2})-([A-Za-z]{3})-(\d{2,4})", str(s or ""))
    if not m or m.group(2).upper() not in _ORA_MONTHS:
        return None
    y = int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0)
    try:
        return datetime(y, _ORA_MONTHS[m.group(2).upper()], int(m.group(1)), 12, tzinfo=LIMA)
    except ValueError:
        return None


def _dep_name(raw: str) -> str:
    from .geo import department_names

    fold = lambda x: unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode().lower().strip()  # noqa: E731
    names = {fold(n): n for n in department_names().values()}
    raw = re.sub(r"^(?:DEPA|PROV|DIST)\.\s*", "", str(raw or "")).strip()
    return names.get(fold(raw), raw.title())


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " y " + names[-1]


def _river_title(t: str) -> str:
    """«SITUACIÓN ACTUAL DEL NIVEL DEL RÍO AMAZONAS - ESTACIÓN PUERTO ALEGRIA» →
    «situación actual del nivel del río Amazonas, estación Puerto Alegria»."""
    m = re.match(r"^(?P<a>.*?\bR[ÍI]OS?)\s+(?P<rio>.+?)\s*[-–]\s*ESTACI[ÓO]N\s+(?P<est>.+)$", re.sub(r"\s+", " ", t.strip()), re.I)
    if not m:
        return _cap(t).lower()
    return f"{m.group('a').lower()} {_proper(m.group('rio'))}, estación {_proper(m.group('est'))}"


def _layer_link(base_url: str, where: str) -> str:
    from urllib.parse import quote

    layer = base_url.split("/query")[0].rstrip("/")
    return f"{layer}/query?where={quote(where)}&outFields=*&returnGeometry=false&f=html"


#: Recuadro del Perú (lat0, lon0, lat1, lon1) para descartar coordenadas vacías o fuera del país.
_PERU_BOX = (-18.6, -81.5, 0.2, -68.4)


def _in_peru_box(lat, lon) -> bool:
    return isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and \
        _PERU_BOX[0] <= lat <= _PERU_BOX[2] and _PERU_BOX[1] <= lon <= _PERU_BOX[3]


def _station_point(r: dict) -> Optional[dict]:
    """La estación hidrológica de una fila de la capa del SENAMHI: su punto, el río y la cuenca (la que trae la capa,
    que coincide con la unidad hidrográfica de la ANA en ese punto; ver ``tests/test_lugares.py``)."""
    try:
        lat, lon = float(r.get("LATITUD")), float(r.get("LONGITUD"))
    except (TypeError, ValueError):
        return None
    if not _in_peru_box(lat, lon) or not r.get("NOM_ESTACI"):
        return None
    p = {"name": f"Estación {_proper(str(r['NOM_ESTACI']))}", "lat": round(lat, 4), "lon": round(lon, 4), "kind": "estacion"}
    m = re.search(r"\bR[ÍI]O\s+(.+?)\s*[-–]\s*ESTACI", str(r.get("TITULO") or ""), re.I)
    if m:
        p["river"] = f"río {_proper(m.group(1))}"
    if r.get("COD_CUENCA"):
        p["basin"] = {"code": str(r["COD_CUENCA"]).strip(), "name": str(r.get("NOM_CUENCA") or "").strip()}
    return p


def _range_es(r: str) -> str:
    """«> 97» → «por encima de 97»; «38 - 97» → «entre 38 y 97»."""
    m = re.match(r"^\s*([<>]=?)\s*([\d.,]+)\s*$", r)
    if m:
        return f"{'por encima' if m.group(1).startswith('>') else 'por debajo'} de {m.group(2)}"
    m = re.match(r"^\s*([\d.,]+)\s*(?:-|–|a)\s*([\d.,]+)\s*$", r)
    return f"entre {m.group(1)} y {m.group(2)}" if m else f"en {r}"


#: Recuadro holgado del Perú (lat0, lon0, lat1, lon1) para la geometría de las capas: los polígonos de un aviso pueden
#: asomar al mar o a un país vecino, no estar en otro continente ni en metros.
_PERU_ENVELOPE = (-21.0, -84.0, 2.5, -66.0)


def _xy(c) -> Iterator[tuple[float, float]]:
    """Pares (x, y) de una geometría GeoJSON (``coordinates`` anidadas) o de Esri (``rings``, ``paths``, ``x``/``y``)."""
    if isinstance(c, dict):
        if isinstance(c.get("x"), (int, float)) and isinstance(c.get("y"), (int, float)):
            yield float(c["x"]), float(c["y"])
        for k in ("coordinates", "rings", "paths", "points"):
            if k in c:
                yield from _xy(c[k])
    elif isinstance(c, list):
        if len(c) >= 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in c[:2]):
            yield float(c[0]), float(c[1])
        else:
            for v in c:
                yield from _xy(v)


def _arcgis_off_peru(feats: list, rows: list[dict]) -> str:
    """Por qué la geometría de la capa no está en el Perú (otra proyección: la consulta pide ``outSR=4326`` y sin él
    ArcGIS responde en metros; latitud y longitud intercambiadas), o "". Mira la geometría y, en las estaciones, las
    columnas LATITUD/LONGITUD: si menos de la mitad de los puntos cae en el Perú, la capa no se lee (antes los avisos
    salían sin lugar ni polígono: ``tools/drift_sim.py``, mutaciones ``json-scale-x10`` y ``arcgis-web-mercator``)."""
    pts = [(lat, lon) for f in feats for lon, lat in itertools.islice(_xy((f or {}).get("geometry") or {}), 200)]
    for r in rows:
        try:
            pts.append((float(r["LATITUD"]), float(r["LONGITUD"])))
        except (KeyError, TypeError, ValueError):
            pass
    if not pts:
        return ""
    inside = sum(1 for lat, lon in pts if _PERU_ENVELOPE[0] <= lat <= _PERU_ENVELOPE[2]
                 and _PERU_ENVELOPE[1] <= lon <= _PERU_ENVELOPE[3])
    if inside * 2 >= len(pts):
        return ""
    lat, lon = next((p for p in pts if not (_PERU_ENVELOPE[0] <= p[0] <= _PERU_ENVELOPE[2]
                                           and _PERU_ENVELOPE[1] <= p[1] <= _PERU_ENVELOPE[3])))
    return (f"la geometría de la capa no está en el Perú ({len(pts) - inside} de {len(pts)} puntos fuera; p. ej. "
            f"lat {lat:g}, lon {lon:g}): ¿otra proyección (falta outSR=4326) o latitud y longitud intercambiadas?")


def parse_arcgis(body: bytes, base_url: str) -> Parsed:
    try:
        data = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise FeedError(f"JSON inválido: {exc}") from exc
    if isinstance(data, dict) and data.get("error"):
        err = data["error"]
        raise FeedError(f"ArcGIS respondió con un error: {err.get('code', '')} {err.get('message', '')}".strip())
    feats = (data or {}).get("features") if isinstance(data, dict) else None
    if not isinstance(feats, list):
        raise FeedError("respuesta de ArcGIS sin lista de elementos")
    rows = [(f or {}).get("attributes") or (f or {}).get("properties") or {} for f in feats]
    if not rows:
        return Parsed("arcgis-json", [], ["la capa no tiene avisos vigentes"])
    off = _arcgis_off_peru(feats, rows)
    if off:
        raise FeedError(off)
    keys = set().union(*rows)
    items: list[dict] = []
    if "NUM_AVISO" in keys:  # avisos hidrológicos: una estación por fila
        kind = "hidrologico"
        by_num: dict = {}
        for r in rows:
            by_num.setdefault(r.get("NUM_AVISO"), []).append(r)
        for num, rs in by_num.items():
            r0 = rs[0]
            when = _ora_day(r0.get("FECHA_HORA")) or _day_ms(r0.get("FECHA"))
            color = str(r0.get("COLOR_TEXT") or "").strip().lower()
            where = [f"distrito de {_proper(str(r.get('NOMBDIST') or ''))}, provincia de {_proper(str(r.get('NOMBPROV') or ''))}, "
                     f"departamento de {_dep_name(r.get('NOMBDEP'))}" for r in rs if r.get("NOMBDEP")]
            places = sorted({f"{_proper(str(r.get('NOM_ESTACI') or ''))} ({w})" for r, w in zip([r for r in rs if r.get("NOMBDEP")], where)})
            facts = [f"Estación {'; '.join(places)}." if places else "",
                     clean_text(str(r0.get("PELIGRO_NI") or ""), 300), clean_text(str(r0.get("RECOMENDAC") or ""), 300)]
            points = [p for p in (_station_point(r) for r in rs) if p]
            items.append({"title": clean_text(f"SENAMHI · aviso hidrológico N° {num}"
                                              + (f" (nivel {color})" if color else "")
                                              + f": {_river_title(str(r0.get('TITULO') or 'situación de los ríos'))}", 300),
                          "link": _layer_link(base_url, f"NUM_AVISO={int(num)}" if str(num).isdigit() else f"NUM_AVISO='{num}'"),
                          "published": _iso(when) if when else None,
                          "summary": clean_text(" ".join(x for x in facts if x), 600),
                          "categories": [f"aviso hidrológico {num}"], "geo": list(dict.fromkeys(where)),
                          **({"points": points} if points else {})})
    elif "NIVEL" in keys and "NOMBDEP" in keys:  # activación de quebradas: cuántas por distrito (o por departamento)
        kind = "quebradas"
        # Cada polígono de la capa es una quebrada (unas decenas de hectáreas), no un distrito: la consulta las cuenta
        # por nivel, fecha y distrito. Una respuesta sin NOMBDIST (la consulta vieja) solo dice cuántas por departamento.
        from .geo import gazetteer

        gz = gazetteer()
        groups: dict = {}
        for r in rows:
            g = groups.setdefault((r.get("FECHA"), r.get("NIVEL")), {"deps": {}, "dists": {}})
            dep = _dep_name(r.get("NOMBDEP"))
            n = int(r.get("N") or r.get("n") or 1)
            g["deps"][dep] = g["deps"].get(dep, 0) + n
            if r.get("NOMBDIST"):
                code = gz.from_admin(_proper(str(r.get("NOMBDIST") or "")), _proper(str(r.get("NOMBPROV") or "")), dep)
                if code and len(code) == 6:
                    g["dists"][code] = g["dists"].get(code, 0) + n
        for (fecha, nivel), g in sorted(groups.items(), key=lambda kv: (kv[0][0] or 0, str(kv[0][1])), reverse=True):
            when = _day_ms(fecha)
            per = sorted(g["deps"].items(), key=lambda x: (-x[1], x[0]))
            total = sum(n for _, n in per)
            deps = [d for d, _ in per]
            dists = sorted(g["dists"].items(), key=lambda x: (-x[1], x[0]))
            where = f"NIVEL='{nivel}'" + (f" AND FECHA=DATE '{when.date().isoformat()}'" if when else "")
            in_dists = f" en {len(dists)} distrito{'s' if len(dists) != 1 else ''}" if dists else ""
            top = ", ".join(f"{gz.label(c)['name']} ({gz.label(c[:2])['name']}) {n}" for c, n in dists[:8])
            items.append({"title": clean_text(f"SENAMHI · aviso de activación de quebradas por lluvias, {str(nivel).lower()}: "
                                              f"{total} quebrada{'s' if total != 1 else ''}{in_dists} de {_join(deps[:6])}"
                                              + (f" y {len(deps) - 6} departamentos más" if len(deps) > 6 else ""), 300),
                          "link": _layer_link(base_url, where), "published": _iso(when) if when else None,
                          "summary": clean_text("Quebradas con probable activación en las próximas 24 horas, según el SENAMHI, "
                                                "por departamento: " + ", ".join(f"{d} ({n})" for d, n in per) + "."
                                                + (f" Distritos con más quebradas: {top}." if top else ""), 600),
                          "categories": ["huaico", str(nivel)], "geo": [", ".join(f"departamento de {d}" for d in deps)],
                          **({"areas": [{"code": c, "name": gz.label(c)["name"], "n": n} for c, n in dists]} if dists else {})})
    elif "INTENSIDAD" in keys and "RANGO" in keys:  # peligro de incendios forestales (FWI): polígonos sin lugares
        kind = "fwi"
        from .geo import department_names
        from .geopoly import cap_rings, polygon_departments, shape_rings

        names = department_names()
        groups, shapes = {}, {}
        for f in feats:
            r = (f or {}).get("properties") or (f or {}).get("attributes") or {}
            k = (r.get("FECHA"), str(r.get("INTENSIDAD") or "").strip(), str(r.get("RANGO") or "").strip())
            g = groups.setdefault(k, {})
            for code, area in polygon_departments((f or {}).get("geometry") or {}).items():
                g[code] = g.get(code, 0.0) + area
            shapes.setdefault(k, []).extend(shape_rings((f or {}).get("geometry") or {}))
        for (fecha, intensidad, rango), by_dep in sorted(groups.items(), key=lambda kv: (kv[0][0] or 0, kv[0][1]), reverse=True):
            rings = cap_rings(shapes.get((fecha, intensidad, rango)) or [])
            total = sum(by_dep.values())
            # Las astillas de menos del 3 % del área no nombran un departamento.
            codes = [c for c, a in sorted(by_dep.items(), key=lambda x: -x[1]) if total and a / total >= 0.03]
            when = _day_ms(fecha)
            deps = [names.get(c, c) for c in codes]
            level = intensidad.lower() or "sin nivel"
            items.append({"title": clean_text(f"SENAMHI · peligro {level} de incendios forestales (índice FWI {rango})"
                                              + (f": {_join(deps[:6])}" if deps else "")
                                              + (f" y {len(deps) - 6} departamentos más" if len(deps) > 6 else ""), 300),
                          "link": _layer_link(base_url, f"INTENSIDAD='{intensidad}'"
                                              + (f" AND FECHA=DATE '{when.date().isoformat()}'" if when else "")),
                          "published": _iso(when) if when else None,
                          "summary": clean_text(f"Zonas donde el índice meteorológico de peligro de incendios forestales (FWI) "
                                                f"está {_range_es(rango)}, nivel {level}, según el aviso de 24 horas del SENAMHI. "
                                                + (f"Departamentos, de mayor a menor área: {', '.join(deps)}. " if deps else "")
                                                + "No es un incendio: son condiciones en que un fuego se inicia y propaga con facilidad.", 600),
                          "categories": ["incendio", "FWI", intensidad],
                          "ubigeo": codes, "geo": [", ".join(f"departamento de {d}" for d in deps)] if deps else [],
                          **({"shapes": [{"rings": rings}]} if rings else {})})
    elif "NIVEL" in keys and "NOMBDEP" not in keys:  # avisos de precipitaciones de 24 horas: polígonos por nivel
        kind = "lluvias"
        from .geo import department_names
        from .geopoly import cap_rings, polygon_departments, shape_rings

        names = department_names()
        groups, shapes = {}, {}
        for f in feats:
            r = (f or {}).get("properties") or (f or {}).get("attributes") or {}
            nivel = str(r.get("NIVEL") or "").strip()
            if not re.match(r"(?i)^nivel\s+[2-4]$", nivel):
                continue  # el nivel 1 (verde) no es un aviso
            g = groups.setdefault((r.get("FECHA"), nivel), {})
            shapes.setdefault((r.get("FECHA"), nivel), []).extend(shape_rings((f or {}).get("geometry") or {}))
            # Un polígono cubre a veces varios departamentos: su área se reparte con una grilla.
            for code, area in polygon_departments((f or {}).get("geometry") or {}, sample=True).items():
                g[code] = g.get(code, 0.0) + area
        for (fecha, nivel), by_dep in sorted(groups.items(), key=lambda kv: (kv[0][0] or 0, kv[0][1]), reverse=True):
            total = sum(by_dep.values())
            codes = [c for c, a in sorted(by_dep.items(), key=lambda x: -x[1]) if total and a / total >= 0.03]
            when = _day_ms(fecha)
            deps = [names.get(c, c) for c in codes]
            more = len(deps) - 6
            named = _join(deps) if more <= 0 else f"{', '.join(deps[:6])} y {more} departamento{'s' if more > 1 else ''} más"
            items.append({"title": clean_text(f"SENAMHI · aviso de precipitaciones para 24 horas, {nivel.lower()}"
                                              + (f": {named}" if deps else ""), 300),
                          "link": _layer_link(base_url, f"NIVEL='{nivel}'"
                                              + (f" AND FECHA=DATE '{when.date().isoformat()}'" if when else "")),
                          "published": _iso(when) if when else None,
                          "summary": clean_text(f"Zonas con aviso de precipitaciones de {nivel.lower()} para las próximas "
                                                "24 horas, según la capa del SENAMHI en el servidor GEOSINPAD del INDECI. "
                                                + (f"Departamentos, de mayor a menor área: {', '.join(deps)}." if deps else ""), 600),
                          "categories": ["lluvias", nivel], "ubigeo": codes,
                          "geo": [", ".join(f"departamento de {d}" for d in deps)] if deps else [],
                          **({"shapes": [{"rings": rings}]} if (rings := cap_rings(shapes.get((fecha, nivel)) or [])) else {})})
        if not items:
            return Parsed("arcgis-json", [], ["la capa no tiene avisos de nivel 2 o más"], kind)
    else:
        raise FeedError("capa de ArcGIS sin los campos de un aviso conocido")
    out = _finish(Parsed("arcgis-json", items))
    out.title = kind  # qué avisos trajo la capa: ``arcgis_kind_error`` lo compara con la capa que se pidió
    return out


#: Qué avisos trae cada capa del SENAMHI en GEOSINPAD (``news.Feed.layer`` → lo que ``parse_arcgis`` reconoce).
ARCGIS_KINDS = (("AvisoActQuebrada", "quebradas"), ("AvisoHidrologico", "hidrologico"), ("AvisoFWI", "fwi"),
                ("AvisoPP", "lluvias"))


def arcgis_kind_error(layer: str, kind: str) -> str:
    """Por qué la capa respondió otros avisos que los de ``layer`` (el URL apunta a otra capa: el servidor las
    renumeró), o "". Una capa de otros avisos con datos se leía como si fuera la pedida: los avisos de incendios
    salían como hidrológicos (``tools/drift_sim.py``, mutación ``arcgis-other-layer``)."""
    want = next((k for name, k in ARCGIS_KINDS if name in (layer or "")), "")
    if want and kind and kind != want:
        return f"la capa respondió avisos de «{kind}», no los de {layer} («{want}»): ¿el servidor renumeró las capas?"
    return ""


# --- NASA FIRMS: focos de calor (VIIRS, 24 horas) -----------------------------------
# Un CSV con todos los focos de Sudamérica de las últimas 24 horas, solo con
# coordenadas. Se ubican por departamento con los límites del INDECI y se publica
# un resumen por corrida: cuántos focos y dónde. Las detecciones de baja confianza
# no se cuentan.

FIRMS_MAP = "https://firms.modaps.eosdis.nasa.gov/map/#d:24hrs;@-75.0,-9.4,5.6z"
FIRMS_COLUMNS = ("latitude", "longitude", "acq_date", "acq_time")
#: El archivo es el de Sudamérica (``J1_VIIRS_C2_South_America_24h.csv``): un foco fuera de este recuadro (lat0, lon0,
#: lat1, lon1) es una columna corrida, no un incendio.
_FIRMS_BOX = (-60.0, -95.0, 15.0, -30.0)


def _days_es(a: datetime, b: datetime) -> str:
    """«19 y 20 de octubre», «20 de octubre», «31 de octubre y 1 de noviembre» (hora del Perú). El archivo
    «24h» de FIRMS junta las pasadas del satélite de unas 24 a 38 horas, así que se dicen los días."""
    months = {v: k for k, v in _ES_MONTHS.items() if k != "setiembre"}
    a, b = a.astimezone(LIMA), b.astimezone(LIMA)
    if a.date() == b.date():
        return f"{b.day} de {months[b.month]}"
    if a.month == b.month:
        return f"{a.day} y {b.day} de {months[b.month]}" if (b - a).days < 2 else f"del {a.day} al {b.day} de {months[b.month]}"
    return f"{a.day} de {months[a.month]} y {b.day} de {months[b.month]}"


def parse_firms(body: bytes, base_url: str = "") -> Parsed:
    import csv
    import io

    from .geo import department_names
    from .geopoly import department_at

    text = text_of(body)
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in FIRMS_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        # «latitude;longitude;…» (otro separador) pasaba el control de la cabecera y daba «sin focos» sin aviso.
        raise FeedError(f"no es un CSV de focos de calor de FIRMS: faltan las columnas {', '.join(missing)} "
                        f"(cabecera: «{text.split(chr(10), 1)[0][:120]}»)")
    names = department_names()
    by_dep: dict[str, int] = {}
    times, low, sat, spots = [], 0, "", []
    rows = numeric = outside = 0
    for r in reader:
        rows += 1
        try:
            lat, lon = float(r["latitude"]), float(r["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        numeric += 1
        if not (_FIRMS_BOX[0] <= lat <= _FIRMS_BOX[2] and _FIRMS_BOX[1] <= lon <= _FIRMS_BOX[3]):
            outside += 1
            continue
        if not (_PERU_BOX[0] <= lat <= _PERU_BOX[2] and _PERU_BOX[1] <= lon <= _PERU_BOX[3]):
            continue
        code = department_at(lat, lon)
        if not code:
            continue  # países vecinos dentro del recuadro
        if str(r.get("confidence") or "").strip().lower() in ("l", "low"):
            low += 1
            continue
        by_dep[code] = by_dep.get(code, 0) + 1
        spots.append((lat, lon))
        sat = sat or str(r.get("satellite") or "").strip()
        hhmm = str(r.get("acq_time") or "").strip().zfill(4)
        try:
            times.append(datetime.strptime(f"{r['acq_date']} {hhmm}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc))
        except (KeyError, ValueError):
            pass
    if not rows:
        # El archivo es el de toda Sudamérica en 24 horas: VIIRS ve allí cientos de focos cada día (quemas agrícolas,
        # mecheros de gas, incendios en la Amazonía); un CSV sin ninguna fila es un archivo vacío, no un día sin
        # fuego, y se publicaba «sin focos de calor en el Perú» (``tools/drift_sim.py``, mutación ``csv-header-only``).
        raise FeedError("el CSV de focos de calor de Sudamérica de FIRMS no trae ninguna fila")
    if numeric < rows / 2:
        raise FeedError(f"solo {numeric} de {rows} filas del CSV de FIRMS tienen coordenadas numéricas: "
                        "¿coma decimal u otro separador?")
    if numeric and outside > numeric * 0.05:
        raise FeedError(f"{outside} de {numeric} focos del CSV de Sudamérica de FIRMS caen fuera de Sudamérica: "
                        "¿latitud y longitud intercambiadas?")
    repairs = [f"{low} detecciones de baja confianza no contadas"] if low else []
    if not by_dep:
        return Parsed("firms-csv", [], repairs + ["sin focos de calor en el Perú en las últimas 24 horas"])
    per = sorted(by_dep.items(), key=lambda x: (-x[1], names.get(x[0], x[0])))
    total = sum(n for _, n in per)
    top = [f"{names.get(c, c)} ({n})" for c, n in per[:3]]
    sat_name = {"N": "Suomi NPP", "1": "NOAA-20", "N20": "NOAA-20", "J1": "NOAA-20", "N21": "NOAA-21", "J2": "NOAA-21"}.get(sat, sat)
    span = (f"entre el {min(times).astimezone(LIMA):%d/%m %H:%M} y el {max(times).astimezone(LIMA):%d/%m %H:%M} (UTC−5)"
            if times else "en las últimas 24 horas")
    title = (f"NASA FIRMS · {total} foco{'s' if total != 1 else ''} de calor en el Perú"
             + (f" ({_days_es(min(times), max(times))})" if times else "") + ": "
             + _join(top + ([f"{len(per) - 3} departamentos más"] if len(per) > 3 else [])))
    summary = (f"Detecciones del satélite {sat_name or '?'} (VIIRS, 375 m) {span}: "
               + ", ".join(f"{names.get(c, c)} {n}" for c, n in per) + ". Un foco de calor es una temperatura alta "
               "detectada desde el espacio: puede ser un incendio forestal, una quema agrícola u otra fuente de calor.")
    from .geopoly import grid_points

    # Dónde están los focos: celdas de 0,1° (~11 km) con cuántos caen en cada una (un foco es un píxel de 375 m).
    cells = [{**c, "kind": "focos"} for c in grid_points(spots)]
    item = {"title": clean_text(title, 300), "link": FIRMS_MAP, "published": _iso(max(times)) if times else None,
            "summary": clean_text(summary, 600), "categories": ["incendio", "focos de calor"],
            "ubigeo": [c for c, _ in per], "geo": [", ".join(f"departamento de {names.get(c, c)}" for c, _ in per)],
            "points": cells}
    return Parsed("firms-csv", [item], repairs)


# --- INDECI COEN: reportes de emergencias (RSS de WordPress) ------------------------
# El feed es válido, pero sus titulares son el rótulo administrativo completo
# («REPORTE COMPLEMENTARIO N.° 14630 – 20/10/2026 / COEN-INDECI / 21:00 HORAS
# (Reporte N.° 5) INCENDIO FORESTAL EN EL DISTRITO DE CURAHUASI – APURÍMAC»).
# Se reescriben como «Incendio forestal en el distrito de Curahuasi (Apurímac)» y el
# rótulo pasa al resumen. Las emergencias que no son peligros naturales (incendios
# urbanos, accidentes, derrames) no son del alcance del observatorio.

_COEN_TITLE_RE = re.compile(
    r"^(?P<tipo>REPORTE\s+(?:COMPLEMENTARIO|PRELIMINAR)|INFORME\s+DE\s+EMERGENCIA)\s*N\.?\s*[°º]?\s*(?P<num>\d+)"
    r"(?:-\d{4}-INDECI/COEN)?\s*[–-]?\s*(?P<fecha>\d{1,2}/\d{1,2}/\d{4})?\s*/?\s*COEN\s*[–-]?\s*INDECI\s*/?\s*"
    r"(?:(?P<hora>\d{1,2}:\d{2})\s*HORAS)?\s*(?:\((?:Reporte|Informe)\s*N\.?\s*[°º]?\s*(?P<seq>\d+)\))?\s*(?P<evento>.+)$",
    re.I | re.S)
_COEN_WHERE_RE = re.compile(r"^(?P<que>.+?)\s+EN\s+(?P<donde>(?:EL|LOS)\s+DISTRITOS?\s+DE\s+.+|LA\s+PROVINCIA\s+DE\s+.+|"
                            r"LAS\s+PROVINCIAS\s+DE\s+.+|LA\s+REGI[ÓO]N\s+.+|EL\s+DEPARTAMENTO\s+DE\s+.+)$", re.I | re.S)
_COEN_BULLETIN_RE = re.compile(r"^BOLET[ÍI]N\s+INFORMATIVO\s+DE\s+AVISO\s+(?P<kind>METEOROL[ÓO]GICO|HIDROL[ÓO]GICO)\s*"
                               r"N\.?\s*[°º]?\s*(?P<num>\d+)", re.I)
#: Otros boletines del COEN: avisos de oleaje (de la DHN), avisos de corto plazo (del SENAMHI, para 24 horas) y
#: boletines que no son avisos (sismos, que llegan del IGP, USGS y la DHN; el resumen diario de peligros).
_COEN_OLEAJE_RE = re.compile(r"^BOLET[ÍI]N\s+INFORMATIVO\s+DE\s+OLEAJES?\s*N\.?\s*[°º]?\s*(?P<num>\d+)", re.I)
_COEN_CORTO_RE = re.compile(r"^BOLET[ÍI]N\s+INFORMATIVO\s+DE\s+AVISO\s+DE\s+CORTO\s+PLAZO\s+ANTE\s+(?P<what>.+?)\s*"
                            r"N\.?\s*[°º]?\s*(?P<num>\d+)", re.I)
_COEN_NOT_AVISO_RE = re.compile(r"^BOLET[ÍI]N\s+INFORMATIVO\s+(?:S[ÍI]SMICO|(?:DE\s+)?MONITOREO)", re.I)
_COEN_OLEAJE_TXT_RE = re.compile(r"AVISO\s+ESPECIAL\s+DE\s+OLEAJE\s*N\.?\s*[°º]?\s*(?P<num>\d+)\s*:\s*(?P<what>.+?)\s*"
                                 r"(?:VIGENCIA\s*:\s*(?P<when>.+?))?\s*$", re.I | re.S)
_COEN_AVISO_RE = re.compile(r"AVISO\s*N\.?\s*[°º]?\s*(?P<num>\d+)\s*:\s*(?P<what>.+?)\s*(?:VIGENCIA\s*:\s*(?P<when>.+?))?\s*$", re.I | re.S)
_COEN_FACTS_RE = re.compile(r"HECHOS:\s*Fecha y hora de la ocurrencia\s+Descripci[óo]n\s+(?P<d>\d{1,2}/\d{1,2}/\d{4})\s+"
                            r"(?P<h>\d{1,2}:\d{2})\s*horas\s*(?P<txt>.*)$", re.I | re.S)
#: Peligros inducidos por la acción humana, según la clasificación del INDECI.
COEN_HUMAN_RE = re.compile(r"^(?:INCENDIO\s+(?:URBANO|INDUSTRIAL|VEHICULAR|EN\s+VIVIENDA)|ACCIDENTE|DERRAME|FUGA|EXPLOSI[ÓO]N|"
                           r"CONTAMINACI[ÓO]N|INTOXICACI[ÓO]N|COLAPSO\s+DE\s+(?:ESTRUCTURA|EDIFICACI[ÓO]N)|"
                           r"MATERIALES\s+PELIGROSOS|CONFLICTO|INCENDIO\s+EN\s+(?:MERCADO|ESTABLECIMIENTO))", re.I)
_LOWER = {"de", "del", "la", "las", "los", "y", "e", "el", "en"}


def _cap(s: str) -> str:
    """«INCENDIO FORESTAL» → «Incendio forestal»."""
    s = re.sub(r"\s+", " ", s).strip()
    return s[:1].upper() + s[1:].lower()


def _proper(s: str) -> str:
    """«RAMÓN CASTILLA» → «Ramón Castilla»; «MADRE DE DIOS» → «Madre de Dios»."""
    words = re.sub(r"\s+", " ", s).strip().lower().split(" ")
    return " ".join(w if (i and w in _LOWER) else w[:1].upper() + w[1:] for i, w in enumerate(words))


def _coen_place(donde: str) -> str:
    donde = re.sub(r"\s+", " ", donde).strip()
    m = re.match(r"^(?P<lvl>(?:EL|LOS) DISTRITOS? DE|LA PROVINCIA DE|LAS PROVINCIAS DE|LA REGI[ÓO]N|EL DEPARTAMENTO DE)\s+"
                 r"(?P<names>.+?)(?:\s*[–-]\s*(?P<dep>[^–-]+))?$", donde, re.I)
    if not m:
        return _proper(donde)
    lvl = m.group("lvl").lower().replace("region", "región")
    names = _proper(m.group("names"))
    dep = _dep_name(m.group("dep")) if m.group("dep") else ""
    if lvl in ("la región", "el departamento de"):
        return f"{lvl} {_dep_name(m.group('names'))}"
    return f"{lvl} {names}" + (f" ({dep})" if dep else "")


def parse_coen(body: bytes, base_url: str) -> Parsed:
    from .feedparse import parse as parse_feed

    p = parse_feed(body, base_url=base_url, default_tz=LIMA)
    items, human, drills, other = [], 0, 0, 0
    for e in p.items:
        title = re.sub(r"\s+", " ", e["title"]).strip()
        summary = e["summary"]
        if SIMULACRO_RE.search(title):
            drills += 1
            continue
        if _COEN_NOT_AVISO_RE.match(title):
            other += 1
            continue
        b = _COEN_BULLETIN_RE.match(title)
        ol, cp = _COEN_OLEAJE_RE.match(title), _COEN_CORTO_RE.match(title)
        if ol or cp:
            # El detalle (vigencia, provincias o tramos del litoral) está en el PDF: lo lee ``documentos``.
            flat = re.sub(r"\s+", " ", summary)
            if ol:
                a = _COEN_OLEAJE_TXT_RE.search(flat)
                what = _cap(a.group("what")).lower() if a else ""
                num = a.group("num") if a else ol.group("num")
                new = f"Aviso especial de oleaje N° {num}" + (f": {what}" if what else "")
                if a and a.group("when"):
                    new += f" (vigencia: {a.group('when').strip().lower()})"
                cats = ["aviso de oleaje", "oleaje"]
            else:
                new = f"Aviso de corto plazo ante {_cap(cp.group('what')).lower()} (boletín N° {cp.group('num')} del COEN)"
                cats = ["aviso de corto plazo"]
            e = dict(e, title=clean_text(new, 300),
                     summary=clean_text(f"{flat if not flat.upper().startswith('BOLET') else ''} Difundido por el COEN del "
                                        f"INDECI en su {title.split(' N')[0].lower()}.", 600),
                     categories=cats)
            items.append(e)
            continue
        m = _COEN_TITLE_RE.match(title)
        if b:  # avisos del SENAMHI que el COEN difunde
            kind = "meteorológico" if b.group("kind").upper().startswith("METEOROL") else "hidrológico"
            a = _COEN_AVISO_RE.search(re.sub(r"\s+", " ", summary))
            what = _cap(a.group("what")).lower() if a else ""
            when = f" (vigencia: {a.group('when').strip().lower()})" if a and a.group("when") else ""
            num = a.group("num") if a else b.group("num")
            e = dict(e, title=clean_text(f"Aviso {kind} N° {num} del SENAMHI" + (f": {what}{when}" if what else ""), 300),
                     summary=clean_text((f"Aviso {kind} N° {num}: {what}. "
                                         + (f"Vigencia: {a.group('when').strip().lower()}. " if a.group("when") else "")
                                         if what else f"{summary} ")
                                        + f"Difundido por el COEN del INDECI en su {title.split(' N')[0].lower()}.", 600),
                     categories=["aviso " + kind])
        elif m:
            evento = re.sub(r"\s+", " ", m.group("evento")).strip()
            if COEN_HUMAN_RE.match(evento):
                human += 1
                continue
            w = _COEN_WHERE_RE.match(evento)
            new = f"{_cap(w.group('que'))} en {_coen_place(w.group('donde'))}" if w else _cap(evento)
            label = f"{_cap(m.group('tipo'))} N° {m.group('num')} del COEN-INDECI"
            label += f", {m.group('fecha')}" if m.group("fecha") else ""
            label += f" {m.group('hora')} h" if m.group("hora") else ""
            label += f" (actualización N° {m.group('seq')})" if m.group("seq") else ""
            f = _COEN_FACTS_RE.match(re.sub(r"\s+", " ", summary))
            facts = f"Ocurrió el {f.group('d')} a las {f.group('h')}. {f.group('txt')}" if f else summary
            e = dict(e, title=clean_text(new, 300), summary=clean_text(f"{label}. {facts}", 600),
                     categories=[_cap(w.group("que") if w else evento)])
        items.append(e)
    out = _finish(Parsed(p.format, items, list(p.repairs)))
    if human:
        out.repairs.append(f"{human} reportes de emergencias no naturales omitidos (incendios urbanos, accidentes…)")
    if drills:
        out.repairs.append(f"{drills} reportes de simulacro omitidos")
    if other:
        out.repairs.append(f"{other} boletines que no son avisos omitidos (sísmicos, monitoreo de peligros)")
    return out


ADAPTERS = {"dhn": parse_dhn, "dhn-avisos": parse_dhn_avisos, "ptwc-text": parse_ptwc_text, "cenvul": parse_cenvul, "telegram": parse_telegram,
            "arcgis": parse_arcgis, "indeci-coen": parse_coen, "firms": parse_firms}


#: Fechas anteriores a esto no son avisos vigentes ni recientes: son una fecha mal leída (segundos Unix leídos como
#: milisegundos dan enero de 1970). El mismo límite que ``feedparse._plausible``.
OLDEST = "1995-01-01"


def _query_box(base_url: str) -> Optional[tuple[float, float, float, float]]:
    """Recuadro (lat0, lon0, lat1, lon1) que pide el URL (``minlatitude``… de la consulta FDSN del USGS), o None."""
    from urllib.parse import parse_qs, urlsplit

    q = {k: v[0] for k, v in parse_qs(urlsplit(base_url).query).items()}
    try:
        return (float(q["minlatitude"]), float(q["minlongitude"]), float(q["maxlatitude"]), float(q["maxlongitude"]))
    except (KeyError, ValueError):
        return None


def _vet(p: Parsed, base_url: str, adapter: str) -> Parsed:
    """Lo que ningún lector de peligros debe publicar sin aviso: fechas imposibles y coordenadas fuera del mundo o del
    área pedida. Una entrada así es un cambio de formato de la fuente (otra unidad de tiempo, latitud y longitud
    intercambiadas, otra proyección): ``FeedError``, no una alerta en otro lugar u otro año (``tools/drift_sim.py``,
    mutaciones ``json-epoch-seconds``, ``json-coords-swap`` y ``json-scale-x10``)."""
    old = [i for i in p.items if i.get("published") and str(i["published"]) < OLDEST]
    if old:
        raise FeedError(f"{len(old)} de {len(p.items)} entradas con fecha anterior a {OLDEST[:4]} "
                        f"(p. ej. {old[0]['published']}): ¿la fecha viene en otra unidad o formato?")
    box = _query_box(base_url) if adapter == "geojson" else None
    for i in p.items:
        for pt in i.get("points") or []:
            _vet_point(pt.get("lat"), pt.get("lon"), box, i["title"][:80])
    return p


def _vet_point(lat, lon, box: Optional[tuple], title: str) -> None:
    """``FeedError`` si (lat, lon) es imposible o cae fuera del recuadro pedido (con medio grado de holgura)."""
    if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))):
        return
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise FeedError(f"coordenadas imposibles ({lat}, {lon}) en «{title}»: ¿otra unidad o proyección?")
    if box and not (box[0] - 0.5 <= lat <= box[2] + 0.5 and box[1] - 0.5 <= lon <= box[3] + 0.5):
        raise FeedError(f"«{title}» está en ({lat}, {lon}), fuera del área pedida {box}: "
                        "¿latitud y longitud intercambiadas?")


def parse(body: bytes, base_url: str, adapter: str) -> Parsed:
    if adapter == "geojson":
        try:
            data = json.loads(body.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise FeedError(f"JSON inválido: {exc}") from exc
        return _vet(parse_geojson(data, base_url), base_url, adapter)
    return _vet(ADAPTERS[adapter](body, base_url), base_url, adapter)
