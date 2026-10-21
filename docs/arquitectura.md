# Arquitectura y contrato de datos

## Vista general

![Arquitectura: fuentes, canales, pipeline, publicación, sitio y operación](arquitectura.svg)

El diagrama (`docs/arquitectura.svg`, copiado en `public/assets/` para la
sección Metodología del sitio) se lee de izquierda a derecha:

1. **Fuentes:** oficiales del ENSO (ENFEN, IGP), NOAA (CPC y PSL), alertas
   de peligros (INDECI, SENAMHI, DHN, IGP, USGS, PTWC, NASA FIRMS), feeds de
   noticias nacionales y regionales, y el registro de fuentes
   (`registry/sources.json`) con el alcance de cada una por red.
2. **Canales**, del más simple al más complejo: directo desde GitHub
   Actions (escalera `robots.txt` → petición simple → cabeceras de
   navegador → Chromium → Firecrawl, que se detiene ante cualquier
   verificación anti-robots), n8n en la nube (rama `data-n8n`, para fuentes
   no geobloqueadas que fallan desde Actions), el recolector en el Perú
   (rama `data-peru`, solo para fuentes geobloqueadas), el Internet Archive
   y la publicación anterior.
3. **Pipeline** en Python: descarga con procedencia, lectores con
   backtesting, lectores de alertas sin RSS (`hazardparse.py`), ubicación
   por distrito, provincia y departamento, validación y armado, señal GRD,
   noticias y feed de fuentes.
4. **Publicación** atómica en `public/data/`, con una copia archivada de
   cada noticia y alerta (`data/archive/news/<día>.html#<id>`) y la
   respuesta original de cada fuente (`data/archive/feeds/`), más la rama
   `data-archive`.
5. **Sitio** estático en Cloudflare Pages (sin enlace al repositorio) o
   GitHub Pages. Cada ítem enlaza a la fuente en vivo, a su copia archivada
   y a la respuesta original bajada.
6. **Operación** en GitHub Actions: actualización diaria, vigilante,
   integración continua, sondeos de fuentes e incidencias como issues.

No hay servidor ni base de datos. Una corrida de GitHub Actions genera la
publicación y el hosting la sirve junto con el sitio. Si algo falla antes
del despliegue, sigue publicado el sitio anterior.

## Pipeline (`python/enso/`)

| Módulo | Función |
|---|---|
| `fetch.py` | Descarga con reintentos, límites de tamaño y respaldo en el Internet Archive (CDX y, si se activa con `ENSO_ARCHIVE_SAVE=1`, Save Page Now). El tiempo está acotado: conectar, 15 s; cada pedido, 5 min las fuentes oficiales y 1 min cada feed en total (el plazo del cliente es por lectura y un servidor que manda la respuesta de a pocos bytes no lo agota), sin reintento si se agota; un servidor con 3 fallos de red seguidos recibe un solo intento por URL, y con 5 ya no se le pide nada en la corrida; todas las fuentes oficiales juntas, 8 min (`OFFICIAL_BUDGET_S`), y las que falten siguen con sus copias o su dato anterior. Una respuesta rota (gzip mal declarado, redirecciones sin fin) es una URL fallida más, no un error que detenga la corrida |
| `feeds/cpc.py` | Lectores de los archivos de texto de NOAA/CPC: semanal OISST, mensual por región, RONI/ONI, matrices año×mes (SOI, presiones, vientos), contenido de calor y la ENSO Diagnostic Discussion |
| `feeds/peru.py` | Lectores del ICEN del IGP, del listado de comunicados del ENFEN (HTML y WordPress JSON) y del texto de cada comunicado (PDF) |
| `signals.py` | Categorías ICEN 2024, eventos ICEN, categorías ONI/RONI y la señal del equipo GRD |
| `observatory.py` | Catálogo de fuentes, adquisición con respaldo, armado de la publicación, registro de incidencias y CLI |
| `reach.py` | `robots.txt` según RFC 9309 (la regla más larga gana) y clases de alcance por red (Actions, n8n, Perú) |
| `feedparse.py` | Lector tolerante de RSS 2.0/1.0, Atom, JSON Feed y listados de gob.pe: repara XML mal formado, fechas y codificaciones |
| `hazardparse.py` | Lectores de alertas sin RSS: GeoJSON de USGS, boletines y avisos especiales de la DHN, mensajes del PTWC, boletines del CENVUL, canal de Telegram y capas ArcGIS del SENAMHI (copia del INDECI), reportes del COEN y focos de calor de FIRMS |
| `geo.py`, `geopoly.py` | Ubicación por distrito, provincia y departamento (UBIGEO del INEI); coordenadas y polígonos por los límites oficiales del INDECI |
| `news.py` | Feeds RSS/Atom de noticias: estado de cada feed, filtro de relevancia, agrupación de notas similares, histórico de solo anexar y CSV |
| `sourcefeed.py` | Alertas y reportes de peligros de los últimos 7 días (con las fuentes de alertas que no respondieron) y la última novedad de cada fuente oficial, agrupada por tipo |

