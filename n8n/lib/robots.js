// robots.txt según la RFC 9309, con el mismo criterio que python/enso/reach.py
// (RobotRules y Robots). n8n solo lo lee para las URL cuyo robots.txt nadie
// pudo leer al medir («robots: unknown» en el registro): las pide si sus
// reglas lo permiten, y si no se sabe, no las pide.

/* global utf8Decode, classify */

const ROBOTS_AGENT = 'observatorio-enso-peru';

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
 * @returns {{source: string, verdicts: Object<string, string>}}  source: rules | absent | unreachable;
 *   cada veredicto: allowed | disallowed | absent | unreachable
 */
function robotsVerdicts(r, urls) {
  const all = (v) => ({ source: v, verdicts: Object.fromEntries(urls.map((u) => [u, v])) });
  const cls = r.cls || {};
  const status = r.status == null ? null : Number(r.status);
  const mitigated = String((r.headers || {})['cf-mitigated'] || '').toLowerCase();
  // Sin respuesta, 429, 5xx o una verificación antirobots: no se sabe, y no se pide nada (§2.3.1.4).
  if (r.error || status == null || mitigated.includes('challenge')) return all('unreachable');
  // 401, 403 o 407: una página de verificación no dice nada; otra, como un 4xx cualquiera.
  if ((status === 401 || status === 403 || status === 407)
    && classify({ url: '', expect: 'any', status: 403, headers: r.headers || {}, body: r.body }).reach === 'challenge') return all('unreachable');
  if (status === 429 || status >= 500) return all('unreachable');
  // Otro 3xx o 4xx: no hay reglas, se permite todo (§2.3.1.3).
  if (status >= 300) return all('absent');
  if (cls.detected === 'html' && cls.reach === 'challenge') return all('unreachable');
  const text = r.body ? utf8Decode(r.body.subarray(0, 500000)) : '';
  const rules = robotRules(text);
  return { source: 'rules', verdicts: Object.fromEntries(urls.map((u) => [u, robotsAllowed(rules, u) ? 'allowed' : 'disallowed'])) };
}

// @export
if (typeof module !== 'undefined') module.exports = { robotRules, robotsAllowed, robotsVerdicts, ROBOTS_AGENT };
