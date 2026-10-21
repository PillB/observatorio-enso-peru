// Observatorio ENSO Perú — aplicación estática.
//
// Toda la información proviene de la publicación de datos en data/ que
// genera el pipeline diario (python -m enso.observatory). El navegador no
// calcula señales ni clasifica valores: solo los presenta. Si los archivos
// de una publicación no coinciden entre sí (publicationId distinto), se
// muestra un aviso y no se mezclan.

import { html, raw, esc, safeUrl, $, $$, storage } from './lib/dom.js';
import * as F from './lib/format.js';
import { timeChart, toXY, sparkline, dataTable } from './lib/charts.js';
import { SITE, DISCLAIMER, OFFICIAL_LINKS, PERU_IMPACTS, PAST_IMPACTS, GLOSSARY } from './content.js';
import { mapView } from './map.js';
import { Tour } from './tour.js';
import { assistantView } from './assistant.js';
import { ICON } from './icons.js';

const DATA = 'data/';
export const S = { dash: null, files: {}, pub: null, mismatch: [] };

// ---------------------------------------------------------------------------
// Datos
// ---------------------------------------------------------------------------
async function fetchJSON(name, bust) {
  const r = await fetch(`${DATA}${name}?v=${encodeURIComponent(bust)}`, { cache: 'no-cache' });
  if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
  return r.json();
}

/** Archivo de la misma publicación que dashboard.json, o null si no coincide. */
export async function load(name) {
  if (S.files[name] !== undefined) return S.files[name];
  let obj = null;
  try {
    obj = await fetchJSON(name, S.pub);
    if (obj.publicationId !== S.pub) obj = await fetchJSON(name, `${S.pub}-${Date.now()}`);
    if (obj.publicationId !== S.pub) {
      S.mismatch.push(name);
      renderBanner();
      obj = null;
    }
  } catch (e) {
    console.warn(e);
    obj = null;
  }
  S.files[name] = obj;
  return obj;
}

const series = (k) => S.dash?.series?.[k] || null;
const latest = (k) => series(k)?.latest || null;

async function fullSeries(k) {
  const all = await load('series.json');
  return all?.series?.[k] || null;
}

// ---------------------------------------------------------------------------
// Componentes
// ---------------------------------------------------------------------------
const LEVEL_TXT = { ok: 'Normal', watch: 'Amarilla', alert: 'Roja', unclassified: 'Sin clasificación', na: 'No disponible' };
const LEVEL_ICON = { ok: 'check', watch: 'triangle', alert: 'octagon', unclassified: 'dash', na: 'clock' };

function chip(level, text) {
  const lv = ['ok', 'watch', 'alert'].includes(level) ? level : 'na';
  return html`<span class="chip chip-${lv}">${raw(ICON[LEVEL_ICON[level] || 'dash'])}<span>${text || LEVEL_TXT[level] || level}</span></span>`;
}

function toneChip(tone, text) {
  if (!text) return '';
  const t = tone === 'warm' ? 'warm' : tone === 'cool' ? 'cool' : 'na';
  return html`<span class="chip chip-${t}">${text}</span>`;
}

function periodText(s, period) {
  if (!period) return '—';
  return s?.periodKind === 'season' ? F.fmtSeason(period) : F.fmtMonth(period);
}

/** Tarjeta de indicador. Un dato vencido no se muestra como actual. */
function metricCard(k, { title, scope, note, href } = {}) {
  const s = series(k);
  if (!s) return html`<div class="card metric"><div class="metric-name">${title || k}</div><p class="metric-value na">Dato actual no disponible</p><p class="metric-desc">La fuente no está disponible en esta publicación.</p></div>`;
  const l = s.latest;
  const spark = S.dash.spark?.[k] || [];
  const cat = l.category;
  const tone = cat?.tone || (l.value > 0 ? 'warm' : l.value < 0 ? 'cool' : 'neutral');
  const value = l.stale
    ? html`<p class="metric-value na">Dato actual no disponible</p><p class="metric-desc">El último dato válido corresponde a ${periodText(s, l.period)} (${F.fmtValue(l.value, s.units)}). No se utiliza para representar la condición actual.</p>`
    : html`<div class="metric-row"><p class="metric-value ${tone}">${F.fmtValue(l.value, s.units)}</p>${raw(sparkline(spark, { tone: 'auto' }))}</div>`;
  const delta = !l.stale && l.previous ? html`<span class="delta">${l.previous.change > 0 ? '▲' : l.previous.change < 0 ? '▼' : '='} ${F.fmtValue(l.previous.change, s.units)} frente a ${periodText(s, l.previous.period)}</span>` : '';
  const tag = href ? 'a' : 'div';
  return html`<${raw(tag)} class="card metric" ${raw(href ? `href="${esc(href)}"` : '')}>
    <div class="metric-top"><div><div class="metric-name">${title || s.label}</div><div class="metric-scope">${scope || ''}</div></div>${cat?.label && !l.stale ? toneChip(cat.tone, cat.short || cat.label) : ''}</div>
    ${value}
    <div class="metric-period">${l.stale ? '' : html`Periodo: <strong>${periodText(s, l.period)}</strong> · `}${s.frequency}${l.carried ? ' · último dato válido conservado' : ''}</div>
    ${delta}
    ${note ? html`<p class="metric-desc">${note}</p>` : ''}
  </${raw(tag)}>`;
}

function statusCard(kind) {
  const o = S.dash.official?.[kind];
  const who = kind === 'enfen' ? 'ENFEN · El Niño Costero (Perú)' : 'NOAA · ENSO de escala cuenca';
  if (!o || !o.status) {
    return html`<article class="status-card" aria-labelledby="st-${kind}"><div class="who">${who}</div>
      <p class="status" id="st-${kind}">Dato actual no disponible</p>
      <p class="status-sub">No se pudo leer el último comunicado en esta publicación. Consulte la fuente oficial.</p>
      <div class="meta"><a href="${safeUrl(o?.url || (kind === 'enfen' ? 'https://enfen.imarpe.gob.pe/comunicados/' : 'https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml'))}" rel="noopener" target="_blank">Ir a la fuente oficial</a></div></article>`;
  }
  const status = kind === 'enfen' ? o.status : o.statusEs;
  const stale = o.stale;
  const lvl = stale ? 'na' : o.level;
  const sub = kind === 'enfen'
    ? html`Comunicado oficial N° ${o.number}${o.issued ? html` · ${F.fmtDate(o.issued)}` : ''}`
    : html`${o.status}${o.issued ? html` · ${F.fmtDate(o.issued)}` : ''}`;
  return html`<article class="status-card lvl-${lvl}" aria-labelledby="st-${kind}">
    <div class="who">${who}</div>
    ${stale
      ? html`<p class="status" id="st-${kind}">Dato actual no disponible</p><p class="status-sub">El último estado leído fue «${status}» (${sub}). ${o.newerListed ? `Existe un comunicado más reciente (N° ${o.newerListed}) que aún no se pudo leer.` : 'Ya debió publicarse un comunicado más reciente.'}</p>`
      : html`<p class="status" id="st-${kind}">${raw(ICON[LEVEL_ICON[lvl]] || '')} ${status}</p><p class="status-sub">${sub}</p>`}
    <div class="meta">
      ${o.nextIssue ? html`<span>Próximo: <strong>${F.fmtDate(o.nextIssue)}</strong>${o.nextIssueEstimated ? ' (estimado)' : ''}</span>` : ''}
      ${o.channel === 'archive' || o.channel === 'archive-fresh' ? html`<span class="tag">vía copia del Internet Archive</span>` : ''}
      ${o.channel === 'relay-peru' ? html`<span class="tag">vía recolector en el Perú</span>` : ''}
      ${o.carried ? html`<span class="tag">último dato válido</span>` : ''}
      <a href="${safeUrl(o.documentUrl || o.url)}" rel="noopener" target="_blank">Documento oficial</a>
      ${archiveHref(o.archive) ? html`<a href="${archiveHref(o.archive)}" rel="noopener" target="_blank" title="Copia que bajó el observatorio${o.retrievedAt ? ` el ${F.fmtDateTime(o.retrievedAt)}` : ''}">Copia archivada</a>` : ''}
    </div>
  </article>`;
}

function phaseNow() {
  const e = S.dash.official?.enfen;
  if (e && !e.stale) {
    if (/nino/.test(e.statusCode || '')) return 'warm';
    if (/nina/.test(e.statusCode || '')) return 'cool';
  }
  const ic = latest('icen');
  if (ic && !ic.stale && ic.category) return ic.category.tone === 'warm' ? 'warm' : ic.category.tone === 'cool' ? 'cool' : 'neutral';
  return null;
}

