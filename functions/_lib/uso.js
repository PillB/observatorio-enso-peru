// Medición anónima del uso del sitio por versión (public/assets/js/sitio.js), para el tablero de la consola.
//
// Corre como Pages Function con la base D1 de la consola (GEO_DB), en la tabla uso_daily. No guarda datos
// personales: ni IP, ni identificador de visitante, ni cookies, ni la página de origen. Cada visita manda, al
// ocultarse o cerrarse la página, un resumen de lo que hizo desde el envío anterior; aquí solo se suman números a
// contadores por (día, versión del sitio, medida, clave). Rutas, bajo /api/uso/:
//
//   POST e      {s: 'B', n: 1, vb: '2', rb: '1-7', v: {noticias: 2}, t: {noticias: 95}, u: {memoria: 1},
//                c: [['sitio', 'A', 'B']]}. Mismo origen; 202 aunque no se guarde (sin base o tope diario).
//   GET  stats  ?days=30 → filas {day, site, dim, key, n} y totales. Solo con una sesión de la consola de revisores
//               (la cookie de /api/geo/login); sin ella, 401.
//
// Medidas (dim) y claves (key):
//   sesion   nueva       sesiones nuevas (30 min sin actividad cierran una sesión, en el navegador)
//   visita   1 · 2 · 3-5 · 6-10 · 11+     número de sesión de ese navegador (cuántas veces volvió)
//   vuelta   hoy · 1-7 · 8-30 · 31+       días desde la sesión anterior, para quien vuelve
//   vista    pestaña     veces que se abrió
//   seg      pestaña     segundos con la página visible y en uso (sin 60 s de inactividad)
//   abrir    pestaña     secciones plegadas o listas cortadas que se abrieron (versión B)
//   cambio   exp:de>a    versiones que se cambiaron en el selector o en la pestaña (sitio, mapa, memoria…)
//
// El plan gratuito de D1 (100 000 filas escritas al día) es por cuenta y lo comparten la consola y /api/ab/: cada
// envío escribe a lo sumo MAX_ROWS filas y hay un tope de filas por día (ROW_CAP), contado en una fila propia.

import { currentSession } from './geo-console.js';
import { EXPERIMENTS } from './ab.js';

export const SITES = ['A', 'B'];
export const ROUTES = ['resumen', 'boletin', 'costero', 'pacifico', 'oceano', 'mapa', 'historia', 'memoria', 'zona', 'noticias', 'datos', 'metodologia', 'asistente', 'variantes'];
export const VISITS = ['1', '2', '3-5', '6-10', '11+'];
export const GAPS = ['hoy', '1-7', '8-30', '31+'];
export const DIMS = ['sesion', 'visita', 'vuelta', 'vista', 'seg', 'abrir', 'cambio'];
export const ROW_CAP = 30000;
export const MAX_ROWS = 40;
export const MAX_SECS = 1800; // por pestaña y envío: una visita se manda al ocultarse, y 30 min sin ocultarse es raro
const MAX_VIEWS = 50;
const MAX_BODY = 2048;
const MAX_DAYS = 120;
const META = ['_', '_', 'filas']; // (site, dim, key) del contador de filas escritas en el día

const SCHEMA = [`CREATE TABLE IF NOT EXISTS uso_daily (day TEXT NOT NULL, site TEXT NOT NULL, dim TEXT NOT NULL, key TEXT NOT NULL,
  n INTEGER NOT NULL, PRIMARY KEY (day, site, dim, key))`];

const HEADERS = {
  'Content-Type': 'application/json; charset=utf-8',
  'Cache-Control': 'no-store',
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'X-Robots-Tag': 'noindex, nofollow',
};
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: HEADERS });
const today = () => new Date().toISOString().slice(0, 10);

let schemaReady = false;
export function resetSchemaCache() { schemaReady = false; }
async function ensureSchema(db) {
  if (schemaReady) return;
  await db.batch(SCHEMA.map((s) => db.prepare(s)));
  schemaReady = true;
}

function sameOrigin(request, url) {
  const origin = request.headers.get('Origin');
  if (origin) return origin === url.origin;
  return request.headers.get('Sec-Fetch-Site') === 'same-origin';
}

const isObj = (x) => x && typeof x === 'object' && !Array.isArray(x);
const count = (x, max) => (Number.isFinite(x) && x > 0 ? Math.min(Math.round(x), max) : 0);

