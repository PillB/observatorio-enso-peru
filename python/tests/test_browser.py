"""Recorridos de usuario en Chromium sobre el sitio construido.

Se ejecutan con ``pytest -m browser --site-dir=../public`` después de
generar ``public/data`` (en CI, con las fuentes capturadas). Se usan
roles y textos visibles, no funciones internas de la aplicación.
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import re
import threading
from pathlib import Path

import pytest

pytestmark = pytest.mark.browser

pw = pytest.importorskip("playwright.sync_api")
expect = pw.expect

ROUTES = ["", "costero", "pacifico", "oceano", "mapa", "historia", "datos", "metodologia", "asistente"]
VIEWPORTS = {"telefono-320": (320, 640), "telefono-390": (390, 844), "tableta": (820, 1180), "escritorio": (1366, 900)}


@pytest.fixture(scope="session")
def site(request):
    d = request.config.getoption("--site-dir")
    if not d:
        pytest.skip("requiere --site-dir")
    root = Path(d).resolve()
    if not (root / "data" / "dashboard.json").exists():
        pytest.fail(f"{root}/data/dashboard.json no existe: genere la publicación antes")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/", root
    srv.shutdown()


@pytest.fixture(scope="session")
def browser():
    with pw.sync_playwright() as p:
        exe = os.environ.get("PW_CHROMIUM")
        b = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser, request):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="es-PE")
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" else None)
    yield pg
    if request.node.rep_call.failed if hasattr(request.node, "rep_call") else False:
        Path("test-results").mkdir(exist_ok=True)
        pg.screenshot(path=f"test-results/{request.node.name}.png", full_page=True)
    ctx.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    out = yield
    rep = out.get_result()
    setattr(item, "rep_" + rep.when, rep)


def go(page, base, route=""):
    page.goto(f"{base}#/{route}")
    expect(page.locator("main h1")).to_have_count(1, timeout=15000)
    expect(page.locator("main .skeleton")).to_have_count(0, timeout=15000)


@pytest.mark.parametrize("vp", VIEWPORTS, ids=list(VIEWPORTS))
def test_every_section_renders_without_errors_or_overflow(site, browser, vp):
    base, _ = site
    w, h = VIEWPORTS[vp]
    ctx = browser.new_context(viewport={"width": w, "height": h})
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    for r in ROUTES:
        go(pg, base, r)
        assert pg.locator("main h1").count() == 1, r
        overflow = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 1, f"desbordamiento horizontal de {overflow}px en #{r} a {w}px"
    assert not errors, errors
    ctx.close()


def test_home_shows_official_status_and_dates(site, page):
    base, root = site
    dash = json.loads((root / "data" / "dashboard.json").read_text(encoding="utf-8"))
    go(page, base)
    cards = page.locator("[data-tour-id=official-status] .status-card")
    assert cards.count() == 2
    noaa = dash["official"]["noaa"]
    if not noaa.get("stale"):
        assert page.get_by_text(noaa["statusEs"]).first.is_visible()
    enfen = dash["official"].get("enfen", {})
    if enfen.get("stale"):
        # Un estado vencido no se muestra como vigente.
        assert cards.nth(0).get_by_text("Dato actual no disponible").is_visible()
    # La señal GRD está separada de lo oficial y lo dice.
    grd = page.locator("[data-tour-id=grd]")
    assert grd.get_by_text("No equivale al sistema oficial").is_visible()


def test_values_shown_match_publication(site, page):
    """Paridad tarjeta ↔ datos: el ICEN mostrado es el publicado."""
    base, root = site
    dash = json.loads((root / "data" / "dashboard.json").read_text(encoding="utf-8"))
    icen = dash["series"]["icen"]["latest"]
    go(page, base)
    card = page.locator(".metric", has_text="ICEN oficial").first
    if icen["stale"]:
        assert card.get_by_text("Dato actual no disponible").is_visible()
    else:
        shown = f"{abs(icen['value']):.2f}".replace(".", ",")  # coma decimal
        assert shown in card.inner_text()


def test_navigation_and_keyboard(site, page):
    base, _ = site
    go(page, base)
    page.get_by_role("link", name="Historia").click()
    page.wait_for_selector("#ev-table")
    assert page.locator("nav a[aria-current=page]").inner_text().strip() == "Historia"
    page.get_by_role("button", name="El Niño", exact=True).click()
    hidden = page.locator("#ev-table tbody tr[data-phase=cool]").first
    assert hidden.is_hidden()
    # Saltar al contenido: primer elemento enfocable de la página.
    page.reload()
    go(page, base, "historia")
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.textContent").strip() == "Saltar al contenido"


def test_theme_persists_after_reload(site, page):
    base, _ = site
    go(page, base)
    page.locator("#theme-btn").click()
    theme = page.evaluate("document.documentElement.dataset.theme")
    page.reload()
    go(page, base)
    assert page.evaluate("document.documentElement.dataset.theme") == theme


def test_tutorial_start_pause_resume_and_clear(site, page):
    base, _ = site
    go(page, base)
    page.get_by_role("button", name="Ayuda y tutorial").click()
    dlg = page.get_by_role("dialog", name="Ayuda y tutorial")
    assert dlg.locator(".tour-menu li").count() == 13
    dlg.get_by_role("button", name=re.compile("^Inicio rápido")).click()
    pop = page.locator(".tour-pop")
    assert pop.get_by_text("paso 1 de").is_visible()
    pop.get_by_role("button", name="Siguiente").click()
    assert pop.get_by_text("paso 2 de").is_visible()
    pop.get_by_role("button", name="Pausar").click()
    assert pop.count() == 0
    page.reload()
    go(page, base)
    page.get_by_role("button", name="Ayuda y tutorial").click()
    dlg.get_by_role("button", name="Reanudar").click()
    assert page.locator(".tour-pop").get_by_text("paso 2 de").is_visible()
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Ayuda y tutorial").click()
    dlg.get_by_role("button", name="Borrar progreso del tutorial").click()
    assert dlg.get_by_role("button", name="Reanudar").count() == 0


def test_full_tour_visits_every_target(site, page):
    base, _ = site
    go(page, base)
    page.get_by_role("button", name="Ayuda y tutorial").click()
    page.get_by_role("button", name=re.compile("^Recorrido completo")).click()
    for _ in range(9):
        pop = page.locator(".tour-pop")
        assert pop.is_visible()
        assert pop.get_by_text("Este elemento no está visible").count() == 0, pop.inner_text()
        pop.get_by_role("button", name=re.compile("Siguiente|Terminar")).click()
    assert page.locator(".tour-pop").count() == 0


def test_assistant_answers_with_evidence_and_refuses_alerts(site, page):
    base, _ = site
    go(page, base, "asistente")
    page.get_by_role("button", name="¿Qué indica el valor más reciente de Niño 1+2 y cuál es su periodo de validez?").click()
    ans = page.locator(".qa-a").last
    assert "Evidencia:" in ans.inner_text() and "serie:nino12_oisst@" in ans.inner_text()
    page.get_by_label("Su pregunta").fill("¿Cuál es el SOI costero?")
    page.get_by_role("button", name="Preguntar").click()
    assert "No existe un «SOI costero»" in page.locator(".qa-a").last.inner_text()
    page.get_by_label("Su pregunta").fill("<img src=x onerror=alert(1)> ¿debo evacuar?")
    page.get_by_role("button", name="Preguntar").click()
    assert page.locator(".qa-q img").count() == 0
    assert "no emite alertas" in page.locator(".qa-a").last.inner_text()


def test_map_animation_and_table(site, page):
    base, _ = site
    go(page, base, "mapa")
    page.wait_for_selector("#map-svg svg")
    assert page.locator("#map-svg .land").count() == 1, "el mapa debe tener costa"
    first = page.locator("#map-date").inner_text()
    page.locator("#map-range").fill("0")
    assert page.locator("#map-date").inner_text() != first
    page.get_by_role("button", name="Reproducir animación").click()
    page.get_by_role("button", name="Pausar animación").click()
    page.get_by_text("Ver los valores de esta semana en una tabla").click()
    assert page.locator("#map-table tbody tr").count() == 4


def test_downloads_exist_and_csv_is_safe(site, page):
    base, root = site
    go(page, base, "datos")
    hrefs = page.locator("[data-tour-id=downloads] a").evaluate_all("els => els.map(a => a.getAttribute('href'))")
    assert len(hrefs) > 10
    for h in hrefs:
        assert (root / h).exists(), h
    with page.expect_download() as dl:
        page.get_by_role("link", name="Descargar CSV").click()
    assert dl.value.suggested_filename.endswith(".csv")


def test_mismatched_publication_is_not_mixed(site, page):
    base, root = site
    series = json.loads((root / "data" / "series.json").read_text(encoding="utf-8"))
    series["publicationId"] = "otra-publicacion"
    page.route("**/data/series.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(series)))
    go(page, base, "costero")
    page.wait_for_selector("#banner .notice-alert")
    assert "otra publicación" in page.locator("#banner").inner_text()


def test_data_failure_shows_containment_text(site, page):
    base, _ = site
    page.route("**/data/dashboard.json*", lambda r: r.fulfill(status=503, body="no"))
    page.goto(base)
    page.wait_for_selector("text=Datos actuales en proceso de validación")


def test_no_inline_scripts_and_strict_csp(site):
    _, root = site
    html = (root / "index.html").read_text(encoding="utf-8")
    assert "script-src 'self'" in html and "unsafe-eval" not in html
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "no debe haber scripts en línea"
