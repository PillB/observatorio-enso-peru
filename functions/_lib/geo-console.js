// Consola de lugares: API para que los revisores corrijan dónde ocurre cada noticia o aviso.
//
// Corre como Pages Function en Cloudflare, con una base D1 vinculada como GEO_DB y los usuarios en el
// secreto GEO_USERS (solo hashes PBKDF2; las contraseñas nunca se guardan). Rutas, bajo /api/geo/:
//
//   POST login            {username, password} → cookie de sesión (HttpOnly, Secure, SameSite=Strict)
//   POST logout
//   GET  me               usuario de la sesión
//   GET  corrections      ?item=<id> historial de una nota; ?latest=1 la última corrección de cada nota
//   POST corrections      {item, action, places?, note?, before?, expectedRev}
//   GET  audit            últimos eventos (ingresos, correcciones)
//   GET  overrides        PÚBLICA: las correcciones vigentes, sin nombres ni notas, para el pipeline diario
//
// Cada corrección es una fila nueva (nunca se borra ni se edita): el historial completo queda en D1.
// Una corrección «clear» deshace la anterior y la nota vuelve a la ubicación automática.

export const ITERATIONS = 100000; // máximo que admite PBKDF2 en Workers
export const SESSION_HOURS = 12;
export const COOKIE = '__Host-geo_session';
export const ACTIONS = ['set', 'confirm', 'none', 'foreign', 'clear'];
const LOGIN_WINDOW_S = 15 * 60;
const LOGIN_MAX_USER = 8; // fallos por usuario en la ventana
const LOGIN_MAX_IP = 30; // fallos por IP en la ventana
const WRITE_MAX_HOUR = 600; // correcciones por usuario por hora
const MAX_BODY = 16 * 1024;
const ITEM_RE = /^[0-9a-f]{16}$/;
const CODE_RE = /^(0[1-9]|1\d|2[0-5])(\d{2}){0,2}$/;

