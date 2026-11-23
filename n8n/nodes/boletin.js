// ¿Hay que mandar el boletín? Lee data/boletin.json del sitio publicado (nodo «Leer boletín»), las suscripciones de
// /api/boletin/lista si «use_list» está activo (nodo «Leer suscripciones») y la última edición que este flujo mandó
// (datos estáticos del flujo), y decide con lib/boletin.js. Si el sitio no responde o el boletín es viejo, la
// ejecución falla y el «Error workflow» de n8n avisa. No guarda nada: eso lo hace «Guardar estado» después de que
// Gmail mandó los correos, así un envío que falla se vuelve a intentar en la hora siguiente.
const cfg = $('Configuración').first().json;
const r = $('Leer boletín').first().json;
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
let list = null;
if (cfg.use_list === true || cfg.use_list === 'true') {
  const l = $('Leer suscripciones').first().json;
  if (l.error || l.statusCode !== 200) {
    // Sin la lista no se manda a nadie de ella, pero tampoco se da la edición por enviada: falla y se reintenta.
    const raw = l.data !== undefined ? l.data : l.body;
    let said = '';
    try { said = (typeof raw === 'string' ? JSON.parse(raw) : raw || {}).error || ''; } catch { said = String(raw || '').slice(0, 200); }
    const hint = l.statusCode === 401 ? ' La credencial de «Leer suscripciones» debe ser «Lista del boletín ENSO» (Header Auth: Name «Authorization», Value «Bearer » + BOLETIN_LIST_TOKEN de Cloudflare, sin espacios ni saltos de línea de más).'
      : l.statusCode === 503 ? ' Al sitio le falta configuración (el mensaje dice qué); después de cambiar un secreto en Cloudflare hay que volver a desplegar.'
        : l.statusCode === 403 ? ' Algo delante del sitio corta el pedido.' : '';
    const why = l.error ? (l.error.message || JSON.stringify(l.error)).slice(0, 200) : `HTTP ${l.statusCode}${said ? `: ${String(said).slice(0, 400)}` : ''}.${hint}`;
    throw new Error(`No se pudo leer la lista de suscripciones (${cfg.list_url || 'api/boletin/lista'}): ${why}`);
  }
  const body = l.data !== undefined ? l.data : l.body;
  list = (typeof body === 'string' ? JSON.parse(body) : body).subs || [];
}
const st = $getWorkflowStaticData('global');
const keys = ['lastEdition', 'lastEditionAt', 'lastDigestDay', 'dailyEdition', 'dailyEditionAt', 'dailyDay', 'weeklyEdition', 'weeklyEditionAt', 'weeklyWeek', 'welcomed'];
const out = decide(doc, cfg, Object.fromEntries(keys.map((k) => [k, st[k]])), Date.now(), list);
out.lastEdition = st.lastEdition || 0;
return [{ json: out }];
