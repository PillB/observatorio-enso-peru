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
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlsplit

import httpx

#: El contacto que ven las fuentes: el sitio publicado cuando el flujo lo
#: define (ENSO_CONTACT_URL), o el repositorio.
CONTACT = os.environ.get("ENSO_CONTACT_URL") or "https://github.com/PillB/observatorio-enso-peru"
UA = f"Observatorio-ENSO-Peru/4.0 (+{CONTACT}; datos abiertos)"
TRANSIENT = (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError)
#: Fallos seguidos de un servidor tras los que se le pide una sola vez por URL, y tras los que ya no se le pide
#: nada en la corrida (se pasa a las copias y al archivo). Cada pedido sin respuesta suma uno, una respuesta que
#: no termina a tiempo dos y una URL que solo recibió 429 o 5xx uno; cualquier otra respuesta vuelve a cero.
#: Save Page Now lleva su propia cuenta.
HOST_ONE_TRY_AFTER = 3
HOST_SKIP_AFTER = 5


class TooSlow(httpx.TransportError):
    """La respuesta no terminó de llegar en el tiempo total del pedido. No es transitorio: al reintentar
    tardaría lo mismo."""


@dataclass
class Response:
    url: str
    body: bytes
    channel: str  # "direct" | "mirror" | "relay-peru" | "relay-n8n" | "archive" | "archive-fresh"
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


