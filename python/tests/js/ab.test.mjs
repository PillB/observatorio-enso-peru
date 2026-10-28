// Pruebas de la analítica de versiones de los mapas (functions/_lib/ab.js) con una D1 de mentira, y de la asignación
// de versiones en el navegador (public/assets/js/ab.js).
// Se corren con `node --test` (las lanza tests/test_alert_map.py).
import assert from 'node:assert/strict';
import { beforeEach, describe, it } from 'node:test';

import { DAILY_CAP, EXPERIMENTS, MIN_VIEWS, decide, handle, parseEvent, resetSchemaCache, wilson } from '../../../functions/_lib/ab.js';
import * as client from '../../../public/assets/js/ab.js';
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
const defaults = () => handle(new Request(`${ORIGIN}/api/ab/defaults`), env);
const today = () => new Date().toISOString().slice(0, 10);
/** Contadores ya sumados: {variante: {evento: n}} de un experimento, hoy. */
function seed(exp, counts, table = 'ab_exp') {
  const db = env.GEO_DB.sqlite;
  db.exec(`CREATE TABLE IF NOT EXISTS ab_exp (day TEXT NOT NULL, exp TEXT NOT NULL, variant TEXT NOT NULL, event TEXT NOT NULL, n INTEGER NOT NULL, PRIMARY KEY (day, exp, variant, event))`);
  db.exec(`CREATE TABLE IF NOT EXISTS ab_daily (day TEXT NOT NULL, variant TEXT NOT NULL, event TEXT NOT NULL, n INTEGER NOT NULL, PRIMARY KEY (day, variant, event))`);
  for (const [v, evs] of Object.entries(counts)) {
    for (const [e, n] of Object.entries(evs)) {
      if (table === 'ab_exp') db.prepare('INSERT INTO ab_exp VALUES (?, ?, ?, ?, ?)').run(today(), exp, v, e, n);
      else db.prepare('INSERT INTO ab_daily VALUES (?, ?, ?, ?)').run(today(), v, e, n);
    }
  }
}

