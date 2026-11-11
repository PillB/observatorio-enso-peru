// Medición anónima del uso del sitio por versión: todo /api/uso/* (ver ../../_lib/uso.js).
import { handle } from '../../_lib/uso.js';

export const onRequest = (context) => handle(context.request, context.env);
