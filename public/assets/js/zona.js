// Mi zona: para un lugar elegido (departamento, provincia o distrito), lo que pasó antes, lo que hay hoy y qué
// meses suelen ser los peores, en una sola página, y lo que se espera: el escenario de riesgo por lluvias del CENEPRED
// para cada distrito y, donde evaluó manzanas ante El Niño 2026-2027, ese detalle.
//
// No calcula nada propio: la historia es la de Memoria de desastres (historico-model.js, el mismo cálculo que los
// CSV del equipo), los avisos son los de feed.json con el nivel que dio cada institución, y la fase del ENSO la
// de resumen.json. Lo pasado no es un pronóstico, y la página lo dice. El riesgo esperado es el nivel que el CENEPRED
// dio a cada distrito por movimientos en masa y por inundaciones (assets/capas/escenario-distritos.json, de
// tools.build_escenario_distritos) y a cada manzana (assets/capas/manzanas-riesgo.json, la misma capa que la vista
// «Daños y pobreza» de la Memoria): aquí solo se muestran y se cuentan, con los dos peligros siempre a la vista y el
// más alto primero. La página no da recomendaciones propias: enlaza a las oficiales.
//
// «Usar mi ubicación» pide la posición al navegador y busca los distritos más cercanos aquí mismo: la posición no se
// envía a ningún servidor ni se guarda.

import { html, raw, esc, safeUrl, $, $$ } from './lib/dom.js';
import * as F from './lib/format.js';
import { ICON } from './icons.js';
import * as M from './historico-model.js';
import { loadAll, downloadTeamCsv } from './historico.js';
import { blocks } from './historico-detalle.js';
import { phaseOf } from './alertmap.js';

const CODE_RE = /^\d{2}(\d{2}){0,2}$/;
const LEVEL = { 2: 'departamento', 4: 'provincia', 6: 'distrito' };
/** Clase de la etiqueta de cada nivel del CENEPRED, de «Muy Alto» a «Bajo» (las mismas etiquetas que los avisos). */
const RISK_CLS = ['lvl-r3', 'lvl-r2', 'lvl-r1', 'lvl-r0'];
/** Más lejos que esto del centro del distrito más cercano, la posición no está en el Perú (o es un error). */
export const NEAR_MAX_KM = 150;
const KM_PER_DEG = 111.32;
const collator = new Intl.Collator('es');
/** El escenario por distrito del CENEPRED; se pide una vez. Si falla, la página lo dice y sigue. */
let SCENARIO = null;
const scenario = () => (SCENARIO ||= fetch('assets/capas/escenario-distritos.json', { cache: 'no-cache' })
  .then((r) => { if (!r.ok) throw new Error(`escenario-distritos.json: HTTP ${r.status}`); return r.json(); })
  .catch((e) => { console.warn(e); SCENARIO = null; return null; }));
/** «A, B y C». */
export const joinEs = (l) => (l.length > 1 ? `${l.slice(0, -1).join(', ')} y ${l[l.length - 1]}` : l[0] || '');

/** Etiqueta única de cada lugar para el buscador: «Chosica · Lima, Lima» (distrito · provincia, departamento). */
export function placeLabels(names) {
  const dep = names.departamento, prov = names.provincia, dist = names.distrito;
  const out = new Map();
  const add = (label, code) => { let l = label, n = 2; while (out.has(l)) l = `${label} (${n++})`; out.set(l, code); };
  for (const [c, n] of Object.entries(dep)) add(`${n} · departamento`, c);
  for (const [c, n] of Object.entries(prov)) add(`${n} · provincia de ${dep[c.slice(0, 2)] || ''}`, c);
  for (const [c, n] of Object.entries(dist)) add(`${n} · ${prov[c.slice(0, 4)] || ''}, ${dep[c.slice(0, 2)] || ''}`, c);
  return out;
}

/** Nombre completo de un código: «Lurigancho, Lima, Lima». */
export function placeName(names, code) {
  const parts = [names.distrito[code], names.provincia[code.slice(0, 4)], names.departamento[code.slice(0, 2)]];
  return (code.length === 6 ? parts : code.length === 4 ? parts.slice(1) : parts.slice(2)).filter(Boolean).join(', ');
}

/** Los lugares un nivel por debajo de ``code`` («» = los departamentos), ordenados por nombre: [[código, nombre], …]. */
export function childrenOf(names, code = '') {
  const src = code.length === 0 ? names.departamento : code.length === 2 ? names.provincia : code.length === 4 ? names.distrito : {};
  return Object.entries(src).filter(([c]) => c.startsWith(code)).sort((a, b) => collator.compare(a[1], b[1]) || (a[0] < b[0] ? -1 : 1));
}

