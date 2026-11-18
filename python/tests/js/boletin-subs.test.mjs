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
  sent.push({ url: String(url), headers: init.headers, body: JSON.parse(init.body) });
  return new Response('{}', { status: env.MAIL_FAILS ? 500 : 200 });
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
    assert.match(sent[0].body.text, /confirmar=/);
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
