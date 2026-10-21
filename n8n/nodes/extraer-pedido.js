// Extracción con OpenAI para los informes del ENFEN: valida la petición del
// pipeline (python/enso/reports.py, llm_extract) y arma la llamada al modelo.
// El modelo solo propone: el pipeline vuelve a validar con el esquema y
// guarda el resultado como propuesta para revisión, nunca lo publica.
const cfg = $('Configuración').first().json;
const req = $('Petición del pipeline').first().json.body || {};
const KINDS = ['enfen-informe', 'enfen-perspectiva'];
// Una petición mal formada se responde con 400 (rama «no» del nodo siguiente).
const invalid = !KINDS.includes(req.kind) ? `«kind» debe ser ${KINDS.join(' o ')}`
  : !req.schema || typeof req.schema !== 'object' ? 'falta «schema» (objeto JSON)'
    : typeof req.text !== 'string' || !req.text.trim() ? 'falta «text»' : null;
if (invalid) return [{ json: { ok: false, status: 400, body: { error: invalid } } }];
const maxChars = Number(cfg.max_chars) || 120000;
const SYSTEM = [
  'Extraes datos de un documento oficial del ENFEN (Perú) a JSON.',
  'Reglas:',
  '1. Usa solo lo que el texto dice. No calcules, no completes, no uses conocimiento externo.',
  '2. Sigue exactamente el esquema JSON dado: mismos nombres de campos y tipos.',
  '3. Si un valor no aparece o no estás seguro, pon null.',
  '4. Responde un objeto JSON con dos claves: "data" (el objeto que sigue el esquema) y',
  '   "evidence" (objeto que asigna a cada ruta de campo con valor, p. ej. "indices.provisional[0].value",',
  '   la cita textual del documento de donde sale, de 300 caracteres como máximo).',
].join('\n');
const user = [
  `Tipo de documento: ${req.kind}`,
  `URL: ${req.url || 'desconocida'}`,
  `Publicado: ${req.published || 'desconocido'}`,
  'Esquema JSON de "data":',
  JSON.stringify(req.schema),
  'Texto del documento:',
  req.text.slice(0, maxChars),
].join('\n\n');
return [{ json: {
  ok: true,
  kind: req.kind,
  request: {
    model: String(cfg.model),
    temperature: 0,
    response_format: { type: 'json_object' },
    messages: [{ role: 'system', content: SYSTEM }, { role: 'user', content: user }],
  },
} }];
