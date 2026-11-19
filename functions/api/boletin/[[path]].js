// Suscripción al Boletín de eventos El Niño: todo /api/boletin/* (ver ../../_lib/boletin-subs.js).
import { handle } from '../../_lib/boletin-subs.js';

export const onRequest = (context) => handle(context.request, context.env);
