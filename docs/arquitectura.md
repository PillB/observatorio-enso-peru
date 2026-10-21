# Arquitectura y contrato de datos

## Vista general

Hay dos diagramas y los dos se dibujan desde un solo modelo,
`docs/arquitectura.json`: cada caja y cada conexión tiene ahí su texto en
español e inglés, cuándo ocurre y en qué parte del código está. Para
cambiarlos se edita el modelo y se corre `python -m tools.architecture`
(desde `python/`), que vuelve a trazar las líneas, escribe los SVG en
`docs/` y en `public/assets/` (la sección Metodología del sitio los muestra,
con un selector entre los dos) y regenera el texto de abajo. Una prueba
falla si el modelo, los SVG o este texto no coinciden.

- **Simplificado** (`arquitectura-simple.svg`): 9 cajas para explicar el
  sistema a cualquier persona, de arriba abajo. Las cajas llevan el número
  del paso del recorrido que las presenta y las líneas una letra con lo que
  viaja por ellas.
- **Completo** (`arquitectura.svg`): 44 cajas y 70 conexiones numeradas,
  en seis bloques (fuentes, recolectores, copias y respaldo, pipeline,
  publicación y sitio, y debajo operación, vigilancia y personas). Debajo
  del dibujo, cada número dice qué viaja, cuándo y por qué.

Las líneas son de cuatro tipos: datos (continua), respaldo que se usa si
falla lo anterior (guiones), disparo o control (puntos) y paso manual de
una persona (guion y punto). En el sitio y al abrir el SVG en el navegador,
pasar el puntero (o tocar, en el sitio) sobre una caja o una conexión
muestra su explicación completa.

### Diagrama simplificado

![Arquitectura simplificada: fuentes, recolectores, respaldo, pipeline, consola, publicación, sitio y operación](arquitectura-simple.svg)

### Diagrama completo

![Arquitectura completa: 44 partes y 70 conexiones numeradas](arquitectura.svg)

### Cómo se recorre

<!-- recorrido:inicio (generado por python -m tools.architecture) -->

**Recorrido del diagrama simplificado** (el número de cada caja es el paso que la presenta):

1. **Qué vigilamos.** El observatorio sigue las fuentes oficiales del ENSO (ENFEN, IGP y NOAA), 13 servicios de alertas de peligros y 154 feeds de noticias. Solo pide lo que las reglas de cada sitio permiten. _Cajas: Fuentes oficiales y alertas (1), Noticias (1)._
2. **Tres recolectores cada noche.** A las 21:00 una computadora en el Perú baja lo bloqueado, a las 22:50 n8n en la nube guarda una segunda copia y a las 23:37 GitHub Actions baja el resto y usa esas copias si algo falla. _Cajas: Recolectores (Actions, n8n, Perú) (2), Fuentes oficiales y alertas (1), Noticias (1)._
3. **Un registro dice quién baja qué.** Algunas páginas del Estado no responden fuera del Perú. Cada lunes se mide qué responde desde dónde y se actualiza un registro que asigna cada dirección a un recolector. _Cajas: Recolectores (Actions, n8n, Perú) (2), Operación y vigilancia (9)._
4. **Cuando algo falla.** Si una fuente no responde, se usa el último dato bueno ya publicado, una copia del Internet Archive o el archivo permanente. Cada dato muestra su fecha real, así nada viejo se hace pasar por nuevo. _Cajas: Respaldo (4), Pipeline diario (5)._
5. **El pipeline diario.** Lee y revisa cada dato, calcula índices, el estado oficial del ENFEN y la señal GRD, filtra las noticias por peligro y las ubica por departamento. Anota cada problema. _Cajas: Pipeline diario (5)._
6. **La consola de lugares.** Cuando el sistema duda dónde ocurrió una noticia, un revisor la corrige en la consola. La corrección se aplica en la corrida siguiente y nunca se pierde. _Cajas: Consola de lugares (6), Publicación (7), Pipeline diario (5)._
7. **Publicar sin romper nada.** Todos los archivos se arman y validan juntos, el sitio se prueba en un navegador y se sube completo. Si hay un problema grave, se queda el sitio de ayer. _Cajas: Publicación (7), Sitio (8)._
8. **Lo que ve la gente.** El sitio muestra 10 vistas y descargas abiertas, con el enlace a la fuente original y a la copia archivada junto a cada dato. Lo de hoy será el respaldo de mañana. _Cajas: Sitio (8), Respaldo (4)._
9. **Vigilancia y avisos.** Dos vigilantes revisan el sitio cada 6 horas y relanzan la actualización si se atrasa. Cada problema se vuelve un aviso en GitHub que se cierra solo al resolverse. _Cajas: Operación y vigilancia (9), Sitio (8), Pipeline diario (5)._

**Conexiones del diagrama simplificado:**

