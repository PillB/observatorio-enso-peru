// Pruebas de la API de la consola de lugares (functions/_lib/geo-console.js) con una D1 de mentira.
// Se corren con `node --test` (las lanza tests/test_geo_console.py).
import assert from 'node:assert/strict';
import { beforeEach, describe, it } from 'node:test';

import {
  COOKIE, handle, hashPassword, resetSchemaCache, resetUbigeoCache, verifyPassword,
} from '../../../functions/_lib/geo-console.js';
import { FakeD1 } from './fake-d1.mjs';

const ORIGIN = 'https://enso-peru.pages.dev';
const ITEM = '0123456789abcdef';
const UBIGEO = { departments: { 15: 'Lima', 20: 'Piura' }, provinces: { 1501: 'Lima' }, districts: { 150101: 'Lima', 150122: 'Miraflores' } };

let env;
let users;

async function makeEnv() {
  resetSchemaCache();
  resetUbigeoCache();
  if (!users) {
    users = {
      pablo: { hash: await hashPassword('clave-admin-123'), role: 'admin' },
      revisor01: { hash: await hashPassword('clave-revisor-1'), role: 'tester' },
      revisor02: { hash: await hashPassword('clave-revisor-2'), role: 'tester' },
    };
  }
  return {
    GEO_DB: new FakeD1(),
    GEO_USERS: JSON.stringify(users),
    ASSETS: { fetch: async (u) => (String(u).endsWith('/data/geo/ubigeo.json') ? new Response(JSON.stringify(UBIGEO)) : new Response('', { status: 404 })) },
  };
}

function req(path, { method = 'GET', body, cookie, origin = ORIGIN, ip = '203.0.113.7', type = 'application/json', headers = {} } = {}) {
  const h = { 'CF-Connecting-IP': ip, ...headers };
  if (origin) h.Origin = origin;
  if (cookie) h.Cookie = `${COOKIE}=${cookie}`;
  if (body !== undefined) h['Content-Type'] = type;
  return new Request(`${ORIGIN}/api/geo/${path}`, { method, headers: h, body: body === undefined ? undefined : typeof body === 'string' ? body : JSON.stringify(body) });
}

async function login(username = 'revisor01', password = 'clave-revisor-1', ip) {
  const r = await handle(req('login', { method: 'POST', body: { username, password }, ip }), env);
  const set = r.headers.get('Set-Cookie') || '';
  const m = set.match(new RegExp(`${COOKIE}=([^;]+)`));
  return { r, cookie: m ? m[1] : null, set };
}

beforeEach(async () => {
  env = await makeEnv();
});

describe('contraseñas', () => {
  it('verifica PBKDF2 y rechaza otra clave o un formato raro', async () => {
    const h = await hashPassword('secreta');
    assert.ok(await verifyPassword('secreta', h));
    assert.ok(!(await verifyPassword('Secreta', h)));
    assert.ok(!(await verifyPassword('secreta', 'md5$abc')));
    assert.ok(!(await verifyPassword('secreta', 'pbkdf2-sha256$5000000$AAAA$AAAA')));
  });

  it('acepta los hashes que genera python/tools/geo_users.py', { skip: !process.env.GEO_TEST_PY_HASH }, async () => {
    assert.ok(await verifyPassword('clave-de-prueba', process.env.GEO_TEST_PY_HASH));
    assert.ok(!(await verifyPassword('otra', process.env.GEO_TEST_PY_HASH)));
  });
});

describe('ingreso', () => {
  it('entrega una cookie segura y la sesión sirve para /me', async () => {
    const { r, cookie, set } = await login();
    assert.equal(r.status, 200);
    assert.match(set, /HttpOnly/);
    assert.match(set, /Secure/);
    assert.match(set, /SameSite=Strict/);
    assert.equal(r.headers.get('Cache-Control'), 'no-store');
    const me = await handle(req('me', { cookie }), env);
    assert.equal(me.status, 200);
    assert.deepEqual(await me.json(), { username: 'revisor01', role: 'tester' });
  });

  it('no guarda el token en claro', async () => {
    const { cookie } = await login();
    const rows = (await env.GEO_DB.prepare('SELECT token_hash FROM sessions').all()).results;
    assert.equal(rows.length, 1);
    assert.notEqual(rows[0].token_hash, cookie);
  });

  it('mismo mensaje para usuario inexistente y clave equivocada', async () => {
    const a = await login('revisor01', 'mal');
    const b = await login('nadie', 'mal');
    assert.equal(a.r.status, 401);
    assert.equal(b.r.status, 401);
    assert.deepEqual(await a.r.json(), await b.r.json());
  });

  it('bloquea tras varios fallos y lo registra', async () => {
    let last;
    for (let i = 0; i < 9; i++) last = await login('revisor02', `mal-${i}`);
    assert.equal(last.r.status, 429);
    const ok = await login('revisor02', 'clave-revisor-2');
    assert.equal(ok.r.status, 429, 'ni con la clave correcta mientras dure el bloqueo');
    const ev = (await env.GEO_DB.prepare("SELECT COUNT(*) AS n FROM audit WHERE event = 'login-bloqueado'").first()).n;
    assert.ok(ev >= 1);
  });

  it('rechaza escrituras de otro origen o sin JSON', async () => {
    const other = await handle(req('login', { method: 'POST', body: { username: 'revisor01', password: 'clave-revisor-1' }, origin: 'https://evil.example' }), env);
    assert.equal(other.status, 403);
    const noOrigin = await handle(req('login', { method: 'POST', body: {}, origin: null }), env);
    assert.equal(noOrigin.status, 403);
    const form = await handle(req('login', { method: 'POST', body: 'username=x', type: 'application/x-www-form-urlencoded' }), env);
    assert.equal(form.status, 415);
  });

  it('sin sesión no hay datos; la cookie de un usuario dado de baja deja de valer', async () => {
    assert.equal((await handle(req('me'), env)).status, 401);
    assert.equal((await handle(req('corrections'), env)).status, 401);
    const { cookie } = await login();
    const gone = { ...env, GEO_USERS: JSON.stringify({ pablo: users.pablo }) };
    assert.equal((await handle(req('me', { cookie }), gone)).status, 401);
  });

  it('cerrar sesión borra la sesión', async () => {
    const { cookie } = await login();
    const out = await handle(req('logout', { method: 'POST', body: {}, cookie }), env);
    assert.equal(out.status, 200);
    assert.match(out.headers.get('Set-Cookie'), /Max-Age=0/);
    assert.equal((await handle(req('me', { cookie }), env)).status, 401);
  });

  it('sin base o sin usuarios responde 503 con un mensaje claro', async () => {
    assert.equal((await handle(req('me'), { GEO_USERS: '{}' })).status, 503);
    const r = await handle(req('login', { method: 'POST', body: { username: 'a', password: 'b' } }), { ...env, GEO_USERS: '' });
    assert.equal(r.status, 503);
  });
});