/** Valida un envío y lo convierte en filas [dim, key, n]. null si no es válido. */
export function parseUsage(text) {
  if (typeof text !== 'string' || text.length > MAX_BODY) return null;
  let b;
  try { b = JSON.parse(text); } catch { return null; }
  if (!isObj(b) || !SITES.includes(b.s)) return null;
  const rows = [];
  if (b.n === 1) {
    rows.push(['sesion', 'nueva', 1]);
    if (VISITS.includes(b.vb)) rows.push(['visita', b.vb, 1]);
    if (GAPS.includes(b.rb)) rows.push(['vuelta', b.rb, 1]);
  }
  for (const [dim, field, max] of [['vista', 'v', MAX_VIEWS], ['seg', 't', MAX_SECS], ['abrir', 'u', MAX_VIEWS]]) {
    if (b[field] === undefined) continue;
    if (!isObj(b[field])) return null;
    for (const [k, x] of Object.entries(b[field])) {
      const n = count(x, max);
      if (ROUTES.includes(k) && n) rows.push([dim, k, n]);
    }
  }
  if (b.c !== undefined) {
    if (!Array.isArray(b.c)) return null;
    const seen = new Set();
    for (const ch of b.c.slice(0, 8)) {
      if (!Array.isArray(ch) || ch.length !== 3) continue;
      const [x, from, to] = ch;
      const vs = EXPERIMENTS[x];
      if (!Object.hasOwn(EXPERIMENTS, x) || !vs.includes(from) || !vs.includes(to) || from === to) continue;
      const key = `${x}:${from}>${to}`;
      if (!seen.has(key)) { seen.add(key); rows.push(['cambio', key, 1]); }
    }
  }
  return rows.length ? { site: b.s, rows: rows.slice(0, MAX_ROWS) } : null;
}

async function record(request, env, url) {
  if (!sameOrigin(request, url)) return json({ error: 'Origen no permitido.' }, 403);
  const ev = parseUsage(await request.text());
  if (!ev) return json({ error: 'Envío no válido.' }, 400);
  const db = env.GEO_DB;
  if (!db) return json({ ok: true, stored: false }, 202);
  await ensureSchema(db);
  const day = today();
  const used = await db.prepare('SELECT n FROM uso_daily WHERE day = ? AND site = ? AND dim = ? AND key = ?').bind(day, ...META).first('n');
  if ((used || 0) + ev.rows.length > ROW_CAP) return json({ ok: true, stored: false, reason: 'tope diario' }, 202);
  const up = db.prepare(`INSERT INTO uso_daily (day, site, dim, key, n) VALUES (?, ?, ?, ?, ?)
    ON CONFLICT (day, site, dim, key) DO UPDATE SET n = n + excluded.n`);
  await db.batch([...ev.rows.map(([dim, key, n]) => up.bind(day, ev.site, dim, key, n)), up.bind(day, ...META, ev.rows.length + 1)]);
  return json({ ok: true, stored: true }, 202);
}

const sinceDay = (days) => new Date(Date.now() - (days - 1) * 864e5).toISOString().slice(0, 10);

/** Totales por versión: {A: {sesion: {nueva: n}, seg: {noticias: s}, …}, B: …}. */
export function totals(rows) {
  const out = Object.fromEntries(SITES.map((s) => [s, Object.fromEntries(DIMS.map((d) => [d, {}]))]));
  for (const r of rows) {
    if (!out[r.site]?.[r.dim]) continue;
    out[r.site][r.dim][r.key] = (out[r.site][r.dim][r.key] || 0) + r.n;
  }
  return out;
}

async function stats(request, env, url) {
  const db = env.GEO_DB;
  if (!db) return json({ available: false, days: 0, rows: [], totals: totals([]) });
  let session = null;
  try { session = await currentSession(request, env); } catch { session = null; } // sin tabla de sesiones todavía
  if (!session) return json({ error: 'Ingrese a la consola para ver la analítica.' }, 401);
  const days = Math.max(1, Math.min(MAX_DAYS, Number(url.searchParams.get('days')) || 30));
  await ensureSchema(db);
  const since = sinceDay(days);
  const { results } = await db.prepare("SELECT day, site, dim, key, n FROM uso_daily WHERE day >= ? AND site != '_' ORDER BY day").bind(since).all();
  return json({ available: true, days, since, sites: SITES, routes: ROUTES, rows: results, totals: totals(results) });
}

export async function handle(request, env = {}) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/^\/api\/uso\/?/, '').replace(/\/$/, '');
  try {
    if (path === 'e' && request.method === 'POST') return await record(request, env, url);
    if (path === 'stats' && request.method === 'GET') return await stats(request, env, url);
    return json({ error: 'No encontrado.' }, 404);
  } catch (e) {
    console.error(e);
    return json({ error: 'Error interno.' }, 500);
  }
}
