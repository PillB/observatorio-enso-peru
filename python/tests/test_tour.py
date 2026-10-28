"""Tutorial guiado (public/assets/js/tour.js): cada recorrido llega a su sección, la resalta, usa los mapas y los
gráficos delante de la persona, y su ventana nunca tapa lo que resalta ni lo que toca.

Un vigilante corre en la página en cada cuadro mientras dura el recorrido y anota cualquier cuadro en que la ventana
del paso se cruce con el resaltado (lo que se ve de él bajo la cabecera fija), con el punto que el puntero del
tutorial está tocando o con el tooltip que abrió un mapa, o en que la ventana se salga de la pantalla. Se prueba en
teléfonos, tableta y escritorio, en tema claro y oscuro, al cambiar el tamaño de la ventana y en los tres motores.
"""

from __future__ import annotations

import pytest

from tests.test_browser import browser, engine, go, site  # noqa: F401  (fixtures compartidas)

pytestmark = pytest.mark.browser

pw = pytest.importorskip("playwright.sync_api")
expect = pw.expect

TOURS = ["inicio", "completo", "resumen", "costero", "pacifico", "oceano", "mapa", "historia", "memoria", "noticias",
         "datos", "metodologia", "asistente"]
TAB_OF = {"resumen": "", "costero": "costero", "pacifico": "pacifico", "oceano": "oceano", "mapa": "mapa",
          "historia": "historia", "memoria": "memoria", "noticias": "noticias", "datos": "datos",
          "metodologia": "metodologia", "asistente": "asistente"}

# Los mapas abren en el resumen (como en test_browser.py) y el vigilante de cada cuadro.
WATCH = """
for (const k of ['enso-vista-memoria', 'enso-vista-noticias'])
  if (!localStorage.getItem(k)) localStorage.setItem(k, JSON.stringify({v: 'resumen', chosen: false, at: '2000-01-01'}));
window.__viol = [];
window.__frames = 0;
(() => {
  const ix = (a, b) => a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5;
  const chk = () => {
    const pop = document.querySelector('.tour-pop');
    if (pop && !pop.classList.contains('tour-moving')) {
      window.__frames++;
      const P = pop.getBoundingClientRect();
      const head = document.querySelector('.site-header');
      const hb = head ? head.getBoundingClientRect().bottom : 0;
      // Lo que se ve de un rectángulo: la cabecera fija tapa lo que pasa por debajo (salvo lo que está en ella).
      const vis = (r) => { if (r.bottom <= hb + 1) return r; const t = Math.max(r.top, hb); return {left: r.left, right: r.right, top: t, bottom: Math.max(t, r.bottom)}; };
      const bad = [];
      const ring = document.querySelector('.tour-ring');
      if (ring && !ring.hidden) {
        const R = vis(ring.getBoundingClientRect());
        // El borde del resaltado (3 px más su halo) también cuenta.
        const R2 = {left: R.left - 3, right: R.right + 3, top: R.top - 3, bottom: R.bottom + 3};
        if (R2.bottom > R2.top && ix(P, R2)) bad.push('resaltado');
      }
      const ptr = document.querySelector('.tour-ptr');
      if (ptr && !ptr.hidden && ptr.classList.contains('tap')) {
        const m = new DOMMatrix(getComputedStyle(ptr).transform);
        if (ix(P, {left: m.e - 6, right: m.e + 6, top: m.f - 6, bottom: m.f + 6})) bad.push('toque');
      }
      for (const t of document.querySelectorAll('.hz-tip:not([hidden]), .amap-tip:not([hidden])'))
        if (ix(P, t.getBoundingClientRect())) bad.push('tooltip');
      const vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;
      if (P.left < -0.5 || P.top < -0.5 || P.right > vw + 0.5 || P.bottom > vh + 0.5) bad.push('fuera de la pantalla');
      if (bad.length) {
        window.__viol.push(`${document.querySelector('.tour-count')?.textContent}: ${bad.join(', ')}`);
        // Detalle para depurar: la ventana, el resaltado y el desplazamiento en ese cuadro.
        const R = ring && !ring.hidden ? ring.getBoundingClientRect() : null;
        const f = (r) => r ? [r.left, r.top, r.width, r.height].map(Math.round).join(',') : '-';
        window.__violDetail = window.__violDetail || [];
        window.__violDetail.push(`pop=${f(P)} ${pop.dataset.side} ring=${f(R)} y=${Math.round(scrollY)} head=${Math.round(hb)}`);
      }
    }
    requestAnimationFrame(chk);
  };
  requestAnimationFrame(chk);
})();
"""


