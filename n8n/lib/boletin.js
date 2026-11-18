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
  const names = Object.fromEntries((Array.isArray(doc.segments) ? doc.segments : []).map((s) => [s.code, s.name]));
  const recent = Array.isArray(doc.recent) ? doc.recent : [];
  const eds = recent.filter((r) => Number(r.edition) > lastEdition).sort((a, b) => a.edition - b.edition);
  // Si n8n estuvo apagado más de lo que guarda ``recent``, se avisa: faltan ediciones de por medio.
  const gap = eds.length && lastEdition > 0 && Number(eds[0].edition) > lastEdition + 1;
  const changes = [];
  for (const r of eds) for (const c of r.changes || []) changes.push({ ...c, edition: r.edition });
  return { editions: eds.map((r) => r.edition), changes: consolidate(changes, names), gap };
}

const LEVEL_WORD = { 3: 'rojo', 2: 'naranja', 1: 'amarillo', 0: 'sin nivel', '-1': 'sin avisos' };

/**
 * Los cambios de varias ediciones, sin lo que se repite ni lo que se deshizo antes de mandarlos: un departamento que
 * subió y volvió a su nivel, un aviso que salió y se canceló, el ENFEN que cambió y volvió, dos comunicados seguidos
 * (cuenta el último). Lo que queda dice el cambio neto desde el último correo. Los cambios de ediciones viejas, sin
 * ``key``/``from``, pasan como están (sin repetir el mismo texto).
 */
function consolidate(changes, names = {}) {
  const groups = new Map();
  const order = [];
  changes.forEach((c, i) => {
    const k = c.rule === 'inicial' ? `i${i}`
      : /^departamento-/.test(c.rule) && c.dep && c.from !== undefined ? `dep:${c.dep}`
        : /^aviso-/.test(c.rule) && c.key ? `aviso:${c.key}`
          : (c.rule === 'enfen-estado' || c.rule === 'noaa-estado') && c.from !== undefined ? c.rule
            : c.rule === 'enfen-comunicado' || c.rule === 'escenario-nuevo' ? c.rule
              : `t:${c.text}`;
    if (!groups.has(k)) { groups.set(k, []); order.push(k); }
    groups.get(k).push(c);
  });
  const out = [];
  for (const k of order) {
    const g = groups.get(k);
    const last = g[g.length - 1];
    if (k.startsWith('dep:')) {
      const from = Number(g[0].from);
      const to = Number(last.rank);
      if (from === to) continue; // subió y volvió (o al revés): nada que contar
      if (g.length === 1) { out.push(last); continue; }
      const up = to > from;
      const name = names[last.dep] || String(last.text).split(' ')[0];
      out.push({ ...last, from, rule: up ? 'departamento-sube' : 'departamento-baja', tier: up && to >= 2 ? 'inmediata' : 'resumen', text: `${name} ${up ? 'sube' : 'baja'} de ${LEVEL_WORD[from]} a ${LEVEL_WORD[to]}.` });
    } else if (k.startsWith('aviso:')) {
      if (g[0].rule === 'aviso-nuevo' && last.rule === 'aviso-cancelado') continue; // salió y se canceló entre dos correos
      out.push(g[0].rule === 'aviso-nuevo' && last.rule !== 'aviso-nuevo' ? { ...last, tier: g.some((c) => c.tier === 'inmediata') && last.rule !== 'aviso-cancelado' ? 'inmediata' : last.tier } : last);
    } else if (k === 'enfen-estado' || k === 'noaa-estado') {
      if (g[0].from === last.to) continue;
      out.push(g.length === 1 ? last : { ...last, from: g[0].from, text: k === 'enfen-estado' ? `El ENFEN cambió su estado: de «${g[0].from}» a «${last.to}».` : `La NOAA pasó de «${g[0].from}» a «${last.to}».` });
    } else out.push(last);
  }
  // Con un cambio de estado del ENFEN, el comunicado que lo trae ya está dicho.
  const res = out.some((c) => c.rule === 'enfen-estado') ? out.filter((c) => c.rule !== 'enfen-comunicado') : out;
  const rank = { inmediata: 0, resumen: 1 };
  return res.map((c, i) => [c, i]).sort((a, b) => (rank[a[0].tier] ?? 2) - (rank[b[0].tier] ?? 2) || (b[0].rank || 0) - (a[0].rank || 0) || a[1] - b[1]).map(([c]) => c);
}

