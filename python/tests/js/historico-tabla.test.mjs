// La tabla de registros de la Memoria (public/assets/js/historico-tabla.js): las funciones puras. Se corre con
// `node --test` (la lanza tests/test_historico_tabla.py, que además compara el CSV con eventos.csv).
import assert from 'node:assert/strict';
import { it } from 'node:test';

import * as TB from '../../../public/assets/js/historico-tabla.js';

const sum = {
  nombres: { departamento: { 15: 'Lima', 20: 'Piura' }, provincia: { 1501: 'Lima', 2001: 'Piura' }, distrito: { 150110: 'Comas', 200101: 'Piura' } },
  peligros: { 'Huayco/Alud': { grupo: 'hidrometeorologico' } },
};
const rec = (o) => ({ d: '2017-03-15', t: 'Huayco/Alud', u: '150110', e: 'Niño Costero 2017', f: 'El Niño', o: 'sinpad', c: 'alta', muertos: 0, afect: 0, viv: 0, i: 0, ...o });
const col = (vals, k) => vals[TB.COLUMNS.indexOf(k)];

it('pone primero las 13 columnas del equipo, en su orden, y no repite columnas', () => {
  assert.deepEqual(TB.COLUMNS.slice(0, 13), ['Date', 'DangerType', 'Ubicacion', 'Distrito', 'Provincia', 'Departamento', 'Descripción', 'DuraciónEvento', 'Ubigeo', 'TipoEvento', 'Fuente', 'Latitud', 'Longitud']);
  assert.equal(new Set(TB.COLUMNS).size, TB.COLUMNS.length);
});

it('completa la fecha con la regla del catálogo', () => {
  assert.equal(TB.fullDate('1998'), '1998-01-01');
  assert.equal(TB.fullDate('1998-03'), '1998-03-01');
  assert.equal(TB.fullDate('1998-03-12'), '1998-03-12');
});

it('protege las fórmulas pero no los números negativos, y cita lo que hace falta', () => {
  assert.equal(TB.csvCell('=HYPERLINK("x")'), '"\'=HYPERLINK(""x"")"');
  assert.equal(TB.csvCell('+51 999'), "'+51 999");
  assert.equal(TB.csvCell('@SUM(A1)'), "'@SUM(A1)");
  assert.equal(TB.csvCell('- crecida del río'), "'- crecida del río");
  assert.equal(TB.csvCell('-8.1'), '-8.1');
  assert.equal(TB.csvCell('-79.0306'), '-79.0306');
  assert.equal(TB.csvCell('1,5'), '"1,5"');
  assert.equal(TB.csvCell('dos\nlíneas'), '"dos\nlíneas"');
  assert.equal(TB.csvCell(null), '');
  assert.equal(TB.csvCell(undefined), '');
  assert.equal(TB.csvCell(0), '0');
  assert.ok(TB.csvHead().startsWith('﻿Date,DangerType,'));
});

it('arma la fila sin ficha y con ficha, y dice de dónde salen las coordenadas', () => {
  const C = { areas: { 150110: ['-11.9', '-77.05'], 2001: ['-5.19', '-80.63'], 200101: ['-5.2', '-80.6', 1] }, puntos: { 7: ['-11.95123', '-77.06789'] } };
  let v = TB.rowValues(rec({}), undefined, C, sum);
  assert.equal(col(v, 'Date'), '2017-03-15');
  assert.equal(col(v, 'Distrito'), 'Comas');
  assert.equal(col(v, 'Provincia'), 'Lima');
  assert.equal(col(v, 'Latitud'), '-11.9');
  assert.equal(col(v, 'PrecisionGeo'), 'capital-distrito');
  assert.equal(col(v, 'GrupoPeligro'), 'hidrometeorologico');
  assert.equal(col(v, 'Descripción'), undefined);
  assert.equal(col(v, 'Corroboracion'), '');
  // Un registro de provincia no tiene distrito y va en la capital de la provincia.
  v = TB.rowValues(rec({ u: '2001' }), undefined, C, sum);
  assert.equal(col(v, 'Distrito'), '');
  assert.equal(col(v, 'Provincia'), 'Piura');
  assert.equal(col(v, 'PrecisionGeo'), 'capital-provincia');
  assert.equal(TB.rowValues(rec({ u: '200101' }), undefined, C, sum)[TB.COLUMNS.indexOf('PrecisionGeo')], 'interior-distrito');
  // Con punto propio: las coordenadas con todos sus decimales y cómo se ubicó, que dice la ficha.
  const ficha = ['Huayco en la quebrada', 'Av. Túpac Amaru', 'INDECI', 'https://x.pe/1', 3, 'dia', 'sinpad-1', 'fuente', 'fecha', { Fallecidos: 2, Damnificados: 40 }, 1, ['https://a.pe', 'https://b.pe'], 'evento', [-11.9512, -77.0679, 1, 'Collique', 0.5, '', 'quebrada Collique', '']];
  v = TB.rowValues(rec({ i: 7 }), ficha, C, sum);
  assert.equal(col(v, 'Latitud'), '-11.95123');
  assert.equal(col(v, 'PrecisionGeo'), 'centro-poblado');
  assert.equal(col(v, 'Lugar'), 'Collique');
  assert.equal(col(v, 'CuerpoAgua'), 'quebrada Collique');
  assert.equal(col(v, 'Fallecidos'), 2);
  assert.equal(col(v, 'Heridos'), undefined);
  assert.equal(col(v, 'FuentesAdicionales'), 'https://a.pe | https://b.pe');
  assert.equal(col(v, 'DuraciónEvento'), 3);
  // Sin coordenadas (el archivo no llegó), Latitud y Longitud van vacías.
  assert.equal(col(TB.rowValues(rec({}), undefined, null, sum), 'Latitud'), '');
});

