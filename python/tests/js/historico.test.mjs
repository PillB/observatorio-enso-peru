// Memoria de desastres: el modelo del navegador (public/assets/js/historico-model.js) calcula lo mismo que
// python/enso/historico/indicadores.py sobre el catálogo publicado. Se corre con `node --test`
// (la lanza tests/test_historico.py).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { it } from 'node:test';

import * as M from '../../../public/assets/js/historico-model.js';

const ROOT = new URL('../../../', import.meta.url);
const ev = JSON.parse(readFileSync(new URL('public/assets/historico/eventos.json', ROOT)));
const sum = JSON.parse(readFileSync(new URL('public/assets/historico/resumen.json', ROOT)));
const recs = M.decode(ev);
const nino = new Set(sum.aniosNino);
const years = M.coverageYears(sum.cobertura.homogenea, 0, 0);
const hom = new Set(sum.cobertura.origenes);

function csv(name) {
  const [head, ...lines] = readFileSync(new URL(`data/historico/${name}`, ROOT), 'utf8').replace(/^﻿/, '').trim().split('\n');
  const cols = head.split(',');
  return new Map(lines.map((l) => { const v = l.split(','); return [v[1], Object.fromEntries(cols.map((c, i) => [c, v[i]]))]; }));
}

it('decodifica todos los registros con su año hidrológico', () => {
  assert.equal(recs.length, sum.registros);
  const r = recs.find((x) => x.d.slice(5, 7) === '02');
  assert.equal(r.hy, r.y - 1); // febrero pertenece a la temporada que empezó en julio del año anterior
  assert.ok(recs.every((x) => /^\d{2}(\d{2}){0,2}$/.test(x.u)));
});

it('la sobredispersión ensancha el intervalo de El Niño igual que en Python', () => {
  const years = [...Array(10).keys()], nino = new Set([2, 7]);
  const flat = new Map(years.map((y) => [y, 4]));
  assert.equal(M.dispersion(flat, years, nino), 1);
  const clustered = new Map([[0, 1], [1, 20], [3, 2], [4, 15], [5, 1], [6, 18], [8, 2], [9, 1], [2, 9], [7, 11]]);
  const phi = M.dispersion(clustered, years, nino);
  assert.ok(phi > 5);
  const [, lo, hi] = M.rateRatio(20, 2, 60, 8, phi), [, lo1, hi1] = M.rateRatio(20, 2, 60, 8);
  assert.ok(lo < lo1 && hi > hi1);
  assert.deepEqual(M.returnPeriodCI(...M.wilson(0, 45)), [12.7, null]); // sin años con daños: «al menos 1 de cada 12,7»
});

it('Wilson y la razón de tasas coinciden con valores conocidos', () => {
  assert.deepEqual(M.wilson(0, 46), [0, 0.0771]);
  assert.deepEqual(M.wilson(46, 46), [0.9229, 1]);
  const [rr, lo, hi] = M.rateRatio(20, 10, 20, 20);
  assert.equal(rr, 2);
  assert.ok(lo < 2 && hi > 2 && Math.abs(Math.log(hi / 2) - Math.log(2 / lo)) < 1e-3);
  assert.deepEqual(M.rateRatio(0, 10, 5, 20), [null, null, null]);
});

for (const [level, file] of [['departamento', 'indicadores-departamento.csv'], ['provincia', 'indicadores-provincia.csv'], ['distrito', 'indicadores-distrito.csv']]) {
  it(`los indicadores por ${level} son los mismos que en Python`, () => {
    const py = csv(file);
    const js = M.byArea(recs, level, years, nino, sum.grandesNinos, hom);
    assert.equal(js.size, py.size);
    let n = 0;
    for (const [code, st] of js) {
      const p = py.get(code);
      assert.ok(p, code);
      assert.equal(st.registros, +p.registros, code);
      assert.equal(st.aniosConEvento, +p.aniosConEvento, code);
      assert.equal(st.distritoAnios, +p.distritoAnios, code);
      assert.equal(st.frecuenciaAnual, +p.frecuenciaAnual, code);
      // Python redondea al par más cercano y JS hacia arriba: 1,8125 → 1,812 o 1,813.
      assert.equal(st.razonNino === null, p.razonNino === '', code);
      if (st.razonNino !== null) assert.ok(Math.abs(st.razonNino - p.razonNino) <= 0.0011, `${code}: ${st.razonNino} ≠ ${p.razonNino}`);
      assert.equal(st.grandesNinos.length, +p.nGrandesNinos, code);
      // Intervalos: sobredispersión, periodo de retorno y probabilidad en 5 años, iguales que en Python.
      assert.equal(st.dispersionNino, +p.dispersionNino, code);
      if (st.razonNino !== null) assert.ok(Math.abs(st.razonNinoIC[0] - p.razonNinoIC_inf) <= 0.0011 && Math.abs(st.razonNinoIC[1] - p.razonNinoIC_sup) <= 0.0011, code);
      const num = (v) => (v === '' ? null : +v);
      assert.deepEqual(st.periodoRetornoIC, [num(p.periodoRetornoIC_inf), num(p.periodoRetornoIC_sup)], code);
      assert.ok(Math.abs(st.prob5AniosIC[0] - p.prob5AniosIC_inf) <= 0.00011 && Math.abs(st.prob5AniosIC[1] - p.prob5AniosIC_sup) <= 0.00011, code);
      n++;
    }
    assert.ok(n > (level === 'distrito' ? 1000 : 20));
  });
}

