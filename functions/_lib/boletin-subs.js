// Suscripción por correo al Boletín de eventos El Niño (docs/boletin.md §Suscripción).
//
// Corre como Pages Function con la base D1 de la consola (GEO_DB), en tablas propias. Doble confirmación: quien se
// anota recibe un correo con un enlace; hasta que lo abre y pulsa «Confirmar», no recibe ningún boletín. Cada boletín
// trae su enlace de baja en un clic (RFC 8058, el que piden Gmail y Yahoo desde 2024) y de preferencias.
//
// Rutas, bajo /api/boletin/:
//   GET  estado        {enabled}: si la suscripción está configurada (base, secreto y una vía de correo).
//   POST suscribir     {email, frecuencia, deps, acepto, sitio_web, ms}. Mismo origen. Responde igual exista o no la
//                      dirección (no se puede averiguar quién está suscrito); manda el correo de confirmación.
//   POST confirmar     {t}. Mismo origen: el botón de la página, nunca el GET del enlace (los filtros de correo abren
//                      los enlaces solos y confirmarían a nadie).
//   POST baja          {t} desde la página, o ?t=… con «List-Unsubscribe=One-Click» desde el programa de correo
//                      (RFC 8058: de otro origen y sin JavaScript). Borra la fila.
//   GET  preferencias  ?t=… → correo enmascarado, frecuencia y departamentos.
//   POST preferencias  {t, frecuencia, deps}. Mismo origen.
//   GET  lista         Authorization: Bearer BOLETIN_LIST_TOKEN → las suscripciones activas, con su enlace de baja y de
//                      preferencias. La lee el flujo de n8n que manda el boletín (n8n/lib/boletin.js).
//
// Configuración (secretos de Cloudflare Pages): BOLETIN_SECRET (firma de los enlaces), BOLETIN_LIST_TOKEN (lectura de
// la lista) y una vía de correo para la confirmación: RESEND_API_KEY + BOLETIN_FROM (API de Resend) o
// BOLETIN_MAIL_WEBHOOK + BOLETIN_MAIL_WEBHOOK_SECRET (el flujo de n8n «Correo de confirmación», con Gmail). Opcionales:
// SITE_URL, BOLETIN_DAILY_CAP (correos de confirmación por día, 200).
//
// Datos personales (Ley 29733 y su reglamento, D. S. 016-2024-JUS): solo el correo, la frecuencia, los departamentos y
// las fechas. Sin IP: el tope por conexión usa un hash con sal del día, que se borra al día siguiente. Una suscripción
// sin confirmar se borra a los 7 días; la baja borra la fila.

