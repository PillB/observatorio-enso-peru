"""Captura una vista del sitio en cada dispositivo de referencia y verifica que se vea bien.

Para cada dispositivo de ``tools.devices`` abre la vista con su motor
(WebKit, Chromium o Firefox), espera a que cargue y comprueba:

* que no haya desplazamiento horizontal (nada más ancho que la pantalla),
* que no haya errores de JavaScript,
* que los botones de filtro midan al menos 32 px de alto en pantallas táctiles,
* que el texto de las noticias no sea menor de 12 px.

Guarda una captura JPEG por dispositivo, una hoja de contacto con todas
(si está instalado Pillow) y ``report.json`` con el resultado.

Uso:
    python -m tools.screenshots --site-dir ../public --out capturas --route "noticias?tab=peru"
    [--engines chromium webkit firefox] [--full-page]
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.devices import DEVICES, context_options  # noqa: E402

CHECK_JS = """() => {
  const doc = document.scrollingElement || document.documentElement;
  const wide = [...document.querySelectorAll('main *')].filter((e) => {
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.right > innerWidth + 1 && getComputedStyle(e).position !== 'fixed'
      && !e.closest('.table-wrap, .kind-chips, .arch-figure, pre');
  }).slice(0, 5).map((e) => `${e.tagName.toLowerCase()}.${[...e.classList].join('.')}`);
  const chips = [...document.querySelectorAll('.kind-chip, .seg button, #news-dep')].map((e) => e.getBoundingClientRect().height);
  const fonts = [...document.querySelectorAll('.feed-text, .feed-title, .feed-meta')].map((e) => parseFloat(getComputedStyle(e).fontSize));
  return { scrollWidth: doc.scrollWidth, innerWidth, wide, minTarget: chips.length ? Math.min(...chips) : null,
           minFont: fonts.length ? Math.min(...fonts) : null, items: document.querySelectorAll('.feed-item').length,
           places: document.querySelectorAll('.tag-place').length };
}"""


def serve(root: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

    handler = functools.partial(Quiet, directory=str(root))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


def contact_sheet(shots: list[tuple[str, Path]], out: Path, height: int = 640) -> bool:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    thumbs = []
    for label, p in shots:
        im = Image.open(p).convert("RGB")
        scale = height / im.height
        im = im.resize((max(1, int(im.width * scale)), height))
        canvas = Image.new("RGB", (max(im.width, 200), height + 34), "white")
        canvas.paste(im, (0, 34))
        ImageDraw.Draw(canvas).text((6, 10), label, fill="black")
        thumbs.append(canvas)
    rows, row, w = [], [], 0
    for t in thumbs:
        if row and w + t.width > 3200:
            rows.append(row)
            row, w = [], 0
        row.append(t)
        w += t.width + 16
    rows.append(row)
    W = max(sum(t.width + 16 for t in r) for r in rows)
    sheet = Image.new("RGB", (W, len(rows) * (height + 50)), (240, 240, 240))
    y = 0
    for r in rows:
        x = 0
        for t in r:
            sheet.paste(t, (x, y))
            x += t.width + 16
        y += height + 50
    sheet.save(out, quality=82)
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--route", default="noticias?tab=peru")
    ap.add_argument("--engines", nargs="*", default=["chromium", "webkit", "firefox"])
    ap.add_argument("--fallback-engine", default="chromium",
                    help="motor para los dispositivos cuyo motor no está instalado (se anota en el informe)")
    ap.add_argument("--full-page", action="store_true")
    ap.add_argument("--anchor", default=".news-filters",
                    help="elemento que se lleva al borde superior antes de capturar (vacío: el comienzo de la página)")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args(argv)
    from playwright.sync_api import sync_playwright

    a.out.mkdir(parents=True, exist_ok=True)
    srv, base = serve(a.site_dir.resolve())
    results, shots = [], []
    with sync_playwright() as p:
        browsers: dict[str, object] = {}

        def browser(engine: str):
            if engine not in browsers:
                exe = os.environ.get(f"PW_{engine.upper()}")
                try:
                    browsers[engine] = (getattr(p, engine).launch(executable_path=exe) if exe else
                                        getattr(p, engine).launch()) if engine in a.engines else None
                except Exception as exc:  # motor no instalado
                    print(f"[aviso] {engine} no disponible: {str(exc).splitlines()[0]}")
                    browsers[engine] = None
            return browsers[engine]

        for dev_id, name, engine, desc, extra in DEVICES:
            if a.only and dev_id not in a.only:
                continue
            used = engine
            b = browser(engine)
            if b is None:
                used = a.fallback_engine
                b = browser(used)
            if b is None:
                raise SystemExit(f"No hay ningún motor disponible para {name}")
            opts = context_options(p, used, desc, extra)
            ctx = b.new_context(**opts)
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.goto(f"{base}#/{a.route}")
            page.wait_for_selector("main h1", timeout=20000)
            page.wait_for_function("!document.querySelector('main .skeleton')", timeout=20000)
            page.wait_for_timeout(400)
            m = page.evaluate(CHECK_JS)
            if a.anchor and not a.full_page:
                page.evaluate("(sel) => { const e = document.querySelector(sel); if (e) window.scrollTo(0, "
                              "e.getBoundingClientRect().top + scrollY - (document.querySelector('.site-header')"
                              "?.offsetHeight || 0) - 8); }", a.anchor)
                page.wait_for_timeout(250)
            problems = []
            if m["scrollWidth"] > m["innerWidth"] + 1 or m["wide"]:
                problems.append(f"desborde horizontal ({m['scrollWidth']} > {m['innerWidth']} px: {', '.join(m['wide'])})")
            if errors:
                problems.append("errores de JavaScript: " + " | ".join(errors[:3]))
            if opts.get("has_touch") and m["minTarget"] is not None and m["minTarget"] < 32:
                problems.append(f"botón táctil de {m['minTarget']:.0f} px de alto")
            if m["minFont"] is not None and m["minFont"] < 12:
                problems.append(f"texto de {m['minFont']:.0f} px")
            shot = a.out / f"{dev_id}.jpg"
            page.screenshot(path=str(shot), full_page=a.full_page, type="jpeg", quality=80)
            vp = opts.get("viewport", {})
            results.append({"id": dev_id, "name": name, "engine": used, "intendedEngine": engine,
                            "viewport": f"{vp.get('width')}×{vp.get('height')}", "dpr": opts.get("device_scale_factor", 1),
                            "metrics": m, "problems": problems, "ok": not problems, "screenshot": shot.name})
            shots.append((f"{name} · {used} · {vp.get('width')}×{vp.get('height')}", shot))
            print(f"{'OK ' if not problems else '!! '}{name:45} {used:9} {vp.get('width')}×{vp.get('height')}"
                  f"  {m['items']} noticias  {'; '.join(problems)}")
            ctx.close()
        for b in browsers.values():
            if b:
                b.close()
    srv.shutdown()
    sheet = contact_sheet(shots, a.out / "hoja-de-contacto.jpg")
    (a.out / "report.json").write_text(json.dumps({"route": a.route, "results": results, "contactSheet": sheet},
                                                  ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    bad = [r for r in results if not r["ok"]]
    print(f"{len(results) - len(bad)} de {len(results)} dispositivos sin problemas")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
