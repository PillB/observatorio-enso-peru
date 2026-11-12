"""Máquinas de estado implícitas del sitio (docs/maquinas-de-estado.md): cada prueba reproduce un estado errado que
se encontró al inventariarlas y comprueba que ya no ocurre.

- Tutorial: «Anterior» hacia un primer paso opcional que esta publicación no trae dejaba la ventana «cargando».
- Vista previa de una versión (?sitio=B): no había forma de quedarse con ella, y el parámetro seguía mandando.
- Animación del mapa: al volver a pintar la vista (selector de versiones) seguía escribiendo en el mapa nuevo.
- Cambio de vista: una vista que la persona ya dejó anunciaba «view:ready» (el tutorial la tomaba por la nueva).
- Lectura de datos: un corte de red dejaba el archivo en «no disponible» hasta recargar la página.
"""

from __future__ import annotations

import json
import re

import pytest

from tests.test_browser import PIN_VIEWS, browser, go, site  # noqa: F401  (fixtures compartidas)

pytestmark = pytest.mark.browser

pw = pytest.importorskip("playwright.sync_api")
expect = pw.expect


def _ctx(browser, w=1280, h=900, script=""):
    ctx = browser.new_context(viewport={"width": w, "height": h}, locale="es-PE", reduced_motion="reduce")
    ctx.add_init_script(PIN_VIEWS + script)
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    return ctx, pg


def test_tour_back_into_a_missing_optional_first_step_does_not_hang(site, browser):
    """Memoria empieza con un paso opcional («Lo que dice la historia ahora», solo con un Niño en curso). Sin él,
    «Anterior» desde el segundo paso iba a buscar el paso -1: la ventana quedaba en «cargando» para siempre. Y la
    dirección de un recorrido anterior se heredaba: empezar este después de usar «Anterior» en otro, igual."""
    base, _ = site
    ctx, pg = _ctx(browser)
    try:
        go(pg, base, "costero")
        pg.add_style_tag(content=".hz-context { display: none !important; }")
        pop = pg.locator(".tour-pop")
        # Otro recorrido, con «Anterior»: la dirección no debe pasar al siguiente.
        pg.locator("#help-btn").click()
        pg.locator("#tour-dialog .tour-menu [data-mode='costero']").click()
        expect(pop).to_have_attribute("data-state", "ready", timeout=30000)
        pop.locator("[data-act='next']").click()
        expect(pop).to_have_attribute("data-state", "ready", timeout=30000)
        pop.locator("[data-act='prev']").click()
        expect(pop).to_have_attribute("data-state", "ready", timeout=30000)
        pg.keyboard.press("Escape")
        expect(pop).to_have_count(0)
        # El de la memoria: el primer paso no está y se salta hacia adelante.
        pg.locator("#help-btn").click()
        pg.locator("#tour-dialog .tour-menu [data-mode='memoria']").click()
        expect(pop).to_have_attribute("data-state", "ready", timeout=30000)
        expect(pop.locator("#tour-title")).to_have_text("Descargar los datos")
        # «Anterior» no tiene adónde ir: vuelve a este paso, listo, y no queda cargando.
        pop.locator("[data-act='prev']").click()
        expect(pop).to_have_attribute("data-state", "ready", timeout=30000)
        expect(pop.locator("#tour-title")).to_have_text("Descargar los datos")
        assert not pg.errors, pg.errors
    finally:
        ctx.close()


def test_a_previewed_site_version_can_be_kept_and_the_link_stops_deciding(site, browser):
    base, _ = site
    ctx, pg = _ctx(browser)
    try:
        pg.goto(f"{base}#/metodologia?sitio=B")
        expect(pg.locator("html")).to_have_attribute("data-sitio", "B")
        pg.locator("#ver-btn").click()
        dlg = pg.get_by_role("dialog", name="Versiones del sitio")
        expect(dlg).to_contain_text("desde un enlace")
        dlg.get_by_role("button", name="Quedarme con la versión B").click()
        st = json.loads(pg.evaluate("localStorage.getItem('enso-version-sitio')"))
        assert st["v"] == "B" and st["chosen"] is True
        assert "sitio=" not in pg.url
        # El panel ya no dice que es de un enlace, y recargar deja la elegida.
        expect(dlg).not_to_contain_text("desde un enlace")
        pg.reload()
        expect(pg.locator("html")).to_have_attribute("data-sitio", "B")
        assert "Vista de un enlace" not in (pg.locator("#ver-btn").get_attribute("title") or "")
        # Y se puede volver a la A (la opción marcada es la que se ve).
        pg.locator("#ver-btn").click()
        dlg.locator("input[name=sitio][value=A]").check()
        expect(pg.locator("html")).to_have_attribute("data-sitio", "A")
        assert json.loads(pg.evaluate("localStorage.getItem('enso-version-sitio')"))["v"] == "A"
        assert not pg.errors, pg.errors
    finally:
        ctx.close()


