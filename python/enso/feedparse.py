"""Lector tolerante de feeds: RSS 2.0/0.9x, RSS 1.0 (RDF), Atom y JSON Feed.

Los medios regionales publican feeds con defectos frecuentes: BOM o avisos
de PHP antes del XML, codificación declarada distinta de la real, entidades
HTML (``&nbsp;``) que el XML no define, ``&`` sin escapar, caracteres de
control, feeds cortados a la mitad, enlaces relativos, fechas en castellano
o sin zona horaria. ``parse`` repara lo que se puede reparar sin adivinar,
anota cada reparación en ``repairs`` y devuelve las entradas en un formato
único (título, enlace absoluto, fecha UTC, resumen, medio, categorías).

Lo que no se repara: un documento que declara entidades XML (riesgo de
expansión), una página HTML en lugar de un feed y un feed sin entradas
legibles. Esos casos levantan ``FeedError``.
"""

from __future__ import annotations

import codecs
import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.entities import html5
from typing import Optional
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

MAX_FEED_BYTES = 5_000_000
LIMA = timezone(timedelta(hours=-5))  # el Perú no usa horario de verano

ATOM = "{http://www.w3.org/2005/Atom}"
TAG_RE = re.compile(r"<[^>]+>")


class FeedError(ValueError):
    pass


@dataclass
class Parsed:
    format: str
    items: list[dict]
    repairs: list[str] = field(default_factory=list)
    title: str = ""
    link: str = ""


#: Coletillas que WordPress y otros gestores agregan al final del resumen.
_BOILER_RE = re.compile(
    r"\s*(?:La entrada .{1,300}? se public[oó] primero en .{1,150}?|The post .{1,300}? appeared first on .{1,150}?|"
    r"\[(?:…|\.\.\.)\]|(?:Leer|Lee|Ver) m[aá]s\W*|Seguir leyendo\W*|Continue reading\W*|Read more\W*)\.?\s*$", re.S | re.I)


def clean_text(text: Optional[str], limit: int = 600) -> str:
    text = html.unescape(TAG_RE.sub(" ", html.unescape(text or "")))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def clean_summary(text: Optional[str], limit: int = 600) -> str:
    """Resumen sin etiquetas ni coletillas («La entrada … se publicó primero en …», «Leer más»)."""
    text = clean_text(text, 4000)
    for _ in range(3):
        text, n = _BOILER_RE.subn("", text)
        if not n:
            break
    return text.strip()[:limit]


# --- Fechas --------------------------------------------------------------------

_ES_MONTHS = {
    "enero": "Jan", "ene": "Jan", "febrero": "Feb", "feb": "Feb", "marzo": "Mar", "mar": "Mar",
    "abril": "Apr", "abr": "Apr", "mayo": "May", "may": "May", "junio": "Jun", "jun": "Jun",
    "julio": "Jul", "jul": "Jul", "agosto": "Aug", "ago": "Aug", "septiembre": "Sep", "setiembre": "Sep",
    "sep": "Sep", "set": "Sep", "sept": "Sep", "octubre": "Oct", "oct": "Oct", "noviembre": "Nov",
    "nov": "Nov", "diciembre": "Dec", "dic": "Dec",
}
_MONTH_NUM = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
_TZ_ABBR = {"PET": "-0500", "COT": "-0500", "ECT": "-0500", "BOT": "-0400", "CLT": "-0400", "CLST": "-0300",
            "ART": "-0300", "BRT": "-0300", "UYT": "-0300", "VET": "-0400", "CST": "-0600", "MST": "-0700",
            "UTC": "+0000", "Z": "+0000"}
_DOW_RE = re.compile(r"^\s*[A-Za-zéáÉÁ]{2,10}\.?,\s*")
_ES_LONG_RE = re.compile(
    r"(\d{1,2})\s+de\s+([a-záé]+)\s+(?:de|del)\s+(\d{4})(?:[^\d]{1,12}(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([ap]\.?\s?m\.?)?)?", re.I)


_AMPM_RE = re.compile(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp])\.?\s?[Mm]\.?(?=\s|$)")
_DATE_ONLY_RE = re.compile(
    r"^(?:(\d{1,2})\s+(?:de\s+)?([A-Za-zé]{3,10})\.?,?\s+(?:de\s+|del\s+)?(\d{4})|"
    r"([A-Za-zé]{3,10})\.?\s+(\d{1,2}),?\s+(\d{4}))$", re.I)


