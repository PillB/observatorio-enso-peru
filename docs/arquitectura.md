# Arquitectura y contrato de datos

## Vista general

![Arquitectura: fuentes, canales, pipeline, publicación, sitio y operación](arquitectura.svg)

El diagrama (`docs/arquitectura.svg`, copiado en `public/assets/` para la
sección Metodología del sitio) se lee de izquierda a derecha:

1. **Fuentes:** oficiales del Perú (ENFEN, IGP; SENAMHI, ANA e IMARPE solo
   desde el Perú), NOAA (CPC y PSL), 21 feeds de noticias y la política de
   umbrales.
2. **Canales**, en orden: directo, recolector en el Perú (rama
   `data-peru`), Internet Archive y publicación anterior.
3. **Pipeline** en Python: descarga con procedencia, lectores con
   backtesting, validación y armado, señal GRD, noticias y feed de fuentes.
4. **Publicación** atómica en `public/data/` y archivo de respuestas
   originales en la rama `data-archive`.
5. **Sitio** estático en GitHub Pages.

No hay servidor ni base de datos. Una corrida de GitHub Actions genera la
publicación y GitHub Pages la sirve junto con el sitio. Si algo falla
antes del despliegue, sigue publicado el sitio anterior.

## Pipeline (`python/enso/`)

| Módulo | Función |
|---|---|
| `fetch.py` | Descarga con reintentos, límites de tamaño y respaldo en el Internet Archive (CDX y, si se activa con `ENSO_ARCHIVE_SAVE=1`, Save Page Now) |
| `feeds/cpc.py` | Lectores de los archivos de texto de NOAA/CPC: semanal OISST, mensual por región, RONI/ONI, matrices año×mes (SOI, presiones, vientos), contenido de calor y la ENSO Diagnostic Discussion |
| `feeds/peru.py` | Lectores del ICEN del IGP, del listado de comunicados del ENFEN (HTML y WordPress JSON) y del texto de cada comunicado (PDF) |
| `signals.py` | Categorías ICEN 2024, eventos ICEN, categorías ONI/RONI y la señal del equipo GRD |
| `observatory.py` | Catálogo de fuentes, adquisición con respaldo, armado de la publicación, registro de incidencias y CLI |
| `news.py` | Feeds RSS/Atom de noticias: estado de cada feed, filtro de relevancia, agrupación de notas similares, histórico de solo anexar y CSV |
| `sourcefeed.py` | Última novedad de cada fuente oficial, agrupada por tipo (comunicados, índices, mar, atmósfera, subsuperficie) |

Cada lector devuelve los datos junto con una **huella del formato**
(cabeceras, columnas y patrón de filas). Si la huella cambia respecto de
la publicación anterior se registra `format-drift`; si el formato ya no
se puede leer se lanza `FormatChanged` y el dato no se publica.

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
| `feed.json` | Novedades de las fuentes oficiales agrupadas por tipo: título, fecha, valor, categoría, cambio y enlace al documento |
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
  Las notas de cada día se guardan también en `data-archive/news/`, de
  modo que el histórico puede reconstruirse si la publicación anterior no
  se pudo leer (incidencia `news-history-missing`).
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
- `test_browser.py`: recorridos en Chromium a 320, 390, 820 y 1366 px
  (errores, desbordes, paridad de valores, teclado, tema, tutorial, mapa,
  descargas, publicación mezclada y caída de datos).
