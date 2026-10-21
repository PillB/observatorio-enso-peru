"""Nivel, vigencia y naturaleza de cada aviso de las fuentes oficiales de peligros.

El mapa de alertas pinta los departamentos con el nivel que **la propia institución** asignó
al aviso. Este módulo lo lee de lo que ya escribe ``enso.hazardparse`` (titulares y resúmenes
que arma el observatorio con los campos de cada fuente) y no inventa ninguno: un aviso sin nivel
en su fuente queda con ``rank: None`` («sin nivel») y se muestra así.

Escalas de las instituciones (``SCALES``):

* SENAMHI, avisos por niveles (capas de GEOSINPAD del INDECI): «Nivel 1» a «Nivel 4». El nivel 1
  (verde) no es un aviso; 2, 3 y 4 son amarillo, naranja y rojo (activación de quebradas de magnitud
  moderada, fuerte y extrema, según el campo ``DESCRIPCIO`` de la capa).
* SENAMHI, avisos hidrológicos: umbral amarillo, naranja o rojo de cada estación (``COLOR_TEXT``).
* IGP / CENVUL: alerta volcánica verde, amarilla, naranja o roja.
* USGS: alerta PAGER verde, amarilla, naranja o roja (impacto estimado), solo si USGS la calculó.
  La magnitud de un sismo es una medida, no un nivel de alerta.
* DHN, boletines de sismo y tsunami: «no genera tsunami» (informativo), alerta o alarma de tsunami.
* PTWC: sin amenaza de tsunami o con amenaza.
* Avisos que citan un color del SENAMHI en su texto («aviso naranja», «nivel rojo»).

``rank`` ordena dentro de la escala de cada institución: 0 sin peligro (verde, informativo),
1 el nivel más bajo de aviso (amarillo), 2 intermedio (naranja), 3 el más alto (rojo, alarma). Es
solo un orden para colorear y filtrar; la etiqueta que se muestra es siempre la de la institución.

``valid`` es la vigencia que declara el aviso («del 22 al 24 de octubre», «VIGENCIA: 21-10-2026
(13:00 h) al 22-10-2026 (13:00 h)», «próximas 24 horas»); ``kind`` dice qué es cada entrada:

* ``pronostico``: un aviso de algo que se espera (tiene vigencia y puede ser futuro).
* ``en-curso``: el estado actual de algo (un río, un volcán, lo que «está ocurriendo en este momento»).
* ``reporte``: un hecho ya ocurrido (daños que informa el COEN, un sismo).
* ``deteccion``: una observación automática (focos de calor de satélite).

El sitio calcula con el reloj del navegador si un pronóstico está vigente, es próximo o venció,
comparando la hora actual con ``valid``; aquí también se guarda cómo estaba al publicar
(``phaseAtPublication``) para quien lea el JSON sin ese cálculo.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from .feedparse import LIMA

#: Escalas por institución: etiqueta de cada nivel y su orden (``rank``).
SCALES = {
    "senamhi-niveles": {"label": "SENAMHI, niveles de aviso (1 a 4)",
                        "levels": {"1": (0, "Nivel 1", "verde"), "2": (1, "Nivel 2", "amarillo"),
                                   "3": (2, "Nivel 3", "naranja"), "4": (3, "Nivel 4", "rojo")}},
    "senamhi-colores": {"label": "SENAMHI, colores de aviso",
                        "levels": {"verde": (0, "Verde", "verde"), "amarillo": (1, "Amarillo", "amarillo"),
                                   "naranja": (2, "Naranja", "naranja"), "rojo": (3, "Rojo", "rojo")}},
    "senamhi-umbral": {"label": "SENAMHI, umbral hidrológico de la estación",
                       "levels": {"amarillo": (1, "Umbral amarillo", "amarillo"),
                                  "naranja": (2, "Umbral naranja", "naranja"), "rojo": (3, "Umbral rojo", "rojo")}},
    "igp-volcan": {"label": "IGP, alerta volcánica",
                   "levels": {"verde": (0, "Alerta verde", "verde"), "amarillo": (1, "Alerta amarilla", "amarillo"),
                              "naranja": (2, "Alerta naranja", "naranja"), "rojo": (3, "Alerta roja", "rojo")}},
    "usgs-pager": {"label": "USGS, alerta PAGER de impacto estimado",
                   "levels": {"green": (0, "PAGER verde", "verde"), "yellow": (1, "PAGER amarilla", "amarillo"),
                              "orange": (2, "PAGER naranja", "naranja"), "red": (3, "PAGER roja", "rojo")}},
    "dhn-tsunami": {"label": "DHN, boletín de sismo y tsunami",
                    "levels": {"info": (0, "No genera tsunami", "verde"), "alerta": (2, "Alerta de tsunami", "naranja"),
                               "alarma": (3, "Alarma de tsunami", "rojo")}},
    "ptwc": {"label": "PTWC, amenaza de tsunami",
             "levels": {"none": (0, "Sin amenaza de tsunami", "verde"), "threat": (3, "Amenaza de tsunami", "rojo")}},
}

_COLOR = {"amarillo": "amarillo", "amarilla": "amarillo", "naranja": "naranja", "rojo": "rojo", "roja": "rojo",
          "verde": "verde"}
_MONTHS = {m: i for i, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                       "septiembre", "octubre", "noviembre", "diciembre"], 1)} | {"setiembre": 9}
_MON_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))

_NIVEL_RE = re.compile(r"\bnivel\s+([1-4])\b", re.I)
_HIDRO_RE = re.compile(r"\(nivel\s+(amarillo|naranja|rojo)\)", re.I)
_VOLCAN_RE = re.compile(r"\balerta\s+(verde|amarill[ao]|naranja|roj[ao])\b", re.I)
_PAGER_RE = re.compile(r"\balerta PAGER (green|yellow|orange|red)\b", re.I)
#: Un color del SENAMHI citado en el texto de un aviso («aviso naranja», «nivel rojo», «alerta amarilla»).
_TEXT_COLOR_RE = re.compile(r"\b(?:aviso|nivel|alerta)\s+(?:de\s+(?:color\s+)?)?(amarill[ao]|naranja|roj[ao])\b", re.I)

# «del 22 al 24 de octubre», «del 18 y 19 de octubre», «del 31 de octubre al 2 de noviembre (del 2026)»
_RANGE_RE = re.compile(
    rf"\bdel\s+(?P<d1>\d{{1,2}})(?:\s+de\s+(?P<m1>{_MON_RE}))?\s+(?:al|y)\s+(?P<d2>\d{{1,2}})\s+de\s+(?P<m2>{_MON_RE})"
    rf"(?:\s+del?\s+(?P<y>\d{{4}}))?", re.I)
# «VIGENCIA: 21-10-2026 (13:00 h) al 22-10-2026 (13:00 h)»
_VIGENCIA_RE = re.compile(r"VIGENCIA:\s*(\d{1,2})-(\d{1,2})-(\d{4})\s*\((\d{1,2}):(\d{2})\s*h\)\s*al\s*"
                          r"(\d{1,2})-(\d{1,2})-(\d{4})\s*\((\d{1,2}):(\d{2})\s*h\)", re.I)
# COEN: «Ocurrió el 6/10/2026 a las 03:00» o «HECHOS Fecha y hora de la ocurrencia Descripción 18/10/2026 11:30 horas»
_OCCURRED_RE = re.compile(r"(?:Ocurri[óo] el|Fecha y hora de (?:la )?ocurrencia Descripci[óo]n)\s+(\d{1,2})/(\d{1,2})/(\d{4})"
                          r"(?:\s+(?:a las\s+)?(\d{1,2}):(\d{2}))?", re.I)
# FIRMS: «entre el 20/10 00:21 y el 21/10 01:42 (UTC−5)»
_FIRMS_RE = re.compile(r"entre el (\d{1,2})/(\d{1,2}) (\d{1,2}):(\d{2}) y el (\d{1,2})/(\d{1,2}) (\d{1,2}):(\d{2})")

#: Horas que dura lo que «está ocurriendo en este momento» o el estado de un río o un volcán, para
#: que el mapa no lo presente como actual días después. No es una vigencia de la fuente.
CURRENT_HOURS = {"senamhi-telegram": 12, "senamhi-hidrologicos": 72, "igp-cenvul-boletines": 336,
                 "igp-cenvul-alertas": 24, "firms-focos": 24}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_when(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _level(scale: str, key: str, basis: str) -> dict:
    rank, label, color = SCALES[scale]["levels"][key]
    return {"rank": rank, "label": label, "color": color, "scale": scale,
            "scaleLabel": SCALES[scale]["label"], "basis": basis}


def _year_for(month: int, ref: datetime) -> int:
    """Año de un mes sin año: el más cercano a la fecha de publicación (un aviso de enero publicado
    en diciembre es del año siguiente)."""
    y = ref.year
    if month - ref.month > 6:
        return y - 1
    if ref.month - month > 6:
        return y + 1
    return y


def _local(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> Optional[datetime]:
    try:
        return datetime(y, m, d, hh, mm, tzinfo=LIMA)
    except ValueError:
        return None


def _range(text: str, ref: datetime) -> Optional[tuple[datetime, datetime]]:
    m = _RANGE_RE.search(text)
    if not m:
        return None
    m2 = _MONTHS[m.group("m2").lower()]
    m1 = _MONTHS[m.group("m1").lower()] if m.group("m1") else m2
    y2 = int(m.group("y")) if m.group("y") else _year_for(m2, ref)
    y1 = y2 - 1 if m1 > m2 else y2
    a, b = _local(y1, m1, int(m.group("d1"))), _local(y2, m2, int(m.group("d2")))
    if not a or not b or b < a or (b - a).days > 31:
        return None
    return a, b + timedelta(days=1) - timedelta(minutes=1)


def severity(feed_id: str, title: str, summary: str) -> Optional[dict]:
    """El nivel que la institución asignó al aviso, o ``None`` si su fuente no trae uno."""
    text = f"{title} {summary}"
    if feed_id == "senamhi-quebradas":
        m = _NIVEL_RE.search(title)
        return _level("senamhi-niveles", m.group(1), "campo NIVEL de la capa del SENAMHI en GEOSINPAD") if m else None
    if feed_id == "senamhi-hidrologicos":
        m = _HIDRO_RE.search(title)
        return _level("senamhi-umbral", m.group(1).lower(), "campo COLOR_TEXT del aviso hidrológico") if m else None
    if feed_id == "senamhi-incendios":
        m = _NIVEL_RE.search(text) or _TEXT_COLOR_RE.search(text)
        if m and m.group(1).isdigit():
            return _level("senamhi-niveles", m.group(1), "campo INTENSIDAD de la capa del SENAMHI en GEOSINPAD")
        return _level("senamhi-colores", _COLOR[m.group(1).lower()], "campo INTENSIDAD de la capa del SENAMHI") if m else None
    if feed_id.startswith("igp-cenvul"):
        m = _VOLCAN_RE.search(text)
        return _level("igp-volcan", _COLOR[m.group(1).lower()], "nivel de alerta del boletín del CENVUL") if m else None
    if feed_id == "usgs-sismos":
        m = _PAGER_RE.search(summary)
        return _level("usgs-pager", m.group(1).lower(), "alerta PAGER publicada por USGS") if m else None
    if feed_id == "dhn-tsunamis":
        low = text.lower()
        if re.search(r"\balarma de tsunami\b", low):
            return _level("dhn-tsunami", "alarma", "estado del boletín de la DHN")
        if re.search(r"\balerta de tsunami\b", low) and not re.search(r"no (?:genera|representa)", low):
            return _level("dhn-tsunami", "alerta", "estado del boletín de la DHN")
        if re.search(r"no (?:genera|generar[ií]a|representa)\w*\s+(?:\w+\s+){0,3}tsunami", low):
            return _level("dhn-tsunami", "info", "estado del boletín de la DHN")
        return None
    if feed_id.startswith("ptwc"):
        up = text.upper()
        if "NO TSUNAMI THREAT" in up or "THERE IS NO TSUNAMI THREAT" in up:
            return _level("ptwc", "none", "mensaje del PTWC")
        if "HAZARDOUS TSUNAMI WAVES" in up or "TSUNAMI THREAT" in up:
            return _level("ptwc", "threat", "mensaje del PTWC")
        return None
    if feed_id in ("senamhi-telegram", "indeci-coen"):
        m = _TEXT_COLOR_RE.search(text)
        return _level("senamhi-colores", _COLOR[m.group(1).lower()], "color del aviso citado en su texto") if m else None
    return None


def kind_of(feed_id: str, title: str) -> str:
    low = title.lower()
    if feed_id == "senamhi-telegram":
        return "en-curso" if low.startswith("senamhi, en este momento") else "pronostico"
    if feed_id == "indeci-coen":
        return "pronostico" if "aviso" in low and ("boletín" in low or "boletin" in low) else "reporte"
    if feed_id in ("senamhi-quebradas", "senamhi-incendios", "dhn-avisos") or feed_id.startswith("ptwc"):
        return "pronostico"
    if feed_id in ("senamhi-hidrologicos",) or feed_id.startswith("igp-cenvul"):
        return "en-curso"
    if feed_id == "firms-focos":
        return "deteccion"
    return "reporte"  # sismos de USGS y de la DHN


def validity(feed_id: str, title: str, summary: str, published: Optional[str]) -> Optional[dict]:
    """Vigencia declarada por el aviso (``from``, ``until``, ``basis``), o una ventana de observación."""
    ref = _parse_when(published)
    if not ref:
        return None
    text = f"{title} {summary}"
    m = _VIGENCIA_RE.search(text)
    if m:
        g = [int(x) for x in m.groups()]
        a, b = _local(g[2], g[1], g[0], g[3], g[4]), _local(g[7], g[6], g[5], g[8], g[9])
        if a and b and b > a:
            return {"from": _iso(a), "until": _iso(b), "basis": "vigencia del boletín del COEN"}
    if feed_id == "senamhi-quebradas" or (feed_id == "senamhi-incendios" and "24 horas" in text):
        return {"from": _iso(ref), "until": _iso(ref + timedelta(hours=24)),
                "basis": "aviso para las 24 horas siguientes a su emisión"}
    if feed_id in ("senamhi-telegram", "dhn-avisos") or (feed_id == "indeci-coen" and kind_of(feed_id, title) == "pronostico"):
        r = _range(title, ref) or _range(summary, ref)
        if r:
            return {"from": _iso(r[0]), "until": _iso(r[1]), "basis": "fechas que indica el aviso"}
    if feed_id == "firms-focos":
        f = _FIRMS_RE.search(summary)
        if f:
            d1, m1, h1, n1, d2, m2, h2, n2 = (int(x) for x in f.groups())
            a = _local(_year_for(m1, ref), m1, d1, h1, n1)
            b = _local(_year_for(m2, ref), m2, d2, h2, n2)
            if a and b and b >= a:
                return {"from": _iso(a), "until": _iso(b), "basis": "periodo de las detecciones del satélite",
                        "observed": True}
    return None


def occurred(feed_id: str, summary: str) -> Optional[str]:
    """Cuándo ocurrió el hecho de un reporte del COEN (el reporte puede ser una actualización días después)."""
    if feed_id != "indeci-coen":
        return None
    m = _OCCURRED_RE.search(summary)
    if not m:
        return None
    d = _local(int(m.group(3)), int(m.group(2)), int(m.group(1)), int(m.group(4) or 0), int(m.group(5) or 0))
    return _iso(d) if d else None


def phase(kind: str, valid: Optional[dict], published: Optional[str], now: datetime, feed_id: str = "") -> str:
    """vigente, proxima, vencida (pronósticos), en-curso, reciente (estado y detecciones) u ocurrido."""
    if kind == "pronostico" and valid:
        a, b = _parse_when(valid["from"]), _parse_when(valid["until"])
        if now < a:
            return "proxima"
        return "vigente" if now <= b else "vencida"
    ref = _parse_when(published)
    if kind == "pronostico":
        return "vigente" if ref and now - ref <= timedelta(hours=24) else "vencida"
    if kind in ("en-curso", "deteccion"):
        hours = CURRENT_HOURS.get(feed_id, 24)
        return "en-curso" if ref and now - ref <= timedelta(hours=hours) else "reciente"
    return "ocurrido"


def assess(feed_id: str, title: str, summary: str, published: Optional[str], now: datetime) -> dict:
    """Todo lo que el mapa necesita de un aviso, leído de su fuente."""
    kind = kind_of(feed_id, title)
    valid = validity(feed_id, title, summary, published)
    out = {"kind": kind, "severity": severity(feed_id, title, summary), "valid": valid,
           "phaseAtPublication": phase(kind, valid, published, now, feed_id)}
    occ = occurred(feed_id, summary)
    if occ:
        out["occurred"] = occ
    if kind in ("en-curso", "deteccion") and feed_id in CURRENT_HOURS:
        out["currentHours"] = CURRENT_HOURS[feed_id]
    return out
