// Pruebas de las bibliotecas que corren dentro de los nodos Code de n8n.
// Se evalúan tal como las arma build.mjs (sin la línea de exportación), así
// que si algo depende de una global que el nodo no tiene, falla aquí.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash, randomBytes } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { libSource, nodeCode } from '../build.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIX = join(HERE, '..', '..', 'python', 'tests', 'fixtures');

function load(...names) {
  return loadWith({}, ...names);
}

/** Como en el nodo Code de n8n 1.x: sin TextEncoder ni TextDecoder. */
function loadBare(...names) {
  return loadWith({ TextEncoder: undefined, TextDecoder: undefined }, ...names);
}

function loadWith(shadow, ...names) {
  const exportsList = {
    hash: ['sha256Hex', 'sha1Hex', 'gitBlobSha', 'toBase64'],
    classify: ['classify', 'reachClass', 'detectFormat', 'feedStats', 'fileExtension', 'utf8Decode', 'utf8Encode'],
    enfen: ['deriveEnfenTargets', 'parseListing', 'parseWpPosts', 'cleanWpdm'],
    relay: ['buildSnapshot', 'pickResults', 'heartbeat', 'parseTokenExpiry'],
  };
  const code = names.map(libSource).join('\n');
  const all = names.flatMap((n) => exportsList[n]);
  return new Function(...Object.keys(shadow), `${code}\nreturn { ${all.join(', ')} };`)(...Object.values(shadow));
}

const { sha256Hex, sha1Hex, gitBlobSha, toBase64 } = load('hash');
const { classify, reachClass, detectFormat, fileExtension } = load('classify');
const { deriveEnfenTargets, parseListing, cleanWpdm } = load('enfen');
const { buildSnapshot, heartbeat, parseTokenExpiry } = load('hash', 'classify', 'relay');

const enc = (s) => new TextEncoder().encode(s);

test('sha256 y sha1 coinciden con node:crypto en los bordes de bloque', () => {
  for (const n of [0, 1, 55, 56, 63, 64, 65, 119, 120, 1000, 70000]) {
    const b = randomBytes(n);
    assert.equal(sha256Hex(b), createHash('sha256').update(b).digest('hex'), `sha256 ${n}`);
    assert.equal(sha1Hex(b), createHash('sha1').update(b).digest('hex'), `sha1 ${n}`);
  }
});

test('el SHA de blob es el de git', () => {
  assert.equal(gitBlobSha(enc('hello\n')), 'ce013625030ba8dba906f756967f9e9ca394464a');
  assert.equal(gitBlobSha(new Uint8Array(0)), 'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391');
});

test('los feeds reales capturados se reconocen como feeds con entradas', () => {
  const dir = join(FIX, 'news-probe');
  let n = 0;
  for (const f of readdirSync(dir).filter((x) => x.endsWith('.xml'))) {
    const body = readFileSync(join(dir, f));
    const c = classify({ url: f, expect: 'feed', status: 200, headers: { 'content-type': 'application/rss+xml' }, body });
    assert.equal(c.verdict, 'ok', `${f}: ${c.verdict} ${c.note}`);
    assert.ok(c.items > 0, f);
    n++;
  }
  assert.ok(n > 100);
});

test('los textos de la NOAA y el PDF del ENFEN pasan como texto y PDF', () => {
  const txt = readFileSync(join(FIX, 'sources', 'cpc-oni.txt'));
  assert.equal(classify({ url: 'x', expect: 'text', status: 200, body: txt }).verdict, 'ok');
  const pdfDir = join(FIX, 'live-run', 'raw', 'enfen-comunicados');
  const pdf = readFileSync(join(pdfDir, readdirSync(pdfDir).find((f) => f.endsWith('.pdf'))));
  const c = classify({ url: 'x', expect: 'pdf', status: 200, headers: { 'content-type': 'application/force-download' }, body: pdf });
  assert.equal(c.verdict, 'ok');
  assert.equal(fileExtension(c.detected), 'pdf');
});