def _ctx(browser, w, h, *, dark=False, motion="reduce", **kw):
    ctx = browser.new_context(viewport={"width": w, "height": h}, locale="es-PE", reduced_motion=motion,
                              color_scheme="dark" if dark else "light", **kw)
    ctx.add_init_script(WATCH)
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" else None)
    return ctx, pg


def _ready(pg, timeout=30000):
    # (wait_for_function evalúa texto: la CSP del sitio no lo permite)
    expect(pg.locator(".tour-pop")).to_have_attribute("data-state", "ready", timeout=timeout)


def _start(pg, base, tour, route=""):
    go(pg, base, route)
    pg.locator("#help-btn").click()
    dlg = pg.locator("#tour-dialog")
    dlg.locator(f".tour-menu [data-mode='{tour}']").click()


def _walk(pg, label):
    """Recorre todos los pasos con «Siguiente». Devuelve los títulos vistos."""
    seen = []
    for _ in range(40):
        _ready(pg)
        pop = pg.locator(".tour-pop")
        count = pop.locator(".tour-count").inner_text()
        assert pop.get_by_text("no está disponible en esta publicación").count() == 0, f"{label} {count}: no encontró su sección"
        ring = pg.locator(".tour-ring")
        assert ring.is_visible(), f"{label} {count}: sin resaltado"
        seen.append(pop.locator("#tour-title").inner_text())
        nxt = pop.locator("[data-act='next']")
        last = nxt.inner_text().strip() == "Terminar"
        # En una pantalla muy baja (KaiOS) la ventana puede quedar como píldora: su botón «›» avanza.
        pill = pop.locator("[data-act='pill-next']")
        (pill if pill.is_visible() else nxt).click()
        if last:
            break
    expect(pg.locator(".tour-pop")).to_have_count(0)
    return seen


# --- Geometría pura (tour-geo.js) ------------------------------------------------------------------------

def test_placement_never_overlaps_what_it_must_avoid(site, browser):
    """5000 casos al azar: la posición elegida está en pantalla, bajo la cabecera, y no toca ningún rectángulo a
    evitar; si no hay lugar, la respuesta es la píldora. El plan de desplazamiento deja ver el elemento con la
    ventana al lado (o, si es más alto que la pantalla, su comienzo bajo la ventana)."""
    base, _ = site
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.goto(f"{base}404.html")
    bad = pg.evaluate("""async () => {
      const g = await import('./assets/js/tour-geo.js');
      let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
      const out = [];
      for (let i = 0; i < 5000; i++) {
        const vp = {width: 240 + rnd() * 1700, height: 300 + rnd() * 900}; vp.top = rnd() * 130;
        const size = {width: Math.min(380, vp.width - 16), height: 120 + rnd() * 260};
        const T = g.rect(vp.top - 200 + rnd() * (vp.height + 200), rnd() * vp.width * 0.8, 20 + rnd() * vp.width * 0.8, 10 + rnd() * 1500);
        const extra = rnd() < 0.5 ? [g.rect(rnd() * vp.height, rnd() * vp.width, 10 + rnd() * 200, 10 + rnd() * 100)] : [];
        const p = g.placePopover(vp, size, T, [T, ...extra], null);
        if (p.side === 'pill') continue;
        const box = g.rect(p.top, p.left, size.width, size.height);
        if (box.left < 7.5 || box.right > vp.width - 7.5 || box.top < vp.top + 7.5 || box.bottom > vp.height - 7.5) out.push(['fuera', i, vp, size, p]);
        for (const r of [T, ...extra]) { const c = g.clipY(r, vp.top, vp.height); if (c && g.intersects(box, c)) out.push(['cruce', i, vp, size, p, r]); }
        // El plan: con el desplazamiento propuesto, el elemento (o su comienzo) y la ventana caben sin cruzarse.
        const plan = g.planScroll(vp, size, T, 0);
        const T2 = g.rect(T.top - plan.y, T.left, T.width, T.height);
        const s2 = {width: size.width, height: plan.maxHeight || size.height};
        const q = g.placePopover(vp, s2, T2, [T2], plan.side);
        if (q.side === 'pill' && vp.height - vp.top > s2.height + 160 && vp.width >= s2.width + 16) out.push(['sin lugar tras desplazar', i, vp, s2, plan, T]);
      }
      return out.slice(0, 5);
    }""")
    ctx.close()
    assert not bad, bad


