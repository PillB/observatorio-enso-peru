// Pruebas de la medición anónima del uso por versión del sitio (functions/_lib/uso.js) con una D1 de mentira, y de
// la versión del sitio en el navegador (public/assets/js/ab.js y sitio.js).
// Se corren con `node --test` (las lanza tests/test_uso.py).
import assert from 'node:assert/strict';
import { beforeEach, describe, it } from 'node:test';

import { EXPERIMENTS } from '../../../functions/_lib/ab.js';
import { COOKIE, handle as geo, hashPassword } from '../../../functions/_lib/geo-console.js';
import { MAX_ROWS, MAX_SECS, ROUTES, ROW_CAP, handle, parseUsage, resetSchemaCache, totals } from '../../../functions/_lib/uso.js';
import * as client from '../../../public/assets/js/ab.js';
import { FakeD1 } from './fake-d1.mjs';

const ORIGIN = 'https://enso-peru.pages.dev';
let env;

function post(body, { origin = ORIGIN } = {}) {
  const h = { 'Content-Type': 'text/plain;charset=UTF-8' };
  if (origin) h.Origin = origin;
  return handle(new Request(`${ORIGIN}/api/uso/e`, { method: 'POST', headers: h, body: typeof body === 'string' ? body : JSON.stringify(body) }), env);
}
const rows = () => env.GEO_DB.sqlite.prepare("SELECT site, dim, key, n FROM uso_daily WHERE site != '_' ORDER BY site, dim, key").all().map((r) => ({ ...r }));
const written = () => env.GEO_DB.sqlite.prepare("SELECT n FROM uso_daily WHERE site = '_'").get()?.n || 0;

async function login() {
  env.GEO_USERS = JSON.stringify({ ana: { role: 'reviewer', hash: await hashPassword('una-clave-larga-1') } });
  const r = await geo(new Request(`${ORIGIN}/api/geo/login`, { method: 'POST', headers: { Origin: ORIGIN, 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'ana', password: 'una-clave-larga-1' }) }), env);
  assert.equal(r.status, 200);
  return r.headers.get('Set-Cookie').match(new RegExp(`${COOKIE}=([^;]+)`))[1];
}

