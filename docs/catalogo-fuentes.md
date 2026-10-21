# Catálogo de fuentes

El catálogo ejecutable está en `SOURCES` (`python/enso/observatory.py`);
esta tabla lo resume. «Antigüedad máxima» es la edad máxima, en días, del
último periodo observado antes de marcar el dato como vencido.

| ID | Institución | Producto | Archivo | Antigüedad máxima | Crítica |
|---|---|---|---|---|---|
| `enfen-comunicados` | ENFEN | Comunicados oficiales: listado y PDF del más reciente | `enfen.imarpe.gob.pe` (WordPress JSON y página de comunicados); réplica de la DHN `dhn.mil.pe/portal/comunicados-oficiales-enfen` | 30 | — |
| `igp-icen` | ENFEN / IGP | ICEN | `met.igp.gob.pe/datos/ICEN.txt` | 100 | — |
| `cpc-ensodisc` | NOAA / CPC | ENSO Diagnostic Discussion | `ensodisc.shtml` | 40 | Sí |
| `cpc-wksst` | NOAA / CPC | TSM semanal por región Niño (OISST v2.1) | `wksst9120.for` | 16 | Sí |
| `cpc-sstoi` | NOAA / CPC | TSM mensual por región (OISST v2.1) | `sstoi.indices` | 50 | — |
| `psl-ersst6-nino12`, `psl-ersst6-nino34` | NOAA / PSL | TSM mensual Niño 1+2 y 3.4 (ERSSTv6) | `nina1.anom.data`, `nina34.anom.data` | 50 | — |
| `cpc-roni` | NOAA / CPC | RONI (oficial) | `RONI.ascii.txt` | 80 | Sí |
| `cpc-oni` | NOAA / CPC | ONI (referencia) | `oni.ascii.txt` | 80 | — |
| `cpc-soi` | NOAA / CPC | SOI estandarizado | `soi` | 50 | — |
| `cpc-tahiti`, `cpc-darwin` | NOAA / CPC | Presión a nivel del mar (para el SOI Troup) | `tahiti`, `darwin` | 50 | — |
| `cpc-wpac850`, `cpc-cpac850`, `cpc-epac850` | NOAA / CPC | Vientos alisios a 850 hPa | `wpac850`, `cpac850`, `epac850` | 50 | — |
| `cpc-heat` | NOAA / CPC | Contenido de calor 0–300 m (GODAS) | `heat_content_index.txt` | 50 | — |

Una fuente «crítica» sin ningún dato (ni directo, ni de archivo, ni de la
publicación anterior) detiene el despliegue.

## Cómo se obtiene lo más reciente del ENFEN

El ENFEN publica sus comunicados como PDF en un sitio WordPress cuyo
formato ha cambiado varias veces (2018, 2021, 2024). Para no depender de
una sola página:

1. Se lee el listado (WordPress JSON o HTML) y se toma el número más alto.
2. Se sondean los dos números siguientes por su página de descarga
   (`/download/comunicado-oficial-enfen-n-NN-AAAA/`), y en enero el n.º 01
   del año nuevo. Así se detecta un comunicado nuevo aunque el listado
   todavía no lo muestre.
3. Se descarga el PDF y se extrae el tipo de alerta, el número, la fecha
   y la fecha del siguiente comunicado.
4. Si el listado muestra un número más nuevo que el que se pudo leer, el
   estado se marca vencido y se registra la incidencia.

Los servidores del ENFEN no resuelven desde GitHub Actions y tampoco
responden al Internet Archive (HTTP 523 al pedir una copia nueva). Por eso
el listado se lee también de la réplica de la Dirección de Hidrografía y
Navegación (DHN), miembro del ENFEN, que publica cada comunicado como PDF
directo (`/Archivos/oceanografia/enfen/comunicado-oficial/NN-AAAA.pdf`,
formato estable desde 2022). Los sondeos de números nuevos prueban
primero ese PDF. Desde el 20 de octubre de 2026 la DHN responde a los PDF
pedidos desde GitHub Actions con una página de «Verificación de seguridad»;
esa página se descarta (no es un PDF) y el número nuevo queda registrado
como publicado pero no leído, de modo que el estado anterior se muestra
vencido en lugar de vigente. El recolector desde el Perú también descarga
esos PDF. Si una URL del ENFEN no responde, se usa la copia que
bajó el [recolector desde el Perú](servidor-peru.md) a las 21:00; si
tampoco la hay, la copia más reciente del Internet Archive. El listado también reconoce los comunicados
extraordinarios, que el ENFEN emite durante los eventos con numeración
propia.

## Backtesting de formatos

