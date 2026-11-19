// Un ítem por correo (la lista fija de «to»/«bcc» y cada suscripción) para el nodo Gmail: destinatario, copia oculta,
// asunto y HTML (con el pie de baja y preferencias de cada suscriptor).
const cfg = $('Configuración').first().json;
const d = $('Decidir envío').first().json;
return (d.messages || []).map((m) => ({ json: { to: m.to, bcc: m.bcc || '', kind: m.kind, subject: m.subject, html: m.html, senderName: cfg.sender_name || 'Observatorio ENSO Perú' } }));
