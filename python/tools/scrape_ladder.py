"""Escalera de extracción: para cada fuente sin feed, lo más simple primero.

Muchas instituciones del Perú publican sus alertas solo en páginas web, sin
RSS ni API documentada. Esta herramienta prueba, para cada candidato de
``scrape_candidates.json``, cada escalón en orden y se detiene en el primero
que trae el dato (``expect``: una expresión que prueba que el dato está en la
respuesta, no solo que la página cargó):

0. ``robots.txt`` (RFC 9309). Si prohíbe la ruta, o no responde, no se sigue.
1. GET simple con httpx, con el User-Agent del observatorio.
2. El mismo GET con las cabeceras ``Accept`` y ``Accept-Language`` de un
   navegador. Sigue identificándose como el observatorio: no se suplanta a
   nadie.
3. Navegador sin interfaz (Playwright + Chromium, el mismo de las pruebas del
   sitio), para páginas que arman el contenido con JavaScript. Se anotan las
   llamadas XHR/fetch que devuelven JSON, XML o texto: si una trae el dato, el
   pipeline la pide directo (escalón 1 sobre esa URL) y el navegador deja de
   hacer falta. Las rutas que el robots.txt prohíbe se bloquean también dentro
   del navegador.
4. Servicio externo de extracción (Firecrawl), solo si hay
   ``FIRECRAWL_API_KEY``. Se registra para comparar; el pipeline no depende de él.

Una verificación antirobots (Cloudflare, Turnstile, CAPTCHA) detiene la
escalera en ese punto: el navegador sirve para ejecutar JavaScript, no para
pasar verificaciones, y nunca se intenta.

Selenium haría lo mismo que el escalón 3 con otra dependencia; Playwright ya
está instalado para las pruebas del sitio.

Uso (en GitHub Actions; el contenedor de desarrollo no tiene salida a estas fuentes)::

    python -m tools.scrape_ladder --out tests/fixtures/scrape-ladder [--only id1,id2] [--no-browser]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from enso.reach import CHALLENGE_RE, Robots, classify  # noqa: E402

CONTACT = os.environ.get("ENSO_CONTACT_URL") or "https://github.com/PillB/observatorio-enso-peru"
UA = f"Observatorio-ENSO-Peru/4.0 (scrape-ladder; +{CONTACT})"
BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Accept-Language": "es-PE,es;q=0.9,en;q=0.6",
}
MAX_BYTES = 5_000_000
XHR_MAX_BYTES = 300_000
XHR_TYPES = ("json", "xml", "text/plain", "csv", "geo+json")
CANDIDATES = Path(__file__).with_name("scrape_candidates.json")
DELAY_S = 1.0


def _ext(content_type: str, body: bytes) -> str:
    ct = content_type.lower()
    head = body[:200].lstrip().lower()
    if "json" in ct or head[:1] in (b"{", b"["):
        return "json"
    if "xml" in ct or head.startswith(b"<?xml") or head.startswith(b"<rss") or head.startswith(b"<feed"):
        return "xml"
    if "csv" in ct:
        return "csv"
    if "html" in ct or b"<html" in head or b"<!doctype html" in head:
        return "html"
    return "txt"


def _found(expect: str, body: bytes) -> bool:
    return bool(re.search(expect.encode("utf-8"), body))


def http_step(client: httpx.Client, url: str, expect: str, headers: Optional[dict] = None) -> dict:
    t = time.monotonic()
    try:
        r = client.get(url, headers=headers)
        body = r.content[:MAX_BYTES]
        cls = classify(r.status_code, body)
        return {"status": r.status_code, "class": cls, "bytes": len(r.content), "ms": round((time.monotonic() - t) * 1000),
                "contentType": r.headers.get("content-type", ""), "finalUrl": str(r.url),
                "found": cls == "ok" and _found(expect, body), "_body": body}
    except Exception as exc:  # noqa: BLE001 — se anota y se sigue con el siguiente candidato
        return {"status": None, "class": classify(None, b"", f"{type(exc).__name__}: {exc}"),
                "error": f"{type(exc).__name__}: {exc}"[:200], "ms": round((time.monotonic() - t) * 1000),
                "found": False, "_body": b""}


def browser_step(browser, url: str, expect: str, robots: Robots) -> dict:
    """Abre la página en Chromium sin interfaz y anota las llamadas de datos que hace."""
    t = time.monotonic()
    calls: list[dict] = []
    blocked: list[str] = []
    ctx = browser.new_context(user_agent=UA, locale="es-PE", extra_http_headers={"Accept-Language": BROWSER_HEADERS["Accept-Language"]})
    page = ctx.new_page()

    def route(r):
        req_url = r.request.url
        if req_url.startswith("http") and robots.allowed(req_url) is False:
            blocked.append(req_url)
            return r.abort()
        return r.continue_()

    def on_response(resp):
        if resp.request.resource_type not in ("xhr", "fetch"):
            return
        ct = resp.headers.get("content-type", "")
        if not any(k in ct.lower() for k in XHR_TYPES):
            return
        try:
            body = resp.body()[:XHR_MAX_BYTES]
        except Exception:  # noqa: BLE001 — respuesta sin cuerpo
            body = b""
        calls.append({"url": resp.url, "status": resp.status, "contentType": ct, "bytes": len(body),
                      "method": resp.request.method, "found": _found(expect, body), "_body": body})

    page.route("**/*", route)
    page.on("response", on_response)
    out: dict = {}
    try:
        resp = page.goto(url, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(1500)
        html = page.content().encode("utf-8")
        status = resp.status if resp else None
        cls = "challenge" if CHALLENGE_RE.search(html[:30000]) else classify(status, html)
        out = {"status": status, "class": cls, "bytes": len(html), "found": cls == "ok" and _found(expect, html), "_body": html}
    except Exception as exc:  # noqa: BLE001
        out = {"status": None, "class": classify(None, b"", f"{type(exc).__name__}: {exc}"),
               "error": f"{type(exc).__name__}: {exc}"[:200], "found": False, "_body": b""}
    finally:
        ctx.close()
    for c in calls:
        c["robots"] = {True: "allowed", False: "disallowed", None: "unreachable"}[robots.allowed(c["url"])]
    out.update({"ms": round((time.monotonic() - t) * 1000), "calls": calls, "blockedByRobots": sorted(set(blocked))})
    return out


def firecrawl_step(client: httpx.Client, url: str, expect: str, key: str) -> dict:
    t = time.monotonic()
    try:
        r = client.post("https://api.firecrawl.dev/v1/scrape", json={"url": url, "formats": ["rawHtml"]},
                        headers={"Authorization": f"Bearer {key}"}, timeout=120)
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        html = ((data.get("data") or {}).get("rawHtml") or "").encode("utf-8")
        return {"status": r.status_code, "class": classify(r.status_code, html), "bytes": len(html),
                "ms": round((time.monotonic() - t) * 1000), "found": _found(expect, html), "_body": html}
    except Exception as exc:  # noqa: BLE001
        return {"status": None, "class": "connect", "error": f"{type(exc).__name__}: {exc}"[:200],
                "ms": round((time.monotonic() - t) * 1000), "found": False, "_body": b""}


def run(cands: list[dict], out: Path, browser_ok: bool = True, client: Optional[httpx.Client] = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    key = os.environ.get("FIRECRAWL_API_KEY", "")
    results = []
    pw = browser = None
    with client or httpx.Client(timeout=45.0, follow_redirects=True, headers={"User-Agent": UA}) as client:
        robots = Robots(client, agent="Observatorio-ENSO-Peru")
        try:
            for c in cands:
                res: dict = {"id": c["id"], "url": c["url"], "hazard": c.get("hazard"), "institution": c.get("institution"),
                             "steps": [], "answer": None}
                allowed = robots.allowed(c["url"])
                res["robots"] = {True: "allowed", False: "disallowed", None: "unreachable"}[allowed]
                if not allowed:
                    res["answer"] = "robots" if allowed is False else (robots.failure(c["url"]) or "robots-unreachable")
                    results.append(res)
                    print(f"{c['id']}\trobots {res['robots']}")
                    continue

                def keep(step: str, r: dict) -> None:
                    body = r.pop("_body", b"")
                    for call in r.get("calls", []):
                        cb = call.pop("_body", b"")
                        if call["found"] and cb:
                            name = f"{c['id']}.xhr-{len([x for x in r['calls'] if x.get('file')]) + 1}.{_ext(call['contentType'], cb)}"
                            (out / name).write_bytes(cb)
                            call["file"] = name
                    if body:
                        name = f"{c['id']}.{step}.{_ext(r.get('contentType', 'text/html' if step == 'browser' else ''), body)}"
                        (out / name).write_bytes(body)
                        r["file"] = name
                    res["steps"].append({"step": step, **r})

                r1 = http_step(client, c["url"], c["expect"])
                keep("http", r1)
                if r1["found"]:
                    res["answer"] = "http"
                elif r1["class"] in ("challenge", "dns", "timeout", "connect", "tls"):
                    res["answer"] = r1["class"]  # sin red o con verificación: el navegador no cambia nada
                else:
                    r2 = http_step(client, c["url"], c["expect"], BROWSER_HEADERS)
                    keep("http-headers", r2)
                    if r2["found"]:
                        res["answer"] = "http-headers"
                    elif r2["class"] == "challenge":
                        res["answer"] = "challenge"
                    elif browser_ok:
                        if browser is None:
                            from playwright.sync_api import sync_playwright
                            pw = sync_playwright().start()
                            browser = pw.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
                        r3 = browser_step(browser, c["url"], c["expect"], robots)
                        keep("browser", r3)
                        xhr = next((x for x in r3.get("calls", []) if x["found"] and x["robots"] == "allowed"), None)
                        if xhr:
                            res["answer"], res["dataUrl"] = "hidden-api", xhr["url"]
                        elif r3["found"]:
                            res["answer"] = "browser"
                        elif r3["class"] == "challenge":
                            res["answer"] = "challenge"
                        elif any(x["found"] for x in r3.get("calls", [])):
                            res["answer"] = "robots"  # el dato está, pero en una ruta que robots.txt prohíbe
                    if res["answer"] is None and key:
                        r4 = firecrawl_step(client, c["url"], c["expect"], key)
                        keep("firecrawl", r4)
                        if r4["found"]:
                            res["answer"] = "hosted"
                res["answer"] = res["answer"] or "not-found"
                results.append(res)
                print(f"{c['id']}\t{res['answer']}\t" + " ".join(f"{s['step']}={s.get('status')}/{s['class']}" for s in res["steps"]))
                time.sleep(DELAY_S)
        finally:
            if browser is not None:
                browser.close()
            if pw is not None:
                pw.stop()
    report = {"generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "vantage": os.environ.get("ENSO_VANTAGE", "github-actions-us"),
              "firecrawl": bool(key), "results": results}
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


#: Escalón de la escalera → nivel (tier) del registro de fuentes (``enso.registry``).
ANSWER_TIER = {"http": 1, "http-headers": 1, "hidden-api": 3, "browser": 4, "hosted": 5}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tests/fixtures/scrape-ladder")
    ap.add_argument("--candidates", default=str(CANDIDATES))
    ap.add_argument("--only", default="", help="ids separados por comas")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    cands = json.loads(Path(args.candidates).read_text(encoding="utf-8"))["candidates"]
    if args.only:
        want = set(args.only.split(","))
        cands = [c for c in cands if c["id"] in want]
    report = run(cands, Path(args.out), browser_ok=not args.no_browser)
    by: dict[str, int] = {}
    for r in report["results"]:
        by[r["answer"]] = by.get(r["answer"], 0) + 1
    print("resumen:", ", ".join(f"{k} {v}" for k, v in sorted(by.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