describe('analítica de versiones', () => {
  beforeEach(() => { resetSchemaCache(); env = { GEO_DB: new FakeD1() }; });

  it('suma 1 por evento y versión, sin datos personales', async () => {
    assert.equal((await post({ v: 'B', e: ['view', 'hover', 'hover', 'select'] })).status, 202);
    assert.equal((await post({ v: 'B', e: ['view'] })).status, 202);
    const s = await stats();
    assert.equal(s.totals.B.view, 2);
    assert.equal(s.totals.B.hover, 1); // repetido en el mismo envío cuenta una vez
    assert.equal(s.totals.A.view, 0);
    const cols = env.GEO_DB.sqlite.prepare('PRAGMA table_info(ab_exp)').all().map((c) => c.name);
    assert.deepEqual(cols.sort(), ['day', 'event', 'exp', 'n', 'variant']);
    // Lo que mandaban las páginas anteriores (sin «x») es el mapa de alertas; ab_daily ya no se escribe.
    assert.equal(env.GEO_DB.sqlite.prepare('SELECT COUNT(*) AS n FROM ab_daily').get().n, 0);
  });

  it('cada experimento cuenta aparte y solo acepta sus versiones', async () => {
    assert.equal((await post({ x: 'memoria', v: 'cuencas', e: ['view', 'select', 'use'] })).status, 202);
    assert.equal((await post({ x: 'noticias', v: 'distritos', e: ['view'] })).status, 202);
    assert.equal((await post({ x: 'memoria', v: 'B', e: ['view'] })).status, 400);
    assert.equal((await post({ x: 'noticias', v: 'puntos', e: ['view'] })).status, 400);
    assert.equal((await post({ x: 'otro', v: 'A', e: ['view'] })).status, 400);
    assert.equal((await post({ x: '__proto__', v: 'A', e: ['view'] })).status, 400);
    const s = await stats();
    assert.equal(s.experiments.memoria.totals.cuencas.view, 1);
    assert.equal(s.experiments.memoria.totals.cuencas.use, 1);
    assert.equal(s.experiments.noticias.totals.distritos.view, 1);
    assert.equal(s.experiments.mapa.totals.A.view, 0);
    assert.deepEqual(Object.keys(s.experiments), Object.keys(EXPERIMENTS));
    assert.equal(s.decideDays, 60);
  });

  it('las versiones del navegador son las del servidor', () => {
    for (const [x, vs] of Object.entries(EXPERIMENTS)) assert.deepEqual(client.EXPERIMENTS[x].variants.map(([v]) => v), vs, x);
    assert.equal(new Set(Object.values(client.EXPERIMENTS).map((e) => e.key)).size, Object.keys(EXPERIMENTS).length);
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

describe('decisión: la versión que más se usa', () => {
  beforeEach(() => { resetSchemaCache(); env = { GEO_DB: new FakeD1() }; });

  it('intervalo de Wilson al 95 %', () => {
    const [lo, hi] = wilson(50, 100);
    assert.ok(Math.abs(lo - 0.4038) < 1e-3 && Math.abs(hi - 0.5962) < 1e-3, `${lo} ${hi}`);
    assert.deepEqual(wilson(0, 0), [0, 1]);
    const [lo0, hi0] = wilson(0, 20);
    assert.equal(lo0, 0);
    assert.ok(hi0 > 0.15 && hi0 < 0.17);
  });

  it('gana solo con visitas suficientes y un intervalo que no se cruza con ningún otro', () => {
    const vs = ['a', 'b', 'c'];
    const clear = { a: { view: 400, use: 200 }, b: { view: 400, use: 100 }, c: { view: 400, use: 90 } };
    assert.equal(decide(vs, clear).winner, 'a');
    // Una versión con pocas visitas impide decidir, aunque la diferencia sea grande.
    assert.equal(decide(vs, { ...clear, c: { view: MIN_VIEWS - 1, use: 0 } }).winner, null);
    assert.equal(decide(vs, { ...clear, c: { view: MIN_VIEWS - 1, use: 0 } }).ready, false);
    // Dos versiones con intervalos que se cruzan: ninguna gana.
    const close = { a: { view: 400, use: 200 }, b: { view: 400, use: 185 }, c: { view: 400, use: 90 } };
    const d = decide(vs, close);
    assert.equal(d.ready, true);
    assert.equal(d.winner, null);
    // «use» nunca pasa de las visitas (un envío repetido no infla la tasa).
    assert.equal(decide(['a'], { a: { view: 10, use: 50 } }, 1).rows[0].rate, 1);
  });

  it('defaults devuelve la ganadora de cada experimento y se cachea en el borde', async () => {
    seed('memoria', { resumen: { view: 300, use: 60 }, cuencas: { view: 300, use: 180 }, puntos: { view: 300, use: 70 }, riesgo: { view: 300, use: 65 } });
    seed('noticias', { resumen: { view: 50, use: 40 }, cuencas: { view: 50, use: 2 }, distritos: { view: 50, use: 2 } });
    const r = await defaults();
    assert.equal(r.status, 200);
    assert.match(r.headers.get('Cache-Control'), /public, max-age=3600/);
    assert.deepEqual(await r.json(), { mapa: null, memoria: 'cuencas', noticias: null });
    const s = await stats(7);
    assert.equal(s.experiments.memoria.decision.winner, 'cuencas');
    assert.equal(s.experiments.noticias.decision.ready, false);
  });

  it('los contadores del mapa de antes (ab_daily, sin «use») suman visitas pero no deciden', async () => {
    seed('mapa', { A: { view: 5000 }, B: { view: 5000 }, C: { view: 5000 }, D: { view: 5000 } }, 'ab_daily');
    const s = await stats();
    assert.equal(s.experiments.mapa.totals.A.view, 5000);
    assert.equal(s.experiments.mapa.decision.rows[0].view, 0);
    assert.equal((await (await defaults()).json()).mapa, null);
  });

  it('sin base vinculada no hay ganadoras', async () => {
    env = {};
    assert.deepEqual(await (await defaults()).json(), { mapa: null, memoria: null, noticias: null });
  });
});

describe('asignación en la primera visita', () => {
  const seq = (...xs) => { let i = 0; return () => xs[i++ % xs.length]; };

  it('sin ganadora, al azar entre todas', () => {
    const all = EXPERIMENTS.memoria;
    const got = all.map((_, i) => client.assign('memoria', null, seq((i + 0.5) / all.length)));
    assert.deepEqual(got, all);
    // Una «ganadora» que no es del experimento se ignora.
    assert.ok(all.includes(client.assign('memoria', 'B', seq(0.1))));
  });

  it(`con ganadora, ella con probabilidad ${client.EXPLOIT} y otra al azar el resto`, () => {
    assert.equal(client.assign('noticias', 'distritos', seq(client.EXPLOIT - 0.01)), 'distritos');
    const rest = new Set([0.0, 0.5, 0.99].map((r) => client.assign('noticias', 'distritos', seq(0.95, r))));
    assert.deepEqual([...rest].sort(), ['cuencas', 'resumen']);
    // La proporción con un azar de verdad.
    let n = 0;
    for (let i = 0; i < 20000; i++) if (client.assign('mapa', 'C') === 'C') n++;
    assert.ok(Math.abs(n / 20000 - client.EXPLOIT) < 0.02, `${n}`);
  });
});
