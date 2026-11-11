# Mapa de alertas (Noticias)

Arriba de las noticias, un mapa del Perú por departamento muestra dónde hay avisos oficiales **vigentes
ahora**, cuáles **se esperan** y dónde hubo **reportes de daños** en los últimos 7 días. Pasar el cursor
(o enfocar con el teclado) muestra los avisos del departamento; hacer clic filtra la lista de avisos y
las noticias de ese departamento. Los filtros de **momento** (vigentes, próximas, reportes y pasadas),
**nivel** y **antigüedad** se aplican al mapa y a la lista, y quedan en la URL
(`#/noticias?dep=20&fase=ahora&nivel=3&edad=24`).

## De dónde sale el nivel

El nivel es siempre **el que publica la institución**; el observatorio no asigna niveles
(`python/enso/severity.py`). Un aviso sin nivel en su fuente se muestra «Sin nivel».

| Fuente | Escala | Campo |
|---|---|---|
| SENAMHI, activación de quebradas (GEOSINPAD) | Nivel 1 a 4 (verde, amarillo, naranja, rojo) | `NIVEL` de la capa |
| SENAMHI, avisos de precipitaciones para 24 horas (GEOSINPAD) | Nivel 2 a 4 (amarillo, naranja, rojo) | `NIVEL` de la capa `SENAMHI_AvisoPP24H` |
| SENAMHI, avisos hidrológicos (GEOSINPAD) | Umbral amarillo, naranja o rojo de la estación | `COLOR_TEXT` |
| SENAMHI, avisos meteorológicos (Telegram y COEN) | Amarillo, naranja o rojo | columna «Nivel» de la tabla de avisos del SENAMHI (ver abajo) |
| IGP, CENVUL | Alerta volcánica verde, amarilla, naranja o roja | nivel del boletín |
| USGS | Alerta PAGER verde, amarilla, naranja o roja (impacto estimado) | solo si USGS la calculó; la magnitud no es un nivel |
| DHN, boletines de sismo y tsunami | No genera tsunami · alerta · alarma | texto del boletín |
| PTWC | Sin amenaza · amenaza de tsunami | texto del mensaje |
| SENAMHI (Telegram) e INDECI (COEN), sin aviso en la tabla | Color del aviso, solo si el texto lo cita | texto |

Para colorear se usa un orden común (`rank`): 1 el nivel más bajo de aviso (amarillo), 2 intermedio
(naranja), 3 el más alto (rojo). La etiqueta que se ve es la de la institución.

**Vigencia** (`valid`): la que declara el aviso («del 22 al 24 de octubre», «VIGENCIA: 21-10-2026 (13:00 h)
al 22-10-2026 (13:00 h)», «próximas 24 horas»). El navegador compara la hora actual con esa vigencia para
decir si un aviso es próximo, está vigente o venció. Los estados actuales sin fin declarado (un río, un
volcán, «en este momento») se consideran en curso por unas horas (`CURRENT_HOURS`) y luego recientes; no
es una vigencia de la fuente y el sitio lo dibuja distinto.

**Lugar**: los publicados por la georreferenciación (confianza ≥ 0,5). Los aproximados (< 0,8, sin revisar
en la consola) se marcan «≈»; los revisados en la consola, «lugar revisado».

## Formas y puntos (más fino que el departamento)

Encima de los departamentos, la capa «Formas y puntos» (encendida al abrir) dibuja lo que cada aviso dice con más
precisión. Viene en `detail` de cada alerta de `feed.json` (`sourcefeed._detail`):

