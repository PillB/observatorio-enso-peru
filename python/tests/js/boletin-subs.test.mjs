// Pruebas de la suscripción al boletín por correo (functions/_lib/boletin-subs.js) con una D1 de mentira y un
// «servidor de correo» de mentira (fetch reemplazado). Se corren con `node --test` (las lanza tests/test_boletin.py).
import assert from 'node:assert/strict';
import { beforeEach, describe, it } from 'node:test';

import { PER_ADDRESS, PER_CONN, cleanDeps, handle, mask, normEmail, resetSchemaCache } from '../../../functions/_lib/boletin-subs.js';
import { FakeD1 } from './fake-d1.mjs';

const ORIGIN = 'https://enso-peru.pages.dev';
const LIST = 'una-clave-de-lectura-de-la-lista-larga';
let env;
let sent;

globalThis.fetch = async (url, init) => {
  if (env.HANG) throw new DOMException('The operation was aborted due to timeout', 'TimeoutError');
  const body = JSON.parse(init.body);
  // Un nginx delante de n8n que corta los pedidos sin User-Agent (como el de producción) o, con PROXY_BLOCK, todos.
  // Como el de producción, también corta los cuerpos con HTML (por eso el sitio manda el correo en base64).
  if (!init.headers['User-Agent'] || env.PROXY_BLOCK || /<(!doctype|meta|style|html)/i.test(init.body)) return new Response('<html><head><title>403 Forbidden</title></head><body><center><h1>403 Forbidden</h1></center></body></html>', { status: 403 });
  // Un n8n de mentira para el diagnóstico: 404 si el flujo no está publicado, 403 con otro secreto y 500 con el bueno
  // (el pedido vacío hace fallar «Armar correo»).
  if (body.diagnostico) {
    if (env.HOOK_404) return new Response('{"message":"not registered"}', { status: 404 });
    return new Response('{"message":"x"}', { status: init.headers['X-Enso-Secret'] === env.N8N_SECRET ? 500 : 403 });
  }
  // Lo que decodifica n8n (n8n/nodes/boletin-confirmar.js).
  if (body.enc === 'base64') {
    // …y corta los cuerpos de más de 8 KB (medido en producción: 8085 bytes pasa, 8353 no).
    if (init.body.length > 8000) return new Response('<html><head><title>403 Forbidden</title></head></html>', { status: 403 });
    for (const k of ['subject', 'html']) body[k] = Buffer.from(body[`${k}_b64`], 'base64').toString('utf8');
  }
  sent.push({ url: String(url), headers: init.headers, body });
  if (env.MAIL_FAILS) return new Response('{}', { status: typeof env.MAIL_FAILS === 'number' ? env.MAIL_FAILS : 500 });
  // Como «Responder» de n8n: 202 {"ok":true}. Con EMPTY_200, como n8n 1.x cuando el flujo falla: 200 vacío.
  if (/webhook/.test(String(url))) return env.EMPTY_200 ? new Response('', { status: 200 }) : new Response('{"ok":true}', { status: 202 });
  return new Response('{}', { status: 200 });
};

const req = (path, { method = 'POST', body, origin = ORIGIN, headers = {}, ip = '1.2.3.4' } = {}) => {
  const h = { 'CF-Connecting-IP': ip, ...headers };
  if (origin) h.Origin = origin;
  if (body !== undefined && !h['Content-Type']) h['Content-Type'] = 'application/json';
  return handle(new Request(`${ORIGIN}/api/boletin/${path}`, { method, headers: h, body: typeof body === 'string' ? body : body === undefined ? undefined : JSON.stringify(body) }), env);
};
const subscribe = (email, extra = {}, opts = {}) => req('suscribir', { body: { email, acepto: true, ms: 4000, frecuencia: 'todo', deps: [], ...extra }, ...opts });
const lastLink = (kind) => {
  const m = sent.at(-1).body.html.match(new RegExp(`#/boletin\\?${kind}=([A-Za-z0-9_-]+)`));
  return m && m[1];
};
const rows = () => env.GEO_DB.sqlite.prepare('SELECT email, status, freq, deps FROM boletin_subs ORDER BY email').all().map((r) => ({ ...r }));