describe('correcciones', () => {
  it('crea, versiona, publica sin nombres y deja auditoría', async () => {
    const { cookie } = await login();
    const c1 = await handle(req('corrections', { method: 'POST', cookie, body: { item: ITEM, action: 'set', places: ['150122'], note: 'es Miraflores de Lima', expectedRev: 0, before: { places: [{ code: '20' }] } } }), env);
    assert.equal(c1.status, 201);
    assert.equal((await c1.json()).rev, 1);
    const pub = await handle(req('overrides', { origin: null }), env);
    assert.equal(pub.status, 200);
    const body = await pub.json();
    assert.deepEqual(body.overrides.map((o) => [o.id, o.action, o.places, o.rev]), [[ITEM, 'set', ['150122'], 1]]);
    assert.ok(!JSON.stringify(body).includes('revisor01'), 'la lista pública no lleva usuarios');
    assert.ok(!JSON.stringify(body).includes('Miraflores de Lima'), 'ni notas');
    const hist = await (await handle(req(`corrections?item=${ITEM}`, { cookie }), env)).json();
    assert.equal(hist.corrections[0].username, 'revisor01');
    assert.equal(hist.corrections[0].note, 'es Miraflores de Lima');
    const audit = await (await handle(req('audit', { cookie }), env)).json();
    assert.ok(audit.events.some((e) => e.event === 'correccion' && e.item_id === ITEM));
  });

  it('detecta ediciones simultáneas (409) y deshacer devuelve la nota a la ubicación automática', async () => {
    const a = (await login('revisor01', 'clave-revisor-1')).cookie;
    const b = (await login('revisor02', 'clave-revisor-2', '198.51.100.2')).cookie;
    const ok = await handle(req('corrections', { method: 'POST', cookie: a, body: { item: ITEM, action: 'confirm', expectedRev: 0 } }), env);
    assert.equal(ok.status, 201);
    const late = await handle(req('corrections', { method: 'POST', cookie: b, body: { item: ITEM, action: 'none', expectedRev: 0 } }), env);
    assert.equal(late.status, 409);
    const clear = await handle(req('corrections', { method: 'POST', cookie: b, body: { item: ITEM, action: 'clear', expectedRev: 1 } }), env);
    assert.equal(clear.status, 201);
    const pub = await (await handle(req('overrides', { origin: null }), env)).json();
    assert.deepEqual(pub.overrides, []);
    const hist = await (await handle(req(`corrections?item=${ITEM}`, { cookie: a }), env)).json();
    assert.deepEqual(hist.corrections.map((c) => c.action), ['clear', 'confirm'], 'el historial no se borra');
  });

  it('valida nota, acción y códigos', async () => {
    const { cookie } = await login();
    const post = (body) => handle(req('corrections', { method: 'POST', cookie, body }), env);
    assert.equal((await post({ item: 'xyz', action: 'set', places: ['15'] })).status, 400);
    assert.equal((await post({ item: ITEM, action: 'borrar' })).status, 400);
    assert.equal((await post({ item: ITEM, action: 'set', places: [] })).status, 400);
    assert.equal((await post({ item: ITEM, action: 'set', places: ['99'] })).status, 400);
    assert.equal((await post({ item: ITEM, action: 'set', places: ['150199'] })).status, 400, 'no existe en el nomenclátor');
    assert.equal((await post({ item: ITEM, action: 'clear' })).status, 400, 'nada que deshacer');
    assert.equal((await handle(req('corrections', { method: 'POST', cookie, body: '{malo' }), env)).status, 400);
    assert.equal((await handle(req('corrections', { method: 'POST', cookie, body: 'x'.repeat(20000) }), env)).status, 413);
  });

  it('las rutas desconocidas o con otro método no hacen nada', async () => {
    assert.equal((await handle(req('nada'), env)).status, 404);
    assert.equal((await handle(req('overrides', { method: 'POST', body: {} }), env)).status, 405);
    assert.equal((await handle(req('me', { method: 'DELETE' }), env)).status, 405);
  });
});