| Qué | De dónde | Cómo se dibuja |
|---|---|---|
| **Zona del aviso** (`shapes`) | Polígonos de las capas del SENAMHI en GEOSINPAD: precipitaciones de 24 horas y peligro de incendios forestales (FWI), simplificados a unos 2 km | Con el color de su nivel, solo si el aviso está vigente o es próximo |
| **Distritos con quebradas** (`areas`) | La capa de activación de quebradas trae cada quebrada (unas decenas de hectáreas); la consulta las cuenta por nivel, fecha y distrito | El trazo del distrito con el color del nivel. Un distrito en avisos de varios niveles se dibuja una vez, con el más alto, y su cuadro dice cuántas quebradas trae cada aviso |
| **Estación hidrológica** (`points`, rombo) | `LATITUD` y `LONGITUD` de la estación en la capa de avisos hidrológicos, con su río y la cuenca que le asigna el SENAMHI | En todas las fases |
| **Epicentro** (círculo) | El punto de USGS, con su magnitud, su profundidad y la incertidumbre (5 km si lo revisó un sismólogo, si no 10 km) | |
| **Volcán** (triángulo) | La cumbre según el Global Volcanism Program del Smithsonian (`hazardparse.VOLCANO_POINTS`), con su enlace | |
| **Focos de calor** (punto chico) | FIRMS agrupado en celdas de 0,1° (unos 11 km); el tamaño crece con los focos | |
| **Centro poblado** (anillo) | Los que nombra el reporte del COEN o su PDF, buscados solo dentro del distrito del reporte (`lugares.localities`, `documentos.table_localities`); un nombre repetido en el distrito no se elige | |
| **Río, quebrada o laguna** (círculo con borde punteado) | El que nombra el reporte («activación de la quebrada Pedregal»), con la palabra que dice qué es, buscado solo dentro del distrito del reporte en la Carta Nacional del IGN (`aguas.waters`) cuando no nombra un centro poblado. Solo si su tramo en el distrito es corto (10 km o menos y menos de tres cuartos del radio del distrito): un río que cruza el distrito no dice dónde fue | El círculo punteado es su tramo (el radio) |
| **Provincia expuesta** (trazo de la provincia) | Las provincias que el COEN lista como expuestas en su boletín de avisos de corto plazo (`documentos`, `sourcefeed._detail`) | Con el color del nivel, debajo de los distritos |

Las formas van del nivel más bajo al más alto (el rojo queda arriba) y debajo del anillo del departamento elegido.
Pasar el cursor por una forma o un punto muestra qué es, el aviso y, si se sabe, el río, la cuenca y la
incertidumbre. En la lista de alertas, cada aviso con un centro poblado, un río o una cuenca lo dice con una etiqueta
(`alertmap.fineTags`). La capa «Cuencas (ANA)» (apagada al abrir) dibuja las 231 cuencas e intercuencas de la ANA
(`public/assets/cuencas-mapa.json`, `python -m tools.build_cuencas_mapa`). Para no pesar, `feed.json` lleva hasta
400 puntos y 600 distritos por aviso.

## Limitaciones conocidas

- Los avisos meteorológicos del SENAMHI llegan por su canal de Telegram y por el COEN sin nivel. El nivel
  sale de la tabla de `?p=aviso-meteorologico` (`enso/senamhi_avisos.py`): el mensaje de Telegram cita el
  número interno del aviso («aviso meteorológico 29296», el `b=` de la tabla) y el COEN su «N°» del año. Esa
  página solo responde desde el Perú: el recolector la guarda cada noche y el pipeline la lee de `data-peru`.
  Un aviso emitido después de la última copia queda «Sin nivel» hasta la noche siguiente. Si el texto no da
  fechas, la vigencia es el inicio y el fin de la tabla (días completos en Lima) y `valid.source` vale
  `"tabla"`. Un aviso que la tabla marca «(AVISO CANCELADO)» lleva `aviso.cancelled: true`.
  Cada nivel que sale de la tabla enlaza el aviso en el SENAMHI (`severity.basisUrl`) y la copia de la tabla
  que publica el sitio (`severity.basisArchive`, en `data/archive/sources/senamhi-avisos/`), porque esa
  página no abre fuera del Perú. El grupo de alertas de `feed.json` dice de qué copia salen los niveles
  (`levelsFrom`: `copyAt`, `archive`, cuántos avisos trae) y el pie del mapa lo muestra; si la copia tiene
  más de 36 horas, el pie lo advierte y el pipeline anota `senamhi-avisos-stale`. Sin tabla legible anota
  `senamhi-avisos-unread`.
