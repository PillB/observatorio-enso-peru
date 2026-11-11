// La tabla de registros al final de la Memoria de desastres y sus descargas.
//
// Sigue los filtros del mapa (evento, peligro, temporadas y el área elegida) y muestra primero los 25 registros más
// recientes; «Mostrar más» agrega filas sin cambiar de página (la persona sigue comparando las que ya vio). Lo que la
// tabla necesita se pide solo cuando hace falta:
//   - las columnas compactas (fecha, peligro, lugar, ubigeo, evento, fase, origen, confianza, daños) ya están en el
//     navegador (eventos.json);
//   - Latitud y Longitud vienen de coordenadas.json (100 KB comprimido), que se pide al acercarse a la tabla;
//   - la descripción, la ubicación, la fuente y la duración vienen de detalle/<departamento>.json, solo de los
//     departamentos de las filas visibles (de uno a tres, sin preguntar; más, con un botón).
// La descarga del filtro arma en el navegador las columnas del tablero del equipo de prevención y las de la Memoria,
// con los mismos valores que eventos.csv (tests/js/historico-tabla.test.mjs lo compara fila por fila). El catálogo
// entero, con todas sus columnas, es eventos.zip.

import { html, raw, safeUrl } from './lib/dom.js';

/** Las 13 columnas del tablero del equipo de prevención, en su orden (enso.historico.esquema.TEAM_COLUMNS). */
export const TEAM = ['Date', 'DangerType', 'Ubicacion', 'Distrito', 'Provincia', 'Departamento', 'Descripción', 'DuraciónEvento', 'Ubigeo', 'TipoEvento', 'Fuente', 'Latitud', 'Longitud'];
/** Cifras de impacto tal como las publicó la fuente (esquema.IMPACT_COLUMNS). */
export const IMPACT = ['Fallecidos', 'Desaparecidos', 'Heridos', 'Afectados', 'Damnificados', 'Evacuados', 'Reubicados', 'Desplazados', 'ViviendasDestruidas', 'ViviendasAfectadas', 'HectareasCultivo', 'KmVias', 'CentrosEducativos', 'CentrosSalud', 'PerdidasUSD'];
/** Las columnas de la Memoria que el navegador puede armar sin el ZIP, en el orden de eventos.csv. */
export const EXTRA = ['Id', 'Origen', 'PrecisionFecha', 'GrupoPeligro', 'DangerTypeMetodo', 'PrecisionGeo', 'Lugar', 'CuerpoAgua', 'FaseENSO', 'AtribucionENSO', ...IMPACT, 'FuenteCita', 'Confianza', 'FechaTipo', 'Corroboracion', 'FuentesAdicionales'];
export const COLUMNS = [...TEAM, ...EXTRA];

/** Cuántas filas se muestran al inicio y cuántas agrega cada «Mostrar más». */
export const PAGE = 25;
/** Hasta cuántos departamentos se piden solos para las filas visibles (cada uno pesa de 50 KB a 800 KB comprimido). */
export const AUTO_DEPS = 3;

const KIND = { 0: 'coordenada-fuente', 1: 'centro-poblado', 3: 'cuerpo-de-agua' };
const CAPITAL = { 6: 'capital-distrito', 4: 'capital-provincia', 2: 'capital-departamento' };

/** La fecha del catálogo (AAAA-MM-DD) desde la de eventos.json, que trae solo lo que se sabe (AAAA, AAAA-MM). */
export const fullDate = (d) => (d.length === 4 ? `${d}-01-01` : d.length === 7 ? `${d}-01` : d);

/** Los registros de un área (prefijo del ubigeo); sin área, todos. */
export const inArea = (recs, area) => (area ? recs.filter((r) => r.u.startsWith(area)) : recs);

/** Las columnas por las que se ordena la tabla: la clave del registro, el nombre y si empieza de mayor a menor. */
export const SORTS = {
  d: ['Fecha', -1],
  t: ['Peligro', 1],
  u: ['Lugar', 1],
  muertos: ['Fallecidos y desaparecidos', -1],
  afect: ['Afectados y damnificados', -1],
  viv: ['Viviendas destruidas', -1],
};

