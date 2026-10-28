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
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytestmark = pytest.mark.browser

pw = pytest.importorskip("playwright.sync_api")
expect = pw.expect

ROUTES = ["", "costero", "pacifico", "oceano", "mapa", "historia", "memoria", "noticias", "datos", "metodologia", "asistente"]
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


LONG = "https://www.dhn.mil.pe/Archivos/oceanografia/enfen/comunicado-oficial/" + "sin-cortes-" * 12 + "18-2026.pdf"
TEXT_KEYS = {"message", "title", "summary", "error", "text", "outlet", "note", "statusEs", "product", "institution"}


def _stretch(v):
    """Agrega una URL larga sin espacios a cada texto que viene de las fuentes o del registro de incidencias."""
    if isinstance(v, dict):
        return {k: (f"{x} {LONG}" if k in TEXT_KEYS and isinstance(x, str) and x else _stretch(x)) for k, x in v.items()}
    if isinstance(v, list):
        return [_stretch(x) for x in v]
    return v


def _with_an_incident(report: dict, clean: bool) -> dict:
    """El informe de la corrida con al menos una incidencia que estirar. Una corrida sin incidencias es la
    situación normal en producción: sin esto la prueba fallaba justo cuando todo respondía bien, y detenía el
    despliegue (21 de octubre de 2026). ``clean`` simula esa corrida quitando las incidencias del sitio armado."""
    events = [e for e in report.get("events") or [] if not clean or e.get("severity") == "info"]
    if not any(e.get("severity") != "info" for e in events):
        events.append({"severity": "warning", "source": "prueba", "stage": "fetch", "code": "fetch-failed",
                       "message": "sin respuesta válida para", "fingerprint": "prueba"})
    return {**report, "events": events}


@pytest.mark.parametrize("w,clean", [(320, False), (390, False), (320, True)])
def test_long_unbroken_text_from_the_sources_never_widens_the_page(site, browser, w, clean):
    """Revisión 8: una incidencia con una URL larga (p. ej. «sin respuesta válida para https://…») ensanchaba
    Metodología en un teléfono, y la comprobación del navegador detenía el despliegue de los datos oficiales.
    Ningún texto que venga de una fuente o del registro de incidencias puede ensanchar la página, haya o no
    incidencias en la corrida real."""
    from urllib.parse import urlsplit

    base, root = site
    ctx = browser.new_context(viewport={"width": w, "height": 800})

    def stretched(route):
        rel = urlsplit(route.request.url).path.split("/data/", 1)[1]
        f = root / "data" / rel
        if not f.is_file():
            return route.continue_()
        data = json.loads(f.read_text(encoding="utf-8"))
        if rel == "run-report.json":
            data = _with_an_incident(data, clean)
        route.fulfill(status=200, content_type="application/json", body=json.dumps(_stretch(data)))

    ctx.route("**/data/**/*.json*", stretched)
    pg = ctx.new_page()
    try:
        for r in ROUTES:
            go(pg, base, r)
            overflow = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            assert overflow <= 1, f"desbordamiento horizontal de {overflow}px en #{r} a {w}px"
        go(pg, base, "metodologia")
        expect(pg.locator(".incidents li").first).to_contain_text("sin-cortes-")
    finally:
        ctx.close()


@pytest.mark.parametrize("w", [320, 390, 820, 1000, 1100, 1366])
def test_indicator_values_never_split_across_lines(site, browser, w):
    """El corte de textos largos (revisión 8) dejaba que la tarjeta partiera «+3,98 °C» en «+3,98 °» y «C», o
    «−20,3» tras la coma, a unos 1100 px. Un valor con su unidad ocupa una sola línea y no sale de su tarjeta."""
    base, _ = site
    ctx = browser.new_context(viewport={"width": w, "height": 900})
    pg = ctx.new_page()
    try:
        for r in ("", "oceano"):
            go(pg, base, r)
            expect(pg.locator(".metric-value").first).to_be_visible()
            bad = pg.evaluate("""() => [...document.querySelectorAll('.metric-value:not(.na)')].filter((e) => e.offsetParent)
              .map((e) => { const rg = document.createRange(); rg.selectNodeContents(e);
                const lines = new Set([...rg.getClientRects()].map((x) => Math.round(x.top))).size;
                const out = e.getBoundingClientRect().right - e.closest('.card').getBoundingClientRect().right;
                return { text: e.textContent, lines, out }; })
              .filter((x) => x.lines > 1 || x.out > 0.5)""")
            assert not bad, f"#{r} a {w}px: {bad}"
    finally:
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