Cada lector devuelve los datos junto con una **huella del formato**
(cabeceras, columnas y patrón de filas). Si la huella cambia respecto de
la publicación anterior se registra `format-drift`; si el formato ya no
se puede leer se lanza `FormatChanged` y el dato no se publica.

### Canales por URL

`registry/sources.json` dice, para cada URL de cada fuente (la principal y sus
réplicas, campo `by_url`), qué recolector la pide: `actions`, `n8n` o
`peru-server`. Una URL va al servidor del Perú si y solo si no responde desde
ninguna red de EE. UU. (GitHub Actions en Azure, n8n en AWS); los canales de
la fuente son la unión. El pipeline lee el registro en cada corrida:

- una URL que Actions no alcanza se lee primero de la copia del Perú o de n8n
  y se pide directo una sola vez, por si volvió a responder;
- una URL cuyo `robots.txt` lo prohíbe no se pide (sin canales), salvo los
  feeds de noticias marcados `reader` (Google Noticias, Noticias ONU, Sin
  Rodeos): se leen como un lector de feeds, solo desde las corridas de
  `observatory.yml` en `main` y como mucho una vez cada 20 horas desde el
  último pedido, haya respondido o no, sin reintento; entre dos pedidos
  queda el estado del último, y las notas de la última lectura buena se
  guardan con él en la caché de Actions por si esa corrida no llega a
  publicar;
- si hay varias copias de una URL (Perú y n8n), gana la más reciente, también
  para las noticias y las alertas.

El recolector del Perú baja las fuentes `peru-server` y n8n las `n8n`, así que
los tres canales leen la misma lista. `probe-sources.yml` mide cada semana
desde Actions y suma lo que bajaron el Perú y n8n.

### Orden de respaldo por fuente

1. URL oficial (y espejos oficiales cuando existen).
2. Copia más reciente del Internet Archive.
3. Copia nueva pedida al Internet Archive (solo en la corrida programada).
4. Último dato válido de la publicación anterior, marcado `carried: true`.

Cuando todo falla para una fuente crítica, la corrida termina en
`critical` y no se despliega.

## Contrato de la publicación (`public/data/`)

Todos los JSON llevan el mismo `publicationId` (`AAAAMMDDTHHMMZ-hash8`).
El navegador compara el de cada archivo con el de `dashboard.json` y,
si no coinciden, muestra un aviso en lugar de mezclar datos.

| Archivo | Contenido |
|---|---|
| `dashboard.json` | Estado oficial (ENFEN, NOAA), último valor de cada serie con su categoría y antigüedad, señal GRD, eventos ICEN y salud de la corrida |
| `series.json` | Series mensuales completas |
| `weekly.json` | Anomalías semanales por región Niño (últimas semanas) |
| `sources.json`, `sources/*.json` | Por fuente: URL usada, canal (directo, archivo, anterior), fecha de descarga, SHA-256, huella del formato y datos leídos |
| `run-report.json` | Todas las incidencias de la corrida con severidad, etapa, código y huella |
| `health.json` | Resumen para monitoreo externo |
| `manifest.json` | Lista de archivos de la publicación |
| `feed.json` | Alertas de peligros (últimos 7 días, con el estado de cada fuente de alertas) y novedades de las fuentes oficiales agrupadas por tipo: título, fecha, valor, categoría, cambio, enlace en vivo, copia archivada y respuesta original |
| `news/feeds.json` | Estado de cada feed de noticias en esta corrida: responde, entradas, relevantes, fecha de la más reciente, activo |
| `news/clusters.json` | Notas de los últimos 14 días agrupadas por similitud del titular: titular más temprano, medios, resumen y enlaces |
| `news/items.jsonl` | Histórico de noticias de solo anexar: cada corrida agrega las notas nuevas al final y nunca reescribe las anteriores |
| `news/items.csv` | El mismo histórico en CSV, protegido contra fórmulas |
| `csv/*.csv` | Descargas con cabecera `periodo,valor,unidad,serie,fuente,publicacion`; los textos que empiezan con `=`, `@`, `+` o `-` no numéricos se neutralizan contra inyección de fórmulas |

Cada último valor publicado incluye `period`, `value`, `ageDays`,
`stale` y `carried`. Un valor vencido se muestra como «Dato actual no
disponible», nunca como vigente.

