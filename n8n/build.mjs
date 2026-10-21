#!/usr/bin/env node
// Construye los flujos de n8n (dist/*.json) a partir del código probado en
// lib/ y nodes/ y del registro de fuentes. Los nodos Code no se editan en la
// interfaz de n8n: se cambia el código aquí, se vuelve a construir y se
// vuelve a importar.
//
//   node n8n/build.mjs          # escribe dist/
//   node n8n/build.mjs --check  # falla si dist/ no está al día

import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..');
const read = (p) => readFileSync(join(HERE, p), 'utf8');

/** Código de una biblioteca sin la línea de exportación para Node. */
export function libSource(name) {
  const src = read(`lib/${name}.js`);
  const cut = src.indexOf('// @export');
  return (cut >= 0 ? src.slice(0, cut) : src).trimEnd() + '\n';
}

const NODE_LIBS = {
  'fuentes': [],
  'analizar': ['classify'],
  'segunda': ['classify', 'enfen'],
  'informe': ['relay'],
  'preparar': ['hash', 'classify', 'relay'],
  'arbol': [],
  'commit': [],
  'rama': [],
  'resumen': [],
  'vigilante': [],
};

/** Código final de un nodo Code: bibliotecas + cuerpo, con los marcadores reemplazados. */
export function nodeCode(name, vars = {}) {
  let body = read(`nodes/${name}.js`);
  for (const [k, v] of Object.entries(vars)) body = body.split(`__${k}__`).join(v);
  const missing = body.match(/__[A-Z_]+__/);
  if (missing) throw new Error(`nodes/${name}.js: falta el valor de ${missing[0]}`);
  const libs = NODE_LIBS[name].map(libSource).join('\n');
  const head = `// Generado por n8n/build.mjs desde n8n/nodes/${name}.js${libs ? ' y n8n/lib/' : ''}. No editar en n8n.\n`;
  return head + (libs ? `${libs}\n// ---- nodo ----\n` : '') + body;
}

const registryText = readFileSync(join(ROOT, 'registry/sources.json'), 'utf8');
const registry = JSON.parse(registryText);
const VERSION = createHash('sha256')
  .update(['hash', 'classify', 'enfen', 'relay'].map(libSource).join(''))
  .update(Object.keys(NODE_LIBS).map((n) => read(`nodes/${n}.js`)).join(''))
  .update(registryText)
  .digest('hex').slice(0, 10);

const GH = '{{ $(\'Configuración\').first().json.api }}/repos/{{ $(\'Configuración\').first().json.repo }}';
// Id de la credencial en el n8n de destino (N8N_GITHUB_CRED_ID), para que al
// reimportar el flujo no haya que volver a elegirla en cada nodo.
const CRED = { githubApi: { id: process.env.N8N_GITHUB_CRED_ID || 'EnsoGithubCred01', name: 'GitHub ENSO (n8n)' } };
const GH_HEADERS = [
  { name: 'Accept', value: 'application/vnd.github+json' },
  { name: 'X-GitHub-Api-Version', value: '2022-11-28' },
];
const UA = '=Observatorio-ENSO-Peru/4.0 (+{{ $(\'Configuración\').first().json.contact }}; datos abiertos; n8n)';

let nextX = 0;
function node(name, type, typeVersion, parameters, extra = {}) {
  const id = createHash('sha256').update(`${type}:${name}`).digest('hex');
  const uuid = `${id.slice(0, 8)}-${id.slice(8, 12)}-4${id.slice(13, 16)}-8${id.slice(17, 20)}-${id.slice(20, 32)}`;
  const n = { parameters, id: uuid, name, type, typeVersion, position: [extra.x ?? (nextX += 240), extra.y ?? 0] };
  delete extra.x; delete extra.y;
  return Object.assign(n, extra);
}

function code(name, file, vars, extra = {}) {
  return node(name, 'n8n-nodes-base.code', 2, { jsCode: nodeCode(file, { VERSION, ...vars }) }, extra);
}

