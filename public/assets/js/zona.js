// Mi zona: para un lugar elegido (departamento, provincia o distrito), lo que pasó antes, lo que hay hoy y qué
// meses suelen ser los peores, en una sola página. Donde el CENEPRED evaluó manzanas ante El Niño 2026-2027, también
// lo que se espera.
//
// No calcula nada propio: la historia es la de Memoria de desastres (historico-model.js, el mismo cálculo que los
// CSV del equipo), los avisos son los de feed.json con el nivel que dio cada institución, y la fase del ENSO la
// de resumen.json. Lo pasado no es un pronóstico, y la página lo dice. El riesgo esperado es el nivel que el CENEPRED
// dio a cada manzana (assets/capas/manzanas-riesgo.json, la misma capa que la vista «Daños y pobreza» de la Memoria):
// aquí solo se cuentan. La página no da recomendaciones propias: enlaza a las oficiales.
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

/** Los departamentos donde la capa tiene manzanas, por nombre: para decir qué cubre cuando el lugar no está. */
export function riskCoverage(K, names) {
  return [...new Set((K?.blocks || []).map((b) => String(b[2]).slice(0, 2)))].map((c) => names.departamento[c]).filter(Boolean).sort(collator.compare);
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

function riskCard(K, names, area) {
  const head = html`<h2 id="zn-rie">Riesgo esperado ante El Niño 2026-2027</h2>`;
  if (!K?.blocks?.length) return html`<section class="card" aria-labelledby="zn-rie">${head}<p class="muted">No se pudo cargar la evaluación del CENEPRED. Vuelva a intentarlo más tarde.</p>${OFFICIAL}</section>`;
  const r = expectedRisk(K, area);
  const cover = riskCoverage(K, names);
  if (!r) return html`<section class="card" aria-labelledby="zn-rie">${head}
    <p id="zn-rie-none">No tenemos el riesgo esperado de este lugar. De la evaluación del CENEPRED ante El Niño 2026-2027 publicamos solo las manzanas de algunas zonas de ${joinEs(cover)}. <strong>Eso no quiere decir que aquí no haya riesgo.</strong></p>${OFFICIAL}</section>`;
  const worst = r.by[r.worst];
  return html`<section class="card" aria-labelledby="zn-rie">${head}
    <p id="zn-rie-sum">${r.high.n
    ? html`<strong>${F.fmtNumber(r.high.pob)} personas</strong> y ${F.fmtNumber(r.high.viv)} viviendas están en las ${F.fmtNumber(r.high.n)} manzanas que el CENEPRED calificó en riesgo alto o muy alto (censo 2017).`
    : html`Ninguna de las manzanas que el CENEPRED evaluó aquí está en riesgo alto o muy alto.`}
      Nivel más alto entre las ${F.fmtNumber(r.n)} manzanas evaluadas: <span class="lvl ${RISK_CLS[r.worst] || ''}">${worst.name}</span></p>
    <div class="table-wrap"><table class="data zn-risk"><caption class="visually-hidden">Manzanas evaluadas por el CENEPRED, por nivel de riesgo</caption>
      <thead><tr><th scope="col">Nivel de riesgo</th><th scope="col">Manzanas</th><th scope="col">Personas</th><th scope="col">Viviendas</th></tr></thead>
      <tbody>${r.by.map((x, i) => html`<tr><th scope="row"><span class="lvl ${RISK_CLS[i] || ''}">${x.name}</span></th><td>${F.fmtNumber(x.n)}</td><td>${F.fmtNumber(x.pob)}</td><td>${F.fmtNumber(x.viv)}</td></tr>`)}</tbody></table></div>
    ${r.places.length ? html`<p>Centros poblados con más personas en riesgo alto o muy alto: ${r.places.map(([n, v], i) => html`${i ? '; ' : ''}${n} (${F.fmtNumber(v)})`)}.</p>` : ''}
    <p class="muted small">El CENEPRED evaluó solo algunas zonas${area.length === 6 ? ' de este distrito' : ` (${F.fmtNumber(r.distritos)} ${r.distritos === 1 ? 'distrito' : 'distritos'} de este lugar)`}: una manzana que no aparece aquí no está libre de riesgo. Fuente: CENEPRED, SIGRID, escenario de riesgo ante El Niño 2026-2027; personas y viviendas por manzana del censo 2017 (INEI), no de hoy. <a href="#/memoria?area=${area}">Ver las manzanas en el mapa de la Memoria</a> (vista «Daños y pobreza»).</p>${OFFICIAL}</section>`;
}

/** Preguntas que la página debe responder sin que nadie la explique: qué es, de cuándo es y qué no dice. */
export const FAQ = [
  ['¿Esto es una alerta?', 'No. El observatorio no emite alertas ni recomendaciones de emergencia. Los avisos de la sección «Hoy» son los que publican el SENAMHI, el INDECI y otras instituciones, con el nivel que dio cada una y un enlace al original.'],
  ['¿De cuándo son los datos?', 'Cada bloque tiene su fecha. La frecuencia de daños usa las temporadas 1970-71 a 2014-15 de DesInventar; los registros llegan hasta el último que figura arriba. Los avisos son los vigentes al abrir la página. El riesgo esperado es el del escenario del CENEPRED ante El Niño 2026-2027, con personas y viviendas del censo 2017.'],
  ['¿Por qué mi lugar no tiene «riesgo esperado»?', 'Porque de esa evaluación del CENEPRED solo publicamos las manzanas de algunas zonas de la costa norte. Que un lugar no aparezca no quiere decir que no tenga riesgo: quiere decir que aquí no tenemos ese dato.'],
  ['¿Qué cuenta como persona o vivienda en riesgo?', 'Las personas y las viviendas que el censo de 2017 contó en cada manzana que el CENEPRED calificó. No es un conteo de hoy, ni de daños: es cuánta gente vivía donde el escenario espera riesgo.'],
  ['¿Un nivel bajo, o pocos registros, quiere decir que es seguro?', 'No. El nivel es de la manzana evaluada, y la historia cuenta solo lo que alguien registró. Una quebrada, una ladera o la ribera de un río pueden ser peligrosas en un lugar con pocos registros.'],
  ['¿Qué pasa con mi ubicación si uso «Usar mi ubicación»?', 'Se usa en su dispositivo para buscar los distritos más cercanos y se descarta. No se envía a ningún servidor ni se guarda.'],
  ['¿Qué debo hacer ante una emergencia?', 'Siga las indicaciones del INDECI, del SENAMHI y de su municipalidad. Esta página ayuda a entender el lugar; no reemplaza a esas instituciones.'],
];

function report(D, feed, area, now, K) {
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
    ${riskCard(K, names, area)}
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
      <p>Elija un departamento, una provincia o un distrito. Verá cuántas veces hubo daños, qué meses suelen ser los peores, cuánto cambia con El Niño, los avisos oficiales de hoy y, donde el CENEPRED lo evaluó, el riesgo esperado.</p></div>
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
    const [feed, K] = await Promise.all([load('feed.json').catch(() => null), blocks()]);
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
    sel.dep.addEventListener('change', () => (sel.dep.value ? go(sel.dep.value) : syncPick('')));
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
      root.innerHTML = String(report(D, feed, area, Date.now(), K));
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