def test_assistant_answers_d20_with_the_published_values(site, page):
    base, root = site
    dash = json.loads((root / "data" / "dashboard.json").read_text(encoding="utf-8"))
    sig = next(s for s in dash["grd"]["signals"] if s["id"] == "d20_coastal")
    go(page, base, "asistente")
    page.get_by_label("Su pregunta").fill("¿Cuál es la profundidad del D20?")
    page.get_by_role("button", name="Preguntar").click()
    ans = page.locator(".qa-a").last.inner_text()
    assert "no publica" not in ans and "GODAS" in ans
    assert f"{abs(sig['value']):.1f}".replace(".", ",") in ans and f"grd:d20_coastal@{sig['period']}" in ans


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


def test_methodology_switches_between_the_two_architecture_diagrams(site, page):
    """Metodología abre el diagrama simplificado, cambia al completo y, al tocar una caja o una conexión, escribe
    debajo su explicación (en el teléfono no hay «hover» que muestre el <title> del SVG)."""
    base, _ = site
    go(page, base, "metodologia")
    fig = page.locator("#arch-fig")
    expect(fig.locator("svg[aria-labelledby^='as-']")).to_have_count(1, timeout=10000)
    expect(page.locator("[data-arch=simple]")).to_have_attribute("aria-pressed", "true")
    note = page.locator("#arch-note")
    expect(note).to_be_hidden()
    fig.locator("[data-edge=A] text").first.click()
    expect(note).to_be_visible()
    assert note.inner_text().startswith("A. ")
    page.locator("[data-arch=full]").click()
    expect(fig.locator("svg[aria-labelledby^='af-']")).to_have_count(1, timeout=10000)
    expect(page.locator("#arch-open")).to_have_attribute("href", "assets/arquitectura.svg")
    expect(note).to_be_hidden()
    fig.locator("[data-node=fetch] text").first.click()
    expect(note).to_contain_text("GitHub Actions")


