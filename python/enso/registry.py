"""Registro único de fuentes: qué se descarga, cómo y por qué canal.

Es la fuente de verdad que leen el pipeline (GitHub Actions), el recolector
del Perú (``servidor-peru``) y el flujo de n8n. Se genera con
``python -m tools.build_registry`` en ``registry/sources.json`` a partir de:

* los feeds de noticias (``news.FEEDS``), las fuentes oficiales
  (``observatory.SOURCES``) y las páginas que se recolectan desde el Perú;
* las mediciones de alcance (``registry/reachability.json``): desde dónde
  responde cada URL, por red: los ejecutores de GitHub Actions, el servidor de
  n8n (ambos en EE. UU.) y el servidor del Perú.

Regla de canales, por URL: una URL va por ``peru-server`` si y solo si está
geobloqueada (no responde desde ninguna red de EE. UU. y sí desde el Perú, o
no responde desde EE. UU. por bloqueo y aún no hay medición desde el Perú).
Las demás van por ``actions`` (la actualización diaria) y ``n8n`` (canal
alternativo); si una de las dos redes se midió y no responde mientras la otra
sí, solo por la que responde (p. ej. un servidor que corta a n8n en AWS y
atiende a Actions). ``by_url`` guarda el estado y los canales de cada URL (la
principal y sus réplicas) y ``channels`` es la unión: el portal del ENFEN no
resuelve desde Azure ni desde AWS y se pide desde el Perú, mientras que su
réplica en la DHN responde a Actions. ``geoblocked`` es verdadero si alguna URL
de la fuente necesita el servidor del Perú.

Método de acceso, de lo más simple a lo más complejo (``tier``):
  1 ``api`` / ``feed`` / ``download`` — interfaz, feed o archivo publicado;
  2 ``html`` — página HTML leída con expresiones regulares;
  3 ``hidden-api`` — el JSON que la propia página consulta (wp-json, ArcGIS…);
  4 ``browser`` — navegador sin pantalla (Playwright), solo si no hay otra vía;
  5 ``hosted`` — servicio externo de rastreo (Firecrawl…), último recurso.
Nunca se evaden CAPTCHAs ni verificaciones antirobots: una fuente así se
marca ``challenge`` y se lee desde el Perú, si allí responde, o de otra fuente.
Si el robots.txt del servidor prohíbe la ruta, la fuente queda sin canales
(``robots-disallowed``) hasta que la institución lo permita o publique otra vía.
Excepción, decidida el 21 de octubre de 2026: los feeds de noticias (Google
Noticias, Noticias ONU, Sin Rodeos) se leen como lo hace un lector de feeds,
solo desde Actions y como mucho una vez al día (``by_url[url]["reader"]``,
``READER_MIN_HOURS``); robots.txt sigue rigiendo todo lo demás y el rastreo.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

SCHEMA = "enso-source-registry/1"
REACH_SCHEMA = "enso-reachability/2"  # /2: mediciones por red y punto de medición
ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "registry" / "sources.json"
REACHABILITY = ROOT / "registry" / "reachability.json"

METHODS = {"api": 1, "feed": 1, "download": 1, "html": 2, "hidden-api": 3, "browser": 4, "hosted": 5}
EXPECT = {"rss", "html", "pdf", "json", "text", "csv"}
CHANNELS = ("actions", "n8n", "peru-server")
#: Clases de resultado de una medición (el mismo clasificador en Actions, n8n y el Perú).
CLASSES = {"ok", "http-403", "http-4xx", "http-5xx", "timeout", "connect", "dns", "tls", "challenge", "empty", "robots"}
#: Clases que, desde EE. UU., indican bloqueo y no caída (el servidor existe pero no atiende a la nube).
BLOCK_CLASSES = {"http-403", "timeout", "connect", "challenge", "dns"}
#: Un feed de noticias que su robots.txt no permite se pide como un lector de feeds: solo desde Actions y
#: no antes de estas horas desde la última lectura buena (decisión del 21 de octubre de 2026).
READER_MIN_HOURS = 20
READER_CHANNELS = ["actions"]


@dataclass
class Entry:
    id: str
    group: str  # institución o medio (slug)
    name: str
    institution: str
    url: str  # exactamente lo que pide el pipeline (el recolector empareja por URL)
    expect: str  # rss | html | pdf | json | text | csv
    method: str  # ver METHODS
    kind: str  # feed | dataset | page | document-list | scraper
    home: str = ""  # página para personas (el enlace «fuente en vivo»)
    alt_urls: list[str] = field(default_factory=list)
    alt_expect: list[str] = field(default_factory=list)  # lo que devuelve cada URL de alt_urls, en el mismo orden
    hazards: list[str] = field(default_factory=list)
    interval_minutes: int = 1440
    parser: str = ""  # «módulo:función» que interpreta la respuesta (en Actions)
    scraper: Optional[str] = None  # «módulo:función» para recorridos de varios pasos
    needs_browser: bool = False
    follow: Optional[dict] = None  # {"pattern": regex, "max": n}: documentos enlazados desde un listado
    department: Optional[str] = None
    archive: bool = True  # se publica la copia descargada como respaldo
    notes: str = ""
    reader: bool = False  # feed de noticias: si robots.txt lo prohíbe, se lee como un lector de feeds


def _slug(text: str) -> str:
    import unicodedata

    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def _feed_entries() -> list[Entry]:
    from . import news

    out = []
    for f in news.FEEDS:
        host = urlparse(f.url).netloc
        expect, method = ADAPTER_KIND.get(f.adapter, ("rss", "feed"))
        parser = "enso.feedparse:parse" if f.adapter in ("feed", "gobpe") else "enso.hazardparse:parse"
        out.append(Entry(
            id=f"news-{f.id}", group=_slug(f.name.split("·")[0]) or host, name=f.name,
            institution=f.name.split("·")[0].strip(), url=f.url, expect=expect,
            method=method, kind="feed", home=f"https://{host}/",
            hazards=list(f.covers) or (["enso"] if f.scope == "general" else []), interval_minutes=1440,
            parser=parser + (f" (adapter={f.adapter})" if f.adapter != "feed" else ""), department=f.department,
            notes=f"tipo de medio: {f.kind}; alcance: {f.scope}", reader=f.adapter == "feed" and not f.covers))
    return out


#: Qué devuelve cada lector de ``news`` (``expect``) y cómo se accede (``method``).
ADAPTER_KIND = {"feed": ("rss", "feed"), "indeci-coen": ("rss", "feed"), "gobpe": ("html", "html"),
                "dhn": ("html", "html"), "dhn-avisos": ("html", "html"), "cenvul": ("html", "html"), "telegram": ("html", "html"),
                "geojson": ("json", "api"), "arcgis": ("json", "api"), "ptwc-text": ("text", "download"),
                "firms": ("csv", "download")}


def _kind_of(url: str) -> tuple[str, str]:
    """Qué devuelve la URL (``expect``) y cómo se lee (``method``), según su forma."""
    path = urlparse(url).path.lower()
    if "wp-json" in url:
        return "json", "api"
    if path.endswith((".txt", ".for", ".data", ".ascii", ".indices")) or re.search(r"/indices/[a-z0-9]+$", path):
        return "text", "download"
    if path.endswith(".pdf"):
        return "pdf", "download"
    if path.endswith(".csv"):
        return "csv", "download"
    return "html", "html"


def _source_entries() -> list[Entry]:
    from .observatory import SOURCES

    out = []
    for s in SOURCES:
        url = s.urls[0]
        expect, method = _kind_of(url)
        follow = None
        if s.id == "enfen-comunicados":
            follow = {"pattern": r"https?://[^\"'\s]+\.pdf", "max": 8}
        out.append(Entry(
            id=s.id, group=_slug(s.institution.split("/")[0]), name=s.product, institution=s.institution,
            url=url, alt_urls=list(s.urls[1:]), alt_expect=[_kind_of(u)[0] for u in s.urls[1:]],
            expect=expect, method=method, kind="dataset",
            home=s.docs or url, hazards=["enso"], interval_minutes=1440, parser=f"enso.observatory:{s.id}",
            follow=follow))
    return out


#: Páginas del recolector del Perú que el pipeline ya lee: lector, peligros y para qué.
_COLLECTOR_READERS = {
    "https://www.senamhi.gob.pe/?p=aviso-meteorologico": (
        "enso.senamhi_avisos:parse", ["lluvias"],
        "se archiva desde el Perú; da el nivel (amarillo, naranja o rojo) y el inicio y fin a los avisos "
        "meteorológicos del SENAMHI que llegan por Telegram y por el COEN (copia de hasta 7 días)"),
}


def _collector_entries(known: set[str]) -> list[Entry]:
    """Páginas que el recolector del Perú ya baja: casi todas solo se archivan; las de ``_COLLECTOR_READERS``
    ya las lee el pipeline."""
    try:
        from tools import peru_collector
    except ImportError:
        return []
    out = []
    ids: set[str] = set()
    for group, urls in peru_collector.SOURCES.items():
        for url in urls:
            if url in known:
                continue
            p = urlparse(url)
            name = (p.path.strip("/") or p.netloc) + (f"?{p.query}" if p.query else "")
            expect = getattr(peru_collector, "EXPECT", {}).get(url, "html")  # JSON y XML de servicios GIS
            sid = f"{group}-{_slug(name) or 'portada'}"
            if sid in ids:  # dos pedidos al mismo servicio solo difieren después de los 40 caracteres del slug
                sid += "-" + hashlib.sha1(url.encode()).hexdigest()[:6]
            ids.add(sid)
            parser, hazards, notes = _COLLECTOR_READERS.get(
                url, (None, [], "se archiva desde el Perú; aún sin intérprete en el pipeline"))
            out.append(Entry(
                id=sid, group=group, name=f"{group.upper()}: {name}",
                institution=group.upper(), url=url, expect=expect,
                method="html" if expect == "html" else "api" if expect == "json" else "download",
                kind="page" if expect == "html" else "dataset", home=url,
                hazards=hazards, notes=notes, **({"parser": parser} if parser else {})))
    return out


# --- Alcance medido --------------------------------------------------------------

#: Puntos de medición agrupados por red: los ejecutores de GitHub Actions (Azure, EE. UU.), el servidor de
#: n8n (nube de EE. UU.) y el servidor del Perú. «No responde a GitHub» no es lo mismo que «geobloqueado».
VANTAGE_GROUPS = ("actions", "n8n", "peru")


def vantage_group(vantage: str) -> str:
    v = (vantage or "").lower()
    if v.startswith("peru"):
        return "peru"
    if v.startswith(("github-actions", "n8n-actions", "actions")):
        return "actions"  # n8n corriendo en un ejecutor de Actions mide la misma red
    if v.startswith("n8n"):
        return "n8n"
    return "actions"


def _groups(entry: dict) -> dict[str, dict[str, dict]]:
    """Mediciones de una URL como {grupo: {vantage: registro}}; acepta también la forma antigua {"us": r, "peru": r}."""
    out: dict[str, dict[str, dict]] = {}
    for k, v in (entry or {}).items():
        if not isinstance(v, dict):
            continue
        if "class" in v:  # forma antigua: un registro por lado
            g = "peru" if k == "peru" else vantage_group(v.get("vantage") or k)
            out.setdefault(g, {})[v.get("vantage") or k] = v
        elif k in VANTAGE_GROUPS:
            out.setdefault(k, {}).update({vk: vr for vk, vr in v.items() if isinstance(vr, dict)})
    return out


def load_reachability(path: Path = REACHABILITY) -> dict:
    """Mediciones por URL: {url: {"actions" | "n8n" | "peru": {vantage: registro}}} (vacío si no hay archivo)."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {u: _groups(e) for u, e in data.get("urls", {}).items()}


