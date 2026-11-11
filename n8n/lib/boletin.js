// Boletín de eventos El Niño por correo: decide si se manda, a quién y con qué.
//
// El boletín lo arma la actualización diaria (python/enso/boletin.py → data/boletin.json): cada edición nueva trae
// sus cambios y la regla de cada uno («inmediata» o «resumen»), y ``recent`` guarda los de las últimas ediciones. Este
// código solo compara con la última edición que este n8n ya mandó (``lastEdition``, en los datos estáticos del flujo)
// y junta los cambios de todas las ediciones nuevas, así no se pierde ninguno aunque salgan dos entre dos revisiones
// ni se repite uno ya enviado.
//
//   - Algún cambio «inmediata» (aviso rojo o naranja nuevo, un departamento que sube a naranja o rojo, otro estado
//     del ENFEN, un aviso importante cancelado): se manda ya.
//   - Solo cambios «resumen»: se manda en la hora del resumen diario (``digestHour``, hora de Lima), una vez al día.
//   - Sin ediciones nuevas: nada.
//   - Primera vez (sin estado): el boletín completo, como «primer boletín».
//   - Numeración reiniciada (la actualización no pudo leer el boletín anterior y volvió a la N° 1): una edición con
//     número menor o igual al último enviado pero de fecha posterior (``editionAt``) es de una serie nueva y se
//     manda completa, en vez de darla por enviada.

/** Direcciones de una lista separada por comas, punto y coma o espacios, sin repetidas (en minúsculas). */
function parseRecipients(text) {
  const seen = new Set();
  const out = [];
  for (const raw of String(text || '').split(/[\s,;]+/)) {
    const a = raw.trim().toLowerCase();
    if (/^[^@\s<>"]+@[^@\s<>"]+\.[a-z]{2,}$/.test(a) && !seen.has(a)) { seen.add(a); out.push(a); }
  }
  return out;
}

/** Hora y día en Lima (UTC−5, sin horario de verano). */
function limaClock(now) {
  const d = new Date(now - 5 * 3600000);
  return { hour: d.getUTCHours(), day: d.toISOString().slice(0, 10) };
}

const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** Los cambios de las ediciones posteriores a ``lastEdition``, de la más vieja a la más nueva. */
function pendingChanges(doc, lastEdition) {
  const recent = Array.isArray(doc.recent) ? doc.recent : [];
  const eds = recent.filter((r) => Number(r.edition) > lastEdition).sort((a, b) => a.edition - b.edition);
  // Si n8n estuvo apagado más de lo que guarda ``recent``, se avisa: faltan ediciones de por medio.
  const gap = eds.length && lastEdition > 0 && Number(eds[0].edition) > lastEdition + 1;
  const changes = [];
  for (const r of eds) for (const c of r.changes || []) changes.push({ ...c, edition: r.edition });
  return { editions: eds.map((r) => r.edition), changes, gap };
}

/** Bloque «Qué cambió» del correo, con los cambios de todas las ediciones nuevas. */
function changesHtml(changes, gap) {
  const list = changes.filter((c) => c.rule !== 'inicial');
  if (!list.length && !gap) return '';
  const tag = (c) => (c.tier === 'inmediata' ? '<strong style="color:#a3141f">Importante:</strong> ' : '');
  const items = list.slice(0, 12).map((c) => `<li style="margin:0 0 4px">${tag(c)}${esc(c.text)}</li>`).join('');
  return '<div style="background:#fff8e1;border-left:4px solid #ef8a2b;padding:8px 12px;margin:0 0 12px">'
    + '<div style="font:700 13px Arial,sans-serif;margin:0 0 4px">Qué cambió desde el último correo</div>'
    + `<ul style="margin:0;padding-left:18px;font:13px/1.4 Arial,sans-serif">${items}</ul>`
    + (list.length > 12 ? `<p style="margin:4px 0 0;font:12px Arial,sans-serif">Y ${list.length - 12} cambios más en el sitio.</p>` : '')
    + (gap ? '<p style="margin:4px 0 0;font:12px Arial,sans-serif">Hubo ediciones que este correo no alcanzó a cubrir: vea el boletín completo en el sitio.</p>' : '')
    + '</div>';
}