def _hour12(hh: int, ampm: str) -> int:
    if ampm.lower().startswith("p") and hh < 12:
        return hh + 12
    if ampm.lower().startswith("a") and hh == 12:
        return 0
    return hh


def _plausible(d: datetime, now: datetime) -> Optional[datetime]:
    """Entre 1995 y dos días después de ``now`` (un feed no publica noticias del futuro)."""
    return d if datetime(1995, 1, 1, tzinfo=timezone.utc) <= d <= now + timedelta(days=2) else None


def parse_date(text: Optional[str], default_tz: timezone = timezone.utc,
               now: Optional[datetime] = None) -> Optional[str]:
    """Fecha ISO en UTC desde RFC 822, ISO 8601, castellano o época Unix; None si no se entiende."""
    if not text:
        return None
    now = now or datetime.now(timezone.utc)
    raw = re.sub(r"\s+", " ", text.strip())
    try:
        return _parse_date(raw, default_tz, now)
    except (OverflowError, ValueError, OSError):
        return None  # fechas fuera del rango de datetime (9999-12-31, 0001-01-01…)


def _parse_date(raw: str, default_tz: timezone, now: datetime) -> Optional[str]:
    d: Optional[datetime] = None
    if re.fullmatch(r"\d{9,10}", raw):
        d = datetime.fromtimestamp(int(raw), timezone.utc)
    if d is None:
        m = _ES_LONG_RE.search(raw)
        if m:
            mon = _MONTH_NUM.get(_ES_MONTHS.get(m.group(2).lower(), ""), 0)
            if mon:
                hh, mm, ss = int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0)
                if m.group(7):
                    hh = _hour12(hh, m.group(7))
                try:
                    d = datetime(int(m.group(3)), mon, int(m.group(1)), hh, mm, ss, tzinfo=default_tz)
                except ValueError:
                    d = None
    if d is None:
        s = _DOW_RE.sub("", raw)
        s = re.sub(r"\b([A-Za-zé]{3,10})\b\.?", lambda m: _ES_MONTHS.get(m.group(1).lower(), m.group(0)), s)
        s = _AMPM_RE.sub(lambda m: f"{_hour12(int(m.group(1)), m.group(4)):02d}:{m.group(2)}:{m.group(3) or '00'}", s)
        s = re.sub(r"\b(GMT|UTC)\s?([+-])(\d{1,2})(?::?(\d{2}))?$",
                   lambda m: f"{m.group(2)}{int(m.group(3)):02d}{m.group(4) or '00'}", s)
        s = re.sub(r"([+-]\d{2}):(\d{2})$", r"\1\2", s) if re.search(r"[A-Za-z]{3} \d{4} \d", s) else s
        s = re.sub(r"\b([A-Z]{1,4})$", lambda m: _TZ_ABBR.get(m.group(1), m.group(1)), s)
        try:
            d = parsedate_to_datetime(s)
        except (TypeError, ValueError, IndexError):
            d = None
        if d is not None and d.tzinfo is None:
            # «-0000» y «GMT» son UTC explícito (RFC 2822); sin zona, la hora es la local del medio.
            d = d.replace(tzinfo=timezone.utc if re.search(r"[+-]\d{4}$|GMT$", s) else default_tz)
        if d is None:
            m = _DATE_ONLY_RE.match(s.strip())
            if m:
                day, mon, year = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(5), m.group(4), m.group(6))
                num = _MONTH_NUM.get(_ES_MONTHS.get(mon.lower(), mon[:3].title()), 0)
                if num:
                    d = datetime(int(year), num, int(day), tzinfo=default_tz)
    if d is None:
        iso = raw.replace("/", "-").replace("Z", "+00:00")
        iso = re.sub(r"^(\d{4}-\d{2}-\d{2}) (\d)", r"\1T\2", iso)
        iso = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", iso)
        try:
            d = datetime.fromisoformat(iso)
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=default_tz)
    d = _plausible(d.astimezone(timezone.utc), now)
    return d.isoformat(timespec="seconds") if d else None


# --- Reparaciones del texto ----------------------------------------------------

