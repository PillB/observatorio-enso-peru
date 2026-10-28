// Versiones de los mapas y su analítica anónima. Tres experimentos (functions/_lib/ab.js):
//
//   mapa      la versión del mapa de alertas de Noticias («Versión A / B / C / D»)
//   memoria   la vista con que abre el mapa de la memoria: el resumen por área o uno de sus detalles
//   noticias  la vista con que abre el mapa de Noticias: el resumen (la versión A–D) o uno de sus detalles
//
// La primera visita recibe una versión de cada uno: al azar mientras no haya una ganadora; si ya la hay
// (/api/ab/defaults: la que más se usa, con su intervalo), la ganadora a 4 de cada 5 personas y otra al azar al
// resto, para seguir midiendo. Si la persona elige otra, esa queda como su versión de siempre (localStorage, en su
// navegador). Al salir de la página se manda un solo aviso por experimento a /api/ab/e con la versión y lo que hizo
// en esta visita (la vio, pasó el cursor, filtró, abrió algo). No se manda ni se guarda nada que identifique a la
// persona: el servidor solo suma contadores por día. Con «No rastrear» o Global Privacy Control activados no se
// manda nada.

import { storage } from './lib/dom.js';

export const EXPERIMENTS = {
  mapa: {
    key: 'enso-mapa-version',
    variants: [['A', 'Semáforo por departamento'], ['B', 'Pulsos por lugar'], ['C', 'Panel: mapa y matriz'], ['D', 'Cronología de avisos']],
  },
  memoria: {
    key: 'enso-vista-memoria',
    variants: [['resumen', 'Resumen por área'], ['cuencas', 'Detalle: cuencas'], ['puntos', 'Detalle: ríos y lugares'], ['riesgo', 'Detalle: daños y pobreza']],
  },
  noticias: {
    key: 'enso-vista-noticias',
    variants: [['resumen', 'Resumen (versión A–D)'], ['cuencas', 'Detalle: avisos por cuenca'], ['distritos', 'Detalle: distritos y su historia']],
  },
};
export const VARIANTS = EXPERIMENTS.mapa.variants;
/** Parte de las primeras visitas que recibe la versión ganadora; el resto, otra al azar. */
export const EXPLOIT = 0.8;
const ENDPOINT = 'api/ab/e';
const DEFAULTS_KEY = 'enso-ab-ganadoras';

const day = () => new Date().toISOString().slice(0, 10);
const ids = (exp) => EXPERIMENTS[exp].variants.map(([v]) => v);

function read(exp) {
  try {
    const s = JSON.parse(storage(EXPERIMENTS[exp].key) || 'null');
    return s && ids(exp).includes(s.v) ? s : null;
  } catch { return null; }
}
const write = (exp, s) => storage(EXPERIMENTS[exp].key, JSON.stringify(s));

/** Hay servidor de analítica: el sitio publicado en Cloudflare (el espejo en GitHub Pages no tiene Functions). */
const hasBackend = () => location.protocol === 'https:' && !/\.github\.io$/.test(location.hostname);

function allowed() {
  if (navigator.globalPrivacyControl || navigator.doNotTrack === '1' || window.doNotTrack === '1') return false;
  return hasBackend();
}

function send(exp, v, events) {
  if (!events.length || !allowed()) return;
  const body = JSON.stringify({ x: exp, v, e: events });
  try {
    if (!navigator.sendBeacon?.(ENDPOINT, new Blob([body], { type: 'text/plain' }))) {
      fetch(ENDPOINT, { method: 'POST', body, keepalive: true, headers: { 'Content-Type': 'text/plain' } }).catch(() => {});
    }
  } catch { /* la analítica nunca rompe la página */ }
}

/** Ganadoras guardadas hoy (de /api/ab/defaults), o null. */
function cachedWinners() {
  try {
    const s = JSON.parse(storage(DEFAULTS_KEY) || 'null');
    return s && s.at === day() && s.d && typeof s.d === 'object' ? s.d : null;
  } catch { return null; }
}