| | De → a | Qué viaja, cuándo y por qué |
|---|---|---|
| A | Fuentes oficiales y alertas → Recolectores (Actions, n8n, Perú) | **Se descargan cada noche.** Cada noche los recolectores bajan los datos oficiales y las alertas. Lo que solo responde dentro del país, como el portal del ENFEN, lo baja la computadora en el Perú. |
| B | Noticias → Recolectores (Actions, n8n, Perú) | **Feeds de noticias.** GitHub Actions lee las noticias cada noche y n8n guarda una copia. Google Noticias se lee como mucho una vez al día porque sus reglas para robots así lo piden. |
| C | Recolectores (Actions, n8n, Perú) → Pipeline diario | **Datos con su origen.** Cada dato llega con quién lo bajó, de dónde y cuándo. Cuando la computadora del Perú termina, además pide que el sitio se actualice. |
| D | Respaldo → Pipeline diario | **Si una fuente falla.** Si una fuente no responde hoy, se usa el último dato bueno, la copia del Internet Archive o el histórico guardado, siempre con su fecha real. |
| E | Pipeline diario → Publicación | **Datos revisados.** Series, estados oficiales, señal GRD, noticias con lugar y la lista de problemas pasan a armar los archivos que verá la gente. |
| F | Publicación → Sitio | **Se publica y se comprueba.** El sitio se sube completo de una vez y luego se comprueba que la página en vivo muestre la versión nueva. Si algo grave falló, se queda la de ayer. |
| G | Sitio → Respaldo | **Hoy es el respaldo de mañana.** Lo que el sitio muestra hoy es lo que la corrida de mañana usa como último dato bueno si una fuente falla. |
| H | Pipeline diario → Respaldo | **Copia permanente.** Después de cada corrida buena, las respuestas originales nuevas y el histórico de noticias se guardan en un archivo que nunca borra nada. |
| I | Publicación → Consola de lugares | **Notas por revisar.** La consola muestra las noticias de los últimos 120 días cuyo lugar es dudoso, para que una persona lo confirme o lo corrija. |
| J | Consola de lugares → Pipeline diario | **Correcciones de lugar.** Las correcciones se aplican en la corrida siguiente y tienen la última palabra. Si la consola no responde, se usan las ya publicadas. |
| K | Operación y vigilancia → Recolectores (Actions, n8n, Perú) | **Ajusta quién baja qué.** Cada lunes se mide qué fuentes responden desde cada lugar y se actualiza el registro que siguen los tres recolectores. |
| L | Sitio → Operación y vigilancia | **Vigilancia cada 6 horas.** Dos vigilantes, uno en GitHub y otro en n8n, revisan cada 6 horas que el sitio tenga menos de 30 horas. |
| M | Operación y vigilancia → Pipeline diario | **Relanza o corre a mano.** Si el sitio está atrasado, el vigilante relanza la actualización. Las personas también la lanzan al aprobar cambios o a mano. |
| N | Publicación → Operación y vigilancia | **Avisos de problemas.** Cada problema de la corrida se vuelve un aviso en GitHub, que se cierra solo cuando el problema desaparece. |

**Qué cubre cada caja del simplificado en el completo:**

- **Fuentes oficiales y alertas:** ENFEN e IGP: fuentes oficiales del Perú, NOAA (CPC y PSL), Alertas oficiales de peligros (13 fuentes), Páginas del Estado solo para archivo, robots.txt de cada servidor.
- **Noticias:** Medios y Estado: 116 feeds de noticias, Google Noticias: 38 búsquedas.
- **Recolectores (Actions, n8n, Perú):** Descarga en GitHub Actions (Fetcher), Recolector en el Perú, Recolector n8n (nube AWS), Rama data-peru, Rama data-n8n, Registro de fuentes (registry/), Armado del registro.
- **Respaldo:** Internet Archive (Wayback), Publicación anterior (data/ en vivo), Rama data-archive, Job archive.
- **Pipeline diario:** Actualización diaria (observatory.yml), Lectura de fuentes oficiales, Series, estados y señal GRD, Noticias y alertas: lectura y filtro, Histórico de noticias (solo anexar), Ubicación y correcciones de lugar, Registro de incidencias, Datos de referencia: lugares y umbrales, Caché de Actions: feeds reader.
- **Publicación:** Escritura y validación de la publicación, Archivos publicados (data/), Despliegue y verificación.
- **Sitio:** Sitio en vivo (SITE_URL), Sitio web (10 vistas), Público.
- **Operación y vigilancia:** Vigilante de GitHub (watchdog.yml), Vigilante n8n (fuera de GitHub), Issues de incidencias (incidente-datos), Sondeo semanal de alcance, Herramientas de desarrollo, Kit y verificación del recolector, Mantenedores y propietario, Responsable del equipo en el Perú, Colega que opera n8n.
- **Consola de lugares:** Consola de lugares (/admin/), Revisores de lugares.

<details><summary>Las 70 conexiones del diagrama completo, en texto</summary>

