// Versiones de los mapas y su analítica anónima. Cuatro experimentos (functions/_lib/ab.js):
//
//   mapa      la versión del mapa de alertas de Noticias («Versión A / B / C / D»)
//   memoria   la vista con que abre el mapa de la memoria: el resumen por área o uno de sus detalles
//   noticias  la vista con que abre el mapa de Noticias: el resumen (la versión A–D) o uno de sus detalles
//   boletin   la forma del Boletín: hoja con el mapa del Perú, hoja con el mosaico (el del correo) o ficha de impacto
//
// La primera visita recibe una versión de cada uno: al azar mientras no haya una ganadora; si ya la hay
// (/api/ab/defaults: la que más se usa, con su intervalo), la ganadora a 4 de cada 5 personas y al resto una al azar
// entre todas (la ganadora incluida), para seguir midiendo con una muestra equilibrada. Si la persona elige otra, esa queda como su versión de siempre (localStorage, en su
// navegador). Al salir de la página se manda un solo aviso por experimento a /api/ab/e con la versión y lo que hizo
// en esta visita (la vio, pasó el cursor, filtró, abrió algo). No se manda ni se guarda nada que identifique a la
// persona: el servidor solo suma contadores por día. Con «No rastrear» o Global Privacy Control activados no se
// manda nada.
//
// La decisión no usa todas las visitas: usa solo la primera visita de cada navegador cuya versión salió del sorteo
// parejo (rview / ruse, por intención de tratar: cuenta para la versión sorteada aunque la persona cambie de versión
// en esa misma visita). Las visitas de quien ya eligió, las que llegan con un enlace que fija la vista y las de quien
// vuelve no entran: no son una muestra al azar ni independiente (docs/mapa-alertas.md, «Analítica anónima»).

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
  boletin: {
    key: 'enso-vista-boletin',
    variants: [['mapa', 'A · Hoja con el mapa del Perú'], ['mosaico', 'B · Hoja con el mosaico de cuadros (como en el correo)'], ['ficha', 'C · Ficha de impacto: estado, cuándo y qué hacer']],
  },
  noticias: {
    key: 'enso-vista-noticias',
    variants: [['resumen', 'Resumen (versión A–D)'], ['cuencas', 'Detalle: avisos por cuenca'], ['distritos', 'Detalle: distritos y su historia']],
  },
  // La versión de todo el sitio (sitio.js): A, las pestañas en una fila y todo desplegado; B, cinco secciones con
  // submenús y lo largo plegado. Sin servidor de analítica (en local, en GitHub Pages) se ve la A si la persona no
  // eligió otra: así las pruebas y el espejo no cambian solos. ?sitio=B en el enlace la muestra sin elegirla.
  sitio: {
    key: 'enso-version-sitio',
    variants: [['A', 'Clásica: todas las pestañas a la vista'], ['B', 'Agrupada: secciones con submenús y lo largo plegado']],
    param: 'sitio',
    local: 'A',
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
// Las pruebas de navegador con el servidor de mentira (http://localhost) lo afirman con ENSO_BACKEND.
const hasBackend = () => globalThis.ENSO_BACKEND === true || (location.protocol === 'https:' && !/\.github\.io$/.test(location.hostname));

/** La persona pidió no participar (selector de versiones), o su navegador pide no rastrear. */
export const OPT_OUT_KEY = 'enso-medicion-no';
export function optedOut() {
  return Boolean(navigator.globalPrivacyControl || navigator.doNotTrack === '1' || window.doNotTrack === '1' || storage(OPT_OUT_KEY) === '1');
}

function allowed() {
  return !optedOut() && hasBackend();
}
export { hasBackend, allowed as canSend };

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

/**
 * La versión de una primera visita: la ganadora con probabilidad EXPLOIT, si la hay; si no, o en el resto, una al
 * azar entre todas. ``r``: salió del sorteo parejo, y por eso puede entrar en la decisión (la ganadora puesta a
 * propósito no: compararla con las demás sería comparar grupos de tamaño y época distintos).
 */
export function assignment(exp, winner = null, rnd = Math.random) {
  const all = ids(exp);
  if (winner && all.includes(winner) && rnd() < EXPLOIT) return { v: winner, r: false };
  return { v: all[Math.floor(rnd() * all.length)], r: true };
}
export const assign = (exp, winner = null, rnd = Math.random) => assignment(exp, winner, rnd).v;

/** El enlace trae parámetros (?vista=, ?version=, ?nivel=…) que pueden fijar lo que se ve: se sabe antes del sorteo. */
const linkHasQuery = () => Boolean(location.search && location.search.length > 1) || /\?./.test(location.hash || '');
/** Eventos de una visita que cuentan como uso para la decisión. */
const USE = new Set(['select', 'detail', 'use']);

/** La versión de la primera visita, guardada, y si esa visita entra en la decisión (sorteo parejo, sin enlace). */
function firstVisit(exp) {
  const local = EXPERIMENTS[exp].local && !hasBackend();
  const a = local ? { v: EXPERIMENTS[exp].local, r: false } : assignment(exp, cachedWinners()?.[exp]);
  const s = { v: a.v, chosen: false, at: day() };
  write(exp, s);
  // Sin almacenamiento (bloqueado, o una ventana que no lo guarda) cada carga sería «primera visita» con un sorteo
  // nuevo: el mismo navegador contaría muchas veces. Solo entra si la versión quedó guardada.
  const kept = read(exp)?.v === a.v;
  return { s, itt: a.r && kept && !linkHasQuery() ? { v: a.v, flags: new Set(), seen: new Set() } : null };
}

class Session {
  constructor(exp) {
    this.exp = exp;
    const param = exp === 'mapa' ? 'version' : EXPERIMENTS[exp].param;
    const q = (src) => new URLSearchParams(src || '');
    const forced = param ? q(location.hash.split('?')[1]).get(param) || q(location.search).get(param) : null;
    // La primera exposición sorteada de este navegador: la única visita que entra en la decisión (this.itt).
    this.itt = null;
    let s = read(exp);
    if (!s) ({ s, itt: this.itt } = firstVisit(exp));
    this.state = s;
    // ?version=B en el enlace muestra esa versión sin cambiar la elegida (para enseñarla a alguien).
    this.preview = null;
    if (forced) this.show(forced.toUpperCase());
    this.flags = new Set();
    // Lo ya mandado en esta visita: un evento cuenta una vez por visita aunque la página se oculte y vuelva.
    this.sent = new Set();
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
    if (byTour()) return;
    this.markItt(e);
    if (this.preview) return;
    if (e === 'view') {
      if (this.viewed) return;
      this.viewed = true;
      if (this.state.chosen) this.flags.add('chosen');
    }
    this.flags.add(e);
    if (e === 'select' || e === 'detail') this.flags.add('use');
  }

  /** La primera visita sorteada: vio (rview) y usó (ruse), con la versión que se vea, para la versión sorteada. */
  markItt(e) {
    const t = this.itt;
    const r = e === 'view' ? 'rview' : USE.has(e) && t?.seen.has('rview') ? 'ruse' : null;
    if (!t || !r || t.seen.has(r)) return;
    t.seen.add(r);
    t.flags.add(r);
  }

  choose(v) {
    // Elegir la versión que se está viendo desde un enlace (o la que dejó el tutorial) la adopta como propia: antes
    // se ignoraba porque ya era la que se veía, y no había forma de quedarse con ella.
    if (!ids(this.exp).includes(v) || (v === this.variant && !this.preview)) return;
    // El tutorial muestra una vista: se ve como un enlace compartido, sin cambiar la de la persona ni contarla.
    if (byTour()) { this.show(v); return; }
    const old = this.state.v;
    const seen = this.variant;
    this.preview = null;
    try { document.dispatchEvent(new CustomEvent('ab:choose', { detail: { exp: this.exp, from: seen, to: v } })); } catch { /* sin DOM */ }
    if (old !== v) send(this.exp, old, ['leave']);
    this.flush();
    this.state = { v, chosen: true, at: day() };
    write(this.exp, this.state);
    this.viewed = false;
    this.sent.clear();
    this.mark('choose');
    this.mark('view');
  }

  flush() {
    const own = [...this.flags].filter((e) => !this.sent.has(e));
    own.forEach((e) => this.sent.add(e));
    this.flags.clear();
    const itt = this.itt ? [...this.itt.flags] : [];
    this.itt?.flags.clear();
    // Lo de la visita sorteada va a la versión sorteada: en el mismo aviso si es la de ahora, si no en otro.
    if (itt.length && this.itt.v !== this.state.v) send(this.exp, this.itt.v, itt);
    else own.push(...itt);
    send(this.exp, this.state.v, own);
  }
}

/** Lo pulsó el tutorial (tour.js), no la persona: no se cuenta ni cambia su versión. */
const byTour = () => typeof document !== 'undefined' && document.documentElement.dataset.tourDemo === '1';

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
