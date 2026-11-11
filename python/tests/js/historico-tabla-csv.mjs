// Arma con historico-tabla.js el CSV de todo el catálogo, en el orden de eventos.json, a partir de los mismos
// archivos que pide la página (eventos.json, resumen.json, coordenadas.json y detalle/). tests/test_historico_tabla.py
// lo compara con eventos.csv (dentro de eventos.zip). Uso: node historico-tabla-csv.mjs <public/assets/historico> <salida.csv>
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { decode } from '../../../public/assets/js/historico-model.js';
import { buildCsv } from '../../../public/assets/js/historico-tabla.js';

const [dir, out] = process.argv.slice(2);
const read = (p) => JSON.parse(readFileSync(join(dir, p), 'utf8'));
const recs = decode(read('eventos.json'));
const res = await buildCsv(recs, {
  C: read('coordenadas.json'), sum: read('resumen.json'),
  load: async (dep) => { try { return read(`detalle/${dep}.json`); } catch { return null; } },
});
if (res.missing.length) throw new Error(`sin ficha: ${res.missing}`);
writeFileSync(out, res.parts.join(''));