/**
 * Qué hacer con el boletín publicado. ``cfg``: la configuración del flujo; ``st``: el estado guardado
 * ({lastEdition, lastDigestDay}); ``now``: milisegundos. Devuelve {send, reason, ...correo}.
 */
function decide(doc, cfg, st, now) {
  if (!doc || doc.schema !== 'enso-boletin/1' || !Array.isArray(doc.segments) || !doc.email) {
    throw new Error('boletin.json no tiene el formato esperado (enso-boletin/1)');
  }
  const maxAge = Number(cfg.max_age_hours) || 36;
  const age = (now - Date.parse(doc.cutoff)) / 3600000;
  if (!(age <= maxAge)) {
    throw new Error(`El boletín publicado es viejo: corte ${doc.cutoff} (hace ${Math.round(age)} h, máximo ${maxAge} h). Revisar la actualización diaria.`);
  }
  const to = parseRecipients(cfg.to);
  const bcc = parseRecipients(cfg.bcc).filter((a) => !to.includes(a));
  const lastAt = Date.parse((st && st.lastEditionAt) || '');
  const restarted = Number(st && st.lastEdition) >= doc.edition && Date.parse(doc.editionAt) > lastAt;
  const last = restarted ? 0 : Number(st && st.lastEdition) || 0;
  const base = { edition: doc.edition, editionAt: doc.editionAt, cutoff: doc.cutoff, recipients: to.length + bcc.length };
  if (last >= doc.edition && last > 0) return { ...base, send: false, reason: `Sin ediciones nuevas (la última enviada es la N° ${last}).` };
  const { editions, changes, gap } = pendingChanges(doc, last);
  const first = last === 0;
  const urgent = first || changes.some((c) => c.tier === 'inmediata');
  const clock = limaClock(now);
  const digestHour = Number.isFinite(Number(cfg.digest_hour)) && String(cfg.digest_hour) !== '' ? Number(cfg.digest_hour) : 7;
  const digestDue = clock.hour >= digestHour && (!st || st.lastDigestDay !== clock.day);
  if (!urgent && !digestDue) {
    return { ...base, send: false, reason: `Solo cambios para el resumen diario: se mandan a las ${digestHour}:00 (hora de Lima).`, pending: changes.length };
  }
  if (!to.length) return { ...base, send: false, reason: 'Falta la dirección «to» en Configuración: no se manda nada.' };
  const kind = restarted ? 'Boletín completo (numeración reiniciada)' : first ? 'Primer boletín' : urgent ? 'Aviso' : 'Resumen diario';
  const subject = `${first ? '' : urgent ? '[Aviso] ' : '[Resumen] '}${doc.email.subject}`;
  const block = first ? '' : changesHtml(changes, gap);
  let html = String(doc.email.html);
  html = /<!--cambios-->[\s\S]*?<!--\/cambios-->/.test(html) ? html.replace(/<!--cambios-->[\s\S]*?<!--\/cambios-->/, `<!--cambios-->${block}<!--/cambios-->`) : html;
  const text = (block ? `Qué cambió desde el último correo:\n${changes.filter((c) => c.rule !== 'inicial').slice(0, 12).map((c) => `- ${c.text}`).join('\n')}\n\n` : '') + String(doc.email.text || '');
  return {
    ...base, send: cfg.send === true || cfg.send === 'true', simulate: !(cfg.send === true || cfg.send === 'true'),
    reason: `${kind}: ediciones ${editions.join(', ') || doc.edition}, ${changes.length} cambios.`,
    kind, digest: !urgent, digestDay: clock.day, to: to.join(','), bcc: bcc.join(','), subject, html, text,
    whatsapp: doc.whatsapp || '',
  };
}

/** El estado que se guarda después de mandar el correo. */
function nextState(st, sent) {
  const out = { ...(st || {}), lastEdition: sent.edition, lastEditionAt: sent.editionAt || null, lastSentAt: new Date(sent.at || Date.now()).toISOString() };
  if (sent.digest || !out.lastDigestDay) out.lastDigestDay = sent.digestDay;
  return out;
}

// @export
if (typeof module !== 'undefined') module.exports = { parseRecipients, limaClock, pendingChanges, changesHtml, decide, nextState };
