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
   del navegador, y no se piden imágenes, videos ni fuentes.
4. Servicio externo de extracción (Firecrawl), solo si hay
   ``FIRECRAWL_API_KEY``. Se registra para comparar; el pipeline no depende de él.

En cada escalón, antes de seguir una redirección se consulta el robots.txt de
su destino: un salto a una ruta prohibida (o a un servidor cuyo robots.txt no
responde) no se pide.

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
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

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
MAX_HOPS = 10
#: Plazo para leer el robots.txt de cada servidor que la página carga y que los GET no tocaron (scripts, CDN), y
#: tope de todas esas lecturas juntas por página: mientras se lee uno, el navegador no avanza con los demás
#: pedidos. Sin respuesta a tiempo, el servidor cuenta como «robots.txt sin respuesta» y no se le pide nada.
SUB_ROBOTS_TIMEOUT_S = 5.0
SUB_ROBOTS_BUDGET_S = 20.0
#: Recursos que no traen datos (tipos del protocolo de Chromium): no se piden, menos carga para servidores con
#: pocos recursos.
SKIP_TYPES = ("Image", "Media", "Font")
#: Reglas de precarga («speculation rules»): Chromium hace esas precargas por fuera de la sesión ``Fetch``, así que
#: no deben llegar a leerse. Las de la cabecera ``Speculation-Rules`` se quitan de la respuesta; las de un
#: ``<script type=speculationrules>`` las saca este guion, que corre en cada página y marco antes que los de la
#: página, apenas el elemento entra al documento (o a una sombra abierta, o a una creada con ``attachShadow``) y
#: antes de que Chromium las procese, que lo hace en una microtarea posterior. Reescribir el HTML en la sesión
#: ``Fetch`` (``fulfillRequest``) no sirve: deja colgados los iframes de otro sitio. Lo que escape (una sombra
#: declarativa cerrada, una página que lo esquive a propósito) aparece en ``unchecked``.
SPECULATION_GUARD_JS = """(() => {
  const rules = e => e.localName === 'script' && (e.getAttribute('type') || '').trim().toLowerCase() === 'speculationrules';
  const watched = new WeakSet();
  const sweep = n => {
    if (n && n.nodeType === 3) n = n.parentNode;
    if (!n || !n.querySelectorAll) return;
    for (const e of n.nodeType === 1 ? [n, ...n.querySelectorAll('*')] : n.querySelectorAll('*')) {
      if (rules(e)) e.remove();
      else if (e.shadowRoot) watch(e.shadowRoot);
    }
  };
  const mo = new MutationObserver(ms => {
    for (const m of ms) { if (m.type === 'childList') m.addedNodes.forEach(sweep); else sweep(m.target); }
  });
  const watch = root => {
    if (watched.has(root)) return;
    watched.add(root);
    mo.observe(root, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['type']});
    sweep(root);
  };
  const attach = Element.prototype.attachShadow;
  Element.prototype.attachShadow = function (...a) { const r = attach.apply(this, a); watch(r); return r; };
  watch(document);
})();"""


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
    """Busca el patrón en el texto, no en los bytes: «[ÍI]» no casa con los dos bytes UTF-8 de «Í».
    Las páginas que no están en UTF-8 suelen estar en Windows-1252."""
    rx = re.compile(expect)
    text = body.decode("utf-8", errors="replace")
    return bool(rx.search(text) or ("\ufffd" in text and rx.search(body.decode("cp1252", errors="replace"))))


def get_checked(client: httpx.Client, url: str, robots: Optional[Robots], headers: Optional[dict] = None):
    """GET que sigue las redirecciones a mano y consulta robots.txt antes de cada salto. Devuelve la respuesta y,
    si un salto no se pudo pedir, su URL y el veredicto de robots.txt (``False`` prohibido, ``None`` sin respuesta)."""
    for _ in range(MAX_HOPS + 1):
        if robots is not None:
            robots.pace(url)  # el Crawl-delay de una entidad pública del Perú (``reach.Robots.pace``)
        r = client.get(url, headers=headers, follow_redirects=False)
        loc = r.headers.get("location")
        if not (r.is_redirect and loc):
            return r, None, True
        url = urljoin(str(r.url), loc)
        verdict = True if robots is None else robots.allowed(url)
        if verdict is not True:
            return r, url, verdict
    raise httpx.TooManyRedirects(f"más de {MAX_HOPS} redirecciones", request=r.request)