/** Bloque «Qué cambió» del correo, con los cambios de todas las ediciones nuevas. */
function changesHtml(changes, gap) {
  const list = changes.filter((c) => c.rule !== 'inicial');
  if (!list.length && !gap) return '';
  // «Importante» solo distingue algo cuando hay de los dos tipos; si todos lo son, ya lo dice el asunto.
  const mixed = list.some((c) => c.tier === 'inmediata') && list.some((c) => c.tier !== 'inmediata');
  const tag = (c) => (mixed && c.tier === 'inmediata' ? '<strong style="color:#a3141f">Importante:</strong> ' : '');
  const items = list.slice(0, 12).map((c) => `<li style="margin:0 0 4px">${tag(c)}${esc(c.text)}</li>`).join('');
  return '<div style="background:#fff8e1;border-left:4px solid #ef8a2b;padding:8px 12px;margin:0 0 12px">'
    + '<div style="font:700 13px Arial,sans-serif;margin:0 0 4px">Qué cambió desde el último correo</div>'
    + `<ul style="margin:0;padding-left:18px;font:13px/1.4 Arial,sans-serif">${items}</ul>`
    + (list.length > 12 ? `<p style="margin:4px 0 0;font:12px Arial,sans-serif">Y ${list.length - 12} cambios más en el sitio.</p>` : '')
    + (gap ? '<p style="margin:4px 0 0;font:12px Arial,sans-serif">Hubo ediciones que este correo no alcanzó a cubrir: vea el boletín completo en el sitio.</p>' : '')
    + '</div>';
}

/** Cambios que le tocan a quien eligió departamentos: los de esos departamentos y los de todo el país (ENFEN, NOAA,
 * CENEPRED). Un cambio sin ``deps`` (de una edición anterior a la suscripción por departamentos) cuenta para todos. */
function relevantChanges(changes, deps) {
  if (!Array.isArray(deps) || !deps.length) return changes;
  return changes.filter((c) => !Array.isArray(c.deps) || !c.deps.length || c.deps.some((d) => deps.includes(d)));
}

// ------------------------------------------------------------------ correo en MIME para la API de Gmail
const toB64 = (s) => (typeof Buffer !== 'undefined' ? Buffer.from(String(s), 'utf8').toString('base64') : btoa(unescape(encodeURIComponent(String(s)))));
const oneLine = (s) => String(s == null ? '' : s).replace(/[\r\n]+/g, ' ').trim();
/** Cabecera con acentos (RFC 2047), en trozos para no pasar de 75 caracteres por palabra codificada. */
function encHeader(s) {
  const v = oneLine(s);
  if (/^[\x20-\x7e]*$/.test(v)) return v;
  const parts = [];
  for (let i = 0; i < v.length; i += 30) parts.push(`=?UTF-8?B?${toB64(v.slice(i, i + 30))}?=`);
  return parts.join('\r\n ');
}
const wrap76 = (s) => s.replace(/.{1,76}/g, '$&\r\n');
/**
 * Un correo listo para la API de Gmail (users.messages.send, campo «raw»): multipart/alternative con texto y HTML en
 * base64, y las cabeceras de la lista. Con List-Unsubscribe y List-Unsubscribe-Post (RFC 2369 y RFC 8058) Gmail,
 * Yahoo y Apple Mail muestran «Anular suscripción» junto al remitente; el nodo de Gmail de n8n no deja poner cabeceras,
 * por eso se manda por la API.
 */