`python/tools/capture_sources.py` (flujo `capture-fixtures`) descarga la
versión actual de cada fuente y versiones históricas del Internet Archive,
y las guarda en `python/tests/fixtures/`. Las pruebas pasan cada lector
por todas esas versiones. El flujo diario además guarda cada respuesta
nueva en la rama `data-archive`, de modo que el corpus crece solo.

## Acceso verificado desde GitHub Actions (20 de octubre de 2026)

| Institución | Resultado | Uso |
|---|---|---|
| NOAA CPC, PSL, NCEI, ERDDAP | Responden | En uso (CPC, PSL); NCEI y ERDDAP disponibles para mapas |
| IGP (`met.igp.gob.pe`) | Responde | En uso (ICEN) |
| DHN (comunicados ENFEN) | El listado responde; los PDF piden verificación humana | Listado en uso; PDF por el recolector del Perú |
| ENFEN (`enfen.imarpe.gob.pe`) | No resuelve el nombre | Réplica DHN e Internet Archive |
| IMARPE | HTTP 403 (bloqueo) | No disponible |
| SENAMHI (avisos, estaciones, boletines) | Tiempo de espera agotado | No disponible desde Actions |
| ANA (caudales, SNIRH) | Tiempo de espera agotado | No disponible desde Actions |
| INDECI, CENEPRED (SIGRID) | Responden | Candidatos |
| CHIRPS (lluvia satelital) | Responde | Candidato |
| NASA GPM IMERG | El índice responde; los datos piden cuenta Earthdata | Requiere credencial |
| CIIFEN, INAMHI, INOCAR, IDEAM | Responden | Candidatos regionales |
| CPPS (ERFEN), SHOA, DMC Chile | URL probada no válida (404/405) | Por revisar |

## Feeds de noticias

Catálogo ejecutable: `FEEDS` en `python/enso/news.py`. Verificado en vivo
desde GitHub Actions el 21 de octubre de 2026 (entradas en el feed /
relevantes sobre El Niño en ese momento). Cada corrida vuelve a comprobar
cada feed y publica el resultado en `news/feeds.json`, salvo los que se leen
una vez al día (ver «Feeds que su robots.txt no permite»): esos repiten el
estado de su última lectura hasta que toque la siguiente.

| Feed | Región | Resultado | Entradas / relevantes |
|---|---|---|---|
| Andina (`andina.pe/agencia/rss/3.xml`) | Perú | Activo | 20 / 0 |
| El Comercio (`elcomercio.pe/arcio/rss/`) | Perú | Activo | 100 / 8 |
| Gestión (`gestion.pe/arcio/rss/`) | Perú | Activo | 100 / 7 |
| Diario Correo (`diariocorreo.pe/arcio/rss/`) | Perú | Activo | 100 / 8 |
| La República (`larepublica.pe/rss/sociedad.xml`) | Perú | Activo | 64 / 10 |
| RPP (`rpp.pe/rss`) | Perú | Activo; algunas fechas llegan adelantadas y se corrigen a la hora de lectura | 60 / 5 |
| Infobae Perú | Perú | Activo | 100 / 4 |
| Caretas | Perú | Activo | 60 / 1 |
| Peru Reports (inglés) | Perú | Activo | 15 / 0 |
| Google Noticias, búsqueda «El Niño», «ENFEN», «Niño costero» (Perú) | Perú | Activo; se lee una vez al día aunque su robots.txt no lo permite (ver abajo) | 100 / 99 |
| Google News, búsqueda «El Niño», «La Niña», «ENSO» (inglés) | Mundo | Activo; una vez al día (ver abajo) | 100 / 96 |
| BBC News Mundo | Mundo | Activo | 34 / 0 |
| Noticias ONU · Cambio climático | Mundo | Activo; una vez al día (ver abajo) | 30 / 5 |
| GDACS (alertas de desastres) | Mundo | Activo; solo cuenta lo que afecta al Perú | 248 / 0 |
| Carbon Brief | Mundo | Activo | 12 / 0 |
| CIIFEN | Mundo | Responde, publica pocas veces al año | 3 / 1 |

Descartados en la verificación:

| Feed | Motivo |
|---|---|
| Perú21 (`peru21.pe/arcio/rss/`) | HTTP 403 a servidores |
| ReliefWeb Perú (RSS) | HTTP 202 con verificación anti-robots; su API pide registro |
| NASA Earth Observatory | El feed no es XML válido |
| ScienceDaily · El Niño | HTTP 404 |
| NOAA Climate.gov · ENSO Blog | Archivado desde el 25 de junio de 2025; la última entrada es del 12 de junio de 2025 |

