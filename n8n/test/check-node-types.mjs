#!/usr/bin/env node
// Comprueba, contra el catálogo de nodos de una instalación real de n8n
// (`n8n export:nodes`), que cada nodo de los flujos exista con esa versión,
// y algunas reglas que n8n no valida al importar:
// - los parámetros JSON del nodo HTTP no usan $('Nodo') (n8n 1.x los rechaza
//   con «JSON parameter needs to be valid JSON»);
// - cada conexión apunta a un nodo existente; cada nodo Code compila.
//
//   node n8n/test/check-node-types.mjs nodes.json n8n/dist/*.json

import { readFileSync } from 'node:fs';

const [catalogFile, ...flows] = process.argv.slice(2);
const catalog = JSON.parse(readFileSync(catalogFile, 'utf8'));
const versions = new Map();
for (const n of catalog) {
  const vs = Array.isArray(n.version) ? n.version : [n.version];
  versions.set(n.name, new Set([...(versions.get(n.name) || []), ...vs]));
}
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
let errors = 0;
const fail = (m) => { console.error(`✗ ${m}`); errors++; };
for (const file of flows) {
  const wf = JSON.parse(readFileSync(file, 'utf8'));
  const names = new Set(wf.nodes.map((n) => n.name));
  for (const n of wf.nodes) {
    if (!versions.has(n.type)) fail(`${file}: ${n.name}: el tipo ${n.type} no existe en esta versión de n8n`);
    else if (!versions.get(n.type).has(n.typeVersion)) fail(`${file}: ${n.name}: ${n.type} v${n.typeVersion} no existe (hay ${[...versions.get(n.type)].join(', ')})`);
    const body = n.parameters && n.parameters.jsonBody;
    if (typeof body === 'string' && body.includes('$(')) fail(`${file}: ${n.name}: jsonBody usa $('…'), que n8n 1.x rechaza`);
    if (n.type === 'n8n-nodes-base.code') {
      try { new AsyncFunction('$input', '$', '$json', '$execution', n.parameters.jsCode); } catch (e) { fail(`${file}: ${n.name}: ${e.message}`); }
    }
  }
  for (const [from, c] of Object.entries(wf.connections)) {
    if (!names.has(from)) fail(`${file}: conexión desde un nodo inexistente: ${from}`);
    for (const outs of c.main) for (const t of outs) if (!names.has(t.node)) fail(`${file}: conexión a un nodo inexistente: ${t.node}`);
  }
  console.log(`${errors ? '✗' : '✓'} ${file}: ${wf.nodes.length} nodos`);
}
process.exit(errors ? 1 : 0);
