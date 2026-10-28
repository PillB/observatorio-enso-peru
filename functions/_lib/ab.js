// Analítica de las versiones de los mapas: el de alertas de Noticias («Versión A / B / C / D»), la vista que abre el
// mapa de la memoria (resumen o uno de sus detalles) y la que abre el mapa de Noticias (resumen o detalle).
//
// Corre como Pages Function con la misma base D1 de la consola de lugares (GEO_DB), en una tabla propia.
// No guarda datos personales: ni IP, ni identificador de visitante, ni cookies. Cada visita manda, al salir
// de la página, una sola solicitud por experimento con la versión que vio y qué hizo (vio, pasó el cursor,
// filtró…), y aquí solo se suma 1 a un contador por día, experimento, versión y evento. Rutas, bajo /api/ab/:
//
//   POST e         {x: 'memoria', v: 'cuencas', e: ['view', 'hover', …]} → suma 1 a cada (día, x, v, evento). Sin x,
//                  el mapa de alertas (lo que mandaban las páginas anteriores). Mismo origen.
//   GET  stats     ?days=30 → contadores por día y totales por experimento y versión, con la decisión de cada uno
//                  (esta, con los últimos DECIDE_DAYS días, como defaults).
//   GET  defaults  → {mapa: 'B' | null, memoria: …, noticias: …}: la versión que ganó, que el sitio muestra a la
//                  mayoría de quienes llegan por primera vez (ab.js). Se guarda una hora en el borde.
//
// La decisión (decide): la tasa de uso de cada versión, las visitas en las que la persona hizo algo con el mapa
// (filtró o abrió algo: el evento «use») sobre las visitas que la vieron, con su intervalo de Wilson al 95 %.
// Gana una versión solo si todas tienen al menos MIN_VIEWS visitas y el límite inferior de su intervalo supera el
// límite superior de todas las demás. Mientras no haya ganadora, cada versión sale con la misma probabilidad.
//
// La base la comparte la consola, y el plan gratuito de D1 (100 000 filas escritas por día) es por cuenta:
// por eso cada solicitud escribe como mucho una fila por evento, se acepta un solo envío por evento y hay un
// tope diario de sumas (DAILY_CAP) para que una avalancha de solicitudes no deje sin escrituras a la consola.
// Si GEO_DB no está vinculada, la API responde sin hacer nada.

export const EXPERIMENTS = {
  mapa: ['A', 'B', 'C', 'D'],
  memoria: ['resumen', 'cuencas', 'puntos', 'riesgo'],
  noticias: ['resumen', 'cuencas', 'distritos'],
};
export const VARIANTS = EXPERIMENTS.mapa;
// view: vio la versión · chosen: la vio siendo su versión elegida · hover: pasó el cursor o tocó una región
// select: filtró o eligió un área desde el mapa · detail: abrió un aviso, una ficha o un registro desde el mapa
// use: hizo select o detail (la tasa que decide) · choose: la eligió en el selector · leave: la dejó por otra
// keep: volvió otro día y sigue con la versión que eligió.
export const EVENTS = ['view', 'chosen', 'hover', 'select', 'detail', 'use', 'choose', 'leave', 'keep'];
export const DAILY_CAP = 20000;
export const MIN_VIEWS = 200;
const Z = 1.959964;
const MAX_BODY = 512;
const MAX_DAYS = 120;
const DECIDE_DAYS = 60;