it('ordena de forma estable y por el nombre que se ve', () => {
  const rows = [rec({ i: 1, d: '2017', muertos: 3 }), rec({ i: 2, d: '2017-03-01', muertos: 0 }), rec({ i: 3, d: '1998-02-10', muertos: 3, u: '200101' })];
  assert.deepEqual(TB.sortRows(rows, 'd', -1).map((r) => r.i), [2, 1, 3]);
  assert.deepEqual(TB.sortRows(rows, 'd', 1).map((r) => r.i), [3, 1, 2]);
  // Empate en fallecidos: el más reciente primero.
  assert.deepEqual(TB.sortRows(rows, 'muertos', -1).map((r) => r.i), [1, 3, 2]);
  const names = { 150110: 'Comas', 200101: 'Ápice' };
  assert.deepEqual(TB.sortRows(rows, 'u', 1, (u) => names[u]).map((r) => r.i), [3, 2, 1]);
  assert.deepEqual(rows.map((r) => r.i), [1, 2, 3], 'no toca el arreglo original');
});

it('filtra por área y lista sus departamentos', () => {
  const rows = [rec({ u: '150110' }), rec({ u: '2001' }), rec({ u: '20' })];
  assert.equal(TB.inArea(rows, '20').length, 2);
  assert.equal(TB.inArea(rows, '').length, 3);
  assert.deepEqual(TB.depsOf(rows), ['15', '20']);
});

it('nombra el archivo con el filtro', () => {
  const s = { area: '150110', peligro: 'Huayco/Alud', evento: 'FEN 1997-98', desde: '1990', hasta: '' };
  assert.equal(TB.fileName(s, () => 'Comas (Lima, Lima)', '2026-10-28T15:00:00Z'), 'memoria-desastres_comas-lima-lima_huayco-alud_fen-1997-98_1990-fin_2026-10-28.csv');
  assert.equal(TB.fileName({}, () => '', ''), 'memoria-desastres.csv');
});

it('arma el CSV por departamentos y avisa los que no llegaron', async () => {
  const rows = [rec({ i: 1, u: '150110' }), rec({ i: 2, u: '200101' })];
  const fichas = { 15: { 1: ['Lluvia, granizo y "huaycos"', 'Comas'] }, 20: null };
  const seen = [];
  const out = await TB.buildCsv(rows, { C: null, sum, load: async (d) => fichas[d], progress: (a, b) => seen.push(`${a}/${b}`) });
  assert.deepEqual(out.missing, ['20']);
  assert.deepEqual(seen, ['1/2', '2/2']);
  const text = out.parts.join('');
  const lines = text.trim().split('\n');
  assert.equal(lines.length, 3);
  assert.ok(lines[1].includes('"Lluvia, granizo y ""huaycos"""'));
  assert.equal(lines[1].split(',')[0], '2017-03-15');
  // Si la página se cerró a medio camino, no entrega nada.
  assert.equal(await TB.buildCsv(rows, { C: null, sum, load: async () => ({}), alive: () => false }), null);
});

it('muestra solo las filas pedidas y los botones para ver más', () => {
  const rows = Array.from({ length: 60 }, (_, i) => rec({ i }));
  const ctx = { caption: 'x', placeName: (u) => u, label: (t) => t, sourceName: (o) => o, fichas: new Map(), C: null, wantDetail: false };
  const out = String(TB.tableHtml(rows, { key: 'd', dir: -1, shown: 25 }, ctx));
  assert.equal((out.match(/<tr>/g) || []).length, 26);
  assert.match(out, /Mostrando 25 de 60 registros/);
  assert.match(out, /data-tbl-more="25">Mostrar 25 más/);
  assert.match(out, /data-tbl-more="35">Mostrar 35 más/);
  assert.match(out, /aria-sort="descending"/);
  assert.equal((out.match(/aria-sort=/g) || []).length, 1);
  assert.match(out, /sin cargar/);
  const all = String(TB.tableHtml(rows, { key: 'd', dir: -1, shown: 100 }, ctx));
  assert.doesNotMatch(all, /data-tbl-more/);
  // Un texto con marcado de la fuente se muestra como texto.
  const x = String(TB.tableHtml([rec({})], { key: 'd', dir: -1, shown: 25 }, { ...ctx, fichas: new Map([['15', { 0: ['<img src=x onerror=alert(1)>'] }]]) }));
  assert.ok(!x.includes('<img'));
});