def http_step(client: httpx.Client, url: str, expect: str, headers: Optional[dict] = None,
              robots: Optional[Robots] = None) -> dict:
    t = time.monotonic()
    try:
        r, blocked, verdict = get_checked(client, url, robots, headers)
        if blocked:
            # Igual que con la URL del candidato: prohibido es «robots»; un robots.txt sin respuesta, su falla.
            cls = "robots" if verdict is False else (robots.failure(blocked) or "robots-unreachable")
            why = "robots.txt no lo permite" if verdict is False else "su robots.txt no respondió"
            return {"status": r.status_code, "class": cls, "finalUrl": blocked, "blockedByRobots": blocked,
                    "error": f"redirige a {blocked} y no se pide: {why}"[:200],
                    "ms": round((time.monotonic() - t) * 1000), "found": False, "_body": b""}
        body = r.content[:MAX_BYTES]
        cls = classify(r.status_code, body)
        return {"status": r.status_code, "class": cls, "bytes": len(r.content), "ms": round((time.monotonic() - t) * 1000),
                "contentType": r.headers.get("content-type", ""), "finalUrl": str(r.url),
                "found": cls == "ok" and _found(expect, body), "_body": body}
    except Exception as exc:  # noqa: BLE001 — se anota y se sigue con el siguiente candidato
        return {"status": None, "class": classify(None, b"", f"{type(exc).__name__}: {exc}"),
                "error": f"{type(exc).__name__}: {exc}"[:200], "ms": round((time.monotonic() - t) * 1000),
                "found": False, "_body": b""}


def browser_step(browser, url: str, expect: str, robots: Robots, sub_robots: Optional[Robots] = None) -> dict:
    """Abre la página en Chromium sin interfaz y anota las llamadas de datos que hace.

    Cada pedido del navegador (de la página, sus iframes, ventanas emergentes y workers, y cada salto de una
    redirección) se detiene antes de salir en una sesión ``Fetch`` del protocolo de Chromium abierta sobre todo
    el navegador, y solo sigue si el robots.txt de su servidor lo permite. ``page.route`` no sirve para esto: solo
    ve el primer pedido de una cadena de redirecciones y nada de otras ventanas. Para los servidores que los GET
    no tocaron se usa ``sub_robots`` con un plazo corto. Como en el resto del observatorio (RFC 9309 §2.3.1.4), un
    robots.txt que no responde equivale a «todo prohibido». No se abren WebSocket ni service workers, y se quitan
    las reglas de precarga, que saldrían por fuera de esta revisión. Lo que igual llegue a responder sin haber
    pasado por ella queda en ``unchecked``."""
    t = time.monotonic()
    calls: list[dict] = []
    blocked: list[str] = []
    verdicts: dict[str, Optional[bool]] = {}  # documentos bloqueados → veredicto (False prohibido, None sin respuesta)
    checked: set[str] = set()  # lo que pasó por ``paused``
    answered: set[str] = set()  # lo que el navegador recibió
    gave_up: set[str] = set()  # servidores cuyo robots.txt no llegó a tiempo
    budget = [SUB_ROBOTS_BUDGET_S]
    pool = ThreadPoolExecutor(max_workers=2)

    def base(u: str) -> str:
        p = urlparse(u)
        return f"{p.scheme}://{p.netloc}"

    def allowed(u: str) -> Optional[bool]:
        if sub_robots is None or robots.known(u) or sub_robots.known(u):
            r = robots if sub_robots is None or robots.known(u) else sub_robots
            # El navegador no espera el Crawl-delay entre los pedidos de una página: la excepción de las entidades
            # públicas del Perú (``reach.public_peru``) vale para los GET, que sí lo esperan, y no aquí.
            return False if r.overridden(u) else r.allowed(u)
        if base(u) in gave_up or budget[0] <= 0:
            return None
        started = time.monotonic()
        try:
            ok = pool.submit(sub_robots.allowed, u).result(timeout=min(SUB_ROBOTS_TIMEOUT_S, budget[0]))
            return False if ok and sub_robots.overridden(u) else ok
        except FutureTimeout:
            gave_up.add(base(u))
            return None
        finally:
            budget[0] -= time.monotonic() - started

    cdp = browser.new_browser_cdp_session()

    def strip_speculation(ev: dict) -> None:
        rid, code = ev["requestId"], ev["responseStatusCode"]
        all_headers = ev.get("responseHeaders") or []
        headers = [h for h in all_headers if h["name"].lower() != "speculation-rules"]
        if len(headers) == len(all_headers):
            cdp.send("Fetch.continueRequest", {"requestId": rid})
        else:  # solo cambian las cabeceras: el cuerpo sigue tal cual
            cdp.send("Fetch.continueResponse", {"requestId": rid, "responseCode": code, "responseHeaders": headers})

    def paused(ev: dict) -> None:
        rid, req_url, kind = ev["requestId"], ev["request"]["url"], ev.get("resourceType")
        if "responseStatusCode" in ev:  # una página ya recibida: sin cabecera de reglas de precarga
            try:
                strip_speculation(ev)
            except Exception:  # noqa: BLE001 — se deja pasar tal cual (ya pasó la revisión de robots.txt)
                try:
                    cdp.send("Fetch.continueRequest", {"requestId": rid})
                except Exception:  # noqa: BLE001 — la página ya se cerró
                    pass
            return
        checked.add(req_url)
        try:
            verdict: Optional[bool] = True
            if kind in SKIP_TYPES:
                verdict = False
            elif req_url.startswith("http"):
                try:
                    verdict = allowed(req_url)
                except Exception:  # noqa: BLE001 — sin veredicto no se pide
                    verdict = None
            if verdict is True:
                cdp.send("Fetch.continueRequest", {"requestId": rid})
                return
            cdp.send("Fetch.failRequest", {"requestId": rid, "errorReason": "BlockedByClient"})
            if kind not in SKIP_TYPES:
                blocked.append(req_url)
                if kind == "Document":
                    verdicts[req_url] = verdict
        except Exception:  # noqa: BLE001 — el pedido ya no existe (la página se cerró)
            pass

    def on_response(resp):
        if resp.url.startswith("http"):
            answered.add(resp.url)
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

    def on_websocket(ws) -> None:
        blocked.append(ws.url)  # sin connect_to_server: el servidor nunca recibe el pedido

    cdp.on("Fetch.requestPaused", paused)
    cdp.send("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"},
                                            {"urlPattern": "*", "resourceType": "Document", "requestStage": "Response"}]})
    ctx = browser.new_context(user_agent=UA, locale="es-PE", service_workers="block",
                              extra_http_headers={"Accept-Language": BROWSER_HEADERS["Accept-Language"]})
    ctx.add_init_script(SPECULATION_GUARD_JS)
    ctx.route_web_socket(re.compile(r".*"), on_websocket)
    ctx.on("response", on_response)
    page = ctx.new_page()
    out: dict = {}
    try:
        resp = page.goto(url, wait_until="load", timeout=60_000)
        try:
            # Una página que nunca queda quieta (sondeo periódico, un worker compartido) no debe costar el paso.
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(1500)
        html = page.content().encode("utf-8")
        status = resp.status if resp else None
        cls = "challenge" if CHALLENGE_RE.search(html[:30000]) else classify(status, html)
        out = {"status": status, "class": cls, "bytes": len(html), "found": cls == "ok" and _found(expect, html), "_body": html}
    except Exception as exc:  # noqa: BLE001
        out = {"status": None, "class": classify(None, b"", f"{type(exc).__name__}: {exc}"),
               "error": f"{type(exc).__name__}: {exc}"[:200], "found": False, "_body": b""}
        doc = next((u for u in verdicts if u in blocked), None)
        if doc and "ERR_BLOCKED_BY_CLIENT" in str(exc):
            # La página (o un salto de su redirección) no se pidió por robots.txt: igual que en los GET.
            out["class"] = "robots" if verdicts[doc] is False else (sub_robots or robots).failure(doc) or "robots-unreachable"
            out["blockedByRobots"] = doc
    finally:
        # Primero se sale de la página, con la revisión todavía activa: los avisos que una página manda al irse
        # («beacons», fetch con keepalive) también pasan por ella.
        try:
            page.goto("about:blank", timeout=10_000)
        except Exception:  # noqa: BLE001
            pass
        ctx.close()
        try:
            cdp.send("Fetch.disable")
            cdp.detach()
        except Exception:  # noqa: BLE001
            pass
        pool.shutdown(wait=False)
    for c in calls:
        c["robots"] = {True: "allowed", False: "disallowed", None: "unreachable"}[allowed(c["url"])]
    page_blocked = out.pop("blockedByRobots", None)
    out.update({"ms": round((time.monotonic() - t) * 1000), "calls": calls, "blockedByRobots": sorted(set(blocked))})
    if page_blocked:
        out["pageBlocked"] = page_blocked
    if answered - checked:
        out["unchecked"] = sorted(answered - checked)
    return out


