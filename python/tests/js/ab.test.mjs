// Pruebas de la analítica de versiones del mapa (functions/_lib/ab.js) con una D1 de mentira.
// Se corren con `node --test` (las lanza tests/test_alert_map.py).
import assert from 'node:assert/strict';
import { beforeEach, describe, it } from 'node:test';

import { DAILY_CAP, handle, parseEvent, resetSchemaCache } from '../../../functions/_lib/ab.js';
import { FakeD1 } from './fake-d1.mjs';

const ORIGIN = 'https://enso-peru.pages.dev';
let env;

function post(body, { origin = ORIGIN, site } = {}) {
  const h = { 'Content-Type': 'text/plain;charset=UTF-8' };
  if (origin) h.Origin = origin;
  if (site) h['Sec-Fetch-Site'] = site;
  return handle(new Request(`${ORIGIN}/api/ab/e`, { method: 'POST', headers: h, body: typeof body === 'string' ? body : JSON.stringify(body) }), env);
}
const stats = async (days = 30) => (await handle(new Request(`${ORIGIN}/api/ab/stats?days=${days}`), env)).json();

describe('analítica de versiones', () => {
  beforeEach(() => { resetSchemaCache(); env = { GEO_DB: new FakeD1() }; });

  it('suma 1 por evento y versión, sin datos personales', async () => {
    assert.equal((await post({ v: 'B', e: ['view', 'hover', 'hover', 'select'] })).status, 202);
    assert.equal((await post({ v: 'B', e: ['view'] })).status, 202);
    const s = await stats();
    assert.equal(s.totals.B.view, 2);
    assert.equal(s.totals.B.hover, 1); // repetido en el mismo envío cuenta una vez
    assert.equal(s.totals.A.view, 0);
    const cols = env.GEO_DB.sqlite.prepare('PRAGMA table_info(ab_daily)').all().map((c) => c.name);
    assert.deepEqual(cols.sort(), ['day', 'event', 'n', 'variant']);
  });

  it('rechaza otro origen, versiones y eventos desconocidos y cuerpos grandes', async () => {
    assert.equal((await post({ v: 'A', e: ['view'] }, { origin: 'https://evil.example' })).status, 403);
    assert.equal((await post({ v: 'A', e: ['view'] }, { origin: null })).status, 403);
    assert.equal((await post({ v: 'A', e: ['view'] }, { origin: null, site: 'same-origin' })).status, 202);
    assert.equal((await post({ v: 'Z', e: ['view'] })).status, 400);
    assert.equal((await post({ v: 'A', e: ['drop table'] })).status, 400);
    assert.equal((await post('x'.repeat(600))).status, 400);
    assert.equal((await post('{no json')).status, 400);
    assert.equal(parseEvent(JSON.stringify({ v: 'C', e: ['view', 'nope'] })).events.length, 1);
  });

  it('respeta el tope diario para no gastar las escrituras de la consola', async () => {
    const day = new Date().toISOString().slice(0, 10);
    env.GEO_DB.sqlite.exec(`CREATE TABLE IF NOT EXISTS ab_daily (day TEXT NOT NULL, variant TEXT NOT NULL, event TEXT NOT NULL, n INTEGER NOT NULL, PRIMARY KEY (day, variant, event))`);
    env.GEO_DB.sqlite.prepare('INSERT INTO ab_daily VALUES (?, ?, ?, ?)').run(day, 'A', 'view', DAILY_CAP);
    const r = await (await post({ v: 'A', e: ['view'] })).json();
    assert.equal(r.stored, false);
    assert.equal((await stats()).totals.A.view, DAILY_CAP);
  });

  it('sin base vinculada no hace nada', async () => {
    env = {};
    assert.equal((await (await post({ v: 'A', e: ['view'] })).json()).stored, false);
    assert.equal((await stats()).available, false);
  });

  it('cada envío es un solo viaje de escritura', async () => {
    await post({ v: 'A', e: ['view'] });
    const before = env.GEO_DB.trips;
    await post({ v: 'A', e: ['view', 'hover', 'select', 'detail'] });
    assert.ok(env.GEO_DB.trips - before <= 2, `viajes: ${env.GEO_DB.trips - before}`);
  });
});
