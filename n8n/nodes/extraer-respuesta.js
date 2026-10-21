// Convierte la respuesta de OpenAI en {data, model, evidence} para el
// pipeline. Si el modelo falla o no devuelve JSON, responde un error HTTP
// (el pipeline lo anota y sigue sin la propuesta).
const r = $input.first().json;
const fail = (status, error) => [{ json: { status, body: { error: String(error).slice(0, 500) } } }];
if (r.error) return fail(502, `OpenAI no respondió: ${r.error.message || JSON.stringify(r.error)}`);
let body = r.body !== undefined ? r.body : r.data;
if (typeof body === 'string') { try { body = JSON.parse(body); } catch (e) { return fail(502, 'respuesta de OpenAI ilegible'); } }
if (r.statusCode !== 200) return fail(502, `OpenAI HTTP ${r.statusCode}: ${(body && body.error && body.error.message) || ''}`);
const content = body && body.choices && body.choices[0] && body.choices[0].message && body.choices[0].message.content;
let parsed;
try { parsed = JSON.parse(content); } catch (e) { return fail(502, 'el modelo no devolvió JSON'); }
// Si el modelo devolvió solo el objeto del esquema, sin envolver, se acepta igual.
const wrapped = parsed && typeof parsed === 'object' && 'data' in parsed;
const data = wrapped ? parsed.data : parsed;
if (!data || typeof data !== 'object') return fail(502, 'el modelo no devolvió «data»');
return [{ json: { status: 200, body: {
  data,
  model: body.model || String($('Configuración').first().json.model),
  evidence: wrapped && parsed.evidence && typeof parsed.evidence === 'object' ? parsed.evidence : {},
  usage: body.usage || null,
} } }];
