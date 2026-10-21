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
import urllib.robotparser
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


class Robots:
    """robots.txt de cada servidor, leído una vez por corrida y respetado (RFC 9309).

    * 2xx: se aplican sus reglas.
    * 4xx (no existe, prohibido): se permite todo, como indica la RFC.
    * 5xx, sin conexión, o una página de verificación en su lugar: no se sabe y,
      como pide la RFC, no se pide nada a ese servidor (``allowed`` devuelve ``None``).
    """

    def __init__(self, client, agent: str = "*"):
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
        rp: Optional[urllib.robotparser.RobotFileParser] = urllib.robotparser.RobotFileParser()
        status, error, head = None, "", b""
        try:
            r = self.client.get(f"{base}/robots.txt")
            status, head = r.status_code, r.content[:30000]
            if 400 <= r.status_code < 500:
                rp.allow_all = True
            elif r.status_code >= 500 or CHALLENGE_RE.search(head) or b"<html" in head[:2000].lower():
                rp = None
            else:
                rp.parse(r.text.splitlines())
        except Exception as exc:  # noqa: BLE001 — sin respuesta: desconocido
            rp, error = None, f"{type(exc).__name__}: {exc}"[:200]
        entry = (rp, status, error, head)
        with self._lock:
            self._cache[base] = entry
        return entry

    def allowed(self, url: str) -> Optional[bool]:
        rp = self._entry(url)[0]
        return None if rp is None else rp.can_fetch(self.agent, url)

    def failure(self, url: str) -> str:
        """Clase de alcance del intento de leer robots.txt (``timeout``, ``challenge``…), si falló."""
        rp, status, error, head = self._entry(url)
        if rp is not None:
            return ""
        cls = classify(status, head, error)
        return "http-5xx" if cls == "ok" else cls  # una página HTML en lugar de robots.txt