Las publicaciones de redes sociales que aparecen en Google Noticias
(Facebook, X, Instagram, TikTok, YouTube) se descartan.

### Feeds que su robots.txt no permite

Decisión del 21 de octubre de 2026: 40 feeds de noticias cuyo robots.txt
no permite pedirlos se leen como lo hace un lector de feeds, solo desde
GitHub Actions y como mucho una vez cada 20 horas (`READER_MIN_HOURS` en
`python/enso/registry.py`). Son 38 búsquedas de Google Noticias (las 25 por
departamento, las de El Niño en el Perú y en el mundo, la de peligros en el
Perú y las de medios sin feed propio con `site:`: El Peruano, Radio Nacional,
Panamericana, TV Perú, Esfera Radio, Chachapoyas Online, Radio Titanka,
Diario Chaski, Diario HOY y Tumbes de Miércoles), Noticias ONU · Clima y Sin
Rodeos Cajamarca. La lista sale del registro: `registry.reader_urls()`. La
hora de la última lectura buena de cada uno se guarda también en la caché de
Actions (`--reader-state`), así que una corrida que los leyó y no llegó a
publicar no hace que la siguiente los pida de nuevo antes de tiempo. En el
registro (`registry/sources.json`) su URL queda `robots-disallowed` con
canales `["actions"]` y `"reader": true`; n8n y el recolector del Perú no
los piden. Entre dos lecturas, `news/feeds.json` repite el estado de la
última con `carried: true` (el sitio dice de cuándo es). robots.txt sigue
rigiendo todo lo demás: fuentes oficiales, páginas y el rastreo con
navegador; una fuente que no sea un feed de noticias y que robots.txt
prohíba queda sin canales. Copias de cada robots.txt en
`python/tests/fixtures/scrape-ladder/robots-*.http.txt` y pruebas en
`python/tests/test_channels.py`.

| Sitio | Regla | Feeds |
|---|---|---|
| Google Noticias | `User-agent: *` con `Disallow: /`; solo permite la portada, temas y publicaciones, no `/rss/` | Las 25 búsquedas por departamento y las de El Niño |
| Noticias ONU | `Disallow: */news/` para todos (solo Feedfetcher-Google puede leer sus feeds) | Cambio climático |
| Sin Rodeos (Cajamarca) | `Disallow: /` | Su feed |
| gob.pe | Prohíbe `?sheet=` y `&sheet=` (la paginación de las búsquedas), no los RSS | Sus 30 feeds van sin `sheet` y sí se leen |

Sin ellos, cada departamento tendría igual entre 1 y 6 feeds regionales
(gob.pe del gobierno regional, RPP regional y medios locales). Bing Noticias en RSS
responde y su robots.txt permite `/news/search`, pero el propio feed
limita su uso a «un agregador RSS para su uso personal y no comercial»,
así que no se usa como reemplazo.

## Alertas oficiales de peligros

Además del ENSO, el sitio reúne los avisos y reportes oficiales de los
peligros que causan emergencias en el Perú. Catálogo ejecutable: las
entradas de `FEEDS` con `covers` en `python/enso/news.py`; los lectores
están en `python/enso/hazardparse.py`. Ninguna de estas fuentes tiene un
RSS útil salvo el INDECI y el PTWC, así que se lee lo que publican (HTML,
GeoJSON, consultas ArcGIS o texto) y se homologa al mismo formato de las
noticias: titular en español, resumen, fecha, enlace en vivo y lugares
(distrito, provincia y departamento). Todas responden a una petición
simple desde GitHub Actions (escalera de extracción del 21 de octubre de
2026); ninguna necesita navegador.

