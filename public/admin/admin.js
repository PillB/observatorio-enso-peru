// Consola de lugares: revisar y corregir dónde ocurre cada noticia o aviso.
// Lee las notas publicadas (../data/geo/items.json) y el nomenclátor (../data/geo/ubigeo.json); guarda las
// correcciones en la API (../api/geo/), que solo existe en el sitio de Cloudflare.
// Todo el texto se inserta con textContent: los títulos vienen de medios externos.

const API = new URL('../api/geo/', location.href);
const DATA = new URL('../data/geo/', location.href);
const PAGE = 50;
const REVIEW_BELOW = 0.8;
const METHOD = { texto: 'texto', campo: 'dato de la fuente', coordenadas: 'coordenadas', medio: 'medio regional', correccion: 'corrección', anterior: 'versión anterior' };
const LEVEL = { departamento: 'departamento', provincia: 'provincia', distrito: 'distrito' };
const ACTION = { set: 'corregida', confirm: 'confirmada', none: 'sin lugar / nacional', foreign: 'no es del Perú', clear: 'corrección deshecha' };

const $ = (id) => document.getElementById(id);
const state = { me: null, items: [], gaz: null, latest: new Map(), tab: 'review', shown: PAGE, q: '', dep: '' };

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
  return el;
}

function say(msg) {
  $('status').textContent = msg || '';
}

async function api(path, { method = 'GET', body } = {}) {
  const r = await fetch(new URL(path, API), {
    method, credentials: 'same-origin', cache: 'no-store',
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = {};
  try {
    data = await r.json();
  } catch { /* respuesta sin JSON: GitHub Pages u otro servidor sin la API */ }
  if (!r.ok) throw Object.assign(new Error(data.error || `Error ${r.status}`), { status: r.status });
  return data;
}

// --- Nomenclátor ---------------------------------------------------------------------

function placeName(code) {
  const g = state.gaz;
  if (!g) return code;
  const dep = g.departments[code.slice(0, 2)] || code.slice(0, 2);
  if (code.length === 2) return dep;
  const prov = g.provinces[code.slice(0, 4)] || code.slice(0, 4);
  if (code.length === 4) return `${prov} (provincia, ${dep})`;
  return `${g.districts[code] || code} (${prov}, ${dep})`;
}

function fillNames() {
  const list = $('gc-names');
  const g = state.gaz;
  const opts = [];
  for (const [c, n] of Object.entries(g.departments)) opts.push([`${n} — departamento`, c]);
  for (const [c, n] of Object.entries(g.provinces)) opts.push([`${n} — provincia de ${g.departments[c.slice(0, 2)]}`, c]);
  for (const [c, n] of Object.entries(g.districts)) opts.push([`${n} — distrito de ${g.provinces[c.slice(0, 4)]}, ${g.departments[c.slice(0, 2)]}`, c]);
  state.byLabel = new Map(opts);
  list.replaceChildren(...opts.map(([label]) => h('option', { value: label })));
  $('dep-filter').append(...Object.entries(g.departments).map(([c, n]) => h('option', { value: c }, n)));
}

// --- Estado de cada nota -------------------------------------------------------------

const latestFix = (it) => state.latest.get(it.id);
const isFixed = (it) => {
  const c = latestFix(it);
  return Boolean(c && c.action !== 'clear');
};

function needsReview(it) {
  if (isFixed(it)) return false;
  const g = it.geo;
  if (!g) return it.region === 'peru';
  if (g.review) return false;
  if (g.country !== 'PE' && !(g.places || []).length) return false;
  if ((g.suggested || []).length) return true;
  // Sin lugar: solo importa en noticias de impactos (una nota general sobre El Niño no ocurre en un sitio).
  if (!(g.places || []).length) return g.scope !== 'nacional' && it.relevance === 'impacto';
  return (g.confidence ?? 1) < REVIEW_BELOW || (g.places || []).some((p) => p.method === 'medio');
}

function matches(it) {
  const g = it.geo || {};
  if (state.dep === 'none' && (g.places || []).length) return false;
  if (state.dep && state.dep !== 'none' && !(g.departments || []).includes(state.dep)) return false;
  if (!state.q) return true;
  const hay = `${it.title} ${it.outlet} ${(g.places || []).map((p) => p.name).join(' ')}`.toLowerCase()
    .normalize('NFD').replace(/[̀-ͯ]/g, '');
  return hay.includes(state.q);
}

function visible() {
  const base = state.tab === 'review' ? state.items.filter(needsReview) : state.tab === 'done' ? state.items.filter((it) => latestFix(it)) : state.items;
  return base.filter(matches);
}

// --- Dibujo --------------------------------------------------------------------------

function placeChip(p, cls = '') {
  const low = p.confidence !== undefined && p.confidence < REVIEW_BELOW;
  return h('span', { class: `gc-place ${low ? 'low' : ''} ${cls}`.trim() },
    h('b', {}, placeName(p.code)),
    h('small', {}, `${LEVEL[p.level] || p.level} · ${METHOD[p.method] || p.method}${p.confidence !== undefined ? ` · ${Math.round(p.confidence * 100)} %` : ''}`),
    p.evidence ? h('small', {}, `«${p.evidence}»${p.rule ? ` (${p.rule})` : ''}`) : null);
}

function fixBanner(it) {
  const c = latestFix(it);
  if (!c) return null;
  const applied = c.action === 'clear' ? !(it.geo && it.geo.review) : Boolean(it.geo && it.geo.review && it.geo.review.rev === c.rev);
  const what = c.action === 'set' ? `: ${c.places.map(placeName).join('; ')}` : '';
  return h('p', { class: `gc-fix ${applied ? '' : 'pending'}` },
    `${c.action === 'clear' ? 'Corrección deshecha' : `Marcada como ${ACTION[c.action]}`}${what} por ${c.username}, ${fmt(c.at)}. `,
    applied ? 'Ya aplicada en el sitio.' : 'Se aplicará en la próxima actualización del sitio.',
    c.note ? h('span', { class: 'muted' }, ` Nota: ${c.note}`) : null);
}

function fmt(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString('es-PE', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'America/Lima' });
  } catch {
    return iso;
  }
}

