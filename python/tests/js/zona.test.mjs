// Mi zona (public/assets/js/zona.js): las funciones puras de la página. Se corre con `node --test`
// (la lanza tests/test_zona.py).
import assert from 'node:assert/strict';
import { it } from 'node:test';

import { currentAlerts, heat, placeLabels, placeName, seasonality, touches } from '../../../public/assets/js/zona.js';

const names = {
  departamento: { 15: 'Lima', 20: 'Piura' },
  provincia: { 1501: 'Lima', 2001: 'Piura' },
  distrito: { 150110: 'Comas', 200101: 'Piura' },
};

it('da una etiqueta única a cada lugar, aunque dos se llamen igual', () => {
  const labels = placeLabels(names);
  assert.equal(labels.get('Comas · Lima, Lima'), '150110');
  assert.equal(labels.get('Lima · departamento'), '15');
  assert.equal(labels.size, 6);
  assert.equal(new Set(labels.values()).size, 6);
});

it('nombra un código con sus niveles', () => {
  assert.equal(placeName(names, '150110'), 'Comas, Lima, Lima');
  assert.equal(placeName(names, '1501'), 'Lima, Lima');
  assert.equal(placeName(names, '20'), 'Piura');
});

it('un aviso toca el lugar si lo contiene o está dentro de él', () => {
  const a = (code) => ({ geo: { places: [{ code }] } });
  assert.ok(touches(a('15'), '150110'));
  assert.ok(touches(a('1501'), '150110'));
  assert.ok(touches(a('150110'), '15'));
  assert.ok(!touches(a('20'), '150110'));
  assert.ok(!touches({}, '15'));
});

it('cuenta peligros por mes e ignora los registros sin mes', () => {
  const rows = seasonality([{ t: 'Huayco/Alud', m: 2 }, { t: 'Huayco/Alud', m: 2 }, { t: 'Sequias', m: 7 }, { t: 'Sequias', m: 0 }]);
  assert.deepEqual(rows.map((r) => [r.t, r.n]), [['Huayco/Alud', 2], ['Sequias', 1]]);
  assert.equal(rows[0].m[1], 2);
});

it('colorea de 0 a 4 respecto del máximo de la fila', () => {
  assert.equal(heat(0, 5), 0);
  assert.equal(heat(1, 5), 1);
  assert.equal(heat(5, 5), 4);
  assert.equal(heat(3, 0), 0);
});

it('separa los avisos vigentes y los próximos con las reglas del mapa y deja fuera los vencidos y cancelados', () => {
  const now = Date.parse('2026-11-02T12:00:00Z');
  const fc = (from, until, extra = {}) => ({ kind: 'pronostico', date: from, valid: { from, until }, ...extra });
  const items = [
    fc('2026-11-02T00:00:00Z', '2026-11-03T00:00:00Z'), // vigente
    fc('2026-11-04T00:00:00Z', '2026-11-05T00:00:00Z'), // próximo
    fc('2026-10-30T00:00:00Z', '2026-11-01T11:00:00Z'), // vencido
    fc('2026-11-02T00:00:00Z', '2026-11-03T00:00:00Z', { aviso: { cancelled: true } }), // cancelado
    { kind: 'deteccion', date: '2026-10-30T00:00:00Z', currentHours: 24 }, // detección vieja
    { kind: 'deteccion', date: '2026-11-02T06:00:00Z', currentHours: 24 }, // detección de hoy
  ];
  const r = currentAlerts(items, now);
  assert.equal(r.now.length, 2);
  assert.equal(r.soon.length, 1);
});

// --- Elegir por pasos, ubicación y riesgo esperado ---
import { NEAR_MAX_KM, childrenOf, expectedRisk, joinEs, nearestDistricts, riskCoverage } from '../../../public/assets/js/zona.js';

it('lista los lugares del nivel siguiente, por nombre', () => {
  const n = { departamento: { 15: 'Lima', '02': 'Áncash', 20: 'Piura' }, provincia: { 1501: 'Lima', 1502: 'Barranca', 2001: 'Piura' }, distrito: { 150110: 'Comas', 150101: 'Lima', 200101: 'Piura' } };
  assert.deepEqual(childrenOf(n).map((x) => x[1]), ['Áncash', 'Lima', 'Piura']);
  assert.deepEqual(childrenOf(n, '15'), [['1502', 'Barranca'], ['1501', 'Lima']]);
  assert.deepEqual(childrenOf(n, '1501').map((x) => x[0]), ['150110', '150101']);
  assert.deepEqual(childrenOf(n, '150110'), []);
});

const peru = { lonLat: { lon0: -81.45, lat1: 0.05, k: 40, cos: 0.986286 }, points: {} };
const put = (code, lat, lon) => { peru.points[code] = [(lon - peru.lonLat.lon0) * peru.lonLat.cos * 40, (peru.lonLat.lat1 - lat) * 40]; };
put('150110', -11.93, -77.05); put('200101', -5.19, -80.63); put('1501', -12.0, -77.0); put('999999', -5.2, -80.6);

