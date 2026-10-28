// Memoria de desastres: la vista de detalle del mapa, más fina que el distrito. La cabecera del mapa cambia de vista
// sin sumar tableros abajo: «Resumen» (el mapa por área de siempre, historico.js) y tres detalles:
//
//   cuencas  las unidades hidrográficas de la ANA coloreadas por los registros de cada una, su ranking y la ficha de
//            una cuenca (sus temporadas, peligros, ríos, centros poblados y distritos)
//   puntos   los registros con un punto más fino que su distrito (hexágonos de densidad o puntos al acercarse), el
//            trazo de cada río, quebrada o laguna que nombran, y los ríos y centros poblados más nombrados
//   riesgo   cada distrito por dos variables a la vez (mapa bivariado de 3 × 3): qué tan seguido tuvo daños y qué
//            tan pobre es, con las manzanas que el CENEPRED evaluó ante El Niño 2026-2027 en la costa norte
//
// Datos (se piden al abrir un detalle): assets/historico/finos.json (cuenca, punto y nombres de cada registro, en el
// orden de eventos.json), assets/capas/rios-mapa.json y assets/capas/manzanas-riesgo.json
// (python -m tools.build_capas_mapa), y assets/cuencas-mapa.json. Este módulo no toca el DOM: arma el SVG y el panel
// y historico.js los monta y conecta; así las pruebas (node --test) llaman a las mismas funciones.

import { html, raw, esc } from './lib/dom.js';
import * as F from './lib/format.js';
import * as M from './historico-model.js';
import { ICON } from './icons.js';

export const VIEWS = [['resumen', 'Resumen'], ['cuencas', 'Cuencas'], ['puntos', 'Ríos y lugares'], ['riesgo', 'Daños y pobreza']];
export const VIEW_HINT = {
  resumen: 'Indicadores por departamento, provincia o distrito',
  cuencas: 'Registros por unidad hidrográfica de la ANA',
  puntos: 'Registros con punto propio, ríos y centros poblados que nombran',
  riesgo: 'Frecuencia de daños y pobreza de cada distrito, y manzanas en riesgo (CENEPRED)',
};
// «anios» como en el resumen (los años de DesInventar 1970-2015 con daños, M.summarize); «densidad» corrige el tamaño:
// una cuenca grande junta más registros solo por ser grande.
export const BASIN_METRICS = [['anios', 'Años con daños (1970-2015)'], ['densidad', 'Registros por 1 000 km²'], ['registros', 'Registros'],
  ['grandes', 'Grandes Niños con registros'], ['muertos', 'Fallecidos y desaparecidos'], ['afectados', 'Afectados, damnificados y desplazados'], ['viviendas', 'Viviendas destruidas']];
/** km² por px² del mapa (40 px por grado; la proyección ya corrige por el coseno de la latitud media: ±4 %). */
const KM2_PER_PX2 = (111.32 / 40) ** 2;
/** Cómo se ubicó un punto fino (finos.json, ``WEB_POINT_KIND`` de tools.build_historico). */
export const KIND = { 0: 'punto de campo de la fuente', 1: 'centro poblado que nombra', 3: 'río, quebrada o laguna que nombra' };
/** Niveles del CENEPRED, de mayor a menor (manzanas-riesgo.json → levels). */
const BLOCK_CLS = ['mz-0', 'mz-1', 'mz-2', 'mz-3'];

const n0 = (v) => F.fmtNumber(v, 0);

// ---------------------------------------------------------------------------
// Datos
// ---------------------------------------------------------------------------
const CACHE = new Map();
function load(path, prep = (x) => x) {
  if (!CACHE.has(path)) {
    CACHE.set(path, fetch(path, { cache: 'no-cache' }).then((r) => {
      if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
      return r.json();
    }).then(prep).catch((e) => { CACHE.delete(path); throw e; }));
  }
  return CACHE.get(path);
}

/** finos.json con índices por registro: ``ptOf`` (punto fino), ``aguaOf`` y ``lugarOf`` (nombre). */
export function prepFine(X) {
  X.ptOf = new Map(X.puntos.map((p) => [p[0], p]));
  X.aguaOf = new Map(X.agua);
  X.lugarOf = new Map(X.lugar);
  return X;
}
export const fine = () => load('assets/historico/finos.json', prepFine);
/**
 * rios-mapa.json con dos índices: ``byKey`` («cuenca|nombre», o «u<distrito>|nombre» para un río sin cuenca: las claves
 * de ``named`` sin la «r:») y ``byName`` («distrito|nombre» de cada distrito y grafía con que lo nombran los registros:
 * así ``named`` junta cada registro con el mismo trazo que tools.build_capas_mapa, que da a un río la cuenca más
 * frecuente de los registros que lo nombran en cada distrito).
 */
export function prepRivers(R) {
  R.byKey = new Map();
  R.byName = new Map();
  for (const r of R.reaches) {
    if (r.b) R.byKey.set(`${r.b}|${r.k}`, r);
    for (const u of r.u) {
      if (!r.b) R.byKey.set(`u${u}|${r.k}`, r);
      for (const k of [r.k, ...(r.a || [])]) if (!R.byName.has(`${u}|${k}`)) R.byName.set(`${u}|${k}`, r);
    }
  }
  return R;
}
export const rivers = () => load('assets/capas/rios-mapa.json', prepRivers);
export const blocks = () => load('assets/capas/manzanas-riesgo.json').catch(() => ({ levels: [], blocks: [] }));

/** La misma clave que ``tools.build_capas_mapa.norm``: sin tildes, en minúsculas, un espacio entre palabras. */
export const norm = (s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().split(/\s+/).filter(Boolean).join(' ');
/** «Río Chili (Sumbay)» → «Río Chili»; «A · B» → ['A', 'B']. */
export const waterNames = (s) => s.split(' · ').map((p) => p.replace(/\s*\([^)]*\)$/, '').trim()).filter(Boolean);

export const basinOf = (X, r) => (X.cuenca[r.i] ? X.cuencas[X.cuenca[r.i] - 1] : '');

