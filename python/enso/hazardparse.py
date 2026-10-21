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
import json
import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional

from .feedparse import LIMA, FeedError, Parsed, clean_summary, clean_text, _finish

COMPASS = {"N": "N", "NNE": "NNE", "NE": "NE", "ENE": "ENE", "E": "E", "ESE": "ESE", "SE": "SE", "SSE": "SSE",
           "S": "S", "SSW": "SSO", "SW": "SO", "WSW": "OSO", "W": "O", "WNW": "ONO", "NW": "NO", "NNW": "NNO"}
_USGS_PLACE_RE = re.compile(r"^(\d+)\s*km\s+([NSEW]{1,3})\s+of\s+(.+)$")
SIMULACRO_RE = re.compile(r"\bsimulacros?\b|\bdrill\b|\bexercise\b", re.I)
_EN_DATE = "%A, %B %d, %Y"


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
    text = body.decode("utf-8", errors="replace")
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
    text = body.decode("utf-8", errors="replace")
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
        item = {"title": clean_text(title, 300), "link": f"{base_url.split('#')[0]}#{aid.group(1) if aid else num}",
                "published": _iso(when) if when else None, "summary": clean_text(summary, 600),
                "categories": [kind, f"aviso especial {num}"]}
        if geo:
            item["geo"] = [", ".join(geo)]
        items.append(item)
    if not items:
        raise FeedError("el listado de la DHN no tiene avisos especiales con el formato esperado")
    return _finish(Parsed("dhn-avisos-html", items))


# --- PTWC: mensaje de texto (WEPA40) ------------------------------------------------

_PTWC_ISSUED_RE = re.compile(r"^(\d{4}) UTC \w{3} (\w{3}) (\d{1,2}) (\d{4})$", re.M)
_PTWC_PARAM_RE = re.compile(r"\*\s+(MAGNITUDE|ORIGIN TIME|COORDINATES|DEPTH|LOCATION)\s+(.+)")
_PTWC_THREAT_RE = re.compile(r"TSUNAMI THREAT FORECAST.*?\n-+\n(?P<txt>.*?)(?:\n[A-Z][A-Z .]+\n-+\n|\Z)", re.S)
_MON = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def parse_ptwc_text(body: bytes, base_url: str = "") -> Parsed:
    """Último mensaje del Centro de Alerta de Tsunamis del Pacífico (el filtro de relevancia
    deja solo los que nombran al Perú, como con su feed Atom)."""
    text = body.decode("utf-8", errors="replace").replace("\r", "")
    if "TSUNAMI" not in text or "PACIFIC TSUNAMI WARNING CENTER" not in text:
        raise FeedError("no es un mensaje del PTWC")
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


def _en_date(s: str, hm: str = "") -> Optional[str]:
    try:
        d = datetime.strptime(s.strip(), _EN_DATE)
    except ValueError:
        return None
    if hm:
        try:
            t = datetime.strptime(hm.strip(), "%I:%M:%S %p")
            d = d.replace(hour=t.hour, minute=t.minute, second=t.second)
        except ValueError:
            pass
    else:
        d = d.replace(hour=12)  # sin hora: mediodía de Lima, para que la fecha no cambie al pasar a UTC
    return _iso(d.replace(tzinfo=LIMA))


#: Dónde está cada volcán que vigila el IGP, para ubicar sus boletines y alertas.
VOLCANOES = {
    "sabancaya": "la provincia de Caylloma (Arequipa)", "ampato": "la provincia de Caylloma (Arequipa)",
    "misti": "la provincia de Arequipa (Arequipa)", "chachani": "la provincia de Arequipa (Arequipa)",
    "coropuna": "la provincia de Castilla (Arequipa)", "ubinas": "la provincia de General Sánchez Cerro (Moquegua)",
    "huaynaputina": "la provincia de General Sánchez Cerro (Moquegua)", "ticsani": "la provincia de Mariscal Nieto (Moquegua)",
    "tutupaca": "la provincia de Candarave (Tacna)", "yucamane": "la provincia de Candarave (Tacna)",
    "casiri": "el departamento de Tacna", "purupuruni": "el departamento de Tacna",
    "sara sara": "la provincia de Parinacochas (Ayacucho)", "auquihuato": "la provincia de Parinacochas (Ayacucho)",
    "quimsachata": "la provincia de Canchis (Cusco)",
}


def _volcano_place(name: str) -> str:
    key = re.sub(r"\s+", " ", unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()).strip()
    where = VOLCANOES.get(key.removeprefix("el ").removesuffix(" volcano"))
    return f" El volcán {name} está en {where}." if where else ""


