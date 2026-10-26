// robots.txt según la RFC 9309, con el mismo criterio que python/enso/reach.py
// (RobotRules y Robots). n8n solo lo lee para las URL cuyo robots.txt nadie
// pudo leer al medir («robots: unknown» en el registro): las pide si sus
// reglas lo permiten, y si no se sabe, no las pide.

/* global utf8Decode, classify */

const ROBOTS_AGENT = 'observatorio-enso-peru';
/** Entidades públicas del Perú, como reach.PUBLIC_PERU_SUFFIXES: decisión del
 * responsable del proyecto (26 de octubre de 2026, Ley 27806). Su robots.txt
 * no decide qué se pide, pero nunca se evade una verificación antirobots. */
const PUBLIC_PERU_SUFFIXES = ['.gob.pe', '.mil.pe'];

function publicPeru(url) {
  const host = ((/^[a-z][a-z0-9+.-]*:\/\/(?:[^@/?#]*@)?([^:/?#]+)/i.exec(String(url)) || [])[1] || '').toLowerCase().replace(/\.$/, '');
  return PUBLIC_PERU_SUFFIXES.some((s) => host.endsWith(s) || host === s.slice(1));
}

/** Reglas del grupo del observatorio o, si no hay, del grupo «*».
 * Gana la regla más larga; ante un empate, Allow. */
function robotRules(text, agent = ROBOTS_AGENT) {
  const groups = [];
  let agents = [];
  let rules = [];
  let inRules = false;
  for (const raw of String(text || '').split(/\r\n|\r|\n/)) {
    const line = raw.split('#', 1)[0].trim();
    const i = line.indexOf(':');
    if (i < 0) continue;
    const k = line.slice(0, i).trim().toLowerCase();
    const v = line.slice(i + 1).trim();
    if (k === 'user-agent') {
      if (inRules) { groups.push({ agents, rules }); agents = []; rules = []; inRules = false; }
      agents.push(v.toLowerCase());
    } else if ((k === 'allow' || k === 'disallow') && agents.length) {
      inRules = true;
      if (v) rules.push({ allow: k === 'allow', pattern: v }); // «Disallow:» vacío no prohíbe nada
    } else if (k === 'crawl-delay' && agents.length) {
      inRules = true;
    }
  }
  if (agents.length) groups.push({ agents, rules });
  const token = agent.toLowerCase();
  let mine = token !== '*' ? groups.filter((g) => g.agents.includes(token)) : [];
  if (!mine.length) mine = groups.filter((g) => g.agents.includes('*'));
  return mine.flatMap((g) => g.rules);
}

function ruleLength(pattern, path) {
  const body = pattern.endsWith('$') ? pattern.replace(/\$+$/, '') : pattern;
  const rx = body.split('').map((c) => (c === '*' ? '.*' : c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))).join('');
  return new RegExp(`^${rx}${pattern.endsWith('$') ? '$' : ''}`, 's').test(path) ? pattern.length : -1;
}

function robotsAllowed(rules, url) {
  // Ruta y consulta sin «URL», que el nodo Code de n8n no tiene.
  const m = /^[a-z][a-z0-9+.-]*:\/\/[^/?#]*([^?#]*)(\?[^#]*)?/i.exec(String(url));
  if (!m) return false;
  const path = (m[1] || '/') + (m[2] && m[2].length > 1 ? m[2] : '');
  if (path === '/robots.txt') return true;
  let best = -1;
  let allow = true;
  for (const r of rules) {
    const n = ruleLength(r.pattern, path);
    if (n > best || (n === best && r.allow)) { best = n; allow = r.allow; }
  }
  return allow;
}

/**
 * Qué dice el robots.txt descargado de cada URL de ``urls``.
 * @param {object} r  {status, headers (en minúsculas), body: Uint8Array|null, error, cls}
 * @returns {{source: string, verdicts: Object<string, string>, challenge: boolean}}  source: rules | absent |
 *   unreachable; cada veredicto: allowed | disallowed | absent | unreachable; challenge: en lugar del robots.txt
 *   llegó una verificación antirobots
 */
function robotsVerdicts(r, urls) {
  const all = (v, challenge = false) => ({ source: v, verdicts: Object.fromEntries(urls.map((u) => [u, v])), challenge });
  const cls = r.cls || {};
  const status = r.status == null ? null : Number(r.status);
  const mitigated = String((r.headers || {})['cf-mitigated'] || '').toLowerCase();
  // Sin respuesta, 429, 5xx o una verificación antirobots: no se sabe, y no se pide nada (§2.3.1.4).
  if (mitigated.includes('challenge')) return all('unreachable', true);
  if (r.error || status == null) return all('unreachable');
  // 401, 403 o 407: una página de verificación no dice nada; otra, como un 4xx cualquiera.
  if ((status === 401 || status === 403 || status === 407)
    && classify({ url: '', expect: 'any', status: 403, headers: r.headers || {}, body: r.body }).reach === 'challenge') return all('unreachable', true);
  if (status === 429 || status >= 500) return all('unreachable');
  // Otro 3xx o 4xx: no hay reglas, se permite todo (§2.3.1.3).
  if (status >= 300) return all('absent');
  if (cls.detected === 'html' && cls.reach === 'challenge') return all('unreachable', true);
  const text = r.body ? utf8Decode(r.body.subarray(0, 500000)) : '';
  const rules = robotRules(text);
  return { source: 'rules', verdicts: Object.fromEntries(urls.map((u) => [u, robotsAllowed(rules, u) ? 'allowed' : 'disallowed'])), challenge: false };
}

/** Si se pide la URL: lo que su robots.txt permite o, en una entidad pública del
 * Perú, también lo que prohíbe o lo que no respondió, salvo una verificación. */
function robotsFetch(verdict, url, challenge) {
  if (verdict === 'allowed' || verdict === 'absent') return true;
  return publicPeru(url) && !challenge;
}

/** Pausa (segundos) antes de cada petición, en el orden en que se harán: entre
 * dos peticiones al mismo servidor de una entidad pública del Perú pasan al
 * menos max(1, Crawl-delay) segundos, hasta 30. Las pausas se cuentan como si
 * cada descarga fuera instantánea, así que el intervalo real nunca es menor.
 * Cada elemento: {url, crawl_delay?}; devuelve una pausa por elemento. */
function pacing(items) {
  const last = new Map();
  let t = 0;
  return items.map((it) => {
    const url = String(it.url || '');
    if (!publicPeru(url)) return 0;
    const host = ((/^[a-z][a-z0-9+.-]*:\/\/(?:[^@/?#]*@)?([^:/?#]+)/i.exec(url) || [])[1] || '').toLowerCase();
    const d = Math.min(30, Math.max(1, Number(it.crawl_delay) || 1));
    const pause = last.has(host) ? Math.max(0, last.get(host) + d - t) : 0;
    t += pause;
    last.set(host, t);
    return pause;
  });
}

// @export
if (typeof module !== 'undefined') module.exports = { robotRules, robotsAllowed, robotsVerdicts, robotsFetch, publicPeru, pacing, ROBOTS_AGENT };
