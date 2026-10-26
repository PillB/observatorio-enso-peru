# Lugares de los PDF del COEN: prueba hacia atrás (agosto–octubre de 2026)

Quienes probaron el sitio vieron que muchas publicaciones «sin categoría» del mapa de alertas enlazan una
portada con un botón de descarga, y que el detalle de las zonas está en el PDF. `python/enso/documentos.py` lee
ese PDF; esta prueba mide qué tan bien lo hace contra publicaciones reales.

## Cómo se corrió

```sh
cd python
python -m tools.documentos_backtest --items <news/items.jsonl del sitio publicado> --since 2026-08-01 --out /tmp/bt \
  --feed 'https://portal.indeci.gob.pe/emergencias/feed/?s=boletin+informativo&paged=1'   # … hasta paged=8
  --feed 'https://portal.indeci.gob.pe/emergencias/feed/?s=reporte&paged=3'               # … 6, 9, … 30
```

272 publicaciones del COEN (202 reportes de emergencia y 70 boletines de aviso), cada una con su página y su
PDF bajados una vez (con pausa de cortesía y caché en disco). Dos páginas ya no existían (404); 8 son el
resumen diario de peligros, que no es un aviso y el sitio omite.

- **Reportes**: la verdad es el lugar del titular («Incendio forestal en el distrito de Zepita (Puno)»), que
  el COEN escribe a mano. TP: el PDF da ese distrito (y nada fuera de su departamento); parcial: el
  departamento sin el distrito; FN: ningún lugar; FP: un departamento que el titular no nombra.
- **Boletines de aviso**: la verdad es el PDF mismo. Se comparó cada departamento leído con los que el PDF
  nombra en cualquier parte, y a mano una muestra de las listas.

## Resultados

| Reportes (184 con verdad) | Primera corrida | Tras las correcciones | Ubicación por el texto del titular (antes) |
|---|---|---|---|
| TP | 164 | **183** | 150 |
| Parcial | 7 | 0 | 31 |
| FN | 10 | 0 | 0 |
| FP | 4 | 1 (revisado: correcto) | 3 |

El FP que queda es el sismo de magnitud 5,4 de Chongos Bajo (Junín): su tabla lista 34 distritos afectados de
Junín, Huancavelica y Lima (Tomás). La lectura es correcta; el titular nombra solo el epicentro.

Los 3 FP del texto del titular (lo que se usaba antes) suman lugares que el reporte no tiene: «La Cruz
(Tumbes)» con provincias de La Libertad y Piura, «Nuevo Occoro (Huancavelica)» con una de Madre de Dios. Por eso
ahora también se lee el PDF de los reportes que ya tienen distrito en el titular.

| Boletines de aviso (69 con PDF) | Primera corrida | Tras las correcciones |
|---|---|---|
| Con lugares | 56 | **69** |
| Departamentos que el PDF lista y no se tomaron | 8 en el aviso 427, 1 (Callao) en 431, 436, 411, 418 y 423 | 0 |
| PDF de otra publicación, descartado | — | 1 |

La aproximación por regiones (para un aviso del SENAMHI sin PDF: «sierra sur» → sus departamentos) acierta el
96 % de los departamentos del PDF y el 80 % de los que propone están en él. Por eso se marca «≈» (confianza 0,6).

## Qué fallaba y cómo se corrigió

| Caso | Causa | Corrección |
|---|---|---|
| Locumba, San Luis, San Nicolás, San Pedro de Cachora, Huancabamba (Pasco) y 7 más (San Roque de Cumbaza, Cusipata, Tambopata, Cacatachi, Alberto Leveau, San Pedro de Pillao, San Antonio) | pypdf pega o parte las celdas: «LOCUMBAJORGE BASADRETACNA», «PAMPASAN LUISCARLOS», «PASCO OX APAMPA» | Los nombres de 4 letras o más se buscan también en el texto sin espacios |
| Tomás con Omas, Chongos Bajo con Hongos, Alto Pichigua con Pichigua, Yavari con Ramón Castilla | Un nombre dentro de otro («TOMAS», «CHONGOS», «MARISCAL RAMÓN CASTILLA») | No cuenta una aparición que es parte de otro nombre del gazetteer presente en el texto |
| Seclla, Kimbiri, Mariscal Gamarra, San Juan de Iscos | El COEN escribe distinto que el INEI (Secclla, Quimbiri, Gamarra, San Juan de Yscos) | Alias en `geo.ALIASES` |
| Andamarca (Junín) con Huánuco | Un centro poblado se llama Huánuco | Un departamento sin provincia ni distrito, cuando otro sí los tiene, no cuenta |
| Ventanilla | La tabla dice «LIMA CALLAO VENTANILLA» | Si la provincia no se lee, se buscan los distritos de todo el departamento |
| Challhuahuacho, Santa Lucía y San Miguel (Puno) | La tabla de ubicación es una imagen | La descripción: «…distrito Challhuahuacho, provincia de Cotabambas.» |
| Ccapi (Cusco) | La página enlaza el reporte de Huancabamba (Piura) | Si el departamento del PDF no es el del titular, el PDF se descarta (`no-coincide`) |
| Boletín de corto plazo N° 193 | La página enlaza el reporte de Mariscal Gamarra | Una publicación de aviso cuyo PDF es un reporte se descarta |
| 13 avisos hidrológicos | No había lector: el lugar está en «…departamento de LORETO (Prov. …)» y en la fila de la estación | El distrito de la estación (Yavari, Nauta, Lagunas, Manseriche…) |
| Avisos 427, 431, 436, 411, 418, 423 | «PROV. CONST. DEL CALLAO» o «PROVINCIACONSTITUCIONALDEL»: el punto de «PROV.» cortaba la lista | Se normaliza antes; un trozo corto desconocido ya no corta la lista |

Los casos reales quedan como pruebas en `python/tests/test_documentos.py`
(`fixtures/documentos/regresiones.json` y los textos de los avisos hidrológicos).

## Límites conocidos

- La verdad de los reportes es el titular del COEN: cuando la tabla lista más distritos (lluvias en Piura,
  el sismo de Chongos Bajo) se revisó a mano.
- Los avisos de oleaje se ubican por los tramos del litoral (norte, centro, sur), no por departamentos del PDF,
  que no los nombra.
- Una tabla de ubicación que es imagen y una descripción sin «distrito …, provincia …» quedan sin lugar del PDF
  (no hubo ninguna en esta muestra); la publicación conserva el del titular.
