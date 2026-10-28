// Memoria de desastres: dónde golpearon antes los Niños, las lluvias, los huaycos, las sequías y las
// heladas, con qué frecuencia, cuánto cambia con El Niño y qué tan bien esa historia anticipó lo que vino después
// (resumen.json → validacion).
//
// Datos: assets/historico/ (python -m tools.build_historico). El catálogo y los indicadores se
// explican en docs/memoria-desastres.md. Toda cifra de impacto es la que reporta la fuente; el
// navegador solo cuenta y filtra (historico-model.js, el mismo cálculo que los CSV del equipo).

import { html, raw, esc, safeUrl, $, $$ } from './lib/dom.js';
import * as F from './lib/format.js';
import { ICON } from './icons.js';
import * as M from './historico-model.js';
import * as EV from './historico-evidencia.js';

const BASE = 'assets/historico/';
let CACHE = null;
let CONTEXT = null;
let PREVENTION = null;
const DETAIL = new Map();

async function getJSON(path) {
  const r = await fetch(path, { cache: 'no-cache' });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

export async function loadAll() {
  if (!CACHE) {
    CACHE = Promise.all([getJSON(`${BASE}eventos.json`), getJSON(`${BASE}resumen.json`), getJSON(`${BASE}mapa.json`), getJSON('assets/peru-map.json')])
      .then(([ev, sum, map, peru]) => {
        const recs = M.decode(ev);
        const attrs = new Map(Object.entries(sum.atributos.distritos));
        return {
          recs, sum, map, peru, attrs, nino: new Set(sum.aniosNino), great: sum.grandesNinos, generatedAt: ev.generatedAt,
          hom: new Set(sum.cobertura.origenes || []), ongoing: sum.eventoEnCurso || '',
        };
      })
      .catch((e) => { CACHE = null; throw e; });
  }
  return CACHE;
}

/** Peligro identificado hoy (INGEMMET, ANA, salud 2023), por distrito; se pide al abrir una ficha. */
function context() {
  if (!CONTEXT) CONTEXT = getJSON(`${BASE}contexto.json`).catch(() => ({ distritos: {} }));
  return CONTEXT;
}

/** Declaratorias, evaluaciones, inventarios y llamamientos (prevencion.json); se pide después del mapa. */
function prevention() {
  if (!PREVENTION) PREVENTION = getJSON(`${BASE}prevencion.json`).catch(() => null);
  return PREVENTION;
}

async function detail(dep) {
  if (!DETAIL.has(dep)) DETAIL.set(dep, getJSON(`${BASE}detalle/${dep}.json`).catch(() => ({})));
  return DETAIL.get(dep);
}

/** Unidades hidrográficas de la ANA con su trazo y la cuenca de cada distrito (python -m tools.build_cuencas_mapa). */
let BASINS = null;
function basins() {
  if (!BASINS) BASINS = getJSON('assets/cuencas-mapa.json').catch(() => ({ units: {}, districts: {} }));
  return BASINS;
}

// ---------------------------------------------------------------------------
// Estado (en la dirección: #/memoria?nivel=distrito&evento=grandes&area=200104)
// ---------------------------------------------------------------------------
const DEFAULTS = { nivel: 'provincia', evento: '', peligro: '', desde: '', hasta: '', metrica: 'anios', area: '', cuencas: '' };
const METRICS = [
  ['anios', 'Años con daños (1970-2015)'], ['minimo', 'Años con daños, como mínimo (IC 95 %)'], ['grandes', 'Grandes Niños que lo golpearon'],
  ['razon', 'Cuántos más lugares con daños en años de Niño'], ['registros', 'Registros'], ['muertos', 'Fallecidos y desaparecidos'],
  ['afectados', 'Afectados, damnificados y desplazados'], ['viviendas', 'Viviendas destruidas'],
];
const LEVEL_NAMES = [['departamento', 'Departamento'], ['provincia', 'Provincia'], ['distrito', 'Distrito']];
const HAZARD_GROUPS = {
  agua: ['Inundación y desborde', ['Inundacion fluvial', 'Inundacion pluvial', 'Inundacion', 'Desborde de rio']],
  masa: ['Huaycos y deslizamientos', ['Huayco/Alud', 'Deslizamiento', 'Erosion']],
  lluvia: ['Lluvias intensas, granizo y tormentas', ['Lluvias intensas', 'Granizada', 'Tormenta electrica', 'Tormenta']],
  mar: ['Oleaje anómalo y erosión costera', ['Oleaje anomalo', 'Erosion costera']],
  seco: ['Sequías, olas de calor e incendios', ['Sequias', 'Ola de calor', 'Incendio forestal']],
  frio: ['Heladas, friaje y nevadas', ['Helada/Friaje', 'Nevada']],
  viento: ['Vientos fuertes', ['Vientos fuertes']],
  salud: ['Epidemias y plagas asociadas a lluvias o El Niño', ['Epidemia', 'Plaga']],
};
const DANGER_LABEL = {
  'Inundacion fluvial': 'Inundación fluvial', 'Inundacion pluvial': 'Inundación pluvial', Inundacion: 'Inundación (sin detalle)',
  'Desborde de rio': 'Desborde de río', 'Huayco/Alud': 'Huayco o alud', Deslizamiento: 'Deslizamiento', 'Lluvias intensas': 'Lluvias intensas',
  'Oleaje anomalo': 'Oleaje anómalo', 'Erosion costera': 'Erosión costera', Nevada: 'Nevada', Granizada: 'Granizada',
  'Helada/Friaje': 'Helada o friaje', 'Ola de calor': 'Ola de calor', 'Vientos fuertes': 'Vientos fuertes', 'Tormenta electrica': 'Tormenta eléctrica', Tormenta: 'Tormenta (lluvia, viento o rayos)',
  Sequias: 'Sequía', 'Incendio forestal': 'Incendio forestal', Erosion: 'Erosión', Epidemia: 'Epidemia', Plaga: 'Plaga',
};
const dl = (t) => DANGER_LABEL[t] || t;
const SOURCE_LINK = { desinventar: 'DesInventar', sinpad: 'SINPAD', idmc: 'IDMC', 'nasa-glc': 'noticia', coen: 'reporte del COEN', prensa: 'nota de prensa', hemeroteca: 'página de periódico', glof: 'base de GLOF' };
/** Qué fecha trae el registro cuando no es la del evento. */
const DATE_KIND = { informe: 'fecha del primer reporte del COEN', publicacion: 'fecha de publicación de la nota', texto: 'fecha que cita la nota' };
const hostOf = (u) => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return 'enlace'; } };
// Varias notas del mismo medio van juntas: «medio.pe (1, 2, 3)», cada número enlaza a una nota.
const corrLinks = (links) => {
  const by = new Map();
  for (const u of links) {
    const h = hostOf(u);
    if (!by.has(h)) by.set(h, []);
    by.get(h).push(u);
  }
  const a = (u, t) => html`<a href="${safeUrl(u)}" rel="noopener" target="_blank">${t}</a>`;
  return [...by.entries()].map(([h, us], k) => html`${k ? ', ' : ''}${us.length === 1 ? a(us[0], h) : html`${h} (${us.map((u, j) => html`${j ? ', ' : ''}${a(u, `nota ${j + 1}`)}`)})`}`);
};

export function readState() {
  const q = new URLSearchParams(location.hash.split('?')[1] || '');
  const s = { ...DEFAULTS };
  for (const k of Object.keys(DEFAULTS)) if (q.has(k)) s[k] = q.get(k);
  if (!LEVEL_NAMES.some(([k]) => k === s.nivel)) s.nivel = DEFAULTS.nivel;
  if (!METRICS.some(([k]) => k === s.metrica)) s.metrica = DEFAULTS.metrica;
  if (s.area && !/^\d{2}(\d{2}){0,2}$/.test(s.area)) s.area = '';
  if (s.cuencas !== '1') s.cuencas = '';
  return s;
}

function writeState(s) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(s)) if (v && v !== DEFAULTS[k]) q.set(k, v);
  const h = `#/memoria${q.toString() ? `?${q}` : ''}`;
  if (location.hash !== h) history.replaceState(null, '', h);
}

// ---------------------------------------------------------------------------
// Utilidades de presentación
// ---------------------------------------------------------------------------
const n0 = (v) => F.fmtNumber(v, 0);
const pct = (v) => (v === null || v === undefined ? 'N/D' : `${F.fmtNumber(v * 100, 0)} %`);
const x1 = (v) => (v === null || v === undefined ? 'N/D' : `${F.fmtNumber(v, 1)}×`);
/** Rango «a–b» de un intervalo; sin cota superior, «a o más». */
/** Intervalo «a–b»; si los dos extremos se escriben igual, una sola cifra (no «100–100 %»). */
function span(lo, hi, fmt) {
  if (lo === null || lo === undefined) return 'N/D';
  if (hi === null || hi === undefined) return `${fmt(lo)} o más`;
  const a = fmt(lo), b = fmt(hi);
  return a === b ? a : `${a}–${b}`;
}
const pctRange = (ic) => (ic[0] >= 0.995 ? 'más del 99 %' : `${span(ic[0], ic[1], (v) => F.fmtNumber(v * 100, 0))} %`);
/** Periodo de retorno con un decimal bajo 10 años: «1 de cada 1,1» y no «1 de cada 1» cuando hubo daños en 40 de 45 años. */
const rp = (v) => F.fmtNumber(v, v < 10 ? 1 : 0);
/** 1 si el intervalo de la razón de El Niño queda entero sobre 1, −1 si bajo 1, 0 si lo incluye. */
const rrSign = (st) => (st?.razonNino ? (st.razonNinoIC[0] > 1 ? 1 : st.razonNinoIC[1] < 1 ? -1 : 0) : null);

/**
 * Indicadores por área con los filtros elegidos. Con un filtro de evento la razón de El Niño no aplica: compararía los
 * registros de un evento con sus propias temporadas.
 */
function statsFor(D, s, recs, years, level = s.nivel) {
  const stats = M.byArea(recs, level, years, D.nino, D.great, D.hom);
  if (s.evento) for (const st of stats.values()) dropRR(st);
  return stats;
}
function dropRR(st) { st.razonNino = null; st.razonNinoIC = [null, null]; return st; }

/** Indicadores sin filtros (para las alertas): por departamento y provincia, calculados una vez. */
function baseline(D) {
  if (!D.base) {
    const years = M.coverageYears(D.sum.cobertura.homogenea, 0, 0);
    D.base = { departamento: M.byArea(D.recs, 'departamento', years, D.nino, D.great, D.hom), provincia: M.byArea(D.recs, 'provincia', years, D.nino, D.great, D.hom) };
  }
  return D.base;
}
/** Fecha con la precisión que trae el registro: «1998», «marzo de 1998» o «12 de marzo de 1998». */
const when = (d) => (d.length === 4 ? d : F.fmtDate(d));

function areaName(D, code) {
  const N = D.sum.nombres;
  if (code.length === 2) return N.departamento[code] || code;
  if (code.length === 4) return `${N.provincia[code] || code} (${N.departamento[code.slice(0, 2)]})`;
  return `${N.distrito[code] || code} (${N.provincia[code.slice(0, 4)]}, ${N.departamento[code.slice(0, 2)]})`;
}
const shortName = (D, code) => (code.length === 2 ? D.sum.nombres.departamento[code] : code.length === 4 ? D.sum.nombres.provincia[code] : D.sum.nombres.distrito[code]) || code;

function population(D, code) {
  let tot = 0;
  for (const [c, a] of D.attrs) if (c.startsWith(code)) tot += a[0] || 0;
  return tot || null;
}

/** La frecuencia histórica con su intervalo, como etiqueta de la ficha. */
function freqChip(st) {
  if (!st?.aniosCobertura) return html`<span class="hz-attn hz-attn-0">Fuera del periodo 1970-2015</span>`;
  if (!st.aniosConEvento) return html`<span class="hz-attn hz-attn-0">Sin registros en DesInventar 1970-2015</span>`;
  return html`<span class="hz-attn hz-attn-2">${raw(ICON.info)}Daños en ${pctRange(st.frecuenciaIC)} de los años</span>`;
}

/** Valor de la métrica para un área (número para colorear o null). */
function metricValue(st, metric) {
  if (!st) return null;
  switch (metric) {
    case 'anios': return st.aniosCobertura ? st.frecuenciaAnual : null;
    case 'minimo': return st.aniosCobertura ? st.frecuenciaIC[0] : null;
    case 'grandes': return st.grandesNinos.length;
    case 'razon': return st.razonNino;
    case 'registros': return st.registros;
    case 'muertos': return st.muertos;
    case 'afectados': return st.afectados;
    case 'viviendas': return st.viviendas;
    default: return null;
  }
}

function metricText(st, metric) {
  if (!st) return 'Sin registros';
  switch (metric) {
    case 'anios': return st.aniosCobertura ? `${st.aniosConEvento} de ${st.aniosCobertura} años en DesInventar (IC 95 %: ${pctRange(st.frecuenciaIC)})${st.muestraPequena ? ' · muestra pequeña' : ''}` : 'Fuera del periodo 1970-2015';
    case 'minimo': return st.aniosCobertura ? `al menos ${pct(st.frecuenciaIC[0])} de los años (${st.aniosConEvento} de ${st.aniosCobertura})` : 'Fuera del periodo 1970-2015';
    case 'grandes': return st.grandesNinos.length ? `${st.grandesNinos.length}: ${st.grandesNinos.join(', ')}` : 'Ninguno registrado';
    case 'razon': return st.razonNino ? `${x1(st.razonNino)} (IC 95 %: ${F.fmtNumber(st.razonNinoIC[0], 1)}–${F.fmtNumber(st.razonNinoIC[1], 1)})${rrSign(st) === 0 ? ' · sin diferencia clara' : ''}` : 'No aplica o datos insuficientes';
    case 'registros': return `${n0(st.registros)} registros`;
    case 'muertos': return `${n0(st.muertos)} fallecidos y desaparecidos`;
    case 'afectados': return `${n0(st.afectados)} afectados, damnificados o desplazados`;
    case 'viviendas': return `${n0(st.viviendas)} viviendas destruidas`;
    default: return '';
  }
}