// ---------------------------------------------------------------------------
// Cálculos (sin DOM)
// ---------------------------------------------------------------------------
function blank() {
  return { registros: 0, seasons: new Set(), muertos: 0, afectados: 0, viviendas: 0, grandes: new Set(), types: new Map(), places: new Map(), last: '', recs: [] };
}
function add(e, r, great) {
  e.registros++;
  e.seasons.add(M.seasonOf(r));
  e.muertos += r.muertos;
  e.afectados += r.afect;
  e.viviendas += r.viv;
  if (great.includes(r.e)) e.grandes.add(r.e);
  e.types.set(r.t, (e.types.get(r.t) || 0) + 1);
  e.places.set(r.u, (e.places.get(r.u) || 0) + 1);
  if (r.d > e.last) e.last = r.d;
  e.recs.push(r);
}

/** Registros por cuenca de la ANA: Map(código → {registros, seasons, muertos, …, recs}). */
export function byBasin(recs, X, great = []) {
  const out = new Map();
  for (const r of recs) {
    const code = basinOf(X, r);
    if (!code) continue;
    if (!out.has(code)) out.set(code, blank());
    add(out.get(code), r, great);
  }
  return out;
}

/** Valor de una métrica de cuenca; ``e.st``: M.summarize de sus registros, ``km2``: su superficie. */
export function basinValue(e, metric, km2 = 0) {
  if (metric === 'anios') return e ? e.st?.frecuenciaAnual ?? null : 0;
  if (!e) return 0;
  if (metric === 'densidad') return km2 ? (1000 * e.registros) / km2 : 0;
  if (metric === 'temporadas') return e.seasons.size;
  if (metric === 'grandes') return e.grandes.size;
  return e[metric] || 0;
}

/** Puntos de cada anillo de un trazo SVG con M, m, L, l y z. */
function rings(d) {
  const t = d.match(/[MmLlZz]|-?\d*\.?\d+(?:e[-+]?\d+)?/g) || [];
  let x = 0, y = 0, sx = 0, sy = 0, cmd = 'M', i = 0, cur = null;
  const out = [];
  while (i < t.length) {
    if (/[A-Za-z]/.test(t[i])) {
      cmd = t[i++];
      if (cmd === 'z' || cmd === 'Z') { x = sx; y = sy; }
      continue;
    }
    const a = +t[i], b = +t[i + 1];
    i += 2;
    if (cmd === 'M' || cmd === 'm') {
      x = cmd === 'M' ? a : x + a; y = cmd === 'M' ? b : y + b; sx = x; sy = y;
      out.push((cur = [[x, y]]));
      cmd = cmd === 'M' ? 'L' : 'l';
    } else if (cmd === 'L') { x = a; y = b; cur.push([x, y]); } else { x += a; y += b; cur.push([x, y]); }
  }
  return out;
}
/** Superficie de un trazo en km² (los anillos interiores restan: los trazos guardan su orientación). */
export function pathArea(d) {
  const sa = (r) => r.reduce((t, p, i) => { const q = r[(i + 1) % r.length]; return t + p[0] * q[1] - q[0] * p[1]; }, 0) / 2;
  return Math.abs(rings(d).reduce((t, r) => t + sa(r), 0)) * KM2_PER_PX2;
}
const AREAS = new Map();
const basinArea = (B, code) => { if (!AREAS.has(code)) AREAS.set(code, pathArea(B.units[code].d)); return AREAS.get(code); };

/** El nombre con más tildes y, entre iguales, el más usado (como ``_preferred`` en Python). */
function preferred(names) {
  return [...names.entries()].sort((a, b) => (b[0].replace(/[\x00-\x7f]/g, '').length - a[0].replace(/[\x00-\x7f]/g, '').length) || (b[1] - a[1]) || a[0].localeCompare(b[0]))[0][0];
}

/** Nevados, volcanes y abras: puntos, no trazos (tools.build_capas_mapa tampoco los dibuja). */
const NOT_WATER = /^(Nevado|Volcán|Abra)\b/;

/**
 * Los ríos o los centros poblados que nombran los registros, juntados: un río por su cuenca y su nombre (el mismo
 * «Río Rímac» en catorce distritos; dos «Quebrada Honda» de cuencas distintas no se juntan), un centro poblado por
 * su distrito y su nombre (un río sin cuenca, también por su distrito: «r:u150118:…»). Con ``R`` (prepRivers), un
 * río con trazo toma la clave de su trazo, para contar lo mismo que el mapa. [{key, name, where (cuenca o
 * distrito), basin, …indicadores}], de más a menos registros.
 */
export function named(recs, X, kind, great = [], R = null) {
  const of = kind === 'agua' ? X.aguaOf : X.lugarOf;
  const groups = new Map();
  for (const r of recs) {
    const ni = of.get(r.i);
    if (ni === undefined) continue;
    const parts = kind === 'agua' ? waterNames(X.nombres[ni]).filter((n) => !NOT_WATER.test(n)) : [X.nombres[ni]];
    for (const name of new Set(parts)) {
      const reach = kind === 'agua' ? R?.byName?.get(`${r.u}|${norm(name)}`) : null;
      const basin = reach ? reach.b : kind === 'agua' ? basinOf(X, r) : '';
      const where = reach ? (reach.b || `u${reach.u[0]}`) : basin || r.u;
      const key = reach ? reachKey(reach) : `${kind === 'agua' ? 'r' : 'l'}:${kind === 'agua' && !basin ? 'u' : ''}${where}:${norm(name)}`;
      let g = groups.get(key);
      if (!g) groups.set(key, (g = { key, where, basin, names: new Map(), ...blank() }));
      g.names.set(name, (g.names.get(name) || 0) + 1);
      add(g, r, great);
    }
  }
  return [...groups.values()].map((g) => ({ ...g, name: preferred(g.names) })).sort((a, b) => b.registros - a.registros || a.name.localeCompare(b.name));
}

/** Los registros de un foco («r:cuenca:nombre» o «l:distrito:nombre»). */
export function focusRecords(recs, X, foco, R = null) {
  const m = /^([rl]):(u?\d+):(.+)$/.exec(foco || '');
  if (!m) return null;
  const g = named(recs, X, m[1] === 'r' ? 'agua' : 'lugar', [], R).find((x) => x.key === foco);
  return g || null;
}

