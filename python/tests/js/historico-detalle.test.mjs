// Vistas de detalle del mapa de la memoria (public/assets/js/historico-detalle.js) sobre los datos publicados:
// los ríos de rios-mapa.json, los puntos de finos.json y los cálculos sin DOM. Se corre con `node --test`
// (la lanza tests/test_historico.py).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { describe, it } from 'node:test';

import * as M from '../../../public/assets/js/historico-model.js';
import * as DT from '../../../public/assets/js/historico-detalle.js';

const ROOT = new URL('../../../', import.meta.url);
const read = (p) => JSON.parse(readFileSync(new URL(p, ROOT)));
const ev = read('public/assets/historico/eventos.json');
const recs = M.decode(ev);
const X = DT.prepFine(read('public/assets/historico/finos.json'));
const R = DT.prepRivers(read('public/assets/capas/rios-mapa.json'));
const B = read('public/assets/cuencas-mapa.json');
const peru = read('public/assets/peru-map.json');
const KM2 = (111.32 / 40) ** 2;

describe('ríos, quebradas y lagunas nombrados', () => {
  it('la clave de cada tramo es la misma normalización que en Python', () => {
    for (const r of R.reaches) assert.equal(DT.norm(r.n), r.k, r.n);
    assert.equal(DT.norm('  Río   Rímac '), 'rio rimac');
    assert.equal(DT.norm('Quebrada San Andrés'), 'quebrada san andres');
  });

  it('cada trazo junta los mismos registros en la página que en Python', () => {
    const groups = new Map(DT.named(recs, X, 'agua', [], R).map((g) => [g.key, g]));
    for (const r of R.reaches) {
      const g = groups.get(DT.reachKey(r));
      assert.ok(g, DT.reachKey(r));
      assert.equal(g.registros, r.r, r.n);  // un registro cuenta una vez por río que nombra
      assert.equal(g.basin, r.b);
    }
    // Lo que queda sin trazo: nombres que la Carta no tiene en esos distritos (pocos registros).
    const rest = [...groups.values()].filter((g) => !R.byKey.has(g.key.slice(2).replace(':', '|')));
    const share = rest.reduce((t, g) => t + g.registros, 0) / [...groups.values()].reduce((t, g) => t + g.registros, 0);
    assert.ok(share < 0.05, `${(share * 100).toFixed(1)} % de los registros con río sin trazo`);
    // Nevados, volcanes y abras no son ríos.
    assert.ok(![...groups.values()].some((g) => /^(Nevado|Volcán|Abra)\b/.test(g.name)));
  });

  it('el foco de un tramo vuelve a sus registros, también el de un río sin cuenca', () => {
    for (const r of R.reaches) {
      const g = DT.focusRecords(recs, X, DT.reachKey(r), R);
      assert.ok(g, DT.reachKey(r));
      assert.equal(g.registros, r.r);
      assert.match(DT.reachKey(r), /^[rl]:u?\d{1,8}:.{1,80}$/);  // lo que acepta el enlace (historico.js readState)
    }
  });

  it('los trazos caen dentro del mapa y los distritos que tocan existen', () => {
    const shapes = read('public/assets/historico/mapa.json');
    for (const r of R.reaches) {
      const b = DT.pathBox(r.d);
      assert.ok(b && b[0] >= -2 && b[1] >= -2 && b[2] <= peru.width + 2 && b[3] <= peru.height + 2, r.n);
      for (const u of r.u) assert.ok(shapes.districts[u], `${r.n}: ${u}`);
      if (r.b) assert.ok(B.units[r.b], `${r.n}: cuenca ${r.b}`);
    }
  });

  it('separa los nombres juntos y les quita la aclaración', () => {
    assert.deepEqual(DT.waterNames('Río Chili (Sumbay) · Quebrada Honda'), ['Río Chili', 'Quebrada Honda']);
  });
});

