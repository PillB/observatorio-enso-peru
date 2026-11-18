// Un ítem por correo (la lista fija de «to»/«bcc» y cada suscripción), con su «raw» para la API de Gmail. El nodo
// siguiente los manda de a 10 por segundo, por debajo del límite de la API.
const d = $('Decidir envío').first().json;
return (d.messages || []).map((m) => ({ json: { to: m.to, kind: m.kind, subject: m.subject, raw: m.raw } }));