def _best(recs: dict[str, dict]) -> Optional[dict]:
    """La medición que cuenta en un grupo: la más reciente que respondió, o la más reciente."""
    rs = list((recs or {}).values())
    ok = [r for r in rs if r.get("class") == "ok"]
    return max(ok or rs, key=lambda r: r.get("at") or "") if rs else None


def unmeasured(rec: dict) -> bool:
    """«aborted» de n8n es su nodo HTTP cortando la petición, no la red: desde el mismo ejecutor curl y Node
    reciben 200 en segundos. No cuenta como medición (ni a favor ni en contra)."""
    return (rec.get("class") == "timeout" and rec.get("detail") == "aborted"
            and str(rec.get("vantage") or "").lower().startswith("n8n"))


def geoblock(url: str, reach: dict) -> dict:
    """Estado de geobloqueo de una URL a partir de lo medido desde cada red (EE. UU.: Actions y n8n; Perú)."""
    groups = {g: kept for g, rs in _groups(reach.get(url) or {}).items()
              if (kept := {v: r for v, r in rs.items() if not unmeasured(r)})}
    act, n8n, pe = (_best(groups.get(g)) for g in VANTAGE_GROUPS)
    us_recs = [r for r in (act, n8n) if r]
    us = max([r for r in us_recs if r.get("class") == "ok"] or us_recs, key=lambda r: r.get("at") or "") if us_recs else None
    open_from = [g for g, r in zip(VANTAGE_GROUPS, (act, n8n, pe)) if r and r.get("class") == "ok"]
    every = [r for g in groups.values() for r in g.values()]
    out = {"status": "unknown", "measured_at": max((r.get("at") for r in every if r.get("at")), default=None),
           "from": sorted({r.get("vantage") or g for g, rs in groups.items() for r in rs.values()}),
           "open_from": open_from, "us": us, "peru": pe, "actions": act, "n8n": n8n}
    if any(r.get("class") == "robots" for r in every):
        out["status"] = "robots-disallowed"  # el servidor pide no automatizar esta ruta: no la pide nadie
    elif any(g in open_from for g in ("actions", "n8n")):
        out["status"] = "open"
    elif us_recs and pe and pe.get("class") == "ok":
        out["status"] = "geoblocked"
    elif us_recs and pe:
        out["status"] = "down"  # no responde ni desde EE. UU. ni desde el Perú
    elif us_recs and all(r.get("class") in BLOCK_CLASSES for r in us_recs):
        out["status"] = "suspected-geoblock"
    elif us_recs:
        out["status"] = "down"
    return out


