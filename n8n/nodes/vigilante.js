// ¿El sitio publicado está al día? Falla (y el «Error workflow» de n8n avisa)
// si data/manifest.json (lo publica cada actualización, con «generatedAt») no responde, no se puede leer o su «generatedAt» es más
// viejo que max_age_hours.
const cfg = $('Configuración').first().json;
const r = $input.first().json;
const maxAge = Number(cfg.max_age_hours) || 30;
const where = `${cfg.site} (data/manifest.json)`;
if (r.error || r.statusCode !== 200) {
  const why = r.error ? (r.error.message || JSON.stringify(r.error)).slice(0, 200) : `HTTP ${r.statusCode}`;
  throw new Error(`El sitio no responde: ${where}: ${why}`);
}
let d;
try {
  const body = r.data !== undefined ? r.data : r.body;
  d = typeof body === 'string' ? JSON.parse(body) : body;
} catch (e) {
  throw new Error(`manifest.json no es JSON válido en ${where}`);
}
const t = Date.parse(d && d.generatedAt);
if (Number.isNaN(t)) throw new Error(`manifest.json no tiene «generatedAt» en ${where}`);
const age = (Date.now() - t) / 3600000;
if (age > maxAge) {
  throw new Error(`El sitio está desactualizado: la publicación ${d.publicationId || '?'} es del ${d.generatedAt} (hace ${age.toFixed(0)} h, máximo ${maxAge} h). Revisar la actualización diaria en GitHub Actions (puede estar desactivada).`);
}
return [{ json: { resultado: 'Sitio al día', publicacion: d.publicationId || '', generado: d.generatedAt, horas: Math.round(age * 10) / 10 } }];
