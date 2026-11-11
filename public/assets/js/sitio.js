// Versión del sitio, selector de versiones y medición anónima del uso.
//
// Dos versiones de todo el sitio (experimento «sitio» de ab.js), con el mismo contenido:
//   A  Clásica: las trece pestañas en una fila y cada sección desplegada.
//   B  Agrupada: cinco secciones con submenús, una barra con las pestañas de la sección actual, las secciones largas
//      de consulta plegadas (con una vista previa y «Mostrar toda la sección») y las listas largas cortadas en 12
//      entradas con «Ver N más». Nada se quita: todo sigue a un clic, y el tutorial abre lo que necesita mostrar.
//
// El botón «Versión» de la cabecera dice qué versión se ve y deja cambiarla, junto con las versiones de la pestaña
// actual (los mapas de Noticias, de la memoria y del boletín), y no participar en la medición.
//
// Medición (functions/_lib/uso.js): al ocultarse o cerrarse la página se manda un resumen de esta visita: la
// versión del sitio, si es una sesión nueva, cuántas veces volvió (en tramos: 1, 2, 3-5, 6-10, 11+) y hace cuánto
// (hoy, 1-7, 8-30, 31+ días), cuántas veces se abrió cada pestaña, los segundos con la página visible y en uso en cada
// una (sin contar una pestaña olvidada: sin tocar nada en 60 s el reloj se detiene), qué secciones plegadas se
// abrieron y qué versiones se cambiaron. No hay identificador, cookie, IP ni huella: el contador de visitas vive solo
// en este navegador y el servidor suma números por día. Con «No rastrear», Global Privacy Control o la casilla del
// selector no se manda nada.

import { html, raw, esc, $, $$, storage } from './lib/dom.js';
import { ICON } from './icons.js';
import { ab, EXPERIMENTS, OPT_OUT_KEY, optedOut, canSend } from './ab.js';
import { applyGuides } from './leer.js';

// Pestañas (ruta, nombre, icono). La versión A las muestra todas en este orden.
export const NAV = [['', 'Resumen', 'home'], ['boletin', 'Boletín', 'bell'], ['costero', 'El Niño Costero', 'wave'], ['pacifico', 'Pacífico', 'globe'], ['oceano', 'Océano y atmósfera', 'layers'], ['mapa', 'Mapa', 'map'], ['historia', 'Historia', 'clock'], ['memoria', 'Memoria de desastres', 'pin'], ['zona', 'Mi zona', 'pin'], ['noticias', 'Noticias', 'news'], ['datos', 'Datos', 'table'], ['metodologia', 'Metodología', 'book'], ['asistente', 'Asistente', 'chat']];
const NAME = Object.fromEntries(NAV.map(([r, l]) => [r, l]));
const ICONS = Object.fromEntries(NAV.map(([r, , i]) => [r, i]));

// Versión B: las mismas trece pestañas en cinco secciones, con una línea de qué hay en cada una.
export const GROUPS = [
  { id: 'inicio', label: 'Inicio', icon: 'home', tabs: [['', 'El estado de hoy, de un vistazo'], ['boletin', 'Los cambios del día, en una hoja']] },
  { id: 'nino', label: 'El Niño', icon: 'wave', tabs: [['costero', 'ICEN y comunicados del ENFEN'], ['pacifico', 'RONI, ONI y las regiones Niño'], ['oceano', 'Mar, vientos, termoclina y SOI'], ['historia', 'Eventos pasados, comparados']] },
  { id: 'lugares', label: 'Lugares', icon: 'pin', tabs: [['zona', 'Historia y avisos de un lugar'], ['noticias', 'Avisos oficiales y noticias'], ['memoria', 'Desastres desde 1970, en el mapa'], ['mapa', 'Temperatura del mar en el mapa']] },
  { id: 'datos', label: 'Datos', icon: 'table', tabs: [['datos', 'Series, gráficos y descargas'], ['metodologia', 'Fuentes, vigencia y método']] },
  { id: 'asistente', label: 'Asistente', icon: 'chat', tabs: [['asistente', 'Preguntas sobre los datos']] },
];
const groupOf = (route) => GROUPS.find((g) => g.tabs.some(([r]) => r === route)) || GROUPS[0];

