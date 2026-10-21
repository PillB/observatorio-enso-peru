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
- **Completo** (`arquitectura.svg`): 44 cajas y 81 conexiones numeradas,
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

![Arquitectura completa: 44 partes y 81 conexiones numeradas](arquitectura.svg)

### Cómo se recorre

<!-- recorrido:inicio (generado por python -m tools.architecture) -->

**Recorrido del diagrama simplificado** (el número de cada caja es el paso que la presenta):

1. **Qué vigilamos.** El observatorio sigue las fuentes oficiales del ENSO (ENFEN, IGP y NOAA), 13 servicios de alertas de peligros y 154 feeds de noticias. Respeta las reglas de cada sitio para robots, salvo 40 feeds de noticias que lee como un lector, como mucho una vez al día. _Cajas: Fuentes oficiales y alertas (1), Noticias (1)._
2. **Tres recolectores cada noche.** A las 21:00 una computadora en el Perú baja lo bloqueado, a las 22:50 n8n en la nube guarda una segunda copia y a las 23:37 GitHub Actions baja lo que alcanza y usa esas copias si algo falla. _Cajas: Recolectores (Actions, n8n, Perú) (2), Fuentes oficiales y alertas (1), Noticias (1)._
3. **Un registro dice quién baja qué.** Algunas páginas del Estado no responden fuera del Perú. Cada lunes se mide qué responde desde dónde y se actualiza un registro que asigna cada dirección a un recolector. _Cajas: Recolectores (Actions, n8n, Perú) (2), Operación y vigilancia (9)._
4. **Cuando algo falla.** Si una fuente no responde, se usa la copia del Perú o de n8n, una copia del Internet Archive o el último dato bueno ya publicado. Cada dato muestra su fecha real, así nada viejo se hace pasar por nuevo. _Cajas: Respaldo (4), Pipeline diario (5), Recolectores (Actions, n8n, Perú) (2)._
5. **El pipeline diario.** Lee y revisa cada dato, arma las series, lee el estado oficial del ENFEN, calcula la señal GRD, filtra las noticias por peligro y las ubica por departamento. Anota cada problema. _Cajas: Pipeline diario (5)._
6. **La consola de lugares.** Con el sitio en Cloudflare, cuando el sistema duda dónde ocurrió una noticia, un revisor la corrige en la consola. La corrección se aplica desde la corrida siguiente y queda guardada. _Cajas: Consola de lugares (6), Publicación (7), Pipeline diario (5)._
7. **Publicar sin romper nada.** Todos los archivos se arman y validan juntos, el sitio se prueba en un navegador y se sube completo. Si hay un problema grave, se queda el sitio de ayer. _Cajas: Publicación (7), Sitio (8)._
8. **Lo que ve la gente.** El sitio muestra 10 vistas y descargas abiertas, con el enlace a la fuente original y a la copia archivada junto a cada dato. Lo de hoy será el respaldo de mañana. _Cajas: Sitio (8), Respaldo (4)._
9. **Vigilancia y avisos.** Dos vigilantes revisan el sitio cada 6 horas; el de GitHub relanza la actualización si se atrasa. Cada problema se vuelve un aviso en GitHub que se cierra solo al resolverse. _Cajas: Operación y vigilancia (9), Sitio (8), Pipeline diario (5)._

**Conexiones del diagrama simplificado:**

| | De → a | Qué viaja, cuándo y por qué |
|---|---|---|
| A | Fuentes oficiales y alertas → Recolectores (Actions, n8n, Perú) | **Se descargan cada noche.** Cada noche los recolectores bajan los datos oficiales y las alertas. Lo que solo responde dentro del país, como el portal del ENFEN, lo baja la computadora en el Perú. |
| B | Noticias → Recolectores (Actions, n8n, Perú) | **Feeds de noticias.** GitHub Actions lee las noticias en cada corrida y n8n guarda una copia. Google Noticias prohíbe robots: se lee como un lector de feeds, como mucho una vez al día. |
| C | Recolectores (Actions, n8n, Perú) → Pipeline diario | **Datos con su origen.** Cada dato llega con quién lo bajó, de dónde y cuándo. Cuando la computadora del Perú sube su copia, además pide que el sitio se actualice. |
| D | Respaldo → Recolectores (Actions, n8n, Perú) | **Copia del Internet Archive.** Si la fuente, su réplica y las copias del Perú y de n8n fallan, la descarga usa la última copia del Internet Archive, con su fecha. |
| E | Respaldo → Pipeline diario | **Si una fuente falla.** Si una fuente no responde hoy, se usa su último dato bueno ya publicado, con su fecha real. Si falta el histórico de noticias, se repone con la copia de data-archive. |
| F | Pipeline diario → Publicación | **Datos revisados.** Series, estados oficiales, señal GRD, noticias con lugar y la lista de problemas pasan a armar los archivos que verá la gente. |
| G | Publicación → Sitio | **Se publica y se comprueba.** El sitio se sube completo de una vez y luego se comprueba que la página en vivo muestre la versión nueva. Si algo grave falló, se queda la de ayer. |
| H | Sitio → Respaldo | **Hoy es el respaldo de mañana.** Lo que el sitio muestra hoy es lo que la corrida de mañana usa como último dato bueno si una fuente falla. |
| I | Pipeline diario → Respaldo | **Copia permanente.** Después de cada corrida buena, las respuestas originales nuevas y el histórico de noticias se guardan en un archivo que nunca borra nada. |
| J | Publicación → Consola de lugares | **Notas por revisar.** La consola trae las noticias de los últimos 120 días y abre con las de lugar dudoso, para que una persona lo confirme o lo corrija. |
| K | Consola de lugares → Pipeline diario | **Correcciones de lugar.** Las correcciones se aplican en la corrida siguiente y tienen la última palabra. Si la consola no responde, se usan las ya publicadas. |
| L | Operación y vigilancia → Recolectores (Actions, n8n, Perú) | **Ajusta quién baja qué.** Cada lunes se mide qué fuentes responden desde cada lugar y se actualiza el registro que siguen los tres recolectores. |
| M | Sitio → Operación y vigilancia | **Vigilancia cada 6 horas.** Dos vigilantes, uno en GitHub y otro en n8n, revisan cada 6 horas que el sitio tenga menos de 30 horas. |
| N | Operación y vigilancia → Pipeline diario | **Relanza o corre a mano.** Si el sitio está atrasado, el vigilante relanza la actualización. Las personas también la lanzan al aprobar cambios o a mano. |
| O | Publicación → Operación y vigilancia | **Avisos de problemas.** Cada problema de la corrida se vuelve un aviso en GitHub, que se cierra solo cuando el problema desaparece. |

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

<details><summary>Las 81 conexiones del diagrama completo, en texto</summary>

