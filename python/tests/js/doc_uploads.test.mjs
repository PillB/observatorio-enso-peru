// Pruebas de la consola de documentos (functions/_lib/doc-uploads.js): una D1 de mentira y una API de GitHub de
// mentira (fetch reemplazado). Se corren con `node --test` (las lanza tests/test_doc_uploads.py).
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { afterEach, beforeEach, describe, it } from 'node:test';

import { handle as geo, hashPassword, COOKIE } from '../../../functions/_lib/geo-console.js';
import { handle, MAX_AGE_DAYS, nextEntries } from '../../../functions/_lib/doc-uploads.js';
import { FakeD1 } from './fake-d1.mjs';
import { prepare } from '../../../public/admin/documentos.js';

const ORIGIN = 'https://enso-peru.pages.dev';
const DOC = {
  id: 'comunicado-18-2026', kind: 'comunicado', label: 'Comunicado oficial ENFEN N° 18-2026',
  urls: ['https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-18-2026/?wpdmdl=2190',
    'https://www.dhn.mil.pe/Archivos/oceanografia/enfen/comunicado-oficial/18-2026.pdf'],
  open: ['https://enfen.imarpe.gob.pe/download/comunicado-oficial-enfen-n-18-2026/'], reason: 'verificación', since: '2026-10-21',
};
const PDF = Buffer.concat([Buffer.from('%PDF-1.7\n'), Buffer.alloc(4000, 0x41), Buffer.from('\n%%EOF\n')]);

let env;
let users;
let gh; // estado de la API de GitHub de mentira
const realFetch = globalThis.fetch;

function fakeGitHub() {
  const state = { refs: {}, commits: {}, trees: {}, blobs: {}, files: {}, calls: [], dispatches: [], conflictOnce: false, n: 0 };
  const sha = () => (state.n += 1).toString(16).padStart(40, '0');
  globalThis.fetch = async (input, init = {}) => {
    const u = new URL(typeof input === 'string' ? input : input.url);
    const path = u.pathname.replace(/^\/repos\/PillB\/observatorio-enso-peru\//, '');
    const method = init.method || 'GET';
    state.calls.push(`${method} ${path}`);
    assert.equal(init.headers.Authorization, 'Bearer token-de-prueba');
    const reply = (status, body) => new Response(body === undefined ? null : JSON.stringify(body), { status });
    const body = async () => {
      if (init.body instanceof ReadableStream) return JSON.parse(await new Response(init.body).text());
      return init.body ? JSON.parse(init.body) : null;
    };
    if (method === 'POST' && path === 'git/blobs') {
      const b = await body();
      assert.equal(b.encoding, 'base64');
      const s = sha();
      state.blobs[s] = Buffer.from(b.content, 'base64');
      return reply(201, { sha: s });
    }
    if (method === 'GET' && path === 'git/ref/heads/data-manual') {
      return state.refs['data-manual'] ? reply(200, { object: { sha: state.refs['data-manual'] } }) : reply(404, { message: 'Not Found' });
    }
    if (method === 'GET' && path.startsWith('git/commits/')) {
      const c = state.commits[path.split('/').pop()];
      return c ? reply(200, { tree: { sha: c.tree } }) : reply(404, {});
    }
    if (method === 'GET' && path === 'contents/index.json') {
      const c = state.commits[state.refs['data-manual']];
      const f = c && state.trees[c.tree]['index.json'];
      return f ? reply(200, { content: Buffer.from(f.content).toString('base64') }) : reply(404, {});
    }
    if (method === 'POST' && path === 'git/trees') {
      const b = await body();
      const files = b.base_tree ? { ...state.trees[b.base_tree] } : {};
      for (const e of b.tree) {
        if (e.sha === null) delete files[e.path];
        else files[e.path] = e.content !== undefined ? { content: e.content } : { blob: e.sha };
      }
      const s = sha();
      state.trees[s] = files;
      return reply(201, { sha: s });
    }
    if (method === 'POST' && path === 'git/commits') {
      const b = await body();
      const s = sha();
      state.commits[s] = { tree: b.tree, parents: b.parents, message: b.message };
      return reply(201, { sha: s });
    }
    if (method === 'POST' && path === 'git/refs') {
      const b = await body();
      state.refs['data-manual'] = b.sha;
      return reply(201, {});
    }
    if (method === 'PATCH' && path === 'git/refs/heads/data-manual') {
      const b = await body();
      if (state.conflictOnce) {
        state.conflictOnce = false;
        return reply(422, { message: 'Update is not a fast forward' });
      }
      assert.equal(b.force, false);
      state.refs['data-manual'] = b.sha;
      return reply(200, {});
    }
    if (method === 'POST' && path === 'dispatches') {
      state.dispatches.push(await body());
      return reply(204);
    }
    return reply(500, { message: `no simulado: ${method} ${path}` });
  };
  return state;
}

function tree() {
  const c = gh.commits[gh.refs['data-manual']];
  return gh.trees[c.tree];
}

async function makeEnv(pending = [DOC]) {
  if (!users) {
    users = {
      pablo: { hash: await hashPassword('clave-admin-123'), role: 'admin' },
      revisor01: { hash: await hashPassword('clave-revisor-1'), role: 'tester' },
    };
  }
  return {
    GEO_DB: new FakeD1(),
    GEO_USERS: JSON.stringify(users),
    DOCS_GITHUB_TOKEN: 'token-de-prueba',
    ASSETS: {
      fetch: async (u) => (String(u).endsWith('/data/manual-needed.json')
        ? new Response(JSON.stringify({ version: 1, generatedAt: '2026-10-21T21:00:00+00:00', pending, used: [] }))
        : new Response('', { status: 404 })),
    },
  };
}

async function login(username = 'pablo', password = 'clave-admin-123') {
  const r = await geo(new Request(`${ORIGIN}/api/geo/login`, {
    method: 'POST', headers: { Origin: ORIGIN, 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }),
  }), env);
  return (r.headers.get('Set-Cookie') || '').match(new RegExp(`${COOKIE}=([^;]+)`))[1];
}

