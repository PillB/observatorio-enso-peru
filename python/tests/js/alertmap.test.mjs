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