/** Los ``n`` distritos cuyo punto central queda más cerca de una posición, del más cercano al más lejano:
 * [{code, km}, …]. Vacío si la posición no es válida o el más cercano queda a más de ``NEAR_MAX_KM`` (fuera del Perú).
 * Es el punto central, no el límite: por eso la página ofrece varios y la persona elige el suyo. */
export function nearestDistricts(peru, names, lat, lon, n = 3) {
  const p = peru?.lonLat;
  if (!p || !Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) return [];
  const x = (lon - p.lon0) * p.cos * p.k, y = (p.lat1 - lat) * p.k;
  const out = [];
  for (const [code, pt] of Object.entries(peru.points || {})) {
    if (code.length !== 6 || !names.distrito[code] || !Array.isArray(pt)) continue;
    out.push({ code, km: (Math.hypot(pt[0] - x, pt[1] - y) / p.k) * KM_PER_DEG });
  }
  out.sort((a, b) => a.km - b.km || (a.code < b.code ? -1 : 1));
  return out.length && out[0].km <= NEAR_MAX_KM ? out.slice(0, n) : [];
}

/** Lo que el CENEPRED evaluó dentro del lugar (manzanas-riesgo.json): manzanas, personas y viviendas por nivel, el
 * nivel más alto que aparece, el total en riesgo alto o muy alto y los centros poblados con más personas en ese
 * riesgo. ``null`` si no hay ninguna manzana evaluada en el lugar. No calcula un nivel propio para el distrito. */
export function expectedRisk(K, area) {
  const levels = K?.levels || [];
  const rows = (K?.blocks || []).filter((b) => String(b[2]).startsWith(area) && levels[b[4]]);
  if (!area || !rows.length) return null;
  const by = levels.map((name) => ({ name, n: 0, pob: 0, viv: 0 }));
  const cp = new Map();
  for (const [, , , place, l, pob, viv] of rows) {
    by[l].n++; by[l].pob += pob || 0; by[l].viv += viv || 0;
    if (l <= 1 && place) cp.set(place, (cp.get(place) || 0) + (pob || 0));
  }
  const high = by.slice(0, 2).reduce((a, x) => ({ n: a.n + x.n, pob: a.pob + x.pob, viv: a.viv + x.viv }), { n: 0, pob: 0, viv: 0 });
  return {
    n: rows.length, by, worst: by.findIndex((x) => x.n), high,
    distritos: new Set(rows.map((b) => String(b[2]))).size,
    places: [...cp.entries()].filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1] || collator.compare(a[0], b[0])).slice(0, 5),
  };
}

/** El escenario por distrito del CENEPRED (escenario-distritos.json) para un distrito: por peligro, el nivel
 * (índice en ``levels``) y lo que hay en las áreas de mayor susceptibilidad; ``worst``, el nivel más alto de los dos
 * y qué peligros lo tienen. ``null`` si el distrito no está en la tabla. No combina ni corrige nada. */
export function districtScenario(S, code) {
  const row = S?.districts?.[code];
  if (!row) return null;
  const hazards = Object.keys(S.hazards || {}).map((key, i) => {
    const r = row[i];
    return r && S.levels[r[0]] ? { key, name: S.hazards[key], level: r[0], personas: r[1] || 0, viviendas: r[2] || 0, salud: r[3] || 0, educativas: r[4] || 0, viasKm: r[5] || 0 } : null;
  }).filter(Boolean);
  if (!hazards.length) return null;
  const worst = Math.min(...hazards.map((h) => h.level));
  return { hazards, worst, worstHazards: hazards.filter((h) => h.level === worst).map((h) => h.key) };
}

/** El escenario para un departamento o una provincia: cuántos distritos hay en cada nivel por cada peligro, cuántos
 * están en riesgo alto o muy alto por al menos uno, y cuántos tiene la tabla. ``null`` si no hay ninguno. */
export function scenarioSummary(S, area) {
  const keys = Object.keys(S?.hazards || {});
  const rows = Object.entries(S?.districts || {}).filter(([c]) => c.startsWith(area));
  if (!area || !rows.length || !keys.length) return null;
  const by = S.levels.map((name) => ({ name, n: keys.map(() => 0) }));
  let highAny = 0;
  const high = keys.map(() => 0);
  for (const [, row] of rows) {
    let any = false;
    keys.forEach((_, i) => {
      const l = row[i]?.[0];
      if (!by[l]) return;
      by[l].n[i]++;
      if (l <= 1) { high[i]++; any = true; }
    });
    if (any) highAny++;
  }
  return { n: rows.length, hazards: keys.map((k) => S.hazards[k]), by, high, highAny };
}