function grdPanel() {
  const g = S.dash.grd;
  if (!g) return '';
  const rows = g.signals.map((x) => html`<tr>
    <th scope="row"><div>${x.name}</div><div class="muted small">${x.region}</div></th>
    <td>${chip(x.level, x.label)}</td>
    <td class="num" data-label="Valor">${x.value === null || x.value === undefined || x.stale ? 'N/D' : x.direction ? html`${x.direction}<div class="muted small">${F.fmtValue(x.value, x.units)}</div>` : F.fmtValue(x.value, x.units)}</td>
    <td data-label="Periodo">${x.period ? F.fmtMonth(x.period) : '—'}<div class="muted small">${sourceName(x.source)}</div></td>
    <td class="small">${x.basis}${x.reason ? html`<div class="muted">${x.reason}</div>` : ''}</td>
  </tr>`);
  return html`<section class="card" data-tour-id="grd" aria-labelledby="grd-h">
    <div class="section-head"><h2 id="grd-h">Señal operativa del equipo GRD</h2><span class="tag">Política ${g.policy_id} · ${g.approval_status === 'DRAFT' ? 'borrador' : g.approval_status}</span></div>
    <p class="notice notice-info">${raw(ICON.info)}<span>${g.disclaimer}</span></p>
    <div class="table-wrap"><table class="grd"><thead><tr><th scope="col">Indicador</th><th scope="col">Señal</th><th scope="col">Valor</th><th scope="col">Periodo y fuente</th><th scope="col">Umbrales de la tabla GRD</th></tr></thead><tbody>${rows}</tbody></table></div>
  </section>`;
}

function sourceName(id) {
  const m = { 'cpc-sstoi': 'NOAA OISST mensual', 'psl-ersst6-nino12': 'NOAA ERSSTv6', 'psl-ersst6-nino34': 'NOAA ERSSTv6', 'cpc-epac850': 'NOAA/CPC 850 hPa', 'cpc-cpac850': 'NOAA/CPC 850 hPa', 'cpc-tahiti': 'Calculado con NOAA/CPC', 'igp-icen': 'ENFEN / IGP', 'cpc-roni': 'NOAA/CPC', 'cpc-wksst': 'NOAA OISST semanal' };
  return m[id] || id || '';
}

function freshestStrip() {
  const w = S.dash.weekly;
  if (!w) return '';
  const names = { nino12: 'Niño 1+2 (costa)', nino3: 'Niño 3', nino34: 'Niño 3.4 (centro)', nino4: 'Niño 4' };
  const items = Object.entries(names).filter(([k]) => w[k]).map(([k, n]) => {
    const l = w[k].latest;
    const stale = l.ageDays > 16;
    const tone = l.anom > 0.5 ? 'warm' : l.anom < -0.5 ? 'cool' : 'neutral';
    return html`<div class="fresh-item"><div class="fresh-name">${n}</div>
      ${stale ? html`<div class="metric-value na">N/D</div>` : html`<div class="fresh-val ${tone}">${F.fmtValue(l.anom, 'degC')}</div>`}
      ${raw(sparkline(w[k].recent, { width: 96, height: 26 }))}</div>`;
  });
  const d = w.nino12?.latest?.date;
  return html`<section class="card fresh" data-tour-id="freshest" aria-labelledby="fresh-h">
    <div class="section-head"><h2 id="fresh-h">Lo más reciente: temperatura del mar semanal</h2>
    <span class="muted small">Semana centrada en el ${F.fmtDate(d)} · NOAA OISST v2.1 · ${F.relativeDays(F.daysBetween(d))}</span></div>
    <div class="fresh-grid">${items}</div>
    <p class="muted small">Anomalía frente a 1991–2020. Es una observación semanal: no equivale al ICEN ni a una declaración oficial.</p>
  </section>`;
}

function rangeSeg(id, ranges, current) {
  return html`<div class="seg" role="group" aria-label="Periodo del gráfico">${ranges.map(([k, l]) => html`<button type="button" data-range="${k}" data-for="${id}" aria-pressed="${String(k === current)}">${l}</button>`)}</div>`;
}

const RANGES = [['2', '2 años'], ['5', '5 años'], ['15', '15 años'], ['all', 'Todo']];

