// Gráficos SVG accesibles y sin dependencias.
//
// timeChart(el, spec) dibuja series temporales con:
//   - eje temporal con marcas adaptativas (años o meses),
//   - bandas de umbral y líneas de referencia,
//   - relleno de anomalía cálida/fría (rojo sobre cero, azul bajo cero),
//   - cursor con tooltip por puntero y por teclado (flechas, Inicio, Fin),
//   - redibujo al cambiar el tamaño del contenedor.
// El SVG lleva role="img" y una descripción; la tabla accesible se genera
// aparte con dataTable().

import { esc } from './dom.js';
import { fmtValue, fmtMonth, fmtDateShort, MES_CORTO, isNum } from './format.js';

let uid = 0;

export function niceTicks(min, max, count = 5) {
  const span = max - min || 1;
  const step0 = span / count;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const err = step0 / mag;
  const step = (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1) * mag;
  const ticks = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) ticks.push(+v.toFixed(10));
  return ticks;
}

function timeTicks(t0, t1, width) {
  const years = (t1 - t0) / (365.25 * 864e5);
  const maxTicks = Math.max(2, Math.floor(width / 70));
  const out = [];
  if (years > 2.5) {
    const steps = [1, 2, 5, 10, 20, 25, 50];
    const step = steps.find((s) => years / s <= maxTicks) || 100;
    const y0 = new Date(t0).getUTCFullYear();
    const y1 = new Date(t1).getUTCFullYear();
    for (let y = Math.ceil(y0 / step) * step; y <= y1; y += step) {
      const t = Date.UTC(y, 0, 1);
      if (t >= t0 && t <= t1) out.push({ t, label: String(y) });
    }
  } else {
    const months = years * 12;
    const step = [1, 2, 3, 6].find((s) => months / s <= maxTicks) || 12;
    const d = new Date(t0);
    let y = d.getUTCFullYear();
    let m = d.getUTCMonth() + 1;
    for (; Date.UTC(y, m, 1) <= t1; m++) {
      if (m > 11) { m = 0; y++; }
      if (m % step === 0) {
        const t = Date.UTC(y, m, 1);
        if (t >= t0 && t <= t1) out.push({ t, label: m === 0 ? String(y) : MES_CORTO[m] });
      }
    }
  }
  return out;
}

/** Convierte puntos {month|date, value} a {t, v}. */
export function toXY(points, key = 'month') {
  const out = [];
  for (const p of points || []) {
    const s = p[key] ?? p.month ?? p.date;
    const m = /^(\d{4})-(\d{2})(?:-(\d{2}))?/.exec(s || '');
    if (!m) continue;
    const t = m[3] ? Date.UTC(+m[1], +m[2] - 1, +m[3]) : Date.UTC(+m[1], +m[2] - 1, 15);
    out.push({ t, v: isNum(p.value) ? p.value : null, flag: p.flag, label: s });
  }
  return out;
}

export function timeChart(el, spec) {
  const id = `c${++uid}`;
  const state = { idx: null };
  const draw = () => render(el, spec, id, state);
  draw();
  if ('ResizeObserver' in window) {
    let w = el.clientWidth;
    const ro = new ResizeObserver(() => {
      if (Math.abs(el.clientWidth - w) > 4) { w = el.clientWidth; draw(); }
    });
    ro.observe(el);
    el._ro?.disconnect();
    el._ro = ro;
  }
  return { redraw: draw };
}