function itemCard(it) {
  const g = it.geo || {};
  const li = h('li', { class: 'gc-item', 'data-id': it.id });
  const places = (g.places || []).map((p) => placeChip(p));
  const sugg = (g.suggested || []).map((p) => placeChip(p, 'sugg'));
  const scope = !places.length ? (g.country === 'PE' ? (g.scope === 'nacional' ? 'Alcance nacional (sin lugar específico)' : 'Sin lugar identificado') : g.scope === 'internacional' ? 'Fuera del Perú' : 'Sin lugar identificado') : null;
  const btn = (label, onclick, extra = {}) => h('button', { type: 'button', class: 'btn btn-small', onclick, ...extra }, label);
  li.append(...[
    h('div', { class: 'gc-meta' }, [it.outlet, fmt(it.published), it.kind].filter(Boolean).join(' · ')),
    h('h2', {}, it.link ? h('a', { href: it.link, target: '_blank', rel: 'noopener noreferrer' }, it.title) : it.title),
    it.summary ? h('p', { class: 'gc-summary' }, it.summary) : null,
    h('div', { class: 'gc-places' }, h('span', { class: 'gc-label' }, 'Ubicación'), places.length ? places : h('span', { class: 'muted' }, scope)),
    sugg.length ? h('div', { class: 'gc-places' }, h('span', { class: 'gc-label' }, 'Sugerido'), sugg) : null,
    fixBanner(it),
    h('div', { class: 'gc-actions' },
      places.length ? btn('Confirmar', () => save(it, { action: 'confirm' }, li)) : null,
      btn('Corregir…', () => openEditor(it, li)),
      btn('Nacional / sin lugar', () => save(it, { action: 'none' }, li)),
      btn('No es del Perú', () => save(it, { action: 'foreign' }, li)),
      isFixed(it) ? btn('Deshacer corrección', () => save(it, { action: 'clear' }, li)) : null,
      btn('Historial', () => history(it, li))),
  ].filter(Boolean));
  return li;
}

function render() {
  const all = visible();
  $('count-review').textContent = `(${state.items.filter(needsReview).length})`;
  $('count-all').textContent = `(${state.items.length})`;
  $('count-done').textContent = `(${state.items.filter((it) => latestFix(it)).length})`;
  const audit = state.tab === 'audit';
  $('list').hidden = audit;
  $('filters').hidden = audit;
  $('audit').hidden = !audit;
  if (audit) {
    $('more').hidden = true;
    $('list-info').textContent = '';
    loadAudit();
    return;
  }
  $('list-info').textContent = all.length ? `${Math.min(all.length, state.shown)} de ${all.length} notas` : 'No hay notas en esta vista.';
  $('list').replaceChildren(...all.slice(0, state.shown).map(itemCard));
  $('more').hidden = all.length <= state.shown;
}

