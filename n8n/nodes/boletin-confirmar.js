// Correo de confirmación de la suscripción (o «ya está suscrito»), que pide el sitio (functions/_lib/boletin-subs.js)
// con el secreto compartido en X-Enso-Secret (lo comprueba el disparador). El sitio arma el correo; aquí solo se
// revisa que venga bien y se convierte al «raw» de la API de Gmail.
const cfg = $('Configuración').first().json;
const b = $input.first().json.body || {};
const [to] = parseRecipients(b.to);
if (!to || String(b.to).trim().toLowerCase() !== to || typeof b.subject !== 'string' || typeof b.html !== 'string' || b.html.length > 60000) {
  throw new Error('Pedido de confirmación inválido');
}
const from = /^[^@\s<>"]+@[^@\s<>"]+$/.test(String(cfg.from_address || '')) ? `${encHeader(cfg.sender_name || 'Observatorio ENSO Perú')} <${cfg.from_address}>` : null;
const raw = mime({ from, to, subject: b.subject.slice(0, 200), html: b.html, text: String(b.text || '').slice(0, 20000), headers: { 'Auto-Submitted': 'auto-generated' } }, to);
return [{ json: { to, raw } }];