def channels_for(status: str, open_from: Optional[list[str]] = None, measured: Optional[list[str]] = None) -> list[str]:
    """Quién la recolecta: ``peru-server`` si y solo si está (o parece) geobloqueada; ninguno si robots.txt lo
    prohíbe; si no, Actions y n8n, salvo el que se midió y no responde mientras el otro sí."""
    if status == "robots-disallowed":
        return []
    if status in ("geoblocked", "suspected-geoblock"):
        return ["peru-server"]
    if status == "open" and open_from is not None:
        measured = measured or []
        return [c for c in ("actions", "n8n") if c in open_from or c not in measured]
    return ["actions", "n8n"]


def build(reach: Optional[dict] = None, now: Optional[datetime] = None) -> dict:
    reach = load_reachability() if reach is None else reach
    entries = _feed_entries() + _source_entries()
    known = {e.url for e in entries} | {u for e in entries for u in e.alt_urls}
    entries += _collector_entries(known)
    sources = []
    for e in entries:
        by_url = {}
        for u in [e.url, *e.alt_urls]:
            g = geoblock(u, reach)
            by_url[u] = {"status": g["status"], "channels": channels_for(
                g["status"], g["open_from"], [k for k in ("actions", "n8n") if g.get(k)])}
            if e.reader and g["status"] == "robots-disallowed":
                by_url[u].update(channels=list(READER_CHANNELS), reader=True)
        d = {k: v for k, v in e.__dict__.items()
             if (v not in (None, [], "") or k in ("hazards", "alt_urls")) and k != "reader"}
        d["tier"] = METHODS[e.method]
        d["geoblock"] = geoblock(e.url, reach)  # la URL principal
        d["channels"] = [c for c in CHANNELS if any(c in r["channels"] for r in by_url.values())]
        d["geoblocked"] = True if "peru-server" in d["channels"] else (
            False if all(r["status"] == "open" for r in by_url.values()) else None)
        d["by_url"] = by_url
        sources.append(d)
    now = now or datetime.now(timezone.utc)
    return {"schema": SCHEMA, "generated_at": now.isoformat(timespec="seconds"),
            "rules": {"peru-server": "si y solo si geoblocked es true (alguna URL geobloqueada; ver by_url)",
                      "robots": "sin canales si robots.txt prohíbe la URL, salvo los feeds de noticias con "
                                f"reader: solo {'+'.join(READER_CHANNELS)}, como mucho cada {READER_MIN_HOURS} h",
                      "tiers": METHODS, "channels": list(CHANNELS)},
            "sources": sources}


