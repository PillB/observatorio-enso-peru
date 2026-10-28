// Mapa de alertas sobre las noticias: qué departamentos tienen avisos oficiales ahora, cuáles se esperan y
// dónde hubo daños, con el nivel que asignó cada institución.
//
// Todo sale de feed.json (grupo «alertas»), que arma el pipeline: el nivel (severity) es el de la fuente
// (SENAMHI, IGP, USGS, DHN…) y nunca se calcula aquí; un aviso sin nivel en su fuente se pinta «sin nivel».
// Lo único que se calcula en el navegador es si un aviso ya empezó o ya venció, comparando su vigencia
// (valid) con la hora actual. Los lugares son los publicados (confianza ≥ 0,5); los aproximados (< 0,8) se
// marcan con «≈». Las sugerencias de la consola de lugares no llegan a feed.json.
//
// Hay cuatro versiones del mapa (ab.js); comparten los datos, el resumen, los filtros y la lista accesible. Además
// del resumen, dos vistas de detalle (botones en la cabecera del mapa) cruzan los avisos con la memoria de desastres:
// los avisos por cuenca de la ANA y los distritos en aviso con su historia (assets/historico/historia.json).

import { html, raw, esc, safeUrl, $, $$ } from './lib/dom.js';
import { ICON } from './icons.js';
import { ab, abReady, EXPERIMENTS, VARIANTS } from './ab.js';
import { fmtDate, fmtNumber } from './lib/format.js';

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
    if (it.aviso?.cancelled) return 'vencida'; // la tabla del SENAMHI lo marca «(AVISO CANCELADO)»: lo reemplazó otro
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
    // url: el informe (PDF) que ofrece la página de la publicación, si lo hay; es lo que se abre desde el mapa.
    id: it.id, it, title: it.title, inst: it.institution, url: it.document || it.url, date: it.date, sev: it.severity || null,
    kind: it.kind || null, valid: it.valid || null, occurred: it.occurred || null, phase: phaseOf(it, now), places, deps,
    hazards: it.hazards || [], detail: it.detail || null,
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
    hasLevels: alerts.some((a) => a.kind), levels: g?.levelsFrom || null };
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

// La copia de la tabla de avisos del SENAMHI que publica el sitio (data/archive/…): esa página solo
// responde desde el Perú, así que es la que casi todos pueden abrir.
const ARCHIVE_RE = /^archive\/[\w.\/-]+$/;
const archiveHref = (p) => (p && ARCHIVE_RE.test(p) ? `data/${p}` : '');

/** De dónde sale el nivel de un aviso del SENAMHI: el aviso en su sitio y la copia de su tabla de avisos. */
function levelSource(sev) {
  const live = sev?.basisUrl ? html`<a href="${safeUrl(sev.basisUrl)}" rel="noopener" target="_blank" title="El sitio del SENAMHI puede no abrir fuera del Perú">aviso en el SENAMHI</a>` : '';
  const copy = archiveHref(sev?.basisArchive) ? html`<a href="${archiveHref(sev.basisArchive)}" rel="noopener" target="_blank" title="La tabla de avisos del SENAMHI tal como la bajó el observatorio desde el Perú">copia de la tabla</a>` : '';
  return live || copy ? html` <span class="muted small">nivel: ${live}${live && copy ? ' · ' : ''}${copy}</span>` : '';
}

/** Etiquetas de nivel y vigencia para cada aviso de la lista de noticias. */
export function itemBadges(it, now = Date.now()) {
  if (!it.kind) return '';
  const a = toAlert(it, now);
  return html`${levelChip(a, { small: true })} <span class="tag tag-phase ph-${a.phase}">${PHASE[a.phase][0]}</span> <span class="muted small">${phaseText(a)}</span>${levelSource(a.sev)}${placeSource(it)}`;
}

/** Lo que ubica un aviso más fino que su distrito, como etiquetas de la lista: el centro poblado, el río o la
 * quebrada que nombra (dentro de su distrito) y las cuencas de la ANA de sus puntos. */
export function fineTags(it) {
  const pts = it.detail?.points || [];
  const names = [...new Set(pts.filter((p) => p.kind === 'centro-poblado' || p.kind === 'cuerpo-de-agua').map((p) => p.name).filter(Boolean))].slice(0, 3);
  const basins = [...new Set(pts.map((p) => p.basin?.name).filter(Boolean))].slice(0, 2);
  return html`${names.map((n) => html`<span class="tag tag-place tag-fine" title="Lugar que nombra el aviso, dentro de su distrito">${raw(ICON.pin)}${n}</span> `)}${basins.map((b) => html`<span class="tag tag-basin" title="Unidad hidrográfica de la ANA">${b}</span> `)}`;
}

/** El informe completo (el PDF que la página de la publicación ofrece para descargar) y de dónde salen los
 * lugares cuando no los trae el aviso mismo (el boletín del COEN del mismo aviso, o las regiones que nombra). */
function placeSource(it) {
  const doc = it.document ? html` <a class="small" href="${safeUrl(it.document)}" rel="noopener" target="_blank">informe completo (PDF)</a>` : '';
  const via = it.geo?.via;
  const viaDoc = via?.document ? html` (<a href="${safeUrl(via.document)}" rel="noopener" target="_blank">PDF</a>)` : '';
  return html`${doc}${via?.basis ? html` <span class="muted small">lugares: ${via.basis}${viaDoc}</span>` : ''}`;
}

/** Para el pie del mapa: de qué copia de la tabla del SENAMHI salen los niveles, y si es vieja (más de 36 h,
 * el mismo plazo con que el pipeline avisa «senamhi-avisos-stale»). */