function setNode(name, fields, extra = {}) {
  return node(name, 'n8n-nodes-base.set', 3.4, {
    assignments: {
      assignments: fields.map(([k, value, type = 'string']) => ({
        id: createHash('sha256').update(k).digest('hex').slice(0, 8), name: k, value, type,
      })),
    },
    options: {},
  }, extra);
}

function download(name, timeoutMs, extra = {}) {
  return node(name, 'n8n-nodes-base.httpRequest', 4.2, {
    url: '={{ $json.url }}',
    sendHeaders: true,
    headerParameters: { parameters: [{ name: 'User-Agent', value: UA }, { name: 'Accept', value: '*/*' }] },
    options: {
      batching: { batch: { batchSize: 4, batchInterval: 1000 } },
      redirect: { redirect: { maxRedirects: 10 } },
      response: { response: { fullResponse: true, neverError: true, responseFormat: 'file', outputPropertyName: 'data' } },
      timeout: timeoutMs,
    },
  }, { onError: 'continueRegularOutput', ...extra });
}

function github(name, method, url, body, opts = {}) {
  const parameters = {
    method,
    url,
    authentication: 'predefinedCredentialType',
    nodeCredentialType: 'githubApi',
    sendHeaders: true,
    headerParameters: { parameters: opts.headers || GH_HEADERS },
    options: {},
  };
  if (body) Object.assign(parameters, { sendBody: true, specifyBody: 'json', jsonBody: body });
  if (opts.full) parameters.options.response = { response: { fullResponse: true, neverError: true, responseFormat: opts.text ? 'text' : 'json' } };
  if (opts.batch) parameters.options.batching = { batch: { batchSize: 1, batchInterval: opts.batch } };
  const extra = { credentials: CRED, ...opts.extra };
  if (opts.retry) Object.assign(extra, { retryOnFail: true, maxTries: 3, waitBetweenTries: 5000 });
  return node(name, 'n8n-nodes-base.httpRequest', 4.2, parameters, extra);
}

const CONFIG_COMMON = [
  ['contact', 'https://github.com/PillB/observatorio-enso-peru'],
  ['only', ''],
];

function passes(sourceNode) {
  return [
    download('Descargar', 40000),
    code('Analizar', 'analizar', { SOURCE_NODE: sourceNode }),
    code('Segunda pasada', 'segunda', {}, { y: 200 }),
    node('Esperar 30 s', 'n8n-nodes-base.wait', 1.1, { resume: 'timeInterval', amount: 30, unit: 'seconds' }, { y: 200, webhookId: 'enso-espera-30s' }),
    download('Descargar (2.ª pasada)', 60000, { y: 200 }),
    code('Analizar (2.ª pasada)', 'analizar', { SOURCE_NODE: 'Segunda pasada' }, { y: 200 }),
    node('Unir pasadas', 'n8n-nodes-base.merge', 3, {}),
  ];
}

function chain(names, connections = {}) {
  for (let i = 0; i + 1 < names.length; i++) {
    const [a, b, input = 0] = Array.isArray(names[i + 1]) ? [names[i], ...names[i + 1]] : [names[i], names[i + 1]];
    const from = Array.isArray(a) ? a[0] : a;
    connections[from] = connections[from] || { main: [[]] };
    connections[from].main[0].push({ node: b, type: 'main', index: input });
  }
  return connections;
}

const PASS_CONNECTIONS = (c) => {
  chain(['Descargar', 'Analizar', 'Segunda pasada', 'Esperar 30 s', 'Descargar (2.ª pasada)', 'Analizar (2.ª pasada)', ['Unir pasadas', 1]], c);
  chain(['Analizar', 'Unir pasadas'], c);
  return c;
};

function workflow(id, name, nodes, connections, settings = {}) {
  return {
    id, name, nodes, connections, active: false, pinData: {},
    settings: { executionOrder: 'v1', timezone: 'America/Lima', saveManualExecutions: true, ...settings },
    meta: { templateCredsSetupCompleted: false, ensoVersion: VERSION },
    tags: [],
  };
}