function render(el, spec, id, state) {
  const series = spec.series.filter((s) => s.points?.length);
  const width = Math.max(280, el.clientWidth || 640);
  const height = spec.height || (width < 520 ? 220 : 300);
  const compact = width < 520;
  const m = { l: compact ? 38 : 48, r: 12, t: 12, b: 28 };
  const pw = width - m.l - m.r;
  const ph = height - m.t - m.b;

  if (!series.length) {
    el.innerHTML = `<p class="chart-empty">Sin datos observados para este periodo.</p>`;
    return;
  }

  let t0 = Infinity, t1 = -Infinity, v0 = Infinity, v1 = -Infinity;
  for (const s of series) for (const p of s.points) {
    if (p.t < t0) t0 = p.t;
    if (p.t > t1) t1 = p.t;
    if (p.v !== null) { v0 = Math.min(v0, p.v); v1 = Math.max(v1, p.v); }
  }
  if (spec.domain) { t0 = Math.max(t0, spec.domain[0]); }
  for (const b of spec.bands || []) {
    if (isNum(b.from) && b.from > v0 - 2 && b.from < v1 + 2) { v0 = Math.min(v0, b.from); v1 = Math.max(v1, b.from); }
  }
  for (const r of spec.refLines || []) { v0 = Math.min(v0, r.v); v1 = Math.max(v1, r.v); }
  if (spec.includeZero !== false) { v0 = Math.min(v0, 0); v1 = Math.max(v1, 0); }
  const pad = (v1 - v0) * 0.08 || 0.5;
  v0 -= pad; v1 += pad;
  const yt = niceTicks(v0, v1, compact ? 4 : 6);
  v0 = Math.min(v0, yt[0]); v1 = Math.max(v1, yt[yt.length - 1]);

  const sx = (t) => m.l + ((t - t0) / (t1 - t0 || 1)) * pw;
  const sy = (v) => m.t + ((v1 - v) / (v1 - v0 || 1)) * ph;
  const y0 = sy(Math.max(v0, Math.min(v1, 0)));

  let svg = `<svg class="chart" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img" aria-labelledby="${id}-t" tabindex="0" focusable="true">`;
  describe.pl = spec.periodLabel;
  svg += `<title id="${id}-t">${esc(spec.title || 'Serie temporal')}. ${esc(describe(series, spec.units))} Use las flechas para recorrer los valores.</title>`;
  svg += `<defs><clipPath id="${id}-plot"><rect x="${m.l}" y="${m.t}" width="${pw}" height="${ph}"/></clipPath>`;
  svg += `<clipPath id="${id}-pos"><rect x="${m.l}" y="${m.t}" width="${pw}" height="${Math.max(0, y0 - m.t)}"/></clipPath>`;
  svg += `<clipPath id="${id}-neg"><rect x="${m.l}" y="${y0}" width="${pw}" height="${Math.max(0, m.t + ph - y0)}"/></clipPath></defs>`;

  // Bandas
  svg += `<g clip-path="url(#${id}-plot)">`;
  for (const b of spec.bands || []) {
    const top = sy(isNum(b.to) ? Math.min(b.to, v1) : v1);
    const bot = sy(isNum(b.from) ? Math.max(b.from, v0) : v0);
    if (bot - top > 0) svg += `<rect class="band band-${esc(b.tone || 'neutral')}" x="${m.l}" y="${top}" width="${pw}" height="${bot - top}"><title>${esc(b.label || '')}</title></rect>`;
  }
  svg += `</g>`;

  // Rejilla y ejes
  svg += `<g class="grid">`;
  for (const v of yt) svg += `<line x1="${m.l}" x2="${m.l + pw}" y1="${sy(v)}" y2="${sy(v)}"/>`;
  svg += `</g><g class="axis axis-y">`;
  for (const v of yt) svg += `<text x="${m.l - 6}" y="${sy(v) + 4}" text-anchor="end">${esc(fmtValue(v, spec.units, { unit: false, digits: Math.abs(yt[1] - yt[0]) < 1 ? 1 : 0 }))}</text>`;
  svg += `</g><g class="axis axis-x">`;
  const ticks = spec.xLabel ? niceTimeTicks(t0, t1, pw, spec.xLabel) : timeTicks(t0, t1, pw);
  for (const tk of ticks) svg += `<line x1="${sx(tk.t)}" x2="${sx(tk.t)}" y1="${m.t + ph}" y2="${m.t + ph + 4}"/><text x="${sx(tk.t)}" y="${height - 8}" text-anchor="middle">${esc(tk.label)}</text>`;
  svg += `</g>`;
  if (v0 < 0 && v1 > 0) svg += `<line class="zero" x1="${m.l}" x2="${m.l + pw}" y1="${y0}" y2="${y0}"/>`;
  for (const r of spec.refLines || []) svg += `<g class="ref ref-${esc(r.tone || 'neutral')}"><line x1="${m.l}" x2="${m.l + pw}" y1="${sy(r.v)}" y2="${sy(r.v)}"/>${compact ? '' : `<text x="${m.l + pw - 4}" y="${sy(r.v) - 4}" text-anchor="end">${esc(r.label || '')}</text>`}</g>`;

  // Series
  svg += `<g clip-path="url(#${id}-plot)">`;
  series.forEach((s, si) => {
    const segs = segments(s.points);
    const line = segs.map((seg) => seg.map((p, i) => `${i ? 'L' : 'M'}${sx(p.t).toFixed(1)},${sy(p.v).toFixed(1)}`).join('')).join('');
    if (s.fill === 'anomaly' || (spec.fill && si === 0)) {
      const area = segs.map((seg) => `M${sx(seg[0].t).toFixed(1)},${y0}` + seg.map((p) => `L${sx(p.t).toFixed(1)},${sy(p.v).toFixed(1)}`).join('') + `L${sx(seg[seg.length - 1].t).toFixed(1)},${y0}Z`).join('');
      const [up, down] = spec.invertFill ? ['area-cool', 'area-warm'] : ['area-warm', 'area-cool'];
      svg += `<path class="${up}" clip-path="url(#${id}-pos)" d="${area}"/><path class="${down}" clip-path="url(#${id}-neg)" d="${area}"/>`;
    }
    const prelim = s.points.filter((p) => p.flag === 'preliminary' && p.v !== null);
    svg += `<path class="line s${si} ${s.dashed ? 'dashed' : ''}" d="${line}"/>`;
    if (prelim.length && prelim.length < 30) for (const p of prelim) svg += `<circle class="prelim" cx="${sx(p.t)}" cy="${sy(p.v)}" r="2.6"><title>Preliminar</title></circle>`;
  });
  svg += `</g>`;

  // Último valor
  const main = series[0];
  const last = [...main.points].reverse().find((p) => p.v !== null);
  if (last) svg += `<circle class="last-dot" cx="${sx(last.t)}" cy="${sy(last.v)}" r="4"/>`;

  svg += `<g class="cursor" hidden><line class="cursor-line" y1="${m.t}" y2="${m.t + ph}"/>${series.map((_, si) => `<circle class="cursor-dot s${si}" r="4"/>`).join('')}</g>`;
  svg += `<rect class="hit" x="${m.l}" y="${m.t}" width="${pw}" height="${ph}" fill="transparent"/>`;
  svg += `</svg>`;

  el.innerHTML = `<div class="chart-wrap">${svg}<div class="tooltip" role="status" aria-live="polite" hidden></div></div>`;
  if (spec.legend !== false && series.length > 1) {
    el.insertAdjacentHTML('beforeend', `<ul class="legend">${series.map((s, si) => `<li><span class="sw s${si} ${s.dashed ? 'dashed' : ''}"></span>${esc(s.label)}</li>`).join('')}</ul>`);
  }
  interact(el, series, spec, { sx, sy, m, pw, state });
}