test('una página de verificación en lugar de un PDF es un bloqueo, no «sin datos»', () => {
  const page = '<!DOCTYPE html><html><head><title>Verificación de seguridad</title></head><body><div class="g-recaptcha"></div></body></html>';
  const c = classify({ url: 'https://www.dhn.mil.pe/x.pdf', expect: 'pdf', status: 200, headers: { 'content-type': 'text/html' }, body: enc(page) });
  assert.equal(c.verdict, 'blocked');
  assert.equal(c.block, 'human-verification');
  assert.equal(c.ok, false);
});

test('desafíos y bloqueos conocidos', () => {
  const cases = [
    [{ status: 403, headers: { server: 'cloudflare', 'cf-mitigated': 'challenge' }, body: '<html><title>Just a moment...</title></html>' }, 'blocked', 'cloudflare-challenge'],
    [{ status: 403, body: '<html>Access Denied</html>' }, 'blocked', 'http-403'],
    [{ status: 429, body: '' }, 'blocked', 'rate-limit'],
    [{ status: 202, body: '<html><script src="/awswaf/challenge.js"></script></html>' }, 'blocked', 'aws-waf'],
    [{ status: 202, body: '' }, 'blocked', 'bot-202'],
    [{ status: 200, body: '<html><body>Request unsuccessful. Incapsula incident ID: 1</body></html>' }, 'blocked', 'imperva'],
    [{ status: 503, body: 'Service Unavailable' }, 'server_error', null],
    [{ status: 404, body: 'no' }, 'not_found', null],
  ];
  for (const [r, verdict, block] of cases) {
    const c = classify({ url: 'u', expect: 'feed', ...r, body: enc(r.body) });
    assert.equal(c.verdict, verdict, JSON.stringify(r));
    assert.equal(c.block, block, JSON.stringify(r));
  }
});

test('errores de red de n8n (axios) y de Node (undici)', () => {
  const cases = [
    ['getaddrinfo ENOTFOUND enfen.imarpe.gob.pe', 'dns', false],
    ['timeout of 40000ms exceeded', 'timeout', true],
    ['UND_ERR_CONNECT_TIMEOUT: Connect Timeout Error', 'timeout', true],
    ['read ECONNRESET', 'connection', true],
    ['Client network socket disconnected before secure TLS connection was established', 'connection', true],
    ['UNABLE_TO_VERIFY_LEAF_SIGNATURE: unable to verify the first certificate', 'tls', false],
  ];
  for (const [error, verdict, transient] of cases) {
    const c = classify({ url: 'u', expect: 'html', error });
    assert.equal(c.verdict, verdict, error);
    assert.equal(c.transient, transient, error);
  }
  // Un proxy de salida que no resuelve el nombre responde 502 «upstream dial failed».
  assert.equal(classify({ url: 'u', status: 502, body: enc('upstream dial failed') }).verdict, 'dns');
});

test('un feed que llega como HTML o vacío no pasa', () => {
  assert.equal(classify({ url: 'u', expect: 'feed', status: 200, body: enc('<!doctype html><html>' + 'x'.repeat(5000)) }).verdict, 'wrong_type');
  assert.equal(classify({ url: 'u', expect: 'feed', status: 200, body: enc('<?xml version="1.0"?><rss><channel><title>t</title></channel></rss>') }).verdict, 'empty');
  assert.equal(classify({ url: 'u', expect: 'feed', status: 200, body: new Uint8Array(0) }).verdict, 'empty');
});

test('detecta el formato sin fiarse del Content-Type', () => {
  assert.equal(detectFormat(enc('﻿<?xml version="1.0"?><rss version="2.0">'), 'text/html'), 'rss');
  assert.equal(detectFormat(enc('<feed xmlns="http://www.w3.org/2005/Atom">'), ''), 'atom');
  assert.equal(detectFormat(enc('[{"id":1}]'), 'text/html'), 'json');
  assert.equal(detectFormat(enc(' SEAS  YR   TOTAL   ANOM'), 'text/plain'), 'text');
});

