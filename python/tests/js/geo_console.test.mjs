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
    const slow = await hashPassword('secreta', new Uint8Array(16), 20000);
    assert.ok(!(await verifyPassword('secreta', slow)), 'más de 8 000 iteraciones no cabe en 10 ms de CPU');
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

describe('consumo del plan gratuito', () => {
  it('base nueva: las tablas se crean solas y luego no se vuelven a crear', async () => {
    const r = await handle(req('overrides', { origin: null }), env);
    assert.equal(r.status, 200);
    const t0 = env.GEO_DB.trips;
    await handle(req('overrides', { origin: null }), env);
    assert.equal(env.GEO_DB.trips - t0, 1, 'una sola consulta por pedido del pipeline');
  });

  it('ingreso en 2 viajes; un fallo en 2; un bloqueo en 1 y sin escribir', async () => {
    await handle(req('overrides', { origin: null }), env); // crea las tablas
    let t0 = env.GEO_DB.trips;
    const { cookie } = await login();
    assert.equal(env.GEO_DB.trips - t0, 2);
    t0 = env.GEO_DB.trips;
    await handle(req('me', { cookie }), env);
    assert.equal(env.GEO_DB.trips - t0, 1);
    t0 = env.GEO_DB.trips;
    await login('revisor02', 'mal');
    assert.equal(env.GEO_DB.trips - t0, 2);
    for (let i = 0; i < 8; i++) await login('revisor02', 'mal');
    const writes = (await env.GEO_DB.prepare('SELECT COUNT(*) AS n FROM audit').first()).n;
    t0 = env.GEO_DB.trips;
    assert.equal((await login('revisor02', 'mal')).r.status, 429);
    assert.equal(env.GEO_DB.trips - t0, 1);
    assert.equal((await env.GEO_DB.prepare('SELECT COUNT(*) AS n FROM audit').first()).n, writes, 'bloqueado no escribe');
  });

  it('nombres inventados no crean contadores por usuario', async () => {
    for (let i = 0; i < 5; i++) await login(`nadie${i}`, 'mal');
    const keys = (await env.GEO_DB.prepare('SELECT key FROM attempts').all()).results.map((r) => r.key);
    assert.deepEqual(keys, ['ip:203.0.113.7']);
  });

  it('una corrección en 3 viajes; la lista vigente lee una fila por nota', async () => {
    const { cookie } = await login();
    const t0 = env.GEO_DB.trips;
    const r = await handle(req('corrections', { method: 'POST', cookie, body: { item: ITEM, action: 'none', expectedRev: 0 } }), env);
    assert.equal(r.status, 201);
    assert.equal(env.GEO_DB.trips - t0, 3);
    for (let rev = 1; rev < 4; rev++) {
      await handle(req('corrections', { method: 'POST', cookie, body: { item: ITEM, action: rev % 2 ? 'confirm' : 'none', expectedRev: rev } }), env);
    }
    const cur = (await env.GEO_DB.prepare('SELECT item_id, rev, action FROM current').all()).results;
    assert.deepEqual(cur, [{ item_id: ITEM, rev: 4, action: 'confirm' }]);
    const latest = await (await handle(req('corrections', { cookie }), env)).json();
    assert.deepEqual(latest.corrections.map((c) => [c.item, c.rev]), [[ITEM, 4]]);
    const plan = env.GEO_DB.sqlite.prepare("EXPLAIN QUERY PLAN SELECT item_id, action, places, rev, created_at FROM current WHERE action != 'clear' ORDER BY item_id").all();
    assert.ok(plan.every((p) => !/TEMP B-TREE/.test(p.detail)), JSON.stringify(plan));
  });

  it('el tope de correcciones por hora se lleva en un contador', async () => {
    const { cookie } = await login();
    await env.GEO_DB.prepare("INSERT INTO attempts (key, count, window_start) VALUES ('write:revisor01', 600, ?)").bind(Math.floor(Date.now() / 1000) - 10).run();
    const r = await handle(req('corrections', { method: 'POST', cookie, body: { item: ITEM, action: 'none', expectedRev: 0 } }), env);
    assert.equal(r.status, 429);
    await env.GEO_DB.prepare("UPDATE attempts SET window_start = window_start - 3600 WHERE key = 'write:revisor01'").run();
    const ok = await handle(req('corrections', { method: 'POST', cookie, body: { item: ITEM, action: 'none', expectedRev: 0 } }), env);
    assert.equal(ok.status, 201, 'la ventana vencida se reinicia');
  });

  it('una base creada antes de la tabla current se completa sola', async () => {
    const db = env.GEO_DB;
    db.sqlite.exec(`CREATE TABLE corrections (id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL, rev INTEGER NOT NULL,
      action TEXT NOT NULL, places TEXT, note TEXT, before TEXT, username TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE (item_id, rev));
      INSERT INTO corrections (item_id, rev, action, places, username, created_at) VALUES
        ('${ITEM}', 1, 'set', '["15"]', 'pablo', '2026-10-01T00:00:00Z'), ('${ITEM}', 2, 'set', '["20"]', 'pablo', '2026-10-02T00:00:00Z');`);
    const pub = await (await handle(req('overrides', { origin: null }), env)).json();
    assert.deepEqual(pub.overrides.map((o) => [o.rev, o.places]), [[2, ['20']]]);
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
    const pub0 = await (await handle(req('overrides', { origin: null }), env)).json();
    assert.deepEqual(pub0.overrides[0].places, [], 'confirmar sin lugares es válido (versiones anteriores)');
    const late = await handle(req('corrections', { method: 'POST', cookie: b, body: { item: ITEM, action: 'none', expectedRev: 0 } }), env);
    assert.equal(late.status, 409);
    const clear = await handle(req('corrections', { method: 'POST', cookie: b, body: { item: ITEM, action: 'clear', expectedRev: 1 } }), env);
    assert.equal(clear.status, 201);
    const pub = await (await handle(req('overrides', { origin: null }), env)).json();
    assert.deepEqual(pub.overrides, []);
    const hist = await (await handle(req(`corrections?item=${ITEM}`, { cookie: a }), env)).json();
    assert.deepEqual(hist.corrections.map((c) => c.action), ['clear', 'confirm'], 'el historial no se borra');
  });

  it('confirmar guarda los lugares que se vieron', async () => {
    const { cookie } = await login();
    const r = await handle(req('corrections', { method: 'POST', cookie, body: { item: ITEM, action: 'confirm', places: ['150101'], expectedRev: 0 } }), env);
    assert.equal(r.status, 201);
    const pub = await (await handle(req('overrides', { origin: null }), env)).json();
    assert.deepEqual(pub.overrides[0].places, ['150101']);
    const bad = await handle(req('corrections', { method: 'POST', cookie, body: { item: ITEM, action: 'confirm', places: ['99'], expectedRev: 1 } }), env);
    assert.equal(bad.status, 400);
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