/** «enero a marzo de 2027» de un escenario ({from: '2027-01', until: '2027-03'}); «octubre de 2026» de un mes. */
export function monthEs(ym) {
  const [y, m] = String(ym || '').split('-').map(Number);
  return F.MESES[m - 1] && y ? `${F.MESES[m - 1]} de ${y}` : '';
}
export function scenarioPeriod(sc) {
  const a = monthEs(sc?.from), b = monthEs(sc?.until);
  if (!a || !b) return '';
  return sc.from.slice(0, 4) === sc.until.slice(0, 4) ? `${a.split(' de ')[0]} a ${b}` : `${a} a ${b}`;
}

/** Si un aviso toca el lugar: un código del aviso es el lugar, lo contiene o está dentro de él. */
export function touches(alert, code) {
  return (alert.geo?.places || []).some((p) => p.code && (p.code.startsWith(code) || code.startsWith(p.code)));
}

/** Registros por peligro y mes: {peligro: [12 cuentas]} de los registros con mes conocido, y el total por peligro. */
export function seasonality(recs) {
  const by = new Map();
  for (const r of recs) {
    if (!r.m) continue;
    if (!by.has(r.t)) by.set(r.t, new Array(12).fill(0));
    by.get(r.t)[r.m - 1]++;
  }
  return [...by.entries()].map(([t, m]) => ({ t, m, n: m.reduce((a, b) => a + b, 0) })).sort((a, b) => b.n - a.n);
}

/** Clase de color 0 a 4 de una cuenta respecto del máximo de su fila (0 = ninguno). */
export const heat = (v, max) => (v > 0 && max > 0 ? Math.min(4, 1 + Math.floor((3.999 * v) / max)) : 0);

function readArea() {
  const a = new URLSearchParams(location.hash.split('?')[1] || '').get('area') || '';
  return CODE_RE.test(a) ? a : '';
}

/** Avisos que tocan el lugar, separados con las mismas reglas de vigencia que el mapa de alertas (``phaseOf``):
 * vigentes o en curso, y próximos. Los vencidos y los reportes pasados no se muestran aquí. */
export function currentAlerts(items, now) {
  const withPhase = items.map((a) => ({ a, phase: phaseOf(a, now) }));
  return {
    now: withPhase.filter((x) => x.phase === 'vigente' || x.phase === 'en-curso').map((x) => x.a),
    soon: withPhase.filter((x) => x.phase === 'proxima').map((x) => x.a),
  };
}

function alertList(list) {
  return html`<ul class="link-list">${list.slice(0, 8).map((a) => html`<li>
    <strong>${a.institution}</strong>${a.severity ? html` · <span class="lvl lvl-r${a.severity.rank}" title="${a.severity.scaleLabel}">${a.severity.label}</span>` : html` · <span class="muted">sin nivel</span>`}
    — <a href="${safeUrl(a.url)}" rel="noopener" target="_blank">${a.title}</a> <span class="muted small">${F.fmtDate(a.date)}</span></li>`)}</ul>
    ${list.length > 8 ? html`<p class="muted small">Y ${list.length - 8} más en <a href="#/noticias">Noticias</a>.</p>` : ''}`;
}

function alertsCard(items, now) {
  const { now: live, soon } = currentAlerts(items, now);
  if (!live.length && !soon.length) return html`<p class="muted">Ninguna fuente oficial tiene un aviso vigente ni próximo que toque este lugar. Eso no quiere decir que no haya peligro: revise también el departamento y las <a href="#/noticias">noticias</a>.</p>`;
  return html`${live.length ? html`<h4>Vigentes ahora</h4>${alertList(live)}` : ''}${soon.length ? html`<h4>Próximos</h4>${alertList(soon)}` : ''}`;
}

function statCard(label, value, note) {
  return html`<div class="card metric"><div class="metric-name">${label}</div><div class="metric-val" style="font-size:1.6rem;font-weight:700">${value}</div><div class="muted small">${note}</div></div>`;
}

function seasonTable(rows) {
  if (!rows.length) return html`<p class="muted">Ningún registro de este lugar trae el mes.</p>`;
  return html`<div class="table-wrap"><table class="data zn-season"><caption class="visually-hidden">Registros por peligro y mes</caption>
    <thead><tr><th scope="col">Peligro</th>${F.MESES.map((m) => html`<th scope="col" title="${m}">${m.slice(0, 3)}</th>`)}<th scope="col">Total</th></tr></thead>
    <tbody>${rows.slice(0, 8).map(({ t, m, n }) => { const max = Math.max(...m); return html`<tr><th scope="row">${t}</th>${m.map((v) => html`<td class="zn-h${heat(v, max)}">${v || ''}</td>`)}<td><strong>${F.fmtNumber(n)}</strong></td></tr>`; })}</tbody></table></div>
    <p class="muted small">Cada fila se colorea respecto de su propio mes más alto. Solo cuenta registros con mes conocido.</p>`;
}

