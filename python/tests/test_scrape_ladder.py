"""Escalera de extracción (tools.scrape_ladder): lo más simple primero, sin evadir nada."""

from __future__ import annotations

import http.server
import json
import os
import threading

import httpx
import pytest

from tools import scrape_ladder as L

ROBOTS = {
    "a.pe": (200, b"User-agent: *\nDisallow: /api/\n"),
    "b.pe": (404, b""),
    "c.pe": (404, b""),
    "d.pe": (404, b""),
    "f.pe": (503, b""),
}
PAGES = {
    "https://b.pe/boletines": (200, b"<html><body><td>IGP/CENVUL-SAB/BV 2026-0042</td></body></html>"),
    "https://c.pe/avisos": (403, b"<html><title>Just a moment...</title><div class='cf-turnstile'></div></html>"),
    "https://d.pe/app": (200, b"<html><body><div id='app'>Este sitio necesita JavaScript</div></body></html>"),
}
REDIRECTS = {"https://a.pe/viejo": "https://a.pe/api/x", "https://b.pe/movido": "/boletines"}
REQUESTED: list[str] = []


def _handler(request: httpx.Request) -> httpx.Response:
    host = request.url.host
    REQUESTED.append(str(request.url))
    if str(request.url) in REDIRECTS:
        return httpx.Response(302, headers={"location": REDIRECTS[str(request.url)]})
    if host == "e.pe":
        raise httpx.ConnectTimeout("timed out", request=request)
    if request.url.path == "/robots.txt":
        status, body = ROBOTS.get(host, (404, b""))
        return httpx.Response(status, content=body)
    status, body = PAGES.get(str(request.url), (404, b"no"))
    return httpx.Response(status, content=body, headers={"content-type": "text/html"})


@pytest.fixture
def ladder(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "DELAY_S", 0)
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)

    def go(cands):
        client = httpx.Client(transport=httpx.MockTransport(_handler))
        rep = L.run(cands, tmp_path, browser_ok=False, client=client)
        return {r["id"]: r for r in rep["results"]}
    return go


def test_simplest_step_that_brings_the_data_wins(ladder, tmp_path):
    r = ladder([{"id": "b", "url": "https://b.pe/boletines", "expect": "IGP/CENVUL"}])["b"]
    assert r["answer"] == "http" and r["robots"] == "allowed"
    assert [s["step"] for s in r["steps"]] == ["http"]  # no se escala si el GET simple basta
    assert (tmp_path / r["steps"][0]["file"]).read_bytes().startswith(b"<html>")
    rep = json.loads((tmp_path / "report.json").read_text())
    assert "_body" not in json.dumps(rep)


def test_robots_and_challenges_stop_the_ladder(ladder):
    got = ladder([
        {"id": "api", "url": "https://a.pe/api/ultimo-sismo", "expect": "x"},
        {"id": "chal", "url": "https://c.pe/avisos", "expect": "aviso"},
        {"id": "down", "url": "https://e.pe/x", "expect": "x"},
        {"id": "unk", "url": "https://f.pe/x", "expect": "x"},
    ])
    assert got["api"]["answer"] == "robots" and got["api"]["steps"] == []  # ni siquiera se pide
    assert got["chal"]["answer"] == "challenge"
    assert [s["step"] for s in got["chal"]["steps"]] == ["http"]  # una verificación no se intenta pasar
    assert got["down"]["answer"] in ("timeout", "robots-unreachable")
    assert got["unk"]["answer"] == "http-5xx" and got["unk"]["robots"] == "unreachable"


def test_redirects_are_checked_against_robots_hop_by_hop(ladder):
    """Una redirección hacia una ruta que robots.txt prohíbe no se sigue; una permitida, sí."""
    REQUESTED.clear()
    got = ladder([
        {"id": "viejo", "url": "https://a.pe/viejo", "expect": "x"},
        {"id": "movido", "url": "https://b.pe/movido", "expect": "IGP/CENVUL"},
    ])
    assert got["viejo"]["answer"] == "robots" and got["viejo"]["steps"][0]["finalUrl"] == "https://a.pe/api/x"
    assert "https://a.pe/api/x" not in REQUESTED
    assert got["movido"]["answer"] == "http" and got["movido"]["steps"][0]["finalUrl"] == "https://b.pe/boletines"


