#!/usr/bin/env node
// Experimento: ¿por qué el nodo HTTP de n8n corta («aborted») descargas que
// curl y Node bajan sin problema desde la misma máquina? Arma un flujo con la
// misma lista de URL pasando por variantes del nodo HTTP y, con
// --resultado, resume la salida de `n8n execute --rawOutput`.
//
//   node n8n/test/experimento-http.mjs > exp.json
//   n8n import:workflow --input=exp.json && n8n execute --id=EnsoExperimento1 --rawOutput > out.log
//   node n8n/test/experimento-http.mjs --resultado out.log

import { readFileSync } from 'node:fs';

const URLS = [
  'https://andina.pe/agencia/rss/3.xml',
  'https://www.gdacs.org/xml/rss.xml',
  'https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for',
  'https://www.infobae.com/arc/outboundfeeds/rss/category/peru/',
  'https://www.gob.pe/busquedas.rss?contenido[]=noticias&institucion[]=indeci&sheet=1&sort_by=recent',
  'https://www.proycontra.com.pe/rss.xml',
  'https://elcomercio.pe/arcio/rss/',
];
const UA = 'Observatorio-ENSO-Peru/4.0 (+https://github.com/PillB/observatorio-enso-peru; datos abiertos; n8n)';
const VARIANTS = {
  'actual': {},
  'sin-timeout': { timeout: null },
  'texto': { format: 'text' },
  'identity': { headers: [{ name: 'Accept-Encoding', value: 'identity' }] },
  'de-a-uno': { batch: { batchSize: 1, batchInterval: 2000 } },
  'sin-cabeceras': { noHeaders: true },
  'sin-lotes': { batch: null },
};

if (process.argv[2] === '--resultado') {
  const raw = readFileSync(process.argv[3], 'utf8');
  const run = JSON.parse(raw.slice(raw.indexOf('{'))).data.resultData.runData;
  const rows = [`| URL | ${Object.keys(VARIANTS).join(' | ')} |`, `|---|${Object.keys(VARIANTS).map(() => '---').join('|')}|`];
  for (let i = 0; i < URLS.length; i++) {
    const cells = Object.keys(VARIANTS).map((v) => {
      const r = run[v] && run[v][0];
      if (!r) return 'no corrió';
      if (r.error) return `error: ${r.error.message}`.slice(0, 60);
      const it = (r.data.main[0] || [])[i];
      if (!it) return '-';
      const j = it.json;
      if (j.error) return `✗ ${(j.error.message || JSON.stringify(j.error)).slice(0, 50)}`;
      const bytes = it.binary && it.binary.data ? it.binary.data.fileSize : (typeof j.data === 'string' ? j.data.length : '?');
      return `${j.statusCode} ${bytes}`;
    });
    rows.push(`| ${URLS[i].slice(0, 60)} | ${cells.join(' | ')} |`);
  }
  console.log(rows.join('\n'));
  process.exit(0);
}

const nodes = [
  { id: 'm', name: 'Manual', type: 'n8n-nodes-base.manualTrigger', typeVersion: 1, position: [0, 0], parameters: {} },
  { id: 'u', name: 'URL', type: 'n8n-nodes-base.code', typeVersion: 2, position: [200, 0],
    parameters: { jsCode: `return ${JSON.stringify(URLS)}.map((url) => ({ json: { url } }));` } },
];
const connections = { Manual: { main: [[{ node: 'URL', type: 'main', index: 0 }]] }, URL: { main: [[]] } };
let y = -300;
for (const [name, v] of Object.entries(VARIANTS)) {
  const options = {
    redirect: { redirect: { maxRedirects: 10 } },
    response: { response: { fullResponse: true, neverError: true, responseFormat: v.format || 'file', ...(v.format ? {} : { outputPropertyName: 'data' }) } },
  };
  if (v.timeout !== null) options.timeout = v.timeout || 40000;
  if (v.batch !== null) options.batching = { batch: v.batch || { batchSize: 4, batchInterval: 1000 } };
  const parameters = { url: '={{ $json.url }}', options };
  if (!v.noHeaders) {
    parameters.sendHeaders = true;
    parameters.headerParameters = { parameters: [{ name: 'User-Agent', value: UA }, { name: 'Accept', value: '*/*' }, ...(v.headers || [])] };
  }
  nodes.push({ id: name, name, type: 'n8n-nodes-base.httpRequest', typeVersion: 4.2, position: [450, y], parameters, onError: 'continueRegularOutput' });
  connections.URL.main[0].push({ node: name, type: 'main', index: 0 });
  y += 120;
}
console.log(JSON.stringify({ id: 'EnsoExperimento1', name: 'ENSO · experimento HTTP', nodes, connections, active: false,
  settings: { executionOrder: 'v1' }, pinData: {}, meta: {}, tags: [] }, null, 1));