/** Hexágonos de densidad (como d3-hexbin, con la punta arriba): [{x, y, n, items}] en coordenadas del mapa; cada punto
 * va al hexágono de centro más cercano. */
export function hexbin(items, R, xy = (p) => p) {
  const dx = Math.sqrt(3) * R, dy = 1.5 * R;
  const bins = new Map();
  for (const it of items) {
    const [x, y] = xy(it);
    let py = y / dy, pj = Math.round(py), px = x / dx - (pj & 1) / 2, pi = Math.round(px);
    const py1 = py - pj;
    if (Math.abs(py1) * 3 > 1) {
      const px1 = px - pi, pi2 = pi + (px < pi ? -1 : 1) / 2, pj2 = pj + (py < pj ? -1 : 1), px2 = px - pi2, py2 = py - pj2;
      // Distancias de verdad (d3-hexbin las compara en unidades de celda, que no son iguales en x y en y).
      if ((px1 * dx) ** 2 + (py1 * dy) ** 2 > (px2 * dx) ** 2 + (py2 * dy) ** 2) { pi = pi2 + (pj & 1 ? 1 : -1) / 2; pj = pj2; }
    }
    const id = `${pi},${pj}`;
    let b = bins.get(id);
    if (!b) bins.set(id, (b = { x: (pi + (pj & 1) / 2) * dx, y: pj * dy, n: 0, items: [] }));
    b.n++;
    b.items.push(it);
  }
  return [...bins.values()];
}
export const hexPath = (R) => `m0 ${-R}${[1, 2, 3, 4, 5].map((i) => { const a = (i * Math.PI) / 3, b = ((i - 1) * Math.PI) / 3; return `l${(R * (Math.sin(a) - Math.sin(b))).toFixed(2)} ${(-R * (Math.cos(a) - Math.cos(b))).toFixed(2)}`; }).join('')}z`;

/** Cortes en terciles: [q1, q2] (un valor ≤ q1 es bajo, ≤ q2 medio, el resto alto). */
export function tertiles(values) {
  const v = values.filter((x) => x !== null && x !== undefined && Number.isFinite(x)).sort((a, b) => a - b);
  if (!v.length) return [0, 0];
  return [v[Math.floor((v.length - 1) / 3)], v[Math.floor((2 * (v.length - 1)) / 3)]];
}
export const tclass = (v, [q1, q2]) => (v <= q1 ? 0 : v <= q2 ? 1 : 2);

/**
 * Bivariado por distrito: x, la parte de los años de DesInventar (1970-2015) con daños; y, la pobreza monetaria
 * (INEI). Map(código → {x, y, freq, pob, cls}) y los cortes; un distrito sin uno de los dos queda fuera.
 */
export function bivariate(stats, attrs, codes, freqOf) {
  const freq = new Map(), pob = new Map();
  for (const c of codes) {
    const f = freqOf(stats.get(c));
    if (f !== null && f !== undefined) freq.set(c, f);
    const a = attrs.get(c);
    if (a && a[1] !== null && a[1] !== undefined) pob.set(c, a[1]);
  }
  const bx = tertiles([...freq.values()]), by = tertiles([...pob.values()]);
  const out = new Map();
  for (const c of codes) {
    if (!freq.has(c) || !pob.has(c)) continue;
    const x = tclass(freq.get(c), bx), y = tclass(pob.get(c), by);
    out.set(c, { x, y, freq: freq.get(c), pob: pob.get(c), cls: `b${x}${y}` });
  }
  return { cells: out, bx, by };
}

/** Caja [x0, y0, x1, y1] de un trazo SVG con M, L, l y z (los de este sitio). */
export function pathBox(d) {
  const t = d.match(/[MmLlZz]|-?\d*\.?\d+(?:e[-+]?\d+)?/g) || [];
  let x = 0, y = 0, sx = 0, sy = 0, cmd = 'M', i = 0;
  const box = [Infinity, Infinity, -Infinity, -Infinity];
  while (i < t.length) {
    if (/[A-Za-z]/.test(t[i])) {
      cmd = t[i++];
      if (cmd === 'z' || cmd === 'Z') { x = sx; y = sy; }
      continue;
    }
    const a = +t[i], b = +t[i + 1];
    i += 2;
    if (cmd === 'M') { x = a; y = b; sx = x; sy = y; cmd = 'L'; } else if (cmd === 'm') { x += a; y += b; sx = x; sy = y; cmd = 'l'; } else if (cmd === 'L') { x = a; y = b; } else { x += a; y += b; }
    box[0] = Math.min(box[0], x); box[1] = Math.min(box[1], y); box[2] = Math.max(box[2], x); box[3] = Math.max(box[3], y);
  }
  return box[0] === Infinity ? null : box;
}
export function joinBox(boxes) {
  const b = boxes.filter(Boolean);
  return b.length ? [Math.min(...b.map((x) => x[0])), Math.min(...b.map((x) => x[1])), Math.max(...b.map((x) => x[2])), Math.max(...b.map((x) => x[3]))] : null;
}
/** viewBox que encuadra una caja con margen y la proporción del mapa (3:4), sin acercarse más que ``min``. */
export function boxView([x0, y0, x1, y1], min = 30) {
  const pad = Math.max(6, (x1 - x0) * 0.15, (y1 - y0) * 0.15);
  const w = x1 - x0 + 2 * pad, h = y1 - y0 + 2 * pad, side = Math.max(w, h * 0.75, min);
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  return `${(cx - side / 2).toFixed(1)} ${(cy - side / 0.75 / 2).toFixed(1)} ${side.toFixed(1)} ${(side / 0.75).toFixed(1)}`;
}

/** Proyección de peru-map.json: grados → coordenadas del SVG. */
export function project(peru, lat, lon) {
  const p = peru.lonLat;
  return [(lon - p.lon0) * p.cos * p.k, (p.lat1 - lat) * p.k];
}

