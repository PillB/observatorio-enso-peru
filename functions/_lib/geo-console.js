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
//
// Consumo (plan gratuito: 5 M filas leídas y 100 000 escritas por día, 50 consultas por solicitud): cada
// solicitud hace como mucho 3 viajes a D1 y lee filas por clave, nunca recorre tablas. La tabla «current»
// guarda la última corrección de cada nota, así la lista pública y la consola leen una fila por nota.
// Las tablas se crean solas la primera vez que una consulta no las encuentra.

// El plan gratuito de Workers da 10 ms de CPU por solicitud; en workerd PBKDF2-SHA256 toma ~4 ms con 5 000
// iteraciones y ~49 ms con 100 000. Las contraseñas son aleatorias de 16 caracteres (~93 bits): con 5 000
// iteraciones una RTX 4090 prueba ~1,8 millones por segundo y tardaría ~10^14 años en adivinar una. Se aceptan
// hashes de hasta 8 000 iteraciones para no pasar nunca de los 10 ms (ver docs/georreferenciacion.md).
export const ITERATIONS = 5000;
const MAX_ITERATIONS = 8000;
export const SESSION_HOURS = 12;
export const COOKIE = '__Host-geo_session';
export const ACTIONS = ['set', 'confirm', 'none', 'foreign', 'clear'];
const LOGIN_WINDOW_S = 15 * 60;
const LOGIN_MAX_USER = 8; // fallos por usuario en la ventana
const LOGIN_MAX_IP = 30; // fallos por IP en la ventana
const WRITE_MAX_HOUR = 600; // correcciones por usuario por hora
const WRITE_WINDOW_S = 3600;
const ATTEMPTS_KEEP_S = 24 * 3600; // contadores viejos que se borran al ingresar
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
  `CREATE TABLE IF NOT EXISTS current (item_id TEXT PRIMARY KEY, rev INTEGER NOT NULL, action TEXT NOT NULL,
     places TEXT, note TEXT, username TEXT NOT NULL, created_at TEXT NOT NULL)`,
  // Si «current» llega después que «corrections», se llena con la última revisión de cada nota.
  `INSERT OR IGNORE INTO current (item_id, rev, action, places, note, username, created_at)
     SELECT c.item_id, c.rev, c.action, c.places, c.note, c.username, c.created_at FROM corrections c
     JOIN (SELECT item_id, MAX(rev) AS rev FROM corrections GROUP BY item_id) m ON m.item_id = c.item_id AND m.rev = c.rev`,
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

/** «pbkdf2-sha256$5000$<sal base64>$<hash base64>», como lo escribe python/tools/geo_users.py. */
export async function hashPassword(password, salt = crypto.getRandomValues(new Uint8Array(16)), iterations = ITERATIONS) {
  return `pbkdf2-sha256$${iterations}$${b64(salt)}$${b64(await pbkdf2(password, salt, iterations))}`;
}

export async function verifyPassword(password, stored) {
  const parts = String(stored || '').split('$');
  if (parts.length !== 4 || parts[0] !== 'pbkdf2-sha256') return false;
  const iterations = Number(parts[1]);
  if (!Number.isInteger(iterations) || iterations < 1000 || iterations > MAX_ITERATIONS) return false;
  try {
    return sameBytes(await pbkdf2(password, unb64(parts[2]), iterations), unb64(parts[3]));
  } catch {
    return false;
  }
}

// Hash de relleno: un usuario inexistente tarda lo mismo que una contraseña equivocada.
const DUMMY = 'pbkdf2-sha256$5000$AAAAAAAAAAAAAAAAAAAAAA==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=';

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

/** Crea las tablas (IF NOT EXISTS): lo llama handle() solo cuando una consulta no encuentra una tabla. */
export async function ensureSchema(db) {
  await db.batch(SCHEMA.map((s) => db.prepare(s)));
}

/** Compatibilidad con las pruebas: ya no hay estado por instancia. */
export function resetSchemaCache() {}

const noTable = (e) => /no such table/i.test(String(e && e.message));
const epoch = () => Math.floor(Date.now() / 1000);

function auditStmt(db, username, event, ip, itemId = null, detail = null) {
  return db.prepare('INSERT INTO audit (at, username, event, item_id, detail, ip) VALUES (?, ?, ?, ?, ?, ?)')
    .bind(nowIso(), username, event, itemId, detail === null ? null : JSON.stringify(detail).slice(0, 4000), ip);
}

/** Suma 1 al contador `key` (ventana fija de `windowS` segundos que se reinicia al vencer). */
function bumpStmt(db, key, windowS, now = epoch()) {
  return db.prepare(`INSERT INTO attempts (key, count, window_start) VALUES (?, 1, ?)
    ON CONFLICT (key) DO UPDATE SET
      count = CASE WHEN ? - window_start >= ? THEN 1 ELSE count + 1 END,
      window_start = CASE WHEN ? - window_start >= ? THEN ? ELSE window_start END`)
    .bind(key, now, now, windowS, now, windowS, now);
}