/** Gráfico de una o varias series con selector de periodo. */
async function mountChart(el, spec, { range = '5', weeklyKeys } = {}) {
  if (!el) return;
  const loaded = [];
  for (const s of spec.series) {
    let pts;
    if (s.weekly) {
      const wk = await load('weekly.json');
      pts = wk?.regions?.[s.weekly]?.points?.map((p) => ({ period: p.date, value: p.value })) || [];
    } else {
      const fs = await fullSeries(s.key);
      pts = fs?.points || [];
    }
    loaded.push({ ...s, all: toXY(pts, 'period') });
  }
  const box = el.querySelector('.chart-box') || el;
  chartSources(el, spec.series);
  const draw = (r) => {
    const cut = r === 'all' ? -Infinity : Date.now() - Number(r) * 365.25 * 864e5;
    timeChart(box, { ...spec, series: loaded.map((s) => ({ ...s, points: s.all.filter((p) => p.t >= cut) })) });
  };
  draw(range);
  el.querySelectorAll('[data-range]').forEach((b) => b.addEventListener('click', () => {
    el.querySelectorAll('[data-range]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    draw(b.dataset.range);
  }));
  const tbl = el.querySelector('.chart-table');
  if (tbl) {
    const det = tbl.closest('details');
    det?.addEventListener('toggle', () => {
      if (det.open && !tbl.dataset.done) {
        tbl.innerHTML = dataTable(loaded.map((s) => ({ label: s.label, points: s.all })), spec.units, { n: 36, periodLabel: spec.periodLabel });
        tbl.dataset.done = '1';
      }
    });
  }
}

function chartCard(id, { title, desc, foot, tour, range = '5' }) {
  return html`<section class="card" id="${id}" ${raw(tour ? `data-tour-id="${esc(tour)}"` : '')} aria-labelledby="${id}-h">
    <div class="section-head"><h2 id="${id}-h">${title}</h2>${rangeSeg(id, RANGES, range)}</div>
    ${desc ? html`<p class="muted">${desc}</p>` : ''}
    <div class="chart-box"><div class="skeleton"></div></div>
    <details class="more"><summary>Ver los valores en una tabla</summary><div class="chart-table"></div></details>
    ${foot ? html`<div class="card-foot">${foot}</div>` : ''}
  </section>`;
}

const seasonLabel = (s) => F.fmtSeason(s);
const monthLabel = (s) => (/^\d{4}-\d{2}-\d{2}/.test(s) ? F.fmtDateShort(s) : F.fmtMonth(s));

function sourceFoot(keys) {
  const out = keys.map((k) => series(k)).filter(Boolean).map((s) => `${s.label}: ${s.description.split('.')[0]}. Base ${s.climatology || '—'}.`);
  return out.join(' ');
}

// Cada dato y cada noticia enlaza a su origen en vivo y a la copia que bajó
// el observatorio, servida por este mismo sitio (data/archive/…).
const ARCHIVE_RE = /^archive\/[\w.\/-]+(?:#[\w-]+)?$/;
const archiveHref = (p) => (p && ARCHIVE_RE.test(p) ? DATA + p : '');

function sourceLinks(live, arch, { liveLabel = 'Fuente en vivo', archLabel = 'Copia archivada', when, prefix, snapshot } = {}) {
  const a = archiveHref(arch);
  const snap = archiveHref(snapshot);
  const parts = [
    live ? html`<a href="${safeUrl(live)}" rel="noopener" target="_blank">${liveLabel}</a>` : '',
    a ? html`<a href="${a}" target="_blank" rel="noopener" title="${when ? `Copia bajada el ${F.fmtDateTime(when)}` : 'Copia que bajó el observatorio'}">${archLabel}</a>` : '',
    snap ? html`<a href="${snap}" target="_blank" rel="noopener" title="La respuesta de la fuente tal como la bajó el observatorio hoy">Respuesta original bajada</a>` : '',
  ].filter(Boolean);
  if (!parts.length) return '';
  return html`<p class="src-links">${prefix ? html`<span>${prefix}:</span> ` : ''}${parts.map((x, i) => html`${i ? ' · ' : ''}${x}`)}</p>`;
}

function chartSources(el, specSeries) {
  const ids = [...new Set(specSeries.map((s) => (s.weekly ? 'cpc-wksst' : series(s.key)?.source)).filter(Boolean))];
  const rows = ids.map((id) => [id, S.dash.sources?.[id]]).filter(([, m]) => m && (m.live || m.archive));
  if (!rows.length || el.querySelector('.src-links')) return;
  el.insertAdjacentHTML('beforeend', String(html`<div class="card-foot card-src">${rows.map(([, m]) => sourceLinks(m.live, m.archive, { when: m.retrievedAt, prefix: `${m.institution} · ${m.product}` }))}</div>`));
}

// ---------------------------------------------------------------------------
// Vistas
// ---------------------------------------------------------------------------
const VIEWS = {};

VIEWS[''] = {
  title: 'Resumen',
  render() {
    const ph = phaseNow();
    const impacts = PERU_IMPACTS[ph || 'neutral'];
    return html`
      <div class="page-head"><div class="eyebrow">Resumen</div><h1>¿Cómo está El Niño hoy?</h1>
        <p>Estados oficiales, mediciones más recientes y la señal operativa del equipo GRD, actualizados cada día con fuentes públicas.</p></div>
      <div class="hero" data-tour-id="official-status">${statusCard('enfen')}${statusCard('noaa')}</div>
      ${freshestStrip()}
      <section aria-labelledby="ind-h" data-tour-id="indicators">
        <div class="section-head"><h2 id="ind-h">Indicadores clave</h2><a href="#/oceano">Ver todos</a></div>
        <div class="grid g4">
          ${metricCard('icen', { title: 'ICEN oficial', scope: 'Costa norte del Perú · ENFEN', href: '#/costero' })}
          ${metricCard('nino12_oisst', { title: 'Niño 1+2 mensual', scope: 'Costa de Ecuador y Perú · NOAA OISST', href: '#/costero' })}
          ${metricCard('roni', { title: 'RONI', scope: 'Pacífico central · índice oficial de NOAA', href: '#/pacifico' })}
          ${metricCard('nino34_oisst', { title: 'Niño 3.4 mensual', scope: 'Pacífico central · NOAA OISST', href: '#/pacifico' })}
          ${metricCard('cpac850_anom', { title: 'Vientos alisios', scope: 'Pacífico central, 850 hPa · anomalía', href: '#/oceano', note: 'Negativo: alisios debilitados o viento del oeste.' })}
          ${metricCard('heat_180w100w', { title: 'Calor bajo la superficie', scope: '0–300 m, 180°–100°O · NOAA GODAS', href: '#/oceano' })}
          ${metricCard('soi_troup', { title: 'SOI', scope: 'Tahití − Darwin · escala Troup', href: '#/oceano', note: 'Negativo sostenido: favorece El Niño.' })}
          ${metricCard('epac850_anom', { title: 'Alisios hacia la costa', scope: 'Pacífico oriental, 850 hPa · anomalía', href: '#/oceano', note: 'Negativo: alisios debilitados o viento del oeste.' })}
        </div>
      </section>
      <section class="card explainer" aria-labelledby="peru-h">
        <h2 id="peru-h">¿Qué significa para el Perú?</h2>
        ${ph ? '' : html`<p class="muted">No hay un estado actual verificado; se muestran efectos generales.</p>`}
        <ul>${impacts.map((t) => html`<li>${t}</li>`)}</ul>
        <p class="muted small">${PERU_IMPACTS.source} Los efectos varían en cada evento; no son un pronóstico.</p>
      </section>
      ${grdPanel()}
      <section class="card" aria-labelledby="links-h"><h2 id="links-h">Fuentes oficiales para tomar decisiones</h2>
        <ul class="link-list">${OFFICIAL_LINKS.map((l) => html`<li><a href="${safeUrl(l.url)}" rel="noopener" target="_blank">${l.name}</a><span class="muted"> — ${l.note}</span></li>`)}</ul>
      </section>`;
  },
};

VIEWS.costero = {
  title: 'El Niño Costero',
  render() {
    const e = S.dash.official?.enfen;
    const ev = (S.dash.events || []).filter((x) => x.ongoing)[0];
    const ic = latest('icen');
    const scale = [
      ['Fría fuerte', '< −1,3', 'cool'], ['Fría moderada', '−1,3 a < −1,1', 'cool'], ['Fría débil', '−1,1 a < −0,7', 'cool'],
      ['Neutra', '−0,7 a +0,5', 'neutral'], ['Cálida débil', '> +0,5 a +1,3', 'warm'], ['Cálida moderada', '> +1,3 a +2,1', 'warm'],
      ['Cálida fuerte', '> +2,1 a +3,5', 'warm'], ['Cálida extraordinaria', '> +3,5', 'warm'],
    ];
    const cur = ic && !ic.stale ? ic.category?.short : null;
    return html`
      <div class="page-head"><div class="eyebrow">Perú y Ecuador</div><h1>El Niño Costero</h1>
        <p>Calentamiento del mar frente a la costa norte del Perú (región Niño 1+2). Es el fenómeno que más afecta directamente al país, y puede ocurrir aunque el Pacífico central esté neutral.</p></div>
      <div class="grid g2">
        <div data-tour-id="coastal-status">${statusCard('enfen')}
          ${e?.summary ? html`<div class="card"><h3>Resumen del comunicado</h3><p>${e.summary}</p><p class="muted small">Texto del comunicado oficial N° ${e.number} de ENFEN.</p></div>` : ''}
        </div>
        <div class="card">
          <h3>Evento en curso</h3>
          ${ev ? html`<p><strong>${ev.name}</strong> desde ${F.fmtMonth(ev.start)} (${ev.months} meses según el ICEN oficial). Máximo hasta ahora: ${F.fmtValue(ev.peak, 'degC')} en ${F.fmtMonth(ev.peakPeriod)}, magnitud <strong>${ev.magnitude}</strong>.</p>
              <p class="muted small">Identificado por el observatorio aplicando la definición operacional de ENFEN (Nota Técnica 01-2024) al ICEN oficial. La declaración oficial corresponde a ENFEN.</p>`
            : html`<p>El ICEN oficial no muestra un evento en curso (tres meses consecutivos en condición cálida o fría).</p>`}
          <dl class="kv">
            <dt>ICEN oficial</dt><dd>${ic ? (ic.stale ? 'Dato actual no disponible' : html`${F.fmtValue(ic.value, 'degC')} (${F.fmtMonth(ic.period)})`) : 'N/D'}</dd>
            <dt>Clasificación</dt><dd>${cur || '—'}</dd>
          </dl>
        </div>
      </div>
      ${chartCard('ch-icen', { title: 'ICEN oficial', tour: 'coastal-icen', range: '15', desc: 'Media móvil de tres meses centrada de la anomalía de Niño 1+2. Las bandas marcan las categorías de ENFEN.', foot: 'Fuente: ENFEN (archivo del IGP), base 1991–2020. El valor de un mes necesita el mes siguiente, por eso el ICEN va unos dos meses detrás.' })}
      <div class="grid g2">
        <section class="card" data-tour-id="coastal-scale" aria-labelledby="scale-h"><h2 id="scale-h">Categorías del ICEN</h2>
          <div class="scale" role="list">${scale.map(([n, r, t]) => html`<div role="listitem" class="scale-row ${n === cur ? 'current' : ''}"><span class="scale-dot dot-${t}"></span><span>${n}${n === cur ? html` <strong>· actual</strong>` : ''}</span><span class="mono">${r} °C</span></div>`)}</div>
          <p class="muted small">Nota Técnica ENFEN 01-2024 (vigente desde diciembre de 2024). Un evento requiere al menos tres meses consecutivos en condición cálida o fría; su magnitud es la máxima alcanzada.</p>
        </section>
        ${chartCard('ch-n12w', { title: 'Niño 1+2 semanal', tour: 'coastal-recent', range: '2', desc: 'Anomalía semanal (OISST v2.1). Llega cada lunes y anticipa la tendencia del ICEN, sin reemplazarlo.' })}
      </div>`;
  },
  async after() {
    const refs = [{ v: 0.5, label: '+0,5', tone: 'warm' }, { v: 1.3, label: '+1,3', tone: 'warm' }, { v: 2.1, label: '+2,1', tone: 'warm' }, { v: 3.5, label: '+3,5', tone: 'warm' }, { v: -0.7, label: '−0,7', tone: 'cool' }];
    await mountChart($('#ch-icen'), { title: 'ICEN', units: 'degC', refLines: refs, series: [{ key: 'icen', label: 'ICEN oficial' }], fill: true }, { range: '15' });
    await mountChart($('#ch-n12w'), { title: 'Niño 1+2 semanal', units: 'degC', series: [{ weekly: 'nino12', label: 'Niño 1+2 semanal' }], fill: true, periodLabel: monthLabel }, { range: '2' });
  },
};

VIEWS.pacifico = {
  title: 'Pacífico',
  render() {
    const n = S.dash.official?.noaa;
    return html`
      <div class="page-head"><div class="eyebrow">Escala cuenca</div><h1>ENSO en el Pacífico ecuatorial</h1>
        <p>El Niño y La Niña de escala cuenca se miden en el Pacífico central (región Niño 3.4). Influyen en el clima de todo el planeta y en las lluvias de los Andes.</p></div>
      <div class="grid g2">
        <div data-tour-id="basin-status">${statusCard('noaa')}</div>
        ${n?.synopsis ? html`<div class="card"><h3>Síntesis de NOAA</h3><blockquote lang="en">${n.synopsis}</blockquote><p class="muted small">Texto original de la discusión diagnóstica de NOAA/CPC del ${F.fmtDate(n.issued)} (en inglés).</p></div>` : ''}
      </div>
      ${chartCard('ch-roni', { title: 'RONI y ONI', tour: 'basin-roni', range: '15', desc: 'Trimestres móviles. Umbral de El Niño: +0,5 °C; de La Niña: −0,5 °C. Desde febrero de 2026 el RONI es el índice oficial de NOAA.', foot: 'Fuente: NOAA/CPC. RONI: Niño 3.4 menos el promedio tropical (20°N–20°S), reescalado; base 1991–2020. ONI: bases de 30 años actualizadas cada 5 años.' })}
      ${chartCard('ch-regions', { title: 'Regiones Niño (mensual)', tour: 'basin-regions', range: '5', desc: 'Anomalía mensual de TSM por región (NOAA OISST v2.1, base 1991–2020).' })}
      ${chartCard('ch-cvb', { title: 'Costa frente a cuenca', range: '5', desc: 'Niño 1+2 (costa) y Niño 3.4 (centro) con OISST mensual. Que la costa se caliente más que el centro es típico de El Niño Costero.' })}`;
  },
  async after() {
    await mountChart($('#ch-roni'), { title: 'RONI y ONI', units: 'degC', periodLabel: seasonLabel, refLines: [{ v: 0.5, label: '+0,5', tone: 'warm' }, { v: -0.5, label: '−0,5', tone: 'cool' }], series: [{ key: 'roni', label: 'RONI' }, { key: 'oni', label: 'ONI', dashed: true }], fill: true }, { range: '15' });
    await mountChart($('#ch-regions'), { title: 'Regiones Niño', units: 'degC', series: [{ key: 'nino3_oisst', label: 'Niño 3' }, { key: 'nino34_oisst', label: 'Niño 3.4' }, { key: 'nino4_oisst', label: 'Niño 4' }] });
    await mountChart($('#ch-cvb'), { title: 'Costa frente a cuenca', units: 'degC', series: [{ key: 'nino12_oisst', label: 'Niño 1+2' }, { key: 'nino34_oisst', label: 'Niño 3.4' }] });
  },
};

VIEWS.oceano = {
  title: 'Océano y atmósfera',
  render() {
    const winds = ['wpac850', 'cpac850', 'epac850'].map((k) => {
      const s = series(k);
      if (!s) return '';
      const l = s.latest;
      const dir = l.stale ? 'Dato actual no disponible' : l.value >= 0 ? 'Del este (alisios)' : 'Del oeste';
      return html`<div class="card metric"><div class="metric-name">${s.label}</div><p class="metric-value ${l.value < 0 ? 'warm' : ''}">${l.stale ? '' : F.fmtValue(l.value, 'm_per_s')}</p><p>${raw(ICON[l.value >= 0 ? 'arrowLeft' : 'arrowRight'])} ${dir}</p><div class="metric-period">${F.fmtMonth(l.period)}</div></div>`;
    });
    return html`
      <div class="page-head"><div class="eyebrow">Indicadores</div><h1>Océano y atmósfera</h1>
        <p>Las cuatro familias de indicadores que se vigilan para El Niño: temperatura del mar, vientos, termoclina y presión atmosférica.</p></div>
      ${chartCard('ch-weekly', { title: 'Temperatura del mar semanal', tour: 'ocean-weekly', range: '2', desc: 'Anomalía semanal por región Niño (NOAA OISST v2.1, base 1991–2020). Semanas centradas en el miércoles.' })}
      ${chartCard('ch-monthly', { title: 'Temperatura del mar mensual', tour: 'ocean-monthly', range: '15', desc: 'NOAA ERSSTv6 (la reconstrucción que NOAA usa para el RONI) y OISST (llega unas semanas antes), ambas con base 1991–2020.' })}
      <section data-tour-id="ocean-winds" aria-labelledby="wind-h">
        <div class="section-head"><h2 id="wind-h">Vientos alisios a 850 hPa</h2></div>
        <div class="grid g3">${winds}</div>
      </section>
      ${chartCard('ch-wind', { title: 'Anomalía de los vientos alisios', range: '5', desc: 'Negativo: alisios más débiles o viento del oeste (favorece El Niño). Positivo: alisios más fuertes. Fuente: NOAA/CPC, 5°N–5°S.' })}
      ${chartCard('ch-heat', { title: 'Calor bajo la superficie (0–300 m)', tour: 'ocean-heat', range: '5', desc: 'Anomalía de la temperatura media de los 300 m superiores del Pacífico ecuatorial (NOAA GODAS, base 1981–2010). Su aumento suele anticipar el calentamiento en superficie.', foot: 'Profundidad de la isoterma de 20 °C (D20): no se publica en el observatorio porque no hay una fuente pública verificada. La variable «dbss_obil» de GODAS es la profundidad de la capa isotérmica, no D20. Ver Metodología.' })}
      ${chartCard('ch-soi', { title: 'Índice de Oscilación del Sur (SOI)', tour: 'ocean-soi', range: '5', desc: 'Diferencia de presión Tahití − Darwin. Negativo sostenido: favorece El Niño. Se muestra en escala Troup (×10, umbrales ±7).', foot: 'SOI en escala Troup calculado por el observatorio con las presiones de NOAA/CPC (climatología 1951–1992) y validado contra valores históricos de la Oficina de Meteorología de Australia. NOAA publica además un SOI estandarizado (±3).' })}`;
  },
  async after() {
    await mountChart($('#ch-weekly'), { title: 'TSM semanal', units: 'degC', periodLabel: monthLabel, series: [{ weekly: 'nino12', label: 'Niño 1+2' }, { weekly: 'nino3', label: 'Niño 3' }, { weekly: 'nino34', label: 'Niño 3.4' }, { weekly: 'nino4', label: 'Niño 4' }] }, { range: '2' });
    await mountChart($('#ch-monthly'), { title: 'TSM mensual', units: 'degC', series: [{ key: 'nino12', label: 'Niño 1+2 ERSSTv6' }, { key: 'nino12_oisst', label: 'Niño 1+2 OISST', dashed: true }, { key: 'nino34', label: 'Niño 3.4 ERSSTv6' }, { key: 'nino34_oisst', label: 'Niño 3.4 OISST', dashed: true }] }, { range: '15' });
    await mountChart($('#ch-wind'), { title: 'Anomalía de vientos', units: 'm_per_s', series: [{ key: 'wpac850_anom', label: 'Occidental' }, { key: 'cpac850_anom', label: 'Central' }, { key: 'epac850_anom', label: 'Oriental' }] });
    await mountChart($('#ch-heat'), { title: 'Contenido de calor', units: 'degC', fill: true, series: [{ key: 'heat_180w100w', label: '180°–100°O' }, { key: 'heat_160e80w', label: '160°E–80°O', dashed: true }] });
    await mountChart($('#ch-soi'), { title: 'SOI', units: 'dimensionless', refLines: [{ v: 7, label: '+7', tone: 'cool' }, { v: -7, label: '−7', tone: 'warm' }], series: [{ key: 'soi_troup', label: 'SOI (Troup)' }], fill: true, invertFill: true });
  },
};

VIEWS.mapa = { title: 'Mapa', render: () => mapView.render(), after: () => mapView.after(load) };

VIEWS.historia = {
  title: 'Historia',
  render() {
    const evs = [...(S.dash.events || [])].reverse();
    const rows = evs.map((e) => html`<tr data-phase="${e.phase}">
      <th scope="row">${e.name}${e.ongoing ? html` <span class="tag tag-prelim">en curso</span>` : ''}</th>
      <td>${F.fmtMonth(e.start, { short: true })} – ${e.ongoing ? 'hoy' : F.fmtMonth(e.end, { short: true })}</td>
      <td class="num">${e.months}</td><td class="num">${F.fmtValue(e.peak, 'degC')}</td><td>${toneChip(e.phase, e.magnitude)}</td></tr>`);
    return html`
      <div class="page-head"><div class="eyebrow">Desde 1950</div><h1>Historia de El Niño y La Niña costeros</h1>
        <p>Eventos identificados con la definición operacional de ENFEN (Nota Técnica 01-2024) aplicada al ICEN oficial: al menos tres meses consecutivos en condición cálida (> +0,5 °C) o fría (< −0,7 °C).</p></div>
      ${chartCard('ch-compare', { title: 'El evento actual frente a los grandes eventos', range: 'all', desc: 'ICEN oficial alineado por el mes de inicio de cada evento.' })}
      <section class="card" data-tour-id="events" aria-labelledby="ev-h">
        <div class="section-head"><h2 id="ev-h">Eventos (${evs.length})</h2>
          <div class="seg" role="group" aria-label="Filtrar eventos"><button type="button" data-ph="all" aria-pressed="true">Todos</button><button type="button" data-ph="warm" aria-pressed="false">El Niño</button><button type="button" data-ph="cool" aria-pressed="false">La Niña</button></div></div>
        <div class="table-wrap"><table id="ev-table"><thead><tr><th scope="col">Evento</th><th scope="col">Periodo</th><th scope="col">Meses</th><th scope="col">ICEN máximo</th><th scope="col">Magnitud</th></tr></thead><tbody>${rows}</tbody></table></div>
        <p class="muted small">Elaboración del observatorio. La lista oficial de eventos la mantiene ENFEN.</p>
      </section>
      <section class="card" aria-labelledby="imp-h"><h2 id="imp-h">Impactos documentados en el Perú</h2>
        <ul class="impacts">${PAST_IMPACTS.map((i) => html`<li><p>${i.text}</p><p class="muted small">Fuente: ${i.source}</p></li>`)}</ul></section>`;
  },
  async after() {
    $$('[data-ph]').forEach((b) => b.addEventListener('click', () => {
      $$('[data-ph]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      $$('#ev-table tbody tr').forEach((tr) => { tr.hidden = b.dataset.ph !== 'all' && tr.dataset.phase !== b.dataset.ph; });
    }));
    const icen = await fullSeries('icen');
    const evs = (S.dash.events || []).filter((e) => e.phase === 'warm');
    const big = evs.filter((e) => e.ongoing || ['1982', '1997', '2015', '2023', '1972'].includes(e.start.slice(0, 4)));
    if (!icen || !big.length) return;
    const idx = new Map(icen.points.map((p) => [p.period, p.value]));
    const series = big.map((e) => {
      const pts = [];
      const [y, m] = e.start.split('-').map(Number);
      for (let i = -2; i < 24; i++) {
        const t = new Date(Date.UTC(y, m - 1 + i, 15));
        const per = `${t.getUTCFullYear()}-${String(t.getUTCMonth() + 1).padStart(2, '0')}`;
        if (!idx.has(per)) continue;
        pts.push({ t: Date.UTC(2000, i, 15), v: idx.get(per), label: `Mes ${i + 1} (${F.fmtMonth(per)})` });
      }
      return { label: `${e.start.slice(0, 4)}${e.ongoing ? ' (actual)' : `–${e.end.slice(2, 4)}`}`, points: pts, dashed: !e.ongoing };
    });
    const box = $('#ch-compare .chart-box');
    timeChart(box, { title: 'Eventos comparados', units: 'degC', series, xLabel: (t) => `Mes ${Math.round((t - Date.UTC(2000, 0, 15)) / (30.44 * 864e5)) + 1}`, periodLabel: (l) => l });
    $('#ch-compare .seg')?.remove();
    const tbl = $('#ch-compare .chart-table');
    $('#ch-compare details')?.addEventListener('toggle', () => { tbl.innerHTML = dataTable(series, 'degC', { n: 30, periodLabel: (l) => l }); });
  },
};

VIEWS.datos = {
  title: 'Datos',
  render() {
    const opts = Object.values(S.dash.series).map((s) => html`<option value="${s.id}">${s.label}</option>`);
    const csvs = Object.values(S.dash.series).map((s) => html`<li><a href="${DATA}csv/${s.id}.csv" download>${s.label}</a> <span class="muted small">${s.frequency} · ${s.source}</span></li>`);
    return html`
      <div class="page-head"><div class="eyebrow">Datos abiertos</div><h1>Datos y descargas</h1>
        <p>Todas las series publicadas, con su periodo, unidad y fuente. Los archivos CSV llevan el identificador de la publicación (${S.pub}).</p></div>
      <section class="card" data-tour-id="explorer" aria-labelledby="ex-h">
        <h2 id="ex-h">Explorador de series</h2>
        <div class="row"><label for="ex-sel">Serie</label><select id="ex-sel" class="input">${opts}</select>
          <label for="ex-from">Desde</label><input id="ex-from" class="input input-s" type="number" min="1950" max="2100" step="1" inputmode="numeric">
          <label for="ex-to">Hasta</label><input id="ex-to" class="input input-s" type="number" min="1950" max="2100" step="1" inputmode="numeric">
          <a id="ex-dl" class="btn ghost" download>Descargar CSV</a></div>
        <p id="ex-desc" class="muted"></p>
        <div class="chart-box" id="ex-chart"></div>
        <div id="ex-table"></div>
      </section>
      <section class="card" data-tour-id="downloads" aria-labelledby="dl-h"><h2 id="dl-h">Descargas</h2>
        <ul class="link-list cols">
          <li><a href="${DATA}csv/todas-las-series.csv" download>Todas las series mensuales (CSV)</a></li>
          <li><a href="${DATA}csv/semanal-regiones-nino.csv" download>TSM semanal por región Niño (CSV)</a></li>
          <li><a href="${DATA}series.json">Series completas (JSON)</a></li>
          <li><a href="${DATA}dashboard.json">Resumen de la publicación (JSON)</a></li>
          <li><a href="${DATA}sources.json">Registro de fuentes (JSON)</a></li>
          <li><a href="${DATA}run-report.json">Informe de la última corrida (JSON)</a></li>
        </ul>
        <h3>Por serie</h3><ul class="link-list cols">${csvs}</ul>
        <p class="muted small">Los valores de texto que empiezan con =, +, − o @ se protegen para evitar fórmulas en hojas de cálculo.</p>
      </section>`;
  },
  async after() {
    const sel = $('#ex-sel'), from = $('#ex-from'), to = $('#ex-to');
    const pre = new URLSearchParams(location.hash.split('?')[1] || '').get('serie');
    if (pre && S.dash.series[pre]) sel.value = pre;
    const draw = async () => {
      const s = await fullSeries(sel.value);
      const meta = S.dash.series[sel.value];
      $('#ex-desc').textContent = `${meta.description} Unidad: ${F.unitLabel(meta.units) || 'adimensional'}. Base: ${meta.climatology || '—'}.`;
      $('#ex-dl').href = `${DATA}csv/${sel.value}.csv`;
      if (!s) { $('#ex-chart').textContent = 'Serie no disponible.'; return; }
      const y0 = Number(from.value) || 0, y1 = Number(to.value) || 9999;
      const pts = s.points.filter((p) => +p.period.slice(0, 4) >= y0 && +p.period.slice(0, 4) <= y1);
      const xy = toXY(pts, 'period');
      const pl = meta.periodKind === 'season' ? seasonLabel : undefined;
      timeChart($('#ex-chart'), { title: meta.label, units: meta.units, series: [{ label: meta.label, points: xy }], fill: meta.units === 'degC', periodLabel: pl });
      $('#ex-table').innerHTML = dataTable([{ label: meta.label, points: xy }], meta.units, { n: 100000, periodLabel: pl });
    };
    [sel, from, to].forEach((x) => x.addEventListener('change', draw));
    await draw();
  },
};

VIEWS.metodologia = {
  title: 'Metodología',
  render() {
    return html`
      <div class="page-head"><div class="eyebrow">Transparencia</div><h1>Fuentes, vigencia y metodología</h1>
        <p>Cómo se obtienen, validan y publican los datos, y qué tan recientes son en esta publicación.</p></div>
      <section class="card" data-tour-id="sources-health" aria-labelledby="sh-h"><div class="section-head"><h2 id="sh-h">Estado de las fuentes</h2><span class="muted small">Publicación ${S.pub} · ${F.fmtDateTime(S.dash.generatedAt)}</span></div><div id="sources-table"><div class="skeleton"></div></div></section>
      <section class="card" data-tour-id="incidents" aria-labelledby="inc-h"><h2 id="inc-h">Incidencias de la última corrida</h2><div id="incidents"><div class="skeleton"></div></div>
        <p class="muted small">${SITE.issues ? html`Cada incidencia se registra también como issue en <a href="${SITE.issues}" rel="noopener" target="_blank">GitHub</a> para su seguimiento y se cierra sola cuando deja de ocurrir.` : 'Cada incidencia se registra también para su seguimiento y se cierra sola cuando deja de ocurrir.'}</p></section>
      <section class="card prose" data-tour-id="thresholds" aria-labelledby="th-h">
        <h2 id="th-h">Umbrales y clasificaciones</h2>
        <h3>ICEN (ENFEN)</h3><p>Nota Técnica ENFEN 01-2024: fría fuerte &lt; −1,3; fría moderada −1,3 a &lt; −1,1; fría débil −1,1 a &lt; −0,7; neutra −0,7 a +0,5; cálida débil &gt; +0,5 a +1,3; moderada &gt; +1,3 a +2,1; fuerte &gt; +2,1 a +3,5; extraordinaria &gt; +3,5 °C. Un evento requiere al menos tres meses consecutivos.</p>
        <h3>RONI y ONI (NOAA)</h3><p>±0,5 °C. Para episodios históricos NOAA exige cinco trimestres móviles consecutivos. Las etiquetas de intensidad (débil, moderado, fuerte, muy fuerte cada 0,5 °C) son una convención de uso común, no una categoría oficial.</p>
        <h3>Señal operativa del equipo GRD</h3><p>Transcripción de la tabla del equipo GRD (política expert-grd-image-v1, en borrador). TSM costera: normal −0,7 a +0,5; amarillo +1,3 a +2,0; rojo &gt; +2,1 °C. TSM de cuenca: normal −0,5 a +0,5; amarillo &gt; +1,0 a +1,5; rojo &gt; +1,5 °C. Vientos: rojo si el flujo es de oeste a este. Termoclina: normal ±20 m; amarillo 30 a 50 m; rojo &gt; 50 m. SOI: normal −7 a +7; rojo &lt; −7. Los intervalos no definidos quedan «Sin clasificación».</p>
      </section>
      <section class="card" aria-labelledby="arch-h" data-tour-id="architecture">
        <h2 id="arch-h">Arquitectura</h2>
        <p class="muted">De las fuentes al sitio: canales de obtención, pipeline en Python, publicación atómica y operación diaria.</p>
        <figure class="arch-figure" id="arch-fig"><a href="assets/arquitectura.svg" rel="noopener" target="_blank">Ver el diagrama de arquitectura</a></figure>
      </section>
      <section class="card prose" aria-labelledby="met-h">
        <h2 id="met-h">Cómo funciona</h2>
        <ol>
          <li><strong>Cada noche (23:37, hora de Lima)</strong> el pipeline descarga cada fuente directamente de la institución. Si la institución no responde, usa la copia que bajó el recolector en el Perú a las 21:00 o la copia más reciente del Internet Archive, y lo indica; si tampoco existe, conserva el último dato válido con su fecha real.</li>
          <li><strong>Noticias.</strong> Se leen los feeds RSS de medios del Perú y del mundo, se conservan las notas sobre El Niño o sus impactos, se agrupan las que cuentan lo mismo y se agregan a un histórico que solo crece. Solo se guarda lo que cada medio publica en su feed.</li>
          <li><strong>Lectura tolerante a cambios de formato.</strong> Los archivos se leen por sus encabezados y etiquetas, no por posiciones fijas, y se comprueban rangos plausibles, duplicados y orden. Si el formato cambia, se registra una incidencia y el dato queda en validación. Los lectores se prueban contra copias históricas de cada fuente (2004–2026).</li>
          <li><strong>Vigencia por fuente.</strong> Cada serie tiene su propia antigüedad máxima según la frecuencia con que publica la institución. Un dato vencido nunca se presenta como actual: se muestra «Dato actual no disponible».</li>
          <li><strong>Publicación atómica.</strong> Todos los archivos de una corrida comparten un identificador de publicación. El sitio verifica que coincidan antes de mostrarlos.</li>
          <li><strong>Vigilancia.</strong> Un vigilante revisa cada 6 horas que el sitio publicado esté al día y relanza la actualización si hace falta.</li>
        </ol>
        <h3>Decisiones y limitaciones</h3>
        <ul>
          <li>El ICEN oficial se toma del archivo que publica el IGP para ENFEN. El observatorio no publica un ICEN propio: con ERSSTv6 el cálculo difiere del oficial hasta 0,7 °C.</li>
          <li>El RONI se usa tal como lo publica NOAA (ahora con ERSSTv6); no se recalcula.</li>
          <li>La señal GRD de TSM usa las anomalías mensuales OISST de Niño 1+2 y Niño 3.4, que llegan antes que ERSST. No se aplica al ICEN ni al RONI.</li>
          <li>D20 (profundidad de la isoterma de 20 °C) no se publica: la variable de GODAS disponible por OPeNDAP («dbss_obil») es la profundidad de la capa isotérmica, no D20. Se muestra en su lugar el contenido de calor de 0–300 m de NOAA, sin aplicarle los umbrales de D20.</li>
          <li>El SOI de la tabla GRD (±7) corresponde a la escala Troup (×10) de la Oficina de Meteorología de Australia. El observatorio la calcula con las presiones de Tahití y Darwin de NOAA porque el servidor australiano no permite descargas automáticas.</li>
          <li>Los comunicados de ENFEN se leen del PDF oficial. Cuando el portal de ENFEN no responde a los servidores de GitHub, se usa la copia del Internet Archive y se indica en el estado.</li>
        </ul>
        ${SITE.repo ? html`<p>Código, datos y registro de cambios: <a href="${SITE.repo}" rel="noopener" target="_blank">${SITE.repo.replace(/^https:\/\//, '')}</a>.</p>` : ''}
      </section>
      <section class="card prose" aria-labelledby="gl-h"><h2 id="gl-h">Glosario</h2><dl class="glossary">${GLOSSARY.map(([t, d]) => html`<dt>${t}</dt><dd>${d}</dd>`)}</dl></section>`;
  },
  async after() {
    fetch('assets/arquitectura.svg').then((r) => (r.ok ? r.text() : null)).then((svg) => {
      if (svg && svg.trimStart().startsWith('<svg')) $('#arch-fig').innerHTML = svg;
    }).catch(() => {});
    const src = await load('sources.json');
    const rep = await load('run-report.json');
    const ST = { ok: ['ok', 'Directa'], archive: ['watch', 'Copia de archivo'], carried: ['watch', 'Último dato válido'], failed: ['alert', 'Falló'] };
    if (src) {
      $('#sources-table').innerHTML = String(html`<div class="table-wrap"><table><thead><tr><th scope="col">Fuente</th><th scope="col">Estado</th><th scope="col">Obtenido</th><th scope="col">Frecuencia</th></tr></thead><tbody>
        ${src.sources.map((s) => html`<tr><th scope="row"><a href="${safeUrl(s.docs)}" rel="noopener" target="_blank">${s.product}</a><div class="muted small">${s.institution}</div></th>
        <td>${chip(ST[s.status]?.[0] || 'na', ST[s.status]?.[1] || s.status)}${s.formatDrift ? html` <span class="tag tag-prelim">formato cambió</span>` : ''}${s.archivedAt ? html`<div class="muted small">copia del ${F.fmtDate(s.archivedAt.slice(0, 10))}</div>` : ''}</td>
        <td>${s.retrievedAt ? F.fmtDateTime(s.retrievedAt) : '—'}${archiveHref(s.archive) ? html`<div class="small"><a href="${archiveHref(s.archive)}" rel="noopener" target="_blank">copia archivada</a></div>` : ''}</td><td>cada ~${s.cadenceDays} días</td></tr>`)}</tbody></table></div>`);
    } else $('#sources-table').textContent = 'No disponible.';
    if (rep) {
      const ev = rep.events.filter((e) => e.severity !== 'info');
      const SV = { warning: ['watch', 'Aviso'], error: ['alert', 'Error'], critical: ['alert', 'Crítico'] };
      $('#incidents').innerHTML = ev.length
        ? String(html`<ul class="incidents">${ev.map((e) => html`<li>${chip(SV[e.severity]?.[0] || 'na', SV[e.severity]?.[1] || e.severity)} <strong>${e.source}</strong> <span class="mono small">${e.code}</span><p>${e.message}</p></li>`)}</ul>`)
        : 'Sin incidencias: todas las fuentes respondieron con normalidad.';
    } else $('#incidents').textContent = 'No disponible.';
  },
};

// ---------------------------------------------------------------------------
// Noticias: novedades de cada fuente oficial y noticias de medios agrupadas
// ---------------------------------------------------------------------------
const NEWS_TABS = [['oficial', 'Fuentes oficiales'], ['peru', 'Perú'], ['mundo', 'Mundo']];
// Tipos de fuente: el filtro agrupa los tipos del catálogo de feeds.
const NEWS_KINDS = [['', 'Todas'], ['estado', 'Autoridades y Estado'], ['diario', 'Diarios'], ['radiotv', 'Radio y TV'], ['digital', 'Medios digitales'], ['agregador', 'Agregadores']];
const KIND_GROUP = { gobierno: 'estado', organismo: 'estado', diario: 'diario', radio: 'radiotv', tv: 'radiotv', digital: 'digital', agregador: 'agregador' };
const KIND_LABEL = { gobierno: 'Estado', organismo: 'Organismo', diario: 'Diario', radio: 'Radio', tv: 'TV', digital: 'Digital', agregador: 'Agregador' };
// Tipos de peligro (enso/news.py HAZARDS).
const HAZARD_LABEL = { lluvias: 'Lluvias', inundacion: 'Inundaciones', huaico: 'Huaicos y deslizamientos', sequia: 'Sequía', calor: 'Calor', frio: 'Frío, friaje y heladas', viento: 'Vientos', oleaje: 'Oleaje', sismo: 'Sismos y tsunamis', volcan: 'Volcanes', incendio: 'Incendios', emergencia: 'Emergencias', salud: 'Salud' };

function newsParams() {
  const q = new URLSearchParams(location.hash.split('?')[1] || '');
  return { tab: q.get('tab') || 'oficial', tipo: q.get('tipo') || '', dep: q.get('dep') || '', peligro: q.get('peligro') || '' };
}

function placeLabel(p, deps) {
  const dep = deps[p.code.slice(0, 2)];
  return p.level === 'departamento' ? p.name : `${p.name}${dep ? ` (${dep})` : ''}`;
}

// Cómo se ubicó la nota, para el título de la etiqueta de lugar.
const PLACE_METHOD = { texto: 'según el texto', campo: 'según la fuente', coordenadas: 'por coordenadas', medio: 'por el medio regional que la publicó', correccion: 'revisada a mano', anterior: 'ubicación anterior' };
function placeTitle(p) {
  if (!p || p.confidence === undefined) return '';
  return `Ubicación ${PLACE_METHOD[p.method] || ''}${p.method === 'correccion' ? '' : ` · confianza ${Math.round(p.confidence * 100)} %`}`.replace('  ', ' ');
}
function placeTag(p, deps) {
  const approx = p.confidence !== undefined && p.confidence < 0.8 && p.method !== 'correccion';
  return html`<span class="tag tag-place${approx ? ' tag-approx' : ''}" title="${placeTitle(p)}">${raw(ICON.pin)}${approx ? '≈ ' : ''}${placeLabel(p, deps)}</span>`;
}

function feedValue(it) {
  if (it.value === undefined || it.value === null) return '';
  const per = it.periodKind === 'season' ? seasonLabel(it.period) : it.periodKind === 'date' ? `semana del ${F.fmtDate(it.period)}` : F.fmtMonth(it.period);
  const ch = F.isNum(it.change) ? ` · ${F.fmtValue(it.change, it.units)} respecto del periodo anterior` : '';
  return html`<p class="feed-value"><strong>${F.fmtValue(it.value, it.units)}</strong> <span class="muted">${per}${ch}</span> ${toneChip(it.tone, it.category)}</p>`;
}

function officialItem(it) {
  const when = it.date ? html`<time datetime="${it.date}">${it.date.length > 10 ? F.fmtDateTime(it.date).replace(' (hora de Lima)', '') : F.fmtDate(it.date)}</time>` : '';
  return html`<li class="feed-item">
    <div class="feed-meta"><span class="feed-inst">${it.institution}</span>${when ? html` · ${when}` : ''}${it.kind ? html` · <span class="muted">${it.kind}</span>` : ''}</div>
    <h3 class="feed-title">${it.url ? html`<a href="${safeUrl(it.url)}" rel="noopener" target="_blank">${it.title}</a>` : it.title}</h3>
    ${feedValue(it)}
    ${it.text ? html`<p class="feed-text">${it.text}</p>` : ''}
    <div class="feed-tags">
      ${(it.hazards || []).filter((h) => HAZARD_LABEL[h]).map((h) => html`<span class="tag tag-hazard">${HAZARD_LABEL[h]}</span> `)}${(it.where || []).map((w) => html`<span class="tag tag-place">${raw(ICON.pin)}${w}</span> `)}
      ${it.level ? chip(it.level, LEVEL_TXT[it.level] && it.level !== 'ok' ? `Alerta ${LEVEL_TXT[it.level].toLowerCase()}` : undefined) : ''}
      ${it.stale ? html`<span class="tag tag-prelim">vencido</span>` : ''}
      ${it.newerListed ? html`<span class="tag tag-prelim">hay un comunicado más reciente (${it.newerListed}) sin leer</span>` : ''}
      ${it.next ? html`<span class="tag">próximo: ${F.fmtDate(it.next)}</span>` : ''}
      ${String(it.channel || '').startsWith('archive') ? html`<span class="tag">vía Internet Archive</span>` : it.channel === 'relay-peru' ? html`<span class="tag">vía recolector en el Perú</span>` : ''}
    </div>
    ${sourceLinks(it.url, it.archive, { when: it.retrievedAt, snapshot: it.snapshot })}</li>`;
}

// Sin avisos no quiere decir sin peligro: se dice qué fuentes de alertas no respondieron.
function alertSources(g) {
  const src = g.sources || [];
  if (!src.length) return '';
  const down = src.filter((s) => !s.ok);
  const links = (list) => list.map((s, i) => html`${i ? ', ' : ''}<a href="${safeUrl(s.url)}" rel="noopener" target="_blank">${s.name}</a>`);
  const empty = g.items.length ? '' : down.length === src.length
    ? html`<p class="notice notice-alert">Ninguna fuente de alertas respondió en esta actualización: consulte directamente a las instituciones.</p>`
    : html`<p>Las fuentes consultadas no publicaron avisos en los últimos 7 días.</p>`;
  return html`${empty}<p class="alert-sources muted small">${src.length - down.length} de ${src.length} fuentes de alertas respondieron en esta actualización.${down.length && down.length < src.length ? html` <strong>Sin respuesta:</strong> ${links(down)}. Sus avisos pueden faltar aquí; consulte la fuente.` : ''}</p>`;
}

function clusterItem(c, deps = {}, dep = '') {
  const more = c.links.length > 1;
  // Con un departamento elegido, sus lugares van primero: la tarjeta muestra por qué está en la lista.
  const all = c.places || [];
  const places = (dep ? [...all.filter((p) => p.code.startsWith(dep)), ...all.filter((p) => !p.code.startsWith(dep))] : all).slice(0, 3);
  return html`<li class="feed-item">
    <div class="feed-meta"><time datetime="${c.first}">${F.fmtDateTime(c.first).replace(' (hora de Lima)', '')}</time> · <span class="feed-inst">${c.outlets.slice(0, 3).join(', ')}${c.outlets.length > 3 ? ` y ${c.outlets.length - 3} más` : ''}</span></div>
    <h3 class="feed-title"><a href="${safeUrl(c.links[0].url)}" rel="noopener" target="_blank">${c.title}</a></h3>
    ${c.summary ? html`<p class="feed-text">${c.summary}</p>` : ''}
    <div class="feed-tags"><span class="tag">${c.relevance === 'enso' ? 'El Niño / La Niña' : 'Impactos y peligros'}</span>${(c.hazards || []).filter((h) => h !== 'enso' && HAZARD_LABEL[h]).slice(0, 3).map((h) => html` <span class="tag tag-hazard">${HAZARD_LABEL[h]}</span>`)}${c.count > 1 ? html` <span class="tag">${c.count} notas similares</span>` : ''}${(c.kinds || []).map((k) => html` <span class="tag tag-kind tag-${KIND_GROUP[k] || 'diario'}">${KIND_LABEL[k] || k}</span>`)}${places.map((p) => html` ${placeTag(p, deps)}`)}</div>
    ${sourceLinks(c.links[0].url, c.links[0].archive, { liveLabel: 'Nota original', snapshot: c.links[0].snapshot })}
    ${more ? html`<details class="feed-more"><summary>Ver las ${c.links.length} notas</summary><ul>${c.links.map((l) => html`<li><a href="${safeUrl(l.url)}" rel="noopener" target="_blank">${l.title}</a> <span class="muted small">${l.outlet}${l.kind ? ` (${(KIND_LABEL[l.kind] || l.kind).toLowerCase()})` : ''}${l.published ? ` · ${F.fmtDate(l.published.slice(0, 10))}` : ''}</span>${archiveHref(l.archive) ? html` <a class="small" href="${archiveHref(l.archive)}" rel="noopener" target="_blank">copia</a>` : ''}</li>`)}</ul></details>` : ''}
  </li>`;
}

VIEWS.noticias = {
  title: 'Noticias',
  render() {
    const { tab } = newsParams();
    const cur = NEWS_TABS.some(([k]) => k === tab) ? tab : 'oficial';
    return html`
      <div class="page-head"><div class="eyebrow">Novedades</div><h1>Noticias y novedades</h1>
        <p>Lo último que publicó cada fuente oficial y las noticias sobre El Niño y sus impactos en el Perú y el mundo: autoridades, diarios, radios y medios regionales. Cuando varios medios cuentan lo mismo se agrupan en una sola entrada con el enlace a cada uno, y cada noticia se ubica en su departamento, provincia o distrito.</p></div>
      <div class="seg" role="tablist" aria-label="Tipo de novedades" data-tour-id="news-tabs">${NEWS_TABS.map(([k, l]) => html`<button type="button" role="tab" data-tab="${k}" aria-selected="${String(k === cur)}" aria-pressed="${String(k === cur)}">${l}</button>`)}</div>
      <p id="news-live" class="visually-hidden" aria-live="polite"></p>
      <div id="news-body" class="news-body"><div class="skeleton"></div></div>
      <section class="card" aria-labelledby="nd-h" data-tour-id="news-downloads"><h2 id="nd-h">Descargas y estado de los feeds</h2>
        <p class="muted small">El histórico de noticias solo crece: cada corrida agrega las notas nuevas y nunca reescribe las anteriores. Solo se guarda lo que cada medio publica en su feed (titular, resumen, fecha y enlace).</p>
        <ul class="link-list cols">
          <li><a href="${DATA}news/items.csv" download>Histórico de noticias (CSV)</a></li>
          <li><a href="${DATA}news/items.jsonl" download>Histórico de noticias (JSON Lines, solo anexar)</a></li>
          <li><a href="${DATA}news/clusters.json">Noticias agrupadas de los últimos 14 días (JSON)</a></li>
          <li><a href="${DATA}feed.json">Novedades de las fuentes oficiales (JSON)</a></li>
          <li><a href="${DATA}news/feeds.json">Estado de cada feed (JSON)</a></li>
        </ul>
        <details id="feeds-status"><summary>Estado de los feeds en esta publicación</summary><div class="feeds-table"></div></details>
      </section>`;
  },
  async after() {
    const body = $('#news-body');
    const hasNews = Boolean(S.dash.news);
    const [feed, clusters, feeds] = await Promise.all([load('feed.json'), hasNews ? load('news/clusters.json') : null, hasNews ? load('news/feeds.json') : null]);
    const deps = clusters?.departmentNames || {};
    const setUrl = (p) => history.replaceState(null, '', `#/noticias?${new URLSearchParams(Object.entries(p).filter(([, v]) => v)).toString()}`);
    const show = (p) => {
      // Parámetros de la URL validados: un valor desconocido no deja la lista vacía sin explicación.
      p = { ...p };
      if (!NEWS_TABS.some(([k]) => k === p.tab)) p.tab = 'oficial';
      if (!NEWS_KINDS.some(([k]) => k === p.tipo)) p.tipo = '';
      if (p.tab !== 'peru' || !deps[p.dep]) p.dep = '';
      if (p.peligro && p.peligro !== 'enso' && !HAZARD_LABEL[p.peligro]) p.peligro = '';
      const { tab } = p;
      $$('[data-tab]').forEach((b) => { const on = b.dataset.tab === tab; b.setAttribute('aria-selected', String(on)); b.setAttribute('aria-pressed', String(on)); });
      if (tab === 'oficial') {
        body.innerHTML = feed ? String(html`${feed.groups.map((g) => html`<section class="card" aria-labelledby="fg-${g.id}"><h2 id="fg-${g.id}">${g.label}</h2>${alertSources(g)}<ul class="feed">${g.items.map(officialItem)}</ul></section>`)}`) : '<p class="card">No disponible en esta publicación.</p>';
        return;
      }
      if (!clusters) { body.innerHTML = '<p class="card">Las noticias no están disponibles en esta publicación.</p>'; return; }
      const region = (clusters.clusters || []).filter((c) => c.region === tab);
      const byKind = (c) => !p.tipo || (c.kinds || ['diario']).some((k) => KIND_GROUP[k] === p.tipo);
      const byDep = (c) => !p.dep || (c.departments || []).includes(p.dep);
      const hasHaz = (c, h) => (h === 'enso' ? c.relevance === 'enso' || (c.hazards || []).includes('enso') : (c.hazards || []).includes(h));
      const byHaz = (c) => !p.peligro || hasHaz(c, p.peligro);
      const list = region.filter((c) => byKind(c) && byDep(c) && byHaz(c));
      const kindCount = (k) => region.filter((c) => byDep(c) && byHaz(c) && (!k || (c.kinds || ['diario']).some((x) => KIND_GROUP[x] === k))).length;
      const depCount = {};
      region.filter((c) => byKind(c) && byHaz(c)).forEach((c) => (c.departments || []).forEach((d) => { depCount[d] = (depCount[d] || 0) + 1; }));
      const hazBase = region.filter((c) => byKind(c) && byDep(c));
      const hazOpts = [['enso', 'El Niño / La Niña'], ...Object.entries(HAZARD_LABEL)].map(([h, l]) => [h, l, hazBase.filter((c) => hasHaz(c, h)).length]).filter(([h, , n]) => n || h === p.peligro);
      const depOpts = Object.keys(deps).sort((a, b) => deps[a].localeCompare(deps[b], 'es'));
      const filters = html`<div class="news-filters">
        <div class="kind-chips" role="group" aria-label="Tipo de fuente">${NEWS_KINDS.map(([k, l]) => html`<button type="button" class="kind-chip" data-kind="${k}" aria-pressed="${String(k === p.tipo)}">${l} <span class="muted">${kindCount(k)}</span></button>`)}</div>
        ${tab === 'peru' ? html`<label class="dep-select"><span>Departamento</span><select id="news-dep"><option value="">Todo el Perú (${region.filter((c) => byKind(c) && byHaz(c)).length})</option>${depOpts.map((d) => html`<option value="${d}" ${d === p.dep ? 'selected' : ''}>${deps[d]} (${depCount[d] || 0})</option>`)}</select></label>` : ''}
        <label class="dep-select"><span>Peligro</span><select id="news-haz"><option value="">Todos (${hazBase.length})</option>${hazOpts.map(([h, l, n]) => html`<option value="${h}" ${h === p.peligro ? 'selected' : ''}>${l} (${n})</option>`)}</select></label>
      </div>`;
      const hazWhat = p.peligro ? ` sobre ${(p.peligro === 'enso' ? 'El Niño / La Niña' : HAZARD_LABEL[p.peligro] || p.peligro).toLowerCase()}` : '';
      const what = `${tab === 'peru' ? 'del Perú' : 'del mundo'}${p.dep && deps[p.dep] ? ` en ${deps[p.dep]}` : ''}${hazWhat}`;
      $('#news-live').textContent = `${list.length} ${list.length === 1 ? 'noticia' : 'noticias'} ${what}`;
      body.innerHTML = String(html`${filters}<section class="card" aria-label="Noticias ${what}">${list.length ? html`<p class="muted small news-count">${list.length} ${list.length === 1 ? 'noticia' : 'noticias'} ${what} en los últimos ${clusters.days} días</p><ul class="feed">${list.map((c) => clusterItem(c, deps, p.dep))}</ul>` : html`<p class="muted">No hay noticias ${what} con este filtro en los últimos ${clusters.days} días.</p>`}</section>`);
      $$('.kind-chip', body).forEach((b) => b.addEventListener('click', () => {
        const n = { ...p, tipo: b.dataset.kind };
        setUrl(n);
        show(n);
        $(`.kind-chip[data-kind="${n.tipo}"]`, body)?.focus();  // la lista se redibuja: el foco vuelve al filtro
      }));
      $('#news-dep', body)?.addEventListener('change', (e) => { const n = { ...p, dep: e.target.value }; setUrl(n); show(n); $('#news-dep', body)?.focus(); });
      $('#news-haz', body)?.addEventListener('change', (e) => { const n = { ...p, peligro: e.target.value }; setUrl(n); show(n); $('#news-haz', body)?.focus(); });
    };
    $$('[data-tab]').forEach((b) => b.addEventListener('click', () => {
      const n = { ...newsParams(), tab: b.dataset.tab };
      if (n.tab !== 'peru') n.dep = '';
      setUrl(n);
      show(n);
    }));
    show(newsParams());
    const box = $('#feeds-status .feeds-table');
    box.innerHTML = feeds ? String(html`<div class="table-wrap"><table><thead><tr><th scope="col">Feed</th><th scope="col">Estado</th><th scope="col">Entradas</th><th scope="col">Más reciente</th></tr></thead><tbody>
      ${feeds.feeds.map((f) => html`<tr><th scope="row"><a href="${safeUrl(f.url)}" rel="noopener" target="_blank">${f.name}</a><div class="muted small">${f.region === 'peru' ? (f.department && deps[f.department] ? deps[f.department] : 'Perú') : 'Mundo'} · ${KIND_LABEL[f.kind] || 'Diario'}${f.repairs && f.repairs.length ? ` · reparado: ${f.repairs.join(', ')}` : ''}</div></th>
      <td>${f.ok ? (f.active ? chip('ok', 'Activo') : chip('watch', 'Sin novedades')) : chip('alert', 'No responde')}${f.error ? html`<div class="muted small">${f.error}</div>` : ''}</td>
      <td>${f.items} (${f.relevant} sobre El Niño)</td><td>${f.latest ? F.fmtDate(f.latest.slice(0, 10)) : '—'}</td></tr>`)}</tbody></table></div>
      <p class="muted small">${feeds.history.items} notas guardadas desde ${feeds.history.since ? F.fmtDate(feeds.history.since.slice(0, 10)) : '—'}; ${feeds.history.added} nuevas en esta corrida.</p>`) : 'No disponible.';
  },
};

VIEWS.asistente = { title: 'Asistente', render: () => assistantView.render(), after: () => assistantView.after(S, load) };

// ---------------------------------------------------------------------------
// Estructura, navegación y arranque
// ---------------------------------------------------------------------------
const NAV = [['', 'Resumen', 'home'], ['costero', 'El Niño Costero', 'wave'], ['pacifico', 'Pacífico', 'globe'], ['oceano', 'Océano y atmósfera', 'layers'], ['mapa', 'Mapa', 'map'], ['historia', 'Historia', 'clock'], ['noticias', 'Noticias', 'news'], ['datos', 'Datos', 'table'], ['metodologia', 'Metodología', 'book'], ['asistente', 'Asistente', 'chat']];

function routeName() {
  const h = location.hash.replace(/^#\/?/, '').split('?')[0];
  return VIEWS[h] ? h : '';
}

let rendering = 0;
async function render() {
  const name = routeName();
  const view = VIEWS[name];
  const main = $('#main');
  const my = ++rendering;
  $$('.nav a').forEach((a) => a.setAttribute('aria-current', a.dataset.route === name ? 'page' : 'false'));
  if (!S.dash) return;
  main.innerHTML = String(view.render());
  document.title = `${view.title} · ${SITE.name}`;
  if (S.navigated) { main.focus({ preventScroll: true }); window.scrollTo(0, 0); }
  S.navigated = true;
  try { if (view.after && my === rendering) await view.after(); } catch (e) { console.error(e); }
  document.dispatchEvent(new CustomEvent('view:ready', { detail: name }));
}

function renderBanner() {
  const b = $('#banner');
  const parts = [];
  if (S.mismatch.length) parts.push(html`<div class="notice notice-alert" role="alert">${raw(ICON.octagon)}<p>Algunos archivos (${S.mismatch.join(', ')}) pertenecen a otra publicación y no se muestran. Recargue la página en unos minutos.</p></div>`);
  const h = S.dash?.health;
  if (h && ['error', 'critical'].includes(h.worst)) parts.push(html`<div class="notice notice-warn">${raw(ICON.triangle)}<p>En la última actualización ${h.sourcesTotal - h.sourcesOk} de ${h.sourcesTotal} fuentes no respondieron con normalidad. Los datos afectados muestran su fecha real. <a href="#/metodologia">Ver detalle</a></p></div>`);
  const age = S.dash ? (Date.now() - new Date(S.dash.generatedAt).getTime()) / 36e5 : 0;
  if (age > 36) parts.push(html`<div class="notice notice-warn">${raw(ICON.clock)}<p>La publicación tiene ${Math.round(age / 24)} días sin actualizarse. Las fechas de cada dato siguen siendo correctas.</p></div>`);
  b.innerHTML = parts.map(String).join('');
}

function shell() {
  $('#nav').innerHTML = NAV.map(([r, l, i]) => `<a href="#/${r}" data-route="${r}">${ICON[i] || ''}<span>${esc(l)}</span></a>`).join('');
  $('#disclaimer').textContent = DISCLAIMER;
  const theme = storage('enso-theme');
  if (theme) document.documentElement.dataset.theme = theme;
  syncThemeBtn();
  $('#theme-btn').addEventListener('click', () => {
    const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    storage('enso-theme', next);
    syncThemeBtn();
    document.dispatchEvent(new Event('theme:change'));
  });
}

function syncThemeBtn() {
  const dark = (document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')) === 'dark';
  const b = $('#theme-btn');
  b.setAttribute('aria-pressed', String(dark));
  b.setAttribute('aria-label', dark ? 'Usar tema claro' : 'Usar tema oscuro');
  b.innerHTML = dark ? ICON.sun : ICON.moon;
}

async function boot() {
  shell();
  try {
    S.dash = await fetchJSON('dashboard.json', Date.now());
    S.pub = S.dash.publicationId;
  } catch (e) {
    $('#main').innerHTML = String(html`<div class="card"><h1>Datos actuales en proceso de validación</h1><p>No se pudo cargar la publicación de datos. Intente nuevamente en unos minutos o consulte directamente las <a href="https://enfen.imarpe.gob.pe/comunicados/" rel="noopener" target="_blank">fuentes oficiales de ENFEN</a>.</p></div>`);
    return;
  }
  $('#pub-info').textContent = `Actualizado: ${F.fmtDateTime(S.dash.generatedAt)} · Publicación ${S.pub}`;
  renderBanner();
  window.addEventListener('hashchange', render);
  await render();
  const tour = new Tour({ getData: () => S.dash, navigate: (r) => { if (location.hash !== r) location.hash = r; } });
  $('#help-btn').addEventListener('click', () => tour.openMenu());
  tour.maybeResume();
}

boot();