// ---------------------------------------------------------------------------
// Piezas comunes del panel
// ---------------------------------------------------------------------------
function tiles(list) {
  return html`<div class="hz-tiles">${list.map(([v, l]) => html`<div class="hz-tile"><span class="hz-tile-v">${v}</span><span class="hz-tile-l">${l}</span></div>`)}</div>`;
}
function bars(rows, { max = null, attr = null, fmt = n0 } = {}) {
  if (!rows.length) return '';
  const top = max || Math.max(1, ...rows.map((r) => r.v));
  return html`<ol class="hz-bars">${rows.map((r) => html`<li>${attr ? html`<button type="button" class="linkish" ${raw(`${attr}="${esc(r.id)}"`)}>${r.label}</button>` : html`<span>${r.label}</span>`}<span class="hz-bar"><span style="width:${Math.max(2, (r.v / top) * 100).toFixed(0)}%"></span></span><span class="hz-bar-v">${fmt(r.v)}</span></li>`)}</ol>`;
}
const topEntries = (map, n) => [...map.entries()].sort((a, b) => b[1] - a[1]).slice(0, n);

/** Ficha de un grupo de registros (una cuenca, un río, un centro poblado). */
function groupProfile(ctx, g, { title, sub = '', close, extra = '' }) {
  const { D, H, X, R } = ctx;
  const seasons = [...g.seasons].sort((a, b) => a - b);
  const hz = topEntries(g.types, 6).map(([t, v]) => ({ label: H.dl(t), v }));
  const places = topEntries(g.places, 8).map(([c, v]) => ({ id: c, label: H.shortName(D, c) + (c.length === 6 ? ` (${D.sum.nombres.provincia[c.slice(0, 4)] || ''})` : ''), v }));
  const waters = X ? named(g.recs, X, 'agua', [], R).filter((w) => w.key !== g.key).slice(0, 6).map((w) => ({ id: w.key, label: w.name, v: w.registros })) : [];
  const lugares = X ? named(g.recs, X, 'lugar').filter((w) => w.key !== g.key).slice(0, 6).map((w) => ({ id: w.key, label: `${w.name} (${H.shortName(D, w.where)})`, v: w.registros })) : [];
  const worst = [...g.recs].sort((a, b) => (b.muertos + b.viv / 10) - (a.muertos + a.viv / 10) || b.d.localeCompare(a.d)).slice(0, 6);
  const st = M.summarize(g.recs, ctx.years, D.nino, D.great, D.hom);
  const pct = (v) => `${F.fmtNumber(v * 100, 0)} %`;
  return html`<div class="hz-prof">
    <div class="hz-prof-top"><h3 class="hz-prof-h">${title}</h3><button type="button" class="icon-btn" ${raw(close)} aria-label="Cerrar la ficha">${raw(ICON.close)}</button></div>
    ${sub ? html`<p class="muted small">${sub}</p>` : ''}
    ${tiles([[n0(g.registros), `registros con los filtros elegidos, en ${n0(g.seasons.size)} temporadas${seasons.length > 1 ? ` (${seasons[0]}–${seasons.at(-1)})` : ''}`],
      st.aniosCobertura ? [html`${st.aniosConEvento} <small>de ${st.aniosCobertura}</small>`, `años de DesInventar (1970-2015) con daños; IC 95 %: ${pct(st.frecuenciaIC[0])}–${pct(st.frecuenciaIC[1])} de los años`] : ['N/D', 'años con daños: fuera del periodo 1970-2015'],
      [n0(g.muertos), 'fallecidos y desaparecidos reportados'], [html`${g.grandes.size} <small>de ${D.great.length}</small>`, 'grandes Niños con registros']])}
    ${g.grandes.size ? html`<p class="small">${[...g.grandes].join(' · ')}</p>` : ''}
    ${extra}
    ${hz.length ? html`<h4 class="hz-h4">Peligros registrados</h4>${bars(hz)}` : ''}
    <h4 class="hz-h4">Temporadas con registros</h4>
    ${raw(H.timeline(D, g.recs, { compact: true }))}
    ${places.length ? html`<h4 class="hz-h4">Distritos con más registros</h4>${bars(places, { attr: 'data-area' })}` : ''}
    ${waters.length ? html`<h4 class="hz-h4">Ríos, quebradas y lagunas que también nombran</h4>${bars(waters, { attr: 'data-foco' })}` : ''}
    ${lugares.length ? html`<h4 class="hz-h4">Centros poblados que nombran</h4>${bars(lugares, { attr: 'data-foco' })}` : ''}
    ${worst.length ? html`<h4 class="hz-h4">Registros con más daños</h4><ul class="hz-mini">${worst.map((r) => html`<li><button type="button" class="linkish" data-area="${r.u}">${H.areaName(D, r.u)}</button> <span class="muted small">${H.when(r.d)} · ${H.dl(r.t)}${r.muertos ? ` · ${n0(r.muertos)} fallecidos o desaparecidos` : ''}${r.viv ? ` · ${n0(r.viv)} viviendas destruidas` : ''}</span></li>`)}</ul>
      <p class="muted small">La descripción y la fuente de cada registro están en la ficha de su distrito.</p>` : ''}
  </div>`;
}

const outline = (D) => `<g class="hz-out" aria-hidden="true">${D.peru.departments.map((d) => `<path d="${d.d}"></path>`).join('')}</g>`;
const svgOpen = (vb, label) => `<svg class="hz-svg hz-det" viewBox="${vb}" role="group" aria-label="${esc(label)}" preserveAspectRatio="xMidYMid meet">`;
const fullView = (D) => `0 0 ${D.peru.width} ${D.peru.height}`;
/** 1 en el mapa de todo el Perú, menos al acercarse (para que los puntos no crezcan con el zoom). */
const unitOf = (vb) => { const [, , w, h] = vb.split(' ').map(Number); return Math.max(w, h * 0.75) / 507; };

/** El foco de un tramo: «r:cuenca:nombre», o «r:u<distrito>:nombre» sin cuenca (las claves de ``named``). */
export const reachKey = (r) => `r:${r.b || `u${r.u[0]}`}:${r.k}`;