// ab_daily: la tabla del mapa de alertas antes de que hubiera más experimentos; se sigue leyendo, ya no se escribe.
const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS ab_daily (day TEXT NOT NULL, variant TEXT NOT NULL, event TEXT NOT NULL,
  n INTEGER NOT NULL, PRIMARY KEY (day, variant, event))`,
  `CREATE TABLE IF NOT EXISTS ab_exp (day TEXT NOT NULL, exp TEXT NOT NULL, variant TEXT NOT NULL, event TEXT NOT NULL,
  n INTEGER NOT NULL, PRIMARY KEY (day, exp, variant, event))`,
];

const HEADERS = {
  'Content-Type': 'application/json; charset=utf-8',
  'Cache-Control': 'no-store',
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'X-Robots-Tag': 'noindex, nofollow',
};

const json = (body, status = 200, extra = {}) => new Response(JSON.stringify(body), { status, headers: { ...HEADERS, ...extra } });
const today = () => new Date().toISOString().slice(0, 10);

let schemaReady = false;
export function resetSchemaCache() { schemaReady = false; }

async function ensureSchema(db) {
  if (schemaReady) return;
  await db.batch(SCHEMA.map((s) => db.prepare(s)));
  schemaReady = true;
}

/** Solo desde el propio sitio: el navegador manda Origin en un POST, o Sec-Fetch-Site. */
function sameOrigin(request, url) {
  const origin = request.headers.get('Origin');
  if (origin) return origin === url.origin;
  return request.headers.get('Sec-Fetch-Site') === 'same-origin';
}

export function parseEvent(text) {
  if (typeof text !== 'string' || text.length > MAX_BODY) return null;
  let body;
  try { body = JSON.parse(text); } catch { return null; }
  if (!body || typeof body !== 'object' || !Array.isArray(body.e)) return null;
  const exp = body.x === undefined ? 'mapa' : body.x;
  if (!Object.hasOwn(EXPERIMENTS, exp) || !EXPERIMENTS[exp].includes(body.v)) return null;
  const events = [...new Set(body.e.filter((x) => EVENTS.includes(x)))];
  return events.length ? { exp, variant: body.v, events } : null;
}

async function record(request, env, url) {
  if (!sameOrigin(request, url)) return json({ error: 'Origen no permitido.' }, 403);
  const text = await request.text();
  const ev = parseEvent(text);
  if (!ev) return json({ error: 'Evento no válido.' }, 400);
  const db = env.GEO_DB;
  if (!db) return json({ ok: true, stored: false }, 202);
  await ensureSchema(db);
  const day = today();
  const used = await db.prepare(`SELECT (SELECT COALESCE(SUM(n), 0) FROM ab_exp WHERE day = ?1)
    + (SELECT COALESCE(SUM(n), 0) FROM ab_daily WHERE day = ?1) AS n`).bind(day).first('n');
  if (used + ev.events.length > DAILY_CAP) return json({ ok: true, stored: false, reason: 'tope diario' }, 202);
  const up = db.prepare(`INSERT INTO ab_exp (day, exp, variant, event, n) VALUES (?, ?, ?, ?, 1)
    ON CONFLICT (day, exp, variant, event) DO UPDATE SET n = n + 1`);
  await db.batch(ev.events.map((e) => up.bind(day, ev.exp, ev.variant, e)));
  return json({ ok: true, stored: true }, 202);
}

/** Intervalo de Wilson al 95 % de y éxitos en t intentos. */
export function wilson(y, t) {
  if (!t) return [0, 1];
  const p = y / t, den = 1 + (Z * Z) / t;
  const centre = (p + (Z * Z) / (2 * t)) / den;
  const half = (Z * Math.sqrt((p * (1 - p)) / t + (Z * Z) / (4 * t * t))) / den;
  return [Math.max(0, centre - half), Math.min(1, centre + half)];
}

/**
 * La versión que gana un experimento, o null. ``totals``: {versión: {view, use, …}} de las filas con «use» (las de
 * ab_exp: el mapa de alertas antes no lo mandaba). Devuelve también la tasa y el intervalo de cada versión.
 */
export function decide(variants, totals, minViews = MIN_VIEWS) {
  const rows = variants.map((v) => {
    const t = totals[v] || {};
    const view = t.view || 0, use = Math.min(t.use || 0, view);
    const [lo, hi] = wilson(use, view);
    return { v, view, use, rate: view ? use / view : null, lo, hi };
  });
  const ready = rows.every((r) => r.view >= minViews);
  const lead = [...rows].sort((a, b) => (b.rate ?? -1) - (a.rate ?? -1))[0];
  const winner = ready && rows.every((r) => r === lead || lead.lo > r.hi) ? lead.v : null;
  return { winner, ready, minViews, rows };
}

const sinceDay = (days) => new Date(Date.now() - (days - 1) * 864e5).toISOString().slice(0, 10);

async function rowsSince(db, since) {
  const { results: exp } = await db.prepare('SELECT day, exp, variant, event, n FROM ab_exp WHERE day >= ? ORDER BY day').bind(since).all();
  const { results: old } = await db.prepare('SELECT day, variant, event, n FROM ab_daily WHERE day >= ? ORDER BY day').bind(since).all();
  return { exp, old };
}

function tally(rows, onlyTracked = false) {
  const out = Object.fromEntries(Object.entries(EXPERIMENTS).map(([x, vs]) => [x, Object.fromEntries(vs.map((v) => [v, Object.fromEntries(EVENTS.map((e) => [e, 0]))]))]));
  for (const r of rows.exp) if (out[r.exp]?.[r.variant] && r.event in out[r.exp][r.variant]) out[r.exp][r.variant][r.event] += r.n;
  if (!onlyTracked) for (const r of rows.old) if (out.mapa[r.variant] && r.event in out.mapa[r.variant]) out.mapa[r.variant][r.event] += r.n;
  return out;
}

async function stats(env, url) {
  const days = Math.max(1, Math.min(MAX_DAYS, Number(url.searchParams.get('days')) || 30));
  const empty = tally({ exp: [], old: [] });
  const base = { days, decideDays: DECIDE_DAYS, events: EVENTS, variants: VARIANTS };
  const db = env.GEO_DB;
  if (!db) {
    return json({ ...base, available: false, totals: empty.mapa, daily: [],
      experiments: Object.fromEntries(Object.entries(EXPERIMENTS).map(([x, vs]) => [x, { variants: vs, totals: empty[x], decision: decide(vs, empty[x]) }])) });
  }
  await ensureSchema(db);
  const since = sinceDay(days);
  const rows = await rowsSince(db, since);
  // La decisión usa siempre los mismos días que /defaults, para que la página muestre lo que hace el sitio.
  const all = tally(rows), tracked = tally(days === DECIDE_DAYS ? rows : await rowsSince(db, sinceDay(DECIDE_DAYS)), true);
  const experiments = Object.fromEntries(Object.entries(EXPERIMENTS).map(([x, vs]) => [x, { variants: vs, totals: all[x], decision: decide(vs, tracked[x]) }]));
  const daily = [...rows.old.map((r) => ({ ...r, exp: 'mapa' })), ...rows.exp].sort((a, b) => a.day.localeCompare(b.day));
  return json({ ...base, available: true, since, totals: all.mapa, experiments, daily });
}

async function defaults(env) {
  const none = Object.fromEntries(Object.keys(EXPERIMENTS).map((x) => [x, null]));
  const db = env.GEO_DB;
  if (!db) return json(none);
  await ensureSchema(db);
  const tracked = tally(await rowsSince(db, sinceDay(DECIDE_DAYS)), true);
  const out = Object.fromEntries(Object.entries(EXPERIMENTS).map(([x, vs]) => [x, decide(vs, tracked[x]).winner]));
  return json(out, 200, { 'Cache-Control': 'public, max-age=3600' });
}

export async function handle(request, env = {}) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/^\/api\/ab\/?/, '').replace(/\/$/, '');
  try {
    if (path === 'e' && request.method === 'POST') return await record(request, env, url);
    if (path === 'stats' && request.method === 'GET') return await stats(env, url);
    if (path === 'defaults' && request.method === 'GET') return await defaults(env);
    return json({ error: 'No encontrado.' }, 404);
  } catch (e) {
    console.error(e);
    return json({ error: 'Error interno.' }, 500);
  }
}