// Versión B: secciones de consulta que empiezan plegadas (por el id de su título) y tamaño de las listas cortadas.
export const FOLD = {
  '': ['peru-h', 'links-h'],
  boletin: ['bol-rules-h'],
  historia: ['imp-h'],
  memoria: ['hz-val-h', 'hz-prev-h', 'hz-past-h', 'hz-ev-h', 'hz-m-h'],
  noticias: ['nd-h'],
  metodologia: ['arch-h', 'met-h', 'gl-h'],
};
export const LIST_MAX = 12;

// Versiones de cada pestaña que el selector deja cambiar (los experimentos de ab.js).
const TAB_EXPS = { noticias: ['mapa', 'noticias'], memoria: ['memoria'], boletin: ['boletin'] };
const EXP_LABEL = { mapa: 'Mapa de alertas', noticias: 'Vista con que abre el mapa', memoria: 'Vista con que abre el mapa', boletin: 'Mapa del boletín' };

// ---------------------------------------------------------------------------
// Versión del sitio
// ---------------------------------------------------------------------------
let SITE = null;
const site = () => (SITE ||= ab('sitio'));
export const version = () => site().variant;
const vName = (v) => (v === 'B' ? 'Agrupada' : 'Clásica');

function applyVersion() {
  document.documentElement.dataset.sitio = version();
}

// ---------------------------------------------------------------------------
// Navegación
// ---------------------------------------------------------------------------
const chevron = '<svg class="chev" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M6 9l6 6 6-6"/></svg>';

function navA() {
  return NAV.map(([r, l, i]) => `<a href="#/${r}" data-route="${r}">${ICON[i] || ''}<span>${esc(l)}</span></a>`).join('');
}

function navB() {
  return GROUPS.map((g) => {
    if (g.tabs.length === 1) {
      const [r] = g.tabs[0];
      return `<a class="nav-solo" href="#/${r}" data-route="${r}" data-group="${g.id}">${ICON[g.icon] || ''}<span>${esc(g.label)}</span></a>`;
    }
    const items = g.tabs.map(([r, d]) => `<a href="#/${r}" data-route="${r}">${ICON[ICONS[r]] || ''}<span><span class="nm-name">${esc(NAME[r])}</span><span class="nm-desc">${esc(d)}</span></span></a>`).join('');
    return `<div class="nav-group" data-group="${g.id}"><button type="button" class="nav-gbtn" aria-expanded="false" aria-controls="ng-${g.id}">${ICON[g.icon] || ''}<span>${esc(g.label)}</span>${chevron}</button><div class="nav-menu" id="ng-${g.id}" hidden>${items}</div></div>`;
  }).join('');
}

function closeMenus(except = null) {
  $$('.nav-group').forEach((g) => {
    if (g === except) return;
    const b = $('.nav-gbtn', g);
    if (b.getAttribute('aria-expanded') === 'true') { b.setAttribute('aria-expanded', 'false'); $('.nav-menu', g).hidden = true; }
  });
}

function openMenu(g, focusFirst = false) {
  closeMenus(g);
  const b = $('.nav-gbtn', g), m = $('.nav-menu', g);
  b.setAttribute('aria-expanded', 'true');
  m.hidden = false;
  // Que el menú no se salga de la pantalla por la derecha (la última sección en un teléfono).
  m.style.left = '';
  const r = m.getBoundingClientRect();
  if (r.right > innerWidth - 8) m.style.left = `${Math.min(0, innerWidth - 8 - r.right)}px`;
  if (focusFirst) $('a', m)?.focus();
}

function wireNavB(nav) {
  nav.addEventListener('click', (e) => {
    const b = e.target.closest('.nav-gbtn');
    if (b) {
      const g = b.closest('.nav-group');
      if (b.getAttribute('aria-expanded') === 'true') closeMenus(); else openMenu(g);
      return;
    }
    if (e.target.closest('.nav-menu a')) closeMenus();
  });
  nav.addEventListener('keydown', (e) => {
    const g = e.target.closest('.nav-group');
    if (!g) return;
    const links = $$('.nav-menu a', g);
    const i = links.indexOf(e.target);
    if (e.key === 'Escape') { closeMenus(); $('.nav-gbtn', g).focus(); e.preventDefault(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); if (i < 0) openMenu(g, true); else links[(i + 1) % links.length].focus(); }
    else if (e.key === 'ArrowUp' && i >= 0) { e.preventDefault(); links[(i - 1 + links.length) % links.length].focus(); }
    else if (e.key === 'Home' && i >= 0) { e.preventDefault(); links[0].focus(); }
    else if (e.key === 'End' && i >= 0) { e.preventDefault(); links[links.length - 1].focus(); }
  });
  // Al salir con el teclado. (No con «focusout»: Safari no enfoca lo que se pulsa y cerraría el menú antes del clic.)
  document.addEventListener('focusin', (e) => { if (!e.target.closest?.('.nav-group')) closeMenus(); });
  document.addEventListener('click', (e) => { if (!e.target.closest?.('.nav-group')) closeMenus(); });
}

