// Consola de documentos: subir a mano los PDF que la actualización diaria no puede bajar (verificación humana).
// La lista sale de la API (../api/docs/status), que lee ../data/manual-needed.json; la sesión es la de la consola
// de lugares (../api/geo/). Todo el texto se inserta con textContent.

const HERE = typeof location === 'undefined' ? 'http://localhost/admin/' : location.href; // sin location: pruebas
const DOCS = new URL('../api/docs/', HERE);
const GEO = new URL('../api/geo/', HERE);
const PREFIX = '{"encoding":"base64","content":"';

const $ = (id) => (typeof document === 'undefined' ? null : document.getElementById(id));
const state = { me: null, data: null, busy: false };

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
  return el;
}

const say = (msg) => { $('status').textContent = msg || ''; };

async function call(base, path, { method = 'GET', body, headers = {} } = {}) {
  const r = await fetch(new URL(path, base), {
    method, credentials: 'same-origin', cache: 'no-store', headers, body,
  });
  let data = {};
  try {
    data = await r.json();
  } catch { /* sin JSON: GitHub Pages u otro servidor sin la API */ }
  if (!r.ok) throw Object.assign(new Error(data.error || `Error ${r.status}`), { status: r.status });
  return data;
}

const geo = (path, body) => call(GEO, path, body === undefined ? {} : {
  method: 'POST', body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' },
});

const fmtDate = (s) => {
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? (s || '') : d.toLocaleString('es-PE', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'America/Lima' });
};
const mb = (n) => `${(n / 1024 / 1024).toFixed(1).replace('.', ',')} MB`;
const host = (u) => {
  try {
    return new URL(u).hostname.replace(/^www\./, '');
  } catch {
    return u;
  }
};

// --- Revisión del archivo en el navegador (antes de subir) -----------------------------

/** Comprueba el archivo y lo prepara: PDF de verdad, completo, no más grande que el límite. */
export async function prepare(file, maxBytes) {
  if (!file) throw new Error('Elija el PDF.');
  if (file.size > maxBytes) throw new Error(`El archivo pesa ${mb(file.size)}; el límite es ${mb(maxBytes)}.`);
  if (file.size < 1024) throw new Error('El archivo es demasiado pequeño para ser el documento.');
  const head = new Uint8Array(await file.slice(0, 1024).arrayBuffer());
  const start = new TextDecoder().decode(head.slice(0, 5));
  if (start !== '%PDF-') {
    const text = new TextDecoder().decode(head).toLowerCase();
    if (text.includes('<html') || text.includes('<!doctype')) {
      throw new Error('Ese archivo es una página web (probablemente la verificación), no el PDF. Ábralo de nuevo, pase la verificación y guarde el PDF.');
    }
    throw new Error('Ese archivo no es un PDF.');
  }
  const tail = new TextDecoder().decode(new Uint8Array(await file.slice(Math.max(0, file.size - 2048)).arrayBuffer()));
  if (!tail.includes('%%EOF')) throw new Error('El PDF está incompleto (la descarga se cortó). Vuelva a bajarlo.');
  const buf = await file.arrayBuffer();
  const sha = [...new Uint8Array(await crypto.subtle.digest('SHA-256', buf))].map((b) => b.toString(16).padStart(2, '0')).join('');
  const b64 = await new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result).slice(String(fr.result).indexOf(',') + 1));
    fr.onerror = () => reject(new Error('No se pudo leer el archivo.'));
    fr.readAsDataURL(file);
  });
  return { sha, body: new Blob([PREFIX, b64, '"}'], { type: 'application/json' }) };
}

async function upload(doc, form) {
  const file = form.querySelector('input[type=file]').files[0];
  const err = form.querySelector('.gc-error');
  const btn = form.querySelector('button[type=submit]');
  err.textContent = '';
  if (!form.querySelector('.confirm').checked) {
    err.textContent = 'Confirme que el PDF es el documento indicado.';
    return;
  }
  btn.disabled = true;
  state.busy = true;
  try {
    say('Revisando el archivo…');
    const { sha, body } = await prepare(file, state.data.maxBytes);
    say('Subiendo…');
    const res = await call(DOCS, `upload?doc=${encodeURIComponent(doc.id)}`, {
      method: 'POST', body, headers: { 'Content-Type': 'application/json', 'X-Doc-Sha256': sha },
    });
    form.replaceWith(h('p', { class: 'dc-ok', role: 'status' },
      `Subido (${mb(res.bytes)}). ${res.dispatched ? 'La actualización del sitio ya empezó; en unos 15 minutos se verá el resultado aquí.' : 'No se pudo pedir la actualización: se leerá en la próxima corrida diaria (23:37, hora de Lima).'}`));
    say('');
    try { // la lista de subidas, sin redibujar los pendientes (se perdería el aviso de arriba)
      state.data = await call(DOCS, 'status');
      renderUploads();
    } catch { /* se verá al recargar */ }
  } catch (e) {
    if (e.status === 401) return showLogin('La sesión venció. Ingrese de nuevo.');
    err.textContent = e.message;
    say('');
  } finally {
    btn.disabled = false;
    state.busy = false;
  }
  return null;
}

