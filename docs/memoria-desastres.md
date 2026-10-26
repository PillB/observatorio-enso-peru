# Memoria de desastres

La pestaña **Memoria de desastres** (`#/memoria`) reúne en un solo catálogo los desastres de origen climático del Perú
desde 1970: inundaciones, desbordes, huaycos, deslizamientos, lluvias intensas, oleajes, sequías, heladas, incendios
forestales y otros. Cada registro está ubicado en su distrito (UBIGEO del INEI), fechado, clasificado y enlazado a su
fuente. Sirve para prepararse: si un Niño como los anteriores vuelve, lo más probable es que vuelva a golpear donde
ya golpeó.

> No es un sistema de alerta. Los avisos oficiales son los del ENFEN, el SENAMHI y el INDECI.

## Contenido

1. [Qué pregunta responde](#qué-pregunta-responde)
2. [Fuentes](#fuentes)
3. [Columnas del catálogo](#columnas-del-catálogo)
4. [Clasificación del peligro y del evento](#clasificación-del-peligro-y-del-evento)
5. [Indicadores](#indicadores)
6. [Peligro identificado hoy (contexto)](#peligro-identificado-hoy-contexto)
7. [La pestaña](#la-pestaña)
8. [Evidencia sobre la prevención desde los años 90](#evidencia-sobre-la-prevención-desde-los-años-90)
9. [Límites](#límites)
10. [Reproducir y actualizar](#reproducir-y-actualizar)
11. [Registros curados y revisiones](#registros-curados-y-revisiones)

## Qué pregunta responde

El especialista en geología y prevención del equipo sostiene que el Perú hizo poca prevención entre los años 90 y hoy,
y que, si las señales de El Niño son más fuertes que en Niños anteriores, los mismos efectos deberían repetirse, o
agravarse, en las mismas regiones, ciudades, cuencas, valles, costas y comunidades. Para usar esa idea hace falta
saber **dónde golpeó cada Niño** y **con qué frecuencia se repiten los daños en cada lugar**. Eso es lo que da el
catálogo, con una respuesta para cada distrito, provincia y departamento:

- ¿En cuántos años de 1970 a 2015 hubo daños aquí? ¿Cada cuántos años, en promedio?
- ¿Cuánto más daño hay en los años de Niño costero que en los demás?
- ¿Cuáles de los grandes Niños (1982-83, 1997-98, 2017, Yaku 2023, 2023-24) dejaron registros aquí?
- ¿Qué peligros fueron, en qué meses, con qué impactos y según qué fuente?
- ¿Qué identifican hoy las instituciones como peligro aquí (puntos críticos de ríos y quebradas, zonas críticas)?
- ¿Ya hay registros del Niño costero en curso (2026)?

## Fuentes

Todas se descargan con `python -m tools.build_historico` y quedan descritas en
[`data/historico/fuentes.json`](../data/historico/fuentes.json) con su URL, su página, su licencia, la fecha en que se
obtuvieron, el número de registros que aportan, los que se descartaron y por qué, y el SHA-256 del archivo descargado.

### Eventos

| Fuente | Años | Escala | Qué aporta | Licencia |
|---|---|---|---|---|
| [DesInventar Perú](https://www.desinventar.net/DesInventar/profiletab.jsp?countrycode=per) (Corporación OSSO, LA RED, UNDRR) | 1970-2015 | Distrito | La serie homogénea: fichas de prensa (El Comercio, La República, Expreso) y del INDECI, con impactos. 14 114 fichas de peligros de origen climático | Uso libre con atribución |
| SINPAD (INDECI), [copia pública en ArcGIS Online](https://services8.arcgis.com/2qDHoDLqu6VOlf1y/arcgis/rest/services/Emergencias/FeatureServer/0) | 2016-2018 | Distrito y punto | 14 124 emergencias, entre ellas más de 4 000 del Niño Costero 2017. Sin cifras de daños | Información pública del INDECI; la copia no es oficial |
| [IDMC, actualizaciones de desplazamiento (IDU)](https://www.internal-displacement.org/database/displacement-data/), con datos del INDECI, por la API del IDMC | 2025-2026 | Distrito y punto | 4 895 emergencias que dejaron viviendas destruidas o inhabitables, con las personas desplazadas | CC BY-NC-SA 3.0 IGO |
| [IDMC, desplazamientos por desastres (GIDD)](https://www.internal-displacement.org/database/displacement-data/), por la API del IDMC | 2019-2024 | Casi siempre departamento y mes | 1 015 eventos; cubre el ciclón Yaku y el Niño costero 2023-24 por departamento | CC BY-NC-SA 3.0 IGO |
| [NASA, Global Landslide Catalog](https://gpm.nasa.gov/landslides/data.html) (copia en ArcGIS Online) | 2016-2020 | Punto | 22 deslizamientos y huaycos con la noticia que los reportó | Dominio público, con cita |
| Registros curados ([`data/historico/curado/`](../data/historico/curado/)) | 2017 | Distrito | Los diez distritos con más viviendas inhabitables o colapsadas en 2017 según el Plan Integral de Reconstrucción con Cambios | Cada registro cita su fuente |

### Contexto (no son eventos)

| Fuente | Qué aporta |
|---|---|
| [INGEMMET, inventario de peligros geológicos](https://geocatmin.ingemmet.gob.pe/arcgis/rest/services/SERV_PELIGROS_GEOLOGICOS/MapServer/0) | 27 300 puntos publicables (caídas, deslizamientos, flujos o huaycos, movimientos complejos, reptación) por distrito |
| [INGEMMET, zonas críticas](https://geocatmin.ingemmet.gob.pe/arcgis/rest/services/SERV_PELIGROS_GEOLOGICOS/MapServer/2) | 2 178 zonas críticas con el elemento expuesto y el boletín técnico |
| [ANA, puntos críticos](https://sigrid.cenepred.gob.pe/arcgis/rest/services/sectores/COEN_FEN_2027/MapServer/25) (servicio del SIGRID, CENEPRED) | 536 puntos críticos de ríos y quebradas de la costa con nivel de peligro, población y viviendas expuestas, acción recomendada y costo |
| [Establecimientos de salud afectados en 2022-23](https://sigrid.cenepred.gob.pe/arcgis/rest/services/sectores/COEN_FEN_2027/MapServer/9) (COE Salud, SIGRID) | 1 230 establecimientos afectados por las lluvias de 2022-2023 |
| [ubigeo-peru-aumentado](https://github.com/jmcastagnetto/ubigeo-peru-aumentado) (INEI y PNUD) | Población 2020, superficie, altitud, IDH 2019 y pobreza por distrito |

### Fuentes que no se pudieron usar

- **El SINPAD completo de 2019 en adelante.** El portal del INDECI lo sirve desde una API pública con más de 135 000
  emergencias, pero descargarla en bloque no es un uso previsto del portal. La vía correcta es pedir la serie al
  INDECI (o que se publique en la Plataforma Nacional de Datos Abiertos), y agregarla como una fuente más en
  `fuentes.json`. Mientras tanto, 2019-2024 queda casi solo por departamento.
- **datosabiertos.gob.pe** responde con un muro antibots (HTTP 418); no se intentó saltarlo.
- **Decretos de emergencia de 2017 y 2023**: no hay una tabla de los distritos declarados; están en anexos en PDF.
- **EM-DAT** pide registro; **DFO** y **GDACS** son demasiado gruesos para el nivel distrital.

## Columnas del catálogo

`public/assets/historico/eventos.csv` (UTF-8 con BOM, para que Excel lea las tildes). Las 13 primeras son las del
tablero del equipo de prevención, con sus nombres exactos:

| Columna | Contenido |
|---|---|
| `Date` | Fecha de inicio (AAAA-MM-DD). Si la fuente solo da el mes, el día 01; si solo el año, 01-01 (ver `PrecisionFecha`) |
| `DangerType` | Inundacion fluvial, Inundacion pluvial, Inundacion (sin detalle), Desborde de rio, Huayco/Alud, Deslizamiento, Lluvias intensas, Oleaje anomalo, Erosion costera, Nevada, Granizada, Helada/Friaje, Ola de calor, Vientos fuertes, Tormenta electrica, Tormenta, Sequias, Incendio forestal, Erosion, Epidemia, Plaga |
| `Ubicacion` | El lugar más fino que da la fuente (sector, caserío, localidad) |
| `Distrito`, `Provincia`, `Departamento` | Nombres oficiales del INEI, con tildes |
| `Descripción` | Qué pasó, con la causa y los daños que describe la fuente |
| `DuraciónEvento` | Días, si la fuente los da |
| `Ubigeo` | Código vigente del INEI: 6 dígitos (distrito), 4 (provincia) o 2 (departamento) |
| `TipoEvento` | FEN 1982-83, FEN 1997-98, Niño Costero 2017, Ciclón Yaku 2023, FEN 2023-24, FEN 2026, La Niña costera…, Temporada de lluvias, Temporada de heladas y friaje, Sin asociación ENSO |
| `Fuente` | URL del registro o de la fuente |
| `Latitud`, `Longitud` | Punto de la fuente si cae en el distrito asignado; si no, la capital del distrito |

Y 43 columnas más para análisis y trazabilidad: `Id` estable (`<origen>-<id en la fuente>`), `Origen`, `IdFuente`,
`FechaFin`, `PrecisionFecha`, `Anio`, `Mes`, `AnioHidrologico` (julio a junio), `GrupoPeligro`, `PeligroFuente` (el
tipo como lo nombra la fuente), `DangerTypeMetodo` (fuente, texto, causa o por-omision), `CausaFuente`,
`NivelUbigeo`, `PrecisionGeo`, `Region` (macrorregión), `AltitudCapital`, `FaseENSO`, `EventoENSO`, `ICEN`, `ONI`,
`AtribucionENSO`, catorce columnas de impactos (fallecidos, desaparecidos, heridos, afectados, damnificados,
evacuados, reubicados, desplazados, viviendas destruidas y afectadas, hectáreas de cultivo, km de vías, centros
educativos y de salud, pérdidas en US$), `ImpactoReportado`, `ImpactoEnTotales`, `FuenteCita` (la cita original
legible), `Licencia` y `Confianza` (alta, media o baja según la precisión de fecha, lugar y tipo).

Un impacto vacío significa «la fuente no lo reporta», no cero.

Otros archivos:

- `data/historico/indicadores-{departamento,provincia,distrito,region}.csv`: los indicadores de cada área.
- `data/historico/contexto-distrito.csv`: por distrito, el historial (registros, años con daños, grandes Niños,
  nivel de atención, registros del Niño en curso) junto al peligro identificado hoy (puntos del INGEMMET, zonas
  críticas, puntos críticos de la ANA con la población, las viviendas y el costo de las acciones, establecimientos de
  salud afectados en 2023). Es la tabla para priorizar.
- `public/assets/historico/eventos.json`, `resumen.json`, `contexto.json`, `mapa.json` y `detalle/<dep>.json`:
  versiones para el navegador. Los CSV de `data/historico/` se copian en `public/assets/historico/` para descargarlos desde la
  pestaña: el sitio publicado no enlaza al repositorio.

## Clasificación del peligro y del evento

**DangerType** usa el tipo de la fuente. Donde la fuente dice solo «inundación», el texto decide
(`esquema.classify_flood`): «desborde del río…» o la rotura de defensas es *Desborde de rio*; un río, una quebrada o
una crecida, *Inundacion fluvial*; lluvia, aniego o drenaje, *Inundacion pluvial*; sin pistas queda *Inundacion*. El
método queda en `DangerTypeMetodo`. No entran los peligros que no dependen del clima: sismos, volcanes, incendios
urbanos, derrames, contaminación. Tampoco los deslizamientos o aludes que desató un sismo (Áncash, 31 de mayo de
1970) ni las epidemias y plagas sin una causa climática en la fuente.

**TipoEvento** sigue este orden:

1. Eventos con nombre, solo para lluvias, inundaciones, huaycos, deslizamientos, oleaje y viento:
   *Ciclón Yaku 2023* (marzo de 2023, costa norte y Lima) y *Niño Costero 2017* (enero a mayo de 2017, en los 13
   departamentos del Plan Integral de Reconstrucción con Cambios: Tumbes, Piura, Lambayeque, La Libertad, Áncash,
   Lima e Ica por inundaciones; Cajamarca, Ayacucho, Arequipa, Huancavelica, Junín y Loreto por movimientos en masa).
2. Si el mes cae en un Niño costero del ICEN (definición operacional del ENFEN, Nota Técnica 01-2024) y el peligro
   es de origen climático: el nombre de ese Niño (*FEN 1997-98*, *FEN costero 2017* fuera de la zona del Plan…).
3. Si la fuente atribuye el evento a El Niño o La Niña.
4. Si el mes cae en una Niña costera del ICEN.
5. *Temporada de lluvias* (noviembre a abril), *Temporada de heladas y friaje* (mayo a setiembre) o *Sin asociación
   ENSO*.

La atribución es temporal: que un registro caiga dentro de un Niño no prueba que el Niño lo causó.
`AtribucionENSO` dice de dónde sale (curado, ventana-icen, fuente o ninguna).

## Indicadores

Se calculan igual en Python (`enso/historico/indicadores.py`, para los CSV) y en el navegador
(`public/assets/js/historico-model.js`, para los filtros de cada persona); una prueba compara ambos.

Con T = años hidrológicos (julio a junio) de 1970-71 a 2014-15 (45) y Y = años con al menos un registro de
DesInventar en el área:

| Indicador | Definición | Para qué sirve |
|---|---|---|
| Años con daños | Y de T, con intervalo de Wilson al 95 % | Cuenta años, no fichas: un Niño deja decenas de fichas en un distrito |
| 1 de cada X años | T / Y | Frecuencia histórica. No es un pronóstico: supone clima y exposición constantes |
| Probabilidad en 5 años | 1 − (1 − Y/T)^5 | Lo mismo, dicho como probabilidad |
| Distrito-años | Pares (distrito, año) con daños | En provincias y departamentos, cuántos de sus distritos sufren cada año |
| Cuánto más daño con Niño | (distrito-años con Niño / años con Niño) ÷ (distrito-años en otros años / otros años), con intervalo de Poisson al 95 % | Dónde El Niño costero multiplica los daños, y dónde no (en la sierra sur suele traer sequía) |
| Grandes Niños | Cuáles de FEN 1982-83, FEN 1997-98, Niño Costero 2017, Ciclón Yaku 2023 y FEN 2023-24 dejaron registros | La pregunta del especialista: ¿se repite? |
| Nivel de atención | Muy alto: registros en ≥ 2 grandes Niños y daños en ≥ 1 de cada 4 años; alto: una de las dos; medio: 1 gran Niño o daños en ≥ 1 de cada 10 años; bajo: el resto con registros | Una regla transparente para ordenar, no un índice oficial de riesgo |
| Registros intensivos | Fichas con ≥ 30 fallecidos o ≥ 600 viviendas destruidas (umbral del GAR 2015 de UNDRR) | Separa los desastres grandes de los daños frecuentes y pequeños |

**Solo DesInventar entra a la frecuencia.** SINPAD 2016-2018 tiene más de diez veces los registros por año de
DesInventar; IDMC 2025-2026 solo incluye emergencias con viviendas inhabitables. Mezclarlas cambiaría la frecuencia
por un cambio de fuente, no del clima. Las fuentes posteriores sí cuentan para los registros, los impactos, los
grandes Niños y el mapa.

Resultados principales (catálogo de octubre de 2026):

- **El Niño multiplica los daños en el norte.** Distritos con daños por año en temporadas de Niño costero frente a las
  demás: Piura 2,4 veces (IC 95 %: 2,0–2,8), Tumbes 1,8 (1,3–2,3), Lambayeque 1,7 (1,3–2,2), La Libertad 1,6
  (1,3–1,9), Áncash 1,6 (1,3–1,8). En Puno es 0,8 (0,7–1,0): menos daños con Niño.
- **Los mismos lugares se repiten.** 108 de 196 provincias tienen nivel de atención muy alto (registros en dos o más
  grandes Niños y daños en al menos uno de cada cuatro años). Piura, Tumbes, Lambayeque, La Libertad, Áncash y Cajamarca
  tienen registros en los cinco grandes Niños.
- **El peligro de hoy coincide con la historia.** 66 distritos con nivel de atención alto o muy alto tienen además
  puntos críticos de peligro muy alto según la ANA (por ejemplo Chimbote, Arequipa, Ica, Chicama, Olmos o Catacaos).

## Peligro identificado hoy (contexto)

La historia dice dónde golpeó; los inventarios oficiales dicen dónde el peligro está identificado hoy. La ficha de
cada área muestra los dos juntos: los puntos críticos de la ANA (con el sector, el peligro, la población y las
viviendas expuestas, la acción recomendada y su costo), las zonas críticas del INGEMMET (con el boletín técnico), el
número de puntos de peligro geológico inventariados y los establecimientos de salud afectados en 2023. No son eventos
con fecha y no entran a ningún indicador.

## La pestaña

- **Aviso del Niño en curso**, con el último ICEN.
- **Mapa** por departamento, provincia o distrito, con filtros de evento (grandes Niños, uno en particular, el Niño
  en curso, cualquier Niño, La Niña, años neutros), de peligro y de periodo, y la métrica a pintar: años con daños,
  grandes Niños, cuánto más daño con Niño, nivel de atención, registros, fallecidos, afectados o viviendas
  destruidas. Los cortes de «años con daños» cambian con el nivel (un departamento casi siempre tiene daños; un
  distrito, rara vez). Todo el estado queda en la dirección (`#/memoria?nivel=distrito&area=200105`) para compartir
  una vista.
- **Ficha** de cada área: nivel de atención, años con daños, 1 de cada X años, probabilidad en 5 años, grandes Niños,
  registros del Niño en curso, «si se repite un gran Niño», peligro identificado hoy, impactos, peligros, temporadas
  con daños y la lista de registros con su descripción y su fuente.
- **Línea de tiempo** de lugares con daños por temporada, con las temporadas de Niño costero marcadas.
- **Los grandes Niños uno al lado del otro** (dónde dejó registros cada uno) y la **tabla de lugares golpeados en dos
  o más**.
- **Ranking** (la versión en tabla del mapa).
- **Evidencia** sobre la prevención desde los años 90 (abajo) y **fuentes, método, límites y descargas**.

El diseño sigue las prácticas de los tableros de riesgo de referencia (DesInventar, el Índice de Riesgo INFORM, el
SIGRID del CENEPRED): mapa coroplético con tabla equivalente, colores de una sola tonalidad para magnitudes y
divergentes centrados en 1 para la razón de tasas, estados con icono y texto (no solo color), cifras siempre con su
fuente y su incertidumbre, y avisos claros de lo que el dato no dice.

## Evidencia sobre la prevención desde los años 90

La sección «¿Se ha hecho poca prevención desde los años 90?» de la pestaña reúne las afirmaciones a favor y en contra,
cada una con su fuente (`public/assets/js/historico-evidencia.js`). El veredicto es **en parte cierto**:

- **Sí se hizo**: el SINAGERD (2011), el CENEPRED y un programa presupuestal de prevención; alertas y pronósticos
  mejores. Los fallecidos por evento bajaron: 512 (1982-83), unos 374 (1997-98), 162 (2017), 84 (2023).
- **Sigue pendiente**: en 2017 el Plan Integral de Reconstrucción prometió soluciones definitivas en 17 ríos, el
  drenaje de cuatro ciudades y cuatro quebradas; en 2023 el Contralor dijo que la reconstrucción «ha fracasado» y a
  mayo de 2026 solo 9 de 102 soluciones integrales estaban terminadas. El río Piura conduce hoy cerca de la mitad del
  caudal pico de 1998.
- **Conclusión para la preparación**: si se repite un Niño fuerte, lo esperable es que vuelvan los daños a viviendas
  e infraestructura en los mismos lugares del norte; repetir la mortalidad de 1983 es menos probable.

## Límites

- **Sesgo de las fuentes.** DesInventar se arma con prensa nacional e informes del INDECI: hay más registros de
  ciudades y lugares accesibles, y menos antes de los años 90. Una zona sin registros no es una zona sin peligro.
- **Cambio de fuentes en el tiempo.** Las barras de la línea de tiempo y los mapas de cada gran Niño no se comparan
  en cantidad: 2017 viene del SINPAD (más denso), 2019-2024 casi solo por departamento, 2025-2026 solo de emergencias
  con viviendas inhabitables. Por eso los mapas de los grandes Niños muestran presencia y no cantidad.
- **Los impactos** son los que publicó cada fuente; las fuentes discrepan (Huggel et al., 2015). Un registro curado
  que resume un área ya detallada por otra fuente con cifras no suma sus impactos dos veces (`ImpactoEnTotales`).
- **Ubicación.** Los registros se ubican por el UBIGEO o el nombre de la fuente; si el nombre está abreviado
  («S. J. DE LURIGANCHO»), por el punto de la fuente dentro de los límites del IGN. Los distritos creados después de
  esos límites no tienen polígono: cuentan para su provincia y su departamento.
- **La copia del SINPAD 2015-2018 no es oficial** (la subió una cuenta de terceros a ArcGIS Online). Si el INDECI
  publica la serie, debe reemplazarla.
- **Frecuencia no es pronóstico.** Suponer que el pasado se repite ignora el cambio climático y el crecimiento de la
  exposición (más gente en riberas y quebradas), que empujan el riesgo hacia arriba.

## Reproducir y actualizar

```bash
cd python
pip install -r requirements-dev.txt
python -m tools.build_historico                    # descarga lo que falte en ~/.cache/enso-historico y reconstruye
python -m tools.build_historico --sin-red          # solo con la caché
python -m tools.build_historico --aceptar-cambios  # tras revisar que una fuente cambió
python -m tools.build_historico_mapa               # polígonos de provincias y distritos (solo si cambian los límites)
node --test tests/js/historico.test.mjs            # paridad Python/navegador
pytest -q tests/test_historico.py
```

- Como el resto del observatorio, el script lee el robots.txt de cada servidor antes de pedir nada (RFC 9309, con
  `enso.reach.Robots`) y respeta su `Crawl-delay`; si el robots.txt no responde, no pide nada a ese servidor.
- El IDMC se pide a su propia API (su robots.txt la permite; el de HDX no deja que un programa baje sus CSV). La API
  pide una clave gratuita (`client_id`) que se solicita una vez por correo a ch.datainfo@idmc.ch, con el uso que se le
  dará, y se guarda en la variable de entorno `IDMC_CLIENT_ID`, nunca en el repositorio. El script guarda las filas
  del Perú como CSV con columnas y filas ordenadas. La copia vigente es la exportación del IDMC en HDX del
  26-10-2026, con las mismas columnas. Los datos del IDMC son CC BY-NC-SA 3.0 IGO: uso no comercial, con atribución
  y la misma licencia en lo derivado.
- Las capas de puntos críticos de la ANA y de establecimientos de salud están en el SIGRID, cuyo robots.txt no deja
  que un programa consulte `/arcgis/` (tampoco el recolector del Perú, que también lo respeta). En `fuentes.json`
  tienen `"descarga": "manual"` y el campo `manual` dice qué abrir en el navegador y con qué nombre guardarlo en la
  caché; sin ese archivo el script se detiene y lo explica.
- Cada fuente tiene su SHA-256 en `fuentes.json`. Si cambia, el script se detiene: hay que revisar el cambio y
  repetir con `--aceptar-cambios`, que actualiza el manifiesto. Así un cambio silencioso de una fuente no altera el
  catálogo publicado.
- Las capas de ArcGIS se descargan por bloques de 1 000 elementos (por rango de OBJECTID) y se guardan como JSON
  canónico (claves ordenadas), para que el SHA-256 solo cambie si cambian los datos.
- El servidor del INGEMMET no envía su certificado intermedio; `enso/data/ca-intermedios.pem` lo agrega (Sectigo
  Public Server Authentication CA OV R36) y la verificación TLS sigue completa.
- Para agregar una fuente: un lector en `enso/historico/fuentes.py` que devuelva filas con `registro.make`, una
  entrada en `READERS` o `CONTEXT` de `tools/build_historico.py` y otra en `fuentes.json`.

## Registros curados y revisiones

**Registros curados** (`data/historico/curado/*.yaml`): para eventos o cifras que no están en las bases, sacados de
informes oficiales, artículos científicos o prensa. Cada registro necesita `Id`, `Date` (AAAA-MM-DD, AAAA-MM o AAAA),
`DangerType` (del vocabulario), el lugar (`Ubigeo` o `Departamento`/`Provincia`/`Distrito`), `Fuente` (https) y
`FuenteCita`; puede llevar `Descripción`, `Ubicacion`, `DuraciónEvento`, `TipoEvento`, `Latitud`/`Longitud`, las
columnas de impacto y `Confianza`. Lo que va en `comun` se aplica a todos los registros del archivo. Un lugar que no
se resuelve o un tipo fuera del vocabulario detienen la construcción.

**Revisiones** (`data/historico/revisiones.yaml`): exclusiones y cifras dudosas, cada una con su motivo y su fuente.
`excluir` quita registros (por `id`, o por `fecha` y `departamento`); `sin-impactos` los deja pero no suma sus cifras y
baja su confianza. Una revisión que no coincide con ningún registro detiene la construcción, para que no queden reglas
muertas.