describe('medición del uso', () => {
  beforeEach(() => { resetSchemaCache(); env = { GEO_DB: new FakeD1() }; });

  it('suma sesiones, vistas, segundos y cambios por versión, sin nada de la persona', async () => {
    const body = { s: 'B', n: 1, vb: '3-5', rb: '1-7', v: { resumen: 1, noticias: 2 }, t: { resumen: 12, noticias: 95.4 }, u: { noticias: 1 }, c: [['sitio', 'A', 'B'], ['mapa', 'A', 'C']] };
    assert.equal((await post(body)).status, 202);
    assert.equal((await post({ s: 'B', t: { noticias: 30 } })).status, 202);
    assert.equal((await post({ s: 'A', n: 1, vb: '1', v: { resumen: 1 } })).status, 202);
    const t = totals(rows());
    assert.deepEqual(t.B.sesion, { nueva: 1 });
    assert.deepEqual(t.B.visita, { '3-5': 1 });
    assert.deepEqual(t.B.vuelta, { '1-7': 1 });
    assert.deepEqual(t.B.vista, { noticias: 2, resumen: 1 });
    assert.deepEqual(t.B.seg, { noticias: 125, resumen: 12 });
    assert.deepEqual(t.B.abrir, { noticias: 1 });
    assert.deepEqual(t.B.cambio, { 'mapa:A>C': 1, 'sitio:A>B': 1 });
    assert.deepEqual(t.A.sesion, { nueva: 1 });
    // Solo existen las columnas de los contadores: nada donde quepa una IP, un identificador o un texto libre.
    const cols = env.GEO_DB.sqlite.prepare('PRAGMA table_info(uso_daily)').all().map((c) => c.name);
    assert.deepEqual(cols, ['day', 'site', 'dim', 'key', 'n']);
  });

  it('rechaza lo que no entiende y nunca guarda texto que no esté en sus listas', async () => {
    for (const bad of ['', 'no json', '[]', '{}', '{"s":"C","n":1}', '{"s":"A"}', '{"s":"A","v":[1]}', '{"s":"A","c":"x"}', JSON.stringify({ s: 'A', v: { resumen: 1 }, pad: 'x'.repeat(3000) })]) {
      assert.equal((await post(bad)).status, 400, bad.slice(0, 40));
    }
    const junk = { s: 'A', v: { '<script>': 5, "'; DROP TABLE uso_daily;--": 2, __proto__: 1, datos: -3, mapa: 'NaN', zona: 1e9 }, t: { datos: 1e9, zona: null }, c: [['sitio', 'A', 'A'], ['sitio', 'A', 'Z'], ['nada', 'A', 'B'], ['constructor', 'A', 'B'], 'x', ['sitio', 'B', 'A'], ['sitio', 'B', 'A']] };
    assert.equal((await post(junk)).status, 202);
    assert.deepEqual(rows(), [
      { site: 'A', dim: 'cambio', key: 'sitio:B>A', n: 1 },
      { site: 'A', dim: 'seg', key: 'datos', n: MAX_SECS },
      { site: 'A', dim: 'vista', key: 'zona', n: 50 },
    ]);
    // La versión de la sesión solo cuenta con n: 1; un tramo desconocido no se guarda.
    assert.deepEqual(parseUsage(JSON.stringify({ s: 'A', n: 1, vb: '999', rb: 'ayer' })).rows, [['sesion', 'nueva', 1]]);
    assert.equal(parseUsage(JSON.stringify({ s: 'A', n: 2, vb: '1' })), null);
  });

  it('solo acepta envíos del propio sitio', async () => {
    assert.equal((await post({ s: 'A', v: { resumen: 1 } }, { origin: 'https://otro.example' })).status, 403);
    assert.equal((await post({ s: 'A', v: { resumen: 1 } }, { origin: null })).status, 403);
    const r = await handle(new Request(`${ORIGIN}/api/uso/e`, { method: 'POST', headers: { 'Sec-Fetch-Site': 'same-origin' }, body: JSON.stringify({ s: 'A', v: { resumen: 1 } }) }), env);
    assert.equal(r.status, 202);
    assert.equal((await handle(new Request(`${ORIGIN}/api/uso/e`), env)).status, 404);
  });

  it('respeta el tope diario de filas y el de filas por envío', async () => {
    const many = Object.fromEntries(ROUTES.map((r) => [r, 1]));
    const p = parseUsage(JSON.stringify({ s: 'A', n: 1, vb: '1', rb: 'hoy', v: many, t: many, u: many, c: [['sitio', 'A', 'B']] }));
    assert.equal(p.rows.length, MAX_ROWS);
    await post({ s: 'A', v: { resumen: 1 } });
    assert.equal(written(), 2);
    env.GEO_DB.sqlite.prepare("UPDATE uso_daily SET n = ? WHERE site = '_'").run(ROW_CAP);
    const r = await post({ s: 'A', v: { resumen: 1 } });
    assert.equal(r.status, 202);
    assert.equal((await r.json()).stored, false);
    assert.equal(rows()[0].n, 1);
  });

  it('sin base responde sin guardar; la lectura pide una sesión de la consola', async () => {
    assert.deepEqual(await (await handle(new Request(`${ORIGIN}/api/uso/e`, { method: 'POST', headers: { Origin: ORIGIN }, body: '{"s":"A","v":{"resumen":1}}' }), {})).json(), { ok: true, stored: false });
    assert.equal((await (await handle(new Request(`${ORIGIN}/api/uso/stats`), {})).json()).available, false);
    await post({ s: 'B', n: 1, vb: '1', v: { memoria: 3 }, t: { memoria: 40 } });
    assert.equal((await handle(new Request(`${ORIGIN}/api/uso/stats`), env)).status, 401);
    assert.equal((await handle(new Request(`${ORIGIN}/api/uso/stats`, { headers: { Cookie: `${COOKIE}=${'x'.repeat(43)}` } }), env)).status, 401);
    const token = await login();
    const r = await handle(new Request(`${ORIGIN}/api/uso/stats?days=7`, { headers: { Cookie: `${COOKIE}=${token}` } }), env);
    assert.equal(r.status, 200);
    assert.equal(r.headers.get('Cache-Control'), 'no-store');
    const s = await r.json();
    assert.equal(s.days, 7);
    assert.deepEqual(s.totals.B.seg, { memoria: 40 });
    assert.ok(s.rows.every((x) => x.site !== '_'));
  });
});

describe('versión del sitio en el navegador', () => {
  it('el servidor y el navegador conocen las mismas versiones; en local se ve la A', () => {
    assert.deepEqual(client.EXPERIMENTS.sitio.variants.map(([v]) => v), EXPERIMENTS.sitio);
    assert.equal(client.EXPERIMENTS.sitio.local, 'A');
    assert.equal(client.EXPERIMENTS.sitio.param, 'sitio');
  });
});
