// Comprueba que GitHub guardó cada blob con el SHA calculado aquí y arma el
// árbol completo de la copia (los archivos reutilizados y los nuevos).
const sent = $('Preparar copia').all();
const got = $input.all();
if (got.length !== sent.length) throw new Error(`GitHub devolvió ${got.length} blobs para ${sent.length} archivos`);
for (let i = 0; i < sent.length; i++) {
  const want = sent[i].json.git_blob;
  const have = got[i].json.sha;
  if (want !== have) throw new Error(`blob de ${sent[i].json.path}: GitHub devolvió ${have}, se esperaba ${want}`);
}
const last = sent[sent.length - 1].json;
const tree = last.manifest.map((f) => ({ path: f.path, mode: '100644', type: 'blob', sha: f.git_blob }));
const groups = Object.entries(last.summary || {}).map(([g, v]) => `${g} ${v}`).join(', ');
const message = `relay n8n: ${last.collected_at} (${groups || 'sin fuentes'})`;
return [{ json: { tree, message, summary: last.summary, verdicts: last.verdicts, collected_at: last.collected_at, uploaded: sent.length, reused: last.reused } }];
