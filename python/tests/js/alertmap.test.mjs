// Fase de un aviso en el mapa (public/assets/js/alertmap.js). Se corre con `node --test`
// (la lanza tests/test_alert_map.py).
import assert from 'node:assert/strict';
import { it } from 'node:test';

import { phaseOf } from '../../../public/assets/js/alertmap.js';

const NOW = Date.parse('2026-10-21T20:40:00Z');
const AVISO = { kind: 'pronostico', date: '2026-10-19T14:18:20Z', valid: { from: '2026-10-20T05:00:00Z', until: '2026-10-23T04:59:00Z' } };

it('un aviso vigente según su vigencia', () => {
  assert.equal(phaseOf(AVISO, NOW), 'vigente');
  assert.equal(phaseOf({ ...AVISO, aviso: { num: 426, cancelled: false } }, NOW), 'vigente');
});

it('un aviso que la tabla del SENAMHI marca cancelado ya no está vigente', () => {
  assert.equal(phaseOf({ ...AVISO, aviso: { num: 425, cancelled: true } }, NOW), 'vencida');
});

// safeUrl resuelve contra la página; en node no hay documento.
globalThis.document ??= { baseURI: 'https://observatorio.example/' };
const { itemBadges, levelsNote, prepare } = await import('../../../public/assets/js/alertmap.js');

const RATED = { ...AVISO, title: 'Aviso del SENAMHI N° 429', severity: { scale: 'senamhi-colores', rank: 3, label: 'Rojo', scaleLabel: 'SENAMHI',
  basisUrl: 'https://www.senamhi.gob.pe/?p=aviso-meteorologico-detalle&a=2026&b=29296&c=00&d=SENA',
  basisArchive: 'archive/sources/senamhi-avisos/0123456789ab.txt' } };

