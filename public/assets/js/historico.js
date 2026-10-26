// Memoria de desastres: dónde golpearon antes los Niños, las lluvias, los huaycos, las sequías y las
// heladas, con qué frecuencia, y qué esperar si se repiten.
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

// ---------------------------------------------------------------------------
// Estado (en la dirección: #/memoria?nivel=distrito&evento=grandes&area=200104)
// ---------------------------------------------------------------------------
const DEFAULTS = { nivel: 'provincia', evento: '', peligro: '', desde: '', hasta: '', metrica: 'anios', area: '' };
const METRICS = [
  ['anios', 'Años con daños (1970-2015)'], ['grandes', 'Grandes Niños que lo golpearon'], ['razon', 'Cuánto más daño en años de Niño'],
  ['atencion', 'Nivel de atención'], ['registros', 'Registros'], ['muertos', 'Fallecidos y desaparecidos'],
  ['afectados', 'Afectados y damnificados'], ['viviendas', 'Viviendas destruidas'],
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
const SOURCE_LINK = { desinventar: 'DesInventar', sinpad: 'SINPAD', idmc: 'IDMC', 'nasa-glc': 'noticia', coen: 'reporte del COEN', prensa: 'nota de prensa', glof: 'base de GLOF' };
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
const ATTN = { 'muy alto': ['Muy alto', 'octagon', 4], alto: ['Alto', 'triangle', 3], medio: ['Medio', 'info', 2], bajo: ['Bajo', 'dash', 1] };

export function readState() {
  const q = new URLSearchParams(location.hash.split('?')[1] || '');
  const s = { ...DEFAULTS };
  for (const k of Object.keys(DEFAULTS)) if (q.has(k)) s[k] = q.get(k);
  if (!LEVEL_NAMES.some(([k]) => k === s.nivel)) s.nivel = DEFAULTS.nivel;
  if (!METRICS.some(([k]) => k === s.metrica)) s.metrica = DEFAULTS.metrica;
  if (s.area && !/^\d{2}(\d{2}){0,2}$/.test(s.area)) s.area = '';
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

function attnChip(level) {
  const a = ATTN[level];
  if (!a) return html`<span class="hz-attn hz-attn-0">Sin registros</span>`;
  return html`<span class="hz-attn hz-attn-${a[2]}">${raw(ICON[a[1]])}${a[0]}</span>`;
}

/** Valor de la métrica para un área (número para colorear o null). */
function metricValue(st, metric) {
  if (!st) return null;
  switch (metric) {
    case 'anios': return st.aniosCobertura ? st.frecuenciaAnual : null;
    case 'grandes': return st.grandesNinos.length;
    case 'razon': return st.razonNino;
    case 'atencion': return ATTN[st.nivelAtencion]?.[2] || 0;
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
    case 'anios': return st.aniosCobertura ? `${st.aniosConEvento} de ${st.aniosCobertura} años (${pct(st.frecuenciaAnual)})${st.muestraPequena ? ' · muestra pequeña' : ''}` : 'Fuera del periodo 1970-2015';
    case 'grandes': return st.grandesNinos.length ? `${st.grandesNinos.length}: ${st.grandesNinos.join(', ')}` : 'Ninguno registrado';
    case 'razon': return st.razonNino ? `${x1(st.razonNino)} (IC 95 %: ${F.fmtNumber(st.razonNinoIC[0], 1)}–${F.fmtNumber(st.razonNinoIC[1], 1)})` : 'Datos insuficientes';
    case 'atencion': return ATTN[st.nivelAtencion]?.[0] || 'Sin registros';
    case 'registros': return `${n0(st.registros)} registros`;
    case 'muertos': return `${n0(st.muertos)} fallecidos y desaparecidos`;
    case 'afectados': return `${n0(st.afectados)} afectados y damnificados`;
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
    const br = [0.67, 0.9, 1.11, 1.5, 2];
    const lab = ['Menos de 0,67×', '0,67–0,9×', '0,9–1,1× (igual)', '1,1–1,5×', '1,5–2×', 'Más de 2×'];
    const cls = (v) => (v === null || v === undefined ? 'na' : `d${br.findIndex((b) => v < b) === -1 ? 5 : br.findIndex((b) => v < b)}`);
    return { cls, legend: [...lab.map((l, i) => [`d${i}`, l]), ['na', 'Datos insuficientes']], diverging: true };
  }
  if (metric === 'grandes') {
    const cls = (v) => (v ? `q${Math.min(4, v - 1)}` : 'none');
    return { cls, legend: [['none', 'Ninguno'], ['q0', '1'], ['q1', '2'], ['q2', '3'], ['q3', '4'], ['q4', '5']] };
  }
  if (metric === 'atencion') {
    const cls = (v) => (v ? `q${[0, 0, 1, 3, 4][v]}` : 'none');
    return { cls, legend: [['none', 'Sin registros'], ['q0', 'Bajo'], ['q1', 'Medio'], ['q3', 'Alto'], ['q4', 'Muy alto']] };
  }
  if (metric === 'anios') {
    const br = YEAR_BREAKS[level] || YEAR_BREAKS.provincia;
    const p = (v) => F.fmtNumber(v * 100, 0);
    const lab = br.map((b, i) => (i === 0 ? `Menos del ${p(b)} % de los años` : i === br.length - 1 ? `${p(br[i - 1])} % de los años o más` : `${p(br[i - 1])}–${p(b)} %`));
    const cls = (v) => (v === null || v === undefined ? 'na' : v <= 0 ? 'none' : `q${br.findIndex((b) => v < b)}`);
    return { cls, legend: [['none', 'Sin daños registrados'], ...lab.map((l, i) => [`q${i}`, l]), ['na', 'Fuera de cobertura']] };
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

function mapSvg(D, s, stats, scale, { small = false, label = '' } = {}) {
  const shapes = shapesFor(D, s.nivel);
  const focusable = s.nivel === 'departamento' && !small;
  const paths = shapes.map(([code, d]) => {
    const st = stats.get(code);
    const cls = scale.cls(metricValue(st, s.metrica));
    const sel = s.area && (code === s.area || s.area.startsWith(code) || code.startsWith(s.area)) ? ' sel' : '';
    return `<path class="hz-a hz-${cls}${sel}" d="${d}" data-code="${code}"${focusable ? ` tabindex="0" role="button" aria-label="${esc(shortName(D, code))}: ${esc(metricText(st, s.metrica))}"` : ''}></path>`;
  }).join('');
  const outline = s.nivel === 'departamento' ? '' : `<g class="hz-out" aria-hidden="true">${D.peru.departments.map((d) => `<path d="${d.d}"></path>`).join('')}</g>`;
  const vb = small ? `0 0 ${D.peru.width} ${D.peru.height}` : viewBoxFor(D, s);
  return `<svg class="hz-svg${small ? ' hz-small' : ''}" viewBox="${vb}" role="${small ? 'img' : 'group'}" aria-label="${esc(label)}" preserveAspectRatio="xMidYMid meet"><g>${paths}</g>${outline}</svg>`;
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
  const W = compact ? 500 : 1000, H = compact ? 90 : 150, bw = W / years.length;
  const named = new Map([[1982, '1982-83'], [1997, '1997-98'], [2016, '2017'], [2022, '2023'], [1972, '1972-73'], [2025, '2026']]);
  const bars = years.map((y, i) => {
    const o = by.get(y);
    const v = o ? o.da.size : 0;
    const h = (v / max) * (H - 22);
    const nino = D.nino.has(y) || D.sum.eventosICEN.some((e) => e.fase === 'warm' && e.inicio <= `${y + 1}-04` && e.fin >= `${y}-12`);
    const label = `Temporada ${y}-${String(y + 1).slice(2)}: ${v} lugares con daños, ${o ? o.n : 0} registros${o?.muertos ? `, ${o.muertos} fallecidos y desaparecidos` : ''}${nino ? '. Hubo Niño costero en la temporada de lluvias' : ''}`;
    return `${nino ? `<rect class="hz-tl-nino" x="${(i * bw).toFixed(1)}" y="0" width="${bw.toFixed(1)}" height="${H - 16}"></rect>` : ''}<rect class="hz-tl-bar" x="${(i * bw + bw * 0.15).toFixed(1)}" y="${(H - 16 - h).toFixed(1)}" width="${(bw * 0.7).toFixed(1)}" height="${h.toFixed(1)}" data-tip="${esc(label)}"><title>${esc(label)}</title></rect>`;
  }).join('');
  // La primera etiqueta va alineada a la izquierda para que no se corte en el borde.
  const ticks = years.filter((y) => y % 10 === 0).map((y) => `<text class="hz-tl-x" x="${y === from ? 0 : ((y - from) * bw + bw / 2).toFixed(1)}" y="${H - 3}"${y === from ? ' data-a="start"' : ''}>${y}</text>`).join('');
  const names = compact ? '' : years.filter((y) => named.has(y) && (by.get(y)?.da.size || 0) > 0).map((y) => `<text class="hz-tl-n" x="${((y - from) * bw + bw / 2).toFixed(1)}" y="11">${named.get(y)}</text>`).join('');
  return `<svg class="hz-tl${compact ? ' hz-tl-c' : ''}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Lugares con daños por temporada de lluvias, ${from}-${last}. Las franjas marcan temporadas con El Niño costero.">${bars}${ticks}${names}</svg>`;
}

// ---------------------------------------------------------------------------
// Vista
// ---------------------------------------------------------------------------
export const memoriaView = {
  title: 'Memoria de desastres',
  render() {
    return html`
      <div class="page-head"><div class="eyebrow">Memoria de desastres · 1559–2026</div><h1>Dónde golpearon antes El Niño, las lluvias y los huaycos</h1>
        <p>Catálogo de inundaciones, desbordes, huaycos, deslizamientos, lluvias intensas, oleajes, sequías, heladas y otros desastres de origen climático en el Perú, ubicados por distrito y con su fuente. Sirve para prepararse: si un Niño como los anteriores vuelve, lo más probable es que vuelva a golpear donde ya golpeó.</p></div>
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
  const stats = M.byArea(recs, s.nivel, years, D.nino, D.great, D.hom);
  const vals = [...stats.values()].map((st) => metricValue(st, s.metrica)).filter((v) => v !== null);
  const scale = scaleFor(s.metrica, vals, s.nivel);
  const evOpts = [['', 'Todos los registros'], ['grandes', 'Solo los grandes Niños'], ...D.great.map((g) => [g, g]), ...(D.ongoing ? [[D.ongoing, `${D.ongoing} (en curso)`]] : []), ['nino', 'Cualquier Niño costero'], ['nina', 'La Niña costera'], ['neutro', 'Años neutros']];
  const yMin = D.sum.cobertura.anios[0], yMax = D.sum.cobertura.anios[1];
  const label = `Mapa por ${s.nivel}: ${METRICS.find(([k]) => k === s.metrica)[1]}`;
  const nat = M.summarize(recs, years, D.nino, D.great, false, D.hom);
  return html`
    ${contextBanner(D)}
    <section class="card hz-card" aria-labelledby="hz-map-h">
      <div class="section-head"><h2 id="hz-map-h">Mapa de la memoria</h2><span class="muted small">${n0(recs.length)} de ${n0(D.recs.length)} registros</span></div>
      <form class="hz-filters" id="hz-filters" aria-label="Filtros del mapa">
        <label class="hz-f"><span>Evento</span><select class="input" name="evento">${evOpts.map(([v, t]) => html`<option value="${v}" ${v === s.evento ? raw('selected') : ''}>${t}</option>`)}</select></label>
        <label class="hz-f"><span>Peligro</span><select class="input" name="peligro"><option value="">Todos</option>${Object.entries(HAZARD_GROUPS).map(([k, [t]]) => html`<option value="${k}" ${k === s.peligro ? raw('selected') : ''}>${t}</option>`)}
          <optgroup label="Un tipo">${Object.keys(DANGER_LABEL).map((t) => html`<option value="${t}" ${t === s.peligro ? raw('selected') : ''}>${dl(t)}</option>`)}</optgroup></select></label>
        <label class="hz-f hz-f-s"><span>Desde</span><input class="input" name="desde" type="number" inputmode="numeric" min="${yMin}" max="${yMax}" placeholder="${yMin}" value="${s.desde}"></label>
        <label class="hz-f hz-f-s"><span>Hasta</span><input class="input" name="hasta" type="number" inputmode="numeric" min="${yMin}" max="${yMax}" placeholder="${yMax}" value="${s.hasta}"></label>
        <label class="hz-f"><span>Mostrar</span><select class="input" name="metrica">${METRICS.map(([v, t]) => html`<option value="${v}" ${v === s.metrica ? raw('selected') : ''}>${t}</option>`)}</select></label>
        <div class="hz-f"><span id="hz-lvl-l">Nivel</span><div class="seg" role="group" aria-labelledby="hz-lvl-l">${LEVEL_NAMES.map(([v, t]) => html`<button type="button" data-nivel="${v}" aria-pressed="${String(v === s.nivel)}">${t}</button>`)}</div></div>
        <div class="hz-f hz-search"><label for="hz-q"><span>Buscar lugar</span></label><input class="input" id="hz-q" list="hz-places" placeholder="Distrito, provincia o departamento" autocomplete="off"><datalist id="hz-places"></datalist></div>
        ${s.evento || s.peligro || s.desde || s.hasta || s.area ? html`<button type="button" class="btn ghost hz-clear" data-clear>Quitar filtros</button>` : ''}
      </form>
      <div class="hz-grid">
        <div class="hz-mapbox">
          ${raw(mapSvg(D, s, stats, scale, { label }))}
          <div class="hz-tip" role="tooltip" hidden></div>
          ${s.area && s.nivel !== 'departamento' ? html`<button type="button" class="btn ghost hz-zoomout" data-area="">${raw(ICON.globe)}<span>Ver todo el Perú</span></button>` : ''}
          ${legendHtml(scale, s.metrica)}
          <p class="muted small">${s.nivel === 'departamento' ? 'Toque un departamento para ver su ficha.' : 'Toque un área para ver su ficha y acercar el mapa a su departamento. También puede buscarla arriba o elegirla en la tabla.'} Los registros a escala de departamento no se pintan en provincias ni distritos.</p>
        </div>
        <aside class="hz-side" id="hz-side" aria-live="polite">${s.area ? profileShell(D, s, recs, years) : nationalCard(D, nat, recs, years)}</aside>
      </div>
    </section>
    <section class="card hz-card" aria-labelledby="hz-tl-h">
      <div class="section-head"><h2 id="hz-tl-h">Lugares con daños en cada temporada de lluvias</h2></div>
      <p class="muted small">Cada barra es una temporada (julio a junio): cuántos lugares distintos tuvieron registros con los filtros elegidos. Franja rosada: hubo El Niño costero en diciembre–abril (ICEN). Las fuentes cambian con el tiempo y las barras no se comparan directamente: DesInventar hasta 2015 (menos registros antes de 1990) y, desde 2016, el SINPAD del INDECI, que registra muchas más emergencias por año. Ver «Límites».</p>
      ${raw(timeline(D, recs))}
    </section>
    ${greatSection(D, s)}
    ${rankingSection(D, s, stats)}
    <section class="card hz-card" id="hz-prev" aria-labelledby="hz-prev-h"><div class="section-head"><h2 id="hz-prev-h">¿Se sabía antes? Peligros documentados y emergencias que igual ocurrieron</h2></div><p class="muted">Cargando declaratorias, evaluaciones e inventarios…</p></section>
    ${pastSection(D)}
    ${evidenceSection(D)}
    ${methodSection(D)}`;
}

function contextBanner(D) {
  const cur = D.sum.eventosICEN.filter((e) => e.fase === 'warm').at(-1);
  const last = D.sum.icenUltimo;
  if (!cur || !cur.enCurso) return '';
  const strong = ['fuerte', 'extraordinaria'].includes(cur.magnitud);
  return html`<div class="notice ${strong ? 'notice-alert' : 'notice-warn'} hz-context" role="note">${raw(ICON.triangle)}
    <p><strong>El Niño costero está en curso desde ${F.fmtMonth(cur.inicio)}${last ? html`; el ICEN de ${F.fmtMonth(last[0])} fue ${F.fmtValue(last[1], 'degC')}, magnitud ${cur.magnitud}` : ''}.</strong>
    ${strong ? 'Es la misma categoría que alcanzaron 1982-83 y 1997-98.' : ''} Use «Solo los grandes Niños» en el mapa para ver dónde golpearon los eventos anteriores. Las alertas oficiales son las del ENFEN, el SENAMHI y el INDECI.</p></div>`;
}

function nationalCard(D, st, recs, years) {
  const byDep = M.byArea(recs, 'departamento', years, D.nino, D.great, D.hom);
  const top = [...byDep.entries()].filter(([, v]) => v.razonNino && v.razonNinoIC[0] > 1).sort((a, b) => b[1].razonNino - a[1].razonNino).slice(0, 6);
  return html`<div class="hz-prof">
    <h3 class="hz-prof-h">Todo el Perú</h3>
    <div class="hz-tiles">
      <div class="hz-tile"><span class="hz-tile-v">${n0(st.registros)}</span><span class="hz-tile-l">registros con los filtros elegidos</span></div>
      <div class="hz-tile"><span class="hz-tile-v">${n0(st.muertos)}</span><span class="hz-tile-l">fallecidos y desaparecidos reportados</span></div>
      <div class="hz-tile"><span class="hz-tile-v">${n0(st.viviendas)}</span><span class="hz-tile-l">viviendas destruidas reportadas</span></div>
      <div class="hz-tile"><span class="hz-tile-v">${st.razonNino ? x1(st.razonNino) : 'N/D'}</span><span class="hz-tile-l">más lugares dañados por año cuando hay Niño costero (1970-2015)</span></div>
    </div>
    ${top.length ? html`<h4 class="hz-h4">Donde El Niño más multiplica los daños</h4>
      <ol class="hz-bars">${top.map(([c, v]) => html`<li><button type="button" class="linkish" data-area="${c}">${shortName(D, c)}</button><span class="hz-bar"><span style="width:${Math.min(100, (v.razonNino / top[0][1].razonNino) * 100).toFixed(0)}%"></span></span><span class="hz-bar-v">${x1(v.razonNino)}</span></li>`)}</ol>
      <p class="muted small">Razón entre los lugares con daños por año en temporadas con Niño costero y en las demás, con intervalo de confianza al 95 % por encima de 1.</p>` : ''}
    <p class="muted small">Elija un área en el mapa, en la tabla o con el buscador para ver su historia, sus indicadores y qué esperar si se repite un gran Niño.</p>
  </div>`;
}

function profileShell(D, s, recs, years) {
  const code = s.area;
  const mine = recs.filter((r) => r.u.startsWith(code));
  const lvl = code.length === 6 ? 'distrito' : code.length === 4 ? 'provincia' : 'departamento';
  const st = M.summarize(mine, years, D.nino, D.great, lvl !== 'departamento', D.hom);
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
  const expect = st.registros ? html`<div class="hz-expect"><h4 class="hz-h4">Si se repite un gran Niño</h4><p>${greatRecs.length
    ? html`En ${st.grandesNinos.join(', ')} hubo registros aquí, sobre todo de ${greatTypes.join(', ').toLowerCase()}. Un evento parecido probablemente vuelva a afectar este lugar.`
    : 'Los grandes Niños no dejaron registros aquí en las fuentes del catálogo; eso no garantiza que no ocurra (la cobertura es incompleta).'} ${peakM.length ? `Los meses con más registros son ${peakM.join(' y ')}.` : ''} ${st.razonNino ? (st.razonNinoIC[0] > 1 ? `Con Niño costero, los daños por año son ${x1(st.razonNino)} los de otros años.` : st.razonNinoIC[1] < 1 ? 'Aquí los daños son menos frecuentes en años de Niño costero (en la sierra sur el Niño suele traer sequía en lugar de lluvias).' : 'Aquí la frecuencia de daños no cambia de forma clara con El Niño costero.') : ''}</p></div>` : '';
  return html`<div class="hz-prof">
    <div class="hz-prof-top"><h3 class="hz-prof-h">${shortName(D, code)} <span class="muted small">(${lvl})</span></h3><button type="button" class="icon-btn" data-area="" aria-label="Cerrar la ficha">${raw(ICON.close)}</button></div>
    ${parents}
    <p class="hz-prof-meta">${attnChip(st.nivelAtencion)} ${pop ? html`<span class="muted small">Población 2020 ≈ ${n0(pop)}${a?.[1] ? ` · pobreza ${F.fmtNumber(a[1], 0)} %` : ''}${a?.[3] ? ` · ${n0(a[3])} m s. n. m.` : ''}</span>` : ''}</p>
    <div class="hz-tiles">
      <div class="hz-tile"><span class="hz-tile-v">${st.aniosConEvento} <small>de ${st.aniosCobertura}</small></span><span class="hz-tile-l">años con daños (1970-2015)${st.muestraPequena ? ' · muestra pequeña' : ''}</span></div>
      <div class="hz-tile"><span class="hz-tile-v">${st.periodoRetorno ? `1 de cada ${F.fmtNumber(st.periodoRetorno, 1)}` : 'N/D'}</span><span class="hz-tile-l">años, en promedio (frecuencia histórica, no pronóstico)</span></div>
      <div class="hz-tile"><span class="hz-tile-v">${st.prob5Anios !== null ? pct(st.prob5Anios) : 'N/D'}</span><span class="hz-tile-l">de probabilidad histórica de al menos un año con daños en 5 años</span></div>
      <div class="hz-tile"><span class="hz-tile-v">${st.grandesNinos.length} <small>de ${D.great.length}</small></span><span class="hz-tile-l">grandes Niños con registros aquí</span></div>
    </div>
    <ul class="hz-great">${D.great.map((g) => html`<li class="${st.grandesNinos.includes(g) ? 'hit' : ''}">${raw(st.grandesNinos.includes(g) ? ICON.check : ICON.dash)}<span>${g}</span></li>`)}</ul>
    ${now.length ? html`<p class="hz-now">${raw(ICON.triangle)}<span><strong>${D.ongoing}:</strong> ${n0(now.length)} registro${now.length > 1 ? 's' : ''} aquí desde ${F.fmtMonth(now.map((r) => r.d).sort()[0])}, el último el ${when(now.map((r) => r.d).sort().at(-1))}.</span></p>` : ''}
    ${expect}
    <div id="hz-ctx"></div>
    <div id="hz-prevbox"></div>
    <dl class="hz-kv"><div><dt>Fallecidos y desaparecidos</dt><dd>${n0(st.muertos)}</dd></div><div><dt>Afectados y damnificados</dt><dd>${n0(st.afectados)}</dd></div><div><dt>Viviendas destruidas</dt><dd>${n0(st.viviendas)}</dd></div><div><dt>Cuánto más daño con Niño</dt><dd>${metricText(st, 'razon')}</dd></div></dl>
    ${hz.length ? html`<h4 class="hz-h4">Peligros registrados</h4><ol class="hz-bars">${hz.map(([t, v]) => html`<li><span>${dl(t)}</span><span class="hz-bar"><span style="width:${((v / maxHz) * 100).toFixed(0)}%"></span></span><span class="hz-bar-v">${n0(v)}</span></li>`)}</ol>` : ''}
    <h4 class="hz-h4">Temporadas con daños aquí</h4>
    ${raw(timeline(D, mine, { compact: true }))}
    <h4 class="hz-h4">Registros (${n0(mine.length)})</h4>
    <div id="hz-list"><p class="muted small">Cargando descripciones y fuentes…</p></div>
  </div>`;
}

async function fillDetail(root, D, s) {
  const box = $('#hz-list', root);
  if (!box) return;
  const f = currentFilter(D, s);
  const mine = M.filter(D.recs, f).filter((r) => r.u.startsWith(s.area));
  const sorted = [...mine].sort((a, b) => (b.muertos + b.viv / 10 + (D.great.includes(b.e) ? 1000 : 0)) - (a.muertos + a.viv / 10 + (D.great.includes(a.e) ? 1000 : 0)) || b.d.localeCompare(a.d));
  const det = await detail(s.area.slice(0, 2));
  if (!box.isConnected) return;
  let shown = 12;
  const item = (r) => {
    const d = det[String(r.i)] || [];
    const [desc, , cite, url, dur] = d;
    const more = d[10] || 0, links = d[11] || [], kind = DATE_KIND[d[12]];
    return html`<li class="hz-ev"><div class="hz-ev-top"><span class="hz-ev-d">${when(r.d)}</span>${kind ? html`<span class="muted small">(${kind})</span>` : ''}<span class="tag">${dl(r.t)}</span>${r.e && !/^(Sin asociación|Temporada)/.test(r.e) ? html`<span class="tag tag-warm">${r.e}</span>` : ''}${r.o === 'curado' ? html`<span class="tag">curado</span>` : ''}${r.e === D.ongoing ? html`<span class="tag tag-warm">en curso</span>` : ''}</div>
      <p class="hz-ev-where">${areaName(D, r.u)}${dur ? ` · ${dur} día${dur > 1 ? 's' : ''}` : ''}</p>
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
  // Alto lógico igual al de la hoja de estilos (150 px) para que las etiquetas solo se estiren a lo ancho.
  const W = 1000, H = 150, top = 6, base = H - 26, bw = W / rows.length, gap = 2;
  const bars = rows.map((a, i) => {
    const share = a.eventosConAviso / a.eventos;
    const h = base - top, hA = share * h;
    const x = (i * bw + bw * 0.12).toFixed(1), w = (bw * 0.76).toFixed(1);
    const label = `${a.anio}: ${n0(a.eventosConAviso)} de ${n0(a.eventos)} emergencias (${pct(share)}) en distritos con el peligro ya documentado`;
    return `<g data-tip="${esc(label)}"><title>${esc(label)}</title><rect class="hz-pv-b" x="${x}" y="${top}" width="${w}" height="${Math.max(0, h - hA - gap).toFixed(1)}" rx="2"></rect><rect class="hz-pv-a" x="${x}" y="${(base - hA).toFixed(1)}" width="${w}" height="${hA.toFixed(1)}" rx="2"></rect></g>`;
  }).join('');
  // Primer y último año pegados a los bordes; los quinquenios demasiado cerca de ellos se omiten para no encimarse.
  const last = rows.length - 1;
  const ticks = rows.map((a, i) => ({ a, i })).filter(({ a, i }) => i === 0 || i === last || (a.anio % 5 === 0 && i > 2 && i < last - 2)).map(({ a, i }) => {
    const x = i === 0 ? 0 : i === last ? W : i * bw + bw / 2;
    const anchor = i === 0 ? ' data-a="start"' : i === last ? ' data-a="end"' : '';
    return `<text class="hz-tl-x" x="${x.toFixed(1)}" y="${H - 4}"${anchor}>${a.anio}</text>`;
  }).join('');
  const grid = [0.5, 1].map((v) => `<line class="hz-pv-grid" x1="0" x2="${W}" y1="${(base - v * (base - top)).toFixed(1)}" y2="${(base - v * (base - top)).toFixed(1)}"></line>`).join('');
  return `<svg class="hz-tl hz-pv" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Parte de las emergencias oficiales de cada año ocurridas donde el peligro ya estaba documentado, ${rows[0].anio}-${rows.at(-1).anio}">${grid}${bars}${ticks}</svg>`;
}

async function fillPrevention(root, D) {
  const box = $('#hz-prev', root);
  if (!box) return;
  const P = await prevention();
  if (!box.isConnected) return;
  const head = '<div class="section-head"><h2 id="hz-prev-h">¿Se sabía antes? Peligros documentados y emergencias que igual ocurrieron</h2></div>';
  if (!P) { box.innerHTML = `${head}<p class="muted">No se pudo cargar prevencion.json.</p>`; return; }
  const A = objs({ cols: P.columnasAnual, rows: P.anual });
  const sum = (rows, k) => rows.reduce((t, a) => t + (a[k] || 0), 0);
  const recent = A.filter((a) => a.anio >= 2016);
  const ev = sum(recent, 'eventos'), aviso = sum(recent, 'eventosConAviso');
  const c = (k) => P.columnas.indexOf(k);
  const dists = Object.values(P.distritos);
  const repeat = dists.filter((v) => v[c('aniosConEvento')] >= 5);
  const repeatKnown = repeat.filter((v) => v[c('inventarioDesde')] || v[c('primeraEvaluacion')]).length;
  const appeals = objs(P.llamamientos).filter((a) => a.clima);
  const decI = sum(A, 'decretosInminente'), decD = sum(A, 'decretosImpacto'), decP = sum(A, 'prorrogas');
  const elp = D.sum.fuentes.find((f) => f.id === 'elperuano-emergencias');
  const pending = elp && elp.parcial;
  box.innerHTML = String(html`${raw(head)}
    <p>Para cada emergencia oficial (SINPAD, DesInventar y COEN, con la fecha del evento) se mira qué se sabía antes en su distrito: si INGEMMET ya había inventariado ahí un peligro del mismo tipo, si había un informe técnico de INGEMMET o del IGP de un año anterior, o si estaba vigente una declaratoria de emergencia por peligro inminente.</p>
    <div class="hz-tiles hz-tiles-4">
      <div class="hz-tile"><span class="hz-tile-v">${ev ? pct(aviso / ev) : 'N/D'}</span><span class="hz-tile-l">de las ${n0(ev)} emergencias oficiales desde 2016 ocurrieron donde el peligro ya estaba documentado</span></div>
      <div class="hz-tile"><span class="hz-tile-v">${n0(repeat.length)}</span><span class="hz-tile-l">distritos con emergencias en 5 o más temporadas desde 2003; en ${n0(repeatKnown)} el peligro ya estaba inventariado o evaluado</span></div>
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
      <li>«Documentado» no quiere decir que se pudiera evitar, sino que el Estado tenía el peligro identificado en ese distrito antes de la emergencia. El inventario de INGEMMET marca puntos de peligro (caídas, deslizamientos, huaycos, erosión, inundación) con la fecha en que los inventarió; el mismo grupo de peligro cuenta (un inventario de huaycos vale para una emergencia por lluvias intensas).</li>
      <li>Las notas de prensa no entran a esta cuenta; sí corroboran las fichas en la lista de cada área. Los reportes del COEN entran con la fecha del evento cuando su PDF ya se leyó.</li>
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
    o.src.add(r.o === 'glof' ? 'base de GLOF' : r.o === 'curado' ? 'archivos' : r.o);
  }
  const rows = [...by.entries()].sort((a, b) => b[1].years.size - a[1].years.size || a[0].localeCompare(b[0]));
  const first = Math.min(...old.map((r) => r.y));
  return html`<section class="card hz-card" aria-labelledby="hz-past-h">
    <div class="section-head"><h2 id="hz-past-h">Antes de 1970: los mismos lugares, una y otra vez</h2><span class="muted small">${n0(old.length)} registros desde ${first}</span></div>
    <p class="muted small">Las actas del Cabildo de Trujillo y otros archivos (cronología de García-Herrera et al., 2008) registran lluvias e inundaciones de El Niño en Trujillo, Chicama, Saña, Lambayeque y Piura desde el siglo XVI; la base mundial de desbordes de lagunas glaciares registra los aluviones de la Cordillera Blanca y otras cordilleras. Son los mismos lugares que vuelven a aparecer en 1983, 1998, 2017 y 2023.</p>
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
    <p class="muted small">Los 40 primeros con los filtros elegidos. Es también la versión en tabla del mapa. «Muestra pequeña»: menos de 5 años con daños, la frecuencia es poco confiable.</p>
    <div class="table-wrap"><table class="hz-table"><thead><tr><th scope="col">Lugar</th><th scope="col">Valor</th><th scope="col" class="num">Años con daños</th><th scope="col" class="num">Grandes Niños</th><th scope="col">Atención</th><th scope="col">Peligro principal</th><th scope="col">Último registro</th></tr></thead>
    <tbody>${rows.map(([c, st]) => html`<tr><th scope="row"><button type="button" class="linkish" data-area="${c}">${areaName(D, c)}</button></th><td>${metricText(st, s.metrica)}</td><td class="num">${st.aniosConEvento}${st.muestraPequena ? html` <span class="tag" title="Menos de 5 años con daños">muestra pequeña</span>` : ''}</td><td class="num">${st.grandesNinos.length}</td><td>${attnChip(st.nivelAtencion)}</td><td>${st.peligros[0] ? dl(st.peligros[0][0]) : ''}</td><td>${st.ultimo ? when(st.ultimo.d) : ''}</td></tr>`)}</tbody></table></div>
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
  const unit = { eventos: 'registros', emergencias: 'registros propios', prensa: 'registros propios', prevencion: 'elementos' }[k] || 'elementos';
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
        </ul>
        ${[['eventos', 'Fuentes de eventos'], ['emergencias', 'Reportes de emergencia del COEN (se unen a las fichas del SINPAD)'], ['prensa', 'Prensa regional y nacional (cada nota se une al evento que cuenta)'], ['prevencion', 'Prevención: declaratorias, evaluaciones, inventarios y llamamientos'], ['contexto', 'Peligro identificado hoy (contexto, no eventos)'], ['referencia', 'Referencias territoriales']].map(([k, t]) => html`<h3 class="hz-h3">${t}</h3>
        ${k === 'prensa' ? html`<details class="more"><summary>${n0(S.fuentes.filter((f) => f.tipo === k).length)} medios</summary>${srcList(S, k)}</details>` : srcList(S, k)}`)}
        <p class="muted small">Catálogo generado el ${F.fmtDate(S.generatedAt.slice(0, 10))}. Límites: IGN vía OCHA HDX (CC BY-IGO). Población, pobreza e IDH por distrito: INEI y PNUD vía ubigeo-peru-aumentado (MIT).</p>
      </div>
      <div>
        <h3 class="hz-h3">Cómo leer los indicadores</h3>
        <ul class="hz-method">
          <li><strong>Años con daños</strong>: temporadas (julio a junio) de 1970-71 a 2014-15 con al menos un registro de DesInventar en el lugar, con intervalo de Wilson al 95 %. Se cuentan años y no registros porque un mismo Niño deja decenas de fichas. Las fuentes posteriores no entran a esta cuenta porque tienen otra densidad.</li>
          <li><strong>1 de cada X años</strong> y <strong>probabilidad en 5 años</strong>: frecuencia histórica; suponen que el clima y la exposición no cambian. No son pronósticos.</li>
          <li><strong>Cuánto más daño con Niño</strong>: lugares-año con daños por año en temporadas con Niño costero (ICEN, diciembre–abril) dividido entre los de las demás temporadas, con intervalo de Poisson al 95 %.</li>
          <li><strong>Nivel de atención</strong> (no es un índice oficial de riesgo): muy alto = registros en 2 o más grandes Niños y daños en al menos 1 de cada 4 años; alto = una de las dos; medio = 1 gran Niño o daños en 1 de cada 10 años; bajo = otros con registros.</li>
          <li><strong>TipoEvento</strong>: los eventos con nombre (Niño Costero 2017 en los 13 departamentos del Plan de Reconstrucción; Ciclón Yaku 2023 en la costa norte y Lima), solo para lluvias, inundaciones, huaycos, oleaje y viento, y los Niños y Niñas costeros del ICEN por la fecha del registro (del SINPAD desde 2019, solo las emergencias de nivel 3 o más, las que necesitaron al gobierno regional o al nacional). Que un registro caiga dentro de un Niño no prueba que el Niño lo causó.</li>
        </ul>
        <h3 class="hz-h3">Límites</h3>
        <ul class="hz-method">
          <li>${S.cobertura.nota}</li>
          <li>DesInventar se arma con prensa nacional e informes del INDECI: hay más registros de ciudades y lugares accesibles, y menos antes de los años 90. Una zona sin registros no es una zona sin peligro.</li>
          <li>Las cifras de impacto son las que publicó cada fuente; un vacío significa «no reportado», no cero. Las fuentes discrepan entre sí (Huggel et al., 2015).</li>
          <li>Los distritos se ubican con su UBIGEO o, si el nombre de la fuente está abreviado, con el punto de la fuente dentro de los límites del IGN; las coordenadas son las de la fuente si caen en el distrito asignado y, si no, las de la capital del distrito.</li>
          <li>Desde 2019 el SINPAD se lee del portal público del INDECI, que da el peligro, el distrito, la fecha, el nivel y el estado de cada emergencia, pero no su descripción ni sus daños. Por eso esas fichas se ubican en la capital del distrito y no aportan impactos; las del IDMC, que salen de las mismas emergencias, sí traen personas desplazadas y viviendas.</li>
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
  const stats = M.byArea(recs, s.nivel, years, D.nino, D.great, D.hom);
  const show = (el, x, y) => {
    const code = el?.dataset?.code;
    if (!code || !tip) return;
    const st = stats.get(code);
    tip.innerHTML = String(html`<strong>${areaName(D, code)}</strong><p>${metricText(st, s.metrica)}</p>${st ? html`<p class="muted small">${n0(st.registros)} registros · ${st.aniosConEvento} años con daños · ${st.grandesNinos.length} grandes Niños</p>` : ''}`);
    tip.hidden = false;
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let left = x + 16, top = Math.max(8, Math.min(innerHeight - th - 8, y - th / 2));
    if (left + tw > innerWidth - 8) left = Math.max(8, x - tw - 16);
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
  };
  const hide = () => { if (tip) tip.hidden = true; };
  svg.addEventListener('pointermove', (e) => { if (e.pointerType !== 'touch') show(e.target.closest('[data-code]'), e.clientX, e.clientY); });
  svg.addEventListener('pointerleave', hide);
  const pick = (code) => { hide(); set({ area: s.area === code ? '' : code }, '#hz-side'); };
  svg.addEventListener('click', (e) => { const t = e.target.closest('[data-code]'); if (t) pick(t.dataset.code); });
  svg.addEventListener('keydown', (e) => { const t = e.target.closest('[data-code]'); if (t && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); pick(t.dataset.code); } });
  svg.addEventListener('focusin', (e) => { const t = e.target.closest('[data-code]'); if (t) { const r = t.getBoundingClientRect(); show(t, r.left + r.width / 2, r.top + r.height / 2); } });
  svg.addEventListener('focusout', hide);
}
