// Pruebas del flujo del boletín por correo: lib/boletin.js y los nodos «Decidir envío» y «Guardar estado», tal como
// los arma build.mjs. Ningún correo se manda: el nodo de Gmail no corre aquí (ver e2e-boletin.sh).

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { libSource, nodeCode, WORKFLOWS } from '../build.mjs';

const L = new Function(`${libSource('boletin')}\nreturn { parseRecipients, limaClock, pendingChanges, consolidate, changesHtml, relevantChanges, mime, encHeader, cleanSubs, decide, nextState };`)();
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
  assert.deepEqual(L.limaClock(Date.parse('2026-11-11T04:30:00Z')), { hour: 23, day: '2026-11-10', week: '2026-11-09' });
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
  // El asunto dice el cambio principal, no el estado de siempre.
  assert.equal(r.subject, '[Aviso] Tumbes sube de naranja a rojo (+1 cambio) · Boletín El Niño N° 6');
  assert.ok(r.html.includes('Tumbes sube de naranja a rojo.') && r.html.includes('Nuevo aviso amarillo en Loreto.'));
  assert.ok(!r.html.includes('ya enviado') && !r.html.includes('viejo'));
  assert.ok(r.html.indexOf('Tumbes') < r.html.indexOf('Loreto'), 'lo importante primero');
  assert.match(r.text, /^Qué cambió desde el último correo:\n- Tumbes sube/);
});

test('un correo de cambios no repite el boletín: sin el detalle ni el ENFEN si no cambió', () => {
  const html = '<p>x</p><!--cambios--><!--/cambios--><p>FRASE</p><!--enfen--><div>ENFEN</div><!--/enfen--><!--detalle--><div>MAPA y LOS 10</div><!--/detalle--><a>Ver el boletín completo</a><!--baja--><!--/baja-->';
  const base = { email: { subject: 'Boletín El Niño N° 6: 1 en rojo', text: 'TEXTO COMPLETO', html }, summary: 'Ahora hay 1 en rojo.' };
  const upd = L.decide(doc(6, [{ edition: 6, changes: [imm('Nuevo aviso rojo en Piura.')] }], base), CFG, { lastEdition: 5 }, NOW);
  assert.ok(upd.html.includes('FRASE') && upd.html.includes('Ver el boletín completo') && upd.html.includes('Nuevo aviso rojo en Piura.'));
  assert.ok(!upd.html.includes('MAPA') && !upd.html.includes('ENFEN'));
  assert.ok(!upd.text.includes('TEXTO COMPLETO') && upd.text.includes('Ahora: Ahora hay 1 en rojo.'));
  assert.ok(!/Importante:/.test(upd.html), 'si todos son importantes, la etiqueta no dice nada');
  // Si cambió el ENFEN, su recuadro va.
  const enfen = L.decide(doc(6, [{ edition: 6, changes: [{ rule: 'enfen-estado', tier: 'inmediata', from: 'A', to: 'B', text: 'El ENFEN cambió.' }] }], base), CFG, { lastEdition: 5 }, NOW);
  assert.ok(enfen.html.includes('ENFEN</div>') && !enfen.html.includes('MAPA'));
  // El primero va completo.
  const first = L.decide(doc(6, [{ edition: 6, changes: [] }], base), CFG, {}, NOW);
  assert.ok(first.html.includes('MAPA') && first.html.includes('ENFEN') && first.text === 'TEXTO COMPLETO');
});

