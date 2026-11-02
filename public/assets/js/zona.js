// Mi zona: para un lugar elegido (departamento, provincia o distrito), lo que pasó antes, lo que hay hoy y qué
// meses suelen ser los peores, en una sola página.
//
// No calcula nada propio: la historia es la de Memoria de desastres (historico-model.js, el mismo cálculo que los
// CSV del equipo), los avisos son los de feed.json con el nivel que dio cada institución, y la fase del ENSO la
// de resumen.json. Lo pasado no es un pronóstico, y la página lo dice.

import { html, raw, esc, safeUrl, $, $$ } from './lib/dom.js';
import * as F from './lib/format.js';
import { ICON } from './icons.js';
import * as M from './historico-model.js';
import { loadAll } from './historico.js';

const CODE_RE = /^\d{2}(\d{2}){0,2}$/;
const LEVEL = { 2: 'departamento', 4: 'provincia', 6: 'distrito' };
const DAY = 864e5;

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

/** CSV de los registros del lugar (columnas de equipo, con el código como texto). El catálogo completo, con todas
 * las columnas, está en eventos.zip. */
export function toCsv(recs, names) {
  const head = ['Date', 'DangerType', 'Departamento', 'Provincia', 'Distrito', 'Ubigeo', 'TipoEvento', 'FaseENSO', 'Origen', 'Confianza', 'Fallecidos', 'Afectados', 'ViviendasAfectadas'];
  const q = (v) => { const s = v === null || v === undefined ? '' : String(v); return /^[=+\-@\t\r]/.test(s) ? `'${s}` : /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const rows = [...recs].sort((a, b) => (a.d < b.d ? 1 : -1)).map((r) => [
    r.d, r.t, names.departamento[r.u.slice(0, 2)] || '', names.provincia[r.u.slice(0, 4)] || '', names.distrito[r.u] || '', r.u,
    r.e, r.f, r.o, r.c, r.muertos || '', r.afect || '', r.viv || ''].map(q).join(','));
  return `﻿${head.join(',')}\n${rows.join('\n')}\n`;
}

function readArea() {
  const a = new URLSearchParams(location.hash.split('?')[1] || '').get('area') || '';
  return CODE_RE.test(a) ? a : '';
}

function alertsCard(items, now) {
  const live = items.filter((a) => a.valid?.until ? new Date(a.valid.until).getTime() >= now - DAY : (now - new Date(a.date).getTime()) < 3 * DAY);
  if (!live.length) return html`<p class="muted">Ninguna fuente oficial tiene un aviso vigente que toque este lugar en los últimos días. Eso no quiere decir que no haya peligro: revise también el departamento y las <a href="#/noticias">noticias</a>.</p>`;
  return html`<ul class="link-list">${live.slice(0, 8).map((a) => html`<li>
    <strong>${a.institution}</strong>${a.severity ? html` · <span class="lvl lvl-r${a.severity.rank}" title="${a.severity.scaleLabel}">${a.severity.label}</span>` : html` · <span class="muted">sin nivel</span>`}
    — <a href="${safeUrl(a.url)}" rel="noopener" target="_blank">${a.title}</a> <span class="muted small">${F.fmtDate(a.date)}</span></li>`)}</ul>
    ${live.length > 8 ? html`<p class="muted small">Y ${live.length - 8} más en <a href="#/noticias">Noticias</a>.</p>` : ''}`;
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

function report(D, feed, area, now) {
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
    <section class="card" aria-labelledby="zn-est"><h2 id="zn-est">Qué meses suelen ser los peores</h2>${seasonTable(seasonality(recs))}</section>
    <section class="card" aria-labelledby="zn-des"><h2 id="zn-des">Seguir</h2>
      <ul class="link-list">
        <li><a href="#/memoria?area=${area}">Ficha completa en Memoria de desastres</a> (mapa, ríos, cuencas, declaratorias)</li>
        <li><button type="button" id="zn-csv" class="btn">Descargar los ${F.fmtNumber(recs.length)} registros de este lugar (CSV)</button> <span class="muted small">Con las columnas del equipo de prevención. El catálogo completo está en <a href="assets/historico/eventos.zip" download>eventos.zip</a>.</span></li>
      </ul></section>
    <p class="muted small">Esto es la historia del catálogo, no un pronóstico: dice con qué frecuencia pasó, no cuándo volverá a pasar. Los avisos de arriba son los que emiten las instituciones.</p>`;
}

export const zonaView = {
  title: 'Mi zona',
  render() {
    return html`<div class="page-head"><div class="eyebrow">Mi zona</div><h1>¿Qué pasó antes en mi lugar, y qué hay hoy?</h1>
      <p>Elija un departamento, una provincia o un distrito. Verá cuántas veces hubo daños, qué meses suelen ser los peores, cuánto cambia con El Niño y los avisos oficiales de hoy.</p></div>
      <div class="card"><label for="zn-q"><strong>Lugar</strong></label>
        <input id="zn-q" class="input" type="search" list="zn-list" autocomplete="off" placeholder="Escriba un nombre, por ejemplo Chosica" style="width:100%;max-width:520px">
        <datalist id="zn-list"></datalist><p id="zn-msg" class="muted small" role="status"></p></div>
      <div id="zn-root" data-tour-id="zona" aria-live="polite"></div>`;
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
    const feed = await load('feed.json').catch(() => null);
    const labels = placeLabels(D.sum.nombres);
    const byCode = new Map([...labels].map(([l, c]) => [c, l]));
    $('#zn-list').innerHTML = [...labels.keys()].map((l) => `<option value="${esc(l)}"></option>`).join('');
    const q = $('#zn-q'), msg = $('#zn-msg');
    const show = () => {
      const area = readArea();
      if (!area || !byCode.has(area)) {
        root.innerHTML = '';
        msg.textContent = area ? 'Ese código no existe en el catálogo.' : '';
        return;
      }
      q.value = byCode.get(area);
      msg.textContent = `${placeName(D.sum.nombres, area)} · ${LEVEL[area.length]}`;
      root.innerHTML = String(report(D, feed, area, Date.now()));
      $('#zn-csv', root)?.addEventListener('click', () => {
        const recs = D.recs.filter((r) => r.u.startsWith(area));
        const a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob([toCsv(recs, D.sum.nombres)], { type: 'text/csv;charset=utf-8' }));
        a.download = `mi-zona-${area}.csv`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 1000);
      });
    };
    q.addEventListener('change', () => {
      const code = labels.get(q.value.trim());
      if (code) location.hash = `#/zona?area=${code}`;
      else msg.textContent = q.value.trim() ? 'Elija un lugar de la lista.' : '';
    });
    show();
  },
};
