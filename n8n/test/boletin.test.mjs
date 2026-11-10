// Pruebas del flujo del boletín por correo: lib/boletin.js y los nodos «Decidir envío» y «Guardar estado», tal como
// los arma build.mjs. Ningún correo se manda: el nodo de Gmail no corre aquí (ver e2e-boletin.sh).

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { libSource, nodeCode, WORKFLOWS } from '../build.mjs';

const L = new Function(`${libSource('boletin')}\nreturn { parseRecipients, limaClock, pendingChanges, changesHtml, decide, nextState };`)();
const H = 3600000;
const NOW = Date.parse('2026-11-11T15:00:00Z'); // 10:00 en Lima

function doc(edition, recent, extra = {}) {
  return {
    schema: 'enso-boletin/1', edition, cutoff: new Date(NOW - 2 * H).toISOString(), segments: [{ code: '24' }],
    email: { subject: `Boletín El Niño N° ${edition}: 1 en rojo, 0 en naranja`, text: 'texto', html: '<p>x</p><!--cambios--><div>viejo</div><!--/cambios--><p>y</p>' },
    whatsapp: 'wa', recent, ...extra,
  };
}
const CFG = { to: 'yo@example.com', bcc: 'A@x.pe; b@y.com, a@x.pe no-es-correo', digest_hour: 7, max_age_hours: 36, send: true };
const imm = (t) => ({ rule: 'aviso-nuevo', tier: 'inmediata', text: t });
const dig = (t) => ({ rule: 'aviso-nuevo', tier: 'resumen', text: t });

test('las direcciones se limpian, sin repetidas y sin las inválidas', () => {
  assert.deepEqual(L.parseRecipients('A@x.pe; b@y.com, a@x.pe no-es-correo\n<c@z.org>'), ['a@x.pe', 'b@y.com']);
  assert.deepEqual(L.parseRecipients(''), []);
});

test('la hora de Lima es UTC−5', () => {
  assert.deepEqual(L.limaClock(Date.parse('2026-11-11T04:30:00Z')), { hour: 23, day: '2026-11-10' });
});

test('primer boletín: se manda completo, sin bloque de cambios', () => {
  const r = L.decide(doc(1, [{ edition: 1, changes: [{ rule: 'inicial', tier: 'inmediata', text: 'Primer boletín' }] }]), CFG, {}, NOW);
  assert.equal(r.send, true);
  assert.equal(r.kind, 'Primer boletín');
  assert.equal(r.subject, 'Boletín El Niño N° 1: 1 en rojo, 0 en naranja');
  assert.equal(r.to, 'yo@example.com');
  assert.equal(r.bcc, 'a@x.pe,b@y.com');
  assert.match(r.html, /<!--cambios--><!--\/cambios-->/);
});

test('sin ediciones nuevas no se manda nada', () => {
  const r = L.decide(doc(4, [{ edition: 4, changes: [imm('x')] }]), CFG, { lastEdition: 4 }, NOW);
  assert.equal(r.send, false);
  assert.match(r.reason, /Sin ediciones nuevas/);
});

test('un cambio inmediato sale ya y junta los cambios de todas las ediciones nuevas', () => {
  const d = doc(6, [{ edition: 6, changes: [imm('Tumbes sube de naranja a rojo.')] }, { edition: 5, changes: [dig('Nuevo aviso amarillo en Loreto.')] }, { edition: 4, changes: [imm('ya enviado')] }]);
  const r = L.decide(d, CFG, { lastEdition: 4 }, NOW);
  assert.equal(r.send, true);
  assert.equal(r.kind, 'Aviso');
  assert.match(r.subject, /^\[Aviso\] Boletín El Niño N° 6/);
  assert.ok(r.html.includes('Tumbes sube de naranja a rojo.') && r.html.includes('Nuevo aviso amarillo en Loreto.'));
  assert.ok(!r.html.includes('ya enviado') && !r.html.includes('viejo'));
  assert.ok(r.html.indexOf('Loreto') < r.html.indexOf('Tumbes'), 'de la edición más vieja a la más nueva');
  assert.match(r.text, /^Qué cambió desde el último correo:\n- Nuevo aviso amarillo/);
});

test('solo cambios menores: esperan a la hora del resumen, una vez por día', () => {
  const d = doc(5, [{ edition: 5, changes: [dig('Nuevo aviso amarillo en Loreto.')] }]);
  const early = L.decide(d, CFG, { lastEdition: 4 }, Date.parse('2026-11-11T10:00:00Z')); // 05:00 en Lima
  assert.equal(early.send, false);
  assert.match(early.reason, /resumen diario/);
  const due = L.decide(d, CFG, { lastEdition: 4 }, NOW);
  assert.equal(due.send, true);
  assert.equal(due.kind, 'Resumen diario');
  assert.match(due.subject, /^\[Resumen\]/);
  const again = L.decide(d, CFG, { lastEdition: 4, lastDigestDay: '2026-11-11' }, NOW);
  assert.equal(again.send, false);
});

test('ediciones que ya no están en «recent»: se dice en el correo', () => {
  const r = L.decide(doc(30, [{ edition: 30, changes: [imm('x')] }]), CFG, { lastEdition: 10 }, NOW);
  assert.match(r.html, /no alcanzó a cubrir/);
});

