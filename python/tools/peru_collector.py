"""Recolector desde el Perú: descarga las fuentes peruanas que no responden
a servidores fuera del país y las publica en la rama ``data-peru``.

SENAMHI, ANA e IMARPE no responden a GitHub Actions (tiempo de espera o
HTTP 403) y el portal del ENFEN no resuelve desde allí. Este programa corre
en una máquina dentro del Perú (o en cualquier lugar donde esas fuentes sí
respondan), guarda cada respuesta original y la sube a la rama
``data-peru``. La actualización diaria la usa como canal «desde Perú»
(ver ``enso.fetch.Relay``) antes de recurrir al Internet Archive.

Uso:
  python -m tools.peru_collector --probe            # ¿qué responde desde esta máquina?
  python -m tools.peru_collector --once --push      # una recolección y subida
  python -m tools.peru_collector --daemon --push    # todos los días a las 21:00 (Lima)
  ... --dispatch                                    # y luego actualizar el sitio en el momento

La subida (y ``--dispatch``) usa un token de GitHub de grano fino con
permiso «Contents: read and write» solo sobre este repositorio, en la
variable ``GITHUB_TOKEN``.

Cada respuesta pasa por el mismo clasificador que usan Actions y n8n
(``enso.reach.classify``): una página de verificación antirobots o un
formato distinto del que espera el registro (``expect``) no se guarda. Si
una URL falla esta noche, se conserva su última copia buena de las 72 horas
anteriores, marcada ``carried`` (como hace n8n). Las URL del registro que
nadie midió desde el Perú se miden (sin guardarlas) para que el registro
sepa si están geobloqueadas o caídas.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from enso.feeds import FormatChanged, peru  # noqa: E402
from enso.fetch import UA, Relay  # noqa: E402
from enso.observatory import ENFEN_BASE, _clean_wpdm, _communique_urls  # noqa: E402
from enso.reach import Robots, classify  # noqa: E402

LIMA = ZoneInfo("America/Lima")
REPO = os.environ.get("ENSO_REPO", "PillB/observatorio-enso-peru")
BRANCH = os.environ.get("ENSO_RELAY_BRANCH", "data-peru")
MAX_BYTES = 8_000_000
#: El informe técnico del ENFEN pesa 10–17 MB; solo se guarda el de los dos últimos comunicados.
MAX_INFORME_BYTES = 20_000_000
HEARTBEAT = "heartbeat.json"
#: Registro de fuentes (rama principal del repositorio; copia en el kit).
REGISTRY_PATH = "registry/sources.json"
REGISTRY_SCHEMA = "enso-source-registry/1"
PERU_CHANNEL = "peru-server"
MAX_REGISTRY_SOURCES = 200
MAX_FOLLOW = 20
#: Una URL que falla esta noche conserva su copia buena de hasta 72 horas
#: antes (la misma regla que n8n, n8n/lib/relay.js).
CARRY_HOURS = 72
#: Plazo para descargar: con todos los servidores caídos, la corrida termina
#: y sube el latido antes del vigilante de 45 minutos (collector_service).
COLLECT_BUDGET_MIN = 25.0
#: Mediciones de URL del registro que nadie midió desde el Perú.
PROBE_STATUSES = {"unknown", "suspected-geoblock", "down"}
MAX_PROBES = 60
MAX_PROBES_PER_HOST = 10
PROBE_MIN_LEFT_S = 180
#: Un registro de respaldo más viejo que esto se avisa en el registro de la corrida.
REGISTRY_OLD_DAYS = 14

#: Fuentes que se recolectan desde el Perú. Las URL deben coincidir con las
#: del catálogo del pipeline para que la actualización diaria las encuentre.
SOURCES: dict[str, list[str]] = {
    "enfen": [
        "https://enfen.imarpe.gob.pe/wp-json/wp/v2/posts?per_page=10&search=comunicado",
        "https://enfen.imarpe.gob.pe/comunicados/",
        # Réplica de la DHN: responde desde fuera, pero sus PDF piden una
        # verificación humana a servidores en la nube.
        "https://www.dhn.mil.pe/portal/comunicados-oficiales-enfen",
    ],
    "senamhi": [
        "https://www.senamhi.gob.pe/?p=fenomeno-el-nino",
        "https://www.senamhi.gob.pe/?p=aviso-meteorologico",
        "https://www.senamhi.gob.pe/?p=boletines",
        "https://www.senamhi.gob.pe/mapas/mapa-estaciones-2/",
        # Solo responden desde el Perú (docs/catalogo-fuentes.md): los avisos del
        # observatorio y el GeoServer de IDESEP (las mismas consultas que
        # tools/scrape_candidates.json).
        "https://observatorio.senamhi.gob.pe/gestion-riesgo-desastres/avisos-meteorologicos",
        "https://idesep.senamhi.gob.pe/geoserver/ows?service=WFS&version=2.0.0&request=GetCapabilities",
        ("https://idesep.senamhi.gob.pe/geoserver/g_aviso/ows?service=WFS&version=1.0.0&request=GetFeature"
         "&typeName=g_aviso:view_aviso&maxFeatures=5&outputFormat=application/json"),
    ],
    "ana": [
        "https://snirh.ana.gob.pe/",
        "https://snirh.ana.gob.pe/onrh/",
    ],
    "imarpe": [
        "https://www.imarpe.gob.pe/",
        "https://www.imarpe.gob.pe/imarpe/index.php?id_seccion=I0178070000000000000000",
    ],
    "cenepred": [
        "https://sig.cenepred.gob.pe/arcgis_server/rest/services?f=pjson",  # SIG del CENEPRED
    ],
}

#: Lo que devuelven las URL de ``SOURCES`` que no son páginas HTML (el
#: registro lo toma como ``expect`` en ``enso.registry._collector_entries``).
EXPECT: dict[str, str] = {
    "https://enfen.imarpe.gob.pe/wp-json/wp/v2/posts?per_page=10&search=comunicado": "json",
    "https://idesep.senamhi.gob.pe/geoserver/ows?service=WFS&version=2.0.0&request=GetCapabilities": "text",
    SOURCES["senamhi"][-1]: "json",
    "https://sig.cenepred.gob.pe/arcgis_server/rest/services?f=pjson": "json",
}


def log(msg: str) -> None:
    print(f"{datetime.now(LIMA):%Y-%m-%d %H:%M:%S} {msg}", flush=True)


# --- Registro de fuentes ---------------------------------------------------------

def _valid_registry(data: object) -> dict:
    return data if isinstance(data, dict) and data.get("schema") == REGISTRY_SCHEMA else {}


def _age_days(iso: object, now: datetime | None = None) -> int | None:
    try:
        when = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0, ((now or datetime.now(timezone.utc)) - when).days)


def registry_info(data: dict, origin: str, note: str = "") -> dict:
    """Qué registro se usó: origen, versión (``generated_at``), cuántas fuentes
    trae y cuántas son de este equipo. Va en index.json y en el latido."""
    info = {"origin": origin or "ninguno", "generated_at": data.get("generated_at"),
            "sources": len(data.get("sources") or []), "peru_server": len(peru_sources(data))}
    if data and origin != "github":
        info["age_days"] = _age_days(data.get("generated_at"))
    if note:
        info["note"] = note
    return info


def load_registry_info(token: str = "") -> tuple[dict, dict]:
    """El registro de fuentes y de dónde salió (``registry_info``). Primero el
    del repositorio en GitHub (con el token, así el equipo sigue los cambios
    sin reinstalar y funciona aunque el repositorio sea privado); si no, la
    copia del kit o del repositorio local, con el motivo en ``note``. Sin
    registro, se recolecta solo ``SOURCES``."""
    override = os.environ.get("ENSO_REGISTRY_FILE", "").strip()
    note = ""
    if override or os.environ.get("ENSO_RELAY_REMOTE"):
        pass  # pruebas, o un archivo fijo: no se consulta GitHub
    elif not token:
        note = "sin token: no se leyó el registro de GitHub"
    else:
        ref = os.environ.get("ENSO_REGISTRY_REF", "").strip()
        try:
            r = httpx.get(f"https://api.github.com/repos/{REPO}/contents/{REGISTRY_PATH}",
                          params={"ref": ref} if ref else None, timeout=30, follow_redirects=True,
                          headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.raw+json",
                                   "User-Agent": UA})
            data = _valid_registry(r.json()) if r.status_code == 200 else {}
            if data:
                return data, registry_info(data, "github")
            note = (f"GitHub respondió HTTP {r.status_code}" if r.status_code != 200 else
                    f"el registro de GitHub no es {REGISTRY_SCHEMA}")
        except (httpx.HTTPError, ValueError) as exc:
            note = f"GitHub no respondió ({type(exc).__name__})"
    # ENSO_REGISTRY_FILE fija el archivo (pruebas, o para no consultar GitHub).
    path, origin = ((Path(override), "archivo") if override else
                    (Path(__file__).resolve().parents[2] / REGISTRY_PATH, "kit"))  # la instalación o el repo
    try:
        data = _valid_registry(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        data = {}
    if not data:
        return {}, registry_info({}, "", f"{note}; sin copia local válida" if note else "sin copia local válida")
    return data, registry_info(data, origin, note)


def load_registry(token: str = "") -> tuple[dict, str]:
    """``load_registry_info`` con solo el origen («github», «kit», «archivo» o «»)."""
    data, info = load_registry_info(token)
    return data, (info["origin"] if data else "")


def describe_registry(info: dict) -> str:
    """Una línea para el registro de la corrida y la verificación."""
    origin = {"github": "GitHub", "kit": "copia del kit", "archivo": "archivo fijo"}.get(info.get("origin"), "ninguno")
    if info.get("origin") in (None, "", "ninguno"):
        text = "registro de fuentes: ninguno (solo las fuentes fijas)"
    else:
        text = (f"registro de fuentes: {origin}, versión {info.get('generated_at') or '?'}, "
                f"{info.get('sources', 0)} fuentes, {info.get('peru_server', 0)} para este equipo")
    if info.get("note"):
        text += f" ({info['note']})"
    return text


def peru_sources(registry: dict) -> list[dict]:
    """Entradas del registro para este equipo: canal «peru-server» (las geobloqueadas)."""
    out = []
    for src in registry.get("sources") or []:
        if not isinstance(src, dict) or PERU_CHANNEL not in (src.get("channels") or []):
            continue
        if str(src.get("url") or "").startswith(("https://", "http://")):
            out.append(src)
    return out[:MAX_REGISTRY_SOURCES]


def url_states(src: dict) -> dict[str, dict]:
    """Estado y canales de cada URL de una fuente del registro (``by_url``: la
    principal y sus réplicas, cada una con su canal). En un registro anterior,
    sin ``by_url``, todas tienen el estado y los canales de la fuente."""
    by_url = src.get("by_url")
    if isinstance(by_url, dict) and by_url:
        return {u: r for u, r in by_url.items() if isinstance(u, str) and isinstance(r, dict)}
    geo = src.get("geoblock") if isinstance(src.get("geoblock"), dict) else {}
    state = {"status": geo.get("status"), "channels": list(src.get("channels") or [])}
    return {u: state for u in [src.get("url"), *(src.get("alt_urls") or [])] if isinstance(u, str)}


def robots_disallowed(registry: dict) -> set[str]:
    """URL que el registro marca «robots-disallowed»: el robots.txt del servidor
    pide no automatizarlas y no las pide nadie, tampoco este equipo."""
    return {u for src in registry.get("sources") or [] if isinstance(src, dict)
            for u, st in url_states(src).items() if st.get("status") == "robots-disallowed"}


def plan(registry: dict) -> tuple[dict[str, list[str]], dict[str, dict]]:
    """Qué descargar: ``SOURCES`` (menos lo que robots.txt no permite) más las
    URL del registro con el canal «peru-server» (las geobloqueadas: la
    principal o una réplica; por grupo, sin repetir URL), y las reglas
    ``follow`` de cada URL."""
    blocked = robots_disallowed(registry)
    groups = {g: [u for u in urls if u not in blocked] for g, urls in SOURCES.items()}
    known = {u for urls in groups.values() for u in urls}
    follow: dict[str, dict] = {}
    for src in peru_sources(registry):
        if isinstance(src.get("follow"), dict):
            follow[src["url"]] = src["follow"]
        group = re.sub(r"[^a-z0-9-]+", "-", str(src.get("group") or src.get("id") or "registro").lower()).strip("-")
        for url, st in url_states(src).items():
            if url in known or PERU_CHANNEL not in (st.get("channels") or []) or "{" in url \
                    or not url.startswith(("https://", "http://")):
                continue
            groups.setdefault(group[:40] or "registro", []).append(url)
            known.add(url)
    return groups, follow


def guess_expect(url: str) -> str | None:
    """Lo que devuelve una URL que el registro no describe, por su forma (como
    ``enso.registry._kind_of``); ``None``: cualquier formato."""
    if url in EXPECT:
        return EXPECT[url]
    low = url.lower()
    if "wp-json" in low or re.search(r"[?&](f=(p?json|geojson)|outputformat=application/json)(&|$)", low):
        return "json"
    return "pdf" if urlparse(low).path.endswith(".pdf") else None


def url_info(registry: dict) -> dict[str, dict]:
    """Por URL del registro: el formato esperado, la fuente a la que pertenece y,
    para la URL principal, las alternativas (``alt_urls`` y ``alt_expect``) que
    se prueban si la principal no sirve."""
    out: dict[str, dict] = {}
    for src in registry.get("sources") or []:
        if not isinstance(src, dict) or not isinstance(src.get("url"), str):
            continue
        sid, expect, states = str(src.get("id") or ""), src.get("expect"), url_states(src)
        alts = [u for u in src.get("alt_urls") or [] if isinstance(u, str)]
        alt_expect = src.get("alt_expect") if isinstance(src.get("alt_expect"), list) else []
        pairs = [(u, alt_expect[k] if k < len(alt_expect) else guess_expect(u)) for k, u in enumerate(alts)]
        # Como respaldo, solo las réplicas que nadie más alcanza (las que responden
        # a EE. UU. ya las bajan Actions o n8n) y que robots.txt permite.
        backup = [(u, e) for u, e in pairs if "{" not in u
                  and (states.get(u) or {}).get("status") not in ("open", "robots-disallowed")]
        out.setdefault(src["url"], {"expect": expect, "source": sid, "alts": backup})
        for u, e in pairs:
            out.setdefault(u, {"expect": e, "source": sid, "alts": []})
    return out


def probe_targets(registry: dict, skip: set[str]) -> list[str]:
    """URL del registro sin medición útil desde el Perú (estado ``unknown``,
    ``suspected-geoblock`` o ``down``) que esta corrida no pidió: se miden sin
    guardarlas, para que el registro sepa si están geobloqueadas (y las recolecte
    este equipo) o caídas. Hasta ``MAX_PROBES`` y ``MAX_PROBES_PER_HOST`` por servidor."""
    out: list[str] = []
    per_host: Counter = Counter()
    for src in registry.get("sources") or []:
        for u, st in url_states(src).items() if isinstance(src, dict) else ():
            if st.get("status") not in PROBE_STATUSES or not u.startswith(("https://", "http://")) \
                    or "{" in u or u in skip:
                continue
            host = urlparse(u).netloc.lower()
            if per_host[host] < MAX_PROBES_PER_HOST and u not in out:
                per_host[host] += 1
                out.append(u)
    return out[:MAX_PROBES]


def follow_links(client: httpx.Client | Session, page: dict, rule: dict, seen: set[str]) -> list[dict]:
    """Regla ``follow`` del registro: baja hasta ``max`` enlaces de la página
    que coinciden con ``pattern`` (p. ej. los PDF de un listado)."""
    body = page.get("body") or b""
    if page.get("status") != 200 or not body:
        return []
    try:
        pattern = re.compile(str(rule.get("pattern") or ""))
        limit = max(0, min(int(rule.get("max") or 4), MAX_FOLLOW))
    except (re.error, TypeError, ValueError):
        return []
    if not pattern.pattern:
        return []
    text = body.decode("utf-8", "replace").replace("\\/", "/")  # JSON escapa las barras
    links: list[str] = []
    for m in pattern.finditer(text):
        if len(links) >= limit:
            break
        url = urljoin(page["url"], html.unescape(m.group(1) if m.groups() else m.group(0)))
        if url.startswith(("https://", "http://")) and url not in seen:
            seen.add(url)
            links.append(url)
    out = []
    for url in links:
        r = fetch(client, url, guess_expect(url))
        r["parent"] = page["url"]
        out.append(r)
    return out


def usable(entry: dict) -> bool:
    """Una entrada sirve si esta corrida la guardó en files/: el sitio
    (enso.fetch.Relay) ignora las demás, aunque hayan respondido 200 (vacías,
    antirobots o demasiado grandes). Las copias conservadas de noches
    anteriores (``carried``) no cuentan como respuesta de esta noche."""
    return entry.get("status") == 200 and bool(entry.get("file")) and not entry.get("carried")


# --- Descarga y control del contenido ----------------------------------------------

FEEDS = {"rss", "atom", "rdf", "jsonfeed"}
#: Extensión del archivo guardado según el formato detectado (las que acepta enso.fetch.Relay).
EXT = {"pdf": ".pdf", "json": ".json", "jsonfeed": ".json", "rss": ".xml", "atom": ".xml", "rdf": ".xml",
       "xml": ".xml", "text": ".txt"}


def detect(body: bytes, content_type: str = "") -> str:
    """Formato del cuerpo, con el mismo criterio que n8n (``detectFormat`` en
    n8n/lib/classify.js): pdf, json, jsonfeed, rss, atom, rdf, html, xml,
    text, binary o empty."""
    if not body:
        return "empty"
    if body[:4] == b"%PDF":
        return "pdf"
    head = body[:4096].decode("latin-1")
    head = head.removeprefix("\xef\xbb\xbf")
    low = head.lstrip(" \t\r\n\x00").lower()
    if low.startswith(("{", "[")):
        return "jsonfeed" if re.search(r'"version"\s*:\s*"https://jsonfeed\.org', low) else "json"
    if re.search(r"<rss[\s>]", low):
        return "rss"
    if re.search(r"<feed[\s>]", low) and 'xmlns="http://www.w3.org/2005/atom"' in low:
        return "atom"
    if re.search(r"<rdf:rdf[\s>]", low):
        return "rdf"
    if re.search(r"<feed[\s>]", low):
        return "atom"
    if re.search(r"<!doctype html|<html[\s>]|<head[\s>]|<body[\s>]", low):
        return "html"
    if low.startswith("<"):
        return "html" if "<html" in low else "xml"
    if "html" in content_type.lower():
        return "html"
    n = min(len(body), 2048)
    ctrl = sum(1 for b in body[:n] if b < 9 or 13 < b < 32)
    return "binary" if ctrl > n * 0.05 else "text"


def judge(status: int | None, body: bytes, content_type: str = "", expect: str | None = None,
          error: str = "") -> tuple[str, str, str]:
    """¿Sirve la respuesta? Devuelve (clase, formato, motivo).

    La clase es la del clasificador común de Actions, n8n y el Perú
    (``enso.reach.classify``: ok, challenge, http-403…). Como en n8n, una
    respuesta con otro formato que el esperado (``expect`` del registro) cuenta
    como ``empty``: responde, pero sin contenido útil (suele ser una página de
    error o de verificación servida con 200). El motivo dice por qué no se guarda."""
    detected = detect(body, content_type) if status else "empty"
    cls = classify(status, body, error)
    if cls == "challenge" and status and 200 <= status < 300 and detected in FEEDS | {"pdf", "json"}:
        cls = "ok"  # un PDF o un feed que menciona «captcha» no es una verificación
    if cls != "ok":
        why = {"challenge": "página de verificación antirobots: no se guarda (no se evade)",
               "empty": "respuesta vacía"}.get(cls, "")
        return cls, detected, why
    exp = {"rss": "feed", "atom": "feed", "csv": "text"}.get(expect or "", expect or "any")
    wanted = ""
    if exp == "feed" and detected not in FEEDS:
        wanted = "un feed"
    elif exp == "pdf" and detected != "pdf":
        wanted = "un PDF"
    elif exp == "json" and detected not in ("json", "jsonfeed"):
        wanted = "JSON"
    elif exp == "json":
        try:
            json.loads(body.decode("utf-8-sig"))
        except ValueError:
            return "empty", detected, "JSON inválido"
    elif exp == "text" and detected in ("html", "binary"):
        wanted = "texto"
    elif exp == "html" and detected in ("html", "xml") and len(body) < 500:
        return "empty", detected, "HTML casi vacío"
    if wanted:
        return "empty", detected, f"se esperaba {wanted} y llegó {detected}"
    return "ok", detected, ""


class Session:
    """Una corrida: el cliente HTTP, el plazo y los servidores que no responden.

    Un servidor que no contesta (tiempo de espera, conexión, DNS, TLS) recibe
    un solo intento por URL desde su primer fallo y se omite tras el segundo.
    Pasado el plazo no se pide nada más. Así, con todas las fuentes caídas,
    la corrida termina y sube el latido antes del vigilante de 45 minutos.
    robots.txt se respeta (RFC 9309, ``enso.reach.Robots``): una ruta que
    prohíbe no se pide, y si robots.txt no responde (sin conexión, 5xx o una
    verificación antirobots en su lugar) no se pide nada a ese servidor."""

    def __init__(self, client: httpx.Client, budget_s: float | None = None, robots: bool = True):
        self.client = client
        self.deadline = time.monotonic() + budget_s if budget_s is not None else None
        self.budget_s = budget_s
        self.down: Counter = Counter()
        self.robots = Robots(client) if robots else None

    def left(self) -> float:
        return float("inf") if self.deadline is None else self.deadline - time.monotonic()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch(client: httpx.Client | Session, url: str, expect: str | None = None, max_bytes: int = MAX_BYTES) -> dict:
    s = client if isinstance(client, Session) else Session(client, robots=False)
    started = time.monotonic()
    host = urlparse(url).netloc.lower()
    out: dict = {"url": url, "status": None, "fetched_at": _now_iso(), "body": b""}
    if expect:
        out["expect"] = expect
    if s.left() <= 0:
        return {**out, "elapsed_s": 0.0, "skipped": "plazo",
                "error": f"no se pidió: la corrida pasó su plazo de {(s.budget_s or 0) / 60:.0f} min"}
    if s.down[host] >= 2:
        return {**out, "elapsed_s": 0.0, "skipped": "servidor",
                "error": "no se pidió: el servidor no respondió a las URL anteriores"}
    if s.robots is not None:
        allowed = s.robots.allowed(url)
        if allowed is False:
            return {**out, "elapsed_s": round(time.monotonic() - started, 1), "skipped": "robots",
                    "class": "robots", "error": "robots.txt no permite la ruta: no se pide"}
        if allowed is None:
            # RFC 9309 §2.3.1.4: robots.txt inalcanzable (sin conexión, 5xx o una verificación
            # antirobots en su lugar) equivale a «todo prohibido»: esta noche no se pide nada a
            # ese servidor. La clase del intento queda como medición desde el Perú.
            cls = s.robots.failure(url) or "connect"
            return {**out, "elapsed_s": round(time.monotonic() - started, 1), "skipped": "robots-sin-respuesta",
                    "class": cls, "error": f"robots.txt sin respuesta ({cls}): no se pide nada a este servidor"}
    err = ""
    attempts = 1 if s.down[host] else 3
    for attempt in range(attempts):
        try:
            r = s.client.get(url)
        except httpx.HTTPError as exc:
            err = f"{type(exc).__name__}: {exc}"[:200]
            if attempt + 1 < attempts and s.left() > 0:
                time.sleep(3 * (attempt + 1))
                continue
            break
        s.down.pop(host, None)
        body = r.content
        ct = r.headers.get("content-type", "")
        cls, detected, why = judge(r.status_code, body, ct, expect)
        out.update({"status": r.status_code, "content_type": ct, "bytes": len(body), "class": cls,
                    "elapsed_s": round(time.monotonic() - started, 1), "fetched_at": _now_iso()})
        if detected != "empty":
            out["detected"] = detected
        if len(body) > max_bytes:
            out["error"] = f"más de {max_bytes // 1_000_000} MB: no se guarda"
        elif cls == "ok":
            out["body"] = body
        elif why:
            out["error"] = why
        return out
    s.down[host] += 1
    return {**out, "error": err, "class": classify(None, b"", err), "fetched_at": _now_iso(),
            "elapsed_s": round(time.monotonic() - started, 1)}


def _pdf_link(html: str) -> str | None:
    got = peru.LISTING_RE.search(html) or re.search(r"href=[\"']([^\"']*\?wpdmdl=\d+[^\"']*)", html)
    return got.group(1) if got else None


def enfen_documents(client: httpx.Client | Session, pages: list[dict]) -> list[dict]:
    """Del listado del ENFEN: el PDF del comunicado más reciente y del
    anterior, y las páginas de descarga de los dos números siguientes (los
    mismos sondeos que hace la actualización diaria). Cuando una URL es una
    página de descarga, también baja el PDF que enlaza y lo registra con la
    URL de la página como alias, para que la actualización diaria lo
    encuentre con la misma URL que pide."""
    listing = []
    for p in pages:
        if p.get("status") == 200 and p["body"]:
            try:
                text = p["body"].decode("utf-8", errors="replace")
                if text.lstrip().startswith("["):
                    listing = [i for i in peru.parse_enfen_wp_posts(text).data if i.get("url")]
                else:
                    listing = peru.parse_enfen_listing(text).data
            except (FormatChanged, ValueError):
                continue
            if listing:
                break
    oficial = [i for i in listing if i.get("kind", "oficial") == "oficial"]
    targets = [_clean_wpdm(u) for i in oficial[:2] for u in _communique_urls(i)]
    if oficial:
        y, n = oficial[0]["year"], oficial[0]["number"]
        for k in (1, 2):
            targets += [f"{peru.DHN_BASE}/Archivos/oceanografia/enfen/comunicado-oficial/{n + k:02d}-{y}.pdf",
                        f"{ENFEN_BASE}/download/comunicado-oficial-enfen-n-{n + k:02d}-{y}/"]
    targets = list(dict.fromkeys(targets))
    out = []
    for url in targets:
        r = fetch(client, url, guess_expect(url))
        out.append(r)
        body = r["body"]
        if r.get("status") == 200 and body and body[:5] != b"%PDF-":
            link = _pdf_link(body.decode("utf-8", "replace"))
            if link and _clean_wpdm(link) != url:
                pdf = fetch(client, _clean_wpdm(link), "pdf")
                pdf["aliases"] = [url]
                out.append(pdf)
    out += enfen_informes(client)
    return out


def enfen_informes(client: httpx.Client | Session, keep: int = 2) -> list[dict]:
    """Listado de informes técnicos del ENFEN y los PDF de los ``keep`` más recientes, con la URL que cita el
    comunicado: el portal no responde fuera del Perú y la réplica de la DHN pide verificación humana."""
    from enso import reports

    listing = fetch(client, reports.INFORMES_PAGE, "html")
    out = [listing]
    if listing.get("status") != 200 or not listing["body"]:
        return out
    entries = reports.informe_entries(listing["body"].decode("utf-8", "replace"))
    for e in sorted(entries, key=lambda e: e.get("dataTo") or "", reverse=True)[:keep]:
        r = fetch(client, e["url"], "pdf", max_bytes=MAX_INFORME_BYTES)
        out.append(r)
        if r.get("status") == 200 and r["body"] and r["body"][:5] != b"%PDF-":
            link = _pdf_link(r["body"].decode("utf-8", "replace"))
            if link and _clean_wpdm(link) != e["url"]:
                pdf = fetch(client, _clean_wpdm(link), "pdf", max_bytes=MAX_INFORME_BYTES)
                pdf["aliases"] = [e["url"]]
                out.append(pdf)
    return out


def _log_fetch(r: dict) -> None:
    note = r.get("error") or ("" if r.get("class") in (None, "ok") else r["class"])
    log(f"{r.get('status')!s:>4} {r.get('bytes', 0):>9} B {r['elapsed_s']:>5}s {r['url']} {note}")


def probe_registry(registry: dict, skip: set[str], session: Session) -> dict[str, dict]:
    """Mide desde el Perú las URL de ``probe_targets`` (``tools.probe_sources``:
    el mismo clasificador y la misma lectura de robots.txt que en Actions).
    ``ENSO_PERU_PROBES=0`` lo desactiva."""
    targets = probe_targets(registry, skip) if os.environ.get("ENSO_PERU_PROBES", "1") != "0" else []
    if not targets:
        return {}
    if session.left() < PROBE_MIN_LEFT_S:
        log(f"no se miden {len(targets)} URL del registro: no queda tiempo en esta corrida")
        return {}
    try:
        from tools.probe_sources import probe
        got = probe(targets, "peru-server", timeout=20.0)
    except Exception as exc:  # una medición fallida no detiene la recolección
        log(f"AVISO no se pudieron medir las URL del registro: {type(exc).__name__}: {exc}"[:300])
        return {}
    for url, rec in got.items():
        log(f"medición {rec.get('class'):>9} {rec.get('http')!s:>4} {url}")
    counts = Counter(r.get("class") for r in got.values())
    log(f"mediciones desde el Perú: {len(got)} URL del registro ("
        + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) + ")")
    return got


def collect(out: Path, *, budget_min: float | None = None) -> dict:
    """Descarga todo en ``out`` (index.json + files/). Devuelve el índice."""
    files = out / "files"
    files.mkdir(parents=True, exist_ok=True)
    entries = []
    registry, reg_info = load_registry_info(os.environ.get("GITHUB_TOKEN", "").strip())
    groups, follow = plan(registry)
    meta = url_info(registry)
    log(describe_registry(reg_info))
    if reg_info.get("origin") != "github" and (reg_info.get("age_days") or 0) > REGISTRY_OLD_DAYS:
        log(f"AVISO el registro de fuentes usado tiene {reg_info['age_days']} días: "
            "actualizar el kit o revisar el acceso a GitHub")
    not_requested = sorted(robots_disallowed(registry) & {u for urls in SOURCES.values() for u in urls})
    for url in not_requested:
        log(f"no se pide {url}: su robots.txt no lo permite (registro)")
    planned = {u for urls in groups.values() for u in urls}
    budget = budget_min
    if budget is None:
        try:
            budget = float(os.environ.get("ENSO_COLLECT_BUDGET_MIN") or COLLECT_BUDGET_MIN)
        except ValueError:
            budget = COLLECT_BUDGET_MIN
    with httpx.Client(timeout=40.0, follow_redirects=True, headers={"User-Agent": UA}) as client:
        session = Session(client, budget * 60)
        results: dict[str, list[dict]] = {}
        seen: set[str] = set()

        def get(group: str, url: str, expect: str | None, **extra: str) -> dict:
            seen.add(url)
            r = fetch(session, url, expect)
            if meta.get(url, {}).get("source"):
                r["source"] = meta[url]["source"]
            r.update(extra)
            results.setdefault(group, []).append(r)
            _log_fetch(r)
            return r

        for group, urls in groups.items():
            results.setdefault(group, [])
            for u in urls:
                if u in seen:
                    continue
                info = meta.get(u, {})
                if get(group, u, info.get("expect") or guess_expect(u)).get("class") == "ok":
                    continue
                # La URL principal no sirvió: sus alternativas del registro, en orden.
                for alt, alt_expect in info.get("alts", []):
                    if alt not in seen and alt not in planned and get(group, alt, alt_expect, alt_of=u).get("class") == "ok":
                        break
        docs = enfen_documents(session, results.get("enfen", []))
        for r in docs:
            _log_fetch(r)
            seen.add(r["url"])
        results["enfen-docs"] = docs
        linked = [d for rs in list(results.values()) for r in rs if r["url"] in follow
                  for d in follow_links(session, r, follow[r["url"]], seen)]
        for r in linked:
            _log_fetch(r)
        if linked:
            results["enlaces"] = linked
        probes = probe_registry(registry, seen | set(not_requested), session)
    for group, rs in results.items():
        for r in rs:
            body = r.pop("body", b"")
            if body and r.get("status") == 200 and r.get("class", "ok") == "ok":
                sha = hashlib.sha256(body).hexdigest()
                name = f"files/{sha[:16]}{EXT.get(r.get('detected', ''), '.html')}"
                (out / name).write_bytes(body)
                r.update({"file": name, "sha256": sha})
            elif r.get("status") == 200 and not r.get("error"):
                r["error"] = "respuesta vacía"
            r["group"] = group
            entries.append(r)
    skipped = Counter(e["skipped"] for e in entries if e.get("skipped"))
    if skipped.get("plazo") or skipped.get("servidor") or skipped.get("robots-sin-respuesta"):
        down = sorted({urlparse(e["url"]).netloc for e in entries if e.get("skipped") == "robots-sin-respuesta"})
        log(f"AVISO no se pidieron {skipped['plazo'] + skipped['servidor'] + skipped['robots-sin-respuesta']} URL: "
            f"{skipped['servidor']} de servidores que no respondían, {skipped['robots-sin-respuesta']} de servidores "
            f"cuyo robots.txt no respondió ({', '.join(down) or 'ninguno'}) y {skipped['plazo']} por el plazo "
            f"de {budget:.0f} min")
    index = {
        "schema": "enso-relay/1",
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "collector": {"host": socket.gethostname(), "tz": "America/Lima"},
        "registry": reg_info,
        "entries": entries,
        "summary": {g: f"{sum(1 for e in entries if e['group'] == g and usable(e))}/"
                       f"{sum(1 for e in entries if e['group'] == g)}" for g in results},
    }
    if not_requested:
        index["not_requested"] = not_requested
    if probes:
        index["probes"] = probes
    (out / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8")
    return index


def heartbeat(idx: dict, result: str) -> dict:
    """Latido de una corrida. Se sube siempre que GitHub responde, aunque
    ninguna fuente lo haga: así el sitio distingue «el recolector no corre»
    (latido viejo) de «las instituciones no responden ni desde el Perú»
    (latido reciente con ``result`` = ``sin-fuentes``). Dice también qué
    registro de fuentes se usó y qué midió desde el Perú."""
    entries = idx.get("entries") or []
    ok = sum(1 for e in entries if usable(e))
    hb = {
        "schema": "enso-relay-heartbeat/1",
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "result": result,
        "reachable": f"{ok}/{len(entries)}",
        "summary": idx.get("summary") or {},
        "failures": [{k: e[k] for k in ("url", "status", "class", "error") if e.get(k) is not None}
                     for e in entries if not usable(e) and not e.get("carried")][:40],
        "collector": idx.get("collector") or {},
        "registry": idx.get("registry") or {},
    }
    if idx.get("probes"):
        hb["probes"] = dict(sorted(Counter(r.get("class") for r in idx["probes"].values()).items()))
    return hb


def push_heartbeat(hb: dict, token: str) -> None:
    """Sube solo el latido y deja intacta la última copia buena."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / HEARTBEAT).write_text(json.dumps(hb, indent=1, ensure_ascii=False), encoding="utf-8")
        push(Path(tmp), token, replace=False,
             message=f"relay: latido {hb['at']} ({hb['result']}, {hb['reachable']} fuentes)")