/** Los ríos nombrados, como líneas (las lagunas, como su contorno): el del foco resaltado. */
function riverLayer(R, { basin = '', focus = '', min = 1 } = {}) {
  if (!R?.reaches?.length) return '';
  const max = Math.max(...R.reaches.map((r) => r.r));
  const w = (n) => (0.8 + 2.2 * Math.sqrt(n / max)).toFixed(2);
  const rows = R.reaches.filter((r) => r.r >= min && (!basin || r.b === basin));
  return `<g class="hz-rivers">${[...rows].reverse().map((r) => {
    const key = reachKey(r);
    const on = focus && (key === focus || (!r.b && r.u.some((u) => `r:u${u}:${r.k}` === focus)));
    return `<path class="hz-river${r.c === 'laguna' ? ' hz-lake' : ''}${on ? ' on' : ''}" d="${r.d}" style="stroke-width:${on ? 4 : w(r.r)}px" data-foco="${esc(key)}" data-tip="${esc(`${r.n}\n${n0(r.r)} registro${r.r > 1 ? 's' : ''} lo nombran en ${r.u.length} distrito${r.u.length > 1 ? 's' : ''}\nTrazo: Carta Nacional 1:100 000 (IGN)`)}"></path>`;
  }).join('')}</g>`;
}

// ---------------------------------------------------------------------------
// Detalle por cuenca
// ---------------------------------------------------------------------------
export function basinView(ctx) {
  const { D, s, recs, X, B, R, H } = ctx;
  const metric = BASIN_METRICS.some(([k]) => k === s.dm) ? s.dm : 'anios';
  const mlabel = BASIN_METRICS.find(([k]) => k === metric)[1];
  const agg = byBasin(recs, X, D.great);
  for (const e of agg.values()) e.st = M.summarize(e.recs, ctx.years, D.nino, D.great, D.hom);
  const value = (code) => (metric === 'anios' && !ctx.years.length ? null : basinValue(agg.get(code), metric, basinArea(B, code)));
  const vals = Object.keys(B.units).map(value).filter((v) => v !== null);
  const scale = metric === 'anios' ? H.scaleFor('anios', vals, 'provincia') : H.scaleFor(metric === 'grandes' ? 'grandes' : 'registros', vals);
  const fmt = metric === 'anios' ? (v) => (v === null ? 'N/D' : `${F.fmtNumber(v * 100, 0)} %`) : metric === 'densidad' ? (v) => F.fmtNumber(v, v < 10 ? 1 : 0) : n0;
  const sel = s.cuenca && B.units[s.cuenca] ? s.cuenca : '';
  const focus = s.foco ? focusRecords(recs, X, s.foco, R) : null;
  const reach = s.foco?.startsWith('r:') ? R?.byKey?.get(s.foco.slice(2).replace(':', '|')) : null;
  const vb = reach ? boxView(pathBox(reach.d)) : sel ? boxView(pathBox(B.units[sel].d)) : s.area ? H.viewBoxFor(D, s) : fullView(D);
  const paths = Object.entries(B.units).map(([code, u]) => {
    const e = agg.get(code);
    const v = value(code);
    const top = e ? topEntries(e.types, 1)[0] : null;
    const st = e?.st;
    const tip = [u.n, `${mlabel}: ${fmt(v)}`, st?.aniosCobertura ? `Daños en ${st.aniosConEvento} de ${st.aniosCobertura} años de DesInventar (1970-2015)` : '',
      e ? `${n0(e.registros)} registros${e.muertos ? ` · ${n0(e.muertos)} fallecidos o desaparecidos` : ''} · ${n0(basinArea(B, code))} km²` : 'Sin registros con los filtros elegidos',
      top ? `Peligro más frecuente: ${H.dl(top[0])}` : '', 'Toque para ver su ficha'].filter(Boolean).join('\n');
    return `<path class="hz-a hz-bu hz-${scale.cls(v)}${sel === code ? ' sel' : ''}" d="${u.d}" data-basin="${code}" data-tip="${esc(tip)}"></path>`;
  }).join('');
  const label = `Mapa de las cuencas de la ANA: ${mlabel.toLowerCase()} con los filtros elegidos`;
  const svg = `${svgOpen(vb, label)}<g>${paths}</g>${outline(D)}${riverLayer(R, { basin: sel, focus: reach ? s.foco : '', min: sel ? 1 : 3 })}${sel ? H.selRing(B.units[sel].d) : ''}</svg>`;
  const legend = html`<div class="hz-legend" aria-label="Leyenda: ${mlabel}"><span class="hz-legend-t">${mlabel}, por cuenca</span><ul>${scale.legend.map(([c, t]) => html`<li><span class="hz-sw hz-${c}"></span>${t}</li>`)}<li><span class="hz-sw-river"></span>Río nombrado en registros</li></ul></div>`;
  const control = html`<label class="hz-f"><span>Colorear por</span><select class="input" name="dm">${BASIN_METRICS.map(([k, t]) => html`<option value="${k}" ${k === metric ? raw('selected') : ''}>${t}</option>`)}</select></label>`;
  let side;
  if (focus) side = groupProfile(ctx, focus, { title: focus.name, sub: focusSub(ctx, focus, reach), close: 'data-foco=""' });
  else if (s.area && !sel) side = null;  // la ficha del área (historico.js)
  else if (sel) {
    const e = agg.get(sel) || blank();
    const u = B.units[sel];
    const rv = R?.reaches?.filter((r) => r.b === sel).length || 0;
    side = groupProfile(ctx, { ...e, key: '' }, { title: u.n, sub: `Unidad hidrográfica ${sel} de la ANA (Pfafstetter, nivel ${u.l}). ${rv ? `${rv} ríos, quebradas o lagunas nombrados en registros, dibujados en el mapa.` : ''}`, close: 'data-cuenca=""' });
  } else {
    const ranked = [...agg.keys()].map((c) => ({ id: c, label: B.units[c]?.n || c, v: value(c) })).filter((r) => r.v > 0).sort((a, b) => b.v - a.v).slice(0, 12);
    const withBasin = recs.filter((r) => X.cuenca[r.i]).length;
    side = html`<div class="hz-prof"><h3 class="hz-prof-h">Cuencas de la ANA</h3>
      ${tiles([[html`${n0(agg.size)} <small>de ${Object.keys(B.units).length}</small>`, 'unidades hidrográficas con registros'], [recs.length ? `${n0((100 * withBasin) / recs.length)} %` : '—', 'de los registros tienen cuenca']])}
      <h4 class="hz-h4">Cuencas con más ${mlabel.replace(/ \(.*\)$/, '').toLowerCase()}</h4>${bars(ranked, { attr: 'data-cuenca', fmt, max: metric === 'anios' ? 1 : null })}
      <p class="muted small">La cuenca de un registro es la del punto que dio la fuente, la del río o el centro poblado que nombra o, si no nombra un lugar, la de su distrito cuando el 80 % o más del distrito cae en una sola cuenca. Los registros de distritos repartidos entre cuencas, sin un lugar más fino, no se cuentan aquí. Unidades hidrográficas: ANA, delimitación Pfafstetter.</p></div>`;
  }
  return { svg, legend, control, side, extra: '', label };
}

