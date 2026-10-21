"""Registro único de fuentes: qué se descarga, cómo y por qué canal.

Es la fuente de verdad que leen el pipeline (GitHub Actions), el recolector
del Perú (``servidor-peru``) y el flujo de n8n. Se genera con
``python -m tools.build_registry`` en ``registry/sources.json`` a partir de:

* los feeds de noticias (``news.FEEDS``), las fuentes oficiales
  (``observatory.SOURCES``) y las páginas que se recolectan desde el Perú;
* las mediciones de alcance (``registry/reachability.json``): desde dónde
  responde cada URL (un servidor de EE. UU. —GitHub Actions o n8n en AWS— y
  el servidor del Perú).

Regla de canales: una fuente va por ``peru-server`` si y solo si está
geobloqueada (no responde desde EE. UU. y sí desde el Perú, o no responde
desde EE. UU. por bloqueo y aún no hay medición desde el Perú). Las demás van
por ``actions`` (la actualización diaria) y ``n8n`` (canal alternativo).

Método de acceso, de lo más simple a lo más complejo (``tier``):
  1 ``api`` / ``feed`` / ``download`` — interfaz, feed o archivo publicado;
  2 ``html`` — página HTML leída con expresiones regulares;
  3 ``hidden-api`` — el JSON que la propia página consulta (wp-json, ArcGIS…);
  4 ``browser`` — navegador sin pantalla (Playwright), solo si no hay otra vía;
  5 ``hosted`` — servicio externo de rastreo (Firecrawl…), último recurso.
Nunca se evaden CAPTCHAs ni verificaciones antirobots: una fuente así se
marca ``challenge`` y se lee desde el Perú, si allí responde, o de otra fuente.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

SCHEMA = "enso-source-registry/1"
REACH_SCHEMA = "enso-reachability/1"
ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "registry" / "sources.json"
REACHABILITY = ROOT / "registry" / "reachability.json"

METHODS = {"api": 1, "feed": 1, "download": 1, "html": 2, "hidden-api": 3, "browser": 4, "hosted": 5}
EXPECT = {"rss", "html", "pdf", "json", "text", "csv"}
CHANNELS = ("actions", "n8n", "peru-server")
#: Clases de resultado de una medición (el mismo clasificador en Actions, n8n y el Perú).
CLASSES = {"ok", "http-403", "http-4xx", "http-5xx", "timeout", "connect", "dns", "tls", "challenge", "empty"}
#: Clases que, desde EE. UU., indican bloqueo y no caída (el servidor existe pero no atiende a la nube).
BLOCK_CLASSES = {"http-403", "timeout", "connect", "challenge", "dns"}


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
    hazards: list[str] = field(default_factory=list)
    interval_minutes: int = 1440
    parser: str = ""  # «módulo:función» que interpreta la respuesta (en Actions)
    scraper: Optional[str] = None  # «módulo:función» para recorridos de varios pasos
    needs_browser: bool = False
    follow: Optional[dict] = None  # {"pattern": regex, "max": n}: documentos enlazados desde un listado
    department: Optional[str] = None
    archive: bool = True  # se publica la copia descargada como respaldo
    notes: str = ""


def _slug(text: str) -> str:
    import unicodedata

    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def _feed_entries() -> list[Entry]:
    from . import news

    out = []
    for f in news.FEEDS:
        host = urlparse(f.url).netloc
        gob = f.adapter == "gobpe"
        out.append(Entry(
            id=f"news-{f.id}", group=_slug(f.name.split("·")[0]) or host, name=f.name,
            institution=f.name.split("·")[0].strip(), url=f.url, expect="html" if gob else "rss",
            method="html" if gob else "feed", kind="feed", home=f"https://{host}/",
            hazards=["enso"] if f.scope == "general" else [], interval_minutes=1440,
            parser="enso.feedparse:parse" + (" (adapter=gobpe)" if gob else ""), department=f.department,
            notes=f"tipo de medio: {f.kind}; alcance: {f.scope}"))
    return out


def _source_entries() -> list[Entry]:
    from .observatory import SOURCES

    out = []
    for s in SOURCES:
        url = s.urls[0]
        path = urlparse(url).path.lower()
        if "wp-json" in url:
            expect, method = "json", "api"
        elif path.endswith((".txt", ".for", ".data", ".ascii")) or re.search(r"/indices/[a-z0-9]+$", path):
            expect, method = "text", "download"
        elif path.endswith(".pdf"):
            expect, method = "pdf", "download"
        else:
            expect, method = "html", "html"
        follow = None
        if s.id == "enfen-comunicados":
            follow = {"pattern": r"https?://[^\"'\s]+\.pdf", "max": 8}
        out.append(Entry(
            id=s.id, group=_slug(s.institution.split("/")[0]), name=s.product, institution=s.institution,
            url=url, alt_urls=list(s.urls[1:]), expect=expect, method=method, kind="dataset",
            home=s.docs or url, hazards=["enso"], interval_minutes=1440, parser=f"enso.observatory:{s.id}",
            follow=follow))
    return out


def _collector_entries(known: set[str]) -> list[Entry]:
    """Páginas que el recolector del Perú ya baja y que el pipeline aún no interpreta."""
    try:
        from tools import peru_collector
    except ImportError:
        return []
    out = []
    for group, urls in peru_collector.SOURCES.items():
        for url in urls:
            if url in known:
                continue
            p = urlparse(url)
            name = (p.path.strip("/") or p.netloc) + (f"?{p.query}" if p.query else "")
            out.append(Entry(
                id=f"{group}-{_slug(name) or 'portada'}", group=group, name=f"{group.upper()}: {name}",
                institution=group.upper(), url=url, expect="html", method="html", kind="page", home=url,
                hazards=[], notes="se archiva desde el Perú; aún sin intérprete en el pipeline"))
    return out


# --- Alcance medido --------------------------------------------------------------

def load_reachability(path: Path = REACHABILITY) -> dict:
    """Mediciones por URL: {url: {"us": {...}, "peru": {...}}} (vacío si no hay archivo)."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("urls", {})


