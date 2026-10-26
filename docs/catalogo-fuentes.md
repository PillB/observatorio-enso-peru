# Catálogo de fuentes

El catálogo ejecutable está en `SOURCES` (`python/enso/observatory.py`);
esta tabla lo resume. «Antigüedad máxima» es la edad máxima, en días, del
último periodo observado antes de marcar el dato como vencido.

| ID | Institución | Producto | Archivo | Antigüedad máxima | Crítica |
|---|---|---|---|---|---|
| `enfen-comunicados` | ENFEN | Comunicados oficiales: listado y PDF del más reciente | `enfen.imarpe.gob.pe` (WordPress JSON y página de comunicados); réplica de la DHN `dhn.mil.pe/portal/comunicados-oficiales-enfen`; repositorio del IMARPE `repositorio.imarpe.gob.pe` (ver abajo) | 30 | — |
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
| `cpc-godas-d20` | NOAA / CPC | D20 en Niño 1+2, Niño 3.4 y 180°–100°O, calculado de GODAS (ver Metodología §7b) | `godas/monthly/godas.M.AAAAMM.grb` (rango de bytes) | 50 | — |

Una fuente «crítica» sin ningún dato (ni directo, ni de archivo, ni de la
publicación anterior) detiene el despliegue.

## Cómo se obtiene lo más reciente del ENFEN

El ENFEN publica sus comunicados como PDF en un sitio WordPress cuyo
formato ha cambiado varias veces (2018, 2021, 2024). Para no depender de
una sola página:

1. Se lee el listado (WordPress JSON o HTML) y se toma el número más alto.
   La API de WordPress se quedó en el N° 13-2026: su entrada es solo un
   candidato y se contrasta con el listado del portal o de la réplica de la
   DHN y con el del repositorio del IMARPE.
2. Se sondean hasta 6 números siguientes (`PROBE_AHEAD`); dos ausencias
   seguidas cortan (`PROBE_MAX_MISSES`). En enero se sondea también el
   n.º 01 del año nuevo. Cada número se busca primero como PDF en la
   réplica de la DHN y luego por su página de descarga del portal
   (`/download/comunicado-oficial-enfen-n-NN-AAAA/`). Así se detecta un
   comunicado nuevo aunque el listado todavía no lo muestre. Para esas
   páginas se usa la copia existente del Internet Archive, sin pedirle una
   nueva: el ENFEN no le responde.
3. Se descarga el PDF (ver abajo) y se extrae el tipo de alerta, el
   número, la fecha, la fecha del siguiente comunicado y la perspectiva
   por región.
4. Si el listado muestra un número más nuevo que el que se pudo leer, el
   estado se marca vencido y se registra la incidencia.

Los servidores del ENFEN no resuelven fuera del Perú (ni desde GitHub
Actions ni desde n8n) y tampoco responden al Internet Archive (HTTP 523 al
pedir una copia nueva); el [recolector desde el Perú](servidor-peru.md) sí
los alcanza y baja el listado y los PDF. Por eso el listado se lee también
de la réplica de la Dirección de Hidrografía y Navegación (DHN), miembro
del ENFEN, que responde a Actions y a n8n. La DHN publica cada comunicado
como PDF directo (`/Archivos/oceanografia/enfen/comunicado-oficial/NN-AAAA.pdf`,
formato estable desde 2022), pero desde el 20 de octubre de 2026 responde a
esos PDF con una página de verificación humana a los servidores, también a
n8n y al recolector del Perú. Esa página se registra y se descarta (no es
un PDF): nunca se intenta pasar la verificación.

El repositorio institucional del IMARPE (`repositorio.imarpe.gob.pe`,
DSpace; cliente único en `python/enso/feeds/imarpe_repo.py`) recibe cada
comunicado y cada informe técnico unos 3 días después de publicados, y su
API (`/server/api`) responde a GitHub Actions: es la ruta oficial sin
verificación. Su listado se suma al del portal y de la DHN.

El PDF del comunicado se busca en este orden (`_get_communique` en
`python/enso/observatory.py`):

1. Cada URL conocida del PDF (la del listado del portal y el PDF de la
   DHN): primero directo y, si no da un PDF, la copia más reciente que
   tengan el recolector del Perú (rama `data-peru`, hasta 7 días), n8n
   (`data-n8n`, hasta 72 h) o la [consola de documentos](documentos-manuales.md)
   (`data-manual`, hasta 120 días). Una URL que el registro no asigna a
   Actions se lee primero de esas copias.
2. La copia del Internet Archive de esas mismas URL (y una nueva con Save
   Page Now si la existente tiene más de un día).
