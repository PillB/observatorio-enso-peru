# Mi zona

Una página (`#/zona?area=<UBIGEO>`) que junta, para un departamento (2 dígitos), una provincia (4) o un distrito (6),
lo que la plataforma ya sabe de ese lugar. No calcula nada propio.

| Bloque | De dónde sale |
|---|---|
| Registros, años con daños, «uno cada X años», probabilidad en 5 años, razón con El Niño costero, último registro | `historico-model.js` (`summarize`), el mismo cálculo que los CSV `indicadores-*.csv`, sobre los registros del lugar y las temporadas homogéneas de DesInventar |
| Evento ENSO en curso e ICEN | `resumen.json` (`eventoEnCurso`, `icenUltimo`) |
| Avisos oficiales que tocan el lugar | `feed.json`, grupo `alertas`, con la vigencia de `phaseOf` del mapa de alertas (vigentes y próximos; los vencidos y cancelados no se muestran): un aviso toca el lugar si uno de sus códigos es el lugar, lo contiene o está dentro de él (un aviso de departamento toca todos sus distritos); con el nivel que dio la institución |
| Riesgo esperado ante El Niño 2026-2027 | `assets/capas/manzanas-riesgo.json`, la capa de manzanas del CENEPRED (SIGRID) que ya usa la vista «Daños y pobreza» de la Memoria: manzanas, personas y viviendas (censo 2017) por nivel, el nivel más alto que aparece y los centros poblados con más personas en riesgo alto o muy alto (`expectedRisk`). La página solo cuenta: no calcula un nivel propio para el distrito. Donde no hay manzanas evaluadas dice que falta el dato y que eso no quiere decir que no haya riesgo |
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
alerta, de cuándo es cada dato, por qué un lugar no tiene riesgo esperado, qué cuenta como persona o vivienda en
riesgo, que un nivel bajo no quiere decir seguro, qué pasa con la ubicación y a quién seguir en una emergencia. La
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
- El riesgo esperado cubre solo las zonas que el CENEPRED evaluó por manzana en Piura, Tumbes y Lambayeque, y es una
  copia con fecha: el escenario ante El Niño 2026-2027, con personas y viviendas del censo 2017. Se regenera con
  `python -m tools.build_capas_mapa --manzanas` (ver [memoria-desastres](memoria-desastres.md)).

Código: `public/assets/js/zona.js`; pruebas: `python/tests/js/zona.test.mjs`, `python/tests/test_zona.py` y los recorridos `test_zona_*` de `python/tests/test_browser.py`.