/** Clases de color: {cls(v) → 'q0'…'q4' | 'none' | 'na', legend:[[cls, texto]]}. */
//: Cortes de «años con daños» por nivel: un departamento casi siempre tiene daños todos los años; un
//: distrito, rara vez. Con un solo juego de cortes, un nivel saldría todo oscuro o todo claro.
const YEAR_BREAKS = { departamento: [0.6, 0.75, 0.9, 0.98, 1.01], provincia: [0.2, 0.35, 0.5, 0.7, 1.01], distrito: [0.05, 0.1, 0.2, 0.35, 1.01] };

function scaleFor(metric, values, level = 'provincia') {
  if (metric === 'razon') {
    // Solo se colorea lo que el intervalo distingue de 1; el resto, gris (con cientos de áreas, muchas razones
    // grandes son ruido de muestras pequeñas).
    const br = [0.67, 0.9, 1.11, 1.5, 2];
    const lab = ['Menos de 0,67×', '0,67–0,9×', 'Sin diferencia clara (el IC incluye 1)', '1,1–1,5×', '1,5–2×', 'Más de 2×'];
    const cls = (v, st) => {
      if (v === null || v === undefined) return 'na';
      if (st && rrSign(st) === 0) return 'd2';
      const i = br.findIndex((b) => v < b);
      return `d${i === -1 ? 5 : i}`;
    };
    return { cls, legend: [...lab.map((l, i) => [`d${i}`, l]), ['na', 'No aplica o datos insuficientes']], diverging: true };
  }
  if (metric === 'grandes') {
    const cls = (v) => (v ? `q${Math.min(4, v - 1)}` : 'none');
    return { cls, legend: [['none', 'Ninguno'], ['q0', '1'], ['q1', '2'], ['q2', '3'], ['q3', '4'], ['q4', '5']] };
  }
  if (metric === 'anios' || metric === 'minimo') {
    const br = YEAR_BREAKS[level] || YEAR_BREAKS.provincia;
    const p = (v) => F.fmtNumber(v * 100, 0);
    const lab = br.map((b, i) => (i === 0 ? `Menos del ${p(b)} % de los años` : i === br.length - 1 ? `${p(br[i - 1])} % de los años o más` : `${p(br[i - 1])}–${p(b)} %`));
    const cls = (v) => (v === null || v === undefined ? 'na' : v <= 0 ? 'none' : `q${br.findIndex((b) => v < b)}`);
    return { cls, legend: [['none', metric === 'minimo' ? 'Cero o sin registros en DesInventar' : 'Sin registros en DesInventar 1970-2015'], ...lab.map((l, i) => [`q${i}`, l]), ['na', 'Fuera de cobertura']] };
  }
  const br = M.quantileBreaks(values, 5);
  const off = 5 - br.length; // con pocos valores distintos, las clases que quedan son las más oscuras
  const cls = (v) => { const c = M.classOf(v, br); return c < 0 ? 'none' : `q${c + off}`; };
  const legend = [['none', 'Cero o sin dato'], ...br.map((b, i) => {
    const lo = i ? Math.floor(br[i - 1]) + 1 : 1;
    return [`q${i + off}`, lo >= Math.floor(b) ? n0(b) : `${n0(lo)}–${n0(b)}`];
  })];
  return { cls, legend };
}

// ---------------------------------------------------------------------------
// Mapa
// ---------------------------------------------------------------------------
function shapesFor(D, level) {
  if (level === 'departamento') return D.peru.departments.map((d) => [d.code, d.d, d.label]);
  const src = level === 'provincia' ? D.map.provinces : D.map.districts;
  return Object.entries(src).map(([c, f]) => [c, f.d, f.c]);
}