# --- Cada recorrido, en cada pantalla --------------------------------------------------------------------

SCREENS = {"telefono-320": (320, 640, False), "telefono-390-oscuro": (390, 844, True), "tableta": (820, 1180, False),
           "escritorio-oscuro": (1366, 900, True)}


@pytest.mark.parametrize("tour", TOURS)
@pytest.mark.parametrize("screen", SCREENS, ids=list(SCREENS))
def test_every_tour_reaches_its_sections_without_covering_them(site, browser, tour, screen):
    base, _ = site
    w, h, dark = SCREENS[screen]
    ctx, pg = _ctx(browser, w, h, dark=dark)
    try:
        _start(pg, base, tour)
        seen = _walk(pg, f"{tour}@{screen}")
        assert len(seen) >= 2
        viol = pg.evaluate("window.__viol")
        assert pg.evaluate("window.__frames") > 20
        assert not viol, sorted(set(viol))[:10]
        assert not pg.errors, pg.errors
    finally:
        ctx.close()


def test_animated_demo_on_a_phone_moves_the_pointer_without_covering_it(site, browser):
    """Con animaciones (sin «reducir movimiento»): el puntero viaja hasta cada control y lo toca a la vista."""
    base, _ = site
    ctx, pg = _ctx(browser, 390, 844, motion="no-preference", has_touch=True)
    try:
        _start(pg, base, "memoria")
        taps = []
        pg.expose_function("__tap", lambda t: taps.append(t))
        pg.evaluate("new MutationObserver(() => { const p = document.querySelector('.tour-ptr'); if (p?.classList.contains('tap')) window.__tap(p.style.transform); })"
                    ".observe(document.body, {subtree: true, attributes: true, attributeFilter: ['class']})")
        _walk(pg, "memoria animada")
        assert len(taps) >= 8, taps
        assert not pg.evaluate("window.__viol")
        assert not pg.errors, pg.errors
    finally:
        ctx.close()


def test_tour_leaves_the_map_versions_and_their_analytics_alone(site, browser):
    """Lo que el tutorial pulsa en los mapas (la vista de detalle, un departamento) no cambia la vista que la
    persona tiene asignada ni cuenta en la analítica de las versiones."""
    base, _ = site
    ctx, pg = _ctx(browser, 1366, 900)
    sent = []
    pg.on("request", lambda r: sent.append(r.url) if "/api/ab/e" in r.url else None)
    try:
        go(pg, base, "memoria")
        before = pg.evaluate("[localStorage.getItem('enso-vista-memoria'), localStorage.getItem('enso-vista-noticias')]")
        for tour in ("memoria", "noticias"):
            pg.locator("#help-btn").click()
            pg.locator(f"#tour-dialog .tour-menu [data-mode='{tour}']").click()
            _walk(pg, tour)
        after = pg.evaluate("[localStorage.getItem('enso-vista-memoria'), localStorage.getItem('enso-vista-noticias')]")
        assert after == before
        assert not sent
    finally:
        ctx.close()


def test_tour_keys_pause_and_resume(site, browser):
    """Esc pausa; las flechas sobre un gráfico son del gráfico, no del tutorial; irse a otra pestaña pausa; al
    reanudar vuelve al mismo paso (también tras recargar)."""
    base, _ = site
    ctx, pg = _ctx(browser, 1280, 900)
    try:
        _start(pg, base, "costero")
        _ready(pg)
        pop = pg.locator(".tour-pop")
        while "ICEN" != pop.locator("#tour-title").inner_text():
            pop.locator("[data-act='next']").click()
            _ready(pg)
        count = pop.locator(".tour-count").inner_text()
        pg.locator("#ch-icen svg.chart").focus()
        pg.keyboard.press("ArrowLeft")
        pg.wait_for_timeout(300)
        assert pop.locator(".tour-count").inner_text() == count
        assert pg.locator("#ch-icen .tooltip").is_visible()
        # Con el foco en la ventana, las flechas avanzan y retroceden.
        pop.locator("[data-act='next']").focus()
        pg.keyboard.press("ArrowRight")
        _ready(pg)
        assert pop.locator(".tour-count").inner_text() != count
        pg.keyboard.press("ArrowLeft")
        _ready(pg)
        assert pop.locator(".tour-count").inner_text() == count
        pg.keyboard.press("Escape")
        expect(pop).to_have_count(0)
        pg.reload()
        go(pg, base, "costero")
        pg.locator("#help-btn").click()
        pg.locator("#tour-dialog").get_by_role("button", name="Reanudar").click()
        _ready(pg)
        assert pg.locator(".tour-count").inner_text() == count
        # La persona se va a otra pestaña por su cuenta: queda en pausa.
        pg.locator(".nav a[data-route='pacifico']").click()
        expect(pg.locator(".tour-pop")).to_have_count(0)
        pg.locator("#help-btn").click()
        expect(pg.locator("#tour-dialog").get_by_role("button", name="Reanudar")).to_be_visible()
        assert not pg.errors, pg.errors
    finally:
        ctx.close()


