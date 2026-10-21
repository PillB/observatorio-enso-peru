// Lista de URL a descargar, del registro de fuentes (registry/sources.json,
// «enso-source-registry/1»). Usa el registro leído de GitHub por el nodo
// «Leer registro» y, si no se pudo leer, la copia incluida al construir el
// flujo. Cada fuente aporta su URL y sus URL alternativas (réplicas): el
// pipeline pide cada una por separado y busca la copia por URL exacta.
const cfg = $('Configuración').first().json;
const EMBEDDED = __REGISTRY__;
const SCHEMA = 'enso-source-registry/1';
let registry = null;
let origin = 'incluido en el flujo (versión __VERSION__)';
let prev = {};
try { prev = $('Leer registro').first().json; } catch (e) { /* el flujo de validación no lee el registro */ }
// Con «Response Format: Text» n8n deja el cuerpo en «data» (en algunas versiones, en «body»).
const prevBody = prev.data !== undefined ? prev.data : prev.body;
if (prev.statusCode === 200 && prevBody) {
  try {
    const j = typeof prevBody === 'string' ? JSON.parse(prevBody) : prevBody;
    if (j && j.schema === SCHEMA && Array.isArray(j.sources) && j.sources.length) {
      registry = j;
      origin = `GitHub ${cfg.repo}@${cfg.registry_ref}:${cfg.registry_path}`;
    }
  } catch (e) { /* se usa la copia incluida */ }
}
if (!registry) registry = EMBEDDED;
const year = new Intl.DateTimeFormat('en', { timeZone: 'America/Lima', year: 'numeric' }).format(new Date());
const only = String(cfg.only || '').trim();
const scope = String(cfg.scope || 'todas');
// Terminación de la URL (extensión), o la ruta completa si no tiene extensión.
const ext = (u) => {
  const path = String(u).split(/[?#]/)[0].replace(/^https?:\/\//i, '');
  return ((path.match(/\.([a-z0-9]{2,5})$/i) || [])[1] || path).toLowerCase();
};
const seen = new Set();
const out = [];
for (const s of registry.sources) {
  if (only && !s.id.includes(only) && s.group !== only) continue;
  const channels = s.channels || [];
  // robots.txt lo prohíbe: el registro deja la fuente sin canales y nadie la pide.
  if (!channels.length || (s.geoblock && s.geoblock.status === 'robots-disallowed')) continue;
  // «n8n»: solo lo que el registro asigna a n8n. «todas»: también mide las del Perú.
  if (scope === 'n8n' && !channels.includes('n8n')) continue;
  const urls = [s.url, ...(s.alt_urls || [])];
  urls.forEach((raw, k) => {
    const url = String(raw).replace('{year}', year);
    // Una alternativa es a veces otra cosa (el listado HTML de una API JSON):
    // conserva el tipo esperado solo si la URL termina igual que la principal
    // (misma extensión o, sin extensión, la misma dirección).
    // El registro trae «alt_expect» (alineado con alt_urls); en registros
    // anteriores se deduce por la terminación.
    const altExpect = k && Array.isArray(s.alt_expect) ? s.alt_expect[k - 1] : null;
    const expect = altExpect || (!k || ext(url) === ext(s.url) ? s.expect || 'any' : 'any');
    if (seen.has(url)) return;
    seen.add(url);
    out.push({ json: {
      id: k ? `${s.id}#${k + 1}` : s.id, group: s.group, name: s.name, url, expect,
      follow: k === 0 && s.follow ? s.follow : null, channels: s.channels || [], pass: 1, registry: origin,
    } });
  });
}
return out;