test('los cambios entre dos correos se dicen netos, sin repetir ni contar lo que se deshizo', () => {
  const C = (edition, c) => ({ edition, changes: [c] });
  const ups = [
    C(2, { rule: 'departamento-sube', dep: '20', from: 1, rank: 3, tier: 'inmediata', text: 'Piura sube de amarillo a rojo: lluvias.' }),
    C(3, { rule: 'departamento-baja', dep: '20', from: 3, rank: 1, tier: 'resumen', text: 'Piura baja de rojo a amarillo.' }),
    C(4, { rule: 'departamento-sube', dep: '24', from: 1, rank: 2, tier: 'inmediata', text: 'Tumbes sube de amarillo a naranja.' }),
    C(5, { rule: 'departamento-sube', dep: '24', from: 2, rank: 3, tier: 'inmediata', text: 'Tumbes sube de naranja a rojo.' }),
    C(2, { rule: 'aviso-nuevo', key: 'k1', rank: 3, tier: 'inmediata', text: 'Nuevo aviso rojo: oleaje.' }),
    C(4, { rule: 'aviso-cancelado', key: 'k1', tier: 'inmediata', text: 'Cancelado: oleaje.' }),
    C(3, { rule: 'aviso-nuevo', key: 'k2', rank: 1, tier: 'resumen', text: 'Nuevo aviso amarillo: lluvias.' }),
    C(5, { rule: 'aviso-sube', key: 'k2', rank: 2, tier: 'inmediata', text: 'Sube a naranja: lluvias.' }),
    C(2, { rule: 'enfen-comunicado', tier: 'resumen', text: 'Comunicado N° 20.' }),
    C(3, { rule: 'enfen-comunicado', tier: 'resumen', text: 'Comunicado N° 21.' }),
    C(4, { rule: 'noaa-estado', from: 'El Niño', to: 'Neutral', tier: 'resumen', text: 'La NOAA pasó de «El Niño» a «Neutral».' }),
    C(5, { rule: 'noaa-estado', from: 'Neutral', to: 'El Niño', tier: 'resumen', text: 'La NOAA pasó de «Neutral» a «El Niño».' }),
    C(5, { rule: 'aviso-nuevo', tier: 'resumen', text: 'Texto viejo sin clave.' }),
    C(5, { rule: 'aviso-nuevo', tier: 'resumen', text: 'Texto viejo sin clave.' }),
  ];
  const d = doc(5, ups, { segments: [{ code: '20', name: 'Piura' }, { code: '24', name: 'Tumbes' }] });
  const texts = L.pendingChanges(d, 1).changes.map((c) => c.text);
  assert.deepEqual(texts, ['Tumbes sube de amarillo a rojo.', 'Sube a naranja: lluvias.', 'Comunicado N° 21.', 'Texto viejo sin clave.']);
  // Un cambio de estado del ENFEN ya trae su comunicado.
  const e = L.consolidate([{ rule: 'enfen-comunicado', tier: 'resumen', text: 'Comunicado' }, { rule: 'enfen-estado', from: 'A', to: 'B', tier: 'inmediata', text: 'Estado' }]);
  assert.deepEqual(e.map((c) => c.text), ['Estado']);
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
function runNode(name, { cfg, input, prior = {}, decided, list }) {
  const st = { ...prior };
  const $ = (n) => ({ first: () => ({ json: n === 'Configuración' ? cfg : n === 'Leer boletín' ? input : n === 'Leer suscripciones' ? list : decided }) });
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
  assert.equal(cfg.find((a) => a.name === 'use_list').value, false);
  assert.equal(cfg.find((a) => a.name === 'bcc').value, '');
  assert.deepEqual(wf.connections['¿Enviar?'].main[0], [{ node: 'Repartir correos', type: 'main', index: 0 }]);
  assert.deepEqual(wf.connections['¿Enviar?'].main[1], []);
  assert.deepEqual(wf.connections['Repartir correos'].main[0], [{ node: 'Enviar por Gmail', type: 'main', index: 0 }]);
  const gmail = wf.nodes.find((n) => n.name === 'Enviar por Gmail');
  // El nodo Gmail propio de n8n, sin la firma de n8n, con el HTML y la copia oculta de cada ítem.
  assert.equal(gmail.type, 'n8n-nodes-base.gmail');
  assert.equal(gmail.parameters.operation, 'send');
  assert.equal(gmail.parameters.emailType, 'html');
  assert.equal(gmail.parameters.message, '={{ $json.html }}');
  assert.equal(gmail.parameters.options.appendAttribution, false);
  assert.ok(gmail.credentials.gmailOAuth2);
  // La lista se lee con una credencial, nunca con un token escrito en el flujo.
  const list = wf.nodes.find((n) => n.name === 'Leer suscripciones');
  assert.ok(list.credentials.httpHeaderAuth);
  assert.ok(!JSON.stringify(wf).match(/Bearer [A-Za-z0-9]/));
  assert.equal(wf.nodes.find((n) => n.name === 'Guardar estado').executeOnce, true);
  assert.equal(wf.active, false);
  const conf = WORKFLOWS['enso-n8n-boletin-confirmar.json'];
  const hook = conf.nodes.find((n) => n.type === 'n8n-nodes-base.webhook');
  assert.equal(hook.parameters.authentication, 'headerAuth');
  assert.ok(hook.credentials.httpHeaderAuth);
});

const SUBS = [
  { email: 'Todo@x.pe', frecuencia: 'todo', deps: [], baja: 'https://s/#/boletin?baja=t1', bajaPost: 'https://s/api/boletin/baja?t=t1', preferencias: 'https://s/#/boletin?preferencias=p1' },
  { email: 'imp@x.pe', frecuencia: 'importantes', deps: [], baja: 'https://s/#/boletin?baja=t2', bajaPost: 'https://s/api/boletin/baja?t=t2', preferencias: 'https://s/#/boletin?preferencias=p2' },
  { email: 'piura@x.pe', frecuencia: 'todo', deps: ['20'], baja: 'https://s/#/boletin?baja=t3', bajaPost: 'https://s/api/boletin/baja?t=t3', preferencias: 'https://s/#/boletin?preferencias=p3' },
  { email: 'dia@x.pe', frecuencia: 'diario', deps: [], baja: 'https://s/#/boletin?baja=t4', bajaPost: 'https://s/api/boletin/baja?t=t4', preferencias: 'https://s/#/boletin?preferencias=p4' },
  { email: 'yo@example.com', frecuencia: 'todo', deps: [], baja: 'https://s/#/boletin?baja=t5', bajaPost: 'https://s/api/boletin/baja?t=t5', preferencias: 'https://s/#/boletin?preferencias=p5' },
  { email: 'mala', frecuencia: 'todo', baja: 'javascript:x', bajaPost: 'x' },
];
// Suscripciones que ya recibieron su bienvenida (con la edición 0: les toca todo lo que haya en «recent»).
// Para revisiones días después del corte del boletín de prueba.
const LATE = { ...CFG, to: '', max_age_hours: 1000 };
const KNOWN = { welcomed: Object.fromEntries(SUBS.map((s) => [String(s.email).toLowerCase(), 0])) };
const decode = (raw) => Buffer.from(raw.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8');
const part = (mail, type) => {
  const m = mail.match(new RegExp(`Content-Type: ${type}; charset=UTF-8\\r\\nContent-Transfer-Encoding: base64\\r\\n\\r\\n([\\s\\S]*?)\\r\\n--`));
  return Buffer.from(m[1].replace(/\r\n/g, ''), 'base64').toString('utf8');
};

test('un correo por suscripción, con su baja en un clic (RFC 8058) y su pie', () => {
  const d = doc(6, [{ edition: 6, changes: [{ ...imm('Tumbes sube a rojo.'), deps: ['24'] }] }], { segments: [{ code: '20', name: 'Piura' }, { code: '24', name: 'Tumbes' }], email: { subject: 'Boletín El Niño N° 6: 1 en rojo', text: 'texto', html: '<p>x</p><!--cambios--><!--/cambios--><!--baja-->genérico<!--/baja-->' } });
  const r = L.decide(d, CFG, { lastEdition: 5, ...KNOWN }, NOW, SUBS);
  const to = r.messages.map((m) => m.to);
  // La lista fija, «todo» e «importantes» (es un cambio importante); Piura no (el cambio es de Tumbes); «diario» espera
  // a su resumen (ya es la hora: sale como resumen diario); «yo@example.com» ya está en «to»; la inválida no.
  assert.deepEqual(to.sort(), ['dia@x.pe', 'imp@x.pe', 'todo@x.pe', 'yo@example.com'].sort());
  const m = r.messages.find((x) => x.to === 'todo@x.pe');
  const mail = decode(m.raw);
  assert.match(mail, /^To: todo@x\.pe\r\n/m);
  assert.match(mail, /List-Unsubscribe: <https:\/\/s\/api\/boletin\/baja\?t=t1>, <https:\/\/s\/#\/boletin\?baja=t1>/);
  assert.match(mail, /List-Unsubscribe-Post: List-Unsubscribe=One-Click/);
  assert.match(mail, /Subject: =\?UTF-8\?B\?/);
  const html = part(mail, 'text/html');
  assert.ok(html.includes('Darse de baja') && html.includes('preferencias=p1') && !html.includes('genérico'));
  assert.ok(html.includes('Tumbes sube a rojo.'));
  assert.match(part(mail, 'text/plain'), /Darse de baja: https:\/\/s\/#\/boletin\?baja=t1/);
  // La lista fija va con Bcc y sin enlaces personales.
  const list = decode(r.messages.find((x) => x.kind === 'lista').raw);
  assert.match(list, /^Bcc: a@x\.pe,b@y\.com\r\n/m);
  assert.ok(!list.includes('List-Unsubscribe:'));
  assert.equal(r.dailySent, true);
  assert.equal(r.mainSent, true);
});

test('«importantes» no recibe el resumen; quien eligió departamentos recibe solo los suyos y los del país', () => {
  const d = doc(6, [{ edition: 6, changes: [{ ...dig('Nuevo aviso amarillo en Piura.'), deps: ['20'] }, { rule: 'enfen-comunicado', tier: 'resumen', deps: [], text: 'Nuevo comunicado del ENFEN.' }] }], { segments: [{ code: '20', name: 'Piura' }] });
  const r = L.decide(d, { ...CFG, to: '' }, { lastEdition: 5, dailyEdition: 6, dailyDay: '2026-11-11', ...KNOWN }, NOW, SUBS);
  assert.deepEqual(r.messages.map((m) => m.to).sort(), ['piura@x.pe', 'todo@x.pe', 'yo@example.com']);
  assert.deepEqual(L.relevantChanges([{ deps: ['24'] }, { deps: [] }, { text: 'viejo' }], ['20']).length, 2);
});

test('la vía diaria tiene su propio puntero y un día', () => {
  const d = doc(8, [{ edition: 8, changes: [dig('a')] }, { edition: 7, changes: [imm('b')] }]);
  const early = L.decide(d, { ...CFG, to: '' }, { lastEdition: 8, dailyEdition: 6, ...KNOWN }, Date.parse('2026-11-11T10:00:00Z'), SUBS);
  assert.equal(early.messages.length, 0);
  const due = L.decide(d, { ...CFG, to: '' }, { lastEdition: 8, dailyEdition: 6, ...KNOWN }, NOW, SUBS);
  assert.deepEqual(due.messages.map((m) => m.to), ['dia@x.pe']);
  assert.equal(due.mainSent, false);
  assert.match(due.messages[0].subject, /^\[Resumen diario\]/);
  const st = L.nextState({ lastEdition: 8, dailyEdition: 6, ...KNOWN }, { ...due, at: NOW });
  assert.equal(st.lastEdition, 8);
  assert.equal(st.dailyEdition, 8);
  assert.equal(st.dailyDay, '2026-11-11');
  assert.equal(L.decide(d, { ...CFG, to: '' }, st, NOW + H, SUBS).messages.length, 0);
});

test('una suscripción nueva recibe el boletín completo en la revisión siguiente, y después solo lo posterior', () => {
  const ID = 'a'.repeat(32);
  const ana = { ...SUBS[0], id: ID, email: 'ana@x.pe', frecuencia: 'semanal' };
  const d = doc(6, [{ edition: 6, changes: [imm('Tumbes sube a rojo.')] }, { edition: 5, changes: [dig('viejo')] }]);
  // 3:00 en Lima, sin ediciones nuevas para la vía principal: igual sale la bienvenida, a cualquier hora.
  const at3 = Date.parse('2026-11-11T08:00:00Z');
  const r = L.decide(d, LATE, { lastEdition: 6, ...KNOWN }, at3, [...SUBS, ana]);
  assert.deepEqual(r.messages.map((m) => [m.to, m.kind]), [['ana@x.pe', 'Bienvenida']]);
  assert.equal(r.send, true);
  assert.equal(r.kind, 'Bienvenida');
  const html = part(decode(r.messages[0].raw), 'text/html');
  assert.match(html, /Bienvenida\.<\/strong> Este es el boletín completo de hoy\. Desde ahora le llegan un resumen a la semana/);
  assert.equal(r.messages[0].subject, 'Boletín El Niño N° 6: 1 en rojo, 0 en naranja');
  assert.equal(r.welcomed[ID], 6);
  assert.equal(r.welcomed['todo@x.pe'], 0);
  const st = L.nextState({ lastEdition: 6, ...KNOWN }, { ...r, at: at3 });
  assert.equal(st.welcomed[ID], 6);
  // La hora siguiente ya no es nueva: nada.
  assert.equal(L.decide(d, LATE, st, at3 + H, [...SUBS, ana]).messages.length, 0);
  // Su resumen semanal no repite lo que ya estaba en la bienvenida: con la N° 7 recibe solo lo de la N° 7.
  const d7 = doc(7, [{ edition: 7, changes: [dig('Nuevo aviso amarillo en Loreto.')] }, ...d.recent]);
  const monday = Date.parse('2026-11-16T13:00:00Z'); // lunes, 8:00 en Lima
  const w = L.decide(d7, LATE, { ...st, lastEdition: 7, dailyDay: '2026-11-16' }, monday, [...SUBS, ana]);
  const m = w.messages.find((x) => x.to === 'ana@x.pe');
  assert.match(m.subject, /^\[Resumen semanal\] Nuevo aviso amarillo en Loreto · Boletín El Niño N° 7$/);
  // Una baja sale de «welcomed»; sin la lista (use_list apagado) «welcomed» no se toca.
  assert.deepEqual(Object.keys(L.decide(d7, LATE, st, at3, [ana]).welcomed), [ID]);
  assert.equal(L.decide(d7, CFG, st, NOW).welcomed, null);
});

test('la vía semanal: el lunes a la hora del resumen, una vez por semana, con su propio puntero', () => {
  const sem = [{ ...SUBS[0], email: 'sem@x.pe', frecuencia: 'semanal' }];
  const known = { welcomed: { 'sem@x.pe': 0 } };
  const d = doc(9, [{ edition: 9, changes: [imm('Piura sube a rojo.')] }, { edition: 8, changes: [dig('a')] }]);
  // Un aviso importante el miércoles no le llega a «semanal».
  assert.equal(L.decide(d, LATE, { lastEdition: 8, weeklyEdition: 8, weeklyWeek: '2026-11-09', ...known }, NOW, sem).messages.length, 0);
  assert.equal(L.limaClock(NOW).week, '2026-11-09');
  assert.equal(L.limaClock(Date.parse('2026-11-16T04:00:00Z')).week, '2026-11-09'); // domingo 23:00 en Lima
  const early = Date.parse('2026-11-16T11:00:00Z'); // lunes 6:00 en Lima
  assert.equal(L.decide(d, LATE, { lastEdition: 9, weeklyEdition: 7, weeklyWeek: '2026-11-09', ...known }, early, sem).messages.length, 0);
  const due = L.decide(d, LATE, { lastEdition: 9, weeklyEdition: 7, weeklyWeek: '2026-11-09', ...known }, early + 2 * H, sem);
  assert.deepEqual(due.messages.map((m) => m.to), ['sem@x.pe']);
  assert.match(due.messages[0].subject, /^\[Resumen semanal\] Piura sube a rojo \(\+1 cambio\)/);
  const st = L.nextState({ lastEdition: 9, weeklyEdition: 7, ...known }, { ...due, at: early + 2 * H });
  assert.equal(st.weeklyEdition, 9);
  assert.equal(st.weeklyWeek, '2026-11-16');
  assert.equal(st.lastEdition, 9);
  // El resto de la semana, nada aunque haya ediciones nuevas.
  const d10 = doc(10, [{ edition: 10, changes: [imm('Lima sube a rojo.')] }, ...d.recent]);
  assert.equal(L.decide(d10, LATE, { ...st, lastEdition: 10 }, early + 30 * H, sem).messages.length, 0);
  assert.deepEqual(L.cleanSubs([{ ...sem[0], frecuencia: 'semanal' }, { ...SUBS[1], frecuencia: 'mensual' }]).map((s) => s.frecuencia), ['semanal', 'todo']);
});

test('las cabeceras no admiten saltos de línea (inyección de cabeceras)', () => {
  const mail = decode(L.mime({ to: 'a@b.pe', subject: 'Hola\r\nBcc: victima@x.pe', html: '<p>x</p>', text: 'x' }));
  assert.ok(!/^Bcc:/m.test(mail));
  assert.equal(L.encHeader('Año\nnuevo').includes('\n '), false);
});

test('«Repartir correos» da al nodo Gmail un ítem por correo, con su HTML personal', async () => {
  const d = doc(6, [{ edition: 6, changes: [imm('Tumbes sube a rojo.')] }], { email: { subject: 'B', text: 't', html: '<p>x</p><!--cambios--><!--/cambios--><!--baja--><!--/baja-->' } });
  const decided = L.decide(d, CFG, { lastEdition: 5, ...KNOWN }, NOW, SUBS);
  const { out } = await runNode('boletin-repartir', { cfg: { sender_name: 'Obs' }, decided });
  const lista = out.find((o) => o.json.kind === 'lista').json;
  assert.equal(lista.to, 'yo@example.com');
  assert.equal(lista.bcc, 'a@x.pe,b@y.com');
  const todo = out.find((o) => o.json.to === 'todo@x.pe').json;
  assert.ok(todo.html.includes('baja=t1') && todo.html.includes('Tumbes sube a rojo.'));
  assert.equal(todo.bcc, '');
  assert.equal(todo.senderName, 'Obs');
  assert.ok(!('raw' in todo));
});

test('el nodo de confirmación arma un correo para una sola dirección válida', async () => {
  const cfg = { sender_name: 'Observatorio' };
  const ok = await runNode('boletin-confirmar', { cfg, input: { body: { to: 'ANA@x.pe', subject: 'Confirme\r\nBcc: x@y.pe', html: '<p>hola</p>', text: 'hola' } } });
  assert.deepEqual(ok.out[0].json, { to: 'ana@x.pe', bcc: '', subject: 'Confirme Bcc: x@y.pe', html: '<p>hola</p>', senderName: 'Observatorio' });
  await assert.rejects(runNode('boletin-confirmar', { cfg, input: { body: { to: 'a@x.pe, b@x.pe', subject: 's', html: 'h' } } }), /inválido/);
});
