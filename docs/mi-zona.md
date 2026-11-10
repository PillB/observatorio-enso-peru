# Mi zona

Una página (`#/zona?area=<UBIGEO>`) que junta, para un departamento (2 dígitos), una provincia (4) o un distrito (6),
lo que la plataforma ya sabe de ese lugar. No calcula nada propio.

| Bloque | De dónde sale |
|---|---|
| Registros, años con daños, «uno cada X años», probabilidad en 5 años, razón con El Niño costero, último registro | `historico-model.js` (`summarize`), el mismo cálculo que los CSV `indicadores-*.csv`, sobre los registros del lugar y las temporadas homogéneas de DesInventar |
| Evento ENSO en curso e ICEN | `resumen.json` (`eventoEnCurso`, `icenUltimo`) |
| Avisos oficiales que tocan el lugar | `feed.json`, grupo `alertas`, con la vigencia de `phaseOf` del mapa de alertas (vigentes y próximos; los vencidos y cancelados no se muestran): un aviso toca el lugar si uno de sus códigos es el lugar, lo contiene o está dentro de él (un aviso de departamento toca todos sus distritos); con el nivel que dio la institución |
| Riesgo esperado por lluvias (todo el país) | `assets/capas/escenario-distritos.json`: el escenario de riesgo por lluvias del CENEPRED para cada distrito, por movimientos en masa (huaycos y deslizamientos) y por inundaciones, con el periodo de vigencia y el mes en que se elaboró en el título y en la fuente. Un distrito muestra **los dos peligros lado a lado, nunca en pestañas**, con el nivel más alto arriba y el peligro que lo tiene nombrado (`districtScenario`); un departamento o una provincia, cuántos distritos hay en cada nivel por cada peligro (`scenarioSummary`). Las cifras son las del CENEPRED para las áreas de mayor susceptibilidad del distrito, y la página lo dice junto a ellas (por eso un nivel alto puede venir con cero viviendas). No se combina ni se corrige nada: no hay un nivel propio |
| Detalle por manzana ante El Niño 2026-2027 (zonas de Piura, Tumbes y Lambayeque) | `assets/capas/manzanas-riesgo.json`, la capa de manzanas del CENEPRED que ya usa la vista «Daños y pobreza» de la Memoria: manzanas, personas y viviendas (censo 2017) por nivel y los centros poblados con más personas en riesgo alto o muy alto (`expectedRisk`). Solo aparece donde hay manzanas evaluadas |
| Meses críticos | Registros del lugar con mes conocido, por peligro y mes; cada fila se colorea respecto de su propio máximo |
| Descarga | CSV con los registros del lugar en el esquema del tablero del equipo de prevención: las 13 columnas del equipo y 30 de la Memoria, con los mismos valores que `eventos.zip`. Es el mismo archivo que da la tabla de la Memoria con ese lugar elegido (`downloadTeamCsv` en `historico.js`, `historico-tabla.js`; ver [memoria-desastres](memoria-desastres.md#tabla-de-registros-y-descargas)) |

## Elegir el lugar

- **Buscador**: el nombre, con una etiqueta única por lugar.
- **Por pasos**: tres listas (departamento, provincia, distrito) que siguen al lugar elegido venga de donde venga
  (`childrenOf`); «Todo el departamento» y «Toda la provincia» vuelven un nivel.
- **Usar mi ubicación**: pide la posición al navegador y ofrece los tres distritos cuyo punto central queda más cerca
  (`nearestDistricts`, con los puntos de `peru-map.json`), para que la persona elija el suyo. Se compara con el punto
  central y no con el límite del distrito (el sitio no publica los polígonos distritales), por eso nunca elige sola.
  La posición no se envía a ningún servidor ni se guarda. A más de 150 km del distrito más cercano dice que la
  posición no parece estar en el Perú. El botón solo aparece si el navegador ofrece la ubicación.

## Preguntas frecuentes

Al pie, siete preguntas (`FAQ` en `zona.js`) que la página debe responder sin que nadie la explique: que no es una
alerta, de cuándo es cada dato, por qué hay dos niveles de riesgo, qué cuenta como persona o vivienda en
el riesgo esperado, que un nivel bajo no quiere decir seguro, qué pasa con la ubicación y a quién seguir en una emergencia. La
página no da recomendaciones propias: enlaza al INDECI y al CENEPRED.

Los datos se piden con los mismos archivos que Memoria de desastres (`eventos.json`, `resumen.json`), así que la
primera visita a una de las dos pestañas abre la otra sin descargar de nuevo.

## Límites

- Es historia, no pronóstico: dice con qué frecuencia pasó, no cuándo volverá a pasar. La página lo dice al pie.
- La frecuencia usa solo DesInventar (1970-71 a 2014-15), como en la memoria; un lugar con pocos años con registros muestra
  un aviso porque sus intervalos son muy anchos.
- Los avisos de nivel departamento aparecen en todos sus distritos; la página dice que incluye los de la provincia y el
  departamento.
- Los registros sin mes no entran en el cuadro de meses.
- El riesgo esperado es una copia con fecha del escenario del CENEPRED (el periodo y el mes de elaboración van en la
  página). Se regenera a mano con `python -m tools.build_escenario_distritos --tablas CARPETA` cuando el CENEPRED
  publica uno nuevo: tres pedidos a la página pública de escenarios del SIGRID, sin inicio de sesión, con al menos 5 s
  entre uno y otro. Los servicios de mapas del SIGRID (`/arcgis/`) piden hoy un token y no se usan. Si el CENEPRED
  cambia las columnas o los niveles, el script se detiene en vez de adivinar.
- Un distrito que no esté en la tabla del CENEPRED lo dice, y dice que eso no quiere decir que no haya riesgo. Si el
  archivo no carga, el bloque lo avisa y el resto de la página sigue.
- El detalle por manzana cubre solo las zonas que el CENEPRED evaluó así en Piura, Tumbes y Lambayeque
  (`python -m tools.build_capas_mapa --manzanas`; ver [memoria-desastres](memoria-desastres.md)).
- La página no da recomendaciones propias: enlaza al INDECI y al CENEPRED.

Código: `public/assets/js/zona.js`; `python/tools/build_escenario_distritos.py`; pruebas: `python/tests/js/zona.test.mjs`, `python/tests/test_zona.py`, `python/tests/test_escenario_distritos.py` y los recorridos `test_zona_*` de `python/tests/test_browser.py`.
