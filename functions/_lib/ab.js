// Analítica de las versiones del mapa de alertas (Noticias → «Versión A / B / C / D»).
//
// Corre como Pages Function con la misma base D1 de la consola de lugares (GEO_DB), en una tabla propia.
// No guarda datos personales: ni IP, ni identificador de visitante, ni cookies. Cada visita manda, al salir
// de la página, una sola solicitud con la versión que vio y qué hizo (vio, pasó el cursor, filtró…), y aquí
// solo se suma 1 a un contador por día, versión y evento. Rutas, bajo /api/ab/:
//
//   POST e       {v: 'A', e: ['view', 'hover', …]} → suma 1 a cada (día, v, evento). Mismo origen.
//   GET  stats   ?days=30 → contadores por día y totales por versión (públicos: no hay nada personal).
//
// La base la comparte la consola, y el plan gratuito de D1 (100 000 filas escritas por día) es por cuenta:
// por eso cada solicitud escribe como mucho una fila por evento, se acepta un solo envío por evento y hay un
// tope diario de sumas (DAILY_CAP) para que una avalancha de solicitudes no deje sin escrituras a la consola.
// Si GEO_DB no está vinculada, la API responde sin hacer nada.

export const VARIANTS = ['A', 'B', 'C', 'D'];
// view: vio la versión · chosen: la vio siendo su versión elegida · hover: pasó el cursor o tocó una región
// select: filtró las noticias desde el mapa · detail: abrió un aviso desde el mapa · choose: la eligió en el
// selector · leave: la dejó por otra · keep: volvió otro día y sigue con la versión que eligió.
export const EVENTS = ['view', 'chosen', 'hover', 'select', 'detail', 'choose', 'leave', 'keep'];
export const DAILY_CAP = 20000;
const MAX_BODY = 512;
const MAX_DAYS = 120;

const SCHEMA = `CREATE TABLE IF NOT EXISTS ab_daily (day TEXT NOT NULL, variant TEXT NOT NULL, event TEXT NOT NULL,
  n INTEGER NOT NULL, PRIMARY KEY (day, variant, event))`;

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
  await db.prepare(SCHEMA).run();
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
  if (!body || typeof body !== 'object' || !VARIANTS.includes(body.v) || !Array.isArray(body.e)) return null;
  const events = [...new Set(body.e.filter((x) => EVENTS.includes(x)))];
  return events.length ? { variant: body.v, events } : null;
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
  const used = await db.prepare('SELECT COALESCE(SUM(n), 0) AS n FROM ab_daily WHERE day = ?').bind(day).first('n');
  if (used + ev.events.length > DAILY_CAP) return json({ ok: true, stored: false, reason: 'tope diario' }, 202);
  const up = db.prepare(`INSERT INTO ab_daily (day, variant, event, n) VALUES (?, ?, ?, 1)
    ON CONFLICT (day, variant, event) DO UPDATE SET n = n + 1`);
  await db.batch(ev.events.map((e) => up.bind(day, ev.variant, e)));
  return json({ ok: true, stored: true }, 202);
}

async function stats(env, url) {
  const days = Math.max(1, Math.min(MAX_DAYS, Number(url.searchParams.get('days')) || 30));
  const empty = Object.fromEntries(VARIANTS.map((v) => [v, Object.fromEntries(EVENTS.map((e) => [e, 0]))]));
  const db = env.GEO_DB;
  if (!db) return json({ available: false, days, variants: VARIANTS, events: EVENTS, totals: empty, daily: [] });
  await ensureSchema(db);
  const since = new Date(Date.now() - (days - 1) * 864e5).toISOString().slice(0, 10);
  const { results } = await db.prepare('SELECT day, variant, event, n FROM ab_daily WHERE day >= ? ORDER BY day')
    .bind(since).all();
  const totals = structuredClone(empty);
  for (const r of results) if (totals[r.variant] && r.event in totals[r.variant]) totals[r.variant][r.event] += r.n;
  return json({ available: true, days, since, variants: VARIANTS, events: EVENTS, totals, daily: results });
}

export async function handle(request, env = {}) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/^\/api\/ab\/?/, '').replace(/\/$/, '');
  try {
    if (path === 'e' && request.method === 'POST') return await record(request, env, url);
    if (path === 'stats' && request.method === 'GET') return await stats(env, url);
    return json({ error: 'No encontrado.' }, 404);
  } catch (e) {
    console.error(e);
    return json({ error: 'Error interno.' }, 500);
  }
}
