// Arma la copia que n8n publica en la rama de datos, en el mismo formato
// que el recolector del Perú («enso-relay/1», ver python/enso/fetch.py
// Relay y python/tools/peru_collector.py):
//
//   index.json            lista de URL descargadas con su estado
//   files/<sha16>.<ext>   cuerpo original de cada respuesta válida
//
// Diferencias con el recolector del Perú:
// - Cada entrada lleva la clasificación (ok, bloqueo, tipo de bloqueo…) y el
//   SHA de blob de git, para reutilizar los archivos que no cambiaron sin
//   volver a subirlos.
// - Si una URL falla ahora pero la copia anterior tiene una válida de hace
//   menos de ``carryHours``, se conserva esa copia (``carried: true``) con su
//   fecha original. El pipeline mide la antigüedad por entrada.
// - index.json se publica siempre, aunque todo falle: es el latido que
//   distingue «n8n caído» de «fuentes caídas».

/* global sha256Hex, gitBlobSha, fileExtension */

function entryFrom(r) {
  const c = r.cls || {};
  const e = {
    url: r.url,
    id: r.id,
    group: r.group,
    status: c.status ?? null,
    content_type: c.content_type || '',
    bytes: c.bytes || 0,
    fetched_at: r.fetched_at,
    verdict: c.verdict,
    reach: c.reach,
  };
  if (c.block) e.block = c.block;
  if (c.detected && c.detected !== 'empty') e.detected = c.detected;
  if (c.items != null) e.items = c.items;
  if (c.newest) e.newest = c.newest;
  if (c.note) e.note = c.note;
  if (r.pass && r.pass > 1) e.pass = r.pass;
  if (r.aliases && r.aliases.length) e.aliases = r.aliases;
  // Qué dijo el robots.txt leído por n8n (solo en las URL «robots: unknown» del registro).
  if (r.robots) e.robots = r.robots;
  if (r.robots_public) e.robots_public = true;
  return e;
}

/** URL «robots: unknown» que no se pidieron porque su robots.txt lo prohíbe
 * («disallowed») o no respondió («unreachable»), de los robots.txt leídos. */
function notRequested(results) {
  const out = [];
  for (const r of results) {
    if (r.role !== 'robots') continue;
    for (const d of r.deferred || []) {
      if (d.fetch || (d.fetch === undefined && (d.robots === 'allowed' || d.robots === 'absent'))) continue;
      const why = d.robots === 'disallowed' ? 'robots.txt no lo permite' : `robots.txt no respondió (${(r.cls && r.cls.reach) || 'sin respuesta'})`;
      // reach: la clase del pedido de robots.txt (timeout, challenge…), como Robots.failure en python/enso/reach.py.
      const e = { url: d.url, id: d.id, group: d.group, robots: d.robots, reach: (r.cls && r.cls.reach) || '', robots_url: r.url, fetched_at: r.fetched_at, note: why };
      // hop: el destino de la redirección cuyo robots.txt se leyó; la excepción de las entidades públicas
      // del Perú se juzga por ese servidor (probe_sources._not_requested).
      if (d.hop) e.hop = d.hop;
      out.push(e);
    }
  }
  return out;
}

/** Elige un resultado por URL: el válido si lo hay, si no el último intento. */
function pickResults(results) {
  const byUrl = new Map();
  for (const r of results) {
    const prev = byUrl.get(r.url);
    if (!prev || (!prev.cls?.ok && (r.cls?.ok || (r.pass || 1) >= (prev.pass || 1)))) byUrl.set(r.url, r);
  }
  return [...byUrl.values()];
}

function hoursBetween(a, b) {
  const t = Date.parse(a);
  return Number.isNaN(t) ? Infinity : (b.getTime() - t) / 3600000;
}

/**
 * @param {object} p
 * @param {Array} p.results   [{id, url, group, fetched_at, pass, cls, body: Uint8Array|null}]
 * @param {object|null} p.previous  index.json anterior (o null)
 * @param {Date} p.now
 * @param {object} p.collector  datos del recolector para index.json
 * @param {number} [p.carryHours]
 * @param {number} [p.maxBytes]
 * @returns {{index: object, files: Array<{path: string, git_blob: string, sha256: string, body: Uint8Array|null}>}}
 */
