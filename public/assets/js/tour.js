// Tutorial guiado: un recorrido por cada pestaña, uno de inicio rápido y uno completo (tour-pasos.js).
//
// Cada paso lleva a su pestaña, deja la vista en el estado que necesita (vista del mapa, filtros, una ficha
// abierta), desplaza la página hasta lo que explica, lo resalta y, si el paso lo pide, lo usa delante de la persona:
// pulsa un botón, elige una opción, pasa el puntero por el mapa o escribe una pregunta, con un puntero animado.
//
// La ventana del paso nunca tapa lo resaltado ni lo que el tutorial toca (tour-geo.js): se recoloca en cada cuadro
// mientras el tutorial está abierto (la página se redibuja, cambia de tamaño, la persona desplaza o lleva el foco a
// otro control) y, si no cabe en ningún lado, se reduce a una píldora sobre la cabecera fija.
//
// No es modal: la página sigue usable durante el tutorial (Esc lo pausa, las flechas avanzan con el foco en la
// ventana). El progreso se guarda en este navegador: se puede pausar, reanudar (también tras recargar), reiniciar y
// borrar. Lo que el tutorial pulsa no cuenta en la analítica de las versiones de los mapas (ab.js).

import { esc, $, storage } from './lib/dom.js';
import { TOURS, tourForTab } from './tour-pasos.js';
import { ICON } from './icons.js';
import { EDGE, GAP, pad, rect, union, intersects, placePopover, planScroll } from './tour-geo.js';

const KEY = 'enso-tour';
const VERSION = 3;
const RING = 6;  // margen del resaltado alrededor del elemento
const HALO = 6;  // el borde del resaltado (3 px) y su halo (otros 3 px), por fuera del anillo
const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const sleep = (ms) => new Promise((res) => setTimeout(res, ms));
const frame = () => new Promise((res) => requestAnimationFrame(() => res()));
export const routeName = (h) => (h || '').replace(/^#\/?/, '').split('?')[0];

function readState() {
  try {
    const s = JSON.parse(storage(KEY) || 'null');
    return s && s.version === VERSION ? s : { version: VERSION, completed: [], active: null };
  } catch {
    return { version: VERSION, completed: [], active: null };
  }
}

/** El primer elemento visible que coincide con alguno de los selectores. */
function find(sel) {
  if (!sel) return null;
  if (typeof sel === 'function') return sel() || null;
  for (const s of Array.isArray(sel) ? sel : [sel]) {
    for (const el of document.querySelectorAll(s)) {
      if (el.closest('.tour-ui')) continue;
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) return el;
    }
  }
  return null;
}

const toRect = (r) => rect(r.top, r.left, r.width, r.height);

/** Pantalla útil: sin la barra de desplazamiento y bajo la cabecera fija. */
function viewport() {
  const de = document.documentElement;
  const head = document.querySelector('.site-header');
  const hb = head ? head.getBoundingClientRect().bottom : 0;
  return { width: de.clientWidth, height: de.clientHeight, top: Math.max(0, hb) };
}

