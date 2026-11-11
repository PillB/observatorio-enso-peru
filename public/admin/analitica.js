// Analítica de uso de la consola: cómo se usa cada versión del sitio (A clásica, B agrupada).
// Lee ../api/uso/stats (con la sesión de la consola) y ../api/ab/stats (los experimentos de los mapas). Solo hay
// contadores por día: aquí se suman y se comparan. Todo se dibuja con nodos del DOM y SVG (la política de contenido
// de la consola no permite estilos ni scripts en línea).

import { statsHtml } from '../assets/js/alertmap.js';

const GEO = new URL('../api/geo/', location.href);
const USO = new URL('../api/uso/', location.href);
const AB = new URL('../api/ab/', location.href);
const SVG = 'http://www.w3.org/2000/svg';
const SITES = [['A', 'Clásica'], ['B', 'Agrupada']];
const TAB = { resumen: 'Resumen', boletin: 'Boletín', costero: 'El Niño Costero', pacifico: 'Pacífico', oceano: 'Océano y atmósfera', mapa: 'Mapa', historia: 'Historia', memoria: 'Memoria de desastres', zona: 'Mi zona', noticias: 'Noticias', datos: 'Datos', metodologia: 'Metodología', asistente: 'Asistente', variantes: 'Versiones de los mapas' };
const EXP = { sitio: 'Versión del sitio', mapa: 'Mapa de alertas', noticias: 'Vista del mapa de Noticias', memoria: 'Vista del mapa de la memoria', boletin: 'Mapa del boletín' };
const VISITS = [['1', 'Primera visita'], ['2', 'Segunda'], ['3-5', '3 a 5'], ['6-10', '6 a 10'], ['11+', '11 o más']];
const GAPS = [['hoy', 'El mismo día'], ['1-7', '1 a 7 días'], ['8-30', '8 a 30 días'], ['31+', 'Más de 30 días']];
const MIN_SESSIONS = 30; // por versión, para leer una diferencia sin que sea ruido

const $ = (id) => document.getElementById(id);
const state = { me: null, days: 30, uso: null, ab: null };

function h(tag, attrs = {}, ...kids) {
  const el = tag === 'svg' || attrs.ns ? document.createElementNS(SVG, tag) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'ns' || v === null || v === undefined || v === false) continue;
    if (k === 'class') el.setAttribute('class', v);
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
  return el;
}
const s = (tag, attrs = {}, ...kids) => h(tag, { ...attrs, ns: 1 }, ...kids);
const say = (msg) => { $('status').textContent = msg || ''; };