// --- Vista ---------------------------------------------------------------------------

function pendingItem(doc) {
  const links = (doc.open || []).map((u) => h('a', { class: 'btn btn-small', href: u, target: '_blank', rel: 'noopener noreferrer' }, `Abrir en ${host(u)}`));
  const li = h('li', { class: 'gc-item' },
    h('p', { class: 'gc-meta' }, `Pendiente desde ${doc.since || '—'}`),
    h('h2', {}, doc.label || doc.id),
    h('p', { class: 'gc-summary' }, doc.reason || ''),
    doc.problem ? h('p', { class: 'dc-problem' }, `La última copia subida no se usó: ${doc.problem}`) : null,
    h('div', { class: 'dc-links' }, links));
  if (!state.data.canUpload) {
    li.append(h('p', { class: 'muted small' }, 'Esta cuenta puede ver la lista pero no subir documentos; avise a un administrador.'));
    return li;
  }
  if (!state.data.configured) {
    li.append(h('p', { class: 'dc-problem' }, 'La subida no está configurada todavía (falta el secreto DOCS_GITHUB_TOKEN en Cloudflare).'));
    return li;
  }
  const form = h('form', { class: 'dc-upload' },
    h('label', {}, 'PDF bajado', h('input', { type: 'file', accept: 'application/pdf,.pdf', required: true })),
    h('label', { class: 'dc-check' }, h('input', { type: 'checkbox', class: 'confirm' }),
      h('span', {}, `Confirmo que este PDF es «${doc.label || doc.id}» y que lo bajé de la fuente oficial.`)),
    h('p', { class: 'gc-error', role: 'alert' }),
    h('div', { class: 'gc-actions' }, h('button', { type: 'submit', class: 'btn btn-primary' }, 'Subir PDF')));
  form.addEventListener('submit', (ev) => {
    ev.preventDefault();
    if (!state.busy) upload(doc, form);
  });
  li.append(form);
  return li;
}

function render() {
  const d = state.data;
  const pending = d.pending || [];
  $('count-pending').textContent = `(${pending.length})`;
  $('pending-info').textContent = pending.length
    ? `Lista de la actualización del ${fmtDate(d.generatedAt)}.`
    : `No falta ningún documento (actualización del ${fmtDate(d.generatedAt)}).`;
  $('pending').replaceChildren(...pending.map(pendingItem));
  $('used').replaceChildren(...((d.used || []).length
    ? d.used.map((u) => h('li', { class: 'gc-audit-row' }, `${u.label || u.id}: publicado desde la copia subida el ${fmtDate(u.uploadedAt)}.`))
    : [h('li', { class: 'muted small' }, 'Ninguno en la última actualización.')]));
  renderUploads();
}

function renderUploads() {
  const d = state.data;
  $('uploads').replaceChildren(...((d.uploads || []).length
    ? d.uploads.map((u) => h('li', { class: 'gc-audit-row' },
      `${fmtDate(u.at)} · ${u.username} · ${u.label || u.doc} · ${mb(u.bytes)}${u.dispatched ? '' : ' · sin actualización inmediata'}`))
    : [h('li', { class: 'muted small' }, 'Todavía no se subió ningún documento.')]));
}

function showLogin(msg = '') {
  state.me = null;
  $('session').hidden = true;
  $('app-view').hidden = true;
  $('login-view').hidden = false;
  $('login-error').textContent = msg;
  $('username').focus();
}

async function start() {
  say('Cargando…');
  try {
    state.data = await call(DOCS, 'status');
  } catch (e) {
    if (e.status === 401) return showLogin();
    say(`No se pudo cargar la lista: ${e.message}`);
    return null;
  }
  $('login-view').hidden = true;
  $('app-view').hidden = false;
  $('session').hidden = false;
  $('who').textContent = `${state.me.username}${state.me.role === 'admin' ? ' (administración)' : ''}`;
  say('');
  render();
  return null;
}

async function boot() {
  try {
    state.me = await geo('me');
  } catch (e) {
    if (e.status === 503) return say(e.message);
    if (e.status !== 401) return say('La consola solo funciona en el sitio publicado en Cloudflare (no se encontró su API).');
    return showLogin();
  }
  return start();
}

if (typeof document !== 'undefined' && $('login-form')) {
  $('login-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const btn = ev.submitter || $('login-form').querySelector('button');
    btn.disabled = true;
    $('login-error').textContent = '';
    try {
      state.me = await geo('login', { username: $('username').value, password: $('password').value });
      $('password').value = '';
      await start();
    } catch (e) {
      $('login-error').textContent = e.message;
    } finally {
      btn.disabled = false;
    }
  });
  $('logout').addEventListener('click', async () => {
    try {
      await geo('logout', {});
    } catch { /* igual se sale */ }
    showLogin('Sesión cerrada.');
  });
  boot();
}