def url_channels(reg: Optional[dict] = None) -> dict[str, list[str]]:
    """Canales de cada URL del registro (la principal y sus réplicas): qué recolector la pide.

    Lo usa el pipeline en GitHub Actions: una URL que Actions no alcanza se lee primero de las copias
    del Perú o de n8n, y una que robots.txt prohíbe (sin canales) no se pide. Vacío si no hay registro."""
    if reg is None:
        try:
            reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    if not isinstance(reg, dict) or reg.get("schema") != SCHEMA:
        return {}
    out: dict[str, list[str]] = {}
    for s in reg.get("sources") or []:
        by_url = s.get("by_url") or {s.get("url"): {"channels": s.get("channels") or []}}
        for u, r in by_url.items():
            if isinstance(u, str) and isinstance(r, dict):
                out[u] = list(r.get("channels") or [])
    return out


def reader_urls(reg: Optional[dict] = None) -> set[str]:
    """Feeds que robots.txt no permite y se leen como un lector de feeds (como mucho cada READER_MIN_HOURS)."""
    if reg is None:
        try:
            reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
    if not isinstance(reg, dict) or reg.get("schema") != SCHEMA:
        return set()
    return {u for s in reg.get("sources") or [] for u, r in (s.get("by_url") or {}).items()
            if isinstance(r, dict) and r.get("reader")}


