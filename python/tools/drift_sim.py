"""Simulador de deriva de las fuentes: aplica a las copias reales de ``tests/fixtures/sources`` los cambios que una
fuente puede hacer sin avisar (columnas corridas, otra unidad, otro centinela, coma decimal, fechas en otro idioma,
archivo truncado, otra codificación, una página de verificación con HTTP 200, un feed vacío pero válido, RSS que pasa
a Atom, claves de JSON renombradas, una capa de ArcGIS renumerada…) y clasifica lo que hace el lector del sitio con
cada una, por el mismo camino que la corrida diaria:

* **LOUD**: alguien se entera. En las fuentes de ``observatory.SOURCES``, una incidencia que abre issue
  (``tools.sync_issues.relevant``: aviso o más, no ``info``) en ``observatory.acquire`` —que corre el lector, la
  validación de rangos, la huella del formato (``format-drift``) y la guardia de regresión (``enso.drift``) contra la
  lectura sin cambios como publicación anterior—, o una página de verificación que ``fetch.block_page`` descarta. En
  los feeds (``news._read_feed``), el feed queda caído o ilegible (``ok`` falso, ``formatError``, entradas sin fecha:
  lo que ``persistent.feed_state`` cuenta como degradado).
* **BENIGN**: lo publicado es idéntico a lo de la copia sin cambios (el lector lo normalizó).
* **SILENT-WRONG**: lo publicado cambia (valores, fechas, número de entradas) y nada avisa. Es lo que hay que evitar.
* **NOISY**: un cambio que no altera el contenido (CRLF, BOM, otra codificación declarada…) y aun así avisa: no publica
  nada malo, pero es una falsa alarma o una fuente perdida sin necesidad.
* **N/A**: la mutación no se aplica a esa copia (no tiene centinelas, ni caracteres fuera de ASCII…).

Lo que una mutación «debería» producir no se declara a mano: la verdad independiente es la lectura de la copia sin
cambios. Si la mutación conserva el contenido (``preserving``), lo correcto es leer exactamente lo mismo; si lo
corrompe, lo correcto es avisar. En los dos casos, publicar otra cosa sin aviso es SILENT-WRONG.

Uso (desde python/):
    python -m tools.drift_sim                     # informe; fuentes y un feed por familia de formato
    python -m tools.drift_sim --all-feeds         # todos los feeds con copia (≈3 min)
    python -m tools.drift_sim --target cpc-oni --mutation col-swap --show
    python -m tools.drift_sim --json salida.json

Sale con 0 si no hay SILENT-WRONG fuera de la lista revisada (``ALLOWLIST``), 1 si hay alguno y 2 si no pudo simular
(una copia que falta, un lector que ya falla sin mutar). La prueba ``tests/test_drift_sim.py`` corre lo mismo.
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import io
import json
import re
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enso import news as N  # noqa: E402
from enso import observatory as O  # noqa: E402
from enso import persistent as P  # noqa: E402
from enso.fetch import block_page  # noqa: E402
from tools.sync_issues import IGNORE  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "sources"
#: Página real de Imunify360 que trece feeds en WordPress dieron con HTTP 200 (noviembre de 2026).
CHALLENGE = FIXTURES / "blocked" / "imunify360-soltv-piura-20261119.html"
#: Página HTML real (portada) servida donde se esperaba un feed o un archivo de datos.
HOMEPAGE = FIXTURES / "indeci-home.html"
#: Listado real del MapServer del SENAMHI en GEOSINPAD (``news.check_layer`` lo pide cuando una capa llega vacía).
MAPSERVER = FIXTURES / "geosinpad-senamhi-mapserver.json"
#: Hora fija de la simulación: posterior a todas las copias (los feeds descartan fechas futuras).
NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)

LOUD, BENIGN, SILENT, NOISY, NA = "LOUD", "BENIGN", "SILENT-WRONG", "NOISY", "N/A"
LIMA = timezone(timedelta(hours=-5))


# ---------------------------------------------------------------------------
# Mutaciones
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Mutation:
    name: str
    families: frozenset
    apply: Callable[[bytes, dict], Optional[bytes]]
    #: Mismo contenido con otra forma: lo correcto es leer exactamente lo mismo (si avisa, es NOISY).
    preserving: bool
    what: str


MUTATIONS: dict[str, Mutation] = {}
ANY = frozenset({"table", "xml", "html", "json", "csv", "text", "internal"})


def mutation(name: str, families: Iterable[str], preserving: bool, what: str):
    def deco(fn):
        MUTATIONS[name] = Mutation(name, frozenset(families), fn, preserving, what)
        return fn
    return deco


def _text(body: bytes) -> str:
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("latin-1")


def _same_or_none(new: bytes, old: bytes) -> Optional[bytes]:
    return None if new == old else new


def _text_op(fn: Callable[[str], str]) -> Callable[[bytes, dict], Optional[bytes]]:
    """Mutación de texto: decodifica, transforma y vuelve a UTF-8 (``None`` si no cambió nada)."""
    def run(body: bytes, ctx: dict) -> Optional[bytes]:
        return _same_or_none(fn(_text(body)).encode("utf-8"), body)
    return run


# --- Bytes, codificación y transporte (todas las familias) ------------------------------------------------------
@mutation("crlf", ANY, True, "fin de línea Windows (CRLF)")
def _crlf(body, ctx):
    return _same_or_none(body.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"), body)


@mutation("bom", ANY, True, "marca de orden de bytes UTF-8 al principio")
def _bom(body, ctx):
    return b"\xef\xbb\xbf" + body if not body.startswith(b"\xef\xbb\xbf") else None


@mutation("latin1", ANY, True, "el servidor pasa a Latin-1 (sin cambiar la declaración del documento)")
def _latin1(body, ctx):
    t = _text(body)
    if t.isascii() or re.search("[ÃÂ][\u0080-\u00bf]", t):
        # Una copia que ya trae texto doblemente codificado («alcanzÃ³»): pasarla a windows-1252 lo «arregla» (C3 B3
        # es «ó» en UTF-8) y no conserva el contenido; la mutación no se aplica.
        return None
    try:
        return t.encode("cp1252")
    except UnicodeEncodeError:
        # Sin pérdida: lo que windows-1252 no tiene va como referencia numérica (lo que hace un servidor que
        # re-codifica HTML o XML); en una tabla de texto no hay cómo, y la mutación no se aplica.
        return t.encode("cp1252", errors="xmlcharrefreplace") if ctx["family"] in ("xml", "html") else None


@mutation("utf16", ANY, True, "el servidor pasa a UTF-16 con BOM")
def _utf16(body, ctx):
    return _text(body).encode("utf-16")


@mutation("gzip", ANY, True, "cuerpo comprimido dos veces (gzip sin Content-Encoding)")
def _gzip(body, ctx):
    return gzip.compress(body, mtime=0)


@mutation("challenge", ANY, False, "página de verificación antirobots (Imunify360) con HTTP 200")
def _challenge(body, ctx):
    return CHALLENGE.read_bytes()


@mutation("homepage", ANY, False, "portada HTML del sitio en lugar del archivo (redirección a la portada)")
def _homepage(body, ctx):
    return HOMEPAGE.read_bytes()


@mutation("empty", ANY, False, "respuesta vacía con HTTP 200")
def _empty(body, ctx):
    return b""


@mutation("truncate", ANY, False, "descarga cortada a la mitad (en medio de una línea)")
def _truncate(body, ctx):
    return body[: len(body) * 6 // 10]


@mutation("trailing-ws", frozenset({"table", "csv", "text", "xml", "html"}), True, "espacios al final de cada línea")
def _trailing_ws(body, ctx):
    return _same_or_none(re.sub(rb"\r?\n", b"   \n", body), body)


# --- Tablas de texto (CPC, PSL, IGP) ----------------------------------------------------------------------------
SEASONS = "DJF|JFM|FMA|MAM|AMJ|MJJ|JJA|JAS|ASO|SON|OND|NDJ"
#: Cabeza de una fila de datos: «AAAA [mes]», «DDMONAAAA» (semanal) o «TEMPORADA AAAA» (ONI/RONI).
LEAD_RE = re.compile(rf"^(\s*(?:\d{{1,2}}[A-Za-z]{{3}}\d{{4}}|(?:{SEASONS})\s+\d{{4}}|\d{{4}}(?:\s+\d{{1,2}}(?=\s))?))(.*)$")
FLOAT_RE = re.compile(r"-?\d*\.\d+")
HEADER_RE = re.compile(r"^\s*(?:YR|YEAR|SEAS|Week|%\s*yy)\b", re.I)


def _rows(text: str) -> tuple[list[str], list[int]]:
    """Líneas (con su fin de línea) e índices de las filas de datos (cabeza + algún número decimal)."""
    lines = text.splitlines(keepends=True)
    idx = [i for i, l in enumerate(lines) if (m := LEAD_RE.match(l.rstrip("\r\n"))) and FLOAT_RE.search(m.group(2))]
    return lines, idx


def _split(line: str) -> tuple[str, list[str], str]:
    eol = line[len(line.rstrip("\r\n")):]
    m = LEAD_RE.match(line.rstrip("\r\n"))
    return m.group(1), FLOAT_RE.findall(m.group(2)), eol


def _join(lead: str, toks: list[str], eol: str) -> str:
    return lead + "".join(f"{t:>8}" for t in toks) + eol


def _map_rows(text: str, fn: Callable[[str, list[str], str], Optional[str]]) -> str:
    lines, idx = _rows(text)
    for i in idx:
        new = fn(*_split(lines[i]))
        if new is not None:
            lines[i] = new
    return "".join(lines)


def _sentinel(tok: str) -> bool:
    return float(tok) <= -99


def _decimals(tok: str) -> int:
    return len(tok.split(".")[1]) if "." in tok else 0


def _scaled(k: float, add: float = 0.0):
    def row(lead, toks, eol):
        return _join(lead, [t if _sentinel(t) else f"{float(t) * k + add:.{_decimals(t)}f}" for t in toks], eol)
    return _text_op(lambda t: _map_rows(t, row))


mutation("scale-x10", {"table"}, False, "valores ×10 (décimas en lugar de unidades)")(_scaled(10))
mutation("scale-div10", {"table"}, False, "valores ÷10")(_scaled(0.1))
mutation("unit-F-anom", {"table"}, False, "anomalías en °F (×1,8) sin cambiar la cabecera")(_scaled(1.8))
mutation("unit-F-abs", {"table"}, False, "valores en °F (×1,8 + 32) sin cambiar la cabecera")(_scaled(1.8, 32))


def _sentinel_to(new: str):
    def row(lead, toks, eol):
        if not any(_sentinel(t) for t in toks):
            return None
        return lead + "".join(f"{(new if _sentinel(t) else t):>8}" for t in toks) + eol
    return _text_op(lambda t: _map_rows(t, row))


mutation("sentinel-999", {"table"}, False, "centinela de dato faltante -99.99 → -999")(_sentinel_to("-999"))
mutation("sentinel-nan", {"table"}, False, "centinela de dato faltante → NaN")(_sentinel_to("NaN"))
mutation("sentinel-blank", {"table"}, False, "dato faltante en blanco (la fila queda más corta)")(_sentinel_to(""))


@mutation("decimal-comma", {"table", "csv"}, False, "coma decimal (configuración regional)")
def _decimal_comma(body, ctx):
    if ctx["family"] == "csv":
        return _csv_op(body, lambda rows: [rows[0]] + [[c.replace(".", ",") if re.fullmatch(r"-?\d+\.\d+", c) else c
                                                         for c in r] for r in rows[1:]], delim=";")
    return _text_op(lambda t: _map_rows(t, lambda lead, toks, eol: _join(lead, [x.replace(".", ",") for x in toks], eol)))(body, ctx)


@mutation("col-swap", {"table"}, False, "dos columnas de valores intercambiadas sin cambiar la cabecera")
def _col_swap(body, ctx):
    def row(lead, toks, eol):
        if len(toks) < 2:
            return None
        t = list(toks)
        if len(t) >= 4:
            t[0:2], t[-2:] = t[-2:], t[0:2]
        else:
            t[0], t[1] = t[1], t[0]
        return _join(lead, t, eol)
    return _text_op(lambda t: _map_rows(t, row))(body, ctx)


@mutation("col-missing", {"table"}, False, "falta la primera columna de valores (la cabecera no cambia)")
def _col_missing(body, ctx):
    return _text_op(lambda t: _map_rows(t, lambda lead, toks, eol: _join(lead, toks[1:], eol) if len(toks) > 1 else None))(body, ctx)


@mutation("col-extra", {"table"}, False, "columna nueva al final (también en la cabecera)")
def _col_extra(body, ctx):
    def fn(text):
        text = _map_rows(text, lambda lead, toks, eol: _join(lead, toks + ["0.00"], eol))
        return "".join(l.rstrip("\r\n") + "   EXTRA" + l[len(l.rstrip("\r\n")):] if HEADER_RE.match(l) else l
                       for l in text.splitlines(keepends=True))
    return _text_op(fn)(body, ctx)


@mutation("header-lower", {"table"}, True, "cabecera en minúsculas")
def _header_lower(body, ctx):
    return _text_op(lambda t: "".join(l.lower() if HEADER_RE.match(l) else l for l in t.splitlines(keepends=True)))(body, ctx)


@mutation("header-rename", {"table"}, False, "columna «ANOM» renombrada «SSTA»")
def _header_rename(body, ctx):
    return _text_op(lambda t: "".join(re.sub(r"\bANOM\b", "SSTA", l) if HEADER_RE.match(l) else l
                                      for l in t.splitlines(keepends=True)))(body, ctx)


@mutation("header-reorder", {"table"}, True, "columnas reordenadas, cabecera y datos a la vez")
def _header_reorder(body, ctx):
    text = _text(body)
    lines, idx = _rows(text)
    heads = [i for i, l in enumerate(lines) if HEADER_RE.match(l)]
    if not idx or not heads:
        return None
    lead, toks, _ = _split(lines[idx[0]])
    h = lines[heads[-1]].split()
    keys = len(lead.split())
    if len(h) != keys + len(toks) or len(toks) < 2:
        return None
    width = _swap_width(toks)

    def swap(seq):
        s = list(seq)
        s[:width], s[-width:] = s[-width:], s[:width]
        return s
    eol = lines[heads[-1]][len(lines[heads[-1]].rstrip("\r\n")):]
    lines[heads[-1]] = " ".join(h[:keys] + swap(h[keys:])) + eol
    _swap_region_names(lines, heads[-1], width, len(toks))
    _swap_data_rows(lines, idx, len(h) - keys, swap)
    return _same_or_none("".join(lines).encode("utf-8"), body)


def _swap_width(toks: list[str]) -> int:
    """Cuántas columnas se intercambian: de a dos si los datos van en pares (valor y anomalía), si no de a una."""
    return 2 if len(toks) >= 4 and len(toks) % 2 == 0 else 1


def _swap_region_names(lines: list[str], head: int, width: int, ntoks: int) -> None:
    """Mueve con sus columnas los nombres de las regiones que van en la línea de arriba de la cabecera."""
    above = next((i for i in range(head - 1, -1, -1) if lines[i].strip()), None)
    names = lines[above].split() if above is not None else []
    if width == 2 and len(names) * 2 == ntoks:
        # Los nombres de las regiones van en otra línea («Nino1+2 Nino3 Nino34 Nino4»): se mueven con sus columnas.
        names[0], names[-1] = names[-1], names[0]
        lines[above] = "        " + "      ".join(names) + "\n"


def _swap_data_rows(lines: list[str], idx: list[int], ncols: int, swap: Callable[[list[str]], list[str]]) -> None:
    """Reordena las columnas de cada fila de datos que tiene tantas columnas como la cabecera."""
    for i in idx:
        lead, toks, eol = _split(lines[i])
        if len(toks) == ncols:
            lines[i] = _join(lead, swap(toks), eol)


def _row_op(fn: Callable[[list[str], list[int]], Optional[list[str]]]):
    def run(body, ctx):
        lines, idx = _rows(_text(body))
        if len(idx) < 4:
            return None
        out = fn(lines, idx)
        return None if out is None else _same_or_none("".join(out).encode("utf-8"), body)
    return run


def _reverse(lines, idx):
    rows = [lines[i] for i in idx]
    out = list(lines)
    for i, r in zip(idx, reversed(rows)):
        out[i] = r
    return out


def _dup(lines, idx):
    k = idx[len(idx) // 2]
    return lines[:k + 1] + [lines[k]] + lines[k + 1:]


def _drop_last(lines, idx):
    # Las tres últimas filas con algún dato (las de años futuros solo tienen centinelas: quitarlas no cambia nada).
    real = [i for i in idx if any(not _sentinel(t) for t in _split(lines[i])[1])]
    drop = set(real[-3:])
    return [l for i, l in enumerate(lines) if i not in drop]


def _drop_first(lines, idx):
    drop = set(idx[: len(idx) * 3 // 10])
    return [l for i, l in enumerate(lines) if i not in drop]


def _header_only(lines, idx):
    drop = set(idx)
    return [l for i, l in enumerate(lines) if i not in drop]


def _blank_lines(lines, idx):
    rows = set(idx)
    return [l + ("\n" if i in rows else "") for i, l in enumerate(lines)]


mutation("rows-reversed", {"table"}, True, "filas en orden inverso (lo más nuevo arriba)")(_row_op(_reverse))
mutation("row-duplicated", {"table"}, False, "una fila repetida")(_row_op(_dup))
mutation("rows-drop-last", {"table"}, False, "faltan las tres últimas filas (espejo o copia atrasada)")(_row_op(_drop_last))
mutation("rows-drop-first", {"table"}, False, "falta el primer 30 % de la historia")(_row_op(_drop_first))
mutation("header-only", {"table"}, False, "archivo válido sin filas de datos")(_row_op(_header_only))
mutation("blank-lines", {"table"}, True, "línea en blanco entre filas")(_row_op(_blank_lines))


@mutation("tabs", {"table"}, True, "tabuladores en lugar de espacios")
def _tabs(body, ctx):
    return _text_op(lambda t: _map_rows(t, lambda lead, toks, eol: "\t".join(lead.split() + toks) + eol))(body, ctx)


@mutation("html-pre", {"table", "text"}, True, "el archivo llega envuelto en <html><pre>")
def _html_pre(body, ctx):
    return b"<html><head><title>data</title></head><body><pre>\n" + body + b"\n</pre></body></html>\n"


MON_EN_ES = {"JAN": "ENE", "APR": "ABR", "AUG": "AGO", "DEC": "DIC"}


@mutation("dates-es", {"table"}, False, "meses de la fecha semanal en castellano (02ENE2026)")
def _dates_es(body, ctx):
    return _text_op(lambda t: re.sub(r"(?m)^(\s*\d{1,2})(JAN|APR|AUG|DEC)(\d{4})",
                                     lambda m: m.group(1) + MON_EN_ES[m.group(2)] + m.group(3), t))(body, ctx)


@mutation("dates-iso", {"table"}, False, "fecha semanal en ISO 8601 (2026-01-07)")
def _dates_iso(body, ctx):
    def iso(m):
        d = datetime.strptime(m.group(2).title(), "%d%b%Y")
        return m.group(1) + d.strftime("%Y-%m-%d")
    return _text_op(lambda t: re.sub(r"(?m)^(\s*)(\d{1,2}[A-Za-z]{3}\d{4})", iso, t))(body, ctx)


SEASON_ES = {"DJF": "DEF", "JFM": "EFM", "NDJ": "NDE"}


@mutation("seasons-es", {"table"}, False, "temporadas en castellano (DEF, EFM, NDE)")
def _seasons_es(body, ctx):
    return _text_op(lambda t: re.sub(r"(?m)^(\s*)(DJF|JFM|NDJ)\b", lambda m: m.group(1) + SEASON_ES[m.group(2)], t))(body, ctx)


# --- Feeds XML ---------------------------------------------------------------------------------------------------
DATE_TAG_RE = re.compile(r"(<(pubDate|dc:date|published|updated|lastBuildDate)\b[^>]*>)\s*(.*?)\s*(</\2\s*>)", re.S)
DAYS_ES = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MONTHS_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def _read_date(raw: str) -> Optional[datetime]:
    raw = raw.strip()
    if raw.startswith("<![CDATA["):
        raw = raw[9:-3].strip()
    try:
        d = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        try:
            d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d and d.tzinfo else None  # sin zona no se sabe qué instante es: la mutación no se aplica


def _date_op(render: Callable[[datetime, dict], str], tags: tuple = ("pubDate", "dc:date", "published", "updated")):
    def run(body, ctx):
        text, hits = _text(body), [0]

        def sub(m):
            d = _read_date(m.group(3))
            if m.group(2) not in tags or d is None:
                return m.group(0)
            hits[0] += 1
            return m.group(1) + render(d, ctx) + m.group(4)
        out = DATE_TAG_RE.sub(sub, text)
        return _same_or_none(out.encode("utf-8"), body) if hits[0] else None
    return run


def _local_tz(ctx: dict) -> timezone:
    return LIMA if ctx.get("region") == "peru" else timezone.utc


mutation("date-es", {"xml"}, True, "fechas RFC 822 en castellano («vie, 20 nov 2026 10:00:00 -0500»)")(
    _date_op(lambda d, c: f"{DAYS_ES[d.weekday()]}, {d.day:02d} {MONTHS_ES[d.month - 1]} {d.year} "
                          f"{d:%H:%M:%S} {d:%z}"))
mutation("date-iso", {"xml"}, True, "fechas en ISO 8601 con zona")(_date_op(lambda d, c: d.isoformat()))
mutation("date-utc", {"xml"}, True, "el mismo instante en UTC («…Z»)")(
    _date_op(lambda d, c: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
mutation("date-gmt", {"xml"}, True, "el mismo instante en RFC 822 «GMT»")(
    _date_op(lambda d, c: format_datetime(d.astimezone(timezone.utc), usegmt=True)))
mutation("date-naive", {"xml"}, True, "fechas sin zona, en la hora local del medio")(
    _date_op(lambda d, c: d.astimezone(_local_tz(c)).strftime("%Y-%m-%d %H:%M:%S")))
mutation("date-epoch", {"xml"}, True, "fechas en segundos Unix")(_date_op(lambda d, c: str(int(d.timestamp()))))


def _items(text: str) -> list[re.Match]:
    return list(re.finditer(r"<(item|entry)\b[^>]*>.*?</\1\s*>\s*", text, re.S))


def _items_op(fn: Callable[[list[str]], list[str]]):
    def run(body, ctx):
        text = _text(body)
        its = _items(text)
        if len(its) < 2:
            return None
        start, end = its[0].start(), its[-1].end()
        return _same_or_none((text[:start] + "".join(fn([m.group(0) for m in its])) + text[end:]).encode("utf-8"), body)
    return run


mutation("items-reversed", {"xml"}, True, "entradas en orden inverso")(_items_op(lambda xs: xs[::-1]))
mutation("item-duplicated", {"xml"}, True, "una entrada repetida")(_items_op(lambda xs: xs[:1] + xs))
mutation("items-none", {"xml"}, False, "feed válido sin entradas")(_items_op(lambda xs: []))


@mutation("title-cdata", {"xml"}, True, "títulos envueltos en CDATA")
def _title_cdata(body, ctx):
    text = _text(body)

    def sub(m):
        inner = m.group(2)
        if inner.lstrip().startswith("<![CDATA[") or "]]>" in inner:
            return m.group(0)
        import html as H
        return f"{m.group(1)}<![CDATA[{H.unescape(inner)}]]>{m.group(3)}"
    return _same_or_none(re.sub(r"(<title\b[^>]*>)(.*?)(</title>)", sub, text, flags=re.S).encode("utf-8"), body)


@mutation("latin1-declared", {"xml"}, True, "Latin-1 con la declaración XML correcta (encoding=\"ISO-8859-1\")")
def _latin1_declared(body, ctx):
    t = _text(body)
    if t.isascii():
        return None
    t = re.sub(r"^﻿?\s*<\?xml[^>]*\?>", "", t)
    return ('<?xml version="1.0" encoding="ISO-8859-1"?>' + t).encode("latin-1", errors="xmlcharrefreplace")


@mutation("pubdate-to-dcdate", {"xml"}, True, "<pubDate> pasa a <dc:date> en ISO 8601")
def _pubdate_dc(body, ctx):
    text = _text(body)
    if "<pubDate" not in text or "<rss" not in text:
        return None

    def sub(m):
        d = _read_date(m.group(1))
        return m.group(0) if d is None else f"<dc:date>{d.isoformat()}</dc:date>"
    out = re.sub(r"<pubDate>\s*(.*?)\s*</pubDate>", sub, text, flags=re.S)
    if 'xmlns:dc="' not in out:
        out = re.sub(r"<rss\b", '<rss xmlns:dc="http://purl.org/dc/elements/1.1/"', out, count=1)
    return _same_or_none(out.encode("utf-8"), body)


@mutation("rss-to-atom", {"xml"}, True, "el medio cambia RSS 2.0 por Atom 1.0 (mismas entradas)")
def _rss_to_atom(body, ctx):
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None
    if root.tag != "rss":
        return None
    A = "http://www.w3.org/2005/Atom"
    feed = ET.Element(f"{{{A}}}feed")
    chan = root.find("channel")
    ET.SubElement(feed, f"{{{A}}}title").text = chan.findtext("title") or ""
    ET.SubElement(feed, f"{{{A}}}link", href=chan.findtext("link") or "")
    for it in chan.findall("item"):
        _atom_entry(feed, it, A)
    ET.register_namespace("", A)
    return ET.tostring(feed, encoding="utf-8", xml_declaration=True)


def _atom_entry(feed: ET.Element, it: ET.Element, A: str) -> None:
    """Agrega al feed Atom la entrada equivalente a un <item> de RSS."""
    e = ET.SubElement(feed, f"{{{A}}}entry")
    ET.SubElement(e, f"{{{A}}}title").text = it.findtext("title") or ""
    ET.SubElement(e, f"{{{A}}}link", href=(it.findtext("link") or "").strip())
    ET.SubElement(e, f"{{{A}}}id").text = it.findtext("guid") or it.findtext("link") or ""
    d = _read_date(it.findtext("pubDate") or "")
    if d is not None:
        ET.SubElement(e, f"{{{A}}}published").text = d.isoformat()
    local = _rss_children(it)
    ET.SubElement(e, f"{{{A}}}summary", type="html").text = _rss_description(local) or ""
    _atom_categories(e, local, A)
    _atom_source(e, it, A)


def _rss_children(it: ET.Element) -> dict[str, list[ET.Element]]:
    """Los hijos de un <item> por su nombre local (sin el espacio de nombres)."""
    local: dict[str, list[ET.Element]] = {}
    for c in it:
        local.setdefault(c.tag.rsplit("}", 1)[-1], []).append(c)
    return local


def _rss_description(local: dict[str, list[ET.Element]]) -> str:
    """El primer texto no vacío entre <description> y <content:encoded>."""
    return next((c.text for k in ("description", "encoded") for c in local.get(k, []) if (c.text or "").strip()), "")


def _atom_categories(e: ET.Element, local: dict[str, list[ET.Element]], A: str) -> None:
    """Pasa <category> y <dc:subject> no vacíos a <category term=…> de Atom."""
    for c in local.get("category", []) + local.get("subject", []):
        if (c.text or "").strip():
            ET.SubElement(e, f"{{{A}}}category", term=c.text.strip())


def _atom_source(e: ET.Element, it: ET.Element, A: str) -> None:
    """Pasa el <source> de RSS (el medio de una nota de Google Noticias) a <source> de Atom."""
    src = it.find("source")
    if src is not None:  # el medio de una nota de Google Noticias: <source url="…">Medio</source>
        s_ = ET.SubElement(e, f"{{{A}}}source")
        ET.SubElement(s_, f"{{{A}}}title").text = src.text or ""
        ET.SubElement(s_, f"{{{A}}}link", href=src.get("url") or "")


# --- HTML (gob.pe, DHN, CENVUL, Telegram, NOAA) ------------------------------------------------------------------
ES_EN = {"enero": "January", "febrero": "February", "marzo": "March", "abril": "April", "mayo": "May",
         "junio": "June", "julio": "July", "agosto": "August", "setiembre": "September", "septiembre": "September",
         "octubre": "October", "noviembre": "November", "diciembre": "December"}
EN_ES = {"January": "enero", "February": "febrero", "March": "marzo", "April": "abril", "May": "mayo",
         "June": "junio", "July": "julio", "August": "agosto", "September": "setiembre", "October": "octubre",
         "November": "noviembre", "December": "diciembre"}


@mutation("months-en", {"html"}, True, "fechas en inglés en lugar de castellano (como el CENVUL al azar)")
def _months_en(body, ctx):
    rx = re.compile(r"\b(\d{1,2}) de (" + "|".join(ES_EN) + r")(?: de|,)? (\d{4})", re.I)
    return _text_op(lambda t: rx.sub(lambda m: f"{ES_EN[m.group(2).lower()]} {int(m.group(1))}, {m.group(3)}", t))(body, ctx)


@mutation("months-es", {"html"}, True, "fechas en castellano en lugar de inglés")
def _months_es(body, ctx):
    us = re.compile(r"\b(" + "|".join(EN_ES) + r") (\d{1,2}),? (\d{4})\b")
    uk = re.compile(r"\b(\d{1,2}) (" + "|".join(EN_ES) + r") (\d{4})\b")
    return _text_op(lambda t: uk.sub(lambda m: f"{int(m.group(1))} de {EN_ES[m.group(2)]} de {m.group(3)}",
                                     us.sub(lambda m: f"{int(m.group(2))} de {EN_ES[m.group(1)]} de {m.group(3)}", t)))(body, ctx)


@mutation("months-abbr", {"html"}, True, "meses abreviados («20 nov. 2026»)")
def _months_abbr(body, ctx):
    rx = re.compile(r"\b(\d{1,2}) de (" + "|".join(ES_EN) + r") de (\d{4})", re.I)
    return _text_op(lambda t: rx.sub(lambda m: f"{m.group(1)} {m.group(2)[:3].lower()}. {m.group(3)}", t))(body, ctx)


@mutation("entities", {"html", "xml"}, True, "acentos como entidades HTML (&aacute;, &ntilde;)")
def _entities(body, ctx):
    names = _accent_entities()
    if ctx["family"] == "xml":
        names = {c: f"&#{ord(c)};" for c in names}  # en XML solo valen las numéricas
    return _text_op(lambda t: "".join(names.get(ch, ch) for ch in t))(body, ctx)


def _accent_entities() -> dict[str, str]:
    """Cada vocal tildada y la eñe con su entidad HTML con nombre más corta («á» → «&aacute;»)."""
    import html as H
    names = {c: f"&{n};" for n, c in H.entities.html5.items() if n.endswith(";") and len(c) == 1 and c in "áéíóúñÁÉÍÓÚÑ"}
    return {c: "&" + min((n for n, v in H.entities.html5.items() if v == c and n.endswith(";")), key=len) for c in names}


@mutation("reflow", {"html"}, True, "el HTML llega en una sola línea (minificado)")
def _reflow(body, ctx):
    return _text_op(lambda t: re.sub(r">\s+<", "><", t.replace("\r", "")))(body, ctx)


@mutation("html-skeleton", {"html"}, False, "página válida sin contenido (plantilla vacía)")
def _skeleton(body, ctx):
    return b"<!DOCTYPE html><html lang=\"es\"><head><title>Inicio</title></head><body><main></main></body></html>"


# --- JSON (GeoJSON, ArcGIS, GODAS) ---------------------------------------------------------------------------------
def _json_op(fn: Callable[[object], object], dumps: Callable[[object], str] = None):
    def run(body, ctx):
        try:
            data = json.loads(body.decode("utf-8-sig"))
        except ValueError:
            return None
        out = fn(data)
        if out is None:
            return None
        return _same_or_none((dumps or (lambda d: json.dumps(d, ensure_ascii=False)))(out).encode("utf-8"), body)
    return run


def _reorder(d):
    if isinstance(d, dict):
        return {k: _reorder(d[k]) for k in reversed(list(d))}
    if isinstance(d, list):
        return [_reorder(v) for v in d]
    return d


def _leaves(d, fn):
    if isinstance(d, dict):
        return {k: _leaves(v, fn) for k, v in d.items()}
    if isinstance(d, list):
        return [_leaves(v, fn) for v in d]
    return fn(d)


RENAMES = {"features": "results", "attributes": "props", "properties": "props", "months": "data", "geometry": "geom"}


def _rename(d):
    if isinstance(d, dict):
        return {RENAMES.get(k, k): _rename(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_rename(v) for v in d]
    return d


def _empty_valid(d):
    if isinstance(d, dict) and isinstance(d.get("features"), list) and d["features"]:
        return {**d, "features": []}
    if isinstance(d, dict) and isinstance(d.get("months"), dict) and d["months"]:
        return {**d, "months": {}}
    return None


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _coords_swap(d):
    if isinstance(d, dict):
        out = {k: _coords_swap(v) for k, v in d.items()}
        if _num(out.get("x")) and _num(out.get("y")):
            out["x"], out["y"] = out["y"], out["x"]
        if isinstance(out.get("coordinates"), list) and len(out["coordinates"]) >= 2 and all(map(_num, out["coordinates"][:2])):
            c = out["coordinates"]
            out["coordinates"] = [c[1], c[0], *c[2:]]
        return out
    if isinstance(d, list):
        return [_coords_swap(v) for v in d]
    return d


def _epoch_seconds(v):
    return v // 1000 if isinstance(v, int) and not isinstance(v, bool) and v > 10 ** 12 else v


mutation("json-pretty", {"json"}, True, "JSON con sangría")(_json_op(lambda d: d, lambda d: json.dumps(d, indent=2, ensure_ascii=False)))
mutation("json-ascii", {"json"}, True, "JSON con \\uXXXX en lugar de UTF-8")(_json_op(lambda d: d, lambda d: json.dumps(d)))
mutation("json-key-order", {"json"}, True, "claves en otro orden")(_json_op(_reorder))
mutation("json-rename-keys", {"json"}, False, "claves renombradas (features→results, attributes→props…)")(_json_op(_rename))
mutation("json-empty-valid", {"json"}, False, "JSON válido sin elementos (features: [])")(_json_op(_empty_valid))
mutation("json-numbers-as-strings", {"json"}, False, "números como texto (\"5.2\")")(
    _json_op(lambda d: _leaves(d, lambda v: str(v) if _num(v) else v)))
mutation("json-coords-swap", {"json"}, False, "latitud y longitud intercambiadas")(_json_op(_coords_swap))
mutation("json-epoch-seconds", {"json"}, False, "fechas en segundos Unix en lugar de milisegundos")(
    _json_op(lambda d: _leaves(d, _epoch_seconds)))
mutation("json-scale-x10", {"json"}, False, "valores decimales ×10")(
    _json_op(lambda d: _leaves(d, lambda v: round(v * 10, 6) if isinstance(v, float) else v)))
mutation("json-error-200", {"json"}, False, "error de ArcGIS con HTTP 200 ({\"error\": {...}})")(
    lambda b, c: json.dumps({"error": {"code": 500, "message": "Error performing query operation", "details": []}}).encode())


def _layer_id(url: str) -> Optional[int]:
    m = re.search(r"/MapServer/(\d+)", url or "")
    return int(m.group(1)) if m else None


@mutation("arcgis-renumbered", {"json"}, False,
          "el servidor renumeró las capas: la del URL es otra (vacía) y la de estos avisos pasó a otro número")
def _arcgis_renumbered(body, ctx):
    lid = _layer_id(ctx.get("url"))
    if ctx.get("adapter") != "arcgis" or lid is None or not MAPSERVER.exists():
        return None
    listing = json.loads(MAPSERVER.read_text(encoding="utf-8"))
    for layer in listing.get("layers") or []:
        if layer.get("id") == lid:
            layer["id"] = lid + 20
    listing.setdefault("layers", []).append({"id": lid, "name": "SDE.OTRA_CAPA"})
    ctx["_listing"] = json.dumps(listing).encode()
    return json.dumps({"type": "FeatureCollection", "features": []}).encode()


@mutation("arcgis-other-layer", {"json"}, False, "el URL responde otra capa de avisos con datos (otro aviso)")
def _arcgis_other_layer(body, ctx):
    if ctx.get("adapter") != "arcgis":
        return None
    others = sorted(p for p in FIXTURES.glob("news-senamhi-*.json") if p.name != ctx.get("fixture"))
    return others[0].read_bytes() if others else None


def _mercator(lon: float, lat: float) -> tuple[float, float]:
    import math
    r = 6378137.0
    return round(math.radians(lon) * r, 1), round(math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * r, 1)


def _to_3857(d):
    if isinstance(d, dict):
        return _dict_to_3857(d)
    if isinstance(d, list):
        return _list_to_3857(d)
    return d


def _dict_to_3857(d: dict) -> dict:
    """Un objeto con sus pares de coordenadas («LONGITUD»/«LATITUD», «x»/«y») llevados a Web Mercator."""
    out = {k: _to_3857(v) for k, v in d.items()}
    for a, b in (("LONGITUD", "LATITUD"), ("x", "y")):
        if _num(out.get(a)) and _num(out.get(b)):
            out[a], out[b] = _mercator(out[a], out[b])
    return out


def _list_to_3857(d: list) -> list:
    """Una lista: si es un punto [lon, lat, …] se proyecta; si no, cada elemento."""
    if len(d) >= 2 and all(_num(v) for v in d[:2]) and -180 <= d[0] <= 180 and -90 <= d[1] <= 90:
        return [*_mercator(d[0], d[1]), *d[2:]]
    return [_to_3857(v) for v in d]


@mutation("arcgis-web-mercator", {"json"}, False, "geometría en Web Mercator (EPSG:3857, metros): se perdió outSR=4326")
def _arcgis_mercator(body, ctx):
    if ctx.get("adapter") != "arcgis":
        return None
    return _json_op(_to_3857)(body, ctx)


# --- CSV (FIRMS) ---------------------------------------------------------------------------------------------------
def _csv_rows(body: bytes) -> list[list[str]]:
    return [l.split(",") for l in _text(body).splitlines() if l.strip()]


def _csv_op(body: bytes, fn: Callable[[list[list[str]]], list[list[str]]], delim: str = ",") -> Optional[bytes]:
    rows = _csv_rows(body)
    if len(rows) < 3:
        return None
    return _same_or_none(("\n".join(delim.join(r) for r in fn(rows)) + "\n").encode("utf-8"), body)


def _csv_mut(name: str, preserving: bool, what: str, fn, delim: str = ","):
    mutation(name, {"csv"}, preserving, what)(lambda b, c: _csv_op(b, fn, delim))


def _swap_cols(rows, a: int, b: int, header: bool):
    out = []
    for i, r in enumerate(rows):
        r = list(r)
        if (header or i) and len(r) > max(a, b):
            r[a], r[b] = r[b], r[a]
        out.append(r)
    return out


_csv_mut("csv-semicolon", True, "separador «;»", lambda rows: rows, delim=";")
_csv_mut("csv-reorder", True, "columnas reordenadas (cabecera y datos)", lambda rows: _swap_cols(rows, 0, 1, True))
_csv_mut("csv-col-swap", False, "latitud y longitud intercambiadas sin cambiar la cabecera",
         lambda rows: _swap_cols(rows, 0, 1, False))
_csv_mut("csv-header-rename", False, "cabeceras renombradas (latitude→lat)",
         lambda rows: [[{"latitude": "lat", "longitude": "lon", "acq_date": "date"}.get(c, c) for c in rows[0]]] + rows[1:])
_csv_mut("csv-header-only", False, "CSV válido sin filas", lambda rows: rows[:1])
_csv_mut("csv-reversed", True, "filas en orden inverso", lambda rows: rows[:1] + rows[1:][::-1])
_csv_mut("csv-dup-row", True, "una fila repetida", lambda rows: rows[:2] + rows[1:])


# ---------------------------------------------------------------------------
# Objetivos: las fuentes de SOURCES y los feeds, leídos por el camino de la corrida
# ---------------------------------------------------------------------------
@dataclass
class Outcome:
    signals: tuple
    obs: str
    latest: Optional[str] = None


@dataclass
class Target:
    id: str
    kind: str  # source | feed
    family: str
    body: bytes
    run: Callable[[bytes], Outcome]
    ctx: dict = field(default_factory=dict)


def canon(x) -> str:
    return json.dumps(x, sort_keys=True, ensure_ascii=False, default=str)


def _loud_events(log) -> tuple:
    """Las incidencias que abren issue (``sync_issues.relevant``): aviso o más y no esperadas."""
    return tuple(sorted({f"{e.severity}:{e.code}" for e in log.events if e.severity != "info" and e.code not in IGNORE}))


def _source_body(src) -> bytes:
    resp = O._fixture_response(src, FIXTURES)
    return resp.body


def _acquire(src, body: bytes, prev_dir: Optional[Path]):
    with tempfile.TemporaryDirectory() as fx:
        (Path(fx) / src.fixture).write_bytes(body)
        log = O.EventLog()
        with contextlib.redirect_stderr(io.StringIO()):
            acq = O.acquire(src, None, Path(fx), O.PreviousPublication(str(prev_dir) if prev_dir else None), log)
    return acq, log


def source_target(src, workdir: Path) -> Target:
    """Una fuente de ``SOURCES``: ``observatory.acquire`` con la copia mutada y, como publicación anterior, la lectura
    de la copia sin cambios (así corren la huella del formato y la guardia de regresión como en producción)."""
    body = _source_body(src)
    base, _ = _acquire(src, body, None)
    if not base.ok:
        raise RuntimeError(f"{src.id}: la copia sin cambios ya no se lee ({base.error})")
    prev = workdir / src.id
    (prev / "sources").mkdir(parents=True, exist_ok=True)
    (prev / "sources" / f"{src.id}.json").write_text(canon({
        "data": base.data, "fingerprint": base.fingerprint, "url": base.url, "retrievedAt": base.retrieved_at}),
        encoding="utf-8")

    def run(b: bytes) -> Outcome:
        blocked = block_page(b, accept=src.accept)
        if blocked:  # ``Fetcher.get`` la descarta y sigue con las copias: la fuente queda «challenge»
            return Outcome((f"challenge:{blocked}",), "")
        acq, log = _acquire(src, b, prev)
        return Outcome(_loud_events(log), canon(acq.data if acq.ok else {"carried": acq.data}))
    # GODAS: el cuerpo es el resumen que arma ``_fetch_godas`` con los GRIB (lo de la fuente es el GRIB, que prueba
    # ``tests/test_godas.py``): solo cuentan las mutaciones de transporte («internal»).
    family = ("internal" if src.fetch else "html" if src.fixture.endswith(".html")
              else "json" if src.fixture.endswith(".json") else "table")
    return Target(src.id, "source", family, body, run, {"family": family})


FEED_FAMILY = {"feed": "xml", "indeci-coen": "xml", "gobpe": "html", "dhn": "html", "dhn-avisos": "html",
               "cenvul": "html", "telegram": "html", "geojson": "json", "arcgis": "json", "firms": "csv",
               "ptwc-text": "text"}


def _norm_entry(e: dict) -> dict:
    return {k: v for k, v in e.items() if k not in ("published",)} | {"published": e.get("published")}


def feed_target(f, body: Optional[bytes] = None) -> Target:
    """Un feed de ``news.FEEDS``: ``news._read_feed`` (lector, filtros de relevancia y ubicación) con la copia mutada."""
    body = body if body is not None else (FIXTURES / f.fixture).read_bytes()
    listing = N._layer_listing_url(f.url) if f.layer else None

    ctx = {"adapter": f.adapter, "region": f.region, "url": f.url, "fixture": f.fixture}

    def fetch(url, b):
        if url == f.url:
            return 200, b, "", ""
        if listing and url == listing and MAPSERVER.exists():
            return 200, ctx.get("_listing") or MAPSERVER.read_bytes(), "application/json", ""
        return None, b"", "", "sin red en la simulación"

    def run(b: bytes) -> Outcome:
        blocked = block_page(b)
        if blocked:
            return Outcome((f"challenge:{blocked}",), "")
        now = ctx.get("now") or NOW
        seen: list = []
        orig = N.parse_any

        def spy(*a, **k):
            p = orig(*a, **k)
            seen.append(p)
            return p
        N.parse_any = spy
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                st, found, _ = N._read_feed(f, lambda u: fetch(u, b), now, {})
        finally:
            N.parse_any = orig
            ctx.pop("_listing", None)  # el listado mutado vale para una sola lectura
        # Lo que la corrida hace con el estado: ``persistent.feed_state`` (degradado: escala a issue si se repite) y,
        # en un feed oficial de avisos, ``alert-source-format`` el mismo día si cambió de forma.
        state, _ = P.feed_state(st, f, {}, now, P.rules())
        sig = [f"degraded:{state}"] if state else []
        if st.get("formatError"):
            sig.append("format-error")
        entries = sorted(canon(_norm_entry(e)) for e in (seen[0].items if seen and st.get("ok") else []))
        obs = canon({"entries": entries, "found": sorted(canon({k: i.get(k) for k in ("id", "published", "relevance",
                                                                                          "hazards", "title", "link")})
                                                          for i in found),
                     "latest": st.get("latest"), "items": st.get("items")})
        return Outcome(tuple(sig), obs, st.get("latest"))
    ctx["family"] = FEED_FAMILY.get(f.adapter, "xml")
    # La hora de la simulación es la de la copia (una hora después de su entrada más reciente): con la de hoy, un feed
    # capturado hace un mes ya estaría «inactivo» sin mutar nada.
    latest = run(body).latest
    if latest:
        ctx["now"] = datetime.fromisoformat(latest.replace("Z", "+00:00")) + timedelta(hours=1)
    return Target(f.id, "feed", ctx["family"], body, run, ctx)


def _date_style(body: bytes) -> str:
    m = DATE_TAG_RE.search(_text(body)[:200000])
    if not m:
        return "none"
    raw = m.group(3)
    if re.search(r"[+-]\d{4}$", raw):
        return "rfc-offset"
    if raw.endswith(("GMT", "UTC", "Z")):
        return "utc"
    if re.match(r"\d{4}-\d{2}-\d{2}", raw):
        return "iso"
    return "other"


def representative_feeds() -> list:
    """Un feed por familia de formato (lector, formato del feed, estilo de fecha, región, con o sin acentos): lo
    que la prueba corre en menos de un minuto. ``--all-feeds`` corre todos."""
    seen, out = set(), []
    for f in N.FEEDS:
        p = FIXTURES / f.fixture
        if not p.exists() or f.id == "senamhi-quebradas":  # 2 s por lectura (polígonos); la capa de lluvias es igual
            continue
        body = p.read_bytes()
        root = re.search(rb"<(rss|feed|rdf:RDF)\b", body[:5000])
        key = (f.adapter, root.group(1) if root else b"", _date_style(body) if f.adapter == "feed" else "",
               f.region, body.isascii())
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


# ---------------------------------------------------------------------------
# Clasificación y corrida
# ---------------------------------------------------------------------------
@dataclass
class Result:
    target: str
    kind: str
    mutation: str
    verdict: str
    signals: tuple = ()
    detail: str = ""
    group: str = ""  # el lector («arcgis», «feed»…) o «source»


def classify(base: Outcome, got: Outcome, preserving: bool) -> tuple[str, tuple]:
    new = tuple(s for s in got.signals if s not in base.signals)
    if new:
        return (NOISY if preserving else LOUD), new
    if got.obs == base.obs:
        return BENIGN, ()
    return SILENT, ()


def _diff(base: str, got: str) -> str:
    """Primera diferencia entre lo publicado sin y con la mutación (para el informe)."""
    a, b = json.loads(base or "null"), json.loads(got or "null")
    return _first_diff(a, b, "$")[:400]


def _first_diff(a, b, path: str) -> str:
    if type(a) is not type(b):
        return f"{path}: {str(a)[:120]} → {str(b)[:120]}"
    if isinstance(a, dict):
        return _first_diff_dict(a, b, path)
    if isinstance(a, list):
        return _first_diff_list(a, b, path)
    return f"{path}: {str(a)[:120]} → {str(b)[:120]}"


def _first_diff_dict(a: dict, b: dict, path: str) -> str:
    """Primera clave (en orden) cuyo valor cambió, o "" si ninguna."""
    for k in sorted(set(a) | set(b)):
        if a.get(k) != b.get(k):
            return _first_diff(a.get(k), b.get(k), f"{path}.{k}")
    return ""


def _first_diff_list(a: list, b: list, path: str) -> str:
    """Cambio de largo (con un elemento de ejemplo) o primer elemento distinto, o "" si ninguno."""
    if len(a) != len(b):
        extra = [x for x in b if x not in a][:1] or [x for x in a if x not in b][:1]
        return f"{path}: {len(a)} → {len(b)} elementos (p. ej. {str(extra)[:200]})"
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return _first_diff_item(x, y, f"{path}[{i}]")
    return ""


def _first_diff_item(x, y, path: str) -> str:
    """Diferencia entre dos elementos; un texto que es JSON («{…}») se compara ya leído."""
    if isinstance(x, str) and isinstance(y, str) and x.startswith("{"):
        return _first_diff(json.loads(x), json.loads(y), path)
    return _first_diff(x, y, path)


def applicable(t: Target, m: Mutation) -> bool:
    return t.family in m.families


def simulate(targets: list[Target], mutations: Optional[list[str]] = None) -> list[Result]:
    out: list[Result] = []
    for t in targets:
        base = t.run(t.body)
        if base.signals:
            raise RuntimeError(f"{t.id}: la copia sin cambios ya avisa ({base.signals}); la simulación no sirve")
        for m in MUTATIONS.values():
            if mutations and m.name not in mutations:
                continue
            body = m.apply(t.body, t.ctx) if applicable(t, m) else None
            if body is None or body == t.body:
                out.append(Result(t.id, t.kind, m.name, NA, group=t.ctx.get("adapter", t.kind)))
                continue
            got = t.run(body)
            verdict, sig = classify(base, got, m.preserving)
            out.append(Result(t.id, t.kind, m.name, verdict, sig, _diff(base.obs, got.obs) if verdict == SILENT else "",
                              t.ctx.get("adapter", t.kind)))
    return out


def build_targets(all_feeds: bool = False, only: Optional[set] = None, work: Optional[Path] = None) -> list[Target]:
    work = work or Path(tempfile.mkdtemp(prefix="drift-sim-"))
    out = [source_target(s, work) for s in O.SOURCES if _selected(s.id, only)]
    out += [feed_target(f) for f in _feeds_to_simulate(all_feeds, only) if _selected(f.id, only)]
    return out


def _selected(id_: str, only: Optional[set]) -> bool:
    """Si el objetivo entra en la selección de --target (sin selección entran todos)."""
    return not only or id_ in only


def _feeds_to_simulate(all_feeds: bool, only: Optional[set]) -> list:
    """Todos los feeds con copia (con --all-feeds o --target) o uno representativo por familia."""
    return [f for f in N.FEEDS if (FIXTURES / f.fixture).exists()] if all_feeds or only else representative_feeds()


#: (objetivo o «*», mutación) → por qué un SILENT-WRONG está revisado y se acepta. Cada entrada es una decisión con su
#: costo dicho: no una forma de callar la prueba.
ALLOWLIST: dict[tuple[str, str], str] = {
    ("adapter:arcgis", "json-empty-valid"): (
        "Una capa de avisos vacía es la respuesta normal cuando no hay avisos vigentes y no se distingue, desde la "
        "respuesta, de una capa que el servidor dejó de llenar. Lo que se puede comprobar se comprueba: que la capa "
        "del URL sigue siendo la de esos avisos (news.check_layer, mutación arcgis-renumbered) y desde cuándo está "
        "vacía (emptySince en news/feeds.json). Costo: una capa que deja de llenarse no avisa; el contraste con la "
        "tabla de avisos vigentes del SENAMHI (senamhi_avisos) sería la prueba independiente y queda pendiente."),
}


def allowed(r: Result) -> Optional[str]:
    return (ALLOWLIST.get((r.target, r.mutation)) or ALLOWLIST.get((f"adapter:{r.group}", r.mutation))
            or ALLOWLIST.get(("*", r.mutation)))


def summary(results: list[Result]) -> dict:
    by: dict[str, int] = {}
    for r in results:
        by[r.verdict] = by.get(r.verdict, 0) + 1
    return by


def _parser() -> argparse.ArgumentParser:
    """Las opciones de la línea de órdenes."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all-feeds", action="store_true", help="todos los feeds con copia, no uno por familia")
    ap.add_argument("--target", action="append", help="solo este objetivo (id de fuente o feed); repetible")
    ap.add_argument("--mutation", action="append", help="solo esta mutación; repetible")
    ap.add_argument("--show", action="store_true", help="todas las filas, no solo SILENT-WRONG y NOISY")
    ap.add_argument("--json", help="escribe los resultados en este archivo")
    return ap


