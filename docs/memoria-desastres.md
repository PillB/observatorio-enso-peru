# Memoria de desastres

La pestaña **Memoria de desastres** (`#/memoria`) reúne en un solo catálogo los desastres de origen climático del Perú
desde 1970, con registros de archivo desde 1559: inundaciones, desbordes, huaycos, deslizamientos, lluvias intensas, oleajes, sequías, heladas, incendios
forestales y otros. Cada registro está ubicado en su distrito (UBIGEO del INEI), fechado, clasificado y enlazado a su
fuente, y dice qué otras fuentes (reportes del COEN, prensa) cuentan lo mismo. Sirve para prepararse: si un Niño como
los anteriores vuelve, lo más probable es que vuelva a golpear donde ya golpeó. Y sirve para la pregunta de la
prevención: cuántas de esas emergencias ocurrieron donde el Estado ya tenía el peligro identificado.

> No es un sistema de alerta. Los avisos oficiales son los del ENFEN, el SENAMHI y el INDECI.

## Contenido

1. [Qué pregunta responde](#qué-pregunta-responde)
2. [Fuentes](#fuentes)
3. [Columnas del catálogo](#columnas-del-catálogo)
4. [Clasificación del peligro y del evento](#clasificación-del-peligro-y-del-evento)
5. [Fuentes que cuentan el mismo evento](#fuentes-que-cuentan-el-mismo-evento)
6. [Reglas de calidad](#reglas-de-calidad)
7. [Indicadores](#indicadores)
8. [Validación](#validación)
9. [Cómo usar los indicadores](#cómo-usar-los-indicadores)
10. [Peligro identificado hoy (contexto)](#peligro-identificado-hoy-contexto)
11. [¿Se sabía antes? Peligros documentados y emergencias](#se-sabía-antes-peligros-documentados-y-emergencias)
12. [La pestaña](#la-pestaña)
13. [Evidencia sobre la prevención desde los años 90](#evidencia-sobre-la-prevención-desde-los-años-90)
14. [Límites](#límites)
15. [Reproducir y actualizar](#reproducir-y-actualizar)
16. [Cosecha en GitHub Actions](#cosecha-en-github-actions)
17. [Registros curados y revisiones](#registros-curados-y-revisiones)

## Qué pregunta responde

El especialista en geología y prevención del equipo sostiene que el Perú hizo poca prevención entre los años 90 y hoy,
y que, si las señales de El Niño son más fuertes que en Niños anteriores, los mismos efectos deberían repetirse, o
agravarse, en las mismas regiones, ciudades, cuencas, valles, costas y comunidades. Para usar esa idea hace falta
saber **dónde golpeó cada Niño** y **con qué frecuencia se repiten los daños en cada lugar**. Eso es lo que da el
catálogo, con una respuesta para cada distrito, provincia y departamento:

- ¿En cuántos años de 1970 a 2015 hubo daños aquí? ¿Cada cuántos años, en promedio?
- ¿Cuántos más lugares con daños hay en las temporadas con Niño costero que en las demás?
- ¿Cuáles de los grandes Niños (1982-83, 1997-98, 2017, Yaku 2023, 2023-24) dejaron registros aquí?
- ¿Qué peligros fueron, en qué meses, con qué impactos y según qué fuente?
- ¿Qué identifican hoy las instituciones como peligro aquí (puntos críticos de ríos y quebradas, zonas críticas)?
- ¿Ya se conocía el peligro antes de cada emergencia (inventario o informe técnico del INGEMMET o del IGP,
  declaratoria por peligro inminente)? ¿Y aun así la emergencia ocurrió?
- ¿Qué pasaba en esos mismos lugares antes de 1970 (actas coloniales, aluviones de lagunas glaciares)?
- ¿Ya hay registros del Niño costero en curso (2026)?
- ¿Qué tan bien anticipó esa historia lo que pasó después, de 2016 a 2025? ([Validación](#validación))

## Fuentes

Todas se descargan con `python -m tools.build_historico` y quedan descritas en
[`data/historico/fuentes.json`](../data/historico/fuentes.json) con su URL, su página, su licencia, la fecha en que se
obtuvieron, el número de registros que aportan, los que se descartaron y por qué, y el SHA-256 del archivo descargado.

### Eventos

| Fuente | Años | Escala | Qué aporta | Licencia |
|---|---|---|---|---|
| [DesInventar Perú](https://www.desinventar.net/DesInventar/profiletab.jsp?countrycode=per) (Corporación OSSO, LA RED, UNDRR) | 1970-2015 | Distrito | La serie homogénea: fichas de prensa (El Comercio, La República, Expreso) y del INDECI, con impactos. 14 114 fichas de peligros de origen climático | Uso libre con atribución |
| SINPAD (INDECI), [copia pública en ArcGIS Online](https://services8.arcgis.com/2qDHoDLqu6VOlf1y/arcgis/rest/services/Emergencias/FeatureServer/0) | 2016-2018 | Distrito y punto | 14 124 emergencias, entre ellas más de 4 000 del Niño Costero 2017. Sin cifras de daños | Información pública del INDECI; la copia no es oficial |
| SINPAD (INDECI), [portal público del SINPAD](https://sinpad.indeci.gob.pe/portal/), por la consulta de emergencias que usa el portal | 2019-2026 | Distrito | 112 170 emergencias de origen climático con su código, peligro, fecha, nivel y estado. Sin descripción, punto ni cifras de daños | Información pública del INDECI (Ley N° 27806) |
| [IDMC, actualizaciones de desplazamiento (IDU)](https://www.internal-displacement.org/database/displacement-data/), con datos del INDECI, por la API del IDMC | 2025-2026 | Distrito y punto | 4 895 emergencias que dejaron viviendas destruidas o inhabitables, con las personas desplazadas | CC BY-NC-SA 3.0 IGO |
| [IDMC, desplazamientos por desastres (GIDD)](https://www.internal-displacement.org/database/displacement-data/), por la API del IDMC | 2019-2024 | Casi siempre departamento y mes | 1 015 eventos; cubre el ciclón Yaku y el Niño costero 2023-24 por departamento | CC BY-NC-SA 3.0 IGO |
| [NASA, Global Landslide Catalog](https://gpm.nasa.gov/landslides/data.html) (copia en ArcGIS Online) | 2016-2020 | Punto | 22 deslizamientos y huaycos con la noticia que los reportó | Dominio público, con cita |
| [COEN (INDECI), reportes preliminares y complementarios](https://portal.indeci.gob.pe/informe/reportes-preliminares-complementarios-emergencias/) | 2021-2026 por ahora (el listado se descarga de lo más reciente hacia atrás) | Distrito | Cada emergencia con el título de su último reporte y, de las climáticas, el PDF: fecha de ocurrencia, descripción, código SINPAD, daños y el decreto que regía. 15 776 corroboran una fila del SINPAD; 3 887 son filas propias. La descarga de los PDF sigue en curso | Información pública del INDECI (Ley N° 27806) |
| Prensa: 44 medios regionales y nacionales (radios, diarios y portales de Piura, Tumbes, Lambayeque, La Libertad, Áncash, Lima, Arequipa, Cusco, Puno, Junín, Huánuco, Loreto, San Martín y otros), por su API de WordPress, su mapa del sitio o su archivo | 2007-2026 | Distrito o provincia | Titular, fecha, extracto de hasta 200 caracteres y enlace. 4 048 notas corroboran una fila; 1 380 son filas propias | La nota es del medio; se cita con enlace (D. Leg. 822, art. 44) |
| [Base mundial de desbordes de lagunas glaciares (GLOF)](https://zenodo.org/records/23370149), Lützow y Veh, v4.2 | 1883-2025 | Punto (la laguna) | 58 aluviones por desborde de lagunas glaciares con fecha, sobre todo de la Cordillera Blanca: laguna, mecanismo, detonante y fallecidos. No entran los que desató un sismo (1725, 1970) | CC BY 4.0 |
| [Cronología de El Niño en Trujillo y el norte](https://www.ncei.noaa.gov/pub/data/paleo/historical/southamerica/peru/trujillo2008.xls) (García-Herrera et al., 2008, actas del Cabildo de Trujillo y otros archivos; NOAA NCEI) | 1559-1899 | Ciudad o valle | 58 años con lluvias o inundaciones de El Niño en Trujillo, Chicama, Saña, Lambayeque, Piura y Paita, con la evaluación de los autores | Libre uso citando el artículo (NOAA WDC Paleoclimatology) |
| [«Las lluvias en Piura»](https://archive.org/details/boletndelasocied4189soci) (Víctor Eguiguren, Boletín de la Sociedad Geográfica de Lima, tomo IV, 1894; copia de Internet Archive) | 1728-1891 | Ciudad | 11 años de lluvias extraordinarias o grandes crecientes del río en Piura, Paita y el despoblado de Sechura, los que la cronología de Trujillo no tiene para Piura | Dominio público |
| [Chronicling America](https://www.loc.gov/collections/chronicling-america/) (Biblioteca del Congreso de EE. UU.), periódicos digitalizados, por la API JSON de loc.gov | 1836-1963 | Distrito, provincia o departamento | Páginas de periódicos de EE. UU. que reproducían cables y cartas de cónsules sobre inundaciones, lluvias, huaicos y aludes en el Perú: fecha de publicación, periódico, extracto del texto OCR de hasta 200 caracteres y enlace a la página. Se unen entre sí (el mismo cable en varios periódicos) y a las filas de archivo del mismo año | Dominio público o sin restricciones conocidas (Biblioteca del Congreso); se cita con enlace |
| Registros curados ([`data/historico/curado/`](../data/historico/curado/)) | 2017 | Distrito | Los diez distritos con más viviendas inhabitables o colapsadas en 2017 según el Plan Integral de Reconstrucción con Cambios | Cada registro cita su fuente |

### Contexto (no son eventos)

| Fuente | Qué aporta |
|---|---|
| [INGEMMET, inventario de peligros geológicos](https://geocatmin.ingemmet.gob.pe/arcgis/rest/services/SERV_PELIGROS_GEOLOGICOS/MapServer/0) | 27 300 puntos publicables (caídas, deslizamientos, flujos o huaycos, movimientos complejos, reptación) por distrito |
| [INGEMMET, zonas críticas](https://geocatmin.ingemmet.gob.pe/arcgis/rest/services/SERV_PELIGROS_GEOLOGICOS/MapServer/2) | 2 178 zonas críticas con el elemento expuesto y el boletín técnico |
| [ANA, puntos críticos](https://sigrid.cenepred.gob.pe/arcgis/rest/services/sectores/COEN_FEN_2027/MapServer/25) (servicio del SIGRID, CENEPRED) | 536 puntos críticos de ríos y quebradas de la costa con nivel de peligro, población y viviendas expuestas, acción recomendada y costo |
| [Establecimientos de salud afectados en 2022-23](https://sigrid.cenepred.gob.pe/arcgis/rest/services/sectores/COEN_FEN_2027/MapServer/9) (COE Salud, SIGRID) | 1 230 establecimientos afectados por las lluvias de 2022-2023 |
| [ubigeo-peru-aumentado](https://github.com/jmcastagnetto/ubigeo-peru-aumentado) (INEI y PNUD) | Población 2020, superficie, altitud, IDH 2019 y pobreza por distrito |

### Prevención (qué se sabía antes; no son eventos)

| Fuente | Qué aporta |
|---|---|
| [INGEMMET, inventario de peligros geológicos](https://geocatmin.ingemmet.gob.pe/arcgis/rest/services/SERV_PELIGROS_GEOLOGICOS/MapServer/0) con la fecha de cada punto (y la capa de otros peligros: erosión, inundación) | 36 800 puntos con fecha, por distrito, año y grupo de peligro (movimientos en masa, peligros geohidrológicos) |
| [INGEMMET, evaluaciones de peligros](https://geocatmin.ingemmet.gob.pe/arcgis/rest/services/SERV_PELIGROS_GEOLOGICOS/MapServer) y [repositorio institucional](https://repositorio.ingemmet.gob.pe/handle/20.500.12544/18) (informes técnicos) | Informes técnicos de un lugar, con su año y su enlace. La descarga del repositorio sigue en curso |
| [IGP, repositorio institucional](https://repositorio.igp.gob.pe/) (OAI-PMH) | Evaluaciones de peligro del IGP |
| [El Peruano, normas legales](https://busquedas.elperuano.pe/) | Decretos supremos de estado de emergencia: por peligro inminente (prevención), por impacto de daños (respuesta) y prórrogas, con los distritos, provincias o departamentos que declaran. La descarga sigue en curso: 235 decretos leídos |
| [IFRC GO, llamamientos](https://go.ifrc.org/countries/135) (Federación Internacional de la Cruz Roja) | 36 llamamientos y operaciones DREF en el Perú (el primero, de 1946), 18 por desastres climáticos (desde 1972). Solo metadatos (fecha, tipo, monto, beneficiarios) |

### Fuentes que no se pudieron usar

- **datosabiertos.gob.pe** responde con un muro antibots (HTTP 418); no se intentó saltarlo.
- **Decretos de emergencia de 2017 y 2023**: no hay una tabla de los distritos declarados; están en anexos en PDF.
- **EM-DAT** pide registro; **DFO** y **GDACS** son demasiado gruesos para el nivel distrital.
- **GDELT** (noticias del mundo desde 2015): la serie histórica solo se consulta en BigQuery y necesita un proyecto
  de Google Cloud con facturación.
- **Copernicus EMS** (mapas de emergencia por satélite): se revisó y no tiene activaciones para el Perú en lo que
  se consultó.
- **Archivos de prensa con muro de pago, inicio de sesión o verificación antirobots** (El Comercio, La República y
  otros): no se intentó saltarlos. La prensa de 1970-2015 ya está en DesInventar, que se armó con El Comercio, La
  República y Expreso.
- **Medios que piden en sus condiciones que su contenido no se use con inteligencia artificial** (entre ellos
  Noticias SER, El Nuevo Diario, Pro & Contra y Diario Uno): no se descargan.
- **ReliefWeb** y **YouTube** (noticieros de radio y televisión) piden una clave o un nombre de aplicación
  registrado; quedan para cuando el proyecto los tenga.
- **Hemerotecas digitales** (periódicos antiguos escaneados), además de Chronicling America:
  - **Biblioteca Nacional del Perú** (hemeroteca digital, El Comercio y El Peruano antiguos): solo responde desde el
    Perú; va por el recolector del Perú con el registro de fuentes.
  - **Gallica** (Biblioteca Nacional de Francia: Le Temps, Journal des débats y otros, que informaban del Perú en el
    siglo XIX), **HathiTrust** y **Papers Past** (Nueva Zelanda): responden con una verificación antirobots; no se
    intentó saltarla.
  - **Hemeroteca Digital de la Biblioteca Nacional de España**, la API de **Trove** (Australia) y el **archivo de
    Google Noticias**: su robots.txt no deja que un programa los consulte.
  - Los estudios de la época que ya resumieron la prensa y los archivos (Eguiguren, 1894; García-Herrera et al.,
    2008) entran como registros curados.

## Columnas del catálogo

`eventos.csv`, dentro de `public/assets/historico/eventos.zip` (UTF-8 con BOM, para que Excel lea las tildes; va
comprimido porque sin comprimir pasa de los 25 MiB que acepta Cloudflare Pages por archivo). Las 13 primeras son las
del tablero del equipo de prevención, con sus nombres exactos:

| Columna | Contenido |
|---|---|
| `Date` | Fecha de inicio (AAAA-MM-DD). Si la fuente solo da el mes, el día 01; si solo el año, 01-01 (ver `PrecisionFecha`) |
| `DangerType` | Inundacion fluvial, Inundacion pluvial, Inundacion (sin detalle), Desborde de rio, Huayco/Alud, Deslizamiento, Lluvias intensas, Oleaje anomalo, Erosion costera, Nevada, Granizada, Helada/Friaje, Ola de calor, Vientos fuertes, Tormenta electrica, Tormenta, Sequias, Incendio forestal, Erosion, Epidemia, Plaga |
| `Ubicacion` | El lugar más fino que da la fuente (sector, caserío, localidad) |
| `Distrito`, `Provincia`, `Departamento` | Nombres oficiales del INEI, con tildes |
| `Descripción` | Qué pasó, con la causa y los daños que describe la fuente |
| `DuraciónEvento` | Días, si la fuente los da |
| `Ubigeo` | Código vigente del INEI: 6 dígitos (distrito), 4 (provincia) o 2 (departamento). Es texto: al importarlo, léalo como texto para no perder el cero inicial («010101») |
| `TipoEvento` | FEN 1982-83, FEN 1997-98, Niño Costero 2017, Ciclón Yaku 2023, FEN 2023-24, FEN 2026, La Niña costera…, Temporada de lluvias, Temporada de heladas y friaje, Sin asociación ENSO, ICEN pendiente (meses después del último ICEN publicado) |
| `Fuente` | URL del registro o, si la fuente no tiene una página por registro (DesInventar, las capas de ArcGIS), de la fuente |
| `Latitud`, `Longitud` | Punto de la fuente si cae en el distrito asignado; si no, la capital del distrito. En las filas de provincia o de departamento, la capital de la provincia o del departamento (`PrecisionGeo` lo dice): en un mapa de puntos parecen agrupadas en las capitales |

Y 45 columnas más para análisis y trazabilidad: `Id` estable (`<origen>-<id en la fuente>`), `Origen`, `IdFuente`,
`FechaFin`, `PrecisionFecha`, `FechaTipo` (de qué es la fecha: `evento`; `informe`, la del primer reporte del COEN
cuando su PDF no se leyó; `publicacion`, la de la nota de prensa; `texto`, la que cita la nota), `Anio`, `Mes`, `AnioHidrologico` (julio a junio), `GrupoPeligro`, `PeligroFuente` (el
tipo como lo nombra la fuente), `DangerTypeMetodo` (fuente, texto, causa o por-omision), `CausaFuente`,
`NivelUbigeo`, `PrecisionGeo`, `Region` (macrorregión), `AltitudCapital`, `FaseENSO`, `EventoENSO`, `ICEN`, `ONI`,
`AtribucionENSO`, catorce columnas de impactos (fallecidos, desaparecidos, heridos, afectados, damnificados,
evacuados, reubicados, desplazados, viviendas destruidas y afectadas, hectáreas de cultivo, km de vías, centros
educativos y de salud, pérdidas en US$), `ImpactoReportado`, `ImpactoEnTotales`, `FuenteCita` (la cita original
legible), `Licencia`, `Confianza` (alta, media o baja según la precisión de fecha, lugar y tipo; nunca alta si la fecha es
la de un reporte o una publicación), `Corroboracion`
(cuántos reportes o notas de otras fuentes cuentan el mismo evento), `OrigenesCorroboran` y `FuentesAdicionales`
(sus enlaces, separados por « | », hasta 10).

Un impacto vacío significa «la fuente no lo reporta», no cero. `ImpactoEnTotales` es «no» solo cuando otra fila del
mismo evento ya detalla esas cifras (un registro curado que resume un área); el resto suma a los totales.

`diccionario.csv` (en `data/historico/` y en la pestaña) describe cada una de las 58 columnas: grupo, tipo, contenido,
valores posibles y el porcentaje de filas que traen el dato, en total y por fuente. Se genera con el catálogo desde
`enso/historico/esquema.py` (`COLUMN_DOCS`), así que no se desfasa.

Otros archivos:

- `data/historico/indicadores-{departamento,provincia,distrito,region}.csv`: los indicadores de cada área.
- `data/historico/contexto-distrito.csv`: por distrito, el historial (registros, años con daños y su intervalo, grandes
  Niños, registros del Niño en curso) junto al peligro identificado hoy (puntos del INGEMMET, zonas
  críticas, puntos críticos de la ANA con la población, las viviendas y el costo de las acciones, establecimientos de
  salud afectados en 2023). Es la tabla para priorizar.
- `data/historico/prevencion-distrito.csv`: por distrito, las declaratorias, los informes técnicos, los puntos de
  inventario con fecha, las emergencias desde 2003 y cuántas ocurrieron con el peligro ya documentado (ver
  [¿Se sabía antes?](#se-sabía-antes-peligros-documentados-y-emergencias)). `public/assets/historico/prevencion.json`
  trae lo mismo, más la serie por año, la lista de decretos e informes y los llamamientos de la Cruz Roja.
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

Entre los pasos 1 y 2: si el mes es posterior al último ICEN publicado, el registro queda como *ICEN pendiente*
(todavía no se sabe si fue un mes de Niño), salvo que la fuente lo atribuya a El Niño o La Niña.

La atribución es temporal: que un registro caiga dentro de un Niño no prueba que el Niño lo causó.
`AtribucionENSO` dice de dónde sale (curado, ventana-icen, fuente o ninguna).

Desde 2019 el SINPAD registra cada emergencia, también las pequeñas que atiende el distrito. Contadas todas, casi
todos los distritos del país tendrían «registros del FEN 2023-24» por las lluvias normales de la sierra entre enero y
abril de 2024 (1 650 distritos, frente a 332 con el criterio que sigue). Por eso una emergencia del portal del SINPAD
cuenta para un Niño o una Niña del ICEN (pasos 2 y 4) solo si fue de nivel 3 o más: la que necesitó al gobierno
regional o al nacional. Las de nivel 0 a 2 pasan al paso 5. Los eventos con nombre (paso 1) cuentan con cualquier
nivel.

## Fuentes que cuentan el mismo evento

El COEN, la prensa, los periódicos antiguos y la base de GLOF casi siempre cuentan una emergencia que el SINPAD o DesInventar ya registran.
Para no contarla dos veces, cada reporte o nota busca una fila del mismo lugar (el distrito; una nota que solo da la
provincia vale para cualquiera de sus distritos), del mismo grupo de peligro (las lluvias valen para lo que las
lluvias causan: inundaciones, huaycos, deslizamientos) y de una fecha compatible
(`enso/historico/enlace.py`):

| Quién | Con qué fila se une |
|---|---|
| COEN con código SINPAD (del PDF) | La emergencia del SINPAD con ese código |
| COEN con fecha de ocurrencia (del PDF) | ±3 días |
| COEN solo con la fecha del primer reporte | Un evento de hasta 10 días antes (o del día siguiente) |
| COEN sin nada de lo anterior | Una emergencia del SINPAD del mismo distrito y grupo hasta 30 días alrededor |
| GLOF | ±3 días con el día; el mismo mes con solo el mes; con solo el año no se une |
| Nota de prensa | Un evento de hasta 10 días antes de la publicación (o del día siguiente); si el texto cita la fecha del evento («el pasado 14 de marzo», hasta 60 días antes), de 3 días antes de esa fecha al día siguiente de la publicación; con solo el mes, ese mes o el anterior |
| Fila distrital del IDMC | La emergencia del SINPAD del mismo distrito a ±1 día (preferida la del mismo grupo de peligro). El IDMC recopila las mismas emergencias del INDECI: sus personas desplazadas, viviendas y duración pasan a la fila del SINPAD, que no trae daños desde 2019, y la fila del IDMC se quita (4 934 en el catálogo de octubre de 2026) |
| Página de periódico antiguo | Un evento de hasta 45 días antes de la publicación (un cable o la carta de un cónsul tardaban semanas en llegar y los semanarios los reproducían después); si no, una fila de ese mes o ese año que solo tiene el mes o el año (los archivos curados). Una página que solo nombra el departamento vale para cualquier lugar del departamento |

Si la encuentra, la fila suma uno a `Corroboracion`, el enlace en `FuentesAdicionales` y el origen en
`OrigenesCorroboran`; las cifras de daños del COEN pasan a la fila solo si la fila no trae ninguna (las de la base de
GLOF y de la prensa no pasan: quedan en su enlace). Si no la
encuentra, el reporte o la nota queda como **fila propia**: un evento que ninguna otra fuente registró (el COEN marca
algunos como «no registrada en el SINPAD»), y las notas siguientes del mismo evento se suman a esa fila. El orden es
COEN, GLOF, prensa y periódicos antiguos. Cuántos se unieron por cada regla queda en `enlace` de `fuentes.json`.

La prensa pasa antes por filtros: se descartan las notas de sismos, desagües, incendios urbanos, crímenes, calles
que se llaman como un peligro, y las de obras, limpiezas, simulacros y otras actividades de prevención; el lugar lo pone el mismo ubicador de noticias del
observatorio y el peligro, el texto. Solo se guarda el titular, la fecha, un extracto de hasta 200 caracteres y el
enlace: el texto completo es del medio.

Los **periódicos antiguos** se buscan en Chronicling America con unas 40 consultas en inglés sobre el texto OCR
(«floods in peru», «peru AND piura AND flood», «ranrahirca»…, en `parametros.consultas` de `fuentes.json`); de cada
página se guarda el fragmento donde aparecen los términos (`tools.build_historico.loc_chronam`). El fragmento junta
varias notas de la página, así que se lee solo el texto alrededor de cada mención del Perú, y se descartan los Perú
y las Lima de EE. UU. (las inundaciones del Wabash en Peru, Indiana, en 1913, llenan las búsquedas), la geografía de
los libros de texto («it never rains in Peru»), los sismos, maremotos y volcanes (el alud de Yungay de 1970 lo desató
un sismo), los derrumbes dentro de minas sin lluvias de por medio (Morococha, 1928) y lo que no dice que algo pasó.
El lugar es el primero que nombra la nota, con el mismo ubicador (los nombres de la época, como Huaras o Payta, y los
del OCR, como Pavta, se cambian por los de hoy, y «town of» por «ciudad de»). No cuentan el encabezado del cable
(«LIMA, Peru, March 20», «Lima Peru Fob 28», «LIMA, Peru (AP)»), porque dice desde dónde se envió, ni Lima o el Callao
como quien informa («advices from Lima», «reports reaching Lima»), porque por ahí pasaban todos los cables; sin fecha
ni agencia, «Piura, Peru» es un lugar de la nota. Así, «landslides in the interior… reports reaching Lima said» no
entra por no tener lugar, en vez de quedar en Lima. La fecha es la de publicación
(`FechaTipo = publicacion`) y la confianza, baja: el OCR tiene errores («lea» por Ica) y una página que no se pudo
ubicar no entra.

## Reglas de calidad

Las aplica `tidy` de `tools/build_historico.py` a todo el catálogo, en la construcción completa y con
`--desde-catalogo`. Las encontró la revisión independiente de octubre de 2026 (ver [Validación](#validación)); cuántas
filas tocó cada una queda en `calidad` de `fuentes.json` y de `resumen.json`.

| Regla | Por qué | Filas (oct. 2026) |
|---|---|---|
| Una fila distrital del IDMC con una emergencia del SINPAD del mismo distrito a ±1 día se une a ella | Es la misma emergencia del INDECI contada dos veces | 4 934 |
| Las fechas del SINPAD 2016-2018 se leen en hora de Lima | La copia guarda la hora de Lima como si fuera UTC: las emergencias de la noche quedaban un día después | 2 630 |
| Confianza alta → media si la fecha es la de un reporte o una publicación | Esa fecha no es la del evento | 3 416 |
| DesInventar con fecha 1 de enero → precisión de mes | DesInventar pone el 1 de enero cuando no sabe el día: hay cinco veces más de lo esperable | 197 |
| Meses después del último ICEN → «ICEN pendiente» | Todavía no se sabe si fue un mes de Niño | 2 858 |
| Notas de prensa cuyo titular trata de bonos, reconstrucción, donaciones, expedientes técnicos o crímenes → fuera | No cuentan un desastre | 15 |
| `ImpactoEnTotales` vacío → «si» | Las cifras del IDMC y de otras fuentes no sumaban a los totales | todas |

Otras correcciones están en los lectores y entran con la próxima cosecha completa: los títulos del COEN con «Niño» o
«Niños» en la dirección y los que nombran varios lugares (solo se separan si el título está en plural), nombres
antiguos o mal escritos (Raimondi, El Arenal, Ccapacmarca, San Miguel del Faique), las fechas de la base de GLOF que
solo dan una ventana de satélite (el año si la ventana cae en un año; el mes del medio si dura menos de un año), la
duración de un día de las filas del IDMC y más palabras para descartar notas de prensa que no son un evento.

## Indicadores

Se calculan igual en Python (`enso/historico/indicadores.py`, para los CSV) y en el navegador
(`public/assets/js/historico-model.js`, para los filtros de cada persona); una prueba compara ambos.

Con T = temporadas (julio a junio) de 1970-71 a 2014-15 (45) e Y = temporadas con al menos un registro de
DesInventar en el área:

| Indicador | Definición | Para qué sirve |
|---|---|---|
| Años con daños | Y de T, con intervalo de Wilson al 95 % (Wilson, 1927; Brown, Cai y DasGupta, 2001), que funciona con muestras pequeñas y con 0 o T. «Como mínimo» es su límite inferior | Cuenta temporadas, no fichas: un Niño deja decenas de fichas en un distrito. El límite inferior ordena las áreas con pocos años sin premiar al azar |
| 1 de cada X años | T / Y, con intervalo [1 / superior, 1 / inferior] del de Wilson | La misma frecuencia, dicha como periodo de retorno |
| Probabilidad en 5 años | 1 − (1 − Y/T)^5, con intervalo [1 − (1 − inferior)^5, 1 − (1 − superior)^5] | Lo mismo, dicho como probabilidad; supone temporadas independientes |
| Lugares-años | Pares (distrito, temporada) con daños | En provincias y departamentos, cuántos de sus distritos sufren cada temporada |
| Razón de El Niño | (lugares-años en temporadas con Niño costero / esas temporadas) ÷ (lugares-años en las demás / las demás), con intervalo al 95 % cuasi-Poisson | Dónde El Niño costero aumenta los lugares con daños, y dónde no |
| Grandes Niños | Cuáles de FEN 1982-83, FEN 1997-98, Niño Costero 2017, Ciclón Yaku 2023 y FEN 2023-24 dejaron registros | La pregunta del especialista: ¿se repite? |
| Registros intensivos | Fichas con ≥ 30 fallecidos o ≥ 600 viviendas destruidas (umbral del GAR 2015 de UNDRR) | Separa los desastres grandes de los daños frecuentes y pequeños (en los CSV) |

Los tres primeros suponen que el clima y la exposición no cambian: son frecuencias del pasado, no pronósticos.

**Temporada con Niño costero.** La media del ICEN de enero a marzo, el pico de lluvias de la costa norte, supera
+0,5 °C, el umbral de condición cálida del ENFEN (Nota Técnica 01-2024). De 1970-71 a 2014-15 son seis: 1971-72,
1972-73, 1982-83, 1986-87, 1991-92 y 1997-98. La regla anterior («algún mes de diciembre a abril en Niño costero»)
marcaba 16 temporadas, muchas con un Niño débil o que empezó en abril, y diluía el efecto: con ella solo Piura y
Tumbes quedan claramente sobre 1. Sigue en los datos (`nino_hydro_years_any`) para la prueba de sensibilidad.

**Distritos que no son independientes.** Un Niño golpea a muchos distritos en la misma temporada, así que los
lugares-años varían más de lo que supone Poisson. El intervalo de la razón multiplica la varianza de Poisson por la
dispersión φ = χ² de Pearson de los lugares-años por temporada / (T − 2), con mínimo 1 (cuasi-Poisson; McCullagh y
Nelder, 1989). Con φ = 5 el intervalo es √5 ≈ 2,2 veces más ancho. φ queda en la columna `dispersionNino` de los CSV.

**Dosis-respuesta.** Como prueba que no depende de un umbral, un modelo de Poisson log μ = a + b · ICEN de enero a
marzo (Newton-Raphson; intervalo de Wald multiplicado por √φ) da cuánto cambian los lugares con daños por cada grado
del ICEN (`dose_response`).

**Solo DesInventar entra a la frecuencia.** El SINPAD (2016 en adelante) tiene más de diez veces los registros por
año de DesInventar; IDMC 2025-2026 solo incluye emergencias con viviendas inhabitables. Mezclarlas cambiaría la frecuencia
por un cambio de fuente, no del clima. Las fuentes posteriores sí cuentan para los registros, los impactos, los
grandes Niños y el mapa, y sirven para la validación.

**Se quitó el nivel de atención.** La regla anterior (muy alto, alto, medio o bajo según los grandes Niños y la
frecuencia) no tenía validación y marcaba muy alto a 127 de 196 provincias: no ordenaba. La revisión independiente
recomendó quitarla. El ranking ordena ahora por la frecuencia o por su límite inferior, cuya capacidad de ordenar sí se
midió (ver [Validación](#validación)).

Resultados principales (catálogo de octubre de 2026):

- **El Niño costero aumenta los lugares con daños en la costa norte y centro.** Lugares con daños por temporada con
  Niño costero frente a las demás: Piura 3,6 veces (IC 95 %: 2,3–5,4), Lambayeque 3,1 (1,9–5,1), La Libertad 2,7
  (1,6–4,8), Áncash 2,7 (1,6–4,6), Tumbes 2,5 (1,6–3,9), Ica 2,2 (1,3–3,6), Lima 1,9 (1,3–2,8) y Arequipa 1,9
  (1,4–2,7); el Perú, 1,6 (1,1–2,2). Los mismos ocho tienen también una dosis-respuesta claramente positiva. En los
  demás departamentos el intervalo incluye 1: no hay diferencia clara.
- **Los mismos lugares se repiten.** Piura, Tumbes, Lambayeque, La Libertad, Áncash, Cajamarca, Lima e Ica tienen
  registros en los cinco grandes Niños. En la costa norte, el 98 % de los distritos golpeados en 1982-83 y en 1997-98
  volvió a tener registros en 2017.
- **El peligro de hoy coincide con la historia.** 81 de los 90 distritos con puntos críticos de peligro muy alto de la
  ANA tienen registros en dos o más grandes Niños (Chimbote, Lurigancho, Chicama, Piura y otros). La capa de la ANA
  cubre sobre todo la costa.

## Validación

El equipo pidió que cada cifra de la pestaña salga de los datos con un método establecido y que se ponga a prueba de
forma independiente. Se hizo en dos partes.

**1. Revisión independiente.** Dos revisores, sin ver el trabajo del otro, revisaron el método y los datos (fila por
fila en muestras). Encontraron cifras de impacto del IDMC que no sumaban a los totales, fechas del SINPAD 2016-2018
corridas un día, emergencias del IDMC contadas dos veces con su gemela del SINPAD, notas de prensa sobre bonos o
reconstrucción tomadas como eventos, una regla de temporada de Niño demasiado amplia, intervalos que suponían
distritos independientes, un «nivel de atención» sin validar y frases que decían más de lo que mostraban los datos.
Todo se corrigió (ver [Reglas de calidad](#reglas-de-calidad) e [Indicadores](#indicadores)).

**2. Prueba fuera de muestra**, como se verifica un pronóstico. Los indicadores usan solo DesInventar de 1970-71 a
2014-15; las emergencias del SINPAD de 2016-17 a 2025-26 no entran a ningún indicador, así que sirven para ponerlos a
prueba con datos que el método no vio (`enso/historico/validacion.py`). Los resultados quedan en `resumen.json`
(`validacion`) y en la sección «¿La historia anticipa lo que vino después?» de la pestaña.

| Pregunta | Método | Resultado (catálogo de octubre de 2026) |
|---|---|---|
| ¿La frecuencia del pasado ordena bien las áreas? | AUC (área bajo la curva ROC; Hanley y McNeil, 1982): la probabilidad de que un área-temporada con emergencias en 2016-2025 tenga más frecuencia histórica que una sin emergencias. Intervalo al 95 % por remuestreo de áreas (bootstrap por conglomerados, 500 réplicas). Solo el orden es comparable: el SINPAD registra muchas más emergencias por año que DesInventar | Provincias: 0,75 (0,62–0,86) con todos los peligros; heladas y friaje 0,81, huaycos y deslizamientos 0,72, inundaciones 0,64. Distritos: 0,55 (0,53–0,56), casi como el azar; heladas 0,63 |
| ¿Se repitió el efecto de El Niño? | Razón de El Niño de 2016-2025 (temporadas con Niño costero: 2016-17, 2018-19, 2022-23 y 2023-24) en las áreas donde la de 1970-2015 fue claramente mayor que 1 y en las demás; correlación de Spearman entre el orden de las áreas en los dos periodos | Departamentos: 1,21 (0,92–1,61) donde la histórica era mayor que 1, frente a 1,00 (0,84–1,19); Spearman 0,71. Provincias: 1,28 (0,93–1,76) frente a 1,02 (0,86–1,22); Spearman 0,43. Va en la dirección esperada; con solo cuatro temporadas de Niño, los intervalos incluyen 1 |
| ¿Acierta la probabilidad de daños? | Con la misma fuente: la frecuencia de DesInventar 1970-1999 como probabilidad de daños en cada bloque de cinco años de 2000-2014 (1 891 distritos). Puntaje de Brier y su habilidad frente a decir siempre la tasa base (Wilks, 2011), diagrama de confiabilidad y la misma frecuencia suavizada por Bayes empírico (beta-binomial por momentos) | Habilidad 0,05 sin suavizar y 0,10 suavizada: mejora poco sobre la tasa base (31 %). Exagera en los extremos: donde da 0 %, el 17 % de los distritos tuvo daños; donde da más de 80 %, el 76 % |
| ¿Vuelven los grandes Niños a los mismos lugares? | Frecuencia condicional: de los distritos golpeados en 1982-83 y 1997-98, en uno de los dos o en ninguno, cuántos tuvieron registros en 2017 | Costa norte (Tumbes, Piura, Lambayeque y La Libertad): 98 % de los golpeados en los dos, frente a 82 % en uno y 83 % en ninguno (90 % en total). 13 departamentos del Plan de Reconstrucción: 91 % frente a 76 % y 75 % |
| ¿Depende la razón de El Niño de la regla elegida? | Sensibilidad: la regla de temporada, la regla anterior y la dosis-respuesta por grado de ICEN | Los ocho departamentos con razón claramente mayor que 1 también la tienen por grado de ICEN; con la regla anterior, solo Piura y Tumbes |

Qué quiere decir:

- Para decidir dónde mirar primero, la historia sirve **por provincia y por peligro**, no por distrito. Por distrito,
  el peligro identificado hoy (puntos del INGEMMET y de la ANA, en cada ficha) anticipa mejor las emergencias: el
  68 % de las emergencias desde 2016 ocurrió donde el peligro ya estaba documentado (ver
  [¿Se sabía antes?](#se-sabía-antes-peligros-documentados-y-emergencias)).
- El efecto de El Niño es firme en la costa norte y centro: aparece con las tres formas de medirlo y se repitió en la
  misma dirección después de 2016.
- «1 de cada X años» y «probabilidad en 5 años» son frecuencias del pasado: anticipan poco y exageran en los extremos.
  Por eso la pestaña siempre las muestra con su intervalo.
- Los grandes Niños sí vuelven a los mismos lugares: en la costa norte, casi todos los distritos golpeados en 1983 y
  1998 volvieron a tener registros en 2017.

Las pruebas (`tests/test_historico.py`) comprueban cada método con datos de resultado conocido (el AUC, una
dosis-respuesta exacta, una predicción perfecta y una que falla en la calibración, la repetición de los grandes Niños,
los intervalos de Wilson y cuasi-Poisson), que Python y el navegador den lo mismo, y que la validación publicada tenga
todas sus partes.

## Cómo usar los indicadores

La pestaña lo resume en «Cómo usar esta pestaña», abierto al entrar.

| Para | Use | No concluya |
|---|---|---|
| Saber qué pasó y dónde | La lista de registros de cada ficha, con su fuente y las otras fuentes que cuentan lo mismo | Que un lugar sin registros no tiene peligro: DesInventar se armó con prensa e informes, y hay más registros donde hay más gente y acceso |
| Elegir provincias que mirar primero | «Años con daños» o «Años con daños, como mínimo», por peligro | Que el orden por distrito es confiable: casi como el azar (AUC 0,55) |
| Prepararse para un Niño fuerte | La razón de El Niño donde su intervalo queda sobre 1, los mapas de los grandes Niños y «Si se repite un gran Niño» en cada ficha | Que la razón mide la magnitud del daño: cuenta lugares con registros. Tampoco compare grandes Niños en cantidad: cada uno viene de fuentes con densidad distinta |
| Saber qué se conocía antes de cada emergencia | «¿Se sabía antes?», comparado con el azar | Que «documentado» quiere decir «evitable»: el inventario marca puntos de peligro, no obras |
| Cifras de daños | Los totales que reportó cada fuente | Que un vacío es cero: es «no reportado» |

Una frecuencia de 0 de 45 años tiene intervalo 0–8 %: quiere decir «sin registros en DesInventar», no «sin peligro»;
uno de cada seis distritos así tuvo daños en los cinco años siguientes. La «alerta según la historia» del aviso del
Niño en curso nombra solo los departamentos con razón de El Niño claramente mayor que 1; las alertas oficiales son
las del ENFEN, el SENAMHI y el INDECI.

## Peligro identificado hoy (contexto)

La historia dice dónde golpeó; los inventarios oficiales dicen dónde el peligro está identificado hoy. La ficha de
cada área muestra los dos juntos: los puntos críticos de la ANA (con el sector, el peligro, la población y las
viviendas expuestas, la acción recomendada y su costo), las zonas críticas del INGEMMET (con el boletín técnico), el
número de puntos de peligro geológico inventariados y los establecimientos de salud afectados en 2023. No son eventos
con fecha y no entran a ningún indicador.

## ¿Se sabía antes? Peligros documentados y emergencias

Para poner a prueba la idea del especialista (poca prevención desde los años 90), para cada emergencia oficial con la
fecha del evento (SINPAD, DesInventar y COEN, desde 2003) se mira qué se sabía antes en su distrito
(`enlace.prevention`):

- **Inventario**: si el INGEMMET ya había inventariado ahí un punto de peligro del mismo grupo, con fecha anterior a
  la emergencia (movimientos en masa para huaycos y deslizamientos; peligros geohidrológicos para inundaciones y
  erosión; las lluvias valen para los dos).
- **Informe técnico**: si había una evaluación del INGEMMET o del IGP de ese distrito de un año anterior.
- **Peligro inminente**: si había una declaratoria de emergencia por peligro inminente de un peligro compatible en
  los 365 días anteriores. Una declaratoria de toda una provincia o un departamento cuenta para cada uno de sus
  distritos.

Resultados (catálogo del 26-10-2026, con las descargas de El Peruano y de los informes del INGEMMET a medias):

- **El 68 % de las emergencias oficiales desde 2016** (86 181 de 126 220) ocurrió en un distrito donde el peligro ya
  estaba documentado; casi todas (82 564) por el inventario del INGEMMET. En 2017 fue el 84 %; en 2025, el 74 %.
- **1 693 de los 1 817 distritos** con emergencias en cinco o más temporadas desde 2003 tenían el peligro inventariado
  o evaluado.
- **Declaratorias**: hasta ahora hay muchas más por impacto (respuesta) y prórrogas que por peligro inminente
  (prevención); la cifra crecerá con la descarga.
- **Comparado con el azar.** Casi todos los distritos tienen algún peligro inventariado, así que la mayoría de las
  emergencias caería en un distrito «documentado» aunque la documentación no tuviera relación con ellas. La
  construcción completa calcula cuántas lo estarían si las mismas emergencias, con su fecha y su peligro, cayeran en
  un distrito al azar: uniforme y según la población (`eventosConAvisoAzar` y `eventosConAvisoAzarPob` de cada año en
  `prevencion.json`; es una prueba de permutación, como en Bar-Hillel, 1980). La diferencia con lo observado es lo
  que la documentación anticipa. La revisión independiente la estimó: entre 64 % y 66 % al azar, solo 2 a 4 puntos
  menos que el 68 % observado.

Cómo leerlo:

- *Documentado* no quiere decir *evitable*. Quiere decir que el Estado tenía el peligro identificado en ese distrito
  antes de la emergencia. El inventario marca puntos de peligro, no obras. Esta cifra no mide cuánta prevención se
  hizo ni si se pudo evitar el daño: para eso hace falta comparar lugares con y sin obras, antes y después
  (diferencias en diferencias).
- La proporción se compara entre años, no la cantidad: desde 2016 el SINPAD registra diez veces más emergencias por
  año que DesInventar antes, y el inventario del INGEMMET creció mucho entre 2003 y 2013.
- La prensa y los registros curados no entran a esta cuenta.

En la pestaña, la sección «¿Se sabía antes?» muestra la proporción por año, la comparación con el azar, la tabla por
año, los llamamientos de la Cruz Roja y estos avisos; la ficha de cada área, su propio recuento.

## La pestaña

- **Aviso del Niño en curso**, con el último ICEN (y si es preliminar), y la **alerta según la historia**: los
  departamentos donde las temporadas con Niño costero tuvieron claramente más lugares con daños (intervalo de la
  razón sobre 1).
- **Cómo usar esta pestaña**: para qué sirve y qué no concluir, con las cifras de la validación.
- **Mapa** por departamento, provincia o distrito, con filtros de evento (grandes Niños, uno en particular, el Niño
  en curso, cualquier Niño, La Niña, años neutros), de peligro y de temporadas, y la métrica a pintar: años con daños,
  años con daños como mínimo (el límite inferior del intervalo), grandes Niños, lugares con daños con Niño (las áreas
  cuyo intervalo incluye 1 van en gris), registros, fallecidos, afectados o viviendas destruidas. Los cortes de «años
  con daños» cambian con el nivel (un departamento casi siempre tiene daños; un distrito, rara vez). Con un filtro de
  evento la razón de El Niño no se muestra: compararía un evento con sus propias temporadas. Todo el estado queda en
  la dirección (`#/memoria?nivel=distrito&area=200105`) para compartir una vista.
- **Ficha** de cada área: años con daños, 1 de cada X años y probabilidad en 5 años, cada uno con su intervalo;
  grandes Niños, registros del Niño en curso, «si se repite un gran Niño» (con cuántos de sus lugares golpeados antes
  volvieron a tener registros), peligro identificado hoy, «¿se sabía antes?», impactos, peligros, temporadas con daños
  y la lista de registros con su descripción, su fuente y las otras fuentes que cuentan lo mismo («También lo
  cuentan…», con enlace a cada reporte o nota).
- **Línea de tiempo** de lugares con daños por temporada, con las temporadas de Niño costero marcadas.
- **Los grandes Niños uno al lado del otro** (dónde dejó registros cada uno) y la **tabla de lugares golpeados en dos
  o más**.
- **Ranking** (la versión en tabla del mapa), con la frecuencia y su intervalo.
- **¿La historia anticipa lo que vino después?**: la [validación](#validación), con su lectura.
- **¿Se sabía antes?** y **antes de 1970**: los lugares con registros de archivo y de lagunas glaciares, con sus años.
- **Evidencia** sobre la prevención desde los años 90 y **fuentes, método, límites y descargas** (catálogo, CSV de
  indicadores, contexto y prevención, y el diccionario de datos).

El diseño sigue las prácticas de los tableros de riesgo de referencia (DesInventar, el Índice de Riesgo INFORM, el
SIGRID del CENEPRED): mapa coroplético con tabla equivalente, colores de una sola tonalidad para magnitudes y
divergentes centrados en 1 para la razón de tasas, estados con icono y texto (no solo color), cifras con su fuente,
frecuencias y razones con su intervalo, y avisos claros de lo que el dato no dice.

## Evidencia sobre la prevención desde los años 90

La sección «¿Se ha hecho poca prevención desde los años 90?» de la pestaña reúne las afirmaciones a favor y en contra,
cada una con su fuente (`public/assets/js/historico-evidencia.js`). El veredicto es **en parte cierto**:

- **Sí se hizo**: el SINAGERD (2011), el CENEPRED y un programa presupuestal de prevención; alertas y pronósticos
  mejores. Los fallecidos reportados por evento bajaron: 512 (1982-83), unos 374 (1997-98), 162 (2017), 84 (2023);
  también por millón de habitantes (unos 28, 15, 5 y 2,5). Son cuatro eventos de intensidad distinta, contados por
  fuentes distintas: muestran menos muertes, no prueban una tendencia.
- **Sigue pendiente**: en 2017 el Plan Integral de Reconstrucción prometió soluciones definitivas en 17 ríos, el
  drenaje de cuatro ciudades y cuatro quebradas; en 2023 el Contralor dijo que la reconstrucción «ha fracasado» y a
  mayo de 2026 solo 9 de 102 soluciones integrales estaban terminadas. El río Piura conduce hoy cerca de la mitad del
  caudal pico de 1998.
- **Conclusión para la preparación**: si se repite un Niño fuerte, lo esperable es que vuelvan los daños a viviendas
  e infraestructura en los mismos lugares del norte (en la costa norte, el 98 % de los distritos golpeados en 1983 y
  1998 tuvo registros en 2017). Que la mortalidad de 1983 no se repita es un juicio de expertos, no una estimación.

## Límites

- **Sesgo de las fuentes.** DesInventar se arma con prensa nacional e informes del INDECI: hay más registros de
  ciudades y lugares accesibles, y menos antes de los años 90. Una zona sin registros no es una zona sin peligro.
- **Cambio de fuentes en el tiempo.** Las barras de la línea de tiempo y los mapas de cada gran Niño no se comparan
  en cantidad: hasta 2015 vienen de DesInventar y desde 2016 del SINPAD, mucho más denso. Por eso los mapas de los
  grandes Niños muestran presencia y no cantidad.
- **El SINPAD desde 2019 no trae descripción ni daños.** El portal da el peligro principal, el distrito, la fecha, el
  nivel y el estado de cada emergencia: esas fichas se ubican en la capital del distrito y su tipo es el que nombra
  el SINPAD. Las cifras de esos años (personas desplazadas, viviendas) vienen del IDMC, que parte de las mismas
  emergencias del INDECI: una fila distrital del IDMC se une a su emergencia del SINPAD (mismo distrito, ±1 día) y le
  pasa sus cifras. Las filas del IDMC por departamento y mes son resúmenes de desplazamiento, no eventos aparte; no
  tienen gemela y siguen como filas propias. Quedan fuera las que el
  SINPAD llama «otros», las epidemias y plagas (sin descripción no se sabe si las causó el clima), y los derrumbes
  de viviendas y los aniegos, que casi siempre no son climáticos.
- **Los impactos** son los que publicó cada fuente; las fuentes discrepan (Huggel et al., 2015). Un registro curado
  que resume un área ya detallada por otra fuente con cifras no suma sus impactos dos veces (`ImpactoEnTotales`).
- **Ubicación.** Los registros se ubican por el UBIGEO o el nombre de la fuente; si el nombre está abreviado
  («S. J. DE LURIGANCHO»), por el punto de la fuente dentro de los límites del IGN. Los distritos creados después de
  esos límites no tienen polígono: cuentan para su provincia y su departamento. Las filas sin punto llevan las
  coordenadas de la capital del distrito, de la provincia o del departamento: en un mapa de puntos se agrupan en las
  capitales, y no deben leerse como el lugar exacto.
- **Fechas.** La fecha de una fila propia del COEN cuyo PDF no se leyó es la de su primer reporte, y la de una nota
  de prensa, la de su publicación (`FechaTipo`): pueden ir días después del evento. Esas filas nunca tienen confianza
  alta. DesInventar pone el 1 de enero cuando no conoce el día; esas fichas quedan con precisión de mes.
- **Tipo de peligro.** Donde la fuente dice solo «inundación» y el texto no da pistas, queda *Inundacion (sin
  detalle)*: no se sabe si fue fluvial o pluvial.
- **Eventos con nombre.** *Niño Costero 2017* y *Ciclón Yaku 2023* se asignan a todo registro de lluvias,
  inundaciones, huaycos, deslizamientos, oleaje o viento de esos meses en sus departamentos, aunque algún daño se
  deba a otra causa. Lo mismo vale para los Niños del ICEN: la atribución es temporal.
- **Más registros con el tiempo.** DesInventar tiene menos fichas antes de 1990 y más en los años 2000, y los
  registros se ubicaron mejor con los años: la frecuencia mezcla el clima con cómo se registraba. Por eso la
  validación compara el orden de las áreas y no los conteos.
- **La copia del SINPAD 2015-2018 no es oficial** (la subió una cuenta de terceros a ArcGIS Online). Si el INDECI
  publica la serie, debe reemplazarla.
- **Prensa.** Hay más notas de las ciudades con medios en línea y de los últimos años (los archivos en línea de la
  mayoría de medios regionales empiezan después de 2010). Una nota que el ubicador no pudo ubicar o que no pasó los
  filtros no entra. Los filtros tampoco son perfectos: en muestras de 40 filas propias de prensa revisadas a mano,
  entre 4 y 6 no eran un evento nuevo (ayuda que llega semanas después, un pedido de los vecinos, un aniego por
  redes de desagüe, un tipo de peligro mal puesto). La prensa corrobora; no entra a la frecuencia ni a la
  prevención.
- **Archivos antes de 1970.** La cronología de Trujillo y el estudio de Eguiguren registran años con lluvias o
  inundaciones, no cada evento, y se ubican en la ciudad o el valle que nombran. Los periódicos antiguos son sobre
  todo de EE. UU.: cuentan lo que llegaba por cable (Lima, Callao, la costa norte, los ferrocarriles), no lo de cada
  distrito. La base de GLOF registra los aluviones que alguien estudió; hay más
  en la Cordillera Blanca porque ahí se estudiaron más.
- **Descargas a medias.** Los PDF del COEN, los decretos de El Peruano, los informes del INGEMMET y algunos medios se
  descargan despacio (5 s o más entre pedidos) y siguen en curso, en GitHub Actions
  ([Cosecha en GitHub Actions](#cosecha-en-github-actions)). `fuentes.json` marca esas fuentes con `parcial` y la
  pestaña lo avisa; las cifras de prevención y de corroboración van a cambiar.
- **Frecuencia no es pronóstico.** Suponer que el pasado se repite ignora el cambio climático y el crecimiento de la
  exposición (más gente en riberas y quebradas), que empujan el riesgo hacia arriba.

## Reproducir y actualizar

```bash
cd python
pip install -r requirements-dev.txt
python -m tools.build_historico                    # descarga lo que falte en ~/.cache/enso-historico y reconstruye
python -m tools.build_historico --sin-red          # solo con la caché
python -m tools.build_historico --aceptar-cambios  # tras revisar que una fuente cambió
python -m tools.build_historico --sin-red --parcial --cache ~/.cache/enso-historico --cache OTRA/CACHE
                                                   # con lo bajado hasta ahora de las descargas largas
python -m tools.build_historico --desde-catalogo   # rehace indicadores, validación y archivos desde eventos.zip
python -m tools.build_historico --indices-al-dia CARPETA
                                                   # con el ICEN y el ONI descargados al día en CARPETA
python -m tools.build_historico_mapa               # polígonos de provincias y distritos (solo si cambian los límites)
node --test tests/js/historico.test.mjs            # paridad Python/navegador
pytest -q tests/test_historico.py
```

- `--desde-catalogo` no descarga ni vuelve a leer las fuentes: parte del catálogo publicado (`eventos.zip`, que se lee
  de vuelta sin pérdida), vuelve a leer los registros curados y, de la caché, las fechas del SINPAD 2016-2018 si
  están, y aplica las [reglas de calidad](#reglas-de-calidad) antes de calcular los indicadores, la validación y los
  archivos del sitio. Sirve cuando cambia el método y no las fuentes. La comparación de prevención con el azar
  necesita la evidencia de la caché y solo se calcula si está; `generado` de `fuentes.json` no cambia.
- `--indices-al-dia CARPETA` descarga el ICEN (IGP) y el ONI (NOAA CPC) vigentes en CARPETA; si una descarga falla o
  trae menos meses que la copia de las pruebas, usa esa copia. `resumen.json` (`indicesENSO`) dice qué archivo se usó,
  su SHA-256 y su último mes. La cosecha de GitHub Actions lo usa.
- Como el resto del observatorio, el script lee el robots.txt de cada servidor antes de pedir nada (RFC 9309, con
  `enso.reach.Robots`) y respeta su `Crawl-delay`; si el robots.txt no responde, no pide nada a ese servidor.
- El IDMC se pide a su propia API (su robots.txt la permite; el de HDX no deja que un programa baje sus CSV). La API
  pide una clave gratuita (`client_id`) que se solicita una vez por correo a ch.datainfo@idmc.ch, con el uso que se le
  dará, y se guarda en la variable de entorno `IDMC_CLIENT_ID` (en GitHub Actions, el secreto del mismo nombre),
  nunca en el repositorio. El script guarda las filas del Perú como CSV con columnas y filas ordenadas. Sin la clave
  usa la semilla del repositorio (`data/historico/semillas/`, campo `semilla` de `fuentes.json`): la exportación del
  IDMC en HDX del 26-10-2026, con las mismas columnas, comprimida. `fuentes.json` dice cuál se usó (`copia`: `API` o
  `semilla`). Los datos del IDMC son CC BY-NC-SA 3.0 IGO: uso no comercial, con atribución y la misma licencia en lo
  derivado, también la semilla.
- Instituciones públicas peruanas (dominios `.gob.pe` y `.mil.pe`): su información es pública por la Ley N° 27806
  y, por decisión del proyecto del 26-10-2026, un `Disallow` de su robots.txt (o un robots.txt que no responde) no
  impide pedirla. El script igual lee su robots.txt, respeta su `Crawl-delay` con un mínimo de 5 s entre pedidos y se
  detiene ante una verificación antirobots, que nunca se evade. Así se consultan las capas de puntos críticos de la
  ANA y de establecimientos de salud del SIGRID (`sigrid.cenepred.gob.pe`, cuyo robots.txt prohíbe `/arcgis/`). El
  resto de servidores (HDX, por ejemplo) se respetan como siempre.
- El SINPAD desde 2019 se pide a la consulta pública que usa el portal del INDECI
  (`prod4.indeci.gob.pe/portal-sinpad/api/v1/public/emergencias`, sin robots.txt), mes por mes desde el 01-01-2019
  (la fecha más antigua que ofrece el portal) y en páginas de 100, lo más que ofrece el portal: unas 1 400 páginas con
  5 s entre pedidos, unas dos horas y media. Cada mes terminado queda en la caché y una descarga cortada sigue donde
  quedó, con la misma fecha de corte. Si a un mes le faltan filas respecto del total que anuncia la consulta, se pide
  de nuevo una vez y luego se detiene. El enlace de cada ficha es esa misma consulta filtrada por el código SINPAD
  (los reportes en PDF del portal llevan una clave en la dirección y no se enlazan).
- Cada fuente tiene su SHA-256 en `fuentes.json`. Si cambia, el script se detiene: hay que revisar el cambio y
  repetir con `--aceptar-cambios`, que actualiza el manifiesto. Así un cambio silencioso de una fuente no altera el
  catálogo publicado.
- Las capas de ArcGIS se descargan por bloques de 1 000 elementos (por rango de OBJECTID) y se guardan como JSON
  canónico (claves ordenadas), para que el SHA-256 solo cambie si cambian los datos.
- El servidor del INGEMMET no envía su certificado intermedio; `enso/data/ca-intermedios.pem` lo agrega (Sectigo
  Public Server Authentication CA OV R36) y la verificación TLS sigue completa.
- Las descargas largas (PDF del COEN, El Peruano, repositorios, archivos de prensa, también la búsqueda en cada medio
  con WordPress, término por término) se pueden cortar en cualquier momento y seguir: cada una guarda lo bajado en
  `<archivo>-partes/` dentro de la caché. Cada parte y el archivo final se escriben de una vez (un temporal y
  `os.replace`), y las partes se borran solo después de escribir el archivo final: un corte no deja nada a medias.
  Con `--parcial`, el script arma lo que haya en un `<archivo>.parcial.json`, marca la fuente como `parcial` en
  `fuentes.json` y salta (como `pendiente`) las que aún no tienen nada. `--cache` se puede repetir para buscar en
  varias cachés.
- Los servidores que solo responden desde el Perú (Biblioteca Nacional, BVPAD del INDECI, SPIJ, Contraloría, TV Perú,
  Radio Nacional, repositorios de tesis y otros) están en el registro de fuentes para que el recolector del proyecto
  en el Perú los mida; con lo medido se decide a cuáles escribirles una descarga.
- Prensa: se piden solo las secciones y búsquedas que permite el robots.txt de cada medio (los medios no son
  instituciones públicas y su robots.txt se respeta), a un ritmo de un pedido cada pocos segundos.
- Para agregar una fuente de eventos: un lector en `enso/historico/fuentes.py` que devuelva filas con
  `registro.make`, una entrada en `READERS` o `CONTEXT` de `tools/build_historico.py` y otra en `fuentes.json`. Para
  una fuente que corrobora (COEN, prensa, GLOF), un lector de candidatos en `enso/historico/cosecha.py` y una entrada
  en `CANDIDATES` y `LINK_ORDER`; para una de prevención, en `EVIDENCE`.

## Cosecha en GitHub Actions

Las descargas largas no caben en una corrida de GitHub Actions (6 h como máximo) ni en un contenedor que se reinicia:
los PDF del COEN son unos 20 000 pedidos a 5 s, más de un día. `.github/workflows/memoria-cosecha.yml` corre cada 6
horas `python -m tools.cosecha_historico`, que:

1. Restaura la caché de la corrida anterior (`actions/cache`, clave `memoria-cosecha-…`) en `~/.cache/enso-historico`.
2. Baja lo que falte de cada fuente de `fuentes.json` con `build_historico.fetch`, cada una en un proceso propio, hasta
   un plazo de 300 minutos. Las fuentes de un mismo servidor van una tras otra (la pausa entre pedidos es de cada
   fuente: en paralelo se sumarían); los servidores van en paralelo, primero los de las descargas largas. Al vencer el
   plazo corta los procesos: lo bajado queda en las partes.
3. Anota en `cosecha-estado.json` (en la caché) cuándo empezó la cosecha y, de cada fuente, los intentos, los fallos
   seguidos, el último error y el avance (páginas del listado del COEN, PDF leídos, meses de El Peruano, días de RPP,
   fichas del INGEMMET, términos de cada medio, consultas y fragmentos de Chronicling America). El resumen de la corrida queda en la página de la corrida en
   Actions. Una fuente que falla en tres corridas seguidas (no por el plazo) deja de esperarse: el catálogo se
   construye sin ella y el PR lo dice; se sigue intentando en las corridas siguientes. Las fuentes de eventos y las
   capas de contexto no dejan de esperarse nunca, porque sin ellas el catálogo no se construye.
4. Guarda la caché (siempre, aunque algo falle) y borra las anteriores de la misma rama.
5. Cuando no falta nada, construye el catálogo sin red (`build_historico --sin-red --parcial --aceptar-cambios
   --indices-al-dia`, con el ICEN y el ONI del día), lo
   sube a la rama `bot/memoria-desastres/<inicio>` y abre un PR con lo que cambió en cada fuente y en el total. Un PR
   abierto por Actions no lanza flujos, así que lanza `ci.yml` en esa rama. Si el repositorio no deja que Actions
   abra PR, abre un issue con el enlace para abrirlo. Con el PR anotado (`cosecha-pr.json`), las corridas siguientes
   no bajan nada: solo mantienen viva la caché, que Actions borra tras 7 días sin uso.

A mano (Actions → memoria-cosecha → Run workflow): `solo` (ids de fuentes), `minutos`, `reconstruir` (construye y abre
o actualiza el PR con lo bajado hasta ahora, con lo que falta como «a medias») y `renovar` (vacía la caché y empieza
una cosecha nueva). En una rama `claude/**`, al cambiar la herramienta o el flujo, corre 12 minutos sin PR: muestra qué
servidores responden desde Actions. Los que solo responden desde el Perú fallan ahí y quedan para el recolector del
Perú.

La caché guarda titulares y extractos de prensa de hasta 500 caracteres (el catálogo publica 200) y el texto de los
reportes del COEN y de los decretos. Solo la leen los flujos de este repositorio; no se publica.

## Registros curados y revisiones

**Registros curados** (`data/historico/curado/*.yaml`): para eventos o cifras que no están en las bases, sacados de
informes oficiales, artículos científicos o prensa. Cada registro necesita `Id`, `Date` (AAAA-MM-DD, AAAA-MM o AAAA),
`DangerType` (del vocabulario), el lugar (`Ubigeo` o `Departamento`/`Provincia`/`Distrito`), `Fuente` (https) y
`FuenteCita`; puede llevar `Descripción`, `Ubicacion`, `DuraciónEvento`, `TipoEvento`, `Latitud`/`Longitud`, las
columnas de impacto y `Confianza`. Lo que va en `comun` se aplica a todos los registros del archivo.
`trujillo-1550-1900.yaml` trae la cronología de García-Herrera et al. (2008): un registro por año y lugar, con
confianza media si los autores la evalúan como segura (2) y baja si como posible (1). `eguiguren-piura-1728-1891.yaml`
trae los años de lluvias extraordinarias o grandes crecientes en Piura y Paita del estudio de Eguiguren (1894), con su
cuadro de lluvias de 1791 a 1890, salvo los que la cronología de Trujillo ya tiene para Piura. Un lugar que no
se resuelve o un tipo fuera del vocabulario detienen la construcción.

**Revisiones** (`data/historico/revisiones.yaml`): exclusiones y cifras dudosas, cada una con su motivo y su fuente.
`excluir` quita registros (por `id`, o por `fecha` y `departamento`); `sin-impactos` los deja pero no suma sus cifras y
baja su confianza. Una revisión que no coincide con ningún registro detiene la construcción, para que no queden reglas
muertas.