/** Ordena sin tocar el arreglo original. Lugar ordena por el nombre que se ve (distrito, provincia, departamento);
 * los empates, por fecha y luego por la posición en el catálogo, para que el orden sea siempre el mismo. */
export function sortRows(rows, key, dir, placeOf = (u) => u) {
  const names = key === 'u' ? new Map() : null;
  const coll = new Intl.Collator('es', { sensitivity: 'base', numeric: true });
  const val = (r) => {
    if (key !== 'u') return r[key];
    if (!names.has(r.u)) names.set(r.u, placeOf(r.u));
    return names.get(r.u);
  };
  const cmp = (a, b) => {
    const x = val(a), y = val(b);
    const c = typeof x === 'string' ? coll.compare(x, y) : (x || 0) - (y || 0);
    return c * dir || (b.d < a.d ? -1 : b.d > a.d ? 1 : 0) || b.i - a.i;
  };
  return [...rows].sort(cmp);
}

/** Los departamentos (dos dígitos) de unas filas, ordenados. */
export const depsOf = (rows) => [...new Set(rows.map((r) => r.u.slice(0, 2)))].sort();

/** De dónde salen Latitud y Longitud (columna PrecisionGeo). Sin la ficha del departamento no se sabe cómo se ubicó
 * un punto propio: queda vacío. */
function precisionGeo(r, d, C) {
  if (C?.puntos?.[r.i]) return d?.[13] ? KIND[d[13][2]] || '' : '';
  const a = C?.areas?.[r.u];
  return a ? (a[2] ? 'interior-distrito' : CAPITAL[r.u.length] || '') : '';
}

/** Los valores de un registro en el orden de COLUMNS, como los escribe eventos.csv.
 * r: el registro compacto (historico-model.decode); d: su ficha (detalle/<dep>.json), o nada si no llegó;
 * C: coordenadas.json; sum: resumen.json (nombres y grupos de peligro). */
export function rowValues(r, d, C, sum) {
  const N = sum.nombres;
  const det = d || [];
  const g = det[13];
  const [lat, lon] = C?.puntos?.[r.i] || C?.areas?.[r.u] || ['', ''];
  const imp = det[9] || {};
  const v = {
    Date: fullDate(r.d), DangerType: r.t, Ubicacion: det[1], Distrito: r.u.length === 6 ? N.distrito[r.u] : '',
    Provincia: r.u.length >= 4 ? N.provincia[r.u.slice(0, 4)] : '', Departamento: N.departamento[r.u.slice(0, 2)],
    Descripción: det[0], DuraciónEvento: det[4], Ubigeo: r.u, TipoEvento: r.e, Fuente: det[3], Latitud: lat, Longitud: lon,
    Id: det[6], Origen: r.o, PrecisionFecha: det[5], GrupoPeligro: sum.peligros?.[r.t]?.grupo, DangerTypeMetodo: det[7],
    PrecisionGeo: precisionGeo(r, d, C), Lugar: g?.[3], CuerpoAgua: g?.[6], FaseENSO: r.f, AtribucionENSO: det[8],
    FuenteCita: det[2], Confianza: r.c, FechaTipo: det[12], Corroboracion: d ? det[10] ?? 0 : '',
    FuentesAdicionales: (det[11] || []).join(' | '),
  };
  for (const k of IMPACT) v[k] = imp[k];
  return COLUMNS.map((k) => v[k]);
}

/** Lo que Python considera un número (float()), para no proteger -12.5 como si fuera una fórmula. */
const isNumber = (s) => /^\s*[+-]?(\d[\d_]*\.?\d*(e[+-]?\d+)?|\.\d+(e[+-]?\d+)?|inf(inity)?|nan)\s*$/i.test(s);