function niceTimeTicks(t0, t1, width, fmt) {
  const n = Math.max(2, Math.floor(width / 70));
  const step = (t1 - t0) / n;
  return Array.from({ length: n + 1 }, (_, i) => ({ t: t0 + i * step, label: fmt(t0 + i * step) }));
}

function segments(points) {
  const segs = [];
  let cur = [];
  let prevT = null;
  for (const p of points) {
    const gap = prevT !== null && p.t - prevT > 75 * 864e5 && points.length > 30 && p.t - prevT > 3 * avgStep(points);
    if (p.v === null || gap) { if (cur.length) segs.push(cur); cur = []; }
    if (p.v !== null) cur.push(p);
    prevT = p.t;
  }
  if (cur.length) segs.push(cur);
  return segs;
}

function avgStep(points) {
  if (points._step) return points._step;
  const n = points.length;
  points._step = n > 1 ? (points[n - 1].t - points[0].t) / (n - 1) : 864e5;
  return points._step;
}

function describe(series, units) {
  const s = series[0];
  const vals = s.points.filter((p) => p.v !== null);
  if (!vals.length) return '';
  const last = vals[vals.length - 1];
  const max = vals.reduce((a, b) => (b.v > a.v ? b : a));
  const min = vals.reduce((a, b) => (b.v < a.v ? b : a));
  const lb = (p) => (describe.pl ? describe.pl(p.label) : label(p));
  return `${s.label}: último valor ${fmtValue(last.v, units)} (${lb(last)}); máximo ${fmtValue(max.v, units)} (${lb(max)}); mínimo ${fmtValue(min.v, units)} (${lb(min)}).`;
}

function label(p) {
  return /^\d{4}-\d{2}-\d{2}/.test(p.label) ? fmtDateShort(p.label) : fmtMonth(p.label);
}

