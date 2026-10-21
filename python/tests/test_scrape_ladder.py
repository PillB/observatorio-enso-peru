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


def _handler(request: httpx.Request) -> httpx.Response:
    host = request.url.host
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
        "/app": ("text/html", b"<html><body><div id=app>cargando</div><script>"
                 b"fetch('/private/secret.json').catch(()=>{});"
                 b"fetch('/data.json').then(r=>r.json()).then(d=>{document.getElementById('app').textContent='Nivel '+d.nivel})"
                 b"</script></body></html>"),
        "/data.json": ("application/json", b'{"nivel": "naranja", "aviso": 123}'),
        "/private/secret.json": ("application/json", b'{"nivel": "naranja"}'),
    }
    hits: list[str] = []

    def do_GET(self):  # noqa: N802
        type(self).hits.append(self.path)
        ct, body = self.FILES.get(self.path, ("text/plain", b"no"))
        self.send_response(200 if self.path in self.FILES else 404)
        self.send_header("content-type", ct)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.mark.browser
def test_browser_step_finds_the_hidden_api_and_honors_robots(tmp_path, monkeypatch):
    pytest.importorskip("playwright.sync_api")
    monkeypatch.setattr(L, "DELAY_S", 0)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        client = httpx.Client(trust_env=False, timeout=10)
        rep = L.run([{"id": "spa", "url": f"{base}/app", "expect": "naranja"}], tmp_path, browser_ok=True, client=client)
    finally:
        srv.shutdown()
    r = rep["results"][0]
    assert [s["step"] for s in r["steps"]] == ["http", "http-headers", "browser"]
    assert r["answer"] == "hidden-api" and r["dataUrl"] == f"{base}/data.json"
    browser = r["steps"][-1]
    assert browser["blockedByRobots"] == [f"{base}/private/secret.json"]
    assert "/private/secret.json" not in _Site.hits  # el navegador tampoco pide lo que robots.txt prohíbe
    assert os.path.exists(tmp_path / next(c["file"] for c in browser["calls"] if c.get("file")))
