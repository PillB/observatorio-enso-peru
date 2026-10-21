// Clasifica cada respuesta del nodo de descarga (mismo criterio que
// tools/probe.mjs) y deja el cuerpo solo en las válidas.
const targets = $('__SOURCE_NODE__').all();
const items = $input.all();
const now = new Date().toISOString().replace(/\.\d{3}Z$/, '+00:00');
const out = [];
for (let i = 0; i < items.length; i++) {
  const it = items[i];
  // Las descargas llegan del bucle «una por una», en el mismo orden y en la
  // misma cantidad que las URL; el índice dentro de cada vuelta (pairedItem)
  // ya no sirve para emparejarlas.
  if (items.length !== targets.length) throw new Error(`Llegaron ${items.length} respuestas para ${targets.length} URL`);
  const t = targets[i].json;
  const j = it.json || {};
  let body = null;
  let error = null;
  if (j.error) {
    const e = j.error;
    error = typeof e === 'string' ? e : [e.code, e.message, e.description, e.cause && e.cause.code].filter(Boolean).join(': ') || JSON.stringify(e).slice(0, 300);
  }
  if (!error && it.binary && it.binary.data) {
    try {
      body = new Uint8Array(await this.helpers.getBinaryDataBuffer(i, 'data'));
    } catch (e) {
      body = it.binary.data.data ? new Uint8Array(Buffer.from(it.binary.data.data, 'base64')) : null;
    }
  }
  const status = j.statusCode == null ? null : j.statusCode;
  const cls = classify({ url: t.url, expect: t.expect, status, headers: j.headers || {}, body, error });
  const o = { json: { id: t.id, group: t.group, name: t.name, url: t.url, expect: t.expect, pass: t.pass || 1, fetched_at: now, cls }, pairedItem: { item: i } };
  if (cls.ok && it.binary && it.binary.data) o.binary = { data: it.binary.data };
  out.push(o);
}
return out;
