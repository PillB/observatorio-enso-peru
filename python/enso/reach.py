"""Clasificador de alcance: ¿responde la URL desde aquí, o la bloquean?

El mismo criterio se usa en GitHub Actions, en n8n (AWS, EE. UU.) y en el
servidor del Perú, para que el registro (``enso.registry``) compare
mediciones equivalentes: ``judge`` da las mismas clases que ``reachClass`` de
``n8n/lib/classify.js`` (``tests/fixtures/reach-parity.json`` lo comprueba en
los dos). Clases:

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
from typing import Optional
from urllib.parse import urlparse

#: Marcas de una página de verificación en lugar del contenido (las de ``BLOCK_SIGNATURES`` en
#: n8n/lib/classify.js). El script de detección de Cloudflare (``/cdn-cgi/challenge-platform/…/scripts/jsd/``) va
#: también en páginas normales: no cuenta.
CHALLENGE_RE = re.compile(
    rb"challenges\.cloudflare\.com|cf-chl|cf_chl_|cf-turnstile|turnstile|Just a moment\.\.\.|"
    rb"/cdn-cgi/challenge(?!-platform/(?:h/\w+/)?scripts/jsd)|challenge-platform(?!/(?:h/\w+/)?scripts/jsd)|"
    rb"Attention Required! \| Cloudflare|Verificaci(?:o|\xc3\xb3)n de seguridad|verify you are human|g-recaptcha|"
    rb"hcaptcha|DDoS protection by|Checking your browser", re.I)
#: Cuánto del cuerpo se revisa, y el tamaño desde el que una página con esas marcas ya no es una verificación
#: salvo con 403, 429 o 503 (como en n8n): una página normal puede traer un formulario con reCAPTCHA o Turnstile.
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


def classify(status: Optional[int], body: bytes = b"", error: str = "", headers=None) -> str:
    """Clase de una respuesta (o del error, si no la hubo). Es una verificación la que trae la cabecera
    ``cf-mitigated: challenge`` de Cloudflare, o una página con las marcas de ``CHALLENGE_RE`` que llega con 403,
    429 o 503 o tiene menos de ``SMALL_PAGE`` bytes."""
    if error and not status:
        e = error.lower()
        if any(s in e for s in ("name or service", "temporary failure in name", "nodename", "getaddrinfo", "no address")):
            return "dns"
        if "ssl" in e or "certificate" in e or "tls" in e:
            return "tls"
        if "timeout" in e or "timed out" in e:
            return "timeout"
        return "connect"
    if header(headers, "cf-mitigated").strip().lower() == "challenge":
        return "challenge"
    head = body[:SCAN_BYTES]
    if head and CHALLENGE_RE.search(head) and (status in (403, 429, 503) or len(body) < SMALL_PAGE):
        return "challenge"
    if status == 403:
        return "http-403"
    if status is not None and status >= 500:
        return "http-5xx"
    if status is not None and status >= 400:
        return "http-4xx"
    if status is not None and 200 <= status < 300:
        return "ok" if body.strip() else "empty"
    return "connect"


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

    Sobre ``classify``, cuenta el formato y lo que el registro espera (``expect``): solo una página HTML es una
    verificación (un PDF o un feed que menciona «captcha» no lo es), aunque sea grande si llega en lugar del PDF, el
    feed o el JSON esperado; un 202 vacío o con HTML es un antirobots (ReliefWeb, AWS WAF); y otro formato que el
    esperado, un feed sin entradas, un JSON ilegible o un HTML casi vacío cuentan como ``empty``: responde, pero
    sin contenido útil (suele ser una página de error servida con 200). El motivo dice por qué no sirve."""
    detected = detect(body, content_type) if status else "empty"
    cls = classify(status, body, error, headers)
    exp = {"rss": "feed", "atom": "feed", "csv": "text"}.get(expect or "", expect or "any")
    if cls == "challenge" and status and 200 <= status < 300 and detected != "html":
        cls = "ok" if body.strip() else "empty"
    elif cls == "ok" and detected == "html" and exp not in ("html", "any") and CHALLENGE_RE.search(body[:SCAN_BYTES]):
        cls = "challenge"
    if status == 202 and cls in ("ok", "empty") and detected in ("html", "empty"):
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
        for raw in text.splitlines():
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
                    rules.append((k == "allow", v))
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
        path = (p.path or "/") + (f"?{p.query}" if p.query else "")
        if path == "/robots.txt":
            return True
        best, allow = -1, True
        for is_allow, pattern in self.rules:
            n = self._matches(pattern, path)
            if n > best or (n == best and is_allow):
                best, allow = n, is_allow
        return allow


