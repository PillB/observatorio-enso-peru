// Mueve la rama de datos al commit nuevo: la crea si no existe y si existe
// la reemplaza (force, porque el commit no tiene padre). Las expresiones de
// los parámetros JSON no pueden usar $('Nodo') en n8n 1.x: se arma aquí.
const cfg = $('Configuración').first().json;
const commit = $('Crear commit').first().json.sha;
const exists = $input.first().json.statusCode === 200;
const base = `${cfg.api}/repos/${cfg.repo}/git/refs`;
return [{ json: exists
  ? { method: 'PATCH', url: `${base}/heads/${cfg.data_branch}`, body: { sha: commit, force: true }, commit }
  : { method: 'POST', url: base, body: { ref: `refs/heads/${cfg.data_branch}`, sha: commit }, commit } }];