test('PDF del ENFEN deducidos de los listados reales', () => {
  const dhn = readFileSync(join(FIX, 'sources', 'dhn-comunicados-enfen.html'), 'utf8');
  const items = parseListing(dhn);
  assert.ok(items.length > 5);
  const urls = deriveEnfenTargets([{ url: 'dhn', text: dhn }], new Date('2026-10-20T00:00:00Z'));
  const top = items.filter((i) => i.kind === 'oficial').sort((a, b) => b.year - a.year || b.number - a.number)[0];
  const pad = (n) => String(n).padStart(2, '0');
  assert.ok(urls.includes(`https://www.dhn.mil.pe/Archivos/oceanografia/enfen/comunicado-oficial/${pad(top.number)}-${top.year}.pdf`));
  assert.ok(urls.includes(`https://www.dhn.mil.pe/Archivos/oceanografia/enfen/comunicado-oficial/${pad(top.number + 2)}-${top.year}.pdf`));
  assert.equal(new Set(urls).size, urls.length);
});

test('enlaces de descarga del ENFEN sin el token «refresh» y n.º 01 en enero', () => {
  const html = '<a href="https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-18-2026/?wpdmdl=2165&amp;refresh=6ad7">x</a>';
  assert.equal(cleanWpdm('https://e/x/?wpdmdl=2165&amp;refresh=6ad7'), 'https://e/x/?wpdmdl=2165');
  const urls = deriveEnfenTargets([{ url: 'c', text: html }], new Date('2027-01-05T00:00:00Z'));
  assert.equal(urls[0], 'https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-18-2026/?wpdmdl=2165');
  assert.ok(urls.includes('https://www.dhn.mil.pe/Archivos/oceanografia/enfen/comunicado-oficial/01-2027.pdf'));
});

test('desde la API de WordPress se usa el enlace de descarga de la entrada', () => {
  const posts = JSON.stringify([
    { title: { rendered: 'Comunicado Oficial ENFEN N° 18-2026' }, link: 'https://enfen.imarpe.gob.pe/2026/10/10/comunicado-18/',
      content: { rendered: '<p>Comunicado oficial</p><a href="https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-18-2026/?wpdmdl=2165&#038;refresh=ab">PDF</a>' } },
    { title: { rendered: 'Comunicado Oficial ENFEN N° 17-2026' }, link: 'https://enfen.imarpe.gob.pe/2026/09/26/comunicado-17/', content: { rendered: '<p>sin enlace</p>' } },
  ]);
  const urls = deriveEnfenTargets([{ url: 'wp', text: posts }], new Date('2026-10-20T00:00:00Z'));
  assert.equal(urls[0], 'https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-18-2026/?wpdmdl=2165');
  assert.ok(urls.includes('https://enfen.imarpe.gob.pe/2026/09/26/comunicado-17/'));
});

function res(url, ok, body, extra = {}) {
  const cls = ok
    ? classify({ url, expect: 'any', status: 200, headers: { 'content-type': 'text/plain' }, body: enc(body) })
    : classify({ url, expect: 'any', error: 'read ECONNRESET' });
  return { id: url, url, group: 'g', fetched_at: '2026-10-21T03:50:00+00:00', pass: 1, cls, body: ok ? enc(body) : null, ...extra };
}

test('la copia guarda los cuerpos válidos y publica index.json aunque todo falle', () => {
  const now = new Date('2026-10-21T03:55:00Z');
  const a = buildSnapshot({ results: [res('u1', true, 'uno'), res('u2', false)], previous: null, now, collector: { kind: 'n8n' } });
  assert.equal(a.index.schema, 'enso-relay/1');
  assert.equal(a.files.length, 1);
  const e1 = a.index.entries.find((e) => e.url === 'u1');
  assert.equal(e1.file, `files/${sha256Hex(enc('uno')).slice(0, 16)}.txt`);
  assert.equal(e1.git_blob, gitBlobSha(enc('uno')));
  assert.equal(a.index.entries.find((e) => e.url === 'u2').file, undefined);
  assert.deepEqual(a.index.summary, { g: '1/2' });
  const none = buildSnapshot({ results: [res('u2', false)], previous: null, now, collector: {} });
  assert.equal(none.files.length, 0);
  assert.equal(none.index.entries.length, 1);
});