def test_shell_pages_escalate_past_plain_requests(ladder):
    r = ladder([{"id": "spa", "url": "https://d.pe/app", "expect": "Nivel naranja"}])["spa"]
    assert [s["step"] for s in r["steps"]] == ["http", "http-headers"]
    assert r["answer"] == "not-found"  # sin navegador en esta prueba
    assert L.ANSWER_TIER["hidden-api"] == 3 and L.ANSWER_TIER["browser"] == 4


def test_candidates_file_is_valid():
    data = json.loads(L.CANDIDATES.read_text(encoding="utf-8"))
    ids = [c["id"] for c in data["candidates"]]
    assert len(ids) == len(set(ids))
    for c in data["candidates"]:
        assert c["url"].startswith("https://") and c["expect"]
        __import__("re").compile(c["expect"])


class _Site(http.server.BaseHTTPRequestHandler):
    FILES = {
        "/robots.txt": ("text/plain", b"User-agent: *\nDisallow: /private/\n"),
        "/app": ("text/html", b"<html><body><div id=app>cargando</div><img src='/foto.png'>"
                 b"<script type=speculationrules>{\"prefetch\":[{\"source\":\"list\",\"urls\":[\"/private/precarga\"]}]}</script>"
                 b"<div><template shadowrootmode=open><script type=speculationrules>"
                 b"{\"prefetch\":[{\"source\":\"list\",\"urls\":[\"/private/sombra\"]}]}</script></template></div>"
                 b"<script>"
                 b"fetch('/private/secret.json').catch(()=>{});"
                 b"setTimeout(()=>window.open('/private/ventana'),500);"  # después: una ventana nueva oculta esta y frena la precarga
                 b"try{new WebSocket('ws://'+location.host+'/private/ws')}catch(e){};"
                 b"addEventListener('pagehide',()=>navigator.sendBeacon('/private/adios'));"
                 b"fetch('/atajo').catch(()=>{});"
                 b"fetch('/go').then(r=>r.json()).then(d=>{document.getElementById('app').textContent='Nivel '+d.nivel})"
                 b"</script></body></html>"),
        "/data.json": ("application/json", b'{"nivel": "naranja", "aviso": 123}'),
        "/marco": ("text/html", b"<html><body><script>fetch('/private/marco.json').catch(()=>{})</script></body></html>"),
        "/private/secret.json": ("application/json", b'{"nivel": "naranja"}'),
        "/reglas.json": ("application/speculationrules+json",
                         b'{"prefetch":[{"source":"list","urls":["/private/regla"]}]}'),
    }
    #: Reglas de precarga también por cabecera: se quita, así que ni se piden las reglas.
    HEADERS = {"/app": [("Speculation-Rules", '"/reglas.json"')]}
    #: Redirecciones: a una ruta prohibida (no se sigue) y a los datos (se sigue).
    REDIRECTS = {"/atajo": "/private/secret.json", "/go": "/data.json"}
    hits: list[str] = []

    def do_GET(self):  # noqa: N802
        type(self).hits.append(self.path)
        if self.path in self.REDIRECTS:
            self.send_response(302)
            self.send_header("location", self.REDIRECTS[self.path])
            self.end_headers()
            return
        ct, body = self.FILES.get(self.path, ("text/plain", b"no"))
        self.send_response(200 if self.path in self.FILES else 404)
        self.send_header("content-type", ct)
        for k, v in self.HEADERS.get(self.path, []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_GET  # navigator.sendBeacon

    def log_message(self, *a):
        pass


class _Down(http.server.BaseHTTPRequestHandler):
    """Otro servidor, cuyo robots.txt da 503: no se sabe qué permite, así que no se le pide nada."""
    hits: list[str] = []

    def do_GET(self):  # noqa: N802
        type(self).hits.append(self.path)
        self.send_response(503 if self.path == "/robots.txt" else 200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(b"" if self.path == "/robots.txt" else b'{"x": 1}')

    def log_message(self, *a):
        pass


@pytest.mark.browser
def test_browser_step_finds_the_hidden_api_and_honors_robots(tmp_path, monkeypatch):
    pytest.importorskip("playwright.sync_api")
    monkeypatch.setattr(L, "DELAY_S", 0)
    down = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Down)
    threading.Thread(target=down.serve_forever, daemon=True).start()
    other = f"http://127.0.0.1:{down.server_address[1]}/lib.json"
    ct, app = _Site.FILES["/app"]
    monkeypatch.setitem(_Site.FILES, "/app", (ct, app.replace(b"<script>", f"<script>fetch('{other}').catch(()=>{{}});"
                                                               f"fetch('/salto').catch(()=>{{}});".encode())))
    monkeypatch.setitem(_Site.REDIRECTS, "/salto", other.replace("lib.json", "salto.json"))
    monkeypatch.setitem(_Site.REDIRECTS, "/inicio", "/app")  # la página misma llega por una redirección permitida
    _Site.hits.clear()
    _Down.hits.clear()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    # Un iframe de otro sitio (localhost no es 127.0.0.1): con aislamiento por sitio iría en otro proceso.
    marco = f"<iframe src='http://localhost:{srv.server_address[1]}/marco'></iframe>".encode()
    monkeypatch.setitem(_Site.FILES, "/app", (ct, _Site.FILES["/app"][1].replace(b"<script>", marco + b"<script>", 1)))
    got: dict = {}

    def ladder():  # en otro hilo: las pruebas del sitio ya tienen Playwright abierto en este
        try:
            client = httpx.Client(trust_env=False, timeout=10)
            got["rep"] = L.run([{"id": "spa", "url": f"{base}/app", "expect": "naranja"},
                                {"id": "inicio", "url": f"{base}/inicio", "expect": "naranja"}], tmp_path,
                               browser_ok=True, client=client)
        except Exception as exc:  # noqa: BLE001 — se vuelve a lanzar abajo
            got["exc"] = exc

    t = threading.Thread(target=ladder)
    try:
        t.start()
        t.join(120)
    finally:
        srv.shutdown()
        down.shutdown()
    if "exc" in got:
        raise got["exc"]
    r = got["rep"]["results"][0]
    assert [s["step"] for s in r["steps"]] == ["http", "http-headers", "browser"]
    assert r["answer"] == "hidden-api" and r["dataUrl"] == f"{base}/data.json"
    browser = r["steps"][-1]
    salto = other.replace("lib.json", "salto.json")
    marco_privado = f"http://localhost:{base.rsplit(':', 1)[1]}/private/marco.json"
    ws = base.replace("http://", "ws://") + "/private/ws"
    assert browser["blockedByRobots"] == sorted([f"{base}/private/secret.json", other, salto, marco_privado,
                                                 f"{base}/private/ventana", f"{base}/private/adios", ws])
    assert "/private/secret.json" not in _Site.hits  # el navegador tampoco pide lo que robots.txt prohíbe,
    assert "/atajo" in _Site.hits  # ni siquiera si llega por una redirección,
    assert _Down.hits == ["/robots.txt"]  # ni nada de un servidor cuyo robots.txt no respondió
    assert "/foto.png" not in _Site.hits  # y las imágenes no se piden
    assert "/marco" in _Site.hits and "/private/marco.json" not in _Site.hits  # también dentro de un iframe ajeno,
    assert not [h for h in _Site.hits if h.startswith("/private/")]  # ventanas, WebSocket, precarga y avisos al salir
    assert "/reglas.json" not in _Site.hits
    assert "unchecked" not in browser  # todo pedido pasó por la revisión
    assert os.path.exists(tmp_path / next(c["file"] for c in browser["calls"] if c.get("file")))
    moved = got["rep"]["results"][1]
    assert moved["answer"] == "hidden-api" and moved["dataUrl"] == f"{base}/data.json"


def test_expect_patterns_match_text_not_bytes():
    from tools.scrape_ladder import _found
    assert _found(r"BOLET[ÍI]N", "BOLETÍN DE SISMO".encode("utf-8"))
    assert _found(r"BOLET[ÍI]N", "BOLETÍN DE SISMO".encode("cp1252"))
    assert _found(r"N[°º] \d+", "Aviso N° 429".encode("utf-8"))
    assert not _found(r"BOLET[ÍI]N", b"<html>sin boletines</html>")