export const FREQS = ['todo', 'importantes', 'diario', 'semanal'];
export const DEPS = ['01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12', '13', '14', '15', '16', '17', '18', '19', '20', '21', '22', '23', '24', '25'];
export const PENDING_DAYS = 7;
export const PER_ADDRESS = 3; // correos de confirmación por dirección y día
export const PER_CONN = 5; // intentos de suscripción por conexión y día
export const MIN_MS = 1500; // un formulario llenado en menos tiempo es de un programa
const DAILY_CAP = 200;
const MAX_BODY = 4096;
const CONSENT = 'v1: acepto que guarden mi correo y mis preferencias solo para mandarme este boletín (Ley 29733)';
const EMAIL_RE = /^[^@\s<>"(),;:\\[\]]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.[A-Za-z]{2,24}$/;

const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS boletin_subs (id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, status TEXT NOT NULL,
    freq TEXT NOT NULL DEFAULT 'todo', deps TEXT NOT NULL DEFAULT '', consent TEXT, created_at TEXT NOT NULL,
    confirmed_at TEXT, updated_at TEXT NOT NULL, mail_day TEXT, mail_n INTEGER NOT NULL DEFAULT 0)`,
  `CREATE TABLE IF NOT EXISTS boletin_limits (day TEXT NOT NULL, k TEXT NOT NULL, n INTEGER NOT NULL, PRIMARY KEY (day, k))`,
];

const HEADERS = {
  'Content-Type': 'application/json; charset=utf-8',
  'Cache-Control': 'no-store',
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'X-Robots-Tag': 'noindex, nofollow',
};
const json = (body, status = 200, extra = {}) => new Response(JSON.stringify(body), { status, headers: { ...HEADERS, ...extra } });
const fail = (status, error, extra) => json({ ok: false, error }, status, extra);
const nowIso = () => new Date().toISOString();
const today = () => nowIso().slice(0, 10);

let schemaReady = false;
export function resetSchemaCache() { schemaReady = false; }
async function ensureSchema(db) {
  if (schemaReady) return;
  await db.batch(SCHEMA.map((s) => db.prepare(s)));
  schemaReady = true;
}

// ------------------------------------------------------------------------------------------------- firmas
const enc = new TextEncoder();
const b64url = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
async function hmac(secret, text) {
  const key = await crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return b64url(await crypto.subtle.sign('HMAC', key, enc.encode(text)));
}
async function sha256(text) {
  return b64url(await crypto.subtle.digest('SHA-256', enc.encode(text)));
}
function randomId() {
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  return [...b].map((x) => x.toString(16).padStart(2, '0')).join('');
}
/** Comparación en tiempo constante (no deja adivinar una firma por cuánto tarda la respuesta). */
function same(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}

/** Enlace firmado para una suscripción y un uso: id (32 hex) + HMAC(secreto, uso:id:correo). Cambiar de correo o de
 * secreto invalida los enlaces anteriores. */
export async function token(env, purpose, id, email) {
  return id + (await hmac(env.BOLETIN_SECRET, `${purpose}:${id}:${email}`));
}

async function fromToken(env, db, purpose, t) {
  if (typeof t !== 'string' || !/^[0-9a-f]{32}[A-Za-z0-9_-]{43}$/.test(t)) return null;
  const row = await db.prepare('SELECT * FROM boletin_subs WHERE id = ?').bind(t.slice(0, 32)).first();
  if (!row) return null;
  return same(t, await token(env, purpose, row.id, row.email)) ? row : null;
}

// --------------------------------------------------------------------------------------------- validación
export function normEmail(v) {
  const e = String(v || '').trim().toLowerCase();
  return e.length <= 254 && EMAIL_RE.test(e) && !e.includes('..') ? e : null;
}
export const cleanDeps = (v) => (Array.isArray(v) ? [...new Set(v.map(String).filter((d) => DEPS.includes(d)))].sort() : []);
export const cleanFreq = (v) => (FREQS.includes(v) ? v : 'todo');
/** «pa***@gmail.com»: lo que muestra la página de preferencias (un correo reenviado no expone la dirección entera). */
export const mask = (e) => e.replace(/^(.{1,2})[^@]*(@.*)$/, (_, a, b) => `${a}***${b}`);

function sameOrigin(request, url) {
  const origin = request.headers.get('Origin');
  if (origin) return origin === url.origin;
  return request.headers.get('Sec-Fetch-Site') === 'same-origin';
}

async function readJson(request) {
  const text = await request.text();
  if (text.length > MAX_BODY) return null;
  try {
    const b = JSON.parse(text || '{}');
    return b && typeof b === 'object' && !Array.isArray(b) ? b : null;
  } catch { return null; }
}

const site = (env, url) => String(env.SITE_URL || `${url.origin}/`).replace(/\/?$/, '/');
const mailer = (env) => (env.RESEND_API_KEY && env.BOLETIN_FROM ? 'resend' : env.BOLETIN_MAIL_WEBHOOK && env.BOLETIN_MAIL_WEBHOOK_SECRET ? 'webhook' : null);
export const enabled = (env) => Boolean(env.GEO_DB && env.BOLETIN_SECRET && String(env.BOLETIN_SECRET).length >= 32 && mailer(env));

// ------------------------------------------------------------------------------------------------- correo
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif";

/** Correo corto de una sola columna (confirmación o «ya está suscrito»), con versión de texto. */
export function shortMail({ title, lead, button, href, note }) {
  const html = `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark"><title>${esc(title)}</title></head>
<body style="margin:0;padding:0;background-color:#f2f4f6"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" bgcolor="#f2f4f6"><tr><td align="center" style="padding:16px 8px">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" bgcolor="#ffffff" style="max-width:520px;background-color:#ffffff;border-radius:8px">
<tr><td bgcolor="#0b4f71" style="background-color:#0b4f71;padding:14px 20px;border-radius:8px 8px 0 0;font:700 18px/1.3 ${FONT};color:#ffffff">Boletín de eventos El Niño · Perú</td></tr>
<tr><td style="padding:18px 20px;font:15px/1.5 ${FONT};color:#1f1f1f"><h1 style="font:700 19px/1.3 ${FONT};margin:0 0 10px;color:#1f1f1f">${esc(title)}</h1><p style="margin:0 0 16px">${esc(lead)}</p>
<table role="presentation" cellspacing="0" cellpadding="0"><tr><td bgcolor="#0b4f71" style="border-radius:6px;background-color:#0b4f71"><a href="${esc(href)}" style="display:inline-block;padding:12px 18px;font:700 15px ${FONT};color:#ffffff;text-decoration:none">${esc(button)}</a></td></tr></table>
<p style="margin:16px 0 0;font:13px/1.5 ${FONT};color:#4a5560">Si el botón no funciona, copie este enlace en el navegador:<br><a href="${esc(href)}" style="color:#0b4f71;word-break:break-all">${esc(href)}</a></p>
<p style="margin:12px 0 0;font:13px/1.5 ${FONT};color:#4a5560">${esc(note)}</p></td></tr></table></td></tr></table></body></html>`;
  const text = `${title}\n\n${lead}\n\n${button}: ${href}\n\n${note}\n\nObservatorio ENSO Perú`;
  return { html, text };
}

async function sendMail(env, msg) {
  const how = mailer(env);
  if (how === 'resend') {
    const r = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ from: env.BOLETIN_FROM, to: [msg.to], subject: msg.subject, html: msg.html, text: msg.text }),
    });
    return r.ok;
  }
  if (how === 'webhook') {
    const r = await fetch(env.BOLETIN_MAIL_WEBHOOK, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Enso-Secret': env.BOLETIN_MAIL_WEBHOOK_SECRET },
      body: JSON.stringify({ to: msg.to, subject: msg.subject, html: msg.html, text: msg.text }),
    });
    return r.ok;
  }
  return false;
}

// ------------------------------------------------------------------------------------------------- topes
async function bump(db, day, k, max) {
  const r = await db.prepare(`INSERT INTO boletin_limits (day, k, n) VALUES (?1, ?2, 1)
    ON CONFLICT(day, k) DO UPDATE SET n = n + 1 RETURNING n`).bind(day, k).first();
  return (r?.n ?? 1) <= max;
}

// ------------------------------------------------------------------------------------------------- rutas
async function subscribe(request, env, url, db) {
  if (!sameOrigin(request, url)) return fail(403, 'Origen no permitido.');
  const b = await readJson(request);
  if (!b) return fail(400, 'Solicitud no válida.');
  const done = json({ ok: true, message: 'Si la dirección es válida, le llegó un correo para confirmar.' }, 202);
  // Trampas para programas: un campo oculto lleno o un formulario llenado en menos de 1,5 s. Se responde igual que a una
  // persona, para no enseñarle al programa qué lo delató.
  if (b.sitio_web || !(Number(b.ms) >= MIN_MS)) return done;
  const email = normEmail(b.email);
  if (!email) return fail(422, 'Revise el correo: debe tener la forma nombre@dominio.pe.');
  if (b.acepto !== true) return fail(422, 'Para suscribirse hay que aceptar el uso del correo para este boletín.');
  const day = today();
  const conn = await sha256(`${day}:${request.headers.get('CF-Connecting-IP') || ''}:${env.BOLETIN_SECRET}`);
  // Limpieza: suscripciones sin confirmar de más de 7 días y topes de días pasados.
  const old = new Date(Date.now() - PENDING_DAYS * 864e5).toISOString();
  await db.batch([
    db.prepare("DELETE FROM boletin_subs WHERE status = 'pendiente' AND created_at < ?").bind(old),
    db.prepare('DELETE FROM boletin_limits WHERE day < ?').bind(day),
  ]);
  if (!(await bump(db, day, `c:${conn}`, PER_CONN))) return fail(429, 'Demasiados intentos desde esta conexión. Inténtelo mañana.');
  const freq = cleanFreq(b.frecuencia);
  const deps = cleanDeps(b.deps).join(',');
  const t = nowIso();
  let row = await db.prepare('SELECT * FROM boletin_subs WHERE email = ?').bind(email).first();
  if (!row) {
    row = { id: randomId(), email, status: 'pendiente', freq, deps };
    await db.prepare(`INSERT INTO boletin_subs (id, email, status, freq, deps, consent, created_at, updated_at, mail_day, mail_n)
      VALUES (?, ?, 'pendiente', ?, ?, ?, ?, ?, ?, 0)`).bind(row.id, email, freq, deps, `${CONSENT} · ${t}`, t, t, day).run();
  } else if (row.status === 'pendiente') {
    await db.prepare('UPDATE boletin_subs SET freq = ?, deps = ?, consent = ?, updated_at = ? WHERE id = ?').bind(freq, deps, `${CONSENT} · ${t}`, t, row.id).run();
  }
  // Una dirección recibe a lo sumo PER_ADDRESS correos de este tipo al día: nadie puede usar el formulario para
  // inundar el buzón de otra persona.
  const n = row.mail_day === day ? Number(row.mail_n || 0) : 0;
  if (n >= PER_ADDRESS) return done;
  if (!(await bump(db, day, 'enviados', Number(env.BOLETIN_DAILY_CAP) || DAILY_CAP))) return fail(503, 'Hoy ya se mandaron muchos correos de confirmación. Inténtelo mañana.');
  const base = site(env, url);
  const msg = row.status === 'activa'
    ? shortMail({ title: 'Ya está suscrito', lead: 'Alguien (quizá usted) pidió suscribir esta dirección al boletín, y ya lo estaba. No cambió nada. Si quiere cambiar la frecuencia o los departamentos, use este enlace.', button: 'Ver mis preferencias', href: `${base}#/boletin?preferencias=${await token(env, 'preferencias', row.id, email)}`, note: 'Si no fue usted, ignore este correo.' })
    : shortMail({ title: 'Confirme su suscripción', lead: 'Recibimos un pedido para mandar el Boletín de eventos El Niño a esta dirección. Para empezar a recibirlo, confírmelo.', button: 'Confirmar mi suscripción', href: `${base}#/boletin?confirmar=${await token(env, 'confirmar', row.id, email)}`, note: `Si no lo pidió, ignore este correo: no recibirá nada y la dirección se borra en ${PENDING_DAYS} días.` });
  const ok = await sendMail(env, { to: email, subject: row.status === 'activa' ? 'Ya está suscrito al Boletín El Niño · Perú' : 'Confirme su suscripción al Boletín El Niño · Perú', ...msg });
  if (!ok) return fail(502, 'No se pudo mandar el correo de confirmación. Inténtelo de nuevo en unos minutos.');
  await db.prepare('UPDATE boletin_subs SET mail_day = ?, mail_n = ? WHERE id = ?').bind(day, n + 1, row.id).run();
  return done;
}