_XML_ENT = {"amp", "lt", "gt", "quot", "apos"}
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_ENT_RE = re.compile(r"&([A-Za-z][A-Za-z0-9]{1,31});")
_BARE_AMP_RE = re.compile(r"&(?!#\d{1,7};|#x[0-9A-Fa-f]{1,6};|[A-Za-z][A-Za-z0-9]{1,31};)")
_ROOT_RE = re.compile(r"<(\?xml\b|rss\b|feed\b|rdf:RDF\b|RDF\b)")
_DECL_RE = re.compile(r"^\s*<\?xml[^>]*\?>", re.I)
_ENC_RE = re.compile(rb"<\?xml[^>]*encoding=[\"']([A-Za-z0-9._-]+)[\"']", re.I)
#: Codificaciones que en la práctica son Windows-1252 (los medios declaran ISO-8859-1 y usan comillas curvas).
_LATIN = {"iso-8859-1", "iso8859-1", "iso_8859-1", "latin-1", "latin1", "l1", "windows-1252", "cp1252", "us-ascii", "ascii"}


def _cp1252_bytes(err: UnicodeDecodeError) -> tuple[str, int]:
    return err.object[err.start:err.end].decode("cp1252", errors="replace"), err.end


codecs.register_error("enso-cp1252", _cp1252_bytes)


def _decode(body: bytes, repairs: list[str]) -> str:
    """Texto del feed. Se prueba primero UTF-8 (lo que usan casi todos, declaren lo que declaren)."""
    if body.startswith((b"\xff\xfe", b"\xfe\xff")):
        return body.decode("utf-16", errors="replace")
    if body.startswith(b"\xef\xbb\xbf"):
        body = body[3:]
    m = _ENC_RE.search(body[:400])
    declared = (m.group(1).decode().lower() if m else "utf-8")
    try:
        text = body.decode("utf-8")
        if declared not in ("utf-8", "utf8") and not text.isascii():
            repairs.append(f"codificación: declarada {declared}, leída como UTF-8")
        return text
    except UnicodeDecodeError:
        pass
    if declared in ("utf-8", "utf8"):
        # UTF-8 con algunos bytes sueltos de Windows-1252: solo esos bytes se leen como windows-1252.
        repairs.append(f"codificación: declarada {declared}, bytes sueltos leídos como windows-1252")
        return body.decode("utf-8", errors="enso-cp1252")
    try:
        return body.decode("cp1252" if declared in _LATIN else declared)
    except (UnicodeDecodeError, LookupError):
        repairs.append(f"codificación: declarada {declared}, leída como windows-1252")
        return body.decode("cp1252", errors="replace")


def _named_entity(m: re.Match) -> str:
    name = m.group(1)
    if name in _XML_ENT:
        return m.group(0)
    ch = html5.get(name + ";")
    return "".join(f"&#{ord(c)};" for c in ch) if ch else f"&amp;{name};"


_CDATA_RE = re.compile(r"(<!\[CDATA\[.*?\]\]>)", re.S)


def _outside_cdata(text: str, fn) -> str:
    """Aplica ``fn`` solo fuera de las secciones CDATA (dentro, todo es texto literal)."""
    return "".join(part if part.startswith("<![CDATA[") else fn(part) for part in _CDATA_RE.split(text))


_ROOT_NAME_RE = re.compile(r"\s*(?:<!--.*?-->\s*|<!DOCTYPE[^>]*>\s*|<\?[^>]*\?>\s*)*<([A-Za-z_][\w:.-]*)", re.S)
_NUMREF_RE = re.compile(r"&#(x[0-9A-Fa-f]{1,6}|\d{1,7});")


def _legal_ref(m: re.Match) -> str:
    """Quita las referencias numéricas a caracteres que el XML prohíbe (``&#11;``, ``&#x1F;``)."""
    v = m.group(1)
    try:
        n = int(v[1:], 16) if v[0] in "xX" else int(v)
    except ValueError:
        return ""
    ok = n in (9, 10, 13) or 0x20 <= n <= 0xD7FF or 0xE000 <= n <= 0xFFFD or 0x10000 <= n <= 0x10FFFF
    return m.group(0) if ok else ""


