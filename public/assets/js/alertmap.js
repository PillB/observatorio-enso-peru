// Mapa de alertas sobre las noticias: qué departamentos tienen avisos oficiales ahora, cuáles se esperan y
// dónde hubo daños, con el nivel que asignó cada institución.
//
// Todo sale de feed.json (grupo «alertas»), que arma el pipeline: el nivel (severity) es el de la fuente
// (SENAMHI, IGP, USGS, DHN…) y nunca se calcula aquí; un aviso sin nivel en su fuente se pinta «sin nivel».
// Lo único que se calcula en el navegador es si un aviso ya empezó o ya venció, comparando su vigencia
// (valid) con la hora actual. Los lugares son los publicados (confianza ≥ 0,5); los aproximados (< 0,8) se
// marcan con «≈». Las sugerencias de la consola de lugares no llegan a feed.json.
//
// Hay cuatro versiones del mapa (ab.js); comparten los datos, el resumen, los filtros y la lista accesible.

import { html, raw, esc, safeUrl, $, $$ } from './lib/dom.js';
import { ICON } from './icons.js';
import { ab, VARIANTS } from './ab.js';

export const DEP_NAMES = { '01': 'Amazonas', '02': 'Áncash', '03': 'Apurímac', '04': 'Arequipa', '05': 'Ayacucho', '06': 'Cajamarca', '07': 'Callao', '08': 'Cusco', '09': 'Huancavelica', 10: 'Huánuco', 11: 'Ica', 12: 'Junín', 13: 'La Libertad', 14: 'Lambayeque', 15: 'Lima', 16: 'Loreto', 17: 'Madre de Dios', 18: 'Moquegua', 19: 'Pasco', 20: 'Piura', 21: 'Puno', 22: 'San Martín', 23: 'Tacna', 24: 'Tumbes', 25: 'Ucayali' };

const H = 36e5;
// Fases (calculadas con la vigencia de cada aviso) y su agrupación en los filtros.
const PHASE = {
  vigente: ['Vigente', 0], 'en-curso': ['En curso', 0], proxima: ['Próximo', 1],
  reciente: ['Reciente', 2], ocurrido: ['Reporte de daños', 2], vencida: ['Vencido', 3],
};
export const FASES = [['', 'Todas'], ['ahora', 'Vigentes ahora'], ['proxima', 'Próximas'], ['pasado', 'Reportes y pasadas']];
const FASE_OF = { vigente: 'ahora', 'en-curso': 'ahora', proxima: 'proxima', reciente: 'pasado', ocurrido: 'pasado', vencida: 'pasado' };
export const NIVELES = [['', 'Todos'], ['3', 'Rojo'], ['2', 'Naranja'], ['1', 'Amarillo'], ['sin', 'Sin nivel']];
export const EDADES = [['', '7 días'], ['72', '72 h'], ['24', '24 h'], ['6', '6 h']];
const RANK_NAME = { 1: 'amarillo', 2: 'naranja', 3: 'rojo' };
const ACTIVE = new Set(['vigente', 'en-curso', 'proxima']);

// ---------------------------------------------------------------------------
// Modelo
// ---------------------------------------------------------------------------
export function phaseOf(it, now = Date.now()) {
  const t = Date.parse(it.date);
  if (it.kind === 'pronostico') {
    if (it.valid?.from && it.valid?.until) {
      const a = Date.parse(it.valid.from), b = Date.parse(it.valid.until);
      return now < a ? 'proxima' : now <= b ? 'vigente' : 'vencida';
    }
    return now - t <= 24 * H ? 'vigente' : 'vencida';
  }
  if (it.kind === 'en-curso' || it.kind === 'deteccion') return now - t <= (it.currentHours || 24) * H ? 'en-curso' : 'reciente';
  if (it.kind === 'reporte') return 'ocurrido';
  return now - t <= 24 * H ? 'en-curso' : 'reciente'; // publicación anterior al mapa: sin vigencia conocida
}

/** Lugar aproximado (confianza < 0,8 y sin revisar): la misma regla que las etiquetas «≈» de las noticias. */
const isApprox = (p) => p.confidence !== undefined && p.confidence !== null && p.confidence < 0.8 && p.method !== 'correccion';
const rankOf = (a) => (a.sev && a.sev.rank > 0 ? a.sev.rank : 0);

function toAlert(it, now) {
  const places = (it.geo?.places || []).filter((p) => p.code && DEP_NAMES[p.code.slice(0, 2)]);
  const deps = [...new Set(places.map((p) => p.code.slice(0, 2)))];
  return {
    id: it.id, it, title: it.title, inst: it.institution, url: it.url, date: it.date, sev: it.severity || null,
    kind: it.kind || null, valid: it.valid || null, occurred: it.occurred || null, phase: phaseOf(it, now), places, deps,
    hazards: it.hazards || [],
  };
}

/** Prioridad para ordenar: primero lo vigente, luego lo próximo; dentro, el nivel más alto y lo más nuevo. */
const prio = (a) => PHASE[a.phase][1] * 10 - rankOf(a) * 2 - (Date.parse(a.date) / 1e13);
const byPrio = (x, y) => prio(x) - prio(y);

