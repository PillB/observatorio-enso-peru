// Clasifica una respuesta HTTP: ¿sirve?, ¿qué formato tiene?, y si no
// sirve, ¿por qué? (bloqueo, verificación anti-robots, caída, DNS…).
//
// La misma función corre en el nodo Code de n8n y en tools/probe (Node), de
// modo que la validación desde n8n (AWS), desde GitHub Actions y desde el
// contenedor de desarrollo usan exactamente el mismo criterio. Un bloqueo se
// informa como bloqueo, nunca como «sin datos».

/** Firmas de páginas de bloqueo o verificación. Se buscan en minúsculas en
 * los primeros 64 KB del cuerpo y en las cabeceras. Como en
 * python/enso/reach.py: no cuentan x-iinfo, x-sucuri-id ni x-datadome, que
 * van en todas las respuestas de Imperva, Sucuri y DataDome (sus páginas de
 * bloqueo se reconocen por el cuerpo). */
const BLOCK_SIGNATURES = [
  { block: 'cloudflare-challenge', body: ['just a moment...', 'cf-chl-', 'challenge-platform', '/cdn-cgi/challenge'], header: { 'cf-mitigated': 'challenge' } },
  { block: 'cloudflare-block', body: ['attention required! | cloudflare', 'cf-error-code', 'sorry, you have been blocked', 'error 1020'] },
  { block: 'human-verification', body: ['verificación de seguridad', 'verificacion de seguridad', 'comprobación de seguridad', 'security check', 'verify you are human', 'verifica que eres humano', 'are you a robot', 'checking your browser'] },
  { block: 'captcha', body: ['g-recaptcha', 'grecaptcha', 'h-captcha', 'hcaptcha.com', 'cf-turnstile', 'px-captcha', 'captcha-delivery.com'] },
  { block: 'imperva', body: ['incapsula incident', '_incapsula_resource', 'request unsuccessful. incapsula'] },
  { block: 'akamai', body: ['reference&#32;&#35;', 'you don\'t have permission to access', 'errors.edgesuite.net'] },
  { block: 'sucuri', body: ['sucuri website firewall', 'access denied - sucuri'] },
  { block: 'aws-waf', body: ['awswaf', 'aws-waf-token'], header: { 'x-amzn-waf-action': '' } },
  { block: 'f5-asm', body: ['the requested url was rejected. please consult with your administrator', 'your support id is'] },
  { block: 'fortinet', body: ['fortiguard', 'web page blocked', 'fortigate'] },
  { block: 'datadome', body: ['datadome'] },
  { block: 'google-consent', body: ['consent.google.com', 'before you continue to google', 'antes de ir a google'] },
  { block: 'geo', body: ['not available in your country', 'no está disponible en tu país', 'no disponible en su país', 'access from your country', 'geo-restricted'] },
];

/** Errores de red (mensajes de axios/Node en n8n, de fetch/undici en Node). */
const ERROR_KINDS = [
  { verdict: 'dns', re: /ENOTFOUND|EAI_AGAIN|getaddrinfo|upstream dial failed|name not resolved|dns/i, transient: false },
  { verdict: 'timeout', re: /timeout|ETIMEDOUT|ECONNABORTED|UND_ERR_(HEADERS|BODY)_TIMEOUT|aborted/i, transient: true },
  { verdict: 'tls', re: /certificate|self[- ]signed|unable to verify|UNABLE_TO_GET_ISSUER|CERT_|wrong version number|SSL routines|handshake failure/i, transient: false },
  { verdict: 'connection', re: /ECONNRESET|ECONNREFUSED|EHOSTUNREACH|ENETUNREACH|EPIPE|socket hang up|other side closed|UND_ERR_SOCKET|network|fetch failed/i, transient: true },
];

const SCAN_BYTES = 65536;

// El nodo Code de n8n 1.x no tiene TextEncoder ni TextDecoder, y su Buffer
// rechaza los ArrayBuffer creados dentro del nodo: se decodifica a mano.
function utf8Decode(bytes) {
  if (typeof TextDecoder !== 'undefined') return new TextDecoder('utf-8').decode(bytes);
  let out = '';
  const parts = [];
  for (let i = 0; i < bytes.length;) {
    const b = bytes[i];
    let cp = 0xfffd, n = 1;
    if (b < 0x80) { cp = b; }
    else if (b >= 0xc2 && b < 0xe0 && i + 1 < bytes.length && (bytes[i + 1] & 0xc0) === 0x80) { cp = ((b & 0x1f) << 6) | (bytes[i + 1] & 0x3f); n = 2; }
    else if (b >= 0xe0 && b < 0xf0 && i + 2 < bytes.length && (bytes[i + 1] & 0xc0) === 0x80 && (bytes[i + 2] & 0xc0) === 0x80) { cp = ((b & 0x0f) << 12) | ((bytes[i + 1] & 0x3f) << 6) | (bytes[i + 2] & 0x3f); n = 3; }
    else if (b >= 0xf0 && b < 0xf5 && i + 3 < bytes.length && (bytes[i + 1] & 0xc0) === 0x80 && (bytes[i + 2] & 0xc0) === 0x80 && (bytes[i + 3] & 0xc0) === 0x80) { cp = ((b & 0x07) << 18) | ((bytes[i + 1] & 0x3f) << 12) | ((bytes[i + 2] & 0x3f) << 6) | (bytes[i + 3] & 0x3f); n = 4; }
    parts.push(cp);
    i += n;
    if (parts.length >= 8192) { out += String.fromCodePoint.apply(null, parts); parts.length = 0; }
  }
  return out + String.fromCodePoint.apply(null, parts);
}