it('el nivel enlaza el aviso en el SENAMHI y la copia de su tabla', () => {
  const out = String(itemBadges(RATED, NOW));
  assert.match(out, /href="https:\/\/www\.senamhi\.gob\.pe\/\?p=aviso-meteorologico-detalle&amp;a=2026&amp;b=29296/);
  assert.match(out, /href="data\/archive\/sources\/senamhi-avisos\/0123456789ab\.txt"[^>]*>copia de la tabla/);
  // Sin esos datos (un aviso de otra institución) no aparece nada, y una ruta ajena no se enlaza.
  assert.doesNotMatch(String(itemBadges({ ...AVISO, severity: { rank: 2, label: 'Naranja' } }, NOW)), /nivel:/);
  assert.doesNotMatch(String(itemBadges({ ...RATED, severity: { ...RATED.severity, basisArchive: '../x' } }, NOW)), /copia de la tabla/);
});

it('el pie dice de qué copia de la tabla salen los niveles y avisa si es vieja', () => {
  const levels = { url: 'https://www.senamhi.gob.pe/?p=aviso-meteorologico', copyAt: '2026-10-21T05:10:00Z',
    archive: 'archive/sources/senamhi-avisos/0123456789ab.txt', avisos: 24 };
  const feed = { groups: [{ id: 'alertas', items: [RATED], levelsFrom: levels }] };
  assert.deepEqual(prepare(feed, NOW).levels, levels);
  const fresh = String(levelsNote(levels, NOW));
  assert.match(fresh, /copiada desde el Perú/);
  assert.match(fresh, /href="data\/archive\/sources\/senamhi-avisos\/0123456789ab\.txt"/);
  assert.doesNotMatch(fresh, /figuran sin nivel/);
  assert.match(String(levelsNote(levels, NOW + 48 * 36e5)), /<strong>Esa copia tiene 3 días: los avisos emitidos después figuran sin nivel/);
  assert.equal(levelsNote(null, NOW), '');
  assert.equal(prepare({ groups: [{ id: 'alertas', items: [] }] }, NOW).levels, null);
});

it('un aviso con informe (PDF) lo enlaza y el mapa lo abre en lugar de la portada', () => {
  const doc = 'https://portal.indeci.gob.pe/wp-content/uploads/2026/10/BOLET%C3%8DN-N%C2%B0435.pdf';
  const item = { ...RATED, id: 'alert-x', url: 'https://portal.indeci.gob.pe/emergencias/boletin-435/', document: doc,
    geo: { places: [{ code: '20', level: 'departamento', name: 'Piura', confidence: 0.95, method: 'campo' }] } };
  const out = String(itemBadges(item, NOW));
  assert.match(out, /href="https:\/\/portal\.indeci\.gob\.pe\/wp-content\/uploads\/2026\/10\/BOLET%C3%8DN-N%C2%B0435\.pdf"[^>]*>informe completo \(PDF\)/);
  const m = prepare({ groups: [{ id: 'alertas', items: [item] }] }, NOW);
  assert.equal(m.alerts[0].url, doc);
  assert.deepEqual(m.alerts[0].deps, ['20']);
  // Sin informe, la publicación.
  assert.equal(prepare({ groups: [{ id: 'alertas', items: [{ ...item, document: undefined }] }] }, NOW).alerts[0].url, item.url);
});

it('los lugares que no trae el aviso dicen de dónde salen', () => {
  const tg = { ...RATED, geo: { places: [{ code: '21', level: 'departamento', name: 'Puno', confidence: 0.6, method: 'region' }],
    via: { basis: 'regiones que nombra el aviso («en la sierra sur»), no departamentos de la fuente' } } };
  assert.match(String(itemBadges(tg, NOW)), /lugares: regiones que nombra el aviso/);
  const shared = { ...RATED, geo: { places: [], via: { basis: 'departamentos del boletín del COEN del aviso N° 435',
    document: 'https://portal.indeci.gob.pe/wp-content/uploads/x.pdf' } } };
  assert.match(String(itemBadges(shared, NOW)), /boletín del COEN del aviso N° 435 \(<a href="https:\/\/portal\.indeci\.gob\.pe\/wp-content\/uploads\/x\.pdf"/);
});

const { project, detailMarkup, basinsMarkup } = await import('../../../public/assets/js/alertmap.js');
const GEO = { lonLat: { lon0: -81.45, lat1: 0.05, k: 40, cos: 0.986286 } };

it('los puntos y las formas caen donde los pone la proyección del mapa (peru-map.json)', () => {
  const [x, y] = project(GEO, -77.03, -12.05);  // Lima
  assert.ok(Math.abs(x - (-77.03 + 81.45) * 0.986286 * 40) < 1e-9 && Math.abs(y - 12.1 * 40) < 1e-9);
  assert.deepEqual(project(GEO, -81.45, 0.05), [0, 0]);
});

it('el detalle de los avisos: formas y distritos de los vigentes, del nivel más bajo al más alto, y puntos de todos', () => {
  const ring = [[-80, -5], [-79, -5], [-79, -6], [-80, -6], [-80, -5]];
  const item = (id, rank, detail, extra = {}) => ({ ...RATED, id, title: `Aviso ${id}`, severity: { ...RATED.severity, rank },
    geo: { places: [{ code: '20', level: 'departamento', name: 'Piura', confidence: 0.95, method: 'campo' }] }, detail, ...extra });
  const feed = { groups: [{ id: 'alertas', items: [
    item('rojo', 3, { shapes: [{ rings: [ring] }], areas: [{ code: '200201', name: 'Ayabaca', n: 17 }] }),
    item('amarillo', 1, { shapes: [{ rings: [ring] }], areas: [{ code: '200201', name: 'Ayabaca', n: 4 }, { code: '200101', name: 'Piura', n: 2 }] }),
    item('pasado', 2, { shapes: [{ rings: [ring] }], areas: [{ code: '200301', n: 1 }],
      points: [{ name: 'Estación Chulucanas', lat: -5.1, lon: -80.16, kind: 'estacion', basin: { code: '13951', name: 'Cuenca Piura' } }] },
    { valid: { from: '2026-10-01T05:00:00Z', until: '2026-10-02T04:59:00Z' } }),
  ] }] };
  const m = prepare(feed, NOW);
  const districts = { 200201: { d: 'M1 1h2v2z' }, 200101: { d: 'M5 5h2v2z' }, 200301: { d: 'M9 9h2v2z' } };
  const out = detailMarkup(GEO, m.alerts, {}, { districts });
  // Las zonas: la del aviso vencido no se dibuja; la amarilla va antes que la roja (el rojo queda arriba).
  const shapes = [...out.matchAll(/class="amap-shape s-(r\d)/g)].map((x) => x[1]);
  assert.deepEqual(shapes, ['r1', 'r3']);
  // Ayabaca sale una sola vez, con el nivel más alto, y su cuadro dice las quebradas de cada aviso.
  const areas = [...out.matchAll(/<path class="amap-area s-(r\d)[^"]*" d="([^"]+)"[^>]*data-tip="([^"]+)"/g)];
  assert.deepEqual(areas.map((x) => [x[1], x[2]]), [['r1', 'M5 5h2v2z'], ['r3', 'M1 1h2v2z']]);
  assert.match(areas[1][3], /^Ayabaca: quebradas con probable activación\n17 quebradas · Aviso rojo\n4 quebradas · Aviso amarillo$/);
  assert.doesNotMatch(out, /M9 9h2v2z/);
  // El punto de la estación del aviso vencido sí aparece, como referencia (s-rep), con su cuenca sin repetir «cuenca».
  const [x, y] = project(GEO, -80.16, -5.1);
  assert.match(out, new RegExp(`<rect class="amap-pt k-estacion s-rep"[^>]*transform="rotate\\(45 ${x.toFixed(1)} ${y.toFixed(1)}\\)"[^>]*data-tip="Estación Chulucanas\\nAviso pasado\\nCuenca Piura"`));
  // Sin detalle no hay capa.
  assert.equal(detailMarkup(GEO, prepare({ groups: [{ id: 'alertas', items: [RATED] }] }, NOW).alerts, {}, { districts }), '');
});

it('las cuencas de la ANA, cada una con su nombre y su código', () => {
  const out = basinsMarkup({ units: { 13951: { n: 'Cuenca Piura', l: 5, d: 'M1 1h1z', c: [1, 1] } } });
  assert.equal(out, '<g class="amap-basins" aria-hidden="true"><path d="M1 1h1z" data-tip="Cuenca Piura\nUnidad hidrográfica 13951 de la ANA"></path></g>');
  assert.equal(basinsMarkup(null), '');
});

it('un río o una quebrada del reporte: su punto y el círculo de su tramo; una provincia expuesta: su trazo, debajo de los distritos', () => {
  const item = { ...RATED, id: 'coen', title: 'Aviso de corto plazo', severity: { ...RATED.severity, rank: 2 },
    geo: { places: [{ code: '20', level: 'departamento', name: 'Piura', confidence: 0.95, method: 'campo' }] },
    detail: {
      areas: [{ code: '200201', name: 'Ayabaca', n: 3 }, { code: '2002', name: 'Ayabaca', kind: 'provincia' }],
      points: [{ name: 'Quebrada Jicamarca', lat: -11.98, lon: -76.896, kind: 'cuerpo-de-agua', radiusKm: 10,
        basin: { code: '137554', name: 'Cuenca Rímac' } }],
    } };
  const m = prepare({ groups: [{ id: 'alertas', items: [item] }] }, NOW);
  const out = detailMarkup(GEO, m.alerts, {}, { districts: { 200201: { d: 'M1 1h2v2z' }, 2002: { d: 'M0 0h9v9z' } } });
  const [x, y] = project(GEO, -76.896, -11.98);
  const reach = ((10 / 111) * 40).toFixed(1);
  assert.match(out, new RegExp(`<g class="amap-pt k-cuerpo-de-agua s-r2"[^>]*data-tip="Quebrada Jicamarca\\nAviso de corto plazo\\nCuenca Rímac · ±10 km"><circle class="amap-reach" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${reach}">`));
  const areas = [...out.matchAll(/<path class="amap-area([^"]*)" d="([^"]+)"[^>]*data-tip="([^"]+)"/g)];
  assert.deepEqual(areas.map((a) => a[2]), ['M0 0h9v9z', 'M1 1h2v2z']);
  assert.match(areas[0][1], /amap-prov s-r2/);
  assert.match(areas[0][3], /^Provincia de Ayabaca: expuesta según el aviso de corto plazo\nAviso de corto plazo$/);
});

it('la lista de alertas nombra el centro poblado, el río y la cuenca del aviso', async () => {
  const { fineTags } = await import('../../../public/assets/js/alertmap.js');
  const item = { detail: { points: [
    { kind: 'centro-poblado', name: 'Panamá', basin: { name: 'Cuenca Crisnejas' } },
    { kind: 'cuerpo-de-agua', name: 'Quebrada Jicamarca', basin: { name: 'Cuenca Rímac' } },
    { kind: 'estacion', name: 'Estación Chulucanas', basin: { name: 'Cuenca Piura' } },
  ] } };
  const out = String(fineTags(item));
  assert.deepEqual([...out.matchAll(/tag-fine"[^>]*>(?:<svg[\s\S]*?<\/svg>)?([^<]+)</g)].map((x) => x[1]), ['Panamá', 'Quebrada Jicamarca']);
  assert.deepEqual([...out.matchAll(/tag-basin"[^>]*>([^<]+)</g)].map((x) => x[1]), ['Cuenca Crisnejas', 'Cuenca Rímac']);
  assert.equal(String(fineTags({})).trim(), '');
});

// ---------------------------------------------------------------------------
// Vistas de detalle: avisos por cuenca y distritos en aviso con su historia
// ---------------------------------------------------------------------------
const { inRing, alertDistricts, alertUnits, detailView } = await import('../../../public/assets/js/alertmap.js');

it('punto dentro de un anillo, también en uno cóncavo', () => {
  const sq = [[0, 0], [10, 0], [10, 10], [0, 10]];
  assert.equal(inRing(5, 5, sq), true);
  assert.equal(inRing(11, 5, sq), false);
  const u = [[0, 0], [9, 0], [9, 9], [6, 9], [6, 3], [3, 3], [3, 9], [0, 9]];  // una «U»
  assert.equal(inRing(4.5, 6, u), false);
  assert.equal(inRing(1.5, 6, u), true);
});

// Un aviso vigente de Piura con todo lo que lo hace más fino que el departamento.
const RING = [[-80.2, -4.9], [-79.4, -4.9], [-79.4, -5.4], [-80.2, -5.4], [-80.2, -4.9]];
const FINE = { ...RATED, id: 'fino-1', title: 'Aviso fino', severity: { ...RATED.severity, rank: 2 },
  geo: { places: [{ code: '20', level: 'departamento', name: 'Piura', confidence: 0.95, method: 'campo' },
    { code: '200401', level: 'distrito', name: 'Huancabamba', confidence: 0.9, method: 'texto' },
    { code: '2007', level: 'provincia', name: 'Talara', confidence: 0.9, method: 'texto' }] },
  detail: { shapes: [{ rings: [RING] }], areas: [{ code: '200201', name: 'Ayabaca', n: 3 }],
    points: [{ kind: 'centro-poblado', name: 'Tambogrande', district: '200111', basin: { code: '13952', name: 'Cuenca Chira' } },
      { kind: 'estacion', name: 'Estación', district: '200301', basin: { code: '13951' } }] } };
const GEO2 = { ...GEO, width: 507, height: 740, departments: [{ d: 'M0 0h9v9z' }], points: {
  200101: project(GEO, -80.63, -5.19), 200105: project(GEO, -79.9, -5.1), 200111: project(GEO, -80.34, -4.91),
  200201: project(GEO, -79.71, -4.64), 200301: project(GEO, -80.16, -5.1), 200401: project(GEO, -79.45, -5.24),
  200701: project(GEO, -81.27, -4.58), 200702: project(GEO, -81.1, -4.2), 150101: project(GEO, -77.03, -12.05) } };
const CODES = Object.keys(GEO2.points);

it('los distritos de un aviso: el que nombra, su provincia, sus quebradas, sus lugares y su zona; una estación no', () => {
  const [a] = prepare({ groups: [{ id: 'alertas', items: [FINE] }] }, NOW).alerts;
  const got = Object.fromEntries(alertDistricts(a, GEO2, CODES));
  assert.deepEqual(got, { 200401: 'lugar', 200701: 'provincia', 200702: 'provincia', 200201: 'quebradas', 200111: 'punto', 200105: 'zona', 200301: 'zona' });
  // Un aviso pasado no extiende su zona; uno que solo nombra el departamento no toca ningún distrito.
  const [old] = prepare({ groups: [{ id: 'alertas', items: [{ ...FINE, id: 'fino-2', valid: { from: '2026-10-01T05:00:00Z', until: '2026-10-02T04:59:00Z' } }] }] }, NOW).alerts;
  assert.ok(![...alertDistricts(old, GEO2, CODES).values()].includes('zona'));
  const [dep] = prepare({ groups: [{ id: 'alertas', items: [{ ...RATED, id: 'dep-1', geo: { places: [{ code: '20', level: 'departamento', name: 'Piura' }] } }] }] }, NOW).alerts;
  assert.equal(alertDistricts(dep, GEO2, CODES).size, 0);
  const U = alertUnits([a, dep], GEO2, CODES, { 200401: '13951', 200201: '13952' });
  assert.deepEqual(U.coarse.map((x) => x.id), ['dep-1']);
  assert.deepEqual([...U.basin.keys()].sort(), ['13951', '13952']);  // por sus distritos y por el centro poblado; la estación no
  assert.equal(U.dist.get('200111')[0].id, 'fino-1');
});

it('el detalle por cuenca y por distrito: color del aviso, memoria y enlace a la memoria', () => {
  const alerts = prepare({ groups: [{ id: 'alertas', items: [{ ...FINE, id: 'fino-3' }] }] }, NOW).alerts;
  const row = (registros, con, cob, extra = {}) => ({ registros, aniosConEvento: con, aniosCobertura: cob, grandesNinos: 1, ultimo: '2017-03-14', muertos: 0, peligro: 0, desde: 1972, poblacion: 0, nombre: 'Huancabamba', ...extra });
  const ctx = {
    districts: Object.fromEntries(CODES.map((c) => [c, { d: `M${c.slice(-2)} 0h1v1z` }])),
    B: { units: { 13951: { n: 'Cuenca Piura', d: 'M0 0h5v5z' }, 13952: { n: 'Cuenca Chira', d: 'M5 0h5v5z' }, 1376: { n: 'Cuenca Santa', d: 'M9 9h1v1z' } },
      districts: { 200401: '13951', 200201: '13952' } },
    H: { peligros: ['Lluvia/Inundación'], distritos: new Map([['200401', row(40, 18, 45)]]), provincias: new Map(),
      cuencas: new Map([['13951', row(900, 50, 0, { nombre: 'Cuenca Piura', desde: 1925 })]]) },
  };
  const C = detailView('cuencas', GEO2, alerts, {}, ctx);
  assert.match(String(C.svg), /class="bas d-r2" d="M0 0h5v5z" data-basin="13951"/);
  assert.match(String(C.svg), /class="bas d-base" d="M9 9h1v1z" data-basin="1376"/);
  assert.match(String(C.side), /Cuenca Piura/);
  assert.match(String(C.side), /50 temporadas con registros/);
  const sel = detailView('cuencas', GEO2, alerts, {}, ctx, '13951');
  assert.match(String(sel.side), /href="#\/memoria\?vista=cuencas&amp;cuenca=13951"/);
  assert.match(String(sel.side), /Memoria: 900 registros, 50 temporadas con registros desde 1925, 1 gran Niño; lo más frecuente: lluvia o inundación\./);
  assert.match(String(sel.svg), /class="sel-ring"/);
  const D = detailView('distritos', GEO2, alerts, {}, ctx, '200401');
  // 18 de 45 años: 40 %, en el quinto tramo (35 % o más) de la escala de la memoria.
  assert.match(String(D.svg), /class="dist hz-q4 s-r2 sel"[^>]*data-dist="200401"/);
  assert.match(String(D.side), /daños en 18 de 45 años \(1970-2015\), 1 gran Niño[^<]*último registro: 14 de marzo de 2017/);
  assert.match(String(D.side), /href="#\/memoria\?nivel=distrito&amp;area=200401"/);
  // Un distrito sin memoria se dice sin registros.
  assert.match(String(D.svg), /class="dist hz-na s-r2"[^>]*data-dist="200111"[^>]*data-tip="[^"]*Sin registros en la memoria de desastres\./);
});

it('#/variantes: los tres experimentos con su tasa de uso, su intervalo y la decisión', async () => {
  const { statsHtml } = await import('../../../public/assets/js/alertmap.js');
  const { decide, EXPERIMENTS } = await import('../../../functions/_lib/ab.js');
  const t = (view, use) => ({ view, use, hover: 0, select: use, detail: 0, choose: 0, leave: 0, keep: 0, chosen: 0 });
  const totals = {
    mapa: { A: t(10, 1), B: t(10, 2), C: t(10, 3), D: t(10, 4) },
    memoria: { resumen: t(300, 60), cuencas: t(300, 180), puntos: t(300, 70), riesgo: t(300, 65) },
    noticias: { resumen: t(50, 10), cuencas: t(250, 50), distritos: t(250, 60) },
  };
  const experiments = Object.fromEntries(Object.entries(EXPERIMENTS).map(([x, vs]) => [x, { variants: vs, totals: totals[x], decision: decide(vs, totals[x]) }]));
  const out = String(statsHtml({ available: true, days: 30, decideDays: 60, since: '2026-09-29', totals: totals.mapa, experiments }));
  assert.equal((out.match(/<table/g) || []).length, 3);
  assert.match(out, /Gana «cuencas»/);
  assert.match(out, /Detalle: cuencas <span class="chip chip-ok">Ganadora<\/span>/);
  assert.match(out, /60 %<div class="muted small">54–65 %<\/div>/);  // 180 de 300, con su intervalo de Wilson
  assert.match(out, /faltan en «A», 10; «B», 10; «C», 10; «D», 10/);
  assert.match(out, /faltan en «resumen», 50\)/);
  assert.match(out, /\(no con el periodo elegido\)/);
  assert.match(String(statsHtml(null)), /No se pudo leer la analítica/);
});