def parse_cenvul(body: bytes, base_url: str) -> Parsed:
    text = body.decode("utf-8", errors="replace")
    if "CENVUL" not in text:
        raise FeedError("no es una página del CENVUL")
    alerts = "alertas-vulcanologicas" in base_url
    items, green, cards = [], 0, _cards(text)
    for card in cards:
        f = {k.strip().lower(): html.unescape(v).strip() for k, v in _CARD_FIELD_RE.findall(card)}
        volcano = f.get("volcán") or f.get("volcan")
        if not volcano:
            continue
        if alerts:
            kind = f.get("tipo de alerta", "")
            when = _en_date(f.get("fecha de publicación", ""), f.get("hora de publicación", ""))
            what = {"cenizas": "dispersión de cenizas", "lahares": "descenso de lahares"}.get(kind.lower(), kind.lower())
            items.append({"title": clean_text(f"Volcán {volcano}: alerta por {what} (IGP)", 300),
                          "link": f"{base_url}#{re.sub(r'[^a-z0-9]+', '-', f'{volcano} {kind} {when or ''}'.lower()).strip('-')}",
                          "published": when,
                          "summary": f"Alerta vulcanológica del CENVUL por {what} del volcán {volcano}." + _volcano_place(volcano),
                          "categories": ["volcan", kind]})
        else:
            code = f.get("código", "")
            color = _ALERT_COLOR_RE.search(card)
            level = color.group(1) if color else ""
            if level == "Verde":
                green += 1  # actividad normal: no es una alerta
                continue
            items.append({"title": clean_text(f"Volcán {volcano}: boletín {code}" + (f", alerta {level.lower()}" if level else ""), 300),
                          "link": f"{base_url}#{re.sub(r'[^A-Za-z0-9]+', '-', code).strip('-')}",
                          "published": _en_date(f.get("fecha de publicación", "")),
                          "summary": f"Boletín vulcanológico del CENVUL (IGP) sobre el volcán {volcano}"
                                     + (f". Nivel de alerta: {level.lower()}." if level else ".") + _volcano_place(volcano),
                          "categories": ["volcan", level]})
    if not cards:
        raise FeedError("la página del CENVUL no tiene tarjetas con el formato esperado")
    out = _finish(Parsed("cenvul-html", items))
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
    text = body.decode("utf-8", errors="replace")
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
    keys = set().union(*rows)
    items: list[dict] = []
    if "NUM_AVISO" in keys:  # avisos hidrológicos: una estación por fila
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
            items.append({"title": clean_text(f"SENAMHI · aviso hidrológico N° {num}"
                                              + (f" (nivel {color})" if color else "")
                                              + f": {_river_title(str(r0.get('TITULO') or 'situación de los ríos'))}", 300),
                          "link": _layer_link(base_url, f"NUM_AVISO={int(num)}" if str(num).isdigit() else f"NUM_AVISO='{num}'"),
                          "published": _iso(when) if when else None,
                          "summary": clean_text(" ".join(x for x in facts if x), 600),
                          "categories": [f"aviso hidrológico {num}"], "geo": list(dict.fromkeys(where))})
    elif "NIVEL" in keys and "NOMBDEP" in keys:  # activación de quebradas: distritos (o conteos) por nivel
        groups: dict = {}
        for r in rows:
            groups.setdefault((r.get("FECHA"), r.get("NIVEL")), {}).setdefault(_dep_name(r.get("NOMBDEP")), 0)
            groups[(r.get("FECHA"), r.get("NIVEL"))][_dep_name(r.get("NOMBDEP"))] += int(r.get("N") or r.get("n") or 1)
        for (fecha, nivel), by_dep in sorted(groups.items(), key=lambda kv: (kv[0][0] or 0, str(kv[0][1])), reverse=True):
            when = _day_ms(fecha)
            per = sorted(by_dep.items(), key=lambda x: (-x[1], x[0]))
            total = sum(n for _, n in per)
            deps = [d for d, _ in per]
            where = f"NIVEL='{nivel}'" + (f" AND FECHA=DATE '{when.date().isoformat()}'" if when else "")
            items.append({"title": clean_text(f"SENAMHI · aviso de activación de quebradas por lluvias, {str(nivel).lower()}: "
                                              f"{total} distrito{'s' if total != 1 else ''} de {_join(deps[:6])}"
                                              + (f" y {len(deps) - 6} departamentos más" if len(deps) > 6 else ""), 300),
                          "link": _layer_link(base_url, where), "published": _iso(when) if when else None,
                          "summary": clean_text("Distritos con probable activación de quebradas en las próximas 24 horas, "
                                                "según el SENAMHI: " + ", ".join(f"{d} ({n})" for d, n in per) + ".", 600),
                          "categories": ["huaico", str(nivel)], "geo": [", ".join(f"departamento de {d}" for d in deps)]})
    else:
        raise FeedError("capa de ArcGIS sin los campos de un aviso conocido")
    return _finish(Parsed("arcgis-json", items))


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
    items, human, drills = [], 0, 0
    for e in p.items:
        title = re.sub(r"\s+", " ", e["title"]).strip()
        summary = e["summary"]
        if SIMULACRO_RE.search(title):
            drills += 1
            continue
        b = _COEN_BULLETIN_RE.match(title)
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
    return out


ADAPTERS = {"dhn": parse_dhn, "dhn-avisos": parse_dhn_avisos, "ptwc-text": parse_ptwc_text, "cenvul": parse_cenvul, "telegram": parse_telegram,
            "arcgis": parse_arcgis, "indeci-coen": parse_coen}


def parse(body: bytes, base_url: str, adapter: str) -> Parsed:
    if adapter == "geojson":
        try:
            return parse_geojson(json.loads(body.decode("utf-8-sig")), base_url)
        except (UnicodeDecodeError, ValueError) as exc:
            raise FeedError(f"JSON inválido: {exc}") from exc
    return ADAPTERS[adapter](body, base_url)