test('reutiliza archivos sin cambios y conserva la última copia válida unas horas', () => {
  const t0 = new Date('2026-10-20T03:55:00Z');
  const first = buildSnapshot({ results: [res('u1', true, 'uno'), res('u2', true, 'dos')], previous: null, now: t0, collector: {} });
  const prev = JSON.parse(JSON.stringify(first.index));
  const t1 = new Date('2026-10-21T03:55:00Z');
  const second = buildSnapshot({ results: [res('u1', true, 'uno'), res('u2', false)], previous: prev, now: t1, collector: {} });
  assert.ok(second.files.every((f) => f.body === null), 'nada nuevo que subir');
  const carried = second.index.entries.find((e) => e.url === 'u2');
  assert.equal(carried.carried, true);
  assert.equal(carried.last_attempt.verdict, 'connection');
  assert.equal(carried.fetched_at, prev.entries.find((e) => e.url === 'u2').fetched_at);
  const later = buildSnapshot({ results: [res('u2', false)], previous: second.index, now: new Date('2026-10-24T12:00:00Z'), collector: {} });
  assert.equal(later.index.entries[0].carried, undefined, 'pasadas las 72 h no se conserva');
});

test('si una URL se reintentó, vale el intento que funcionó', () => {
  const r1 = res('u', false);
  const r2 = { ...res('u', true, 'ok'), pass: 2 };
  const s = buildSnapshot({ results: [r1, r2], previous: null, now: new Date(), collector: {} });
  assert.equal(s.index.entries.length, 1);
  assert.equal(s.index.entries[0].verdict, 'ok');
  assert.equal(s.index.entries[0].pass, 2);
});

test('clases de alcance iguales a las del registro (python/enso/reach.py)', () => {
  const c = (r) => classify({ url: 'u', expect: 'rss', ...r, body: r.body === undefined ? undefined : enc(r.body) }).reach;
  assert.equal(c({ status: 200, body: '<rss><channel><item><title>a</title></item></channel></rss>' }), 'ok');
  assert.equal(c({ status: 403, body: 'no' }), 'http-403');
  assert.equal(c({ status: 403, headers: { 'cf-mitigated': 'challenge' }, body: '' }), 'challenge');
  assert.equal(c({ status: 200, body: '<html><title>Verificación de seguridad</title></html>' }), 'challenge');
  assert.equal(c({ status: 404, body: '' }), 'http-4xx');
  assert.equal(c({ status: 502, body: 'bad gateway' }), 'http-5xx');
  assert.equal(c({ error: 'read ECONNRESET' }), 'connect');
  assert.equal(c({ error: 'getaddrinfo ENOTFOUND x' }), 'dns');
  assert.equal(c({ status: 200, body: '<!doctype html><html>' + 'x'.repeat(900) }), 'empty');
  assert.ok(reachClass({ verdict: 'wrong_type' }) === 'empty');
});

test('mismas clases de alcance que python/enso/reach.py (tabla compartida)', () => {
  // La misma tabla corre en python/tests/test_reach_parity.py con enso.reach.judge. «n8n»: la clase que da hoy
  // classify.js donde aún difiere («n8n_fix» dice el cambio que falta); al corregirlo, quitar «n8n» de la fila.
  const { cases } = JSON.parse(readFileSync(join(FIX, 'reach-parity.json'), 'utf8'));
  assert.ok(cases.length >= 50);
  for (const row of cases) {
    const text = (row.body || '') + 'x'.repeat(row.pad || 0);
    const body = row.body_file ? readFileSync(join(FIX, row.body_file))
      : row.encoding === 'latin-1' ? new Uint8Array(Buffer.from(text, 'latin1')) : enc(text);
    const c = classify({ url: 'u', expect: row.expect, status: row.status, headers: row.headers || {}, body });
    assert.equal(c.reach, row.n8n || row.reach, `${row.name}: ${c.verdict} ${c.block || ''} ${c.note}`);
  }
});

test('el latido dice «sin-fuentes» cuando nada respondió en esta corrida', () => {
  const now = new Date('2026-10-21T03:55:00Z');
  const ok = buildSnapshot({ results: [res('u1', true, 'uno'), res('u2', false)], previous: null, now, collector: { kind: 'n8n' } });
  const hb = heartbeat(ok.index, now);
  assert.equal(hb.schema, 'enso-relay-heartbeat/1');
  assert.equal(hb.result, 'ok');
  assert.equal(hb.reachable, '1/2');
  assert.equal(hb.failures[0].verdict, 'connection');
  const down = buildSnapshot({ results: [res('u1', false)], previous: ok.index, now: new Date('2026-10-21T15:55:00Z'), collector: {} });
  assert.equal(down.index.entries[0].carried, true);
  assert.equal(heartbeat(down.index, now).result, 'sin-fuentes');
});