export class Tour {
  constructor({ getData, navigate }) {
    this.getData = getData;
    this.navigate = navigate;
    this.state = readState();
    this.ui = null;
    this.gen = 0;
    this.navigating = false;
    this.side = null;
    this.onKey = (e) => {
      if (!this.ui) return;
      const inPop = this.ui.pop.contains(e.target);
      if (e.key === 'Escape' && !e.defaultPrevented) { e.preventDefault(); this.pause(); return; }
      // Las flechas son de la página (gráficos, mapas, deslizadores) salvo con el foco en la ventana o en ninguna parte.
      if (!inPop && e.target !== document.body) return;
      if (e.key === 'ArrowRight') { e.preventDefault(); this.next(); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); this.prev(); }
    };
    // La persona se fue a otra pestaña por su cuenta: el tutorial queda en pausa (se reanuda desde «Ayuda»).
    this.onHash = () => {
      if (!this.ui || this.navigating) return;
      const st = this.step();
      if (st?.route && routeName(location.hash) !== routeName(st.route)) this.pause();
    };
    this.onResize = () => {
      // En el mismo cuadro del cambio de tamaño (antes de pintarse) la ventana ya va a una posición válida.
      if (this.ui) this.layout(true);
      clearTimeout(this.resizeT); this.resizeT = setTimeout(() => this.replan(), 200); };
    document.addEventListener('view:ready', () => this.decorate());
  }

  save() { storage(KEY, JSON.stringify(this.state)); }
  mode() { return TOURS.find((m) => m.id === this.state.active?.mode); }
  step() { const m = this.mode(); return m?.steps[this.state.active.step]; }

  // -------------------------------------------------------------------------
  // Menú y botón de cada pestaña
  // -------------------------------------------------------------------------

  /** Botón «Cómo se usa esta pestaña» en la cabecera de cada vista con recorrido. */
  decorate() {
    const head = document.querySelector('#main .page-head');
    const t = tourForTab(routeName(location.hash));
    if (!head || !t || head.querySelector('.tab-tour')) return;
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn ghost tab-tour';
    b.innerHTML = `${ICON.play || ''}<span>Cómo se usa esta pestaña</span>`;
    b.setAttribute('aria-label', `Recorrido guiado: ${t.title} (${t.steps.length} pasos)`);
    b.addEventListener('click', () => this.start(t.id));
    head.append(b);
  }

  /** Diálogo con los recorridos y los controles de progreso. */
  openMenu() {
    const dlg = document.getElementById('tour-dialog');
    const a = this.state.active;
    const paused = a && a.status === 'paused' ? TOURS.find((m) => m.id === a.mode) : null;
    const here = tourForTab(routeName(location.hash));
    const item = (m) => `<li><button type="button" data-mode="${esc(m.id)}"${m === here ? ' class="here"' : ''}><strong>${esc(m.title)}</strong><br><span class="muted small">${esc(m.desc)} · ${m.steps.length} pasos</span>${this.state.completed.includes(m.id) ? ' <span class="done">✓ completado</span>' : ''}</button></li>`;
    const general = TOURS.filter((m) => !m.tab), tabs = TOURS.filter((m) => m.tab);
    dlg.querySelector('.dlg-body').innerHTML = `
      ${paused ? `<div class="notice notice-info"><p>Tiene en pausa «${esc(paused.title)}» (paso ${a.step + 1} de ${paused.steps.length}).</p><button type="button" class="btn" data-act="resume">Reanudar</button></div>` : ''}
      <p class="muted">Cada recorrido lleva a su sección, la resalta y le muestra cómo usar los mapas y los gráficos. Puede seguir usando la página mientras tanto. Esc lo pausa; el progreso se guarda en este navegador.</p>
      ${here ? `<h3 class="tour-menu-h">En esta pestaña</h3><div class="tour-here"><button type="button" class="btn" data-mode="${esc(here.id)}">${ICON.play || ''}<span>Recorrer «${esc(here.title)}»</span></button></div>` : ''}
      <h3 class="tour-menu-h">Recorridos generales</h3>
      <ul class="tour-menu">${general.map(item).join('')}</ul>
      <h3 class="tour-menu-h">Una pestaña a la vez</h3>
      <ul class="tour-menu">${tabs.map(item).join('')}</ul>
      <div class="row tour-reset"><button type="button" class="btn ghost" data-act="clear">Borrar progreso del tutorial</button></div>`;
    dlg.querySelectorAll('[data-mode]').forEach((b) => b.addEventListener('click', () => { dlg.close(); this.start(b.dataset.mode); }));
    dlg.querySelector('[data-act="resume"]')?.addEventListener('click', () => { dlg.close(); this.resume(); });
    dlg.querySelector('[data-act="clear"]').addEventListener('click', () => {
      this.state = { version: VERSION, completed: [], active: null };
      this.save();
      this.announce('Se borró el progreso del tutorial.');
      this.openMenu();
    });
    if (!dlg.open) dlg.showModal();
  }

  // -------------------------------------------------------------------------
  // Ciclo de vida
  // -------------------------------------------------------------------------

  start(modeId, step = 0) {
    if (!TOURS.some((m) => m.id === modeId)) return;
    this.state.active = { mode: modeId, step, status: 'running', startedAt: new Date().toISOString() };
    this.save();
    this.show();
  }

  resume() {
    if (!this.state.active || !this.mode()) return;
    this.state.active.status = 'running';
    this.save();
    this.show();
  }

  /** Tras recargar, un recorrido que estaba en curso queda en pausa (se ofrece reanudarlo en el menú). */
  maybeResume() {
    const a = this.state.active;
    if (a && a.status === 'running') { a.status = 'paused'; this.save(); }
  }

  next() {
    const m = this.mode();
    if (!m) return;
    if (this.state.active.step >= m.steps.length - 1) { this.finish(); return; }
    this.lastDir = 'next';
    this.state.active.step += 1;
    this.save();
    this.show();
  }

  prev() {
    if (!this.state.active || this.state.active.step === 0) return;
    this.lastDir = 'prev';
    this.state.active.step -= 1;
    this.save();
    this.show();
  }

  finish() {
    const m = this.mode();
    if (!this.state.completed.includes(m.id)) this.state.completed.push(m.id);
    this.state.active = null;
    this.save();
    this.close();
    this.announce(`Completó «${m.title}».`);
  }

  pause() {
    if (!this.state.active) return;
    this.state.active.status = 'paused';
    this.save();
    this.close();
    this.announce('Tutorial en pausa. Puede reanudarlo desde «Ayuda y tutorial».');
  }

  exit() {
    this.state.active = null;
    this.save();
    this.close();
    this.announce('Salió del tutorial.');
  }

  close() {
    this.gen++;
    if (!this.ui) return;
    cancelAnimationFrame(this.raf);
    this.unhover();
    this.ui.root.remove();
    this.ui = null;
    this.setSpacers(0, 0);
    document.documentElement.classList.remove('tour-on');
    document.removeEventListener('keydown', this.onKey);
    window.removeEventListener('hashchange', this.onHash);
    window.removeEventListener('resize', this.onResize);
    $('#help-btn')?.focus({ preventScroll: true });
  }

  announce(msg) {
    const live = document.getElementById('live');
    if (live) { live.textContent = ''; setTimeout(() => { live.textContent = msg; }, 50); }
  }

  // -------------------------------------------------------------------------
  // Un paso
  // -------------------------------------------------------------------------

  mount() {
    if (this.ui) return;
    const root = document.createElement('div');
    root.className = 'tour-ui';
    root.innerHTML = `<div class="tour-ring" hidden></div><div class="tour-ptr" hidden aria-hidden="true">${ICON.pointer}</div>
      <div class="tour-pop" role="dialog" aria-modal="false" aria-labelledby="tour-title" aria-describedby="tour-text"></div>`;
    document.body.append(root);
    this.ui = { root, pop: root.querySelector('.tour-pop'), ring: root.querySelector('.tour-ring'), ptr: root.querySelector('.tour-ptr') };
    this.ui.pop.tour = this;  // para las pruebas de navegador (test_browser.py)
    document.documentElement.classList.add('tour-on');
    document.addEventListener('keydown', this.onKey);
    window.addEventListener('hashchange', this.onHash);
    window.addEventListener('resize', this.onResize);
    this.ui.pop.addEventListener('click', (e) => {
      const act = e.target.closest('[data-act]')?.dataset.act;
      if (act === 'close') this.pause();
      else if (act === 'prev') this.prev();
      else if (act === 'next' || act === 'pill-next') this.next();
      else if (act === 'replay') this.show({ replay: true });
      else if (act === 'expand') { this.ui.pop.classList.remove('tour-pill'); this.replan(); }
      else if (act === 'then') { const n = this.mode()?.next; this.finish(); if (n) this.start(n); }
    });
    const loop = () => { this.layout(); this.raf = requestAnimationFrame(loop); };
    this.raf = requestAnimationFrame(loop);
  }

  async show({ replay = false } = {}) {
    const m = this.mode();
    if (!m) return;
    const my = ++this.gen;
    const live = () => my === this.gen && this.ui;
    this.mount();
    const i = this.state.active.step;
    const st = m.steps[i];
    this.target = null;
    this.targetSel = null;
    this.actSel = [];
    this.primary = 'target';
    this.side = null;
    this.render(m, st, i, { busy: true });
    // Mientras carga la pestaña no hay nada resaltado: la ventana espera abajo, con su texto.
    this.settling = false;
    this.ui.pop.dataset.state = 'busy';
    this.ui.ptr.hidden = true;
    delete this.ui.ptr.dataset.placed;
    this.unhover();

    // 1. La pestaña.
    if (st.route && routeName(location.hash) !== routeName(st.route)) {
      this.navigating = true;
      await new Promise((res) => {
        const done = () => { document.removeEventListener('view:ready', done); clearTimeout(t); res(); };
        const t = setTimeout(done, 10000);
        document.addEventListener('view:ready', done);
        this.navigate(st.route);
      });
      this.navigating = false;
      if (!live()) return;
    }
    // 2. El estado que necesita el paso (en silencio).
    for (const e of st.ensure || []) {
      await this.waitFor(e.ready || null, 4000);
      if (!live()) return;
      if (e.when()) {
        await this.act(e.act, { visible: false });
        await this.settle(e.ready);
        if (!live()) return;
      }
    }
    // 3. El elemento: la vista puede terminar de pintarse después de «view:ready» (datos que llegan tarde).
    let el = await this.waitFor(st.target, 6000);
    if (!live()) return;
    if (!el && st.optional) {
      // Un dato que esta publicación no trae (p. ej. la perspectiva del ENFEN): se salta el paso.
      const dir = this.lastDir === 'prev' ? -1 : 1;
      const j = i + dir;
      if (j >= 0 && j < m.steps.length) { this.state.active.step = j; this.save(); this.show(); } else if (dir > 0) this.finish();
      return;
    }
    this.target = el;
    this.targetSel = st.target;
    if (!el) this.render(m, st, i, { missing: true });
    // Un gráfico o un mapa que todavía se está dibujando cambia de alto: se espera a que la página se quede quieta.
    if (el) await this.settle(null, 2500);
    if (!live()) return;
    await this.replan();
    if (!live()) return;
    this.announce(`Paso ${i + 1} de ${m.steps.length}: ${st.title}`);
    this.ui.pop.querySelector('[data-act="next"]')?.focus({ preventScroll: true });

    // 4. La demostración, delante de la persona.
    if (st.demo && el) {
      await sleep(replay || reduced() ? 150 : 500);
      for (const a of st.demo) {
        if (!live()) return;
        const who = await this.waitFor(a.click || a.select || a.type || a.hover || a.open || a.target, 4000);
        if (!who) continue;
        this.actSel = [() => (who.isConnected ? who : find(a.click || a.select || a.type || a.hover || a.open))];
        if (a.say) this.say(a.say);
        // El control que se va a tocar también debe verse y quedar libre.
        this.primary = 'act';
        await this.replan({ keep: true });
        if (!live()) return;
        await this.act(a, { visible: true, el: who });
        if (!live()) return;
        await this.settle(a.ready);
        if (!live()) return;
        this.primary = 'target';
        if (a.target) { this.target = await this.waitFor(a.target, 4000) || this.target; this.targetSel = a.target; }
        this.actSel = a.keep ? [a.keep] : [];
        await this.replan({ keep: true });
        if (a.pause) await sleep(reduced() ? 200 : a.pause);
      }
      if (!live()) return;
      if (st.after) { this.target = await this.waitFor(st.after, 4000) || this.target; this.targetSel = st.after; }
      this.say('Listo. Pruébelo usted también.');
      await this.replan({ keep: true });
      if (!live()) return;
    }
    this.ui.pop.dataset.state = 'ready';
  }

  /** El texto de la ventana. */
  render(m, st, i, { missing = false, busy = false } = {}) {
    const last = i === m.steps.length - 1;
    const text = typeof st.text === 'function' ? st.text(this.getData()) : st.text;
    const nextMode = last && m.next ? TOURS.find((x) => x.id === m.next) : null;
    this.ui.pop.classList.remove('tour-pill');
    this.ui.pop.innerHTML = `
      <div class="tour-head"><span class="tour-count">${esc(m.title)} · paso ${i + 1} de ${m.steps.length}</span>
        <button type="button" class="icon-btn" data-act="close" aria-label="Cerrar el tutorial (puede reanudarlo después)">${ICON.close}</button></div>
      <h2 id="tour-title">${esc(st.title)}</h2>
      <div class="tour-body"><p id="tour-text">${esc(text)}</p>
        ${missing ? '<p class="muted small">Esta sección no está disponible en esta publicación.</p>' : ''}
        <p class="tour-doing small" aria-live="polite">${busy && st.demo ? 'Mire: el tutorial lo hace por usted…' : ''}</p></div>
      <div class="tour-progress" aria-hidden="true"><span style="width:${((i + 1) / m.steps.length) * 100}%"></span></div>
      <div class="tour-pill-bar"><span class="tour-pill-t">${i + 1}/${m.steps.length} · ${esc(st.title)}</span><button type="button" class="btn ghost" data-act="expand">Ver el paso</button><button type="button" class="btn" data-act="pill-next" aria-label="${last ? 'Terminar' : 'Siguiente paso'}">${last ? '✓' : '›'}</button></div>
      <div class="tour-actions">
        ${st.demo ? `<button type="button" class="btn ghost tour-replay" data-act="replay" aria-label="Repetir la demostración">${ICON.replay}<span>Repetir</span></button>` : ''}
        <span class="tour-sp"></span>
        <button type="button" class="btn ghost" data-act="prev" ${i === 0 ? 'disabled' : ''}>Anterior</button>
        ${nextMode ? `<button type="button" class="btn ghost" data-act="next">Terminar</button><button type="button" class="btn" data-act="then">Seguir: ${esc(nextMode.title)}</button>`
          : `<button type="button" class="btn" data-act="next">${last ? 'Terminar' : 'Siguiente'}</button>`}
      </div>`;
    this.layout(true);  // el texto nuevo puede cambiar el alto: se recoloca ya, no en el cuadro siguiente
  }

  say(t) { const d = this.ui?.pop.querySelector('.tour-doing'); if (d) { d.textContent = t; this.layout(true); } }

  /** Espera a que exista el elemento (o se cumpla la condición). */
  async waitFor(sel, ms) {
    if (!sel) return null;
    const t0 = performance.now();
    for (;;) {
      const el = find(sel);
      if (el) return el === true ? document.body : el;
      if (performance.now() - t0 > ms) return null;
      await sleep(100);
    }
  }

  /** Espera a que la página deje de cambiar (sin contar el tutorial) y, si se pide, a un elemento. */
  async settle(ready, ms = 8000) {
    const t0 = performance.now();
    let last = performance.now();
    const mo = new MutationObserver((list) => { if (list.some((r) => !(r.target.closest?.('.tour-ui') || r.target.parentElement?.closest('.tour-ui')))) last = performance.now(); });
    mo.observe(document.body, { subtree: true, childList: true, attributes: true, characterData: true });
    try {
      for (;;) {
        await sleep(60);
        const ok = !ready || find(ready);
        if (ok && performance.now() - last > 220) return;
        if (performance.now() - t0 > ms) return;
      }
    } finally { mo.disconnect(); }
  }

  // -------------------------------------------------------------------------
  // Acciones: lo que el tutorial hace en la página
  // -------------------------------------------------------------------------

  async act(a, { visible, el = null }) {
    el = el || find(a.click || a.select || a.type || a.hover || a.open);
    if (!el) return;
    // Si la persona cierra el tutorial o cambia de paso mientras el puntero viaja o se escribe, la acción se cancela.
    const my = this.gen;
    const live = () => my === this.gen && this.ui;
    if (visible && !a.open) await this.point(el, a.at);
    if (!live()) return;
    // Lo que el tutorial pulsa no es una elección de la persona: ab.js no lo cuenta.
    const H = document.documentElement;
    H.dataset.tourDemo = '1';
    try {
      if (a.click) {
        if (el instanceof HTMLElement) el.click();
        else {
          const r = el.getBoundingClientRect();
          el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 }));
        }
      } else if (a.select) {
        el.value = a.value;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      } else if (a.type) {
        el.value = '';
        for (const ch of a.text) {
          el.value += ch;
          el.dispatchEvent(new Event('input', { bubbles: true }));
          if (visible && !reduced()) {
            delete H.dataset.tourDemo;
            await sleep(28);
            if (!live()) return;
            H.dataset.tourDemo = '1';
          }
        }
        if (a.submit) el.form?.requestSubmit();
      } else if (a.hover) {
        const r = el.getBoundingClientRect();
        const [fx, fy] = a.at || [0.5, 0.5];
        const init = { bubbles: true, cancelable: true, view: window, clientX: r.left + r.width * fx, clientY: r.top + r.height * fy, pointerType: 'mouse', isPrimary: true };
        el.dispatchEvent(typeof PointerEvent === 'function' ? new PointerEvent('pointermove', init) : new MouseEvent('pointermove', init));
        this.hovered = el;
      } else if (a.open) {
        el.open = a.value !== false;
      }
    } finally { delete H.dataset.tourDemo; }
    // El tooltip que abrió la demostración aparece ya: la ventana se aparta en este mismo cuadro.
    this.layout(true);
    // El puntero se va en cuanto toca: la página puede redibujarse y moverse debajo (queda su posición para la acción
    // siguiente).
    if (visible && this.ui) { this.ui.ptr.classList.remove('tap'); this.ui.ptr.hidden = true; }
  }

  /** Cierra el tooltip que abrió una demostración (la página lo cierra cuando el puntero sale del mapa). */
  unhover() {
    const h = this.hovered;
    this.hovered = null;
    if (!h?.isConnected) return;
    const box = h.closest('svg') || h;
    box.dispatchEvent(typeof PointerEvent === 'function' ? new PointerEvent('pointerleave', { bubbles: false, pointerType: 'mouse' }) : new MouseEvent('pointerleave'));
  }

  /** El puntero animado va hasta el control y marca el toque. */
  async point(el, at) {
    const p = this.ui?.ptr;
    if (!p) return;
    const r = el.getBoundingClientRect();
    const [fx, fy] = at || [0.5, 0.5];
    const x = r.left + r.width * fx, y = r.top + r.height * fy;
    p.hidden = false;
    if (reduced()) { p.style.transform = `translate(${x}px, ${y}px)`; }
    else {
      if (!p.dataset.placed) {
        const pr = this.ui.pop.getBoundingClientRect();
        p.style.transition = 'none';
        p.style.transform = `translate(${pr.left + pr.width / 2}px, ${pr.top + pr.height / 2}px)`;
        await frame();
        p.style.transition = '';
      }
      p.style.transform = `translate(${x}px, ${y}px)`;
      await sleep(620);
    }
    p.dataset.placed = '1';
    p.classList.add('tap');
    await sleep(reduced() ? 50 : 300);
  }

  // -------------------------------------------------------------------------
  // Geometría
  // -------------------------------------------------------------------------

  /** Los controles que el tutorial está tocando (se buscan en cada cuadro: la vista los redibuja). */
  acting() { return (this.actSel || []).map((s) => find(s)).filter((e) => e && e !== true); }

  /** Rectángulos que la ventana no puede tocar (en coordenadas de la ventana del navegador). */
  avoidRects({ plan = false } = {}) {
    const out = [];
    const st = this.step();
    // Al planear el desplazamiento no cuentan los `avoid` del paso (tooltips fijos a la ventana, que se mueven con
    // ella): se esquivan cuadro a cuadro al colocar la ventana.
    const els = [this.target, ...this.acting(), ...(plan ? [] : (st?.avoid || []).map((s) => find(s)))];
    // El control con el foco del teclado (WCAG 2.4.11): no los contenedores que reciben el foco al navegar (main).
    const act = document.activeElement;
    if (act && act !== document.body && act.id !== 'main' && !act.closest('.tour-ui') && !(this.target?.contains(act))) {
      const r = act.getBoundingClientRect();
      let fv = false;
      try { fv = act.matches(':focus-visible'); } catch { /* navegador sin :focus-visible */ }
      if (fv && r.height < innerHeight / 2) els.push(act);
    }
    for (const el of els) {
      if (!el?.isConnected) continue;
      const r = el.getBoundingClientRect();
      if (r.width || r.height) out.push(pad(toRect(r), el === this.target ? RING + HALO : 4));
    }
    return out;
  }

  /** Lo que debe quedar a la vista: el elemento y el control que se toca. */
  focusRect() {
    const box = (e) => pad(toRect(e.getBoundingClientRect()), RING);
    const t = this.target?.isConnected ? this.target : null;
    const acts = this.acting();
    const all = union([t, ...acts].filter(Boolean).map(box));
    if (!all || !acts.length) return all;
    // Si juntos no caben con la ventana, manda el control que se va a tocar (antes del toque) o lo resaltado.
    const vp = viewport();
    const room = vp.height - vp.top - 2 * EDGE - GAP - (this.ui?.pop.offsetHeight || 0);
    if (all.height <= room) return all;
    const main = this.primary === 'act' ? acts[0] : t || acts[0];
    return box(main);
  }

  setSpacers(top, bottom) {
    const mk = (cls, where) => {
      let s = document.querySelector(`.${cls}`);
      if (!s) { s = document.createElement('div'); s.className = cls; s.setAttribute('aria-hidden', 'true'); where(s); }
      return s;
    };
    const main = document.getElementById('main');
    if (top > 0 && main) mk('tour-spacer-top', (s) => main.prepend(s)).style.height = `${Math.ceil(top)}px`;
    else document.querySelector('.tour-spacer-top')?.remove();
    if (bottom > 0) mk('tour-spacer-bottom', (s) => document.body.append(s)).style.height = `${Math.ceil(bottom)}px`;
    else document.querySelector('.tour-spacer-bottom')?.remove();
  }

  /** Desplaza la página para que se vean el elemento y la ventana, sin taparse. */
  async replan({ keep = false } = {}) {
    if (!this.ui) return;
    const my = this.gen;
    this.settling = true;
    const pop = this.ui.pop;
    pop.classList.add('tour-moving');  // oculta ya, no en el cuadro siguiente
    pop.classList.remove('tour-pill');  // se mide la ventana entera, no la píldora
    // Los contenedores con desplazamiento horizontal (la barra de pestañas, las tablas anchas) primero.
    for (const el of [this.target, ...this.acting()]) if (el?.isConnected) scrollInline(el);
    const vp = viewport();
    const w = popWidth(vp);
    pop.style.width = `${w}px`;
    const F0 = this.focusRect();
    if (!F0) { this.settling = false; return; }
    // Alto natural (sin el límite del plan anterior), medido sin dejar pasar un cuadro.
    const prevMax = pop.style.maxHeight;
    pop.style.maxHeight = '';
    const body = pop.querySelector('.tour-body');
    // Lo mínimo: todo menos el texto, que se desplaza por dentro (así los botones quedan siempre a la vista).
    const size = { width: w, height: pop.offsetHeight, min: pop.offsetHeight - (body?.offsetHeight || 0) + 28 };
    pop.style.maxHeight = prevMax;
    const fixed = isFixed(this.target);
    if (fixed) { this.side = null; pop.style.maxHeight = ''; this.settling = false; return; }
    // En coordenadas del documento sin los espacios que agregó el tutorial: lo que no alcanza el desplazamiento de
    // la página se agrega como espacio arriba o abajo mientras dure el paso.
    const de = document.documentElement;
    const curTop = document.querySelector('.tour-spacer-top')?.offsetHeight || 0;
    const curBottom = document.querySelector('.tour-spacer-bottom')?.offsetHeight || 0;
    const y0 = window.scrollY - curTop;
    const doc = (r) => rect(r.top + window.scrollY - curTop, r.left, r.width, r.height);
    const plan = planScroll(vp, size, doc(F0), y0, this.avoidRects({ plan: true }).filter((r) => !intersects(r, F0)).map(doc));
    this.lastPlan = { vp, size, plan };  // para las pruebas y para depurar
    pop.style.maxHeight = plan.maxHeight ? `${plan.maxHeight}px` : '';
    const maxScroll = de.scrollHeight - curTop - curBottom - vp.height;
    const top = Math.min(2000, Math.max(0, -plan.y)), bottom = Math.min(2000, Math.max(0, plan.y - maxScroll));
    this.setSpacers(top, bottom);
    const y = Math.max(0, Math.round(plan.y + top));
    this.side = plan.side;
    if (Math.abs(y - window.scrollY) > (keep ? 2 : 1)) {
      window.scrollTo({ top: y, behavior: reduced() ? 'auto' : 'smooth' });
      await scrolled(y);
    }
    if (my !== this.gen) return;
    this.settling = false;
    this.planned = window.scrollY;
    this.layout(true);
  }

  /** Coloca el resaltado y la ventana (en cada cuadro). */
  layout(force = false) {
    const ui = this.ui;
    if (!ui) return;
    const vp = viewport();
    const t = this.target?.isConnected ? this.target : (this.target = this.reresolve());
    const ring = ui.ring;
    if (t) {
      const r = pad(toRect(t.getBoundingClientRect()), RING);
      // Recortado a la pantalla (con margen) para que el borde no marque un final que no es el del elemento; y bajo
      // la cabecera fija, que tapa lo que pasa por debajo (salvo que el elemento esté en ella).
      if (this.fixedOf !== t) { this.fixedOf = t; this.fixedT = isFixed(t); }
      const top = Math.max(r.top, this.fixedT ? -20 : vp.top - 2), bottom = Math.min(r.bottom, vp.height + 20);
      const key = `${r.left}|${top}|${r.width}|${bottom}`;
      if (ring.dataset.k !== key) {
        ring.dataset.k = key;
        Object.assign(ring.style, { left: `${r.left}px`, top: `${top}px`, width: `${r.width}px`, height: `${Math.max(0, bottom - top)}px` });
      }
      // Si en este momento no se ve nada del elemento (la demostración muestra otro control), no hay borde.
      ring.hidden = bottom - top < 4;
    } else ring.hidden = true;
    { const w = `${popWidth(vp)}px`; if (ui.pop.style.width !== w) ui.pop.style.width = w; }
    if (this.settling && !force) { ui.pop.classList.add('tour-moving'); return; }
    ui.pop.classList.remove('tour-moving');
    const pop = ui.pop;
    const pill = pop.classList.contains('tour-pill');
    const size = { width: pop.offsetWidth, height: pop.offsetHeight };
    // Los tooltips de los mapas también se esquivan (están sobre la cabecera: cuentan enteros para la píldora).
    const tips = [...document.querySelectorAll('.amap-tip:not([hidden]), .hz-tip:not([hidden])')].map((e) => e.getBoundingClientRect()).filter((r) => r.width && r.height);
    const avoid = [...this.avoidRects(), ...tips];
    let pos;
    if (pill) {
      // La píldora vuelve a ser ventana en cuanto cabe.
      pop.classList.remove('tour-pill');
      const full = { width: pop.offsetWidth, height: pop.offsetHeight };
      pos = placePopover(vp, full, this.focusRect(), avoid, this.side);
      if (pos.side === 'pill') pop.classList.add('tour-pill');
    } else pos = placePopover(vp, size, t ? this.focusRect() : null, avoid, this.side);
    if (!t && pos.side !== 'pill') pos = { side: 'dock', left: Math.round((vp.width - size.width) / 2), top: Math.max(vp.top + EDGE, vp.height - EDGE - size.height) };
    if (pos.side === 'pill') {
      pop.classList.add('tour-pill');
      const ps = { width: pop.offsetWidth, height: pop.offsetHeight };
      const bottom = vp.height - EDGE - ps.height;
      const spots = [[Math.round((vp.width - ps.width) / 2), EDGE], [vp.width - EDGE - ps.width, EDGE], [EDGE, EDGE],
        [Math.round((vp.width - ps.width) / 2), bottom], [EDGE, bottom], [vp.width - EDGE - ps.width, bottom]];
      const freeAt = ([x, y]) => !avoid.some((a) => intersects(rect(y, x, ps.width, ps.height), tips.includes(a) ? a : visibleUnderHeader(a, vp)));
      let ok = spots.find(freeAt);
      // Ni la píldora cabe: lo que estorba es un tooltip de la demostración. Se cierra (no se tapa).
      if (!ok && tips.length) {
        this.unhover();
        document.querySelectorAll('.amap-tip, .hz-tip').forEach((e) => { e.hidden = true; });
      }
      ok = ok || spots[0];
      pos = { side: 'pill', left: ok[0], top: ok[1] };
      // Sin lugar sin que la persona haya desplazado la página: algo cambió de tamaño (un gráfico que terminó de
      // dibujarse, una ficha que se abrió). Se vuelve a planear.
      if (t && Math.abs(window.scrollY - (this.planned ?? -1)) < 2 && !this.replanT) {
        this.replanT = setTimeout(() => { this.replanT = null; this.replan(); }, 250);
      }
    } else this.side = pos.side;
    const k = `${pos.left}|${pos.top}|${pos.side}`;
    if (pop.dataset.k !== k) {
      pop.dataset.k = k;
      pop.dataset.side = pos.side;
      pop.style.left = `${pos.left}px`;
      pop.style.top = `${pos.top}px`;
    }
  }

  /** El elemento se redibujó (el mapa, la ficha): se vuelve a buscar con el selector del paso o de la acción. */
  reresolve() {
    const el = find(this.targetSel);
    return el === true ? null : el;
  }
}