// ---------------------------------------------------------------- validación
nextX = -240;
const validation = workflow('EnsoValidacion01', 'ENSO · Validación de fuentes desde n8n', [
  node('Ejecutar a mano', 'n8n-nodes-base.manualTrigger', 1, {}),
  setNode('Configuración', [['scope', 'todas'], ...CONFIG_COMMON]),
  code('Fuentes', 'fuentes', { REGISTRY: JSON.stringify(registry) }),
  ...passes('Fuentes'),
  code('Informe', 'informe', {}),
  node('Informe CSV', 'n8n-nodes-base.convertToFile', 1.1, { options: { fileName: 'validacion-fuentes-n8n.csv' } }),
], (() => {
  const c = chain(['Ejecutar a mano', 'Configuración', 'Fuentes', 'Descargar']);
  PASS_CONNECTIONS(c);
  chain(['Unir pasadas', 'Informe', 'Informe CSV'], c);
  return c;
})());

// ---------------------------------------------------------------- recolector
nextX = -240;
const contents = (path, ref) => `=${GH}/contents/${path}?ref={{ encodeURIComponent($('Configuración').first().json.${ref}) }}`;
const RAW = [{ name: 'Accept', value: 'application/vnd.github.raw+json' }, { name: 'X-GitHub-Api-Version', value: '2022-11-28' }];
const collector = workflow('EnsoRecolector01', 'ENSO · Recolector n8n (fuentes no bloqueadas)', [
  node('Cada día 22:50 (Lima)', 'n8n-nodes-base.scheduleTrigger', 1.2,
    { rule: { interval: [{ field: 'cronExpression', expression: '50 22 * * *' }] } }, { y: -120 }),
  node('Ejecutar a mano', 'n8n-nodes-base.manualTrigger', 1, {}, { x: 0, y: 120 }),
  setNode('Configuración', [
    ['repo', 'PillB/observatorio-enso-peru'],
    ['api', 'https://api.github.com'],
    ['data_branch', 'data-n8n'],
    ['registry_ref', 'main'],
    ['registry_path', 'registry/sources.json'],
    ['scope', 'n8n'],
    ['host_label', 'n8n-aws'],
    ['egress', 'aws-us-east-1'],
    ['carry_hours', 72, 'number'],
    ['max_file_mb', 8, 'number'],
    ...CONFIG_COMMON,
  ]),
  github('Leer registro', 'GET', contents("{{ $('Configuración').first().json.registry_path }}", 'registry_ref'), null, { full: true, text: true, headers: RAW, retry: true, extra: { onError: 'continueRegularOutput' } }),
  github('Leer copia anterior', 'GET', contents('index.json', 'data_branch'), null, { full: true, text: true, headers: RAW, retry: true, extra: { onError: 'continueRegularOutput', executeOnce: true } }),
  code('Fuentes', 'fuentes', { REGISTRY: JSON.stringify(registry) }),
  ...passes('Fuentes'),
  code('Preparar copia', 'preparar', {}),
  github('Crear blobs', 'POST', `=${GH}/git/blobs`, "={{ JSON.stringify({ content: $json.content, encoding: 'base64' }) }}", { batch: 800, retry: true }),
  code('Armar árbol', 'arbol', {}),
  github('Crear árbol', 'POST', `=${GH}/git/trees`, '={{ JSON.stringify({ tree: $json.tree }) }}', { retry: true }),
  code('Preparar commit', 'commit', {}),
  github('Crear commit', 'POST', `=${GH}/git/commits`, '={{ JSON.stringify($json) }}', { retry: true }),
  github('Leer rama', 'GET', `=${GH}/git/ref/heads/{{ $('Configuración').first().json.data_branch }}`, null, { full: true }),
  code('Preparar rama', 'rama', {}),
  github('Publicar', '={{ $json.method }}', '={{ $json.url }}', '={{ JSON.stringify($json.body) }}', { full: true }),
  code('Resumen', 'resumen', {}),
  github('Avisar al sitio', 'POST', `=${GH}/dispatches`, "={{ JSON.stringify({ event_type: 'enso-refresh', client_payload: { from: 'n8n' } }) }}",
    { extra: { disabled: true, notes: 'Opcional: pide la actualización del sitio en el momento. Activar solo si el token tiene permiso para repository_dispatch.' } }),
], (() => {
  const c = chain(['Cada día 22:50 (Lima)', 'Configuración', 'Leer registro', 'Leer copia anterior', 'Fuentes', 'Descargar']);
  chain(['Ejecutar a mano', 'Configuración'], c);
  PASS_CONNECTIONS(c);
  chain(['Unir pasadas', 'Preparar copia', 'Crear blobs', 'Armar árbol', 'Crear árbol', 'Preparar commit', 'Crear commit', 'Leer rama', 'Preparar rama', 'Publicar', 'Resumen', 'Avisar al sitio'], c);
  return c;
})());

