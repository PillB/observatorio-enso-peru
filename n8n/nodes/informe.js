// Informe de la validación: un resumen y una fila por fuente, primero las
// que fallaron. Lo que no responde por bloqueo se informa como bloqueo.
const items = $input.all().map((it) => it.json);
// Los robots.txt leídos no son fuentes: solo deciden si se pidieron sus URL.
const results = pickResults(items.filter((j) => j.role !== 'robots'));
const counts = {};
for (const r of results) counts[r.cls.verdict] = (counts[r.cls.verdict] || 0) + 1;
const groups = {};
for (const r of results) {
  const g = groups[r.group] || (groups[r.group] = { ok: 0, total: 0 });
  g.total++;
  if (r.cls.ok) g.ok++;
}
const rank = (r) => (r.cls.ok ? 1 : 0);
results.sort((a, b) => rank(a) - rank(b) || String(a.group).localeCompare(String(b.group)) || String(a.id).localeCompare(String(b.id)));
const rows = results.map((r) => ({
  resultado: r.cls.ok ? 'OK' : 'FALLA',
  veredicto: r.cls.verdict,
  alcance: r.cls.reach,
  bloqueo: r.cls.block || '',
  http: r.cls.status ?? '',
  bytes: r.cls.bytes,
  formato: r.cls.detected,
  entradas: r.cls.items ?? '',
  mas_reciente: r.cls.newest || '',
  grupo: r.group,
  id: r.id,
  url: r.url,
  nota: r.cls.note || '',
  intento: r.pass || 1,
  medido: r.fetched_at,
  robots: r.robots || '',
}));
// URL «robots: unknown» que no se pidieron: su robots.txt lo prohíbe o no respondió.
for (const s of notRequested(items)) {
  rows.unshift({ resultado: 'NO PEDIDA', veredicto: 'not_requested', alcance: s.robots === 'unreachable' ? s.reach : '', bloqueo: '', http: '', bytes: '', formato: '',
    entradas: '', mas_reciente: '', grupo: s.group, id: s.id, url: s.url, nota: s.note, intento: '', medido: s.fetched_at, robots: s.robots });
}
const total = results.length;
const ok = results.filter((r) => r.cls.ok).length;
const summary = {
  resultado: `RESUMEN: ${ok}/${total} fuentes responden desde este n8n`,
  veredicto: JSON.stringify(counts),
  alcance: '',
  bloqueo: '', http: '', bytes: '', formato: '', entradas: '', mas_reciente: '',
  grupo: Object.entries(groups).map(([g, v]) => `${g} ${v.ok}/${v.total}`).join('; '),
  id: 'resumen', url: '', nota: `versión del flujo __VERSION__`, intento: '', medido: new Date().toISOString(), robots: '',
};
return [summary, ...rows].map((json) => ({ json }));