class _ShortTimeout:
    """El mismo cliente con un plazo corto: ``Robots`` solo llama a ``get``."""

    def __init__(self, client: httpx.Client):
        self.client = client

    def get(self, url: str, **kw):
        return self.client.get(url, timeout=SUB_ROBOTS_TIMEOUT_S, **kw)


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
        sub_robots = Robots(_ShortTimeout(client), agent="Observatorio-ENSO-Peru")
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

                r1 = http_step(client, c["url"], c["expect"], robots=robots)
                keep("http", r1)
                if r1["found"]:
                    res["answer"] = "http"
                elif r1.get("blockedByRobots") or r1["class"] in ("challenge", "dns", "timeout", "connect", "tls"):
                    res["answer"] = r1["class"]  # sin red, con verificación o redirigida a lo que no se pide: el navegador no cambia nada
                else:
                    r2 = http_step(client, c["url"], c["expect"], BROWSER_HEADERS, robots=robots)
                    keep("http-headers", r2)
                    if r2["found"]:
                        res["answer"] = "http-headers"
                    elif r2.get("blockedByRobots") or r2["class"] == "challenge":
                        res["answer"] = r2["class"]
                    elif browser_ok:
                        if browser is None:
                            from playwright.sync_api import sync_playwright
                            pw = sync_playwright().start()
                            browser = pw.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
                        r3 = browser_step(browser, c["url"], c["expect"], robots, sub_robots)
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