def test_tour_follows_resizes_rotation_and_theme_changes(site, browser):
    """A mitad de un paso con mapa: escritorio → teléfono → teléfono acostado → tableta, y cambio de tema. La
    ventana se recoloca sin tapar el mapa en ningún cuadro."""
    base, _ = site
    ctx, pg = _ctx(browser, 1366, 900)
    try:
        _start(pg, base, "memoria")
        pop = pg.locator(".tour-pop")
        _ready(pg)
        while pop.locator("#tour-title").inner_text() != "El mapa":
            pop.locator("[data-act='next']").click()
            _ready(pg)
        for w, h in ((390, 844), (844, 390), (820, 1180), (320, 640), (1366, 900)):
            pg.set_viewport_size({"width": w, "height": h})
            pg.wait_for_timeout(900)
            assert pg.locator(".tour-ring").is_visible()
        pg.locator("#theme-btn").click()
        pg.wait_for_timeout(300)
        assert pg.evaluate("document.documentElement.dataset.theme") == "dark"
        assert pg.locator(".tour-ring").is_visible()
        viol = pg.evaluate("window.__viol")
        assert not viol, sorted(set(viol))[:10]
        assert not pg.errors, pg.errors
    finally:
        ctx.close()


def test_each_tab_has_a_button_for_its_own_tour(site, browser):
    base, _ = site
    ctx, pg = _ctx(browser, 1280, 900)
    try:
        for tour, route in TAB_OF.items():
            go(pg, base, route)
            btn = pg.locator(".page-head .tab-tour")
            expect(btn).to_have_count(1)
            btn.click()
            _ready(pg)
            assert pg.locator(".tour-count").inner_text().endswith(" · paso 1 de " + pg.locator(".tour-count").inner_text().split(" de ")[-1])
            title = pg.evaluate(f"import('./assets/js/tour-pasos.js').then(m => m.TOURS.find(t => t.id === '{tour}').title)")
            assert pg.locator(".tour-count").inner_text().startswith(title)
            pg.keyboard.press("Escape")
        assert not pg.errors, pg.errors
    finally:
        ctx.close()


def test_menu_offers_this_tab_first_and_every_tab(site, browser):
    base, _ = site
    ctx, pg = _ctx(browser, 1280, 900)
    try:
        go(pg, base, "memoria")
        pg.locator("#help-btn").click()
        dlg = pg.get_by_role("dialog", name="Ayuda y tutorial")
        expect(dlg.locator(".tour-here")).to_contain_text("Memoria de desastres")
        expect(dlg.locator(".tour-menu li")).to_have_count(len(TOURS))
    finally:
        ctx.close()


# --- Dispositivos de referencia, cada uno con su motor --------------------------------------------------

def test_tours_fit_every_reference_device(site, engine):
    """En cada dispositivo de referencia de su motor (KaiOS de 240×320, la pantalla externa de un Z Flip, iPhone,
    iPad, laptops): el recorrido del mapa y el de la memoria sin cruces ni errores."""
    from tools.devices import DEVICES, context_options

    base, _ = site
    p, b = engine
    name = b.browser_type.name
    checked = 0
    for dev_id, label, eng, desc, extra in DEVICES:
        if eng != name:
            continue
        ctx = b.new_context(**{"locale": "es-PE", **context_options(p, name, desc, extra), "reduced_motion": "reduce"})
        ctx.add_init_script(WATCH)
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        try:
            for tour in ("mapa", "memoria"):
                _start(pg, base, tour)
                _walk(pg, f"{tour}@{dev_id}")
            viol = pg.evaluate("window.__viol")
            assert not viol, f"{label}: {sorted(set(viol))[:8]}"
            assert not errors, f"{label}: {errors}"
        finally:
            ctx.close()
        checked += 1
    if not checked:
        pytest.skip(f"ningún dispositivo de referencia usa {name}")