describe('suscripción al boletín', () => {
  beforeEach(() => {
    resetSchemaCache();
    sent = [];
    env = { GEO_DB: new FakeD1(), BOLETIN_SECRET: 'x'.repeat(40), BOLETIN_LIST_TOKEN: LIST, BOLETIN_MAIL_WEBHOOK: 'https://n8n.example/webhook/confirmar', BOLETIN_MAIL_WEBHOOK_SECRET: 's3cr3t', SITE_URL: `${ORIGIN}/` };
  });

  it('dice si está habilitada y no hace nada sin configuración', async () => {
    assert.deepEqual(await (await req('estado', { method: 'GET' })).json(), { ok: true, enabled: true });
    env = { GEO_DB: new FakeD1(), BOLETIN_SECRET: 'corto' };
    assert.equal((await (await req('estado', { method: 'GET' })).json()).enabled, false);
    assert.equal((await subscribe('ana@example.pe')).status, 503);
  });

  it('doble confirmación: nada se activa hasta pulsar «Confirmar»', async () => {
    const r = await subscribe('Ana@Example.PE', { frecuencia: 'importantes', deps: ['20', '24', '99', '20'] });
    assert.equal(r.status, 202);
    assert.equal(sent.length, 1);
    assert.equal(sent[0].url, 'https://n8n.example/webhook/confirmar');
    assert.equal(sent[0].headers['X-Enso-Secret'], 's3cr3t');
    assert.equal(sent[0].body.to, 'ana@example.pe');
    assert.match(sent[0].body.subject, /Confirme/);
    assert.match(sent[0].body.html, /confirmar=/);
    assert.equal(sent[0].body.text, undefined);
    assert.deepEqual(rows(), [{ email: 'ana@example.pe', status: 'pendiente', freq: 'importantes', deps: '20,24' }]);
    // La lista no la trae todavía.
    let l = await (await req('lista', { method: 'GET', origin: null, headers: { Authorization: `Bearer ${LIST}` } })).json();
    assert.equal(l.count, 0);
    const t = lastLink('confirmar');
    assert.equal((await req('confirmar', { body: { t } })).status, 200);
    assert.equal(rows()[0].status, 'activa');
    // Confirmar dos veces no rompe nada.
    assert.equal((await req('confirmar', { body: { t } })).status, 200);
    l = await (await req('lista', { method: 'GET', origin: null, headers: { Authorization: `Bearer ${LIST}` } })).json();
    assert.equal(l.count, 1);
    assert.deepEqual(l.subs[0].deps, ['20', '24']);
    // El id (fijo mientras dure la suscripción) le sirve a n8n para saber a quién no le dio la bienvenida.
    assert.match(l.subs[0].id, /^[0-9a-f]{32}$/);
    assert.match(l.subs[0].baja, /#\/boletin\?baja=[0-9a-f]{32}/);
    assert.match(l.subs[0].bajaPost, /\/api\/boletin\/baja\?t=/);
  });

  it('un enlace alterado, de otro uso o de otro secreto no sirve', async () => {
    await subscribe('ana@example.pe');
    const t = lastLink('confirmar');
    const bad = t.slice(0, -1) + (t.endsWith('A') ? 'B' : 'A');
    assert.equal((await req('confirmar', { body: { t: bad } })).status, 404);
    assert.equal((await req('preferencias', { method: 'GET', origin: null })).status, 404);
    // El enlace de confirmación no sirve para dar de baja ni para ver preferencias.
    await req('confirmar', { body: { t } });
    assert.equal((await req(`preferencias?t=${t}`, { method: 'GET' })).status, 404);
    env.BOLETIN_SECRET = 'y'.repeat(40);
    assert.equal((await req('confirmar', { body: { t } })).status, 404);
  });

  it('confirmar y cambiar preferencias piden el mismo origen; la baja en un clic (RFC 8058) no', async () => {
    await subscribe('ana@example.pe');
    const t = lastLink('confirmar');
    assert.equal((await req('confirmar', { body: { t }, origin: 'https://otro.example' })).status, 403);
    assert.equal((await subscribe('b@example.pe', {}, { origin: 'https://otro.example' })).status, 403);
    await req('confirmar', { body: { t } });
    const l = await (await req('lista', { method: 'GET', headers: { Authorization: `Bearer ${LIST}` } })).json();
    const post = l.subs[0].bajaPost.replace(ORIGIN, '');
    // Sin el cuerpo de RFC 8058, no.
    assert.equal((await handle(new Request(ORIGIN + post, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: 'x=1' }), env)).status, 400);
    const r = await handle(new Request(ORIGIN + post, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded', Origin: 'https://mail.google.com' }, body: 'List-Unsubscribe=One-Click' }), env);
    assert.equal(r.status, 200);
    assert.deepEqual(rows(), []);
    // Otra vez: sigue respondiendo bien (idempotente) y no dice si estaba.
    assert.equal((await handle(new Request(ORIGIN + post, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: 'List-Unsubscribe=One-Click' }), env)).status, 200);
  });

  it('preferencias: correo enmascarado, cambios validados', async () => {
    await subscribe('analucia@example.pe');
    await req('confirmar', { body: { t: lastLink('confirmar') } });
    const l = await (await req('lista', { method: 'GET', headers: { Authorization: `Bearer ${LIST}` } })).json();
    const t = new URL(l.subs[0].preferencias.replace('#/boletin?', '?')).searchParams.get('preferencias');
    const g = await (await req(`preferencias?t=${t}`, { method: 'GET' })).json();
    assert.equal(g.email, 'an***@example.pe');
    assert.equal((await req('preferencias', { body: { t, frecuencia: 'nada', deps: ['15', 'x'] } })).status, 200);
    assert.deepEqual(rows()[0], { email: 'analucia@example.pe', status: 'activa', freq: 'todo', deps: '15' });
    assert.equal((await req('preferencias', { body: { t, frecuencia: 'semanal', deps: [] } })).status, 200);
    assert.equal(rows()[0].freq, 'semanal');
    // La baja desde la página (JSON) borra la fila.
    const b = new URL(l.subs[0].baja.replace('#/boletin?', '?')).searchParams.get('baja');
    assert.equal((await req('baja', { body: { t: b } })).status, 200);
    assert.deepEqual(rows(), []);
  });

  it('la lista acepta «Bearer <token>» o el token solo, y nada más', async () => {
    const get = (a) => req('lista', { method: 'GET', origin: null, headers: a == null ? {} : { Authorization: a } });
    for (const a of [`Bearer ${LIST}`, `bearer  ${LIST} `, LIST]) assert.equal((await get(a)).status, 200, a);
    for (const a of [null, '', 'Bearer', `Bearer ${LIST}x`, `Basic ${LIST}`, LIST.slice(1)]) assert.equal((await get(a)).status, 401, String(a));
  });

  it('si falta un secreto, la lista y el diagnóstico dicen cuál (solo a quien tiene la clave)', async () => {
    delete env.BOLETIN_MAIL_WEBHOOK_SECRET;
    assert.deepEqual(await (await req('estado', { method: 'GET' })).json(), { ok: true, enabled: false });
    assert.equal((await subscribe('ana@example.pe')).status, 503);
    // Sin la clave: 401 y nada sobre la configuración.
    const anon = await req('lista', { method: 'GET', origin: null });
    assert.equal(anon.status, 401);
    assert.doesNotMatch(JSON.stringify(await anon.json()), /BOLETIN/);
    const l = await req('lista', { method: 'GET', origin: null, headers: { Authorization: `Bearer ${LIST}` } });
    assert.equal(l.status, 503);
    assert.match((await l.json()).error, /falta BOLETIN_MAIL_WEBHOOK_SECRET\..*Producción/);
    const d = await (await req('diagnostico', { body: { clave: LIST } })).json();
    assert.deepEqual(d.faltan, ['BOLETIN_MAIL_WEBHOOK_SECRET']);
    assert.equal(d.secrets.BOLETIN_MAIL_WEBHOOK_SECRET.set, false);
    assert.equal(d.secrets.BOLETIN_MAIL_WEBHOOK.set, true);
    assert.equal((await req('diagnostico', { body: { clave: LIST, enviar_a: 'yo@example.pe' } })).status, 503);
    assert.equal((await req('diagnostico', { body: { clave: 'otra-clave-cualquiera-bastante-larga' } })).status, 401);
    // Sin la base vinculada, el diagnóstico también responde.
    delete env.GEO_DB;
    resetSchemaCache();
    const d2 = await req('diagnostico', { body: { clave: LIST } });
    assert.equal(d2.status, 200);
    assert.deepEqual((await d2.json()).faltan, ['GEO_DB (vínculo con la base D1)', 'BOLETIN_MAIL_WEBHOOK_SECRET']);
    assert.equal(sent.length, 0);
  });

  it('el pedido a n8n no lleva HTML en claro y cabe en 8 KB aun con la dirección más larga', async () => {
    const long = `${'a'.repeat(64)}@${'b'.repeat(63)}.${'c'.repeat(63)}.${'d'.repeat(58)}.pe`;
    assert.equal(long.length, 254);
    assert.equal((await subscribe(long)).status, 202);
    await req('confirmar', { body: { t: lastLink('confirmar') } });
    assert.equal((await subscribe(long, {}, { ip: '5.5.5.5' })).status, 202);
    assert.equal(sent.length, 2);
    assert.match(sent[1].body.subject, /Ya está/);
    for (const m of sent) assert.match(m.body.html, /^<!doctype html>/);
  });

  it('no deja averiguar quién está suscrito ni inundar un buzón', async () => {
    await subscribe('ana@example.pe');
    await req('confirmar', { body: { t: lastLink('confirmar') } });
    const again = await subscribe('ana@example.pe');
    assert.equal(again.status, 202);
    assert.deepEqual(await again.json(), await (await subscribe('nueva@example.pe', {}, { ip: '9.9.9.9' })).json());
    // A quien ya está suscrito le llega «ya está suscrito», no otra confirmación.
    assert.match(sent.find((m) => m.body.to === 'ana@example.pe' && /Ya está/.test(m.body.subject)).body.html, /preferencias=/);
    sent = [];
    for (let i = 0; i < 6; i++) await subscribe('victima@example.pe', {}, { ip: `10.0.0.${i}` });
    assert.equal(sent.length, PER_ADDRESS);
  });

  it('trampas para programas y topes por conexión', async () => {
    assert.equal((await subscribe('bot@example.pe', { sitio_web: 'http://spam' })).status, 202);
    assert.equal((await subscribe('bot2@example.pe', { ms: 200 })).status, 202);
    assert.equal(sent.length, 0);
    assert.deepEqual(rows(), []);
    assert.equal((await subscribe('x@example.pe', { acepto: false })).status, 422);
    assert.equal((await subscribe('no-es-correo')).status, 422);
    assert.equal((await subscribe('a@b..pe')).status, 422);
    for (let i = 0; i < PER_CONN; i++) await subscribe(`p${i}@example.pe`, {}, { ip: '5.5.5.5' });
    assert.equal((await subscribe('ultimo@example.pe', {}, { ip: '5.5.5.5' })).status, 429);
  });

  it('si el correo no sale, lo dice y deja reintentar', async () => {
    env.MAIL_FAILS = true;
    assert.equal((await subscribe('ana@example.pe')).status, 502);
    env.MAIL_FAILS = false;
    assert.equal((await subscribe('ana@example.pe')).status, 202);
  });

  it('un 200 vacío de n8n (el flujo falló antes de «Responder») no cuenta como enviado', async () => {
    const logs = [];
    const orig = console.error;
    console.error = (m) => logs.push(String(m));
    try {
      env.EMPTY_200 = true;
      assert.equal((await subscribe('eva@example.pe')).status, 502);
    } finally { console.error = orig; delete env.EMPTY_200; }
    assert.match(logs.join(' '), /HTTP 200 sin confirmar el envío \(vacío\).*Responder/);
    assert.ok(!logs.join(' ').includes('eva@'));
    assert.equal((await subscribe('eva@example.pe')).status, 202);
  });

  it('el diagnóstico pide la clave, da huellas sin los valores y prueba el webhook', async () => {
    const diag = (body, opts) => req('diagnostico', { body, ...opts });
    assert.equal((await diag({ clave: 'otra' })).status, 401);
    assert.equal((await diag({ clave: LIST }, { origin: 'https://otro.example' })).status, 403);
    env.N8N_SECRET = 's3cr3t';
    env.BOLETIN_MAIL_WEBHOOK_SECRET = 's3cr3t\n';
    let r = await (await diag({ clave: LIST })).json();
    const text = JSON.stringify(r);
    assert.ok(!text.includes(LIST) && !text.includes('s3cr3t') && !text.includes('xxxxxxxx'));
    assert.equal(r.secrets.BOLETIN_MAIL_WEBHOOK_SECRET.length, 7);
    assert.match(r.secrets.BOLETIN_MAIL_WEBHOOK_SECRET.issues[0], /espacios o saltos de línea/);
    assert.match(r.secrets.BOLETIN_LIST_TOKEN.sha256_12, /^[0-9a-f]{12}$/);
    assert.equal(r.webhook.con_secreto.status, 403); // el salto de línea sobrante
    assert.match(r.webhook.verdict, /rechaza el secreto/);
    env.BOLETIN_MAIL_WEBHOOK_SECRET = 's3cr3t';
    r = await (await diag({ clave: LIST })).json();
    assert.equal(r.webhook.secreto_falso.status, 403);
    assert.match(r.webhook.verdict, /^Bien/);
    assert.match(r.webhook.issues[0], /enso-boletin-confirmar/);
    env.HOOK_404 = true;
    r = await (await diag({ clave: LIST })).json();
    assert.match(r.webhook.verdict, /no está publicado/);
    env.HOOK_404 = false;
    env.PROXY_BLOCK = true;
    r = await (await diag({ clave: LIST })).json();
    assert.match(r.webhook.verdict, /servidor delante de n8n/);
    env.PROXY_BLOCK = false;
    // Con «enviar_a», un correo de verdad por la misma vía.
    r = await (await diag({ clave: LIST, enviar_a: 'Yo@Example.pe' })).json();
    assert.equal(r.prueba.sent, true);
    assert.equal(sent.at(-1).body.to, 'yo@example.pe');
    assert.equal((await diag({ clave: LIST, enviar_a: 'no' })).status, 422);
    // El correo de prueba cuenta en el tope diario de correos.
    env.BOLETIN_DAILY_CAP = '1';
    assert.equal((await diag({ clave: LIST, enviar_a: 'yo@example.pe' })).status, 503);
    delete env.BOLETIN_DAILY_CAP;
    // Un n8n que no contesta: se corta y se dice, sin la dirección.
    env.HANG = true;
    const errs = [];
    const orig = console.error;
    console.error = (m) => errs.push(String(m));
    try {
      r = await (await diag({ clave: LIST, enviar_a: 'yo@example.pe' })).json();
    } finally { console.error = orig; }
    env.HANG = false;
    assert.equal(r.webhook.con_secreto.status, 0);
    assert.match(r.webhook.verdict, /No se pudo llegar a n8n/);
    assert.equal(r.prueba.sent, false);
    assert.match(r.prueba.detail, /timeout/);
    assert.ok(!r.prueba.detail.includes('yo@') && !errs.join(' ').includes('yo@'));
  });

  it('el motivo de la falla queda en el registro de la función, sin la dirección', async () => {
    const logs = [];
    const orig = console.error;
    console.error = (m) => logs.push(String(m));
    try {
      env.MAIL_FAILS = 404;
      assert.equal((await subscribe('luis@example.pe')).status, 502);
      env.MAIL_FAILS = 403;
      assert.equal((await subscribe('luis@example.pe')).status, 502);
      env.MAIL_FAILS = false;
      env.BOLETIN_MAIL_WEBHOOK = 'https://n8n.example/webhook-test/enso-boletin-confirmar';
      await subscribe('luis@example.pe');
    } finally { console.error = orig; }
    assert.match(logs[0], /HTTP 404.*no está publicado/);
    assert.match(logs[1], /HTTP 403.*BOLETIN_MAIL_WEBHOOK_SECRET/);
    assert.match(logs[2], /webhook-test/);
    assert.ok(!logs.join(' ').includes('luis@'));
  });

  it('la lista pide su clave', async () => {
    assert.equal((await req('lista', { method: 'GET' })).status, 401);
    assert.equal((await req('lista', { method: 'GET', headers: { Authorization: 'Bearer otra' } })).status, 401);
    assert.equal((await req('nada', { method: 'GET' })).status, 404);
    assert.equal((await req('suscribir', { method: 'GET' })).status, 405);
  });

  it('ayudas', () => {
    assert.equal(normEmail(' A@B.pe '), 'a@b.pe');
    assert.equal(normEmail('a@b'), null);
    assert.equal(normEmail('<a@b.pe>'), null);
    assert.equal(normEmail(`${'a'.repeat(65)}@b.pe`), null);
    assert.deepEqual(cleanDeps(['25', '01', '01', '26', 3]), ['01', '25']);
    assert.equal(mask('x@y.pe'), 'x***@y.pe');
  });
});
