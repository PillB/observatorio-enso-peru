// Boletín de eventos El Niño: una hoja con lo que viene, dónde y cuándo.
//
// Todo sale de data/boletin.json, que arma la actualización diaria (python/enso/boletin.py) con los avisos oficiales,
// el estado del ENFEN y el escenario del CENEPRED. El mismo archivo alimenta el correo que manda n8n
// (n8n/nodes/boletin.js), así que la pestaña y el correo nunca dicen cosas distintas. Aquí no se calcula ningún
// nivel ni ningún orden: solo se dibuja. Lo único que mira la hora es el aviso «esta edición tiene N avisos que ya
// vencieron», para que nadie lea un boletín viejo como si fuera de ahora.
//
// La mitad de arriba es general (contadores, mapa y «qué se viene»); la de abajo, los diez departamentos más críticos.
// El mapa tiene dos versiones (experimento «boletin» de ab.js): el mapa del Perú y un mosaico de cuadros, el mismo
// que lleva el correo. En papel (Imprimir o Guardar como PDF) cabe en una hoja A4.

import { html, raw, safeUrl, $, $$ } from './lib/dom.js';
import * as F from './lib/format.js';
import { ICON } from './icons.js';
import { ab, abReady } from './ab.js';

const LV = { 3: 'r3', 2: 'r2', 1: 'r1', 0: 'un', '-1': 'ok' };
const TOP = 10;
/** Mosaico: fila y columna de cada departamento (igual que TILES en python/enso/boletin.py). */
export const TILES = {
  24: [0, 0], '01': [0, 2], 16: [0, 3], 20: [1, 0], '06': [1, 1], 22: [1, 2], 14: [2, 0], 13: [2, 1], 10: [2, 2], 25: [2, 3],
  '02': [3, 1], 19: [3, 2], 12: [3, 3], '07': [4, 0], 15: [4, 1], '09': [4, 2], '05': [4, 3], '08': [4, 4], 17: [4, 5],
  11: [5, 1], '03': [5, 3], 21: [5, 4], '04': [6, 2], 18: [6, 3], 23: [7, 3],
};
export const ABBR = { '01': 'AMA', '02': 'ANC', '03': 'APU', '04': 'ARE', '05': 'AYA', '06': 'CAJ', '07': 'CAL', '08': 'CUS', '09': 'HVC', 10: 'HUC', 11: 'ICA', 12: 'JUN', 13: 'LAL', 14: 'LAM', 15: 'LIM', 16: 'LOR', 17: 'MDD', 18: 'MOQ', 19: 'PAS', 20: 'PIU', 21: 'PUN', 22: 'SAM', 23: 'TAC', 24: 'TUM', 25: 'UCA' };
const TIER = { inmediata: ['Correo al momento', 'r3'], resumen: ['En el resumen diario', 'r1'], ninguna: ['No se envía', 'un'], inicial: ['Primer boletín', 'un'] };

