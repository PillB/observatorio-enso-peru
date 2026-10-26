"""Tabla de avisos meteorológicos del SENAMHI: número, fechas y nivel de cada aviso.

Los avisos meteorológicos llegan al sitio por el canal de Telegram del SENAMHI y por el COEN del INDECI,
sin su nivel. La tabla de ``?p=aviso-meteorologico`` lo tiene (columna «Nivel»: AMARILLO, NARANJA o
ROJO, en ``<span class="dos|tres|cuatro">``), con la emisión, el inicio y el fin de cada aviso desde
2021. La página solo responde desde el Perú: el recolector la guarda cada noche en la rama
``data-peru`` y aquí se lee de esa copia (``from_relay``). Un aviso emitido después de la última copia
queda sin nivel hasta la copia siguiente; nunca se le pone uno que la tabla no tenga.

Cada aviso se identifica de dos maneras:

* ``id``: el número interno del enlace de la tabla (``b=29296``), el mismo que cita el mensaje de
  Telegram (``observatorio.senamhi.gob.pe/…/avisos-meteorologicos/29296``, que ``hazardparse``
  resume como «aviso meteorológico 29296»).
* ``num`` y el año: el «Nro.» del aviso (429), que vuelve a 1 cada año y es el que cita el COEN.

Un mensaje de Telegram sin enlace se reconoce solo si una única fila tiene las mismas fechas de inicio
y fin y todas las palabras de su título.

Que falte la tabla no se calla (``load`` dice por qué y ``sourcefeed.levels_table`` lo registra), y la
copia usada se publica en el archivo del sitio: cada nivel enlaza el aviso en el sitio del SENAMHI y esa
copia, porque la página solo responde desde el Perú.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

URL = "https://www.senamhi.gob.pe/?p=aviso-meteorologico"
#: Una tabla más vieja que esto se avisa: los avisos emitidos después quedan sin nivel y una cancelación
#: posterior no se ve (la copia del Perú es diaria; el recolector conserva hasta 72 h la última buena).
STALE_HOURS = 36
#: Clase del nivel en la tabla → color (``severity.SCALES["senamhi-colores"]``).
LEVEL_CLASS = {"dos": "amarillo", "tres": "naranja", "cuatro": "rojo"}
LEVEL_NAME = {"AMARILLO": "amarillo", "NARANJA": "naranja", "ROJO": "rojo"}
DETAIL = "https://www.senamhi.gob.pe/?p=aviso-meteorologico-vigente&a={year}&b={id}&c=00&d=SENA"

_ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_LINK_RE = re.compile(r"[?&]a=(\d{4})&(?:amp;)?b=(\d+)")
_SPAN_RE = re.compile(r'<span class="(\w+)"[^>]*>\s*([A-Za-zÁÉÍÓÚáéíóú]+)')
_TG_ID_RE = re.compile(r"aviso meteorol[óo]gico (\d{3,})", re.I)
_COEN_NUM_RE = re.compile(r"^Aviso meteorol[óo]gico N° (\d+) del SENAMHI", re.I)
_STOP = {"en", "la", "el", "de", "del", "los", "las", "y", "a", "al", "e", "o"}


@dataclass(frozen=True)
class Aviso:
    id: int
    year: int
    num: int
    title: str
    issued: date
    start: date
    end: date
    level: str  # amarillo, naranja o rojo
    cancelled: bool = False

    @property
    def url(self) -> str:
        return DETAIL.format(year=self.year, id=self.id)


def _text(cell: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", cell))).strip()


def _day(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(s.strip()[:10])
    except ValueError:
        return None


def _fold(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower())


def parse(body: str | bytes) -> list[Aviso]:
    """Las filas de la tabla con nivel y fechas legibles; las demás se omiten."""
    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    out = []
    for row in _ROW_RE.findall(text):
        tds = _TD_RE.findall(row)
        if len(tds) != 7:
            continue
        link = _LINK_RE.search(tds[0]) or _LINK_RE.search(tds[1])
        num = re.match(r"\s*(\d+)", _text(tds[1]))
        span = _SPAN_RE.search(tds[6])
        level = (LEVEL_CLASS.get(span.group(1)) or LEVEL_NAME.get(span.group(2).upper())) if span else \
            LEVEL_NAME.get(_text(tds[6]).upper())
        issued, start, end = _day(_text(tds[2])), _day(_text(tds[3])), _day(_text(tds[4]))
        if not (link and num and level and issued and start and end):
            continue
        title = _text(tds[0])
        out.append(Aviso(id=int(link.group(2)), year=int(link.group(1)), num=int(num.group(1)), title=title,
                         issued=issued, start=start, end=end, level=level,
                         cancelled=bool(re.search(r"\(\s*AVISO CANCELADO\s*\)", title, re.I))))
    return out


class Table:
    """Los avisos de la tabla, por ``id`` y por año y número."""

    def __init__(self, avisos: list[Aviso], copy_at: Optional[str] = None, body: bytes = b""):
        self.avisos = avisos
        #: Cuándo bajó la página el recolector del Perú, y la página tal cual (para el archivo del sitio).
        self.copy_at = copy_at
        self.body = body
        self.by_id = {a.id: a for a in avisos}
        self.by_num: dict[tuple[int, int], list[Aviso]] = {}
        for a in avisos:
            self.by_num.setdefault((a.year, a.num), []).append(a)

    def __len__(self) -> int:
        return len(self.avisos)

    def age_hours(self, now: Optional[datetime] = None) -> Optional[float]:
        when = _when(self.copy_at)
        return None if when is None else ((now or datetime.now(timezone.utc)) - when).total_seconds() / 3600

    def find(self, feed_id: str, title: str, summary: str, published: Optional[str],
             valid: Optional[dict] = None) -> Optional[Aviso]:
        """El aviso de la tabla que cita una entrada del canal de Telegram o del COEN, o ``None``."""
        if feed_id == "senamhi-telegram":
            m = _TG_ID_RE.search(f"{title} {summary}")
            if m:
                return self.by_id.get(int(m.group(1)))
            if title.startswith("Aviso del SENAMHI") and valid and not valid.get("source"):
                return self._by_dates_and_words(title, valid)
            return None
        if feed_id in ("indeci-coen", "indeci-coen-boletines"):
            m = _COEN_NUM_RE.match(title)
            when = _when(published)
            if not m or when is None:
                return None
            # El número vuelve a 1 cada año: el aviso con ese número emitido hasta 15 días antes del reporte.
            near = [a for y in (when.year, when.year - 1) for a in self.by_num.get((y, int(m.group(1))), [])
                    if timedelta(days=-2) <= when.date() - a.issued <= timedelta(days=15)]
            return near[0] if len(near) == 1 else None
        return None

    def _by_dates_and_words(self, title: str, valid: dict) -> Optional[Aviso]:
        a, b = _when(valid.get("from")), _when(valid.get("until"))
        if a is None or b is None:
            return None
        lima = timezone(timedelta(hours=-5))
        start, end = a.astimezone(lima).date(), b.astimezone(lima).date()
        text = f" {_fold(title)}"
        hits = []
        for av in self.avisos:
            if av.start != start or av.end != end:
                continue
            words = [w for w in _fold(re.sub(r"\(.*?\)", " ", av.title)).split() if w not in _STOP]
            # «incremento» e «incrementará», «nevada» y «nevadas»: basta el comienzo de cada palabra.
            if words and all(f" {w[:6]}" in text for w in words):
                hits.append(av)
        return hits[0] if len(hits) == 1 else None


def _when(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def load(relay) -> tuple[Optional[Table], str]:
    """La tabla de la última copia del recolector del Perú y, si no hay tabla que usar, por qué («» sin copia
    del Perú: de eso ya avisa ``observatory.load_relay``)."""
    if relay is None:
        return None, ""
    try:
        r = relay.get(URL)
    except Exception as exc:  # noqa: BLE001 — sin tabla, los avisos quedan con lo que diga su texto
        return None, f"no se pudo leer la copia ({type(exc).__name__}: {exc})"[:200]
    if r is None:
        return None, "la copia del Perú no la trae (no respondió, pidió verificación o tiene más de 7 días)"
    try:
        avisos = parse(r.body)
    except Exception as exc:  # noqa: BLE001
        return None, f"no se pudo leer la página ({type(exc).__name__})"
    if not avisos:
        return None, ("la página no trae filas de avisos legibles: puede haber cambiado de formato o haber "
                      "respondido una página de mantenimiento")
    return Table(avisos, getattr(r, "archived_at", None), r.body), ""


def from_relay(relay) -> Optional[Table]:
    """La tabla de la última copia del recolector del Perú, o ``None`` si no hay copia legible."""
    return load(relay)[0]


# ---------------------------------------------------------------------------
# Regiones que nombran los avisos («costa norte y sierra», «selva centro y sur»)
# ---------------------------------------------------------------------------
#: Departamentos de cada región en que el SENAMHI divide sus avisos. Es una aproximación: el aviso no dice en
#: qué departamentos de la región, y un departamento andino está en la costa, la sierra y a veces la selva.
#: Solo se usa si no hay nada mejor (el PDF del COEN con los departamentos expuestos, ``documentos``), y el
#: mapa lo marca «≈» (confianza ``REGION_CONFIDENCE``). Validado con los departamentos expuestos de los avisos
#: 432, 435 y 440 de 2026 (``tests/test_documentos.py``).
REGIONS = {
    ("costa", "norte"): ("Tumbes", "Piura", "Lambayeque", "La Libertad"),
    ("costa", "centro"): ("Áncash", "Lima", "Callao", "Ica"),
    ("costa", "sur"): ("Arequipa", "Moquegua", "Tacna"),
    ("sierra", "norte"): ("Piura", "Lambayeque", "Cajamarca", "La Libertad", "Amazonas"),
    ("sierra", "centro"): ("Áncash", "Huánuco", "Pasco", "Junín", "Lima", "Huancavelica"),
    ("sierra", "sur"): ("Ayacucho", "Apurímac", "Cusco", "Arequipa", "Moquegua", "Tacna", "Puno"),
    ("selva", "norte"): ("Amazonas", "Loreto", "San Martín", "Cajamarca"),
    ("selva", "centro"): ("Huánuco", "Pasco", "Junín", "Ucayali"),
    ("selva", "sur"): ("Cusco", "Madre de Dios", "Puno"),
}
REGION_CONFIDENCE = 0.6
_ZONE = {"costa": "costa", "litoral": "costa", "sierra": "sierra", "andes": "sierra", "altoandina": "sierra",
         "altoandinas": "sierra", "selva": "selva", "amazonia": "selva", "amazonica": "selva"}
_PART = {"norte": "norte", "centro": "centro", "sur": "sur", "nororiental": "norte", "central": "centro"}
_GLUE = {"y", "e", "la", "el", "los", "las", "del", "de", "zonas", "zona", ","}


def regions_named(text: str) -> list[tuple[str, str]]:
    """Las regiones que nombra el texto de un aviso. «costa y sierra norte y centro» → costa y sierra, norte y
    centro; «costa norte y sierra» → costa norte y toda la sierra."""
    words = re.findall(r"[a-z]+|,", _fold(text).replace(",", " , "))
    out: list[tuple[str, str]] = []
    pending: list[str] = []
    parts: list[str] = []

    def close():
        for z in pending:
            for p in parts or ["norte", "centro", "sur"]:
                if (z, p) not in out:
                    out.append((z, p))

    run = False
    for w in words:
        if w in _ZONE:
            if parts:  # «costa norte y sierra»: la costa ya tiene sus partes
                close()
                pending, parts = [], []
            pending.append(_ZONE[w])
            run = True
        elif w in _PART and run:
            parts.append(_PART[w])
        elif w in _GLUE and run:
            continue
        elif run:
            close()
            pending, parts, run = [], [], False
    close()
    return out


def region_departments(text: str) -> tuple[list[str], str]:
    """Nombres de los departamentos de las regiones que nombra el texto, y la frase que las nombra."""
    regions = regions_named(text)
    names = list(dict.fromkeys(d for r in regions for d in REGIONS.get(r, ())))
    m = re.search(r"\b(?:en (?:la|el|los|las) )?(?:costa|sierra|selva|litoral|zonas altoandinas|andes)\b[^.;:()]{0,60}", text, re.I)
    return names, (m.group(0).strip() if m else "")
