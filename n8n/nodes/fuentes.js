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
const seen = new Set();
const out = [];
for (const s of registry.sources) {
  if (only && !s.id.includes(only) && s.group !== only) continue;
  if (scope === 'n8n' && !(s.channels || []).includes('n8n')) continue;
  const urls = [s.url, ...(s.alt_urls || [])];
  urls.forEach((raw, k) => {
    const url = String(raw).replace('{year}', year);
    if (seen.has(url)) return;
    seen.add(url);
    out.push({ json: {
      id: k ? `${s.id}#${k + 1}` : s.id, group: s.group, name: s.name, url, expect: s.expect || 'any',
      follow: k === 0 && s.follow ? s.follow : null, channels: s.channels || [], pass: 1, registry: origin,
    } });
  });
}
return out;
