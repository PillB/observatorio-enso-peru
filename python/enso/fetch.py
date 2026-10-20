"""Descarga defensiva con canales alternativos y procedencia explícita.

Orden de intento para cada fuente:
  1. URL oficial (y sus espejos declarados), con reintentos y espera
     exponencial ante errores transitorios (DNS, 5xx, 429, timeouts).
  2. Si una URL no responde, la copia que el recolector del Perú
     (``tools/peru_collector.py``) bajó de esa misma URL y subió a la rama
     ``data-peru`` (canal «relay-peru»). Las fuentes peruanas que bloquean
     a servidores extranjeros se leen así con horas de antigüedad.
  3. Copia más reciente en el Internet Archive (Wayback Machine), solo si
     la fuente lo permite. Útil cuando el sitio oficial bloquea a robots
     (Cloudflare) o tiene caídas: el dato sigue siendo el publicado por la
     institución, pero se marca con canal «archivo» y la fecha de la copia.
  4. «Save Page Now» del Internet Archive cuando la copia existente tiene
     más de un día (o no hay ninguna) y se habilita; si falla, se usa la
     copia existente.

Cada respuesta lleva su procedencia (canal, URL efectiva, fecha de copia,
sha256), que se publica en el registro de fuentes.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import httpx

UA = "Observatorio-ENSO-Peru/4.0 (+https://github.com/PillB/observatorio-enso-peru; datos abiertos; contacto via issues)"
TRANSIENT = (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError)


@dataclass
class Response:
    url: str
    body: bytes
    channel: str  # "direct" | "mirror" | "relay-peru" | "archive" | "archive-fresh"
    status: int
    content_type: str = ""
    last_modified: str = ""
    archived_at: Optional[str] = None
    retrieved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    attempts: list = field(default_factory=list)

    @property
    def text(self) -> str:
        for enc in ("utf-8", "latin-1"):
            try:
                return self.body.decode(enc)
            except UnicodeDecodeError:
                continue
        return self.body.decode("utf-8", errors="replace")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


class FetchError(RuntimeError):
    def __init__(self, message: str, attempts: list):
        super().__init__(message)
        self.attempts = attempts


class Relay:
    """Copias recolectadas desde el Perú (rama ``data-peru``).

    ``index.json`` lista cada URL descargada, su estado y el archivo con el
    cuerpo. Solo se usan copias con estado 200, cuyo sha256 coincide y que
    no superan ``max_age_hours``.
    """

    FILE_RE = re.compile(r"^files/[0-9a-f]{16}\.(pdf|html|json)$")

    def __init__(self, root: Path, max_age_hours: float = 7 * 24):
        self.root = Path(root)
        idx = json.loads((self.root / "index.json").read_text(encoding="utf-8"))
        if idx.get("schema") != "enso-relay/1":
            raise ValueError(f"esquema de relay desconocido: {idx.get('schema')!r}")
        self.collected_at: str = idx.get("collected_at", "")
        self.host: str = (idx.get("collector") or {}).get("host", "")
        self.summary: dict = idx.get("summary") or {}
        self.max_age_hours = max_age_hours
        self._by_url: dict[str, list[dict]] = {}
        for e in idx.get("entries") or []:
            if e.get("status") != 200 or not self.FILE_RE.match(e.get("file") or ""):
                continue
            for u in [e.get("url"), *(e.get("aliases") or [])]:
                if u:
                    self._by_url.setdefault(u, []).append(e)

    @property
    def age_hours(self) -> float:
        return _age_hours(self.collected_at)

    def get(self, url: str, accept: tuple[str, ...] = ()) -> Optional[Response]:
        if self.age_hours > self.max_age_hours:
            return None
        for e in self._by_url.get(url, []):
            ct = (e.get("content_type") or "").lower()
            if accept and not any(a in ct for a in accept):
                continue
            body = (self.root / e["file"]).read_bytes() if (self.root / e["file"]).is_file() else b""
            if not body or hashlib.sha256(body).hexdigest() != e.get("sha256"):
                continue
            return Response(url, body, "relay-peru", 200, ct, archived_at=e.get("fetched_at") or self.collected_at)
        return None


class Fetcher:
    def __init__(self, timeout: float = 45.0, retries: int = 3, polite_delay: float = 0.8,
                 allow_archive: bool = True, allow_save: bool = False, offline: bool = False,
                 relay: Optional[Relay] = None):
        self.client = httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": UA})
        self.retries = retries
        self.polite_delay = polite_delay
        self.allow_archive = allow_archive
        self.allow_save = allow_save
        self.offline = offline
        self.relay = relay
        self._last: dict[str, float] = {}

    def close(self) -> None:
        self.client.close()

    def _wait_host(self, url: str) -> None:
        host = httpx.URL(url).host
        dt = time.monotonic() - self._last.get(host, 0)
        if dt < self.polite_delay:
            time.sleep(self.polite_delay - dt)
        self._last[host] = time.monotonic()

    def _get(self, url: str, attempts: list) -> Optional[httpx.Response]:
        for i in range(self.retries):
            self._wait_host(url)
            try:
                r = self.client.get(url)
            except TRANSIENT as exc:
                attempts.append({"url": url, "error": f"{type(exc).__name__}: {exc}"[:200]})
                time.sleep(min(30, 2 ** i * 2))
                continue
            attempts.append({"url": url, "status": r.status_code})
            if r.status_code == 429 or r.status_code >= 500:
                wait = r.headers.get("retry-after")
                time.sleep(min(60, float(wait)) if wait and wait.isdigit() else min(30, 2 ** i * 3))
                continue
            return r
        return None

    def get(self, urls: list[str], *, archive: bool = True, save: bool = False,
            accept: tuple[str, ...] = ()) -> Response:
        """Intenta cada URL y luego los canales de archivo."""
        attempts: list = []
        if self.offline:
            raise FetchError("modo sin conexión", attempts)
        for i, url in enumerate(urls):
            r = self._get(url, attempts)
            if r is not None and r.status_code == 200 and r.content and self._acceptable(r, accept):
                return Response(str(r.url), r.content, "direct" if i == 0 else "mirror", 200,
                                r.headers.get("content-type", ""), r.headers.get("last-modified", ""),
                                attempts=attempts)
            if r is not None and r.status_code == 200:
                attempts[-1]["note"] = "contenido vacío o tipo inesperado"
            if self.relay is not None:
                got = self.relay.get(url, accept)
                if got is not None:
                    attempts.append({"url": url, "channel": "relay-peru", "collected_at": self.relay.collected_at})
                    got.attempts = attempts
                    return got
        if archive and self.allow_archive:
            for url in urls:
                got = self._from_archive(url, attempts, fresh=save and self.allow_save)
                if got:
                    return got
        raise FetchError(f"sin respuesta válida para {urls[0]}", attempts)

    @staticmethod
    def _acceptable(r: httpx.Response, accept: tuple[str, ...]) -> bool:
        if not accept:
            return True
        ct = r.headers.get("content-type", "").lower()
        return any(a in ct for a in accept)

    def _from_archive(self, url: str, attempts: list, fresh: bool) -> Optional[Response]:
        """Copia más reciente del Internet Archive; si tiene más de un día y
        se permite, pide una nueva (Save Page Now) y, si esa falla, devuelve
        la existente."""
        cdx = ("https://web.archive.org/cdx/search/cdx?output=json&limit=-1&filter=statuscode:200"
               f"&url={quote(url, safe='')}")
        snap = None
        r = self._get(cdx, attempts)
        if r is not None and r.status_code == 200:
            try:
                rows = json.loads(r.text or "[]")[1:]
            except ValueError:
                rows = []
                attempts[-1]["note"] = "respuesta CDX no es JSON"
            if rows:
                ts, original = rows[-1][1], rows[-1][2]
                got = self._get(f"https://web.archive.org/web/{ts}id_/{original}", attempts)
                if got is not None and got.status_code == 200 and got.content:
                    snap = Response(url, got.content, "archive", 200, got.headers.get("content-type", ""),
                                    archived_at=_ts_iso(ts), attempts=attempts)
            else:
                attempts[-1]["note"] = attempts[-1].get("note", "sin copias en el archivo")
        if fresh and (snap is None or _age_hours(snap.archived_at) > 24):
            r = self._get(f"https://web.archive.org/save/{url}", attempts)
            if r is not None and r.status_code == 200 and r.content:
                return Response(url, r.content, "archive-fresh", 200, r.headers.get("content-type", ""),
                                archived_at=_wayback_ts(str(r.url)), attempts=attempts)
        return snap


def _age_hours(iso: Optional[str]) -> float:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 3600
    except (TypeError, ValueError):
        return float("inf")


def _ts_iso(ts: str) -> str:
    try:
        return datetime.strptime(ts[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return ts


def _wayback_ts(url: str) -> Optional[str]:
    m = re.search(r"/web/(\d{14})", url)
    return _ts_iso(m.group(1)) if m else None