const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, role TEXT NOT NULL,
     created_at TEXT NOT NULL, expires_at TEXT NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS attempts (key TEXT PRIMARY KEY, count INTEGER NOT NULL, window_start INTEGER NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS corrections (id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL,
     rev INTEGER NOT NULL, action TEXT NOT NULL, places TEXT, note TEXT, before TEXT, username TEXT NOT NULL,
     created_at TEXT NOT NULL, UNIQUE (item_id, rev))`,
  `CREATE INDEX IF NOT EXISTS corrections_user ON corrections (username, created_at)`,
  `CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, username TEXT,
     event TEXT NOT NULL, item_id TEXT, detail TEXT, ip TEXT)`,
];

const SECURITY_HEADERS = {
  'Cache-Control': 'no-store',
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'X-Frame-Options': 'DENY',
  'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'",
  'X-Robots-Tag': 'noindex, nofollow',
};

const enc = new TextEncoder();
let schemaReady = null; // una vez por instancia

export function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', ...SECURITY_HEADERS, ...extra },
  });
}

const fail = (status, error, extra) => json({ error }, status, extra);
const nowIso = () => new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');

// --- Criptografía --------------------------------------------------------------------

const b64 = (bytes) => btoa(String.fromCharCode(...bytes));
const unb64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const b64url = (bytes) => b64(bytes).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

export async function sha256(text) {
  const d = new Uint8Array(await crypto.subtle.digest('SHA-256', enc.encode(text)));
  return [...d].map((b) => b.toString(16).padStart(2, '0')).join('');
}

async function pbkdf2(password, salt, iterations) {
  const key = await crypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt, iterations }, key, 256);
  return new Uint8Array(bits);
}

function sameBytes(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

/** «pbkdf2-sha256$100000$<sal base64>$<hash base64>», como lo escribe python/tools/geo_users.py. */
export async function hashPassword(password, salt = crypto.getRandomValues(new Uint8Array(16)), iterations = ITERATIONS) {
  return `pbkdf2-sha256$${iterations}$${b64(salt)}$${b64(await pbkdf2(password, salt, iterations))}`;
}

export async function verifyPassword(password, stored) {
  const parts = String(stored || '').split('$');
  if (parts.length !== 4 || parts[0] !== 'pbkdf2-sha256') return false;
  const iterations = Number(parts[1]);
  if (!Number.isInteger(iterations) || iterations < 10000 || iterations > ITERATIONS) return false;
  try {
    return sameBytes(await pbkdf2(password, unb64(parts[2]), iterations), unb64(parts[3]));
  } catch {
    return false;
  }
}

// Hash de relleno: un usuario inexistente tarda lo mismo que una contraseña equivocada.
const DUMMY = 'pbkdf2-sha256$100000$AAAAAAAAAAAAAAAAAAAAAA==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=';

/** Usuarios del secreto GEO_USERS: {"usuario": {"hash": "...", "role": "tester" | "admin"}} o {"usuario": "hash"}. */
export function users(env) {
  let raw;
  try {
    raw = JSON.parse(env.GEO_USERS || '{}');
  } catch {
    return {};
  }
  const out = {};
  for (const [name, v] of Object.entries(raw || {})) {
    const hash = typeof v === 'string' ? v : v && v.hash;
    if (/^[a-z0-9._-]{3,32}$/.test(name) && hash) out[name] = { hash, role: (v && v.role) === 'admin' ? 'admin' : 'tester' };
  }
  return out;
}

// --- Base de datos -------------------------------------------------------------------

export async function ensureSchema(db) {
  if (!schemaReady) {
    schemaReady = db.batch(SCHEMA.map((s) => db.prepare(s))).catch((e) => {
      schemaReady = null;
      throw e;
    });
  }
  return schemaReady;
}

export function resetSchemaCache() {
  schemaReady = null;
}

async function audit(db, username, event, ip, itemId = null, detail = null) {
  await db.prepare('INSERT INTO audit (at, username, event, item_id, detail, ip) VALUES (?, ?, ?, ?, ?, ?)')
    .bind(nowIso(), username, event, itemId, detail === null ? null : JSON.stringify(detail).slice(0, 4000), ip)
    .run();
}

async function tooMany(db, key, max) {
  const row = await db.prepare('SELECT count, window_start FROM attempts WHERE key = ?').bind(key).first();
  const now = Math.floor(Date.now() / 1000);
  return Boolean(row && now - row.window_start < LOGIN_WINDOW_S && row.count >= max);
}

async function countFailure(db, key) {
  const now = Math.floor(Date.now() / 1000);
  await db.prepare(`INSERT INTO attempts (key, count, window_start) VALUES (?, 1, ?)
    ON CONFLICT (key) DO UPDATE SET
      count = CASE WHEN ? - window_start >= ? THEN 1 ELSE count + 1 END,
      window_start = CASE WHEN ? - window_start >= ? THEN ? ELSE window_start END`)
    .bind(key, now, now, LOGIN_WINDOW_S, now, LOGIN_WINDOW_S, now).run();
}

// --- Solicitudes ---------------------------------------------------------------------

const clientIp = (request) => request.headers.get('CF-Connecting-IP') || '';

/** Escrituras solo desde la propia consola: mismo origen y cuerpo JSON (protección contra CSRF). */
function checkWrite(request, url) {
  const origin = request.headers.get('Origin');
  const site = request.headers.get('Sec-Fetch-Site');
  if (origin ? origin !== url.origin : site !== 'same-origin') return fail(403, 'Origen no permitido.');
  if (!(request.headers.get('Content-Type') || '').toLowerCase().startsWith('application/json')) {
    return fail(415, 'Se espera JSON.');
  }
  return null;
}

async function readJson(request) {
  const text = await request.text();
  if (text.length > MAX_BODY) throw Object.assign(new Error('grande'), { status: 413 });
  try {
    const body = JSON.parse(text || '{}');
    if (body && typeof body === 'object' && !Array.isArray(body)) return body;
  } catch { /* abajo */ }
  throw Object.assign(new Error('json'), { status: 400 });
}

function sessionToken(request) {
  const cookie = request.headers.get('Cookie') || '';
  const m = cookie.match(new RegExp(`(?:^|;\\s*)${COOKIE}=([A-Za-z0-9_-]{20,100})`));
  return m ? m[1] : null;
}

async function currentSession(request, env) {
  const token = sessionToken(request);
  if (!token) return null;
  const row = await env.GEO_DB.prepare('SELECT username, role, expires_at FROM sessions WHERE token_hash = ?')
    .bind(await sha256(token)).first();
  if (!row || row.expires_at <= nowIso()) return null;
  const u = users(env)[row.username];
  if (!u) return null; // usuario dado de baja: la sesión deja de valer
  return { username: row.username, role: u.role, tokenHash: await sha256(token) };
}

async function login(request, env, url) {
  const db = env.GEO_DB;
  const ip = clientIp(request);
  const body = await readJson(request);
  const username = String(body.username || '').trim().toLowerCase().slice(0, 40);
  const password = String(body.password || '').slice(0, 200);
  if (await tooMany(db, `ip:${ip}`, LOGIN_MAX_IP) || await tooMany(db, `user:${username}`, LOGIN_MAX_USER)) {
    await audit(db, username || null, 'login-bloqueado', ip);
    return fail(429, 'Demasiados intentos. Espere 15 minutos.', { 'Retry-After': String(LOGIN_WINDOW_S) });
  }
  const u = users(env)[username];
  const ok = await verifyPassword(password, u ? u.hash : DUMMY);
  if (!u || !ok) {
    await countFailure(db, `ip:${ip}`);
    await countFailure(db, `user:${username}`);
    await audit(db, username || null, 'login-fallido', ip);
    return fail(401, 'Usuario o contraseña incorrectos.');
  }
  const token = b64url(crypto.getRandomValues(new Uint8Array(32)));
  const now = new Date();
  const expires = new Date(now.getTime() + SESSION_HOURS * 3600 * 1000);
  await db.batch([
    db.prepare('DELETE FROM sessions WHERE expires_at <= ?').bind(nowIso()),
    db.prepare('DELETE FROM attempts WHERE key = ?').bind(`user:${username}`),
    db.prepare('INSERT INTO sessions (token_hash, username, role, created_at, expires_at) VALUES (?, ?, ?, ?, ?)')
      .bind(await sha256(token), username, u.role, nowIso(), expires.toISOString().replace(/\.\d{3}Z$/, 'Z')),
  ]);
  await audit(db, username, 'login', ip);
  const secure = url.protocol === 'https:' || url.hostname === 'localhost' || url.hostname === '127.0.0.1';
  return json({ username, role: u.role, expiresAt: expires.toISOString() }, 200, {
    'Set-Cookie': `${COOKIE}=${token}; Path=/; HttpOnly; ${secure ? 'Secure; ' : ''}SameSite=Strict; Max-Age=${SESSION_HOURS * 3600}`,
  });
}

async function logout(request, env, session) {
  if (session) {
    await env.GEO_DB.prepare('DELETE FROM sessions WHERE token_hash = ?').bind(session.tokenHash).run();
    await audit(env.GEO_DB, session.username, 'logout', clientIp(request));
  }
  return json({ ok: true }, 200, { 'Set-Cookie': `${COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0` });
}

// Códigos válidos: los del nomenclátor publicado con el sitio (data/geo/ubigeo.json).
let ubigeoCache = null;
async function validCodes(env, url) {
  if (ubigeoCache && Date.now() - ubigeoCache.at < 3600 * 1000) return ubigeoCache.codes;
  let codes = null;
  try {
    const fetcher = env.ASSETS ? (u) => env.ASSETS.fetch(u) : null;
    const r = fetcher ? await fetcher(new URL('/data/geo/ubigeo.json', url)) : null;
    if (r && r.ok) {
      const g = await r.json();
      codes = new Set([...Object.keys(g.departments || {}), ...Object.keys(g.provinces || {}), ...Object.keys(g.districts || {})]);
    }
  } catch { /* abajo */ }
  ubigeoCache = { at: Date.now(), codes };
  return codes;
}

export function resetUbigeoCache() {
  ubigeoCache = null;
}

const parseRow = (r) => ({
  id: r.id, item: r.item_id, rev: r.rev, action: r.action, places: r.places ? JSON.parse(r.places) : [],
  note: r.note || '', username: r.username, at: r.created_at,
});

async function listCorrections(env, url) {
  const db = env.GEO_DB;
  const item = url.searchParams.get('item');
  if (item) {
    if (!ITEM_RE.test(item)) return fail(400, 'Nota inválida.');
    const { results } = await db.prepare('SELECT * FROM corrections WHERE item_id = ? ORDER BY rev DESC').bind(item).all();
    return json({ item, corrections: results.map(parseRow) });
  }
  const { results } = await db.prepare(`SELECT c.* FROM corrections c
      JOIN (SELECT item_id, MAX(rev) AS rev FROM corrections GROUP BY item_id) m ON m.item_id = c.item_id AND m.rev = c.rev
      ORDER BY c.created_at DESC LIMIT 5000`).all();
  return json({ corrections: results.map(parseRow) });
}

async function createCorrection(request, env, url, session) {
  const db = env.GEO_DB;
  const body = await readJson(request);
  const item = String(body.item || '');
  const action = String(body.action || '');
  if (!ITEM_RE.test(item)) return fail(400, 'Nota inválida.');
  if (!ACTIONS.includes(action)) return fail(400, 'Acción inválida.');
  let places = [];
  if (action === 'set') {
    if (!Array.isArray(body.places) || !body.places.length || body.places.length > 20) {
      return fail(400, 'Indique entre 1 y 20 lugares.');
    }
    places = [...new Set(body.places.map(String))];
    const known = await validCodes(env, url);
    const bad = places.filter((c) => !CODE_RE.test(c) || (known && !known.has(c)));
    if (bad.length) return fail(400, `Códigos UBIGEO desconocidos: ${bad.join(', ')}`);
  }
  const note = String(body.note || '').trim().slice(0, 500);
  const expected = Number.isInteger(body.expectedRev) ? body.expectedRev : null;
  const since = new Date(Date.now() - 3600 * 1000).toISOString();
  const recent = await db.prepare('SELECT COUNT(*) AS n FROM corrections WHERE username = ? AND created_at >= ?')
    .bind(session.username, since).first();
  if (recent && recent.n >= WRITE_MAX_HOUR) return fail(429, 'Demasiadas correcciones en una hora.');
  const last = await db.prepare('SELECT MAX(rev) AS rev FROM corrections WHERE item_id = ?').bind(item).first();
  const current = (last && last.rev) || 0;
  if (expected !== null && expected !== current) {
    return fail(409, 'Otra persona corrigió esta nota mientras usted la editaba. Recargue para ver su cambio.', {});
  }
  if (action === 'clear' && !current) return fail(400, 'La nota no tiene correcciones que deshacer.');
  const before = body.before === undefined ? null : JSON.stringify(body.before).slice(0, 4000);
  const at = nowIso();
  try {
    await db.prepare(`INSERT INTO corrections (item_id, rev, action, places, note, before, username, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)`)
      .bind(item, current + 1, action, JSON.stringify(places), note, before, session.username, at).run();
  } catch (e) {
    if (/UNIQUE|constraint/i.test(String(e && e.message))) {
      return fail(409, 'Otra persona corrigió esta nota al mismo tiempo. Recargue para ver su cambio.');
    }
    throw e;
  }
  await audit(db, session.username, 'correccion', clientIp(request), item, { action, places, rev: current + 1 });
  return json({ item, rev: current + 1, action, places, note, username: session.username, at }, 201);
}

async function listAudit(env, url) {
  const limit = Math.min(500, Math.max(1, Number(url.searchParams.get('limit')) || 200));
  const { results } = await env.GEO_DB.prepare('SELECT at, username, event, item_id, detail FROM audit ORDER BY id DESC LIMIT ?')
    .bind(limit).all();
  const parse = (t) => {
    try {
      return t ? JSON.parse(t) : null;
    } catch {
      return null;
    }
  };
  return json({ events: results.map((r) => ({ ...r, detail: parse(r.detail) })) });
}

/** Correcciones vigentes, sin usuarios ni notas: lo que lee el pipeline diario. */
async function publicOverrides(env) {
  const { results } = await env.GEO_DB.prepare(`SELECT c.item_id, c.action, c.places, c.rev, c.created_at FROM corrections c
      JOIN (SELECT item_id, MAX(rev) AS rev FROM corrections GROUP BY item_id) m ON m.item_id = c.item_id AND m.rev = c.rev
      WHERE c.action != 'clear' ORDER BY c.item_id`).all();
  return json({
    version: 1, generatedAt: nowIso(),
    overrides: results.map((r) => ({ id: r.item_id, action: r.action, places: JSON.parse(r.places || '[]'), rev: r.rev, at: r.created_at })),
  }, 200, { 'Cache-Control': 'public, max-age=60' });
}

export async function handle(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/^\/api\/geo\/?/, '').replace(/\/$/, '');
  const method = request.method;
  try {
    if (!env.GEO_DB) return fail(503, 'La consola no está configurada todavía (falta la base de datos GEO_DB).');
    await ensureSchema(env.GEO_DB);
    const routes = {
      login: ['POST'], logout: ['POST'], me: ['GET'], corrections: ['GET', 'POST'], audit: ['GET'], overrides: ['GET'],
    };
    if (!routes[path]) return fail(404, 'No existe.');
    if (!routes[path].includes(method)) return fail(405, 'Método no permitido.', { Allow: routes[path].join(', ') });
    if (path === 'overrides') return await publicOverrides(env);
    if (method === 'POST') {
      const bad = checkWrite(request, url);
      if (bad) return bad;
      const len = Number(request.headers.get('Content-Length') || 0);
      if (len > MAX_BODY) return fail(413, 'Solicitud demasiado grande.');
    }
    if (path === 'login') {
      if (!Object.keys(users(env)).length) return fail(503, 'No hay usuarios configurados (secreto GEO_USERS).');
      return await login(request, env, url);
    }
    const session = await currentSession(request, env);
    if (path === 'logout') return await logout(request, env, session);
    if (!session) return fail(401, 'Inicie sesión.');
    if (path === 'me') return json({ username: session.username, role: session.role });
    if (path === 'corrections') {
      return method === 'GET' ? await listCorrections(env, url) : await createCorrection(request, env, url, session);
    }
    if (path === 'audit') return await listAudit(env, url);
    return fail(404, 'No existe.');
  } catch (e) {
    if (e && e.status === 400) return fail(400, 'JSON inválido.');
    if (e && e.status === 413) return fail(413, 'Solicitud demasiado grande.');
    console.error('geo-console', e && e.stack ? e.stack : e);
    return fail(500, 'Error interno. Intente de nuevo.');
  }
}
