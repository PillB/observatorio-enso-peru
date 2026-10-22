#!/usr/bin/env node
// API de GitHub falsa (solo lo que usa el recolector de n8n), para probar el
// flujo real de n8n de punta a punta sin tocar el repositorio:
// contents (lectura), git/blobs, git/trees, git/commits, git/ref(s),
// dispatches. Verifica lo mismo que GitHub: el SHA de cada blob, que los
// árboles apunten a blobs existentes y que el commit apunte a un árbol.
//
//   node n8n/test/fake-github.mjs --port 8787 --registry registry/sources.json
//
// GET /__dump?branch=data-n8n&dir=/ruta escribe el contenido de la rama en
// una carpeta; GET /__stats devuelve cuántos blobs se crearon.

import { createServer } from 'node:http';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';

const arg = (n, d) => { const i = process.argv.indexOf(`--${n}`); return i > 0 ? process.argv[i + 1] : d; };
const PORT = Number(arg('port', '8787'));
const registry = readFileSync(arg('registry', 'registry/sources.json'));

const blobs = new Map(); // sha -> Buffer
const trees = new Map(); // sha -> [{path, sha}]
const commits = new Map(); // sha -> {tree, parents, message}
const refs = new Map(); // branch -> commit sha
const stats = { blobs_created: 0, requests: 0, auth_missing: 0 };

const gitSha = (b) => createHash('sha1').update(Buffer.concat([Buffer.from(`blob ${b.length}\0`), b])).digest('hex');
const sha = (s) => createHash('sha1').update(s).digest('hex');

function files(branch) {
  const c = commits.get(refs.get(branch));
  return c ? trees.get(c.tree) : null;
}

function send(res, status, body, type = 'application/json') {
  // Como GitHub con un token de plazo fijo: el recolector guarda el vencimiento.
  res.writeHead(status, { 'content-type': type, 'GitHub-Authentication-Token-Expiration': '2027-05-10 00:00:00 UTC' });
  res.end(typeof body === 'string' || Buffer.isBuffer(body) ? body : JSON.stringify(body));
}

createServer(async (req, res) => {
  stats.requests++;
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const raw = Buffer.concat(chunks);
  const body = raw.length ? JSON.parse(raw.toString('utf8')) : {};
  const u = new URL(req.url, 'http://x');
  if (!u.pathname.startsWith('/__') && !req.headers.authorization) stats.auth_missing++;
  const m = u.pathname.match(/^\/repos\/[^/]+\/[^/]+\/(.*)$/);
  const p = m ? m[1] : u.pathname;
  try {
    if (p === '/__stats') return send(res, 200, { ...stats, refs: Object.fromEntries(refs) });
    if (p === '/__dump') {
      const list = files(u.searchParams.get('branch')) || [];
      for (const f of list) {
        const out = join(u.searchParams.get('dir'), f.path);
        mkdirSync(dirname(out), { recursive: true });
        writeFileSync(out, blobs.get(f.sha));
      }
      return send(res, 200, { files: list.length });
    }
    if (req.method === 'GET' && p.startsWith('contents/')) {
      const path = decodeURIComponent(p.slice('contents/'.length));
      const ref = u.searchParams.get('ref');
      if (path === 'registry/sources.json') return send(res, 200, registry, 'application/vnd.github.raw+json');
      const f = (files(ref) || []).find((x) => x.path === path);
      return f ? send(res, 200, blobs.get(f.sha), 'application/vnd.github.raw+json') : send(res, 404, { message: 'Not Found' });
    }
    if (req.method === 'POST' && p === 'git/blobs') {
      if (body.encoding !== 'base64') return send(res, 422, { message: 'encoding' });
      const b = Buffer.from(body.content, 'base64');
      const s = gitSha(b);
      blobs.set(s, b);
      stats.blobs_created++;
      return send(res, 201, { sha: s });
    }
    if (req.method === 'POST' && p === 'git/trees') {
      for (const e of body.tree) if (!blobs.has(e.sha)) return send(res, 422, { message: `tree.sha ${e.sha} is not a valid blob` });
      const list = body.tree.map((e) => ({ path: e.path, sha: e.sha }));
      const s = sha(JSON.stringify(list));
      trees.set(s, list);
      return send(res, 201, { sha: s });
    }
    if (req.method === 'POST' && p === 'git/commits') {
      if (!trees.has(body.tree)) return send(res, 422, { message: 'tree not found' });
      const s = sha(JSON.stringify(body) + Date.now() + Math.random());
      commits.set(s, body);
      return send(res, 201, { sha: s });
    }
    let r;
    if (req.method === 'GET' && (r = p.match(/^git\/ref\/heads\/(.+)$/))) {
      return refs.has(r[1]) ? send(res, 200, { ref: `refs/heads/${r[1]}`, object: { sha: refs.get(r[1]) } }) : send(res, 404, { message: 'Not Found' });
    }
    if (req.method === 'PATCH' && (r = p.match(/^git\/refs\/heads\/(.+)$/))) {
      if (!refs.has(r[1])) return send(res, 422, { message: 'Reference does not exist' });
      if (!commits.has(body.sha)) return send(res, 422, { message: 'Object does not exist' });
      refs.set(r[1], body.sha);
      return send(res, 200, { ref: `refs/heads/${r[1]}`, object: { sha: body.sha } });
    }
    if (req.method === 'POST' && p === 'git/refs') {
      const name = String(body.ref).replace(/^refs\/heads\//, '');
      if (refs.has(name)) return send(res, 422, { message: 'Reference already exists' });
      if (!commits.has(body.sha)) return send(res, 422, { message: 'Object does not exist' });
      refs.set(name, body.sha);
      return send(res, 201, { ref: body.ref, object: { sha: body.sha } });
    }
    if (req.method === 'POST' && p === 'dispatches') return send(res, 204, '');
    return send(res, 404, { message: `no implementado: ${req.method} ${p}` });
  } catch (e) {
    return send(res, 500, { message: String(e) });
  }
}).listen(PORT, '0.0.0.0', () => console.log(`fake GitHub en :${PORT}`));
