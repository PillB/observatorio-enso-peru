// Correo de confirmación de la suscripción (o «ya está suscrito»), que pide el sitio (functions/_lib/boletin-subs.js)
// con el secreto compartido en X-Enso-Secret (lo comprueba el disparador). El sitio arma el correo; aquí solo se
// revisa que venga bien y se pasa al nodo Gmail.
const cfg = $('Configuración').first().json;
// El pedido viene del disparador, no de la entrada: la entrada de este nodo es la salida de «Configuración».
const raw = $('Pedido del sitio').first().json.body || {};
// El sitio manda asunto y HTML en base64 (subject_b64, html_b64), porque el cortafuegos delante de n8n rechaza
// pedidos con HTML en el cuerpo. Se aceptan también los campos en claro (subject, html).
const b = { to: raw.to, subject: raw.subject_b64 != null ? fromB64(raw.subject_b64) : raw.subject, html: raw.html_b64 != null ? fromB64(raw.html_b64) : raw.html };
const [to] = parseRecipients(b.to);
// El motivo (sin datos del pedido) queda en la ejecución de n8n, para saber qué arreglar.
const why = !to || String(b.to).trim().toLowerCase() !== to ? 'destinatario («to») ausente, inválido o con más de una dirección'
  : typeof b.subject !== 'string' ? `asunto ausente o no es base64 válido (claves: ${Object.keys(raw).join(', ')}; subject_b64: ${typeof raw.subject_b64})`
    : typeof b.html !== 'string' ? `HTML ausente o no es base64 válido (html_b64: ${typeof raw.html_b64}, ${String(raw.html_b64 || '').length} caracteres)`
      : b.html.length > 60000 ? 'HTML de más de 60 000 caracteres' : '';
if (why) throw new Error(`Pedido de confirmación inválido: ${why}`);
// Para el nodo Gmail: destinatario, asunto y HTML (el nombre del remitente sale de «Configuración»).
return [{ json: { to, bcc: '', subject: b.subject.replace(/[\r\n]+/g, ' ').slice(0, 200), html: b.html, senderName: cfg.sender_name || 'Observatorio ENSO Perú' } }];