let READY = null;
/**
 * Pide las ganadoras una vez al día, antes de asignar versiones a una primera visita. Nunca demora el mapa más de
 * ``ms``: sin respuesta, se asigna al azar. No manda nada de la persona (es un GET sin cuerpo, cacheado en el borde).
 */
export function abReady(ms = 1200) {
  if (READY) return READY;
  if (cachedWinners() || !hasBackend() || Object.keys(EXPERIMENTS).every((x) => read(x))) return (READY = Promise.resolve());
  const get = fetch('api/ab/defaults', { cache: 'default' }).then((r) => (r.ok ? r.json() : null))
    .then((d) => { if (d && typeof d === 'object') storage(DEFAULTS_KEY, JSON.stringify({ at: day(), d })); })
    .catch(() => {});
  READY = Promise.race([get, new Promise((res) => setTimeout(res, ms))]);
  return READY;
}

/** La versión de una primera visita: la ganadora con probabilidad EXPLOIT, si la hay; si no, una al azar. */
export function assign(exp, winner = null, rnd = Math.random) {
  const all = ids(exp);
  if (!winner || !all.includes(winner)) return all[Math.floor(rnd() * all.length)];
  if (rnd() < EXPLOIT) return winner;
  const rest = all.filter((v) => v !== winner);
  return rest[Math.floor(rnd() * rest.length)];
}

class Session {
  constructor(exp) {
    this.exp = exp;
    const forced = exp === 'mapa' ? new URLSearchParams(location.hash.split('?')[1] || '').get('version') : null;
    let s = read(exp);
    if (!s) {
      s = { v: assign(exp, cachedWinners()?.[exp]), chosen: false, at: day() };
      write(exp, s);
    }
    this.state = s;
    // ?version=B en el enlace muestra esa versión sin cambiar la elegida (para enseñarla a alguien).
    this.preview = null;
    if (forced) this.show(forced.toUpperCase());
    this.flags = new Set();
    this.viewed = false;
    if (s.chosen && s.at !== day() && s.lastKeep !== day() && !this.preview) {
      this.flags.add('keep');
      write(exp, { ...s, lastKeep: day() });
    }
    const flush = () => this.flush();
    addEventListener('pagehide', flush);
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') flush(); });
  }

  get variant() { return this.preview || this.state.v; }
  /** La versión de esta persona (la que vería sin el enlace que está mirando). */
  get own() { return this.state.v; }
  get chosen() { return !this.preview && this.state.chosen; }
  get variants() { return EXPERIMENTS[this.exp].variants; }

  /** Muestra otra versión sin contarla ni cambiar la elegida (un enlace que alguien compartió). */
  show(v) {
    this.preview = ids(this.exp).includes(v) && v !== this.state.v ? v : null;
  }

  /** Marca un evento de esta visita (cada uno cuenta una vez por visita). */
  mark(e) {
    if (this.preview) return;
    if (e === 'view') {
      if (this.viewed) return;
      this.viewed = true;
      if (this.state.chosen) this.flags.add('chosen');
    }
    this.flags.add(e);
    if (e === 'select' || e === 'detail') this.flags.add('use');
  }

  choose(v) {
    if (!ids(this.exp).includes(v) || v === this.variant) return;
    const old = this.state.v;
    this.preview = null;
    if (old !== v) send(this.exp, old, ['leave']);
    this.flush();
    this.state = { v, chosen: true, at: day() };
    write(this.exp, this.state);
    this.viewed = false;
    this.mark('choose');
    this.mark('view');
  }

  flush() {
    if (!this.flags.size) return;
    send(this.exp, this.state.v, [...this.flags]);
    this.flags.clear();
  }
}

const sessions = {};
export function ab(exp = 'mapa') {
  if (!EXPERIMENTS[exp]) throw new Error(`experimento desconocido: ${exp}`);
  if (!sessions[exp]) sessions[exp] = new Session(exp);
  return sessions[exp];
}

/** Resultados para la vista #/variantes. */
export async function stats(days = 30) {
  try {
    const r = await fetch(`api/ab/stats?days=${days}`, { cache: 'no-store' });
    if (!r.ok) return null;
    return await r.json();
  } catch { return null; }
}