const OFFICIAL = html`<p class="muted small">El observatorio no da recomendaciones propias ni es un servicio de alerta. Qué hacer antes, durante y después lo dicen el <a href="https://www.gob.pe/indeci" rel="noopener" target="_blank">INDECI</a> y su municipalidad; los escenarios de riesgo completos los publica el <a href="https://www.gob.pe/cenepred" rel="noopener" target="_blank">CENEPRED</a> en su sistema SIGRID.</p>`;

const lvl = (S, l) => html`<span class="lvl ${RISK_CLS[l] || ''}">${S.levels[l]}</span>`;

/** Un distrito: los dos peligros lado a lado (nunca en pestañas), con el más alto arriba y nombrado. */
function scenarioDistrict(S, d) {
  const names = d.hazards.filter((h) => h.level === d.worst).map((h) => h.name.split(' (')[0].toLowerCase());
  return html`<p id="zn-rie-sum">Nivel más alto: ${lvl(S, d.worst)} por <strong>${joinEs(names)}</strong>.${d.hazards.length > 1 && d.worstHazards.length === 1 ? ' El otro peligro tiene un nivel menor: mire los dos.' : ''}</p>
    <div class="grid zn-haz">${d.hazards.map((h) => html`<div class="zn-haz-c" data-hazard="${h.key}"><h3>${h.name}</h3>
      <p>Nivel de riesgo: ${lvl(S, h.level)}</p>
      <dl class="zn-dl"><div><dt>Personas</dt><dd>${F.fmtNumber(h.personas)}</dd></div><div><dt>Viviendas</dt><dd>${F.fmtNumber(h.viviendas)}</dd></div>
        <div><dt>Establecimientos de salud</dt><dd>${F.fmtNumber(h.salud)}</dd></div><div><dt>Instituciones educativas</dt><dd>${F.fmtNumber(h.educativas)}</dd></div>
        <div><dt>Vías</dt><dd>${F.fmtNumber(h.viasKm, 1)} km</dd></div></dl></div>`)}</div>
    <p class="muted small">Las cifras son lo que el CENEPRED cuenta <strong>en las áreas de mayor susceptibilidad</strong> del distrito, no todo el distrito. Un cero con un nivel alto quiere decir que no ubicó personas o viviendas en esas áreas, no que no haya riesgo: el nivel también pesa la vulnerabilidad.</p>`;
}

/** Un departamento o una provincia: distritos por nivel, un peligro por columna. */
function scenarioArea(S, a) {
  return html`<p id="zn-rie-sum"><strong>${F.fmtNumber(a.highAny)} de ${F.fmtNumber(a.n)} distritos</strong> están en riesgo alto o muy alto por al menos uno de los dos peligros.</p>
    <div class="table-wrap"><table class="data zn-risk zn-scen"><caption class="visually-hidden">Distritos por nivel de riesgo y peligro</caption>
      <thead><tr><th scope="col">Nivel de riesgo</th>${a.hazards.map((h) => html`<th scope="col">${h.split(' (')[0]}</th>`)}</tr></thead>
      <tbody>${a.by.map((x, i) => html`<tr><th scope="row">${lvl(S, i)}</th>${x.n.map((v) => html`<td>${F.fmtNumber(v)}</td>`)}</tr>`)}</tbody></table></div>
    <p class="muted small">Número de distritos en cada nivel. Elija un distrito para ver sus dos niveles y lo que hay en sus áreas de mayor susceptibilidad.</p>`;
}

