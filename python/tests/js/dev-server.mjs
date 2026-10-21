// Servidor de prueba que imita Cloudflare Pages: archivos estáticos de --site y /api/geo/* con la
// Function real (functions/_lib/geo-console.js) sobre una D1 de mentira. Usuarios en GEO_USERS.
//   node dev-server.mjs --site ../public --port 8788
import { readFile } from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';

import { handle } from '../../../functions/_lib/geo-console.js';
import { FakeD1 } from './fake-d1.mjs';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const site = path.resolve(args.site || '../public');
const port = Number(args.port || 8788);
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png' };

async function asset(pathname) {
  let p = path.join(site, decodeURIComponent(pathname));
  if (!p.startsWith(site)) return new Response('', { status: 403 });
  if (p.endsWith('/')) p += 'index.html';
  try {
    return new Response(await readFile(p), { headers: { 'Content-Type': TYPES[path.extname(p)] || 'application/octet-stream' } });
  } catch {
    return new Response('no existe', { status: 404 });
  }
}

const env = { GEO_DB: new FakeD1(), GEO_USERS: process.env.GEO_USERS || '{}', ASSETS: { fetch: (u) => asset(new URL(u).pathname) } };

http.createServer(async (req, res) => {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const url = `http://localhost:${port}${req.url}`;
  const headers = new Headers();
  for (const [k, v] of Object.entries(req.headers)) headers.set(k, Array.isArray(v) ? v.join(', ') : v);
  headers.set('CF-Connecting-IP', req.socket.remoteAddress || '');
  const request = new Request(url, { method: req.method, headers, body: ['GET', 'HEAD'].includes(req.method) ? undefined : Buffer.concat(chunks) });
  const pathname = new URL(url).pathname;
  const r = pathname.startsWith('/api/geo/') ? await handle(request, env) : await asset(pathname);
  res.writeHead(r.status, Object.fromEntries(r.headers));
  res.end(Buffer.from(await r.arrayBuffer()));
}).listen(port, '127.0.0.1', () => console.log(`listo en http://localhost:${port}/`));