it('los filtros por evento, peligro y periodo', () => {
  const great = M.filter(recs, { event: 'grandes', great: sum.grandesNinos });
  assert.ok(great.length > 1000 && great.every((r) => sum.grandesNinos.includes(r.e)));
  const fen97 = M.filter(recs, { event: 'FEN 1997-98' });
  assert.ok(fen97.every((r) => r.d >= '1997-04-01' && r.d <= '1998-08-31'));
  const huaycos = M.filter(recs, { types: new Set(['Huayco/Alud']), from: 1990, to: 1999 });
  assert.ok(huaycos.length > 100 && huaycos.every((r) => r.t === 'Huayco/Alud' && M.seasonOf(r) >= 1990 && M.seasonOf(r) <= 1999));
  // Periodo y registros con la misma unidad (temporadas): «1998 a 1998» es una temporada entera, no dos mitades.
  assert.deepEqual(M.coverageYears([1970, 2014], 1998, 2000), [1998, 1999, 2000]);
  const piura98 = M.summarize(M.filter(recs, { from: 1997, to: 1997 }).filter((r) => r.u.startsWith('20')), M.coverageYears(sum.cobertura.homogenea, 1997, 1997), nino, sum.grandesNinos, hom);
  assert.equal(piura98.aniosCobertura, 1);
  assert.ok(piura98.frecuenciaAnual <= 1 && piura98.razonNino === null);
});

it('Piura: El Niño multiplica los daños y es un lugar de daños repetidos', () => {
  const dep = M.byArea(recs, 'departamento', years, nino, sum.grandesNinos, hom).get('20');
  assert.ok(dep.razonNino > 1.5 && dep.razonNinoIC[0] > 1, JSON.stringify(dep.razonNinoIC));
  const hot = M.repeatHotspots(recs, 'provincia', sum.grandesNinos);
  assert.ok(hot.find((h) => h.code === '2001').n >= 2);
});

it('la frecuencia usa solo la fuente homogénea; los registros, todas', () => {
  const lima = recs.filter((r) => r.u.startsWith('1501'));
  const all = M.summarize(lima, years, nino, sum.grandesNinos, null);
  const only = M.summarize(lima, years, nino, sum.grandesNinos, hom);
  assert.equal(all.registros, only.registros);
  assert.ok(only.distritoAnios <= all.distritoAnios);
  const later = lima.filter((r) => !hom.has(r.o));
  assert.ok(later.length > 0, 'Lima tiene registros de 2016 en adelante');
  assert.equal(M.summarize(later, years, nino, sum.grandesNinos, hom).aniosConEvento, 0);
});

it('el Niño Costero 2017 solo en los 13 departamentos del Plan de Reconstrucción', () => {
  const zone = new Set(sum.eventosNombrados.find((e) => e.nombre === 'Niño Costero 2017').departamentos);
  assert.equal(zone.size, 13);
  const n17 = recs.filter((r) => r.e === 'Niño Costero 2017');
  assert.ok(n17.length > 1000 && n17.every((r) => zone.has(r.u.slice(0, 2))));
  assert.ok(!n17.some((r) => ['Helada/Friaje', 'Nevada', 'Sequias', 'Incendio forestal'].includes(r.t)));
});

it('cortes por cuantiles y clases', () => {
  const br = M.quantileBreaks([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5);
  assert.equal(br.at(-1), 10);
  assert.equal(M.classOf(0, br), -1);
  assert.equal(M.classOf(10, br), br.length - 1);
  assert.deepEqual(M.quantileBreaks([], 5), []);
});