def _repair_text(text: str, repairs: list[str]) -> str:
    m = _ROOT_RE.search(text)
    if m and text[: m.start()].strip():
        repairs.append("texto antes del XML")
    if m:
        text = text[m.start():]
    text = _DECL_RE.sub("", text, count=1).lstrip()
    root = _ROOT_NAME_RE.match(text)
    if root:
        close = f"</{root.group(1)}>"
        i = text.rfind(close)
        if i != -1:
            if text[i + len(close):].strip():
                repairs.append("texto después del XML")
            text = text[: i + len(close)]
    if _CTRL_RE.search(text):
        repairs.append("caracteres de control")
        text = _CTRL_RE.sub("", text)
    fixed = _outside_cdata(text, lambda t: _NUMREF_RE.sub(_legal_ref, t))
    if fixed != text:
        if "caracteres de control" not in repairs:
            repairs.append("caracteres de control")
        text = fixed
    fixed = _outside_cdata(text, lambda t: _ENT_RE.sub(_named_entity, t))
    if fixed != text:
        repairs.append("entidades HTML")
        text = fixed
    fixed = _outside_cdata(text, lambda t: _BARE_AMP_RE.sub("&amp;", t))
    if fixed != text:
        repairs.append("& sin escapar")
        text = fixed
    return text


_BLOCK_RE = re.compile(r"<(item|entry)\b[^>]*>.*?</\1\s*>", re.S)
_NS_RE = re.compile(r"\sxmlns(?::[A-Za-z0-9_-]+)?=(\"[^\"]*\"|'[^']*')")
_COMMON_NS = {
    "content": "http://purl.org/rss/1.0/modules/content/", "dc": "http://purl.org/dc/elements/1.1/",
    "media": "http://search.yahoo.com/mrss/", "atom": "http://www.w3.org/2005/Atom",
    "feedburner": "http://rssnamespace.org/feedburner/ext/1.0", "a10": "http://www.w3.org/2005/Atom",
}


def _salvage(text: str, repairs: list[str]) -> ET.Element:
    """Lee las entradas una por una cuando el documento completo no es XML válido."""
    first = re.search(r"<(?![?!])[^>]*>", text)
    opening = first.group(0) if first else ""
    # Solo los prefijos declarados en la raíz; el espacio por omisión no hace falta (se lee el nombre local).
    declared = "".join(m.group(0) for m in _NS_RE.finditer(opening) if m.group(0).lstrip().startswith("xmlns:"))
    extra = "".join(f' xmlns:{p}="{u}"' for p, u in _COMMON_NS.items() if f"xmlns:{p}=" not in declared)
    # Las secciones CDATA se tapan (con el mismo largo) para que un «<item>» literal dentro no corte las entradas.
    masked = _CDATA_RE.sub(lambda c: " " * len(c.group(0)), text)
    spans = [(m.start(), m.end()) for m in _BLOCK_RE.finditer(masked)]
    found = [text[a:b] for a, b in spans]
    if not found:
        raise FeedError("XML inválido y sin entradas recuperables")
    is_atom = opening.startswith("<feed")
    is_rdf = opening.startswith(("<rdf:RDF", "<RDF"))
    head = text[: spans[0][0]]
    title = re.search(r"<title\b[^>]*>(.*?)</title>", head, re.S)
    if is_atom:
        root = ET.Element(f"{ATOM}feed")
        parent = root
        link = re.search(r"<link\b(?=[^>]*rel=[\"']alternate)[^>]*href=[\"']([^\"']+)", head) or \
            re.search(r"<link\b[^>]*href=[\"']([^\"']+)", head)
        if link:
            ET.SubElement(root, f"{ATOM}link", rel="alternate", href=html.unescape(link.group(1)))
        if title:
            ET.SubElement(root, f"{ATOM}title").text = clean_text(title.group(1), 200)
    else:
        root = ET.Element("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF" if is_rdf else "rss")
        chan = ET.SubElement(root, "channel")
        parent = root if is_rdf else chan
        link = re.search(r"<link>\s*(?:<!\[CDATA\[)?\s*([^<\]\s]+)", head)
        if link:
            ET.SubElement(chan, "link").text = html.unescape(link.group(1))
        if title:
            ET.SubElement(chan, "title").text = clean_text(title.group(1), 200)
    default = ' xmlns="http://www.w3.org/2005/Atom"' if is_atom else ' xmlns="http://purl.org/rss/1.0/"' if is_rdf else ""
    ok = 0
    for block in found:
        try:
            parent.append(ET.fromstring(f"<x{default}{declared}{extra}>{block}</x>")[0])
            ok += 1
        except ET.ParseError:
            continue
    if not ok:
        raise FeedError("XML inválido y sin entradas recuperables")
    repairs.append(f"documento inválido: {ok} de {len(found)} entradas recuperadas una por una")
    return root


# --- Extracción ----------------------------------------------------------------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _children(e: ET.Element, *names: str) -> list[ET.Element]:
    return [c for c in e if _local(c.tag) in names]