/** Ancho de la ventana del paso: 380 px o la pantalla menos los márgenes. */
const popWidth = (vp) => Math.max(200, Math.min(380, vp.width - 2 * EDGE));

/** Lo que se ve de un rectángulo: la cabecera fija tapa lo que pasa por debajo (salvo lo que está en ella). */
function visibleUnderHeader(r, vp) {
  if (r.bottom <= vp.top + 1) return r;  // está en la cabecera
  return rect(Math.max(r.top, vp.top), r.left, r.width, Math.max(0, r.bottom - Math.max(r.top, vp.top)));
}

function isFixed(el) {
  for (let e = el; e && e !== document.body; e = e.parentElement) {
    const p = getComputedStyle(e).position;
    if (p === 'fixed' || p === 'sticky') return true;
  }
  return false;
}

/** Centra el elemento dentro de sus contenedores con desplazamiento horizontal. */
function scrollInline(el) {
  for (let c = el.parentElement; c && c !== document.body; c = c.parentElement) {
    if (c.scrollWidth <= c.clientWidth + 1) continue;
    const ox = getComputedStyle(c).overflowX;
    if (ox !== 'auto' && ox !== 'scroll') continue;
    const cr = c.getBoundingClientRect(), er = el.getBoundingClientRect();
    if (er.left >= cr.left && er.right <= cr.right) continue;
    c.scrollLeft += er.left + er.width / 2 - (cr.left + cr.width / 2);
  }
}

/** Espera a que termine el desplazamiento suave (o a que deje de moverse). */
async function scrolled(y) {
  const t0 = performance.now();
  let last = window.scrollY, still = 0;
  while (performance.now() - t0 < 1500) {
    await frame();
    if (Math.abs(window.scrollY - y) <= 1) return;
    if (Math.abs(window.scrollY - last) < 0.5) { if (++still > 6) return; } else still = 0;
    last = window.scrollY;
  }
}