const live = (row, windowS, now) => (row && now - row.window_start < windowS ? row.count : 0);

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
  const tokenHash = await sha256(token);
  const row = await env.GEO_DB.prepare('SELECT username, expires_at FROM sessions WHERE token_hash = ?').bind(tokenHash).first();
  if (!row || row.expires_at <= nowIso()) return null;
  const u = users(env)[row.username];
  if (!u) return null; // usuario dado de baja: la sesión deja de valer
  return { username: row.username, role: u.role, tokenHash };
}

// Ingreso: una lectura (los dos contadores) y una escritura en lote. Un intento bloqueado no escribe nada, para
// que una avalancha de intentos no gaste las 100 000 escrituras diarias del plan gratuito; el bloqueo queda en
// el registro una vez, con el fallo que lo provoca.
async function login(env, url, body, ip) {
  const db = env.GEO_DB;
  const username = String(body.username || '').trim().toLowerCase().slice(0, 40);
  const password = String(body.password || '').slice(0, 200);
  const ipKey = `ip:${ip}`;
  const userKey = `user:${username}`;
  const now = epoch();
  const { results } = await db.prepare('SELECT key, count, window_start FROM attempts WHERE key IN (?, ?)').bind(ipKey, userKey).all();
  const row = (k) => results.find((r) => r.key === k);
  const ipFails = live(row(ipKey), LOGIN_WINDOW_S, now);
  const userFails = live(row(userKey), LOGIN_WINDOW_S, now);
  if (ipFails >= LOGIN_MAX_IP || userFails >= LOGIN_MAX_USER) {
    return fail(429, 'Demasiados intentos. Espere 15 minutos.', { 'Retry-After': String(LOGIN_WINDOW_S) });
  }
  const u = users(env)[username];
  const ok = await verifyPassword(password, u ? u.hash : DUMMY);
  if (!u || !ok) {
    const blocked = ipFails + 1 >= LOGIN_MAX_IP || (u && userFails + 1 >= LOGIN_MAX_USER);
    // Solo se cuentan fallos por usuario de cuentas que existen: inventar nombres no llena la tabla.
    await db.batch([
      bumpStmt(db, ipKey, LOGIN_WINDOW_S, now),
      ...(u ? [bumpStmt(db, userKey, LOGIN_WINDOW_S, now)] : []),
      auditStmt(db, username || null, blocked ? 'login-bloqueado' : 'login-fallido', ip),
    ]);
    return fail(401, 'Usuario o contraseña incorrectos.');
  }
  const token = b64url(crypto.getRandomValues(new Uint8Array(32)));
  const expires = new Date(Date.now() + SESSION_HOURS * 3600 * 1000);
  await db.batch([
    db.prepare('DELETE FROM sessions WHERE expires_at <= ?').bind(nowIso()),
    db.prepare('DELETE FROM attempts WHERE key = ? OR window_start < ?').bind(userKey, now - ATTEMPTS_KEEP_S),
    db.prepare('INSERT INTO sessions (token_hash, username, role, created_at, expires_at) VALUES (?, ?, ?, ?, ?)')
      .bind(await sha256(token), username, u.role, nowIso(), expires.toISOString().replace(/\.\d{3}Z$/, 'Z')),
    auditStmt(db, username, 'login', ip),
  ]);
  const secure = url.protocol === 'https:' || url.hostname === 'localhost' || url.hostname === '127.0.0.1';
  return json({ username, role: u.role, expiresAt: expires.toISOString() }, 200, {
    'Set-Cookie': `${COOKIE}=${token}; Path=/; HttpOnly; ${secure ? 'Secure; ' : ''}SameSite=Strict; Max-Age=${SESSION_HOURS * 3600}`,
  });
}