def test_architecture_explorer_navigates_from_the_diagrams_to_their_annexes(site, page):
    """arquitectura.html: tocar una caja del simplificado abre su anexo (o deja elegir entre sus anexos), la
    etiqueta A4 del completo abre el A4, «Volver» regresa al completo, hay versión en inglés y Metodología enlaza
    cada etiqueta al explorador. Ningún texto de un anexo se sale de su caja."""
    base, _ = site
    page.goto(f"{base}arquitectura.html")
    fig = page.locator("#ax-fig")
    expect(fig.locator("svg[aria-labelledby^='as-']")).to_have_count(1, timeout=10000)
    # La consola del simplificado tiene un solo anexo (A7): se abre directamente.
    fig.locator("[data-node=s-consola] text").first.click()
    expect(page).to_have_url(re.compile(r"#a7$"))
    expect(fig.locator("svg[aria-labelledby^='a7-']")).to_have_count(1, timeout=10000)
    expect(page.locator("#ax-title")).to_contain_text("A7")
    # Las cajas del anexo explican qué son y enlazan a sus vecinos.
    fig.locator("[data-node=login] text").first.click()
    expect(page.locator("#ax-note")).to_contain_text("SameSite=Strict")
    fig.locator('a[data-annex="full"]').click()
    expect(fig.locator("svg[aria-labelledby^='af-']")).to_have_count(1, timeout=10000)
    fig.locator('[data-node=fetch] a[data-annex="a4"]').click()
    expect(page).to_have_url(re.compile(r"#a4$"))
    expect(fig.locator("svg[aria-labelledby^='a4-']")).to_have_count(1, timeout=10000)
    page.locator("[data-lang=en]").click()
    expect(page).to_have_url(re.compile(r"#a4-en$"))
    expect(fig.locator("svg title").first).to_contain_text("Annex A4", timeout=10000)
    expect(page.locator("html")).to_have_attribute("lang", "en")
    page.locator("#ax-next").click()
    expect(page).to_have_url(re.compile(r"#a5-en$"))
    # Una caja del simplificado con varios anexos deja elegir.
    page.goto(f"{base}arquitectura.html#simple")
    expect(fig.locator("svg[aria-labelledby^='as-']")).to_have_count(1, timeout=10000)
    fig.locator("[data-node=s-recolectores] text").first.click()
    expect(page.locator("#ax-note .ax-go")).to_have_count(3)
    page.locator("#ax-note .ax-go").nth(1).click()
    expect(page).to_have_url(re.compile(r"#a3$"))
    outside = page.evaluate("""() => {
      const bad = [];
      for (const g of document.querySelectorAll('#ax-fig g[data-node]')) {
        const r = g.querySelector('rect').getBBox();
        for (const t of g.querySelectorAll('text')) {
          const b = t.getBBox();
          if (b.x < r.x - 0.5 || b.y < r.y - 0.5 || b.x + b.width > r.x + r.width + 0.5 || b.y + b.height > r.y + r.height + 0.5)
            bad.push(`${g.dataset.node}: ${t.textContent}`);
        }
      }
      return bad;
    }""")
    assert not outside, outside
    assert not page.errors, page.errors
    # Desde Metodología, la etiqueta de una caja abre su anexo en el explorador.
    go(page, base, "metodologia")
    page.locator("[data-arch=full]").click()
    page.locator('#arch-fig [data-node=fetch] a[data-annex="a4"]').click()
    expect(page).to_have_url(re.compile(r"arquitectura\.html#a4$"))


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


def test_grd_rows_link_to_live_source_and_archived_copy(site, page):
    """Revisión del 22-10-2026: la tabla GRD, la de las decisiones, era la única sin enlace a la fuente en vivo ni a la
    copia archivada. Cada fila con fuente enlaza su origen y, si la publicación tiene copia, la copia que sirve el
    sitio (data/archive/…), como las demás tarjetas. El SOI Troup se calcula con Tahití y Darwin: enlaza los dos."""
    base, root = site
    dash = json.loads((root / "data" / "dashboard.json").read_text(encoding="utf-8"))
    signals = dash["grd"]["signals"]
    inputs = {"soi_troup": ["cpc-tahiti", "cpc-darwin"]}  # GRD_INPUTS en app.js
    go(page, base)
    rows = page.locator("[data-tour-id=grd] table.grd tbody tr")
    expect(rows).to_have_count(len(signals))
    with_source = [(i, x, [dash["sources"][sid] for sid in inputs.get(x["id"], [x["source"]]) if sid in dash["sources"]])
                   for i, x in enumerate(signals) if x.get("source") in dash["sources"]]
    assert with_source, "ninguna fila de la tabla GRD trae su fuente"
    assert any(x["id"] == "soi_troup" and len(ms) == 2 for _, x, ms in with_source), "falta la fila del SOI Troup"
    for i, x, ms in with_source:
        row = rows.nth(i)
        live = row.get_by_role("link", name="Fuente en vivo")
        expect(live).to_have_count(len(ms))
        assert [live.nth(k).get_attribute("href") for k in range(len(ms))] == [m["live"] for m in ms], x["name"]
        assert all(m["live"].startswith("http") for m in ms), x["name"]
        arch = row.locator("a[href^='data/archive/']")
        expected = [f"data/{m['archive']}" for m in ms if m.get("archive")]
        # sin copia en esta publicación (la fuente no respondió y no quedó la anterior): no hay enlace
        expect(arch).to_have_count(len(expected))
        hrefs = [arch.nth(k).get_attribute("href") for k in range(len(expected))]
        assert hrefs == expected and all((root / h).exists() for h in hrefs), hrefs


