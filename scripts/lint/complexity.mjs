#!/usr/bin/env node
// Complejidad ciclomática (McCabe) de cada función de JavaScript, medida con la regla «complexity» de ESLint
// (variante clásica: 1 + if, ?:, &&, ||, ??, &&=, ||=, ??=, ?., parámetros con valor por omisión, case sin
// default, catch y cada bucle). La llama python/tools/complexity.py; no se usa sola.
//
// Entrada (stdin): JSON [{"path": "ruta/relativa.js", "wrap": false}, ...], rutas relativas a la carpeta actual
// (la raíz del repositorio). «wrap» envuelve el archivo en una función async: es el cuerpo de un nodo Code de n8n,
// que n8n ejecuta dentro de una función (por eso tiene «return» en el nivel superior).
// Salida (stdout): JSON {"tool": {...versiones}, "functions": [{path, name, line, score}], "errors": [{path, line, message}]}.
//
// ESLint informa la complejidad de cada función con la posición de su «cabeza» (nombre y paréntesis, o «=>»);
// el nombre calificado (Clase.metodo, externa.(map callback) #2) sale del árbol de espree, el mismo analizador
// que usa ESLint, buscando la función más interna cuyo tramo contiene esa posición. Si alguna función queda sin
// nombre o algún mensaje sin función, es un error y no un silencio: sin eso una función compleja podría escapar.

import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { ESLint } from 'eslint';
import * as espree from 'espree';

const require = createRequire(import.meta.url);
const VERSIONS = {
  eslint: require('eslint/package.json').version,
  espree: require('espree/package.json').version,
  node: process.versions.node,
};
const WRAP_HEAD = 'async function __n8nCodeNode() {\n';
const WRAP_NAME = '(n8n Code node)';
const MSG = /^(.*) has a complexity of (\d+)\. Maximum allowed is 0\.$/;

const engines = new Map();
function engine(sourceType) {
  if (!engines.has(sourceType)) {
    engines.set(sourceType, new ESLint({
      cwd: process.cwd(),
      overrideConfigFile: true,
      ignore: false,
      overrideConfig: [{
        files: ['**/*'],
        languageOptions: { ecmaVersion: 'latest', sourceType },
        linterOptions: { noInlineConfig: true, reportUnusedDisableDirectives: 'off' },
        rules: { complexity: ['error', { max: 0, variant: 'classic' }] },
      }],
    }));
  }
  return engines.get(sourceType);
}

/** El primer modo de análisis que acepta el archivo: los .cjs son CommonJS; el resto, módulo y si no, script. */
function parse(text, path) {
  const kinds = path.endsWith('.cjs') ? ['commonjs'] : path.endsWith('.mjs') ? ['module'] : ['module', 'script'];
  let first;
  for (const sourceType of kinds) {
    try {
      return { sourceType, ast: espree.parse(text, { ecmaVersion: 'latest', sourceType, loc: true, range: true }) };
    } catch (e) {
      first ??= e;
    }
  }
  return { error: first };
}

const isFn = (n) => n && (n.type === 'FunctionDeclaration' || n.type === 'FunctionExpression' || n.type === 'ArrowFunctionExpression');
const isUnit = (n) => isFn(n) || n.type === 'StaticBlock' || (n.type === 'PropertyDefinition' && n.value && !isFn(n.value));

function keyName(key, computed) {
  if (!key) return '(anonymous)';
  if (computed) return '[computed]';
  if (key.type === 'Identifier') return key.name;
  if (key.type === 'PrivateIdentifier') return `#${key.name}`;
  if (key.type === 'Literal') return String(key.value);
  return '(anonymous)';
}

function dotted(n) {
  if (n.type === 'Identifier') return n.name;
  if (n.type === 'ThisExpression') return 'this';
  if (n.type === 'MemberExpression' && !n.computed) {
    const o = dotted(n.object);
    return o && `${o}.${n.property.name}`;
  }
  return null;
}

function calleeName(c) {
  if (c.type === 'Identifier') return c.name;
  if (c.type === 'MemberExpression' && !c.computed) return c.property.name;
  return 'call';
}

function memberName(parent) {
  const k = keyName(parent.key, parent.computed);
  return parent.kind === 'get' || parent.kind === 'set' ? `${parent.kind} ${k}` : k;
}

function callbackName(n, parent) {
  if (parent.callee === n) return '(iife)';
  const first = parent.arguments[0];
  const ev = first !== n && first?.type === 'Literal' && typeof first.value === 'string' ? ` '${first.value.slice(0, 40)}'` : '';
  return `(${calleeName(parent.callee)}${ev} callback)`;
}

/** Nombre de una función anónima según el nodo que la recibe. */
const BY_PARENT = {
  VariableDeclarator: (n, p) => (p.id.type === 'Identifier' ? p.id.name : '(destructured)'),
  MethodDefinition: (n, p) => memberName(p),
  Property: (n, p) => memberName(p),
  PropertyDefinition: (n, p) => memberName(p),
  AssignmentExpression: (n, p) => dotted(p.left) ?? '(assignment)',
  AssignmentPattern: (n, p) => `(default of ${p.left.type === 'Identifier' ? p.left.name : 'param'})`,
  ExportDefaultDeclaration: () => 'default',
  CallExpression: callbackName,
  NewExpression: callbackName,
};

