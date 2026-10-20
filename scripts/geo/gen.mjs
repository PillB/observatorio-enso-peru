// Genera la costa del Pacífico tropical para public/assets/js/geo.js.
// Fuente: Natural Earth vía world-atlas@2.0.2 (land-110m; Perú de countries-50m).
// Proyección equirectangular en longitudes 0–360 °E. No se recortan los
// polígonos (el recorte deforma la costa): el SVG usa un clipPath.
import fs from 'fs';
import { feature } from 'topojson-client';
const K = 5, LON0 = 110, LON1 = 300, LAT0 = -25, LAT1 = 25, MIN = 1.2;
const W = (LON1 - LON0) * K, H = (LAT1 - LAT0) * K;
// Costura en 25°O (Atlántico): América queda continua en 0–360 °E y
// Eurasia/África no se parten en Greenwich.
const proj = ([lon, lat]) => [((lon < -25 ? lon + 360 : lon) - LON0) * K, (LAT1 - lat) * K];
function ringPath(ring) {
  const pts = [];
  for (const p of ring) {
    const q = proj(p);
    const l = pts[pts.length - 1];
    if (!l || Math.hypot(q[0] - l[0], q[1] - l[1]) > MIN) pts.push(q);
  }
  if (pts.length < 3) return '';
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const pad = 60;
  if (Math.max(...xs) < -pad || Math.min(...xs) > W + pad || Math.max(...ys) < -pad || Math.min(...ys) > H + pad) return '';
  // Un anillo que cruza la costura (salto de 360°) queda lejos de la
  // ventana (Groenlandia); se descarta para no dibujar cuerdas falsas.
  for (let i = 1; i < pts.length; i++) if (Math.abs(pts[i][0] - pts[i - 1][0]) > K * 180) return '';
  return pts.map((q, i) => (i ? 'L' : 'M') + q[0].toFixed(0) + ' ' + q[1].toFixed(0)).join('') + 'Z';
}
const geomPath = (g) => (g.type === 'Polygon' ? [g.coordinates] : g.coordinates).map((p) => p.map(ringPath).join('')).join('');
const land = JSON.parse(fs.readFileSync('node_modules/world-atlas/land-110m.json'));
const d = feature(land, land.objects.land).features.map((f) => geomPath(f.geometry)).join('');
const c = JSON.parse(fs.readFileSync('node_modules/world-atlas/countries-50m.json'));
const peru = feature(c, c.objects.countries).features.find((f) => f.id === '604' || f.properties.name === 'Peru');
fs.writeFileSync('pacific.json', JSON.stringify({ K, LON0, LON1, LAT0, LAT1, width: W, height: H, land: d, peru: geomPath(peru.geometry) }));
console.log(d.length);
