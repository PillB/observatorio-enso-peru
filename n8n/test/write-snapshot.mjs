#!/usr/bin/env node
// Escribe en una carpeta la copia que armaría el recolector de n8n para
// unas respuestas dadas (con el mismo código de los nodos). La usan las
// pruebas de Python para comprobar que el pipeline la lee.
//
//   node n8n/test/write-snapshot.mjs <carpeta> <respuestas.json>
//
// respuestas.json: [{url, id, group, expect, status, content_type, body_file|body|error, fetched_at}]

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { libSource } from '../build.mjs';

const [out, spec] = process.argv.slice(2);
const lib = new Function(`${['hash', 'classify', 'relay'].map(libSource).join('\n')}\nreturn { classify, buildSnapshot, heartbeat };`)();
const items = JSON.parse(readFileSync(spec, 'utf8'));
const now = new Date();
const results = items.map((r) => {
  const body = r.body_file ? new Uint8Array(readFileSync(r.body_file)) : r.body != null ? new TextEncoder().encode(r.body) : null;
  const cls = lib.classify({ url: r.url, expect: r.expect, status: r.status ?? null, headers: { 'content-type': r.content_type || '' }, body, error: r.error || null });
  return { id: r.id || r.url, url: r.url, group: r.group || 'g', fetched_at: r.fetched_at || now.toISOString(), pass: 1, cls, body };
});
const previous = process.env.PREVIOUS ? JSON.parse(readFileSync(process.env.PREVIOUS, 'utf8')) : null;
const { index, files } = lib.buildSnapshot({ results, previous, now, collector: { kind: 'n8n', host: 'prueba' } });
for (const f of files) {
  if (!f.body) continue;
  mkdirSync(dirname(join(out, f.path)), { recursive: true });
  writeFileSync(join(out, f.path), f.body);
}
writeFileSync(join(out, 'index.json'), JSON.stringify(index, null, 1) + '\n');
writeFileSync(join(out, 'heartbeat.json'), JSON.stringify(lib.heartbeat(index, now), null, 1) + '\n');
