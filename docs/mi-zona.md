# Mi zona

Una página (`#/zona?area=<UBIGEO>`) que junta, para un departamento (2 dígitos), una provincia (4) o un distrito (6),
lo que la plataforma ya sabe de ese lugar. No calcula nada propio.

| Bloque | De dónde sale |
|---|---|
| Registros, años con daños, «uno cada X años», probabilidad en 5 años, razón con El Niño costero, último registro | `historico-model.js` (`summarize`), el mismo cálculo que los CSV `indicadores-*.csv`, sobre los registros del lugar y las temporadas homogéneas de DesInventar |
| Evento ENSO en curso e ICEN | `resumen.json` (`eventoEnCurso`, `icenUltimo`) |
| Avisos oficiales que tocan el lugar | `feed.json`, grupo `alertas`, con la vigencia de `phaseOf` del mapa de alertas (vigentes y próximos; los vencidos y cancelados no se muestran): un aviso toca el lugar si uno de sus códigos es el lugar, lo contiene o está dentro de él (un aviso de departamento toca todos sus distritos); con el nivel que dio la institución |
| Meses críticos | Registros del lugar con mes conocido, por peligro y mes; cada fila se colorea respecto de su propio máximo |
| Descarga | CSV con los registros del lugar en el esquema del tablero del equipo de prevención: las 13 columnas del equipo y 30 de la Memoria, con los mismos valores que `eventos.zip`. Es el mismo archivo que da la tabla de la Memoria con ese lugar elegido (`downloadTeamCsv` en `historico.js`, `historico-tabla.js`; ver [memoria-desastres](memoria-desastres.md#tabla-de-registros-y-descargas)) |

Los datos se piden con los mismos archivos que Memoria de desastres (`eventos.json`, `resumen.json`), así que la
primera visita a una de las dos pestañas abre la otra sin descargar de nuevo.

## Límites

- Es historia, no pronóstico: dice con qué frecuencia pasó, no cuándo volverá a pasar. La página lo dice al pie.
- La frecuencia usa solo DesInventar (1970-71 a 2014-15), como en la memoria; un lugar con pocos años con registros muestra
  un aviso porque sus intervalos son muy anchos.
- Los avisos de nivel departamento aparecen en todos sus distritos; la página dice que incluye los de la provincia y el
  departamento.
- Los registros sin mes no entran en el cuadro de meses.

Código: `public/assets/js/zona.js`; pruebas: `python/tests/js/zona.test.mjs` y `python/tests/test_zona.py`.