/** Debajo del nombre de un río o un centro poblado: dónde está y qué se dibuja. */
function focusSub(ctx, focus, reach) {
  const { D, H, B } = ctx;
  if (focus.key.startsWith('l:')) return `Centro poblado de ${H.areaName(D, focus.where)} que nombran los registros`;
  const where = focus.basin ? (B.units[focus.basin]?.n || '') : H.areaName(D, focus.where);
  return `${where}${reach ? ` · ${reach.u.length} distrito${reach.u.length > 1 ? 's' : ''} con registros que lo nombran; su trazo, en el mapa (Carta Nacional 1:100 000, IGN)` : ' · sin trazo de la Carta para este nombre'}`;
}

// ---------------------------------------------------------------------------
// Detalle por ríos y lugares
// ---------------------------------------------------------------------------
export function pointsView(ctx) {
  const { D, s, recs, X, R, H } = ctx;
  const focus = s.foco ? focusRecords(recs, X, s.foco, R) : null;
  const reach = s.foco?.startsWith('r:') ? R?.byKey?.get(s.foco.slice(2).replace(':', '|')) : null;
  const pts = [];
  for (const r of recs) {
    const p = X.ptOf.get(r.i);
    if (p) pts.push({ r, p, xy: project(D.peru, p[1], p[2]) });
  }
  let box = null;
  if (focus) {
    const own = pts.filter(({ r }) => focus.recs.includes(r)).map(({ xy }) => [xy[0], xy[1], xy[0], xy[1]]);
    box = joinBox([reach ? pathBox(reach.d) : null, ...own]);
    if (!box && !focus.basin && D.map.districts[focus.where]) box = pathBox(D.map.districts[focus.where].d);
  }
  const vb = box ? boxView(box) : s.area ? H.viewBoxFor(D, s) : fullView(D);
  const unit = unitOf(vb);
  const zoomed = vb !== fullView(D);
  let layer;
  if (!zoomed) {
    const bins = hexbin(pts, 5.5, (q) => q.xy);
    const br = M.quantileBreaks(bins.map((b) => b.n), 5);
    const off = 5 - br.length;
    const shape = hexPath(5.5);
    layer = `<g class="hz-hex">${bins.map((b) => {
      const c = M.classOf(b.n, br);
      const kinds = [0, 1, 3].map((k) => b.items.filter((q) => q.p[3] === k).length);
      const where = topEntries(b.items.reduce((m, q) => m.set(q.r.u, (m.get(q.r.u) || 0) + 1), new Map()), 2).map(([u]) => H.shortName(D, u)).join(', ');
      const tip = `${n0(b.n)} registro${b.n > 1 ? 's' : ''} con punto propio\n${where}\n${kinds[0] ? `${n0(kinds[0])} de campo · ` : ''}${kinds[1] ? `${n0(kinds[1])} en centro poblado · ` : ''}${kinds[2] ? `${n0(kinds[2])} en un río` : ''}`.replace(/ · $/, '');
      return `<path class="hz-hx hz-q${c < 0 ? 0 : c + off}" d="M${b.x.toFixed(1)} ${b.y.toFixed(1)}${shape}" data-tip="${esc(tip)}" data-code="${b.items[0].r.u.slice(0, 2)}"></path>`;
    }).join('')}</g>`;
  } else {
    const dep = new Set((focus ? focus.recs.map((r) => r.u) : [s.area]).map((u) => u.slice(0, 2)));
    const shown = pts.filter(({ r }) => dep.has(r.u.slice(0, 2)));
    const at = new Map();
    for (const q of shown) {
      const k = `${q.xy[0].toFixed(1)},${q.xy[1].toFixed(1)},${q.p[3]}`;
      if (!at.has(k)) at.set(k, { q, recs: [] });
      at.get(k).recs.push(q.r);
    }
    layer = `<g class="hz-dots">${[...at.values()].sort((a, b) => b.recs.length - a.recs.length).map(({ q, recs: rs }) => {
      const on = focus && rs.some((r) => focus.recs.includes(r));
      const rad = unit * (1.8 + 1.1 * Math.sqrt(rs.length - 1));
      const name = q.p[3] === 3 ? X.nombres[X.aguaOf.get(q.r.i)] : q.p[3] === 1 ? X.nombres[X.lugarOf.get(q.r.i)] : '';
      const years = [...new Set(rs.map((r) => r.y))].sort();
      const tip = [name || 'Punto de campo de la fuente', `${rs.length} registro${rs.length > 1 ? 's' : ''} (${years.length > 1 ? `${years[0]}–${years.at(-1)}` : years[0]}) en ${H.shortName(D, q.r.u)}`, `${KIND[q.p[3]]}${q.p[4] ? `, ±${F.fmtNumber(q.p[4], q.p[4] % 1 ? 1 : 0)} km` : ''}`].join('\n');
      return `<circle class="hz-pt${q.p[3] === 1 ? ' hz-pt-cp' : q.p[3] === 3 ? ' hz-pt-w' : ''}${on ? ' on' : focus ? ' dim' : ''}" cx="${q.xy[0].toFixed(2)}" cy="${q.xy[1].toFixed(2)}" r="${rad.toFixed(2)}" data-code="${q.r.u}" data-tip="${esc(tip)}"></circle>`;
    }).join('')}</g>`;
  }
  const label = 'Mapa de los registros con punto propio y de los ríos que nombran';
  const ring = focus && !focus.basin && !reach ? H.selRing(D.map.districts[focus.where]?.d || '') : s.area && !focus ? H.selRing(H.areaShape(D, s.area)) : '';
  const svg = `${svgOpen(vb, label)}${outline(D)}${riverLayer(R, { focus: reach ? s.foco : '', min: zoomed ? 1 : 2 })}${layer}${ring}</svg>`;
  const legend = html`<div class="hz-legend" aria-label="Leyenda"><span class="hz-legend-t">${zoomed ? 'Registros con punto propio' : 'Registros con punto propio por hexágono (unos 15 km)'}</span><ul>
    ${zoomed ? html`<li><span class="hz-sw hz-sw-dot"></span>Punto de campo de la fuente</li><li><span class="hz-sw hz-sw-dot hz-sw-cp"></span>Centro poblado</li><li><span class="hz-sw hz-sw-dot hz-sw-w"></span>Río, quebrada o laguna</li>`
      : html`<li><span class="hz-sw hz-q0"></span>Pocos</li><li><span class="hz-sw hz-q2"></span></li><li><span class="hz-sw hz-q4"></span>Muchos</li>`}
    <li><span class="hz-sw-river"></span>Río nombrado (más grueso: más registros)</li></ul></div>`;
  let side = null;
  if (focus) side = groupProfile(ctx, focus, { title: focus.name, sub: focusSub(ctx, focus, reach), close: 'data-foco=""' });
  else if (!s.area) {
    const kinds = [0, 1, 3].map((k) => pts.filter((q) => q.p[3] === k).length);
    const basinTag = (w) => {
      const b = w.basin && ctx.B.units[w.basin] ? ctx.B.units[w.basin].n.replace(/^(Cuenca|Intercuenca) /, '') : '';
      return b && !norm(w.name).includes(norm(b)) && !norm(b).includes(norm(w.name).replace(/^(rio|quebrada|laguna) /, '')) ? ` · ${b}` : '';
    };
    const ws = named(recs, X, 'agua', [], R).slice(0, 10).map((w) => ({ id: w.key, label: `${w.name}${basinTag(w)}`, v: w.registros }));
    const ls = named(recs, X, 'lugar').slice(0, 10).map((w) => ({ id: w.key, label: `${w.name} (${H.shortName(D, w.where)})`, v: w.registros }));
    side = html`<div class="hz-prof"><h3 class="hz-prof-h">Más fino que el distrito</h3>
      ${tiles([[n0(pts.length), `de ${n0(recs.length)} registros tienen un punto propio: ${n0(kinds[0])} de campo, ${n0(kinds[1])} en un centro poblado y ${n0(kinds[2])} sobre un río, una quebrada o una laguna`],
        [n0(named(recs, X, 'agua', [], R).length), 'ríos, quebradas y lagunas nombrados (por cuenca)']])}
      <h4 class="hz-h4">Ríos, quebradas y lagunas más nombrados</h4>${bars(ws, { attr: 'data-foco' })}
      <h4 class="hz-h4">Centros poblados más nombrados</h4>${bars(ls, { attr: 'data-foco' })}
      <p class="muted small">Un punto de campo es el que trae la ficha de la fuente (SINPAD, DesInventar) cuando no es uno por defecto; un centro poblado o un río salen del texto del registro, dentro de su distrito (ver «Cómo se ubicó cada registro» en la metodología). Toque un río o un centro poblado para ver sus registros.</p></div>`;
  }
  return { svg, legend, control: '', side, extra: '', label };
}