| N.º | De → a | Cuándo | Qué viaja y por qué |
|---|---|---|---|
| 1 | ENFEN e IGP: fuentes oficiales del Perú → Recolector en el Perú | diario 21:00 Lima, reintentos hasta 23:30 | **portal ENFEN e ICEN https.** Cada noche el equipo en el Perú baja la API y el listado del portal del ENFEN, los PDF de los comunicados y el ICEN por https, que no responden desde EE. UU. Así el comunicado oficial llega aunque el portal no responda a la nube. |
| 2 | ENFEN e IGP: fuentes oficiales del Perú → Descarga en GitHub Actions (Fetcher) | diario 23:37 Lima, primeras fuentes | **réplica DHN e ICEN, directo.** Actions pide el ICEN por http y la réplica de la DHN, que responden desde EE. UU. Para el API y el listado del portal usa primero la copia del Perú; si no hay, los pide una vez. |
| 3 | ENFEN e IGP: fuentes oficiales del Perú → Recolector n8n (nube AWS) | diario 22:50 Lima | **copia de réplica e ICEN.** n8n baja el ICEN por http y la réplica de la DHN con sus PDF, y deja una segunda copia por si Actions no obtiene una respuesta válida. |
| 4 | NOAA (CPC y PSL) → Descarga en GitHub Actions (Fetcher) | diario 23:37 Lima | **14 productos, directo.** Actions baja cada noche los índices, la temperatura del mar, el calor bajo la superficie y la discusión ENSO de NOAA. Si un producto crítico falla y no hay dato anterior, no se despliega. |
| 5 | NOAA (CPC y PSL) → Recolector n8n (nube AWS) | diario 22:50 Lima | **copia de respaldo.** n8n baja las mismas 14 URL cada noche; si el pedido directo de Actions falla, el pipeline usa esa copia. |
| 6 | Alertas oficiales de peligros (13 fuentes) → Descarga en GitHub Actions (Fetcher) | diario 23:37 Lima | **13 fuentes de alertas.** Junto con las noticias, Actions lee los avisos del INDECI, SENAMHI, DHN, IGP, USGS, PTWC y NASA FIRMS, cada uno en su formato (RSS, JSON, HTML, CSV o texto). |
| 7 | Alertas oficiales de peligros (13 fuentes) → Recolector n8n (nube AWS) | diario 22:50 Lima | **copia de respaldo.** n8n guarda una copia de las 13 fuentes de alertas por si Actions no las alcanza esa noche. |
| 8 | Páginas del Estado solo para archivo → Recolector en el Perú | diario 21:00 Lima | **solo archivo, desde el Perú.** Cada noche el recolector baja las 12 páginas de su lista fija para guardar el original. 6 (4 web del SENAMHI y 2 de la ANA) no responden desde EE. UU. |
| 9 | Páginas del Estado solo para archivo → Recolector n8n (nube AWS) | diario 22:50 Lima | **las 6 del canal n8n.** IMARPE, CENEPRED, el observatorio del SENAMHI e IDESEP llevan el canal n8n por regla (abiertas o sin medir), así que n8n también las baja. La corrida diaria no las pide porque no tienen lector. |
| 10 | Medios y Estado: 116 feeds de noticias → Descarga en GitHub Actions (Fetcher) | diario 23:37 Lima, tras las fuentes oficiales | **116 feeds de noticias.** Actions lee cada noche los feeds del Estado, medios nacionales y regionales, radios e internacionales, uno tras otro por servidor por cortesía. Noticias ONU y Sin Rodeos se piden como lector de feeds. |
| 11 | Medios y Estado: 116 feeds de noticias → Recolector n8n (nube AWS) | diario 22:50 Lima | **copia de respaldo (114).** n8n baja los mismos feeds menos los 2 de lector de feeds; si uno falla desde Actions, el pipeline usa la copia más reciente. |
| 12 | Google Noticias: 38 búsquedas → Descarga en GitHub Actions (Fetcher) | como mucho cada 20 h; solo corridas de main | **lector de feeds, 1 cada 20 h.** Como su robots.txt prohíbe estos 38 feeds, Actions los pide como un lector de RSS: solo en main, sin reintento y como mucho una vez cada 20 h. Entre lecturas se repite la última. |
| 13 | robots.txt de cada servidor → Sondeo semanal de alcance | lunes 04:17 Lima | **regla más larga gana.** Cada semana el sondeo lee el robots.txt de cada servidor antes de medir. Una ruta prohibida queda como robots-disallowed y pierde sus canales, salvo los feeds reader. |
| 14 | robots.txt de cada servidor → Recolector en el Perú | diario 21:00 Lima | **se respeta en vivo.** Cada noche el recolector lee el robots.txt antes de pedir. No pide una ruta prohibida, y si el robots.txt no responde no le pide nada a ese servidor. |
| 15 | Sondeo semanal de alcance → Armado del registro | lunes 04:17 Lima (09:17 UTC) | **mide y regenera.** El sondeo escribe reachability.json con lo medido desde Actions, el Perú y n8n, y enseguida corre build_registry para que los canales sigan las mediciones nuevas. |
| 16 | Armado del registro → Registro de fuentes (registry/) | lunes 04:17 Lima | **genera y valida.** Escribe sources.json con estado y canales por URL. En main el sondeo hace commit de registry/; en otras ramas el resultado va a bot/registry/&lt;rama>. |
| 17 | Rama data-peru → Sondeo semanal de alcance | lunes 04:17 Lima | **lo medido desde el Perú.** El sondeo lee el index.json del Perú: el resultado de cada URL allá y sus mediciones extra. Así el registro confirma un geobloqueo o una caída; hoy no hay mediciones del Perú. |
| 18 | Rama data-n8n → Sondeo semanal de alcance | lunes 04:17 Lima | **lo medido desde n8n.** También suma el último intento de n8n en AWS como medición de la red n8n. Una copia arrastrada cuenta como su último fallo, no como medición de hoy. |
| 19 | Registro de fuentes (registry/) → Descarga en GitHub Actions (Fetcher) | cada corrida de observatory.yml | **plan de canales por URL.** En cada corrida el pipeline lee quién pide cada URL. Lo que el registro no da a Actions se lee de las copias (sin copia, se pide directo una vez), lo prohibido no se pide y los 40 reader se piden como mucho cada 20 h, solo en main. |
| 20 | Registro de fuentes (registry/) → Recolector n8n (nube AWS) | diario 22:50 Lima | **149 URL para n8n.** Al empezar, n8n lee el registro de main en GitHub (o la copia incluida en el flujo) y pide solo las URL asignadas a n8n. |
| 21 | Registro de fuentes (registry/) → Recolector en el Perú | diario 21:00 Lima | **URL peru-server y PDF.** El recolector lee el registro de GitHub con su token (o la copia del kit), suma a su lista fija las URL peru-server y sus reglas para seguir PDF, y mide hasta 60 URL unknown, suspected-geoblock o down que esta corrida no pidió. |
| 22 | Herramientas de desarrollo → Armado del registro | a mano | **fuentes verificadas al catálogo.** Una persona revisa los informes de los sondeos y agrega al código los feeds y lectores que funcionan; desde ahí entran al registro. Así se armó el catálogo del 21-10-2026. |
| 23 | Recolector en el Perú → Rama data-peru | 21:00 a 23:30 Lima | **copias, latido y mediciones.** Al terminar sube index.json, los archivos, heartbeat.json y sus mediciones a data-peru. Si nada respondió, solo sube el latido y deja intacta la última copia buena. |
| 24 | Rama data-peru → Recolector en el Perú | diario 21:00 Lima | **copia anterior.** Antes de subir, el recolector lee su copia anterior y conserva hasta 72 h las URL que esta noche fallaron, marcadas carried. |
| 25 | Recolector en el Perú → Actualización diaria (observatory.yml) | tras subir una copia (no si solo sube el latido) | **pide actualizar (enso-refresh).** Tras subir la copia envía repository_dispatch enso-refresh para que el sitio se actualice sin esperar a las 23:37. Si hay una corrida en curso, queda en cola. Viene activo en el kit. |
| 26 | Recolector n8n (nube AWS) → Rama data-n8n | diario 22:50 Lima | **commit que reemplaza la rama.** n8n sube los archivos nuevos por la API de GitHub, arma un commit sin padre y mueve data-n8n. index.json y heartbeat.json van siempre, aunque nada responda. |
| 27 | Rama data-n8n → Recolector n8n (nube AWS) | diario 22:50 Lima | **copia anterior.** Su nodo «Leer copia anterior» lee el index.json de data-n8n y conserva hasta 72 h las URL que esta noche fallaron, marcadas carried. |
| 28 | Kit y verificación del recolector → Responsable del equipo en el Perú | al fusionar en main cambios del kit, python/enso/ o el registro (el commit semanal del bot no cuenta) | **kit .zip y VERIFICAR.** La persona baja recolector-peru.zip de la versión recolector-kit y corre VERIFICAR (el informe queda en logs/ para enviarlo). El equipo no se actualiza solo: un kit nuevo se instala con ACTUALIZAR. |
| 29 | Responsable del equipo en el Perú → Recolector en el Perú |  | **instala, token y tarea.** Al ejecutar INSTALAR con el token queda registrada la tarea programada de las 21:00. El recolector le avisa en el escritorio tras 2 fallas o si el token vence en menos de 21 días. |
| 30 | Mantenedores y propietario → Responsable del equipo en el Perú |  | **token y kit.** Le dan un token de GitHub de grano fino (solo este repositorio) y el kit, y uno nuevo cuando el recolector avisa que vence. |
| 31 | Colega que opera n8n → Recolector n8n (nube AWS) |  | **importa y activa.** La persona importa n8n/dist/enso-n8n-recolector.json en su n8n, elige la credencial de GitHub y lo activa. Los nodos se regeneran con build.mjs, no se editan en n8n. |
| 32 | Mantenedores y propietario → Colega que opera n8n |  | **token de GitHub.** Le dan un token de grano fino (solo este repositorio, Contents de lectura y escritura, 1 año) para la credencial de n8n. n8n no avisa antes de que venza: al vencer, la copia deja de subir y sale relay-n8n-stale. |
| 33 | Actualización diaria (observatory.yml) → Descarga en GitHub Actions (Fetcher) | 23:37 Lima (04:37 UTC); push a main; manual; enso-refresh; vigilante | **lanza el pipeline.** El paso «Fetch, validate and build» corre python -m enso.observatory con las copias del Perú y de n8n, el histórico y el estado reader ya bajados, con 26 min de límite. |
| 34 | Rama data-peru → Descarga en GitHub Actions (Fetcher) | cada corrida de observatory.yml | **copia del Perú (relay-peru).** Si Actions no obtiene respuesta válida, o la URL es solo del Perú, usa la copia de data-peru: hasta 7 días de antigüedad, estado 200 y sha256 verificado. |
| 35 | Rama data-n8n → Descarga en GitHub Actions (Fetcher) | cada corrida de observatory.yml | **copia de n8n (relay-n8n).** Lo mismo con las copias de n8n, válidas hasta 72 h. Si el Perú y n8n tienen copia de la misma URL, gana la más reciente. |
| 36 | Internet Archive (Wayback) → Descarga en GitHub Actions (Fetcher) | solo si falla todo lo anterior, dentro de los 8 min oficiales | **copia archivada.** Si la URL, la réplica y las copias fallan, se usa la última copia del Wayback, con su fecha. Para el ENFEN (listado y PDF) se pide una nueva si no hay o si la que hay tiene más de un día. |
| 37 | Descarga en GitHub Actions (Fetcher) → Lectura de fuentes oficiales |  | **respuesta con procedencia.** Cada respuesta llega con cuerpo, canal, URL, fecha de copia, sha256 e intentos; si todo falló, llega el error con los intentos. |
| 38 | Publicación anterior (data/ en vivo) → Lectura de fuentes oficiales | cada corrida | **último dato válido.** Se lee sources/&lt;id>.json de la publicación anterior para comparar la huella del formato. Si la fuente falla, se reutiliza ese dato con su fecha real, marcado carried. |
| 39 | Lectura de fuentes oficiales → Series, estados y señal GRD |  | **datos y comunicado.** Los datos de las 16 fuentes, frescos o arrastrados, y el último comunicado del ENFEN pasan a armar las series, el semanal y los estados oficiales. |
| 40 | Datos de referencia: lugares y umbrales → Series, estados y señal GRD |  | **umbrales GRD.** Cada indicador recibe su color GRD según expert-grd-image-v1.yaml. Un valor entre intervalos queda «sin clasificación», nunca normal. Las categorías ICEN están fijas en signals.py. |
| 41 | Series, estados y señal GRD → Escritura y validación de la publicación |  | **series, estados y señal GRD.** Las series, el semanal, los estados de ENFEN y NOAA, los eventos ICEN y la señal GRD van a series.json, weekly.json, los CSV y dashboard.json. |
| 42 | Descarga en GitHub Actions (Fetcher) → Noticias y alertas: lectura y filtro | diario 23:37 Lima, tras las fuentes oficiales | **cuerpos de los feeds.** Los feeds se bajan con dos clientes propios (normal, y de un solo intento para los reader) que comparten las copias del Perú y de n8n, pero nunca usan el Internet Archive. |
| 43 | Caché de Actions: feeds reader → Noticias y alertas: lectura y filtro | solo corridas de main | **estado reader (lee y guarda).** Al empezar se restaura cuándo se pidió cada feed reader y sus notas sin publicar. Sin caché no se piden, salvo en la primera publicación. Cada pedido se anota antes de hacerlo y el estado se guarda al final aunque la corrida falle. |
| 44 | Publicación anterior (data/ en vivo) → Noticias y alertas: lectura y filtro |  | **estado anterior de los feeds.** Se lee news/feeds.json de la publicación anterior (3 intentos): junto con la caché da la hora del último pedido de cada feed reader, para no repetirlo antes de 20 h. |
| 45 | Noticias y alertas: lectura y filtro → Histórico de noticias (solo anexar) |  | **notas nuevas ubicadas.** Las notas relevantes de hoy y las de feeds reader que aún no se publicaron, con sus peligros y su lugar, se agregan al final del histórico si su id es nuevo. |
| 46 | Publicación anterior (data/ en vivo) → Histórico de noticias (solo anexar) |  | **histórico anterior.** Se lee news/items.jsonl (hasta 3 intentos ante errores del servidor). Si llega, se completa con la copia de data-archive; si no, se rehace con ella o, sin copia, se marca restarted. |
| 47 | Rama data-archive → Histórico de noticias (solo anexar) | al inicio de cada corrida | **copia completa del histórico.** Antes del pipeline se baja sources/news/items.jsonl.gz por la API de GitHub. Con ella se agregan las notas que falten o se rehace el histórico si el sitio no lo sirvió. |
| 48 | Histórico de noticias (solo anexar) → Ubicación y correcciones de lugar |  | **todo el histórico.** El histórico entero, viejo y nuevo, se vuelve a ubicar y a corregir en bloque; el texto JSONL guardado no cambia. |
| 49 | Datos de referencia: lugares y umbrales → Ubicación y correcciones de lugar |  | **UBIGEO y límites.** Con los nombres del INEI se reconoce un lugar en el texto, y con los límites del IGN se sabe en qué distrito, provincia o departamento cae una coordenada. |
| 50 | Consola de lugares (/admin/) → Ubicación y correcciones de lugar | cada corrida, solo con DEPLOY_TARGET=cloudflare | **correcciones vigentes.** Con Cloudflare, el pipeline pide GET /api/geo/overrides (20 s de plazo) y aplica la última corrección de cada nota. Con GitHub Pages no hay consola y este paso no ocurre. |
| 51 | Publicación anterior (data/ en vivo) → Ubicación y correcciones de lugar |  | **correcciones anteriores.** Si la consola no está o no responde, se usan las de geo/overrides.json de la publicación anterior; si tampoco se lee, no se aplica ninguna (siguen guardadas en D1). |
| 52 | Ubicación y correcciones de lugar → Escritura y validación de la publicación |  | **notas, grupos y alertas.** Pasan el histórico tal como se guardó y, con los lugares corregidos, items.csv, los grupos de 14 días, los avisos de 7 días para feed.json y los archivos geo/ para la consola. |
| 53 | Publicación anterior (data/ en vivo) → Escritura y validación de la publicación |  | **copias y noticias anteriores.** Si una fuente no respondió, se vuelve a publicar la copia archivada que tenía la publicación anterior. Si la lectura de noticias falló, se reusan sus news/ y geo/ con carriedFrom. |
| 54 | Lectura de fuentes oficiales → Registro de incidencias |  | **fallos, arrastres y formato.** Se anotan unreachable (error si la fuente es crítica), format-drift, format-changed, carried-forward y communique-unread, outlook-unread (la perspectiva del comunicado no se pudo leer) e informe-* (el informe técnico no se bajó, no se pudo leer o una parte no pasó la validación; si no responde ninguna ruta es solo una advertencia). |
| 55 | Series, estados y señal GRD → Registro de incidencias |  | **datos vencidos y estados.** Se anotan stale-&lt;serie> y stale-weekly (dato fuera de plazo), official-overdue (no llegó el boletín previsto de NOAA o del ENFEN), newer-communique-unparsed (hay un comunicado más nuevo que no se pudo leer), status-unknown (error: no hay estado del ENFEN), informe-icen-mismatch (el ICEN del informe técnico difiere del IGP) y late-&lt;dato> (pasó la fecha en que debía llegar el siguiente). |
| 56 | Rama data-peru → Registro de incidencias | cada corrida de observatory.yml | **salud de la copia del Perú.** Al empezar, el pipeline lee index.json y heartbeat.json de data-peru y anota relay-missing, relay-stale (más de 36 h), relay-sources-down, relay-goal-missed o relay-token-expiring. Así un equipo apagado se vuelve issue. |
| 57 | Rama data-n8n → Registro de incidencias | cada corrida de observatory.yml | **salud de la copia de n8n.** Lo mismo con data-n8n: relay-n8n-missing, relay-n8n-stale (más de 36 h) o relay-n8n-sources-down. Así un flujo de n8n detenido se vuelve issue. |
| 58 | Noticias y alertas: lectura y filtro → Registro de incidencias |  | **noticias e histórico.** En la etapa de noticias se anotan feeds-reader-unknown, news-degraded, news-history-missing (error si tampoco hay copia), news-history-restored y news-history-large. También pasan a issues. |
| 59 | Ubicación y correcciones de lugar → Registro de incidencias |  | **correcciones fallidas.** Se anotan overrides-http (la consola respondió con error), overrides-down (no respondió) y overrides-rejected (una corrección trae códigos inválidos). |
| 60 | Registro de incidencias → Escritura y validación de la publicación |  | **incidencias y salud.** Las incidencias, la peor severidad y los conteos van a run-report.json; health.json marca degraded (con error o critical) y dashboard.json guarda la peor severidad. |
| 61 | Registro de incidencias → Despliegue y verificación |  | **crítico: no se despliega.** Con --fail-on critical, si la peor severidad es critical el paso del pipeline sale con 1, el build falla y el despliegue no corre; sigue publicado el sitio anterior. |
| 62 | Escritura y validación de la publicación → Archivos publicados (data/) |  | **reemplazo atómico de data/.** Si la validación pasa (mismo publicationId en todo, series ordenadas, dashboard con official, series y grd), public/data se reemplaza de una vez por la carpeta nueva. |
| 63 | Archivos publicados (data/) → Despliegue y verificación |  | **public/ listo para probar.** Con data/ escrita, el build adapta las direcciones del sitio, corre las pruebas de navegador en Chromium y sube el sitio; si falla uno de esos pasos, no se despliega. |
| 64 | Despliegue y verificación → Sitio en vivo (SITE_URL) | tras cada build exitoso | **publica y verifica en vivo.** Sube todo el sitio de una vez a GitHub Pages o Cloudflare Pages, y verify_live espera hasta 10 min a que dashboard.json y manifest.json traigan el publicationId nuevo. |
| 65 | Sitio en vivo (SITE_URL) → Publicación anterior (data/ en vivo) | en la corrida siguiente | **hoy es la anterior de mañana.** Lo que el sitio sirve hoy en data/ es lo que la corrida siguiente lee con --previous para arrastrar datos y seguir el histórico. |
| 66 | Sitio en vivo (SITE_URL) → Sitio web (10 vistas) |  | **sirve páginas y datos.** El hosting entrega index.html, assets/ y data/. La página pide primero dashboard.json y luego cada archivo con el mismo publicationId. |
| 67 | Público → Sitio web (10 vistas) |  | **abre el sitio o descarga.** Cualquier persona abre la página o baja directamente los CSV y JSON de data/; desde cada dato puede ir a la fuente en vivo o a la copia archivada. |
| 68 | Actualización diaria (observatory.yml) → Job archive | cada corrida de main cuyo build pasa | **tras build exitoso en main.** El build deja el artefacto raw-sources (7 días) con las respuestas originales nuevas y el histórico de noticias; el job archive lo baja en paralelo al despliegue. |
| 69 | Job archive → Rama data-archive | tras cada build exitoso en main | **solo agrega, nunca borra.** Agrega las respuestas que no tenía, suma las notas del día y une el histórico con merge_history.py. Rechaza commits con borrados e intenta el push hasta 3 veces. |
| 70 | Archivos publicados (data/) → Issues de incidencias (incidente-datos) | al final de cada corrida, aunque falle | **run-report a issues.** El job incidents baja run-report.json y abre, actualiza o cierra un issue por huella. Si build, deploy o archive fallan, abre además «La actualización diaria falló». |
| 71 | Issues de incidencias (incidente-datos) → Mantenedores y propietario |  | **avisos para revisar.** Los mantenedores ven las incidencias abiertas con la etiqueta incidente-datos; se cierran solas cuando el problema deja de aparecer. |
| 72 | Sitio en vivo (SITE_URL) → Vigilante de GitHub (watchdog.yml) | 19:17, 01:17, 07:17 y 13:17 Lima | **lee dashboard.json.** Cada 6 horas pide data/dashboard.json sin caché y calcula la edad de la publicación con generatedAt. |
| 73 | Vigilante de GitHub (watchdog.yml) → Actualización diaria (observatory.yml) | solo si el sitio está atrasado | **relanza si pasa 30 h.** Si la publicación tiene más de 30 h o no se puede leer, lanza la actualización diaria, salvo que haya una en curso o una lanzada a mano o por él en las últimas 6 h. |
| 74 | Vigilante de GitHub (watchdog.yml) → Issues de incidencias (incidente-datos) | si hay atraso o se recupera | **issue «sitio desactualizado».** Abre o comenta «El sitio publicado está desactualizado» con la acción tomada y lo cierra cuando el sitio vuelve a estar al día. |
| 75 | Sitio en vivo (SITE_URL) → Vigilante n8n (fuera de GitHub) | cada 6 h (intervalo de n8n) | **lee manifest.json.** Cada 6 horas, desde fuera de GitHub, n8n pide data/manifest.json y revisa que generatedAt tenga menos de 30 h. |
| 76 | Vigilante n8n (fuera de GitHub) → Colega que opera n8n |  | **Error workflow, si lo hay.** Si el colega configuró un Error workflow en n8n (por ejemplo, un correo), una ejecución fallida lo dispara. Sirve aunque GitHub haya apagado sus flujos programados. |
| 77 | Archivos publicados (data/) → Consola de lugares (/admin/) | al abrir la consola | **notas por revisar.** La consola carga data/geo/items.json (hasta 4000 notas de 120 días) y ubigeo.json para sus selectores; la API también usa ubigeo.json para rechazar códigos desconocidos. |
| 78 | Mantenedores y propietario → Revisores de lugares |  | **cuentas de revisor.** tools.geo_users crea usuario y clave para cada revisor; el propietario carga el secreto GEO_USERS y vincula la base D1 GEO_DB en Cloudflare. |
| 79 | Revisores de lugares → Consola de lugares (/admin/) |  | **corrigen lugares.** Con su usuario fijan, confirman o marcan como nacional o «no es del Perú» cada nota. Cada cambio es una fila nueva en la base D1 y se aplica en la siguiente corrida (la de 23:37 u otra antes). |
| 80 | Mantenedores y propietario → Actualización diaria (observatory.yml) | al fusionar o a mano | **fusión en main o a mano.** Cada push a main publica enseguida (salvo cambios solo en .md o docs/). También se puede lanzar a mano y elegir si se piden copias nuevas al Internet Archive. |
| 81 | Mantenedores y propietario → Herramientas de desarrollo |  | **PR, ramas claude/** o a mano.** ci.yml corre en cada PR y push a claude/**; n8n.yml, cuando cambia n8n/. Sondeos y capturas: a mano o al cambiar su herramienta en claude/**. Sus resultados se traen a mano de las ramas bot/. |

</details>

<details><summary>Las 44 cajas del diagrama completo, en texto</summary>

**1 · Fuentes**

| Caja | Qué es y qué hace | Detalle |
|---|---|---|
| **ENFEN e IGP: fuentes oficiales del Perú** | El comunicado oficial del ENFEN (portal y su réplica en la DHN de la Marina), que trae el estado de alerta El Niño o La Niña Costero, y el ICEN mensual del IGP. | 3 URL del ENFEN: wp-json y /comunicados/ las baja el Perú (su DNS no resuelve desde EE. UU.); sin esa copia, Actions hace un solo intento. La réplica de la DHN es abierta. La API se quedó en el N° 13-2026 (desde el 14 el ENFEN publica solo el PDF en el listado): su entrada es apenas un candidato, se contrasta con el listado del portal o de la DHN y se sondean los números siguientes al último conocido mientras aparezcan (hasta 6; dos ausencias seguidas cortan). ICEN: http abierto (actions+n8n); el https, igual que el portal del ENFEN. Se piden primero (OFFICIAL_FIRST). Solo el ENFEN usa Save Page Now. |
| **NOAA (CPC y PSL)** | 14 productos de NOAA: OISST semanal y mensual, RONI, ONI, SOI, presión en Tahití y Darwin, vientos a 850 hPa, contenido de calor y la discusión ENSO en HTML (CPC), y ERSSTv6 Niño 1+2 y 3.4 (PSL). | Críticos: cpc-wksst, cpc-roni y cpc-ensodisc. Si uno falla y no hay dato anterior, la corrida termina en critical y no se despliega. Las 14 URL son abiertas (actions+n8n). |
| **Alertas oficiales de peligros (13 fuentes)** | Avisos del COEN del INDECI, del SENAMHI (Telegram y 3 capas en GEOSINPAD), focos de calor de NASA FIRMS, sismos del USGS, boletines de la DHN, mensajes del PTWC y alertas volcánicas del IGP (CENVUL). | Son 13 de los 167 feeds (los que tienen covers): indeci-coen, senamhi-quebradas, senamhi-hidrologicos, senamhi-incendios, senamhi-telegram, firms-focos, usgs-sismos, dhn-tsunamis, dhn-avisos, ptwc-mensajes, ptwc-wepa40, igp-cenvul-boletines, igp-cenvul-alertas. Abiertas (actions+n8n). Se omiten los simulacros de la DHN y del COEN. Los PDF de boletines de la DHN tienen verificación antirobots y no se piden. En la última medición el robots.txt del INDECI dio 5xx (estado down). |
| **Páginas del Estado solo para archivo** | Web del SENAMHI, el GeoServer IDESEP, el SNIRH de la ANA, dos páginas del IMARPE y el catálogo del CENEPRED. Se guardan como respaldo; el pipeline todavía no las interpreta. | 12 URL de la lista fija del recolector del Perú. 6 no responden desde EE. UU. y solo las baja el Perú (4 de www.senamhi.gob.pe y 2 de la ANA, suspected-geoblock). Las otras 6 (IMARPE, CENEPRED, observatorio del SENAMHI, IDESEP) son abiertas o sin medir y n8n también las baja. La corrida diaria no las pide porque no tienen lector; el sondeo semanal sí las mide. feed.json solo muestra cuántas bajó el Perú. |
| **Medios y Estado: 116 feeds de noticias** | Feeds RSS del Estado (33, sobre todo búsquedas en gob.pe), medios nacionales (14), medios regionales de 19 departamentos (27), radios (37, 27 de RPP) e internacionales (5). | Medios generales (Andina incluida): la nota cuenta si habla del ENSO o trae el peligro en el titular. Medios locales, del Estado y feeds de peligros del Perú: basta un peligro. Feeds temáticos del mundo: si no tratan del ENSO, solo si nombran al Perú. 2 feeds (Noticias ONU y Sin Rodeos Cajamarca) prohíben robots y se leen como lector de feeds, solo desde Actions. El robots.txt de gob.pe solo prohíbe /admin/ y las URL con sheet=. |
| **Google Noticias: 38 búsquedas** | Búsquedas RSS por departamento (25), nacionales (2), mundial (1) y de medios sin feed propio (10, como El Peruano, Radio Nacional o TV Perú). _como mucho cada 20 h._ | El robots.txt de news.google.com prohíbe estos feeds. Desde la decisión del 21-10-2026 se leen como un lector de feeds: solo en corridas de main con --reader-state, un intento y como mucho una vez cada 20 h. n8n y el Perú no los piden. |
| **robots.txt de cada servidor** | Las reglas que cada sitio publica para los robots. El observatorio las lee según la RFC 9309 y no pide lo que prohíben, salvo 40 feeds de noticias que lee como lector, cada 20 h o más. | Gana la regla más larga y un empate lo gana Allow. Los leen en vivo el sondeo semanal, el recolector del Perú y la escalera de extracción: si el robots.txt da 5xx, no responde o trae una verificación antirobots sin código 4xx, no le piden nada a ese servidor; un 4xx, aunque sea una verificación, cuenta como «todo permitido» (RFC 9309), y la verificación que aparezca después se anota, nunca se evade. La corrida diaria y n8n no los leen: siguen el registro. |
| **Armado del registro** | Junta los catálogos del código (167 feeds, 16 fuentes ENSO y 12 páginas del Perú) con las mediciones y decide el estado y los canales de cada URL. | Regla: peru-server si y solo si la URL está geobloqueada o lo parece; sin canales si robots.txt la prohíbe, salvo los 40 reader (solo actions, cada 20 h o más); en lo demás, actions y n8n, menos la red que no responde cuando la otra sí. tools.build_registry --check falla si el archivo no está al día y una prueba lo exige. |

**2 · Recolectores**

| Caja | Qué es y qué hace | Detalle |
|---|---|---|
| **Registro de fuentes (registry/)** | Lista única de qué se descarga y quién lo pide: sources.json da el canal de cada URL (Actions, n8n o Perú) y reachability.json guarda las mediciones de alcance. _198 URL: 149 Actions y n8n, 40 solo Actions, 9 solo Perú._ | 195 fuentes y 198 URL: 149 actions+n8n, 40 solo actions (feeds reader), 9 solo peru-server. Estado por URL: open 144, robots-disallowed 40, suspected-geoblock 9, unknown 4, down 1. reachability.json: 311 URL medidas desde Actions y n8n, todavía ninguna desde el Perú, así que ningún geobloqueo está confirmado. Generado el 21-10-2026 a las 05:15 UTC. |
| **Recolector en el Perú** | Programa en una computadora dentro del Perú que cada noche baja lo que no responde fuera del país (portal del ENFEN, SENAMHI, ANA, ICEN por https) y lo sube a la rama data-peru. _21:00 Lima; reintentos hasta las 23:30._ | Tarea programada (Windows, macOS o Linux): 21:00 Lima, reintentos cada 30 min hasta las 23:30 y al encender; solo recolecta si falta la copia de esa noche. 16 URL (15 de su lista fija y el ICEN https del registro) más los PDF del ENFEN (comunicados y los dos últimos informes técnicos, hasta 20 MB). Usa el mismo clasificador de alcance (reach.py), respeta robots.txt en vivo, no guarda páginas antirobots, conserva 72 h la última copia buena, 25 min de plazo y mide hasta 60 URL sin medición del Perú. Avisa en el escritorio tras 2 fallas o si el token vence en menos de 21 días. |
| **Recolector n8n (nube AWS)** | Flujo de n8n en AWS que cada noche baja las 149 URL que el registro asigna a n8n y deja una segunda copia en la rama data-n8n, por si GitHub Actions no obtiene respuesta. _22:50 Lima · 149 URL._ | Flujo «ENSO · Recolector n8n (fuentes no bloqueadas)», 22:50 Lima (cron 50 22 * * *, zona America/Lima). Lee el registro de main o la copia incluida al construir. Omite las URL sin canales, las robots-disallowed, las reader y las solo peru-server. Baja todo su alcance cada noche, falle o no Actions. Una URL a la vez (40 s), segunda pasada tras 30 s, sigue los PDF del ENFEN, conserva 72 h la copia buena. Su nodo «Avisar al sitio» (enso-refresh) viene desactivado. |
| **Descarga en GitHub Actions (Fetcher)** | Pide cada fuente desde servidores de GitHub en EE. UU. y anota canal, URL, fecha y sha256. Si falla, busca la copia más reciente del Perú o de n8n, luego la réplica y al final el Internet Archive. _23:37 Lima · 8 min para las oficiales._ | Canales: direct, mirror, relay-peru, relay-n8n, archive, archive-fresh. Fuentes oficiales: 8 min en total, 5 min por pedido, 3 intentos, 0,8 s entre pedidos al mismo servidor; servidor con 3 fallos: 1 intento, con 5: se omite. Noticias: 8 hilos, en serie por servidor, 60 s por feed, 10 min para empezar. URL que el registro no da a actions: se lee la copia y, solo si no hay, se hace un intento directo. Abre data-peru (hasta 7 días) y data-n8n (hasta 72 h). No usa navegador ni lee robots.txt durante la corrida. |

**3 · Copias y respaldo**

| Caja | Qué es y qué hace | Detalle |
|---|---|---|
| **Rama data-peru** | Copias que sube el recolector del Perú: index.json, files/ y heartbeat.json, que distingue un equipo apagado de unas fuentes caídas. _vale hasta 7 días; aviso a las 36 h._ | Formato enso-relay/1. Cada subida reemplaza el contenido y el historial de git guarda las anteriores. El pipeline usa copias de hasta 7 días con estado 200 y sha256 verificado, y avisa a las 36 h. Si nada respondió, solo se sube el latido «sin-fuentes». |
| **Rama data-n8n** | Copias de n8n en el mismo formato enso-relay/1. Cada corrida es un commit sin padre que reemplaza la rama: solo guarda la última. _vale hasta 72 h; aviso a las 36 h._ | index.json y heartbeat.json se publican siempre, aunque nada responda. El pipeline acepta copias de hasta 72 h (canal relay-n8n) y avisa a las 36 h. |
| **Internet Archive (Wayback)** | Último respaldo de red: la copia archivada más reciente de una URL oficial. Para el comunicado del ENFEN también pide una copia nueva (Save Page Now) si la existente tiene más de un día. | Consulta CDX y baja la copia con estado 200 sin cambios (id_). Busca los PDF del ENFEN por prefijo (hasta 4 copias). Save Page Now solo con ENSO_ARCHIVE_SAVE=1, que vale en todas las corridas salvo una manual con archive_save desmarcado. Las noticias nunca lo usan. Pasados los 8 min de las fuentes oficiales ya no se consulta. |
| **Caché de Actions: feeds reader** | Archivo reader-state.json en la caché de GitHub Actions con la última vez que se pidió cada uno de los 40 feeds reader y sus notas todavía no publicadas. | Solo en main: se restaura la clave enso-reader-state-* más reciente y se guarda al final aunque la corrida falle. Mínimo 20 h entre pedidos; notas guardadas hasta 14 días. Fuera de main esos feeds no se piden. |
| **Publicación anterior (data/ en vivo)** | Lo que publicó la corrida anterior, leído por HTTP desde el sitio en vivo. Da el último dato válido de cada fuente, el histórico de noticias, el estado de los feeds y las correcciones de lugar. | --previous ${SITE_URL}data. Lee sources/&lt;id>.json, news/items.jsonl y news/feeds.json (3 intentos), geo/overrides.json y archive/sources/. Distingue ok, missing (404/410) y unreachable. El tope de 8 min de las fuentes oficiales no las corta, pero las de sources/ consumen ese tiempo. |
| **Rama data-archive** | Corpus permanente de respuestas originales por fuente, fecha y sha256, más la copia completa del histórico de noticias. Solo crece: nunca borra. | sources/&lt;fuente>/&lt;día>-&lt;sha12>.&lt;ext>, sources/news/&lt;día>.jsonl y sources/news/items.jsonl.gz. Solo la escribe el job archive en main. El pipeline solo lee de vuelta items.jsonl.gz; el job archive baja sources/news/ para agregarle. |
| **Datos de referencia: lugares y umbrales** | Archivos fijos en el repositorio: UBIGEO del INEI, límites distritales del IGN, departamentos del INDECI, las 8 categorías ICEN del ENFEN (2024) y la tabla de umbrales del equipo GRD. | ubigeo.json (1891 distritos), limites-ign.json.gz (polígonos de 1873 distritos, más provincias y departamentos, límites de 2020), departamentos.geojson (25). Se arman a mano con tools.build_ubigeo, tools.build_limites y (departamentos) tools.scrape_ladder, no en cada corrida. ICEN: Nota Técnica ENFEN 01-2024. La tabla GRD es un borrador transcrito de una imagen recibida el 06-08-2026, no un sistema oficial. |

**4 · Pipeline diario**

| Caja | Qué es y qué hace | Detalle |
|---|---|---|
| **Lectura de fuentes oficiales** | Pasa cada respuesta a su lector, valida rangos y compara la huella del formato con la de la publicación anterior. Busca el último comunicado del ENFEN y lee su PDF. Si una fuente falla, reutiliza su último dato válido. | acquire, feeds/cpc.py, feeds/peru.py y enfen_latest. ENFEN, ICEN y la discusión ENSO van primero. Del PDF saca número, estado (Alerta, Vigilancia, No activo), nivel, fechas y resumen. Un dato reutilizado se marca carried con su fecha real. Códigos: format-drift, format-changed, unreachable, carried-forward, probe-found, communique-unread. Del comunicado también lee la perspectiva por región (magnitud y hasta cuándo). Con el comunicado nuevo baja una vez su informe técnico (reports.py; portal, réplica de la DHN, copia del Perú o Internet Archive), elegido por fecha y no por número: ICEN temporal y probabilidades mensuales, validados con esquema, sumas al 100 %, saltos y el ICEN del IGP, con la página y la cita de origen; si falla, conserva el último bueno (enfen-informe). Un modelo de lenguaje opcional (ENSO_LLM_EXTRACT_URL) solo deja una propuesta para revisión. |
| **Series, estados y señal GRD** | Arma 20 series con último valor y antigüedad (17 con categoría), el semanal por región Niño, los estados de ENFEN y NOAA y la señal GRD: normal, amarillo, rojo, sin clasificar o sin dato. | Builder y signals.py. Evento costero: ICEN sobre +0,5 o bajo −0,7 al menos 3 meses seguidos. Las categorías, los estados y la señal GRD salen de Python; el navegador solo agrega ayudas de lectura: colores por umbral o por signo (franja semanal ±0,5, escala del mapa de −2 a +4 °C, minigráficos, áreas de los gráficos y valor del viento), la dirección del viento y N/D si el dato semanal tiene más de 16 días. La termoclina D20 no tiene fuente y siempre sale «na». freshness.py da a cada dato su vigencia (al día, atrasado, vencido, sin dato) según el calendario de su institución y la agrupa por vista en dashboard.json. |
| **Noticias y alertas: lectura y filtro** | Lee los 167 feeds, guarda solo las notas sobre el ENSO o sobre un peligro en el Perú, las etiqueta con 13 tipos de peligro y ubica cada una en su lugar. | feedparse lee RSS, Atom, JSON Feed y listados de gob.pe; hazardparse convierte USGS, DHN, PTWC, CENVUL, Telegram, ArcGIS, COEN y FIRMS. Descarta empleo, accidentes, sismos menores de 4 y los simulacros de la DHN y del COEN. Feeds reader: como mucho cada 20 h. Si toda la lectura falla, se usan las alertas de la publicación anterior y las 13 fuentes figuran como no leídas, para que el silencio no parezca calma. |
| **Histórico de noticias (solo anexar)** | Toma el histórico de la publicación anterior y le agrega al final las notas nuevas, sin borrar nada. Si le faltan notas, las completa con la copia de data-archive. | news/items.jsonl, una nota por id (sha256 del enlace y el titular). Si no puede leerlo ni rehacerlo, publica solo las de hoy marcado «restarted». Aviso news-history-large a los 20 MiB (Cloudflare sirve hasta 25 MiB por archivo). |
| **Ubicación y correcciones de lugar** | Vuelve a ubicar todo el histórico con las reglas actuales y aplica las correcciones de la consola (solo con Cloudflare), que tienen la última palabra. Luego agrupa las notas de los últimos 14 días. | geo.py, limites.py, geopoly.py y geo_overrides.py. Confianza de 0,35 a 0,97 (1 con set o confirm); se publica desde 0,5 y va a revisión lo menor a 0,8. Acciones: set, confirm, none y foreign; gana el rev mayor. Grupos: 3 palabras en común y 60 % del titular más corto. |
| **Registro de incidencias** | Cada etapa anota sus problemas con severidad (info, warning, error, critical), fuente, código y una huella. Si una fuente crítica no tiene dato ni anterior, la corrida es critical y no se despliega. | Incluye la salud de las copias: relay-missing, relay-stale (más de 36 h), relay-sources-down, relay-goal-missed (falta el PDF del comunicado o del informe más reciente), relay-token-expiring (menos de 21 días) y relay-n8n-missing, -stale y -sources-down. Huella: sha1 de fuente\|etapa\|código. |
| **Escritura y validación de la publicación** | Escribe todos los archivos de data/ en una carpeta temporal con un publicationId común, valida que sean coherentes y reemplaza public/data de una sola vez. Si la validación falla, queda la publicación anterior. | write_publication y validate_publication. También arma feed.json con sourcefeed.build sin descargar nada, con el estado de las 13 fuentes de alertas, y guarda en raw/ las respuestas nuevas para data-archive (archive_raw). |

**5 · Publicación y sitio**

| Caja | Qué es y qué hace | Detalle |
|---|---|---|
| **Archivos publicados (data/)** | Lo que se publica: dashboard.json, series y CSV, estado de las 16 fuentes, feed.json, news/, geo/, run-report.json, manifest.json y data/archive/ con las copias archivadas. | Cada JSON propio (no las copias de terceros) lleva schema observatorio-enso/4, publicationId y generatedAt. data/archive/: respuesta original y PDF de cada fuente oficial (archive/sources/), cada feed bajado (archive/feeds/) y una página por día de noticias (60 días); máx. 20 MiB por copia. geo/items.json: 120 días, máx. 4000 notas. |
| **Despliegue y verificación** | Adapta el sitio a su dirección, lo prueba en Chromium, lo publica en GitHub Pages (por omisión) o Cloudflare Pages y comprueba que el sitio en vivo ya sirve la publicación nueva. | prepare_site.py (con Cloudflare quita los enlaces al repositorio y escribe _headers), pytest -m browser, deploy-pages o wrangler (que sube también functions/), verify_live cada 20 s hasta 10 min. El destino lo fija la variable DEPLOY_TARGET; con Cloudflare, cloudflare_pages.py crea el proyecto si falta. |
| **Sitio en vivo (SITE_URL)** | La dirección pública que sirve el sitio y su carpeta data/. Por omisión es https://pillb.github.io/observatorio-enso-peru/. | Con Cloudflare: &lt;proyecto>.pages.dev o SITE_URL, más /api/geo/* y CORS abierto en /data/*. Lo leen el público, la corrida siguiente, verify_live, los dos vigilantes y la consola. Qué destino está activo depende de una variable del repositorio que no está en el código. |
| **Sitio web (10 vistas)** | Página estática sin compilación: Resumen, El Niño Costero, Pacífico, Océano y atmósfera, Mapa, Historia, Noticias, Datos, Metodología y Asistente. Junto a cada dato enlaza la fuente en vivo y la copia archivada. | Carga primero dashboard.json; su publicationId es la referencia y no muestra archivos de otra publicación. Avisa si la publicación tiene más de 36 h o si worst es error o critical. El Asistente usa reglas fijas, no un modelo de lenguaje. Metodología muestra el diagrama simplificado y, con un botón, el completo (copias de docs/). |
| **Público** | Personas, equipos de gestión del riesgo y usuarios de datos abiertos que abren el sitio o descargan los CSV y JSON de data/. |  |
| **Consola de lugares (/admin/)** | Página para revisores con su API en Cloudflare (Pages Function) y una base D1, donde se confirma o corrige el lugar de cada nota. Cada cambio queda con usuario y hora. | /api/geo/*: login, corrections, audit y overrides (pública, sin usuarios ni comentarios). Base D1 GEO_DB (nunca borra correcciones) y secreto GEO_USERS con hashes PBKDF2; tools.geo_users crea un admin y revisor01 a revisor10, y el propietario carga el secreto en el panel. Solo funciona con Cloudflare; en GitHub Pages la página existe pero no tiene API. |
| **Revisores de lugares** | Personas autorizadas que en la consola revisan las notas dudosas (p. ej. confianza menor a 0,8) y fijan, confirman o descartan su lugar. |  |

**6 · Operación, vigilancia y personas**

| Caja | Qué es y qué hace | Detalle |
|---|---|---|
| **Sondeo semanal de alcance** | probe-sources.yml mide desde Actions qué URL del registro responden, con las mismas clases que usan n8n y el Perú, suma lo que ellos midieron y regenera el registro. _lunes 04:17 Lima._ | Lunes 04:17 Lima (cron 17 9 * * 1), a mano o al cambiar el medidor en ramas claude/**. Lee robots.txt antes de medir. Clases: ok, empty, http-403, http-4xx, http-5xx, timeout, connect, dns, tls, challenge, robots; una verificación antirobots se anota y nunca se evade. Las mediciones del flujo de validación de n8n (su CSV, o el JSON que deja n8n.yml los lunes) entran a mano con --import. En main hace commit de registry/; en otras ramas va a bot/registry/&lt;rama>. |
| **Kit y verificación del recolector** | recolector-kit.yml arma un .zip con el código, los instaladores y una copia de respaldo del registro, lo instala de prueba en Windows, macOS y Linux y lo publica en la versión recolector-kit. VERIFICAR revisa el equipo. | Se publica al fusionar en main cambios del kit, del recolector, de python/enso/, de config/ o de registry/. El commit semanal del registro no lo dispara (lo sube el bot con el token de Actions); no hace falta, porque el recolector lee el registro de GitHub y la copia del kit solo se usa cuando no puede leer el de GitHub (sin token, una respuesta distinta de 200, otro esquema o sin respuesta); avisa si esa copia tiene más de 14 días. El equipo no se actualiza solo: un kit nuevo se instala con ACTUALIZAR. VERIFICAR (collector_check.py) revisa Python, git, token, acceso a las fuentes, la tarea programada y la edad de la última copia en data-peru (aviso a las 36 h); con --probar-tarea dispara la tarea real. |
| **Job archive** | Tras un build exitoso en main, agrega a data-archive las respuestas originales nuevas y une el histórico de noticias. Rechaza cualquier commit que borre archivos. | Baja el artefacto raw-sources (7 días). No repite fuente + sha12. merge_history.py: una nota por id, límite 90 MiB. 3 intentos de push. Corre en paralelo con el despliegue. |
| **Actualización diaria (observatory.yml)** | El único flujo que publica el sitio: corre pruebas, prepara las copias, ejecuta el pipeline, despliega y archiva. Si algo falla antes del despliegue, sigue el sitio anterior. _23:37 Lima (04:37 UTC)._ | 23:37 Lima (cron 37 4 * * *, 04:37 UTC), al fusionar en main (salvo .md y docs/), a mano, por enso-refresh y a pedido del vigilante. Una corrida a la vez y una en espera (grupo enso-production-publication; la que está en curso no se cancela). Jobs: build 36 min (pipeline 26), deploy 15, archive, incidents y keepalive, que reactiva 3 flujos programados. |
| **Vigilante de GitHub (watchdog.yml)** | Cada 6 horas lee data/dashboard.json del sitio en vivo. Si tiene más de 30 h, relanza la actualización diaria y abre un issue; además reactiva 3 flujos programados. _19:17, 01:17, 07:17 y 13:17 Lima._ | 19:17, 01:17, 07:17 y 13:17 Lima (cron 17 */6 * * *). No relanza si hay una corrida en curso o una lanzada a mano o por él en las últimas 6 h. Reactiva observatory, watchdog y probe-sources para que GitHub no los apague tras 60 días sin actividad (el job keepalive del flujo diario hace lo mismo). Con Cloudflare exige la variable SITE_URL. |
| **Herramientas de desarrollo** | Flujos que no publican: pruebas (ci.yml, n8n.yml), sondeo de feeds candidatos, escalera de extracción, captura de fixtures y capturas por dispositivo. Dejan resultados en ramas bot/ y artefactos. | probe-feeds: 170 candidatos. scrape-ladder: 50 candidatos sin feed; prueba robots.txt, GET simple, cabeceras de navegador, Chromium y Firecrawl (si hay clave); consulta robots.txt también en cada redirección y en lo que carga la página (sin pedir imágenes) y se detiene ante cualquier verificación antirobots. device-screens: 16 dispositivos. n8n.yml prueba los flujos en n8n real y corre la validación de fuentes los lunes 08:17 Lima; ese cron no lo reactiva nadie. Ningún paso del pipeline diario los llama. |
| **Responsable del equipo en el Perú** | Instala el kit con un token de GitHub de grano fino (solo este repositorio), corre VERIFICAR, deja el equipo encendido a la hora de recolección y renueva el token cuando vence. |  |
| **Colega que opera n8n** | Importa los 3 flujos de n8n/dist (recolector, vigilante y validación) en su n8n de AWS, elige la credencial de GitHub y activa los programados; asignarles un Error workflow es opcional. |  |
| **Issues de incidencias (incidente-datos)** | Al final de cada corrida, el job incidents convierte cada aviso, error o falla crítica de run-report.json en un issue de GitHub, uno por huella, que se cierra solo cuando el problema desaparece. | tools.sync_issues ignora info y los códigos esperados (archive-channel, carried-forward, probe-found). Aparte hay dos issues fijos: «La actualización diaria falló» (build, deploy o archive fallan) y «El sitio publicado está desactualizado» (vigilante). |
| **Vigilante n8n (fuera de GitHub)** | Flujo de n8n que cada 6 horas lee data/manifest.json del sitio. Si no responde o tiene más de 30 h, la ejecución falla y avisa el Error workflow que se le asigne en n8n, aunque GitHub esté apagado. _cada 6 h._ | enso-n8n-vigilante.json. Dirección fija https://pillb.github.io/observatorio-enso-peru/: hay que cambiarla a mano si el sitio pasa a Cloudflare. No relanza nada en GitHub. |
| **Mantenedores y propietario** | Quienes fusionan en main, lanzan flujos a mano, eligen el destino del sitio, crean las cuentas de la consola y revisan los issues y los resultados de las ramas bot/. |  |

