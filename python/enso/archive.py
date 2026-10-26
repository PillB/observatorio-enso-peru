"""Copias archivadas que publica el propio sitio (el enlace «copia archivada»).

Cada dato y cada noticia del sitio lleva dos enlaces: la fuente en vivo (la
página de la institución o la nota del medio) y la copia que bajó el
observatorio, servida desde el mismo sitio, por si la fuente cambia, se cae
o no responde. Nunca se enlaza a ramas ni archivos del repositorio.

Dentro de la publicación (``data/``):

* ``archive/sources/<fuente>/<sha12>.<ext>``: la respuesta original de cada
  fuente oficial y los PDF de los comunicados, byte por byte. Excepción:
  ``cpc-godas-d20`` archiva el D20 calculado por mes (JSON); las URL de los GRIB
  leídos quedan en su lista ``grib`` y en los intentos.
* ``archive/feeds/<feed>.txt``: el feed RSS/Atom/JSON de cada medio tal como
  se bajó en esta corrida.
* ``archive/news/<AAAA-MM-DD>.html``: por día, lo que dijo el feed de cada
  noticia que el observatorio vio por primera vez ese día (título, resumen,
  fecha y enlace; nunca el artículo completo).
* ``archive/index.json``: los archivos con su URL de origen, fecha, canal y sha256.

Las páginas HTML y los feeds de terceros se guardan como texto (``.txt``):
servidos como HTML desde el dominio del sitio, sus scripts correrían con los
permisos del sitio. Los PDF, JSON, CSV y texto conservan su extensión.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable, Optional

ROOT = "archive"
#: Días de páginas de noticias archivadas que se publican (el sitio muestra 14).
NEWS_DAYS = 60
#: Una copia mayor que esto no se publica (Cloudflare Pages admite 25 MiB por archivo).
MAX_BYTES = 20 * 1024 * 1024
SAFE_EXT = {"pdf", "json", "csv", "txt"}


def kind(body: bytes, content_type: str = "", url: str = "") -> str:
    """Extensión segura para servir ``body`` desde el sitio."""
    head = body[:4096].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if head.startswith(b"%pdf-"):
        return "pdf"
    ct = (content_type or "").lower()
    path = url.lower().split("?")[0]
    if head[:1] in (b"{", b"[") and ("json" in ct or path.endswith(".json") or "wp-json" in path):
        try:
            json.loads(body)
            return "json"
        except ValueError:
            pass
    if ("csv" in ct or path.endswith(".csv")) and b"<" not in head[:200]:
        return "csv"
    return "txt"  # HTML, XML, feeds y texto plano: se sirven como texto


def sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def source_path(sid: str, body: bytes, content_type: str = "", url: str = "") -> str:
    return f"{ROOT}/sources/{sid}/{sha(body)[:12]}.{kind(body, content_type, url)}"


def feed_path(fid: str) -> str:
    return f"{ROOT}/feeds/{fid}.txt"


def news_page(item: dict) -> str:
    """Página del día en que se vio la noticia por primera vez, con su ancla."""
    return f"{ROOT}/news/{item['first_seen'][:10]}.html#{item['id']}"


class Writer:
    """Escribe las copias dentro del directorio temporal de la publicación."""

    def __init__(self, base: Path):
        self.base = base
        self.files: dict[str, dict] = {}
        #: Copias que la publicación anterior listaba y no se pudieron leer: ``(fuente, ruta)``.
        self.missed: list[tuple[str, str]] = []

    def add(self, rel: str, body: bytes, **meta) -> Optional[str]:
        if not body or len(body) > MAX_BYTES:
            return None
        p = self.base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if rel not in self.files:
            p.write_bytes(body)
        self.files[rel] = {"path": rel, "sha256": sha(body), "bytes": len(body),
                           **{k: v for k, v in meta.items() if v not in (None, "")}}
        return rel

    def add_text(self, rel: str, text: str, **meta) -> str:
        return self.add(rel, text.encode("utf-8"), **meta) or rel

    def index(self, generated_at: str) -> dict:
        return {"generatedAt": generated_at, "files": sorted(self.files.values(), key=lambda f: f["path"])}


def write_sources(w: Writer, acquired: dict, previous_get: Optional[Callable[[str], Optional[bytes]]] = None,
                  previous_source: Optional[Callable[[str], Optional[dict]]] = None, log=None) -> dict[str, dict]:
    """Copia de cada fuente oficial; si hoy no respondió, la copia anterior (si sigue publicada).

    Devuelve, por fuente, ``{"file", "retrievedAt", "channel", "documents": [...]}``. Un documento de más de
    ``MAX_BYTES`` no se archiva: queda la advertencia ``archive-too-large`` (si se pasa ``log``).
    """
    out: dict[str, dict] = {}
    for sid, a in acquired.items():
        entry: dict = {}
        if a.raw:
            rel = w.add(source_path(sid, a.raw, url=a.url), a.raw, source=sid, url=a.url,
                        retrievedAt=a.retrieved_at, archivedAt=a.archived_at, channel=a.channel)
            if rel:
                entry = {"file": rel, "retrievedAt": a.retrieved_at, "channel": a.channel}
        elif previous_get and previous_source:
            prev = (previous_source(sid) or {}).get("archive") or {}
            rel = prev.get("file")
            body = previous_get(rel) if rel and _is_archive_path(rel) else None
            if body and w.add(rel, body, source=sid, url=a.url or None, retrievedAt=prev.get("retrievedAt"),
                              channel=prev.get("channel"), carried=True):
                entry = {**prev, "carried": True}
            elif rel and _is_archive_path(rel) and not body:
                w.missed.append((sid, rel))
        docs = []
        for body in a.documents:
            rel = w.add(source_path(sid, body), body, source=sid, retrievedAt=a.retrieved_at, document=True,
                        channel=a.channel)
            if rel:
                docs.append(rel)
            elif len(body) > MAX_BYTES and log is not None:
                log.add("warning", sid, "archive", "archive-too-large",
                        f"Un documento de {len(body) / 2**20:.1f} MiB supera el límite de la copia archivada "
                        f"({MAX_BYTES // 2**20} MiB): se publica sin copia.")
        if docs:
            entry["documents"] = docs
        if entry:
            out[sid] = entry
    return out


def carry(w: Writer, rel: Optional[str], previous_get: Optional[Callable[[str], Optional[bytes]]], **meta) -> Optional[str]:
    """Vuelve a publicar una copia de la publicación anterior (p. ej. el PDF del último comunicado).

    Si la anterior la listaba y no se pudo leer, queda en ``w.missed``."""
    if not rel or not _is_archive_path(rel):
        return None
    if rel in w.files:
        return rel
    body = previous_get(rel) if previous_get else None
    if previous_get and not body:
        w.missed.append((meta.get("source") or "", rel))
    return w.add(rel, body, carried=True, **meta) if body else None


def write_feeds(w: Writer, raw: dict[str, bytes], feeds: dict, fetched_at: str) -> dict[str, str]:
    """Feeds tal como se bajaron en esta corrida: ``{feed_id: ruta}``."""
    out = {}
    for fid, body in raw.items():
        f = feeds.get(fid)
        rel = w.add(feed_path(fid), body, feed=fid, url=getattr(f, "url", None), retrievedAt=fetched_at)
        if rel:
            out[fid] = rel
    return out


_DAY_CSS = ("body{font:16px/1.5 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;margin:0 auto;max-width:46rem;"
            "padding:16px;color:#1b1f24;background:#fff}h1{font-size:1.3rem}article{border-top:1px solid #d0d7de;"
            "padding:12px 0}h2{font-size:1.05rem;margin:0 0 4px}p{margin:4px 0}.m{color:#57606a;font-size:.875rem}"
            "a{color:#0b5cad;overflow-wrap:anywhere}:target{background:#fff8c5}"
            "@media (prefers-color-scheme:dark){body{background:#0d1117;color:#e6edf3}a{color:#6cb6ff}"
            ".m{color:#9198a1}article{border-color:#30363d}:target{background:#3b2e00}}")


def _day_html(day: str, items: list[dict], feeds: dict, snapshots: dict[str, str], live_ids: set[str]) -> str:
    e = html.escape
    rows = []
    for i in sorted(items, key=lambda i: i.get("published") or i["first_seen"], reverse=True):
        f = feeds.get(i.get("feed"))
        links = [f'<a href="{e(i["link"])}" rel="noopener noreferrer">Nota original (en vivo)</a>']
        if f is not None:
            links.append(f'<a href="{e(f.url)}" rel="noopener noreferrer">Feed de {e(f.name)} (en vivo)</a>')
        snap = snapshots.get(i.get("feed"))
        if snap and i["id"] in live_ids:
            links.append(f'<a href="../feeds/{e(Path(snap).name)}">Copia del feed bajada hoy</a>')
        when = i.get("published") or ""
        rows.append(
            f'<article id="{e(i["id"])}"><h2>{e(i["title"])}</h2>'
            f'<p class="m">{e(i.get("outlet") or "")} · publicado {e(when[:16].replace("T", " ")) or "sin fecha"} · '
            f'archivado {e(i["first_seen"][:16].replace("T", " "))} UTC</p>'
            + (f"<p>{e(i['summary'])}</p>" if i.get("summary") else "")
            + f'<p class="m">{" · ".join(links)}</p></article>')
    return (
        "<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<meta name=\"robots\" content=\"noindex\">"
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        f"<title>Noticias archivadas del {e(day)}</title><style>{_DAY_CSS}</style></head><body>"
        f"<h1>Noticias archivadas del {e(day)}</h1>"
        "<p class=\"m\">Copia de lo que publicó el feed de cada medio o institución (título, resumen, fecha y "
        "enlace) el día en que el observatorio vio la noticia por primera vez. El observatorio no copia los "
        f"artículos: para leerlos, siga el enlace a la nota original. {len(items)} noticias.</p>"
        + "".join(rows) + "<p class=\"m\"><a href=\"../../../\">Volver al observatorio</a></p></body></html>\n")


def write_news_days(w: Writer, items: Iterable[dict], feeds: dict, snapshots: dict[str, str],
                    live_ids: set[str], today: date, days: int = NEWS_DAYS) -> list[str]:
    since = (today - timedelta(days=days)).isoformat()
    by_day: dict[str, list[dict]] = {}
    for i in items:
        d = (i.get("first_seen") or "")[:10]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) and d >= since:
            by_day.setdefault(d, []).append(i)
    return [w.add_text(f"{ROOT}/news/{d}.html", _day_html(d, its, feeds, snapshots, live_ids), news=len(its))
            for d, its in sorted(by_day.items())]


def _is_archive_path(rel: str) -> bool:
    return bool(re.fullmatch(rf"{ROOT}/sources/[a-z0-9-]+/[0-9a-f]{{12}}\.(?:{'|'.join(SAFE_EXT)})", rel))


def stamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
