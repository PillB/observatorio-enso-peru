// Versiones del mapa de alertas («Versión A / B / C / D») y su analítica anónima.
//
// La primera visita recibe una versión al azar; si la persona elige otra en el selector, esa queda como su
// versión de siempre (localStorage, en su navegador). Al salir de la página se manda un solo aviso a
// /api/ab/e con la versión y lo que hizo en esta visita (la vio, pasó el cursor, filtró, abrió un aviso).
// No se manda ni se guarda nada que identifique a la persona: el servidor solo suma contadores por día.
// Con «No rastrear» o Global Privacy Control activados no se manda nada.

import { storage } from './lib/dom.js';

export const VARIANTS = [
  ['A', 'Semáforo por departamento'],
  ['B', 'Pulsos por lugar'],
  ['C', 'Panel: mapa y matriz'],
  ['D', 'Cronología de avisos'],
];
const IDS = VARIANTS.map(([v]) => v);
const KEY = 'enso-mapa-version';
const ENDPOINT = 'api/ab/e';

const day = () => new Date().toISOString().slice(0, 10);

function read() {
  try {
    const s = JSON.parse(storage(KEY) || 'null');
    return s && IDS.includes(s.v) ? s : null;
  } catch { return null; }
}
const write = (s) => storage(KEY, JSON.stringify(s));

function allowed() {
  if (navigator.globalPrivacyControl || navigator.doNotTrack === '1' || window.doNotTrack === '1') return false;
  // El espejo en GitHub Pages no tiene Functions: no se manda nada que fallaría.
  return location.protocol === 'https:' && !/\.github\.io$/.test(location.hostname);
}

function send(v, events) {
  if (!events.length || !allowed()) return;
  const body = JSON.stringify({ v, e: events });
  try {
    if (!navigator.sendBeacon?.(ENDPOINT, new Blob([body], { type: 'text/plain' }))) {
      fetch(ENDPOINT, { method: 'POST', body, keepalive: true, headers: { 'Content-Type': 'text/plain' } }).catch(() => {});
    }
  } catch { /* la analítica nunca rompe la página */ }
}

class Session {
  constructor() {
    const forced = new URLSearchParams(location.hash.split('?')[1] || '').get('version');
    let s = read();
    if (!s) {
      s = { v: IDS[Math.floor(Math.random() * IDS.length)], chosen: false, at: day() };
      write(s);
    }
    this.state = s;
    // ?version=B en el enlace muestra esa versión sin cambiar la elegida (para enseñarla a alguien).
    this.preview = forced && IDS.includes(forced.toUpperCase()) ? forced.toUpperCase() : null;
    this.flags = new Set();
    this.viewed = false;
    if (!this.preview && s.chosen && s.at !== day() && s.lastKeep !== day()) {
      this.flags.add('keep');
      write({ ...s, lastKeep: day() });
    }
    const flush = () => this.flush();
    addEventListener('pagehide', flush);
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') flush(); });
  }

  get variant() { return this.preview || this.state.v; }
  get chosen() { return !this.preview && this.state.chosen; }

  /** Marca un evento de esta visita (cada uno cuenta una vez por visita). */
  mark(e) {
    if (this.preview) return;
    if (e === 'view') {
      if (this.viewed) return;
      this.viewed = true;
      if (this.state.chosen) this.flags.add('chosen');
    }
    this.flags.add(e);
  }

  choose(v) {
    if (!IDS.includes(v) || v === this.variant) return;
    const old = this.state.v;
    this.preview = null;
    if (old !== v) send(old, ['leave']);
    this.flush();
    this.state = { v, chosen: true, at: day() };
    write(this.state);
    this.viewed = false;
    this.mark('choose');
    this.mark('view');
  }

  flush() {
    if (!this.flags.size) return;
    send(this.state.v, [...this.flags]);
    this.flags.clear();
  }
}

let session;
export function ab() {
  if (!session) session = new Session();
  return session;
}

/** Resultados para la vista #/variantes. */
export async function stats(days = 30) {
  try {
    const r = await fetch(`api/ab/stats?days=${days}`, { cache: 'no-store' });
    if (!r.ok) return null;
    return await r.json();
  } catch { return null; }
}