export function levelsNote(levels, now = Date.now()) {
  if (!levels?.copyAt) return '';
  const h = (now - Date.parse(levels.copyAt)) / H;
  const copy = archiveHref(levels.archive);
  return html`Los niveles de los avisos del SENAMHI salen de su <a href="${safeUrl(levels.url)}" rel="noopener" target="_blank">tabla de avisos</a>, copiada desde el Perú el ${when(levels.copyAt)}${copy ? html` (<a href="${copy}" rel="noopener" target="_blank">copia</a>)` : ''}.${h > 36 ? html` <strong>Esa copia tiene ${ago(levels.copyAt, now).replace('hace ', '')}: los avisos emitidos después figuran sin nivel.</strong>` : ''} `;
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

function stateText(list) {
  const st = depState(list);
  const n = (ph) => list.filter((a) => ph.includes(a.phase)).length;
  const lvl = st.rank > 0 ? `nivel ${RANK_NAME[st.rank]}${st.soon ? ' próximo' : ''}` : st.rank === 0 ? 'avisos sin nivel' : list.length ? 'solo reportes' : 'sin avisos';
  return `${lvl}. ${n(['vigente', 'en-curso'])} vigentes, ${n(['proxima'])} próximos, ${n(['ocurrido', 'reciente', 'vencida'])} reportes o pasados.`;
}
const depLabel = (code, list) => `${DEP_NAMES[code]}: ${stateText(list)}`;

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

// Anillo del departamento elegido. Va después de todas las formas para que
// ningún borde vecino lo tape; en el Callao rodea también su círculo.
function selRing(geo, code) {
  const d = code && geo.departments.find((x) => x.code === code);
  if (!d) return '';
  const dot = (k) => (code === '07' ? html`<circle class="${k}" cx="${d.label[0] - 4}" cy="${d.label[1]}" r="6"></circle>` : '');
  return html`<g class="sel-ring" aria-hidden="true">${['sel-glow', 'sel-case', 'sel-line'].map((k) => html`<path class="${k}" d="${d.d}"></path>${dot(k)}`)}</g>`;
}

function depShapes(geo, by, f, { badges = false, overlay = '' } = {}) {
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
  return html`${shapes}${callao}${overlay}${selRing(geo, f.dep)}${counts}`;
}

// ---------------------------------------------------------------------------
// Detalle más fino que el departamento: formas, distritos y puntos de cada aviso
// ---------------------------------------------------------------------------
/** Grados → coordenadas del SVG (la proyección de peru-map.json, tools.build_peru_map). */
export function project(geo, lon, lat) {
  const p = geo.lonLat;
  return [(lon - p.lon0) * p.cos * p.k, (p.lat1 - lat) * p.k];
}

const ringPath = (geo, ring) => `M${ring.map(([lon, lat]) => project(geo, lon, lat).map((v) => v.toFixed(1)).join(' ')).join('L')}Z`;
const levelCls = (a) => (rankOf(a) ? `r${rankOf(a)}` : 'un');
const POINT_KIND = { estacion: 'Estación hidrológica', epicentro: 'Epicentro', volcan: 'Volcán', focos: 'Focos de calor', 'centro-poblado': 'Centro poblado', 'cuerpo-de-agua': 'Río, quebrada o laguna' };

/** Texto del cuadro de un punto: qué es, el aviso y, si se sabe, el río, la cuenca y la incertidumbre. */
function pointTip(p, a) {
  const what = p.kind === 'focos' ? `${p.n} foco${p.n > 1 ? 's' : ''} de calor en esta celda de unos 11 km`
    : p.kind === 'epicentro' ? `Epicentro${p.mag !== undefined ? ` · magnitud ${p.mag}` : ''}${p.depthKm !== undefined ? ` · ${p.depthKm} km de profundidad` : ''}`
      : p.name || POINT_KIND[p.kind] || 'Lugar';
  return [what, shortTitle(a.title, 140), [p.river, p.basin?.name, p.radiusKm ? `±${p.radiusKm} km` : ''].filter(Boolean).join(' · ')].filter(Boolean).join('\n');
}

/** Formas de los avisos vigentes o próximos (polígonos del SENAMHI), los distritos con quebradas (de
 * ``districts``: el trazo de cada distrito, assets/historico/mapa.json) y los puntos de todos los avisos visibles.
 * Las formas van del nivel más bajo al más alto, así el rojo queda arriba; un distrito con quebradas en avisos de
 * varios niveles se dibuja una sola vez, con el más alto (y su cuadro dice cuántas trae cada uno). */
export function detailMarkup(geo, alerts, f, { districts = null, unit = 1 } = {}) {
  const dim = (a) => (f.dep && !a.deps.includes(f.dep) ? ' dim' : '');
  const shapes = [], area = {}, points = [];
  for (const a of [...alerts].sort((x, y) => rankOf(x) - rankOf(y))) {
    const d = a.detail;
    if (!d) continue;
    const act = ACTIVE.has(a.phase);
    if (act) {
      for (const sh of d.shapes || []) {
        const dd = (sh.rings || []).filter((r) => r.length >= 4).map((r) => ringPath(geo, r)).join('');
        if (dd) shapes.push(`<path class="amap-shape s-${levelCls(a)}${a.phase === 'proxima' ? ' soon' : ''}${dim(a)}" d="${dd}" data-dep="${esc(a.deps[0] || '')}" data-tip="${esc(`${shortTitle(a.title, 140)}\nZona del aviso`)}"></path>`);
      }
      for (const ar of (districts && d.areas) || []) {
        if (!districts[ar.code]) continue;
        const at = (area[ar.code] ||= { code: ar.code, name: ar.name, kind: ar.kind || 'quebradas', a, dim: dim(a), lines: [] });
        if (rankOf(a) >= rankOf(at.a)) Object.assign(at, { a, dim: at.dim && dim(a) });
        at.lines.push(ar.kind === 'provincia' ? shortTitle(a.title, 140) : `${ar.n} quebrada${ar.n > 1 ? 's' : ''} · ${shortTitle(a.title, 140)}`);
      }
    }
    for (const p of d.points || []) {
      if (typeof p.lat !== 'number' || typeof p.lon !== 'number') continue;
      const [x, y] = project(geo, p.lon, p.lat);
      const cls = `amap-pt k-${esc(p.kind || 'lugar')} s-${act ? levelCls(a) : 'rep'}${dim(a)}`;
      const tip = esc(pointTip(p, a));
      const dep = esc(a.deps[0] || '');
      const r = (p.kind === 'focos' ? 1.3 + Math.min(3, Math.sqrt(p.n || 1) * 0.6) : 3.4) * unit;
      if (p.kind === 'volcan') {
        points.push(`<path class="${cls}" d="M${x.toFixed(1)} ${(y - r * 1.3).toFixed(1)}l${(r * 1.2).toFixed(1)} ${(r * 2.1).toFixed(1)}h${(-r * 2.4).toFixed(1)}z" data-dep="${dep}" data-tip="${tip}"></path>`);
      } else if (p.kind === 'cuerpo-de-agua') {
        // Un tramo de río o quebrada: el círculo de su radio, sin relleno, y el punto del cauce.
        const rr = Math.max(r, ((p.radiusKm || 0) / 111) * geo.lonLat.k);
        points.push(`<g class="${cls}" data-dep="${dep}" data-tip="${tip}"><circle class="amap-reach" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${rr.toFixed(1)}"></circle><circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(r * 0.7).toFixed(1)}"></circle></g>`);
      } else if (p.kind === 'estacion') {
        points.push(`<rect class="${cls}" x="${(x - r).toFixed(1)}" y="${(y - r).toFixed(1)}" width="${(2 * r).toFixed(1)}" height="${(2 * r).toFixed(1)}" transform="rotate(45 ${x.toFixed(1)} ${y.toFixed(1)})" data-dep="${dep}" data-tip="${tip}"></rect>`);
      } else {
        points.push(`<circle class="${cls}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r.toFixed(1)}" data-dep="${dep}" data-tip="${tip}"></circle>`);
      }
    }
  }
  // Las provincias (más grandes) primero, para que los distritos con quebradas queden encima.
  const areas = Object.values(area).sort((x, y) => (x.code.length - y.code.length) || (rankOf(x.a) - rankOf(y.a))).map((at) => {
    const g = districts[at.code];
    const head = at.kind === 'provincia' ? `Provincia de ${at.name || at.code}: expuesta según el aviso de corto plazo`
      : `${at.name ? `${at.name}: ` : ''}quebradas con probable activación`;
    return `<path class="amap-area${at.kind === 'provincia' ? ' amap-prov' : ''} s-${levelCls(at.a)}${at.dim}" d="${g.d}" data-dep="${esc(at.code.slice(0, 2))}" data-tip="${esc([head, ...at.lines.reverse()].join('\n'))}"></path>`;
  });
  if (!shapes.length && !areas.length && !points.length) return '';
  return `<g class="amap-detail" aria-hidden="true">${shapes.join('')}${areas.join('')}${points.join('')}</g>`;
}

/** Las cuencas de la ANA (assets/cuencas-mapa.json), debajo del detalle. */
export function basinsMarkup(B) {
  if (!B?.units) return '';
  return `<g class="amap-basins" aria-hidden="true">${Object.entries(B.units).map(([c, u]) => `<path d="${u.d}" data-tip="${esc(`${u.n}\nUnidad hidrográfica ${c} de la ANA`)}"></path>`).join('')}</g>`;
}

function pings(geo, alerts, f) {
  const at = {};
  for (const a of alerts) {
    for (const p of a.places) {
      const dep = geo.departments.find((d) => d.code === p.code.slice(0, 2));
      // Un código sin punto propio (un distrito más nuevo que el mapa) va al de su provincia o su
      // departamento: el aviso se dibuja igual, nunca se pierde.
      const xy = (p.code.length > 2 && (geo.points[p.code] || geo.points[p.code.slice(0, 4)])) || dep?.label;
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
// Vistas de detalle: los avisos por cuenca y los distritos en aviso con su historia
// ---------------------------------------------------------------------------
export const VISTAS = EXPERIMENTS.noticias.variants;
const VISTA_LABEL = { resumen: 'Resumen', cuencas: 'Por cuenca', distritos: 'Distritos y su historia' };
const VISTA_HINT = { resumen: 'Avisos por departamento (versión A–D)', cuencas: 'Avisos por cuenca de la ANA, con lo que pasó antes en cada una', distritos: 'Distritos en aviso, coloreados por cuántas veces tuvieron daños antes' };

let HISTORY = null;
/** La memoria de cada distrito, provincia y cuenca en una fila (python -m tools.build_historico → history_payload). */
function historyRows() {
  if (!HISTORY) {
    HISTORY = fetch('assets/historico/historia.json').then((r) => (r.ok ? r.json() : null)).then((h) => {
      if (!h) return null;
      const col = Object.fromEntries(h.cols.map((c, i) => [c, i]));
      const wrap = (rows) => new Map(Object.entries(rows).map(([c, v]) => [c, Object.fromEntries(Object.entries(col).map(([k, i]) => [k, v[i]]))]));
      return { distritos: wrap(h.distritos), provincias: wrap(h.provincias), cuencas: wrap(h.cuencas), peligros: h.peligros };
    }).catch(() => null);
  }
  return HISTORY;
}

/** Punto dentro de un anillo (regla par-impar). */
export function inRing(x, y, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

const TOUCH = new Map();
/**
 * Los distritos que toca un aviso, más finos que su departamento: Map(código → cómo). «lugar»: el distrito que nombra;
 * «provincia»: los distritos de una provincia que nombra o que expone un aviso de corto plazo; «quebradas»: los
 * distritos con quebradas en aviso; «punto»: el de un centro poblado o un río que nombra; «zona»: los distritos cuyo
 * centro cae dentro de la zona de un aviso del SENAMHI. Un aviso que solo nombra departamentos no toca ninguno.
 */
export function alertDistricts(a, geo, codes) {
  const key = `${a.id}|${a.phase}`;
  if (TOUCH.has(key)) return TOUCH.get(key);
  const out = new Map();
  const put = (c, how) => { if (!out.has(c)) out.set(c, how); };
  const prov = (p) => codes.filter((c) => c.startsWith(p)).forEach((c) => put(c, 'provincia'));
  for (const p of a.places) {
    if (p.code.length === 6) put(p.code, 'lugar');
    else if (p.code.length === 4) prov(p.code);
  }
  const d = a.detail || {};
  for (const ar of d.areas || []) {
    if (ar.code?.length === 6) put(ar.code, 'quebradas');
    else if (ar.code?.length === 4) prov(ar.code);
  }
  for (const p of d.points || []) if (p.district && (p.kind === 'centro-poblado' || p.kind === 'cuerpo-de-agua')) put(p.district, 'punto');
  if (ACTIVE.has(a.phase)) {
    const rings = (d.shapes || []).flatMap((sh) => (sh.rings || []).filter((r) => r.length >= 4).map((r) => r.map(([lon, lat]) => project(geo, lon, lat))));
    if (rings.length) {
      for (const c of codes) {
        const xy = geo.points[c];
        if (xy && rings.some((r) => inRing(xy[0], xy[1], r))) put(c, 'zona');
      }
    }
  }
  TOUCH.set(key, out);
  return out;
}

/** Avisos por distrito y por cuenca; ``coarse``: los que solo nombran departamentos. */
export function alertUnits(alerts, geo, codes, basinOf) {
  const dist = new Map(), basin = new Map(), coarse = [];
  const push = (m, k, a) => { if (!m.has(k)) m.set(k, []); if (!m.get(k).includes(a)) m.get(k).push(a); };
  for (const a of alerts) {
    const ds = alertDistricts(a, geo, codes);
    if (!ds.size && !(a.detail?.points || []).some((p) => p.basin?.code)) { if (a.deps.length) coarse.push(a); continue; }
    for (const c of ds.keys()) {
      push(dist, c, a);
      const b = basinOf[c];
      if (b) push(basin, b, a);
    }
    for (const p of a.detail?.points || []) if (p.basin?.code && (p.kind === 'centro-poblado' || p.kind === 'cuerpo-de-agua')) push(basin, p.basin.code, a);
  }
  return { dist, basin, coarse };
}

const HOW = { lugar: 'el aviso nombra el distrito', provincia: 'el aviso nombra su provincia', quebradas: 'quebradas con probable activación', punto: 'el aviso nombra un lugar del distrito', zona: 'su centro está en la zona del aviso' };
const YEAR_BREAKS = [0.05, 0.1, 0.2, 0.35];
const freqCls = (h) => (!h || !h.aniosCobertura ? 'na' : !h.aniosConEvento ? 'none' : `q${Math.min(4, YEAR_BREAKS.filter((b) => h.aniosConEvento / h.aniosCobertura >= b).length)}`);
const pct0 = (v) => `${Math.round(v * 100)} %`;
function memoryLine(h, H, { basin = false } = {}) {
  if (!h) return 'Sin registros en la memoria de desastres.';
  const hz = h.peligro >= 0 ? (H.peligros[h.peligro] || '') : '';
  const freq = h.aniosCobertura ? `daños en ${h.aniosConEvento} de ${h.aniosCobertura} años (1970-2015)` : `${h.aniosConEvento} temporadas con registros${h.desde ? ` desde ${h.desde}` : ''}`;
  const great = h.grandesNinos === 1 ? ', 1 gran Niño' : h.grandesNinos ? `, ${h.grandesNinos} grandes Niños` : '';
  const last = h.ultimo ? (h.ultimo.length === 4 ? h.ultimo : fmtDate(h.ultimo)) : '';
  return `Memoria: ${fmtNumber(h.registros)} registros, ${freq}${great}${h.muertos ? `, ${fmtNumber(h.muertos)} fallecidos o desaparecidos` : ''}${hz ? `; lo más frecuente: ${hz.toLowerCase().replace('/', ' o ')}` : ''}${!basin && last ? `; último registro: ${last}` : ''}.`;
}

/** Mapa y panel de una vista de detalle. ``sel``: la cuenca o el distrito elegido. */
export function detailView(kind, geo, vis, f, ctx, sel = '') {
  const { districts, B, H } = ctx;
  const codes = Object.keys(districts).filter((c) => c.length === 6);
  const U = alertUnits(vis, geo, codes, B.districts || {});
  const deps = html`<g class="amap-deps" aria-hidden="true">${geo.departments.map((d) => html`<path d="${d.d}"></path>`)}</g>`;
  const label = kind === 'cuencas' ? 'Cuencas de la ANA con avisos' : 'Distritos con avisos y su historia de daños';
  const memo = (code) => (kind === 'cuencas' ? H.cuencas.get(code) : H.distritos.get(code));
  const nameOf = (code) => (kind === 'cuencas' ? B.units[code]?.n || code : `${memo(code)?.nombre || code} (${DEP_NAMES[code.slice(0, 2)]})`);
  const link = (code) => (kind === 'cuencas' ? `#/memoria?vista=cuencas&cuenca=${code}` : `#/memoria?nivel=distrito&area=${code}`);
  const map = kind === 'cuencas' ? U.basin : U.dist;
  let shapes;
  if (kind === 'cuencas') {
    shapes = Object.entries(B.units).map(([code, u]) => {
      const list = map.get(code) || [];
      const st = depState(list);
      const fill = st.soon && st.rank >= 0 ? `url(#amap-soon-${st.rank > 0 ? `r${st.rank}` : 'un'})` : '';
      const tip = `${u.n}\n${list.length ? `${list.filter((a) => ACTIVE.has(a.phase)).length} avisos vigentes o próximos, ${list.filter((a) => !ACTIVE.has(a.phase)).length} reportes o pasados` : 'Sin avisos con este filtro'}\n${memoryLine(memo(code), H, { basin: true })}`;
      return `<path class="bas d-${st.cls}${sel === code ? ' sel' : ''}${f.dep && list.length && !list.some((a) => a.deps.includes(f.dep)) ? ' dim' : ''}" d="${u.d}" data-basin="${code}" data-tip="${esc(tip)}"${fill ? ` style="fill:${fill}"` : ''}></path>`;
    }).join('');
  } else {
    shapes = [...map.entries()].filter(([c]) => districts[c]).map(([code, list]) => {
      const st = depState(list);
      const h = memo(code);
      const how = [...new Set(list.map((a) => alertDistricts(a, geo, codes).get(code)))].map((k) => HOW[k]).join('; ');
      const tip = `${nameOf(code)}\n${list.filter((a) => ACTIVE.has(a.phase)).length} avisos vigentes o próximos (${how})\n${memoryLine(h, H)}`;
      return `<path class="dist hz-${freqCls(h)} s-${st.cls}${sel === code ? ' sel' : ''}${f.dep && f.dep !== code.slice(0, 2) ? ' dim' : ''}" d="${districts[code].d}" data-dist="${code}" data-tip="${esc(tip)}"></path>`;
    }).join('');
  }
  const ring = sel && (kind === 'cuencas' ? B.units[sel]?.d : districts[sel]?.d);
  const svg = html`<svg class="amap-svg amap-det amap-det-${kind}" viewBox="0 0 ${geo.width} ${geo.height}" role="group" aria-label="${label}" preserveAspectRatio="xMidYMid meet">${DEFS}${kind === 'distritos' ? deps : ''}${raw(shapes)}${kind === 'cuencas' ? deps : ''}${ring ? html`<g class="sel-ring" aria-hidden="true">${['sel-glow', 'sel-case', 'sel-line'].map((k) => html`<path class="${k}" d="${ring}"></path>`)}</g>` : ''}</svg>`;
  // Panel: lo elegido, o el ranking (primero el nivel más alto vigente; entre iguales, el que más daños tuvo antes).
  const score = (code) => { const h = memo(code); return h ? (h.aniosCobertura ? h.aniosConEvento / h.aniosCobertura : h.aniosConEvento / 60) : 0; };
  const rows = [...map.entries()].map(([code, list]) => ({ code, list, st: depState(list), act: list.filter((a) => ACTIVE.has(a.phase)).length }))
    .filter((r) => r.act || f.fase)
    .sort((x, y) => y.st.rank - x.st.rank || score(y.code) - score(x.code) || y.list.length - x.list.length);
  const unit = kind === 'cuencas' ? 'cuencas' : 'distritos';
  let side;
  if (sel) {
    const list = map.get(sel) || [];
    side = html`<div class="amap-sel"><div class="amap-sel-top"><h3 class="amap-h3">${nameOf(sel)}</h3><button type="button" class="icon-btn" data-${kind === 'cuencas' ? 'basin' : 'dist'}="" aria-label="Cerrar">${raw(ICON.close)}</button></div>
      <p class="amap-memo">${raw(ICON.clock)}<span>${memoryLine(memo(sel), H, { basin: kind === 'cuencas' })} <a href="${link(sel)}" data-memoria>Ver su memoria de desastres</a></span></p>
      ${tipHtml('', list, { foot: 'Los avisos y noticias están en la lista de abajo.' })}</div>`;
  } else {
    side = html`<div class="amap-sel"><h3 class="amap-h3">${kind === 'cuencas' ? 'Cuencas con avisos' : 'Distritos en aviso que más daños tuvieron antes'}</h3>
      <p class="muted small">${rows.length} ${unit} con avisos ${f.fase ? 'con este filtro' : 'vigentes o próximos'}. ${U.coarse.length ? `${U.coarse.length} avisos solo nombran departamentos y no entran en este detalle (están en el resumen).` : ''}</p>
      ${rows.length ? html`<ol class="amap-rank amap-rank-det">${rows.slice(0, 12).map(({ code, list, st }) => {
        const h = memo(code);
        const freq = h ? (h.aniosCobertura ? `${pct0(h.aniosConEvento / h.aniosCobertura)} de los años con daños` : `${h.aniosConEvento} temporadas con registros`) : 'sin registros';
        return html`<li><button type="button" class="rank-row" data-${kind === 'cuencas' ? 'basin' : 'dist'}="${code}" aria-label="${nameOf(code)}: ${stateText(list)} Memoria: ${freq}.">
          <span class="rank-name">${nameOf(code)}<small class="muted">${freq}</small></span><span class="lvl-dot d-${st.cls}" aria-hidden="true"></span><span class="rank-n">${list.length}</span></button></li>`;
      })}</ol>${rows.length > 12 ? html`<p class="muted small">y ${rows.length - 12} ${unit} más.</p>` : ''}` : html`<p class="muted small">Ningún aviso de este filtro nombra un lugar más fino que el departamento.</p>`}
      <p class="muted small">${kind === 'cuencas' ? 'Color: el nivel más alto de los avisos que tocan la cuenca (sus distritos, si el 80 % o más de cada uno cae en ella, o los lugares que nombran).' : 'Relleno: la parte de los años de DesInventar (1970-2015) con daños en el distrito; borde: el nivel más alto de sus avisos.'} La memoria es lo que pasó antes, no un pronóstico.</p></div>`;
  }
  const legend = kind === 'cuencas'
    ? html`<div class="amap-legend-box"><ul class="amap-legend"><li><span class="sw sw-r3"></span>Rojo</li><li><span class="sw sw-r2"></span>Naranja</li><li><span class="sw sw-r1"></span>Amarillo</li><li><span class="sw sw-un"></span>Sin nivel en la fuente</li><li><span class="sw sw-rep"></span>Solo reportes o pasados</li><li><span class="sw sw-r2 sw-striped"></span>Rayado: próximo</li></ul></div>`
    : html`<div class="amap-legend-box"><ul class="amap-legend"><li><span class="sw hz-none"></span>Sin daños registrados</li><li><span class="sw hz-q0"></span>Menos del 5 % de los años</li><li><span class="sw hz-q1"></span>5–10 %</li><li><span class="sw hz-q2"></span>10–20 %</li><li><span class="sw hz-q3"></span>20–35 %</li><li><span class="sw hz-q4"></span>35 % o más</li></ul>
      <ul class="amap-legend"><li><span class="sw sw-ring r3"></span>Borde rojo</li><li><span class="sw sw-ring r2"></span>Naranja</li><li><span class="sw sw-ring r1"></span>Amarillo</li><li><span class="sw sw-ring un"></span>Sin nivel</li></ul></div>`;
  return { svg, side, legend };
}

// ---------------------------------------------------------------------------
// Montaje
// ---------------------------------------------------------------------------
/** Trazos de los distritos y las provincias (los del mapa de la memoria), para los avisos de quebradas y las provincias
 * expuestas de un aviso de corto plazo; se piden solo si hacen falta. */
let DISTRICTS = null;
function districtShapes() {
  if (!DISTRICTS) DISTRICTS = fetch('assets/historico/mapa.json').then((r) => (r.ok ? r.json() : null)).then((m) => (m ? { ...(m.provinces || {}), ...(m.districts || {}) } : null)).catch(() => null);
  return DISTRICTS;
}
let BASINS = null;
function basinShapes() {
  if (!BASINS) BASINS = fetch('assets/cuencas-mapa.json').then((r) => (r.ok ? r.json() : null)).catch(() => null);
  return BASINS;
}

function layersHtml(layers, alerts) {
  const kinds = new Set(alerts.flatMap((a) => (a.detail?.points || []).map((p) => p.kind)));
  const shapes = alerts.some((a) => ACTIVE.has(a.phase) && a.detail?.shapes?.length);
  const areaKinds = new Set(alerts.filter((a) => ACTIVE.has(a.phase)).flatMap((a) => (a.detail?.areas || []).map((ar) => ar.kind || 'quebradas')));
  const key = [shapes ? html`<li><span class="sw sw-shape"></span>Zona de un aviso del SENAMHI</li>` : '', areaKinds.has('quebradas') ? html`<li><span class="sw sw-area"></span>Distritos con quebradas en aviso</li>` : '',
    areaKinds.has('provincia') ? html`<li><span class="sw sw-area sw-prov"></span>Provincias expuestas (aviso de corto plazo)</li>` : '',
    ...[['estacion', 'sw-k-estacion', 'Estación hidrológica'], ['epicentro', 'sw-k-epicentro', 'Epicentro'], ['volcan', 'sw-k-volcan', 'Volcán'],
      ['focos', 'sw-k-focos', 'Focos de calor (celdas de ~11 km)'], ['centro-poblado', 'sw-k-cp', 'Centro poblado del reporte'],
      ['cuerpo-de-agua', 'sw-k-agua', 'Río, quebrada o laguna del reporte (con su tramo)']]
      .filter(([k]) => kinds.has(k)).map(([, c, t]) => html`<li><span class="sw ${c}"></span>${t}</li>`)].filter(Boolean);
  return html`<div class="amap-layers" role="group" aria-label="Capas del mapa">
    <button type="button" class="kind-chip" data-layer="detalle" aria-pressed="${String(layers.detalle)}">Formas y puntos</button>
    <button type="button" class="kind-chip" data-layer="cuencas" aria-pressed="${String(layers.cuencas)}"><span class="sw sw-basin"></span>Cuencas (ANA)</button>
    ${layers.detalle && key.length ? html`<ul class="amap-legend amap-legend-detail">${key}</ul>` : ''}</div>`;
}

export async function mountAlertMap(el, { feed, getFilter, onFilter }) {
  if (!el) return null;
  const [geo] = await Promise.all([geometry(), abReady()]);
  const session = ab();
  // La vista (ab.js «noticias»): la del enlace (?vista=, sin contarla si no es la suya) o la de esta persona.
  const vsession = ab('noticias');
  const VIDS = VISTAS.map(([k]) => k);
  let vista = VIDS.includes(getFilter().vista) ? getFilter().vista : vsession.own;
  vsession.show(vista);
  let sel = '';
  let det = null;  // {districts, B, H} de las vistas de detalle, cuando llegan
  const loadDet = () => Promise.all([districtShapes(), basinShapes(), historyRows()]).then(([districts, B, H]) => {
    det = districts && B && H ? { districts, B, H } : false;
  });
  let model = prepare(feed);
  if (!geo || !model.alerts.length && !model.sources.total) {
    el.innerHTML = '';
    return null;
  }
  // Capas: el detalle de cada aviso (formas, distritos con quebradas, puntos) y las cuencas de la ANA.
  const layers = { detalle: true, cuencas: false };
  let districts = model.alerts.some((a) => a.detail?.areas?.length) ? await districtShapes() : null;
  let basinsGeo = null;
  const tick = setInterval(() => { model = prepare(feed); draw(); }, 5 * 60 * 1000);  // las fases avanzan con el reloj
  const draw = () => {
    if (!el.isConnected) { clearInterval(tick); return; }
    const f = readFilter(getFilter());
    const v = session.variant;
    const vis = model.alerts.filter((a) => matches(a, f, { ignore: ['dep'] }));
    const by = aggregate(vis);
    const depSel = f.dep ? (by[f.dep] || []) : null;
    const label = 'Mapa del Perú por departamento con los avisos oficiales';
    // El detalle va debajo del anillo del departamento elegido (depShapes lo pone al final).
    const overlay = raw((layers.cuencas ? basinsMarkup(basinsGeo) : '') + (layers.detalle ? detailMarkup(geo, vis, f, { districts }) : ''));
    const tipBox = html`<div class="amap-tip" role="tooltip" hidden></div>${layersHtml(layers, vis)}`;
    let body;
    if (v === 'B') {
      body = html`<div class="amap-grid"><div class="amap-mapbox">${svgMap(geo, html`<g class="outline">${depShapes(geo, {}, f, { overlay })}</g>${pings(geo, vis, f)}`, label)}${tipBox}</div>
        <div class="amap-side">${legend('B')}${depRanking(model.alerts, f, 6)}</div></div>`;
    } else if (v === 'C') {
      body = html`<div class="amap-grid amap-grid-c"><div class="amap-mapbox">${svgMap(geo, depShapes(geo, by, f, { overlay }), label)}${tipBox}</div>
        <div class="amap-side">${matrix(model.alerts, f)}<h3 class="amap-h3">Departamentos con más avisos</h3>${depRanking(model.alerts, f)}${legend('C')}</div></div>`;
    } else if (v === 'D') {
      body = html`<div class="amap-grid amap-grid-d"><div class="amap-mapbox">${svgMap(geo, depShapes(geo, by, f, { overlay }), label)}${tipBox}</div>
        <div class="amap-side"><h3 class="amap-h3">Vigencia de los avisos: ayer, hoy y los próximos días</h3>${timeline(model.alerts, f, Date.now())}${legend('D')}</div></div>`;
    } else {
      body = html`<div class="amap-grid amap-grid-a"><div class="amap-mapbox">${svgMap(geo, depShapes(geo, by, f, { badges: true, overlay }), label)}${tipBox}</div>
        <div class="amap-side">${legend('A')}${depSel ? html`<div class="amap-sel"><h3 class="amap-h3">${DEP_NAMES[f.dep]}</h3>${tipHtml('', depSel, { foot: 'Sus avisos y noticias están en la lista de abajo.' })}</div>` : html`<p class="muted small">Pase el cursor o toque un departamento para ver sus avisos; haga clic para filtrar las noticias.</p>`}</div></div>`;
    }
    if (vista !== 'resumen') {
      if (det === null) loadDet().then(() => { if (det === false) { vsession.show('resumen'); vista = 'resumen'; } draw(); });
      const D = det ? detailView(vista, geo, vis, f, det, sel) : null;
      body = html`<div class="amap-grid amap-grid-det"><div class="amap-mapbox">${D ? D.svg : html`<div class="skeleton" aria-hidden="true"></div><p class="muted">Cargando las cuencas, los distritos y la memoria de desastres…</p>`}<div class="amap-tip" role="tooltip" hidden></div>${D ? D.legend : ''}</div>
        <div class="amap-side">${D ? D.side : ''}</div></div>`;
    }
    const pubAge = model.generatedAt ? (Date.now() - Date.parse(model.generatedAt)) / H : 0;
    // Al redibujar, el foco vuelve al mismo control (un departamento, un filtro) para el teclado.
    const act = el.contains(document.activeElement) ? document.activeElement : null;
    const refocus = act && (act.dataset.dep && !act.dataset.f ? `[data-dep="${act.dataset.dep}"]${act.classList.contains('dep') ? '.dep' : act.dataset.spot ? `[data-spot="${act.dataset.spot}"]` : `.${act.classList[0]}`}`
      : act.dataset.f ? `[data-f="${act.dataset.f}"][data-v="${act.dataset.v}"]` : act.id ? `#${act.id}` : act.dataset.fase ? `.cell[data-fase="${act.dataset.fase}"][data-nivel="${act.dataset.nivel}"]` : '');
    el.innerHTML = String(html`<section class="card amap amap-v${vista === 'resumen' ? v : vista}" aria-labelledby="amap-h" data-tour-id="alert-map">
      <div class="amap-head"><div><h2 id="amap-h">Mapa de alertas y avisos oficiales</h2>
        <p class="amap-sum" aria-live="polite">${summary(model, vis.filter((a) => !f.dep || a.deps.includes(f.dep)))}</p></div>
        <div class="amap-tools"><div class="hz-views amap-views" role="group" aria-label="Vista del mapa"><div class="seg">${viewBtn('resumen')}</div><span class="hz-views-l" aria-hidden="true">Detalle</span><div class="seg">${VIDS.slice(1).map(viewBtn)}</div></div>
        ${vista === 'resumen' ? html`<label class="amap-ver"><span>Versión del mapa</span><select id="amap-ver">${VARIANTS.map(([k, l]) => html`<option value="${k}" ${k === v ? 'selected' : ''}>Versión ${k}: ${l}</option>`)}</select></label>` : ''}</div></div>
      ${model.sources.total && !model.sources.ok ? html`<p class="notice notice-alert">${raw(ICON.octagon)}<span>Ninguna fuente de alertas respondió en la última actualización: el mapa muestra los últimos avisos conocidos y puede faltar lo más reciente. Consulte directamente al SENAMHI y al INDECI.</span></p>` : ''}
      ${!model.hasLevels && model.alerts.length ? html`<p class="notice notice-info">${raw(ICON.info)}<span>Esta publicación es anterior al mapa: los niveles y la vigencia de cada aviso aparecerán con la próxima actualización diaria.</span></p>` : ''}
      ${body}
      ${filtersHtml(f, model.alerts)}
      ${national(model.alerts, f)}
      ${depList(geo, by)}
      <p class="amap-foot muted small">El nivel y la vigencia son los que publica cada institución (SENAMHI, INDECI, IGP, DHN, USGS); el observatorio no asigna niveles. ${levelsNote(model.levels)}${model.sources.total ? `${model.sources.ok} de ${model.sources.total} fuentes de alertas respondieron en la actualización ${model.generatedAt ? `del ${when(model.generatedAt)}` : ''}.` : ''} ${pubAge > 30 ? html`<strong>Esa actualización tiene ${Math.round(pubAge / 24)} días: pueden faltar avisos recientes.</strong>` : 'Los avisos emitidos después llegan con la siguiente actualización.'} Sin avisos no quiere decir sin peligro: ante una emergencia, siga a INDECI, al SENAMHI y a su gobierno local. Límites: INDECI (GEOSINPAD).</p>
    </section>`);
    wire(el, f, by);
    if (refocus) (el.querySelector(refocus) || $('#amap-h', el))?.focus?.({ preventScroll: true });
    if (vista === 'resumen') session.mark('view');
    vsession.mark('view');
  };
  const viewBtn = (k) => html`<button type="button" data-vista="${k}" aria-pressed="${String(k === vista)}" title="${VISTA_HINT[k]}">${VISTA_LABEL[k]}</button>`;
  // Las marcas de uso van a la versión A–D en el resumen y siempre a la vista.
  const mark = (e) => { if (vista === 'resumen') session.mark(e); vsession.mark(e); };

  const setF = (partial) => { mark('select'); onFilter(partial); };

  function wire(root, f, by) {
      const tip = $('.amap-tip', root);
    let hovered = false;
    const place = (x, y) => {
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
    };
    const showTip = (target, x, y) => {
      if (!tip) return;
      const det = target.closest('[data-tip]');
      if (det) {  // una forma, un distrito, un punto o una cuenca: su texto viene en data-tip
        const [head, ...rest] = det.dataset.tip.split('\n');
        tip.innerHTML = String(html`<div class="amap-tip-h"><strong>${head}</strong></div>${rest.map((t) => html`<p class="muted">${t}</p>`)}`);
        tip.hidden = false;
        place(x, y);
        if (!hovered && det.closest('.amap-det')) { hovered = true; mark('hover'); }
        return;
      }
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
      place(x, y);
      if (!hovered) { hovered = true; mark('hover'); }
    };
    const hideTip = () => { if (tip) tip.hidden = true; };
    const svg = $('.amap-svg', root);
    if (svg) {
      svg.addEventListener('pointermove', (e) => { if (e.pointerType !== 'touch') showTip(e.target, e.clientX, e.clientY); });
      svg.addEventListener('pointerleave', hideTip);
      svg.addEventListener('click', (e) => {
        const u = e.target.closest('[data-basin], [data-dist]');
        if (u) {
          hideTip();
          const code = u.dataset.basin ?? u.dataset.dist;
          mark('select');
          sel = sel === code ? '' : code;
          draw();
          return;
        }
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
    $$('.rank-row[data-dep], .amap-a11y [data-dep]', root).forEach((b) => b.addEventListener('click', () => setF({ dep: f.dep === b.dataset.dep ? '' : b.dataset.dep })));
    $$('.tl-row', root).forEach((b) => b.addEventListener('click', () => {
      if (b.dataset.dep) setF({ dep: f.dep === b.dataset.dep ? '' : b.dataset.dep });
      else { const a = model.alerts.find((x) => x.id === b.dataset.id); if (a?.url) { mark('detail'); window.open(safeUrl(a.url), '_blank', 'noopener'); } }
    }));
    $$('[data-detail]', root).forEach((a) => a.addEventListener('click', () => mark('detail')));
    $$('[data-memoria]', root).forEach((a) => a.addEventListener('click', () => mark('detail')));
    $$('[data-vista]', root).forEach((b) => b.addEventListener('click', () => {
      const k = b.dataset.vista;
      if (k === vista) return;
      vsession.choose(k);
      vista = k;
      sel = '';
      onFilter({ vista: k === 'resumen' ? '' : k });
      $(`[data-vista="${k}"]`, el)?.focus();
    }));
    $$('.amap-side [data-basin], .amap-side [data-dist]', root).forEach((b) => b.addEventListener('click', () => {
      const code = b.dataset.basin ?? b.dataset.dist;
      if (code) mark('detail');
      sel = code;
      draw();
      $('.amap-side .amap-h3', el)?.focus?.();
    }));
    $$('[data-layer]', root).forEach((b) => b.addEventListener('click', async () => {
      const k = b.dataset.layer;
      layers[k] = !layers[k];
      if (k === 'cuencas' && layers.cuencas && !basinsGeo) basinsGeo = await basinShapes();
      if (k === 'detalle' && layers.detalle && !districts && model.alerts.some((a) => a.detail?.areas?.length)) districts = await districtShapes();
      draw();
      $(`[data-layer="${k}"]`, el)?.focus();
    }));
    $('#amap-ver', root)?.addEventListener('change', (e) => {
      session.choose(e.target.value);
      draw();
      $('#amap-ver', el)?.focus();
    });
  }

  draw();
  return { update: draw, markDetail: () => mark('detail') };
}

// ---------------------------------------------------------------------------
// Resultados de las versiones (#/variantes)
// ---------------------------------------------------------------------------
const EXP_TITLE = {
  mapa: ['Versión del mapa de alertas', 'Noticias, vista Resumen: las cuatro formas de dibujar los avisos por departamento.'],
  memoria: ['Vista con que abre el mapa de la memoria', 'Memoria de desastres: el resumen por área o uno de sus tres detalles.'],
  noticias: ['Vista con que abre el mapa de Noticias', 'Noticias: el resumen (con su versión A–D) o uno de sus dos detalles.'],
};

export function statsHtml(s) {
  if (!s) return html`<p>No se pudo leer la analítica. Solo funciona en el sitio publicado en Cloudflare Pages.</p>`;
  if (!s.available) return html`<p>La base de datos no está vinculada en este despliegue (GEO_DB): no hay datos.</p>`;
  const pct = (a, b) => (b ? `${Math.round((100 * a) / b)} %` : '—');
  const exps = s.experiments || { mapa: { totals: s.totals } };
  const block = (x) => {
    const e = exps[x];
    if (!e) return '';
    const dec = e.decision;
    const byV = Object.fromEntries((dec?.rows || []).map((r) => [r.v, r]));
    const rows = EXPERIMENTS[x].variants.map(([v, name]) => {
      const t = e.totals?.[v] || {};
      const d = byV[v];
      const use = d && d.view ? html`${pct(d.use, d.view)}<div class="muted small">${Math.round(d.lo * 100)}–${Math.round(d.hi * 100)} %</div>` : '—';
      return html`<tr><th scope="row">${x === 'mapa' ? `Versión ${v}` : name}${dec?.winner === v ? html` <span class="chip chip-ok">Ganadora</span>` : ''}<div class="muted small">${x === 'mapa' ? name : v}</div></th>
        <td class="num">${t.view || 0}</td><td class="num">${use}</td><td class="num">${pct(t.hover || 0, t.view)}</td><td class="num">${pct(t.select || 0, t.view)}</td><td class="num">${pct(t.detail || 0, t.view)}</td>
        <td class="num">${t.choose || 0}</td><td class="num">${t.leave || 0}</td><td class="num">${t.keep || 0}</td><td class="num">${pct(t.chosen || 0, t.view)}</td></tr>`;
    });
    const need = dec ? dec.rows.filter((r) => r.view < dec.minViews) : [];
    const verdict = !dec ? ''
      : dec.winner ? `Gana «${dec.winner}»: el límite inferior de su tasa de uso supera el límite superior de todas las demás. Se muestra a 4 de cada 5 personas que llegan por primera vez; el resto recibe otra al azar.`
        : need.length ? `Aún sin ganadora: cada versión necesita al menos ${dec.minViews} visitas medidas (faltan en ${need.map((r) => `«${r.v}», ${r.view}`).join('; ')}). Mientras tanto, cada versión sale con la misma probabilidad.`
          : 'Aún sin ganadora: los intervalos de las versiones se cruzan. Cada versión sigue saliendo con la misma probabilidad.';
    const [title, sub] = EXP_TITLE[x];
    return html`<h3 class="amap-h3">${title}</h3><p class="muted small">${sub}</p>
      <div class="table-wrap"><table class="grd"><thead><tr><th scope="col">${x === 'mapa' ? 'Versión' : 'Vista'}</th><th scope="col">Visitas</th><th scope="col">Usaron el mapa</th><th scope="col">Pasaron el cursor</th><th scope="col">Filtraron o eligieron</th><th scope="col">Abrieron algo</th><th scope="col">La eligieron</th><th scope="col">La dejaron</th><th scope="col">Volvieron con ella elegida</th><th scope="col">Visitas con ella elegida</th></tr></thead><tbody>${rows}</tbody></table></div>
      ${verdict ? html`<p class="small"><strong>${verdict}</strong></p>` : ''}`;
  };
  return html`${Object.keys(EXPERIMENTS).map(block)}
    <p class="muted small">Últimos ${s.days} días (desde el ${s.since}). Cada visita cuenta una vez por evento. «Usaron el mapa»: visitas en las que la persona filtró, eligió un área o abrió algo desde el mapa, con su intervalo de Wilson al 95 %; es la tasa que decide, con los últimos ${s.decideDays || 60} días${s.decideDays && s.decideDays !== s.days ? ' (no con el periodo elegido)' : ''}. «Volvieron con ella elegida»: visitas de otro día de personas que eligieron esa versión y la mantienen. Las versiones se asignan al azar en la primera visita (o la ganadora, si la hay); elegir otra la deja como predeterminada en ese navegador. No se guarda ningún dato personal: solo contadores por día.</p>`;
}