| N.º | De → a | Cuándo | Qué viaja y por qué |
|---|---|---|---|
| 1 | ENFEN e IGP: fuentes oficiales del Perú → Recolector en el Perú | diario 21:00 Lima, reintentos hasta 23:30 | **portal ENFEN e ICEN https.** Cada noche el equipo en el Perú baja la API y el listado del portal del ENFEN, los PDF de los comunicados y el ICEN por https, que no responden desde EE. UU. Así el comunicado oficial llega aunque el portal bloquee a la nube. |
| 2 | ENFEN e IGP: fuentes oficiales del Perú → Descarga en GitHub Actions (Fetcher) | diario 23:37 Lima, primeras fuentes | **réplica DHN e ICEN, directo.** Actions pide la réplica de la DHN y el ICEN por http, que sí responden desde EE. UU. Para las URL del portal lee primero la copia del Perú y prueba una sola vez por si volvieron. |
| 3 | ENFEN e IGP: fuentes oficiales del Perú → Recolector n8n (nube AWS) | diario 22:50 Lima | **copia de réplica e ICEN.** n8n baja la réplica de la DHN con sus PDF y el ICEN por http, y deja una segunda copia por si Actions no obtiene una respuesta válida. |
| 4 | NOAA (CPC y PSL) → Descarga en GitHub Actions (Fetcher) | diario 23:37 Lima | **14 productos, directo.** Actions baja cada noche los índices, la temperatura del mar, el calor bajo la superficie y la discusión ENSO de NOAA. Si un producto crítico falla y no hay dato anterior, no se despliega. |
| 5 | NOAA (CPC y PSL) → Recolector n8n (nube AWS) | diario 22:50 Lima | **copia de respaldo.** n8n baja las mismas 14 URL cada noche; si el pedido directo de Actions falla, el pipeline usa esa copia. |
| 6 | Alertas oficiales de peligros (13 fuentes) → Descarga en GitHub Actions (Fetcher) | diario 23:37 Lima | **13 fuentes de alertas.** Junto con las noticias, Actions lee los avisos del INDECI, SENAMHI, DHN, IGP, USGS, PTWC y NASA FIRMS, cada uno en su formato (RSS, JSON, HTML, CSV o texto). |
| 7 | Alertas oficiales de peligros (13 fuentes) → Recolector n8n (nube AWS) | diario 22:50 Lima | **copia de respaldo.** n8n guarda una copia de las 13 fuentes de alertas por si Actions no las alcanza esa noche. |
| 8 | Páginas del Estado solo para archivo → Recolector en el Perú | diario 21:00 Lima | **solo archivo, desde el Perú.** El recolector baja cada noche estas 12 páginas de su lista fija para conservar el original. 6 de ellas (SENAMHI y ANA) no responden desde EE. UU. |
| 9 | Páginas del Estado solo para archivo → Recolector n8n (nube AWS) | diario 22:50 Lima | **las 6 páginas abiertas.** IMARPE, CENEPRED, el observatorio del SENAMHI e IDESEP llevan el canal n8n por regla (abiertas o sin medir), así que n8n también las baja. Actions no las pide porque no tienen lector. |
| 10 | Medios y Estado: 116 feeds de noticias → Descarga en GitHub Actions (Fetcher) | diario 23:37 Lima, tras las fuentes oficiales | **116 feeds de noticias.** Actions lee cada noche los feeds del Estado, medios nacionales y regionales, radios e internacionales, uno tras otro por servidor por cortesía. Noticias ONU y Sin Rodeos se piden como lector de feeds. |
| 11 | Medios y Estado: 116 feeds de noticias → Recolector n8n (nube AWS) | diario 22:50 Lima | **copia de respaldo (114).** n8n baja los mismos feeds menos los 2 de lector de feeds; si uno falla desde Actions, el pipeline usa la copia más reciente. |
| 12 | Google Noticias: 38 búsquedas → Descarga en GitHub Actions (Fetcher) | como mucho cada 20 h; solo corridas de main | **lector de feeds, 1 cada 20 h.** Como su robots.txt prohíbe estos 38 feeds, Actions los pide como un lector de RSS: solo en main, sin reintento y como mucho una vez cada 20 h. Entre lecturas se repite la última. |
| 13 | robots.txt de cada servidor → Sondeo semanal de alcance | lunes 04:17 Lima | **regla más larga gana.** Cada semana el sondeo lee el robots.txt de cada servidor antes de medir. Una ruta prohibida queda como robots-disallowed y pierde sus canales, salvo los feeds reader. |
| 14 | robots.txt de cada servidor → Recolector en el Perú | diario 21:00 Lima | **se respeta en vivo.** Cada noche el recolector lee el robots.txt antes de pedir. No pide una ruta prohibida, y si el robots.txt no responde no le pide nada a ese servidor. |
| 15 | Sondeo semanal de alcance → Armado del registro | lunes 04:17 Lima (09:17 UTC) | **mide y regenera.** El sondeo escribe reachability.json con lo medido desde Actions, el Perú y n8n, y enseguida corre build_registry para que los canales sigan las mediciones nuevas. |
| 16 | Armado del registro → Registro de fuentes (registry/) | lunes 04:17 Lima | **genera y valida.** Escribe sources.json con estado y canales por URL. En main el sondeo hace commit de registry/; en otras ramas el resultado va a bot/registry/<rama>. |
| 17 | Rama data-peru → Sondeo semanal de alcance | lunes 04:17 Lima | **lo medido desde el Perú.** El sondeo lee el index.json del Perú: qué URL respondieron allá y sus mediciones extra. Con eso el registro puede confirmar un geobloqueo; hoy todavía no hay mediciones del Perú. |
| 18 | Rama data-n8n → Sondeo semanal de alcance | lunes 04:17 Lima | **lo medido desde n8n.** También suma el último intento de n8n en AWS como medición de la red n8n. Una copia arrastrada cuenta como su último fallo, no como medición de hoy. |
| 19 | Registro de fuentes (registry/) → Descarga en GitHub Actions (Fetcher) | cada corrida de observatory.yml | **plan de canales por URL.** En cada corrida el pipeline lee quién pide cada URL. Lo que Actions no alcanza se lee primero de las copias, lo prohibido no se pide y los 40 reader se piden como lector de feeds. |
| 20 | Registro de fuentes (registry/) → Recolector n8n (nube AWS) | diario 22:50 Lima | **149 URL para n8n.** Al empezar, n8n lee el registro de main en GitHub (o la copia incluida en el flujo) y pide solo las URL asignadas a n8n. |
| 21 | Registro de fuentes (registry/) → Recolector en el Perú | diario 21:00 Lima | **URL peru-server y PDF.** El recolector baja el registro de GitHub con su token (o usa la copia del kit) y suma a su lista fija las URL peru-server, sus reglas para seguir PDF y las URL sin medición del Perú. |
| 22 | Herramientas de desarrollo → Armado del registro | a mano | **fuentes verificadas al catálogo.** Una persona revisa los informes de los sondeos y agrega al código los feeds y lectores que funcionan; desde ahí entran al registro. Así se armó el catálogo del 21-10-2026. |
| 23 | Recolector en el Perú → Rama data-peru | 21:00 a 23:30 Lima | **copias, latido y mediciones.** Al terminar sube index.json, los archivos, heartbeat.json y sus mediciones a data-peru. Si nada respondió, solo sube el latido y deja intacta la última copia buena. |
| 24 | Recolector en el Perú → Actualización diaria (observatory.yml) | tras cada subida (cerca de las 21:00 Lima) | **pide actualizar (enso-refresh).** Tras subir la copia envía repository_dispatch enso-refresh para que el sitio se actualice sin esperar a las 23:37. Si hay una corrida en curso, queda en cola. Viene activo en el kit. |
| 25 | Recolector n8n (nube AWS) → Rama data-n8n | diario 22:50 Lima | **commit que reemplaza la rama.** n8n sube los archivos nuevos por la API de GitHub, arma un commit sin padre y mueve data-n8n. index.json y heartbeat.json van siempre, aunque nada responda. |
| 26 | Kit y verificación del recolector → Responsable del equipo en el Perú | cuando cambia el recolector en main | **kit .zip y VERIFICAR.** La persona baja recolector-peru.zip de la versión recolector-kit y, al instalar o ante un problema, corre VERIFICAR; el informe queda en logs/ para enviarlo. |
| 27 | Responsable del equipo en el Perú → Recolector en el Perú |  | **instala, token y tarea.** Al ejecutar INSTALAR con el token queda registrada la tarea programada de las 21:00. El recolector le avisa en el escritorio tras 2 fallas o si el token vence en menos de 21 días. |
| 28 | Colega que opera n8n → Recolector n8n (nube AWS) |  | **importa y activa.** La persona importa n8n/dist/enso-n8n-recolector.json en su n8n, elige la credencial de GitHub y lo activa. Los nodos se regeneran con build.mjs, no se editan en n8n. |
| 29 | Actualización diaria (observatory.yml) → Descarga en GitHub Actions (Fetcher) | 23:37 Lima (04:37 UTC); push a main; manual; enso-refresh; vigilante | **lanza el pipeline.** El paso «Fetch, validate and build» corre python -m enso.observatory con las copias del Perú y de n8n, el histórico y el estado reader ya bajados, con 26 min de límite. |
| 30 | Rama data-peru → Descarga en GitHub Actions (Fetcher) | diario 23:37 Lima | **copia del Perú (relay-peru).** Si Actions no obtiene respuesta válida, o la URL es solo del Perú, usa la copia de data-peru: hasta 7 días de antigüedad, estado 200 y sha256 verificado. |
| 31 | Rama data-n8n → Descarga en GitHub Actions (Fetcher) | diario 23:37 Lima | **copia de n8n (relay-n8n).** Lo mismo con las copias de n8n, válidas hasta 72 h. Si el Perú y n8n tienen copia de la misma URL, gana la más reciente. |
| 32 | Internet Archive (Wayback) → Descarga en GitHub Actions (Fetcher) | solo si falla todo lo anterior, dentro de los 8 min oficiales | **copia archivada.** Si la URL, la réplica y las copias fallan, se usa la última copia del Wayback, marcada con su fecha. Solo para el comunicado del ENFEN se pide además una copia nueva. |
| 33 | Descarga en GitHub Actions (Fetcher) → Lectura de fuentes oficiales |  | **respuesta con procedencia.** Cada respuesta llega con cuerpo, canal, URL, fecha de copia, sha256 e intentos; si todo falló, llega el error con los intentos. |
| 34 | Publicación anterior (data/ en vivo) → Lectura de fuentes oficiales | cada corrida | **último dato válido.** Se lee sources/<id>.json de ayer para comparar la huella del formato. Si la fuente falla hoy, se reutiliza ese dato con su fecha real, marcado carried. |
| 35 | Lectura de fuentes oficiales → Series, estados y señal GRD |  | **datos y comunicado.** Los datos de las 16 fuentes, frescos o arrastrados, y el último comunicado del ENFEN pasan a armar las series, el semanal y los estados oficiales. |
| 36 | Datos de referencia: lugares y umbrales → Series, estados y señal GRD |  | **umbrales ICEN y GRD.** Cada valor del ICEN recibe su categoría oficial y cada indicador su color GRD. Un valor entre intervalos queda «sin clasificación», nunca como normal. |
| 37 | Series, estados y señal GRD → Escritura y validación de la publicación |  | **series, estados y señal GRD.** Las series, el semanal, los estados de ENFEN y NOAA, los eventos ICEN y la señal GRD van a series.json, weekly.json, los CSV y dashboard.json. |
| 38 | Descarga en GitHub Actions (Fetcher) → Noticias y alertas: lectura y filtro | diario 23:37 Lima, tras las fuentes oficiales | **cuerpos de los feeds.** Los feeds se bajan con dos clientes propios (normal, y de un solo intento para los reader) que comparten las copias del Perú y de n8n, pero nunca usan el Internet Archive. |
| 39 | Caché de Actions: feeds reader → Noticias y alertas: lectura y filtro | solo corridas de main | **estado reader (lee y guarda).** Al empezar se restaura cuándo se pidió cada feed reader y sus notas sin publicar. Cada pedido se anota antes de hacerlo y el estado se guarda al final aunque la corrida falle. |
| 40 | Noticias y alertas: lectura y filtro → Histórico de noticias (solo anexar) |  | **notas nuevas ubicadas.** Las notas relevantes de hoy, con sus peligros y su lugar, se agregan al final del histórico si su id es nuevo. |
| 41 | Publicación anterior (data/ en vivo) → Histórico de noticias (solo anexar) |  | **histórico de ayer.** Se lee news/items.jsonl con 3 intentos. Según responda (ok, missing o unreachable) se completa, se rehace con la copia de data-archive o se marca restarted. |
| 42 | Rama data-archive → Histórico de noticias (solo anexar) | al inicio de cada corrida | **copia completa del histórico.** Antes del pipeline se baja sources/news/items.jsonl.gz por la API de GitHub. Con ella se agregan las notas que falten o se rehace el histórico si el sitio no lo sirvió. |
| 43 | Histórico de noticias (solo anexar) → Ubicación y correcciones de lugar |  | **todo el histórico.** El histórico entero, viejo y nuevo, se vuelve a ubicar y a corregir en bloque; el texto JSONL guardado no cambia. |
| 44 | Datos de referencia: lugares y umbrales → Ubicación y correcciones de lugar |  | **UBIGEO y límites.** Con los nombres del INEI se reconoce un lugar en el texto, y con los límites del IGN y del INDECI se sabe en qué distrito o departamento cae una coordenada. |
| 45 | Consola de lugares (/admin/) → Ubicación y correcciones de lugar | cada corrida, solo con DEPLOY_TARGET=cloudflare | **correcciones vigentes.** Con Cloudflare, el pipeline pide GET /api/geo/overrides (20 s de plazo) y aplica la última corrección de cada nota. Con GitHub Pages no hay consola y este paso no ocurre. |
| 46 | Publicación anterior (data/ en vivo) → Ubicación y correcciones de lugar |  | **correcciones de ayer.** Si la consola no está, falla o no responde, se usan las de geo/overrides.json de la publicación anterior: una corrección nunca se pierde. |
| 47 | Ubicación y correcciones de lugar → Escritura y validación de la publicación |  | **notas, grupos y alertas.** Pasan el histórico corregido, items.csv, los grupos de 14 días, los avisos de 7 días para feed.json y los archivos geo/ para la consola. |
| 48 | Publicación anterior (data/ en vivo) → Escritura y validación de la publicación |  | **copias y noticias de ayer.** Si una fuente no respondió hoy, se vuelve a publicar su copia archivada de ayer. Si la lectura de noticias falló, se reusan news/ y geo/ de ayer con carriedFrom. |
| 49 | Lectura de fuentes oficiales → Registro de incidencias |  | **fallos, arrastres y formato.** Se anotan unreachable (error si la fuente es crítica), format-drift, format-changed, carried-forward y communique-unread. Las copias del Perú y de n8n también anotan su salud. |
| 50 | Registro de incidencias → Escritura y validación de la publicación |  | **incidencias y salud.** Todas las incidencias, la peor severidad y los conteos van a run-report.json, health.json (degraded si hay error) y dashboard.json. |
| 51 | Registro de incidencias → Despliegue y verificación |  | **crítico: no se despliega.** Con --fail-on critical, si la peor severidad es critical el paso del pipeline sale con 1, el build falla y el despliegue no corre; sigue publicado el sitio anterior. |
| 52 | Escritura y validación de la publicación → Archivos publicados (data/) |  | **reemplazo atómico de data/.** Si la validación pasa (mismo publicationId en todo, series ordenadas, dashboard completo), public/data se reemplaza de una vez por la carpeta nueva. |
| 53 | Archivos publicados (data/) → Despliegue y verificación |  | **public/ listo para probar.** Con data/ escrita, el build adapta las direcciones del sitio, corre las pruebas de navegador en Chromium y sube el sitio como artefacto; si algo falla, no se despliega. |
| 54 | Despliegue y verificación → Sitio en vivo (SITE_URL) | tras cada build exitoso | **publica y verifica en vivo.** Sube todo el sitio de una vez a GitHub Pages o Cloudflare Pages, y verify_live espera hasta 10 min a que dashboard.json y manifest.json traigan el publicationId nuevo. |
| 55 | Sitio en vivo (SITE_URL) → Publicación anterior (data/ en vivo) | en la corrida siguiente | **hoy es la anterior de mañana.** Lo que el sitio sirve hoy en data/ es lo que la corrida siguiente lee con --previous para arrastrar datos y seguir el histórico. |
| 56 | Sitio en vivo (SITE_URL) → Sitio web (10 vistas) |  | **sirve páginas y datos.** El hosting entrega index.html, assets/ y data/. La página pide primero dashboard.json y luego cada archivo con el mismo publicationId. |
| 57 | Público → Sitio web (10 vistas) |  | **abre el sitio o descarga.** Cualquier persona abre la página o baja directamente los CSV y JSON de data/; desde cada dato puede ir a la fuente en vivo o a la copia archivada. |
| 58 | Actualización diaria (observatory.yml) → Job archive | cada corrida de main cuyo build pasa | **tras build exitoso en main.** El build deja el artefacto raw-sources (7 días) con las respuestas originales nuevas y el histórico de noticias; el job archive lo baja en paralelo al despliegue. |
| 59 | Job archive → Rama data-archive | tras cada build exitoso en main | **solo agrega, nunca borra.** Agrega las respuestas que no tenía, suma las notas del día y une el histórico con merge_history.py. Rechaza commits con borrados y reintenta el push 3 veces. |
| 60 | Archivos publicados (data/) → Issues de incidencias (incidente-datos) | al final de cada corrida, aunque falle | **run-report a issues.** El job incidents baja run-report.json y abre, actualiza o cierra un issue por huella. Si build, deploy o archive fallan, abre además «La actualización diaria falló». |
| 61 | Issues de incidencias (incidente-datos) → Mantenedores y propietario |  | **avisos para revisar.** Los mantenedores ven las incidencias abiertas con la etiqueta incidente-datos; se cierran solas cuando el problema deja de aparecer. |
| 62 | Sitio en vivo (SITE_URL) → Vigilante de GitHub (watchdog.yml) | 19:17, 01:17, 07:17 y 13:17 Lima | **lee dashboard.json.** Cada 6 horas pide data/dashboard.json sin caché y calcula la edad de la publicación con generatedAt. |
| 63 | Vigilante de GitHub (watchdog.yml) → Actualización diaria (observatory.yml) | solo si el sitio está atrasado | **relanza si pasa 30 h.** Si la publicación tiene más de 30 h o no se puede leer, lanza la actualización diaria, salvo que ya haya una en curso o un relanzamiento en las últimas 6 h. |
| 64 | Vigilante de GitHub (watchdog.yml) → Issues de incidencias (incidente-datos) | cada 6 h | **issue «sitio desactualizado».** Abre o comenta «El sitio publicado está desactualizado» con la acción tomada y lo cierra cuando el sitio vuelve a estar al día. |
| 65 | Sitio en vivo (SITE_URL) → Vigilante n8n (fuera de GitHub) | cada 6 h (intervalo de n8n) | **lee manifest.json.** Cada 6 horas, desde fuera de GitHub, n8n pide data/manifest.json y revisa que generatedAt tenga menos de 30 h. |
| 66 | Vigilante n8n (fuera de GitHub) → Colega que opera n8n |  | **avisa el Error workflow.** Una ejecución fallida dispara el Error workflow configurado en n8n (por ejemplo, un correo). Sirve aunque GitHub haya apagado sus flujos programados. |
| 67 | Archivos publicados (data/) → Consola de lugares (/admin/) | al abrir la consola | **notas por revisar.** La consola carga data/geo/items.json (notas de 120 días) y ubigeo.json para sus selectores; la API también usa ubigeo.json para rechazar códigos desconocidos. |
| 68 | Revisores de lugares → Consola de lugares (/admin/) |  | **corrigen lugares.** Con su usuario fijan, confirman o marcan como nacional o «no es del Perú» cada nota. Cada cambio es una fila nueva en la base D1 y se aplica en la siguiente corrida de las 23:37. |
| 69 | Mantenedores y propietario → Actualización diaria (observatory.yml) | al fusionar o a mano | **fusión en main o a mano.** Cada push a main publica enseguida (salvo cambios solo en .md o docs/). También se puede lanzar a mano y elegir si se piden copias nuevas al Internet Archive. |
| 70 | Mantenedores y propietario → Herramientas de desarrollo |  | **PR, ramas claude/** o a mano.** Las pruebas corren en cada PR y push a ramas claude/**; los sondeos y capturas, a mano o al cambiar su herramienta. Sus resultados se traen a mano desde las ramas bot/. |

</details>

<!-- recorrido:fin -->

### Lo esencial

- **Tres recolectores leen la misma lista.** `registry/sources.json` dice
  quién pide cada URL. GitHub Actions baja casi todo a las 23:37; n8n en la
  nube baja cada noche (22:50) una segunda copia de todo lo que no está
  prohibido ni bloqueado, haya fallado Actions o no; el equipo en el Perú
  (21:00) baja solo lo que no responde fuera del país. La corrida diaria
  no lee `robots.txt` ni usa un navegador: sigue el registro, que el
  sondeo semanal arma con lo que mide (y ahí sí se lee `robots.txt`). La
  escalera de extracción (`scrape-ladder.yml`: `robots.txt` → petición
  simple → cabeceras de navegador → Chromium → Firecrawl, que se detiene
  ante cualquier verificación anti-robots) es una herramienta para
  investigar fuentes nuevas, no un paso de la corrida.
- **Nada se publica a medias.** Si algo falla antes del despliegue sigue
  publicado el sitio anterior, y cada dato muestra su fecha real.
- **Servidor y base de datos, solo para la consola.** El sitio es estático;
  la consola de lugares usa una función de Cloudflare Pages con una base
  D1, y solo existe cuando el sitio se despliega en Cloudflare.

## Pipeline (`python/enso/`)

| Módulo | Función |
|---|---|
| `fetch.py` | Descarga con reintentos, límites de tamaño y respaldo en el Internet Archive (CDX y, si se activa con `ENSO_ARCHIVE_SAVE=1`, Save Page Now). El tiempo está acotado: conectar, 15 s; cada pedido, 5 min las fuentes oficiales y 1 min cada feed en total (el plazo del cliente es por lectura y un servidor que manda la respuesta de a pocos bytes no lo agota), sin reintento si se agota; cada servidor lleva la cuenta de sus fallos seguidos (un pedido sin respuesta suma uno, una respuesta que no termina a tiempo dos, una URL que solo recibió 429 o 5xx uno, y cualquier otra respuesta la pone en cero; Save Page Now lleva la suya): con 3 recibe un solo intento por URL, y con 5 ya no se le pide nada en la corrida; tras el último intento no se espera. Todas las fuentes oficiales juntas, 8 min (`OFFICIAL_BUDGET_S`), empezando por el ENFEN (listado y último comunicado), el ICEN y la ENSO Diagnostic Discussion (`OFFICIAL_FIRST`); pasado ese tiempo, las que falten siguen solo con las copias del Perú y de n8n o con su dato anterior (ya no se pide al Internet Archive). Una respuesta rota (gzip mal declarado, redirecciones sin fin) es una URL fallida más, no un error que detenga la corrida |
| `feeds/cpc.py` | Lectores de los archivos de texto de NOAA/CPC: semanal OISST, mensual por región, RONI/ONI, matrices año×mes (SOI, presiones, vientos), contenido de calor y la ENSO Diagnostic Discussion |
| `feeds/peru.py` | Lectores del ICEN del IGP, del listado de comunicados del ENFEN (HTML y WordPress JSON) y del texto de cada comunicado (PDF) |
| `signals.py` | Categorías ICEN 2024, eventos ICEN, categorías ONI/RONI y la señal del equipo GRD |
| `observatory.py` | Catálogo de fuentes, adquisición con respaldo, armado de la publicación, registro de incidencias y CLI |
| `reach.py` | `robots.txt` según RFC 9309 (la regla más larga gana) y clases de alcance por red (Actions, n8n, Perú) |
| `feedparse.py` | Lector tolerante de RSS 2.0/1.0, Atom, JSON Feed y listados de gob.pe: repara XML mal formado, fechas y codificaciones |
| `hazardparse.py` | Lectores de alertas sin RSS: GeoJSON de USGS, boletines y avisos especiales de la DHN, mensajes del PTWC, boletines del CENVUL, canal de Telegram y capas ArcGIS del SENAMHI (copia del INDECI), reportes del COEN y focos de calor de FIRMS |
| `geo.py`, `limites.py`, `geopoly.py`, `geo_overrides.py` | Ubicación por distrito, provincia y departamento (UBIGEO del INEI): por el texto, por los campos de la fuente o por coordenadas (límites del IGN en `limites.py`; departamentos del INDECI en `geopoly.py` para focos de calor y polígonos), más las correcciones de la consola |
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

1. URL oficial y, si no responde, la copia de esa misma URL que bajaron el
   recolector del Perú o n8n (gana la más reciente). Una URL que según el
   registro Actions no alcanza se lee primero de esas copias y se pide
   directo una sola vez.
2. Lo mismo con cada espejo oficial, en orden (por ejemplo, la réplica del
   ENFEN en la DHN).
3. Copia más reciente del Internet Archive.
4. Copia nueva pedida al Internet Archive (Save Page Now): solo para el
   listado y el PDF de los comunicados del ENFEN (no para los números que
   se sondean antes de que aparezcan), en las corridas de Actions con
   `ENSO_ARCHIVE_SAVE=1` (todas salvo una manual con `archive_save`
   desmarcado), cuando la copia existente tiene más de un día.
5. Último dato válido de la publicación anterior, marcado `carried: true`.

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
| `health.json` | Resumen de la corrida (ningún vigilante lo lee hoy: el de GitHub lee `dashboard.json` y el de n8n `manifest.json`) |
| `manifest.json` | Lista de archivos, versión del pipeline, commit (`gitSha`), series y `contentHash` |
| `feed.json` | Alertas de peligros (últimos 7 días, con el estado de cada fuente de alertas) y novedades de las fuentes oficiales agrupadas por tipo: título, fecha, valor, categoría, cambio, enlace en vivo, copia archivada y respuesta original |
| `news/feeds.json` | Estado de cada feed de noticias en esta corrida: responde, entradas, relevantes, fecha de la más reciente, activo |
| `news/clusters.json` | Notas de los últimos 14 días agrupadas por similitud del titular: titular más temprano, medios, resumen y enlaces |
| `news/items.jsonl` | Histórico de noticias de solo anexar: cada corrida agrega las notas nuevas al final y nunca reescribe las anteriores |
| `news/items.csv` | El mismo histórico en CSV, protegido contra fórmulas |
| `geo/items.json`, `geo/ubigeo.json` | Notas recientes con su lugar (hasta 120 días y 4000 notas) y el nomenclátor de departamentos, provincias y distritos, para la consola de lugares |
| `geo/overrides.json`, `geo/quality.json` | Correcciones de lugar aplicadas (sin nombres de revisores) y cuántas notas tienen lugar, con qué método y confianza ([georreferenciacion](georreferenciacion.md)) |
| `archive/sources/<fuente>/<sha12>.<ext>` | La respuesta original de cada fuente oficial y los PDF de los comunicados, byte por byte |
| `archive/feeds/<feed>.txt` | Cada feed de noticias tal como se bajó en esta corrida (como texto, para que sus scripts no corran en el sitio) |
| `archive/news/<día>.html` | Por día (60 días), lo que dijo el feed de cada noticia vista por primera vez ese día: el enlace «copia archivada» |
| `archive/index.json` | Los archivos copiados con su URL de origen, fecha, canal y SHA-256 |
| `csv/*.csv` | Descargas con cabecera `periodo,valor,unidad,serie,fuente,publicacion`; los textos que empiezan con `=`, `@`, `+` o `-` no numéricos se neutralizan contra inyección de fórmulas |

Cada último valor publicado incluye `period`, `value`, `ageDays`,
`stale` y `carried`. Un valor vencido se muestra como «Dato actual no
disponible», nunca como vigente.

## Sitio (`public/`)

- HTML, CSS y módulos ES sin dependencias ni paso de compilación.
- Política de seguridad de contenido estricta (`script-src 'self'`), sin
  scripts en línea; las respuestas del asistente escapan todo el texto.
- Rutas por hash: Resumen, El Niño Costero, Pacífico, Océano y atmósfera,
  Mapa, Historia, Noticias, Datos, Metodología y Asistente.
- Consola de lugares (`public/admin/`): los revisores corrigen el lugar de
  una nota. En Cloudflare Pages la atiende una función
  (`functions/api/geo/`) con una base D1; en GitHub Pages no hay API y
  solo se mantienen las correcciones ya publicadas
  ([georreferenciacion](georreferenciacion.md)).
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
  mar…). En feeds de emergencias o clima (GDACS, ONU, búsquedas de Google
  Noticias) basta un peligro asociado (lluvias intensas, huaicos,
  inundaciones, sequía…) si la nota es del Perú; en un medio general,
  también si el peligro está en el titular.
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
