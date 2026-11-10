// ¿Hay que mandar el boletín? Lee data/boletin.json del sitio publicado (nodo «Leer boletín») y la última
// edición que este flujo mandó (datos estáticos del flujo), y decide con lib/boletin.js. Si el sitio no responde o el
// boletín es viejo, la ejecución falla y el «Error workflow» de n8n avisa. No guarda nada: eso lo hace «Guardar
// estado» después de que Gmail mandó el correo, así un envío que falla se vuelve a intentar en la hora siguiente.
const cfg = $('Configuración').first().json;
const r = $input.first().json;
const where = `${cfg.site} (data/boletin.json)`;
if (r.error || r.statusCode !== 200) {
  const why = r.error ? (r.error.message || JSON.stringify(r.error)).slice(0, 200) : `HTTP ${r.statusCode}`;
  throw new Error(`No se pudo leer el boletín: ${where}: ${why}`);
}
let doc;
try {
  const body = r.data !== undefined ? r.data : r.body;
  doc = typeof body === 'string' ? JSON.parse(body) : body;
} catch (e) {
  throw new Error(`boletin.json no es JSON válido en ${where}`);
}
const st = $getWorkflowStaticData('global');
const out = decide(doc, cfg, { lastEdition: st.lastEdition, lastDigestDay: st.lastDigestDay }, Date.now());
out.lastEdition = st.lastEdition || 0;
return [{ json: out }];