def _run(a: argparse.Namespace) -> tuple[list[Target], list[Result]]:
    """Arma los objetivos pedidos y los simula; RuntimeError si --target no nombra ninguno."""
    targets = build_targets(a.all_feeds, set(a.target) if a.target else None)
    if a.target and not targets:
        raise RuntimeError(f"objetivo desconocido: {', '.join(a.target)}")
    return targets, simulate(targets, a.mutation)


def _print_rows(results: list[Result], show: bool) -> None:
    """Imprime las filas SILENT-WRONG y NOISY (todas con --show)."""
    for r in results:
        if show or r.verdict in (SILENT, NOISY):
            tag = " (revisado: " + allowed(r) + ")" if r.verdict == SILENT and allowed(r) else ""
            print(f"{r.verdict:12} {r.kind:6} {r.target:28} {r.mutation:24} {','.join(r.signals) or r.detail}{tag}")


def _print_summary(targets: list[Target], results: list[Result], bad: list[Result], t0: float) -> None:
    """Imprime la línea de resumen: objetivos, mutaciones, tiempo y cuenta por veredicto."""
    print(f"\n{len(targets)} objetivos, {len(MUTATIONS)} mutaciones, {time.monotonic() - t0:.1f} s: "
          + ", ".join(f"{k} {v}" for k, v in sorted(summary(results).items()))
          + f"; SILENT-WRONG sin revisar: {len(bad)}")


