// Ruta de la consola de documentos: todo /api/docs/* (ver ../../_lib/doc-uploads.js).
import { handle } from '../../_lib/doc-uploads.js';

export const onRequest = (context) => handle(context.request, context.env);
