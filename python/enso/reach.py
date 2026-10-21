"""Clasificador de alcance: ¿responde la URL desde aquí, o la bloquean?

El mismo criterio se usa en GitHub Actions, en n8n (AWS, EE. UU.) y en el
servidor del Perú, para que el registro (``enso.registry``) compare
mediciones equivalentes. Clases:

``ok`` responde con contenido · ``empty`` responde vacío · ``http-403`` ·
``http-4xx`` · ``http-5xx`` · ``timeout`` · ``connect`` (conexión rechazada o
cortada) · ``dns`` (el nombre no resuelve) · ``tls`` (certificado inválido) ·
``challenge`` (verificación antirobots: Cloudflare, Turnstile, CAPTCHA; no se
evade, se anota).
"""

from __future__ import annotations

import re
from typing import Optional

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
