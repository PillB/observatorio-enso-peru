#!/usr/bin/env node
// Sondeo de acceso: descarga cada fuente del registro y la clasifica con el
// mismo código que usa el flujo de n8n (lib/classify.js). Sirve para medir,
// desde cualquier máquina (GitHub Actions, el contenedor de desarrollo, un
// servidor en AWS), qué fuentes responden y cuáles están bloqueadas.
//
//   node n8n/tools/probe.mjs --registry registry/sources.json --out informe.json [--label actions-azure]
//
// Detrás de un proxy: NODE_USE_ENV_PROXY=1 (Node ≥ 22.21).

import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { classify } = require('../lib/classify.js');

function arg(name, def) {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : def;
}

const registry = JSON.parse(readFileSync(arg('registry', 'registry/sources.json'), 'utf8'));
const out = arg('out', '');
const label = arg('label', 'local');
const only = arg('only', '');
const contact = process.env.ENSO_CONTACT_URL || 'https://github.com/PillB/observatorio-enso-peru';
const UA = `Observatorio-ENSO-Peru/4.0 (+${contact}; datos abiertos; sondeo)`;
const TIMEOUT_MS = Number(arg('timeout', '40000'));
const CONCURRENCY = Number(arg('concurrency', '8'));
const year = new Intl.DateTimeFormat('en', { timeZone: 'America/Lima', year: 'numeric' }).format(new Date());

const sources = registry.sources
  .filter((s) => !only || s.id.includes(only) || s.group === only)
  .map((s) => ({ ...s, url: s.url.replace('{year}', year) }));

async function probe(s) {
  const started = Date.now();
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(new Error(`timeout of ${TIMEOUT_MS}ms exceeded`)), TIMEOUT_MS);
  let status = null, headers = {}, body = null, error = null;
  try {
    const r = await fetch(s.url, { headers: { 'User-Agent': UA, Accept: '*/*' }, redirect: 'follow', signal: ctrl.signal });
    status = r.status;
    headers = Object.fromEntries(r.headers.entries());
    body = new Uint8Array(await r.arrayBuffer());
  } catch (e) {
    const c = e.cause || e;
    error = `${c.code || c.name || 'Error'}: ${c.message || e.message}`;
  } finally {
    clearTimeout(timer);
  }
  const cls = classify({ url: s.url, expect: s.expect, status, headers, body, error });
  return { id: s.id, group: s.group, url: s.url, expect: s.expect, ms: Date.now() - started, ...cls };
}

// Una petición a la vez por servidor, varias en paralelo entre servidores.
const byHost = new Map();
for (const s of sources) {
  const h = new URL(s.url).host;
  if (!byHost.has(h)) byHost.set(h, []);
  byHost.get(h).push(s);
}
const queues = [...byHost.values()];
const results = [];
async function worker() {
  while (queues.length) {
    const q = queues.shift();
    for (const s of q) {
      results.push(await probe(s));
      await new Promise((r) => setTimeout(r, 500));
    }
  }
}
await Promise.all(Array.from({ length: CONCURRENCY }, worker));

const order = new Map(sources.map((s, i) => [s.id, i]));
results.sort((a, b) => order.get(a.id) - order.get(b.id));
const counts = {};
for (const r of results) counts[r.verdict] = (counts[r.verdict] || 0) + 1;
const report = { schema: 'enso-probe/1', label, measured_at: new Date().toISOString(), counts, results };
if (out) writeFileSync(out, JSON.stringify(report, null, 1) + '\n');
for (const r of results.filter((x) => !x.ok)) {
  console.log(`${r.verdict.padEnd(12)} ${String(r.status ?? '-').padStart(4)} ${(r.block || '').padEnd(20)} ${r.id}  ${r.url}  ${r.note}`);
}
console.log(`\n${label}: ${JSON.stringify(counts)} (${results.length} fuentes)`);
