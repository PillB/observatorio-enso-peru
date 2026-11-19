// Boletín de eventos El Niño: una hoja con lo que viene, dónde y cuándo.
//
// Todo sale de data/boletin.json, que arma la actualización diaria (python/enso/boletin.py) con los avisos oficiales,
// el estado del ENFEN y el escenario del CENEPRED. El mismo archivo alimenta el correo que manda n8n
// (n8n/nodes/boletin.js), así que la pestaña y el correo nunca dicen cosas distintas. Aquí no se calcula ningún
// nivel ni ningún orden: solo se dibuja. Lo único que mira la hora es si la edición es vieja y qué avisos ya vencieron
// desde el corte, para que nadie lea un boletín viejo como si fuera de ahora.
//
// Tres versiones (experimento «boletin» de ab.js; docs/boletin.md):
//   mapa     A · la hoja con el mapa del Perú;
//   mosaico  B · la misma hoja con un mosaico de cuadros (el que lleva el correo);
//   ficha    C · una ficha de impacto: estado del ENFEN en su escala, el boletín en 30 segundos, cuándo, qué hacer según
//            el color y tarjetas por departamento (el formato de los boletines de la NOAA, la Met Office y la OMM).
// En papel (Imprimir o Guardar como PDF) cada una cabe en una hoja A4.
//
// La suscripción por correo (doble confirmación, baja en un clic) habla con /api/boletin/ (functions/_lib/boletin-subs.js).

import { html, raw, safeUrl, $, $$ } from './lib/dom.js';
import * as F from './lib/format.js';
import { ICON } from './icons.js';
import { ab, abReady, hasBackend } from './ab.js';

const LV = { 3: 'r3', 2: 'r2', 1: 'r1', 0: 'un', '-1': 'ok' };
const LEVEL_WORD = { 3: 'en rojo', 2: 'en naranja', 1: 'en amarillo', 0: 'con avisos sin nivel', '-1': 'sin avisos de El Niño' };
const TOP = 10;
/** Mosaico: fila y columna de cada departamento (igual que TILES en python/enso/boletin.py). */
export const TILES = {
  24: [0, 0], '01': [0, 2], 16: [0, 3], 20: [1, 0], '06': [1, 1], 22: [1, 2], 14: [2, 0], 13: [2, 1], 10: [2, 2], 25: [2, 3],
  '02': [3, 1], 19: [3, 2], 12: [3, 3], '07': [4, 0], 15: [4, 1], '09': [4, 2], '05': [4, 3], '08': [4, 4], 17: [4, 5],
  11: [5, 1], '03': [5, 3], 21: [5, 4], '04': [6, 2], 18: [6, 3], 23: [7, 3],
};
export const ABBR = { '01': 'AMA', '02': 'ANC', '03': 'APU', '04': 'ARE', '05': 'AYA', '06': 'CAJ', '07': 'CAL', '08': 'CUS', '09': 'HVC', 10: 'HUC', 11: 'ICA', 12: 'JUN', 13: 'LAL', 14: 'LAM', 15: 'LIM', 16: 'LOR', 17: 'MDD', 18: 'MOQ', 19: 'PAS', 20: 'PIU', 21: 'PUN', 22: 'SAM', 23: 'TAC', 24: 'TUM', 25: 'UCA' };
const TIER = { inmediata: ['Importante', 'r3'], resumen: ['Menor', 'r1'], ninguna: ['No se envía', 'un'], inicial: ['Primer boletín', 'un'] };
const TIER_MAIL = { inmediata: ['Correo al momento', 'r3'], resumen: ['En el resumen diario', 'r1'], ninguna: ['No se envía', 'un'] };
export const VARIANTS = [['mapa', 'Mapa'], ['mosaico', 'Mosaico'], ['ficha', 'Ficha']];
const FREQ = [
  ['todo', 'Avisos importantes al momento y un resumen diario', 'Recomendado para equipos de gestión del riesgo.'],
  ['importantes', 'Solo avisos importantes', 'Rojo o naranja nuevo, un departamento que sube, otro estado del ENFEN.'],
  ['diario', 'Un solo correo al día', 'El resumen de las 7:00 (hora de Lima), con todo lo que cambió.'],
  ['semanal', 'Un solo correo a la semana', 'El resumen de los lunes a las 7:00 (hora de Lima), con todo lo que cambió.'],
];

