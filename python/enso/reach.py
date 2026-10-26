"""Clasificador de alcance: ¿responde la URL desde aquí, o la bloquean?

El mismo criterio se usa en GitHub Actions, en n8n (AWS, EE. UU.) y en el
servidor del Perú, para que el registro (``enso.registry``) compare
mediciones equivalentes: ``judge`` sigue a ``reachClass`` de
``n8n/lib/classify.js`` (el orden de los códigos HTTP y las marcas de
``BLOCK_SIGNATURES``), y ``tests/fixtures/reach-parity.json`` lo comprueba en
los dos. Las filas con ``n8n`` son las diferencias que quedan, a corregir en
classify.js: el script de detección de Cloudflare que va en páginas normales
y las cabeceras que llevan todas las respuestas de Imperva, Sucuri y DataDome
no son una verificación. Clases:

``ok`` responde con contenido · ``empty`` responde vacío · ``http-403`` ·
``http-4xx`` · ``http-5xx`` · ``timeout`` · ``connect`` (conexión rechazada o
cortada) · ``dns`` (el nombre no resuelve) · ``tls`` (certificado inválido) ·
``challenge`` (verificación antirobots: Cloudflare, Turnstile, CAPTCHA; no se
evade, se anota) · ``robots`` (el robots.txt del servidor no permite la ruta:
no se pide).
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Optional
from urllib.parse import urlparse

import httpx
from httpx import Client as HTTPClient

#: Marcas de una página de bloqueo o de verificación en lugar del contenido, por familia: las de
#: ``BLOCK_SIGNATURES`` en n8n/lib/classify.js, que se buscan en minúsculas en los primeros ``SCAN_BYTES`` del
#: cuerpo, leído como Latin-1 y como UTF-8. El script de detección de Cloudflare
#: (``/cdn-cgi/challenge-platform/…/scripts/jsd/``) va también en páginas normales: no cuenta.
BLOCK_SIGNATURES = (
    ("cloudflare-challenge", ("just a moment...", "cf-chl-", "challenge-platform", "/cdn-cgi/challenge")),
    ("cloudflare-block", ("attention required! | cloudflare", "cf-error-code", "sorry, you have been blocked",
                          "error 1020")),
    ("human-verification", ("verificación de seguridad", "verificacion de seguridad", "comprobación de seguridad",
                            "security check", "verify you are human", "verifica que eres humano", "are you a robot",
                            "checking your browser")),
    ("captcha", ("g-recaptcha", "grecaptcha", "h-captcha", "hcaptcha.com", "cf-turnstile", "px-captcha",
                 "captcha-delivery.com")),
    ("imperva", ("incapsula incident", "_incapsula_resource", "request unsuccessful. incapsula")),
    ("akamai", ("reference&#32;&#35;", "you don't have permission to access", "errors.edgesuite.net")),
    ("sucuri", ("sucuri website firewall", "access denied - sucuri")),
    ("aws-waf", ("awswaf", "aws-waf-token")),
    ("f5-asm", ("the requested url was rejected. please consult with your administrator", "your support id is")),
    ("fortinet", ("fortiguard", "web page blocked", "fortigate")),
    ("datadome", ("datadome",)),
    ("google-consent", ("consent.google.com", "before you continue to google", "antes de ir a google")),
    ("geo", ("not available in your country", "no está disponible en tu país", "no disponible en su país",
             "access from your country", "geo-restricted")),
)
#: Cabeceras de una verificación (nombre, valor que contiene; vacío: basta con que esté). No van las que llevan
#: todas las respuestas de esos servicios (``x-iinfo``, ``x-sucuri-id``, ``x-datadome``); n8n tampoco las cuenta.
BLOCK_HEADERS = (("cloudflare-challenge", "cf-mitigated", "challenge"), ("aws-waf", "x-amzn-waf-action", ""))
#: Lo que sigue a esas dos marcas en el script de detección de Cloudflare, que va también en páginas normales.
_NOT_JSD = {"challenge-platform": r"(?!/(?:h/\w+/)?scripts/jsd)",
            "/cdn-cgi/challenge": r"(?!-platform/(?:h/\w+/)?scripts/jsd)"}


def _pattern(mark: str, enc: str = "") -> str:
    """La marca como expresión regular (con ``enc``, la de sus bytes en esa codificación)."""
    return re.escape(mark.encode(enc).decode("latin-1") if enc else mark) + _NOT_JSD.get(mark, "")


_BLOCK_RES = tuple((name, re.compile("|".join(_pattern(m) for m in marks))) for name, marks in BLOCK_SIGNATURES)
#: Las mismas marcas sobre los bytes del cuerpo, sin decodificarlo (en UTF-8 y en Latin-1), para
#: ``tools.scrape_ladder``.
CHALLENGE_RE = re.compile("|".join(dict.fromkeys(
    _pattern(m, enc) for _, marks in BLOCK_SIGNATURES for m in marks for enc in ("utf-8", "latin-1"))).encode("latin-1"),
    re.I)
#: Cuánto del cuerpo se revisa, y el tamaño desde el que una página 2xx con esas marcas ya no es una verificación
#: salvo en lugar de otro formato (como en n8n): una página normal puede traer un formulario con reCAPTCHA.
SCAN_BYTES = 65536
SMALL_PAGE = 40000
#: Plazo para leer robots.txt: un servidor que no lo entrega en ese tiempo cuenta como sin respuesta.
ROBOTS_TIMEOUT_S = 15.0
FEEDS = {"rss", "atom", "rdf", "jsonfeed"}


def header(headers, name: str) -> str:
    """Valor de la cabecera ``name`` (en minúsculas) de ``httpx.Headers`` o de un dict, o ``""``."""
    for k, v in (headers or {}).items():
        if str(k).lower() == name:
            return str(v)
    return ""


def block_mark(body: bytes, headers=None) -> str:
    """Familia de la marca de bloqueo o de verificación de la respuesta (``BLOCK_HEADERS``, ``BLOCK_SIGNATURES``),
    o ``""``: ``findBlock`` de n8n/lib/classify.js."""
    names = {str(k).lower() for k in (headers or {})}
    for name, h, value in BLOCK_HEADERS:
        if h in names and value in header(headers, h).lower():
            return name
    head = body[:SCAN_BYTES]
    if not head:
        return ""
    text = (head.decode("latin-1") + "\n" + head.decode("utf-8", errors="replace")).lower()
    return next((name for name, rx in _BLOCK_RES if rx.search(text)), "")


def classify(status: Optional[int], body: bytes = b"", error: str = "", headers=None) -> str:
    """Clase de una respuesta (o del error, si no la hubo), en el orden de n8n: 429, 401, 407, 404 y 410 se
    deciden por el código; con otro código que no es 2xx, una marca de ``block_mark`` (la cabecera
    ``cf-mitigated: challenge`` de Cloudflare, una página de verificación) es una verificación; con un 2xx, solo
    en una página HTML de menos de ``SMALL_PAGE`` bytes (``judge`` cuenta también la que llega en lugar del
    formato esperado), y un 202 vacío o con HTML es un antirobots (ReliefWeb, AWS WAF)."""
    if status == 502 and b"upstream dial failed" in body[:200].lower():
        return "dns"  # el proxy de salida no resolvió el nombre
    if error and not status:
        e = error.lower()
        if any(s in e for s in ("name or service", "temporary failure in name", "nodename", "getaddrinfo", "no address")):
            return "dns"
        if "ssl" in e or "certificate" in e or "tls" in e:
            return "tls"
        if "timeout" in e or "timed out" in e:
            return "timeout"
        return "connect"
    if status is None:
        return "connect"
    if status in (429, 401, 407, 404, 410):
        return "http-4xx"
    mark = block_mark(body, headers)
    if status == 403:
        return "challenge" if mark else "http-403"
    if status >= 500:
        return "challenge" if mark else "http-5xx"
    html = bool(body) and detect(body, header(headers, "content-type")) == "html"
    if status == 202 and (mark or not body or html):
        return "challenge"
    if not 200 <= status < 300:  # 451, otro 4xx, un 3xx que no se siguió
        return "challenge" if mark else "http-4xx"
    if not body.strip():
        return "empty"
    return "challenge" if mark and html and len(body) < SMALL_PAGE else "ok"


def detect(body: bytes, content_type: str = "") -> str:
    """Formato del cuerpo, con el mismo criterio que n8n (``detectFormat`` en n8n/lib/classify.js): pdf, json,
    jsonfeed, rss, atom, rdf, html, xml, text, binary o empty."""
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


def _feed_items(body: bytes, detected: str) -> int:
    """Entradas de un feed (como ``feedStats`` en n8n: sin un lector XML completo)."""
    if detected == "jsonfeed":
        try:
            items = json.loads(body.decode("utf-8-sig")).get("items")
        except (ValueError, AttributeError):
            return 0
        return len(items) if isinstance(items, list) else 0
    return len(re.findall(rb"<(?:item|entry)[\s>]", body, re.I))


def judge(status: Optional[int], body: bytes, content_type: str = "", expect: Optional[str] = None,
          error: str = "", headers=None) -> tuple[str, str, str]:
    """¿Sirve la respuesta? Devuelve (clase, formato, motivo), con el criterio de n8n (``classify`` en
    n8n/lib/classify.js, ``reach``) y del recolector del Perú.

    Sobre ``classify``, cuenta lo que el registro espera (``expect``): una página HTML con una marca de verificación
    lo es aunque sea grande si llega en lugar del PDF, el feed o el JSON esperado (un PDF o un feed que menciona
    «captcha» no lo es); y otro formato que el esperado, un feed sin entradas, un JSON ilegible o un HTML casi vacío
    cuentan como ``empty``: responde, pero sin contenido útil (suele ser una página de error servida con 200). El
    motivo dice por qué no sirve."""
    if headers is None and content_type:
        headers = {"content-type": content_type}
    detected = detect(body, content_type) if status else "empty"
    cls = classify(status, body, error, headers)
    exp = {"rss": "feed", "atom": "feed", "csv": "text"}.get(expect or "", expect or "any")
    if cls == "ok" and detected == "html" and exp not in ("html", "any") and block_mark(body, headers):
        cls = "challenge"
    if cls != "ok":
        why = {"challenge": "página de verificación antirobots: no se guarda (no se evade)",
               "empty": "respuesta vacía"}.get(cls, "")
        return cls, detected, why
    wanted = ""
    if exp == "feed" and detected not in FEEDS:
        wanted = "un feed"
    elif exp == "feed" and not _feed_items(body, detected):
        return "empty", detected, "feed sin entradas"
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


_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


class RobotRules:
    """Reglas de un robots.txt según la RFC 9309.

    A diferencia de ``urllib.robotparser`` (que aplica la primera regla que
    coincide), gana la regla más larga, y ante un empate gana ``Allow``. Con
    «Allow: /» seguido de «Disallow: /api/», como en el IGP, ``/api/…`` queda
    prohibido. Se usan los grupos cuyo User-agent es el nombre del
    observatorio; si no hay ninguno, el grupo ``*``.
    """

    def __init__(self, text: str = "", agent: str = "*", allow_all: bool = False):
        self.allow_all = allow_all
        self.crawl_delay: Optional[float] = None
        groups: list[tuple[list[str], list[tuple[bool, str]], Optional[float]]] = []
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        delay: Optional[float] = None
        in_rules = False
        # Una marca de orden de bytes (BOM) al inicio dejaba la primera línea como «\ufeffuser-agent»: el grupo se
        # perdía y sus reglas no contaban (el analizador de Google la salta).
        for raw in text.lstrip("\ufeff").splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            k, v = (x.strip() for x in line.split(":", 1))
            k = k.lower()
            if k == "user-agent":
                if in_rules:
                    groups.append((agents, rules, delay))
                    agents, rules, delay, in_rules = [], [], None, False
                agents.append(v.lower())
            elif k in ("allow", "disallow") and agents:
                in_rules = True
                if v:  # «Disallow:» vacío no prohíbe nada
                    rules.append((k == "allow", self._canon(v)))
            elif k == "crawl-delay" and agents:
                in_rules = True
                try:
                    delay = float(v)
                except ValueError:
                    pass
        if agents:
            groups.append((agents, rules, delay))
        token = agent.lower()
        mine = [g for g in groups if token != "*" and token in g[0]] or [g for g in groups if "*" in g[0]]
        self.rules = [r for g in mine for r in g[1]]
        delays = [g[2] for g in mine if g[2] is not None]
        self.crawl_delay = max(delays) if delays else None

    @staticmethod
    def _canon(text: str) -> str:
        """Ruta o regla en la forma en que se comparan (RFC 9309 §2.2.2): lo que no es ASCII, en UTF-8 con
        ``%XX``; un ``%XX`` de un carácter no reservado (letras, cifras, ``-._~``), decodificado; los demás, en
        mayúsculas. Así ``/Señal``, ``/Se%c3%b1al`` y ``/Se%C3%B1al`` son la misma ruta."""
        out, raw, i = [], text.encode("utf-8"), 0
        while i < len(raw):
            c = raw[i]
            if c == 0x25 and re.fullmatch(rb"[0-9A-Fa-f]{2}", raw[i + 1:i + 3]):
                v = int(raw[i + 1:i + 3], 16)
                out.append(chr(v) if chr(v) in _UNRESERVED else f"%{v:02X}")
                i += 3
                continue
            out.append(chr(c) if 0x20 < c < 0x7F else f"%{c:02X}")
            i += 1
        return "".join(out)

    @staticmethod
    def _matches(pattern: str, path: str) -> int:
        """Largo de la regla si coincide con la ruta (``*`` comodín, ``$`` fin), o -1."""
        rx = "".join(".*" if c == "*" else re.escape(c) for c in pattern.rstrip("$"))
        if pattern.endswith("$"):
            rx += r"\Z"
        return len(pattern) if re.match(rx, path) else -1

    def allowed(self, url: str) -> bool:
        if self.allow_all:
            return True
        p = urlparse(url)
        path = self._canon((p.path or "/") + (f"?{p.query}" if p.query else ""))
        if path == "/robots.txt":
            return True
        best, allow = -1, True
        for is_allow, pattern in self.rules:
            n = self._matches(pattern, path)
            if n > best or (n == best and is_allow):
                best, allow = n, is_allow
        return allow


#: Redirecciones que se siguen como mucho, cada una con su robots.txt (``get_checked``, ``Fetcher``).
MAX_HOPS = 10


class RobotsHop(httpx.HTTPError):
    """Una redirección lleva a una ruta que su robots.txt no permite (``verdict`` ``False``) o a un servidor cuyo
    robots.txt no respondió (``None``): no se sigue. ``hop`` es la URL que no se pidió."""

    def __init__(self, hop: str, verdict: Optional[bool], why: str, request: Optional[httpx.Request] = None):
        super().__init__(f"redirige a {hop} y no se pide: {why}")
        self.hop, self.verdict, self.why = hop, verdict, why
        if request is not None:
            self.request = request


def next_hop(r: httpx.Response) -> Optional[str]:
    """A dónde redirige ``r`` (``None`` si no redirige), como lo resuelve httpx: un ``Location`` absoluto sin servidor
    (``http:///login``) va al mismo servidor."""
    loc = r.headers.get("location")
    if not (r.is_redirect and loc):
        return None
    url = httpx.URL(loc)
    if url.scheme and not url.host:
        url = url.copy_with(host=r.url.host)
    return str(r.url.join(url) if url.is_relative_url else url)


def get_checked(client, url: str, robots: Optional["Robots"], headers: Optional[dict] = None, **kw):
    """GET que sigue las redirecciones a mano y consulta robots.txt antes de cada salto, con la misma regla que
    el pedido: una ruta prohibida o un robots.txt sin respuesta no se piden. El robots.txt de ``url`` lo revisa
    quien llama. Devuelve la respuesta y, si un salto no se pidió, su URL y el veredicto (``False`` prohibido,
    ``None`` sin respuesta); si no, ``None`` y ``True``."""
    for _ in range(MAX_HOPS + 1):
        r = client.get(url, headers=headers, follow_redirects=False, **kw)
        hop = next_hop(r)
        if hop is None:
            return r, None, True
        verdict = True if robots is None else robots.allowed(hop)
        if verdict is not True:
            return r, hop, verdict
        url = hop
    raise httpx.TooManyRedirects(f"más de {MAX_HOPS} redirecciones", request=r.request)


class Robots:
    """robots.txt de cada servidor, leído una vez por corrida y respetado (RFC 9309).

    * 2xx: se aplican sus reglas (``RobotRules``: gana la regla más larga). Una
      página HTML en su lugar (un «no encontrado» con código 200, o una
      redirección a la portada, como ``portal.indeci.gob.pe``) no tiene reglas:
      se permite todo, como al leer cualquier archivo sin reglas (RFC 9309 §2.3.1.1).
    * 4xx salvo 429 (no existe, prohibido): se permite todo, como indica la RFC
      (§2.3.1.3), aunque la página de error traiga un formulario con reCAPTCHA;
      con 401, 403 o 407, salvo que sea una página de verificación.
    * 429, 5xx, sin conexión (o sin respuesta en ``timeout`` segundos), o una
      verificación antirobots en su lugar (la cabecera ``cf-mitigated: challenge``
      con cualquier código, una página de verificación con 401, 403 o 407, o una
      página HTML de verificación con 2xx): no se sabe y, como pide la RFC
      (§2.3.1.4), no se pide nada a ese servidor (``allowed`` devuelve ``None``).

    ``source`` dice qué se leyó: ``rules`` (un archivo), ``absent`` (un 4xx: se
    permite todo) o ``unreachable``. ``timeout``: plazo del pedido de robots.txt
    con un ``httpx.Client`` (otro cliente, como el de plazo corto de
    ``tools.scrape_ladder``, usa el suyo); ``None``, el del cliente. ``tries``:
    intentos ante un fallo pasajero (429, 5xx o sin conexión; no una
    verificación), con ``backoff_s`` segundos entre uno y otro: lo que se
    guarda vale para toda la corrida.
    """

    def __init__(self, client, agent: str = "Observatorio-ENSO-Peru", timeout: Optional[float] = ROBOTS_TIMEOUT_S,
                 tries: int = 1, backoff_s: float = 0.0):
        self.client = client
        self.agent = agent
        self.timeout = timeout
        self.tries = max(1, tries)
        self.backoff_s = backoff_s
        self._cache: dict[str, tuple] = {}
        self._lock = threading.Lock()

    def _entry(self, url: str) -> tuple:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        with self._lock:
            if base in self._cache:
                return self._cache[base]
        for attempt in range(self.tries):
            if attempt:
                time.sleep(self.backoff_s * attempt)
            entry = self._read(base)
            if entry[2] in ("", "challenge"):  # leído, o una verificación: otro intento no cambia nada
                break
        with self._lock:
            self._cache[base] = entry
        return entry

    def _read(self, base: str) -> tuple:
        rp: Optional[RobotRules] = None
        status, head, headers, source, fail, error = None, b"", None, "unreachable", "", ""
        try:
            # Las redirecciones de robots.txt se siguen aunque el cliente no las siga (RFC 9309 §2.3.1.2: un
            # robots.txt movido a https o a otro nombre trae las mismas reglas, no «se permite todo»).
            kw = {"follow_redirects": True} if isinstance(self.client, HTTPClient) else {}
            if self.timeout and isinstance(self.client, HTTPClient):
                kw["timeout"] = self.timeout
            r = self.client.get(f"{base}/robots.txt", **kw)
            status, head, headers = r.status_code, r.content[:SCAN_BYTES], r.headers
            # Un archivo de reglas que nombra «hcaptcha» o «turnstile», aunque llegue como text/html, no es una
            # verificación: en un 2xx solo cuenta un cuerpo HTML.
            if "challenge" in header(headers, "cf-mitigated").lower() or (
                    status in (401, 403, 407) and block_mark(r.content, headers)) or (
                    200 <= status < 300 and detect(head) == "html" and classify(status, r.content, headers=headers)
                    == "challenge"):
                fail = "challenge"
            elif status == 429 or status >= 500:
                fail, error = classify(status, head, headers=headers), f"HTTP {status}"
            elif status >= 300:
                rp, source = RobotRules(allow_all=True), "absent"
            else:
                rp, source = RobotRules(r.content[:500_000].decode("utf-8", errors="replace"), self.agent), "rules"
        except Exception as exc:  # noqa: BLE001 — sin respuesta: desconocido
            error = f"{type(exc).__name__}: {exc}"[:200]
            rp, fail = None, classify(None, b"", error)
        return (rp, status, fail, head, headers, source, error)

    def known(self, url: str) -> bool:
        """Si ya se leyó (o se intentó leer) el robots.txt del servidor de ``url``."""
        p = urlparse(url)
        with self._lock:
            return f"{p.scheme}://{p.netloc}" in self._cache

    def allowed(self, url: str) -> Optional[bool]:
        rp = self._entry(url)[0]
        return None if rp is None else rp.allowed(url)

    def source(self, url: str) -> str:
        """``rules`` (se leyeron reglas), ``absent`` (un 4xx: se permite todo) o ``unreachable``."""
        return self._entry(url)[5]

    def crawl_delay(self, url: str) -> Optional[float]:
        rp = self._entry(url)[0]
        return rp.crawl_delay if rp else None

    def failure(self, url: str) -> str:
        """Clase de alcance del intento de leer robots.txt (``timeout``, ``challenge``…), si falló."""
        return self._entry(url)[2]

    def error(self, url: str) -> str:
        """El error de red o el código con que falló la lectura de robots.txt (``ConnectError: …``, ``HTTP 503``),
        para el motivo de la incidencia; vacío si se leyó o fue una verificación."""
        return self._entry(url)[6]