def test_sources_table_names_the_relay_instead_of_direct(site, page):
    """Revisión del 22-10-2026: una copia del recolector del Perú (hasta 7 días) o de n8n (hasta 72 h) salía como
    «Directa». El estado sigue siendo «ok», pero la tabla dice por dónde llegó el dato. El listado del ENFEN de la
    publicación anterior con su comunicado ya leído (``enfen_latest`` deja «ok») es el último dato válido."""
    base, root = site
    src = json.loads((root / "data" / "sources.json").read_text(encoding="utf-8"))
    rows = src["sources"]
    assert len(rows) >= 6
    relayed = {rows[0]["id"]: ("relay-peru", "recolector en el Perú"), rows[1]["id"]: ("relay-n8n", "n8n"),
               rows[2]["id"]: ("relay-manual", "consola de documentos"), rows[3]["id"]: ("mirror", "otra dirección oficial")}
    for r in rows:
        if r["id"] in relayed:
            r.update(status="ok", channel=relayed[r["id"]][0], archivedAt="2026-10-20T02:10:00+00:00")
    direct = rows[4]
    direct.update(status="ok", channel="direct")
    carried = rows[5]
    carried.update(status="ok", channel="previous-publication", carried=True)
    page.route("**/data/sources.json*", lambda r: r.fulfill(status=200, content_type="application/json",
                                                           body=json.dumps(src)))
    go(page, base, "metodologia")
    table = page.locator("#sources-table")
    expect(table.locator("tbody tr")).to_have_count(len(rows), timeout=10000)
    for sid, (_, via) in relayed.items():
        status = table.locator(f'tr[data-source="{sid}"] td').first
        expect(status).to_contain_text(via)
        expect(status).not_to_contain_text("Directa")
    expect(table.locator(f'tr[data-source="{rows[0]["id"]}"] td').first).to_contain_text("copia del")
    expect(table.locator(f'tr[data-source="{direct["id"]}"] td').first).to_contain_text("Directa")
    kept = table.locator(f'tr[data-source="{carried["id"]}"] td').first
    expect(kept).to_contain_text("Último dato válido")
    expect(kept).not_to_contain_text("Directa")
    expect(kept.locator(".chip")).to_have_class(re.compile(r"\bchip-watch\b"))


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


# Anillo del área elegida: va después de todas las áreas y bordes del SVG (ningún vecino lo tapa), dibuja la
# forma esperada, deja pasar el clic al área de abajo y su brillo late salvo que se pida menos movimiento.
RING_CHECK = """({ svg, shape, d }) => {
  const root = document.querySelector(svg), ring = root.querySelector('.sel-ring');
  if (!ring) return null;
  const line = ring.querySelector('.sel-line'), want = d || root.querySelector(shape).getAttribute('d');
  const below = [...root.querySelectorAll('path:not(.sel-ring *)')];
  const p = line.getPointAtLength(0), m = line.getScreenCTM(), x = m.a * p.x + m.c * p.y + m.e, y = m.b * p.x + m.d * p.y + m.f;
  return {
    above: below.every((e) => e.compareDocumentPosition(ring) & Node.DOCUMENT_POSITION_FOLLOWING),
    shape: line.getAttribute('d') === want,
    clickThrough: !document.elementFromPoint(x, y)?.closest('.sel-ring'),
    glow: getComputedStyle(ring.querySelector('.sel-glow')).animationName,
  };
}"""
RING_OK = {"above": True, "shape": True, "clickThrough": True, "glow": "sel-glow"}