- Los avisos meteorológicos traen regiones («costa norte y sierra»), no departamentos. Los departamentos están
  en el **PDF** que el COEN enlaza en la página de cada boletín (ver «Del aviso al documento»). El mensaje de
  Telegram del mismo aviso (mismo año y número, por la tabla del SENAMHI) toma esos departamentos
  (`geo.via` dice de qué boletín salen). Si ningún canal trae el PDF, se usan los departamentos de las regiones
  que nombra el aviso (`senamhi_avisos.REGIONS`), con confianza 0,6: el mapa los marca «≈» y la ficha dice
  «lugares: regiones que nombra el aviso». Un aviso sin región reconocible sigue en «avisos sin departamento».
  La capa de precipitaciones de 24 horas de GEOSINPAD (`senamhi-lluvias`) trae polígonos y colorea los
  departamentos con su nivel desde la nube, sin depender del recolector.
- Un aviso en unos distritos colorea todo el departamento en las versiones A, C y D (el color dice «en
  algún lugar del departamento»). La versión B dibuja cada lugar.
- El mapa es tan reciente como la última actualización diaria; el pie lo dice.

## Del aviso al documento (`python/enso/documentos.py`)

La página de cada publicación del COEN es una portada con un botón «Descargar archivo»; el detalle está en el
PDF. Cada corrida baja la página y el PDF de las publicaciones de los últimos 7 días que aún no leyó (como
mucho 40 por corrida y 3 minutos; los avisos primero, luego los reportes sin distrito; 3 intentos por
publicación) y lee:

| Publicación | Qué se lee del PDF | Lugar que publica |
|---|---|---|
| Aviso meteorológico | «… DEPARTAMENTOS EXPUESTOS: AMAZONAS, ÁNCASH, … Y TUMBES» (o «de posible afectación», con «Prov. Const. del Callao» en cualquiera de sus formas), el tema, la vigencia y el párrafo del aviso | Departamentos |
| Aviso hidrológico | «…en el departamento de LORETO (Prov. Mariscal Ramón Castilla)» y la fila de la estación («Amazonas Puerto Alegría Yavari 59.54 58.78») | Distrito de la estación (si no se lee, la provincia) |
| Aviso de corto plazo (lluvias intensas, activación de quebradas) | Tabla «DEPARTAMENTOS · PROVINCIAS EXPUESTAS» y «VIGENCIA: 25-10-2026 (13:00 h) al 26-10-2026 (13:00 h)» | Provincias (por departamento si son más de 25) |
| Aviso de oleaje | Tramos del litoral (norte, centro, sur) | Departamentos costeros de esos tramos |
| Reporte de emergencia | Tabla «UBICACIÓN» (departamento, provincia, distrito); si la tabla es una imagen, la descripción («…distrito Challhuahuacho, provincia de Cotabambas.») | Distritos |

En los boletines de corto plazo, pypdf corta la celda de cada departamento en líneas, a veces en medio de un
nombre («Carlos / Fermin Fitzcarrald», «San / Pablo», «Santiago de / Chuco»): se une la celda antes de separar
por comas («*Callao» en la fila de Lima es la Provincia Constitucional). Antes se perdían de 1 a 3 provincias por
boletín.

En los reportes, pypdf pega y parte las celdas de la tabla («LOCUMBAJORGE BASADRETACNA», «PAMPASAN LUISCARLOS», «PASCO OX
APAMPA»): los nombres de 4 letras o más se buscan también en el texto sin espacios, pero no dentro de otro nombre
del gazetteer que también aparece («TOMAS» no es Omas, «CHONGOS» no es Hongos, «ALTO PICHIGUA» no es Pichigua).
Se aceptan los alias del COEN (Kimbiri, Seclla, Mariscal Gamarra, San Juan de Iscos). Un departamento sin
provincia ni distrito cuando otro sí los tiene es un centro poblado de ese nombre («… ANDAMARCA HUÁNUCO»).