/** Nombre propio de una función: el suyo, el de la variable, propiedad o asignación que la recibe, o su papel. */
function ownName(n, parent) {
  if (n.type === 'StaticBlock') return '(static block)';
  if (n.type === 'PropertyDefinition') return `${keyName(n.key, n.computed)} (field initializer)`;
  if (n.id?.name) return n.id.name;
  const by = parent && BY_PARENT[parent.type];
  return by ? by(n, parent) : '(anonymous)';
}

function className(node, parent) {
  if (node.id?.name) return node.id.name;
  return parent?.type === 'VariableDeclarator' && parent.id.type === 'Identifier' ? parent.id.name : '(class)';
}

const HOLDERS = new Set(['MethodDefinition', 'Property', 'PropertyDefinition']);

/** Dónde empieza la cabeza: en un método o una propiedad con función, en la clave (fuera del nodo de la función). */
function headStart(node, parent) {
  return isFn(node) && parent && HOLDERS.has(parent.type) && parent.value === node ? parent.loc.start : node.loc.start;
}

function children(node) {
  const out = [];
  for (const k of Object.keys(node)) {
    if (k === 'parent' || k === 'loc' || k === 'range') continue;
    const v = node[k];
    if (Array.isArray(v)) out.push(...v.filter((c) => c && typeof c.type === 'string'));
    else if (v && typeof v.type === 'string') out.push(v);
  }
  return out;
}

/** Funciones del árbol con su nombre calificado y el tramo [inicio, fin] en el que cae su «cabeza». */
function units(ast) {
  const out = [];
  const walk = (node, parent, path) => {
    let here = path;
    if (isUnit(node)) {
      here = [...path, ownName(node, parent)];
      out.push({ name: here.join('.'), start: headStart(node, parent), end: node.loc.end, depth: here.length });
    } else if (node.type === 'ClassDeclaration' || node.type === 'ClassExpression') {
      here = [...path, className(node, parent)];
    }
    for (const c of children(node)) walk(c, node, here);
  };
  walk(ast, null, []);
  return out;
}

const before = (a, b) => a.line < b.line || (a.line === b.line && a.column <= b.column);

/** La función más interna cuyo tramo contiene la posición del mensaje. */
function innermost(found, m) {
  const at = { line: m.line, column: m.column - 1 };
  let best = null;
  for (const u of found) if (before(u.start, at) && before(at, u.end) && (!best || u.depth > best.depth)) best = u;
  return best;
}

/** La función (aún no usada) de un mensaje de la regla, con su número; null si no casa. */
function match(found, m, used) {
  const mm = MSG.exec(m.message);
  const best = innermost(found, m);
  if (!mm || !best || used.has(best)) return null;
  used.add(best);
  return { ...best, score: Number(mm[2]) };
}

/** Junta cada mensaje de la regla con su función; lo que no casa uno a uno es un error, no un silencio. */
function attribute(path, found, messages, shift) {
  const errors = [];
  const fns = [];
  const used = new Set();
  const err = (line, message) => errors.push({ path, line: Math.max(1, line - shift), message });
  for (const m of messages) {
    // Avisos (severidad 1), como el de un comentario «/* eslint-disable */» sin efecto: noInlineConfig impide que un
    // comentario apague la medida, y eso no es un error. Lo fatal (no se pudo analizar) sí lo es.
    if (m.ruleId !== 'complexity') {
      if (m.fatal || m.severity >= 2) err(m.line ?? 1, `ESLint: ${m.message}`);
      continue;
    }
    const fn = match(found, m, used);
    if (fn) fns.push({ path, name: fn.name, line: Math.max(1, fn.start.line - shift), score: fn.score });
    else err(m.line, `no se pudo atribuir el mensaje de complejidad a una función: «${m.message}»`);
  }
  for (const u of found) if (!used.has(u)) err(u.start.line, `ESLint no midió la función ${u.name}`);
  return { functions: fns, errors };
}

async function measure({ path, wrap }) {
  const raw = readFileSync(path, 'utf8');
  const text = wrap ? `${WRAP_HEAD}${raw}\n}\n` : raw;
  const shift = wrap ? 1 : 0;
  const parsed = parse(text, path);
  if (parsed.error) {
    const line = Math.max(1, (parsed.error.lineNumber ?? 1) - shift);
    return { functions: [], errors: [{ path, line, message: `no se pudo analizar: ${parsed.error.message}` }] };
  }
  const found = units(parsed.ast);
  if (wrap) for (const u of found) u.name = u.name.replace(/^__n8nCodeNode/, WRAP_NAME);
  const [res] = await engine(parsed.sourceType).lintText(text, { filePath: path });
  return attribute(path, found, res.messages, shift);
}

const files = JSON.parse(readFileSync(0, 'utf8'));
const out = { tool: VERSIONS, functions: [], errors: [] };
// Los nombres salen del espree de package.json y los números del espree que trae ESLint: si npm instaló dos versiones
// distintas, las posiciones podrían no casar. Se exige la misma.
const eslintEspree = createRequire(require.resolve('eslint'))('espree/package.json').version;
if (eslintEspree !== VERSIONS.espree) {
  out.errors.push({ path: 'scripts/lint/package.json', line: 1, message: `ESLint usa espree ${eslintEspree} y package.json fija ${VERSIONS.espree}: fije la misma versión` });
  files.length = 0;
}
for (const f of files) {
  try {
    const r = await measure(f);
    out.functions.push(...r.functions);
    out.errors.push(...r.errors);
  } catch (e) {
    out.errors.push({ path: f.path, line: 1, message: `error inesperado: ${e.stack ?? e}` });
  }
}
process.stdout.write(JSON.stringify(out));