def _text(e: Optional[ET.Element]) -> str:
    return "".join(e.itertext()) if e is not None else ""


def _first(e: ET.Element, *names: str) -> str:
    for n in names:
        for c in _children(e, n):
            t = _text(c).strip()
            if t:
                return t
    return ""


def _abs(link: str, base: str) -> str:
    link = (link or "").strip()
    if not link:
        return ""
    if link.startswith("//"):
        return "https:" + link
    return urljoin(base, link) if base and not link.startswith(("http://", "https://")) else link


def _rss_item(e: ET.Element, base: str, tz: timezone, now: datetime) -> dict:
    link = _first(e, "origLink")
    if not link:
        link = _first(e, "link")
    if not link:
        link = next((c.get("href", "") for c in _children(e, "link") if c.get("href")), "")
    if not link:
        for g in _children(e, "guid"):
            t = _text(g).strip()
            if g.get("isPermaLink", "true") != "false" and t.startswith(("http://", "https://")):
                link = t
    item = {
        "title": clean_text(_first(e, "title"), 300),
        "link": _abs(link, base),
        "published": parse_date(_first(e, "pubDate", "date", "published", "issued", "updated", "modified"), tz, now),
        "summary": clean_summary(_first(e, "description", "summary", "encoded", "content")
                                 or next((_text(c) for c in e.iter() if _local(c.tag) == "description"), "")),
        "categories": [clean_text(_text(c), 80) for c in _children(e, "category", "subject") if _text(c).strip()][:12],
    }
    src = _children(e, "source")
    if src and _text(src[0]).strip():
        outlet = clean_text(_text(src[0]), 120)
        # Google Noticias a veces pone la URL del medio en lugar de su nombre.
        m = re.match(r"^https?://(?:www\.)?([^/\s]+)/?$", outlet)
        item["outlet"] = m.group(1) if m else outlet
    if src and src[0].get("url", "").startswith(("http://", "https://")):
        item["outletUrl"] = src[0].get("url")
    return item


def _atom_entry(e: ET.Element, base: str, tz: timezone, now: datetime) -> dict:
    links = _children(e, "link")
    link = next((l.get("href") for l in links if l.get("rel", "alternate") == "alternate" and l.get("href")), None)
    link = link or next((l.get("href") for l in links if l.get("href")), "") or _first(e, "id")
    return {
        "title": clean_text(_first(e, "title"), 300),
        "link": _abs(link, base),
        "published": parse_date(_first(e, "published", "issued", "updated", "modified"), tz, now),
        "summary": clean_summary(_first(e, "summary", "content", "description")),
        "categories": [clean_text(c.get("term") or c.get("label") or _text(c), 80) for c in _children(e, "category")][:12],
    }