def test_memory_map_ring_marks_the_selected_area_above_every_border(site, browser):
    """Mapa de la memoria: el área elegida lleva un anillo encima de los bordes vecinos y del contorno de los
    departamentos, con su propia forma aunque el mapa muestre un nivel más fino (una provincia entre distritos),
    y se queda quieto si se pide menos movimiento."""
    base, root = site
    geo = json.loads((root / "assets" / "historico" / "mapa.json").read_text(encoding="utf-8"))
    deps = {d["code"]: d["d"] for d in json.loads((root / "assets" / "peru-map.json").read_text(encoding="utf-8"))["departments"]}
    cases = [("1501", "distrito", geo["provinces"]["1501"]["d"]), ("1501", "provincia", geo["provinces"]["1501"]["d"]),
             ("20", "departamento", deps["20"]), ("200101", "distrito", geo["districts"]["200101"]["d"])]
    for motion in ("no-preference", "reduce"):
        ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="es-PE", reduced_motion=motion)
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        try:
            for area, nivel, d in cases:
                pg.goto(f"{base}#/memoria?area={area}&nivel={nivel}")
                expect(pg.locator(".hz-mapbox .sel-ring")).to_have_count(1)
                got = pg.evaluate(RING_CHECK, {"svg": ".hz-mapbox .hz-svg", "d": d})
                assert got == {**RING_OK, "glow": "none" if motion == "reduce" else "sel-glow"}, (area, nivel, got)
            pg.locator(".hz-prof-top [data-area='']").click()
            expect(pg.locator(".hz-mapbox .sel-ring")).to_have_count(0)
            assert not errors, errors
        finally:
            ctx.close()


@pytest.mark.parametrize("variant", ["A", "B", "C", "D"])
def test_alert_map_filters_the_news_and_remembers_the_version(site, browser, variant):
    """Mapa de alertas sobre las noticias: cada versión se dibuja sin errores ni desbordes en un teléfono, un
    departamento filtra los avisos (y queda en la URL), y la versión elegida se recuerda al volver."""
    base, root = site
    feed = json.loads((root / "data" / "feed.json").read_text(encoding="utf-8"))
    alerts = next((g["items"] for g in feed["groups"] if g["id"] == "alertas"), [])
    with_dep = [a for a in alerts if (a.get("geo") or {}).get("places")]
    for w in (320, 1366):
        ctx = browser.new_context(viewport={"width": w, "height": 900}, locale="es-PE")
        ctx.add_init_script(f"if (!sessionStorage.getItem('t')) {{ sessionStorage.setItem('t', 1); localStorage.setItem('enso-mapa-version', JSON.stringify({{v: '{variant}', chosen: false, at: '2000-01-01'}})); }}")
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        try:
            pg.goto(f"{base}#/noticias")
            expect(pg.locator(f".amap.amap-v{variant}")).to_be_visible()
            expect(pg.locator("#amap-ver")).to_have_value(variant)
            assert pg.locator(".amap-svg path.dep").count() == 25
            overflow = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            assert overflow <= 1, f"desbordamiento de {overflow}px a {w}px"
            if with_dep and w == 1366:
                dep = with_dep[0]["geo"]["places"][0]["code"][:2]
                pg.locator(f'path.dep[data-dep="{dep}"]').focus()
                expect(pg.locator(".amap-tip")).to_be_visible()
                pg.keyboard.press("Enter")
                expect(pg).to_have_url(re.compile(rf"dep={dep}"))
                expect(pg.locator(".amap-filtered")).to_contain_text("según el filtro del mapa")
                assert pg.evaluate(RING_CHECK, {"svg": ".amap-svg", "shape": f'path.dep[data-dep="{dep}"]'}) == RING_OK
                n = pg.locator("#fg-alertas-list .feed-item").count()
                assert 1 <= n <= len(alerts)
                pg.locator(".amap-filtered [data-clear-map]").click()
                expect(pg.locator(".amap-filtered")).to_have_count(0)
                expect(pg.locator(".amap-svg .sel-ring")).to_have_count(0)
                pg.select_option("#amap-ver", "C" if variant != "C" else "A")
                pg.reload()
                expect(pg.locator("#amap-ver")).to_have_value("C" if variant != "C" else "A")
            assert not errors, errors
        finally:
            ctx.close()


