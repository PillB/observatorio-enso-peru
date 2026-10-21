// Mapa de las regiones Niño con su anomalía semanal medida (NOAA OISST).
// Cada caja se colorea con el valor de su región; no hay interpolación
// ni campo espacial inventado. La costa proviene de Natural Earth.

import { html, raw, esc, $ } from './lib/dom.js';
import * as F from './lib/format.js';
import { GEO } from './geo.js';
import { ICON } from './icons.js';

// Cajas oficiales (longitudes en °E, 0–360).
const REGIONS = [
  { id: 'nino4', name: 'Niño 4', lon: [160, 210], lat: [-5, 5] },
  { id: 'nino34', name: 'Niño 3.4', lon: [190, 240], lat: [-5, 5] },
  { id: 'nino3', name: 'Niño 3', lon: [210, 270], lat: [-5, 5] },
  { id: 'nino12', name: 'Niño 1+2', lon: [270, 280], lat: [-10, 0] },
];

// RdBu de ColorBrewer (apta para daltonismo), centrada en 0, pasos de 0,5 °C.
const STEPS = [-2, -1.5, -1, -0.5, 0.5, 1, 1.5, 2, 3, 4];
const COLORS = ['#053061', '#2166ac', '#4393c3', '#92c5de', '#f7f7f7', '#fddbc7', '#f4a582', '#d6604d', '#b2182b', '#67001f', '#3f0010'];
function color(v) {
  if (!F.isNum(v)) return 'none';
  let i = 0;
  while (i < STEPS.length && v > STEPS[i]) i++;
  return COLORS[i];
}

const px = (lon) => (lon - GEO.LON0) * GEO.K;
const py = (lat) => (GEO.LAT1 - lat) * GEO.K;

const VIEWS = { pacifico: `0 0 ${GEO.width} ${GEO.height}`, peru: `${px(250)} ${py(8)} ${px(290) - px(250)} ${py(-22) - py(8)}` };