function uploadReq(cookie, { doc = DOC.id, pdf = PDF, origin = ORIGIN, raw, sha } = {}) {
  const body = raw !== undefined ? raw : `{"encoding":"base64","content":"${pdf.toString('base64')}"}`;
  const headers = { 'Content-Type': 'application/json', 'X-Doc-Sha256': sha || createHash('sha256').update(pdf).digest('hex'),
    'Content-Length': String(Buffer.byteLength(body)) };
  if (origin) headers.Origin = origin;
  if (cookie) headers.Cookie = `${COOKIE}=${cookie}`;
  return new Request(`${ORIGIN}/api/docs/upload?doc=${encodeURIComponent(doc)}`, { method: 'POST', headers, body, duplex: 'half' });
}

const statusReq = (cookie) => new Request(`${ORIGIN}/api/docs/status`, { headers: { Cookie: `${COOKIE}=${cookie}` } });

beforeEach(async () => {
  env = await makeEnv();
  gh = fakeGitHub();
});

afterEach(() => {
  globalThis.fetch = realFetch;
});

describe('subida de documentos', () => {
  it('guarda el PDF en data-manual con el formato de los recolectores y pide la actualización', async () => {
    const cookie = await login();
    const r = await handle(uploadReq(cookie), env);
    const out = await r.json();
    assert.equal(r.status, 201, JSON.stringify(out));
    assert.equal(out.bytes, PDF.length);
    assert.ok(out.dispatched);
    const files = tree();
    const sha = createHash('sha256').update(PDF).digest('hex');
    const pdf = files[`files/${sha.slice(0, 16)}.pdf`];
    assert.ok(gh.blobs[pdf.blob].equals(PDF), 'el blob es el PDF, sin cambios');
    const index = JSON.parse(files['index.json'].content);
    assert.equal(index.schema, 'enso-relay/1');
    assert.equal(index.collector.kind, 'manual');
    const [e] = index.entries;
    assert.equal(e.url, DOC.urls[0]);
    assert.deepEqual(e.aliases, DOC.urls.slice(1));
    assert.equal(e.sha256, sha);
    assert.equal(e.doc, DOC.id);
    assert.equal(e.uploaded_by, 'pablo');
    assert.deepEqual(gh.dispatches, [{ event_type: 'enso-refresh', client_payload: { reason: 'manual-upload', doc: DOC.id } }]);
    // Primera subida: la rama se crea (commit sin padres).
    assert.deepEqual(gh.commits[gh.refs['data-manual']].parents, []);
    const st = await (await handle(statusReq(cookie), env)).json();
    assert.equal(st.pending.length, 1);
    assert.equal(st.uploads[0].username, 'pablo');
    assert.ok(st.canUpload);
    const audit = env.GEO_DB.sqlite.prepare("SELECT * FROM audit WHERE event = 'documento-subido'").all();
    assert.equal(audit.length, 1);
  });

  it('una segunda subida del mismo documento reemplaza la anterior y quita su archivo', async () => {
    const cookie = await login();
    assert.equal((await handle(uploadReq(cookie), env)).status, 201);
    const other = Buffer.concat([PDF, Buffer.from('% otra versión\n%%EOF\n')]);
    const r = await handle(uploadReq(cookie, { pdf: other }), env);
    assert.equal(r.status, 201);
    const files = tree();
    const pdfs = Object.keys(files).filter((f) => f.endsWith('.pdf'));
    assert.equal(pdfs.length, 1);
    assert.equal(JSON.parse(files['index.json'].content).entries.length, 1);
    assert.equal(gh.commits[gh.refs['data-manual']].parents.length, 1);
  });

  it('si otra subida movió la rama, rehace el commit sobre la nueva punta', async () => {
    const cookie = await login();
    assert.equal((await handle(uploadReq(cookie), env)).status, 201);
    gh.conflictOnce = true;
    const r = await handle(uploadReq(cookie, { pdf: Buffer.concat([PDF, Buffer.from('%%EOF\n')]) }), env);
    assert.equal(r.status, 201);
    assert.equal(gh.calls.filter((c) => c === 'PATCH git/refs/heads/data-manual').length, 2);
  });

  it('rechaza lo que no es un PDF sin mandarlo a GitHub', async () => {
    const cookie = await login();
    const html = Buffer.from('<!doctype html><title>Verificación</title>'.padEnd(3000, ' '));
    const r = await handle(uploadReq(cookie, { pdf: html }), env);
    assert.equal(r.status, 415);
    assert.ok(!gh.calls.includes('POST git/blobs'));
  });

  it('rechaza un PDF cortado (sin %%EOF) y no lo publica', async () => {
    const cookie = await login();
    const cut = PDF.subarray(0, 2000);
    const r = await handle(uploadReq(cookie, { pdf: cut }), env);
    assert.equal(r.status, 415);
    assert.ok(!gh.refs['data-manual']);
  });

  it('solo acepta documentos pendientes', async () => {
    const cookie = await login();
    const r = await handle(uploadReq(cookie, { doc: 'comunicado-99-2026' }), env);
    assert.equal(r.status, 404);
    assert.equal(gh.calls.length, 0);
  });

  it('solo las cuentas con permiso suben (por omisión, administración)', async () => {
    const cookie = await login('revisor01', 'clave-revisor-1');
    assert.equal((await handle(uploadReq(cookie), env)).status, 403);
    const st = await (await handle(statusReq(cookie), env)).json();
    assert.equal(st.canUpload, false);
    env.DOCS_UPLOAD_ROLES = 'admin,tester';
    assert.equal((await handle(uploadReq(cookie), env)).status, 201);
  });

  it('exige sesión, mismo origen y JSON', async () => {
    assert.equal((await handle(uploadReq(null), env)).status, 401);
    const cookie = await login();
    assert.equal((await handle(uploadReq(cookie, { origin: 'https://otro.example' }), env)).status, 403);
    assert.equal((await handle(statusReq('x'.repeat(30)), env)).status, 401);
  });

  it('sin el token configurado avisa en vez de fallar', async () => {
    delete env.DOCS_GITHUB_TOKEN;
    const cookie = await login();
    const r = await handle(uploadReq(cookie), env);
    assert.equal(r.status, 503);
    assert.match((await r.json()).error, /DOCS_GITHUB_TOKEN/);
  });

  it('limita las subidas por hora', async () => {
    const cookie = await login();
    for (let i = 0; i < 10; i++) {
      const pdf = Buffer.concat([PDF, Buffer.from(`% ${i}\n%%EOF\n`)]);
      assert.equal((await handle(uploadReq(cookie, { pdf }), env)).status, 201);
    }
    assert.equal((await handle(uploadReq(cookie), env)).status, 429);
  });

  it('funciona con una base nueva (crea sus tablas)', async () => {
    const cookie = await login();
    env.GEO_DB.sqlite.exec('DROP TABLE IF EXISTS uploads');
    const st = await handle(statusReq(cookie), env);
    assert.equal(st.status, 200);
  });

  it('el índice olvida las copias de más de MAX_AGE_DAYS', () => {
    const old = new Date(Date.parse('2026-10-21T00:00:00Z') - (MAX_AGE_DAYS + 1) * 86400 * 1000).toISOString();
    const index = { entries: [{ doc: 'informe-1-2026', file: 'files/aaaa.pdf', fetched_at: old },
      { doc: 'informe-2-2026', file: 'files/bbbb.pdf', fetched_at: '2026-10-20T00:00:00Z' }] };
    const { entries, removed } = nextEntries(index, { doc: DOC, sha256: 'c'.repeat(64), bytes: 1, username: 'pablo', at: '2026-10-21T00:00:00Z' });
    assert.deepEqual(entries.map((e) => e.doc), [DOC.id, 'informe-2-2026']);
    assert.deepEqual(removed, ['files/aaaa.pdf']);
  });
});

describe('revisión en el navegador', () => {
  const file = (buf) => new File([buf], 'doc.pdf', { type: 'application/pdf' });
  globalThis.FileReader ??= class {
    readAsDataURL(f) {
      f.arrayBuffer().then((b) => {
        this.result = `data:application/pdf;base64,${Buffer.from(b).toString('base64')}`;
        this.onload();
      });
    }
  };

  it('prepara el cuerpo exacto de la API de blobs y el sha256', async () => {
    const { sha, body } = await prepare(file(PDF), 25 * 1024 * 1024);
    assert.equal(sha, createHash('sha256').update(PDF).digest('hex'));
    assert.equal(await body.text(), `{"encoding":"base64","content":"${PDF.toString('base64')}"}`);
  });

  it('reconoce la página de verificación guardada en vez del PDF', async () => {
    await assert.rejects(prepare(file(Buffer.from('<!DOCTYPE html><html>'.padEnd(2000, ' '))), 1e8), /verificación/);
    await assert.rejects(prepare(file(PDF.subarray(0, 3000)), 1e8), /incompleto/);
    await assert.rejects(prepare(file(PDF), 1000), /límite/);
  });
});
