// Consola de documentos: subir a mano los PDF que ninguna ruta automática trae (python/enso/manual.py).
//
// La réplica de la DHN pide verificación humana a GitHub Actions, a n8n y a veces al equipo del Perú. El pipeline
// anota en data/manual-needed.json lo que le falta; una persona lo abre en su navegador, pasa la verificación ella
// misma, baja el PDF y lo sube aquí. Esta API lo guarda en la rama data-manual con el formato de los recolectores
// (enso-relay/1, canal «relay-manual») y pide una actualización del sitio. El pipeline lo lee con la misma URL que
// buscaba y lo valida como cualquier otra copia: si no es el documento esperado, no se publica.
//
// Rutas, bajo /api/docs/ (con la sesión de la consola de lugares, functions/_lib/geo-console.js):
//
//   GET  status            pendientes (de data/manual-needed.json), últimas subidas y si esta cuenta puede subir
//   POST upload?doc=<id>   cuerpo {"encoding":"base64","content":"<PDF en base64>"}, cabecera X-Doc-Sha256
//
// El plan gratuito de Workers da 10 ms de CPU por solicitud: el PDF (hasta 25 MB) no se decodifica ni se copia
// aquí. El navegador lo codifica en base64 con el formato exacto de la API de blobs de GitHub y esta función lo
// pasa en flujo a GitHub, mirando solo el principio (%PDF-) y el final (%%EOF). El sha256 lo calcula el
// navegador; el pipeline lo vuelve a calcular y descarta la copia si no coincide.
//
// Secretos y variables (panel de Cloudflare Pages → Settings → Variables and Secrets):
//   DOCS_GITHUB_TOKEN   token de grano fino con Contents: Read and write solo en este repositorio
//   DOCS_GITHUB_REPO    «dueño/repositorio» (por omisión PillB/observatorio-enso-peru)
//   DOCS_UPLOAD_ROLES   roles que pueden subir, separados por comas (por omisión «admin»)

import {
  auditStmt, bumpStmt, clientIp, currentSession, ensureSchema, fail, json, noTable, nowIso,
} from './geo-console.js';

export const BRANCH = 'data-manual';
export const MAX_PDF_BYTES = 20 * 1024 * 1024; // el mismo límite que la copia archivada (enso.archive.MAX_BYTES)
export const MAX_AGE_DAYS = 120; // como enso.manual.MAX_AGE_DAYS: las copias más viejas se quitan del índice
const UPLOADS_MAX_HOUR = 10;
const UPLOAD_WINDOW_S = 3600;
const PREFIX = '{"encoding":"base64","content":"';
const PDF_B64 = 'JVBERi0'; // «%PDF-» en base64
const DOC_RE = /^[a-z0-9][a-z0-9-]{2,80}$/;
const SHA_RE = /^[0-9a-f]{64}$/;
const API = 'https://api.github.com';