def test_maps_draw_what_is_known_finer_than_the_area(site, browser):
    """Los dos mapas dibujan lo que se sabe más fino que el departamento o el distrito: en el de alertas, las zonas,
    los distritos con quebradas y los puntos de los avisos (con su cuadro); en el de la memoria, los registros con
    punto propio o de centro poblado. La capa de cuencas de la ANA se prende y se apaga, y nada tapa el anillo."""
    base, root = site
    feed = json.loads((root / "data" / "feed.json").read_text(encoding="utf-8"))
    alerts = next((g["items"] for g in feed["groups"] if g["id"] == "alertas"), [])
    if not any(a.get("detail") for a in alerts):
        pytest.skip("la publicación no trae avisos con detalle")
    # El reloj, poco después del último aviso: así los avisos de la publicación siguen vigentes o recientes.
    last = max(datetime.fromisoformat(a["date"].replace("Z", "+00:00")) for a in alerts if a.get("date"))
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="es-PE")
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    try:
        pg.clock.install(time=last + timedelta(minutes=90))
        pg.goto(f"{base}#/noticias")
        expect(pg.locator(".amap-svg .amap-detail")).to_have_count(1)
        assert pg.locator(".amap-svg .amap-pt").count() > 0
        pt = pg.locator(".amap-svg .amap-pt").first
        pt.hover(force=True)
        expect(pg.locator(".amap-tip")).to_be_visible()
        expect(pg.locator(".amap-tip strong").first).to_have_text(re.compile(r"\S"))
        pg.locator('.amap [data-layer="cuencas"]').click()
        expect(pg.locator(".amap-svg .amap-basins path")).to_have_count(231)
        pg.locator('.amap [data-layer="detalle"]').click()
        expect(pg.locator(".amap-svg .amap-detail")).to_have_count(0)
        dep = next(a["geo"]["places"][0]["code"][:2] for a in alerts if (a.get("geo") or {}).get("places"))
        pg.locator(f'path.dep[data-dep="{dep}"]').focus()
        pg.keyboard.press("Enter")
        assert pg.evaluate(RING_CHECK, {"svg": ".amap-svg", "shape": f'path.dep[data-dep="{dep}"]'}) == RING_OK

        pg.goto(f"{base}#/memoria?nivel=distrito&area=20&cuencas=1")
        expect(pg.locator(".hz-mapbox .hz-basins path")).to_have_count(231)
        expect(pg.locator(".hz-mapbox .hz-pts circle").first).to_be_attached()
        expect(pg.locator("#hz-pts-note")).to_contain_text("registros de esta área tienen un punto más fino que su distrito")
        layers = pg.evaluate("[...document.querySelector('.hz-mapbox .hz-svg').children].map((e) => e.getAttribute('class'))")
        assert layers[-3:] == ["hz-basins", "hz-pts", "sel-ring"], layers
        deps = {d["code"]: d["d"] for d in json.loads((root / "assets" / "peru-map.json").read_text(encoding="utf-8"))["departments"]}
        assert pg.evaluate(RING_CHECK, {"svg": ".hz-mapbox .hz-svg", "d": deps["20"]}) == RING_OK
        assert pg.locator(".hz-ev-fine").count() > 0
        pg.locator('.hz-layers [data-layer="cuencas"]').click()
        expect(pg.locator(".hz-mapbox .hz-basins")).to_have_count(0)
        expect(pg).not_to_have_url(re.compile(r"cuencas=1"))
        assert not errors, errors
    finally:
        ctx.close()


def test_variant_results_view_without_backend(page, site):
    """#/variantes en un sitio sin Functions (GitHub Pages, servidor local) dice que no hay datos, sin romperse."""
    base, _ = site
    page.goto(f"{base}#/variantes")
    expect(page.locator("#ab-stats")).to_contain_text("No se pudo leer la analítica")
