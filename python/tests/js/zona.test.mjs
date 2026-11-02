// Mi zona (public/assets/js/zona.js): las funciones puras de la página. Se corre con `node --test`
// (la lanza tests/test_zona.py).
import assert from 'node:assert/strict';
import { it } from 'node:test';

import { currentAlerts, heat, placeLabels, placeName, seasonality, toCsv, touches } from '../../../public/assets/js/zona.js';

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

it('el CSV lleva los códigos como texto y protege las celdas contra fórmulas', () => {
  const out = toCsv([{ d: '2020-02-01', t: 'Huayco/Alud', u: '150110', e: '=SUMA(1)', f: 'Neutro', o: 'sinpad', c: 'alta', muertos: 0, afect: 12, viv: 0 }], names);
  const [head, row] = out.replace(/^﻿/, '').trim().split('\n');
  assert.ok(head.startsWith('Date,DangerType,Departamento'));
  // las cifras agregadas no se hacen pasar por las columnas originales del equipo
  assert.ok(head.endsWith('FallecidosYDesaparecidos,AfectadosYDamnificados,ViviendasDestruidas'));
  assert.ok(!head.split(',').some((c) => ['Fallecidos', 'Afectados', 'ViviendasAfectadas'].includes(c)));
  assert.ok(row.includes(",150110,'=SUMA(1),"));
  assert.ok(row.includes('Comas'));
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