function mime({ from, to, bcc, subject, html, text, headers = {} }, seed = '') {
  const b = `enso-${toB64(`${seed}${to}${subject}`).replace(/[^A-Za-z0-9]/g, '').slice(0, 24)}`;
  const lines = [
    from ? `From: ${from}` : null, `To: ${oneLine(to)}`, bcc ? `Bcc: ${oneLine(bcc)}` : null, `Subject: ${encHeader(subject)}`,
    'MIME-Version: 1.0', ...Object.entries(headers).map(([k, v]) => `${k}: ${oneLine(v)}`),
    `Content-Type: multipart/alternative; boundary="${b}"`, '',
    `--${b}`, 'Content-Type: text/plain; charset=UTF-8', 'Content-Transfer-Encoding: base64', '', wrap76(toB64(text || '')),
    `--${b}`, 'Content-Type: text/html; charset=UTF-8', 'Content-Transfer-Encoding: base64', '', wrap76(toB64(html || '')),
    `--${b}--`, '',
  ].filter((x) => x !== null);
  return toB64(lines.join('\r\n')).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

const withBlock = (html, block) => (/<!--cambios-->[\s\S]*?<!--\/cambios-->/.test(html) ? html.replace(/<!--cambios-->[\s\S]*?<!--\/cambios-->/, `<!--cambios-->${block}<!--/cambios-->`) : html);
const cut = (html, tag) => html.replace(new RegExp(`<!--${tag}-->[\\s\\S]*?<!--\\/${tag}-->`, 'g'), '');

/**
 * El cuerpo de un correo. El primero lleva el boletín completo. Los demás, solo lo nuevo: qué cambió, la frase y los
 * contadores de ahora y el botón al boletín; sin el mapa, los más críticos ni «qué hacer» (iguales a los del correo
 * anterior y a un clic en el sitio), y sin el recuadro del ENFEN si el ENFEN no cambió.
 */
function body(doc, changes, gap, full, siteUrl = '') {
  const block = full ? '' : changesHtml(changes, gap);
  let html = withBlock(String(doc.email.html), block);
  if (!full) {
    html = cut(html, 'detalle');
    if (!changes.some((c) => /^enfen-/.test(c.rule))) html = cut(html, 'enfen');
  }
  if (full) return { block, html, text: String(doc.email.text || '') };
  const list = changes.filter((c) => c.rule !== 'inicial');
  const site = String(siteUrl || '').replace(/\/?$/, '/');
  const text = [`Qué cambió desde el último correo:\n${list.slice(0, 12).map((c) => `- ${c.text}`).join('\n')}`
    + (list.length > 12 ? `\n- Y ${list.length - 12} cambios más en el sitio.` : '') + (gap ? '\n(Hubo ediciones que este correo no alcanzó a cubrir.)' : ''),
  doc.summary ? `Ahora: ${doc.summary}` : '',
  `Boletín completo (N° ${doc.edition}): ${siteUrl ? `${site}#/boletin` : 'en el sitio'}`,
  'Este boletín no es una alerta oficial: los niveles son los de cada institución.'].filter(Boolean).join('\n\n');
  return { block, html, text };
}

/** El asunto: en un correo de cambios, el cambio principal (lo que hay que saber sin abrirlo), no el estado de siempre. */
function subjectFor(doc, changes, prefix, full) {
  const base = oneLine(doc.email.subject);
  if (full) return `${prefix}${base}`;
  const list = changes.filter((c) => c.rule !== 'inicial');
  if (!list.length) return `${prefix}${base}`;
  let lead = oneLine(list[0].text).replace(/\.$/, '');
  if (lead.length > 90) lead = `${lead.slice(0, 89).replace(/\s+\S*$/, '')}…`;
  const more = list.length > 1 ? ` (+${list.length - 1} ${list.length === 2 ? 'cambio' : 'cambios'})` : '';
  return `${prefix}${lead}${more} · Boletín El Niño N° ${doc.edition}`;
}

/** El pie de cada suscriptor: por qué le llega y sus enlaces de preferencias y de baja. */
function personalize(html, text, sub, names) {
  const deps = (sub.deps || []).map((d) => names[d] || d);
  const why = `Recibe este correo porque se suscribió al Boletín de eventos El Niño${deps.length ? ` (departamentos: ${deps.join(', ')})` : ''}.`;
  const foot = `<p style="margin:10px 0 0;font:12px/1.5 Arial,sans-serif;color:#4a5560">${esc(why)} <a href="${esc(sub.preferencias)}" style="color:#0b4f71">Preferencias</a> · <a href="${esc(sub.baja)}" style="color:#0b4f71">Darse de baja</a></p>`;
  const h = /<!--baja-->[\s\S]*?<!--\/baja-->/.test(html) ? html.replace(/<!--baja-->[\s\S]*?<!--\/baja-->/, `<!--baja-->${foot}<!--/baja-->`) : html.replace(/<\/body>/i, `${foot}</body>`);
  return { html: h, text: `${text}\n\n—\n${why}\nPreferencias: ${sub.preferencias}\nDarse de baja: ${sub.baja}` };
}

/** Suscripciones válidas de /api/boletin/lista (cada una con su correo, frecuencia, departamentos y enlaces). */
function cleanSubs(list) {
  const seen = new Set();
  const out = [];
  for (const s of Array.isArray(list) ? list : []) {
    const [email] = parseRecipients(s && s.email);
    if (!email || seen.has(email) || !/^https:\/\//.test(String(s.baja || '')) || !/^https:\/\//.test(String(s.bajaPost || ''))) continue;
    seen.add(email);
    out.push({ email, frecuencia: ['todo', 'importantes', 'diario'].includes(s.frecuencia) ? s.frecuencia : 'todo', deps: Array.isArray(s.deps) ? s.deps.map(String) : [], baja: s.baja, bajaPost: s.bajaPost, preferencias: String(s.preferencias || s.baja) });
  }
  return out;
}

/**
 * Qué hacer con el boletín publicado. ``cfg``: la configuración del flujo; ``st``: el estado guardado
 * ({lastEdition, lastDigestDay, dailyEdition, dailyDay}); ``now``: milisegundos; ``list``: las suscripciones de
 * /api/boletin/lista (o nada). Devuelve {send, reason, messages, ...}: un mensaje para la lista fija de «to»/«bcc» y uno
 * por suscriptor, cada uno con su «raw» para la API de Gmail.
 *
 * Dos vías: la principal (avisos importantes al momento y el resumen diario de los menores) para «to», «bcc» y las
 * suscripciones «todo» e «importantes» (estas solo los importantes); y la diaria (un correo al día con todo lo que
 * cambió) para las suscripciones «diario», con su propio puntero de edición.
 */
function decide(doc, cfg, st, now, list = null) {
  if (!doc || doc.schema !== 'enso-boletin/1' || !Array.isArray(doc.segments) || !doc.email) {
    throw new Error('boletin.json no tiene el formato esperado (enso-boletin/1)');
  }
  const maxAge = Number(cfg.max_age_hours) || 36;
  const age = (now - Date.parse(doc.cutoff)) / 3600000;
  if (!(age <= maxAge)) {
    throw new Error(`El boletín publicado es viejo: corte ${doc.cutoff} (hace ${Math.round(age)} h, máximo ${maxAge} h). Revisar la actualización diaria.`);
  }
  st = st || {};
  const to = parseRecipients(cfg.to);
  const bcc = parseRecipients(cfg.bcc).filter((a) => !to.includes(a));
  const subs = cleanSubs(list).filter((s) => !to.includes(s.email) && !bcc.includes(s.email));
  const restartedFor = (ed, at) => Number(ed) >= doc.edition && Date.parse(doc.editionAt) > Date.parse(at || '');
  const restarted = restartedFor(st.lastEdition, st.lastEditionAt);
  const last = restarted ? 0 : Number(st.lastEdition) || 0;
  const clock = limaClock(now);
  const digestHour = Number.isFinite(Number(cfg.digest_hour)) && String(cfg.digest_hour) !== '' ? Number(cfg.digest_hour) : 7;
  const names = Object.fromEntries(doc.segments.map((s) => [s.code, s.name]));
  const base = { edition: doc.edition, editionAt: doc.editionAt, cutoff: doc.cutoff, recipients: to.length + bcc.length + subs.length };
  const host = String(cfg.site || '').replace(/^https?:\/\//, '').replace(/\/.*$/, '') || 'enso-peru';
  const from = /^[^@\s<>"]+@[^@\s<>"]+$/.test(String(cfg.from_address || '')) ? `${encHeader(cfg.sender_name || 'Observatorio ENSO Perú')} <${cfg.from_address}>` : null;
  const listHeaders = { 'List-Id': `Boletin El Nino Peru <boletin.${host}>`, 'Auto-Submitted': 'auto-generated', Precedence: 'bulk' };
  const messages = [];
  const personal = (sub, prefix, changes, gap, first, kind) => {
    const b = body(doc, changes, gap, first, cfg.site);
    const subject = subjectFor(doc, changes, first ? '' : prefix, first);
    const p = personalize(b.html, b.text, sub, names);
    const headers = { ...listHeaders, 'List-Unsubscribe': `<${sub.bajaPost}>, <${sub.baja}>`, 'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click' };
    messages.push({ to: sub.email, kind, frecuencia: sub.frecuencia, subject, headers, raw: mime({ from, to: sub.email, subject, html: p.html, text: p.text, headers }, sub.email) });
  };

  // Vía principal.
  let reason = '';
  let main = null;
  let pending = 0;
  if (last >= doc.edition && last > 0) reason = `Sin ediciones nuevas (la última enviada es la N° ${last}).`;
  else {
    const { editions, changes, gap } = pendingChanges(doc, last);
    const first = last === 0;
    const urgent = first || changes.some((c) => c.tier === 'inmediata');
    const digestDue = clock.hour >= digestHour && st.lastDigestDay !== clock.day;
    if (!urgent && !digestDue) {
      reason = `Solo cambios para el resumen diario: se mandan a las ${digestHour}:00 (hora de Lima).`;
      pending = changes.length;
    } else {
      const kind = restarted ? 'Boletín completo (numeración reiniciada)' : first ? 'Primer boletín' : urgent ? 'Aviso' : 'Resumen diario';
      const prefix = first ? '' : urgent ? '[Aviso] ' : '[Resumen] ';
      main = { editions, changes, gap, first, urgent, kind, prefix, subject: subjectFor(doc, changes, prefix, first) };
      Object.assign(main, body(doc, changes, gap, first, cfg.site));
      if (to.length) {
        messages.push({ to: to.join(','), bcc: bcc.join(','), kind: 'lista', subject: main.subject, headers: listHeaders, raw: mime({ from, to: to.join(','), bcc: bcc.join(','), subject: main.subject, html: main.html, text: main.text, headers: listHeaders }) });
      }
      for (const s of subs) {
        if (s.frecuencia === 'diario' || (s.frecuencia === 'importantes' && !urgent)) continue;
        const rel = relevantChanges(changes, s.deps);
        if (!first && !rel.length) continue;
        personal(s, main.prefix, rel, gap, first, kind);
      }
      reason = `${kind}: ediciones ${editions.join(', ') || doc.edition}, ${changes.length} cambios.`;
    }
  }

  // Vía diaria.
  const dailySubs = subs.filter((s) => s.frecuencia === 'diario');
  let daily = null;
  const dRestart = restartedFor(st.dailyEdition, st.dailyEditionAt);
  const dLast = dRestart ? 0 : Number(st.dailyEdition) || 0;
  if (dailySubs.length && clock.hour >= digestHour && st.dailyDay !== clock.day && doc.edition > dLast) {
    const p = pendingChanges(doc, dLast);
    daily = { ...p, first: dLast === 0 };
    let n = 0;
    for (const s of dailySubs) {
      const rel = relevantChanges(p.changes, s.deps);
      if (!daily.first && !rel.length) continue;
      personal(s, '[Resumen diario] ', rel, p.gap, daily.first, 'Resumen diario');
      n++;
    }
    reason = `${reason ? `${reason} ` : ''}Resumen diario para ${n} ${n === 1 ? 'suscripción' : 'suscripciones'}.`;
  }

  if (!messages.length) {
    if (main && !to.length && !subs.length) reason = 'Falta la dirección «to» en Configuración y no hay suscripciones: no se manda nada.';
    else if (main) reason = `${reason} Ningún destinatario tiene cambios de sus departamentos.`;
    return { ...base, send: false, reason: reason || 'Nada que mandar.', pending, messages: [], mainSent: Boolean(main), dailySent: Boolean(daily), digest: main ? !main.urgent : false, digestDay: clock.day };
  }
  const willSend = cfg.send === true || cfg.send === 'true';
  const first = messages.find((m) => m.kind === 'lista') || messages[0];
  return {
    ...base, send: willSend, simulate: !willSend, reason, kind: main ? main.kind : 'Resumen diario', digest: main ? !main.urgent : false,
    digestDay: clock.day, mainSent: Boolean(main), dailySent: Boolean(daily), to: to.join(','), bcc: bcc.join(','),
    subject: main ? main.subject : first.subject, html: main ? main.html : String(doc.email.html), text: main ? main.text : String(doc.email.text || ''),
    whatsapp: doc.whatsapp || '', messages,
  };
}

/** El estado que se guarda después de mandar los correos. */
function nextState(st, sent) {
  const out = { ...(st || {}) };
  if (sent.mainSent !== false) {
    Object.assign(out, { lastEdition: sent.edition, lastEditionAt: sent.editionAt || null, lastSentAt: new Date(sent.at || Date.now()).toISOString() });
    if (sent.digest || !out.lastDigestDay) out.lastDigestDay = sent.digestDay;
  }
  if (sent.dailySent) Object.assign(out, { dailyEdition: sent.edition, dailyEditionAt: sent.editionAt || null, dailyDay: sent.digestDay });
  return out;
}

// @export
if (typeof module !== 'undefined') module.exports = { parseRecipients, limaClock, pendingChanges, consolidate, changesHtml, body, subjectFor, relevantChanges, mime, encHeader, cleanSubs, decide, nextState };