/** Una celda como la escribe el catálogo: vacía si no hay dato; un texto que empieza con =, +, - o @ (y no es un
 * número) lleva un apóstrofo delante para que la hoja de cálculo no lo lea como fórmula (observatory.csv_safe);
 * comillas si trae comas, comillas o saltos de línea (RFC 4180, como csv.writer). */
export function csvCell(value) {
  let s = value === null || value === undefined ? '' : String(value);
  if (/^[=+\-@]/.test(s) && !isNumber(s)) s = `'${s}`;
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export const csvLine = (values) => `${values.map(csvCell).join(',')}\n`;
/** La cabecera, con BOM para que Excel lea las tildes (como eventos.csv). */
export const csvHead = () => `﻿${csvLine(COLUMNS)}`;

const slug = (s) => String(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

/** Nombre del archivo: el filtro que lo produjo y la fecha del catálogo. */
export function fileName(s, placeName, generatedAt) {
  const parts = ['memoria-desastres'];
  if (s.area) parts.push(slug(placeName(s.area)) || s.area);
  if (s.peligro) parts.push(slug(s.peligro));
  if (s.evento) parts.push(slug(s.evento));
  if (s.desde || s.hasta) parts.push(`${s.desde || 'inicio'}-${s.hasta || 'fin'}`);
  if (generatedAt) parts.push(String(generatedAt).slice(0, 10));
  return `${parts.join('_')}.csv`;
}

/** Arma el CSV de unas filas (en su orden) pidiendo las fichas departamento por departamento. De cada ficha guarda
 * solo las de esas filas, así que un filtro grande no deja los 80 MB de fichas en memoria.
 * load(dep) → la ficha del departamento o null; progress(hechos, total). Devuelve las partes del CSV (para un Blob)
 * y los departamentos cuya ficha no llegó (sus filas van sin descripción, ubicación ni fuente). */
export async function buildCsv(rows, { C, sum, load, progress = () => {}, alive = () => true }) {
  const deps = depsOf(rows);
  const want = new Map(deps.map((d) => [d, []]));
  for (const r of rows) want.get(r.u.slice(0, 2)).push(r.i);
  const fichas = new Map();
  const missing = [];
  let done = 0;
  for (const dep of deps) {
    if (!alive()) return null;
    const det = await load(dep);
    if (!det || !Object.keys(det).length) missing.push(dep);
    else for (const i of want.get(dep)) fichas.set(i, det[String(i)]);
    progress(++done, deps.length);
  }
  const parts = [csvHead()];
  // Partes de unas mil filas: un solo texto de 100 MB puede pasar el límite de un string del navegador.
  let chunk = '';
  rows.forEach((r, n) => {
    chunk += csvLine(rowValues(r, fichas.get(r.i), C, sum));
    if (n % 1000 === 999) { parts.push(chunk); chunk = ''; }
  });
  if (chunk) parts.push(chunk);
  return { parts, missing };
}

// ---------------------------------------------------------------------------
// Vista
// ---------------------------------------------------------------------------

const n0 = (v) => Number(v || 0).toLocaleString('es');
const hostOf = (u) => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return 'enlace'; } };
const cut = (t, n) => (t.length > n ? `${t.slice(0, n).replace(/\s+\S*$/, '')}…` : t);

/** Encabezado de una columna que se puede ordenar: un botón dentro del th y aria-sort solo en la ordenada. */
function sortHead(T, key, cls = '') {
  const [label] = SORTS[key];
  const on = T.key === key;
  const sort = on ? (T.dir < 0 ? 'descending' : 'ascending') : null;
  return html`<th scope="col" class="${cls}" ${sort ? raw(`aria-sort="${sort}"`) : ''}><button type="button" class="hz-sort" data-sort="${key}">${label}<span class="hz-sort-i" aria-hidden="true">${on ? (T.dir < 0 ? '▼' : '▲') : '↕'}</span></button></th>`;
}