const fmtWhen = new Intl.DateTimeFormat('es-PE', { timeZone: 'America/Lima', weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
/** «mié 11 nov 23:59» en hora de Lima; vacío si la fecha no se entiende (una fecha rota no tumba la pestaña). */
export const when = (iso) => {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isFinite(t) ? fmtWhen.format(new Date(t)).replace(/\.,? /g, ' ').replace(',', '') : '';
};
export const joinEs = (l, limit = 0) => {
  const x = l.filter(Boolean);
  if (limit && x.length > limit) return `${x.slice(0, limit).join(', ')} y otros`;
  return x.length > 1 ? `${x.slice(0, -1).join(', ')} y ${x[x.length - 1]}` : x[0] || '';
};

/** Cuándo, para un departamento: «Ahora, hasta mié 11 nov 23:59», «Desde jue 12 nov 00:00» o «Venció mié 11 nov…». */
export function segWhen(s, now = null) {
  if (s.rank < 0) return '—';
  if (!s.now && s.since) return `Desde ${when(s.since)}`;
  if (now !== null && segExpired(s, now)) return `Venció ${when(s.until)}`;
  return `Ahora${s.until ? `, hasta ${when(s.until)}` : ''}`;
}

/** Los avisos del nivel más alto de un departamento ya vencieron a la hora ``now``. */
export const segExpired = (s, now = Date.now()) => s.rank >= 0 && s.now && Boolean(s.until) && Date.parse(s.until) < now;

/** Avisos de la edición que ya vencieron a la hora ``now`` (la edición es una foto del corte). */
export function expiredSince(doc, now = Date.now()) {
  return (doc.events || []).filter((e) => e.phase !== 'cancelado' && e.until && Date.parse(e.until) < now);
}

/** La edición se ve vieja: más de 36 h desde el corte (la actualización es diaria), o un corte que no se entiende. */
export const isOld = (doc, now = Date.now()) => {
  const t = Date.parse(doc.cutoff);
  return !Number.isFinite(t) || now - t > 36 * 36e5;
};

/** Parámetros del enlace (#/boletin?dep=20&confirmar=…). */
const params = () => new URLSearchParams(location.hash.split('?')[1] || '');

const chip = (s, small = false) => html`<span class="lvl lvl-${LV[s.rank]}${small ? ' lvl-s' : ''}">${s.rank === 3 ? raw(ICON.octagon) : s.rank > 0 ? raw(ICON.triangle) : ''}${s.label}</span>`;
const lvChip = (rank, label) => html`<span class="lvl lvl-s lvl-${LV[rank]}">${label}</span>`;

function counters(c, level) {
  const box = (r, n, t) => html`<button type="button" class="bol-count bc-${LV[r]}" data-level="${r}" aria-pressed="${String(level === r)}" ${n ? '' : 'disabled'}
    aria-label="${n} ${n === 1 ? 'departamento' : 'departamentos'} ${LEVEL_WORD[r]}${n ? ': mostrar solo esos' : ''}"><strong>${n}</strong><span>${t}</span></button>`;
  return html`<div class="bol-counts" role="group" aria-label="Departamentos por nivel (de 25). Toque uno para ver solo esos">
    ${box(3, c.rojo, 'en rojo')}${box(2, c.naranja, 'en naranja')}${box(1, c.amarillo, 'en amarillo')}${box(0, c.sinNivel, 'sin nivel')}${box(-1, c.verde, 'sin avisos')}</div>`;
}

function svgMap(geo, segs, sel, now) {
  const by = Object.fromEntries(segs.map((s) => [s.code, s]));
  const label = (s) => `${s.name}: ${s.rank < 0 ? 'sin avisos' : `${s.label}, ${segWhen(s, now)}`}`;
  const paths = geo.departments.map((d) => {
    const s = by[d.code];
    if (!s) return '';
    const soon = s.rank >= 0 && !s.now;
    return html`<path class="bol-dep d-${LV[s.rank]}${soon ? ' soon' : ''}${segExpired(s, now) ? ' gone' : ''}${sel === d.code ? ' sel' : ''}" d="${d.d}" data-dep="${d.code}" tabindex="0" role="button" aria-pressed="${String(sel === d.code)}" aria-label="${label(s)}"><title>${label(s)}</title></path>`;
  });
  // Callao es muy chico para tocarlo en el mapa: un punto con su propio nombre y foco de teclado.
  const cal = geo.departments.find((d) => d.code === '07');
  const dot = cal && by['07'] ? html`<circle class="bol-dep bol-dot d-${LV[by['07'].rank]}${sel === '07' ? ' sel' : ''}" cx="${cal.label[0] - 4}" cy="${cal.label[1]}" r="7" data-dep="07" tabindex="0" role="button" aria-pressed="${String(sel === '07')}" aria-label="${label(by['07'])}"><title>${label(by['07'])}</title></circle>` : '';
  const labels = geo.departments.filter((d) => by[d.code]?.rank >= 2 && d.code !== '07').map((d) => html`<text class="bol-lbl" x="${d.label[0]}" y="${d.label[1]}" aria-hidden="true">${ABBR[d.code]}</text>`);
  const defs = html`<defs>${['r3', 'r2', 'r1', 'un'].map((k) => html`<pattern id="bol-soon-${k}" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="7" height="7" class="pt-bg"/><rect width="3.2" height="7" class="pt-${k}"/></pattern>`)}</defs>`;
  return html`<svg class="bol-svg" viewBox="0 0 ${geo.width} ${geo.height}" role="group" aria-label="Mapa del Perú: cada departamento con el nivel más alto de sus avisos oficiales. Tóquelo para ver sus avisos" preserveAspectRatio="xMidYMid meet">${defs}${paths}${dot}${labels}</svg>`;
}

function tileMap(segs, sel, now, small = false) {
  const by = Object.fromEntries(segs.map((s) => [s.code, s]));
  const focus = sel && by[sel] ? sel : '24';
  const cells = Object.entries(TILES).map(([code, [r, c]]) => {
    const s = by[code];
    if (!s) return '';
    const soon = s.rank >= 0 && !s.now;
    return html`<button type="button" class="bol-tile d-${LV[s.rank]}${soon ? ' soon' : ''}${segExpired(s, now) ? ' gone' : ''}${sel === code ? ' sel' : ''}" style="grid-row:${r + 1};grid-column:${c + 1}" data-dep="${code}" data-r="${r}" data-c="${c}" tabindex="${code === focus ? '0' : '-1'}" aria-pressed="${String(sel === code)}" aria-label="${s.name}: ${s.rank < 0 ? 'sin avisos' : `${s.label}, ${segWhen(s, now)}`}"><span>${ABBR[code]}</span>${soon ? html`<i aria-hidden="true">próx.</i>` : ''}</button>`;
  });
  return html`<div class="bol-tiles${small ? ' bol-tiles-s' : ''}" role="group" aria-label="Mosaico de departamentos del Perú, norte arriba y la costa a la izquierda. Use las flechas para moverse">${cells}</div>
    <p class="bol-compass small muted" aria-hidden="true">↑ norte · ← costa</p>`;
}

function abbrList(segs) {
  return html`<details class="bol-abbr small"><summary>Qué departamento es cada sigla</summary><ul>${segs.slice().sort((a, b) => a.name.localeCompare(b.name, 'es')).map((s) => html`<li><strong>${ABBR[s.code]}</strong> ${s.name}</li>`)}</ul></details>`;
}

function legend(doc, now) {
  const gone = doc.segments.some((s) => segExpired(s, now));
  return html`<ul class="bol-legend">${(doc.legend || []).map((l) => html`<li><span class="sw sw-${LV[l.rank]}"></span><span>${l.text}</span></li>`)}
    <li><span class="sw sw-r2 sw-striped"></span><span>Rayado o «próx.»: ese nivel solo se espera (aviso próximo).</span></li>
    ${gone ? html`<li><span class="sw sw-r3 sw-gone"></span><span>Más claro: los avisos de ese nivel vencieron después del corte.</span></li>` : ''}</ul>`;
}

function headline(doc) {
  // «brief»: sin lo que ya dicen la línea del ENFEN, sus barras y los contadores de arriba.
  const lines = (doc.headline || []).map((h) => [h, h.brief ?? h.text]).filter(([, t]) => t);
  return html`<div class="bol-head">${lines.map(([h, t]) => html`<p data-line="${h.id}"><strong>${h.title}.</strong> ${t}</p>`)}</div>`;
}

function probBars(doc) {
  const p = (doc.enso?.probabilities || []).find((x) => x.region === 'nino12');
  if (!p) return '';
  return html`<div class="bol-prob"><div class="small"><strong>Probabilidad para el verano según el ENFEN</strong> (costa del Perú, ${p.url ? html`<a href="${safeUrl(p.url)}" rel="noopener" target="_blank">informe técnico N° ${p.informe}</a>` : `informe técnico N° ${p.informe}`}${p.page ? `, pág. ${p.page}` : ''})</div>
    ${p.summer.map((x) => html`<div class="bol-pbar"><span class="bol-plab">${x.label}</span><span class="bol-ptrack" role="img" aria-label="${x.pct} %"><span style="width:${Math.max(0, Math.min(100, x.pct))}%"></span></span><strong>${x.pct} %</strong></div>`)}
    ${p.other ? html`<div class="small muted">Otras categorías: ${p.other} %.</div>` : ''}</div>`;
}

function guidance(doc, compact = false) {
  const present = new Set(doc.segments.map((s) => s.rank));
  const rows = (doc.guidance || []).filter((g) => present.has(g.rank) && (g.rank >= 1 || !compact));
  if (!rows.length) return '';
  const count = (r) => doc.segments.filter((s) => s.rank === r).length;
  if (compact) {
    return html`<details class="bol-do no-print"><summary><strong>Qué hacer según el color</strong></summary><dl>${rows.map((g) => html`<dt>${lvChip(g.rank, g.label)}</dt><dd><strong>${g.do}</strong> ${g.expect}</dd>`)}</dl><p class="small muted">${doc.guidanceSource || ''}</p></details>`;
  }
  return html`<section class="fc-do" aria-labelledby="fc-do-h"><h3 id="fc-do-h">Qué hacer según el color</h3>
    <div class="table-wrap"><table class="data"><thead><tr><th scope="col">Color</th><th scope="col">Departamentos</th><th scope="col">Qué esperar</th><th scope="col">Qué hacer</th></tr></thead>
    <tbody>${rows.map((g) => html`<tr><th scope="row">${lvChip(g.rank, g.label)}</th><td class="num">${count(g.rank)}</td><td>${g.expect}</td><td><strong>${g.do}</strong></td></tr>`)}</tbody></table></div>
    <p class="small muted">${doc.guidanceSource || ''}</p></section>`;
}

function segRow(s, events, now) {
  const evs = s.events.map((k) => events[k]).filter(Boolean);
  const sc = s.scenario;
  const pct = sc.districts ? Math.round((100 * sc.muyAlto) / sc.districts) : 0;
  const inst = s.institutionsAll || [...new Set(evs.map((e) => e.institution))];
  return html`<tr data-dep="${s.code}" class="bol-row${segExpired(s, now) ? ' gone' : ''}">
    <td class="num">${s.position}</td>
    <th scope="row"><button type="button" class="linkish bol-name" data-pick="${s.code}">${s.name}</button><div>${chip(s, true)}</div></th>
    <td data-label="Qué podría pasar">${s.hazards.slice(0, 3).join(' · ') || '—'}${s.places.length ? html`<div class="muted small">${joinEs(s.places.slice(0, 4))}</div>` : ''}</td>
    <td data-label="Cuándo">${segWhen(s, now)}</td>
    <td data-label="Fuente">${evs.length ? html`<details class="bol-evs"><summary>${joinEs(inst) || '—'} <span class="muted small">(${evs.length} ${evs.length === 1 ? 'aviso' : 'avisos'})</span></summary>
      <ul>${evs.map((e) => html`<li><span class="lvl lvl-s lvl-${e.rank ? `r${e.rank}` : 'un'}">${e.level || 'Sin nivel'}</span> <a href="${safeUrl(e.url)}" rel="noopener" target="_blank">${e.title}</a>
        <span class="muted small">${e.institution}${e.alsoBy?.length ? ` (también ${e.alsoBy.join(', ')})` : ''} · ${e.phase === 'proxima' ? `desde ${when(e.from)}` : e.until ? `${Date.parse(e.until) < now ? 'venció' : 'hasta'} ${when(e.until)}` : 'en curso'}${e.approx ? ' · ≈ lugar aproximado' : ''}</span></li>`)}</ul></details>` : '—'}</td>
    <td data-label="Riesgo CENEPRED" class="small">${sc.districts ? html`<span class="bol-risk" role="img" aria-label="${pct} % de sus distritos en riesgo muy alto"><span style="width:${pct}%"></span></span>${F.fmtNumber(sc.muyAlto)} muy alto · ${F.fmtNumber(sc.alto)} alto <span class="muted">de ${F.fmtNumber(sc.districts)}</span>` : html`<span class="muted">sin escenario</span>`}</td>
    <td data-label="Daños 72 h" class="num">${s.reports}</td></tr>`;
}

/** Qué filas se muestran: las diez primeras con aviso, las 25, o las de un nivel (contadores). */
function visibleRows(doc, st) {
  if (st.level !== null) return doc.segments.filter((s) => s.rank === st.level);
  return st.all ? doc.segments : doc.segments.filter((s) => s.rank >= 0).slice(0, TOP);
}

function tableHead(doc, st) {
  const rated = doc.segments.filter((s) => s.rank >= 0);
  if (st.level !== null) return `Departamentos ${LEVEL_WORD[st.level]} (${visibleRows(doc, st).length})`;
  if (st.all) return 'Los 25 departamentos, por criticidad';
  return `Los ${Math.min(TOP, rated.length) || ''} departamentos más críticos`;
}

/** Aviso de empate: con 19 en rojo, los diez primeros no son «los diez en rojo»; se dice cuántos quedan fuera. */
function tieNote(doc, st) {
  if (st.all || st.level !== null) return '';
  const rated = doc.segments.filter((s) => s.rank >= 0);
  if (rated.length <= TOP) return '';
  const cut = rated[TOP - 1].rank;
  const same = rated.filter((s) => s.rank === cut).length;
  const shown = rated.slice(0, TOP).filter((s) => s.rank === cut).length;
  if (same <= shown) return html`<p class="small muted">Y ${rated.length - TOP} departamentos más con avisos.</p>`;
  return html`<p class="small bol-tie">${raw(ICON.info)} Hay ${same} departamentos ${LEVEL_WORD[cut]}: aquí van ${shown}, por el orden de abajo. <button type="button" class="linkish" data-level-go="${cut}">Ver los ${same}</button></p>`;
}

function table(doc, st, now) {
  const events = Object.fromEntries((doc.events || []).map((e) => [e.key, e]));
  const rows = visibleRows(doc, st);
  const green = doc.segments.filter((s) => s.rank < 0);
  return html`<div class="table-wrap"><table class="data bol-table"><caption class="visually-hidden">${tableHead(doc, st)}. Orden: ${(doc.order || []).join('; ')}</caption>
    <thead><tr><th scope="col">#</th><th scope="col">Departamento</th><th scope="col">Qué podría pasar · dónde</th><th scope="col">Cuándo</th><th scope="col">Fuente oficial</th><th scope="col">Distritos en riesgo (CENEPRED)</th><th scope="col">Daños 72 h</th></tr></thead>
    <tbody>${rows.length ? rows.map((s) => segRow(s, events, now)) : html`<tr><td colspan="7">Ningún departamento tiene avisos oficiales vigentes o próximos relacionados con El Niño.</td></tr>`}</tbody></table></div>
    ${tieNote(doc, st)}
    ${!st.all && st.level === null && green.length ? html`<p class="muted small bol-green">Sin avisos relacionados con El Niño: ${joinEs(green.map((s) => s.name))}.</p>` : ''}`;
}

function changesBlock(doc) {
  const ch = (doc.changes || []).filter((c) => c.rule !== 'inicial');
  if (!ch.length) return '';
  const same = doc.editionAt && doc.editionAt !== doc.cutoff;
  return html`<div class="bol-changes" role="note"><strong>Qué cambió en la edición N° ${doc.edition}${same ? ` (${when(doc.editionAt)})` : ''}:</strong><ul>${ch.slice(0, 6).map((c) => html`<li><span class="lvl lvl-s lvl-${TIER[c.tier]?.[1] || 'un'}">${TIER[c.tier]?.[0] || c.tier}</span> ${c.text}</li>`)}</ul>${ch.length > 6 ? html`<p class="small">Y ${ch.length - 6} cambios más. <button type="button" class="linkish" data-open="bol-recent">Ver todos los cambios</button></p>` : ''}</div>`;
}

function enfenLine(doc, now) {
  const e = doc.enso?.enfen;
  const n = doc.enso?.noaa;
  if (!e && !n) return '';
  const late = e && !e.stale && e.next && Date.parse(e.next) + 864e5 < now;
  return html`<div class="bol-enfen">${e ? html`<span class="tag">ENFEN</span> <strong>${e.status}</strong> <span class="muted small">${e.url ? html`<a href="${safeUrl(e.url)}" rel="noopener" target="_blank">Comunicado oficial${e.number ? ` N° ${e.number}` : ''}</a>` : `Comunicado oficial${e.number ? ` N° ${e.number}` : ''}`}${e.issued ? `, ${F.fmtDate(e.issued)}` : ''}${e.next ? ` · próximo: ${F.fmtDate(e.next)}` : ''}</span>${e.stale || late ? html` <span class="tag tag-prelim">ya debió salir uno nuevo</span>` : ''}` : ''}
    ${n ? html`<span class="bol-noaa small muted">· NOAA: ${n.url ? html`<a href="${safeUrl(n.url)}" rel="noopener" target="_blank">${n.status}</a>` : n.status}</span>` : ''}</div>`;
}

function sourcesLine(doc) {
  const s = doc.sources || {};
  if (!s.total) return html`<span class="tag tag-stale">no se leyó ninguna fuente de avisos</span>`;
  if (s.ok < s.total) return html`<span class="tag tag-prelim" title="${(s.failed || []).join(', ')}">${s.ok} de ${s.total} fuentes de avisos respondieron</span>`;
  return `${s.ok} de ${s.total} fuentes de avisos respondieron`;
}

function variantSwitch(variant) {
  return html`<div class="seg bol-variant no-print" role="group" aria-label="Forma del boletín">${VARIANTS.map(([v, l]) => html`<button type="button" data-variant="${v}" aria-pressed="${String(v === variant)}">${l}</button>`)}</div>`;
}

function topHeader(doc, st, lead = true) {
  const same = doc.editionAt && doc.editionAt !== doc.cutoff;
  return html`<header class="bol-top"><div><div class="eyebrow">Boletín de eventos El Niño · Perú</div><h2 id="bol-h">Edición N° ${doc.edition}${same ? html` <span class="bol-ed-date">del ${when(doc.editionAt)}</span>` : ''}</h2>
      <p class="muted small">${same ? 'Sin cambios desde entonces · revisado' : 'Corte:'} ${when(doc.cutoff)} (hora de Lima) · ${sourcesLine(doc)}</p></div>
      ${counters(doc.counts, st.level)}</header>
    ${lead && doc.summary ? html`<p class="bol-summary"><strong>En una frase:</strong> ${doc.summary}</p>` : ''}`;
}

function bottom(doc, st, now) {
  return html`<section class="bol-bottom" data-tour-id="boletin-top" aria-labelledby="bol-top-h">
      <div class="section-head"><h3 id="bol-top-h">${tableHead(doc, st)}</h3>
        <div class="bol-tbl-ctl no-print">${st.level !== null ? html`<button type="button" class="linkish" data-level="${st.level}">Quitar el filtro</button>` : ''}
        <button type="button" class="linkish" id="bol-all" aria-pressed="${String(st.all)}">${st.all ? 'Ver solo los diez primeros' : 'Ver los 25 departamentos'}</button></div></div>
      ${table(doc, st, now)}
      <p class="muted small bol-order"><strong>Orden:</strong> ${(doc.order || []).join('; ')}. Los niveles son los de cada institución (SENAMHI, INDECI, DHN, IGP, ANA); el boletín no emite alertas propias ni calcula probabilidades: las de arriba son del ENFEN. Ante una emergencia, siga al INDECI, al SENAMHI y a su municipalidad.</p>
    </section>`;
}

const footer = html`<footer class="bol-foot small muted">Observatorio ENSO Perú · datos abiertos: <a href="data/boletin.json">boletin.json</a> · <a href="data/boletin.xml">canal Atom</a> · <a href="#/noticias">mapa de alertas al momento</a></footer>`;

/** A y B: la hoja clásica, con el mapa del Perú o el mosaico. */
function sheet(doc, geo, st, now) {
  const useTiles = st.variant === 'mosaico' || !geo;
  const map = useTiles ? tileMap(doc.segments, st.sel, now) : svgMap(geo, doc.segments, st.sel, now);
  return html`<article class="bol-sheet card" id="bol-sheet" data-form="${st.variant}" aria-labelledby="bol-h">
    ${topHeader(doc, st)}
    ${enfenLine(doc, now)}
    ${changesBlock(doc)}
    <div class="bol-half" data-tour-id="boletin-map">
      <div class="bol-map"><div class="bol-map-head"><strong>Nivel más alto de los avisos oficiales</strong>${variantSwitch(st.variant)}</div>
        ${st.variant === 'mapa' && !geo ? html`<p class="small muted">No se pudo cargar el mapa del Perú: se muestra el mosaico.</p>` : ''}
        ${map}<div id="bol-dep" aria-live="polite"></div>${legend(doc, now)}${useTiles ? abbrList(doc.segments) : ''}</div>
      <div class="bol-what"><h3>Qué se viene</h3>${headline(doc)}${probBars(doc)}${guidance(doc, true)}</div>
    </div>
    ${bottom(doc, st, now)}
    ${footer}
  </article>`;
}

// ---------------------------------------------------------------------------------------------------- versión C
const LADDER = [['No activo', 'Condiciones normales'], ['Vigilancia', 'Es probable que se desarrolle'], ['Alerta', 'Está en curso o es inminente']];

function ladder(doc) {
  const e = doc.enso?.enfen;
  if (!e) return '';
  const step = Number.isInteger(e.step) ? e.step : null;
  const what = e.phase === 'nina' ? 'La Niña Costera' : 'El Niño Costero';
  return html`<section class="fc-status" aria-labelledby="fc-st-h"><div class="fc-st-txt"><div class="eyebrow" id="fc-st-h">Estado oficial del ENFEN · ${what}</div>
      <strong class="fc-st-now">${e.status}</strong>
      <div class="small muted">${e.url ? html`<a href="${safeUrl(e.url)}" rel="noopener" target="_blank">Comunicado oficial${e.number ? ` N° ${e.number}` : ''}</a>` : 'Comunicado oficial'}${e.issued ? `, ${F.fmtDate(e.issued)}` : ''}${e.next ? ` · próximo: ${F.fmtDate(e.next)}` : ''}${doc.enso?.noaa ? ` · NOAA: ${doc.enso.noaa.status}` : ''}</div>${e.stale ? html`<span class="tag tag-prelim">ya debió salir uno nuevo</span>` : ''}</div>
    <ol class="fc-ladder" aria-label="Escala del sistema de alerta del ENFEN">${LADDER.map(([l, t], i) => html`<li class="${i === step ? 'on' : ''}${step !== null && i < step ? ' past' : ''}" ${i === step ? 'aria-current="step"' : ''}><strong>${l}</strong><span>${t}</span></li>`)}</ol></section>`;
}

function keyMessages(doc) {
  const first = (t) => (t.match(/^.*?[.!?](\s|$)/) || [t])[0].trim();
  const lines = (doc.headline || []).map((h) => html`<li><strong>${h.title}:</strong> ${first(h.text)}</li>`);
  return html`<section class="fc-key" aria-labelledby="fc-key-h"><h3 id="fc-key-h">El boletín en 30 segundos</h3>${doc.summary ? html`<p class="fc-lead">${doc.summary}</p>` : ''}<ul>${lines}</ul></section>`;
}

function timelineBlock(doc, sel) {
  const tl = doc.timeline || [];
  if (!tl.length) return '';
  return html`<section class="fc-when" aria-labelledby="fc-when-h"><h3 id="fc-when-h">Cuándo</h3><ol class="fc-tl">${tl.map((w) => html`<li><div class="fc-tl-h"><strong>${w.label}</strong><span class="muted small">${w.deps.length || 'ninguno'}</span></div>
      <div class="fc-chips">${w.deps.length ? w.deps.map((d) => html`<button type="button" class="fc-chip d-${LV[d.rank]}${sel === d.code ? ' sel' : ''}" data-pick="${d.code}" aria-pressed="${String(sel === d.code)}">${d.name}</button>`) : html`<span class="small muted">Sin avisos que empiecen en esta ventana.</span>`}</div></li>`)}</ol>
    <p class="small muted">Según el inicio y el fin de cada aviso oficial; no es un pronóstico propio.</p></section>`;
}

function probStack(doc) {
  const p = (doc.enso?.probabilities || []).find((x) => x.region === 'nino12');
  if (!p || !(p.all || []).length) return probBars(doc);
  return html`<section class="fc-prob" aria-labelledby="fc-prob-h"><h3 id="fc-prob-h">Probabilidad para el verano (ENFEN)</h3>
    <div class="fc-stack" role="img" aria-label="${p.all.map((x) => `${x.label} ${x.pct} %`).join(', ')}">${p.all.map((x, i) => html`<span class="fc-s${Math.min(i, 7)} cat-${x.category}" style="flex:${x.pct}" title="${x.label}: ${x.pct} %">${x.pct >= 12 ? `${x.pct} %` : ''}</span>`)}</div>
    <ul class="fc-stack-key small">${p.all.map((x) => html`<li><span class="sw cat-${x.category}"></span>${x.label}: <strong>${x.pct} %</strong></li>`)}</ul>
    <p class="small muted">Costa del Perú (Niño 1+2), ${p.url ? html`<a href="${safeUrl(p.url)}" rel="noopener" target="_blank">informe técnico N° ${p.informe}</a>` : `informe técnico N° ${p.informe}`}${p.page ? `, pág. ${p.page}` : ''}.</p></section>`;
}

function depCards(doc, st, now) {
  const events = Object.fromEntries((doc.events || []).map((e) => [e.key, e]));
  const rows = visibleRows(doc, st);
  if (!rows.length) return html`<p>Ningún departamento tiene avisos oficiales vigentes o próximos relacionados con El Niño.</p>`;
  return html`<ol class="fc-cards">${rows.map((s) => {
    const sc = s.scenario;
    const pct = sc.districts ? Math.round((100 * sc.muyAlto) / sc.districts) : 0;
    const n = s.events.filter((k) => events[k]).length;
    return html`<li class="fc-card bc-${LV[s.rank]}-edge${segExpired(s, now) ? ' gone' : ''}${st.sel === s.code ? ' sel' : ''}" data-dep="${s.code}">
      <div class="fc-card-h"><span class="fc-pos">${s.position}</span><button type="button" class="linkish bol-name" data-pick="${s.code}" aria-pressed="${String(st.sel === s.code)}">${s.name}</button>${chip(s, true)}</div>
      <p class="fc-what">${s.hazards.slice(0, 3).join(' · ') || 'Sin avisos de El Niño'}</p>
      <dl class="fc-facts small"><div><dt>Cuándo</dt><dd>${segWhen(s, now)}</dd></div>
        <div><dt>Fuente</dt><dd>${joinEs(s.institutionsAll || s.institutions) || '—'}${n ? ` (${n})` : ''}</dd></div>
        <div><dt>Riesgo CENEPRED</dt><dd>${sc.districts ? html`<span class="bol-risk" role="img" aria-label="${pct} % muy alto"><span style="width:${pct}%"></span></span>${pct} % muy alto` : 'sin escenario'}</dd></div>
        <div><dt>Daños 72 h</dt><dd>${s.reports}</dd></div></dl></li>`;
  })}</ol>`;
}

function ficha(doc, st, now) {
  return html`<article class="bol-sheet bol-ficha card" id="bol-sheet" data-form="ficha" aria-labelledby="bol-h">
    ${topHeader(doc, st, false)}
    <div class="fc-switch">${variantSwitch(st.variant)}</div>
    ${ladder(doc)}
    ${changesBlock(doc)}
    <div class="fc-grid" data-tour-id="boletin-map">
      ${keyMessages(doc)}
      <section class="fc-map" aria-labelledby="fc-map-h"><h3 id="fc-map-h">Dónde</h3>${tileMap(doc.segments, st.sel, now, true)}<div id="bol-dep" aria-live="polite"></div></section>
    </div>
    <div class="fc-grid2">${timelineBlock(doc, st.sel)}${probStack(doc)}</div>
    ${guidance(doc)}
    <section class="bol-bottom" data-tour-id="boletin-top" aria-labelledby="bol-top-h">
      <div class="section-head"><h3 id="bol-top-h">${tableHead(doc, st)}</h3>
        <div class="bol-tbl-ctl no-print">${st.level !== null ? html`<button type="button" class="linkish" data-level="${st.level}">Quitar el filtro</button>` : ''}
        <button type="button" class="linkish" id="bol-all" aria-pressed="${String(st.all)}">${st.all ? 'Ver solo los diez primeros' : 'Ver los 25 departamentos'}</button></div></div>
      ${depCards(doc, st, now)}${tieNote(doc, st)}
      <p class="muted small bol-order"><strong>Orden:</strong> ${(doc.order || []).join('; ')}. Los niveles son los de cada institución; el boletín no emite alertas propias. Ante una emergencia, siga al INDECI, al SENAMHI y a su municipalidad.</p>
    </section>
    ${footer}
  </article>`;
}

// ---------------------------------------------------------------------------------------------- tarjeta y correo
function depDetail(doc, code, now) {
  const s = doc.segments.find((x) => x.code === code);
  if (!s) return '';
  const events = Object.fromEntries((doc.events || []).map((e) => [e.key, e]));
  const evs = s.events.map((k) => events[k]).filter(Boolean);
  const reps = (doc.reports || []).filter((r) => (r.deps || []).includes(code));
  const sc = s.scenario;
  return html`<div class="bol-depcard" role="region" aria-label="${s.name}"><div class="section-head"><strong>${s.position}. ${s.name}</strong> ${chip(s, true)}<button type="button" class="linkish" data-close>Cerrar</button></div>
    ${s.rank < 0 ? html`<p class="small">Ninguna institución tiene un aviso vigente o próximo relacionado con El Niño aquí. No quiere decir que no haya peligro.</p>`
      : html`<p class="small">${s.hazards.join(' · ')} · ${segWhen(s, now)}${s.places.length ? ` · ${joinEs(s.places.slice(0, 5))}` : ''}</p>
        <ul class="small">${evs.slice(0, 5).map((e) => html`<li><a href="${safeUrl(e.url)}" rel="noopener" target="_blank">${e.title}</a> <span class="muted">(${e.institution}, ${e.level || 'sin nivel'})</span></li>`)}</ul>
        ${evs.length > 5 ? html`<p class="small muted">Y ${evs.length - 5} avisos más en la tabla.</p>` : ''}`}
    ${reps.length ? html`<p class="small"><strong>Daños reportados en 72 h (INDECI):</strong></p><ul class="small">${reps.slice(0, 4).map((r) => html`<li>${r.url ? html`<a href="${safeUrl(r.url)}" rel="noopener" target="_blank">${r.title}</a>` : r.title}</li>`)}</ul>` : html`<p class="small muted">Sin reportes de daños del INDECI en 72 h.</p>`}
    <p class="small muted">${sc.districts ? `CENEPRED: ${F.fmtNumber(sc.muyAlto)} de ${F.fmtNumber(sc.districts)} distritos en riesgo muy alto y ${F.fmtNumber(sc.alto)} en alto.` : 'Sin escenario del CENEPRED para este departamento.'} <a href="#/zona?area=${s.code}">Ver ${s.name} en Mi zona</a></p></div>`;
}

function subForm(doc, enabled) {
  const deps = doc.segments.slice().sort((a, b) => a.name.localeCompare(b.name, 'es'));
  return html`<form id="bol-sub" class="bol-sub" novalidate data-t0="${Date.now()}">
    <h3 id="bol-sub-h">Recibir el boletín por correo</h3>
    <p class="small">Gratis. Le mandamos un correo para confirmar (doble confirmación): sin ese clic no recibe nada. Cada correo trae un enlace para darse de baja con un clic.</p>
    ${enabled ? '' : html`<p class="notice notice-info small">${raw(ICON.info)}<span>La suscripción funciona en el sitio publicado. Aquí puede usar el <a href="data/boletin.xml">canal Atom</a> o compartir por WhatsApp.</span></p>`}
    <label class="bol-field"><span>Correo electrónico</span><input type="email" name="email" autocomplete="email" inputmode="email" required maxlength="254" placeholder="nombre@ejemplo.pe" ${enabled ? '' : 'disabled'}></label>
    <fieldset class="bol-freq" ${enabled ? '' : 'disabled'}><legend>¿Cuándo quiere recibirlo?</legend>${FREQ.map(([v, l, t], i) => html`<label><input type="radio" name="frecuencia" value="${v}" ${i === 0 ? 'checked' : ''}><span><strong>${l}</strong><br><span class="small muted">${t}</span></span></label>`)}</fieldset>
    <details class="bol-deps"><summary>Solo me interesan algunos departamentos (opcional)</summary><p class="small muted">Sin marcar ninguno, recibe los cambios de todo el país. Los cambios del ENFEN llegan siempre.</p>
      <div class="bol-deps-grid">${deps.map((s) => html`<label><input type="checkbox" name="deps" value="${s.code}" ${enabled ? '' : 'disabled'}> ${s.name}</label>`)}</div></details>
    <label class="bol-hp" aria-hidden="true">Sitio web<input type="text" name="sitio_web" tabindex="-1" autocomplete="off"></label>
    <label class="bol-consent"><input type="checkbox" name="acepto" required ${enabled ? '' : 'disabled'}><span>Acepto que el Observatorio guarde mi correo y mis preferencias solo para mandarme este boletín (Ley 29733). <a href="#bol-privacy">Cómo se usan mis datos</a>.</span></label>
    <div class="bol-sub-row"><button type="submit" class="btn" ${enabled ? '' : 'disabled'}>${raw(ICON.bell)} Suscribirme</button><span class="small" id="bol-sub-st" role="status" aria-live="polite"></span></div>
  </form>`;
}

function deliveryCard(doc, enabled) {
  const recent = doc.recent || [];
  return html`<section class="card no-print bol-deliver" aria-labelledby="bol-rules-h" data-tour-id="boletin-rules"><h2 id="bol-rules-h">Recibir el boletín</h2>
    <div class="bol-deliver-grid">${subForm(doc, enabled)}
      <div class="bol-other"><h3>Otras formas</h3><ul>
        <li><a href="data/boletin.xml">Canal Atom</a> para lectores de noticias, Slack, Teams o IFTTT: no pide ningún dato.</li>
        <li>«Compartir por WhatsApp» (arriba) manda el resumen al chat o grupo que elija. El envío automático por WhatsApp necesita la API de pago de Meta y queda para una segunda fase.</li>
        <li><a href="data/boletin-correo.html" target="_blank" rel="noopener">Así se ve el correo</a>, con un mapa de cuadros que se lee en cualquier programa de correo.</li></ul>
        <h3 id="bol-privacy">Sus datos</h3><p class="small">Se guarda solo su correo, los departamentos y la frecuencia que elija, y la fecha en que confirmó. No se comparte con nadie ni se usa para otra cosa. Una suscripción sin confirmar se borra a los 7 días; al darse de baja se borra su correo. Puede pedir ver o borrar sus datos en cualquier momento desde el enlace «Preferencias» de cada correo (Ley 29733 de Protección de Datos Personales).</p></div></div>
    <details class="more"><summary>Cuándo llega un correo</summary><p>Cada actualización arma una edición nueva solo si algo cambió.</p>
      <div class="table-wrap"><table class="data bol-rules"><thead><tr><th scope="col">Situación</th><th scope="col">Qué se hace</th></tr></thead>
      <tbody>${(doc.rules || []).map((r) => html`<tr><td>${r.when}</td><td><span class="lvl lvl-s lvl-${TIER_MAIL[r.tier]?.[1] || 'un'}">${TIER_MAIL[r.tier]?.[0] || r.tier}</span></td></tr>`)}</tbody></table></div></details>
    ${recent.length > 1 ? html`<details class="more" id="bol-recent"><summary>Ediciones anteriores y sus cambios (${recent.length})</summary><ol class="bol-recent">${recent.map((r) => html`<li><details><summary><strong>N° ${r.edition}</strong> · ${when(r.at)} · ${(r.changes || []).length} ${(r.changes || []).length === 1 ? 'cambio' : 'cambios'}</summary><ul>${(r.changes || []).map((c) => html`<li>${c.text}</li>`)}</ul></details></li>`)}</ol></details>` : ''}
  </section>`;
}

// ------------------------------------------------------------------------------------- confirmación, baja, prefs
const API = 'api/boletin/';
async function api(path, body) {
  try {
    const r = await fetch(API + path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : { cache: 'no-store' });
    let j = {};
    try { j = await r.json(); } catch { /* sin cuerpo */ }
    return { ok: r.ok, status: r.status, ...j };
  } catch {
    return { ok: false, status: 0, error: 'No hay conexión con el servidor. Inténtelo de nuevo en un momento.' };
  }
}

/** El panel de un enlace del correo: confirmar, darse de baja o cambiar preferencias. Siempre con un botón: los
 * filtros de correo abren los enlaces solos y un GET no puede confirmar ni dar de baja a nadie. */
function tokenPanel(kind) {
  const T = {
    confirmar: ['Confirmar la suscripción', 'Falta un paso: confirme que quiere recibir el boletín de eventos El Niño en este correo.', 'Confirmar'],
    baja: ['Darse de baja', '¿Dejar de recibir el boletín? Se borra su correo de la lista.', 'Darme de baja'],
    preferencias: ['Sus preferencias', 'Cambie cuándo recibe el boletín y de qué departamentos.', 'Guardar'],
  }[kind];
  return html`<section class="card bol-token" id="bol-token" aria-labelledby="bol-token-h"><h2 id="bol-token-h">${T[0]}</h2><p>${T[1]}</p>
    <div id="bol-token-body"></div>
    <div class="bol-sub-row"><button type="button" class="btn" id="bol-token-go">${T[2]}</button><span class="small" id="bol-token-st" role="status" aria-live="polite"></span></div></section>`;
}

async function wireToken(kind, token, doc) {
  const go = $('#bol-token-go');
  const st = $('#bol-token-st');
  const body = $('#bol-token-body');
  if (!go) return;
  if (!/^[A-Za-z0-9_-]{20,200}$/.test(token)) { st.textContent = 'El enlace está incompleto. Cópielo entero desde el correo.'; go.disabled = true; return; }
  let prefs = null;
  if (kind === 'preferencias') {
    go.disabled = true;
    prefs = await api(`preferencias?t=${encodeURIComponent(token)}`);
    if (!prefs.ok) { st.textContent = prefs.error || 'No se encontró la suscripción.'; return; }
    const deps = doc.segments.slice().sort((a, b) => a.name.localeCompare(b.name, 'es'));
    body.innerHTML = String(html`<p class="small">Correo: <strong>${prefs.email}</strong> · suscrito desde ${F.fmtDate(prefs.since)}</p>
      <fieldset class="bol-freq"><legend>¿Cuándo?</legend>${FREQ.map(([v, l]) => html`<label><input type="radio" name="frecuencia" value="${v}" ${prefs.frecuencia === v ? 'checked' : ''}> ${l}</label>`)}</fieldset>
      <fieldset class="bol-deps-grid"><legend>Departamentos (ninguno = todo el país)</legend>${deps.map((s) => html`<label><input type="checkbox" name="deps" value="${s.code}" ${(prefs.deps || []).includes(s.code) ? 'checked' : ''}> ${s.name}</label>`)}</fieldset>
      <p class="small"><button type="button" class="linkish" id="bol-token-del">Borrar mis datos y darme de baja</button></p>`);
    go.disabled = false;
    $('#bol-token-del')?.addEventListener('click', async () => {
      const r = await api('baja', { t: token });
      st.textContent = r.ok ? 'Listo: se borró su correo de la lista.' : r.error || 'No se pudo.';
      if (r.ok) { go.disabled = true; body.innerHTML = ''; }
    });
  }
  go.addEventListener('click', async () => {
    go.disabled = true;
    st.textContent = 'Un momento…';
    const payload = { t: token };
    if (kind === 'preferencias') {
      payload.frecuencia = $('input[name="frecuencia"]:checked', body)?.value || 'todo';
      payload.deps = $$('input[name="deps"]:checked', body).map((i) => i.value);
    }
    const r = await api(kind, payload);
    st.textContent = r.ok ? ({ confirmar: 'Suscripción confirmada. Le llegará el próximo boletín.', baja: 'Listo: se borró su correo de la lista. No recibirá más boletines.', preferencias: 'Preferencias guardadas.' })[kind] : r.error || 'No se pudo. Inténtelo de nuevo.';
    go.disabled = r.ok && kind !== 'preferencias';
  });
}

async function wireSub(enabled) {
  const f = $('#bol-sub');
  if (!f || !enabled) return;
  const st = $('#bol-sub-st');
  f.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const email = f.email.value.trim();
    if (!/^[^@\s<>"]+@[^@\s<>"]+\.[A-Za-z]{2,}$/.test(email) || email.length > 254) { st.textContent = 'Revise el correo: debe tener la forma nombre@dominio.pe.'; f.email.focus(); return; }
    if (!f.acepto.checked) { st.textContent = 'Para suscribirse, marque la casilla de aceptación.'; f.acepto.focus(); return; }
    const btn = $('button[type="submit"]', f);
    btn.disabled = true;
    st.textContent = 'Enviando…';
    const r = await api('suscribir', {
      email, frecuencia: $('input[name="frecuencia"]:checked', f)?.value || 'todo', deps: $$('input[name="deps"]:checked', f).map((i) => i.value),
      acepto: true, sitio_web: f.sitio_web.value, ms: Date.now() - Number(f.dataset.t0 || Date.now()),
    });
    btn.disabled = false;
    st.textContent = r.ok ? `Listo. Revise ${email} (y la carpeta de spam): le llegó un correo para confirmar.` : r.error || 'No se pudo. Inténtelo de nuevo en un momento.';
    if (r.ok) f.reset();
  });
}