function utf8Encode(text) {
  if (typeof TextEncoder !== 'undefined') return new TextEncoder().encode(text);
  const out = [];
  for (const ch of text) {
    const cp = ch.codePointAt(0);
    if (cp < 0x80) out.push(cp);
    else if (cp < 0x800) out.push(0xc0 | (cp >> 6), 0x80 | (cp & 63));
    else if (cp < 0x10000) out.push(0xe0 | (cp >> 12), 0x80 | ((cp >> 6) & 63), 0x80 | (cp & 63));
    else out.push(0xf0 | (cp >> 18), 0x80 | ((cp >> 12) & 63), 0x80 | ((cp >> 6) & 63), 0x80 | (cp & 63));
  }
  return new Uint8Array(out);
}

function toBytes(body) {
  if (body == null) return new Uint8Array(0);
  if (body instanceof Uint8Array) return body;
  if (typeof body === 'string') return utf8Encode(body);
  if (body.buffer instanceof ArrayBuffer) return new Uint8Array(body.buffer, body.byteOffset || 0, body.byteLength);
  return new Uint8Array(body);
}

function latin1(bytes, n) {
  const end = Math.min(bytes.length, n);
  let s = '';
  for (let i = 0; i < end; i += 8192) s += String.fromCharCode.apply(null, bytes.subarray(i, Math.min(end, i + 8192)));
  return s;
}

function lowerHeaders(headers) {
  const out = {};
  for (const [k, v] of Object.entries(headers || {})) out[String(k).toLowerCase()] = Array.isArray(v) ? v.join(', ') : String(v);
  return out;
}