## Sitio (`public/`)

- HTML, CSS y módulos ES sin dependencias ni paso de compilación.
- Política de seguridad de contenido estricta (`script-src 'self'`), sin
  scripts en línea; las respuestas del asistente escapan todo el texto.
- Rutas por hash: Resumen, Costa peruana, Pacífico, Océano, Mapa,
  Historia, Noticias, Datos, Metodología y Asistente.
- Español del Perú, coma decimal, tema claro y oscuro, navegación por
  teclado, enlace para saltar al contenido, tablas alternativas a cada
  gráfico y al mapa.
- `assets/js/assistant.js` responde con reglas deterministas a partir de
  la publicación y cita la evidencia de cada respuesta; no usa un modelo
  de lenguaje ni inventa valores.
- `assets/js/geo.js` contiene la costa de Natural Earth ya proyectada; se
  regenera con `scripts/geo/gen.mjs`.

## Noticias

- **Relevancia:** en medios generales se exige un término del ENSO
  («El Niño», «La Niña», «Niño costero», ENFEN, ICEN, temperatura del
  mar…). En feeds de emergencias o clima (ReliefWeb, GDACS, ONU, búsquedas
  de Google Noticias) basta un peligro asociado (lluvias intensas,
  huaicos, inundaciones, sequía…) si la nota es del Perú.
- **Agrupación:** dos titulares se agrupan si comparten al menos tres
  palabras significativas y el 60 % de las del más corto, dentro de la
  misma región (Perú o mundo). El titular del grupo es el de la nota más
  temprana; el resumen es la primera oración del resumen más largo.
- **Histórico:** `news/items.jsonl` se lee de la publicación anterior y
  se le agregan las notas nuevas (por `id` = hash de enlace y titular).
  Cada corrida archivada guarda en la rama `data-archive` la unión de todo
  lo publicado, comprimida (`sources/news/items.jsonl.gz`: el job
  `archive` le agrega con `python/tools/merge_history.py` las notas de la
  corrida que no tenga y nunca le quita ninguna), y las notas nuevas de
  cada día (`sources/news/<día>.jsonl`, que se suman). La corrida baja
  siempre esa copia y le agrega al histórico publicado, al final, las notas
  que no tenga (p. ej. las de una corrida que no llegó a desplegar:
  `news-history-restored`). Si el histórico publicado no responde tras tres
  intentos, lo rehace con la copia (`news-history-missing`, advertencia).
  Un sitio que no responde (5xx, sin respuesta) no es lo mismo que uno que
  no tiene el archivo (404): solo con 404 en el sitio y en `data-archive`
  se trata como primera publicación. Si no hay histórico ni copia que
  leer, publica solo las notas de hoy y marca el histórico como
  `restarted` en `news/feeds.json` (`news-history-missing`, error, que se
  repite mientras siga así); la corrida siguiente que lea la copia lo
  completa. Una corrida sin noticias (su lectura falló) sirve las de la
  publicación anterior, con `carriedFrom` en `news/feeds.json`, y sus
  alertas son las últimas conocidas, con los lugares corregidos en la
  consola; el sitio avisa que ninguna fuente de alertas se leyó. GitHub no
  acepta archivos de más de 100 MB y Cloudflare Pages no sirve archivos de
  más de 25 MiB: el pipeline avisa (`news-history-large`) cuando
  `items.jsonl` pasa de 20 MiB, y la copia comprimida deja de crecer (con
  aviso) si pasaría de 90 MiB.
- **Derechos:** solo se guarda lo que el medio publica en su feed
  (titular, resumen, fecha y enlace). El sitio enlaza siempre a la nota
  original.

## Pruebas (`python/tests/`)

- `test_feeds_backtest.py`: cada lector contra respuestas reales actuales
  y contra versiones históricas del Internet Archive (2009–2026), para
  detectar a tiempo los cambios de formato de las instituciones.
- `test_signals_and_pipeline.py`: bordes de las categorías, coincidencia
  entre los YAML de umbrales y el código, eventos ICEN frente al registro
  oficial, SOI Troup frente a los valores archivados de BoM, publicación
  completa sin red, respaldo cuando falla una fuente y detección de
  cambios de formato.
- `test_hazards.py`: cada lector de alertas sobre respuestas reales del
  21 de octubre de 2026 y sobre formatos anteriores o mal formados.
- `test_geopoly.py`: la ubicación por departamento frente a la que asigna
  el INPE de Brasil a los mismos focos de calor.
- `test_browser.py`: recorridos en Chromium a 320, 390, 820 y 1366 px
  (errores, desbordes, paridad de valores, teclado, tema, tutorial, mapa,
  descargas, publicación mezclada y caída de datos).