function buildSnapshot({ results, previous, now, collector, carryHours = 72, maxBytes = 8000000 }) {
  const prevByUrl = new Map();
  for (const e of (previous && previous.entries) || []) {
    if (e.status === 200 && e.file && e.git_blob && e.sha256) prevByUrl.set(e.url, e);
  }
  const files = new Map();
  const entries = [];
  for (const r of pickResults(results.filter((x) => x.role !== 'robots'))) {
    const e = entryFrom(r);
    const body = r.body;
    if (r.cls && r.cls.ok && body && body.length) {
      if (body.length > maxBytes) {
        e.note = `${e.note ? e.note + '; ' : ''}más de ${maxBytes} bytes: no se guarda`;
      } else {
        const sha = sha256Hex(body);
        const path = `files/${sha.slice(0, 16)}.${fileExtension(r.cls.detected)}`;
        const prev = [...prevByUrl.values()].find((p) => p.sha256 === sha && p.file === path);
        const blob = prev ? prev.git_blob : gitBlobSha(body);
        if (!files.has(path)) files.set(path, { path, sha256: sha, git_blob: blob, body: prev ? null : body });
        Object.assign(e, { file: path, sha256: sha, git_blob: blob });
      }
    } else {
      const prev = prevByUrl.get(r.url);
      if (prev && hoursBetween(prev.fetched_at, now) <= carryHours) {
        const carried = { ...prev, carried: true, last_attempt: { at: r.fetched_at, verdict: e.verdict, status: e.status } };
        if (e.block) carried.last_attempt.block = e.block;
        if (e.note) carried.last_attempt.note = e.note;
        entries.push(carried);
        if (!files.has(prev.file)) files.set(prev.file, { path: prev.file, sha256: prev.sha256, git_blob: prev.git_blob, body: null });
        continue;
      }
    }
    entries.push(e);
  }
  const groups = [...new Set(entries.map((e) => e.group))];
  const summary = {};
  for (const g of groups) {
    const es = entries.filter((e) => e.group === g);
    summary[g] = `${es.filter((e) => e.verdict === 'ok' && !e.carried).length}/${es.length}`;
  }
  const verdicts = {};
  for (const e of entries) {
    const v = e.carried ? 'carried' : e.verdict;
    verdicts[v] = (verdicts[v] || 0) + 1;
  }
  const index = {
    schema: 'enso-relay/1',
    collected_at: now.toISOString().replace(/\.\d{3}Z$/, '+00:00'),
    collector,
    entries,
    summary,
    verdicts,
  };
  const skipped = notRequested(results);
  if (skipped.length) index.not_requested = skipped;
  return { index, files: [...files.values()] };
}

/** Latido de la corrida, en el formato del recolector del Perú
 * («enso-relay-heartbeat/1»): ``result`` es «ok» si alguna fuente respondió
 * en esta corrida y «sin-fuentes» si ninguna (n8n funciona, las fuentes no). */
function heartbeat(index, now) {
  const fresh = index.entries.filter((e) => e.verdict === 'ok' && !e.carried);
  return {
    schema: 'enso-relay-heartbeat/1',
    at: now.toISOString().replace(/\.\d{3}Z$/, '+00:00'),
    result: fresh.length ? 'ok' : 'sin-fuentes',
    reachable: `${fresh.length}/${index.entries.length}`,
    summary: index.summary,
    failures: index.entries.filter((e) => e.verdict !== 'ok' || e.carried).slice(0, 40).map((e) => {
      const f = { url: e.url, status: e.carried ? e.last_attempt.status : e.status, verdict: e.carried ? e.last_attempt.verdict : e.verdict };
      const block = e.carried ? e.last_attempt.block : e.block;
      if (block) f.block = block;
      return f;
    }),
    collector: index.collector,
  };
}

/** Vencimiento del token de GitHub, de la cabecera
 * «GitHub-Authentication-Token-Expiration» («2027-05-10 00:00:00 UTC» o
 * «2027-05-09 19:00:00 -0500»), en ISO con «+00:00». null si no viene o no se
 * entiende. Mismo criterio que collector_service.parse_token_expiry. */
function parseTokenExpiry(header) {
  const m = /^\s*(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)\s*(UTC|Z|[+-]\d{2}:?\d{2})?/.exec(String(header || ''));
  if (!m) return null;
  let tz = m[3] || 'UTC';
  tz = tz === 'UTC' || tz === 'Z' ? '+00:00' : (tz.includes(':') ? tz : `${tz.slice(0, 3)}:${tz.slice(3)}`);
  const t = Date.parse(`${m[1]}T${m[2].length === 5 ? `${m[2]}:00` : m[2]}${tz}`);
  return Number.isNaN(t) ? null : new Date(t).toISOString().replace(/\.\d{3}Z$/, '+00:00');
}

// @export
if (typeof module !== 'undefined') module.exports = { buildSnapshot, pickResults, heartbeat, parseTokenExpiry, notRequested };