// --- Acciones ------------------------------------------------------------------------

function snapshot(it) {
  const g = it.geo || {};
  return { places: (g.places || []).map((p) => ({ code: p.code, method: p.method, confidence: p.confidence })), scope: g.scope || null, country: g.country || null };
}

async function save(it, change, li) {
  const buttons = li.querySelectorAll('button');
  buttons.forEach((b) => { b.disabled = true; });
  const prev = latestFix(it);
  try {
    const res = await api('corrections', { method: 'POST', body: { item: it.id, expectedRev: prev ? prev.rev : 0, before: snapshot(it), ...change } });
    state.latest.set(it.id, { ...res, item: it.id });
    say(`Guardado: «${it.title.slice(0, 60)}» ${ACTION[res.action]}.`);
    li.replaceWith(itemCard(it));
    $('count-review').textContent = `(${state.items.filter(needsReview).length})`;
    $('count-done').textContent = `(${state.items.filter((x) => latestFix(x)).length})`;
  } catch (e) {
    if (e.status === 401) return showLogin('Su sesión venció. Vuelva a ingresar.');
    if (e.status === 409) await loadLatest();
    say(e.message);
    buttons.forEach((b) => { b.disabled = false; });
  }
  return null;
}

function openEditor(it, li) {
  if (li.querySelector('.gc-editor')) return;
  const form = $('editor-tpl').content.firstElementChild.cloneNode(true);
  const g = state.gaz;
  const chosen = new Set(((latestFix(it) || {}).action === 'set' ? latestFix(it).places : (it.geo?.places || []).map((p) => p.code)));
  const [dep, prov, dist] = ['dep', 'prov', 'dist'].map((c) => form.querySelector(`.${c}`));
  const list = form.querySelector('.gc-chosen');
  const err = form.querySelector('.gc-error');
  dep.append(...Object.entries(g.departments).map(([c, n]) => h('option', { value: c }, n)));
  const draw = () => list.replaceChildren(...[...chosen].map((c) => h('li', {}, placeName(c),
    h('button', { type: 'button', 'aria-label': `Quitar ${placeName(c)}`, onclick: () => { chosen.delete(c); draw(); } }, '×'))));
  const options = (sel, src, prefix, first) => {
    sel.replaceChildren(h('option', { value: '' }, first), ...Object.entries(src).filter(([c]) => prefix && c.startsWith(prefix)).map(([c, n]) => h('option', { value: c }, n)));
    sel.disabled = !prefix;
  };
  dep.addEventListener('change', () => { options(prov, g.provinces, dep.value, '(toda la región)'); options(dist, g.districts, '', '(toda la provincia)'); });
  prov.addEventListener('change', () => options(dist, g.districts, prov.value, '(toda la provincia)'));
  const add = (code) => {
    if (!code) return;
    // Un lugar más específico reemplaza a su departamento o provincia, y viceversa.
    for (const c of [...chosen]) if (code.startsWith(c) || c.startsWith(code)) chosen.delete(c);
    chosen.add(code);
    draw();
  };
  form.querySelector('.add').addEventListener('click', () => add(dist.value || prov.value || dep.value));
  const find = form.querySelector('.find');
  find.addEventListener('change', () => {
    const code = state.byLabel.get(find.value);
    if (code) {
      add(code);
      find.value = '';
    }
  });
  form.querySelector('.cancel').addEventListener('click', () => form.remove());
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (!chosen.size) {
      err.textContent = 'Agregue al menos un lugar, o use «Nacional / sin lugar».';
      return;
    }
    err.textContent = '';
    await save(it, { action: 'set', places: [...chosen], note: form.querySelector('.note').value }, li);
  });
  draw();
  li.append(form);
  dep.focus();
}

