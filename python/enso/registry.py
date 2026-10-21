"""Registro único de fuentes: qué se descarga, cómo y por qué canal.

Es la fuente de verdad que leen el pipeline (GitHub Actions), el recolector
del Perú (``servidor-peru``) y el flujo de n8n. Se genera con
``python -m tools.build_registry`` en ``registry/sources.json`` a partir de:

* los feeds de noticias (``news.FEEDS``), las fuentes oficiales
  (``observatory.SOURCES``) y las páginas que se recolectan desde el Perú;
* las mediciones de alcance (``registry/reachability.json``): desde dónde
  responde cada URL, por red: los ejecutores de GitHub Actions, el servidor de
  n8n (ambos en EE. UU.) y el servidor del Perú.

Regla de canales: una fuente va por ``peru-server`` si y solo si está
geobloqueada (no responde desde ninguna red de EE. UU. y sí desde el Perú, o
no responde desde EE. UU. por bloqueo y aún no hay medición desde el Perú).
Las demás van por ``actions`` (la actualización diaria) y ``n8n`` (canal
alternativo); si una de las dos redes se midió y no responde mientras la otra
sí, solo por la que responde (p. ej. ENFEN no resuelve desde Azure y sí desde
la nube de n8n: la recolecta n8n y el pipeline usa esa copia).

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
            notes=f"tipo de medio: {f.kind}; alcance: {f.scope}"))
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


def geoblock(url: str, reach: dict) -> dict:
    """Estado de geobloqueo de una URL a partir de lo medido desde cada red (EE. UU.: Actions y n8n; Perú)."""
    groups = _groups(reach.get(url) or {})
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
        gb = geoblock(e.url, reach)
        d = {k: v for k, v in e.__dict__.items() if v not in (None, [], "") or k in ("hazards", "alt_urls")}
        d["tier"] = METHODS[e.method]
        d["geoblock"] = gb
        d["geoblocked"] = True if gb["status"] in ("geoblocked", "suspected-geoblock") else (
            False if gb["status"] == "open" else None)
        d["channels"] = channels_for(gb["status"], gb["open_from"],
                                     [g for g in ("actions", "n8n") if gb.get(g)])
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
        robots = (s.get("geoblock") or {}).get("status") == "robots-disallowed"
        if not set(s.get("channels", [])) <= set(CHANNELS) or (not s.get("channels")) != robots:
            errs.append(f"{sid}: canales no válidos (vacíos solo si robots.txt prohíbe la ruta)")
        if ("peru-server" in s.get("channels", [])) != (s.get("geoblocked") is True):
            errs.append(f"{sid}: peru-server debe usarse si y solo si la fuente está geobloqueada")
        if s.get("alt_expect") and (len(s["alt_expect"]) != len(s.get("alt_urls", []))
                                    or not set(s["alt_expect"]) <= EXPECT):
            errs.append(f"{sid}: alt_expect no corresponde a alt_urls")
        if not str(s.get("url", "")).startswith(("http://", "https://")):
            errs.append(f"{sid}: URL no válida")
    return errs