def _hours_since(iso: object, now: datetime) -> float | None:
    try:
        when = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (now - when).total_seconds() / 3600


def carry_forward(snapshot: Path, previous: Path, now: datetime | None = None) -> int:
    """Conserva en ``snapshot`` las copias buenas de ``previous`` (la rama tal
    como está) de las URL que esta noche no sirvieron o no se pidieron, si son
    de menos de ``CARRY_HOURS`` (contadas desde su descarga original): la
    entrada anterior con su fecha, ``carried: true`` y lo que pasó esta noche
    en ``last_attempt``, como en n8n. No se conservan las URL que robots.txt
    no permite, ni las de una fuente que esta noche respondió por otra URL (el
    sitio pide primero la principal y tomaría la copia vieja). Actualiza
    index.json y el latido de ``snapshot`` y devuelve cuántas conservó.

    Solo corre cuando se sube una copia nueva. Si no respondió ninguna fuente,
    ``push_heartbeat`` deja la copia anterior intacta, con su ``collected_at``:
    el sitio la usa hasta 7 días y, pasadas 36 horas, abre el aviso
    «relay-sources-down» (con una copia nueva cada noche no se abriría nunca)."""
    try:
        old = json.loads((previous / "index.json").read_text(encoding="utf-8"))
        idx = json.loads((snapshot / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not isinstance(old, dict) or old.get("schema") != "enso-relay/1" or not isinstance(old.get("entries"), list):
        return 0
    now = now or datetime.now(timezone.utc)
    entries = idx.get("entries") or []
    fresh = [e for e in entries if usable(e)]
    covered = {u for e in fresh for u in [e.get("url"), *(e.get("aliases") or [])]}
    fresh_sources = {e["source"] for e in fresh if e.get("source")}
    no_carry = set(idx.get("not_requested") or []) | {e.get("url") for e in entries if e.get("class") == "robots"}
    tonight = {e.get("url"): k for k, e in enumerate(entries)}
    extra: list[dict] = []
    kept = 0
    for p in old["entries"]:
        if not isinstance(p, dict) or p.get("status") != 200 or not p.get("sha256") \
                or not Relay.FILE_RE.match(str(p.get("file") or "")):
            continue
        url, aliases = p.get("url"), [a for a in p.get("aliases") or [] if isinstance(a, str)]
        k = tonight.get(url)
        now_e = entries[k] if k is not None else {}
        if not url or url in covered or url in no_carry or any(a in covered for a in aliases) \
                or (now_e.get("source") or p.get("source")) in fresh_sources:
            continue
        age = _hours_since(p.get("fetched_at"), now)
        if age is None or age > CARRY_HOURS:
            continue
        try:
            body = (previous / p["file"]).read_bytes()
        except OSError:
            continue
        if hashlib.sha256(body).hexdigest() != p["sha256"]:
            continue
        dest = snapshot / p["file"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            dest.write_bytes(body)
        kept += 1
        carried = {**p, "carried": True}
        if k is None:
            if not p.get("carried"):
                carried["last_attempt"] = {"note": "no se pidió esta noche"}
            extra.append(carried)
            continue
        carried["group"] = now_e.get("group", p.get("group"))
        carried["last_attempt"] = {key: now_e[field] for key, field in
                                   (("at", "fetched_at"), ("status", "status"), ("class", "class"), ("error", "error"))
                                   if now_e.get(field) is not None}
        entries[k] = carried
    if not kept:
        return 0
    idx["entries"] = entries + extra
    idx["carried"] = kept
    (snapshot / "index.json").write_text(json.dumps(idx, indent=1, ensure_ascii=False), encoding="utf-8")
    try:
        hb = json.loads((snapshot / HEARTBEAT).read_text(encoding="utf-8"))
        hb["carried"] = kept
        (snapshot / HEARTBEAT).write_text(json.dumps(hb, indent=1, ensure_ascii=False), encoding="utf-8")
    except (OSError, ValueError):
        pass
    return kept


def push(snapshot: Path, token: str, *, replace: bool = True, message: str = "") -> None:
    """Reemplaza el contenido de la rama ``data-peru`` con la nueva copia
    (el historial de git conserva las anteriores), más las copias buenas
    recientes de las URL que fallaron esta noche (``carry_forward``). Con
    ``replace=False`` solo agrega o reemplaza los archivos de ``snapshot``
    (el latido)."""
    remote = os.environ.get("ENSO_RELAY_REMOTE") or f"https://x-access-token:{token}@github.com/{REPO}.git"
    # Sin ayudantes de credenciales (guardarían el token en el llavero o en el
    # administrador de credenciales de Windows) ni ventanas que pidan clave:
    # en una tarea programada nadie las contestaría. Una subida trabada se corta.
    base = ["git", "-c", "credential.helper=", "-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=60"]
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "repo"

        def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
            try:
                res = subprocess.run([*base, *args], cwd=work if work.exists() else tmp,
                                     capture_output=True, text=True, env=env, timeout=900)
            except subprocess.TimeoutExpired:
                raise RuntimeError(f"git {args[0]} falló: sin respuesta en 15 minutos") from None
            if check and res.returncode != 0:
                # No mostrar el token en los mensajes de error.
                raise RuntimeError(f"git {args[0]} falló: {res.stderr.replace(token, '***')[:400]}")
            return res

        ls = git("ls-remote", "--exit-code", "--heads", remote, BRANCH, check=False)
        if ls.returncode not in (0, 2):  # 2: la rama no existe todavía; otro código: red o permisos
            raise RuntimeError(f"git ls-remote falló: {ls.stderr.replace(token, '***')[:400]}")
        exists = ls.returncode == 0
        if exists:
            git("clone", "--depth", "1", "--branch", BRANCH, remote, str(work))
        else:
            work.mkdir()
            git("init", "-q", "-b", BRANCH)
            git("remote", "add", "origin", remote)
        git("config", "user.name", "enso-peru-collector")
        git("config", "user.email", "enso-peru-collector@users.noreply.github.com")
        carried = carry_forward(snapshot, work) if replace and exists else 0
        if carried:
            log(f"se conservan {carried} copias buenas de noches anteriores (URL que hoy fallaron o no se pidieron)")
        for p in work.iterdir() if replace else ():
            if p.name != ".git":
                shutil.rmtree(p) if p.is_dir() else p.unlink()
        shutil.copytree(snapshot, work, dirs_exist_ok=True)
        git("add", "-A")
        if git("diff", "--cached", "--quiet", check=False).returncode == 0:
            log("sin cambios respecto de la copia anterior")
            return
        if not message:
            idx = json.loads((snapshot / "index.json").read_text(encoding="utf-8"))
            message = (f"relay: fuentes peruanas {idx['collected_at']} ({idx['summary']}"
                       f"{f', {carried} conservadas' if carried else ''})")
        git("commit", "-q", "-m", message)
        git("push", "-q", "origin", f"HEAD:{BRANCH}")
        log(f"subido a {REPO}@{BRANCH}")


def dispatch(token: str) -> None:
    """Pide a GitHub la actualización del sitio ahora (evento «enso-refresh»)."""
    r = httpx.post(f"https://api.github.com/repos/{REPO}/dispatches",
                   headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                   json={"event_type": "enso-refresh", "client_payload": {"from": "peru-collector"}}, timeout=30)
    if r.status_code != 204:
        raise RuntimeError(f"dispatch rechazado: HTTP {r.status_code} {r.text[:200]}")
    log("actualización del sitio solicitada")


def run_once(do_push: bool, keep: Path | None, do_dispatch: bool = False) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "snapshot"
        idx = collect(snap)
        log(f"resumen: {idx['summary']}")
        if keep:
            shutil.copytree(snap, keep, dirs_exist_ok=True)
        ok = sum(1 for e in idx["entries"] if usable(e))
        token = os.environ.get("GITHUB_TOKEN", "").strip()
        if do_push and not token:
            log("falta GITHUB_TOKEN: no se sube nada")
            return 2
        if do_push and not ok:
            # Una copia vacía reemplazaría a la última buena en data-peru: solo el latido.
            log("ninguna fuente respondió: solo se sube el latido")
            try:
                push_heartbeat(heartbeat(idx, "sin-fuentes"), token)
            except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
                log(f"tampoco se pudo subir el latido: {exc}")
            return 1
        if do_push:
            (snap / HEARTBEAT).write_text(json.dumps(heartbeat(idx, "ok"), indent=1, ensure_ascii=False),
                                          encoding="utf-8")
            push(snap, token)
            if do_dispatch:
                dispatch(token)
    return 0 if ok else 1


def next_run(at: str, now: datetime | None = None) -> datetime:
    h, m = (int(x) for x in at.split(":"))
    now = now or datetime.now(LIMA)
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return target if target > now else target + timedelta(days=1)


def probe() -> int:
    """Muestra qué fuentes responden desde esta máquina, sin subir nada."""
    registry, info = load_registry_info(os.environ.get("GITHUB_TOKEN", "").strip())
    print(describe_registry(info), flush=True)
    groups, _ = plan(registry)
    meta = url_info(registry)
    with httpx.Client(timeout=25.0, follow_redirects=True, headers={"User-Agent": UA}) as client:
        session = Session(client)
        ok = 0
        for group, urls in groups.items():
            for u in urls:
                r = fetch(session, u, meta.get(u, {}).get("expect") or guess_expect(u))
                good = r.get("class") == "ok"
                ok += good
                note = r.get("error") or ("" if good else r.get("class", ""))
                print(f"{'OK ' if good else 'NO '} {group:8} {r.get('status')!s:>4} {r.get('bytes', 0):>9} B "
                      f"{r['elapsed_s']:>5}s {u} {note}", flush=True)
    total = sum(len(v) for v in groups.values())
    print(f"\n{ok}/{total} fuentes responden desde esta máquina.")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--probe", action="store_true", help="solo comprobar el acceso")
    mode.add_argument("--once", action="store_true", help="recolectar una vez")
    mode.add_argument("--daemon", action="store_true", help="recolectar todos los días a la hora --at")
    ap.add_argument("--push", action="store_true", help="subir a la rama data-peru (requiere GITHUB_TOKEN)")
    ap.add_argument("--dispatch", action="store_true",
                    default=os.environ.get("ENSO_DISPATCH") == "1",
                    help="tras subir, pedir la actualización del sitio en el momento")
    ap.add_argument("--at", default=os.environ.get("ENSO_COLLECT_AT", "21:00"), help="hora de Lima, HH:MM")
    ap.add_argument("--keep", type=Path, help="guardar también una copia local en esta carpeta")
    args = ap.parse_args(argv)
    if args.probe:
        return probe()
    if args.once:
        return run_once(args.push, args.keep, args.dispatch)
    while True:
        t = next_run(args.at)
        log(f"próxima recolección: {t:%Y-%m-%d %H:%M} (Lima)")
        time.sleep(max(1, (t - datetime.now(LIMA)).total_seconds()))
        try:
            run_once(args.push, args.keep, args.dispatch)
        except Exception as exc:  # seguir funcionando al día siguiente
            log(f"ERROR {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