export function prepare(feed, now = Date.now()) {
  const g = (feed?.groups || []).find((x) => x.id === 'alertas');
  const alerts = (g?.items || []).map((it) => toAlert(it, now)).sort(byPrio);
  const src = g?.sources || [];
  return { alerts, now, generatedAt: feed?.generatedAt, sources: { ok: src.filter((s) => s.ok).length, total: src.length },
    hasLevels: alerts.some((a) => a.kind) };
}

export function readFilter(p) {
  return {
    dep: DEP_NAMES[p.dep] ? p.dep : '',
    fase: FASES.some(([k]) => k === p.fase) ? p.fase : '',
    nivel: NIVELES.some(([k]) => k === p.nivel) ? p.nivel : '',
    edad: EDADES.some(([k]) => k === p.edad) ? p.edad : '',
  };
}

export function matches(a, f, { ignore = [] } = {}) {
  if (f.dep && !ignore.includes('dep') && !a.deps.includes(f.dep)) return false;
  if (f.fase && !ignore.includes('fase') && FASE_OF[a.phase] !== f.fase) return false;
  if (f.nivel && !ignore.includes('nivel') && (f.nivel === 'sin' ? rankOf(a) !== 0 : String(rankOf(a)) !== f.nivel)) return false;
  if (f.edad && !ignore.includes('edad') && Date.now() - Date.parse(a.date) > Number(f.edad) * H) return false;
  return true;
}

export const isFiltered = (f) => Boolean(f.dep || f.fase || f.nivel || f.edad);

/** Las alertas de feed.json que pasan el filtro del mapa (para la lista de abajo). */
export function filterItems(items, f, now = Date.now()) {
  if (!isFiltered(f)) return items;
  return items.filter((it) => matches(toAlert(it, now), f));
}

function aggregate(alerts) {
  const by = {};
  for (const a of alerts) for (const d of a.deps) (by[d] ||= []).push(a);
  return by;
}

/** Cómo se pinta un departamento: el nivel más alto de lo vigente o próximo; rayado si solo es próximo. */
function depState(list = []) {
  const act = list.filter((a) => ACTIVE.has(a.phase));
  const rated = act.filter((a) => rankOf(a));
  if (rated.length) {
    const r = Math.max(...rated.map(rankOf));
    return { cls: `r${r}`, rank: r, soon: !rated.some((a) => rankOf(a) === r && a.phase !== 'proxima') };
  }
  if (act.length) return { cls: 'un', rank: 0, soon: act.every((a) => a.phase === 'proxima') };
  if (list.length) return { cls: 'rep', rank: -1, soon: false };
  return { cls: 'base', rank: -2, soon: false };
}