Si el PDF no es de la publicación (la página del COEN a veces enlaza el de otra: «…Ccapi (Cusco)» con el reporte
de Huancabamba, Piura; un boletín de corto plazo con un reporte de emergencia), no se usa: queda como
`no-coincide` en `news/documentos.json`, se reintenta hasta 3 veces por si el COEN corrige la página, y la
publicación conserva el lugar de su titular. Lima y Callao cuentan como uno al comparar.

Lo leído entra como lugares de campo (confianza 0,95) en `geoHint.geo` y reemplaza la ubicación por el
titular; el aviso enlaza el PDF (`document`, «informe completo (PDF)») y el mapa lo abre en lugar de la portada.
Se publica en `news/documentos.json` (21 días) y la corrida siguiente no lo vuelve a pedir; como el histórico
es de solo anexar, se aplica en memoria a cada publicación, también a las que ya estaban guardadas.

Como el RSS del COEN trae solo sus últimas ~14 publicaciones (unas horas de reportes), sus boletines se leen
además de la búsqueda de WordPress (`indeci-coen-boletines`, `…/emergencias/feed/?s=boletin+informativo`). Los
boletines sísmicos y el resumen diario de peligros no son avisos y se omiten.

**Prueba hacia atrás**: `python -m tools.documentos_backtest --items news/items.jsonl --out /tmp/bt --feed
'https://portal.indeci.gob.pe/emergencias/feed/?s=reporte&paged=5'` compara los lugares del PDF con el
titular de cada reporte (falsos positivos y negativos) y la aproximación por regiones con los departamentos
de cada aviso. Resultados (272 publicaciones de agosto a octubre de 2026): `docs/documentos-backtest.md`.

## Vistas de detalle: por cuenca y distritos con su historia

Arriba del mapa, junto al título, un selector cambia lo que dibuja el mismo mapa (no agrega tableros debajo):
**Resumen** (la versión A–D de abajo) o uno de dos **detalles**. El estado queda en la dirección
(`#/noticias?vista=cuencas`).

- **Por cuenca**: las 231 unidades hidrográficas de la ANA (`assets/cuencas-mapa.json`), coloreadas con el nivel más
  alto de los avisos que las tocan; rayado si ese nivel es solo de un aviso próximo. Un aviso toca una cuenca por
  sus distritos (el distrito de una cuenca es el que tiene el 80 % o más de su superficie en ella, como en la memoria
  de desastres) o por el centro poblado o el río que nombra. Al lado, las cuencas con avisos vigentes o próximos,
  primero el nivel más alto y, entre iguales, la que más daños tuvo antes; cada una abre su ficha con sus avisos y su
  memoria («1 351 registros, 56 temporadas con registros desde 1970…») y un enlace a su vista en la memoria de
  desastres (`#/memoria?vista=cuencas&cuenca=…`).
- **Distritos y su historia**: los distritos en aviso, rellenos con la parte de los años de DesInventar (1970-2015)
  con daños en cada uno (la misma escala que la memoria) y con el borde del nivel de sus avisos. Un aviso toca un
  distrito si lo nombra, si nombra su provincia (o la expone un aviso de corto plazo), si tiene quebradas en aviso,
  si nombra un centro poblado o un río del distrito, o, para un aviso vigente o próximo del SENAMHI con zona, si el
  centro del distrito cae dentro de ella. La ficha dice por cuál de esas razones está y enlaza su ficha en la memoria.

Un aviso que solo nombra departamentos no entra en los detalles (el panel dice cuántos hay: siguen en el resumen).
La memoria es lo que pasó antes, no un pronóstico; el panel lo dice. Los datos de la memoria vienen de
`assets/historico/historia.json` (una fila por distrito, provincia y cuenca, de `python -m tools.build_historico`) y
se piden solo al abrir un detalle. Funciones: `alertDistricts`, `alertUnits` y `detailView` en
`public/assets/js/alertmap.js`.

