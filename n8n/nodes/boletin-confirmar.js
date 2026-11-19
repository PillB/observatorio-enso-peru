// Correo de confirmación de la suscripción (o «ya está suscrito»), que pide el sitio (functions/_lib/boletin-subs.js)
// con el secreto compartido en X-Enso-Secret (lo comprueba el disparador). El sitio arma el correo; aquí solo se
// revisa que venga bien y se pasa al nodo Gmail.
const cfg = $('Configuración').first().json;
const raw = $input.first().json.body || {};
// El sitio manda asunto y HTML en base64 (subject_b64, html_b64), porque el cortafuegos delante de n8n rechaza
// pedidos con HTML en el cuerpo. Se aceptan también los campos en claro (subject, html).
const unb64 = (v) => (typeof v === 'string' && /^[A-Za-z0-9+/=\s]*$/.test(v) ? Buffer.from(v, 'base64').toString('utf8') : null);
const b = { to: raw.to, subject: raw.subject_b64 != null ? unb64(raw.subject_b64) : raw.subject, html: raw.html_b64 != null ? unb64(raw.html_b64) : raw.html };
const [to] = parseRecipients(b.to);
if (!to || String(b.to).trim().toLowerCase() !== to || typeof b.subject !== 'string' || typeof b.html !== 'string' || b.html.length > 60000) {
  throw new Error('Pedido de confirmación inválido');
}
// Para el nodo Gmail: destinatario, asunto y HTML (el nombre del remitente sale de «Configuración»).
return [{ json: { to, bcc: '', subject: b.subject.replace(/[\r\n]+/g, ' ').slice(0, 200), html: b.html, senderName: cfg.sender_name || 'Observatorio ENSO Perú' } }];
