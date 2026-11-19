// Correo de confirmación de la suscripción (o «ya está suscrito»), que pide el sitio (functions/_lib/boletin-subs.js)
// con el secreto compartido en X-Enso-Secret (lo comprueba el disparador). El sitio arma el correo; aquí solo se
// revisa que venga bien y se pasa al nodo Gmail.
const cfg = $('Configuración').first().json;
const b = $input.first().json.body || {};
const [to] = parseRecipients(b.to);
if (!to || String(b.to).trim().toLowerCase() !== to || typeof b.subject !== 'string' || typeof b.html !== 'string' || b.html.length > 60000) {
  throw new Error('Pedido de confirmación inválido');
}
// Para el nodo Gmail: destinatario, asunto y HTML (el nombre del remitente sale de «Configuración»).
return [{ json: { to, bcc: '', subject: b.subject.replace(/[\r\n]+/g, ' ').slice(0, 200), html: b.html, senderName: cfg.sender_name || 'Observatorio ENSO Perú' } }];
