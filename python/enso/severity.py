"""Nivel, vigencia y naturaleza de cada aviso de las fuentes oficiales de peligros.

El mapa de alertas pinta los departamentos con el nivel que **la propia institución** asignó
al aviso. Este módulo lo lee de lo que ya escribe ``enso.hazardparse`` (titulares y resúmenes
que arma el observatorio con los campos de cada fuente) y no inventa ninguno: un aviso sin nivel
en su fuente queda con ``rank: None`` («sin nivel») y se muestra así.

Escalas de las instituciones (``SCALES``):

* SENAMHI, avisos por niveles (capas de GEOSINPAD del INDECI): «Nivel 1» a «Nivel 4». El nivel 1
  (verde) no es un aviso; 2, 3 y 4 son amarillo, naranja y rojo (activación de quebradas de magnitud
  moderada, fuerte y extrema, según el campo ``DESCRIPCIO`` de la capa).
* SENAMHI, avisos de precipitaciones para 24 horas (capa ``SENAMHI_AvisoPP24H`` de GEOSINPAD): «Nivel 2»
  a «Nivel 4» por polígono, en la misma escala.
* SENAMHI, avisos meteorológicos que llegan por Telegram o por el COEN: el nivel del aviso en la tabla de
  ``?p=aviso-meteorologico`` (AMARILLO, NARANJA o ROJO), que el recolector del Perú guarda cada noche
  (``enso.senamhi_avisos``; ver ``assess``).
* SENAMHI, avisos hidrológicos: umbral amarillo, naranja o rojo de cada estación (``COLOR_TEXT``). Los que difunde
  el COEN: el umbral que dice su PDF («…ubicándose en el umbral amarillo», ``documentos``) o, si no se leyó, el
  del mismo aviso en la capa del SENAMHI (``sourcefeed.alerts``).
* SENAMHI, peligro de incendios forestales (capa ``SENAMHI_AvisoFWI24H`` de GEOSINPAD, campo ``INTENSIDAD``): bajo,
  moderado, alto, muy alto y extremo, con los colores que la capa misma declara en su ``drawingInfo`` (bajo
  transparente, moderado amarillo, alto naranja, muy alto rojo, extremo morado).
* IGP / CENVUL: alerta volcánica verde, amarilla, naranja o roja.
* USGS: alerta PAGER verde, amarilla, naranja o roja (impacto estimado), solo si USGS la calculó.
  La magnitud de un sismo es una medida, no un nivel de alerta.
* DHN, boletines de sismo y tsunami: «no genera tsunami» (informativo), alerta o alarma de tsunami.
* PTWC: sin amenaza de tsunami o con amenaza.
* Avisos que citan un color del SENAMHI en su texto («aviso naranja», «nivel rojo»).

Un aviso sin nivel nunca queda como un genérico «sin nivel»: ``level_status`` dice por qué (es un reporte, la
institución no usa niveles, el boletín reúne varios, USGS no calculó PAGER, la DHN sigue evaluando…) y, si la
fuente sí asigna niveles y no se pudo leer, lo marca ``no-leido``, que la publicación convierte en una incidencia
(``audit``). Así un cambio de formato en el campo del nivel no se confunde con «la fuente no trae nivel».

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
from .textnorm import Match, fold, level_number, lookup

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
                    "levels": {"info": (0, "No genera tsunami", "verde"),
                               "cancelacion": (0, "Cancelación de la alerta de tsunami", "verde"), "alerta": (2, "Alerta de tsunami", "naranja"),
                               "alarma": (3, "Alarma de tsunami", "rojo")}},
    "senamhi-fwi": {"label": "SENAMHI, peligro de incendios forestales (índice FWI)",
                    # El orden y los colores, los de la capa (``drawingInfo``): muy alto y extremo comparten el
                    # rango más alto de la escala común del mapa (rojo); la etiqueta los distingue.
                    "levels": {"bajo": (0, "Peligro bajo", "verde"), "moderado": (1, "Peligro moderado", "amarillo"),
                               "alto": (2, "Peligro alto", "naranja"), "muy alto": (3, "Peligro muy alto", "rojo"),
                               "extremo": (3, "Peligro extremo", "morado")}},
    "ptwc": {"label": "PTWC, amenaza de tsunami",
             "levels": {"none": (0, "Sin amenaza de tsunami", "verde"), "threat": (3, "Amenaza de tsunami", "rojo")}},
}

_MONTHS = {m: i for i, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                       "septiembre", "octubre", "noviembre", "diciembre"], 1)} | {"setiembre": 9}
_MON_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))

# Los lectores de nivel trabajan sobre el texto plegado (``textnorm.fold``: sin tildes, minúsculas) y toman la
# palabra del nivel con ``textnorm.lookup`` (género, número, tildes, una errata): una expresión por forma de
# escribir el nivel dejaba avisos «sin nivel» (docs/niveles-de-aviso.md).
_HIDRO_RE = re.compile(r"\(nivel\s+(\w+)\)")
#: «alerta naranja», «alertas naranjas», «alerta volcánica naranja», «Alerta volcánica: Naranja».
_VOLCAN_RE = re.compile(r"\balertas?\s*(?:volcanicas?\s*)?:?\s*(\w+)")
_PAGER_RE = re.compile(r"\balerta pager (green|yellow|orange|red)\b")
#: Titular que arma ``hazardparse`` con el campo INTENSIDAD de la capa FWI: «SENAMHI · peligro extremo de incendios…».
_FWI_RE = re.compile(r"\bpeligro\s+((?:muy\s+)?\w+)\s+de\s+incendios\b")
#: Umbral de la estación en el PDF del COEN de un aviso hidrológico («ubicándose en el umbral amarillo»), como lo
#: deja ``documentos.summary``: «Umbral de la estación según el PDF del COEN: amarillo.»
_UMBRAL_RE = re.compile(r"\bumbral de la estacion segun el pdf del coen:\s+(\w+)")
#: Un color del SENAMHI citado en el texto de un aviso («aviso naranja», «nivel rojo», «alertas amarillas»).
_TEXT_COLOR_RE = re.compile(r"\b(?:avisos?|nivel(?:es)?|alertas?)\s+(?:de\s+(?:color\s+)?)?(\w+)")

#: Vocabulario de cada escala para ``textnorm.lookup``: las claves de ``SCALES``, y las variantes que no son flexión.
_COLORS = {"verde": "verde", "amarillo": "amarillo", "naranja": "naranja", "rojo": "rojo"}
_UMBRALES = {k: k for k in ("amarillo", "naranja", "rojo")}
_FWI_WORDS = {k: k for k in ("bajo", "moderado", "alto", "muy alto", "extremo")}

# «del 22 al 24 de octubre», «del 18 y 19 de octubre», «del 31 de octubre al 2 de noviembre (del 2026)» y, en los
# boletines del COEN, «desde el jueves 22 al domingo 24 de octubre»
_DAY = r"(?:(?:lunes|martes|mi[ée]rcoles|jueves|viernes|s[áa]bado|domingo)\s+)?"
_RANGE_RE = re.compile(
    rf"\b(?:del|desde el)\s+{_DAY}(?P<d1>\d{{1,2}})(?:\s+de\s+(?P<m1>{_MON_RE}))?\s+(?:al|y)\s+{_DAY}(?P<d2>\d{{1,2}})"
    rf"\s+de\s+(?P<m2>{_MON_RE})(?:\s+del?\s+(?P<y>\d{{4}}))?", re.I)
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


def is_coen(feed_id: str) -> bool:
    """Los feeds del COEN: el de reportes de emergencias y el de sus boletines de aviso."""
    return feed_id in ("indeci-coen", "indeci-coen-boletines")


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


def _level(scale: str, key: str, basis: str, hit: Optional[Match] = None) -> dict:
    rank, label, color = SCALES[scale]["levels"][key]
    out = {"rank": rank, "label": label, "color": color, "scale": scale,
           "scaleLabel": SCALES[scale]["label"], "basis": basis}
    if hit is not None and hit.how == "aproximado":
        # Una errata («amarrillo») leída con distancia de edición 1: se publica, se dice en la ficha y la publicación
        # la registra (``alert-level-approx``) para que alguien la confirme.
        out["approx"] = hit.raw
        out["basis"] = f"{basis} (lectura aproximada de «{hit.raw}»)"
    return out


def _first(rx: re.Pattern, text: str, vocab: dict) -> Optional[Match]:
    """La primera coincidencia de ``rx`` cuya palabra está en el vocabulario («alerta de tsunami» no lo está)."""
    return next((hit for m in rx.finditer(text) if (hit := lookup(m.group(1), vocab))), None)


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


def _sev_layer(feed_id: str, title: str, summary: str) -> Optional[dict]:
    n = level_number(title)
    layer = "de precipitaciones " if feed_id == "senamhi-lluvias" else ""
    return _level("senamhi-niveles", str(n), f"campo NIVEL de la capa {layer}del SENAMHI en GEOSINPAD") if n else None


def _sev_hidro(feed_id: str, title: str, summary: str) -> Optional[dict]:
    hit = _first(_HIDRO_RE, title, _UMBRALES)
    return _level("senamhi-umbral", hit.key, "campo COLOR_TEXT del aviso hidrológico", hit) if hit else None


def _sev_fwi(feed_id: str, title: str, summary: str) -> Optional[dict]:
    # La capa da palabras (BAJO … EXTREMO), no «Nivel N» ni colores: hasta noviembre de 2026 se buscaban esos y
    # los 9 avisos de peligro extremo de los 60 días anteriores quedaron «sin nivel» (docs/niveles-de-aviso.md).
    hit = _first(_FWI_RE, title, _FWI_WORDS)
    return _level("senamhi-fwi", hit.key, "campo INTENSIDAD de la capa FWI del SENAMHI en GEOSINPAD", hit) if hit else None


def _sev_volcan(feed_id: str, title: str, summary: str) -> Optional[dict]:
    hit = _first(_VOLCAN_RE, f"{title} {summary}", _COLORS)
    return _level("igp-volcan", hit.key, "nivel de alerta del boletín del CENVUL", hit) if hit else None


def _sev_usgs(feed_id: str, title: str, summary: str) -> Optional[dict]:
    m = _PAGER_RE.search(summary)
    return _level("usgs-pager", m.group(1), "alerta PAGER publicada por USGS") if m else None


#: Nombres de instituciones que contienen «alerta de tsunamis»: el boletín los cita en cada número («organismo
#: responsable del Sistema Nacional de Alerta de Tsunamis»). Se quitan antes de buscar el estado: la regla vieja
#: solo los esquivaba porque pedía «tsunami» en singular, y aceptar el plural los volvía alertas.
_DHN_NAMES_RE = re.compile(r"\b(?:sistema|centro) nacional de alerta de tsunamis?\b|\bsnat\b|\bcnat\b")


def _sev_dhn_tsunami(feed_id: str, title: str, summary: str) -> Optional[dict]:
    low = _DHN_NAMES_RE.sub(" ", f"{title} {summary}")
    # Antes que «alerta»: «Cancelación de alerta de tsunami en el litoral peruano» se mostraba como una alerta
    # vigente (naranja) hasta noviembre de 2026.
    # «…hasta la cancelación de ALERTA de tsunamis» es parte de una alerta vigente, no su cancelación.
    if re.search(r"(?<!hasta la )\bcancelacion de (?:la )?(?:alerta|alarma) de tsunami\b", low):
        return _level("dhn-tsunami", "cancelacion", "estado del boletín de la DHN")
    if re.search(r"\balarmas? de tsunamis?\b", low):
        return _level("dhn-tsunami", "alarma", "estado del boletín de la DHN")
    if re.search(r"\balertas? de tsunamis?\b", low) and not re.search(r"no (?:genera|representa)", low):
        return _level("dhn-tsunami", "alerta", "estado del boletín de la DHN")
    if re.search(r"no (?:genera|generar[ií]a|representa)\w*\s+(?:\w+\s+){0,3}tsunami", low):
        return _level("dhn-tsunami", "info", "estado del boletín de la DHN")
    return None


def _sev_ptwc(feed_id: str, title: str, summary: str) -> Optional[dict]:
    up = f"{title} {summary}".upper()
    if "NO TSUNAMI THREAT" in up:
        return _level("ptwc", "none", "mensaje del PTWC")
    if "HAZARDOUS TSUNAMI WAVES" in up or "TSUNAMI THREAT" in up:
        return _level("ptwc", "threat", "mensaje del PTWC")
    return None


def _sev_text_color(feed_id: str, title: str, summary: str) -> Optional[dict]:
    if is_coen(feed_id) and title.startswith("aviso hidrol"):
        hit = _first(_UMBRAL_RE, summary, _UMBRALES)
        if hit:
            return _level("senamhi-umbral", hit.key, "umbral de la estación en el PDF del boletín del COEN", hit)
    hit = _first(_TEXT_COLOR_RE, f"{title} {summary}", _COLORS)
    return _level("senamhi-colores", hit.key, "color del aviso citado en su texto", hit) if hit else None


#: Lector del nivel de cada feed (por id exacto o por prefijo, en ese orden).
_SEVERITY_BY_FEED = {"senamhi-quebradas": _sev_layer, "senamhi-lluvias": _sev_layer,
                     "senamhi-hidrologicos": _sev_hidro, "senamhi-incendios": _sev_fwi, "usgs-sismos": _sev_usgs,
                     "dhn-tsunamis": _sev_dhn_tsunami, "senamhi-telegram": _sev_text_color,
                     "indeci-coen": _sev_text_color, "indeci-coen-boletines": _sev_text_color}
_SEVERITY_BY_PREFIX = (("igp-cenvul", _sev_volcan), ("ptwc", _sev_ptwc))


def _reader(feed_id: str):
    return _SEVERITY_BY_FEED.get(feed_id) or next((fn for pre, fn in _SEVERITY_BY_PREFIX if feed_id.startswith(pre)), None)


def severity(feed_id: str, title: str, summary: str) -> Optional[dict]:
    """El nivel que la institución asignó al aviso, o ``None`` si no se encontró (``level_status`` dice por qué)."""
    fn = _reader(feed_id)
    # Cada lector recibe el texto plegado (``textnorm.fold``): sin tildes ni mayúsculas, guiones y comillas en ASCII.
    return fn(feed_id, fold(title), fold(summary)) if fn else None


# ---------------------------------------------------------------------------
# Por qué un aviso no tiene nivel
# ---------------------------------------------------------------------------
#: Feeds cuya institución asigna un nivel a todo lo que publica: si no se lee, es un problema del observatorio
#: (el campo cambió de nombre o de vocabulario), nunca «la fuente no trae nivel».
LEVELED = frozenset({"senamhi-quebradas", "senamhi-lluvias", "senamhi-hidrologicos", "senamhi-incendios",
                     "igp-cenvul-boletines", "igp-cenvul-alertas", "ptwc-mensajes", "ptwc-wepa40", "dhn-tsunamis"})

#: Cada razón: etiqueta corta (la del mapa), explicación y si es un problema que abre una incidencia (``loud``).
STATUS = {
    "no-aplica": ("Reporte, sin nivel", "es un reporte de un hecho ocurrido o una detección: la institución no le "
                  "asigna nivel de aviso", False),
    "sin-escala": ("Sin escala de niveles", "la institución no asigna niveles a este tipo de aviso", False),
    "multinivel": ("Varios niveles", "el boletín reúne zonas de distintos niveles en un mapa; cada zona se ve con su "
                   "nivel en la capa del SENAMHI del mismo aviso", False),
    "no-calculado": ("Sin alerta PAGER", "USGS no publicó una alerta PAGER para este sismo; la magnitud es una medida, "
                     "no un nivel de alerta", False),
    "en-evaluacion": ("En evaluación", "la DHN informó que intensifica la vigilancia y aún no dice si el sismo genera "
                      "tsunami en el litoral peruano; el boletín siguiente lo dirá", False),
    "pendiente": ("Nivel pendiente", "el nivel está en un documento que el observatorio aún no leyó (el PDF del COEN "
                  "o la copia de la tabla de avisos del SENAMHI)", False),
    "no-leido": ("Nivel no leído", "la fuente asigna niveles pero el observatorio no pudo leer este: se abrió una "
                 "incidencia", True),
    "sin-regla": ("Nivel no revisado", "fuente de peligros sin regla de niveles: alguien debe decidir si los trae",
                  True),
}

#: La DHN aún evalúa: «se intensifica vigilancia», «se intensificará la vigilancia», «se mantendrá en constante vigilancia».
_VIGILANCIA_RE = re.compile(r"intensific\w*\s+(?:la\s+)?vigilancia|constante\s+vigilancia", re.I)
_COEN_RULES = (  # (comienzo del titular en minúsculas, razón) para lo que el COEN difunde sin nivel
    ("aviso de corto plazo", "multinivel"), ("boletín informativo de aviso de corto plazo", "multinivel"),
    ("aviso especial de oleaje", "sin-escala"), ("boletín informativo de aviso especial de oleaje", "sin-escala"),
    ("aviso hidrol", "pendiente"), ("aviso meteorol", "pendiente"))
_BY_FEED = {"dhn-avisos": "sin-escala", "usgs-sismos": "no-calculado", "firms-focos": "no-aplica"}


def _status(code: str, why: str = "", label: str = "") -> dict:
    default, text, loud = STATUS[code]
    return {"code": code, "label": label or default, "why": why or text, "loud": loud}


def _coen_reason(title: str, summary: str, kind: str) -> str:
    low = fold(title)
    code = next((c for pre, c in _COEN_RULES if low.startswith(fold(pre))), None)
    if code == "pendiente" and "segun el pdf del coen" in fold(summary):
        return "no-leido"  # el PDF se leyó y no dice el umbral (o lo dice de otra forma)
    if code:
        return code
    # Un boletín del COEN de un tipo que ninguna regla conoce: alguien debe decidir si trae nivel.
    return "no-aplica" if kind == "reporte" else "sin-regla"


def _telegram_reason(kind: str, cites_aviso: bool) -> str:
    if kind == "en-curso":
        return "sin-escala"  # «SENAMHI, en este momento…»: lo que ocurre, sin nivel propio
    return "pendiente" if cites_aviso else "sin-escala"


def level_status(feed_id: str, kind: str, title: str, summary: str, sev: Optional[dict],
                 cites_aviso: bool = False) -> Optional[dict]:
    """Por qué un aviso no tiene nivel (``None`` si lo tiene). ``loud``: la fuente sí asigna niveles y no se
    leyó (``no-leido``) o la fuente no tiene regla (``sin-regla``): la publicación abre una incidencia."""
    if sev is not None:
        return None
    if feed_id == "dhn-tsunamis" and _VIGILANCIA_RE.search(fold(f"{title} {summary}")):
        return _status("en-evaluacion")
    if feed_id in LEVELED:
        return _status("no-leido", "la fuente asigna un nivel a cada aviso y no se encontró en el titular ni en "
                                   "el resumen: el campo del nivel pudo cambiar de nombre o de vocabulario")
    if is_coen(feed_id):
        return _status(_coen_reason(title, summary, kind))
    if feed_id == "senamhi-telegram":
        return _status(_telegram_reason(kind, cites_aviso))
    code = _BY_FEED.get(feed_id)
    if code:
        return _status(code, label="Detección, sin nivel" if kind == "deteccion" else "")
    return _status("sin-regla")


def kind_of(feed_id: str, title: str) -> str:
    low = title.lower()
    if feed_id == "senamhi-telegram":
        return "en-curso" if low.startswith("senamhi, en este momento") else "pronostico"
    if is_coen(feed_id):
        # Avisos del SENAMHI que el COEN difunde (``hazardparse.parse_coen`` los titula «Aviso meteorológico N° …
        # del SENAMHI»): el meteorológico es un pronóstico; el hidrológico, el estado de un río.
        if re.match(r"aviso (meteorol|hidrol)\w+ n° \d+ del senamhi", low):
            return "pronostico" if low.startswith("aviso meteorol") else "en-curso"
        if re.match(r"aviso (especial de oleaje|de corto plazo)\b", low):
            return "pronostico"  # boletines de oleaje (DHN) y de corto plazo (SENAMHI) del COEN
        return "pronostico" if "aviso" in low and ("boletín" in low or "boletin" in low) else "reporte"
    if feed_id in ("senamhi-quebradas", "senamhi-lluvias", "senamhi-incendios", "dhn-avisos") or feed_id.startswith("ptwc"):
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
    if feed_id in ("senamhi-quebradas", "senamhi-lluvias") or (feed_id == "senamhi-incendios" and "24 horas" in text):
        return {"from": _iso(ref), "until": _iso(ref + timedelta(hours=24)),
                "basis": "aviso para las 24 horas siguientes a su emisión"}
    if feed_id in ("senamhi-telegram", "dhn-avisos") or (is_coen(feed_id) and kind_of(feed_id, title) == "pronostico"):
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
    if not is_coen(feed_id):
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


def _table_level(aviso, kind: str) -> dict:
    cites = " que cita" if kind != "pronostico" else ""  # «en este momento…, según el aviso vigente»
    # De dónde sale el nivel: el aviso en el sitio del SENAMHI (``basisArchive``, la copia de la tabla en el
    # archivo del sitio, la agrega la publicación: esa página solo responde desde el Perú).
    return {**_level("senamhi-colores", aviso.level,
                     f"nivel del aviso N° {aviso.num}{cites} en la tabla de avisos del SENAMHI"),
            "basisUrl": aviso.url}


def _table_validity(aviso) -> Optional[dict]:
    """Inicio y fin del aviso en la tabla del SENAMHI: días completos en Lima (la tabla no da la hora)."""
    a, b = _local(aviso.start.year, aviso.start.month, aviso.start.day), \
        _local(aviso.end.year, aviso.end.month, aviso.end.day)
    if not a or not b or b < a:
        return None
    return {"from": _iso(a), "until": _iso(b + timedelta(days=1) - timedelta(minutes=1)),
            "basis": f"inicio y fin del aviso N° {aviso.num} en la tabla de avisos del SENAMHI", "source": "tabla"}


def _status_field(feed_id: str, kind: str, title: str, summary: str, sev: Optional[dict]) -> dict:
    """``{"levelStatus": …}`` si el aviso no tiene nivel. Un aviso de Telegram que empieza «Aviso del SENAMHI» es
    uno de la tabla de avisos: sin nivel, está pendiente de ella."""
    st = level_status(feed_id, kind, title, summary, sev,
                      cites_aviso=feed_id == "senamhi-telegram" and title.startswith("Aviso del SENAMHI"))
    return {"levelStatus": st} if st else {}


def assess(feed_id: str, title: str, summary: str, published: Optional[str], now: datetime,
           avisos=None) -> dict:
    """Todo lo que el mapa necesita de un aviso, leído de su fuente.

    ``avisos`` (``senamhi_avisos.Table``): la tabla de avisos meteorológicos del SENAMHI. Un mensaje de
    Telegram o un boletín del COEN que cita uno de sus avisos toma el nivel de la tabla y, si su texto no
    da fechas, su inicio y su fin (``valid.source == "tabla"``; solo si la entrada es el aviso mismo y no un
    mensaje de «en este momento» que lo cita)."""
    kind = kind_of(feed_id, title)
    valid = validity(feed_id, title, summary, published)
    aviso = avisos.find(feed_id, title, summary, published, valid) if avisos is not None else None
    if aviso is not None and valid is None and kind == "pronostico":
        valid = _table_validity(aviso)
    sev = _table_level(aviso, kind) if aviso is not None else severity(feed_id, title, summary)
    out = {"kind": kind, "severity": sev, "valid": valid, "phaseAtPublication": phase(kind, valid, published, now, feed_id)}
    out.update(_status_field(feed_id, kind, title, summary, sev))
    if aviso is not None:
        out["aviso"] = {"num": aviso.num, "year": aviso.year, "url": aviso.url, "cancelled": aviso.cancelled}
    occ = occurred(feed_id, summary)
    if occ:
        out["occurred"] = occ
    if kind in ("en-curso", "deteccion") and feed_id in CURRENT_HOURS:
        out["currentHours"] = CURRENT_HOURS[feed_id]
    return out