/** Una fila de la tabla. det: la ficha (o undefined si no se pidió o no llegó); C: coordenadas.json (o null). */
function rowHtml(r, det, C, ctx) {
  const { placeName, label, sourceName, wantDetail } = ctx;
  // undefined: la ficha del departamento no se pidió todavía; null: se pidió y no trae este registro (o no llegó).
  const pending = wantDetail && det === undefined;
  const unloaded = !wantDetail && det === undefined;
  const d = det || [];
  const [desc, ubic, , url, dur] = d;
  const [lat, lon] = C?.puntos?.[r.i] || C?.areas?.[r.u] || [];
  const wait = html`<span class="muted" aria-label="cargando">…</span>`;
  const text = (v) => (pending ? wait : v || '');
  return html`<tr>
    <td class="hz-t-d">${r.d}</td>
    <td>${label(r.t)}</td>
    <th scope="row" class="hz-t-place">${placeName(r.u)}</th>
    <td class="hz-t-mono">${r.u}</td>
    <td>${r.e || ''}</td>
    <td class="hz-t-desc">${pending ? wait : unloaded ? html`<span class="muted small">sin cargar</span>` : desc ? (desc.length > 160 ? html`<details><summary>${cut(desc, 140)}</summary>${desc}</details>` : desc) : html`<span class="muted" title="La fuente no trae descripción">—</span>`}</td>
    <td>${text(ubic)}</td>
    <td class="num">${text(dur)}</td>
    <td class="num">${r.muertos ? n0(r.muertos) : ''}</td>
    <td class="num">${r.afect ? n0(r.afect) : ''}</td>
    <td class="num">${r.viv ? n0(r.viv) : ''}</td>
    <td>${pending ? wait : url ? html`<a href="${safeUrl(url)}" rel="noopener" target="_blank" title="${d[2] || ''}">${hostOf(url)}</a>` : html`<span class="muted">${sourceName(r.o)}</span>`}</td>
    <td class="num hz-t-mono">${C ? (lat ? `${lat}, ${lon}` : '') : wait}</td>
    <td>${r.f || ''}</td>
    <td>${r.c || ''}</td>
  </tr>`;
}

/** La tabla con las filas visibles. ctx trae los nombres, las fichas pedidas y el estado. */
export function tableHtml(rows, T, ctx) {
  const shown = rows.slice(0, T.shown);
  const left = rows.length - shown.length;
  return html`<div class="table-wrap hz-tbl-wrap" role="region" aria-labelledby="hz-tbl-cap" tabindex="0">
    <table class="hz-table hz-tbl">
      <caption id="hz-tbl-cap" class="visually-hidden">${ctx.caption}</caption>
      <thead><tr>
        ${sortHead(T, 'd')}${sortHead(T, 't')}${sortHead(T, 'u')}
        <th scope="col">Ubigeo</th><th scope="col">TipoEvento</th><th scope="col">Descripción</th><th scope="col">Ubicación</th><th scope="col" class="num">Duración (días)</th>
        ${sortHead(T, 'muertos', 'num')}${sortHead(T, 'afect', 'num')}${sortHead(T, 'viv', 'num')}
        <th scope="col">Fuente</th><th scope="col" class="num">Latitud, longitud</th><th scope="col">Fase ENSO</th><th scope="col">Confianza</th>
      </tr></thead>
      <tbody>${shown.map((r) => rowHtml(r, ctx.fichas.get(r.u.slice(0, 2))?.[String(r.i)] ?? (ctx.fichas.has(r.u.slice(0, 2)) ? null : undefined), ctx.C, ctx))}</tbody>
    </table></div>
    <div class="hz-tbl-foot">
      <span class="muted small">Mostrando ${n0(shown.length)} de ${n0(rows.length)} registros</span>
      ${left > 0 ? html`<button type="button" class="btn ghost" data-tbl-more="${PAGE}">Mostrar ${n0(Math.min(PAGE, left))} más</button>` : ''}
      ${left > PAGE ? html`<button type="button" class="btn ghost" data-tbl-more="${Math.min(left, 200)}">Mostrar ${n0(Math.min(left, 200))} más</button>` : ''}
    </div>`;
}