def validate(reg: dict) -> list[str]:
    """Problemas del registro (vacío si está bien)."""
    errs = []
    if reg.get("schema") != SCHEMA:
        errs.append(f"schema distinto de {SCHEMA}")
    ids, urls = set(), set()
    for s in reg.get("sources", []):
        sid = s.get("id", "?")
        for k in ("id", "group", "name", "url", "expect", "method", "channels", "geoblock"):
            if k not in s:
                errs.append(f"{sid}: falta {k}")
        if sid in ids:
            errs.append(f"{sid}: id repetido")
        ids.add(sid)
        if s.get("url") in urls:
            errs.append(f"{sid}: URL repetida {s.get('url')}")
        urls.add(s.get("url"))
        if s.get("expect") not in EXPECT:
            errs.append(f"{sid}: expect «{s.get('expect')}» no válido")
        if s.get("method") not in METHODS or s.get("tier") != METHODS.get(s.get("method")):
            errs.append(f"{sid}: método o nivel no válido")
        by_url = s.get("by_url") or {s.get("url"): {"status": (s.get("geoblock") or {}).get("status"),
                                                   "channels": s.get("channels", [])}}
        for u, r in by_url.items():
            robots = r.get("status") == "robots-disallowed"
            reader = bool(r.get("reader"))
            if reader and not (robots and s.get("kind") == "feed" and r.get("channels") == READER_CHANNELS):
                errs.append(f"{sid}: «reader» solo para un feed que robots.txt prohíbe, y solo por {READER_CHANNELS}")
            elif not set(r.get("channels", [])) <= set(CHANNELS) or (not r.get("channels")) != (robots and not reader):
                errs.append(f"{sid}: canales no válidos para {u} (vacíos solo si robots.txt prohíbe la ruta)")
            if ("peru-server" in r.get("channels", [])) != (r.get("status") in ("geoblocked", "suspected-geoblock")):
                errs.append(f"{sid}: peru-server debe usarse si y solo si {u} está geobloqueada")
        if set(by_url) != {s.get("url"), *s.get("alt_urls", [])}:
            errs.append(f"{sid}: by_url no corresponde a url y alt_urls")
        union = [c for c in CHANNELS if any(c in r.get("channels", []) for r in by_url.values())]
        if s.get("channels") != union:
            errs.append(f"{sid}: channels debe ser la unión de los canales de cada URL")
        if ("peru-server" in s.get("channels", [])) != (s.get("geoblocked") is True):
            errs.append(f"{sid}: peru-server debe usarse si y solo si la fuente está geobloqueada")
        if s.get("alt_expect") and (len(s["alt_expect"]) != len(s.get("alt_urls", []))
                                    or not set(s["alt_expect"]) <= EXPECT):
            errs.append(f"{sid}: alt_expect no corresponde a alt_urls")
        if not str(s.get("url", "")).startswith(("http://", "https://")):
            errs.append(f"{sid}: URL no válida")
    return errs