## Versiones A, B, C y D

| Versión | Qué muestra |
|---|---|
| A · Semáforo por departamento | Departamentos coloreados por el nivel más alto; número de avisos activos |
| B · Pulsos por lugar | Un círculo por distrito, provincia o departamento con avisos; late solo un aviso rojo vigente |
| C · Panel | Mapa, matriz nivel × momento (cada celda filtra) y ranking de departamentos |
| D · Cronología | Mapa y línea de tiempo de la vigencia de cada aviso, de ayer a cuatro días adelante |

La versión (y la vista: resumen o detalle) de una primera visita se sortea: al azar mientras no haya una ganadora y,
cuando la hay, la ganadora para 4 de cada 5 personas y otra al azar para el resto, para seguir midiendo. Quien elige
otra en «Versión del mapa» o en el selector de vistas la deja como predeterminada en su navegador.
`#/noticias?version=B` y `#/noticias?vista=distritos` muestran una versión o una vista sin cambiar la elegida.

### Analítica anónima y decisión

Hay tres experimentos, cada uno con su clave en el navegador (`public/assets/js/ab.js`):

| Experimento | Qué se sortea | Versiones |
|---|---|---|
| `mapa` | La versión del mapa de alertas en el resumen | A, B, C, D |
| `noticias` | La vista con que abre el mapa de Noticias | resumen, cuencas, distritos |
| `memoria` | La vista con que abre el mapa de la memoria de desastres | resumen, cuencas, puntos, riesgo |

`functions/_lib/ab.js` (ruta `/api/ab/*`) suma contadores por **día, experimento, versión y evento** en la tabla
`ab_exp` de la base D1 `GEO_DB` (la de la consola; la tabla `ab_daily` de antes, solo del mapa A–D, se sigue leyendo).
No guarda IP, identificadores ni cookies. Cada visita manda, al salir, un aviso por experimento con lo que hizo:
`view`, `chosen` (la vio siendo su versión elegida), `hover`, `select` (filtró o eligió un área desde el mapa),
`detail` (abrió un aviso, una ficha o un registro), `use` (hizo `select` o `detail`), `choose`, `leave` y `keep`
(volvió otro día con la versión elegida). Con «No rastrear» o Global Privacy Control no se manda nada. Hay un tope
de 20 000 sumas por día para no gastar las escrituras de la consola.

**Decisión** (`decide`): la tasa de uso de cada versión (visitas con `use` sobre visitas con `view`, en los últimos
60 días) con su intervalo de Wilson al 95 %. Gana una versión solo si todas tienen al menos 200 visitas medidas y el
límite inferior de su intervalo supera el límite superior de todas las demás; así una diferencia que puede ser azar no
cambia lo que ve la gente. `GET /api/ab/defaults` devuelve la ganadora de cada experimento (o `null`) y se guarda una
hora en el borde; el navegador la pide una vez al día y nunca espera más de 1,2 s antes de dibujar el mapa. Las
visitas del mapa A–D anteriores a este cambio no traen `use`: cuentan en los totales, no en la decisión.

Resultados: `https://<sitio>/#/variantes` (no está en el menú: los tres experimentos con su tasa de uso, su intervalo
y la decisión) o `GET /api/ab/stats?days=30`.

## Mantenimiento

- `public/assets/peru-map.json` se regenera con `python -m tools.build_peru_map` (límites del INDECI,
  GEOSINPAD). Tiene un punto por cada provincia y cada distrito del nomenclátor; si un aviso nombra un código
  sin punto, la versión B lo dibuja en su provincia o su departamento, nunca lo omite.
- Pruebas: `tests/test_severity.py`, `tests/test_alert_map.py` (incluye la API, la decisión y las vistas de
  detalle con `node --test`) y, en los recorridos de navegador, `test_alert_map_filters_the_news_and_remembers_the_version`,
  `test_news_detail_views_show_alerts_by_basin_and_district_with_their_history` y
  `test_a_shared_link_shows_its_view_without_changing_the_chosen_one`.