// ---------------------------------------------------------------------------
// Detalle de daños y pobreza (bivariado) y manzanas del CENEPRED
// ---------------------------------------------------------------------------
const pctTxt = (v) => `${F.fmtNumber(v * 100, 0)} %`;
export function riskView(ctx) {
  const { D, s, H, K } = ctx;
  const stats = H.statsFor(D, s, ctx.recs, ctx.years, 'distrito');
  const codes = Object.keys(D.map.districts);
  const { cells, bx, by } = bivariate(stats, D.attrs, codes, (st) => (st?.aniosCobertura ? st.frecuenciaAnual : null));
  const vb = s.area ? H.viewBoxFor(D, s) : fullView(D);
  const unit = unitOf(vb);
  const xl = ['baja', 'media', 'alta'], yl = ['baja', 'media', 'alta'];
  const paths = codes.map((code) => {
    const c = cells.get(code);
    const tip = c ? `${H.areaName(D, code)}\nDaños en el ${pctTxt(c.freq)} de los años de DesInventar (frecuencia ${xl[c.x]})\nPobreza monetaria: ${F.fmtNumber(c.pob, 0)} % (${yl[c.y]})` : `${H.areaName(D, code)}\nSin frecuencia (fuera de DesInventar 1970-2015) o sin dato de pobreza`;
    const sel = s.area && (code === s.area || code.startsWith(s.area)) ? ' sel' : '';
    const dim = s.celda && (!c || `${c.x}${c.y}` !== s.celda) ? ' dim' : '';
    return `<path class="hz-a hz-${c ? c.cls : 'na'}${sel}${dim}" d="${D.map.districts[code].d}" data-code="${code}" data-tip="${esc(tip)}"></path>`;
  }).join('');
  const show = s.mz !== '0' && K?.blocks?.length;
  const lv = K?.levels || [];
  const blockLayer = show ? `<g class="hz-mz">${K.blocks.map(([lat, lon, u, cp, l, pob, viv]) => {
    const [x, y] = project(D.peru, lat, lon);
    const r = unit * (l <= 1 ? 3 : 2.2);
    return `<rect class="${BLOCK_CLS[l]}" x="${(x - r).toFixed(2)}" y="${(y - r).toFixed(2)}" width="${(2 * r).toFixed(2)}" height="${(2 * r).toFixed(2)}" data-tip="${esc(`Manzana en riesgo ${(lv[l] || '').toLowerCase()} ante El Niño 2026-2027\n${cp ? `${cp}, ` : ''}${H.shortName(D, u)}\n${n0(pob)} personas y ${n0(viv)} viviendas (censo 2017)\nEvaluación del CENEPRED (SIGRID)`)}"></rect>`;
  }).join('')}</g>` : '';
  const label = 'Mapa bivariado por distrito: frecuencia de daños y pobreza';
  const svg = `${svgOpen(vb, label)}<g>${paths}</g>${outline(D)}${blockLayer}${s.area ? H.selRing(H.areaShape(D, s.area)) : ''}</svg>`;
  const count = (x, y) => [...cells.values()].filter((c) => c.x === x && c.y === y).length;
  const grid = html`<div class="hz-bv" role="group" aria-label="Leyenda bivariada: toque una casilla para resaltar sus distritos">
    <div class="hz-bv-grid">${[2, 1, 0].map((y) => [0, 1, 2].map((x) => html`<button type="button" class="hz-bv-c hz-b${x}${y}${s.celda === `${x}${y}` ? ' on' : ''}" data-celda="${x}${y}" aria-pressed="${String(s.celda === `${x}${y}`)}" aria-label="Frecuencia de daños ${xl[x]}, pobreza ${yl[y]}: ${count(x, y)} distritos">${count(x, y)}</button>`))}</div>
    <span class="hz-bv-y">Pobreza →</span><span class="hz-bv-x">Años con daños →</span></div>`;
  const legend = html`<div class="hz-legend hz-legend-bv"><span class="hz-legend-t">Daños frecuentes y pobreza, por distrito (terciles)</span>${grid}
    <p class="muted small">Años con daños: bajo hasta ${pctTxt(bx[0])}, medio hasta ${pctTxt(bx[1])} de los años de DesInventar (1970-2015). Pobreza monetaria (INEI): baja hasta ${F.fmtNumber(by[0], 0)} %, media hasta ${F.fmtNumber(by[1], 0)} %. Gris: sin uno de los dos datos.</p>
    ${K?.blocks?.length ? html`<ul><li><span class="hz-sw mz-0"></span>Manzana en riesgo muy alto</li><li><span class="hz-sw mz-1"></span>Alto</li><li><span class="hz-sw mz-2"></span>Medio</li><li><span class="hz-sw mz-3"></span>Bajo</li></ul>` : ''}</div>`;
  const control = K?.blocks?.length ? html`<div class="hz-f"><span>Capas</span><button type="button" class="kind-chip" data-mz aria-pressed="${String(Boolean(show))}"><span class="hz-sw mz-0" aria-hidden="true"></span>Manzanas en riesgo (CENEPRED)</button></div>` : '';
  let side = null, extra = '';
  const blockBox = (pre) => {
    const mine = (K?.blocks || []).filter((b) => b[2].startsWith(pre));
    if (!mine.length) return '';
    const by = lv.map((name, l) => ({ name, n: mine.filter((b) => b[4] === l).length, pob: mine.filter((b) => b[4] === l).reduce((t, b) => t + b[5], 0) }));
    const hot = topEntries(mine.filter((b) => b[4] <= 1).reduce((m, b) => m.set(b[2], (m.get(b[2]) || 0) + b[5]), new Map()), 6);
    return html`<div class="hz-ctxbox"><h4 class="hz-h4">Manzanas evaluadas por el CENEPRED ante El Niño 2026-2027</h4>
      ${tiles(by.filter((x) => x.n).map((x) => [n0(x.n), `manzanas en riesgo ${x.name.toLowerCase()} (${n0(x.pob)} personas en el censo 2017)`]))}
      ${hot.length ? html`<h4 class="hz-h4">Distritos con más personas en manzanas de riesgo alto o muy alto</h4>${bars(hot.map(([c, v]) => ({ id: c, label: H.shortName(D, c), v })), { attr: 'data-area' })}` : ''}
      <p class="muted small">Escenario de riesgo del CENEPRED (SIGRID, servicio sectores/COEN_FEN_2027) para las zonas que evaluó en Piura, Tumbes y Lambayeque; no cubre todo el departamento. Población y viviendas por manzana del censo 2017 (INEI): datos por manzana, no por persona.</p></div>`;
  };
  if (s.area) extra = blockBox(s.area);
  else {
    const hh = [...cells.entries()].filter(([, c]) => (s.celda ? `${c.x}${c.y}` === s.celda : c.x === 2 && c.y === 2))
      .sort((a, b) => b[1].freq - a[1].freq || b[1].pob - a[1].pob).slice(0, 15);
    const pop = (c) => D.attrs.get(c)?.[0] || 0;
    const cellName = s.celda ? `frecuencia de daños ${xl[+s.celda[0]]} y pobreza ${yl[+s.celda[1]]}` : 'daños frecuentes y pobreza alta';
    const all = [...cells.entries()].filter(([, c]) => (s.celda ? `${c.x}${c.y}` === s.celda : c.x === 2 && c.y === 2));
    side = html`<div class="hz-prof"><h3 class="hz-prof-h">Dónde se juntan los daños y la pobreza</h3>
      ${tiles([[n0(all.length), `distritos con ${cellName}`], [n0(all.reduce((t, [c]) => t + pop(c), 0)), 'personas viven en ellos (2020)']])}
      <h4 class="hz-h4">Distritos con ${cellName}</h4>
      <ol class="hz-bars">${hh.map(([c, v]) => html`<li><button type="button" class="linkish" data-area="${c}">${H.shortName(D, c)} <span class="muted small">(${D.sum.nombres.departamento[c.slice(0, 2)]})</span></button><span class="hz-bar"><span style="width:${(v.freq * 100).toFixed(0)}%"></span></span><span class="hz-bar-v">${pctTxt(v.freq)} · ${F.fmtNumber(v.pob, 0)} %</span></li>`)}</ol>
      <p class="muted small">Barra y primera cifra: parte de los años de DesInventar (1970-2015) con daños registrados, con los filtros elegidos; segunda: pobreza monetaria. Un mapa bivariado muestra dónde coinciden dos cosas; no es un índice de riesgo oficial. Toque una casilla de la leyenda para ver otros grupos.</p>
      ${blockBox('')}</div>`;
  }
  return { svg, legend, control, side, extra, label };
}