def read_heartbeat(root: Path) -> dict:
    """Latido de la última corrida del recolector (``heartbeat.json``), o ``{}``."""
    try:
        hb = json.loads((Path(root) / "heartbeat.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return hb if isinstance(hb, dict) and hb.get("schema") == "enso-relay-heartbeat/1" else {}


class Relay:
    """Copias recolectadas fuera de GitHub Actions: desde el Perú (rama
    ``data-peru``) o por el flujo de n8n (rama ``data-n8n``), con el mismo
    formato «enso-relay/1».

    ``index.json`` lista cada URL descargada, su estado y el archivo con el
    cuerpo. Solo se usan copias con estado 200, cuyo sha256 coincide y que
    no superan ``max_age_hours`` (la recolección y cada copia: n8n conserva
    unas horas la última copia válida de una URL que dejó de responder).
    """

    FILE_RE = re.compile(r"^files/[0-9a-f]{16}\.(pdf|html|json|xml|txt)$")

    def __init__(self, root: Path, max_age_hours: float = 7 * 24):
        self.root = Path(root)
        idx = json.loads((self.root / "index.json").read_text(encoding="utf-8"))
        if idx.get("schema") != "enso-relay/1":
            raise ValueError(f"esquema de relay desconocido: {idx.get('schema')!r}")
        self.collected_at: str = idx.get("collected_at", "")
        self.collector: dict = idx.get("collector") or {}
        self.host: str = self.collector.get("host", "")
        self.summary: dict = idx.get("summary") or {}
        #: Metas de la recolección (``tools.peru_collector.goals``): documento → si se guardó su PDF.
        self.goals: dict = idx.get("goals") or {}
        self.heartbeat: dict = read_heartbeat(self.root)
        self.max_age_hours = max_age_hours
        #: Canal con que se marcan las respuestas: «relay-n8n», «relay-manual» (consola de documentos) o «relay-peru».
        kind = (idx.get("collector") or {}).get("kind")
        self.channel = {"n8n": "relay-n8n", "manual": "relay-manual"}.get(kind, "relay-peru")
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
            if e.get("fetched_at") and _age_hours(e["fetched_at"]) > self.max_age_hours:
                continue
            ct = (e.get("content_type") or "").lower()
            # El tipo que el recolector reconoció en el cuerpo cuenta igual que
            # la cabecera: un PDF servido como «text/html» sigue siendo un PDF.
            kind = f"{ct} {(e.get('detected') or '').lower()}"
            body = (self.root / e["file"]).read_bytes() if (self.root / e["file"]).is_file() else b""
            if not body or hashlib.sha256(body).hexdigest() != e.get("sha256"):
                continue
            if accept and not any(a in kind for a in accept) and not ("pdf" in accept and body.startswith(b"%PDF")):
                continue
            return Response(url, body, self.channel, 200, ct, archived_at=e.get("fetched_at") or self.collected_at)
        return None


class Fetcher:
    def __init__(self, timeout: float = 45.0, retries: int = 3, polite_delay: float = 0.8,
                 allow_archive: bool = True, allow_save: bool = False, offline: bool = False,
                 relay: Optional["Relay | list[Relay]"] = None, plan: Optional[dict[str, list[str]]] = None,
                 max_seconds: Optional[float] = None, budget_s: Optional[float] = None):
        # Conectar no lleva más de unos segundos aunque el servidor sea lento: un servidor que no acepta la
        # conexión no retiene cada pedido el plazo entero.
        self.client = httpx.Client(timeout=httpx.Timeout(timeout, connect=min(timeout, 15.0)), follow_redirects=True,
                                   headers={"User-Agent": UA})
        self.retries = retries
        #: Tiempo total de cada pedido. ``timeout`` vale por lectura: un servidor que manda la respuesta de a
        #: pocos bytes nunca lo agota y, sin este límite, retendría la corrida hasta el límite del build.
        self.max_seconds = max_seconds
        #: Tiempo para todos los pedidos de este cliente (desde que se crea): pasado ese tiempo no se pide nada
        #: más y cada fuente sigue con sus copias o con el dato anterior, para que la corrida llegue a publicar.
        self.deadline = time.monotonic() + budget_s if budget_s else None
        #: Fallos de red seguidos por servidor en esta corrida.
        self._down: dict[str, int] = {}
        self.polite_delay = polite_delay
        self.allow_archive = allow_archive
        self.allow_save = allow_save
        self.offline = offline
        #: Copias de otros recolectores, en orden de preferencia; si varias
        #: tienen la URL, se usa la más reciente.
        self.relays: list[Relay] = [r for r in (relay if isinstance(relay, list) else [relay]) if r is not None]
        self.relay = self.relays[0] if self.relays else None
        #: Canales de cada URL según el registro (``registry.url_channels``). Una URL que Actions no
        #: alcanza (geobloqueada) se lee primero de esas copias y se pide directo una sola vez, por si
        #: volvió a responder; una que robots.txt prohíbe (sin canales) no se pide al servidor.
        self.plan = plan or {}
        self._last: dict[str, float] = {}

    def close(self) -> None:
        self.client.close()

    def _wait_host(self, host: str) -> None:
        dt = time.monotonic() - self._last.get(host, 0)
        if dt < self.polite_delay:
            time.sleep(self.polite_delay - dt)
        self._last[host] = time.monotonic()

    def _request(self, url: str) -> httpx.Response:
        ends = [t for t in (time.monotonic() + self.max_seconds if self.max_seconds else None, self.deadline) if t]
        if not ends:
            return self.client.get(url)
        end = min(ends)
        with self.client.stream("GET", url) as r:
            chunks = []
            for chunk in r.iter_bytes():
                chunks.append(chunk)
                if time.monotonic() > end:
                    raise TooSlow("la respuesta no terminó de llegar a tiempo"
                                  + (f" ({self.max_seconds:g} s por pedido)" if self.max_seconds else ""), request=r.request)
            # El cuerpo ya viene descomprimido: sin Content-Encoding, la respuesta no lo descomprime otra vez.
            # Las cabeceras van en bytes, tal como llegaron: decodificadas no se pueden volver a armar si traen
            # caracteres fuera de ASCII (el ENFEN manda «filename="Comunicado Oficial N°18…"»).
            headers = [(k, v) for k, v in r.headers.raw
                       if k.lower() not in (b"content-encoding", b"content-length", b"transfer-encoding")]
        return httpx.Response(r.status_code, headers=headers, content=b"".join(chunks), request=r.request)

    @staticmethod
    def _key(url: str) -> str:
        """Cuenta de fallos de la URL: la del servidor. Save Page Now lleva la suya: una captura lenta no apaga las
        lecturas del archivo (CDX y copias)."""
        parts = urlsplit(url)
        host = parts.hostname or ""
        return host + "/save" if host == "web.archive.org" and parts.path.startswith("/save/") else host

    def skip_reason(self, url: str) -> Optional[str]:
        """Por qué no se pediría ahora esta URL (``None``: se pediría): se agotó el tiempo o su servidor ya falló
        demasiadas veces en la corrida."""
        if self.deadline is not None and time.monotonic() > self.deadline:
            return "omitido: se agotó el tiempo de la corrida para estos pedidos"
        down = self._down.get(self._key(url), 0)
        if down >= HOST_SKIP_AFTER:
            return f"omitido: el servidor suma {down} fallos seguidos en esta corrida"
        return None

    def _get(self, url: str, attempts: list, tries: Optional[int] = None) -> Optional[httpx.Response]:
        host = urlsplit(url).hostname or ""
        key = self._key(url)
        n = tries or self.retries
        overloaded = False  # el último intento fue un 429 o un 5xx
        for i in range(n):
            skip = self.skip_reason(url)
            if skip:
                attempts.append({"url": url, "error": skip})
                return None
            down = self._down.get(key, 0)
            if down >= HOST_ONE_TRY_AFTER and i:
                break
            self._wait_host(host)
            overloaded = False
            try:
                r = self._request(url)
            except TooSlow as exc:
                attempts.append({"url": url, "error": f"{type(exc).__name__}: {exc}"[:200]})
                self._down[key] = down + 2  # un servidor así de lento lo será también con el pedido siguiente
                return None
            except TRANSIENT as exc:
                attempts.append({"url": url, "error": f"{type(exc).__name__}: {exc}"[:200]})
                self._down[key] = down + 1
                if i + 1 < n and self._down[key] < HOST_ONE_TRY_AFTER:
                    time.sleep(min(30, 2 ** i * 2))
                continue
            except (httpx.HTTPError, httpx.InvalidURL) as exc:  # gzip roto, redirecciones sin fin, URL inválida
                attempts.append({"url": url, "error": f"{type(exc).__name__}: {exc}"[:200]})
                return None
            attempts.append({"url": url, "status": r.status_code})
            if r.status_code == 429 or r.status_code >= 500:
                overloaded = True
                if i + 1 < n and down < HOST_ONE_TRY_AFTER:  # tras el último intento no hay nada que esperar
                    wait = r.headers.get("retry-after")
                    time.sleep(min(60, float(wait)) if wait and wait.isdigit() else min(30, 2 ** i * 3))
                continue
            self._down[key] = 0
            return r
        if overloaded:
            # Una URL que solo recibió 429 o 5xx es un fallo más del servidor: uno que responde así a todo deja de
            # costar tres intentos y sus esperas por URL.
            self._down[key] = self._down.get(key, 0) + 1
        return None

    def get(self, urls: list[str], *, archive: bool = True, save: bool = False,
            accept: tuple[str, ...] = ()) -> Response:
        """Intenta cada URL y luego los canales de archivo."""
        attempts: list = []
        if self.offline:
            raise FetchError("modo sin conexión", attempts)
        for i, url in enumerate(urls):
            planned = self.plan.get(url)
            if planned is not None and "actions" not in planned:
                got = self._from_relays(url, accept)
                if got is not None:
                    attempts.append({"url": url, "channel": got.channel, "collected_at": got.archived_at,
                                     "note": "el registro la asigna a " + ", ".join(planned)})
                    got.attempts = attempts
                    return got
                if not planned:
                    attempts.append({"url": url, "note": "robots.txt no permite la ruta: no se pide"})
                    continue
            r = self._get(url, attempts, tries=1 if planned is not None and "actions" not in planned else None)
            if r is not None and r.status_code == 200 and r.content and self._acceptable(r, accept):
                return Response(str(r.url), r.content, "direct" if i == 0 else "mirror", 200,
                                r.headers.get("content-type", ""), r.headers.get("last-modified", ""),
                                attempts=attempts)
            if r is not None and r.status_code == 200:
                attempts[-1]["note"] = "contenido vacío o tipo inesperado"
            got = self._from_relays(url, accept)
            if got is not None:
                attempts.append({"url": url, "channel": got.channel, "collected_at": got.archived_at})
                got.attempts = attempts
                return got
        if archive and self.allow_archive:
            for url in urls:
                got = self._from_archive(url, attempts, fresh=save and self.allow_save)
                if got and (not accept or any(a in got.content_type.lower() for a in accept)):
                    return got
                if got:
                    attempts.append({"url": url, "channel": got.channel,
                                     "note": f"copia de archivo con tipo inesperado ({got.content_type[:60]})"})
        raise FetchError(f"sin respuesta válida para {urls[0]}", attempts)

    def copy(self, url: str, accept: tuple[str, ...] = ()) -> Optional[Response]:
        """Solo las copias de los recolectores (sin pedir nada): para las URL sintéticas ``manual://``."""
        return self._from_relays(url, accept)

    def _from_relays(self, url: str, accept: tuple[str, ...]) -> Optional[Response]:
        hits = [got for got in (r.get(url, accept) for r in self.relays) if got is not None]
        return max(hits, key=lambda g: -_age_hours(g.archived_at)) if hits else None

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


def archive_prefix(fetcher: "Fetcher", prefix: str, magic: bytes = b"%PDF-",
                   attempts: Optional[list] = None) -> Optional[Response]:
    """Copia más reciente en el Internet Archive de cualquier URL que empiece
    con ``prefix`` y cuyo contenido empiece con ``magic`` (p. ej. un PDF de
    WordPress cuyo parámetro de descarga no se conoce). El tipo declarado no
    sirve de filtro: estas descargas se archivan como PDF, octet-stream o
    force-download según el día."""
    attempts = [] if attempts is None else attempts
    if fetcher.offline or not fetcher.allow_archive:
        return None
    cdx = ("https://web.archive.org/cdx/search/cdx?output=json&limit=-25&matchType=prefix"
           f"&filter=statuscode:200&url={quote(prefix, safe='')}")
    r = fetcher._get(cdx, attempts)
    if r is None or r.status_code != 200:
        return None
    try:
        rows = json.loads(r.text or "[]")[1:]
    except ValueError:
        return None
    rows = [row for row in rows if len(row) > 3 and "html" not in row[3].lower()]
    attempts.append({"url": prefix, "channel": "archive-prefix", "note": f"{len(rows)} copias que no son HTML"})
    for row in sorted(rows, key=lambda row: row[1], reverse=True)[:4]:
        ts, original = row[1], row[2]
        got = fetcher._get(f"https://web.archive.org/web/{ts}id_/{original}", attempts)
        if got is not None and got.status_code == 200 and got.content[:len(magic)] == magic:
            return Response(original, got.content, "archive", 200, got.headers.get("content-type", ""),
                            archived_at=_ts_iso(ts), attempts=attempts)
    return None


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