test('sin TextEncoder/TextDecoder (n8n 1.x) se decodifica y codifica igual', () => {
  const bare = loadBare('hash', 'classify');
  const samples = ['', 'ascii', 'Verificación de seguridad — ñandú 🌊', '\u00ff\u0100\uffff'];
  for (const s of samples) {
    const b = new TextEncoder().encode(s);
    assert.deepEqual(bare.utf8Encode(s), b, s);
    assert.equal(bare.utf8Decode(b), s, s);
  }
  assert.equal(bare.utf8Decode(new Uint8Array([0x61, 0xff, 0x62])), 'a\ufffdb');
  const feed = readFileSync(join(FIX, 'news-probe', 'andina.xml'));
  assert.equal(bare.classify({ url: 'u', expect: 'rss', status: 200, body: new Uint8Array(feed) }).verdict, 'ok');
  assert.equal(bare.gitBlobSha(enc('hello\n')), 'ce013625030ba8dba906f756967f9e9ca394464a');
  for (const n of [0, 1, 2, 3, 4, 5, 1000, 70001]) {
    const b = randomBytes(n);
    assert.equal(toBase64(b), b.toString('base64'), `base64 ${n}`);
  }
});

test('si el registro espera HTML y llega texto, se guarda con una nota', () => {
  const txt = readFileSync(join(FIX, 'sources', 'cpc-sstoi.indices'));
  const c = classify({ url: 'u', expect: 'html', status: 200, headers: { 'content-type': 'text/plain' }, body: txt });
  assert.equal(c.verdict, 'ok');
  assert.match(c.note, /esperaba HTML/);
});

async function runCode(name, vars, nodes, input = []) {
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  const $ = (n) => { if (!(n in nodes)) throw new Error(`nodo sin ejecutar: ${n}`); return { first: () => nodes[n][0], all: () => nodes[n] }; };
  const fn = new AsyncFunction('$', '$input', nodeCode(name, { VERSION: 'test', ...vars }));
  return fn.call({ helpers: {} }, $, { all: () => input, first: () => input[0] });
}

test('Fuentes: respeta robots.txt y el alcance «n8n»', async () => {
  const reg = { schema: 'enso-source-registry/1', sources: [
    { id: 'a', group: 'g', url: 'https://a/', alt_urls: ['https://a2/'], expect: 'rss', channels: ['actions', 'n8n'] },
    { id: 'p', group: 'g', url: 'https://p/', expect: 'html', channels: ['peru-server'] },
    { id: 'r', group: 'g', url: 'https://r/', expect: 'json', channels: [], geoblock: { status: 'robots-disallowed' } },
  ] };
  const cfg = (scope) => ({ 'Configuración': [{ json: { scope, only: '' } }] });
  const n8n = await runCode('fuentes', { REGISTRY: JSON.stringify(reg) }, cfg('n8n'));
  assert.deepEqual(n8n.map((i) => i.json.url), ['https://a/', 'https://a2/']);
  const todas = await runCode('fuentes', { REGISTRY: JSON.stringify(reg) }, cfg('todas'));
  assert.deepEqual(todas.map((i) => i.json.id), ['a', 'a#2', 'p']);
  // El registro leído de GitHub (cuerpo en «data») gana sobre el incluido.
  const fromGh = await runCode('fuentes', { REGISTRY: JSON.stringify(reg) }, {
    ...cfg('n8n'), 'Leer registro': [{ json: { statusCode: 200, data: JSON.stringify({ ...reg, sources: [reg.sources[0]] }).replace('https://a2/', 'https://b/') } }],
  });
  assert.deepEqual(fromGh.map((i) => i.json.url), ['https://a/', 'https://b/']);
  assert.match(fromGh[0].json.registry, /^GitHub/);
  // Sin fuentes seleccionadas la corrida falla en vez de terminar sin hacer nada.
  await assert.rejects(runCode('fuentes', { REGISTRY: JSON.stringify(reg) }, { 'Configuración': [{ json: { scope: 'n8n', only: 'no-existe' } }] }), /Ninguna fuente/);
});

