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
import io
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from .feedparse import LIMA, FeedError, parse as parse_any


@dataclass(frozen=True)
class Feed:
    id: str
    name: str
    region: str  # "peru" | "mundo"
    url: str
    lang: str = "es"
    #: "general": medio general (se exige un término ENSO);
    #: "hazard": feed de emergencias o clima (basta un peligro asociado).
    #: "local": medio regional (basta un peligro: lluvias, huaico, friaje…).
    scope: str = "general"
    stale_days: int = 7
    #: "gobierno" | "diario" | "radio" | "tv" | "digital" | "agregador" | "organismo"
    kind: str = "diario"
    #: Código UBIGEO de 2 dígitos del departamento que cubre el medio, si es regional.
    department: Optional[str] = None
    #: "feed" (RSS/Atom/JSON Feed) o "gobpe" (listado de noticias de gob.pe, sin RSS).
    adapter: str = "feed"

    @property
    def fixture(self) -> str:
        """Nombre del archivo capturado (fixtures y archivo crudo)."""
        return f"news-{self.id}.{'html' if self.adapter == 'gobpe' else 'xml'}"


_GN = "https://news.google.com/rss/search?q="

#: Catálogo de feeds verificado en vivo desde GitHub Actions el 21 de octubre
#: de 2026 (ver docs/catalogo-fuentes.md, donde también figuran los
#: descartados). El estado de cada uno se vuelve a verificar en cada corrida
#: y se publica en ``news/feeds.json``.
FEEDS: list[Feed] = [
    # Perú
    Feed("andina", "Andina (agencia estatal)", "peru", "https://andina.pe/agencia/rss/3.xml", kind="gobierno"),
    Feed("elcomercio", "El Comercio", "peru", "https://elcomercio.pe/arcio/rss/"),
    Feed("gestion", "Gestión", "peru", "https://gestion.pe/arcio/rss/"),
    Feed("correo", "Diario Correo", "peru", "https://diariocorreo.pe/arcio/rss/"),
    Feed("larepublica", "La República", "peru", "https://larepublica.pe/rss/sociedad.xml"),
    Feed("rpp", "RPP Noticias", "peru", "https://rpp.pe/rss", kind="radio"),
    Feed("infobae-peru", "Infobae Perú", "peru", "https://www.infobae.com/arc/outboundfeeds/rss/category/peru/",
         kind="digital"),
    Feed("caretas", "Caretas", "peru", "https://caretas.pe/feed/"),
    Feed("perureports", "Peru Reports", "peru", "https://perureports.com/feed/", lang="en", kind="digital"),
    Feed("gnews-peru", "Google Noticias Perú (búsqueda El Niño)", "peru",
         _GN + "%22El%20Ni%C3%B1o%22%20OR%20ENFEN%20OR%20%22Ni%C3%B1o%20costero%22&hl=es-419&gl=PE&ceid=PE:es-419",
         scope="hazard", stale_days=3, kind="agregador"),
    # Mundo
    Feed("gnews-world", "Google News (search El Niño)", "mundo",
         _GN + "%22El%20Ni%C3%B1o%22%20OR%20%22La%20Ni%C3%B1a%22%20OR%20ENSO&hl=en-US&gl=US&ceid=US:en",
         lang="en", scope="hazard", stale_days=3, kind="agregador"),
    Feed("bbc-mundo", "BBC News Mundo", "mundo", "https://feeds.bbci.co.uk/mundo/rss.xml", kind="digital"),
    Feed("un-news-clima", "Noticias ONU · Clima", "mundo",
         "https://news.un.org/feed/subscribe/es/news/topic/climate-change/feed/rss.xml", scope="hazard", stale_days=14, kind="organismo"),
    Feed("gdacs", "GDACS (alertas de desastres)", "mundo", "https://www.gdacs.org/xml/rss.xml", lang="en", scope="hazard",
         kind="organismo"),
    Feed("carbonbrief", "Carbon Brief", "mundo", "https://www.carbonbrief.org/feed/", lang="en", stale_days=14, kind="digital"),
    Feed("ciifen", "CIIFEN", "mundo", "https://ciifen.org/feed/", scope="hazard", stale_days=120, kind="organismo"),
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
#: Peligros concretos para medios regionales (sin «emergencia» ni «clima», demasiado amplios).
LOCAL_RE = re.compile(
    r"\b(lluvias?|precipitaci[oó]n(es)?|huaicos?|inundaci[oó]n(es)?|inundad[oa]s?|desbordes?|desbord[oó]|"
    r"crecida|caudal|sequ[ií]as?|d[eé]ficit h[ií]drico|friaje|heladas?|nevadas?|granizadas?|oleajes?|"
    r"deslizamientos?|derrumbes?|aluvi[oó]n|activaci[oó]n de quebradas?|quebradas? activad|damnificad[oa]s?|"
    r"estado de emergencia|alerta (roja|naranja|amarilla)|senamhi|indeci|coer|coen|cenepred|"
    r"temperatura del mar|anchoveta|pesca artesanal|dengue)\b", re.I)
PERU_RE = re.compile(r"\b(per[uú]|peruan[oa]s?|lima|piura|tumbes|lambayeque|la libertad|ica|arequipa|"
                     r"ancash|[aá]ncash|loreto|cusco|puno|cajamarca|jun[ií]n)\b", re.I)


def relevance(feed: Feed, title: str, summary: str) -> Optional[str]:
    """Motivo por el que una entrada es relevante, o None."""
    text = f"{title} {summary}"
    if ENSO_RE.search(text):
        return "enso"
    if feed.scope == "hazard" and HAZARD_RE.search(text) and (feed.region == "peru" or PERU_RE.search(text)):
        return "impacto"
    if feed.scope == "local" and LOCAL_RE.search(text):
        return "impacto"
    return None


# --- Lectura de RSS/Atom -----------------------------------------------------
# El lector tolerante (reparaciones, formatos, fechas) está en ``feedparse``.

def parse_feed(body: bytes, base_url: str = "", adapter: str = "feed") -> list[dict]:
    """Entradas homologadas de un feed (RSS 2.0/1.0, Atom, JSON Feed o listado de gob.pe)."""
    return parse_any(body, base_url=base_url, adapter=adapter).items


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


def _kind(i: dict) -> str:
    """Tipo de fuente para entradas del histórico anteriores a este campo."""
    f = FEED_BY_ID.get(i["feed"])
    return f.kind if f else "diario"


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
        places = list({p["code"]: p for i in its for p in (i.get("places") or [])}.values())
        out.append({
            "id": lead["id"], "region": g["region"], "title": lead["title"],
            "summary": _first_sentence(summary) if summary else "",
            "first": lead.get("published") or lead["first_seen"],
            "last": max(i.get("published") or i["first_seen"] for i in its),
            "relevance": "enso" if any(i["relevance"] == "enso" for i in its) else "impacto",
            "count": len(its), "outlets": outlets,
            "kinds": list(dict.fromkeys(i.get("kind") or _kind(i) for i in its)),
            "departments": list(dict.fromkeys(d for i in its for d in (i.get("departments") or []))),
            "places": places[:6],
            "links": [{"title": i["title"], "url": i["link"], "outlet": _outlet(i), "published": i.get("published"),
                       "kind": i.get("kind") or _kind(i)}
                      for i in its][:8],
        })
    out.sort(key=lambda g: (g["last"], g["count"]), reverse=True)
    return out


# --- Histórico de solo anexar y CSV -------------------------------------------

CSV_FIELDS = ["first_seen", "published", "region", "kind", "feed", "outlet", "relevance", "departments", "places",
              "title", "summary", "link", "id"]


def _csv_value(i: dict, k: str) -> str:
    if k == "departments":
        from .geo import department_names
        names = department_names()
        return "; ".join(names.get(c, c) for c in i.get("departments") or [])
    if k == "places":
        return "; ".join(p["name"] for p in i.get("places") or [])
    return i.get(k) or ""


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
        w.writerow({k: _csv_safe(_csv_value(i, k)) for k in CSV_FIELDS})
    return buf.getvalue()


# --- Recolección -------------------------------------------------------------

def _by_host(feeds: list[Feed]) -> list[list[Feed]]:
    """Feeds agrupados por servidor: cada grupo se descarga en serie (cortesía), los grupos en paralelo."""
    groups: dict[str, list[Feed]] = {}
    for f in feeds:
        groups.setdefault(re.sub(r"^https?://([^/]+).*", r"\1", f.url), []).append(f)
    return list(groups.values())


def _read_feed(f: Feed, fetch, now: datetime) -> tuple[dict, list[dict], Optional[bytes]]:
    from .geo import gazetteer

    seen_at = now.isoformat(timespec="seconds")
    st = {"id": f.id, "name": f.name, "region": f.region, "url": f.url, "lang": f.lang, "scope": f.scope,
          "kind": f.kind, "department": f.department, "checkedAt": seen_at, "ok": False, "items": 0,
          "relevant": 0, "latest": None, "active": False, "error": "", "format": None, "repairs": []}
    code, body, ctype, err = fetch(f.url)
    st["httpStatus"] = code
    if code != 200 or not body:
        st["error"] = err or f"HTTP {code}"
        return st, [], None
    try:
        parsed = parse_any(body, base_url=f.url, default_tz=LIMA if f.region == "peru" else timezone.utc, now=now,
                           adapter=f.adapter)
    except FeedError as exc:
        st["error"] = str(exc)
        return st, [], body
    entries = parsed.items
    dates = [e["published"] for e in entries if e["published"]]
    st.update({"ok": True, "items": len(entries), "latest": max(dates) if dates else None,
               "format": parsed.format, "repairs": parsed.repairs})
    st["active"] = bool(st["latest"]) and st["latest"] >= (now - timedelta(days=f.stale_days)).isoformat()
    if not entries:
        st["error"] = "feed sin entradas"
    future = (now + timedelta(hours=2)).isoformat()
    gz = gazetteer()
    found = []
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
        tag = gz.tag([title, e["summary"], " · ".join(e.get("categories") or [])],
                     peru_context=f.region == "peru", default_dep=f.department)
        item = {"id": item_id(e["link"], e["title"]), "first_seen": seen_at, "published": published,
                "region": f.region, "feed": f.id, "kind": f.kind, "outlet": outlet, "relevance": why,
                "title": title, "summary": e["summary"], "link": e["link"]}
        if tag:
            item["departments"] = tag["departments"]
            item["places"] = [{k: p[k] for k in ("code", "level", "name")} for p in tag["places"]]
            item["geoSource"] = tag["source"]
        found.append(item)
    return st, found, body


def collect(fetch, now: datetime, feeds: Optional[list[Feed]] = None,
            workers: int = 8) -> tuple[list[dict], list[dict], dict[str, bytes]]:
    """Descarga los feeds. ``fetch(url)`` devuelve (estado, cuerpo, tipo, error) y debe ser seguro entre hilos.

    Devuelve (entradas relevantes, estado por feed, cuerpos crudos por feed), en el orden del catálogo.
    """
    from concurrent.futures import ThreadPoolExecutor

    feeds = FEEDS if feeds is None else feeds
    results: dict[str, tuple] = {}

    def run_group(group: list[Feed]) -> None:
        for f in group:
            results[f.id] = _read_feed(f, fetch, now)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(run_group, _by_host(feeds)))
    found, status, raw = [], [], {}
    for f in feeds:
        st, items, body = results[f.id]
        status.append(st)
        found.extend(items)
        if body is not None:
            raw[f.id] = body
    return found, status, raw