let ENABLED = null;
/** ¿Está activa la suscripción? Solo en el sitio publicado con su API (no en GitHub Pages ni en local). */
async function subEnabled() {
  if (ENABLED !== null) return ENABLED;
  if (!hasBackend()) return (ENABLED = false);
  const r = await api('estado');
  return (ENABLED = Boolean(r.ok && r.enabled));
}

// --------------------------------------------------------------------------------------------------------- vista
export const boletinView = {
  title: 'Boletín',
  render() {
    return html`<div class="page-head no-print"><div class="eyebrow">Boletín</div><h1>Boletín de eventos de El Niño</h1>
      <p>Una hoja con lo que viene, dónde y cuándo: arriba el país; abajo los departamentos más críticos. Lo arma cada actualización con los avisos oficiales, el ENFEN y el CENEPRED. No es una alerta oficial.</p>
      <div class="bol-actions" data-tour-id="boletin-actions">
        <a class="btn" href="#bol-sub" id="bol-subscribe">${raw(ICON.bell)} Recibir por correo</a>
        <button type="button" class="btn ghost" id="bol-print">${raw(ICON.download)} Imprimir o PDF</button>
        <button type="button" class="btn ghost" id="bol-share" hidden>Compartir</button>
        <a class="btn ghost" id="bol-wa" href="https://wa.me/" target="_blank" rel="noopener" aria-disabled="true">Compartir por WhatsApp</a>
        <button type="button" class="btn ghost" id="bol-copy">Copiar resumen</button>
        <details class="bol-more-act"><summary class="btn ghost">Más</summary><div>
          <a class="btn ghost" id="bol-mail" href="data/boletin-correo.html" target="_blank" rel="noopener">Ver como correo</a>
          <a class="btn ghost" href="data/csv/boletin-departamentos.csv" download>CSV de departamentos</a>
          <a class="btn ghost" href="data/csv/boletin-avisos.csv" download>CSV de avisos</a>
          <a class="btn ghost" href="data/boletin.png" download="boletin-el-nino.png" id="bol-img">Imagen para compartir (PNG)</a>
          <a class="btn ghost" href="data/boletin.xml">Canal Atom</a></div></details>
        <span class="small muted" id="bol-st" role="status" aria-live="polite"></span>
      </div></div>
      <div id="bol-root" data-tour-id="boletin"><div class="skeleton"></div></div>`;
  },
  async after(load) {
    const root = $('#bol-root');
    const doc = await load('boletin.json');
    if (!root.isConnected) return;
    if (!doc || !Array.isArray(doc.segments)) {
      root.innerHTML = String(html`<div class="notice notice-warn">${raw(ICON.triangle)}<p>El boletín no está en esta publicación. Vea los avisos de este momento en el <a href="#/noticias">mapa de alertas</a>.</p></div>`);
      $$('.bol-actions a, .bol-actions button, .bol-actions details').forEach((b) => { b.hidden = true; });
      return;
    }
    const q = params();
    const [geo, enabled] = await Promise.all([
      fetch('assets/peru-map.json').then((r) => (r.ok ? r.json() : null)).catch(() => null),
      subEnabled(),
      abReady(),
    ]);
    if (!root.isConnected) return;
    const exp = ab('boletin');
    const codes = new Set(doc.segments.map((s) => s.code));
    const variant = VARIANTS.some(([v]) => v === exp.variant) ? exp.variant : 'mapa';
    const st = { variant, sel: codes.has(q.get('dep')) ? q.get('dep') : '', all: false, level: null };
    const tokenKind = ['confirmar', 'baja', 'preferencias'].find((k) => q.get(k));
    const now = Date.now();
    let viewed = false;
    /** Foco antes de redibujar: el mismo control vuelve a tenerlo (el teclado no se pierde al elegir). */
    const focusKey = () => {
      const a = document.activeElement;
      if (!a || !root.contains(a)) return null;
      for (const k of ['data-pick', 'data-dep', 'data-variant', 'data-level', 'data-level-go']) if (a.hasAttribute(k)) return `[${k}="${a.getAttribute(k)}"]`;
      return a.id ? `#${a.id}` : null;
    };
    const draw = () => {
      const fk = focusKey();
      const inMap = document.activeElement?.closest?.('.bol-svg, .bol-tiles') ? (document.activeElement.closest('.bol-svg') ? '.bol-svg ' : '.bol-tiles ') : '';
      const old = expiredSince(doc, now);
      main.innerHTML = String(html`${isOld(doc, now) ? html`<div class="notice notice-warn">${raw(ICON.clock)}<p>Esta edición es del ${when(doc.cutoff) || 'corte sin fecha'}: la actualización diaria no corrió después. Lo de este momento está en el <a href="#/noticias">mapa de alertas</a>.</p></div>` : ''}
        ${old.length ? html`<p class="notice notice-info">${raw(ICON.info)}<span>Desde el corte, ${old.length} ${old.length === 1 ? 'aviso de esta edición ya venció' : 'avisos de esta edición ya vencieron'} (se ven más claros). La próxima edición sale con la actualización diaria; lo de este momento está en el <a href="#/noticias">mapa de alertas</a>.</span></p>` : ''}
        ${st.variant === 'ficha' ? ficha(doc, st, now) : sheet(doc, geo, st, now)}`);
      if (st.sel) $('#bol-dep').innerHTML = String(depDetail(doc, st.sel, now));
      $$('.bol-row, .fc-card', root).forEach((r) => r.classList.toggle('on', r.dataset.dep === st.sel));
      if (fk) (root.querySelector(inMap + fk) || root.querySelector(fk))?.focus({ preventScroll: true });
      if (!viewed) { exp.mark('view'); viewed = true; }
    };
    const keepHash = () => {
      const p = params();
      if (st.sel) p.set('dep', st.sel); else p.delete('dep');
      const s = p.toString();
      try { history.replaceState(null, '', `#/boletin${s ? `?${s}` : ''}`); } catch { /* sin historial */ }
    };
    const pick = (code, scroll = true) => {
      st.sel = st.sel === code ? '' : code;
      exp.mark('select');
      draw();
      keepHash();
      // En el teléfono la tarjeta queda bajo el mapa: se trae a la vista para que no parezca que no pasó nada.
      const card = st.sel && $('#bol-dep .bol-depcard');
      if (card && scroll && card.getBoundingClientRect().bottom > innerHeight) card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    };
    root.addEventListener('click', (ev) => {
      const t = ev.target;
      const v = t.closest('[data-variant]');
      if (v) { if (v.dataset.variant !== st.variant) { exp.choose(v.dataset.variant); st.variant = v.dataset.variant; draw(); } return; }
      if (t.closest('[data-close]')) { st.sel = ''; draw(); keepHash(); return; }
      if (t.closest('#bol-all')) { st.all = !st.all; st.level = null; draw(); return; }
      const lv = t.closest('[data-level], [data-level-go]');
      if (lv) {
        const r = Number(lv.dataset.level ?? lv.dataset.levelGo);
        st.level = st.level === r ? null : r;
        draw();
        if (lv.dataset.levelGo !== undefined) $('#bol-top-h')?.scrollIntoView({ block: 'start', behavior: 'smooth' });
        return;
      }
      const op = t.closest('[data-open]');
      if (op) { const d = document.getElementById(op.dataset.open); if (d) { d.open = true; d.scrollIntoView({ block: 'start', behavior: 'smooth' }); } return; }
      const p = t.closest('[data-pick]');
      if (p) { pick(p.dataset.pick); return; }
      const d = t.closest('[data-dep]');
      if (d && (d.closest('.bol-svg') || d.closest('.bol-tiles'))) pick(d.dataset.dep);
      if (t.closest('.bol-evs summary') || t.closest('.bol-evs a')) exp.mark('detail');
    });
    root.addEventListener('keydown', (ev) => {
      const d = ev.target.closest?.('.bol-svg [data-dep]');
      if (d && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); pick(d.dataset.dep); return; }
      if (ev.key === 'Escape' && st.sel) { const was = st.sel; st.sel = ''; draw(); keepHash(); root.querySelector(`.bol-tiles [data-dep="${was}"], .bol-svg [data-dep="${was}"]`)?.focus(); return; }
      // Mosaico: flechas para ir al cuadro vecino (un solo cuadro en el orden de tabulación).
      const tile = ev.target.closest?.('.bol-tile');
      const dir = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] }[ev.key];
      if (tile && dir) {
        ev.preventDefault();
        const [r, c] = [Number(tile.dataset.r), Number(tile.dataset.c)];
        const all = $$('.bol-tile', tile.parentElement);
        const cand = all.filter((x) => (dir[0] ? Math.sign(Number(x.dataset.r) - r) === dir[0] : Math.sign(Number(x.dataset.c) - c) === dir[1]));
        const dist = (x) => Math.abs(Number(x.dataset.r) - r) * (dir[0] ? 1 : 3) + Math.abs(Number(x.dataset.c) - c) * (dir[1] ? 1 : 3);
        const next = cand.sort((a, b) => dist(a) - dist(b))[0];
        if (next) { all.forEach((x) => { x.tabIndex = x === next ? 0 : -1; }); next.focus(); }
      }
    });
    // La analítica de «pasó el cursor» cuenta solo el mapa o el mosaico, no la tabla ni las tarjetas.
    root.addEventListener('mouseover', (ev) => { if (ev.target.closest?.('.bol-svg [data-dep], .bol-tiles [data-dep]')) exp.mark('hover'); }, { passive: true });
    // Tres partes: el enlace del correo (si lo hay), la hoja (se redibuja al elegir) y la suscripción, que no se
    // redibuja para no borrar lo que la persona está escribiendo.
    root.innerHTML = String(html`${tokenKind ? tokenPanel(tokenKind) : ''}<div id="bol-main"></div>${deliveryCard(doc, enabled)}`);
    const main = $('#bol-main');
    draw();
    wireSub(enabled);
    if (tokenKind) { wireToken(tokenKind, q.get(tokenKind), doc); $('#bol-token')?.scrollIntoView({ block: 'start' }); }
    else if (q.has('suscribir')) $('#bol-sub')?.scrollIntoView({ block: 'start' });
    else if (st.sel) $('#bol-dep')?.scrollIntoView({ block: 'nearest' });
    $('#bol-subscribe')?.addEventListener('click', (ev) => { ev.preventDefault(); const f = $('#bol-sub'); f?.scrollIntoView({ block: 'start', behavior: 'smooth' }); f?.email?.focus({ preventScroll: true }); });
    const wa = $('#bol-wa');
    if (wa) { wa.href = `https://wa.me/?text=${encodeURIComponent(doc.whatsapp || '')}`; wa.removeAttribute('aria-disabled'); }
    const share = $('#bol-share');
    if (share && navigator.share) {
      share.hidden = false;
      // En el teléfono se comparte la imagen del mapa con el texto (WhatsApp, Telegram, correo…); si el navegador no
      // comparte archivos, el texto y el enlace (que en WhatsApp muestra la misma imagen como vista previa).
      // La imagen se baja antes: Safari solo deja compartir en el mismo gesto del clic, sin esperas de red de por medio.
      let file = null;
      if (navigator.canShare) {
        fetch(`data/boletin.png?n=${doc.edition}`).then((r) => (r.ok ? r.blob() : null)).then((b) => {
          const f = b && new File([b], `boletin-el-nino-${doc.edition}.png`, { type: 'image/png' });
          if (f && navigator.canShare({ files: [f] })) file = f;
        }).catch(() => {});
      }
      share.addEventListener('click', () => {
        const data = { title: `Boletín El Niño N° ${doc.edition}`, text: doc.whatsapp || '' };
        navigator.share(file ? { ...data, files: [file] } : { ...data, url: `${location.origin}${location.pathname}#/boletin` }).catch(() => {});
      });
    }
    $('#bol-print')?.addEventListener('click', () => window.print());
    $('#bol-copy')?.addEventListener('click', async () => {
      const msg = $('#bol-st');
      const text = doc.whatsapp || '';
      try {
        await navigator.clipboard.writeText(text);
        msg.textContent = 'Resumen copiado. Péguelo en WhatsApp o en un correo.';
      } catch {
        // Sin portapapeles (http, permisos): se selecciona el texto en un cuadro para copiarlo a mano.
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.className = 'bol-copybox';
        ta.setAttribute('aria-label', 'Resumen para copiar');
        msg.replaceChildren(ta);
        ta.select();
        let ok = false;
        try { ok = document.execCommand('copy'); } catch { /* navegador sin execCommand */ }
        if (ok) msg.textContent = 'Resumen copiado. Péguelo en WhatsApp o en un correo.';
      }
    });
  },
};