def geoblock(url: str, reach: dict) -> dict:
    """Estado de geobloqueo de una URL a partir de las mediciones desde EE. UU. y desde el Perú."""
    r = reach.get(url) or {}
    us, pe = r.get("us"), r.get("peru")
    out = {"status": "unknown", "measured_at": None, "from": [], "us": us, "peru": pe}
    if us:
        out["from"].append(us.get("vantage", "us"))
        out["measured_at"] = us.get("at")
    if pe:
        out["from"].append("peru-server")
        out["measured_at"] = max(filter(None, [out["measured_at"], pe.get("at")]), default=None)
    us_ok = bool(us) and us.get("class") == "ok"
    pe_ok = bool(pe) and pe.get("class") == "ok"
    if us_ok:
        out["status"] = "open"
    elif us and pe_ok:
        out["status"] = "geoblocked"
    elif us and pe:
        out["status"] = "down"  # no responde ni desde EE. UU. ni desde el Perú
    elif us and us.get("class") in BLOCK_CLASSES:
        out["status"] = "suspected-geoblock"
    elif us:
        out["status"] = "down"
    return out


def channels_for(status: str) -> list[str]:
    """``peru-server`` si y solo si la fuente está (o parece) geobloqueada."""
    if status in ("geoblocked", "suspected-geoblock"):
        return ["peru-server"]
    return ["actions", "n8n"]


def build(reach: Optional[dict] = None, now: Optional[datetime] = None) -> dict:
    reach = load_reachability() if reach is None else reach
    entries = _feed_entries() + _source_entries()
    known = {e.url for e in entries} | {u for e in entries for u in e.alt_urls}
    entries += _collector_entries(known)
    sources = []
    for e in entries:
        gb = geoblock(e.url, reach)
        d = {k: v for k, v in e.__dict__.items() if v not in (None, [], "") or k in ("hazards", "alt_urls")}
        d["tier"] = METHODS[e.method]
        d["geoblock"] = gb
        d["geoblocked"] = True if gb["status"] in ("geoblocked", "suspected-geoblock") else (
            False if gb["status"] == "open" else None)
        d["channels"] = channels_for(gb["status"])
        sources.append(d)
    now = now or datetime.now(timezone.utc)
    return {"schema": SCHEMA, "generated_at": now.isoformat(timespec="seconds"),
            "rules": {"peru-server": "si y solo si geoblocked es true",
                      "tiers": METHODS, "channels": list(CHANNELS)},
            "sources": sources}


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
        if not set(s.get("channels", [])) <= set(CHANNELS) or not s.get("channels"):
            errs.append(f"{sid}: canales no válidos")
        if ("peru-server" in s.get("channels", [])) != (s.get("geoblocked") is True):
            errs.append(f"{sid}: peru-server debe usarse si y solo si la fuente está geobloqueada")
        if not str(s.get("url", "")).startswith(("http://", "https://")):
            errs.append(f"{sid}: URL no válida")
    return errs
