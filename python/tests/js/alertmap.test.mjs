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