const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS uploads (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT NOT NULL, label TEXT,
     sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, username TEXT NOT NULL, created_at TEXT NOT NULL,
     commit_sha TEXT, dispatched INTEGER NOT NULL DEFAULT 0)`,
];

const dec = new TextDecoder();
const epoch = () => Math.floor(Date.now() / 1000);

class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

export function uploadRoles(env) {
  return String(env.DOCS_UPLOAD_ROLES || 'admin').split(',').map((r) => r.trim()).filter(Boolean);
}

async function pendingList(env, url) {
  try {
    const r = env.ASSETS ? await env.ASSETS.fetch(new URL('/data/manual-needed.json', url)) : null;
    if (r && r.ok) {
      const data = await r.json();
      return { pending: Array.isArray(data.pending) ? data.pending : [], used: Array.isArray(data.used) ? data.used : [],
        generatedAt: data.generatedAt || null };
    }
  } catch { /* abajo */ }
  return { pending: [], used: [], generatedAt: null };
}

// Lecturas de antes de tocar el cuerpo: si la base es nueva, se crean las tablas y se repite (el cuerpo todavía no
// se leyó, así que repetir es seguro).
async function withSchema(env, fn) {
  try {
    return await fn();
  } catch (e) {
    if (!noTable(e)) throw e;
    await ensureSchema(env.GEO_DB);
    await env.GEO_DB.batch(SCHEMA.map((s) => env.GEO_DB.prepare(s)));
    return fn();
  }
}

async function status(env, url, session) {
  const { results } = await env.GEO_DB.prepare(`SELECT doc_id, label, sha256, bytes, username, created_at, commit_sha, dispatched
      FROM uploads ORDER BY id DESC LIMIT 30`).all();
  const list = await pendingList(env, url);
  return json({
    ...list,
    uploads: results.map((r) => ({ doc: r.doc_id, label: r.label, sha256: r.sha256, bytes: r.bytes, username: r.username,
      at: r.created_at, commit: r.commit_sha, dispatched: !!r.dispatched })),
    canUpload: uploadRoles(env).includes(session.role),
    configured: !!env.DOCS_GITHUB_TOKEN,
    ...(env.DOCS_GITHUB_TOKEN ? await tokenCheck(env) : {}),
    maxBytes: MAX_PDF_BYTES,
  });
}

/** ¿Sirve el token y cuándo vence? Se mira al abrir la consola, no recién cuando urge subir un documento. */
export async function tokenCheck(env) {
  const repo = env.DOCS_GITHUB_REPO || 'PillB/observatorio-enso-peru';
  try {
    const r = await fetch(`${API}/repos/${repo}`, {
      headers: { Authorization: `Bearer ${env.DOCS_GITHUB_TOKEN}`, Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'enso-consola-documentos' },
    });
    const expires = r.headers.get('github-authentication-token-expiration') || '';
    return { tokenOk: r.status === 200, tokenStatus: r.status,
      ...(expires ? { tokenExpiresAt: new Date(expires.replace(' UTC', 'Z').replace(' ', 'T')).toISOString() } : {}) };
  } catch (err) {
    return { tokenOk: null, tokenStatus: 0 }; // GitHub no respondió: no se sabe
  }
}

// --- GitHub --------------------------------------------------------------------------

function gh(env) {
  const repo = env.DOCS_GITHUB_REPO || 'PillB/observatorio-enso-peru';
  const headers = {
    Authorization: `Bearer ${env.DOCS_GITHUB_TOKEN}`,
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'User-Agent': 'enso-consola-documentos',
  };
  const call = async (method, path, body, extra = {}) => {
    const r = await fetch(`${API}/repos/${repo}/${path}`, {
      method, headers: { ...headers, ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...extra },
      body: body === undefined ? undefined : body instanceof ReadableStream ? body : JSON.stringify(body),
      ...(body instanceof ReadableStream ? { duplex: 'half' } : {}),
    });
    let data = null;
    try {
      data = r.status === 204 ? null : await r.json();
    } catch { /* sin JSON */ }
    return { status: r.status, data };
  };
  return { call, headers };
}

/** Pasa el cuerpo a la API de blobs de GitHub sin decodificarlo: revisa el principio, el final y el largo. */
async function streamBlob(env, request, length) {
  const reader = request.body.getReader();
  // Lo primero: el formato exacto y la firma del PDF, antes de mandar nada a GitHub.
  const head = [];
  let headLen = 0;
  while (headLen < PREFIX.length + PDF_B64.length) {
    const { value, done } = await reader.read();
    if (done) break;
    head.push(value);
    headLen += value.length;
  }
  const first = dec.decode(concat(head, headLen).slice(0, PREFIX.length + PDF_B64.length));
  if (first !== PREFIX + PDF_B64) {
    reader.cancel().catch(() => {});
    throw new HttpError(415, 'El archivo no es un PDF (debe empezar con %PDF-).');
  }
  let tail = new Uint8Array(0);
  let seen = 0;
  // Solo los últimos bytes, sin copiar cada trozo entero (CPU).
  const TAIL = 1400;
  const keepTail = (chunk) => {
    seen += chunk.length;
    if (chunk.length >= TAIL) {
      tail = chunk.slice(chunk.length - TAIL);
      return;
    }
    const joined = concat([tail, chunk], tail.length + chunk.length);
    tail = joined.slice(Math.max(0, joined.length - TAIL));
  };
  const Fixed = globalThis.FixedLengthStream;
  const { readable, writable } = Fixed ? new Fixed(length) : new TransformStream();
  const writer = writable.getWriter();
  const pump = (async () => {
    try {
      for (const c of head) {
        keepTail(c);
        await writer.write(c);
      }
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        if (seen + value.length > length) throw new HttpError(400, 'El cuerpo es más largo de lo anunciado.');
        keepTail(value);
        await writer.write(value);
      }
      if (seen !== length) throw new HttpError(400, 'El cuerpo llegó incompleto.');
      await writer.close();
    } catch (e) {
      await writer.abort(e).catch(() => {});
      throw e;
    }
  })();
  const { call } = gh(env);
  const [res] = await Promise.all([call('POST', 'git/blobs', readable), pump]);
  if (res.status !== 201 || !res.data || !res.data.sha) {
    throw new HttpError(502, `GitHub no guardó el archivo (HTTP ${res.status}).`);
  }
  // El final: «"}» y, en los últimos bytes del PDF, «%%EOF» (un PDF cortado no lo trae).
  const t = dec.decode(tail);
  if (!t.endsWith('"}')) throw new HttpError(400, 'Formato de envío inválido.');
  const body = t.slice(0, -2);
  const b64 = body.slice(body.lastIndexOf('"') + 1);
  const aligned = b64.slice(b64.length % 4);
  let end = '';
  try {
    end = atob(aligned);
  } catch {
    throw new HttpError(400, 'El contenido no es base64 válido.');
  }
  if (!end.includes('%%EOF')) throw new HttpError(415, 'El PDF está incompleto (no termina en %%EOF): vuelva a bajarlo.');
  const pad = b64.endsWith('==') ? 2 : b64.endsWith('=') ? 1 : 0;
  return { blob: res.data.sha, bytes: pdfBytes(length - PREFIX.length - 2) - pad };
}

function concat(parts, total) {
  const out = new Uint8Array(total);
  let o = 0;
  for (const p of parts) {
    out.set(p, o);
    o += p.length;
  }
  return out;
}

const pdfBytes = (b64Len) => Math.floor((b64Len * 3) / 4);

/** Commit en data-manual con el PDF y el índice; crea la rama la primera vez. Repite una vez si alguien ganó. */
export async function commitUpload(env, { blob, sha256, bytes, doc, uploader, at }) {
  const { call } = gh(env);
  for (let attempt = 0; attempt < 2; attempt++) {
    const ref = await call('GET', `git/ref/heads/${BRANCH}`);
    let parent = null;
    let baseTree = null;
    let index = null;
    if (ref.status === 200) {
      parent = ref.data.object.sha;
      const c = await call('GET', `git/commits/${parent}`);
      if (c.status !== 200) throw new HttpError(502, `GitHub no dio el último commit (HTTP ${c.status}).`);
      baseTree = c.data.tree.sha;
      const idx = await call('GET', `contents/index.json?ref=${encodeURIComponent(BRANCH)}`);
      if (idx.status === 200 && idx.data && idx.data.content) {
        try {
          index = JSON.parse(dec.decode(Uint8Array.from(atob(idx.data.content.replace(/\s/g, '')), (ch) => ch.charCodeAt(0))));
        } catch {
          index = null;
        }
      }
    } else if (ref.status !== 404) {
      throw new HttpError(502, `GitHub no respondió por la rama ${BRANCH} (HTTP ${ref.status}).`);
    }
    const { entries, removed } = nextEntries(index, { doc, sha256, bytes, uploader, at });
    const file = `files/${sha256.slice(0, 16)}.pdf`;
    const newIndex = {
      schema: 'enso-relay/1', collected_at: at,
      collector: { kind: 'manual', host: 'consola de documentos' },
      entries, summary: { manual: `${entries.length}/${entries.length}` },
    };
    const tree = [
      { path: file, mode: '100644', type: 'blob', sha: blob },
      { path: 'index.json', mode: '100644', type: 'blob', content: `${JSON.stringify(newIndex, null, 1)}\n` },
      ...(baseTree ? removed.filter((f) => f !== file).map((f) => ({ path: f, mode: '100644', type: 'blob', sha: null })) : []),
    ];
    const t = await call('POST', 'git/trees', baseTree ? { base_tree: baseTree, tree } : { tree });
    if (t.status !== 201) throw new HttpError(502, `GitHub no armó el árbol (HTTP ${t.status}).`);
    const c = await call('POST', 'git/commits', {
      message: `Documento subido a mano: ${doc.label || doc.id} (${uploader})`, tree: t.data.sha, parents: parent ? [parent] : [],
    });
    if (c.status !== 201) throw new HttpError(502, `GitHub no creó el commit (HTTP ${c.status}).`);
    const u = parent
      ? await call('PATCH', `git/refs/heads/${BRANCH}`, { sha: c.data.sha, force: false })
      : await call('POST', 'git/refs', { ref: `refs/heads/${BRANCH}`, sha: c.data.sha });
    if (u.status === 200 || u.status === 201) return c.data.sha;
    if (u.status !== 422 || attempt) throw new HttpError(502, `GitHub no actualizó la rama ${BRANCH} (HTTP ${u.status}).`);
    // 422: otra subida movió la rama mientras tanto; se rehace sobre la nueva punta.
  }
  throw new HttpError(502, 'No se pudo guardar el documento.');
}

/** Índice nuevo: la subida nueva, sin las anteriores del mismo documento ni las que pasaron MAX_AGE_DAYS. */
// La rama data-manual es pública: lleva el rol de quien subió, no su usuario (que queda en D1, en «uploads» y en
// el registro de la consola).
export function nextEntries(index, { doc, sha256, bytes, uploader, at }) {
  const limit = Date.parse(at) - MAX_AGE_DAYS * 86400 * 1000;
  const old = Array.isArray(index && index.entries) ? index.entries : [];
  const keep = old.filter((e) => e && e.doc !== doc.id && Date.parse(e.fetched_at || 0) >= limit);
  const used = new Set(keep.map((e) => e.file));
  const removed = [...new Set(old.map((e) => e && e.file).filter((f) => f && !used.has(f)))];
  const [url, ...aliases] = doc.urls;
  const entry = {
    url, aliases, status: 200, content_type: 'application/pdf', detected: 'pdf', class: 'ok', group: 'manual',
    file: `files/${sha256.slice(0, 16)}.pdf`, sha256, bytes, fetched_at: at, doc: doc.id, label: doc.label || doc.id,
    uploaded_by: uploader,
  };
  return { entries: [entry, ...keep], removed };
}

async function upload(request, env, url, session, ip) {
  if (!uploadRoles(env).includes(session.role)) return fail(403, 'Esta cuenta no puede subir documentos.');
  if (!env.DOCS_GITHUB_TOKEN) return fail(503, 'Falta configurar el secreto DOCS_GITHUB_TOKEN en Cloudflare.');
  const docId = url.searchParams.get('doc') || '';
  if (!DOC_RE.test(docId)) return fail(400, 'Documento inválido.');
  const sha256 = String(request.headers.get('X-Doc-Sha256') || '').toLowerCase();
  if (!SHA_RE.test(sha256)) return fail(400, 'Falta el sha256 del archivo.');
  const length = Number(request.headers.get('Content-Length') || 0);
  if (!Number.isInteger(length) || length <= PREFIX.length + 2) return fail(411, 'Falta el largo del archivo.');
  if (pdfBytes(length - PREFIX.length - 2) > MAX_PDF_BYTES + 2) return fail(413, `El PDF pesa más de ${MAX_PDF_BYTES / 1024 / 1024} MB.`);
  if (!request.body) return fail(400, 'Falta el archivo.');
  const { pending } = await pendingList(env, url);
  const doc = pending.find((p) => p && p.id === docId);
  // Solo lo que el pipeline pidió: así nadie puede publicar un archivo bajo una URL cualquiera.
  if (!doc || !Array.isArray(doc.urls) || !doc.urls.length) {
    return fail(404, 'Ese documento ya no está pendiente. Recargue la lista.');
  }
  const db = env.GEO_DB;
  const writeKey = `upload:${session.username}`;
  const now = epoch();
  const st = await withSchema(env, () => db.prepare(`SELECT (SELECT count FROM attempts WHERE key = ? AND window_start > ?) AS n,
      (SELECT COUNT(*) FROM uploads WHERE doc_id = ?) AS prior`).bind(writeKey, now - UPLOAD_WINDOW_S, docId).first());
  if (st && st.n >= UPLOADS_MAX_HOUR) return fail(429, 'Demasiadas subidas en una hora.');

  const { blob, bytes } = await streamBlob(env, request, length);
  const at = nowIso();
  const commit = await commitUpload(env, { blob, sha256, bytes, doc, uploader: `rol ${session.role}`, at });
  const { call } = gh(env);
  const d = await call('POST', 'dispatches', { event_type: 'enso-refresh', client_payload: { reason: 'manual-upload', doc: docId } });
  const dispatched = d.status === 204;
  await db.batch([
    db.prepare(`INSERT INTO uploads (doc_id, label, sha256, bytes, username, created_at, commit_sha, dispatched)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)`).bind(docId, String(doc.label || '').slice(0, 200), sha256, bytes, session.username, at, commit, dispatched ? 1 : 0),
    bumpStmt(db, writeKey, UPLOAD_WINDOW_S, now),
    auditStmt(db, session.username, 'documento-subido', ip, null, { doc: docId, sha256, bytes, commit, dispatched }),
  ]);
  return json({ doc: docId, sha256, bytes, commit, dispatched, at }, 201);
}

export async function handle(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/^\/api\/docs\/?/, '').replace(/\/$/, '');
  const method = request.method;
  try {
    if (!env.GEO_DB) return fail(503, 'La consola no está configurada todavía (falta la base de datos GEO_DB).');
    const routes = { status: ['GET'], upload: ['POST'] };
    if (!routes[path]) return fail(404, 'No existe.');
    if (!routes[path].includes(method)) return fail(405, 'Método no permitido.', { Allow: routes[path].join(', ') });
    if (method === 'POST') {
      // Solo desde la propia consola (CSRF): mismo origen y el formato JSON de la API de blobs.
      const origin = request.headers.get('Origin');
      const site = request.headers.get('Sec-Fetch-Site');
      if (origin ? origin !== url.origin : site !== 'same-origin') return fail(403, 'Origen no permitido.');
      if (!(request.headers.get('Content-Type') || '').toLowerCase().startsWith('application/json')) return fail(415, 'Se espera JSON.');
    }
    const session = await withSchema(env, () => currentSession(request, env));
    if (!session) return fail(401, 'Inicie sesión.');
    const ip = clientIp(request);
    if (path === 'status') return await withSchema(env, () => status(env, url, session));
    return await upload(request, env, url, session, ip);
  } catch (e) {
    if (e instanceof HttpError) return fail(e.status, e.message);
    console.error('doc-uploads', e && e.stack ? e.stack : e);
    return fail(500, 'Error interno. Intente de nuevo.');
  }
}