function drawNav() {
  const nav = $('#nav');
  const b = version() === 'B';
  nav.innerHTML = b ? navB() : navA();
  nav.classList.toggle('nav-grouped', b);
  let sub = $('#subnav');
  if (!sub) {
    sub = document.createElement('nav');
    sub.id = 'subnav';
    sub.className = 'subnav';
    sub.setAttribute('aria-label', 'Pestañas de esta sección');
    $('.site-header').after(sub); // fuera de la cabecera fija: en el teléfono no le quita alto a la página
  }
  sub.hidden = !b;
  if (b && !nav.dataset.wired) { wireNavB(nav); nav.dataset.wired = '1'; }
}

/** Marca la pestaña actual (las dos versiones) y, en la B, su sección y la barra de sus pestañas. */
export function syncNav(route) {
  $$('#nav a[data-route]').forEach((a) => a.setAttribute('aria-current', a.dataset.route === route ? 'page' : 'false'));
  if (version() !== 'B') return;
  const g = groupOf(route);
  $$('#nav [data-group]').forEach((el) => el.classList.toggle('active', el.dataset.group === g.id));
  const sub = $('#subnav');
  sub.hidden = g.tabs.length < 2;
  sub.innerHTML = g.tabs.length < 2 ? '' : `<div class="subnav-inner"><span class="subnav-h">${esc(g.label)}</span>${g.tabs.map(([r]) => `<a href="#/${r}" data-route="${r}" aria-current="${r === route ? 'page' : 'false'}">${esc(NAME[r])}</a>`).join('')}</div>`;
}

// ---------------------------------------------------------------------------
// Secciones plegadas y listas cortadas (versión B)
// ---------------------------------------------------------------------------
let currentRoute = '';

function setFold(sec, folded) {
  sec.classList.toggle('folded', folded);
  const b = $(':scope > .fold-btn', sec);
  if (b) {
    b.setAttribute('aria-expanded', String(!folded));
    b.lastChild.textContent = folded ? 'Mostrar toda la sección' : 'Plegar la sección';
  }
}

function foldSections(main) {
  for (const id of FOLD[currentRoute] || []) {
    const h = document.getElementById(id);
    const sec = h?.closest('section');
    if (!sec || sec.dataset.fold || !main.contains(sec)) continue;
    sec.dataset.fold = '1';
    sec.classList.add('foldable');
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'fold-btn';
    b.innerHTML = `${chevron}<span></span>`;
    b.addEventListener('click', () => {
      const opening = sec.classList.contains('folded');
      setFold(sec, !opening);
      if (opening) usage.unfold(); else sec.scrollIntoView({ block: 'nearest' });
    });
    sec.append(b);
    setFold(sec, true);
    // Quien llega con el teclado o el lector a algo que está en la parte plegada la ve completa.
    sec.addEventListener('focusin', (e) => { if (sec.classList.contains('folded') && e.target !== b) setFold(sec, false); });
  }
}

function clipLists(main) {
  for (const ul of $$('ul.feed', main)) {
    const n = ul.children.length;
    if (ul.dataset.clip || n <= LIST_MAX + 3) continue;
    ul.dataset.clip = '1';
    ul.classList.add('clipped');
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn ghost clip-btn';
    b.setAttribute('aria-expanded', 'false');
    b.textContent = `Ver ${n - LIST_MAX} más`;
    b.addEventListener('click', () => {
      ul.classList.remove('clipped');
      b.remove();
      usage.unfold();
      ul.children[LIST_MAX]?.querySelector('a')?.focus();
    });
    ul.after(b);
    ul.addEventListener('focusin', (e) => {
      if (ul.classList.contains('clipped') && [...ul.children].indexOf(e.target.closest('li')) >= LIST_MAX) { ul.classList.remove('clipped'); b.remove(); }
    });
  }
}