const fmtWhen = new Intl.DateTimeFormat('es-PE', { timeZone: 'America/Lima', weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
export const when = (iso) => (iso ? fmtWhen.format(new Date(iso)).replace(/\.,? /g, ' ').replace(',', '') : '');
export const joinEs = (l, limit = 0) => {
  const x = l.filter(Boolean);
  if (limit && x.length > limit) return `${x.slice(0, limit).join(', ')} y otros`;
  return x.length > 1 ? `${x.slice(0, -1).join(', ')} y ${x[x.length - 1]}` : x[0] || '';
};

/** Cuándo, para un departamento: «Ahora, hasta mié 11 nov 23:59» o «Desde jue 12 nov 00:00». */
export function segWhen(s) {
  if (s.rank < 0) return '—';
  if (!s.now && s.since) return `Desde ${when(s.since)}`;
  return `Ahora${s.until ? `, hasta ${when(s.until)}` : ''}`;
}

/** Avisos de la edición que ya vencieron a la hora ``now`` (la edición es una foto del corte). */
export function expiredSince(doc, now = Date.now()) {
  return (doc.events || []).filter((e) => e.phase !== 'cancelado' && e.until && Date.parse(e.until) < now);
}

/** La edición se ve vieja: más de 36 h desde el corte (la actualización es diaria). */
export const isOld = (doc, now = Date.now()) => now - Date.parse(doc.cutoff) > 36 * 36e5;

const chip = (s, small = false) => html`<span class="lvl lvl-${LV[s.rank]}${small ? ' lvl-s' : ''}">${s.rank === 3 ? raw(ICON.octagon) : s.rank > 0 ? raw(ICON.triangle) : ''}${s.label}</span>`;

function counters(c) {
  const box = (r, n, t) => html`<div class="bol-count bc-${LV[r]}"><strong>${n}</strong><span>${t}</span></div>`;
  return html`<div class="bol-counts" role="group" aria-label="Departamentos por nivel">
    ${box(3, c.rojo, 'en rojo')}${box(2, c.naranja, 'en naranja')}${box(1, c.amarillo, 'en amarillo')}${box(0, c.sinNivel, 'sin nivel')}${box(-1, c.verde, 'sin avisos')}</div>`;
}

function svgMap(geo, segs, sel) {
  const by = Object.fromEntries(segs.map((s) => [s.code, s]));
  const paths = geo.departments.map((d) => {
    const s = by[d.code];
    if (!s) return '';
    const soon = s.rank >= 0 && !s.now;
    return html`<path class="bol-dep d-${LV[s.rank]}${soon ? ' soon' : ''}${sel === d.code ? ' sel' : ''}" d="${d.d}" data-dep="${d.code}" tabindex="0" role="button" aria-pressed="${String(sel === d.code)}" aria-label="${s.name}: ${s.rank < 0 ? 'sin avisos' : `${s.label}, ${segWhen(s)}`}"><title>${s.name}: ${s.label}</title></path>`;
  });
  const cal = geo.departments.find((d) => d.code === '07');
  const dot = cal && by['07'] ? html`<circle class="bol-dep d-${LV[by['07'].rank]}" cx="${cal.label[0] - 4}" cy="${cal.label[1]}" r="6" data-dep="07" aria-hidden="true"></circle>` : '';
  const labels = geo.departments.filter((d) => by[d.code]?.rank >= 2 && d.code !== '07').map((d) => html`<text class="bol-lbl" x="${d.label[0]}" y="${d.label[1]}" aria-hidden="true">${ABBR[d.code]}</text>`);
  const defs = html`<defs>${['r3', 'r2', 'r1', 'un'].map((k) => html`<pattern id="bol-soon-${k}" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="7" height="7" class="pt-bg"/><rect width="3.2" height="7" class="pt-${k}"/></pattern>`)}</defs>`;
  return html`<svg class="bol-svg" viewBox="0 0 ${geo.width} ${geo.height}" role="group" aria-label="Mapa del Perú: cada departamento con el nivel más alto de sus avisos oficiales" preserveAspectRatio="xMidYMid meet">${defs}${paths}${dot}${labels}</svg>`;
}

function tileMap(segs, sel) {
  const by = Object.fromEntries(segs.map((s) => [s.code, s]));
  const cells = Object.entries(TILES).map(([code, [r, c]]) => {
    const s = by[code];
    if (!s) return '';
    return html`<button type="button" class="bol-tile d-${LV[s.rank]}${s.rank >= 0 && !s.now ? ' soon' : ''}${sel === code ? ' sel' : ''}" style="grid-row:${r + 1};grid-column:${c + 1}" data-dep="${code}" aria-pressed="${String(sel === code)}" title="${s.name}: ${s.label}" aria-label="${s.name}: ${s.rank < 0 ? 'sin avisos' : `${s.label}, ${segWhen(s)}`}">${ABBR[code]}</button>`;
  });
  return html`<div class="bol-tiles" role="group" aria-label="Mosaico de departamentos del Perú, norte arriba y la costa a la izquierda">${cells}</div>`;
}

function legend(doc) {
  return html`<ul class="bol-legend">${(doc.legend || []).map((l) => html`<li><span class="sw sw-${LV[l.rank]}"></span><span>${l.text}</span></li>`)}
    <li><span class="sw sw-${'r2'} sw-striped"></span><span>Rayado: ese nivel solo se espera (aviso próximo).</span></li></ul>`;
}

function headline(doc) {
  return html`<div class="bol-head">${(doc.headline || []).map((h) => html`<p data-line="${h.id}"><strong>${h.title}.</strong> ${h.text}</p>`)}</div>`;
}

function probBars(doc) {
  const p = (doc.enso?.probabilities || []).find((x) => x.region === 'nino12');
  if (!p) return '';
  return html`<div class="bol-prob"><div class="small"><strong>Probabilidad para el verano según el ENFEN</strong> (costa del Perú, informe técnico N° ${p.informe}${p.page ? `, pág. ${p.page}` : ''})</div>
    ${p.summer.map((x) => html`<div class="bol-pbar"><span class="bol-plab">${x.label}</span><span class="bol-ptrack"><span style="width:${Math.max(0, Math.min(100, x.pct))}%"></span></span><strong>${x.pct} %</strong></div>`)}</div>`;
}

function segRow(s, events) {
  const evs = s.events.map((k) => events[k]).filter(Boolean);
  const sc = s.scenario;
  const pct = sc.districts ? Math.round((100 * sc.muyAlto) / sc.districts) : 0;
  return html`<tr data-dep="${s.code}" class="bol-row">
    <td class="num">${s.position}</td>
    <th scope="row"><strong>${s.name}</strong><div>${chip(s, true)}</div></th>
    <td data-label="Qué podría pasar">${s.hazards.slice(0, 3).join(' · ') || '—'}${s.places.length ? html`<div class="muted small">${joinEs(s.places.slice(0, 4))}</div>` : ''}</td>
    <td data-label="Cuándo">${segWhen(s)}</td>
    <td data-label="Fuente">${evs.length ? html`<details class="bol-evs"><summary>${joinEs([...new Set(evs.map((e) => e.institution))]) || '—'} <span class="muted small">(${evs.length} ${evs.length === 1 ? 'aviso' : 'avisos'})</span></summary>
      <ul>${evs.map((e) => html`<li><span class="lvl lvl-s lvl-${e.rank ? `r${e.rank}` : 'un'}">${e.level || 'Sin nivel'}</span> <a href="${safeUrl(e.url)}" rel="noopener" target="_blank">${e.title}</a>
        <span class="muted small">${e.institution}${e.alsoBy?.length ? ` (también ${e.alsoBy.join(', ')})` : ''} · ${e.phase === 'proxima' ? `desde ${when(e.from)}` : e.until ? `hasta ${when(e.until)}` : 'en curso'}${e.approx ? ' · ≈ lugar aproximado' : ''}</span></li>`)}</ul></details>` : '—'}</td>
    <td data-label="Riesgo CENEPRED" class="small">${sc.districts ? html`<span class="bol-risk" title="${pct} % de sus distritos en riesgo muy alto"><span style="width:${pct}%"></span></span>${F.fmtNumber(sc.muyAlto)} muy alto · ${F.fmtNumber(sc.alto)} alto <span class="muted">de ${F.fmtNumber(sc.districts)}</span>` : '—'}</td>
    <td data-label="Daños 72 h" class="num">${s.reports ? html`<span title="${s.reportTitles.join(' · ')}">${s.reports}</span>` : '0'}</td></tr>`;
}

function table(doc, all) {
  const events = Object.fromEntries((doc.events || []).map((e) => [e.key, e]));
  const rated = doc.segments.filter((s) => s.rank >= 0);
  const rows = all ? doc.segments : rated.slice(0, TOP);
  const green = doc.segments.filter((s) => s.rank < 0);
  return html`<div class="table-wrap"><table class="data bol-table"><caption class="visually-hidden">Departamentos ordenados por criticidad</caption>
    <thead><tr><th scope="col">#</th><th scope="col">Departamento</th><th scope="col">Qué podría pasar · dónde</th><th scope="col">Cuándo</th><th scope="col">Fuente oficial</th><th scope="col">Distritos en riesgo (CENEPRED)</th><th scope="col">Daños 72 h</th></tr></thead>
    <tbody>${rows.length ? rows.map((s) => segRow(s, events)) : html`<tr><td colspan="7">Ningún departamento tiene avisos oficiales vigentes o próximos relacionados con El Niño.</td></tr>`}</tbody></table></div>
    ${!all && green.length ? html`<p class="muted small bol-green">Sin avisos relacionados con El Niño: ${joinEs(green.map((s) => s.name))}.</p>` : ''}`;
}

function changesBlock(doc) {
  const ch = (doc.changes || []).filter((c) => c.rule !== 'inicial');
  if (!ch.length) return '';
  return html`<div class="bol-changes" role="note"><strong>Qué cambió en esta edición:</strong><ul>${ch.slice(0, 6).map((c) => html`<li><span class="lvl lvl-s lvl-${TIER[c.tier]?.[1] || 'un'}">${TIER[c.tier]?.[0] || c.tier}</span> ${c.text}</li>`)}</ul>${ch.length > 6 ? html`<p class="muted small">Y ${ch.length - 6} cambios más (ver «Ediciones anteriores» abajo).</p>` : ''}</div>`;
}

function enfenLine(doc) {
  const e = doc.enso?.enfen;
  if (!e) return '';
  return html`<div class="bol-enfen"><span class="tag">ENFEN</span> <strong>${e.status}</strong> <span class="muted small">Comunicado oficial N° ${e.number}${e.issued ? `, ${F.fmtDate(e.issued)}` : ''}${e.next ? ` · próximo: ${F.fmtDate(e.next)}` : ''}</span>${e.stale ? html` <span class="tag tag-prelim">ya debió salir uno nuevo</span>` : ''}</div>`;
}

function sheet(doc, geo, variant, sel, all) {
  const map = variant === 'mosaico' || !geo ? tileMap(doc.segments, sel) : svgMap(geo, doc.segments, sel);
  return html`<article class="bol-sheet card" id="bol-sheet" aria-labelledby="bol-h">
    <header class="bol-top"><div><div class="eyebrow">Boletín de eventos El Niño · Perú</div><h2 id="bol-h">Edición N° ${doc.edition}</h2>
      <p class="muted small">Corte: ${when(doc.cutoff)} (hora de Lima)${doc.editionAt && doc.editionAt !== doc.cutoff ? ` · sin cambios desde ${when(doc.editionAt)}` : ''} · ${doc.sources?.ok ?? '—'} de ${doc.sources?.total ?? '—'} fuentes de avisos respondieron</p></div>
      ${counters(doc.counts)}</header>
    ${enfenLine(doc)}
    ${changesBlock(doc)}
    <div class="bol-half" data-tour-id="boletin-map">
      <div class="bol-map"><div class="bol-map-head"><strong>Nivel más alto de los avisos oficiales</strong>
        <div class="seg bol-variant" role="group" aria-label="Forma del mapa">${[['mapa', 'Mapa'], ['mosaico', 'Mosaico']].map(([v, l]) => html`<button type="button" data-variant="${v}" aria-pressed="${String(v === variant)}">${l}</button>`)}</div></div>
        ${map}${legend(doc)}</div>
      <div class="bol-what"><h3>Qué se viene</h3>${headline(doc)}${probBars(doc)}<div id="bol-dep" aria-live="polite"></div></div>
    </div>
    <section class="bol-bottom" data-tour-id="boletin-top" aria-labelledby="bol-top-h">
      <div class="section-head"><h3 id="bol-top-h">${all ? 'Los 25 departamentos, por criticidad' : `Los ${Math.min(TOP, doc.segments.filter((s) => s.rank >= 0).length) || ''} departamentos más críticos`}</h3>
        <button type="button" class="linkish no-print" id="bol-all" aria-pressed="${String(all)}">${all ? 'Ver solo los diez primeros' : 'Ver los 25 departamentos'}</button></div>
      ${table(doc, all)}
      <p class="muted small bol-order"><strong>Orden:</strong> ${(doc.order || []).join('; ')}. Los niveles son los de cada institución (SENAMHI, INDECI, DHN, IGP); el boletín no emite alertas propias ni calcula probabilidades: las de arriba son del ENFEN. Ante una emergencia, siga al INDECI, al SENAMHI y a su municipalidad.</p>
    </section>
    <footer class="bol-foot small muted">Observatorio ENSO Perú · datos abiertos: <a href="data/boletin.json">boletin.json</a> · <a href="#/noticias">mapa de alertas al momento</a></footer>
  </article>`;
}

function rulesCard(doc) {
  return html`<section class="card no-print" aria-labelledby="bol-rules-h" data-tour-id="boletin-rules"><h2 id="bol-rules-h">Cómo llega el boletín a quien no entra al sitio</h2>
    <p>Cada actualización arma una edición nueva solo si algo cambió. Un flujo de n8n lee <a href="data/boletin.json">boletin.json</a> cada hora y manda el correo con Gmail según estas reglas. El boletín se puede reenviar por WhatsApp con un toque (botón de arriba); el envío automático por WhatsApp queda para una segunda fase.</p>
    <div class="table-wrap"><table class="data bol-rules"><thead><tr><th scope="col">Situación</th><th scope="col">Qué se hace</th></tr></thead>
      <tbody>${(doc.rules || []).map((r) => html`<tr><td>${r.when}</td><td><span class="lvl lvl-s lvl-${TIER[r.tier]?.[1] || 'un'}">${TIER[r.tier]?.[0] || r.tier}</span></td></tr>`)}</tbody></table></div>
    <p class="muted small">El correo lleva el mismo boletín que esta página, con un mapa de cuadros que se ve en cualquier programa de correo. Para recibirlo, pida que lo agreguen a la lista. Configuración: <a href="https://github.com/PillB/observatorio-enso-peru/blob/main/docs/boletin.md" rel="noopener" target="_blank">docs/boletin.md</a>.</p>
    ${(doc.recent || []).length > 1 ? html`<details class="more"><summary>Ediciones anteriores y sus cambios</summary><ol class="bol-recent">${doc.recent.map((r) => html`<li><strong>N° ${r.edition}</strong> · ${when(r.at)}<ul>${(r.changes || []).map((c) => html`<li>${c.text}</li>`)}</ul></li>`)}</ol></details>` : ''}
  </section>`;
}

function depDetail(doc, code) {
  const s = doc.segments.find((x) => x.code === code);
  if (!s) return '';
  const events = Object.fromEntries((doc.events || []).map((e) => [e.key, e]));
  const evs = s.events.map((k) => events[k]).filter(Boolean);
  return html`<div class="bol-depcard"><div class="section-head"><strong>${s.position}. ${s.name}</strong> ${chip(s, true)}<button type="button" class="linkish" data-close>Cerrar</button></div>
    ${s.rank < 0 ? html`<p class="small">Ninguna institución tiene un aviso vigente o próximo relacionado con El Niño aquí. No quiere decir que no haya peligro.</p>`
      : html`<p class="small">${s.hazards.join(' · ')} · ${segWhen(s)}${s.places.length ? ` · ${joinEs(s.places.slice(0, 5))}` : ''}</p>
        <ul class="small">${evs.slice(0, 5).map((e) => html`<li><a href="${safeUrl(e.url)}" rel="noopener" target="_blank">${e.title}</a> <span class="muted">(${e.institution}, ${e.level || 'sin nivel'})</span></li>`)}</ul>`}
    <p class="small muted">CENEPRED: ${s.scenario.muyAlto} de ${s.scenario.districts} distritos en riesgo muy alto y ${s.scenario.alto} en alto. Daños reportados en 72 h: ${s.reports}. <a href="#/zona?area=${s.code}">Ver ${s.name} en Mi zona</a></p></div>`;
}

export const boletinView = {
  title: 'Boletín',
  render() {
    return html`<div class="page-head no-print"><div class="eyebrow">Boletín</div><h1>Boletín de eventos de El Niño</h1>
      <p>Una hoja con lo que viene, dónde y cuándo: arriba el país; abajo los diez departamentos más críticos. Lo arma cada actualización con los avisos oficiales, el ENFEN y el CENEPRED.</p>
      <div class="bol-actions" data-tour-id="boletin-actions">
        <button type="button" class="btn" id="bol-print">${raw(ICON.download)} Imprimir o guardar en PDF</button>
        <a class="btn ghost" id="bol-mail" href="data/boletin-correo.html" target="_blank" rel="noopener">Ver como correo</a>
        <a class="btn ghost" id="bol-wa" href="#" target="_blank" rel="noopener">Compartir por WhatsApp</a>
        <button type="button" class="btn ghost" id="bol-copy">Copiar resumen</button>
        <a class="btn ghost" href="data/csv/boletin-departamentos.csv" download>CSV de departamentos</a>
        <a class="btn ghost" href="data/csv/boletin-avisos.csv" download>CSV de avisos</a>
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
      $$('.bol-actions a, .bol-actions button').forEach((b) => { b.hidden = true; });
      return;
    }
    const geo = await fetch('assets/peru-map.json').then((r) => (r.ok ? r.json() : null)).catch(() => null);
    await abReady();
    const exp = ab('boletin');
    const st = { variant: exp.variant, sel: '', all: false };
    const now = Date.now();
    const draw = () => {
      const old = expiredSince(doc, now);
      root.innerHTML = String(html`${isOld(doc, now) ? html`<div class="notice notice-warn">${raw(ICON.clock)}<p>Esta edición es del ${when(doc.cutoff)}: la actualización diaria no corrió después. Lo de este momento está en el <a href="#/noticias">mapa de alertas</a>.</p></div>` : ''}
        ${old.length ? html`<p class="notice notice-info no-print">${raw(ICON.info)}<span>Desde el corte, ${old.length} ${old.length === 1 ? 'aviso de esta edición ya venció' : 'avisos de esta edición ya vencieron'}. La próxima edición sale con la actualización diaria; lo de este momento está en el <a href="#/noticias">mapa de alertas</a>.</span></p>` : ''}
        ${sheet(doc, geo, st.variant, st.sel, st.all)}${rulesCard(doc)}`);
      if (st.sel) $('#bol-dep').innerHTML = String(depDetail(doc, st.sel));
      exp.mark('view');
    };
    const pick = (code) => {
      st.sel = st.sel === code ? '' : code;
      exp.mark('select');
      draw();
      const row = st.sel && $(`.bol-row[data-dep="${st.sel}"]`, root);
      $$('.bol-row', root).forEach((r) => r.classList.toggle('on', r === row));
    };
    root.addEventListener('click', (ev) => {
      const t = ev.target;
      const v = t.closest('[data-variant]');
      if (v) { if (v.dataset.variant !== st.variant) { exp.choose(v.dataset.variant); st.variant = v.dataset.variant; draw(); } return; }
      if (t.closest('[data-close]')) { st.sel = ''; draw(); return; }
      if (t.closest('#bol-all')) { st.all = !st.all; draw(); return; }
      const d = t.closest('[data-dep]');
      if (d && (d.closest('.bol-svg') || d.closest('.bol-tiles'))) pick(d.dataset.dep);
      if (t.closest('.bol-evs summary') || t.closest('.bol-evs a')) exp.mark('detail');
    });
    root.addEventListener('keydown', (ev) => {
      const d = ev.target.closest?.('.bol-svg [data-dep]');
      if (d && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); pick(d.dataset.dep); }
    });
    root.addEventListener('mouseover', (ev) => { if (ev.target.closest?.('[data-dep]')) exp.mark('hover'); }, { passive: true });
    draw();
    const wa = $('#bol-wa');
    if (wa) wa.href = `https://wa.me/?text=${encodeURIComponent(doc.whatsapp || '')}`;
    $('#bol-print')?.addEventListener('click', () => window.print());
    $('#bol-copy')?.addEventListener('click', async () => {
      const msg = $('#bol-st');
      try { await navigator.clipboard.writeText(doc.whatsapp || ''); msg.textContent = 'Resumen copiado. Péguelo en WhatsApp o en un correo.'; } catch { msg.textContent = 'No se pudo copiar: use «Compartir por WhatsApp».'; }
    });
  },
};