// ---------------------------------------------------------------------------
// Textos
// ---------------------------------------------------------------------------
const fmtWhen = new Intl.DateTimeFormat('es-PE', { timeZone: 'America/Lima', weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
const fmtDay = new Intl.DateTimeFormat('es-PE', { timeZone: 'America/Lima', weekday: 'short', day: 'numeric' });
const when = (iso) => (iso ? fmtWhen.format(new Date(iso)).replace(/\.,? /g, ' ').replace(',', '') : '');

export function ago(iso, now = Date.now()) {
  const h = (now - Date.parse(iso)) / H;
  if (!Number.isFinite(h)) return '';
  if (h < 1) return 'hace menos de 1 h';
  if (h < 36) return `hace ${Math.round(h)} h`;
  return `hace ${Math.round(h / 24)} días`;
}

function phaseText(a) {
  if (a.phase === 'proxima') return `desde ${when(a.valid.from)}`;
  if (a.phase === 'vigente' && a.valid?.until) return `vigente hasta ${when(a.valid.until)}`;
  if (a.phase === 'vencida' && a.valid?.until) return `venció ${when(a.valid.until)}`;
  if (a.phase === 'ocurrido') return a.occurred ? `ocurrió ${when(a.occurred)}` : `reportado ${ago(a.date)}`;
  return `${PHASE[a.phase][0].toLowerCase()} · ${ago(a.date)}`;
}

/** Etiqueta del nivel de la institución, o «sin nivel» (nunca uno inventado). */
function levelChip(a, { small = false } = {}) {
  const r = rankOf(a);
  if (!a.sev) return html`<span class="lvl lvl-un${small ? ' lvl-s' : ''}" title="La fuente no asigna nivel a este aviso">Sin nivel</span>`;
  return html`<span class="lvl lvl-r${r}${small ? ' lvl-s' : ''}" title="${a.sev.scaleLabel}">${r === 3 ? raw(ICON.octagon) : r ? raw(ICON.triangle) : ''}${a.sev.label}</span>`;
}

/** Etiquetas de nivel y vigencia para cada aviso de la lista de noticias. */
export function itemBadges(it, now = Date.now()) {
  if (!it.kind) return '';
  const a = toAlert(it, now);
  return html`${levelChip(a, { small: true })} <span class="tag tag-phase ph-${a.phase}">${PHASE[a.phase][0]}</span> <span class="muted small">${phaseText(a)}</span>`;
}

function summary(m, alerts) {
  const now = alerts.filter((a) => a.phase === 'vigente' || a.phase === 'en-curso');
  const soon = alerts.filter((a) => a.phase === 'proxima');
  const rep = alerts.filter((a) => a.phase === 'ocurrido');
  const top = [...now, ...soon].filter(rankOf).sort(byPrio)[0];
  const parts = [];
  if (!alerts.length) return 'No hay avisos ni reportes con este filtro.';
  parts.push(html`<strong>${now.length}</strong> ${now.length === 1 ? 'aviso vigente o situación en curso' : 'avisos vigentes o situaciones en curso'}`);
  parts.push(html`<strong>${soon.length}</strong> ${soon.length === 1 ? 'próximo' : 'próximos'}`);
  parts.push(html`<strong>${rep.length}</strong> ${rep.length === 1 ? 'reporte de daños' : 'reportes de daños'}`);
  const topTxt = top ? html` El nivel más alto ${top.phase === 'proxima' ? 'que se espera' : 'ahora'}: ${levelChip(top, { small: true })} de ${top.inst}${top.deps.length ? ` en ${top.deps.slice(0, 3).map((d) => DEP_NAMES[d]).join(', ')}${top.deps.length > 3 ? ` y ${top.deps.length - 3} más` : ''}` : ''}.` : '';
  return html`${parts[0]}, ${parts[1]} y ${parts[2]}.${topTxt}`;
}

function depLabel(code, list) {
  const st = depState(list);
  const n = (ph) => list.filter((a) => ph.includes(a.phase)).length;
  const lvl = st.rank > 0 ? `nivel ${RANK_NAME[st.rank]}${st.soon ? ' próximo' : ''}` : st.rank === 0 ? 'avisos sin nivel' : list.length ? 'solo reportes' : 'sin avisos';
  return `${DEP_NAMES[code]}: ${lvl}. ${n(['vigente', 'en-curso'])} vigentes, ${n(['proxima'])} próximos, ${n(['ocurrido', 'reciente', 'vencida'])} reportes o pasados.`;
}

function tipHtml(title, list, { foot = 'Clic o Enter: ver sus avisos y noticias abajo' } = {}) {
  const items = [...list].sort(byPrio);
  const n = (ph) => items.filter((a) => ph.includes(a.phase)).length;
  const approx = (a) => !a.it.geo?.reviewed && a.places.some(isApprox);
  return html`${title ? html`<div class="amap-tip-h"><strong>${title}</strong></div>` : ''}
    <div class="amap-tip-n"><span><b>${n(['vigente', 'en-curso'])}</b> vigentes</span><span><b>${n(['proxima'])}</b> próximos</span><span><b>${n(['ocurrido', 'reciente', 'vencida'])}</b> reportes y pasados</span></div>
    ${items.length ? html`<ul>${items.slice(0, 3).map((a) => html`<li>${levelChip(a, { small: true })} <span class="amap-tip-t">${shortTitle(a.title, 110)}</span>
      <span class="muted">${a.inst} · ${phaseText(a)}${approx(a) ? ' · ≈ lugar aproximado' : a.it.geo?.reviewed ? ' · lugar revisado' : ''}</span></li>`)}</ul>${items.length > 3 ? html`<p class="muted">y ${items.length - 3} más</p>` : ''}` : html`<p class="muted">Sin avisos ni reportes con este filtro.</p>`}
    <p class="amap-tip-f">${foot}</p>`;
}

// ---------------------------------------------------------------------------
// Geometría
// ---------------------------------------------------------------------------
let GEO = null;
async function geometry() {
  if (!GEO) {
    GEO = fetch('assets/peru-map.json').then((r) => (r.ok ? r.json() : null)).catch(() => null);
  }
  return GEO;
}

const DEFS = html`<defs>${[1, 2, 3].map((r) => html`<pattern id="amap-soon-r${r}" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="7" height="7" class="pt-bg"/><rect width="3.2" height="7" class="pt-r${r}"/></pattern>`)}
  <pattern id="amap-soon-un" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="7" height="7" class="pt-bg"/><rect width="3.2" height="7" class="pt-un"/></pattern></defs>`;

function depShapes(geo, by, f, { badges = false } = {}) {
  const shapes = geo.departments.map((d) => {
    const list = by[d.code] || [];
    const st = depState(list);
    const fill = st.soon && (st.rank > 0 || st.rank === 0) ? `url(#amap-soon-${st.rank > 0 ? `r${st.rank}` : 'un'})` : '';
    const cls = `dep d-${st.cls}${f.dep === d.code ? ' sel' : ''}${f.dep && f.dep !== d.code ? ' dim' : ''}`;
    return html`<path class="${cls}" d="${d.d}" data-dep="${d.code}" ${raw(fill ? `style="fill:${fill}"` : '')} tabindex="0" role="button" aria-pressed="${String(f.dep === d.code)}" aria-label="${depLabel(d.code, list)}"></path>`;
  });
  // El Callao es diminuto a esta escala: un círculo encima lo hace visible y fácil de tocar.
  const cal = geo.departments.find((d) => d.code === '07');
  const calSt = depState(by['07'] || []);
  const callao = cal ? html`<circle class="dep dep-dot d-${calSt.cls}${f.dep === '07' ? ' sel' : ''}${f.dep && f.dep !== '07' ? ' dim' : ''}" cx="${cal.label[0] - 4}" cy="${cal.label[1]}" r="6" data-dep="07" aria-hidden="true"></circle>` : '';
  const counts = badges ? geo.departments.map((d) => {
    const n = (by[d.code] || []).filter((a) => ACTIVE.has(a.phase)).length;
    if (!n) return '';
    const [x, y] = d.code === '07' ? [d.label[0] - 16, d.label[1] - 10] : d.label;
    return html`<g class="badge${f.dep && f.dep !== d.code ? ' dim' : ''}" transform="translate(${x} ${y})" aria-hidden="true"><circle r="${n > 9 ? 10 : 8.5}"></circle><text dy="3.6">${n}</text></g>`;
  }) : '';
  return html`${shapes}${callao}${counts}`;
}

function pings(geo, alerts, f) {
  const at = {};
  for (const a of alerts) {
    for (const p of a.places) {
      const dep = geo.departments.find((d) => d.code === p.code.slice(0, 2));
      const xy = p.code.length > 2 ? geo.points[p.code] : dep?.label;
      if (!xy) continue;
      const k = p.code;
      const spot = (at[k] ||= { code: k, xy, name: p.level === 'departamento' ? p.name : `${p.name} (${DEP_NAMES[p.code.slice(0, 2)]})`, dep: p.code.slice(0, 2), alerts: [], approx: true });
      spot.alerts.push(a);
      if (!isApprox(p) || a.it.geo?.reviewed) spot.approx = false;
    }
  }
  const spots = Object.values(at).sort((x, y) => y.alerts.length - x.alerts.length);
  return html`${spots.map((s) => {
    const act = s.alerts.filter((a) => ACTIVE.has(a.phase));
    const r = Math.max(0, ...act.map(rankOf));
    const cls = act.length ? (r ? `r${r}` : 'un') : 'rep';
    const soon = act.length && act.every((a) => a.phase === 'proxima');
    const live = act.some((a) => rankOf(a) === 3 && a.phase !== 'proxima');
    const rad = Math.min(15, 3.5 + 2.6 * Math.sqrt(s.alerts.length));
    const dim = f.dep && f.dep !== s.dep ? ' dim' : '';
    return html`<g class="ping p-${cls}${soon ? ' soon' : ''}${s.approx ? ' approx' : ''}${dim}" transform="translate(${s.xy[0]} ${s.xy[1]})" data-dep="${s.dep}" data-spot="${s.code}" tabindex="0" role="button" aria-label="${s.approx ? '≈ ' : ''}${s.name}${s.approx ? ' (lugar aproximado)' : ''}: ${act.length} avisos vigentes o próximos, ${s.alerts.length - act.length} reportes o pasados">
      ${live ? html`<circle class="pulse" r="${rad}"></circle>` : ''}<circle class="dot" r="${rad}"></circle></g>`;
  })}`;
}

// ---------------------------------------------------------------------------
// Vistas de cada versión
// ---------------------------------------------------------------------------
function svgMap(geo, inner, label) {
  return html`<svg class="amap-svg" viewBox="0 0 ${geo.width} ${geo.height}" role="group" aria-label="${label}" preserveAspectRatio="xMidYMid meet">${DEFS}${inner}</svg>`;
}

const LEGEND_NOTE = {
  A: 'Color: el nivel más alto de un aviso vigente o próximo en algún lugar del departamento, en la escala de la institución que lo emitió (rojo es el más alto). El número: cuántos avisos vigentes o próximos tiene.',
  B: 'Cada círculo es un lugar con avisos (distrito, provincia o departamento, según lo que dice la fuente); el tamaño es la cantidad. El anillo que late: un aviso rojo vigente ahora.',
  C: 'Color del mapa: el nivel más alto vigente o próximo en el departamento. Toque una celda de la matriz para filtrar por nivel y momento.',
  D: 'Barra: la vigencia que declara la institución. Barra que se desvanece: un estado actual sin fecha de fin (un río, un volcán). La línea vertical marca este momento.',
};
function legend(kind) {
  const sw = (cls, txt) => html`<li><span class="sw sw-${cls}"></span>${txt}</li>`;
  const extra = kind === 'B' ? html`<li><span class="sw sw-soon"></span>Punteado: próximo</li><li><span class="sw sw-approx"></span>Más claro: ≈ lugar aproximado</li>`
    : kind === 'D' ? html`<li><span class="sw sw-fade"></span>Estado actual</li>`
      : html`<li><span class="sw sw-r2 sw-striped"></span>Rayado: próximo</li>${kind === 'A' ? html`<li><span class="sw sw-badge">3</span>Avisos activos</li>` : ''}`;
  return html`<div class="amap-legend-box"><ul class="amap-legend">${sw('r3', 'Rojo')}${sw('r2', 'Naranja')}${sw('r1', 'Amarillo')}${sw('un', 'Sin nivel en la fuente')}${sw('rep', 'Solo reportes o pasados')}${extra}</ul>
    <p class="muted small">${LEGEND_NOTE[kind]}</p></div>`;
}

function matrix(alerts, f) {
  const rows = [['3', 'Rojo'], ['2', 'Naranja'], ['1', 'Amarillo'], ['sin', 'Sin nivel']];
  const cols = FASES.slice(1);
  const base = alerts.filter((a) => matches(a, f, { ignore: ['fase', 'nivel'] }));
  const cnt = (r, c) => base.filter((a) => matches(a, { fase: c, nivel: r })).length;
  return html`<div class="amap-matrix-wrap"><table class="amap-matrix"><caption>Avisos por nivel y momento</caption>
    <thead><tr><th scope="col"><span class="visually-hidden">Nivel</span></th>${cols.map(([, l]) => html`<th scope="col">${l}</th>`)}</tr></thead>
    <tbody>${rows.map(([r, l]) => html`<tr><th scope="row"><span class="sw sw-${r === 'sin' ? 'un' : `r${r}`}"></span>${l}</th>${cols.map(([c, cl]) => {
      const n = cnt(r, c);
      const on = f.fase === c && f.nivel === r;
      return html`<td><button type="button" class="cell c-${r === 'sin' ? 'un' : `r${r}`}${on ? ' on' : ''}" data-fase="${c}" data-nivel="${r}" aria-pressed="${String(on)}" style="--a:${n ? (r === 'sin' ? 0.45 : r === '1' ? 0.75 : 0.9) : 0}" aria-label="${l}, ${cl.toLowerCase()}: ${n}" ${raw(n ? '' : 'disabled')}>${n}</button></td>`;
    })}</tr>`)}</tbody></table></div>`;
}

function depRanking(alerts, f, limit = 10) {
  const by = aggregate(alerts.filter((a) => matches(a, f, { ignore: ['dep'] })));
  const rows = Object.entries(by).map(([d, list]) => ({ d, list, st: depState(list), act: list.filter((a) => ACTIVE.has(a.phase)) }))
    .sort((x, y) => y.st.rank - x.st.rank || y.act.length - x.act.length || y.list.length - x.list.length).slice(0, limit);
  const max = Math.max(1, ...rows.map((r) => r.list.length));
  if (!rows.length) return html`<p class="muted small">Ningún departamento con este filtro.</p>`;
  return html`<ol class="amap-rank">${rows.map(({ d, list, st }) => {
    const seg = (cls, n) => (n ? html`<span class="seg-${cls}" style="width:${(100 * n) / max}%"></span>` : '');
    const by3 = (r) => list.filter((a) => ACTIVE.has(a.phase) && rankOf(a) === r).length;
    return html`<li><button type="button" class="rank-row${f.dep === d ? ' on' : ''}" data-dep="${d}" aria-pressed="${String(f.dep === d)}" aria-label="${depLabel(d, list)}">
      <span class="rank-name">${DEP_NAMES[d]}</span><span class="rank-bar">${seg('r3', by3(3))}${seg('r2', by3(2))}${seg('r1', by3(1))}${seg('un', by3(0))}${seg('rep', list.filter((a) => !ACTIVE.has(a.phase)).length)}</span><span class="rank-n">${list.length}</span></button></li>`;
  })}</ol>`;
}

function timeline(alerts, f, now) {
  const t0 = now - 24 * H, t1 = now + 96 * H;
  const pos = (t) => Math.max(0, Math.min(100, ((t - t0) / (t1 - t0)) * 100));
  const rows = alerts.filter((a) => matches(a, f) && (ACTIVE.has(a.phase) || a.phase === 'vencida'))
    .map((a) => {
      const a0 = a.valid?.from ? Date.parse(a.valid.from) : Date.parse(a.date);
      const a1 = a.valid?.until ? Date.parse(a.valid.until) : Date.parse(a.date) + (a.it.currentHours || 24) * H;
      return { a, a0, a1 };
    })
    .filter((r) => r.a1 >= t0 && r.a0 <= t1)
    .sort((x, y) => x.a0 - y.a0 || rankOf(y.a) - rankOf(x.a));
  const days = [];
  for (let d = new Date(t0); d.getTime() <= t1; d = new Date(d.getTime() + 24 * H)) {
    const mid = new Date(new Date(d).setUTCHours(5, 0, 0, 0)); // medianoche en Lima (UTC−5)
    if (mid.getTime() >= t0 && mid.getTime() <= t1) days.push(mid.getTime());
  }
  const shown = rows.slice(0, 14);
  return html`<div class="amap-tl" role="group" aria-label="Avisos entre ayer y los próximos cuatro días">
    <div class="tl-axis" aria-hidden="true">${days.map((d) => html`<span style="left:${pos(d)}%">${fmtDay.format(new Date(d + 12 * H))}</span>`)}<span class="tl-now" style="left:${pos(now)}%">ahora</span></div>
    <ol class="tl-rows">${shown.length ? shown.map(({ a, a0, a1 }) => html`<li><button type="button" title="${a.title}" class="tl-row${f.dep && a.deps.includes(f.dep) ? ' on' : ''}" data-dep="${a.deps[0] || ''}" data-id="${a.id}" aria-label="${a.title}. ${a.inst}. ${phaseText(a)}">
      <span class="tl-lbl">${a.deps.length ? a.deps.slice(0, 2).map((d) => DEP_NAMES[d]).join(', ') + (a.deps.length > 2 ? ` +${a.deps.length - 2}` : '') : 'Sin departamento'}<small>${a.inst}</small></span>
      <span class="tl-track"><span class="tl-bar b-${rankOf(a) ? `r${rankOf(a)}` : 'un'}${a.phase === 'vencida' ? ' past' : ''}${a.kind !== 'pronostico' && !a.valid ? ' state' : ''}" style="left:${pos(a0)}%;width:${Math.max(1.2, pos(a1) - pos(a0))}%"></span><span class="tl-nowline" style="left:${pos(now)}%"></span></span></button></li>`)
      : html`<li class="muted small">Ningún aviso con vigencia entre ayer y los próximos cuatro días con este filtro.</li>`}</ol>
    ${rows.length > shown.length ? html`<p class="muted small">y ${rows.length - shown.length} avisos más; use los filtros para verlos.</p>` : ''}</div>`;
}

function filtersHtml(f, alerts) {
  const n = (k, v) => alerts.filter((a) => matches(a, { ...f, [k]: v }, {})).length;
  const group = (k, label, opts) => html`<div class="amap-fg" role="group" aria-label="${label}"><span class="amap-fl">${label}</span>${opts.map(([v, l]) => html`<button type="button" class="kind-chip" data-f="${k}" data-v="${v}" aria-pressed="${String(f[k] === v)}">${l} <span class="muted">${n(k, v)}</span></button>`)}</div>`;
  return html`<div class="amap-filters">
    ${group('fase', 'Momento', FASES)}
    ${group('nivel', 'Nivel', NIVELES)}
    ${group('edad', 'Antigüedad', EDADES)}
    ${f.dep ? html`<button type="button" class="kind-chip dep-on" data-f="dep" data-v="" aria-label="Quitar el filtro de ${DEP_NAMES[f.dep]}">${raw(ICON.pin)}${DEP_NAMES[f.dep]} ${raw(ICON.close)}</button>` : ''}
    ${isFiltered(f) ? html`<button type="button" class="linkish" data-clear>Quitar filtros</button>` : ''}
  </div>`;
}

function national(alerts, f) {
  const list = alerts.filter((a) => !a.deps.length && ACTIVE.has(a.phase) && matches(a, f, { ignore: ['dep'] }));
  if (!list.length) return '';
  const inst = [...new Set(list.map((a) => a.inst))].join(', ');
  return html`<details class="amap-nat"><summary><strong>${list.length}</strong> ${list.length === 1 ? 'aviso vigente o próximo' : 'avisos vigentes o próximos'} sin departamento en su fuente <span class="muted">(${inst}): no aparecen en el mapa</span></summary>
    <ul>${list.slice(0, 8).map((a) => html`<li>${levelChip(a, { small: true })} <a href="${safeUrl(a.url)}" rel="noopener" target="_blank" data-detail>${shortTitle(a.title)}</a> <span class="muted small">${phaseText(a)}</span></li>`)}</ul></details>`;
}

/** Titulares en mayúsculas (boletines del COEN) en tipo oración, y recortados. */
export function shortTitle(t, max = 120) {
  let s = t.replace(/^Aviso del SENAMHI: /, 'SENAMHI: ');
  const letters = s.replace(/[^A-Za-zÁÉÍÓÚÑáéíóúñ]/g, '');
  if (letters && letters.replace(/[^A-ZÁÉÍÓÚÑ]/g, '').length / letters.length > 0.7) {
    s = s.toLowerCase().replace(/^./, (c) => c.toUpperCase()).replace(/\b(indeci|coen|senamhi|igp|dhn)\b/g, (w) => w.toUpperCase()).replace(/n° (\d)/g, 'N° $1');
  }
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

function depList(geo, by) {
  const rows = geo.departments.map((d) => ({ d, list: by[d.code] || [] })).filter((r) => r.list.length);
  return html`<details class="amap-a11y"><summary>Ver el mapa como lista</summary><ul>${rows.map(({ d, list }) => html`<li><button type="button" class="linkish" data-dep="${d.code}">${depLabel(d.code, list)}</button></li>`)}</ul></details>`;
}

// ---------------------------------------------------------------------------
// Montaje
// ---------------------------------------------------------------------------
export async function mountAlertMap(el, { feed, getFilter, onFilter }) {
  if (!el) return null;
  const geo = await geometry();
  const session = ab();
  let model = prepare(feed);
  if (!geo || !model.alerts.length && !model.sources.total) {
    el.innerHTML = '';
    return null;
  }
  const tick = setInterval(() => { model = prepare(feed); draw(); }, 5 * 60 * 1000);  // las fases avanzan con el reloj
  const draw = () => {
    if (!el.isConnected) { clearInterval(tick); return; }
    const f = readFilter(getFilter());
    const v = session.variant;
    const vis = model.alerts.filter((a) => matches(a, f, { ignore: ['dep'] }));
    const by = aggregate(vis);
    const sel = f.dep ? (by[f.dep] || []) : null;
    const label = 'Mapa del Perú por departamento con los avisos oficiales';
    let body;
    if (v === 'B') {
      body = html`<div class="amap-grid"><div class="amap-mapbox">${svgMap(geo, html`<g class="outline">${depShapes(geo, {}, f)}</g>${pings(geo, vis, f)}`, label)}<div class="amap-tip" role="tooltip" hidden></div></div>
        <div class="amap-side">${legend('B')}${depRanking(model.alerts, f, 6)}</div></div>`;
    } else if (v === 'C') {
      body = html`<div class="amap-grid amap-grid-c"><div class="amap-mapbox">${svgMap(geo, depShapes(geo, by, f), label)}<div class="amap-tip" role="tooltip" hidden></div></div>
        <div class="amap-side">${matrix(model.alerts, f)}<h3 class="amap-h3">Departamentos con más avisos</h3>${depRanking(model.alerts, f)}${legend('C')}</div></div>`;
    } else if (v === 'D') {
      body = html`<div class="amap-grid amap-grid-d"><div class="amap-mapbox">${svgMap(geo, depShapes(geo, by, f), label)}<div class="amap-tip" role="tooltip" hidden></div></div>
        <div class="amap-side"><h3 class="amap-h3">Vigencia de los avisos: ayer, hoy y los próximos días</h3>${timeline(model.alerts, f, Date.now())}${legend('D')}</div></div>`;
    } else {
      body = html`<div class="amap-grid amap-grid-a"><div class="amap-mapbox">${svgMap(geo, depShapes(geo, by, f, { badges: true }), label)}<div class="amap-tip" role="tooltip" hidden></div></div>
        <div class="amap-side">${legend('A')}${sel ? html`<div class="amap-sel"><h3 class="amap-h3">${DEP_NAMES[f.dep]}</h3>${tipHtml('', sel, { foot: 'Sus avisos y noticias están en la lista de abajo.' })}</div>` : html`<p class="muted small">Pase el cursor o toque un departamento para ver sus avisos; haga clic para filtrar las noticias.</p>`}</div></div>`;
    }
    const pubAge = model.generatedAt ? (Date.now() - Date.parse(model.generatedAt)) / H : 0;
    // Al redibujar, el foco vuelve al mismo control (un departamento, un filtro) para el teclado.
    const act = el.contains(document.activeElement) ? document.activeElement : null;
    const refocus = act && (act.dataset.dep && !act.dataset.f ? `[data-dep="${act.dataset.dep}"]${act.classList.contains('dep') ? '.dep' : act.dataset.spot ? `[data-spot="${act.dataset.spot}"]` : `.${act.classList[0]}`}`
      : act.dataset.f ? `[data-f="${act.dataset.f}"][data-v="${act.dataset.v}"]` : act.id ? `#${act.id}` : act.dataset.fase ? `.cell[data-fase="${act.dataset.fase}"][data-nivel="${act.dataset.nivel}"]` : '');
    el.innerHTML = String(html`<section class="card amap amap-v${v}" aria-labelledby="amap-h" data-tour-id="alert-map">
      <div class="amap-head"><div><h2 id="amap-h">Mapa de alertas y avisos oficiales</h2>
        <p class="amap-sum" aria-live="polite">${summary(model, vis.filter((a) => !f.dep || a.deps.includes(f.dep)))}</p></div>
        <label class="amap-ver"><span>Versión del mapa</span><select id="amap-ver">${VARIANTS.map(([k, l]) => html`<option value="${k}" ${k === v ? 'selected' : ''}>Versión ${k}: ${l}</option>`)}</select></label></div>
      ${model.sources.total && !model.sources.ok ? html`<p class="notice notice-alert">${raw(ICON.octagon)}<span>Ninguna fuente de alertas respondió en la última actualización: el mapa muestra los últimos avisos conocidos y puede faltar lo más reciente. Consulte directamente al SENAMHI y al INDECI.</span></p>` : ''}
      ${!model.hasLevels && model.alerts.length ? html`<p class="notice notice-info">${raw(ICON.info)}<span>Esta publicación es anterior al mapa: los niveles y la vigencia de cada aviso aparecerán con la próxima actualización diaria.</span></p>` : ''}
      ${body}
      ${filtersHtml(f, model.alerts)}
      ${national(model.alerts, f)}
      ${depList(geo, by)}
      <p class="amap-foot muted small">El nivel y la vigencia son los que publica cada institución (SENAMHI, INDECI, IGP, DHN, USGS); el observatorio no asigna niveles. ${model.sources.total ? `${model.sources.ok} de ${model.sources.total} fuentes de alertas respondieron en la actualización ${model.generatedAt ? `del ${when(model.generatedAt)}` : ''}.` : ''} ${pubAge > 30 ? html`<strong>Esa actualización tiene ${Math.round(pubAge / 24)} días: pueden faltar avisos recientes.</strong>` : 'Los avisos emitidos después llegan con la siguiente actualización.'} Sin avisos no quiere decir sin peligro: ante una emergencia, siga a INDECI, al SENAMHI y a su gobierno local. Límites: IGN, vía OCHA HDX (CC BY-IGO).</p>
    </section>`);
    wire(el, f, by);
    if (refocus) (el.querySelector(refocus) || $('#amap-h', el))?.focus?.({ preventScroll: true });
    session.mark('view');
  };

  const setF = (partial) => { session.mark('select'); onFilter(partial); };

  function wire(root, f, by) {
      const tip = $('.amap-tip', root);
    let hovered = false;
    const showTip = (target, x, y) => {
      if (!tip) return;
      const spot = target.closest('[data-spot]');
      const dep = target.closest('[data-dep]')?.dataset.dep;
      if (!dep) return;
      let title, list;
      if (spot) {
        const code = spot.dataset.spot;
        list = model.alerts.filter((a) => matches(a, f, { ignore: ['dep'] }) && a.places.some((p) => p.code === code));
        const p = list[0]?.places.find((q) => q.code === code);
        title = p ? (p.level === 'departamento' ? p.name : `${p.name} (${DEP_NAMES[dep]})`) : DEP_NAMES[dep];
      } else {
        title = DEP_NAMES[dep];
        list = by[dep] || [];
      }
      tip.innerHTML = String(tipHtml(title, list));
      tip.hidden = false;
      // Posición fija en la ventana, a un lado del cursor, para no tapar el mapa ni salirse de la pantalla.
      const tw = tip.offsetWidth, th = tip.offsetHeight, vw = innerWidth, vh = innerHeight;
      let left = x + 18, top = Math.max(8, Math.min(vh - th - 8, y - th / 2));
      if (left + tw > vw - 8) left = x - tw - 18;
      if (left < 8) {  // pantalla angosta: encima o debajo del punto
        left = Math.max(8, Math.min(vw - tw - 8, x - tw / 2));
        top = y + 24 + th < vh ? y + 24 : Math.max(8, y - th - 24);
      }
      tip.style.left = `${left}px`;
      tip.style.top = `${top}px`;
      if (!hovered) { hovered = true; session.mark('hover'); }
    };
    const hideTip = () => { if (tip) tip.hidden = true; };
    const svg = $('.amap-svg', root);
    if (svg) {
      svg.addEventListener('pointermove', (e) => { if (e.pointerType !== 'touch') showTip(e.target, e.clientX, e.clientY); });
      svg.addEventListener('pointerleave', hideTip);
      svg.addEventListener('click', (e) => {
        const t = e.target.closest('[data-dep]');
        if (!t) return;
        const dep = t.dataset.dep;
        hideTip();
        setF({ dep: f.dep === dep ? '' : dep });
      });
      svg.addEventListener('focusin', (e) => {
        const t = e.target.closest('[data-dep]');
        if (!t) return;
        const r = t.getBoundingClientRect();
        showTip(t, r.left + r.width / 2, r.top + r.height / 2);
      });
      svg.addEventListener('focusout', hideTip);
      svg.addEventListener('keydown', (e) => {
        const t = e.target.closest('[data-dep]');
        if (!t || (e.key !== 'Enter' && e.key !== ' ')) return;
        e.preventDefault();
        setF({ dep: f.dep === t.dataset.dep ? '' : t.dataset.dep });
      });
    }
    $$('[data-f]', root).forEach((b) => b.addEventListener('click', () => setF({ [b.dataset.f]: f[b.dataset.f] === b.dataset.v ? '' : b.dataset.v })));
    $('[data-clear]', root)?.addEventListener('click', () => setF({ dep: '', fase: '', nivel: '', edad: '' }));
    $$('.cell', root).forEach((b) => b.addEventListener('click', () => {
      const on = f.fase === b.dataset.fase && f.nivel === b.dataset.nivel;
      setF({ fase: on ? '' : b.dataset.fase, nivel: on ? '' : b.dataset.nivel });
    }));
    $$('.rank-row, .amap-a11y [data-dep]', root).forEach((b) => b.addEventListener('click', () => setF({ dep: f.dep === b.dataset.dep ? '' : b.dataset.dep })));
    $$('.tl-row', root).forEach((b) => b.addEventListener('click', () => {
      if (b.dataset.dep) setF({ dep: f.dep === b.dataset.dep ? '' : b.dataset.dep });
      else { const a = model.alerts.find((x) => x.id === b.dataset.id); if (a?.url) { session.mark('detail'); window.open(safeUrl(a.url), '_blank', 'noopener'); } }
    }));
    $$('[data-detail]', root).forEach((a) => a.addEventListener('click', () => session.mark('detail')));
    $('#amap-ver', root)?.addEventListener('change', (e) => {
      session.choose(e.target.value);
      draw();
      $('#amap-ver', el)?.focus();
    });
  }

  draw();
  return { update: draw, markDetail: () => session.mark('detail') };
}

// ---------------------------------------------------------------------------
// Resultados de las versiones (#/variantes)
// ---------------------------------------------------------------------------
export function statsHtml(s) {
  if (!s) return html`<p>No se pudo leer la analítica. Solo funciona en el sitio publicado en Cloudflare Pages.</p>`;
  if (!s.available) return html`<p>La base de datos no está vinculada en este despliegue (GEO_DB): no hay datos.</p>`;
  const pct = (a, b) => (b ? `${Math.round((100 * a) / b)} %` : '—');
  const rows = VARIANTS.map(([v, name]) => {
    const t = s.totals[v] || {};
    return html`<tr><th scope="row">Versión ${v}<div class="muted small">${name}</div></th>
      <td class="num">${t.view || 0}</td><td class="num">${pct(t.hover || 0, t.view)}</td><td class="num">${pct(t.select || 0, t.view)}</td><td class="num">${pct(t.detail || 0, t.view)}</td>
      <td class="num">${t.choose || 0}</td><td class="num">${t.leave || 0}</td><td class="num">${t.keep || 0}</td><td class="num">${pct(t.chosen || 0, t.view)}</td></tr>`;
  });
  return html`<div class="table-wrap"><table class="grd"><thead><tr><th scope="col">Versión</th><th scope="col">Visitas</th><th scope="col">Pasaron el cursor</th><th scope="col">Filtraron desde el mapa</th><th scope="col">Abrieron un aviso</th><th scope="col">La eligieron</th><th scope="col">La dejaron</th><th scope="col">Volvieron con ella elegida</th><th scope="col">Visitas con ella elegida</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="muted small">Últimos ${s.days} días (desde el ${s.since}). Cada visita cuenta una vez por evento. «Volvieron con ella elegida»: visitas de otro día de personas que eligieron esa versión y la mantienen. Las versiones se asignan al azar en la primera visita; elegir otra en el selector la deja como predeterminada en ese navegador. No se guarda ningún dato personal: solo contadores por día.</p>`;
}