async function call(base, path, { method = 'GET', body } = {}) {
  const r = await fetch(new URL(path, base), {
    method, credentials: 'same-origin', cache: 'no-store',
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = {};
  try { data = await r.json(); } catch { /* sin JSON: un servidor sin la API */ }
  if (!r.ok) throw Object.assign(new Error(data.error || `Error ${r.status}`), { status: r.status });
  return data;
}

// --- Números ---------------------------------------------------------------------------------------------------
const nf = new Intl.NumberFormat('es-PE');
const n0 = (x) => nf.format(Math.round(x));
const pct = (a, b) => (b ? `${Math.round((100 * a) / b)} %` : '—');
const sum = (o) => Object.values(o || {}).reduce((a, b) => a + b, 0);
export function dur(secs) {
  if (!Number.isFinite(secs) || secs <= 0) return '—';
  if (secs < 60) return `${Math.round(secs)} s`;
  const m = Math.floor(secs / 60), r = Math.round(secs % 60);
  return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min ${String(r).padStart(2, '0')} s`;
}
const day = (d) => new Date(`${d}T12:00:00Z`).toLocaleDateString('es-PE', { day: 'numeric', month: 'short', timeZone: 'UTC' });

/** Lo que se muestra de una versión: sesiones, quienes vuelven, tiempo y pestañas por sesión. */
export function summary(t) {
  const ses = t.sesion?.nueva || 0;
  const first = t.visita?.['1'] || 0;
  const known = sum(t.visita);
  const secs = sum(t.seg), views = sum(t.vista);
  return { ses, back: known - first, known, secs, views, perSes: ses ? secs / ses : null, tabsPerSes: ses ? views / ses : null };
}

/** Ancho de los gráficos en píxeles reales del contenedor: así el texto del SVG no se achica en el teléfono. */
function chartWidth() {
  const w = Math.min(1080, document.documentElement.clientWidth) - 76;
  return Math.max(260, Math.min(980, w));
}

// --- Piezas ----------------------------------------------------------------------------------------------------
const key = (v) => h('span', { class: `an-key an-key-${v.toLowerCase()}` }, h('span', { class: 'an-swatch', 'aria-hidden': 'true' }), `Versión ${v}`);
const legend = () => h('p', { class: 'an-legend' }, SITES.map(([v, l]) => h('span', { class: `an-key an-key-${v.toLowerCase()}` }, h('span', { class: 'an-swatch', 'aria-hidden': 'true' }), `${v} · ${l}`)));
const card = (title, note, ...kids) => h('section', { class: 'gc-card an-card' }, h('h2', {}, title), note ? h('p', { class: 'muted small' }, note) : null, ...kids);

function tile(label, a, b, hint) {
  return h('div', { class: 'an-tile' }, h('div', { class: 'an-tile-l' }, label),
    h('div', { class: 'an-tile-v' }, h('div', {}, key('A'), h('strong', {}, a)), h('div', {}, key('B'), h('strong', {}, b))),
    hint ? h('div', { class: 'muted small' }, hint) : null);
}

/** Barras horizontales agrupadas: una fila por categoría, una barra por versión, con su valor al final. */
function bars(rows, fmt, label) {
  const max = Math.max(1, ...rows.flatMap((r) => [r.A, r.B]));
  const W = chartWidth(), narrow = W < 480, L = narrow ? 112 : 170, R = 78, BH = 12, GAP = 3, ROW = 2 * BH + GAP + 14;
  const short = (t) => (narrow && t.length > 16 ? `${t.slice(0, 15)}…` : t);
  const H = rows.length * ROW + 4;
  const svg = h('svg', { viewBox: `0 0 ${W} ${H}`, class: 'an-bars', role: 'img', 'aria-label': label });
  rows.forEach((r, i) => {
    const y = i * ROW + 4;
    svg.append(s('text', { x: L - 10, y: y + BH + GAP / 2 + 4, 'text-anchor': 'end', class: 'an-axis' }, short(r.label)));
    SITES.forEach(([v], j) => {
      const w = Math.max(r[v] > 0 ? 2 : 0, ((W - L - R) * r[v]) / max);
      const by = y + j * (BH + GAP);
      const g = s('g', { class: 'an-hit' });
      g.append(s('title', {}, `${r.label}, versión ${v}: ${fmt(r[v])}`));
      g.append(s('rect', { x: L, y: by, width: W - L - R, height: BH, class: 'an-track' }));
      g.append(s('rect', { x: L, y: by, width: w, height: BH, rx: 3, class: `an-fill-${v.toLowerCase()}` }));
      g.append(s('text', { x: L + w + 6, y: by + BH - 2, class: 'an-val' }, fmt(r[v])));
      svg.append(g);
    });
  });
  return svg;
}

/** Sesiones por día, una línea por versión, con una regla que sigue al puntero y dice los valores del día. */
function lines(days, series) {
  const W = chartWidth(), H = 220, L = 36, R = 12, T = 12, B = 26;
  const max = Math.max(1, ...series.flatMap((x) => x.values));
  const step = max <= 5 ? 1 : 10 ** Math.floor(Math.log10(max)) / (max / 10 ** Math.floor(Math.log10(max)) < 3 ? 2 : 1);
  const top = Math.ceil(max / step) * step;
  const x = (i) => L + (days.length === 1 ? (W - L - R) / 2 : ((W - L - R) * i) / (days.length - 1));
  const y = (v) => T + (H - T - B) * (1 - v / top);
  const svg = h('svg', { viewBox: `0 0 ${W} ${H}`, class: 'an-lines', role: 'img', 'aria-label': 'Sesiones nuevas por día en cada versión' });
  for (let v = 0; v <= top; v += step) {
    svg.append(s('line', { x1: L, x2: W - R, y1: y(v), y2: y(v), class: 'an-grid' }), s('text', { x: L - 6, y: y(v) + 4, 'text-anchor': 'end', class: 'an-axis' }, n0(v)));
  }
  const every = Math.ceil(days.length / (W < 480 ? 3 : 6));
  days.forEach((d, i) => { if (i % every === 0 || i === days.length - 1) svg.append(s('text', { x: x(i), y: H - 6, 'text-anchor': i === 0 ? 'start' : i === days.length - 1 ? 'end' : 'middle', class: 'an-axis' }, day(d))); });
  for (const sr of series) {
    svg.append(s('polyline', { points: sr.values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' '), class: `an-line an-stroke-${sr.id.toLowerCase()}` }));
    const last = sr.values.length - 1;
    svg.append(s('circle', { cx: x(last), cy: y(sr.values[last]), r: 4, class: `an-dot an-fill-${sr.id.toLowerCase()}` }));
  }
  const rule = s('line', { y1: T, y2: H - B, class: 'an-rule', visibility: 'hidden' });
  svg.append(rule);
  const tip = h('p', { class: 'an-tip', 'aria-live': 'off' }, 'Pase el puntero por el gráfico para ver cada día.');
  const at = (ev) => {
    const r = svg.getBoundingClientRect();
    const px = ((ev.clientX - r.left) / r.width) * W;
    const i = Math.max(0, Math.min(days.length - 1, Math.round(((px - L) / (W - L - R)) * (days.length - 1))));
    rule.setAttribute('x1', x(i)); rule.setAttribute('x2', x(i)); rule.setAttribute('visibility', 'visible');
    tip.replaceChildren(h('strong', {}, day(days[i])), ...series.flatMap((sr) => [' · ', key(sr.id), ` ${n0(sr.values[i])}`]));
  };
  svg.addEventListener('pointermove', at);
  svg.addEventListener('pointerdown', at);
  svg.addEventListener('pointerleave', () => rule.setAttribute('visibility', 'hidden'));
  return h('div', {}, svg, tip);
}

function table(head, rows, caption) {
  return h('div', { class: 'table-wrap' }, h('table', { class: 'an-table' }, caption ? h('caption', { class: 'visually-hidden' }, caption) : null,
    h('thead', {}, h('tr', {}, head.map((c, i) => h('th', { scope: 'col', class: i ? 'num' : null }, c)))),
    h('tbody', {}, rows.map((r) => h('tr', {}, r.map((c, i) => (i ? h('td', { class: 'num' }, c) : h('th', { scope: 'row' }, c))))))));
}

// --- Lectura ---------------------------------------------------------------------------------------------------
function verdict(a, b) {
  if (a.ses < MIN_SESSIONS || b.ses < MIN_SESSIONS) {
    return `Todavía es pronto para comparar: hacen falta al menos ${MIN_SESSIONS} sesiones en cada versión (A tiene ${n0(a.ses)}; B, ${n0(b.ses)}). Con pocas sesiones las diferencias son azar.`;
  }
  const more = a.perSes === b.perSes ? null : a.perSes > b.perSes ? 'A' : 'B';
  const backA = a.known ? a.back / a.known : 0, backB = b.known ? b.back / b.known : 0;
  const parts = [];
  if (more) parts.push(`En la versión ${more} cada sesión pasa más tiempo en uso (${dur(Math.max(a.perSes, b.perSes))} frente a ${dur(Math.min(a.perSes, b.perSes))})`);
  if (Math.abs(backA - backB) >= 0.03) parts.push(`vuelve más gente a la ${backA > backB ? 'A' : 'B'} (${pct(Math.max(backA, backB), 1)} de sus sesiones son de alguien que ya había venido, frente a ${pct(Math.min(backA, backB), 1)})`);
  return parts.length ? `${parts.join(' y ')}. Más tiempo no siempre es mejor: en la B hay menos que recorrer para llegar a lo mismo; mire también qué pestañas se abren y qué se cambia.` : 'Las dos versiones se usan de forma parecida en este periodo.';
}

function render() {
  const body = $('an-body');
  const u = state.uso;
  if (!u || u.available === false) {
    body.replaceChildren(h('p', { class: 'gc-card' }, 'La base de datos no está vinculada en este despliegue (GEO_DB): no hay medición que mostrar.'));
    return;
  }
  $('an-range').textContent = `Desde el ${day(u.since)} (${u.days} días). Los días son UTC: el día cambia a las 19:00 de Lima.`;
  const T = u.totals, A = summary(T.A), B = summary(T.B);
  const out = [];
  if (!A.ses && !B.ses) {
    out.push(h('p', { class: 'gc-card an-empty' }, 'Todavía no hay sesiones medidas en este periodo. La medición empieza cuando alguien visita el sitio publicado; quien pide no ser rastreado no cuenta.'));
  } else {
    out.push(h('p', { class: 'gc-card an-verdict' }, h('strong', {}, 'Lectura. '), verdict(A, B)));
    out.push(h('div', { class: 'an-tiles' },
      tile('Sesiones', n0(A.ses), n0(B.ses), 'Una sesión termina tras 30 minutos sin actividad.'),
      tile('Sesiones de quien ya había venido', pct(A.back, A.known), pct(B.back, B.known), 'De ese navegador: no se sabe quién es.'),
      tile('Tiempo en uso por sesión', dur(A.perSes), dur(B.perSes), 'Con la página visible y actividad en el último minuto.'),
      tile('Pestañas abiertas por sesión', A.tabsPerSes ? A.tabsPerSes.toFixed(1).replace('.', ',') : '—', B.tabsPerSes ? B.tabsPerSes.toFixed(1).replace('.', ',') : '—', 'Cuenta cada vez que se abre una pestaña.')));

    const days = [...new Set(u.rows.map((r) => r.day))].sort();
    const all = [];
    for (let d = new Date(`${u.since}T00:00:00Z`); d <= new Date(); d = new Date(d.getTime() + 864e5)) all.push(d.toISOString().slice(0, 10));
    const span = all.length ? all : days;
    const perDay = (v) => span.map((d) => u.rows.filter((r) => r.day === d && r.site === v && r.dim === 'sesion').reduce((a, r) => a + r.n, 0));
    out.push(card('Sesiones por día', null, legend(), lines(span, SITES.map(([v]) => ({ id: v, values: perDay(v) })))));

    const tabs = Object.keys(TAB).filter((k) => (T.A.seg[k] || 0) + (T.B.seg[k] || 0) + (T.A.vista[k] || 0) + (T.B.vista[k] || 0) > 0)
      .sort((x, y) => ((T.A.seg[y] || 0) + (T.B.seg[y] || 0)) - ((T.A.seg[x] || 0) + (T.B.seg[x] || 0)));
    if (tabs.length) {
      const per = (t, v, tot) => (tot.ses ? (t.seg[v] || 0) / tot.ses : 0);
      out.push(card('Dónde se pasa el tiempo', 'Segundos en uso en cada pestaña por sesión de esa versión, para comparar aunque una versión tenga más visitas que la otra.',
        legend(), bars(tabs.map((k) => ({ label: TAB[k], A: per(T.A, k, A), B: per(T.B, k, B) })), (x) => (x ? dur(x) : '0 s'), 'Tiempo en uso por sesión en cada pestaña, versión A y versión B'),
        h('details', { class: 'an-more' }, h('summary', {}, 'Ver la tabla'),
          table(['Pestaña', 'Veces abierta, A', 'Veces abierta, B', 'Tiempo total, A', 'Tiempo total, B', 'Tiempo por apertura, A', 'Tiempo por apertura, B'],
            tabs.map((k) => [TAB[k], n0(T.A.vista[k] || 0), n0(T.B.vista[k] || 0), dur(T.A.seg[k] || 0), dur(T.B.seg[k] || 0), dur((T.A.seg[k] || 0) / (T.A.vista[k] || 1)), dur((T.B.seg[k] || 0) / (T.B.vista[k] || 1))]), 'Uso de cada pestaña por versión'))));
      out.push(card('Qué pestañas se abren', 'De cada 100 aperturas de pestaña de esa versión, cuántas son de cada una. Si la B esconde algo que se usaba, aquí baja.',
        legend(), bars(tabs.map((k) => ({ label: TAB[k], A: A.views ? (100 * (T.A.vista[k] || 0)) / A.views : 0, B: B.views ? (100 * (T.B.vista[k] || 0)) / B.views : 0 })), (x) => `${Math.round(x)} %`, 'Reparto de las aperturas de pestaña, versión A y versión B')));
    }

    out.push(card('Visitas repetidas', 'Qué número de visita era cada sesión (lo cuenta el propio navegador) y, para quien vuelve, cuánto había pasado.',
      h('div', { class: 'an-two' },
        table(['Número de visita', 'A', 'B'], VISITS.map(([k, l]) => [l, `${n0(T.A.visita[k] || 0)} · ${pct(T.A.visita[k] || 0, A.known)}`, `${n0(T.B.visita[k] || 0)} · ${pct(T.B.visita[k] || 0, B.known)}`]), 'Sesiones por número de visita'),
        table(['Volvió después de', 'A', 'B'], GAPS.map(([k, l]) => [l, n0(T.A.vuelta[k] || 0), n0(T.B.vuelta[k] || 0)]), 'Tiempo desde la visita anterior'))));

    const changes = {};
    for (const [v] of SITES) for (const [k, n] of Object.entries(T[v].cambio)) changes[k] = (changes[k] || 0) + n;
    const toB = changes['sitio:A>B'] || 0, toA = changes['sitio:B>A'] || 0;
    const rows = Object.entries(changes).sort((x, y) => y[1] - x[1]).map(([k, n]) => { const [x, mv] = k.split(':'); const [from, to] = mv.split('>'); return [EXP[x] || x, `${from} → ${to}`, n0(n)]; });
    out.push(card('Qué versiones se cambian', 'Cada vez que alguien elige otra versión en el selector de la cabecera o en una pestaña.',
      h('p', {}, h('strong', {}, `De A a B: ${n0(toB)}`), ' · ', h('strong', {}, `de B a A: ${n0(toA)}`), toB + toA ? `. ${toB === toA ? 'Empate.' : `Más gente se pasa a la ${toB > toA ? 'B' : 'A'}.`}` : '. Nadie cambió de versión del sitio en este periodo.'),
      rows.length ? table(['Qué', 'Cambio', 'Veces'], rows.map(([a, b, c]) => [a, b, c]), 'Cambios de versión') : null));

    const opened = Object.keys(TAB).filter((k) => T.B.abrir[k] || T.A.abrir[k]);
    out.push(card('Lo plegado que se abre (versión B)', 'Cuántas veces se abrió una sección plegada o una lista cortada, frente a las veces que se abrió la pestaña. Si casi siempre se abre, esa sección no debería estar plegada.',
      opened.length ? table(['Pestaña', 'Abrió algo plegado', 'Veces abierta la pestaña', 'Proporción'], opened.map((k) => [TAB[k], n0(T.B.abrir[k] || 0), n0(T.B.vista[k] || 0), pct(T.B.abrir[k] || 0, T.B.vista[k] || 0)]), 'Secciones plegadas abiertas') : h('p', { class: 'muted' }, 'Nadie abrió una sección plegada en este periodo.')));
  }

  const maps = h('div', { class: 'an-maps' });
  // statsHtml arma su HTML con la plantilla que escapa cada valor (lib/dom.js); los datos son contadores propios.
  maps.innerHTML = String(statsHtml(state.ab));
  out.push(h('section', { class: 'gc-card an-card' }, h('h2', {}, 'Versiones de los mapas y del sitio'), h('p', { class: 'muted small' }, 'Los experimentos de cada mapa (Noticias, memoria, boletín) y el del sitio: quién ve cada versión, quién la usa y si ya hay una ganadora.'), maps));
  body.replaceChildren(...out);
}

async function load(days = state.days) {
  state.days = days;
  document.querySelectorAll('[data-days]').forEach((b) => b.setAttribute('aria-pressed', String(Number(b.dataset.days) === days)));
  say('Cargando…');
  try {
    const [uso, ab] = await Promise.all([call(USO, `stats?days=${days}`), call(AB, `stats?days=${days}`).catch(() => null)]);
    state.uso = uso;
    state.ab = ab;
  } catch (e) {
    if (e.status === 401) return showLogin('Su sesión venció. Vuelva a ingresar.');
    say(`No se pudo leer la analítica: ${e.message}`);
    return null;
  }
  say('');
  render();
  return null;
}

function showLogin(msg = '') {
  state.me = null;
  $('session').hidden = true;
  $('app-view').hidden = true;
  $('login-view').hidden = false;
  $('login-error').textContent = msg;
  $('username').focus();
}

async function start() {
  $('login-view').hidden = true;
  $('app-view').hidden = false;
  $('session').hidden = false;
  $('who').textContent = `${state.me.username}${state.me.role === 'admin' ? ' (administración)' : ''}`;
  await load();
}

async function boot() {
  try {
    state.me = await call(GEO, 'me');
  } catch (e) {
    if (e.status === 503) return say(e.message);
    if (e.status !== 401) return say('La consola solo funciona en el sitio publicado en Cloudflare (no se encontró su API).');
    return showLogin();
  }
  return start();
}

if (typeof document !== 'undefined' && $('login-form')) {
  $('login-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const btn = ev.submitter || $('login-form').querySelector('button');
    btn.disabled = true;
    $('login-error').textContent = '';
    try {
      state.me = await call(GEO, 'login', { method: 'POST', body: { username: $('username').value, password: $('password').value } });
      $('password').value = '';
      await start();
    } catch (e) {
      $('login-error').textContent = e.message;
    } finally {
      btn.disabled = false;
    }
  });
  $('logout').addEventListener('click', async () => {
    try { await call(GEO, 'logout', { method: 'POST', body: {} }); } catch { /* igual se sale */ }
    showLogin('Sesión cerrada.');
  });
  document.querySelectorAll('[data-days]').forEach((b) => b.addEventListener('click', () => load(Number(b.dataset.days))));
  let last = chartWidth(), timer;
  addEventListener('resize', () => {
    clearTimeout(timer);
    timer = setTimeout(() => { if (state.uso && chartWidth() !== last) { last = chartWidth(); render(); } }, 200);
  });
  boot();
}