function viewBoxFor(D, s) {
  const full = `0 0 ${D.peru.width} ${D.peru.height}`;
  if (!s.area || s.nivel === 'departamento') return full;
  const dep = s.area.slice(0, 2);
  const pts = Object.entries(D.map.districts).filter(([c]) => c.startsWith(dep)).map(([, f]) => f.c);
  if (!pts.length) return full;
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  let [x0, x1_, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const pad = Math.max(18, (x1_ - x0) * 0.18, (y1 - y0) * 0.18);
  x0 -= pad; y0 -= pad; x1_ += pad; y1 += pad;
  const w = x1_ - x0, h = y1 - y0, side = Math.max(w, h * 0.75);
  return `${(x0 + w / 2 - side / 2).toFixed(1)} ${(y0 + h / 2 - (side / 0.75) / 2).toFixed(1)} ${side.toFixed(1)} ${(side / 0.75).toFixed(1)}`;
}

// Contorno del área elegida con su propia forma: un distrito, una provincia
// entera aunque el mapa muestre distritos, o un departamento. Si falta su
// forma (distritos creados después del mapa base), usa la de quien la contiene.
function areaShape(D, code) {
  for (const c of [code, code.slice(0, 4), code.slice(0, 2)]) {
    const d = c.length === 2 ? D.peru.departments.find((x) => x.code === c)?.d : (c.length === 4 ? D.map.provinces : D.map.districts)[c]?.d;
    if (d) return d;
  }
  return '';
}

// Va al final del SVG para que ningún borde vecino ni el contorno de los
// departamentos lo tape.
function selRing(d) {
  return d ? `<g class="sel-ring" aria-hidden="true"><path class="sel-glow" d="${d}"></path><path class="sel-case" d="${d}"></path><path class="sel-line" d="${d}"></path></g>` : '';
}

function mapSvg(D, s, stats, scale, { small = false, label = '' } = {}) {
  const shapes = shapesFor(D, s.nivel);
  const focusable = s.nivel === 'departamento' && !small;
  const paths = shapes.map(([code, d]) => {
    const st = stats.get(code);
    const cls = scale.cls(metricValue(st, s.metrica), st);
    const sel = s.area && (code === s.area || s.area.startsWith(code) || code.startsWith(s.area)) ? ' sel' : '';
    return `<path class="hz-a hz-${cls}${sel}" d="${d}" data-code="${code}"${focusable ? ` tabindex="0" role="button" aria-label="${esc(shortName(D, code))}: ${esc(metricText(st, s.metrica))}"` : ''}></path>`;
  }).join('');
  const outline = s.nivel === 'departamento' ? '' : `<g class="hz-out" aria-hidden="true">${D.peru.departments.map((d) => `<path d="${d.d}"></path>`).join('')}</g>`;
  const ring = s.area && !small ? selRing(areaShape(D, s.area)) : '';
  const vb = small ? `0 0 ${D.peru.width} ${D.peru.height}` : viewBoxFor(D, s);
  return `<svg class="hz-svg${small ? ' hz-small' : ''}" viewBox="${vb}" role="${small ? 'img' : 'group'}" aria-label="${esc(label)}" preserveAspectRatio="xMidYMid meet"><g>${paths}</g>${outline}${ring}</svg>`;
}

function legendHtml(scale, metric) {
  const title = METRICS.find(([k]) => k === metric)?.[1] || '';
  return html`<div class="hz-legend" aria-label="Leyenda: ${title}"><span class="hz-legend-t">${title}</span><ul>${scale.legend.map(([c, t]) => html`<li><span class="hz-sw hz-${c}"></span>${t}</li>`)}</ul></div>`;
}

// ---------------------------------------------------------------------------
// Línea de tiempo por temporada (julio–junio)
// ---------------------------------------------------------------------------
function timeline(D, recs, { compact = false, from = 1970, to = null } = {}) {
  const by = M.byYear(recs);
  // Sin «Math.max(...recs)»: con 146 000 registros desborda la pila de llamadas.
  const last = to || D.recs.reduce((m, r) => (r.hy > m ? r.hy : m), from);
  const years = [];
  for (let y = from; y <= last; y++) years.push(y);
  const max = Math.max(1, ...years.map((y) => by.get(y)?.da.size || 0));
  // El SVG se estira a lo ancho (preserveAspectRatio="none"): un ancho lógico cercano al real evita que las
  // etiquetas se deformen (la ficha lateral mide unos 500 px; la línea principal, unos 1 100).
  const W = compact ? 500 : 1000, H = compact ? 74 : 124, bw = W / years.length;
  const named = new Map([[1982, '1982-83'], [1997, '1997-98'], [2016, '2017'], [2022, '2023'], [1972, '1972-73'], [2025, '2026']]);
  const bars = years.map((y, i) => {
    const o = by.get(y);
    const v = o ? o.da.size : 0;
    const h = (v / max) * (H - 2);
    const nino = D.nino.has(y);
    const label = `Temporada ${y}-${String(y + 1).slice(2)}: ${v} lugares con daños, ${o ? o.n : 0} registros${o?.muertos ? `, ${o.muertos} fallecidos y desaparecidos` : ''}${nino ? '. Niño costero en el pico de lluvias (enero a marzo)' : ''}`;
    return `${nino ? `<rect class="hz-tl-nino" x="${(i * bw).toFixed(1)}" y="0" width="${bw.toFixed(1)}" height="${H}"></rect>` : ''}<rect class="hz-tl-bar" x="${(i * bw + bw * 0.15).toFixed(1)}" y="${(H - h).toFixed(1)}" width="${(bw * 0.7).toFixed(1)}" height="${h.toFixed(1)}" data-tip="${esc(label)}"><title>${esc(label)}</title></rect>`;
  }).join('');
  // La primera etiqueta va alineada a la izquierda para que no se corte en el borde.
  const at = (y) => (((y - from) + 0.5) / years.length) * 100;
  const ticks = years.filter((y) => y % 10 === 0).map((y) => (y === from ? { x: 0, text: y, edge: 'start' } : { x: at(y), text: y }));
  // En pantallas angostas se ocultan los nombres secundarios (1972-73 y 2026) para que no se encimen.
  const names = compact ? [] : years.filter((y) => named.has(y) && (by.get(y)?.da.size || 0) > 0)
    .map((y) => ({ x: at(y), text: named.get(y), top: true, minor: y === 1972 || y === 2025 }));
  const svg = `<svg class="hz-tl${compact ? ' hz-tl-c' : ''}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Lugares con daños por temporada de lluvias, ${from}-${last}. Las franjas marcan temporadas con El Niño costero de enero a marzo.">${bars}</svg>`;
  return labelled(svg, [...ticks, ...names], { compact, names: names.length > 0 });
}

/** Etiquetas en HTML encima de un SVG estirado a lo ancho: el texto no se deforma con el ancho de la pantalla.
 *  ``x`` va en porcentaje del ancho; ``edge`` alinea la etiqueta al borde izquierdo o derecho. */
function labelled(svg, labels, { compact = false, names = false } = {}) {
  const spans = labels.map(({ x, text, top, edge, minor }) => `<span class="hz-tl-l${top ? ' hz-tl-n' : ' hz-tl-x'}${minor ? ' hz-tl-minor' : ''}"${edge ? ` data-a="${edge}"` : ''} style="left:${x.toFixed(2)}%" aria-hidden="true">${esc(String(text))}</span>`).join('');
  return `<div class="hz-tlw${compact ? ' hz-tlw-c' : ''}${names ? ' hz-tlw-n' : ''}">${svg}${spans}</div>`;
}

// ---------------------------------------------------------------------------
// Vista
// ---------------------------------------------------------------------------
export const memoriaView = {
  title: 'Memoria de desastres',
  render() {
    return html`
      <div class="page-head"><div class="eyebrow">Memoria de desastres · 1559–2026</div><h1>Dónde golpearon antes El Niño, las lluvias y los huaycos</h1>
        <p>Catálogo de inundaciones, desbordes, huaycos, deslizamientos, lluvias intensas, oleajes, sequías, heladas y otros desastres de origen climático en el Perú, ubicados por distrito y con su fuente. Sirve para prepararse con evidencia: con qué frecuencia golpearon antes, cuánto aumentan con El Niño costero y qué tan bien esa historia anticipó los daños de 2016 a 2025, que se muestra abajo.</p></div>
      <div id="hz-root" data-tour-id="memoria"><div class="skeleton" aria-hidden="true"></div><p class="muted">Cargando el catálogo histórico…</p></div>`;
  },
  async after() {
    const root = $('#hz-root');
    let D;
    try { D = await loadAll(); } catch (e) {
      console.error(e);
      root.innerHTML = String(html`<div class="notice notice-warn">${raw(ICON.triangle)}<p>No se pudo cargar el catálogo histórico. Puede descargarlo directamente: <a href="${BASE}eventos.zip" download>CSV (en un ZIP)</a>.</p></div>`);
      return;
    }
    mount(root, D);
  },
};

function mount(root, D) {
  let s = readState();
  const set = (partial, sel) => { s = { ...s, ...partial }; draw(sel); };
  const draw = (focusSel) => {
    writeState(s);
    root.innerHTML = String(page(D, s));
    wire(root, D, s, set);
    if (focusSel) $(focusSel, root)?.focus({ preventScroll: true });
    if (s.area) { fillDetail(root, D, s); fillContext(root, D, s); fillPrevArea(root, D, s); }
    fillLayers(root, D, s);
    fillPrevention(root, D);
  };
  // Clic delegado en rankings, enlaces de área y cierre del perfil. root sobrevive a cada redibujo, así que se
  // registra una sola vez por montaje (en wire se sumaría un manejador por redibujo).
  root.addEventListener('click', (e) => {
    const b = e.target.closest('[data-area]');
    if (!b || b.closest('svg')) return;
    const area = b.dataset.area;
    const nivel = b.dataset.nivelGo || (area && area.length === 6 && s.nivel !== 'distrito' ? 'distrito' : area && area.length === 4 && s.nivel === 'departamento' ? 'provincia' : s.nivel);
    set({ area, nivel }, '#hz-side');
    if (area) $('#hz-map-h', root)?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
  });
  draw();
}

function currentFilter(D, s) {
  const types = s.peligro ? new Set(HAZARD_GROUPS[s.peligro]?.[1] || [s.peligro]) : null;
  return { types, event: s.evento, from: +s.desde || 0, to: +s.hasta || 0, great: D.great };
}

function page(D, s) {
  const f = currentFilter(D, s);
  const recs = M.filter(D.recs, f);
  const years = M.coverageYears(D.sum.cobertura.homogenea, f.from, f.to);
  const stats = statsFor(D, s, recs, years);
  const vals = [...stats.values()].map((st) => metricValue(st, s.metrica)).filter((v) => v !== null);
  const scale = scaleFor(s.metrica, vals, s.nivel);
  const evOpts = [['', 'Todos los registros'], ['grandes', 'Solo los grandes Niños'], ...D.great.map((g) => [g, g]), ...(D.ongoing ? [[D.ongoing, `${D.ongoing} (en curso)`]] : []), ['nino', 'Cualquier Niño costero'], ['nina', 'La Niña costera'], ['neutro', 'Años neutros']];
  const yMin = D.sum.cobertura.anios[0], yMax = D.sum.cobertura.anios[1];
  const label = `Mapa por ${s.nivel}: ${METRICS.find(([k]) => k === s.metrica)[1]}`;
  const nat = M.summarize(recs, years, D.nino, D.great, D.hom);
  if (s.evento) dropRR(nat);
  return html`
    ${contextBanner(D)}
    ${howToSection(D)}
    <section class="card hz-card" aria-labelledby="hz-map-h">
      <div class="section-head"><h2 id="hz-map-h">Mapa de la memoria</h2><span class="muted small">${n0(recs.length)} de ${n0(D.recs.length)} registros</span></div>
      <form class="hz-filters" id="hz-filters" aria-label="Filtros del mapa">
        <label class="hz-f"><span>Evento</span><select class="input" name="evento">${evOpts.map(([v, t]) => html`<option value="${v}" ${v === s.evento ? raw('selected') : ''}>${t}</option>`)}</select></label>
        <label class="hz-f"><span>Peligro</span><select class="input" name="peligro"><option value="">Todos</option>${Object.entries(HAZARD_GROUPS).map(([k, [t]]) => html`<option value="${k}" ${k === s.peligro ? raw('selected') : ''}>${t}</option>`)}
          <optgroup label="Un tipo">${Object.keys(DANGER_LABEL).map((t) => html`<option value="${t}" ${t === s.peligro ? raw('selected') : ''}>${dl(t)}</option>`)}</optgroup></select></label>
        <label class="hz-f hz-f-s" title="Temporadas de julio a junio por su año de inicio: 1997 es julio de 1997 a junio de 1998"><span>Desde temporada</span><input class="input" name="desde" type="number" inputmode="numeric" min="${yMin}" max="${yMax}" placeholder="${yMin}" value="${s.desde}"></label>
        <label class="hz-f hz-f-s" title="Temporadas de julio a junio por su año de inicio: 1997 es julio de 1997 a junio de 1998"><span>Hasta temporada</span><input class="input" name="hasta" type="number" inputmode="numeric" min="${yMin}" max="${yMax}" placeholder="${yMax}" value="${s.hasta}"></label>
        <label class="hz-f"><span>Mostrar</span><select class="input" name="metrica">${METRICS.map(([v, t]) => html`<option value="${v}" ${v === s.metrica ? raw('selected') : ''}>${t}</option>`)}</select></label>
        <div class="hz-f hz-f-lvl"><span id="hz-lvl-l">Nivel</span><div class="seg" role="group" aria-labelledby="hz-lvl-l">${LEVEL_NAMES.map(([v, t]) => html`<button type="button" data-nivel="${v}" aria-pressed="${String(v === s.nivel)}">${t}</button>`)}</div></div>
        <div class="hz-f hz-search"><label for="hz-q"><span>Buscar lugar</span></label><input class="input" id="hz-q" list="hz-places" placeholder="Distrito, provincia o departamento" autocomplete="off"><datalist id="hz-places"></datalist></div>
        ${s.evento || s.peligro || s.desde || s.hasta || s.area ? html`<button type="button" class="btn ghost hz-clear" data-clear>Quitar filtros</button>` : ''}
      </form>
      <div class="hz-grid">
        <div class="hz-mapbox">
          ${raw(mapSvg(D, s, stats, scale, { label }))}
          <div class="hz-tip" role="tooltip" hidden></div>
          ${s.area && s.nivel !== 'departamento' ? html`<button type="button" class="btn ghost hz-zoomout" data-area="">${raw(ICON.globe)}<span>Ver todo el Perú</span></button>` : ''}
          ${legendHtml(scale, s.metrica)}
          <div class="hz-layers" role="group" aria-label="Capas del mapa"><button type="button" class="kind-chip" data-layer="cuencas" aria-pressed="${String(s.cuencas === '1')}"><span class="hz-sw-basin" aria-hidden="true"></span>Cuencas (ANA)</button>
            <span class="muted small" id="hz-pts-note">${s.area ? 'Cargando los puntos de los registros…' : 'Elija un área para ver sus registros como puntos: el punto de campo de la fuente, el centro poblado o el río que nombran.'}</span></div>
          <p class="muted small">${s.nivel === 'departamento' ? 'Toque un departamento para ver su ficha.' : 'Toque un área para ver su ficha y acercar el mapa a su departamento. También puede buscarla arriba o elegirla en la tabla.'} Los registros a escala de departamento no se pintan en provincias ni distritos. Desde y hasta son temporadas de julio a junio (1997 = 1997-98).${s.evento ? ' Con un filtro de evento, «años con daños» cuenta solo los años con registros de ese evento y la razón de El Niño no aplica.' : ''}</p>
        </div>
        <aside class="hz-side" id="hz-side" aria-live="polite">${s.area ? profileShell(D, s, recs, years) : nationalCard(D, nat, recs, years, s)}</aside>
      </div>
    </section>
    <section class="card hz-card" aria-labelledby="hz-tl-h">
      <div class="section-head"><h2 id="hz-tl-h">Lugares con daños en cada temporada de lluvias</h2></div>
      <p class="muted small">Cada barra es una temporada (julio a junio): cuántos lugares distintos tuvieron registros con los filtros elegidos. Franja rosada: Niño costero en el pico de lluvias (ICEN medio de enero a marzo mayor que +0,5 °C, el umbral de condición cálida del ENFEN). Las fuentes cambian con el tiempo y las barras no se comparan directamente: DesInventar hasta 2015 (menos registros antes de 1990) y, desde 2016, el SINPAD del INDECI, que registra muchas más emergencias por año. Ver «Límites».</p>
      ${raw(timeline(D, recs))}
    </section>
    ${greatSection(D, s)}
    ${rankingSection(D, s, stats)}
    ${validationSection(D)}
    <section class="card hz-card" id="hz-prev" aria-labelledby="hz-prev-h"><div class="section-head"><h2 id="hz-prev-h">¿Se sabía antes? Peligros documentados antes de cada emergencia</h2></div><p class="muted">Cargando declaratorias, evaluaciones e inventarios…</p></section>
    ${pastSection(D)}
    ${evidenceSection(D)}
    ${methodSection(D)}`;
}

/** Departamentos donde, en 1970-2015, las temporadas con Niño costero tuvieron claramente más lugares con daños. */
function ninoHotspots(D) {
  return [...baseline(D).departamento.entries()].filter(([, st]) => rrSign(st) === 1).sort((a, b) => b[1].razonNino - a[1].razonNino);
}

function contextBanner(D) {
  const cur = D.sum.eventosICEN.filter((e) => e.fase === 'warm').at(-1);
  const last = D.sum.icenUltimo;
  if (!cur || !cur.enCurso) return '';
  const strong = ['fuerte', 'extraordinaria'].includes(cur.magnitud);
  const hot = ninoHotspots(D);
  return html`<div class="notice ${strong ? 'notice-alert' : 'notice-warn'} hz-context" role="note">${raw(ICON.triangle)}
    <p><strong>El Niño costero está en curso desde ${F.fmtMonth(cur.inicio)}${last ? html`; el ICEN de ${F.fmtMonth(last[0])} fue ${F.fmtValue(last[1], 'degC')}, magnitud ${cur.magnitud}` : ''}.</strong>
    ${strong ? 'Con el ICEN preliminar de los últimos meses, es la misma categoría que alcanzaron 1982-83 y 1997-98.' : ''}
    ${hot.length ? html`<strong>Alerta según la historia:</strong> en 1970-2015, las temporadas con Niño costero tuvieron claramente más lugares con daños por año en ${hot.map(([c, st], i) => html`${i ? (i === hot.length - 1 ? ' y ' : ', ') : ''}<button type="button" class="linkish" data-area="${c}">${shortName(D, c)}</button> (${x1(st.razonNino)})`)}; el efecto se repitió en 2016-2025 (ver «¿La historia anticipa lo que vino después?»).` : ''}
    Use «Solo los grandes Niños» en el mapa para ver dónde golpearon los eventos anteriores. Las alertas oficiales son las del ENFEN, el SENAMHI y el INDECI.</p></div>`;
}

/** Guía de lectura: qué dice cada cifra, para qué sirve y qué no se puede concluir de ella. */
function howToSection(D) {
  const v = D.sum.validacion;
  const prov = v?.discriminacion?.find((d) => d.nivel === 'provincia' && d.peligros === 'todos');
  const dist = v?.discriminacion?.find((d) => d.nivel === 'distrito' && d.peligros === 'todos');
  const auc = (d) => (d ? F.fmtNumber(d.auc, 2) : 'N/D');
  return html`<details class="card hz-card hz-howto" open><summary><h2 class="hz-howto-h">Cómo usar esta pestaña</h2></summary>
    <div class="grid g2">
      <div>
        <h3 class="hz-h3">Para qué sirve</h3>
        <ul class="hz-method">
          <li><strong>Saber qué pasó y dónde.</strong> Cada registro tiene fecha, lugar, peligro y fuente. Es la parte más sólida: hechos documentados.</li>
          <li><strong>Comparar provincias y peligros.</strong> Los años con daños de 1970-2015 ordenan bien las provincias según lo que vino después (AUC ${auc(prov)}; 0,5 es azar), sobre todo para heladas y huaycos. Úselos para decidir dónde mirar primero.</li>
          <li><strong>Saber dónde El Niño costero empeora las cosas.</strong> La razón de El Niño dice cuántos más lugares con daños por año hubo en temporadas con Niño. Donde su intervalo queda sobre 1, el efecto es claro y se repitió en 2016-2025.</li>
          <li><strong>Ver qué se conocía.</strong> El peligro identificado hoy (INGEMMET, ANA) y las declaratorias complementan la historia: los puntos de peligro del INGEMMET anticipan las emergencias graves mejor que la frecuencia histórica.</li>
        </ul>
      </div>
      <div>
        <h3 class="hz-h3">Qué no concluir</h3>
        <ul class="hz-method">
          <li><strong>Un distrito sin registros no es un distrito sin peligro.</strong> DesInventar se armó con prensa e informes: hay más registros donde hay más gente y acceso.</li>
          <li><strong>«1 de cada X años» y «probabilidad en 5 años» no son pronósticos.</strong> Son frecuencias del pasado con su intervalo. Por distrito anticipan poco (AUC ${auc(dist)}) y exageran en los extremos: donde marcan 0 %, uno de cada seis distritos tuvo daños en los 5 años siguientes.</li>
          <li><strong>La razón de El Niño cuenta lugares con registros, no la magnitud del daño.</strong> Y no compara grandes Niños entre sí: cada uno viene de fuentes con densidad distinta.</li>
          <li><strong>Las cifras de impacto son las reportadas.</strong> Un vacío es «no reportado», no cero.</li>
          <li><strong>Las alertas oficiales son del ENFEN, el SENAMHI y el INDECI.</strong> Esta pestaña da contexto histórico.</li>
        </ul>
      </div>
    </div>
  </details>`;
}

function nationalCard(D, st, recs, years, s) {
  const byDep = statsFor(D, s, recs, years, 'departamento');
  const top = [...byDep.entries()].filter(([, v]) => rrSign(v) === 1).sort((a, b) => b[1].razonNino - a[1].razonNino).slice(0, 8);
  return html`<div class="hz-prof">
    <h3 class="hz-prof-h">Todo el Perú</h3>
    <div class="hz-tiles">
      <div class="hz-tile"><span class="hz-tile-v">${n0(st.registros)}</span><span class="hz-tile-l">registros con los filtros elegidos</span></div>
      <div class="hz-tile"><span class="hz-tile-v">${n0(st.muertos)}</span><span class="hz-tile-l">fallecidos y desaparecidos reportados</span></div>
      <div class="hz-tile"><span class="hz-tile-v">${n0(st.viviendas)}</span><span class="hz-tile-l">viviendas destruidas reportadas</span></div>
      <div class="hz-tile"><span class="hz-tile-v">${st.razonNino ? x1(st.razonNino) : 'N/D'}</span><span class="hz-tile-l">${st.razonNino ? `lugares con daños por año en temporadas con Niño costero frente a las demás (1970-2015; IC 95 %: ${F.fmtNumber(st.razonNinoIC[0], 1)}–${F.fmtNumber(st.razonNinoIC[1], 1)}${rrSign(st) === 0 ? ', sin diferencia clara' : ''})` : 'razón de El Niño: no aplica con un filtro de evento o faltan datos'}</span></div>
    </div>
    ${top.length ? html`<h4 class="hz-h4">Donde El Niño costero aumentó claramente los lugares con daños</h4>
      <ol class="hz-bars">${top.map(([c, v]) => html`<li><button type="button" class="linkish" data-area="${c}">${shortName(D, c)}</button><span class="hz-bar"><span style="width:${Math.min(100, (v.razonNino / top[0][1].razonNino) * 100).toFixed(0)}%"></span></span><span class="hz-bar-v">${x1(v.razonNino)}</span></li>`)}</ol>
      <p class="muted small">Razón entre los lugares con daños por año en temporadas con Niño costero (enero a marzo) y en las demás, solo donde todo su intervalo al 95 % queda sobre 1. El intervalo tiene en cuenta que los distritos de un mismo año no son independientes (cuasi-Poisson).</p>` : ''}
    <p class="muted small">Elija un área en el mapa, en la tabla o con el buscador para ver su historia, sus indicadores y qué esperar si se repite un gran Niño.</p>
  </div>`;
}

function profileShell(D, s, recs, years) {
  const code = s.area;
  const mine = recs.filter((r) => r.u.startsWith(code));
  const lvl = code.length === 6 ? 'distrito' : code.length === 4 ? 'provincia' : 'departamento';
  const st = M.summarize(mine, years, D.nino, D.great, D.hom);
  if (s.evento) dropRR(st);
  const pop = population(D, code);
  const a = code.length === 6 ? D.attrs.get(code) : null;
  const months = new Array(12).fill(0);
  for (const r of mine) if (r.m) months[r.m - 1]++;
  const peakM = months.map((v, i) => [v, i]).sort((x, y) => y[0] - x[0]).filter(([v]) => v > 0).slice(0, 2).map(([, i]) => F.MESES[i]);
  const greatRecs = mine.filter((r) => D.great.includes(r.e));
  const now = D.ongoing ? mine.filter((r) => r.e === D.ongoing) : [];
  const typeCount = new Map();
  for (const r of greatRecs) typeCount.set(r.t, (typeCount.get(r.t) || 0) + 1);
  const greatTypes = [...typeCount.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3).map(([t]) => dl(t));
  const hz = st.peligros.slice(0, 6);
  const maxHz = hz[0]?.[1] || 1;
  const parents = code.length > 2 ? html`<p class="muted small">${code.length === 6 ? html`Provincia de <button type="button" class="linkish" data-area="${code.slice(0, 4)}">${D.sum.nombres.provincia[code.slice(0, 4)]}</button> · ` : ''}Departamento de <button type="button" class="linkish" data-area="${code.slice(0, 2)}">${D.sum.nombres.departamento[code.slice(0, 2)]}</button></p>` : '';
  const rep = repeatEvidence(D, code, st);
  const sign = rrSign(st);
  const expect = st.registros ? html`<div class="hz-expect"><h4 class="hz-h4">Si se repite un gran Niño</h4><p>${greatRecs.length
    ? html`En ${st.grandesNinos.join(', ')} hubo registros aquí, sobre todo de ${greatTypes.join(', ').toLowerCase()}.`
    : 'Los grandes Niños no dejaron registros aquí en las fuentes del catálogo; eso no garantiza que no ocurra (la cobertura es incompleta).'} ${rep} ${peakM.length ? `Los meses con más registros son ${peakM.join(' y ')}.` : ''} ${sign === 1 ? `En temporadas con Niño costero hubo ${x1(st.razonNino)} lugares con daños por año que en las demás (IC 95 %: ${F.fmtNumber(st.razonNinoIC[0], 1)}–${F.fmtNumber(st.razonNinoIC[1], 1)}).` : sign === -1 ? 'Aquí los daños fueron menos frecuentes en temporadas con Niño costero (en la sierra sur el Niño suele traer sequía en lugar de lluvias).' : sign === 0 ? 'Aquí la frecuencia de daños no cambia de forma clara con El Niño costero (el intervalo incluye 1).' : ''}</p></div>` : '';
  return html`<div class="hz-prof">
    <div class="hz-prof-top"><h3 class="hz-prof-h">${shortName(D, code)} <span class="muted small">(${lvl})</span></h3><button type="button" class="icon-btn" data-area="" aria-label="Cerrar la ficha">${raw(ICON.close)}</button></div>
    ${parents}
    <p class="hz-prof-meta">${freqChip(st)} ${pop ? html`<span class="muted small">Población 2020 ≈ ${n0(pop)}${a?.[1] ? ` · pobreza ${F.fmtNumber(a[1], 0)} %` : ''}${a?.[3] ? ` · ${n0(a[3])} m s. n. m.` : ''}</span>` : ''}</p>
    <div class="hz-tiles">
      <div class="hz-tile"><span class="hz-tile-v">${st.aniosConEvento} <small>de ${st.aniosCobertura}</small></span><span class="hz-tile-l">años con registros en DesInventar (1970-2015)${st.aniosCobertura ? `; IC 95 %: ${pctRange(st.frecuenciaIC)} de los años` : ''}${st.muestraPequena ? ' · muestra pequeña' : ''}</span></div>
      <div class="hz-tile"><span class="hz-tile-v">${st.periodoRetorno ? `1 de cada ${rp(st.periodoRetorno)}` : st.aniosCobertura ? 'Ninguno' : 'N/D'}</span><span class="hz-tile-l">${st.aniosCobertura ? `años, en promedio; con el intervalo, 1 de cada ${span(st.periodoRetornoIC[0], st.periodoRetornoIC[1], rp)} (frecuencia del pasado, no pronóstico)` : 'fuera del periodo con frecuencia'}</span></div>
      <div class="hz-tile"><span class="hz-tile-v">${st.aniosCobertura ? pctRange(st.prob5AniosIC) : 'N/D'}</span><span class="hz-tile-l">de probabilidad de al menos un año con daños en 5 años si se repitiera la frecuencia de 1970-2015 (intervalo al 95 %; ver «¿La historia anticipa…?»)</span></div>
      <div class="hz-tile"><span class="hz-tile-v">${st.grandesNinos.length} <small>de ${D.great.length}</small></span><span class="hz-tile-l">grandes Niños con registros aquí</span></div>
    </div>
    <ul class="hz-great">${D.great.map((g) => html`<li class="${st.grandesNinos.includes(g) ? 'hit' : ''}">${raw(st.grandesNinos.includes(g) ? ICON.check : ICON.dash)}<span>${g}</span></li>`)}</ul>
    ${now.length ? html`<p class="hz-now">${raw(ICON.triangle)}<span><strong>${D.ongoing}:</strong> ${n0(now.length)} registro${now.length > 1 ? 's' : ''} aquí desde ${F.fmtMonth(now.map((r) => r.d).sort()[0])}, el último el ${when(now.map((r) => r.d).sort().at(-1))}.</span></p>` : ''}
    ${expect}
    <div id="hz-ctx"></div>
    <div id="hz-prevbox"></div>
    <dl class="hz-kv"><div><dt>Fallecidos y desaparecidos</dt><dd>${n0(st.muertos)}</dd></div><div><dt>Afectados, damnificados o desplazados</dt><dd>${n0(st.afectados)}</dd></div><div><dt>Viviendas destruidas</dt><dd>${n0(st.viviendas)}</dd></div><div><dt>Lugares con daños por año con Niño costero</dt><dd>${metricText(st, 'razon')}</dd></div></dl>
    ${hz.length ? html`<h4 class="hz-h4">Peligros registrados</h4><ol class="hz-bars">${hz.map(([t, v]) => html`<li><span>${dl(t)}</span><span class="hz-bar"><span style="width:${((v / maxHz) * 100).toFixed(0)}%"></span></span><span class="hz-bar-v">${n0(v)}</span></li>`)}</ol>` : ''}
    <h4 class="hz-h4">Temporadas con daños aquí</h4>
    ${raw(timeline(D, mine, { compact: true }))}
    <h4 class="hz-h4">Registros (${n0(mine.length)})</h4>
    <div id="hz-list"><p class="muted small">Cargando descripciones y fuentes…</p></div>
  </div>`;
}

/** Lo que pasó en 2017 con los distritos de la misma región según cuántos grandes Niños los golpearon antes. */
function repeatEvidence(D, code, st) {
  const R = D.sum.validacion?.grandesNinos || [];
  const dep = code.slice(0, 2);
  const reg = R.find((r) => r.region.startsWith('costa norte') && ['24', '20', '14', '13'].includes(dep)) || R.find((r) => !r.region.startsWith('costa norte') && D.sum.eventosNombrados.find((e) => e.nombre === r.despues)?.departamentos?.includes(dep));
  if (!reg || code.length !== 6) return '';
  const both = reg.grupos.find((g) => g.golpeados === 'en los dos'), none = reg.grupos.find((g) => g.golpeados === 'en ninguno');
  const hit = ['FEN 1982-83', 'FEN 1997-98'].filter((g) => st.grandesNinos.includes(g)).length;
  return `En ${reg.region.startsWith('costa') ? 'la' : 'los'} ${reg.region}, de los distritos golpeados en 1982-83 y en 1997-98, el ${pct(both.conRegistros)} volvió a tener registros en el Niño Costero 2017, frente al ${pct(none.conRegistros)} de los que no tuvieron registros en ninguno de los dos (${n0(both.distritos)} y ${n0(none.distritos)} distritos). Este distrito tuvo registros en ${hit === 2 ? 'los dos' : hit === 1 ? 'uno de los dos' : 'ninguno de los dos'}.`;
}

async function fillDetail(root, D, s) {
  const box = $('#hz-list', root);
  if (!box) return;
  const f = currentFilter(D, s);
  const mine = M.filter(D.recs, f).filter((r) => r.u.startsWith(s.area));
  const sorted = [...mine].sort((a, b) => (b.muertos + b.viv / 10 + (D.great.includes(b.e) ? 1000 : 0)) - (a.muertos + a.viv / 10 + (D.great.includes(a.e) ? 1000 : 0)) || b.d.localeCompare(a.d));
  const det = await detail(s.area.slice(0, 2));
  const B = await basins();
  if (!box.isConnected) return;
  let shown = 12;
  /** Dónde, más fino que el distrito: el punto de la fuente, el centro poblado o el río que nombra, y la cuenca (la
   * del punto, la del río que nombra o la del distrito si el 80 % o más de él está en una). Si la fuente dio un punto
   * por defecto (la capital, o uno que repite en todo el distrito), se dice. */
  const fine = (r, g) => {
    const basin = B.units[(g && g[5]) || B.districts[r.u]]?.n;
    const km = (v) => `±${F.fmtNumber(v, v % 1 ? 1 : 0)} km`;
    const water = g && g[6] && g[2] !== 3 ? `nombra ${g[6]}` : '';
    const where = g && g[2] === 1 ? `centro poblado ${g[3]} (${km(g[4])})`
      : g && g[2] === 3 ? `${g[6]} (su tramo en el distrito, ${km(g[4])})`
        : g && g[2] === 0 ? `punto de campo de la fuente${g[3] ? `, en ${g[3]}` : ''}` : g && g[3] ? `nombra ${g[3]}` : '';
    const dropped = g && g[7] ? DROPPED[g[7]] : '';
    return [where, water, basin, dropped].filter(Boolean).join(' · ');
  };
  const item = (r) => {
    const d = det[String(r.i)] || [];
    const [desc, , cite, url, dur] = d;
    const more = d[10] || 0, links = d[11] || [], kind = DATE_KIND[d[12]];
    const place = fine(r, d[13]);
    return html`<li class="hz-ev"><div class="hz-ev-top"><span class="hz-ev-d">${when(r.d)}</span>${kind ? html`<span class="muted small">(${kind})</span>` : ''}<span class="tag">${dl(r.t)}</span>${r.e && !/^(Sin asociación|Temporada)/.test(r.e) ? html`<span class="tag tag-warm">${r.e}</span>` : ''}${r.o === 'curado' ? html`<span class="tag">curado</span>` : ''}${r.e === D.ongoing ? html`<span class="tag tag-warm">en curso</span>` : ''}</div>
      <p class="hz-ev-where">${areaName(D, r.u)}${dur ? ` · ${dur} día${dur > 1 ? 's' : ''}` : ''}</p>
      ${place ? html`<p class="small hz-ev-fine">${raw(ICON.pin)}<span>${place}</span></p>` : ''}
      ${desc ? html`<p class="hz-ev-t">${desc.length > 420 ? `${desc.slice(0, 420)}…` : desc}</p>` : ''}
      ${r.muertos || r.afect || r.viv ? html`<p class="small">${[r.muertos ? `${n0(r.muertos)} fallecidos o desaparecidos` : '', r.afect ? `${n0(r.afect)} afectados o damnificados` : '', r.viv ? `${n0(r.viv)} viviendas destruidas` : ''].filter(Boolean).join(' · ')}</p>` : ''}
      <p class="muted small">Fuente: ${cite || 'ver enlace'} ${url ? html`· <a href="${safeUrl(url)}" rel="noopener" target="_blank">${SOURCE_LINK[r.o] || 'documento'}</a>` : ''}</p>
      ${more ? html`<p class="small hz-corr">${raw(ICON.check)}<span>También lo ${more > 1 ? `cuentan ${n0(more)} reportes o notas` : 'cuenta otro reporte o nota'}${links.length ? ': ' : '.'}${corrLinks(links)}</span></p>` : ''}</li>`;
  };
  const paint = () => {
    box.innerHTML = String(html`<ol class="hz-evs">${sorted.slice(0, shown).map(item)}</ol>${sorted.length > shown ? html`<button type="button" class="btn ghost" id="hz-more">Ver ${Math.min(30, sorted.length - shown)} más (quedan ${n0(sorted.length - shown)})</button>` : ''}`);
    $('#hz-more', box)?.addEventListener('click', () => { shown += 30; paint(); });
  };
  paint();
}

// ---------------------------------------------------------------------------
// Capas del mapa: cuencas y puntos de los registros
// ---------------------------------------------------------------------------
const SVG_NS = 'http://www.w3.org/2000/svg';
/** Cómo se ubicó el punto de un registro (posición 13 del detalle, tools.build_historico._web_place). */
const POINT_KIND = ['punto de campo de la fuente', 'centro poblado que nombra el registro', 'capital del distrito', 'río, quebrada o laguna que nombra el registro (su tramo en el distrito)'];
/** Por qué no se usó el punto que dio la fuente (posición 7 del lugar). */
const DROPPED = { capital: 'el punto de la fuente era la capital (uno por defecto)', repetido: 'el punto de la fuente era uno que repite en todo el distrito', fuera: 'el punto de la fuente caía fuera del área' };

/** Proyección de peru-map.json (tools.build_peru_map): grados → coordenadas del SVG. */
function project(D, lat, lon) {
  const p = D.peru.lonLat;
  return [(lon - p.lon0) * p.cos * p.k, (p.lat1 - lat) * p.k];
}

/** Agrega una capa al mapa debajo del anillo del área elegida, que siempre va al final para que nada lo tape. */
function addLayer(svg, cls, markup) {
  svg.querySelector(`g.${cls}`)?.remove();
  const g = document.createElementNS(SVG_NS, 'g');
  g.setAttribute('class', cls);
  g.innerHTML = markup;
  svg.insertBefore(g, svg.querySelector(':scope > .sel-ring'));
}

/** Las cuencas (si se pidieron) y, con un área elegida, sus registros ubicados más fino que el distrito. */
async function fillLayers(root, D, s) {
  const svg = $('.hz-mapbox .hz-svg', root);
  if (!svg) return;
  const vb = svg.viewBox.baseVal;
  const unit = Math.max(vb.width, vb.height * 0.75) / 507;  // 1 en el mapa de todo el Perú, menos al acercarse
  if (s.cuencas === '1') {
    const B = await basins();
    if (!svg.isConnected) return;
    addLayer(svg, 'hz-basins', Object.entries(B.units).map(([c, u]) => `<path d="${u.d}" data-tip="${esc(`${u.n}\nUnidad hidrográfica ${c} de la ANA (Pfafstetter)`)}"></path>`).join(''));
  }
  const note = $('#hz-pts-note', root);
  if (!s.area) return;
  const det = await detail(s.area.slice(0, 2));
  const B = await basins();
  if (!svg.isConnected) return;
  const mine = M.filter(D.recs, currentFilter(D, s)).filter((r) => r.u.startsWith(s.area));
  const at = new Map();
  let n0_ = 0, n1 = 0, n3 = 0;
  for (const r of mine) {
    const g = (det[String(r.i)] || [])[13];
    if (!g || g[0] === null || g[2] === 2) continue;
    if (g[2] === 3) n3++; else if (g[2]) n1++; else n0_++;
    const k = `${g[0].toFixed(3)},${g[1].toFixed(3)},${g[2]}`;
    const spot = at.get(k) || { g, recs: [] };
    spot.recs.push(r);
    at.set(k, spot);
  }
  const spots = [...at.values()].sort((a, b) => b.recs.length - a.recs.length);
  addLayer(svg, 'hz-pts', spots.map(({ g, recs }) => {
    const [x, y] = project(D, g[0], g[1]);
    const r = unit * (2.2 + 1.3 * Math.sqrt(recs.length - 1));
    const basin = g[5] && B.units[g[5]] ? B.units[g[5]].n : '';
    const years = [...new Set(recs.map((q) => q.y))].sort();
    const tipText = [(g[2] === 3 ? g[6] : g[3]) || (g[2] ? 'Centro poblado' : 'Punto de la fuente'),
      `${recs.length} registro${recs.length > 1 ? 's' : ''} (${years.length > 1 ? `${years[0]}–${years.at(-1)}` : years[0]}): ${[...new Set(recs.map((q) => dl(q.t)))].slice(0, 3).join(', ')}`,
      `${POINT_KIND[g[2]]}${g[4] ? `, ±${F.fmtNumber(g[4], g[4] % 1 ? 1 : 0)} km` : ''}`, basin].filter(Boolean).join('\n');
    if (g[2] === 3) {
      // El tramo del río o la quebrada: su círculo sin relleno y el punto del cauce.
      const reach = Math.max(r, ((g[4] || 0) / 111) * D.peru.lonLat.k);
      return `<g class="hz-pt hz-pt-agua" data-tip="${esc(tipText)}"><circle class="hz-reach" cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="${reach.toFixed(2)}"></circle><circle cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="${r.toFixed(2)}"></circle></g>`;
    }
    return `<circle class="${g[2] ? 'hz-pt hz-pt-cp' : 'hz-pt'}" cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="${r.toFixed(2)}" data-tip="${esc(tipText)}"></circle>`;
  }).join(''));
  if (note) {
    note.textContent = n0_ + n1 + n3
      ? `${n0(n0_ + n1 + n3)} de los ${n0(mine.length)} registros de esta área tienen un punto más fino que su distrito: ${n0(n0_)} con el punto de campo de la fuente (punto lleno), ${n0(n1)} en el centro poblado que nombran (anillo) y ${n0(n3)} sobre el río, la quebrada o la laguna que nombran (círculo punteado: su tramo en el distrito). Los demás solo se conocen por distrito.`
      : `Ninguno de los ${n0(mine.length)} registros de esta área tiene un punto más fino que su distrito.`;
  }
}

/** Lo que las instituciones identificaron hoy como peligro en el área (no son eventos con fecha). */
async function fillContext(root, D, s) {
  const box = $('#hz-ctx', root);
  if (!box) return;
  const C = await context();
  if (!box.isConnected) return;
  const codes = Object.keys(C.distritos || {}).filter((c) => c.startsWith(s.area));
  if (!codes.length) return;
  const ing = [0, 0, 0, 0], zc = [], ana = [], ips = [];
  for (const c of codes) {
    const d = C.distritos[c];
    if (d.ing) for (let i = 0; i < 4; i++) ing[i] += d.ing[i] || 0;
    for (const z of d.zc || []) zc.push([c, ...z]);
    for (const a of d.ana || []) ana.push([c, ...a]);
    for (const x of d.ips || []) ips.push([c, ...x]);
  }
  ana.sort((a, b) => (b[4] === 'Muy Alto') - (a[4] === 'Muy Alto') || (b[5] || 0) - (a[5] || 0));
  const where = (c) => (s.area.length === 6 ? '' : ` · ${shortName(D, c)}`);
  const muyAlto = ana.filter((a) => a[4] === 'Muy Alto').length;
  box.innerHTML = String(html`<div class="hz-ctxbox"><h4 class="hz-h4">Peligro identificado hoy</h4>
    <p class="muted small">Inventarios oficiales de lugares con peligro, no eventos con fecha: complementan la historia de arriba.</p>
    <dl class="hz-kv">
      ${ana.length ? html`<div><dt>Puntos críticos en ríos y quebradas (ANA)</dt><dd>${n0(ana.length)}${muyAlto ? html` · <strong>${n0(muyAlto)} muy alto</strong>` : ''}</dd></div>` : ''}
      ${zc.length ? html`<div><dt>Zonas críticas por peligro geológico (INGEMMET)</dt><dd>${n0(zc.length)}</dd></div>` : ''}
      ${ing[0] ? html`<div><dt>Puntos de peligro geológico inventariados (INGEMMET)</dt><dd>${n0(ing[0])}${ing[1] ? ` · ${n0(ing[1])} flujos o huaycos` : ''}</dd></div>` : ''}
      ${ips.length ? html`<div><dt>Establecimientos de salud afectados por lluvias en 2022-23</dt><dd>${n0(ips.length)}</dd></div>` : ''}
    </dl>
    ${ana.length ? html`<details class="more"${muyAlto ? raw(' open') : ''}><summary>Puntos críticos de la ANA (${n0(ana.length)})</summary><ul class="hz-ctxlist">${ana.slice(0, 15).map((a) => html`<li><strong>${a[1]}</strong>${where(a[0])} <span class="tag${a[4] === 'Muy Alto' ? ' tag-warm' : ''}">peligro ${a[4].toLowerCase()}</span><br><span class="small">${a[2]} · ${a[3]}${a[5] ? ` · ${n0(a[5])} personas` : ''}${a[6] ? ` · ${n0(a[6])} viviendas expuestas` : ''}</span>${a[7] ? html`<br><span class="muted small">Acción recomendada: ${a[7]}${a[8] ? ` (S/ ${n0(a[8])})` : ''}</span>` : ''}</li>`)}</ul>${ana.length > 15 ? html`<p class="muted small">Y ${n0(ana.length - 15)} más en el CSV de contexto.</p>` : ''}</details>` : ''}
    ${zc.length ? html`<details class="more"><summary>Zonas críticas del INGEMMET (${n0(zc.length)})</summary><ul class="hz-ctxlist">${zc.slice(0, 15).map((z) => html`<li><strong>${z[1] || 'Sin nombre'}</strong>${where(z[0])} · ${z[2]}${z[3] ? ` · expone: ${z[3].toLowerCase()}` : ''}${z[4] ? html` · <a href="${safeUrl(z[4])}" rel="noopener" target="_blank">boletín</a>` : ''}</li>`)}</ul>${zc.length > 15 ? html`<p class="muted small">Y ${n0(zc.length - 15)} más en el CSV de contexto.</p>` : ''}</details>` : ''}
  </div>`);
}

/** Filas de una tabla {cols, rows} como objetos. */
const objs = (t) => (t?.rows || []).map((r) => Object.fromEntries(t.cols.map((c, i) => [c, r[i]])));

/** Barras al 100 %: en cada año, la parte de las emergencias con el peligro ya documentado. */
function prevChart(A) {
  const rows = A.filter((a) => a.anio >= 2003 && a.eventos > 0);
  if (!rows.length) return '';
  const W = 1000, H = 124, top = 2, base = H, bw = W / rows.length, gap = 2;
  const bars = rows.map((a, i) => {
    const share = a.eventosConAviso / a.eventos;
    const h = base - top, hA = share * h;
    const x = (i * bw + bw * 0.12).toFixed(1), w = (bw * 0.76).toFixed(1);
    const label = `${a.anio}: ${n0(a.eventosConAviso)} de ${n0(a.eventos)} emergencias (${pct(share)}) en distritos con el peligro ya documentado`;
    return `<g data-tip="${esc(label)}"><title>${esc(label)}</title><rect class="hz-pv-b" x="${x}" y="${top}" width="${w}" height="${Math.max(0, h - hA - gap).toFixed(1)}" rx="2"></rect><rect class="hz-pv-a" x="${x}" y="${(base - hA).toFixed(1)}" width="${w}" height="${hA.toFixed(1)}" rx="2"></rect></g>`;
  }).join('');
  // Primer y último año pegados a los bordes; los quinquenios demasiado cerca de ellos se omiten para no encimarse.
  const last = rows.length - 1;
  const ticks = rows.map((a, i) => ({ a, i })).filter(({ a, i }) => i === 0 || i === last || (a.anio % 5 === 0 && i > 2 && i < last - 2))
    .map(({ a, i }) => ({ x: i === 0 ? 0 : i === last ? 100 : ((i + 0.5) / rows.length) * 100, text: a.anio, edge: i === 0 ? 'start' : i === last ? 'end' : '' }));
  const grid = [0.5, 1].map((v) => `<line class="hz-pv-grid" x1="0" x2="${W}" y1="${(base - v * (base - top)).toFixed(1)}" y2="${(base - v * (base - top)).toFixed(1)}"></line>`).join('');
  const svg = `<svg class="hz-tl hz-pv" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Parte de las emergencias oficiales de cada año ocurridas donde el peligro ya estaba documentado, ${rows[0].anio}-${rows.at(-1).anio}">${grid}${bars}</svg>`;
  return labelled(svg, ticks);
}

async function fillPrevention(root, D) {
  const box = $('#hz-prev', root);
  if (!box) return;
  const P = await prevention();
  if (!box.isConnected) return;
  const head = '<div class="section-head"><h2 id="hz-prev-h">¿Se sabía antes? Peligros documentados antes de cada emergencia</h2></div>';
  if (!P) { box.innerHTML = `${head}<p class="muted">No se pudo cargar prevencion.json.</p>`; return; }
  const A = objs({ cols: P.columnasAnual, rows: P.anual });
  const sum = (rows, k) => rows.reduce((t, a) => t + (a[k] || 0), 0);
  const recent = A.filter((a) => a.anio >= 2016);
  const ev = sum(recent, 'eventos'), aviso = sum(recent, 'eventosConAviso');
  // Base de comparación: lo esperable si las mismas emergencias hubieran caído en distritos al azar (la construcción
  // la calcula con la evidencia cosechada); sin ella, la parte de todos los distritos con algún peligro documentado.
  const chance = P.columnasAnual.includes('eventosConAvisoAzar') ? sum(recent, 'eventosConAvisoAzar') / ev : null;
  const chancePop = P.columnasAnual.includes('eventosConAvisoAzarPob') ? sum(recent, 'eventosConAvisoAzarPob') / ev : null;
  const c = (k) => P.columnas.indexOf(k);
  const allDists = Object.keys(D.sum.nombres.distrito).length;
  const lastYear = recent.at(-1)?.anio || 2026;
  const docBy = (y) => Object.values(P.distritos).filter((v) => (v[c('inventarioDesde')] && v[c('inventarioDesde')] < y) || (v[c('primeraEvaluacion')] && v[c('primeraEvaluacion')] < y)).length / allDists;
  const dists = Object.values(P.distritos);
  const repeat = dists.filter((v) => v[c('aniosConEvento')] >= 5);
  const repeatKnown = repeat.filter((v) => v[c('inventarioDesde')] || v[c('primeraEvaluacion')]).length;
  const docAll = dists.filter((v) => v[c('inventarioDesde')] || v[c('primeraEvaluacion')]).length / allDists;
  const appeals = objs(P.llamamientos).filter((a) => a.clima);
  const decI = sum(A, 'decretosInminente'), decD = sum(A, 'decretosImpacto'), decP = sum(A, 'prorrogas');
  const elp = D.sum.fuentes.find((f) => f.id === 'elperuano-emergencias');
  const pending = elp && elp.parcial;
  box.innerHTML = String(html`${raw(head)}
    <p>Para cada emergencia oficial (SINPAD, DesInventar y COEN, con la fecha del evento) se mira qué se sabía antes en su distrito: si INGEMMET ya había inventariado ahí un peligro del mismo tipo, si había un informe técnico de INGEMMET o del IGP de un año anterior, o si estaba vigente una declaratoria de emergencia por peligro inminente.</p>
    <div class="hz-tiles hz-tiles-4">
      <div class="hz-tile"><span class="hz-tile-v">${ev ? pct(aviso / ev) : 'N/D'}</span><span class="hz-tile-l">de las ${n0(ev)} emergencias oficiales desde 2016 ocurrieron donde el peligro ya estaba documentado; ${chance !== null ? `al azar se esperaría ${pct(chance)} (${pct(chancePop)} según la población)` : `en ${lastYear} el ${pct(docBy(lastYear))} de todos los distritos ya tenía algún peligro inventariado o evaluado`}</span></div>
      <div class="hz-tile"><span class="hz-tile-v">${n0(repeat.length)}</span><span class="hz-tile-l">distritos con emergencias en 5 o más temporadas desde 2003; en ${n0(repeatKnown)} (${pct(repeatKnown / (repeat.length || 1))}) el peligro ya estaba inventariado o evaluado, frente al ${pct(docAll)} de todos los distritos</span></div>
      <div class="hz-tile"><span class="hz-tile-v">${n0(appeals.length)}</span><span class="hz-tile-l">llamamientos de ayuda internacional de la Cruz Roja por desastres climáticos (desde ${appeals[0]?.fecha.slice(0, 4) || '—'})</span></div>
      <div class="hz-tile"><span class="hz-tile-v">${n0(decI)} <small>/ ${n0(decD)}</small></span><span class="hz-tile-l">declaratorias por peligro inminente (prevención) frente a declaratorias por impacto (respuesta)${pending ? ', leídas hasta ahora' : ''}</span></div>
    </div>
    <h3 class="hz-h3">Cada año, qué parte de las emergencias ocurrió donde el peligro ya se conocía</h3>
    <p class="hz-legend small"><span class="hz-key hz-key-a"></span> en un distrito con el peligro ya documentado <span class="hz-key hz-key-b"></span> sin documentación previa encontrada</p>
    ${raw(prevChart(A))}
    <p class="muted small">Proporción, no cantidad: desde 2016 el SINPAD registra diez veces más emergencias por año que DesInventar antes. Pase el cursor por una barra para ver las cifras, o abra la tabla.</p>
    <details class="more"><summary>Tabla por año</summary><div class="table-wrap"><table class="hz-table"><thead><tr><th scope="col">Año</th><th scope="col" class="num">Emergencias</th><th scope="col" class="num">Con el peligro documentado</th><th scope="col" class="num">Tras inventario</th><th scope="col" class="num">Tras informe técnico</th><th scope="col" class="num">Tras declaratoria inminente</th><th scope="col" class="num">Declaratorias inminente / impacto / prórroga</th><th scope="col" class="num">Informes técnicos</th><th scope="col" class="num">Puntos inventariados</th><th scope="col" class="num">Llamamientos (clima)</th></tr></thead>
      <tbody>${[...A].reverse().map((a) => html`<tr><th scope="row">${a.anio}</th><td class="num">${n0(a.eventos)}</td><td class="num">${a.eventos ? `${n0(a.eventosConAviso)} (${pct(a.eventosConAviso / a.eventos)})` : ''}</td><td class="num">${n0(a.eventosTrasInventario)}</td><td class="num">${n0(a.eventosTrasEvaluacion)}</td><td class="num">${n0(a.eventosTrasInminente)}</td><td class="num">${n0(a.decretosInminente)} / ${n0(a.decretosImpacto)} / ${n0(a.prorrogas)}</td><td class="num">${n0(a.evaluaciones)}</td><td class="num">${n0(a.puntosInventario)}</td><td class="num">${n0(a.llamamientosClima)}</td></tr>`)}</tbody></table></div></details>
    ${appeals.length ? html`<details class="more"><summary>Llamamientos internacionales por desastres climáticos (${n0(appeals.length)})</summary><ul class="hz-ctxlist">${[...appeals].reverse().map((a) => html`<li><strong>${F.fmtDate(a.fecha)}</strong> · ${a.nombre} <span class="tag">${a.modalidad}</span>${a.montoCHF ? ` · CHF ${n0(a.montoCHF)} pedidos` : ''}${a.beneficiarios ? ` · ${n0(a.beneficiarios)} personas` : ''} · <a href="${safeUrl(a.url)}" rel="noopener" target="_blank">IFRC GO</a></li>`)}</ul></details>` : ''}
    <h3 class="hz-h3">Cómo leerlo</h3>
    <ul class="hz-method">
      <li><strong>Compárelo con el azar.</strong> Casi todos los distritos tienen algún peligro inventariado por el INGEMMET, así que la mayoría de las emergencias caería en un distrito «documentado» aunque la documentación no tuviera relación con ellas. ${chance !== null ? `Si las mismas emergencias (con su fecha y su peligro) hubieran caído en distritos al azar, el ${pct(chance)} habría ocurrido donde el peligro ya estaba documentado; la diferencia con el ${pct(aviso / ev)} observado es lo que la documentación anticipa.` : 'La comparación exacta con el azar (las mismas emergencias en distritos elegidos al azar) se calcula en la próxima construcción completa del catálogo; una revisión independiente la estimó entre 64 % y 66 %, solo 2 a 4 puntos menos que lo observado.'} Esta cifra no mide cuánta prevención se hizo ni si se pudo evitar el daño; para eso hace falta comparar lugares con y sin obras (diferencias en diferencias).</li>
      <li>«Documentado» no quiere decir que se pudiera evitar, sino que el Estado tenía el peligro identificado en ese distrito antes de la emergencia. El inventario de INGEMMET marca puntos de peligro (caídas, deslizamientos, huaycos, erosión, inundación) con la fecha en que los inventarió; el mismo grupo de peligro cuenta (un inventario de huaycos vale para una emergencia por lluvias intensas).</li>
      <li>Las notas de prensa y las páginas de periódicos antiguos no entran a esta cuenta; sí corroboran las fichas en la lista de cada área. Los reportes del COEN entran con la fecha del evento cuando su PDF ya se leyó.</li>
      <li>Las declaratorias de emergencia se leen del diario oficial El Peruano (sumilla y texto del decreto). Una declaratoria de toda una provincia o un departamento cuenta para cada uno de sus distritos.${pending ? ' La descarga sigue en curso y por ahora hay pocas: esa columna crecerá.' : ''} Prórrogas en total: ${n0(decP)}.</li>
    </ul>`);
}

/** Lo que se sabía del peligro en el área: inventarios, informes técnicos y declaratorias. */
async function fillPrevArea(root, D, s) {
  const box = $('#hz-prevbox', root);
  if (!box) return;
  const P = await prevention();
  if (!box.isConnected || !P) return;
  const codes = Object.keys(P.distritos).filter((x) => x.startsWith(s.area));
  if (!codes.length) return;
  const c = (k) => P.columnas.indexOf(k);
  const tot = (k) => codes.reduce((t, x) => t + (P.distritos[x][c(k)] || 0), 0);
  const first = (k) => {
    const v = codes.map((x) => P.distritos[x][c(k)]).filter(Boolean);
    return v.length ? Math.min(...v) : null;
  };
  const evs = tot('eventos'), av = tot('eventosConAviso');
  const inv = first('inventarioDesde'), ev1 = first('primeraEvaluacion');
  // En un área grande, las declaratorias de toda la provincia o el departamento se repiten en cada distrito.
  const decI = Math.max(...codes.map((x) => P.distritos[x][c('decretosInminente')])), decD = Math.max(...codes.map((x) => P.distritos[x][c('decretosImpacto')]));
  const reports = objs(P.evaluaciones).filter((e) => e.ubigeos.some((u) => u.startsWith(s.area) || s.area.startsWith(u))).reverse();
  box.innerHTML = String(html`<div class="hz-ctxbox"><h4 class="hz-h4">¿Se sabía antes?</h4>
    <dl class="hz-kv">
      <div><dt>Peligro inventariado por INGEMMET</dt><dd>${inv ? `desde ${inv} · ${n0(tot('puntosInventario'))} puntos` : 'sin puntos con fecha'}</dd></div>
      <div><dt>Informes técnicos (INGEMMET, IGP)</dt><dd>${reports.length ? `${n0(reports.length)}, el primero de ${ev1 || reports.at(-1).anio}` : 'ninguno encontrado'}</dd></div>
      <div><dt>Declaratorias de emergencia${codes.length > 1 ? ' (máximo en un distrito)' : ''}</dt><dd>${n0(decI)} por peligro inminente · ${n0(decD)} por impacto</dd></div>
      <div><dt>Emergencias oficiales desde 2003</dt><dd>${n0(evs)}${evs ? `, ${n0(av)} (${pct(av / evs)}) con el peligro ya documentado` : ''}</dd></div>
    </dl>
    ${reports.length ? html`<details class="more"><summary>Informes técnicos (${n0(reports.length)})</summary><ul class="hz-ctxlist">${reports.slice(0, 12).map((e) => html`<li><strong>${e.anio}</strong> · ${e.institucion}: ${e.url ? html`<a href="${safeUrl(e.url)}" rel="noopener" target="_blank">${e.titulo}</a>` : e.titulo}</li>`)}</ul>${reports.length > 12 ? html`<p class="muted small">Y ${n0(reports.length - 12)} más en prevencion.json.</p>` : ''}</details>` : ''}
  </div>`);
}

/** Registros anteriores a 1970 (archivos coloniales y republicanos, desbordes de lagunas glaciares). */
function pastSection(D) {
  const old = D.recs.filter((r) => r.y < 1970);
  if (!old.length) return '';
  const by = new Map();
  for (const r of old) {
    const k = r.u;
    if (!by.has(k)) by.set(k, { years: new Set(), types: new Map(), src: new Set() });
    const o = by.get(k);
    o.years.add(r.y);
    o.types.set(r.t, (o.types.get(r.t) || 0) + 1);
    o.src.add(r.o === 'glof' ? 'base de GLOF' : r.o === 'curado' ? 'archivos' : r.o === 'hemeroteca' ? 'periódicos antiguos' : r.o);
  }
  const rows = [...by.entries()].sort((a, b) => b[1].years.size - a[1].years.size || a[0].localeCompare(b[0]));
  const first = Math.min(...old.map((r) => r.y));
  return html`<section class="card hz-card" aria-labelledby="hz-past-h">
    <div class="section-head"><h2 id="hz-past-h">Antes de 1970: los mismos lugares, una y otra vez</h2><span class="muted small">${n0(old.length)} registros desde ${first}</span></div>
    <p class="muted small">Las actas del Cabildo de Trujillo y otros archivos (cronología de García-Herrera et al., 2008) registran lluvias e inundaciones de El Niño en Trujillo, Chicama, Saña, Lambayeque y Piura desde el siglo XVI, y el estudio de Eguiguren (1894), las de Piura y Paita desde 1728; los periódicos antiguos digitalizados cuentan las de los siglos XIX y XX, y la base mundial de desbordes de lagunas glaciares, los aluviones de la Cordillera Blanca y otras cordilleras. Son los mismos lugares que vuelven a aparecer en 1983, 1998, 2017 y 2023.</p>
    <div class="table-wrap"><table class="hz-table"><thead><tr><th scope="col">Lugar</th><th scope="col" class="num">Años</th><th scope="col">Cuándo</th><th scope="col">Peligro</th><th scope="col">Fuente</th></tr></thead>
      <tbody>${rows.slice(0, 30).map(([code, o]) => html`<tr><th scope="row"><button type="button" class="linkish" data-area="${code}">${areaName(D, code)}</button></th><td class="num">${o.years.size}</td><td class="small">${[...o.years].sort((a, b) => a - b).join(', ')}</td><td class="small">${[...o.types.entries()].sort((a, b) => b[1] - a[1]).map(([t]) => dl(t)).join(', ')}</td><td class="small">${[...o.src].join(', ')}</td></tr>`)}</tbody></table></div>
  </section>`;
}

function greatSection(D, s) {
  const lvl = s.nivel === 'departamento' ? 'departamento' : 'provincia';
  const all = M.filter(D.recs, { ...currentFilter(D, s), event: '' });
  const maps = D.great.map((g) => {
    const recs = all.filter((r) => r.e === g);
    const st = M.byArea(recs, lvl, [], D.nino, D.great);
    const vals = [...st.values()].map((x) => x.registros);
    const scale = { cls: (v) => (v > 0 ? 'q3' : 'none') }; // presencia: las fuentes de cada evento tienen densidades distintas
    return html`<figure class="hz-sm"><figcaption><strong>${g}</strong> <span class="muted small">${n0(recs.length)} registros · ${n0(st.size)} ${lvl === 'provincia' ? 'provincias' : 'departamentos'}</span></figcaption>
      ${raw(mapSvg(D, { ...s, nivel: lvl, metrica: 'registros', area: '' }, st, scale, { small: true, label: `${g}: ${st.size} áreas con registros` }))}${vals.length ? '' : html`<p class="muted small">Sin registros en el catálogo con estos filtros.</p>`}</figure>`;
  });
  const hot = M.repeatHotspots(all, s.nivel === 'departamento' ? 'provincia' : s.nivel, D.great).filter((h) => h.n >= 2).slice(0, 25);
  return html`<section class="card hz-card" aria-labelledby="hz-great-h">
    <div class="section-head"><h2 id="hz-great-h">Los grandes Niños, uno al lado del otro</h2></div>
    <p class="muted small">En color, cada ${lvl} con al menos un registro del evento. Se muestra solo si hubo registros y no cuántos, porque cada evento viene de fuentes distintas: 1982-83 y 1997-98 de DesInventar (prensa e INDECI), 2017 del SINPAD (mucho más denso) y del Plan de Reconstrucción, y 2023 casi solo por departamento (IDMC), por eso en el mapa por provincias se ve poco.</p>
    <div class="hz-sms">${maps}</div>
    <h3 class="hz-h3">Lugares golpeados en dos o más grandes Niños</h3>
    ${hot.length ? html`<div class="table-wrap"><table class="hz-table"><caption class="visually-hidden">Lugares con registros en varios grandes Niños</caption><thead><tr><th scope="col">Lugar</th><th scope="col" class="num">Grandes Niños</th>${D.great.map((g) => html`<th scope="col" class="hz-th-g">${g}</th>`)}</tr></thead>
      <tbody>${hot.map((h) => html`<tr><th scope="row"><button type="button" class="linkish" data-area="${h.code}">${areaName(D, h.code)}</button></th><td class="num">${h.n}</td>${D.great.map((g) => html`<td class="hz-td-g">${h.hit.includes(g) ? html`<span class="hz-dot" aria-label="sí">●</span>` : html`<span class="muted" aria-label="no">·</span>`}</td>`)}</tr>`)}</tbody></table></div>` : html`<p class="muted">Ningún lugar con registros en dos o más grandes Niños con estos filtros.</p>`}
  </section>`;
}

function rankingSection(D, s, stats) {
  const rows = [...stats.entries()].map(([c, st]) => [c, st, metricValue(st, s.metrica)]).filter(([, , v]) => v !== null && v > 0)
    .sort((a, b) => b[2] - a[2] || b[1].registros - a[1].registros).slice(0, 40);
  return html`<section class="card hz-card" aria-labelledby="hz-rank-h">
    <div class="section-head"><h2 id="hz-rank-h">Ranking por ${LEVEL_NAMES.find(([k]) => k === s.nivel)[1].toLowerCase()}: ${METRICS.find(([k]) => k === s.metrica)[1].toLowerCase()}</h2></div>
    <p class="muted small">Los 40 primeros con los filtros elegidos. Es también la versión en tabla del mapa. «Muestra pequeña»: menos de 5 años con daños, la frecuencia es poco confiable; para ordenar áreas con pocos años, use «Años con daños, como mínimo», el límite inferior del intervalo.</p>
    <div class="table-wrap"><table class="hz-table"><thead><tr><th scope="col">Lugar</th><th scope="col">Valor</th><th scope="col" class="num">Años con daños</th><th scope="col">Frecuencia (IC 95 %)</th><th scope="col" class="num">Grandes Niños</th><th scope="col">Peligro principal</th><th scope="col">Último registro</th></tr></thead>
    <tbody>${rows.map(([c, st]) => html`<tr><th scope="row"><button type="button" class="linkish" data-area="${c}">${areaName(D, c)}</button></th><td>${rankText(st, s.metrica)}</td><td class="num">${st.aniosConEvento}${st.muestraPequena ? html` <span class="tag" title="Menos de 5 años con daños">muestra pequeña</span>` : ''}</td><td>${st.aniosCobertura ? pctRange(st.frecuenciaIC) : ''}</td><td class="num">${st.grandesNinos.length}</td><td>${st.peligros[0] ? dl(st.peligros[0][0]) : ''}</td><td>${st.ultimo ? when(st.ultimo.d) : ''}</td></tr>`)}</tbody></table></div>
  </section>`;
}

/** Valor de la métrica en el ranking. Para las frecuencias, solo la estimación: los años y el intervalo tienen su columna. */
function rankText(st, metric) {
  if (metric === 'anios') return st.aniosCobertura ? `${pct(st.frecuenciaAnual)} de los años` : 'Fuera del periodo 1970-2015';
  if (metric === 'minimo') return st.aniosCobertura ? `al menos ${pct(st.frecuenciaIC[0])} de los años` : 'Fuera del periodo 1970-2015';
  return metricText(st, metric);
}

/** Lectura del AUC (Hosmer y Lemeshow, 2000): 0,5 es azar y 1, perfecto. */
const aucWord = (a) => (a === null ? 'N/D' : a < 0.6 ? 'casi como el azar' : a < 0.7 ? 'débil' : a < 0.8 ? 'aceptable' : 'excelente');
/** Dos decimales fijos (0,60 y no 0,6): en una tabla de métricas, la cifra sola no debe parecer menos precisa. */
const f2 = (v) => (v === null || v === undefined ? 'N/D' : v.toLocaleString('es', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

/** ¿La historia anticipa lo que vino después? Validación fuera de muestra (resumen.json → validacion). */
function validationSection(D) {
  const v = D.sum.validacion;
  if (!v) return '';
  const G = { todos: 'Todos los peligros', inundaciones: 'Inundaciones y desbordes', 'huaycos y deslizamientos': 'Huaycos y deslizamientos', 'heladas, friaje y nevadas': 'Heladas, friaje y nevadas' };
  const cal = v.calibracion, nino = v.nino || {};
  const ninoRows = ['departamento', 'provincia'].filter((l) => nino[l]).flatMap((l) => nino[l].grupos.map((g) => [l, g, nino[l].spearman]));
  const sens = (v.sensibilidadNino || []).filter((r) => r.razon !== null);
  return html`<section class="card hz-card" aria-labelledby="hz-val-h">
    <div class="section-head"><h2 id="hz-val-h">¿La historia anticipa lo que vino después?</h2></div>
    <p>Los indicadores usan solo DesInventar de ${v.entrenamiento[0]}-${String(v.entrenamiento[0] + 1).slice(2)} a ${v.entrenamiento[1]}-${String(v.entrenamiento[1] + 1).slice(2)}. Las emergencias del SINPAD de las temporadas ${v.prueba[0]}-${String(v.prueba[0] + 1).slice(2)} a ${v.prueba[1]}-${String(v.prueba[1] + 1).slice(2)} no entran a ningún indicador, así que sirven para ponerlos a prueba, como se verifica un pronóstico: con datos que el método no vio.</p>
    <h3 class="hz-h3">1. ¿Ordena bien las áreas la frecuencia del pasado?</h3>
    <p class="muted small">AUC: la probabilidad de que un área-temporada con emergencias tenga más frecuencia histórica que una sin emergencias (0,5 es azar; 0,7–0,8, aceptable; desde 0,8, excelente). Intervalo al 95 % por remuestreo de áreas. No se mide si los porcentajes aciertan, porque el SINPAD registra muchas más emergencias por año que DesInventar: solo el orden es comparable.</p>
    <div class="table-wrap"><table class="hz-table"><thead><tr><th scope="col">Nivel</th><th scope="col">Peligros</th><th scope="col" class="num">AUC (IC 95 %)</th><th scope="col">Lectura</th><th scope="col" class="num">Área-temporadas con emergencias</th></tr></thead>
      <tbody>${v.discriminacion.map((d) => html`<tr><th scope="row">${d.nivel === 'distrito' ? 'Distrito' : 'Provincia'}</th><td>${G[d.peligros] || d.peligros}</td><td class="num">${f2(d.auc)} (${f2(d.aucIC[0])}–${f2(d.aucIC[1])})</td><td>${aucWord(d.auc)}</td><td class="num">${pct(d.tasaBase)}</td></tr>`)}</tbody></table></div>
    <h3 class="hz-h3">2. ¿Se repitió el efecto de El Niño?</h3>
    <p class="muted small">Razón de El Niño de ${v.prueba[0]}-${v.prueba[1]} (SINPAD; temporadas con Niño costero: ${v.aniosNinoPrueba.join(', ') || 'ninguna'}) en las áreas donde la de 1970-2015 fue claramente mayor que 1 y en las demás. Spearman: correlación entre el orden de las áreas en ambos periodos (1 = mismo orden).</p>
    <div class="table-wrap"><table class="hz-table"><thead><tr><th scope="col">Nivel</th><th scope="col">En 1970-2015, la razón de El Niño fue</th><th scope="col" class="num">Áreas</th><th scope="col" class="num">Razón en ${v.prueba[0]}-${v.prueba[1]} (IC 95 %)</th><th scope="col" class="num">Spearman</th></tr></thead>
      <tbody>${ninoRows.map(([l, g, rho]) => html`<tr><th scope="row">${l === 'departamento' ? 'Departamento' : 'Provincia'}</th><td>${g.clase === 'mayor' ? 'claramente mayor que 1' : g.clase === 'menor' ? 'claramente menor que 1' : 'sin diferencia clara'}</td><td class="num">${n0(g.areas)}</td><td class="num">${f2(g.rrPrueba)}× (${f2(g.rrPruebaIC[0])}–${f2(g.rrPruebaIC[1])})</td><td class="num">${f2(rho)}</td></tr>`)}</tbody></table></div>
    ${cal ? html`<h3 class="hz-h3">3. ¿Acierta la «probabilidad en 5 años»?</h3>
    <p class="muted small">Con la misma fuente: la probabilidad calculada con DesInventar ${cal.entrenamiento[0]}-${cal.entrenamiento[1]}, frente a lo que DesInventar registró en ${cal.bloques.map((b) => `${b[0]}-${b[1]}`).join(', ')} (${n0(cal.distritos)} distritos). Habilidad de Brier: cuánto mejora sobre decir siempre la tasa base (${pct(cal.tasaBase)}); 0 es igual y 1, perfecto. AUC ${f2(cal.cruda.auc)} (${f2(cal.cruda.aucIC[0])}–${f2(cal.cruda.aucIC[1])}).</p>
    <div class="grid g2"><div><div class="table-wrap"><table class="hz-table"><caption class="small">Diagrama de confiabilidad (frecuencia sin suavizar)</caption><thead><tr><th scope="col">Probabilidad calculada</th><th scope="col" class="num">Promedio calculado</th><th scope="col" class="num">Ocurrió</th><th scope="col" class="num">Distrito-bloques</th></tr></thead>
      <tbody>${cal.cruda.confiabilidad.map((b) => html`<tr><th scope="row">${b.rango}</th><td class="num">${pct(b.predicha)}</td><td class="num">${pct(b.observada)}</td><td class="num">${n0(b.n)}</td></tr>`)}</tbody></table></div></div>
      <div><ul class="hz-method"><li>Habilidad de la frecuencia sin suavizar: <strong>${f2(cal.cruda.habilidad)}</strong>; suavizada por Bayes empírico: <strong>${f2(cal.suavizada.habilidad)}</strong>. Las dos mejoran poco sobre la tasa base.</li><li>Exagera en los extremos: donde da 0 %, ${pct(cal.cruda.confiabilidad[0]?.observada)} de los distritos tuvo daños; donde da más de 80 %, ${pct(cal.cruda.confiabilidad.at(-1)?.observada)}. Por eso el sitio muestra el intervalo y no un número solo.</li></ul></div></div>` : ''}
    ${v.grandesNinos?.length ? html`<h3 class="hz-h3">4. ¿Vuelven los grandes Niños a los mismos lugares?</h3>
    <div class="table-wrap"><table class="hz-table"><thead><tr><th scope="col">Región</th><th scope="col">Distritos con registros en 1982-83 y 1997-98</th><th scope="col" class="num">Distritos</th><th scope="col" class="num">Con registros en 2017</th></tr></thead>
      <tbody>${v.grandesNinos.flatMap((r) => r.grupos.map((g, i) => html`<tr>${i ? '' : html`<th scope="rowgroup" rowspan="${r.grupos.length}">${r.region}<br><span class="muted small">en total, ${pct(r.tasaBase)}</span></th>`}<td>${g.golpeados}</td><td class="num">${n0(g.distritos)}</td><td class="num">${pct(g.conRegistros)}</td></tr>`))}</tbody></table></div>` : ''}
    ${sens.length ? html`<details class="more"><summary>Sensibilidad de la razón de El Niño por departamento</summary>
      <p class="muted small">La razón publicada (temporada con Niño si el ICEN medio de enero a marzo supera +0,5 °C), la que daría la regla anterior (cualquier mes de diciembre a abril dentro de un Niño costero) y la respuesta a la intensidad: cuánto cambian los lugares con daños por año por cada grado más de ICEN, sin umbral. Las tres señalan los mismos departamentos.</p>
      <div class="table-wrap"><table class="hz-table"><thead><tr><th scope="col">Departamento</th><th scope="col" class="num">Razón (IC 95 %)</th><th scope="col" class="num">Regla anterior</th><th scope="col" class="num">Por cada +1 °C de ICEN</th></tr></thead>
        <tbody>${sens.map((r) => html`<tr><th scope="row">${r.nombre}</th><td class="num">${x1(r.razon)} (${F.fmtNumber(r.razonIC[0], 1)}–${F.fmtNumber(r.razonIC[1], 1)})</td><td class="num">${r.razonReglaAnterior ? html`${x1(r.razonReglaAnterior)} (${F.fmtNumber(r.razonReglaAnteriorIC[0], 1)}–${F.fmtNumber(r.razonReglaAnteriorIC[1], 1)})` : 'N/D'}</td><td class="num">${r.porGradoICEN ? html`${f2(r.porGradoICEN)}× (${f2(r.porGradoICENIC[0])}–${f2(r.porGradoICENIC[1])})` : 'N/D'}</td></tr>`)}</tbody></table></div></details>` : ''}
    <h3 class="hz-h3">Qué quiere decir</h3>
    <ul class="hz-method">
      <li>Para elegir dónde mirar primero, la historia sirve más por provincia y por peligro que por distrito. Por distrito, el peligro identificado hoy (puntos del INGEMMET y de la ANA, en cada ficha) anticipa mejor las emergencias graves.</li>
      <li>El efecto de El Niño costero es lo más firme: en los mismos departamentos de la costa norte y centro, con cualquiera de las tres formas de medirlo, y se repitió después de 2015.</li>
      <li>Las cifras de 2016 en adelante vienen de otra fuente (SINPAD), con otra densidad; por eso se compara el orden de las áreas y la razón dentro de cada periodo, no los conteos.</li>
    </ul>
  </section>`;
}

function srcLinks(src) {
  return html`<span class="muted small">${src.map(([t, u], i) => html`${i ? ' · ' : ''}<a href="${safeUrl(u)}" rel="noopener" target="_blank">${t}</a>`)}</span>`;
}

function evidenceSection(D) {
  const N = D.sum.nombres.distrito;
  const recsBy = (codes) => {
    const rs = D.recs.filter((r) => codes.some((c) => r.u.startsWith(c)));
    return { n: rs.length, great: D.great.filter((g) => rs.some((r) => r.e === g)), years: new Set(rs.map((r) => r.hy).filter((y) => y !== null)).size };
  };
  return html`<section class="card hz-card" aria-labelledby="hz-ev-h">
    <div class="section-head"><h2 id="hz-ev-h">${EV.VERDICT.title}</h2><span class="hz-verdict">${EV.VERDICT.verdict}</span></div>
    <p>${EV.VERDICT.summary}</p>
    <p class="muted small">${EV.VERDICT.caveat}</p>
    <div class="table-wrap"><table class="hz-table"><caption>Impactos nacionales de cada gran evento</caption><thead><tr><th scope="col">Evento</th><th scope="col">Fallecidos</th><th scope="col">Damnificados y afectados</th><th scope="col">Otros</th><th scope="col">Fuente</th></tr></thead>
      <tbody>${EV.EVENT_TOTALS.map((e) => html`<tr><th scope="row">${e.event}</th><td>${e.deaths}</td><td>${e.homeless}</td><td>${e.note}</td><td>${srcLinks(e.src)}</td></tr>`)}</tbody></table></div>
    <div class="grid g2 hz-proscons">
      <div><h3 class="hz-h3">Lo que sí se hizo</h3><ul class="hz-claims">${EV.AGAINST.map((c) => html`<li><p>${c.text}</p>${srcLinks(c.src)}</li>`)}</ul></div>
      <div><h3 class="hz-h3">Lo que sigue pendiente</h3><ul class="hz-claims">${EV.FOR.map((c) => html`<li><p>${c.text}</p>${srcLinks(c.src)}</li>`)}</ul></div>
    </div>
    <h3 class="hz-h3">Lugares con daños repetidos, cruzados con el catálogo</h3>
    <div class="table-wrap"><table class="hz-table"><thead><tr><th scope="col">Lugar</th><th scope="col">Eventos según la literatura</th><th scope="col">En el catálogo</th><th scope="col">Nota</th></tr></thead>
      <tbody>${EV.HOTSPOTS.map((h) => { const c = recsBy(h.codes); return html`<tr><th scope="row"><button type="button" class="linkish" data-area="${h.codes[0]}" data-nivel-go="distrito">${h.name}</button><br><span class="muted small">${h.codes.map((x) => N[x]).filter(Boolean).join(', ')}</span></th><td>${h.years}</td><td>${n0(c.n)} registros en ${c.years} temporadas${c.great.length ? html`<br><span class="small">${c.great.join(', ')}</span>` : ''}</td><td>${h.note} ${srcLinks(h.src)}</td></tr>`; })}</tbody></table></div>
    <details class="more"><summary>Referencias</summary><ul class="link-list">${EV.REFERENCES.map(([t, u]) => html`<li><a href="${safeUrl(u)}" rel="noopener" target="_blank">${t}</a></li>`)}</ul></details>
  </section>`;
}

function srcList(S, k) {
  const unit = { eventos: 'registros', complemento: 'fichas unidas', emergencias: 'registros propios', prensa: 'registros propios', hemeroteca: 'registros propios', prevencion: 'elementos' }[k] || 'elementos';
  return html`<ul class="link-list">${S.fuentes.filter((f) => (f.tipo || 'eventos') === k).map((f) => html`<li>${f.pagina || f.url ? html`<a href="${safeUrl(f.pagina || f.url)}" rel="noopener" target="_blank">${f.nombre}</a>` : f.nombre} <span class="muted small">${f.cobertura || ''}${f.registros ? ` · ${n0(f.registros)} ${unit}` : ''}${f.corroboran ? ` · corroboran ${n0(f.corroboran)}` : ''}${f.parcial ? ' · descarga en curso' : ''}${f.obtenido ? ` · copia del ${F.fmtDate(f.obtenido)}` : ''} · ${f.licencia || ''}</span>${f.nota ? html`<br><span class="muted small">${f.nota}</span>` : ''}</li>`)}</ul>`;
}

function methodSection(D) {
  const S = D.sum;
  return html`<section class="card hz-card" aria-labelledby="hz-m-h">
    <h2 id="hz-m-h">Fuentes, método, límites y descargas</h2>
    <div class="grid g2">
      <div>
        <h3 class="hz-h3">Descargas</h3>
        <ul class="link-list">
          <li><a href="${BASE}eventos.zip" download>Catálogo completo (CSV en un ZIP, ${n0(S.registros)} registros)</a> <span class="muted small">Las 13 primeras columnas son las del tablero del equipo de prevención: Date, DangerType, Ubicacion, Distrito, Provincia, Departamento, Descripción, DuraciónEvento, Ubigeo, TipoEvento, Fuente, Latitud, Longitud.</span></li>
          <li><a href="${BASE}eventos.json">Versión compacta (JSON)</a> · <a href="${BASE}resumen.json">Resumen, cobertura y atributos (JSON)</a> · <a href="${BASE}contexto.json">Peligro identificado hoy por distrito (JSON)</a></li>
          <li><a href="${BASE}contexto-distrito.csv">Historial y peligro actual por distrito (CSV)</a> · <a href="${BASE}indicadores-distrito.csv">indicadores por distrito</a>, <a href="${BASE}indicadores-provincia.csv">provincia</a> y <a href="${BASE}indicadores-departamento.csv">departamento</a></li>
          <li><a href="${BASE}prevencion-distrito.csv">Prevención por distrito (CSV)</a> · <a href="${BASE}prevencion.json">declaratorias, evaluaciones y llamamientos (JSON)</a></li>
          <li><a href="${BASE}diccionario.csv">Diccionario de datos (CSV)</a> <span class="muted small">Tipo, contenido y regla de cada columna del catálogo, con el porcentaje de filas que traen el dato por fuente. Lea Ubigeo e IdFuente como texto (llevan ceros a la izquierda).</span></li>
        </ul>
        ${[['eventos', 'Fuentes de eventos'], ['complemento', 'Complementos de las fichas del SINPAD (cifras de daños y punto; no agregan registros)'], ['emergencias', 'Reportes de emergencia del COEN (se unen a las fichas del SINPAD)'], ['prensa', 'Prensa regional y nacional (cada nota se une al evento que cuenta)'], ['hemeroteca', 'Periódicos antiguos digitalizados (cada página se une al evento que cuenta)'], ['prevencion', 'Prevención: declaratorias, evaluaciones, inventarios y llamamientos'], ['contexto', 'Peligro identificado hoy (contexto, no eventos)'], ['referencia', 'Referencias territoriales']].map(([k, t]) => html`<h3 class="hz-h3">${t}</h3>
        ${k === 'prensa' ? html`<details class="more"><summary>${n0(S.fuentes.filter((f) => f.tipo === k).length)} medios</summary>${srcList(S, k)}</details>` : srcList(S, k)}`)}
        <p class="muted small">Catálogo generado el ${F.fmtDate(S.generatedAt.slice(0, 10))}. Límites: INDECI (GEOSINPAD). Centros poblados: INEI (censo 2017), IGN y SDOT; ríos, quebradas, lagunas y nevados: IGN, Carta Nacional 1:100 000; cuencas: ANA (los tres vía el geoportal de la IDEP, PCM). Población, pobreza e IDH por distrito: INEI y PNUD vía ubigeo-peru-aumentado (MIT).</p>
      </div>
      <div>
        <h3 class="hz-h3">Cómo leer los indicadores</h3>
        <ul class="hz-method">
          <li><strong>Años con daños</strong>: temporadas (julio a junio) de 1970-71 a 2014-15 con al menos un registro de DesInventar en el lugar, con intervalo de Wilson al 95 % (válido con muestras pequeñas). Se cuentan años y no registros porque un mismo Niño deja decenas de fichas. Las fuentes posteriores no entran a esta cuenta porque tienen otra densidad. «Como mínimo» es el límite inferior del intervalo: ordena mejor las áreas con pocos años.</li>
          <li><strong>1 de cada X años</strong> y <strong>probabilidad en 5 años</strong>: la misma frecuencia dicha de otra forma, con el intervalo que sale del de Wilson; suponen que el clima y la exposición no cambian. No son pronósticos (ver la validación).</li>
          <li><strong>Lugares con daños por año con Niño</strong>: lugares-año con daños por año en temporadas con Niño costero dividido entre los de las demás. Temporada con Niño: ICEN medio de enero a marzo mayor que +0,5 °C (umbral de condición cálida del ENFEN, en el pico de lluvias). El intervalo al 95 % se ensancha por la sobredispersión (cuasi-Poisson): los distritos de un mismo año no son independientes. Un lugar-año es un distrito, o una provincia o un departamento cuando la fuente no da el distrito.</li>
          <li><strong>Grandes Niños</strong>: cuáles de los cinco eventos (1982-83, 1997-98, 2017, 2023 y 2023-24) dejaron registros en el lugar. Vienen de fuentes con densidad distinta: no se suman en un puntaje.</li>
          <li><strong>TipoEvento</strong>: los eventos con nombre (Niño Costero 2017 en los 13 departamentos del Plan de Reconstrucción; Ciclón Yaku 2023 en la costa norte y Lima), solo para lluvias, inundaciones, huaycos, oleaje y viento, y los Niños y Niñas costeros del ICEN por la fecha del registro (del SINPAD desde 2019, solo las emergencias de nivel 3 o más, las que necesitaron al gobierno regional o al nacional). Que un registro caiga dentro de un Niño no prueba que el Niño lo causó.</li>
        </ul>
        <h3 class="hz-h3">Límites</h3>
        <ul class="hz-method">
          <li>${S.cobertura.nota}</li>
          <li>DesInventar se arma con prensa nacional e informes del INDECI: hay más registros de ciudades y lugares accesibles, y menos antes de los años 90. Una zona sin registros no es una zona sin peligro.</li>
          <li>Las cifras de impacto son las que publicó cada fuente; un vacío significa «no reportado», no cero. Las fuentes discrepan entre sí (Huggel et al., 2015).</li>
          <li>Los distritos se ubican con su UBIGEO o, si el nombre de la fuente está abreviado, con el punto de la fuente dentro de los límites vigentes del INDECI; las coordenadas son las de la fuente si caen en el distrito asignado y no son un punto por defecto (la capital, o el mismo punto para todo el distrito); si no, las del centro poblado oficial que nombra el registro (INEI, IGN o SDOT, con su incertidumbre en km); si no, las del río, la quebrada o la laguna que nombra, si su tramo en el distrito es corto (Carta Nacional del IGN, con su tramo en km); y si no, las de la capital del distrito (o un punto dentro del distrito si no se conoce su capital). La cuenca es la unidad hidrográfica de la ANA del punto, la del río que nombra el registro o la del distrito si el 80 % o más de él está en una. Solo 1 de cada 17 registros tiene un punto más fino que el distrito.</li>
          <li>Desde 2019 el SINPAD se lee del portal público del INDECI, que da el peligro, el distrito, la fecha, el nivel y el estado de cada emergencia, pero no su descripción ni sus daños. Las cifras de daños (la evaluación EDAN de cada emergencia, también las de 2016-2018) y un punto vienen de la capa de emergencias del GEOSINPAD, unida por el código SINPAD; casi todos esos puntos son la capital o un mismo punto para todo el distrito, así que la mayoría de esas fichas sigue en la capital del distrito. El IDMC recopila las mismas emergencias: cuando una fila del IDMC coincide con una del SINPAD (mismo distrito, ±1 día), sus personas desplazadas y viviendas pasan a la fila del SINPAD y el IDMC queda como corroboración; las filas del IDMC por departamento son resúmenes de desplazamiento, no eventos aparte.</li>
          <li>Las filas ubicadas solo por provincia o departamento llevan las coordenadas de su capital (columna PrecisionGeo): en un mapa de puntos parecen agrupadas en las capitales.</li>
          <li>La fecha de una fila del COEN es la de su primer reporte encontrado y la de una nota, la de su publicación (columna FechaTipo): su confianza nunca es alta.</li>
        </ul>
      </div>
    </div>
  </section>`;
}

// ---------------------------------------------------------------------------
// Interacción
// ---------------------------------------------------------------------------
function wire(root, D, s, set) {
  const form = $('#hz-filters', root);
  form?.addEventListener('submit', (e) => e.preventDefault());
  form?.addEventListener('change', (e) => {
    const t = e.target;
    if (!t.name) return;
    let v = t.value.trim();
    if ((t.name === 'desde' || t.name === 'hasta') && v && !/^\d{4}$/.test(v)) v = '';
    set({ [t.name]: v }, `[name="${t.name}"]`);
  });
  $$('[data-nivel]', root).forEach((b) => b.addEventListener('click', () => {
    const lvl = b.dataset.nivel;
    const area = s.area && s.area.length > M.LEVELS[lvl] ? s.area.slice(0, M.LEVELS[lvl]) : s.area;
    set({ nivel: lvl, area }, `[data-nivel="${lvl}"]`);
  }));
  $('[data-clear]', root)?.addEventListener('click', () => set({ evento: '', peligro: '', desde: '', hasta: '', area: '' }, '#hz-map-h'));
  $('[data-layer="cuencas"]', root)?.addEventListener('click', () => set({ cuencas: s.cuencas === '1' ? '' : '1' }, '[data-layer="cuencas"]'));

  // Buscador de lugares (datalist con los tres niveles).
  const q = $('#hz-q', root), list = $('#hz-places', root);
  if (q && list) {
    const N = D.sum.nombres;
    const entries = [
      ...Object.entries(N.departamento).map(([c, n]) => [c, `${n} (departamento)`]),
      ...Object.entries(N.provincia).map(([c, n]) => [c, `${n}, ${N.departamento[c.slice(0, 2)]} (provincia)`]),
      ...Object.entries(N.distrito).map(([c, n]) => [c, `${n}, ${N.provincia[c.slice(0, 4)]}, ${N.departamento[c.slice(0, 2)]} (distrito)`]),
    ];
    const byLabel = new Map(entries.map(([c, l]) => [l, c]));
    q.addEventListener('focus', () => { if (!list.childElementCount) list.innerHTML = entries.map(([, l]) => `<option value="${esc(l)}"></option>`).join(''); }, { once: true });
    q.addEventListener('change', () => {
      const code = byLabel.get(q.value);
      if (!code) return;
      const nivel = code.length === 6 ? 'distrito' : code.length === 4 ? (s.nivel === 'distrito' ? 'distrito' : 'provincia') : s.nivel;
      set({ area: code, nivel }, '#hz-side');
    });
  }

  // Mapa: tooltip, clic y teclado.
  const svg = $('.hz-mapbox .hz-svg', root), tip = $('.hz-tip', root);
  if (!svg) return;
  const f = currentFilter(D, s);
  const recs = M.filter(D.recs, f);
  const years = M.coverageYears(D.sum.cobertura.homogenea, f.from, f.to);
  const stats = statsFor(D, s, recs, years);
  const show = (el, x, y) => {
    const code = el?.dataset?.code;
    if (!tip || !(code || el?.dataset?.tip)) return;
    if (code) {
      const st = stats.get(code);
      tip.innerHTML = String(html`<strong>${areaName(D, code)}</strong><p>${metricText(st, s.metrica)}</p>${st ? html`<p class="muted small">${n0(st.registros)} registros · ${st.aniosConEvento} años con daños · ${st.grandesNinos.length} grandes Niños</p>` : ''}`);
    } else {
      // Un punto de registros o una cuenca: su texto ya viene armado (y escapado) en data-tip.
      const [head, ...rest] = el.dataset.tip.split('\n');
      tip.innerHTML = String(html`<strong>${head}</strong>${rest.map((t) => html`<p class="muted small">${t}</p>`)}`);
    }
    tip.hidden = false;
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let left = x + 16, top = Math.max(8, Math.min(innerHeight - th - 8, y - th / 2));
    if (left + tw > innerWidth - 8) left = Math.max(8, x - tw - 16);
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
  };
  const hide = () => { if (tip) tip.hidden = true; };
  svg.addEventListener('pointermove', (e) => { if (e.pointerType !== 'touch') show(e.target.closest('[data-tip]') || e.target.closest('[data-code]'), e.clientX, e.clientY); });
  svg.addEventListener('pointerleave', hide);
  const pick = (code) => { hide(); set({ area: s.area === code ? '' : code }, '#hz-side'); };
  svg.addEventListener('click', (e) => { const t = e.target.closest('[data-code]'); if (t) pick(t.dataset.code); });
  svg.addEventListener('keydown', (e) => { const t = e.target.closest('[data-code]'); if (t && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); pick(t.dataset.code); } });
  svg.addEventListener('focusin', (e) => { const t = e.target.closest('[data-code]'); if (t) { const r = t.getBoundingClientRect(); show(t, r.left + r.width / 2, r.top + r.height / 2); } });
  svg.addEventListener('focusout', hide);
}