def _write_json(path: str, results: list[Result]) -> None:
    """Escribe los resultados, el resumen y las mutaciones en un archivo JSON (--json)."""
    Path(path).write_text(json.dumps({"generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                      "summary": summary(results),
                                      "mutations": {m.name: {"what": m.what, "preserving": m.preserving,
                                                             "families": sorted(m.families)}
                                                    for m in MUTATIONS.values()},
                                      "results": [r.__dict__ | {"allowed": allowed(r)} for r in results]},
                                     ensure_ascii=False, indent=1, default=list), encoding="utf-8")


def _unknown_mutations(names: Optional[list[str]]) -> list[str]:
    """Las mutaciones pedidas con --mutation que no existen."""
    return [m for m in names or [] if m not in MUTATIONS]


def main(argv: Optional[list[str]] = None) -> int:
    a = _parser().parse_args(argv)
    unknown = _unknown_mutations(a.mutation)
    if unknown:
        print(f"mutación desconocida: {', '.join(unknown)}; hay: {', '.join(MUTATIONS)}", file=sys.stderr)
        return 2
    t0 = time.monotonic()
    try:
        targets, results = _run(a)
    except (RuntimeError, OSError) as exc:
        print(f"drift_sim: no se pudo simular: {exc}", file=sys.stderr)
        return 2
    bad = [r for r in results if r.verdict == SILENT and not allowed(r)]
    _print_rows(results, a.show)
    _print_summary(targets, results, bad, t0)
    if a.json:
        _write_json(a.json, results)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