it('ofrece los distritos más cercanos a una posición, en orden, y solo distritos del catálogo', () => {
  const r = nearestDistricts(peru, names, -5.2, -80.6);
  assert.deepEqual(r.map((x) => x.code), ['200101', '150110']);
  assert.ok(r[0].km < 5 && r[1].km > 700);
  assert.equal(nearestDistricts(peru, names, -5.2, -80.6, 1).length, 1);
});

it('no ofrece nada si la posición está fuera del Perú o no es válida', () => {
  assert.deepEqual(nearestDistricts(peru, names, 40.4, -3.7), []); // Madrid
  assert.deepEqual(nearestDistricts(peru, names, 0, 0), []);
  assert.deepEqual(nearestDistricts(peru, names, NaN, -77), []);
  assert.deepEqual(nearestDistricts(peru, names, undefined, undefined), []);
  assert.deepEqual(nearestDistricts(peru, names, -200, -77), []);
  assert.deepEqual(nearestDistricts({}, names, -12, -77), []);
  assert.deepEqual(nearestDistricts({ ...peru, points: {} }, names, -12, -77), []);
  assert.ok(NEAR_MAX_KM >= 100);
});

const K = {
  levels: ['Muy Alto', 'Alto', 'Medio', 'Bajo'],
  blocks: [
    [-5.19, -80.63, '200101', 'Piura', 0, 100, 30], [-5.19, -80.63, '200101', 'Piura', 1, 50, 10], [-5.19, -80.63, '200101', 'La Legua', 1, 70, 20],
    [-5.19, -80.63, '200101', 'Piura', 3, 10, 2], [-5.2, -80.6, '200104', 'Castilla', 3, 5, 1], [-5.2, -80.6, '200104', 'Castilla', 9, 999, 999],
  ],
};

it('cuenta las manzanas del CENEPRED del lugar por nivel, sin inventar un nivel propio', () => {
  const r = expectedRisk(K, '200101');
  assert.equal(r.n, 4);
  assert.deepEqual(r.by.map((x) => [x.n, x.pob, x.viv]), [[1, 100, 30], [2, 120, 30], [0, 0, 0], [1, 10, 2]]);
  assert.equal(r.worst, 0);
  assert.deepEqual(r.high, { n: 3, pob: 220, viv: 60 });
  assert.deepEqual(r.places, [['Piura', 150], ['La Legua', 70]]);
  const dep = expectedRisk(K, '20');
  assert.equal(dep.n, 5); // la manzana con un nivel desconocido no cuenta
  assert.equal(dep.distritos, 2);
});

it('el nivel más alto es el peor que aparece, y un lugar sin manzanas no tiene riesgo esperado', () => {
  const r = expectedRisk(K, '200104');
  assert.equal(r.worst, 3);
  assert.equal(r.high.n, 0);
  assert.deepEqual(r.places, []);
  assert.equal(expectedRisk(K, '150110'), null);
  assert.equal(expectedRisk(K, ''), null);
  assert.equal(expectedRisk(null, '20'), null);
  assert.equal(expectedRisk({ levels: [], blocks: [] }, '20'), null);
});

it('dice qué departamentos cubre la capa', () => {
  assert.deepEqual(riskCoverage(K, names), ['Piura']);
  assert.deepEqual(riskCoverage(null, names), []);
  assert.equal(joinEs(['Lambayeque', 'Piura', 'Tumbes']), 'Lambayeque, Piura y Tumbes');
  assert.equal(joinEs(['Piura']), 'Piura');
  assert.equal(joinEs([]), '');
});

it('con la capa publicada: cada manzana cae en un distrito del catálogo de tres departamentos', async () => {
  const { readFile } = await import('node:fs/promises');
  const real = JSON.parse(await readFile(new URL('../../../public/assets/capas/manzanas-riesgo.json', import.meta.url), 'utf8'));
  const all = ['14', '20', '24'].map((d) => expectedRisk(real, d));
  assert.equal(all.reduce((a, r) => a + r.n, 0), real.blocks.length);
  assert.deepEqual(real.levels, ['Muy Alto', 'Alto', 'Medio', 'Bajo']);
  assert.equal(expectedRisk(real, '15'), null);
});

it('las preguntas frecuentes dicen que no es una alerta, de cuándo son los datos y qué pasa con la ubicación', async () => {
  const { FAQ } = await import('../../../public/assets/js/zona.js');
  assert.ok(FAQ.length >= 6);
  const text = FAQ.map(([q, a]) => `${q} ${a}`).join(' ');
  for (const must of ['no emite alertas', 'censo 2017', '2026-2027', 'no quiere decir que no tenga riesgo', 'No se envía a ningún servidor', 'INDECI']) assert.ok(text.includes(must), must);
  for (const [q, a] of FAQ) { assert.ok(q.startsWith('¿') && q.endsWith('?'), q); assert.ok(a.length > 40); }
});
