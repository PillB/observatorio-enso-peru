"""Clasificador de alcance: ¿responde la URL desde aquí, o la bloquean?

El mismo criterio se usa en GitHub Actions, en n8n (AWS, EE. UU.) y en el
servidor del Perú, para que el registro (``enso.registry``) compare
mediciones equivalentes. Clases:

``ok`` responde con contenido · ``empty`` responde vacío · ``http-403`` ·
``http-4xx`` · ``http-5xx`` · ``timeout`` · ``connect`` (conexión rechazada o
cortada) · ``dns`` (el nombre no resuelve) · ``tls`` (certificado inválido) ·
``challenge`` (verificación antirobots: Cloudflare, Turnstile, CAPTCHA; no se
evade, se anota) · ``robots`` (el robots.txt del servidor no permite la ruta:
no se pide).
"""

from __future__ import annotations

import re
import threading
from typing import Optional
from urllib.parse import urlparse

CHALLENGE_RE = re.compile(
    rb"challenges\.cloudflare\.com|cf-chl|cf_chl_|cf-turnstile|turnstile|Just a moment\.\.\.|"
    rb"Attention Required! \| Cloudflare|Verificaci(?:o|\xc3\xb3)n de seguridad|g-recaptcha|hcaptcha|"
    rb"DDoS protection by|Checking your browser", re.I)


def classify(status: Optional[int], body: bytes = b"", error: str = "") -> str:
    if error and not status:
        e = error.lower()
        if any(s in e for s in ("name or service", "temporary failure in name", "nodename", "getaddrinfo", "no address")):
            return "dns"
        if "ssl" in e or "certificate" in e or "tls" in e:
            return "tls"
        if "timeout" in e or "timed out" in e:
            return "timeout"
        return "connect"
    head = body[:30000]
    if head and CHALLENGE_RE.search(head) and (status in (403, 429, 503) or len(body) < 60000):
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

    * 2xx: se aplican sus reglas (``RobotRules``: gana la regla más larga).
    * 4xx (no existe, prohibido): se permite todo, como indica la RFC.
    * 5xx, sin conexión, o una página de verificación en su lugar: no se sabe y,
      como pide la RFC, no se pide nada a ese servidor (``allowed`` devuelve ``None``).
    """

    def __init__(self, client, agent: str = "Observatorio-ENSO-Peru"):
        self.client = client
        self.agent = agent
        self._cache: dict[str, tuple] = {}
        self._lock = threading.Lock()

    def _entry(self, url: str) -> tuple:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        with self._lock:
            if base in self._cache:
                return self._cache[base]
        rp: Optional[RobotRules] = None
        status, error, head = None, "", b""
        try:
            r = self.client.get(f"{base}/robots.txt")
            status, head = r.status_code, r.content[:30000]
            if 400 <= r.status_code < 500:
                rp = RobotRules(allow_all=True)
            elif r.status_code >= 500 or CHALLENGE_RE.search(head) or b"<html" in head[:2000].lower():
                rp = None
            else:
                rp = RobotRules(r.content[:500_000].decode("utf-8", errors="replace"), self.agent)
        except Exception as exc:  # noqa: BLE001 — sin respuesta: desconocido
            rp, error = None, f"{type(exc).__name__}: {exc}"[:200]
        entry = (rp, status, error, head)
        with self._lock:
            self._cache[base] = entry
        return entry

    def allowed(self, url: str) -> Optional[bool]:
        rp = self._entry(url)[0]
        return None if rp is None else rp.allowed(url)

    def crawl_delay(self, url: str) -> Optional[float]:
        rp = self._entry(url)[0]
        return rp.crawl_delay if rp else None

    def failure(self, url: str) -> str:
        """Clase de alcance del intento de leer robots.txt (``timeout``, ``challenge``…), si falló."""
        rp, status, error, head = self._entry(url)
        if rp is not None:
            return ""
        cls = classify(status, head, error)
        return "http-5xx" if cls == "ok" else cls  # una página HTML en lugar de robots.txt