test('«send» en false arma el correo pero no lo manda (simulacro)', () => {
  const r = L.decide(doc(1, [{ edition: 1, changes: [] }]), { ...CFG, send: false }, {}, NOW);
  assert.equal(r.send, false);
  assert.equal(r.simulate, true);
  assert.ok(r.html && r.subject);
});

test('sin «to» no se manda, y lo dice', () => {
  const r = L.decide(doc(1, [{ edition: 1, changes: [] }]), { ...CFG, to: '' }, {}, NOW);
  assert.equal(r.send, false);
  assert.match(r.reason, /Falta la dirección/);
});

test('un boletín viejo o con otro formato detiene la ejecución (el «Error workflow» avisa)', () => {
  const old = doc(3, [], { cutoff: new Date(NOW - 40 * H).toISOString() });
  assert.throws(() => L.decide(old, CFG, {}, NOW), /viejo/);
  assert.throws(() => L.decide({ schema: 'otra' }, CFG, {}, NOW), /formato/);
});

test('una numeración reiniciada (fecha posterior) se manda completa; la misma edición no', () => {
  const st = { lastEdition: 7, lastEditionAt: '2026-11-10T04:00:00Z' };
  const restarted = L.decide(doc(1, [{ edition: 1, changes: [{ rule: 'inicial', tier: 'inmediata', text: 'Primer boletín' }] }], { editionAt: '2026-11-11T04:00:00Z' }), CFG, st, NOW);
  assert.equal(restarted.send, true);
  assert.match(restarted.kind, /reiniciada/);
  assert.equal(restarted.editionAt, '2026-11-11T04:00:00Z');
  const same = L.decide(doc(7, [{ edition: 7, changes: [imm('x')] }], { editionAt: '2026-11-10T04:00:00Z' }), CFG, st, NOW);
  assert.equal(same.send, false);
});

test('el estado guarda la edición enviada y el día del resumen', () => {
  assert.deepEqual(L.nextState({}, { edition: 3, digest: false, digestDay: '2026-11-11', at: NOW }),
    { lastEdition: 3, lastEditionAt: null, lastSentAt: '2026-11-11T15:00:00.000Z', lastDigestDay: '2026-11-11' });
  assert.equal(L.nextState({}, { edition: 3, editionAt: '2026-11-11T14:00:00Z', at: NOW }).lastEditionAt, '2026-11-11T14:00:00Z');
  const s = L.nextState({ lastEdition: 3, lastDigestDay: '2026-11-10' }, { edition: 4, digest: false, digestDay: '2026-11-11', at: NOW });
  assert.equal(s.lastDigestDay, '2026-11-10'); // un aviso inmediato no cuenta como el resumen del día
});

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
function runNode(name, { cfg, input, prior = {}, decided }) {
  const st = { ...prior };
  const $ = (n) => ({ first: () => ({ json: n === 'Configuración' ? cfg : decided }) });
  const fn = new AsyncFunction('$', '$input', '$getWorkflowStaticData', nodeCode(name, { VERSION: 'test' }));
  return fn($, { first: () => ({ json: input }) }, () => st).then((out) => ({ out, st }));
}

test('los nodos «Decidir envío» y «Guardar estado» usan los datos estáticos del flujo', async () => {
  const body = JSON.stringify(doc(2, [{ edition: 2, changes: [imm('Piura sube a rojo.')] }], { cutoff: new Date(Date.now() - H).toISOString() }));
  const cfg = { ...CFG, site: 'https://ejemplo/' };
  const { out } = await runNode('boletin', { cfg, input: { statusCode: 200, data: body }, prior: { lastEdition: 1 } });
  assert.equal(out[0].json.send, true);
  assert.equal(out[0].json.lastEdition, 1);
  const { st } = await runNode('boletin-guardar', { cfg, decided: out[0].json, prior: { lastEdition: 1 } });
  assert.equal(st.lastEdition, 2);
  await assert.rejects(runNode('boletin', { cfg, input: { statusCode: 503 } }), /No se pudo leer el boletín/);
  await assert.rejects(runNode('boletin', { cfg, input: { statusCode: 200, data: '<html>' } }), /no es JSON/);
});

test('el flujo empieza sin mandar, y Gmail solo corre por la rama «true» de «¿Enviar?»', () => {
  const wf = WORKFLOWS['enso-n8n-boletin.json'];
  const cfg = wf.nodes.find((n) => n.name === 'Configuración').parameters.assignments.assignments;
  assert.equal(cfg.find((a) => a.name === 'send').value, false);
  assert.equal(cfg.find((a) => a.name === 'bcc').value, '');
  assert.deepEqual(wf.connections['¿Enviar?'].main[0], [{ node: 'Enviar por Gmail', type: 'main', index: 0 }]);
  assert.deepEqual(wf.connections['¿Enviar?'].main[1], []);
  const gmail = wf.nodes.find((n) => n.name === 'Enviar por Gmail');
  assert.equal(gmail.type, 'n8n-nodes-base.gmail');
  assert.equal(gmail.parameters.options.appendAttribution, false);
  assert.ok(gmail.credentials.gmailOAuth2);
  assert.equal(wf.active, false);
});