</details>

<!-- recorrido:fin -->

### Lo esencial

- **Tres recolectores leen la misma lista.** `registry/sources.json` dice
  quién pide cada URL. GitHub Actions baja casi todo a las 23:37; n8n en la
  nube baja cada noche (22:50) una segunda copia de todo lo que no está
  prohibido ni bloqueado, haya fallado Actions o no; el equipo en el Perú
  (21:00) baja lo que no responde fuera del país y el resto de su lista fija. La corrida diaria
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
  D1, y solo funciona con el sitio en Cloudflare (en GitHub Pages queda sin API).

## Pipeline (`python/enso/`)

| Módulo | Función |
|---|---|
| `fetch.py` | Descarga con reintentos, plazos de tiempo (no de tamaño: el tope de 5 MB por feed lo aplica `feedparse.py` al leer y el de 20 MiB por copia, `archive.py`) y respaldo en el Internet Archive (CDX y, si se activa con `ENSO_ARCHIVE_SAVE=1`, Save Page Now). El tiempo está acotado: conectar, 15 s; cada pedido, 5 min las fuentes oficiales y 1 min cada feed en total (el plazo del cliente es por lectura y un servidor que manda la respuesta de a pocos bytes no lo agota), sin reintento si se agota; cada servidor lleva la cuenta de sus fallos seguidos (un pedido sin respuesta suma uno, una respuesta que no termina a tiempo dos, una URL que solo recibió 429 o 5xx uno, y cualquier otra respuesta la pone en cero; Save Page Now lleva la suya): con 3 recibe un solo intento por URL, y con 5 ya no se le pide nada en la corrida; tras el último intento no se espera. Todas las fuentes oficiales juntas, 8 min (`OFFICIAL_BUDGET_S`), empezando por el ENFEN (listado y último comunicado), el ICEN y la ENSO Diagnostic Discussion (`OFFICIAL_FIRST`); pasado ese tiempo, las que falten siguen solo con las copias del Perú y de n8n o con su dato anterior (ya no se pide al Internet Archive). Una respuesta rota (gzip mal declarado, redirecciones sin fin) es una URL fallida más, no un error que detenga la corrida |
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
ninguna red de EE. UU. que la midió (GitHub Actions en Azure, n8n en AWS) y
además responde desde el Perú, o falla allá por bloqueo (403, tiempo,
conexión, desafío anti-robots o DNS) y aún no se midió desde el Perú; los
canales de la fuente son la unión. El pipeline lee el registro en cada corrida:

- una URL que el registro no da a Actions se lee de la copia del Perú o de n8n;
  solo si no hay copia se pide directo, una sola vez;
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
   registro no da a Actions se lee de esas copias y, solo si no hay, se pide
   directo una vez.
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
