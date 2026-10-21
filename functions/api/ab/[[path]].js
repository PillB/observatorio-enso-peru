// Analítica anónima de las versiones del mapa de alertas: todo /api/ab/* (ver ../../_lib/ab.js).
import { handle } from '../../_lib/ab.js';

export const onRequest = (context) => handle(context.request, context.env);