// ---------------------------------------------------------------- vigilante
// Revisa el sitio publicado cada 6 horas, sin depender de GitHub: si
// data/manifest.json no responde o es de hace más de 30 horas, la ejecución
// falla y el «Error workflow» de n8n avisa (GitHub ya desactivó una vez los
// flujos programados por inactividad sin que nadie lo notara).
nextX = -240;
const watcher = workflow('EnsoVigilante001', 'ENSO · Vigilante del sitio publicado', [
  node('Cada 6 horas', 'n8n-nodes-base.scheduleTrigger', 1.2, { rule: { interval: [{ field: 'hours', hoursInterval: 6 }] } }, { y: -120 }),
  node('Ejecutar a mano', 'n8n-nodes-base.manualTrigger', 1, {}, { x: 0, y: 120 }),
  setNode('Configuración', [
    ['site', 'https://pillb.github.io/observatorio-enso-peru/'],
    ['max_age_hours', 30, 'number'],
    ...CONFIG_COMMON.filter(([k]) => k === 'contact'),
  ]),
  node('Leer manifest.json', 'n8n-nodes-base.httpRequest', 4.2, {
    url: "={{ $('Configuración').first().json.site.replace(/\\/?$/, '/') + 'data/manifest.json?t=' + Date.now() }}",
    sendHeaders: true,
    headerParameters: { parameters: [{ name: 'User-Agent', value: UA }, { name: 'Cache-Control', value: 'no-cache' }] },
    options: { timeout: 30000, response: { response: { fullResponse: true, neverError: true, responseFormat: 'text' } } },
  }, { onError: 'continueRegularOutput', retryOnFail: true, maxTries: 3, waitBetweenTries: 5000 }),
  code('Revisar frescura', 'vigilante', {}),
], (() => {
  const c = chain(['Cada 6 horas', 'Configuración', 'Leer manifest.json', 'Revisar frescura']);
  chain(['Ejecutar a mano', 'Configuración'], c);
  return c;
})());

export const WORKFLOWS = {
  'enso-n8n-validacion.json': validation,
  'enso-n8n-recolector.json': collector,
  'enso-n8n-vigilante.json': watcher,
};

if (import.meta.url === `file://${process.argv[1]}`) {
  const check = process.argv.includes('--check');
  mkdirSync(join(HERE, 'dist'), { recursive: true });
  let stale = 0;
  for (const [file, wf] of Object.entries(WORKFLOWS)) {
    const text = JSON.stringify(wf, null, 2) + '\n';
    const path = join(HERE, 'dist', file);
    if (check) {
      let cur = '';
      try { cur = readFileSync(path, 'utf8'); } catch (e) { /* falta */ }
      if (cur !== text) { console.error(`${file} no está al día: correr node n8n/build.mjs`); stale++; }
    } else {
      writeFileSync(path, text);
      console.log(`dist/${file}: ${wf.nodes.length} nodos, versión ${VERSION}`);
    }
  }
  process.exit(stale ? 1 : 0);
}
