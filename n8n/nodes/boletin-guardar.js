// Después de que Gmail mandó el correo: anota la edición enviada (y el día del resumen) en los datos estáticos del
// flujo. n8n los guarda solo en las ejecuciones activadas por el disparador (no en «Execute workflow» a mano), así que
// una prueba a mano no impide el envío real de la hora siguiente.
const sent = $('Decidir envío').first().json;
const st = $getWorkflowStaticData('global');
const next = nextState(st, { edition: sent.edition, editionAt: sent.editionAt, digest: sent.digest, digestDay: sent.digestDay, at: Date.now() });
Object.assign(st, next);
return [{ json: { resultado: `Enviado: ${sent.kind}, edición N° ${sent.edition}`, destinatarios: sent.recipients, asunto: sent.subject, estado: next } }];