/** Detecta el formato real del cuerpo, sin fiarse del Content-Type. */
function detectFormat(bytes, contentType) {
  if (!bytes.length) return 'empty';
  if (bytes[0] === 0x25 && bytes[1] === 0x50 && bytes[2] === 0x44 && bytes[3] === 0x46) return 'pdf';
  let head = latin1(bytes, 4096);
  if (head.charCodeAt(0) === 0xef && head.charCodeAt(1) === 0xbb && head.charCodeAt(2) === 0xbf) head = head.slice(3);
  head = head.replace(/^[\s\u0000]+/, '');
  const low = head.toLowerCase();
  if (low.startsWith('{') || low.startsWith('[')) {
    if (/"version"\s*:\s*"https:\/\/jsonfeed\.org/.test(low)) return 'jsonfeed';
    return 'json';
  }
  if (/<rss[\s>]/.test(low)) return 'rss';
  if (/<feed[\s>]/.test(low) && /xmlns="http:\/\/www\.w3\.org\/2005\/atom"/.test(low)) return 'atom';
  if (/<rdf:rdf[\s>]/.test(low)) return 'rdf';
  if (/<feed[\s>]/.test(low)) return 'atom';
  if (/<!doctype html|<html[\s>]|<head[\s>]|<body[\s>]/.test(low)) return 'html';
  if (low.startsWith('<?xml') || low.startsWith('<')) return /<html/.test(low) ? 'html' : 'xml';
  const ct = (contentType || '').toLowerCase();
  if (ct.includes('html')) return 'html';
  // Binario si hay muchos bytes de control en el inicio.
  let ctrl = 0;
  const n = Math.min(bytes.length, 2048);
  for (let i = 0; i < n; i++) { const b = bytes[i]; if (b < 9 || (b > 13 && b < 32)) ctrl++; }
  return ctrl > n * 0.05 ? 'binary' : 'text';
}

const FEED_FORMATS = ['rss', 'atom', 'rdf', 'jsonfeed'];

/** Cuenta entradas y la fecha más reciente de un feed (sin un lector XML
 * completo; el lector tolerante del pipeline es quien decide al final). */
function feedStats(text, format) {
  if (format === 'jsonfeed') {
    try {
      const j = JSON.parse(text);
      const items = Array.isArray(j.items) ? j.items : [];
      return { items: items.length, newest: newestDate(items.map((i) => i.date_published || i.date_modified)), title: String(j.title || '').slice(0, 120) };
    } catch (e) { return { items: 0, newest: null, title: '', parse_error: 'JSON Feed inválido' }; }
  }
  const items = (text.match(/<(item|entry)[\s>]/gi) || []).length;
  const dates = [];
  const re = /<(pubDate|updated|published|dc:date|lastBuildDate)[^>]*>([^<]{6,64})</gi;
  let m;
  while ((m = re.exec(text)) && dates.length < 500) dates.push(m[2].trim());
  const t = /<title[^>]*>(?:<!\[CDATA\[)?([^<\]]{1,200})/i.exec(text);
  return { items, newest: newestDate(dates), title: t ? t[1].trim().slice(0, 120) : '' };
}

function newestDate(values) {
  let best = null;
  for (const v of values) {
    if (!v) continue;
    const t = Date.parse(v);
    if (!Number.isNaN(t) && (best === null || t > best)) best = t;
  }
  return best === null ? null : new Date(best).toISOString();
}

/** El script de detección de Cloudflare (/cdn-cgi/challenge-platform/…/scripts/jsd)
 * va también en páginas normales: esas dos marcas no cuentan si lo siguen. */
const NOT_JSD = {
  'challenge-platform': /challenge-platform(?!\/(?:h\/\w+\/)?scripts\/jsd)/,
  '/cdn-cgi/challenge': /\/cdn-cgi\/challenge(?!-platform\/(?:h\/\w+\/)?scripts\/jsd)/,
};

function findBlock(scanLow, headers) {
  for (const sig of BLOCK_SIGNATURES) {
    for (const [h, v] of Object.entries(sig.header || {})) {
      if (h in headers && (!v || headers[h].toLowerCase().includes(v))) return sig.block;
    }
    for (const s of sig.body || []) {
      if (NOT_JSD[s] ? NOT_JSD[s].test(scanLow) : scanLow.includes(s)) return sig.block;
    }
  }
  return null;
}

/**
 * @param {object} r
 * @param {string} r.url
 * @param {string} [r.expect]  feed | html | pdf | json | text | any
 * @param {number|null} [r.status]
 * @param {object} [r.headers]
 * @param {Uint8Array|Buffer|string|null} [r.body]
 * @param {string|null} [r.error]  mensaje de error de red, si no hubo respuesta
 */
function classify(r) {
  const c = classifyRaw(r);
  c.reach = reachClass(c);
  return c;
}

function classifyRaw(r) {
  const headers = lowerHeaders(r.headers);
  const bytes = toBytes(r.body);
  const contentType = headers['content-type'] || '';
  const out = {
    ok: false, verdict: '', block: null, transient: false,
    status: r.status == null ? null : Number(r.status), bytes: bytes.length,
    content_type: contentType.slice(0, 120), detected: 'empty', items: null, newest: null, title: '', note: '',
  };
  const err = r.error ? String(r.error) : '';
  // Proxies de salida devuelven 502 con «upstream dial failed» cuando el nombre no resuelve.
  if (err || (out.status === 502 && /upstream dial failed/i.test(latin1(bytes, 200)))) {
    const msg = err || latin1(bytes, 200);
    const kind = ERROR_KINDS.find((k) => k.re.test(msg));
    out.verdict = kind ? kind.verdict : 'connection';
    out.transient = kind ? kind.transient : true;
    out.status = err ? null : out.status;
    out.note = msg.replace(/\s+/g, ' ').slice(0, 200);
    return out;
  }
  out.detected = detectFormat(bytes, contentType);
  const scan = latin1(bytes, SCAN_BYTES);
  // Las firmas con tildes se buscan en UTF-8 y en Latin-1.
  const scanLow = `${scan}\n${utf8Decode(bytes.subarray(0, SCAN_BYTES))}`.toLowerCase();
  const block = findBlock(scanLow, headers);
  const st = out.status;

  if (st === 429) { out.verdict = 'blocked'; out.block = 'rate-limit'; out.transient = true; return out; }
  if (st === 401 || st === 407) { out.verdict = 'blocked'; out.block = 'auth-required'; return out; }
  if (st === 403 || st === 451) { out.verdict = 'blocked'; out.block = block || (st === 451 ? 'legal' : 'http-403'); return out; }
  if (st === 404 || st === 410) { out.verdict = 'not_found'; return out; }
  if (st !== null && st >= 500) {
    out.verdict = block ? 'blocked' : 'server_error';
    out.block = block;
    out.transient = !block;
    return out;
  }
  if (st === 202 && (block || !bytes.length || out.detected === 'html')) {
    // 202 de anti-robots (ReliefWeb, AWS WAF): «aceptado», pero sin el contenido.
    out.verdict = 'blocked';
    out.block = block || 'bot-202';
    return out;
  }
  if (st !== null && (st < 200 || st >= 300)) {
    // 3xx que no se siguió, 1xx, etc.
    out.verdict = block ? 'blocked' : 'http_error';
    out.block = block;
    return out;
  }
  // Solo espacios es vacío, como body.strip() en python/enso/reach.py.
  if (bytes.every((b) => b === 0x20 || (b >= 0x09 && b <= 0x0d))) { out.verdict = 'empty'; out.transient = true; return out; }

  // El registro dice «rss» para cualquier feed y «csv» para tablas de texto.
  const expect = ({ rss: 'feed', atom: 'feed', csv: 'text' })[(r.expect || 'any').toLowerCase()] || (r.expect || 'any').toLowerCase();
  const isFeed = FEED_FORMATS.includes(out.detected);
  // Una página de verificación responde 200 con HTML pequeño: es un bloqueo
  // solo si no es lo que se esperaba (un feed o PDF que menciona «captcha» no lo es).
  const unexpectedHtml = out.detected === 'html' && expect !== 'html' && expect !== 'any';
  if (block && (unexpectedHtml || (out.detected === 'html' && bytes.length < 40000))) {
    out.verdict = 'blocked';
    out.block = block;
    return out;
  }
  if (expect === 'feed') {
    if (!isFeed) {
      out.verdict = 'wrong_type';
      out.note = `se esperaba un feed y llegó ${out.detected}`;
      return out;
    }
    const st2 = feedStats(utf8Decode(bytes), out.detected);
    Object.assign(out, { items: st2.items, newest: st2.newest, title: st2.title });
    if (st2.parse_error) { out.verdict = 'parse_error'; out.note = st2.parse_error; return out; }
    if (!st2.items) { out.verdict = 'empty'; out.note = 'feed sin entradas'; return out; }
  } else if (expect === 'pdf') {
    if (out.detected !== 'pdf') { out.verdict = 'wrong_type'; out.note = `se esperaba PDF y llegó ${out.detected}`; return out; }
  } else if (expect === 'json') {
    if (out.detected !== 'json' && out.detected !== 'jsonfeed') { out.verdict = 'wrong_type'; out.note = `se esperaba JSON y llegó ${out.detected}`; return out; }
    try { JSON.parse(utf8Decode(bytes)); } catch (e) { out.verdict = 'parse_error'; out.note = 'JSON inválido'; return out; }
  } else if (expect === 'text') {
    if (out.detected === 'html' || out.detected === 'binary') { out.verdict = 'wrong_type'; out.note = `se esperaba texto y llegó ${out.detected}`; return out; }
  } else if (expect === 'html') {
    // Un bloqueo llega como HTML: si llegó otra cosa, no es un bloqueo y se
    // guarda igual (el registro puede equivocarse de tipo).
    if (out.detected !== 'html' && out.detected !== 'xml') out.note = `llegó ${out.detected}; el registro esperaba HTML`;
    else if (bytes.length < 500) { out.verdict = 'empty'; out.note = 'HTML casi vacío'; return out; }
  }
  if (out.detected === 'html' || out.detected === 'xml') {
    const t = /<title[^>]*>([^<]{1,200})/i.exec(scan);
    if (t && !out.title) out.title = t[1].trim().slice(0, 120);
  }
  out.ok = true;
  out.verdict = 'ok';
  return out;
}

/** Clase de alcance del registro (python/enso/reach.py: ok, empty, http-403,
 * http-4xx, http-5xx, timeout, connect, dns, tls, challenge), para que las
 * mediciones desde n8n se comparen con las de Actions y del Perú. */
function reachClass(c) {
  switch (c.verdict) {
    case 'ok': return 'ok';
    case 'timeout': return 'timeout';
    case 'connection': return 'connect';
    case 'dns': return 'dns';
    case 'tls': return 'tls';
    case 'not_found': case 'http_error': return 'http-4xx';
    case 'server_error': return 'http-5xx';
    case 'blocked':
      if (c.block === 'http-403') return 'http-403';
      if (c.block === 'rate-limit' || c.block === 'auth-required' || c.block === 'legal') return 'http-4xx';
      return 'challenge';
    default: return 'empty'; // vacío, tipo inesperado o ilegible: responde, pero sin contenido útil
  }
}

/** Extensión del archivo guardado según el formato detectado. */
function fileExtension(detected) {
  if (detected === 'pdf') return 'pdf';
  if (detected === 'json' || detected === 'jsonfeed') return 'json';
  if (['rss', 'atom', 'rdf', 'xml'].includes(detected)) return 'xml';
  if (detected === 'html') return 'html';
  return 'txt';
}

// @export
if (typeof module !== 'undefined') module.exports = { classify, reachClass, utf8Decode, utf8Encode, detectFormat, feedStats, fileExtension, BLOCK_SIGNATURES };