function interact(el, series, spec, { sx, sy, pw, m, state }) {
  const svg = el.querySelector('svg');
  const tip = el.querySelector('.tooltip');
  const cursor = svg.querySelector('.cursor');
  const main = series[0].points;
  const show = (i) => {
    if (i === null || !main[i]) { cursor.hidden = true; tip.hidden = true; return; }
    state.idx = i;
    const p = main[i];
    const x = sx(p.t);
    cursor.hidden = false;
    const ln = cursor.querySelector('.cursor-line');
    ln.setAttribute('x1', x); ln.setAttribute('x2', x);
    const rows = series.map((s, si) => {
      const q = nearest(s.points, p.t);
      const dot = cursor.querySelectorAll('.cursor-dot')[si];
      if (q && q.v !== null) { dot.setAttribute('cx', sx(q.t)); dot.setAttribute('cy', sy(q.v)); dot.style.display = ''; }
      else dot.style.display = 'none';
      return `<div class="tt-row"><span class="sw s${si}"></span><span>${esc(s.label)}</span><strong>${q ? esc(fmtValue(q.v, spec.units)) : 'N/D'}</strong></div>`;
    }).join('');
    const flag = p.flag === 'preliminary' ? ' · preliminar' : '';
    tip.innerHTML = `<div class="tt-date">${esc(spec.periodLabel ? spec.periodLabel(p.label) : label(p))}${flag}</div>${rows}`;
    tip.hidden = false;
    const box = svg.getBoundingClientRect();
    const scale = box.width / (pw + m.l + m.r);
    const left = x * scale;
    tip.style.left = `${Math.min(Math.max(left, 70), box.width - 70)}px`;
  };
  const idxAt = (clientX) => {
    const box = svg.getBoundingClientRect();
    const scale = box.width / (pw + m.l + m.r);
    const x = (clientX - box.left) / scale;
    let best = 0, bd = Infinity;
    // búsqueda binaria por tiempo
    let lo = 0, hi = main.length - 1;
    const t = main[0].t + ((x - m.l) / pw) * (main[main.length - 1].t - main[0].t);
    while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (main[mid].t < t) lo = mid; else hi = mid; }
    for (const i of [lo, hi]) { const d = Math.abs(main[i].t - t); if (d < bd) { bd = d; best = i; } }
    return best;
  };
  svg.addEventListener('pointermove', (e) => show(idxAt(e.clientX)));
  svg.addEventListener('pointerleave', () => { if (document.activeElement !== svg) show(null); });
  svg.addEventListener('blur', () => show(null));
  svg.addEventListener('focus', () => show(state.idx ?? lastIndex(main)));
  svg.addEventListener('keydown', (e) => {
    const n = main.length;
    let i = state.idx ?? lastIndex(main);
    const step = e.shiftKey ? 12 : 1;
    if (e.key === 'ArrowLeft') i = Math.max(0, i - step);
    else if (e.key === 'ArrowRight') i = Math.min(n - 1, i + step);
    else if (e.key === 'Home') i = 0;
    else if (e.key === 'End') i = lastIndex(main);
    else if (e.key === 'Escape') { show(null); return; }
    else return;
    e.preventDefault();
    show(i);
  });
}

function lastIndex(points) {
  for (let i = points.length - 1; i >= 0; i--) if (points[i].v !== null) return i;
  return points.length - 1;
}

function nearest(points, t) {
  let lo = 0, hi = points.length - 1;
  if (hi < 0) return null;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (points[mid].t < t) lo = mid; else hi = mid; }
  const p = Math.abs(points[lo].t - t) <= Math.abs(points[hi].t - t) ? points[lo] : points[hi];
  return Math.abs(p.t - t) < 40 * 864e5 ? p : null;
}

/** Mini gráfico de tendencia para tarjetas (no interactivo). */
export function sparkline(values, { width = 120, height = 32, tone = 'auto' } = {}) {
  const pts = values.filter((v) => isNum(v[1]));
  if (pts.length < 2) return '';
  const vs = pts.map((p) => p[1]);
  let lo = Math.min(...vs, 0), hi = Math.max(...vs, 0);
  if (hi - lo < 0.2) { hi += 0.1; lo -= 0.1; }
  const sx = (i) => 2 + (i / (pts.length - 1)) * (width - 4);
  const sy = (v) => 2 + ((hi - v) / (hi - lo)) * (height - 4);
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${sx(i).toFixed(1)},${sy(p[1]).toFixed(1)}`).join('');
  const last = vs[vs.length - 1];
  const cls = tone === 'auto' ? (last > 0 ? 'warm' : last < 0 ? 'cool' : 'neutral') : tone;
  return `<svg class="spark spark-${cls}" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" aria-hidden="true"><line class="spark-zero" x1="0" x2="${width}" y1="${sy(0)}" y2="${sy(0)}"/><path d="${d}"/><circle cx="${sx(pts.length - 1)}" cy="${sy(last)}" r="2.5"/></svg>`;
}

/** Tabla accesible de los últimos n valores de una o varias series. */
export function dataTable(series, units, { n = 24, periodLabel } = {}) {
  const main = series[0].points.filter((p) => p.v !== null).slice(-n).reverse();
  const head = `<tr><th scope="col">Periodo</th>${series.map((s) => `<th scope="col">${esc(s.label)}</th>`).join('')}</tr>`;
  const rows = main.map((p) => `<tr><th scope="row">${esc(periodLabel ? periodLabel(p.label) : label(p))}${p.flag === 'preliminary' ? ' <span class="tag">prelim.</span>' : ''}</th>${series.map((s) => { const q = nearest(s.points, p.t); return `<td>${esc(q ? fmtValue(q.v, units) : 'N/D')}</td>`; }).join('')}</tr>`).join('');
  return `<div class="table-wrap"><table class="data"><thead>${head}</thead><tbody>${rows}</tbody></table></div>`;
}
