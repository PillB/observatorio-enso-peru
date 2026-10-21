"""Noticias: feeds RSS/Atom de medios del Perú y del mundo sobre El Niño.

Cada corrida:
  1. Descarga cada feed del catálogo ``FEEDS`` y registra su estado
     (responde, cuántas entradas, fecha de la más reciente). Un feed sin
     entradas nuevas en ``stale_days`` se marca inactivo.
  2. Se queda con las entradas que tratan del ENSO o de sus impactos en el
     Perú (``relevance``). Los feeds temáticos (ReliefWeb Perú, GDACS) usan
     un filtro más amplio de peligros.
  3. Agrega las nuevas al histórico de solo anexar ``news/items.jsonl``
     (una línea por entrada, nunca se reescriben las anteriores) y genera
     ``news/items.csv`` con todo el histórico.
  4. Agrupa las entradas similares de los últimos días (``cluster``): cada
     grupo lleva el titular más temprano, cuántos medios lo publicaron, un
     resumen extractivo y el enlace a cada fuente.

Solo se guarda lo que el medio publica en su feed (título, resumen, fecha
y enlace); no se copian los artículos completos.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class Feed:
    id: str
    name: str
    region: str  # "peru" | "mundo"
    url: str
    lang: str = "es"
    #: "general": medio general (se exige un término ENSO);
    #: "hazard": feed de emergencias o clima (basta un peligro asociado).
    scope: str = "general"
    stale_days: int = 7


_GN = "https://news.google.com/rss/search?q="

#: Catálogo de feeds verificado en vivo desde GitHub Actions el 21 de octubre
#: de 2026 (ver docs/catalogo-fuentes.md, donde también figuran los
#: descartados). El estado de cada uno se vuelve a verificar en cada corrida
#: y se publica en ``news/feeds.json``.
FEEDS: list[Feed] = [
    # Perú
    Feed("andina", "Andina (agencia estatal)", "peru", "https://andina.pe/agencia/rss/3.xml"),
    Feed("elcomercio", "El Comercio", "peru", "https://elcomercio.pe/arcio/rss/"),
    Feed("gestion", "Gestión", "peru", "https://gestion.pe/arcio/rss/"),
    Feed("correo", "Diario Correo", "peru", "https://diariocorreo.pe/arcio/rss/"),
    Feed("larepublica", "La República", "peru", "https://larepublica.pe/rss/sociedad.xml"),
    Feed("rpp", "RPP Noticias", "peru", "https://rpp.pe/rss"),
    Feed("infobae-peru", "Infobae Perú", "peru", "https://www.infobae.com/arc/outboundfeeds/rss/category/peru/"),
    Feed("caretas", "Caretas", "peru", "https://caretas.pe/feed/"),
    Feed("perureports", "Peru Reports", "peru", "https://perureports.com/feed/", lang="en"),
    Feed("gnews-peru", "Google Noticias Perú (búsqueda El Niño)", "peru",
         _GN + "%22El%20Ni%C3%B1o%22%20OR%20ENFEN%20OR%20%22Ni%C3%B1o%20costero%22&hl=es-419&gl=PE&ceid=PE:es-419",
         scope="hazard", stale_days=3),
    # Mundo
    Feed("gnews-world", "Google News (search El Niño)", "mundo",
         _GN + "%22El%20Ni%C3%B1o%22%20OR%20%22La%20Ni%C3%B1a%22%20OR%20ENSO&hl=en-US&gl=US&ceid=US:en",
         lang="en", scope="hazard", stale_days=3),
    Feed("bbc-mundo", "BBC News Mundo", "mundo", "https://feeds.bbci.co.uk/mundo/rss.xml"),
    Feed("un-news-clima", "Noticias ONU · Clima", "mundo",
         "https://news.un.org/feed/subscribe/es/news/topic/climate-change/feed/rss.xml", scope="hazard", stale_days=14),
    Feed("gdacs", "GDACS (alertas de desastres)", "mundo", "https://www.gdacs.org/xml/rss.xml", lang="en", scope="hazard"),
    Feed("carbonbrief", "Carbon Brief", "mundo", "https://www.carbonbrief.org/feed/", lang="en", stale_days=14),
    Feed("ciifen", "CIIFEN", "mundo", "https://ciifen.org/feed/", scope="hazard", stale_days=120),
]

FEED_BY_ID = {f.id: f for f in FEEDS}

# --- Relevancia --------------------------------------------------------------

ENSO_RE = re.compile(
    r"\b(el ni[nñ]o|la ni[nñ]a|enso|ni[nñ]o costero|ni[nñ]a costera|enfen|icen|oscilaci[oó]n del sur|"
    r"fen[oó]meno del ni[nñ]o|anomal[ií]as? de (la )?temperatura del mar|calentamiento del mar|"
    r"temperatura superficial del mar|mar peruano|corriente de humboldt|niño 1\+2|niño 3\.4)\b", re.I)
HAZARD_RE = re.compile(
    r"\b(lluvias? (intensas?|fuertes?)|huaicos?|inundaci[oó]n(es)?|desbordes?|sequ[ií]as?|friaje|heladas?|"
    r"oleajes?|deslizamientos?|emergencia|senamhi|indeci|cenepred|imarpe|igp|aviso meteorol[oó]gico|"
    r"flood(s|ing)?|drought|heavy rain|landslides?|cyclone|tropical storm|climate|clima)\b", re.I)
PERU_RE = re.compile(r"\b(per[uú]|peruan[oa]s?|lima|piura|tumbes|lambayeque|la libertad|ica|arequipa|"
                     r"ancash|[aá]ncash|loreto|cusco|puno|cajamarca|jun[ií]n)\b", re.I)


def relevance(feed: Feed, title: str, summary: str) -> Optional[str]:
    """Motivo por el que una entrada es relevante, o None."""
    text = f"{title} {summary}"
    if ENSO_RE.search(text):
        return "enso"
    if feed.scope == "hazard" and HAZARD_RE.search(text) and (feed.region == "peru" or PERU_RE.search(text)):
        return "impacto"
    return None


# --- Lectura de RSS/Atom -----------------------------------------------------

ATOM = "{http://www.w3.org/2005/Atom}"
TAG_RE = re.compile(r"<[^>]+>")
MAX_FEED_BYTES = 5_000_000


class FeedError(ValueError):
    pass


def _clean(text: Optional[str], limit: int = 600) -> str:
    text = html.unescape(TAG_RE.sub(" ", html.unescape(text or "")))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _date(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    text = text.strip()
    try:
        d = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_feed(body: bytes) -> list[dict]:
    """Entradas de un RSS 2.0, RSS 1.0 (RDF) o Atom: título, enlace, fecha, resumen."""
    if len(body) > MAX_FEED_BYTES:
        raise FeedError("feed demasiado grande")
    head = body[:2048].lower()
    if b"<!entity" in body[:20000].lower():
        raise FeedError("el feed declara entidades XML; se rechaza")
    if b"<html" in head and b"<rss" not in head and b"<feed" not in head:
        raise FeedError("la respuesta es una página HTML, no un feed")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise FeedError(f"XML inválido: {exc}") from exc
    items = []
    if root.tag == f"{ATOM}feed":
        for e in root.findall(f"{ATOM}entry"):
            link = next((l.get("href") for l in e.findall(f"{ATOM}link") if l.get("rel", "alternate") == "alternate"), None)
            items.append({"title": _clean(e.findtext(f"{ATOM}title"), 300), "link": (link or "").strip(),
                          "published": _date(e.findtext(f"{ATOM}published") or e.findtext(f"{ATOM}updated")),
                          "summary": _clean(e.findtext(f"{ATOM}summary") or e.findtext(f"{ATOM}content"))})
    else:
        for e in root.iter():
            if not (e.tag == "item" or e.tag.endswith("}item")):
                continue

            def child(name: str) -> Optional[str]:
                for c in e:
                    if c.tag == name or c.tag.endswith("}" + name):
                        return c.text
                return None

            items.append({"title": _clean(child("title"), 300), "link": (child("link") or "").strip(),
                          "published": _date(child("pubDate") or child("date") or child("published")),
                          "summary": _clean(child("description") or child("encoded"))})
            src = next((c for c in e if c.tag == "source"), None)
            if src is not None and src.text:
                items[-1]["outlet"] = _clean(src.text, 120)
    if root.tag not in (f"{ATOM}feed", "rss") and not root.tag.endswith("RDF"):
        raise FeedError(f"raíz XML inesperada: {root.tag[:60]}")
    return [i for i in items if i["title"] and i["link"].startswith(("http://", "https://"))]


SOCIAL_RE = re.compile(r"(facebook|instagram|tiktok|twitter|youtube)\.com|//(www\.)?x\.com/|^(Facebook|Instagram|TikTok|X|YouTube)$", re.I)


def _strip_outlet(title: str, outlet: str) -> str:
    """Google Noticias termina los titulares con « - Medio»."""
    for sep in (" - ", " – ", " | "):
        if outlet and title.endswith(sep + outlet):
            return title[: -len(sep + outlet)].rstrip()
    return title


def item_id(link: str, title: str) -> str:
    return hashlib.sha256(f"{link.strip()}|{title.strip().lower()}".encode()).hexdigest()[:16]


# --- Agrupación de entradas similares ----------------------------------------

STOP = set("""a al ante con de del desde e el en entre es la las lo los para por que se sin su sus un una y o
the of in on to for and a an is are as at by from with its it this that""".split())


def _tokens(title: str) -> set[str]:
    t = unicodedata.normalize("NFKD", title.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    # Google Noticias añade « - Medio» al final del titular.
    t = re.sub(r"\s[-–|]\s[^-–|]{2,40}$", "", t)
    return {w.strip(".") for w in re.findall(r"[a-z0-9+.]{3,}", t) if w.strip(".") not in STOP and len(w.strip(".")) >= 3}


def _similar(a: set[str], b: set[str]) -> bool:
    if not a or not b:
        return False
    inter = len(a & b)
    return inter >= 3 and inter / min(len(a), len(b)) >= 0.6


def _first_sentence(text: str) -> str:
    m = re.match(r"(.{40,320}?[.!?])(\s|$)", text)
    return (m.group(1) if m else text[:280]).strip()


def _outlet(i: dict) -> str:
    return i.get("outlet") or (FEED_BY_ID[i["feed"]].name if i["feed"] in FEED_BY_ID else i["feed"])


def _without_title(i: dict) -> str:
    """El resumen sin el titular repetido al comienzo (algunos medios lo repiten)."""
    summ, title = i["summary"].strip(), i["title"].strip().rstrip(".")
    if summ.lower().startswith(title.lower()):
        summ = summ[len(title):].lstrip(" .:-–")
    return summ


def cluster(items: list[dict], now: datetime, days: int = 14) -> list[dict]:
    """Grupos de entradas similares de los últimos ``days`` días, más recientes primero."""
    since = (now - timedelta(days=days)).isoformat()
    recent = sorted((i for i in items if (i.get("published") or i["first_seen"]) >= since),
                    key=lambda i: i.get("published") or i["first_seen"])
    groups: list[dict] = []
    for it in recent:
        tok = _tokens(it["title"])
        for g in groups:
            if g["region"] == it["region"] and any(_similar(tok, t) for t in g["_tokens"]):
                g["items"].append(it)
                g["_tokens"].append(tok)
                break
        else:
            groups.append({"region": it["region"], "items": [it], "_tokens": [tok]})
    out = []
    for g in groups:
        # La misma nota puede llegar por el feed del medio y por Google Noticias.
        uniq: dict = {}
        for i, tok in zip(g["items"], g["_tokens"]):
            uniq.setdefault((_outlet(i).lower(), frozenset(tok)), i)
        its = list(uniq.values())
        lead = its[0]
        own = [x for x in (_without_title(i) for i in its) if x and not _tokens(x) <= _tokens(lead["title"]) | _tokens(_outlet(lead))]
        summary = max(own, key=len, default="")
        outlets = list(dict.fromkeys(_outlet(i) for i in its))
        out.append({
            "id": lead["id"], "region": g["region"], "title": lead["title"],
            "summary": _first_sentence(summary) if summary else "",
            "first": lead.get("published") or lead["first_seen"],
            "last": max(i.get("published") or i["first_seen"] for i in its),
            "relevance": "enso" if any(i["relevance"] == "enso" for i in its) else "impacto",
            "count": len(its), "outlets": outlets,
            "links": [{"title": i["title"], "url": i["link"], "outlet": _outlet(i), "published": i.get("published")}
                      for i in its][:8],
        })
    out.sort(key=lambda g: (g["last"], g["count"]), reverse=True)
    return out


# --- Histórico de solo anexar y CSV -------------------------------------------

CSV_FIELDS = ["first_seen", "published", "region", "feed", "outlet", "relevance", "title", "summary", "link", "id"]


def read_jsonl(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue  # una línea dañada no invalida el resto del histórico
        if isinstance(obj, dict) and obj.get("id") and obj.get("link"):
            out.append(obj)
    return out


def new_lines(history: list[dict], fresh: list[dict]) -> list[dict]:
    """Entradas de ``fresh`` que aún no están en el histórico (por id)."""
    seen = {h["id"] for h in history}
    out = []
    for f in fresh:
        if f["id"] not in seen:
            seen.add(f["id"])
            out.append(f)
    return out


def _csv_safe(v) -> str:
    """Evita que una hoja de cálculo interprete un titular como fórmula."""
    s = str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def to_csv(items: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for i in sorted(items, key=lambda i: i.get("published") or i["first_seen"], reverse=True):
        w.writerow({k: _csv_safe(i.get(k) or "") for k in CSV_FIELDS})
    return buf.getvalue()


# --- Recolección -------------------------------------------------------------

def collect(fetch, now: datetime) -> tuple[list[dict], list[dict], dict[str, bytes]]:
    """Descarga todos los feeds. ``fetch(url)`` devuelve (estado, cuerpo, tipo, error).

    Devuelve (entradas relevantes, estado por feed, cuerpos crudos por feed).
    """
    found, status, raw = [], [], {}
    seen_at = now.isoformat(timespec="seconds")
    for f in FEEDS:
        st = {"id": f.id, "name": f.name, "region": f.region, "url": f.url, "lang": f.lang, "scope": f.scope,
              "checkedAt": seen_at, "ok": False, "items": 0, "relevant": 0, "latest": None, "active": False, "error": ""}
        code, body, ctype, err = fetch(f.url)
        st["httpStatus"] = code
        if code != 200 or not body:
            st["error"] = err or f"HTTP {code}"
            status.append(st)
            continue
        raw[f.id] = body
        try:
            entries = parse_feed(body)
        except FeedError as exc:
            st["error"] = str(exc)
            status.append(st)
            continue
        dates = [e["published"] for e in entries if e["published"]]
        st.update({"ok": True, "items": len(entries), "latest": max(dates) if dates else None})
        st["active"] = bool(st["latest"]) and st["latest"] >= (now - timedelta(days=f.stale_days)).isoformat()
        if not entries:
            st["error"] = "feed sin entradas"
        future = (now + timedelta(hours=2)).isoformat()
        for e in entries:
            outlet = e.get("outlet") or f.name
            if SOCIAL_RE.search(e["link"]) or SOCIAL_RE.search(outlet):
                continue  # publicaciones en redes sociales, no notas de prensa
            title = _strip_outlet(e["title"], outlet)
            why = relevance(f, title, e["summary"])
            if not why:
                continue
            st["relevant"] += 1
            published = e["published"]
            if published and published > future:
                # Algunos medios publican la hora local marcada como UTC.
                st["futureDates"] = st.get("futureDates", 0) + 1
                published = seen_at
            found.append({"id": item_id(e["link"], e["title"]), "first_seen": seen_at, "published": published,
                          "region": f.region, "feed": f.id, "outlet": outlet, "relevance": why,
                          "title": title, "summary": e["summary"], "link": e["link"]})
        status.append(st)
    return found, status, raw
