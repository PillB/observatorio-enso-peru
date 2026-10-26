// Segunda pasada: reintenta lo que falló por causas pasajeras (tiempo de
// espera, conexión cortada, 5xx, 429), sigue los enlaces que el registro
// indica (``follow``: p. ej. los PDF enlazados desde un listado) y agrega
// los PDF del ENFEN que se deducen de sus listados (mismo criterio que el
// pipeline). Si no hay nada que hacer, no devuelve nada y la rama de la
// segunda pasada no corre.
const items = $input.all();
const out = [];
const okUrls = new Set(items.filter((it) => it.json.cls.ok).map((it) => it.json.url));
const queued = new Set();
const add = (t) => {
  if (okUrls.has(t.url) || queued.has(t.url)) return;
  queued.add(t.url);
  out.push({ json: { pass: 2, ...t } });
};
for (const it of items) {
  const j = it.json;
  if (j.role === 'robots') {
    // Las URL que su robots.txt permite (o que no tiene reglas) se piden ahora, y en una entidad
    // pública del Perú también las demás salvo detrás de una verificación («fetch», nodo Analizar).
    // Un robots.txt que no respondió no se reintenta.
    for (const { pass, fetch, ...d } of j.deferred) if (fetch) add(d);
    continue;
  }
  if (!j.cls.ok && j.cls.transient) add({ id: j.id, group: j.group, name: j.name, url: j.url, expect: j.expect, robots: j.robots, robots_public: j.robots_public, crawl_delay: j.crawl_delay });
}
const pages = [];
for (let i = 0; i < items.length; i++) {
  const j = items[i].json;
  if (j.role === 'robots' || !j.cls.ok || !items[i].binary || !items[i].binary.data) continue;
  const isEnfen = j.group === 'enfen' || /^enfen-comunicados/.test(j.id);
  if (!isEnfen && !j.follow) continue;
  const text = utf8Decode(new Uint8Array(await this.helpers.getBinaryDataBuffer(i, 'data')));
  if (isEnfen) pages.push({ url: j.url, text });
  if (j.follow && j.follow.pattern) {
    let rx;
    try { rx = new RegExp(j.follow.pattern, 'gi'); } catch (e) { continue; }
    // Solo enlaces del mismo servidor que la página: el robots.txt de otro servidor no se leyó.
    const host = (u) => ((/^https?:\/\/([^/?#]+)/i.exec(u) || [])[1] || '').toLowerCase();
    const found = [...new Set((text.match(rx) || []).map((u) => u.replace(/&amp;/g, '&')))]
      .filter((u) => host(u) === host(j.url)).slice(0, Number(j.follow.max) || 8);
    for (const url of found) {
      add({ id: `${j.id}:enlace`, group: j.group, name: `${j.name} (documento enlazado)`, url, expect: /\.pdf\b/i.test(url) ? 'pdf' : 'any' });
    }
  }
}
for (const url of deriveEnfenTargets(pages)) {
  // Desde la API de WordPress llega la página de la entrada (HTML), no el PDF.
  const pdf = /\.pdf(?:[?#]|$)|wpdmdl=/i.test(url);
  add({ id: 'enfen-pdf', group: 'enfen', name: `Comunicado oficial del ENFEN (${pdf ? 'PDF' : 'página'})`, url, expect: pdf ? 'pdf' : 'any' });
}
// Intervalo entre peticiones al mismo servidor público del Perú (nodo «Pausa (2.ª pasada)»).
pacing(out.map((o) => o.json)).forEach((p, i) => { out[i].json.pause_s = p; });
return out;
