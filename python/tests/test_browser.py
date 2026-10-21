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

ROUTES = ["", "costero", "pacifico", "oceano", "mapa", "historia", "noticias", "datos", "metodologia", "asistente"]
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


# ``playwright`` y ``browser`` están en conftest.py (los comparte la consola de lugares).


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
    expect(dlg.locator(".tour-menu li")).to_have_count(13)
    dlg.get_by_role("button", name=re.compile("^Inicio rápido")).click()
    pop = page.locator(".tour-pop")
    expect(pop.get_by_text("paso 1 de")).to_be_visible()
    pop.get_by_role("button", name="Siguiente").click()
    expect(pop.get_by_text("paso 2 de")).to_be_visible()
    pop.get_by_role("button", name="Pausar").click()
    expect(pop).to_have_count(0)
    page.reload()
    go(page, base)
    page.get_by_role("button", name="Ayuda y tutorial").click()
    dlg.get_by_role("button", name="Reanudar").click()
    expect(page.locator(".tour-pop").get_by_text("paso 2 de")).to_be_visible()
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Ayuda y tutorial").click()
    dlg.get_by_role("button", name="Borrar progreso del tutorial").click()
    expect(dlg.get_by_role("button", name="Reanudar")).to_have_count(0)


def test_full_tour_visits_every_target(site, page):
    base, _ = site
    go(page, base)
    page.get_by_role("button", name="Ayuda y tutorial").click()
    page.get_by_role("button", name=re.compile("^Recorrido completo")).click()
    for _ in range(9):
        pop = page.locator(".tour-pop")
        expect(pop).to_be_visible()
        assert pop.get_by_text("Este elemento no está visible").count() == 0, pop.inner_text()
        pop.get_by_role("button", name=re.compile("Siguiente|Terminar")).click()
    expect(page.locator(".tour-pop")).to_have_count(0)


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


def test_news_view_shows_official_feed_and_news(site, page):
    base, root = site
    feed = json.loads((root / "data" / "feed.json").read_text(encoding="utf-8"))
    go(page, base, "noticias")
    expect(page.locator("[data-tab]")).to_have_count(3)
    expect(page.locator("#news-body section.card")).to_have_count(len(feed["groups"]), timeout=10000)
    first = next(i for g in feed["groups"] for i in g["items"])  # el grupo de alertas puede no tener avisos
    expect(page.locator("#news-body .feed-title").first).to_contain_text(first["title"][:30])
    page.locator("[data-tab=peru]").click()
    expect(page.locator("[data-tab=peru]")).to_have_attribute("aria-selected", "true")
    assert "tab=peru" in page.url
    clusters = root / "data" / "news" / "clusters.json"
    if clusters.exists():
        peru = [c for c in json.loads(clusters.read_text(encoding="utf-8"))["clusters"] if c["region"] == "peru"]
        expect(page.locator("#news-body .feed-item")).to_have_count(len(peru))
    page.locator("#feeds-status summary").click()
    expect(page.locator("#feeds-status")).to_have_attribute("open", "")
    go(page, base, "metodologia")
    expect(page.locator("#arch-fig svg")).to_have_count(1, timeout=10000)


