// Resultado de la corrida. Falla (y n8n la marca en rojo) si la copia no
// llegó a GitHub; la falta de fuentes se ve en index.json, no es un error
// del recolector.
const cfg = $('Configuración').first().json;
const r = $input.first().json;
const info = $('Armar árbol').first().json;
const ok = r.statusCode === 200 || r.statusCode === 201;
if (!ok) {
  throw new Error(`No se pudo actualizar ${cfg.repo}@${cfg.data_branch}: HTTP ${r.statusCode} ${JSON.stringify(r.body || r.data || '').slice(0, 300)}`);
}
return [{ json: {
  resultado: `Copia publicada en ${cfg.repo}@${cfg.data_branch}`,
  commit: $('Preparar rama').first().json.commit,
  recolectado: info.collected_at,
  resumen: info.summary,
  veredictos: info.verdicts,
  archivos_subidos: info.uploaded,
  archivos_reutilizados: info.reused,
} }];
