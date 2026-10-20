// Utilidades DOM mínimas y seguras. Todo texto que proviene de datos
// externos pasa por esc() antes de llegar a innerHTML.

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

export function esc(value) {
  if (value === null || value === undefined) return '';
  return String(value).replace(/[&<>"']/g, (c) => ESC[c]);
}

/** Plantilla etiquetada: escapa todas las interpolaciones salvo las marcadas con raw(). */
export function html(strings, ...values) {
  let out = '';
  strings.forEach((s, i) => {
    out += s;
    if (i < values.length) out += toHtml(values[i]);
  });
  return new Raw(out);
}

class Raw {
  constructor(s) { this.s = s; }
  toString() { return this.s; }
}

export function raw(s) { return new Raw(s); }

function toHtml(v) {
  if (v instanceof Raw) return v.s;
  if (Array.isArray(v)) return v.map(toHtml).join('');
  if (v === false || v === null || v === undefined) return '';
  return esc(v);
}

/** Solo permite URLs http(s) o relativas; cualquier otra cosa se neutraliza. */
export function safeUrl(u) {
  if (!u) return '#';
  try {
    const url = new URL(u, document.baseURI);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : '#';
  } catch {
    return '#';
  }
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function storage(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch { /* modo privado o almacenamiento bloqueado */ }
  return null;
}