class Robots:
    """robots.txt de cada servidor, leído una vez por corrida y respetado (RFC 9309).

    * 2xx: se aplican sus reglas (``RobotRules``: gana la regla más larga). Una
      página HTML en su lugar (un «no encontrado» con código 200, o una
      redirección a la portada, como ``portal.indeci.gob.pe``) no tiene reglas:
      se permite todo, como al leer cualquier archivo sin reglas (RFC 9309 §2.3.1.1).
    * 4xx salvo 429 (no existe, prohibido), sin ser una verificación: se permite
      todo, como indica la RFC (§2.3.1.3).
    * 429, 5xx, sin conexión (o sin respuesta en ``timeout`` segundos), o una
      verificación antirobots en su lugar (la cabecera ``cf-mitigated: challenge``
      o una página de verificación, con cualquier código): no se sabe y, como pide
      la RFC (§2.3.1.4), no se pide nada a ese servidor (``allowed`` devuelve ``None``).

    ``source`` dice qué se leyó: ``rules`` (un archivo), ``absent`` (un 4xx: se
    permite todo) o ``unreachable``. ``timeout``: plazo del pedido de robots.txt
    (``ROBOTS_TIMEOUT_S``); ``None``, el del cliente.
    """

    def __init__(self, client, agent: str = "Observatorio-ENSO-Peru", timeout: Optional[float] = None):
        self.client = client
        self.agent = agent
        self.timeout = timeout
        self._cache: dict[str, tuple] = {}
        self._lock = threading.Lock()

    def _entry(self, url: str) -> tuple:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        with self._lock:
            if base in self._cache:
                return self._cache[base]
        rp: Optional[RobotRules] = None
        status, error, head, headers, source = None, "", b"", None, "unreachable"
        try:
            r = (self.client.get(f"{base}/robots.txt", timeout=self.timeout) if self.timeout
                 else self.client.get(f"{base}/robots.txt"))
            status, head, headers = r.status_code, r.content[:SCAN_BYTES], r.headers
            # Un archivo de reglas que nombra «hcaptcha» o «turnstile» no es una verificación: en un 2xx solo
            # cuenta una página HTML (o la cabecera de Cloudflare).
            challenged = classify(status, r.content, headers=headers) == "challenge" and (
                status >= 400 or detect(head, headers.get("content-type", "")) == "html"
                or header(headers, "cf-mitigated"))
            if challenged or status == 429 or status >= 500:
                rp = None
            elif status >= 300:
                rp, source = RobotRules(allow_all=True), "absent"
            else:
                rp, source = RobotRules(r.content[:500_000].decode("utf-8", errors="replace"), self.agent), "rules"
        except Exception as exc:  # noqa: BLE001 — sin respuesta: desconocido
            rp, error = None, f"{type(exc).__name__}: {exc}"[:200]
        entry = (rp, status, error, head, headers, source)
        with self._lock:
            self._cache[base] = entry
        return entry

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
        rp, status, error, head, headers, _ = self._entry(url)
        if rp is not None:
            return ""
        cls = classify(status, head, error, headers)
        return "http-5xx" if cls == "ok" else cls
