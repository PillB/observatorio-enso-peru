"""Versión del sitio (A clásica, B agrupada), selector de versiones y medición anónima del uso."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS = Path(__file__).resolve().parent / "js"


def test_usage_api_with_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node no está instalado")
    r = subprocess.run([node, "--test", str(JS / "uso.test.mjs")], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
    assert re.search(r"# fail 0", r.stdout) and not re.search(r"# skipped [1-9]", r.stdout), r.stdout[-2000:]


def test_version_b_keeps_every_tab_and_the_server_knows_every_route():
    """La versión B agrupa las pestañas sin perder ninguna, y el servidor acepta el tiempo de todas."""
    sitio = (ROOT / "public" / "assets" / "js" / "sitio.js").read_text(encoding="utf-8")
    nav = re.search(r"export const NAV = (\[\[.*?\]\]);", sitio).group(1)
    routes = re.findall(r"\['([a-z]*)', '[^']+', '[a-z]+'\]", nav)
    assert len(routes) == 13 and len(set(routes)) == 13
    groups = sitio[sitio.index("export const GROUPS"):sitio.index("const groupOf")]
    grouped = re.findall(r"\[\['?([a-z]*)'?, '|\], \['([a-z]*)', '", groups)
    in_groups = re.findall(r"\['([a-z]*)', '[^']+'\]", groups)
    assert sorted(in_groups) == sorted(routes), (grouped, in_groups)
    uso = (ROOT / "functions" / "_lib" / "uso.js").read_text(encoding="utf-8")
    server = re.findall(r"'([a-z]+)'", re.search(r"export const ROUTES = \[(.*?)\];", uso).group(1))
    assert {r or "resumen" for r in routes} <= set(server)
    # Lo que la B pliega existe: cada id es el título de una sección de esa pestaña.
    js = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "public" / "assets" / "js").glob("*.js"))
    fold = sitio[sitio.index("export const FOLD"):sitio.index("export const LIST_MAX")]
    for hid in re.findall(r"'([a-z-]+-h)'", fold):
        assert f'id="{hid}"' in js, hid


def test_no_third_party_tracker_and_the_page_can_reach_its_own_api_only():
    index = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    assert "connect-src 'self'" in index and "script-src 'self'" in index
    sitio = (ROOT / "public" / "assets" / "js" / "sitio.js").read_text(encoding="utf-8")
    assert "document.cookie" not in sitio and "https://" not in sitio


# --- Recorridos en el navegador -----------------------------------------------------------------------------------
from test_browser import ROUTES, PIN_VIEWS, go, site  # noqa: E402,F401
from test_geo_console import console  # noqa: E402,F401

ALL = [*ROUTES, "zona"]
SET_B = "localStorage.setItem('enso-version-sitio', JSON.stringify({v: 'B', chosen: true, at: '2026-01-01'}));"


def _ctx(browser, w=1280, h=900, script=""):
    ctx = browser.new_context(viewport={"width": w, "height": h}, locale="es-PE")
    ctx.add_init_script(PIN_VIEWS + script)
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" else None)
    return ctx, pg


@pytest.mark.browser
@pytest.mark.parametrize("w", [320, 390, 820, 1366])
def test_version_b_renders_every_tab_without_errors_or_overflow(site, browser, w):
    base, _ = site
    ctx, pg = _ctx(browser, w, 844, SET_B)
    try:
        for r in ALL:
            go(pg, base, r)
            assert pg.locator("html").get_attribute("data-sitio") == "B"
            overflow = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            assert overflow <= 1, f"desbordamiento horizontal de {overflow}px en #{r} a {w}px (versión B)"
            # La sección de la pestaña está marcada y la pestaña es la actual, en su menú o en la barra de la sección.
            assert pg.locator("#nav [data-group].active").count() == 1, r
            assert pg.locator("#nav a[aria-current=page]").count() == 1, r
        # Cada menú abierto cabe en la pantalla.
        for g in pg.locator(".nav-gbtn").all():
            g.click()
            box = pg.locator(".nav-menu:not([hidden])").bounding_box()
            assert box["x"] >= 0 and box["x"] + box["width"] <= w + 1, box
            pg.keyboard.press("Escape")
        assert not pg.errors, pg.errors
    finally:
        ctx.close()


@pytest.mark.browser
def test_switcher_changes_the_whole_site_keeps_it_and_nothing_is_lost(site, browser):
    from playwright.sync_api import expect

    base, _ = site
    ctx, pg = _ctx(browser)
    try:
        go(pg, base, "metodologia")
        # Sin servidor de analítica y sin elección: versión A, con las trece pestañas a la vista.
        assert pg.locator("html").get_attribute("data-sitio") == "A"
        assert pg.locator("#nav > a").count() == 13
        btn = pg.locator("#ver-btn")
        expect(btn).to_contain_text("Versión A")
        btn.click()
        expect(pg.get_by_role("dialog", name="Versiones del sitio")).to_be_visible()
        pg.get_by_role("radio", name=re.compile("Versión B")).check()
        expect(btn).to_contain_text("Versión B")
        # B: cinco secciones; las trece pestañas siguen ahí, dentro de los menús.
        assert pg.locator("#nav > [data-group]").count() == 5
        assert pg.locator("#nav a[data-route]").count() == 13
        expect(pg.locator("#subnav a[aria-current=page]")).to_have_text("Metodología")
        # Lo largo queda plegado y se abre; el contenido está en la página en las dos versiones.
        gl = pg.locator("section.foldable", has=pg.locator("#gl-h"))
        expect(gl).to_have_class(re.compile("folded"))
        n_terms = gl.locator("dt").count()
        assert n_terms > 5
        gl.get_by_role("button", name="Mostrar toda la sección").click()
        expect(gl).not_to_have_class(re.compile("folded"))
        expect(gl.get_by_role("button", name="Plegar la sección")).to_have_attribute("aria-expanded", "true")
        # El menú se maneja con el teclado y lleva a la pestaña.
        pg.locator(".nav-group[data-group=nino] .nav-gbtn").focus()
        pg.keyboard.press("ArrowDown")
        expect(pg.locator("#ng-nino a").first).to_be_focused()
        pg.keyboard.press("ArrowDown")
        pg.keyboard.press("Enter")
        expect(pg.locator("main h1")).to_contain_text("Pacífico")
        expect(pg.locator("#ng-nino")).to_be_hidden()
        # La elección se guarda.
        pg.reload()
        expect(pg.locator("html")).to_have_attribute("data-sitio", "B")
        # Las noticias: la lista larga se corta y «Ver N más» la completa.
        go(pg, base, "noticias")
        clip = pg.locator("ul.feed.clipped").first
        if clip.count():
            total = clip.locator("> li").count()
            assert clip.locator("> li:visible").count() == 12 < total
            pg.locator(".clip-btn").first.click()
            assert pg.locator("ul.feed").first.locator("> li:visible").count() == total
        # El selector ofrece también las versiones de esta pestaña y cambia el mapa.
        pg.locator("#ver-btn").click()
        dlg = pg.get_by_role("dialog", name="Versiones del sitio")
        expect(dlg).to_contain_text("Esta pestaña: Noticias")
        dlg.locator("input[name=mapa][value=C]").check()
        assert json.loads(pg.evaluate("localStorage.getItem('enso-mapa-version')"))["v"] == "C"
        # De vuelta en A: nada plegado.
        dlg.locator("input[name=sitio][value=A]").check()
        go(pg, base, "metodologia")
        assert pg.locator(".folded").count() == 0 and pg.locator("#gl-h ~ dl dt, section:has(#gl-h) dt").count() == n_terms
        assert not pg.errors, pg.errors
    finally:
        ctx.close()


@pytest.mark.browser
def test_a_link_previews_version_b_without_changing_the_choice_and_the_tour_opens_folds(site, browser):
    from playwright.sync_api import expect

    base, _ = site
    ctx, pg = _ctx(browser)
    try:
        pg.goto(f"{base}#/metodologia?sitio=B")
        expect(pg.locator("html")).to_have_attribute("data-sitio", "B")
        assert json.loads(pg.evaluate("localStorage.getItem('enso-version-sitio')"))["v"] == "A"
        # El tutorial muestra un elemento de una sección plegada: la sección se abre.
        arch = pg.locator("section.foldable", has=pg.locator("#arch-h"))
        expect(arch).to_have_class(re.compile("folded"))
        pg.evaluate("document.dispatchEvent(new CustomEvent('fold:reveal', {detail: document.querySelector('#arch-fig')}))")
        expect(arch).not_to_have_class(re.compile("folded"))
        assert not pg.errors, pg.errors
    finally:
        ctx.close()


@pytest.mark.browser
def test_usage_is_measured_anonymously_and_shown_in_the_console(console, browser):
    """Una visita en la versión B manda su resumen al ocultarse; la consola lo muestra a quien ingresó."""
    from playwright.sync_api import expect

    # Sin sendBeacon se usa fetch, cuyo cuerpo sí puede leer la prueba (el de un Blob no).
    ctx, pg = _ctx(browser, script="globalThis.ENSO_BACKEND = true; Object.defineProperty(Navigator.prototype, 'sendBeacon', {value: undefined});" + SET_B)
    try:
        sent = []
        pg.on("request", lambda r: sent.append((r.url, r.post_data)) if "/api/uso/e" in r.url else None)
        go(pg, console, "")
        go(pg, console, "metodologia")
        pg.locator("section.foldable", has=pg.locator("#gl-h")).get_by_role("button").click()
        pg.locator("#ver-btn").click()
        pg.locator("input[name=sitio][value=A]").check()
        pg.wait_for_timeout(300)
        pg.evaluate("document.dispatchEvent(new Event('visibilitychange'))")  # visible: no manda nada más
        pg.evaluate("window.dispatchEvent(new Event('pagehide'))")
        pg.wait_for_timeout(500)
        bodies = [json.loads(b) for _, b in sent if b]
        assert bodies, sent
        first = bodies[0]
        # El primer envío es de la versión B (el tiempo hasta el cambio), con la sesión nueva y sin nada más.
        assert first["s"] == "B" and first["n"] == 1 and first["vb"] == "1"
        assert first["v"] == {"resumen": 1, "metodologia": 1} and first["u"] == {"metodologia": 1}
        allowed = {"s", "n", "vb", "rb", "v", "t", "u", "c"}
        assert all(set(b) <= allowed for b in bodies), bodies
        assert any(b.get("c") == [["sitio", "B", "A"]] for b in bodies), bodies
        assert all("cookie" not in (pg.evaluate("document.cookie") or "").lower() for _ in [0])
        # Con «No participar» no se manda nada.
        n = len(sent)
        expect(pg.get_by_role("dialog", name="Versiones del sitio")).to_be_visible()  # sigue abierto tras cambiar
        pg.get_by_label(re.compile("No participar en la medición")).check()
        go(pg, console, "datos")
        pg.evaluate("window.dispatchEvent(new Event('pagehide'))")
        pg.wait_for_timeout(300)
        assert len(sent) == n, sent[n:]
        # La consola: sin sesión, el ingreso; con sesión, las dos versiones.
        pg.goto(console + "admin/analitica.html")
        expect(pg.get_by_role("heading", name="Ingresar")).to_be_visible()
        assert pg.request.get(console + "api/uso/stats").status == 401
        pg.get_by_label("Usuario").fill("revisor01")
        pg.get_by_label("Contraseña").fill("clave-revisor-1")
        pg.get_by_role("button", name="Ingresar").click()
        expect(pg.get_by_role("heading", name="Qué versiones se cambian")).to_be_visible()
        expect(pg.locator(".an-tile").first).to_contain_text("Sesiones")
        expect(pg.locator("#an-body")).to_contain_text("De A a B: 0 · de B a A: 1")
        expect(pg.locator("#an-body")).to_contain_text("Todavía es pronto para comparar")
        expect(pg.get_by_role("link", name="Lugares")).to_be_visible()
        overflow = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 1
        errors = [e for e in pg.errors if "401" not in e]
        assert not errors, errors
    finally:
        ctx.close()


# --- «Cómo leer esto» ---------------------------------------------------------------------------------------------

def test_every_reading_guide_hangs_from_a_title_that_exists():
    js_dir = ROOT / "public" / "assets" / "js"
    leer = (js_dir / "leer.js").read_text(encoding="utf-8")
    code = "".join(p.read_text(encoding="utf-8") for p in js_dir.glob("*.js") if p.name != "leer.js")
    keys = re.findall(r"^  '([^']+)': \{", leer, re.M)
    assert len(keys) >= 30 and len(set(keys)) == len(keys)
    for k in keys:
        if re.fullmatch(r"[a-z][a-z0-9-]*", k):
            # Los gráficos (chartCard) titulan con «<id>-h».
            assert f'id="{k}"' in code or (k.startswith("ch-") and f"'{k[:-2]}'" in code), k
    # Ninguna guía promete algo sin decir qué se ve; y nunca presenta la señal GRD como oficial.
    assert leer.count("que: '") == len(keys)
    assert "no un estado oficial" in leer and "El observatorio no emite alertas" in leer


@pytest.mark.browser
@pytest.mark.parametrize("w", [360, 1280])
def test_reading_guides_appear_in_every_tab_and_open(site, browser, w):
    from playwright.sync_api import expect

    base, _ = site
    ctx, pg = _ctx(browser, w, 844)
    try:
        for r in ALL:
            go(pg, base, r)
            if r == "asistente":
                continue
            expect(pg.locator("main .leer").first).to_be_attached(timeout=8000)
            keys = pg.evaluate("[...document.querySelectorAll('main .leer')].map((d) => d.dataset.leer)")
            assert len(keys) == len(set(keys)), (r, keys)  # una por sección, sin repetirse al redibujar
            overflow = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            assert overflow <= 1, (r, overflow)
        go(pg, base, "costero")
        g = pg.locator("#ch-icen .leer")
        g.locator("summary").click()
        expect(g).to_contain_text("umbrales del ENFEN")
        expect(g.locator(".lsw")).to_have_count(2)
        # Las etiquetas de color dicen qué quiere decir su color al pasar el puntero.
        go(pg, base, "")
        assert pg.locator(".chip[title]").count() >= 5
        assert not pg.errors, pg.errors
    finally:
        ctx.close()


# --- El tutorial en la versión B ----------------------------------------------------------------------------------
import test_tour as T  # noqa: E402


@pytest.mark.browser
@pytest.mark.parametrize("tour", T.TOURS)
@pytest.mark.parametrize("screen", ["telefono-390-oscuro", "escritorio-oscuro"])
def test_every_tour_reaches_its_sections_in_version_b(site, browser, tour, screen):
    """Con la navegación agrupada y las secciones plegadas, cada recorrido encuentra y muestra lo que explica."""
    base, _ = site
    w, h, dark = T.SCREENS[screen]
    ctx, pg = T._ctx(browser, w, h, dark=dark)
    ctx.add_init_script(SET_B)
    try:
        T._start(pg, base, tour)
        assert pg.locator("html").get_attribute("data-sitio") == "B"
        seen = T._walk(pg, f"{tour}@{screen}@B")
        assert len(seen) >= 2
        viol = pg.evaluate("window.__viol")
        assert not viol, sorted(set(viol))[:10]
        assert not pg.errors, pg.errors
    finally:
        ctx.close()
