// Pruebas de la analítica de versiones de los mapas (functions/_lib/ab.js) con una D1 de mentira, y de la asignación
// de versiones en el navegador (public/assets/js/ab.js).
// Se corren con `node --test` (las lanza tests/test_alert_map.py).
import assert from 'node:assert/strict';
import { beforeEach, describe, it } from 'node:test';

import { DAILY_CAP, EXPERIMENTS, MIN_VIEWS, SRM_ALPHA, chi2Sf, decide, handle, parseEvent, resetSchemaCache, srm, wilson } from '../../../functions/_lib/ab.js';
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
    const clear = { a: { rview: 400, ruse: 200 }, b: { rview: 400, ruse: 100 }, c: { rview: 400, ruse: 90 } };
    assert.equal(decide(vs, clear).winner, 'a');
    // Una versión con pocas visitas impide decidir, aunque la diferencia sea grande.
    assert.equal(decide(vs, { ...clear, c: { rview: MIN_VIEWS - 1, ruse: 0 } }).winner, null);
    assert.equal(decide(vs, { ...clear, c: { rview: MIN_VIEWS - 1, ruse: 0 } }).ready, false);
    // Dos versiones con intervalos que se cruzan: ninguna gana.
    const close = { a: { rview: 400, ruse: 200 }, b: { rview: 400, ruse: 185 }, c: { rview: 400, ruse: 90 } };
    const d = decide(vs, close);
    assert.equal(d.ready, true);
    assert.equal(d.winner, null);
    // «use» nunca pasa de las visitas (un envío repetido no infla la tasa).
    assert.equal(decide(['a'], { a: { rview: 10, ruse: 50 } }, 1).rows[0].rate, 1);
  });

  it('defaults devuelve la ganadora de cada experimento y se cachea en el borde', async () => {
    seed('memoria', { resumen: { rview: 300, ruse: 60 }, cuencas: { rview: 300, ruse: 180 }, puntos: { rview: 300, ruse: 70 }, riesgo: { rview: 300, ruse: 65 } });
    seed('noticias', { resumen: { rview: 50, ruse: 40 }, cuencas: { rview: 50, ruse: 2 }, distritos: { rview: 50, ruse: 2 } });
    // Muchas visitas de quienes ya eligieron (view / use) no deciden: no son una muestra sorteada.
    seed('boletin', { mapa: { view: 5000, use: 4000, chosen: 5000 }, mosaico: { view: 5000, use: 10 }, ficha: { view: 5000, use: 10 } });
    const r = await defaults();
    assert.equal(r.status, 200);
    assert.match(r.headers.get('Cache-Control'), /public, max-age=3600/);
    assert.deepEqual(await r.json(), { boletin: null, mapa: null, memoria: 'cuencas', noticias: null, sitio: null });
    assert.equal((await stats()).experiments.boletin.decision.rows[0].view, 0);
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

  it('χ² de cola superior: cuantiles publicados de la tabla de la χ²', () => {
    // Valores críticos de cualquier tabla de la χ² (p. ej. NIST/SEMATECH e-Handbook, 1.3.6.7.4).
    for (const [x, df, p] of [[3.841459, 1, 0.05], [10.827566, 1, 0.001], [5.991465, 2, 0.05], [13.815511, 2, 0.001],
      [7.814728, 3, 0.05], [16.266236, 3, 0.001], [9.487729, 4, 0.05]]) {
      assert.ok(Math.abs(chi2Sf(x, df) - p) < 1e-6 * Math.max(1, p * 1e3), `${x} ${df}: ${chi2Sf(x, df)}`);
    }
    // df = 2 es exacto: e^(−x/2). df = 4: e^(−x/2)(1 + x/2).
    assert.ok(Math.abs(chi2Sf(20, 4) - Math.exp(-10) * 11) < 1e-12);
    assert.equal(chi2Sf(0, 3), 1);
  });

  it('control de proporciones (SRM): un reparto que el sorteo parejo no explica impide decidir', () => {
    // 1000 frente a 870: χ² = (65² + 65²) / 935 = 9,037; p = 0,00265 > 0,0005: pasa.
    const ok = srm([1000, 870]);
    assert.ok(Math.abs(ok.chi2 - 8450 / 935) < 1e-9);
    assert.equal(ok.mismatch, false);
    // 1000 frente a 840: χ² = 2·80² / 920 = 13,913; p = 0,00019 < 0,0005: desajuste.
    assert.equal(srm([1000, 840]).mismatch, true);
    // Justo a cada lado del umbral: 1000 frente a 850 (χ² = 12,16, p = 0,00049) es desajuste; 1000 frente a 852
    // (χ² = 11,83, p = 0,00058) no. Fija que el umbral es SRM_ALPHA y no la mitad ni el doble.
    assert.equal(srm([1000, 850]).mismatch, true);
    assert.equal(srm([1000, 852]).mismatch, false);
    // El umbral en su borde: χ²(1) = 12,1157 deja p = 0,0005.
    const x = 12.115665;
    assert.ok(Math.abs(chi2Sf(x, 1) - SRM_ALPHA) < 1e-7);
    // Pocas visitas: el χ² no vale y no se prueba.
    assert.equal(srm([4, 0]).tested, false);
    // Borde: 5 esperadas por versión sí se prueba; 4,5 no.
    assert.equal(srm([5, 5]).tested, true);
    assert.equal(srm([5, 4]).tested, false);
    // Con desajuste, una diferencia que de otro modo ganaría no gana.
    const vs = ['a', 'b'];
    const fine = { a: { rview: 1000, ruse: 500 }, b: { rview: 870, ruse: 200 } };
    assert.equal(decide(vs, fine).winner, 'a');
    const bad = { a: { rview: 1000, ruse: 500 }, b: { rview: 840, ruse: 200 } };
    assert.equal(decide(vs, bad).winner, null);
    assert.equal(decide(vs, bad).srm.mismatch, true);
  });

  it('solo deciden las primeras visitas sorteadas (rview / ruse), no las de quien ya eligió (view / use)', () => {
    const vs = ['a', 'b'];
    // Quien elige «a» y vuelve a diario la usa mucho: con view / use, «a» ganaba sin haber sorteo de por medio.
    const chosen = { a: { view: 900, use: 700, chosen: 880, rview: 210, ruse: 60 }, b: { view: 300, use: 60, rview: 205, ruse: 58 } };
    const d = decide(vs, chosen);
    assert.equal(d.winner, null);
    assert.deepEqual(d.rows.map((r) => [r.view, r.use]), [[210, 60], [205, 58]]);
  });

  it('A/A: dos versiones iguales casi nunca «ganan» con una sola mirada (semilla fija, el decide real)', () => {
    // Generador mulberry32 con semilla: reproducible. 2000 experimentos de 300 primeras visitas por versión, uso 20 %.
    let st = 12345;
    const rnd = () => { st = (st + 0x6D2B79F5) >>> 0; let t = st; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
    const draw = (n) => { let k = 0; for (let i = 0; i < n; i++) if (rnd() < 0.2) k++; return k; };
    let wins = 0;
    for (let i = 0; i < 2000; i++) if (decide(['a', 'b'], { a: { rview: 300, ruse: draw(300) }, b: { rview: 300, ruse: draw(300) } }).winner) wins++;
    // Que dos intervalos al 95 % no se crucen equivale a |z| > 2,77 para la diferencia: p ≈ 0,0056 por mirada.
    assert.ok(wins / 2000 < 0.015, `${wins}`);
    // Y con una diferencia real de 10 puntos (0,30 frente a 0,20) con 300 por versión, casi siempre gana la buena.
    let good = 0;
    for (let i = 0; i < 500; i++) {
      const a = { rview: 300, ruse: [...Array(300)].filter(() => rnd() < 0.3).length };
      if (decide(['a', 'b'], { a, b: { rview: 300, ruse: draw(300) } }).winner === 'a') good++;
    }
    assert.ok(good / 500 > 0.5, `${good}`);
  });

  it('sin base vinculada no hay ganadoras', async () => {
    env = {};
    assert.deepEqual(await (await defaults()).json(), { boletin: null, mapa: null, memoria: null, noticias: null, sitio: null });
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

  it(`con ganadora, ella con probabilidad ${client.EXPLOIT}; el resto, al azar entre todas y marcado para la decisión`, () => {
    assert.deepEqual(client.assignment('noticias', 'distritos', seq(client.EXPLOIT - 0.01)), { v: 'distritos', r: false });
    // El resto sale del sorteo parejo entre las tres (la ganadora incluida): antes era entre las otras dos, y la
    // muestra que sigue midiendo no tenía ganadora con quien comparar.
    const rest = [0.0, 0.5, 0.99].map((r) => client.assignment('noticias', 'distritos', seq(0.95, r)));
    assert.deepEqual(rest.map((a) => a.v), ['resumen', 'cuencas', 'distritos']);
    assert.ok(rest.every((a) => a.r));
    assert.ok(client.assignment('memoria', null, seq(0.3)).r, 'sin ganadora, todo es sorteo parejo');
    // La proporción con un azar de verdad: EXPLOIT + (1 − EXPLOIT) / 4 = 0,85 para la ganadora de cuatro.
    let n = 0;
    for (let i = 0; i < 20000; i++) if (client.assign('mapa', 'C') === 'C') n++;
    assert.ok(Math.abs(n / 20000 - (client.EXPLOIT + (1 - client.EXPLOIT) / 4)) < 0.01, `${n}`);
  });
});