test('Fuentes: con alcance «n8n» omite las URL que el registro asigna a otros canales', async () => {
  const reg = { schema: 'enso-source-registry/1', sources: [
    { id: 'e', group: 'enfen', url: 'https://portal/api', alt_urls: ['https://dhn/listado'], alt_expect: ['html'], expect: 'json', channels: ['n8n', 'peru-server'],
      by_url: { 'https://portal/api': { status: 'suspected-geoblock', channels: ['peru-server'] }, 'https://dhn/listado': { status: 'open', channels: ['n8n'] } } },
  ] };
  const cfg = (scope) => ({ 'Configuración': [{ json: { scope, only: '' } }] });
  assert.deepEqual((await runCode('fuentes', { REGISTRY: JSON.stringify(reg) }, cfg('n8n'))).map((i) => i.json.url), ['https://dhn/listado']);
  assert.deepEqual((await runCode('fuentes', { REGISTRY: JSON.stringify(reg) }, cfg('todas'))).map((i) => i.json.url), ['https://portal/api', 'https://dhn/listado']);
  // robots.txt por URL: se salta la URL prohibida, no las demás de la fuente.
  const robots = { schema: 'enso-source-registry/1', sources: [
    { id: 'r', group: 'g', url: 'https://x/api/', alt_urls: ['https://x/listado'], expect: 'json', channels: [], geoblock: { status: 'robots-disallowed' },
      by_url: { 'https://x/api/': { status: 'robots-disallowed', channels: [] }, 'https://x/listado': { status: 'open', channels: ['actions', 'n8n'] } } },
  ] };
  assert.deepEqual((await runCode('fuentes', { REGISTRY: JSON.stringify(robots) }, cfg('todas'))).map((i) => i.json.url), ['https://x/listado']);
  // Feeds que el pipeline lee como lector (robots.txt en contra): nunca desde n8n.
  const reader = { schema: 'enso-source-registry/1', sources: [
    { id: 'gn', group: 'g', url: 'https://news.google/rss', alt_urls: ['https://feed/ok'], expect: 'rss', channels: ['actions', 'n8n'],
      by_url: { 'https://news.google/rss': { status: 'robots-disallowed', channels: ['actions'], reader: true }, 'https://feed/ok': { status: 'open', channels: ['actions', 'n8n'] } } },
    { id: 'r2', group: 'g', url: 'https://reader-only/rss', expect: 'rss', channels: ['actions'], by_url: { 'https://reader-only/rss': { status: 'open', channels: ['actions', 'n8n'], reader: true } } },
  ] };
  for (const scope of ['n8n', 'todas']) {
    assert.deepEqual((await runCode('fuentes', { REGISTRY: JSON.stringify(reader) }, cfg(scope))).map((i) => i.json.url), ['https://feed/ok'], scope);
  }
});

test('Fuentes: no pide lo que robots.txt no permite ni aquello cuyo robots.txt nadie pudo leer', async () => {
  // Revisión del 22 de octubre de 2026 (gap 1): el feed del INDECI y el SNIRH del ANA se pedían sin que nadie
  // hubiera leído su robots.txt; el repositorio del IMARPE no va por n8n (no verifica su certificado).
  const reg = { schema: 'enso-source-registry/1', sources: [
    { id: 'm', group: 'g', url: 'https://ok/feed', alt_urls: ['https://sin-leer/feed', 'https://prohibe/feed', 'https://antes/feed'],
      expect: 'rss', channels: ['actions', 'n8n', 'peru-server'],
      by_url: {
        'https://ok/feed': { status: 'open', channels: ['actions', 'n8n'], robots: 'allowed' },
        'https://sin-leer/feed': { status: 'down', channels: ['actions', 'n8n'], robots: 'unknown' },
        'https://prohibe/feed': { status: 'open', channels: ['actions', 'n8n'], robots: 'disallowed' },
        'https://antes/feed': { status: 'open', channels: ['actions', 'n8n'] }, // registro anterior, sin «robots»
      } },
    { id: 'ana', group: 'ana', url: 'https://snirh/', expect: 'html', channels: ['peru-server'],
      by_url: { 'https://snirh/': { status: 'suspected-geoblock', channels: ['peru-server'], robots: 'unknown' } } },
    { id: 'repo', group: 'imarpe', url: 'https://repo/api', expect: 'json', channels: ['actions'], n8n: false,
      by_url: { 'https://repo/api': { status: 'open', channels: ['actions'], robots: 'allowed' } } },
  ] };
  const cfg = (scope) => ({ 'Configuración': [{ json: { scope, only: '' } }] });
  const urls = async (scope) => (await runCode('fuentes', { REGISTRY: JSON.stringify(reg) }, cfg(scope))).map((i) => i.json.url);
  assert.deepEqual(await urls('n8n'), ['https://ok/feed', 'https://antes/feed']);
  // El repositorio del IMARPE tampoco en la validación: su «tls» desde n8n no es una medición de la red.
  assert.deepEqual(await urls('todas'), ['https://ok/feed', 'https://antes/feed']);
});