export const mapView = {
  render() {
    return html`
      <div class="page-head"><div class="eyebrow">Mapa</div><h1>Regiones Niño en el Pacífico ecuatorial</h1>
        <p>Anomalía semanal de la temperatura superficial del mar en cada región Niño (NOAA OISST v2.1, base 1991–2020). Cada caja muestra el promedio medido de esa región; no es un mapa interpolado.</p></div>
      <section class="card map" data-tour-id="map" aria-labelledby="map-h">
        <div class="section-head"><h2 id="map-h">Semana del <span id="map-date">—</span></h2>
          <div class="seg" role="group" aria-label="Encuadre del mapa"><button type="button" data-view="pacifico" aria-pressed="true">Pacífico</button><button type="button" data-view="peru" aria-pressed="false">Costa del Perú</button></div></div>
        <div id="map-svg"></div>
        <div class="colorbar" aria-hidden="true"><span>−2 °C</span><span class="bar"></span><span>+4 °C</span></div>
        <div class="map-controls" data-tour-id="map-controls">
          <button type="button" class="btn ghost" id="map-play" aria-label="Reproducir animación">${raw(ICON.play)}<span>Reproducir</span></button>
          <label for="map-range" class="visually-hidden">Semana</label>
          <input type="range" id="map-range" min="0" max="0" value="0" step="1">
          <label for="map-speed" class="visually-hidden">Velocidad</label>
          <select id="map-speed" class="input input-s"><option value="900">Lenta</option><option value="450" selected>Normal</option><option value="200">Rápida</option></select>
        </div>
        <p class="muted small" id="map-status" role="status" aria-live="polite"></p>
        <details class="more"><summary>Ver los valores de esta semana en una tabla</summary><div id="map-table"></div></details>
        <p class="muted small">Costa: Natural Earth (dominio público). Proyección equirectangular. Cajas: Niño 1+2 (0°–10°S, 90°–80°O), Niño 3 (5°N–5°S, 150°–90°O), Niño 3.4 (5°N–5°S, 170°–120°O), Niño 4 (5°N–5°S, 160°E–150°O).</p>
      </section>`;
  },

  async after(load) {
    const wk = await load('weekly.json');
    const host = $('#map-svg');
    if (!wk?.regions) { host.textContent = 'Datos semanales no disponibles.'; return; }
    const dates = [...new Set(Object.values(wk.regions).flatMap((r) => r.points.map((p) => p.date)))].sort().slice(-52);
    const at = Object.fromEntries(Object.entries(wk.regions).map(([k, r]) => [k, new Map(r.points.map((p) => [p.date, p.value]))]));
    const range = $('#map-range');
    range.max = String(dates.length - 1);
    range.value = range.max;
    let view = 'pacifico';

    const draw = () => {
      const d = dates[+range.value];
      const grid = [];
      for (let lon = 120; lon <= 290; lon += 20) grid.push(`<line class="gridline" x1="${px(lon)}" x2="${px(lon)}" y1="0" y2="${GEO.height}"/><text class="gridlabel" x="${px(lon) + 3}" y="${GEO.height - 4}">${lon <= 180 ? `${lon}°E` : `${360 - lon}°O`}</text>`);
      for (const lat of [-20, -10, 0, 10, 20]) grid.push(`<line class="gridline" x1="0" x2="${GEO.width}" y1="${py(lat)}" y2="${py(lat)}"/><text class="gridlabel" x="3" y="${py(lat) - 3}">${lat === 0 ? 'Ecuador' : lat > 0 ? `${lat}°N` : `${-lat}°S`}</text>`);
      // Niño 3.4 se superpone con Niño 3 y Niño 4: se dibujan primero las
      // cajas 4 y 3 rellenas y encima Niño 3.4 con borde discontinuo.
      const labelAt = { nino4: [175, 7.5, 'middle'], nino3: [255, 7.5, 'middle'], nino34: [215, -8.5, 'middle'], nino12: [275, -13.5, 'middle'] };
      const order = ['nino4', 'nino3', 'nino34', 'nino12'];
      const boxes = order.map((id) => {
        const r = REGIONS.find((x) => x.id === id);
        const v = at[r.id]?.get(d);
        const x = px(r.lon[0]), y = py(r.lat[1]), w = px(r.lon[1]) - x, h = py(r.lat[0]) - y;
        const [lx, ly, anchor] = labelAt[id];
        const fill = id === 'nino34' ? `fill="${color(v)}" fill-opacity="0.55"` : `fill="${color(v)}" fill-opacity="0.92"`;
        return `<g><rect class="region ${id === 'nino34' ? 'region-overlay' : ''}" x="${x}" y="${y}" width="${w}" height="${h}" ${fill}><title>${esc(r.name)}: ${esc(F.fmtValue(v, 'degC'))}</title></rect>
          <text class="region-label" x="${px(lx)}" y="${py(ly)}" text-anchor="${anchor}">${esc(r.name)} <tspan class="region-value">${esc(F.fmtValue(v, 'degC'))}</tspan></text></g>`;
      }).join('');
      host.innerHTML = `<svg viewBox="${VIEWS[view]}" role="img" aria-labelledby="map-t"><title id="map-t">Mapa del Pacífico ecuatorial con las regiones Niño y su anomalía semanal del ${esc(F.fmtDate(d))}.</title>
        <defs><clipPath id="map-clip"><rect x="0" y="0" width="${GEO.width}" height="${GEO.height}"/></clipPath></defs>
        <g clip-path="url(#map-clip)"><rect class="ocean" x="0" y="0" width="${GEO.width}" height="${GEO.height}"/>${grid.join('')}
        <path class="land" d="${GEO.land}"/><path class="peru" d="${GEO.peru}"/></g>
        <text class="country-label" x="${px(284.5)}" y="${py(-11)}">PERÚ</text>${boxes}</svg>`;
      $('#map-date').textContent = F.fmtDate(d);
      $('#map-table').innerHTML = `<div class="table-wrap"><table><thead><tr><th scope="col">Región</th><th scope="col">Anomalía</th></tr></thead><tbody>${REGIONS.map((r) => `<tr><th scope="row">${esc(r.name)}</th><td>${esc(F.fmtValue(at[r.id]?.get(d), 'degC'))}</td></tr>`).join('')}</tbody></table></div>`;
    };
    draw();

    let timer = null;
    const play = $('#map-play');
    const stop = () => { clearInterval(timer); timer = null; if (!play.isConnected) return; play.innerHTML = `${ICON.play}<span>Reproducir</span>`; play.setAttribute('aria-label', 'Reproducir animación'); $('#map-status').textContent = 'Animación en pausa.'; };
    const start = () => {
      if (+range.value >= dates.length - 1) range.value = '0';
      play.innerHTML = `${ICON.pause}<span>Pausar</span>`; play.setAttribute('aria-label', 'Pausar animación');
      $('#map-status').textContent = `Mostrando ${dates.length} semanas, desde el ${F.fmtDate(dates[0])}.`;
      timer = setInterval(() => {
        if (+range.value >= dates.length - 1) { stop(); return; }
        range.value = String(+range.value + 1); draw();
      }, +$('#map-speed').value);
    };
    play.addEventListener('click', () => (timer ? stop() : start()));
    $('#map-speed').addEventListener('change', () => { if (timer) { stop(); start(); } });
    range.addEventListener('input', () => { if (timer) stop(); draw(); });
    document.querySelectorAll('[data-view]').forEach((b) => b.addEventListener('click', () => {
      view = b.dataset.view;
      document.querySelectorAll('[data-view]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      draw();
    }));
    window.addEventListener('hashchange', stop, { once: true });
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) $('#map-status').textContent = 'La animación avanza solo al pulsar Reproducir.';
  },
};