async function history(it, li) {
  const old = li.querySelector('.gc-history');
  if (old) return old.remove();
  try {
    const { corrections } = await api(`corrections?item=${encodeURIComponent(it.id)}`);
    li.append(h('div', { class: 'gc-history' }, h('b', {}, 'Historial de correcciones'),
      corrections.length ? h('ol', {}, corrections.map((c) => h('li', {},
        `v${c.rev} · ${fmt(c.at)} · ${c.username}: ${ACTION[c.action]}${c.places.length ? ` (${c.places.map(placeName).join('; ')})` : ''}${c.note ? ` · «${c.note}»` : ''}`)))
        : h('p', { class: 'muted' }, 'Sin correcciones: la ubicación es la automática.')));
  } catch (e) {
    say(e.message);
  }
  return null;
}

async function loadAudit() {
  try {
    const { events } = await api('audit?limit=300');
    const label = { login: 'ingresó', logout: 'salió', 'login-fallido': 'intento de ingreso fallido', 'login-bloqueado': 'ingreso bloqueado por intentos', correccion: 'corrigió' };
    $('audit').replaceChildren(...events.map((e) => h('li', { class: 'gc-audit-row' },
      `${fmt(e.at)} · ${e.username || '¿?'} ${label[e.event] || e.event}`,
      e.item_id ? ` «${(state.items.find((i) => i.id === e.item_id) || {}).title || e.item_id}»` : '',
      e.detail && e.detail.action ? ` → ${ACTION[e.detail.action]}${(e.detail.places || []).length ? ` (${e.detail.places.map(placeName).join('; ')})` : ''}` : '')));
  } catch (e) {
    say(e.message);
  }
}

async function loadLatest() {
  const { corrections } = await api('corrections');
  state.latest = new Map(corrections.map((c) => [c.item, c]));
}

// --- Sesión --------------------------------------------------------------------------

function showLogin(msg = '') {
  state.me = null;
  $('session').hidden = true;
  $('app-view').hidden = true;
  $('login-view').hidden = false;
  $('login-error').textContent = msg;
  $('username').focus();
}

async function start() {
  say('Cargando…');
  try {
    const [items, gaz] = await Promise.all([
      fetch(new URL('items.json', DATA), { cache: 'no-store' }).then((r) => (r.ok ? r.json() : { items: [] })),
      fetch(new URL('ubigeo.json', DATA), { cache: 'no-store' }).then((r) => { if (!r.ok) throw new Error('nomenclátor'); return r.json(); }),
    ]);
    state.items = items.items || [];
    state.gaz = gaz;
    fillNames();
    await loadLatest();
  } catch (e) {
    if (e.status === 401) return showLogin();
    say(`No se pudieron cargar los datos: ${e.message}`);
    return null;
  }
  $('login-view').hidden = true;
  $('app-view').hidden = false;
  $('session').hidden = false;
  $('who').textContent = `${state.me.username}${state.me.role === 'admin' ? ' (administración)' : ''}`;
  say('');
  render();
  return null;
}

async function boot() {
  try {
    state.me = await api('me');
  } catch (e) {
    if (e.status === 503) return say(`${e.message}`);
    if (e.status !== 401) return say('La consola solo funciona en el sitio publicado en Cloudflare (no se encontró su API).');
    return showLogin();
  }
  return start();
}

$('login-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const btn = ev.submitter || $('login-form').querySelector('button');
  btn.disabled = true;
  $('login-error').textContent = '';
  try {
    state.me = await api('login', { method: 'POST', body: { username: $('username').value, password: $('password').value } });
    $('password').value = '';
    await start();
  } catch (e) {
    $('login-error').textContent = e.message;
  } finally {
    btn.disabled = false;
  }
});

$('logout').addEventListener('click', async () => {
  try {
    await api('logout', { method: 'POST', body: {} });
  } catch { /* igual se sale */ }
  showLogin('Sesión cerrada.');
});

document.querySelectorAll('.gc-tabs [role=tab]').forEach((b) => b.addEventListener('click', () => {
  state.tab = b.dataset.tab;
  state.shown = PAGE;
  document.querySelectorAll('.gc-tabs [role=tab]').forEach((x) => x.setAttribute('aria-selected', String(x === b)));
  render();
}));

let timer;
$('q').addEventListener('input', () => {
  clearTimeout(timer);
  timer = setTimeout(() => {
    state.q = $('q').value.trim().toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
    state.shown = PAGE;
    render();
  }, 150);
});
$('dep-filter').addEventListener('change', () => {
  state.dep = $('dep-filter').value;
  state.shown = PAGE;
  render();
});
$('more').addEventListener('click', () => {
  state.shown += PAGE;
  render();
});

boot();
