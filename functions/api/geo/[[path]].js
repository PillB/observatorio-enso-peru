// Ruta de la consola de lugares: todo /api/geo/* (ver ../../_lib/geo-console.js).
import { handle } from '../../_lib/geo-console.js';

export const onRequest = (context) => handle(context.request, context.env);