function compactNow() {
  const main = $('#main');
  if (!main) return;
  applyGuides(main); // «Cómo leer esto», en las dos versiones
  if (version() !== 'B') return;
  foldSections(main);
  clipLists(main);
}

// Lo que la vista pinta después (una lista que se filtra, un gráfico que llega): con una pausa corta, para que el
// globo de un gráfico que sigue al puntero no dispare el repaso en cada movimiento.
let pending = 0;
function compact() {
  clearTimeout(pending);
  pending = setTimeout(compactNow, 80);
}

/** Muestra un elemento que quedó en una sección plegada o en una lista cortada (el tutorial lo usa). */
export function reveal(el) {
  if (!el || !el.closest) return;
  const sec = el.closest('.folded');
  if (sec) setFold(sec, false);
  const ul = el.closest('ul.clipped');
  if (ul) { ul.classList.remove('clipped'); ul.nextElementSibling?.classList.contains('clip-btn') && ul.nextElementSibling.remove(); }
}

// ---------------------------------------------------------------------------
// Selector de versiones
// ---------------------------------------------------------------------------
let rerender = () => {};

function verLabel() {
  const b = $('#ver-btn');
  if (!b) return;
  const v = version();
  b.innerHTML = `<span class="ver-badge" aria-hidden="true">${v}</span><span class="hide-xs">Versión ${v} · ${vName(v)}</span>${chevron}`;
  b.setAttribute('aria-label', `Versión del sitio: ${v}, ${vName(v)}. Cambiar de versión`);
  b.title = site().preview ? 'Vista de un enlace: su versión elegida no cambia' : 'Cambiar la versión del sitio o de esta pestaña';
}

const cap = (t) => (t ? t[0].toUpperCase() + t.slice(1) : '');

function radios(name, list, cur, describe = (x) => x[1]) {
  return html`<div class="ver-opts" role="radiogroup" aria-label="${name}">${list.map((x) => html`<label class="ver-opt"><input type="radio" name="${name}" value="${x[0]}" ${x[0] === cur ? 'checked' : ''}><span class="ver-opt-l"><strong>${x[0].length <= 2 ? `Versión ${x[0]}` : x[1].split(':')[0]}</strong><span class="muted small">${cap(describe(x))}</span></span></label>`)}</div>`;
}

function panelHtml() {
  const v = version();
  const exps = (TAB_EXPS[currentRoute] || []).filter((x) => EXPERIMENTS[x]);
  const prev = site().preview;
  return html`<div class="ver-head"><h2 id="ver-h">Versiones del sitio</h2><button type="button" class="icon-btn ver-close" aria-label="Cerrar">${raw(ICON.close)}</button></div>
    <p class="small muted">Estamos probando dos formas de ordenar el mismo contenido. Elija la que le resulte más cómoda: queda guardada en este navegador. Nada se quita al cambiar.</p>
    ${prev ? html`<p class="notice notice-info small">${raw(ICON.info)}<span>Está viendo la versión ${prev} desde un enlace. Su versión elegida es la ${site().own}.</span></p>` : ''}
    <fieldset class="ver-set"><legend>Todo el sitio</legend>
      ${radios('sitio', EXPERIMENTS.sitio.variants, v, (x) => x[1].split(': ')[1] || x[1])}</fieldset>
    ${exps.length ? html`<fieldset class="ver-set"><legend>Esta pestaña: ${NAME[currentRoute]}</legend>
      ${exps.map((x) => html`<p class="ver-sub">${EXP_LABEL[x]}</p>${radios(x, EXPERIMENTS[x].variants, ab(x).variant, (o) => (o[0].length <= 2 ? o[1] : o[1].split(': ')[1] || ''))}`)}</fieldset>` : ''}
    <label class="ver-opt ver-optout"><input type="checkbox" id="ver-optout" ${storage(OPT_OUT_KEY) === '1' ? 'checked' : ''}><span class="ver-opt-l"><strong>No participar en la medición</strong><span class="muted small">La medición es anónima: cuenta, por día, cuánto se usa cada pestaña en cada versión, sin cookies ni datos de quien visita.${optedOut() && storage(OPT_OUT_KEY) !== '1' ? ' Su navegador ya pide no rastrear: no se manda nada.' : ''}</span></span></label>`;
}

function openPanel() {
  const pop = $('#ver-pop'), b = $('#ver-btn');
  pop.innerHTML = String(panelHtml());
  pop.hidden = false;
  b.setAttribute('aria-expanded', 'true');
  ($('input:checked', pop) || $('input', pop))?.focus();
}