3. El repositorio del IMARPE.
4. Cualquier copia en PDF que el Internet Archive tenga de la página de
   descarga del portal.

Solo vale un cuerpo que empiece con `%PDF-` y que sea el comunicado
buscado. Si ninguna ruta lo da, el número nuevo queda registrado como
publicado pero no leído, el estado anterior se muestra vencido en lugar de
vigente y el comunicado queda pendiente en la consola de documentos para
que una persona lo baje en su navegador y lo suba. La tarjeta del estado
muestra el canal del listado y enlaza la copia archivada del PDF leído; el
canal del PDF queda en `data.latest.channel` de
`data/sources/enfen-comunicados.json`. El informe técnico que cita el comunicado (ICEN
temporal y probabilidades) sigue el mismo orden ([informes-texto.md](informes-texto.md)).
El listado también reconoce los comunicados extraordinarios, que el ENFEN
emite durante los eventos con numeración propia.

## Boletín semanal del IMARPE (columna de agua frente a Paita y Chicama)

El IMARPE deposita cada domingo su Boletín Semanal Oceanográfico y
Biológico-Pesquero (BS-OBP) en su repositorio institucional
(`repositorio.imarpe.gob.pe`, API REST de DSpace, que responde a GitHub
Actions; SIOFEN, en cambio, está detrás de una verificación de
Cloudflare). La corrida diaria busca los boletines nuevos con el cliente
único `enso.feeds.imarpe_repo`, baja hasta dos por corrida y los lee con
`enso.feeds.imarpe_bsobp`; publica `imarpe-bsobp.json` con el último año.

El boletín no trae una serie numérica: el resumen de la primera página
dice, en texto, la anomalía térmica subsuperficial frente a la costa norte
y con qué la midió (puntos fijos a 7 mn de Paita y 15 mn de Chicama,
secciones del monitoreo bio-oceanográfico, perfiladores Argo). Se toma,
por lugar, la anomalía más intensa que la frase le atribuye sin
ambigüedad, con su capa, la plataforma, la cita y la página; los valores
de otros lugares (Punta La Negra, Chimbote) o de un tramo («desde Chicama
a Huarmey») no se atribuyen. La profundidad de la isoterma de 15 °C (la
termoclina costera del IMARPE y el ENFEN) se publica solo cuando el texto
la da para Paita o Chicama. En los 44 boletines de diciembre de 2025 a
octubre de 2026, 12 traen un valor para Paita o Chicama y 1 la isoterma
de 15 °C; las demás semanas no muestrearon allí, lo que no es un error.
No se le aplican los umbrales del D20.

Si un boletín listado no se puede leer, o pasan 12 días sin uno nuevo,
la corrida abre un issue (`bsobp-unreadable`, `bsobp-overdue`) y el
boletín queda en la consola de documentos para subirlo a mano: nadie
tiene que revisar el repositorio cada día.

## Backtesting de formatos

`python/tools/capture_sources.py` (flujo `capture-fixtures`) descarga la
versión actual de cada fuente y versiones históricas del Internet Archive,
y las guarda en `python/tests/fixtures/`. Las pruebas pasan cada lector
por todas esas versiones. El flujo diario además guarda cada respuesta
nueva en la rama `data-archive`, de modo que el corpus crece solo.

## Acceso verificado desde GitHub Actions y n8n (20 y 21 de octubre de 2026)

Las mediciones de cada URL por red están en `registry/reachability.json` y
el canal que decide quién la pide, en `registry/sources.json`.

