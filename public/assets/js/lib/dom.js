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

/**
 * Un tooltip de mapa que cae encima de la ventana del tutorial (tour.js) se muda al otro lado del punto (debajo,
 * encima o a un costado), dentro de la pantalla. La ventana del tutorial no se mueve por él: el tutorial la puso
 * junto a lo que explica.
 */
export function clearOfTour(tip, x, y) {
  const pop = document.querySelector('.tour-pop:not(.tour-moving)');
  if (!pop || tip.hidden) return;
  const P = pop.getBoundingClientRect();
  const hit = (l, t, w, h) => l < P.right && P.left < l + w && t < P.bottom && P.top < t + h;
  const tw = tip.offsetWidth, th = tip.offsetHeight, vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;
  const cur = [parseFloat(tip.style.left) || 0, parseFloat(tip.style.top) || 0];
  if (!hit(cur[0], cur[1], tw, th)) return;
  const cx = Math.max(8, Math.min(vw - tw - 8, x - tw / 2)), cy = Math.max(8, Math.min(vh - th - 8, y - th / 2));
  const spots = [[cx, y + 24], [cx, y - th - 24], [x + 18, cy], [x - tw - 18, cy]];
  const ok = spots.find(([l, t]) => l >= 8 && t >= 8 && l + tw <= vw - 8 && t + th <= vh - 8 && !hit(l, t, tw, th));
  if (ok) { tip.style.left = `${ok[0]}px`; tip.style.top = `${ok[1]}px`; }
}