test('Preparar copia: no publica si no pudo leer la copia anterior', async () => {
  const nodes = (prev) => ({ 'Configuración': [{ json: { data_branch: 'data-n8n', carry_hours: 72, max_file_mb: 8 } }], 'Leer copia anterior': [{ json: prev }], Fuentes: [{ json: { registry: 'GitHub x@main (2026-10-21)' } }] });
  await assert.rejects(runCode('preparar', {}, nodes({ statusCode: 500, data: '' })), /no se publica/);
  await assert.rejects(runCode('preparar', {}, nodes({ error: { message: 'ECONNRESET' } })), /ECONNRESET/);
  const first = await runCode('preparar', {}, nodes({ statusCode: 404, data: '' }));
  const idx = first.find((i) => i.json.path === 'index.json');
  assert.ok(idx);
  assert.match(Buffer.from(idx.json.content, 'base64').toString(), /"registry": "GitHub x@main/);
  assert.equal(JSON.parse(Buffer.from(idx.json.content, 'base64').toString()).collector.token_expires_at, null);
  // El vencimiento del token (cabecera de GitHub en «Leer registro») queda en index.json y en el latido.
  const withToken = await runCode('preparar', {}, { ...nodes({ statusCode: 404, data: '' }),
    'Leer registro': [{ json: { statusCode: 200, headers: { 'github-authentication-token-expiration': '2026-11-01 00:00:00 UTC' } } }] });
  for (const path of ['index.json', 'heartbeat.json']) {
    const f = withToken.find((i) => i.json.path === path);
    assert.equal(JSON.parse(Buffer.from(f.json.content, 'base64').toString()).collector.token_expires_at, '2026-11-01T00:00:00+00:00', path);
  }
});

test('vencimiento del token de GitHub, como collector_service.parse_token_expiry', () => {
  assert.equal(parseTokenExpiry('2027-05-10 00:00:00 UTC'), '2027-05-10T00:00:00+00:00');
  assert.equal(parseTokenExpiry('2027-05-09 19:00:00 -0500'), '2027-05-10T00:00:00+00:00');
  assert.equal(parseTokenExpiry('2027-05-09 19:00 -05:00'), '2027-05-10T00:00:00+00:00');
  assert.equal(parseTokenExpiry(undefined), null);
  assert.equal(parseTokenExpiry('nunca'), null);
});

test('Fuentes: una alternativa con otra terminación no hereda el tipo esperado', async () => {
  const reg = { schema: 'enso-source-registry/1', sources: [
    { id: 'icen', group: 'g', url: 'http://x/ICEN.txt', alt_urls: ['https://x/ICEN.txt'], expect: 'text', channels: ['n8n'] },
    { id: 'wp', group: 'g', url: 'https://e/wp-json/wp/v2/posts?search=c', alt_urls: ['https://e/comunicados/'], expect: 'json', channels: ['n8n'] },
  ] };
  const out = await runCode('fuentes', { REGISTRY: JSON.stringify(reg) }, { 'Configuración': [{ json: { scope: 'n8n', only: '' } }] });
  assert.deepEqual(out.map((i) => i.json.expect), ['text', 'text', 'json', 'any']);
  reg.sources[1].alt_expect = ['html'];
  const withAlt = await runCode('fuentes', { REGISTRY: JSON.stringify(reg) }, { 'Configuración': [{ json: { scope: 'n8n', only: '' } }] });
  assert.equal(withAlt[3].json.expect, 'html');
});

test('Vigilante: falla si el sitio está viejo o no responde', async () => {
  const cfg = { 'Configuración': [{ json: { site: 'https://s/', max_age_hours: 30 } }] };
  const ok = await runCode('vigilante', {}, cfg, [{ json: { statusCode: 200, data: JSON.stringify({ generatedAt: new Date().toISOString(), publicationId: 'x' }) } }]);
  assert.equal(ok[0].json.resultado, 'Sitio al día');
  await assert.rejects(runCode('vigilante', {}, cfg, [{ json: { statusCode: 200, data: '{"generatedAt":"2026-08-09T06:04:07+00:00"}' } }]), /desactualizado/);
  await assert.rejects(runCode('vigilante', {}, cfg, [{ json: { statusCode: 404, data: '' } }]), /no responde/);
});

test('Vigilante: revisa el sitio de Cloudflare, o el de N8N_SITE_URL al construir', () => {
  const site = (env) => {
    const r = spawnSync(process.execPath, ['--input-type=module', '-e',
      "const m = await import(process.argv[1]); const w = m.WORKFLOWS['enso-n8n-vigilante.json']; console.log(w.nodes.find((n) => n.name === 'Configuración').parameters.assignments.assignments.find((a) => a.name === 'site').value);",
      new URL('../build.mjs', import.meta.url).href], { env: { ...process.env, ...env }, encoding: 'utf8' });
    assert.equal(r.status, 0, r.stderr);
    return r.stdout.trim();
  };
  assert.equal(site({ N8N_SITE_URL: '' }), 'https://enso-peru.pages.dev/');
  assert.equal(site({ N8N_SITE_URL: 'https://enso.example.pe/' }), 'https://enso.example.pe/');
});

test('Extractor: valida el pedido y convierte la respuesta de OpenAI', async () => {
  const cfg = { 'Configuración': [{ json: { model: 'gpt-x', max_chars: 50 } }] };
  const pedido = (body) => runCode('extraer-pedido', {}, { ...cfg, 'Petición del pipeline': [{ json: { body } }] });
  const bad = await pedido({ kind: 'otro', schema: {}, text: 'x' });
  assert.deepEqual([bad[0].json.ok, bad[0].json.status], [false, 400]);
  const ok = await pedido({ kind: 'enfen-informe', schema: { type: 'object' }, text: 'a'.repeat(200), url: 'u', published: '2026-10-10' });
  const r = ok[0].json.request;
  assert.equal(ok[0].json.ok, true);
  assert.deepEqual([r.model, r.temperature, r.response_format.type], ['gpt-x', 0, 'json_object']);
  assert.ok(r.messages[1].content.endsWith('a'.repeat(50)) && !r.messages[1].content.includes('a'.repeat(51)));
  const respuesta = (json) => runCode('extraer-respuesta', {}, cfg, [{ json }]);
  const content = JSON.stringify({ data: { icen: 0.85 }, evidence: { icen: 'ICEN 0,85' } });
  const good = await respuesta({ statusCode: 200, body: { model: 'gpt-x-2026', choices: [{ message: { content } }] } });
  assert.deepEqual(good[0].json, { status: 200, body: { data: { icen: 0.85 }, model: 'gpt-x-2026', evidence: { icen: 'ICEN 0,85' }, usage: null } });
  const bare = await respuesta({ statusCode: 200, body: { choices: [{ message: { content: '{"icen":1}' } }] } });
  assert.deepEqual(bare[0].json.body.data, { icen: 1 });
  assert.equal((await respuesta({ statusCode: 429, body: { error: { message: 'cuota' } } }))[0].json.status, 502);
  assert.equal((await respuesta({ statusCode: 200, body: { choices: [{ message: { content: 'no es json' } }] } }))[0].json.status, 502);
});

test('docs/n8n.md cuenta los flujos de n8n/dist', () => {
  const words = { uno: 1, dos: 2, tres: 3, cuatro: 4, cinco: 5, seis: 6 };
  const m = /Hay (\w+) flujos/.exec(readFileSync(join(HERE, '..', '..', 'docs', 'n8n.md'), 'utf8'));
  assert.ok(m);
  assert.equal(words[m[1]], readdirSync(join(HERE, '..', 'dist')).filter((f) => f.endsWith('.json')).length);
});