| Feed | Peligros | Qué se lee | Notas |
|---|---|---|---|
| `indeci-coen` | Incendios forestales, vientos fuertes, heladas y descenso de temperatura, lluvias intensas, erosión, huaicos, inundaciones, oleaje | RSS de reportes del COEN (`portal.indeci.gob.pe/emergencias/feed/`) | Los titulares en mayúsculas se reescriben («Incendio forestal en el distrito de Curahuasi (Apurímac)»); los eventos de origen humano (incendio urbano, derrame, accidente…) se descartan. Los boletines de aviso meteorológico del SENAMHI que difunde el COEN se publican con su número y vigencia |
| `senamhi-quebradas` | Huaicos (activación de quebradas por lluvias) | Capa 2 del servicio SENAMHI en GEOSINPAD (INDECI), agrupada por nivel y fecha | El servidor del SENAMHI no responde fuera del Perú; el INDECI publica una copia. Cada aviso enlaza a la consulta en vivo en HTML |
| `senamhi-hidrologicos` | Inundaciones y vaciantes (nivel de los ríos) | Capa 4 del mismo servicio: avisos hidrológicos por estación | Un aviso por número, con la estación, el distrito, la provincia y el departamento |
| `senamhi-telegram` | Lluvias, nevadas y granizo, viento, temperatura | Vista pública del canal oficial (`t.me/s/Senamhi_Peru`) | Los mensajes con #Aviso y #Ahora son avisos; las notas de prensa del canal no entran en las alertas |
| `usgs-sismos` | Sismos de magnitud 4 o más | GeoJSON del USGS para el Perú y alrededores | Solo los ubicados en el Perú o frente a su costa; la hora va en UTC−5 |
| `dhn-tsunamis` | Sismos y tsunamis | Boletines de la DHN | Se omiten los simulacros |
| `ptwc-mensajes`, `ptwc-wepa40` | Tsunamis | Atom y texto del Centro de Alerta de Tsunamis del Pacífico | Solo cuentan si el mensaje menciona al Perú; la alerta nacional la emite la DHN |
| `dhn-avisos` | Oleaje anómalo y vientos en el litoral | Listado de avisos especiales de la DHN (`dhn.mil.pe/portal/avisos-especiales`) | Lee los títulos de todos los formatos desde 2020; el titular dice el oleaje más fuerte y en qué tramo del litoral (norte, centro, sur, con sus departamentos), o la velocidad del viento en nudos y entre qué localidades |
| `firms-focos` | Incendios forestales y quemas | CSV de focos de calor de las últimas 24 horas del satélite NOAA-20 (VIIRS) de NASA FIRMS para Sudamérica | Cada foco se ubica por departamento con los límites oficiales del INDECI (`enso.geopoly`); se publica un resumen por corrida («259 focos de calor en el Perú: Huánuco (47), Ucayali (38)…»). Frente a los departamentos que asigna el INPE de Brasil coincide en 399 de 401 focos y no cuenta ninguno de los países vecinos. No se cuentan las detecciones de baja confianza |
| `senamhi-incendios` | Peligro de incendios forestales | Capa 3 del servicio SENAMHI en GEOSINPAD: polígonos del índice FWI (aviso de 24 horas) | Los polígonos no traen lugares: se nombran los departamentos que cubren (de mayor a menor área) |
| `igp-cenvul-boletines`, `igp-cenvul-alertas` | Volcanes | Tarjetas de boletines y alertas del CENVUL (IGP) | Se omiten los volcanes en alerta verde; cada volcán lleva su provincia y departamento |

En el sitio, la pestaña Oficial de Noticias empieza por «Alertas y
reportes de peligros (últimos 7 días)». Cada aviso tiene tres enlaces: la
fuente en vivo, su entrada en la página del archivo del día en que se vio
(`data/archive/news/AAAA-MM-DD.html#id`) y la respuesta original que bajó
esa corrida (`data/archive/feeds/...`).

Evaluadas y pendientes:

| Fuente | Estado |
|---|---|
| Focos de calor del INPE (Brasil) | Trae país y departamento de cada foco, pero el archivo diario pesa de 3 a 8 MB y llega con un día de atraso; se usa como referencia en las pruebas |
| Avisos de lluvia de 24 horas del SENAMHI (capa 5 de GEOSINPAD) | Repite como polígonos lo que la capa 2 ya da por distrito |
| Global Volcanism Program (Smithsonian) | Verificación anti-robots; no se intenta saltarla |
| API del IGP (`api.igp.gob.pe`) | `robots.txt` la excluye |
| SENAMHI (`senamhi.gob.pe`, observatorio), IDESEP, SIG del CENEPRED | Tiempo de espera agotado fuera del Perú; quedan para el recolector del Perú |
| Normas legales de El Peruano (declaratorias de emergencia) | Su API exige fechas y páginas; candidata para un flujo de n8n |

## Fuentes evaluadas y no usadas

| Producto | Motivo |
|---|---|
| D20 de GODAS (`dbss_obil`) | Es la profundidad de la capa isotérmica, no la isoterma de 20 °C |
| ERSSTv5 (`ersst5.nino.mth.91-20.ascii`) | NOAA dejó de actualizarlo en junio de 2026; se conserva solo en las pruebas |
| ERSSTv6 Niño 1+2 en el CPC | El CPC solo publica Niño 3.4 en v6; Niño 1+2 se toma de PSL |
| Estado de alerta en la portada del ENFEN | Se toma del comunicado, que es el documento oficial |
| BoM SOI | Se usa solo para validar el SOI Troup calculado |