def test_alerts_card_says_when_no_alert_source_was_read(site, page):
    """Una corrida que no leyó ninguna fuente de alertas muestra las últimas conocidas: el aviso lo dice, haya
    avisos o no (la línea «0 de N fuentes» sola no alcanza)."""
    base, root = site
    feed = json.loads((root / "data" / "feed.json").read_text(encoding="utf-8"))
    sample = dict(next(i for g in feed["groups"] for i in g["items"]), group="alertas")
    alerts = next((g for g in feed["groups"] if g["id"] == "alertas"), None)
    if alerts is None:
        alerts = {"id": "alertas", "label": "Alertas oficiales", "items": []}
        feed["groups"].insert(0, alerts)
    alerts["sources"] = [{**s, "ok": False, "error": "no se leyeron las noticias en esta corrida"}
                         for s in alerts.get("sources") or [{"id": "indeci", "name": "INDECI", "url": "https://www.gob.pe/indeci"}]]
    body = {}
    page.route("**/data/feed.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=body["v"]))
    for items, text in (([sample], "los avisos de abajo son los últimos conocidos"),
                        ([], "Ninguna fuente de alertas respondió")):
        alerts["items"] = items
        body["v"] = json.dumps(feed)
        page.goto("about:blank")  # la vista guarda el feed ya leído
        go(page, base, "noticias")
        expect(page.locator("#news-body section.card").first.locator(".notice-alert")).to_contain_text(text, timeout=10000)


def test_feeds_table_names_why_a_feed_was_not_asked(site, page):
    """Revisión 7: todo feed omitido decía «Omitido (robots.txt)», también los que se leen una vez al día y no se
    pidieron porque no se sabía cuándo se habían pedido; y uno arrastrado decía «Lectura del…» sin haberse leído."""
    base, root = site
    feeds = json.loads((root / "data" / "news" / "feeds.json").read_text(encoding="utf-8"))
    a, b, c = feeds["feeds"][:3]
    a.update(ok=False, skipped="robots", error="omitido: su robots.txt no permite pedir este feed")
    b.update(ok=False, skipped="reader-unknown", httpStatus=None, error="no se pidió: no se sabía cuándo se pidió")
    c.update(ok=False, skipped="reader-unknown", httpStatus=None, carried=True, checkedAt="2026-10-20T04:40:00+00:00",
             error="no se pidió: no se sabía cuándo se pidió")
    page.route("**/data/news/feeds.json*", lambda r: r.fulfill(status=200, content_type="application/json",
                                                               body=json.dumps(feeds)))
    go(page, base, "noticias")
    page.locator("#feeds-status summary").click()
    rows = page.locator("#feeds-status tbody tr")
    expect(rows.nth(0)).to_contain_text("Omitido (robots.txt)", timeout=10000)
    for row in (rows.nth(1), rows.nth(2)):
        expect(row).to_contain_text("Omitido")
        expect(row).not_to_contain_text("robots.txt")
    expect(rows.nth(2)).to_contain_text("Corrida del")
    expect(rows.nth(2)).not_to_contain_text("Lectura del")


def test_items_link_to_live_source_and_archived_copy(site, page):
    """Cada noticia y cada dato oficial enlaza a su fuente en vivo y a una copia servida por el sitio."""
    base, root = site
    go(page, base, "noticias?tab=peru")
    item = page.locator("#news-body .feed-item").first
    expect(item).to_be_visible(timeout=10000)
    live = item.get_by_role("link", name="Nota original")
    arch = item.get_by_role("link", name="Copia archivada")
    assert live.get_attribute("href").startswith("http")
    href = arch.get_attribute("href")
    assert href.startswith("data/archive/news/") and "#" in href, href
    page_file, anchor = href.split("#")
    assert f'id="{anchor}"' in (root / page_file).read_text(encoding="utf-8")
    # Filtro por peligro: la cuenta del filtro coincide con la lista.
    sel = page.locator("#news-haz")
    opt = sel.locator("option").nth(1)
    value, label = opt.get_attribute("value"), opt.inner_text()
    sel.select_option(value)
    expect(page).to_have_url(re.compile(rf"peligro={value}"))
    n = int(re.search(r"\((\d+)\)", label).group(1))
    expect(page.locator("#news-body .feed-item")).to_have_count(n)
    expect(page.locator("#news-live")).to_contain_text(str(n))
    go(page, base, "noticias?tab=oficial")
    off = page.locator("#news-body .feed-item").first
    expect(off.get_by_role("link", name="Copia archivada")).to_have_count(1, timeout=10000)
    a = off.get_by_role("link", name="Copia archivada").get_attribute("href")
    assert (root / a.split("#")[0]).exists(), a  # las alertas enlazan a su entrada en la página del día
    snap = off.get_by_role("link", name="Respuesta original bajada")
    if snap.count():  # la respuesta de la fuente tal como se bajó en esta corrida
        assert (root / snap.get_attribute("href")).exists()
    go(page, base, "")
    doc = page.locator(".status-card").get_by_role("link", name="Copia archivada").first
    assert (root / doc.get_attribute("href")).exists()


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


# --- Dispositivos de referencia (tools/devices.py) ----------------------------

@pytest.fixture(scope="module", params=["chromium", "webkit", "firefox"])
def engine(request, playwright, browser):
    """El motor pedido si está instalado (WebKit = Safari de iPhone y Mac); si no, la prueba se omite."""
    name = request.param
    if name == "chromium":
        yield playwright, browser
        return
    exe = os.environ.get(f"PW_{name.upper()}")
    try:
        b = getattr(playwright, name).launch(executable_path=exe) if exe else getattr(playwright, name).launch()
    except Exception as exc:  # motor no instalado en este equipo
        if os.environ.get("CI"):  # en CI se instalan los tres motores: si uno no arranca, es una falla
            raise
        pytest.skip(f"{name} no está instalado: {str(exc).splitlines()[0]}")
    yield playwright, b
    b.close()


def test_news_fits_every_reference_device(site, engine):
    """Noticias (pestaña Perú) sin desborde horizontal ni errores en cada dispositivo de su motor."""
    from tools.devices import DEVICES, context_options

    base, _ = site
    p, b = engine
    name = b.browser_type.name
    checked = 0
    for dev_id, label, eng, desc, extra in DEVICES:
        if eng != name and not (name == "chromium" and os.environ.get("ENSO_ALL_DEVICES_ON_CHROMIUM", "1") == "1"):
            continue
        ctx = b.new_context(**context_options(p, name, desc, extra))
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(f"{base}#/noticias?tab=peru")
        expect(pg.locator(".news-filters")).to_be_visible(timeout=15000)
        # clientWidth, no innerWidth: con la emulación móvil innerWidth crece con el desborde.
        dims = pg.evaluate("() => [document.scrollingElement.scrollWidth, document.documentElement.clientWidth]")
        assert dims[0] <= dims[1] + 1, f"{label}: la página mide {dims[0]} px en una pantalla de {dims[1]} px"
        assert not errors, f"{label}: {errors}"
        if dev_id not in ("kaios-flip",):
            pg.get_by_role("button", name=re.compile("^Radio y TV")).click()
            expect(pg).to_have_url(re.compile(r"tipo=radiotv"))
        ctx.close()
        checked += 1
    if not checked:
        pytest.skip(f"ningún dispositivo de referencia usa {name}")