def test_choosing_a_map_view_from_the_panel_drops_the_link_view(site, browser):
    """?vista= de un enlace se ve sin elegirla; elegir otra en el panel la deja como la suya y quita la del enlace."""
    base, _ = site
    ctx, pg = _ctx(browser)
    try:
        pg.goto(f"{base}#/noticias?tab=oficial&vista=cuencas")
        expect(pg.locator(".amap-views [data-vista='cuencas']")).to_have_attribute("aria-pressed", "true", timeout=20000)
        pg.locator("#ver-btn").click()
        dlg = pg.get_by_role("dialog", name="Versiones del sitio")
        expect(dlg.locator(".ver-preview")).to_contain_text("enlace")
        dlg.get_by_role("button", name="Quedarme con esta").click()
        assert json.loads(pg.evaluate("localStorage.getItem('enso-vista-noticias')"))["v"] == "cuencas"
        assert "vista=" not in pg.url
        expect(dlg.locator(".ver-preview")).to_have_count(0)
        assert not pg.errors, pg.errors
    finally:
        ctx.close()


def test_map_animation_stops_when_the_view_is_painted_again(site, browser):
    base, _ = site
    ctx, pg = _ctx(browser)
    try:
        go(pg, base, "mapa")
        last = pg.locator("#map-date").inner_text()
        pg.locator("#map-speed").select_option("200")
        pg.locator("#map-play").click()
        pg.wait_for_timeout(500)
        assert pg.locator("#map-date").inner_text() != last  # la animación corre
        # Cambiar la versión del sitio vuelve a pintar la vista sin cambiar de ruta.
        pg.locator("#ver-btn").click()
        pg.locator("input[name=sitio][value=B]").check()
        expect(pg.locator("html")).to_have_attribute("data-sitio", "B")
        # (Corta: la animación vieja llega sola a la última semana en ~10 s.)
        expect(pg.locator("#map-date")).to_have_text(last, timeout=2000)
        pg.wait_for_timeout(1200)
        # La animación vieja no escribe en el mapa nuevo: sigue en la última semana y en pausa.
        assert pg.locator("#map-date").inner_text() == last
        expect(pg.locator("#map-play")).to_contain_text("Reproducir")
        assert not pg.errors, pg.errors
    finally:
        ctx.close()


def test_only_the_current_view_announces_it_is_ready(site, browser):
    base, _ = site
    ctx, pg = _ctx(browser)
    try:
        go(pg, base, "")
        events = pg.evaluate("""() => new Promise((res) => {
            const got = [];
            document.addEventListener('view:ready', (e) => got.push(e.detail));
            location.hash = '#/datos';
            setTimeout(() => { location.hash = '#/metodologia'; }, 0);
            setTimeout(() => res(got), 4000);
        })""")
        assert events == ["metodologia"], events
        assert not pg.errors, pg.errors
    finally:
        ctx.close()


def test_a_network_blip_does_not_leave_a_file_unavailable_until_reload(site, browser):
    base, _ = site
    ctx, pg = _ctx(browser)
    fails = {"n": 0}

    def once(route):
        if fails["n"] == 0:
            fails["n"] += 1
            route.abort()
        else:
            route.continue_()

    try:
        go(pg, base, "")
        pg.route(re.compile(r".*/data/feed\.json.*"), once)
        go(pg, base, "noticias")
        expect(pg.locator("#news-body")).to_contain_text("No disponible en esta publicación")
        go(pg, base, "costero")
        go(pg, base, "noticias")
        expect(pg.locator("#news-body .feed").first).to_be_visible(timeout=15000)
        assert fails["n"] == 1
    finally:
        ctx.close()
