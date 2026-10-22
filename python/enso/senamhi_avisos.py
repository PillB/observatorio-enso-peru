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
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

URL = "https://www.senamhi.gob.pe/?p=aviso-meteorologico"
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

    def __init__(self, avisos: list[Aviso], copy_at: Optional[str] = None):
        self.avisos = avisos
        self.copy_at = copy_at
        self.by_id = {a.id: a for a in avisos}
        self.by_num: dict[tuple[int, int], list[Aviso]] = {}
        for a in avisos:
            self.by_num.setdefault((a.year, a.num), []).append(a)

    def __len__(self) -> int:
        return len(self.avisos)

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
        if feed_id == "indeci-coen":
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


def from_relay(relay) -> Optional[Table]:
    """La tabla de la última copia del recolector del Perú, o ``None`` si no hay copia legible."""
    if relay is None:
        return None
    try:
        r = relay.get(URL)
        avisos = parse(r.body) if r is not None else []
    except Exception:  # noqa: BLE001 — sin tabla, los avisos quedan con lo que diga su texto
        return None
    return Table(avisos, getattr(r, "archived_at", None)) if avisos else None