function closePanel(focus = true) {
  const pop = $('#ver-pop'), b = $('#ver-btn');
  if (!pop || pop.hidden) return;
  pop.hidden = true;
  b.setAttribute('aria-expanded', 'false');
  if (focus) b.focus();
}

/** Vuelve a pintar la vista sin cerrar el selector ni quitarle el foco: quien compara versiones sigue ahí. */
let keepPanel = false;
function repaint(name) {
  keepPanel = true;
  try { rerender(); } finally { keepPanel = false; }
  $(`#ver-pop input[name="${name}"]:checked`)?.focus({ preventScroll: true });
}

function chooseSite(v) {
  if (v === version()) return;
  usage.flush(); // el tiempo hasta aquí es de la versión anterior
  site().choose(v);
  applyVersion();
  drawNav();
  verLabel();
  repaint('sitio');
}

function wirePanel() {
  const b = $('#ver-btn'), pop = $('#ver-pop');
  b.addEventListener('click', () => (pop.hidden ? openPanel() : closePanel()));
  pop.addEventListener('change', (e) => {
    const t = e.target;
    if (t.id === 'ver-optout') {
      storage(OPT_OUT_KEY, t.checked ? '1' : null);
      if (t.checked) usage.drop();
      return;
    }
    if (t.name === 'sitio') { chooseSite(t.value); return; }
    if (EXPERIMENTS[t.name]) {
      ab(t.name).choose(t.value);
      // La vista del enlace (?vista=, ?version=) ya no manda: se ve la elegida.
      const [path, q] = location.hash.split('?');
      const p = new URLSearchParams(q || '');
      p.delete('vista');
      p.delete('version');
      history.replaceState(null, '', `${path}${p.toString() ? `?${p}` : ''}`);
      repaint(t.name);
    }
  });
  pop.addEventListener('click', (e) => { if (e.target.closest('.ver-close')) closePanel(); });
  pop.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); closePanel(); } });
  document.addEventListener('click', (e) => { if (!pop.hidden && !e.target.closest?.('#ver-pop, #ver-btn')) closePanel(false); });
}

function mountSwitcher() {
  const actions = $('.header-actions');
  if (!actions || $('#ver-btn')) return;
  const wrap = document.createElement('div');
  wrap.className = 'ver-wrap';
  wrap.innerHTML = '<button type="button" class="icon-btn ver-btn" id="ver-btn" aria-haspopup="dialog" aria-expanded="false" aria-controls="ver-pop" data-tour-id="version-switch"></button><div class="ver-pop" id="ver-pop" role="dialog" aria-labelledby="ver-h" hidden></div>';
  actions.prepend(wrap);
  verLabel();
  wirePanel();
}

// ---------------------------------------------------------------------------
// Medición anónima del uso
// ---------------------------------------------------------------------------
const VISITS_KEY = 'enso-uso-visitas';
const SESSION_KEY = 'enso-uso-sesion';
const IDLE_MS = 60e3;
const SESSION_GAP_MS = 30 * 60e3;
const TICK_MS = 5e3;
const ROUTE_KEY = (r) => r || 'resumen';

export function visitBucket(n) {
  return n <= 1 ? '1' : n === 2 ? '2' : n <= 5 ? '3-5' : n <= 10 ? '6-10' : '11+';
}
export function gapBucket(days) {
  return days === null ? '' : days < 1 ? 'hoy' : days <= 7 ? '1-7' : days <= 30 ? '8-30' : '31+';
}

const ss = (k, v) => { try { if (v === undefined) return sessionStorage.getItem(k); sessionStorage.setItem(k, v); } catch { /* bloqueado */ } return null; };