| Institución | Resultado | Uso |
|---|---|---|
| NOAA CPC, PSL, NCEI, ERDDAP | Responden | En uso (CPC, PSL); NCEI y ERDDAP disponibles para mapas |
| IGP (`met.igp.gob.pe`) | Responde | En uso (ICEN) |
| DHN (comunicados ENFEN) | El listado responde (también a n8n); los PDF piden verificación humana a los servidores, también a n8n y al recolector del Perú | Listado en uso; PDF del repositorio del IMARPE, la consola de documentos o el Internet Archive |
| ENFEN (`enfen.imarpe.gob.pe`) | No resuelve el nombre (tampoco desde n8n) | Copia del recolector del Perú; réplica DHN, repositorio del IMARPE e Internet Archive |
| IMARPE, repositorio (`repositorio.imarpe.gob.pe`) | Responde (API DSpace; el intermedio de su certificado va en `enso/data/ca-intermedios.pem`) | En uso: comunicados e informes técnicos del ENFEN y boletín semanal BS-OBP |
| IMARPE, sitio web (`www.imarpe.gob.pe`) | El feed responde; la portada y la página de sección dan HTTP 403 con verificación anti-robots (se registra, no se evade). Desde n8n responden las tres | Feed en las noticias; las dos páginas las bajan n8n y el recolector del Perú como archivo, sin lector todavía |
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
Rodeos Cajamarca. La lista sale del registro: `registry.reader_urls()`. Solo
los piden las corridas de `observatory.yml` en `main` (con `--reader-state`);
las demás (otra rama, la prueba de `capture-fixtures.yml`, una corrida
local sin `--reader-state`) los omiten. En `main` cuentan todas: la
diaria, la que pide el vigilante, la del recolector o n8n, la que se lanza
al fusionar y la manual. El plazo cuenta desde el último pedido, haya respondido o
no (un 429 o un 5xx no se reintentan hasta el día siguiente), con un margen
de 30 minutos porque la hora anotada es la de inicio de la corrida y el
paso del pipeline no dura más de 26. Cada
uno se pide una sola vez por corrida, sin reintento, y dos 429 seguidos de
Google detienen los demás pedidos a Google en esa corrida. La hora del
último pedido de cada uno se guarda también en la caché de Actions, y se
anota antes de hacerlo: una corrida que los pidió y no llegó a publicar
(o que se cortó a mitad de la recolección) no hace que la siguiente los
pida de nuevo antes de tiempo. Ese estado guarda también sus notas que
ninguna publicación tiene todavía, en cuanto termina cada lectura y hasta
14 días (`READER_KEEP_DAYS`): no se pierden aunque varias corridas
seguidas no publiquen y el feed ya no las traiga. Si no hay estado (la
caché no se pudo leer), la publicación anterior no basta: el sitio puede no
responder, y aunque responda, una corrida que no llegó a publicar pudo
haberlos pedido. Esa corrida no pide los que la publicación no muestra
pedidos hace menos de 20 horas (`feeds-reader-unknown`) y cuenta como su
pedido, en el estado y en la publicación, así que se vuelven a pedir 20
horas después de ella. En la primera publicación (sin `news/feeds.json`)
sí se piden. El sondeo de candidatos (`probe-feeds.yml`) no los pide:
respeta robots.txt como la captura de fuentes. En el
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
| `senamhi-lluvias` | Lluvias | Capa 5 del servicio SENAMHI en GEOSINPAD (`SENAMHI_AvisoPP24H`): polígonos del aviso de precipitaciones para 24 horas, con su nivel | Un aviso por nivel (2, 3 o 4; el nivel 1, verde, no es un aviso). Cada polígono cubre a veces media sierra: su área se reparte entre departamentos con una grilla (`polygon_departments(sample=True)`). Responde desde EE. UU.: es el camino de nube para el nivel de los avisos de lluvia |
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
| D20 de las boyas TAO/TRITON (PMEL, ERDDAP `pmelTaoDyIso`) | Mide D20 diario, pero solo en puntos del ecuador (no hay boyas al este de 95°O, así que nada en Niño 1+2), sin anomalía publicada y con 3 a 4 semanas de retraso en ERDDAP. Se usa para validar el cálculo con GODAS |
| `GODAS_pentad_EQ_anom_AAAA.nc` (CPC) | Anomalía de temperatura por pentada en 5°N–5°S; no trae la temperatura total, así que no da D20 sin otra climatología, y no cubre 10°S |
| Mapas de D20 de CPC (`pent.anom.xy.d20.30d.gif`) y del IRI | Solo imágenes: no se leen valores de píxeles |
| Copernicus Marine (GLORYS12, análisis global) | Exige cuenta y credenciales; GLORYS llega con meses de retraso |
| Argo en grilla (Roemmich–Gilson, IPRC) | Mensual con 1 a 2 meses de retraso y casi sin datos sobre la plataforma peruana |
| Informe técnico ENFEN, secciones de IMARPE, IGP | Describen la termoclina costera con la isoterma de 15 °C, en texto y figuras y sin serie numérica por región |
| ERSSTv5 (`ersst5.nino.mth.91-20.ascii`) | NOAA dejó de actualizarlo en junio de 2026; se conserva solo en las pruebas |
| ERSSTv6 Niño 1+2 en el CPC | El CPC solo publica Niño 3.4 en v6; Niño 1+2 se toma de PSL |
| Estado de alerta en la portada del ENFEN | Se toma del comunicado, que es el documento oficial |
| BoM SOI | Se usa solo para validar el SOI Troup calculado |