async function confirm(request, env, url, db) {
  if (!sameOrigin(request, url)) return fail(403, 'Origen no permitido.');
  const b = await readJson(request);
  const row = b && (await fromToken(env, db, 'confirmar', b.t));
  if (!row) return fail(404, 'El enlace no es válido o venció. Vuelva a suscribirse.');
  if (row.status !== 'activa') {
    const t = nowIso();
    await db.prepare("UPDATE boletin_subs SET status = 'activa', confirmed_at = ?, updated_at = ? WHERE id = ?").bind(t, t, row.id).run();
  }
  return json({ ok: true });
}

async function unsubscribe(request, env, url, db) {
  const ct = (request.headers.get('Content-Type') || '').toLowerCase();
  let t = url.searchParams.get('t');
  if (ct.startsWith('application/json')) {
    // Desde la página: mismo origen.
    if (!sameOrigin(request, url)) return fail(403, 'Origen no permitido.');
    t = (await readJson(request))?.t;
  } else {
    // RFC 8058: el programa de correo manda «List-Unsubscribe=One-Click» por POST, desde su servidor.
    const body = (await request.text()).slice(0, 200);
    if (!/(^|&)List-Unsubscribe=One-Click(&|$)/.test(body)) return fail(400, 'Falta List-Unsubscribe=One-Click.');
  }
  const row = await fromToken(env, db, 'baja', t);
  if (row) await db.prepare('DELETE FROM boletin_subs WHERE id = ?').bind(row.id).run();
  // Responde bien aunque ya no estuviera: la baja es idempotente y no dice si una dirección estaba en la lista.
  if (row || /^[0-9a-f]{32}[A-Za-z0-9_-]{43}$/.test(t || '')) return json({ ok: true });
  return fail(404, 'El enlace no es válido. Cópielo entero desde el correo.');
}