def _json_feed(body: bytes, base: str, tz: timezone, now: datetime) -> Parsed:
    try:
        data = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise FeedError(f"JSON inválido: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise FeedError("JSON sin lista de entradas")
    items = []
    for it in data["items"]:
        if not isinstance(it, dict):
            continue
        tags = it.get("tags") if isinstance(it.get("tags"), list) else []
        items.append({
            "title": clean_text(str(it.get("title") or ""), 300),
            "link": _abs(str(it.get("url") or it.get("external_url") or ""), base),
            "published": parse_date(str(it.get("date_published") or it.get("date_modified") or ""), tz, now),
            "summary": clean_summary(str(it.get("summary") or it.get("content_text") or it.get("content_html") or "")),
            "categories": [clean_text(str(t), 80) for t in tags if isinstance(t, (str, int, float)) and t][:12],
        })
    return Parsed("jsonfeed", items, title=clean_text(str(data.get("title") or ""), 200),
                  link=str(data.get("home_page_url") or ""))


# --- Listados HTML de gob.pe ----------------------------------------------------
# Las entidades del Estado (INDECI, SENAMHI, ANA, gobiernos regionales…) publican
# sus notas en https://www.gob.pe/institucion/<entidad>/noticias, sin RSS. Cada
# nota es una tarjeta con <h3><a href>, una descripción y <time datetime> en hora
# de Lima. El adaptador la convierte al mismo formato que las entradas de un feed.

_GOBPE_CARD_RE = re.compile(
    r'<h3\b[^>]*>\s*<a\b[^>]*href="(?P<href>/institucion/[^"]+/noticias/\d+[^"]*)"[^>]*>(?P<title>.*?)</a>'
    r'(?P<rest>.*?)<time\b[^>]*datetime="(?P<dt>[^"]+)"', re.S)
_GOBPE_DESC_RE = re.compile(r'id="[^"]*-description"[^>]*>(.*?)</div>\s*</div>', re.S)


def parse_gobpe(body: bytes, base_url: str = "https://www.gob.pe/", now: Optional[datetime] = None) -> Parsed:
    now = now or datetime.now(timezone.utc)
    text = body.decode("utf-8", errors="replace")
    if "gob.pe" not in text[:5000] and "gob.pe" not in base_url:
        raise FeedError("no es una página de gob.pe")
    items = []
    for m in _GOBPE_CARD_RE.finditer(text):
        desc = _GOBPE_DESC_RE.search(m.group("rest"))
        items.append({"title": clean_text(m.group("title"), 300), "link": urljoin("https://www.gob.pe/", m.group("href")),
                      "published": parse_date(m.group("dt").split(".")[0], LIMA, now),
                      "summary": clean_summary(desc.group(1) if desc else ""), "categories": []})
    if not items:
        raise FeedError("la página de gob.pe no tiene notas con el formato esperado")
    p = _finish(Parsed("gobpe-html", items))
    p.items.sort(key=lambda i: i["published"] or "", reverse=True)
    return p


_ENTITY_DECL_RE = re.compile(r"<!ENTITY", re.I)


def parse(body: bytes, base_url: str = "", default_tz: timezone = timezone.utc,
          now: Optional[datetime] = None, adapter: str = "feed") -> Parsed:
    """Lee un feed en cualquiera de los formatos admitidos, reparando lo reparable.

    ``adapter="gobpe"`` lee en cambio un listado de noticias de gob.pe."""
    now = now or datetime.now(timezone.utc)
    if adapter == "gobpe":
        return parse_gobpe(body, base_url, now)
    if len(body) > MAX_FEED_BYTES:
        raise FeedError("feed demasiado grande")
    if not body.strip():
        raise FeedError("respuesta vacía")
    if body.lstrip(b"\xef\xbb\xbf \t\r\n")[:1] in (b"{", b"["):
        p = _json_feed(body, base_url, default_tz, now)
        return _finish(p)
    repairs: list[str] = []
    text = _decode(body, repairs)
    if _ENTITY_DECL_RE.search(text):
        raise FeedError("el feed declara entidades XML; se rechaza")
    head = text[:3000].lower()
    if not _ROOT_RE.search(text[:20000]) and ("<html" in head or "<!doctype html" in head):
        raise FeedError("la respuesta es una página HTML, no un feed")
    try:
        root = ET.fromstring(_DECL_RE.sub("", text, count=1).lstrip().encode("utf-8"))
    except ET.ParseError as exc:
        error = str(exc)[:80]
        text = _repair_text(text, repairs)
        try:
            root = ET.fromstring(text.encode("utf-8"))
        except ET.ParseError:
            repairs.append(f"XML inválido ({error})")
            root = _salvage(text, repairs)
    tag = _local(root.tag)
    if tag == "feed":
        title, base = _first(root, "title"), next((l.get("href", "") for l in _children(root, "link")
                                                    if l.get("rel", "alternate") == "alternate"), "")
        base = _abs(base, base_url) or base_url
        items = [_atom_entry(e, base, default_tz, now) for e in _children(root, "entry")]
        fmt = "atom"
    elif tag in ("rss", "RDF"):
        chan = (_children(root, "channel") or [root])[0]
        title = _first(chan, "title")
        base = _abs(_first(chan, "link"), base_url) or base_url
        items = [_rss_item(e, base, default_tz, now) for e in root.iter() if _local(e.tag) == "item"]
        fmt = "rss1" if tag == "RDF" else f"rss{root.get('version', '2.0')}"
    else:
        raise FeedError(f"raíz XML inesperada: {root.tag[:60]}")
    return _finish(Parsed(fmt, items, repairs, clean_text(title, 200), base))


def _finish(p: Parsed) -> Parsed:
    seen, out = set(), []
    for i in p.items:
        if not i["title"] or not i["link"].startswith(("http://", "https://")) or i["link"] in seen:
            continue
        seen.add(i["link"])
        out.append(i)
    if p.items and not out:
        p.repairs.append("ninguna entrada con título y enlace válido")
    p.items = out
    return p
