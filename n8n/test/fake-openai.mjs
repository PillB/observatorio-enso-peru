#!/usr/bin/env node
// OpenAI falso (solo /v1/chat/completions) para probar el extractor de punta
// a punta. Exige «Authorization: Bearer sk-prueba» y «response_format:
// json_object»; si el texto dice «FALLA UNA VEZ» responde 429 la primera vez y «FALLA SIEMPRE», 500. GET /__last devuelve
// el último pedido recibido.
import { createServer } from 'node:http';

const PORT = Number(process.argv[process.argv.indexOf('--port') + 1] || 8790);
let last = null;
const seen = new Set();
createServer(async (req, res) => {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const send = (status, body) => { res.writeHead(status, { 'content-type': 'application/json' }); res.end(JSON.stringify(body)); };
  if (req.url === '/__last') return send(200, last || {});
  if (req.method !== 'POST' || !req.url.endsWith('/chat/completions')) return send(404, { error: { message: 'no implementado' } });
  if (req.headers.authorization !== 'Bearer sk-prueba') return send(401, { error: { message: 'clave inválida' } });
  const body = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  last = { headers: { authorization: req.headers.authorization }, body };
  if (!body.response_format || body.response_format.type !== 'json_object') return send(400, { error: { message: 'falta response_format' } });
  const user = body.messages.find((m) => m.role === 'user').content;
  if (user.includes('FALLA UNA VEZ') && !seen.has(user)) { seen.add(user); return send(429, { error: { message: 'límite simulado' } }); }
  if (user.includes('FALLA SIEMPRE')) return send(500, { error: { message: 'error interno simulado' } });
  const m = /ICEN[^0-9-]*(-?\d+[.,]\d+)/.exec(user);
  const value = m ? Number(m[1].replace(',', '.')) : null;
  return send(200, {
    model: 'gpt-prueba-2026', usage: { prompt_tokens: 10, completion_tokens: 5 },
    choices: [{ message: { role: 'assistant', content: JSON.stringify({ data: { icen: value, estado: null }, evidence: { icen: m ? m[0] : null } }) } }],
  });
}).listen(PORT, '0.0.0.0', () => console.log(`OpenAI falso en :${PORT}`));