async function logout(env, session, ip) {
  if (session) {
    const db = env.GEO_DB;
    await db.batch([
      db.prepare('DELETE FROM sessions WHERE token_hash = ?').bind(session.tokenHash),
      auditStmt(db, session.username, 'logout', ip),
    ]);
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
  item: r.item_id, rev: r.rev, action: r.action, places: r.places ? JSON.parse(r.places) : [],
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
  const { results } = await db.prepare('SELECT * FROM current ORDER BY created_at DESC LIMIT 5000').all();
  return json({ corrections: results.map(parseRow) });
}

async function createCorrection(env, url, session, body, ip) {
  const db = env.GEO_DB;
  const item = String(body.item || '');
  const action = String(body.action || '');
  if (!ITEM_RE.test(item)) return fail(400, 'Nota inválida.');
  if (!ACTIONS.includes(action)) return fail(400, 'Acción inválida.');
  let places = [];
  // «confirm» guarda los lugares que la persona vio: si el ubicador cambia después, valen esos.
  if (action === 'set' || (action === 'confirm' && Array.isArray(body.places) && body.places.length)) {
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
  const now = epoch();
  const writeKey = `write:${session.username}`;
  // Una sola lectura de dos filas por clave: la revisión vigente de la nota y el contador de la persona.
  const st = await db.prepare(`SELECT (SELECT rev FROM current WHERE item_id = ?) AS rev,
      (SELECT count FROM attempts WHERE key = ? AND window_start > ?) AS n`)
    .bind(item, writeKey, now - WRITE_WINDOW_S).first();
  if (st && st.n >= WRITE_MAX_HOUR) return fail(429, 'Demasiadas correcciones en una hora.');
  const current = (st && st.rev) || 0;
  if (expected !== null && expected !== current) {
    return fail(409, 'Otra persona corrigió esta nota mientras usted la editaba. Recargue para ver su cambio.', {});
  }
  if (action === 'clear' && !current) return fail(400, 'La nota no tiene correcciones que deshacer.');
  const before = body.before === undefined ? null : JSON.stringify(body.before).slice(0, 4000);
  const at = nowIso();
  const rev = current + 1;
  const placesJson = JSON.stringify(places);
  try {
    // En lote (una transacción): si otra persona ganó la carrera, UNIQUE (item_id, rev) anula todo el lote.
    await db.batch([
      db.prepare(`INSERT INTO corrections (item_id, rev, action, places, note, before, username, created_at)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?)`)
        .bind(item, rev, action, placesJson, note, before, session.username, at),
      db.prepare(`INSERT INTO current (item_id, rev, action, places, note, username, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT (item_id) DO UPDATE SET rev = excluded.rev, action = excluded.action, places = excluded.places,
            note = excluded.note, username = excluded.username, created_at = excluded.created_at`)
        .bind(item, rev, action, placesJson, note, session.username, at),
      bumpStmt(db, writeKey, WRITE_WINDOW_S, now),
      auditStmt(db, session.username, 'correccion', ip, item, { action, places, rev }),
    ]);
  } catch (e) {
    if (/UNIQUE|constraint/i.test(String(e && e.message))) {
      return fail(409, 'Otra persona corrigió esta nota al mismo tiempo. Recargue para ver su cambio.');
    }
    throw e;
  }
  return json({ item, rev, action, places, note, username: session.username, at }, 201);
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

async function route(request, env, url, path, method, body) {
  if (path === 'overrides') return publicOverrides(env);
  const ip = clientIp(request);
  if (path === 'login') return login(env, url, body, ip);
  const session = await currentSession(request, env);
  if (path === 'logout') return logout(env, session, ip);
  if (!session) return fail(401, 'Inicie sesión.');
  if (path === 'me') return json({ username: session.username, role: session.role });
  if (path === 'corrections') {
    return method === 'GET' ? listCorrections(env, url) : createCorrection(env, url, session, body, ip);
  }
  if (path === 'audit') return listAudit(env, url);
  return fail(404, 'No existe.');
}

/** Correcciones vigentes, sin usuarios ni notas: lo que lee el pipeline diario. */
async function publicOverrides(env) {
  const { results } = await env.GEO_DB.prepare(`SELECT item_id, action, places, rev, created_at FROM current
      WHERE action != 'clear' ORDER BY item_id`).all();
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
    const routes = {
      login: ['POST'], logout: ['POST'], me: ['GET'], corrections: ['GET', 'POST'], audit: ['GET'], overrides: ['GET'],
    };
    if (!routes[path]) return fail(404, 'No existe.');
    if (!routes[path].includes(method)) return fail(405, 'Método no permitido.', { Allow: routes[path].join(', ') });
    let body = null;
    if (method === 'POST') {
      const bad = checkWrite(request, url);
      if (bad) return bad;
      const len = Number(request.headers.get('Content-Length') || 0);
      if (len > MAX_BODY) return fail(413, 'Solicitud demasiado grande.');
      body = await readJson(request);
    }
    if (path === 'login' && !Object.keys(users(env)).length) return fail(503, 'No hay usuarios configurados (secreto GEO_USERS).');
    const run = () => route(request, env, url, path, method, body);
    try {
      return await run();
    } catch (e) {
      // Base recién creada: se crean las tablas y se repite. Las escrituras van en lotes (transacciones), así que
      // un intento fallido no dejó nada a medias.
      if (!noTable(e)) throw e;
      await ensureSchema(env.GEO_DB);
      return await run();
    }
  } catch (e) {
    if (e && e.status === 400) return fail(400, 'JSON inválido.');
    if (e && e.status === 413) return fail(413, 'Solicitud demasiado grande.');
    console.error('geo-console', e && e.stack ? e.stack : e);
    return fail(500, 'Error interno. Intente de nuevo.');
  }
}