async function prefs(request, env, url, db, method) {
  if (method === 'GET') {
    const row = await fromToken(env, db, 'preferencias', url.searchParams.get('t'));
    if (!row || row.status !== 'activa') return fail(404, 'No se encontró una suscripción activa con este enlace.');
    return json({ ok: true, email: mask(row.email), frecuencia: row.freq, deps: row.deps ? row.deps.split(',') : [], since: row.confirmed_at });
  }
  if (!sameOrigin(request, url)) return fail(403, 'Origen no permitido.');
  const b = await readJson(request);
  const row = b && (await fromToken(env, db, 'preferencias', b.t));
  if (!row || row.status !== 'activa') return fail(404, 'No se encontró una suscripción activa con este enlace.');
  await db.prepare('UPDATE boletin_subs SET freq = ?, deps = ?, updated_at = ? WHERE id = ?').bind(cleanFreq(b.frecuencia), cleanDeps(b.deps).join(','), nowIso(), row.id).run();
  return json({ ok: true });
}

async function list(request, env, url, db) {
  const auth = request.headers.get('Authorization') || '';
  const want = env.BOLETIN_LIST_TOKEN ? `Bearer ${env.BOLETIN_LIST_TOKEN}` : '';
  if (!want || String(env.BOLETIN_LIST_TOKEN).length < 24 || !same(auth, want)) return fail(401, 'No autorizado.');
  const { results } = await db.prepare("SELECT id, email, freq, deps FROM boletin_subs WHERE status = 'activa' ORDER BY confirmed_at").all();
  const base = site(env, url);
  const api = `${url.origin}/api/boletin/baja`;
  const subs = [];
  for (const r of results) {
    const baja = await token(env, 'baja', r.id, r.email);
    subs.push({
      id: r.id, email: r.email, frecuencia: r.freq, deps: r.deps ? r.deps.split(',') : [],
      baja: `${base}#/boletin?baja=${baja}`, bajaPost: `${api}?t=${baja}`,
      preferencias: `${base}#/boletin?preferencias=${await token(env, 'preferencias', r.id, r.email)}`,
    });
  }
  return json({ ok: true, count: subs.length, subs });
}