function scenarioPart(S, area) {
  if (!S?.districts || !Object.keys(S.districts).length) return html`<p class="muted" id="zn-rie-none">No se pudo cargar el escenario del CENEPRED. Vuelva a intentarlo más tarde.</p>`;
  const sc = S.scenario || {};
  const source = html`<p class="muted small" id="zn-rie-src">Fuente: CENEPRED, SIGRID, escenario de riesgo por lluvias para ${scenarioPeriod(sc)}, elaborado en ${monthEs(sc.prepared)}. <a href="${safeUrl(S.url)}" rel="noopener" target="_blank">Página de escenarios del SIGRID</a>${S.document ? html` · <a href="${safeUrl(S.document)}" rel="noopener" target="_blank">documento del escenario</a>` : ''} · <a href="${safeUrl(S.table)}" rel="noopener">tabla original (ZIP)</a>. Es una copia de esa fecha: el CENEPRED publica escenarios nuevos durante el año.</p>`;
  if (area.length === 6) {
    const d = districtScenario(S, area);
    return d ? html`${scenarioDistrict(S, d)}${source}` : html`<p id="zn-rie-none">Este distrito no está en la tabla del escenario del CENEPRED. <strong>Eso no quiere decir que aquí no haya riesgo.</strong> Mire su provincia.</p>${source}`;
  }
  const a = scenarioSummary(S, area);
  return a ? html`${scenarioArea(S, a)}${source}` : html`<p id="zn-rie-none">Este lugar no está en la tabla del escenario del CENEPRED. <strong>Eso no quiere decir que aquí no haya riesgo.</strong></p>${source}`;
}

/** El detalle por manzana, solo donde el CENEPRED lo evaluó (zonas de Piura, Tumbes y Lambayeque). */
function blocksPart(K, area) {
  const r = expectedRisk(K, area);
  if (!r) return '';
  const worst = r.by[r.worst];
  return html`<h3 id="zn-mz">Detalle por manzana ante El Niño 2026-2027</h3>
    <p id="zn-mz-sum">${r.high.n
    ? html`<strong>${F.fmtNumber(r.high.pob)} personas</strong> y ${F.fmtNumber(r.high.viv)} viviendas están en las ${F.fmtNumber(r.high.n)} manzanas que el CENEPRED calificó en riesgo alto o muy alto (censo 2017).`
    : html`Ninguna de las manzanas que el CENEPRED evaluó aquí está en riesgo alto o muy alto.`}
      Nivel más alto entre las ${F.fmtNumber(r.n)} manzanas evaluadas: <span class="lvl ${RISK_CLS[r.worst] || ''}">${worst.name}</span></p>
    <div class="table-wrap"><table class="data zn-risk zn-blocks"><caption class="visually-hidden">Manzanas evaluadas por el CENEPRED, por nivel de riesgo</caption>
      <thead><tr><th scope="col">Nivel de riesgo</th><th scope="col">Manzanas</th><th scope="col">Personas</th><th scope="col">Viviendas</th></tr></thead>
      <tbody>${r.by.map((x, i) => html`<tr><th scope="row"><span class="lvl ${RISK_CLS[i] || ''}">${x.name}</span></th><td>${F.fmtNumber(x.n)}</td><td>${F.fmtNumber(x.pob)}</td><td>${F.fmtNumber(x.viv)}</td></tr>`)}</tbody></table></div>
    ${r.places.length ? html`<p>Centros poblados con más personas en riesgo alto o muy alto: ${r.places.map(([n, v], i) => html`${i ? '; ' : ''}${n} (${F.fmtNumber(v)})`)}.</p>` : ''}
    <p class="muted small">Es otra evaluación del CENEPRED, más fina y solo de algunas zonas${area.length === 6 ? ' de este distrito' : ` (${F.fmtNumber(r.distritos)} ${r.distritos === 1 ? 'distrito' : 'distritos'} de este lugar)`}: una manzana que no aparece aquí no está libre de riesgo. Fuente: CENEPRED, SIGRID, escenario de riesgo ante El Niño 2026-2027; personas y viviendas por manzana del censo 2017 (INEI), no de hoy. <a href="#/memoria?area=${area}">Ver las manzanas en el mapa de la Memoria</a> (vista «Daños y pobreza»).</p>`;
}

function riskCard(S, K, area) {
  const period = scenarioPeriod(S?.scenario);
  return html`<section class="card" aria-labelledby="zn-rie"><h2 id="zn-rie">Riesgo esperado por lluvias${period ? `: ${period}` : ''}</h2>
    ${scenarioPart(S, area)}${blocksPart(K, area)}${OFFICIAL}</section>`;
}

