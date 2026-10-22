// Arma la copia (index.json + files/) y devuelve un elemento por archivo
// nuevo que hay que subir a GitHub, más index.json, que va siempre (es el
// latido del recolector). Los archivos que no cambiaron reutilizan el blob
// de la copia anterior y no se vuelven a subir.
const cfg = $('Configuración').first().json;
const items = $input.all();
let previous = null;
let previousNote = 'sin copia anterior';
const prevResp = $('Leer copia anterior').first().json;
// Con «Response Format: Text» n8n deja el cuerpo en «data» (en algunas versiones, en «body»).
const prevBody = prevResp.data !== undefined ? prevResp.data : prevResp.body;
if (prevResp.statusCode === 200 && prevBody) {
  try {
    const j = typeof prevBody === 'string' ? JSON.parse(prevBody) : prevBody;
    if (j.schema === 'enso-relay/1') { previous = j; previousNote = `copia anterior del ${j.collected_at}`; }
  } catch (e) { previousNote = 'index.json anterior ilegible'; }
} else if (prevResp.statusCode !== 404) {
  // Sin la copia anterior se perderían las copias que se arrastran y la rama
  // se reemplazaría: mejor no publicar y que avise el «Error workflow».
  const why = prevResp.statusCode ? `HTTP ${prevResp.statusCode}` : String((prevResp.error && prevResp.error.message) || prevResp.error || 'sin respuesta');
  throw new Error(`No se pudo leer la copia anterior en ${cfg.data_branch} (${why}); no se publica para no reemplazarla. Revisar la credencial de GitHub y volver a correr.`);
}
const results = [];
for (let i = 0; i < items.length; i++) {
  const j = items[i].json;
  let body = null;
  if (j.cls.ok && items[i].binary && items[i].binary.data) {
    body = new Uint8Array(await this.helpers.getBinaryDataBuffer(i, 'data'));
  }
  results.push({ ...j, body });
}
let tokenHeader = null;
try {
  tokenHeader = (($('Leer registro').first().json || {}).headers || {})['github-authentication-token-expiration'];
} catch (e) { /* sin «Leer registro» no hay vencimiento que informar */ }
const now = new Date();
const { index, files } = buildSnapshot({
  results,
  previous,
  now,
  carryHours: Number(cfg.carry_hours) || 72,
  maxBytes: (Number(cfg.max_file_mb) || 8) * 1000000,
  collector: {
    kind: 'n8n',
    host: String(cfg.host_label || 'n8n'),
    egress: String(cfg.egress || ''),
    tz: 'America/Lima',
    workflow: 'enso-n8n-recolector',
    version: '__VERSION__',
    execution: typeof $execution !== 'undefined' ? String($execution.id) : '',
    previous: previousNote,
    registry: String($('Fuentes').first().json.registry || ''),
    // Para que el pipeline avise antes de que venza (el token se crea con un año de plazo).
    token_expires_at: parseTokenExpiry(tokenHeader),
  },
});
const indexBytes = utf8Encode(JSON.stringify(index, null, 1) + '\n');
const hbBytes = utf8Encode(JSON.stringify(heartbeat(index, now), null, 1) + '\n');
const out = [];
for (const f of files) {
  if (f.body) out.push({ json: { path: f.path, git_blob: f.git_blob, content: toBase64(f.body) } });
}
out.push({ json: { path: 'heartbeat.json', git_blob: gitBlobSha(hbBytes), content: toBase64(hbBytes) } });
const manifest = files.map((f) => ({ path: f.path, git_blob: f.git_blob }));
manifest.push({ path: 'heartbeat.json', git_blob: gitBlobSha(hbBytes) });
manifest.push({ path: 'index.json', git_blob: gitBlobSha(indexBytes) });
out.push({ json: {
  path: 'index.json', git_blob: gitBlobSha(indexBytes), content: toBase64(indexBytes),
  manifest, summary: index.summary, verdicts: index.verdicts, collected_at: index.collected_at,
  reused: files.filter((f) => !f.body).length,
} });
return out;