export async function handle(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/^\/api\/boletin\/?/, '').replace(/\/$/, '');
  const method = request.method;
  const routes = { estado: ['GET'], suscribir: ['POST'], confirmar: ['POST'], baja: ['POST'], preferencias: ['GET', 'POST'], lista: ['GET'] };
  if (!routes[path]) return fail(404, 'No existe.');
  if (!routes[path].includes(method)) return fail(405, 'Método no permitido.', { Allow: routes[path].join(', ') });
  if (path === 'estado') return json({ ok: true, enabled: enabled(env) }, 200, { 'Cache-Control': 'public, max-age=300' });
  if (!enabled(env)) return fail(503, 'La suscripción por correo todavía no está habilitada.');
  const len = Number(request.headers.get('Content-Length') || 0);
  if (len > MAX_BODY) return fail(413, 'Solicitud demasiado grande.');
  const db = env.GEO_DB;
  try {
    await ensureSchema(db);
    if (path === 'suscribir') return await subscribe(request, env, url, db);
    if (path === 'confirmar') return await confirm(request, env, url, db);
    if (path === 'baja') return await unsubscribe(request, env, url, db);
    if (path === 'preferencias') return await prefs(request, env, url, db, method);
    return await list(request, env, url, db);
  } catch (e) {
    console.error('boletin-subs', e && e.message);
    return fail(500, 'Error del servidor. Inténtelo de nuevo en un momento.');
  }
}