/** Preguntas que la página debe responder sin que nadie la explique: qué es, de cuándo es y qué no dice. */
export const FAQ = [
  ['¿Esto es una alerta?', 'No. El observatorio no emite alertas ni recomendaciones de emergencia. Los avisos de la sección «Hoy» son los que publican el SENAMHI, el INDECI y otras instituciones, con el nivel que dio cada una y un enlace al original.'],
  ['¿De cuándo son los datos?', 'Cada bloque dice su fecha. La frecuencia de daños usa las temporadas 1970-71 a 2014-15 de DesInventar; los registros llegan hasta el último que figura arriba. Los avisos son los vigentes al abrir la página. El riesgo esperado es el escenario del CENEPRED cuyo periodo y mes de elaboración figuran en su título y en su fuente: es una copia de esa fecha, y el CENEPRED publica escenarios nuevos durante el año.'],
  ['¿Por qué hay dos niveles de riesgo?', 'Porque el CENEPRED evalúa por separado los movimientos en masa (huaycos y deslizamientos) y las inundaciones, y un distrito puede estar bajo en uno y muy alto en el otro. La página muestra siempre los dos y nombra el más alto; no los combina en un nivel propio.'],
  ['¿Qué cuenta como persona o vivienda en el riesgo esperado?', 'Las que el CENEPRED ubica en las áreas de mayor susceptibilidad del distrito, no todo el distrito. Por eso un distrito puede tener un nivel alto y cero viviendas: el nivel también pesa la vulnerabilidad. En el detalle por manzana son las personas y viviendas del censo 2017.'],
  ['¿Un nivel bajo, o pocos registros, quiere decir que es seguro?', 'No. El nivel es un resumen del distrito, y la historia cuenta solo lo que alguien registró. Una quebrada, una ladera o la ribera de un río pueden ser peligrosas en un distrito con nivel bajo o con pocos registros.'],
  ['¿Qué pasa con mi ubicación si uso «Usar mi ubicación»?', 'Se usa en su dispositivo para buscar los distritos más cercanos y se descarta. No se envía a ningún servidor ni se guarda.'],
  ['¿Qué debo hacer ante una emergencia?', 'Siga las indicaciones del INDECI, del SENAMHI y de su municipalidad. Esta página ayuda a entender el lugar; no reemplaza a esas instituciones.'],
];

function report(D, feed, area, now, K, S) {
  const names = D.sum.nombres;
  const recs = D.recs.filter((r) => r.u.startsWith(area));
  const years = M.coverageYears(D.sum.cobertura.homogenea, 0, 0);
  const st = M.summarize(recs, years, D.nino, D.great, D.hom, area.length);
  const alerts = (feed?.groups?.find((g) => g.id === 'alertas')?.items || []).filter((a) => touches(a, area));
  const [period, icen] = D.sum.icenUltimo || [];
  const fmtP = (v) => (v === null || v === undefined ? '—' : `${F.fmtNumber(v * 100, 0)} %`);
  const ic = (a, f) => (a && a[0] !== null ? `${f(a[0])}–${f(a[1])}` : '—');
  const last = st.ultimo;
  const small = st.muestraPequena;
  return html`
    <div class="grid g3">
      ${statCard('Registros', F.fmtNumber(st.registros), `desde ${recs.length ? recs.reduce((m, r) => (r.d < m ? r.d : m), '9999').slice(0, 4) : '—'}, todas las fuentes`)}
      ${statCard('Años con daños', `${st.aniosConEvento} de ${st.aniosCobertura}`, `temporadas ${years[0]}-${years[years.length - 1]} (DesInventar)`)}
      ${statCard('Uno cada', st.periodoRetorno ? `${F.fmtNumber(st.periodoRetorno, 1)} años` : '—', `IC 95 %: ${ic(st.periodoRetornoIC, (v) => F.fmtNumber(v, 1))}`)}
      ${statCard('En los próximos 5 años', fmtP(st.prob5Anios), `IC 95 %: ${ic(st.prob5AniosIC, fmtP)}`)}
      ${statCard('Con El Niño costero', st.razonNino ? `×${F.fmtNumber(st.razonNino, 1)}` : '—', st.razonNino ? `lugares con daños por año frente a las demás temporadas (IC ${ic(st.razonNinoIC, (v) => F.fmtNumber(v, 1))})` : 'sin datos suficientes')}
      ${statCard('Último registro', last ? F.fmtDate(last.d) : '—', last ? `${last.t}` : 'ninguno')}
    </div>
    ${small ? html`<div class="notice notice-warn">${raw(ICON.triangle)}<p>Pocos años con registros: los intervalos son muy anchos. Mire también la provincia y el departamento.</p></div>` : ''}
    <section class="card" aria-labelledby="zn-hoy"><h2 id="zn-hoy">Hoy</h2>
      <p>${D.ongoing ? html`Evento en curso en el catálogo: <strong>${D.ongoing}</strong>.` : 'Sin un evento ENSO en curso en el catálogo.'}${period ? html` Último ICEN publicado: <strong>${F.fmtNumber(icen, 2)} °C</strong> (${period}).` : ''}</p>
      <h3>Avisos oficiales que tocan este lugar</h3><p class="muted small">Incluye los que nombran su provincia o su departamento.</p>${alertsCard(alerts, now)}</section>
    ${riskCard(S, K, area)}
    <section class="card" aria-labelledby="zn-est"><h2 id="zn-est">Qué meses suelen ser los peores</h2>${seasonTable(seasonality(recs))}</section>
    <section class="card" aria-labelledby="zn-des"><h2 id="zn-des">Seguir</h2>
      <ul class="link-list">
        <li><a href="#/memoria?area=${area}">Ficha completa en Memoria de desastres</a> (mapa, ríos, cuencas, declaratorias)</li>
        <li><button type="button" id="zn-csv" class="btn">Descargar los ${F.fmtNumber(recs.length)} registros de este lugar (CSV)</button> <span class="muted small">En el esquema del tablero del equipo de prevención (Date, DangerType, Ubicacion, Distrito, Provincia, Departamento, Descripción, DuraciónEvento, Ubigeo, TipoEvento, Fuente, Latitud, Longitud) y los metadatos de la Memoria, con los mismos valores que <a href="assets/historico/eventos.zip" download>el catálogo completo</a>.</span><span class="small" id="zn-csv-st" role="status" aria-live="polite"></span></li>
      </ul></section>
    <p class="muted small">Esto es la historia del catálogo, no un pronóstico: dice con qué frecuencia pasó, no cuándo volverá a pasar. Los avisos de arriba son los que emiten las instituciones.</p>`;
}

