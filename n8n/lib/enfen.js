// URL de los PDF de los comunicados del ENFEN a partir de sus listados.
// Es el mismo criterio que python/enso/feeds/peru.py (parse_enfen_listing,
// parse_enfen_wp_posts) y que python/tools/peru_collector.py
// (enfen_documents): los dos comunicados oficiales más recientes y los dos
// números siguientes en la réplica de la DHN, que pueden existir antes de
// que el listado los muestre.

const DHN_BASE = 'https://www.dhn.mil.pe';
const ENFEN_BASE = 'https://enfen.imarpe.gob.pe';
const LISTING_RE = /href=["']([^"']*comunicado-(oficial|extraordinario)-enfen-n-?(\d{1,2})-(\d{4})[^"']*)["']/gi;
const DHN_RE = /href=["']([^"']*\/comunicado-(oficial|extraordinario)\/(\d{1,2})-(\d{4})\.pdf)["']/gi;
const NUMBER_RE = /COMUNICADO\s+OFICIAL\s+(?:DEL?\s+)?ENFEN\s+N\s*[°ºo.]*\s*(\d{1,2})\s*[-–]\s*(\d{4})/i;

function unescapeHtml(s) {
  return s.replace(/&#0?38;/g, '&').replace(/&amp;/g, '&');
}

/** Quita el parámetro «refresh» (token por visita) de los enlaces de descarga. */
function cleanWpdm(url) {
  return unescapeHtml(url).replace(/[&?]refresh=[^&]*/g, '');
}

function dhnPdf(n, y) {
  return `${DHN_BASE}/Archivos/oceanografia/enfen/comunicado-oficial/${String(n).padStart(2, '0')}-${y}.pdf`;
}

/** Comunicados en un listado HTML (portal del ENFEN o réplica de la DHN). */
function parseListing(html) {
  const seen = new Map();
  for (const rx of [LISTING_RE, DHN_RE]) {
    rx.lastIndex = 0;
    let m;
    while ((m = rx.exec(html))) {
      let url = unescapeHtml(m[1]);
      if (url.startsWith('/')) url = DHN_BASE + url;
      const key = `${m[2].toLowerCase()}|${m[4]}|${m[3].padStart(2, '0')}`;
      if (!seen.has(key)) seen.set(key, { kind: m[2].toLowerCase(), year: Number(m[4]), number: Number(m[3]), url });
    }
  }
  return [...seen.values()];
}

/** Comunicados en la respuesta JSON de WordPress del portal del ENFEN. */
function parseWpPosts(text) {
  let posts;
  try { posts = JSON.parse(text); } catch (e) { return []; }
  if (!Array.isArray(posts)) return [];
  const out = [];
  for (const p of posts) {
    const title = String((p.title || {}).rendered || '').replace(/<[^>]+>/g, ' ');
    const content = String((p.content || {}).rendered || '').replace(/<[^>]+>/g, ' ');
    const m = NUMBER_RE.exec(`${title} ${content}`) || /N\s*[°º]?\s*(\d{1,2})\s*[-–]\s*(\d{4})/.exec(title);
    if (!m || !(title + content.slice(0, 300)).toLowerCase().includes('comunicado')) continue;
    // La entrada trae el enlace de descarga (``?wpdmdl=`` o un .pdf) en su
    // contenido; si no, queda la página de la entrada.
    const html = String((p.content || {}).rendered || '');
    const dl = /href=["']([^"']*(?:[?&](?:amp;|#0?38;)?wpdmdl=\d+|\.pdf)[^"']*)["']/i.exec(html);
    out.push({ kind: 'oficial', year: Number(m[2]), number: Number(m[1]), url: dl ? dl[1] : (p.link || '') });
  }
  return out;
}

/**
 * @param {{url: string, text: string}[]} pages  listados descargados
 * @param {Date} [now]  para sondear el n.º 01 del año nuevo en enero
 * @returns {string[]} URL a descargar (sin repetir)
 */
function deriveEnfenTargets(pages, now = new Date()) {
  const items = [];
  for (const p of pages) {
    if (!p.text) continue;
    const t = p.text.trimStart();
    items.push(...(t.startsWith('[') ? parseWpPosts(t) : parseListing(p.text)));
  }
  const oficial = items.filter((i) => i.kind === 'oficial')
    .sort((a, b) => (b.year - a.year) || (b.number - a.number));
  if (!oficial.length) return [];
  const latest = [];
  for (const i of oficial) {
    if (!latest.some((x) => x.year === i.year && x.number === i.number)) latest.push(i);
    if (latest.length === 2) break;
  }
  const urls = [];
  for (const i of latest) {
    if (i.url) urls.push(cleanWpdm(i.url));
    urls.push(dhnPdf(i.number, i.year));
  }
  const { year, number } = latest[0];
  for (const k of [1, 2]) urls.push(dhnPdf(number + k, year));
  const thisYear = now.getUTCFullYear();
  if (year < thisYear) urls.push(dhnPdf(1, thisYear), dhnPdf(2, thisYear));
  return [...new Set(urls)];
}

// @export
if (typeof module !== 'undefined') module.exports = { deriveEnfenTargets, parseListing, parseWpPosts, cleanWpdm, dhnPdf, DHN_BASE, ENFEN_BASE };