describe('puntos finos', () => {
  it('cada punto, nombre y cuenca es de un registro del catálogo', () => {
    assert.equal(X.cuenca.length, recs.length);
    for (const [i, lat, lon, kind] of X.puntos) {
      assert.ok(Number.isInteger(i) && i >= 0 && i < recs.length);
      assert.ok(lat > -18.6 && lat < 0.2 && lon > -81.5 && lon < -68.5, `${i}: ${lat}, ${lon}`);
      assert.ok([0, 1, 3].includes(kind));
    }
    for (const [i, ni] of [...X.agua, ...X.lugar]) assert.ok(i < recs.length && ni < X.nombres.length);
    for (const c of X.cuenca) assert.ok(c === 0 || (c <= X.cuencas.length && B.units[X.cuencas[c - 1]]));
    // El registro i de finos.json es la fila i de eventos.json.
    assert.ok(recs.every((r, k) => r.i === undefined || r.i === k));
  });

  it('un punto cae en el distrito de su registro o a menos de 3 km de su borde (los límites del mapa están simplificados)', () => {
    const shapes = read('public/assets/historico/mapa.json');
    const ringsOf = (d) => d.split(/(?=M)/).map((sub) => {
      const nums = sub.match(/-?\d*\.?\d+/g).map(Number);
      const pts = [[nums[0], nums[1]]];
      for (let k = 2; k + 1 < nums.length; k += 2) pts.push([pts.at(-1)[0] + nums[k], pts.at(-1)[1] + nums[k + 1]]);
      return pts;
    });
    const inside = (x, y, rings) => rings.reduce((acc, ring) => {
      let c = false;
      for (let a = 0, b = ring.length - 1; a < ring.length; b = a++) {
        const [xa, ya] = ring[a], [xb, yb] = ring[b];
        if ((ya > y) !== (yb > y) && x < ((xb - xa) * (y - ya)) / (yb - ya) + xa) c = !c;
      }
      return acc !== c;
    }, false);
    let out = 0, n = 0;
    for (const [i, lat, lon] of X.puntos) {
      const u = recs[i].u;
      const d = shapes.districts[u]?.d;
      if (u.length !== 6 || !d) continue;
      n++;
      const [x, y] = DT.project(peru, lat, lon);
      const rings = ringsOf(d);
      if (inside(x, y, rings)) continue;
      // Distancia al borde más cercano, en km (unos 2,78 km por unidad del mapa en los dos ejes).
      let best = Infinity;
      for (const ring of rings) {
        for (let a = 0, b = ring.length - 1; a < ring.length; b = a++) {
          const [x1, y1] = ring[b], [x2, y2] = ring[a];
          const L = (x2 - x1) ** 2 + (y2 - y1) ** 2;
          const t = L ? Math.max(0, Math.min(1, ((x - x1) * (x2 - x1) + (y - y1) * (y2 - y1)) / L)) : 0;
          best = Math.min(best, Math.hypot(x - x1 - t * (x2 - x1), y - y1 - t * (y2 - y1)));
        }
      }
      if (best * 2.78 > 3) out++;
    }
    assert.ok(n > 8000);
    assert.equal(out, 0, `${out} de ${n} a más de 3 km de su distrito`);
  });
});

describe('geometría sin DOM', () => {
  it('superficie de un trazo, con agujeros y movimientos relativos', () => {
    assert.ok(Math.abs(DT.pathArea('M0 0l10 0l0 10l-10 0z') - 100 * KM2) < 1e-9);
    // Un agujero con la orientación contraria resta.
    assert.ok(Math.abs(DT.pathArea('M0 0l10 0l0 10l-10 0zM2 2l0 2l2 0l0 -2z') - 96 * KM2) < 1e-9);
    assert.ok(Math.abs(DT.pathArea('M0 0L10 0L10 10L0 10z') - 100 * KM2) < 1e-9);
    assert.ok(Math.abs(DT.pathArea('m0 0l10 0l0 10l-10 0zm20 0l5 0l0 5l-5 0z') - 125 * KM2) < 1e-9);
  });

  it('las cuencas de la ANA suman la superficie del Perú', () => {
    const total = Object.values(B.units).reduce((t, u) => t + DT.pathArea(u.d), 0);
    assert.ok(Math.abs(total / 1285216 - 1) < 0.03, `${Math.round(total)} km²`);
  });

  it('caja y encuadre', () => {
    assert.deepEqual(DT.pathBox('M1 2l3 4l-5 0z'), [-1, 2, 4, 6]);
    assert.deepEqual(DT.joinBox([[0, 0, 1, 1], null, [-1, 2, 0, 5]]), [-1, 0, 1, 5]);
    const [, , w, h] = DT.boxView([0, 0, 100, 40]).split(' ').map(Number);
    assert.ok(Math.abs(w / h - 0.75) < 1e-3 && w >= 100);
    assert.equal(DT.pathBox(''), null);
  });

  it('hexágonos: cada punto en el más cercano, sin perder ninguno', () => {
    const pts = Array.from({ length: 2000 }, (_, k) => [(k * 37.1) % 500, (k * 53.7) % 700]);
    const R5 = 5.5;
    const bins = DT.hexbin(pts, R5);
    assert.equal(bins.reduce((t, b) => t + b.n, 0), pts.length);
    for (const b of bins) for (const [x, y] of b.items) assert.ok(Math.hypot(x - b.x, y - b.y) <= R5 + 1e-9);
    assert.equal(new Set(bins.map((b) => `${b.x},${b.y}`)).size, bins.length);
    assert.match(DT.hexPath(R5), /^m0 -5\.5(l-?\d+\.\d\d -?\d+\.\d\d){5}z$/);
  });

  it('terciles y clases del bivariado', () => {
    assert.deepEqual(DT.tertiles([9, 1, 2, 3, 4, 5, 6, 7, 8, null]), [3, 6]);
    assert.deepEqual([1, 3, 4, 6, 7].map((v) => DT.tclass(v, [3, 6])), [0, 0, 1, 1, 2]);
    const stats = new Map([['a', 0.1], ['b', 0.5], ['c', 0.9], ['d', 0.2]]);
    const attrs = new Map([['a', [0, 10]], ['b', [0, 50]], ['c', [0, 90]], ['d', [0, null]]]);
    const { cells } = DT.bivariate(stats, attrs, ['a', 'b', 'c', 'd'], (v) => v);
    assert.deepEqual([...cells.keys()], ['a', 'b', 'c']);
    assert.deepEqual([...cells.values()].map((c) => c.cls), ['b00', 'b11', 'b22']);
  });

  it('la proyección es la de peru-map.json', () => {
    const [x, y] = DT.project(peru, -12.0464, -77.0428);  // Lima
    assert.ok(x > 150 && x < 210 && y > 450 && y < 510, `${x}, ${y}`);
  });
});