export const zonaView = {
  title: 'Mi zona',
  render() {
    return html`<div class="page-head"><div class="eyebrow">Mi zona</div><h1>¿Qué pasó antes en mi lugar, y qué hay hoy?</h1>
      <p>Elija un departamento, una provincia o un distrito. Verá cuántas veces hubo daños, qué meses suelen ser los peores, cuánto cambia con El Niño, los avisos oficiales de hoy y el riesgo esperado por lluvias según el CENEPRED.</p></div>
      <div class="card"><label for="zn-q"><strong>Lugar</strong></label>
        <input id="zn-q" class="input" type="search" list="zn-list" autocomplete="off" placeholder="Escriba un nombre, por ejemplo Chosica" style="width:100%;max-width:520px">
        <datalist id="zn-list"></datalist>
        <div class="zn-pick" role="group" aria-label="O elija por pasos">
          <label>Departamento <select id="zn-dep" class="input"></select></label>
          <label>Provincia <select id="zn-prov" class="input" disabled></select></label>
          <label>Distrito <select id="zn-dist" class="input" disabled></select></label>
          <button type="button" id="zn-geo" class="btn ghost" hidden>Usar mi ubicación</button>
        </div>
        <p id="zn-msg" class="muted small" role="status"></p>
        <div id="zn-near" aria-live="polite"></div></div>
      <div id="zn-root" data-tour-id="zona" aria-live="polite"></div>
      <section class="card zn-faq" aria-labelledby="zn-faq-h"><h2 id="zn-faq-h">Preguntas frecuentes sobre esta página</h2>
        ${FAQ.map(([q, a]) => html`<details class="more"><summary>${q}</summary><p>${a}</p></details>`)}</section>`;
  },
  async after(load) {
    const root = $('#zn-root');
    root.innerHTML = String(html`<div class="skeleton"></div><p class="muted">Cargando el catálogo histórico…</p>`);
    let D;
    try { D = await loadAll(); } catch (e) {
      console.error(e);
      root.innerHTML = String(html`<div class="notice notice-warn">${raw(ICON.triangle)}<p>No se pudo cargar el catálogo histórico. Puede descargarlo directamente: <a href="assets/historico/eventos.zip" download>CSV (en un ZIP)</a>.</p></div>`);
      return;
    }
    const [feed, K, S] = await Promise.all([load('feed.json').catch(() => null), blocks(), scenario()]);
    if (!root.isConnected) return;
    const labels = placeLabels(D.sum.nombres);
    const byCode = new Map([...labels].map(([l, c]) => [c, l]));
    $('#zn-list').innerHTML = [...labels.keys()].map((l) => `<option value="${esc(l)}"></option>`).join('');
    const q = $('#zn-q'), msg = $('#zn-msg'), near = $('#zn-near'), geoBtn = $('#zn-geo');
    const names = D.sum.nombres;
    const sel = { dep: $('#zn-dep'), prov: $('#zn-prov'), dist: $('#zn-dist') };
    const ALL = { dep: 'Elija…', prov: 'Todo el departamento', dist: 'Toda la provincia' };
    const fill = (el, key, parent, value) => {
      const list = key === 'dep' || parent ? childrenOf(names, parent) : [];
      el.innerHTML = `<option value="">${ALL[key]}</option>` + list.map(([c, n]) => `<option value="${esc(c)}">${esc(n)}</option>`).join('');
      el.disabled = !list.length;
      el.value = list.some(([c]) => c === value) ? value : '';
    };
    /** Las tres listas siguen al lugar elegido, venga del buscador, de un enlace o de la ubicación. */
    const syncPick = (area) => {
      fill(sel.dep, 'dep', '', area.slice(0, 2));
      fill(sel.prov, 'prov', sel.dep.value, area.length >= 4 ? area.slice(0, 4) : '');
      fill(sel.dist, 'dist', sel.prov.value, area.length === 6 ? area : '');
    };
    const go = (code) => { if (code) location.hash = `#/zona?area=${code}`; };
    // «Elija…» quita el lugar de la ruta, no solo de las listas: así volver a elegir el mismo departamento cambia la
    // ruta y la página se arma de nuevo.
    sel.dep.addEventListener('change', () => { location.hash = sel.dep.value ? `#/zona?area=${sel.dep.value}` : '#/zona'; });
    sel.prov.addEventListener('change', () => go(sel.prov.value || sel.dep.value));
    sel.dist.addEventListener('change', () => go(sel.dist.value || sel.prov.value));
    const show = () => {
      const area = readArea();
      if (!area || !byCode.has(area)) {
        root.innerHTML = '';
        syncPick('');
        msg.textContent = area ? 'Ese código no existe en el catálogo.' : '';
        return;
      }
      q.value = byCode.get(area);
      syncPick(area);
      msg.textContent = `${placeName(names, area)} · ${LEVEL[area.length]}`;
      root.innerHTML = String(report(D, feed, area, Date.now(), K, S));
      $('#zn-csv', root)?.addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        if (btn.disabled) return;
        btn.disabled = true;
        // El mismo archivo que la tabla de la Memoria con este lugar elegido, del más reciente al más antiguo.
        const recs = [...D.recs.filter((r) => r.u.startsWith(area))].sort((a, b) => (b.d < a.d ? -1 : b.d > a.d ? 1 : b.i - a.i));
        try {
          await downloadTeamCsv(D, recs, `mi-zona-${area}.csv`, $('#zn-csv-st', root), () => btn.isConnected);
        } finally {
          btn.disabled = false;
        }
      });
    };
    q.addEventListener('change', () => {
      const code = labels.get(q.value.trim());
      if (code) location.hash = `#/zona?area=${code}`;
      else msg.textContent = q.value.trim() ? 'Elija un lugar de la lista.' : '';
    });
    // Ubicación: solo si el navegador la ofrece. La posición se usa aquí y se descarta; nunca se envía ni se guarda.
    if (navigator.geolocation) {
      geoBtn.hidden = false;
      const GEO_ERR = { 1: 'No dio permiso para usar su ubicación. Puede escribir el nombre o elegirlo en las listas.', 2: 'Su dispositivo no pudo determinar la ubicación. Escriba el nombre o elíjalo en las listas.', 3: 'La ubicación tardó demasiado. Inténtelo de nuevo o escriba el nombre.' };
      geoBtn.addEventListener('click', () => {
        if (geoBtn.disabled) return;
        geoBtn.disabled = true;
        near.innerHTML = '';
        msg.textContent = 'Buscando su ubicación…';
        const done = () => { geoBtn.disabled = false; };
        navigator.geolocation.getCurrentPosition((pos) => {
          done();
          if (!near.isConnected) return;
          const list = nearestDistricts(D.peru, names, pos.coords.latitude, pos.coords.longitude);
          if (!list.length) { msg.textContent = 'Su ubicación no parece estar en el Perú. Escriba el nombre o elíjalo en las listas.'; return; }
          msg.textContent = '';
          near.innerHTML = String(html`<p><strong>Distritos más cercanos a su ubicación.</strong> Elija el suyo:</p>
            <div class="zn-near">${list.map((d) => html`<a class="btn ghost" href="#/zona?area=${d.code}">${placeName(names, d.code)} <span class="muted small">a ${F.fmtNumber(d.km, d.km < 10 ? 1 : 0)} km del centro</span></a>`)}</div>
            <p class="muted small">Se compara con el punto central de cada distrito, no con su límite: por eso se ofrecen varios. Su ubicación no salió de este dispositivo.</p>`);
        }, (err) => {
          done();
          if (msg.isConnected) msg.textContent = GEO_ERR[err?.code] || GEO_ERR[2];
        }, { enableHighAccuracy: false, timeout: 15000, maximumAge: 600000 });
      });
    }
    show();
  },
};