const usage = {
  t: {}, v: {}, u: {}, c: [], fresh: false, vb: '', rb: '', last: Date.now(), tick: Date.now(), route: null, tabs: new Set(),

  start() {
    const now = Date.now();
    let ses = null;
    try { ses = JSON.parse(ss(SESSION_KEY) || 'null'); } catch { /* nada */ }
    if (!ses || now - ses.at > SESSION_GAP_MS) {
      let st = null;
      try { st = JSON.parse(storage(VISITS_KEY) || 'null'); } catch { /* nada */ }
      const n = (st?.n || 0) + 1;
      const gap = st?.at ? (now - st.at) / 864e5 : null;
      storage(VISITS_KEY, JSON.stringify({ n, at: now }));
      this.fresh = true;
      this.vb = visitBucket(n);
      this.rb = n > 1 ? gapBucket(gap) : '';
    }
    ss(SESSION_KEY, JSON.stringify({ at: now }));
    const act = () => { this.last = Date.now(); };
    for (const ev of ['pointerdown', 'keydown', 'wheel', 'touchstart', 'scroll']) addEventListener(ev, act, { passive: true, capture: true });
    let mv = 0;
    addEventListener('pointermove', () => { const t = Date.now(); if (t - mv > 2000) { mv = t; act(); } }, { passive: true });
    setInterval(() => this.count(), TICK_MS);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') { this.count(); this.flush(); } else { this.tick = Date.now(); this.last = Date.now(); }
    });
    addEventListener('pagehide', () => { this.count(); this.flush(); });
    document.addEventListener('ab:choose', (e) => {
      const { exp, from, to } = e.detail || {};
      if (exp && from && to && from !== to && this.c.length < 8) this.c.push([exp, from, to]);
    });
  },

  /** Suma el tiempo en uso desde el último conteo a la pestaña actual. */
  count() {
    const now = Date.now();
    const dt = Math.min(now - this.tick, TICK_MS + 1000);
    this.tick = now;
    if (this.route === null || document.visibilityState !== 'visible' || now - this.last > IDLE_MS) return;
    const k = ROUTE_KEY(this.route);
    this.t[k] = (this.t[k] || 0) + dt / 1000;
    ss(SESSION_KEY, JSON.stringify({ at: now }));
  },

  view(route) {
    this.count();
    this.route = route;
    this.last = Date.now();
    const k = ROUTE_KEY(route);
    this.v[k] = (this.v[k] || 0) + 1;
    this.tabs.add(k);
    // Para la decisión del experimento «sitio»: usar el sitio es ir más allá de la primera pestaña.
    if (this.tabs.size === 2) site().mark('use');
  },

  unfold() {
    const k = ROUTE_KEY(this.route);
    this.u[k] = (this.u[k] || 0) + 1;
  },

  drop() {
    this.t = {}; this.v = {}; this.u = {}; this.c = []; this.fresh = false;
  },

  payload() {
    const t = Object.fromEntries(Object.entries(this.t).map(([k, s]) => [k, Math.round(s)]).filter(([, s]) => s > 0));
    const body = { s: site().own, t, v: this.v };
    if (this.fresh) Object.assign(body, { n: 1, vb: this.vb, rb: this.rb || undefined });
    if (Object.keys(this.u).length) body.u = this.u;
    if (this.c.length) body.c = this.c;
    return body;
  },

  flush() {
    const body = this.payload();
    const empty = !body.n && !Object.keys(body.t).length && !Object.keys(body.v).length && !body.u && !body.c;
    // Lo que se vio desde un enlace de vista previa (?sitio=B) no se cuenta como uso de la versión.
    if (empty || site().preview) { this.drop(); return; }
    if (canSend()) {
      const text = JSON.stringify(body);
      try {
        if (!navigator.sendBeacon?.('api/uso/e', new Blob([text], { type: 'text/plain' }))) {
          fetch('api/uso/e', { method: 'POST', body: text, keepalive: true, headers: { 'Content-Type': 'text/plain' } }).catch(() => {});
        }
      } catch { /* la medición nunca rompe la página */ }
    }
    this.drop();
  },
};
export { usage as _usage };

// ---------------------------------------------------------------------------
// Arranque y cada vista
// ---------------------------------------------------------------------------
/** Prepara la versión, la navegación y el selector. ``opts.rerender`` vuelve a pintar la vista actual. */
export function initSite(opts = {}) {
  rerender = opts.rerender || rerender;
  applyVersion();
  drawNav();
  mountSwitcher();
  site().mark('view');
  usage.start();
  document.addEventListener('fold:reveal', (e) => reveal(e.detail));
  new MutationObserver(compact).observe($('#main'), { childList: true, subtree: true });
}

/** Llamada en cada cambio de vista (antes de pintar). */
export function enterView(route) {
  currentRoute = route;
  syncNav(route);
  closeMenus();
  if (!keepPanel) { closePanel(false); usage.view(route); }
}

/** Llamada cuando la vista terminó de pintarse. */
export function viewReady() {
  compactNow();
}
