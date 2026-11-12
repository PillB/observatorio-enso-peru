# Fiabilidad de las escrituras y de la red

Qué pasa con cada dato que el observatorio escribe o pide cuando la red se corta, cuando dos personas hacen lo mismo
a la vez o cuando un proceso se interrumpe a la mitad. Complementa [maquinas-de-estado.md](maquinas-de-estado.md)
(los estados del sitio) con lo que se guarda fuera del navegador: la base D1 de la consola, la rama `data-manual` en
GitHub y los pedidos del pipeline.

La pregunta de cada sección es la misma: **si esto se hace dos veces, o a medias, ¿qué queda?**

## Dónde se escribe

| Escritura | Dónde | Quién | Concurrencia | Si se repite | Si se corta a la mitad |
|---|---|---|---|---|---|
| Corrección de lugar | D1 `corrections` + `current` | revisores (`/api/geo/corrections`) | bloqueo optimista por revisión | se reconoce y se responde lo guardado (200) | el lote es una transacción: todo o nada |
| Subida de documento | GitHub `data-manual` + D1 `uploads` | administración (`/api/docs/upload`) | compare-and-swap de la rama, 3 intentos | se reconoce por sha256 y no hay commit nuevo | la subida se anota antes de pedir la actualización (bandeja de salida) |
| Pedido de actualización | GitHub `repository_dispatch` | la API de documentos | grupo de concurrencia de `observatory.yml` | inocuo: queda una corrida en espera | se vuelve a pedir al abrir la consola |
| Ingreso, sesión, contadores | D1 `sessions`, `attempts`, `audit` | la consola | `INSERT … ON CONFLICT DO UPDATE` atómico | cuenta otro intento (es lo que mide) | el lote es una transacción |
| Analítica de versiones y uso | D1 `ab_exp`, `uso_daily` | cada visita, al salir | suma atómica en la fila | se cuenta dos veces (ver abajo por qué se acepta) | una solicitud, un lote |
| Publicación del día | `public/data/` | pipeline | un flujo a la vez (`enso-production-publication`) | la misma entrada da la misma salida | se escribe en una carpeta temporal y se cambia de una vez |
| Cachés de la cosecha | archivos JSON | `cosecha_historico`, `build_historico` | un flujo por rama | se retoma desde el estado guardado | `write_atomic`: archivo temporal y `os.replace` |
| Copias crudas | rama `data-archive` | pipeline | solo ese flujo escribe ahí | `cp -n`: no reescribe lo archivado | un commit que borre algo no se sube |

## Patrones que se aplican

### Bloqueo optimista (correcciones de lugares)

Cada corrección dice sobre qué revisión de la nota se hizo (`expectedRev`). La API lee la revisión vigente
(`current.rev`) y escribe la siguiente en un lote; la restricción `UNIQUE (item_id, rev)` hace de compare-and-swap
cuando dos escrituras leyeron la misma revisión: la segunda anula todo su lote (corrección, fila vigente, contador y
registro). No hay candados que se queden puestos si un Worker muere, y D1 no los ofrece entre solicitudes.

Cambios de esta revisión:

- **`expectedRev` es obligatoria (428).** Antes, un envío sin ella se aceptaba sobre cualquier revisión: una
  escritura a ciegas que pisaba la de otro revisor sin enterarse (actualización perdida). La consola siempre la
  mandaba; ahora la API también lo exige, para cualquier otro cliente (un script, n8n).
- **El 409 trae la revisión vigente** (`current`), quién la hizo y cuándo. La consola rehace la tarjeta con ella sin
  volver a pedir la lista entera (esa lista tiene un tope de 5 000 notas: una nota fuera de él quedaba en un 409
  sin salida).

### Idempotencia (los dos POST de la consola)

Una solicitud cuya respuesta se pierde (la red móvil se cae, el Worker responde tarde) deja a la persona sin saber
si se guardó. Repetirla tiene que ser seguro.

- **Correcciones.** Si la fila vigente es exactamente el cambio que llega (misma persona, acción, lugares y nota) y
  está una revisión por encima de la esperada, es el mismo envío repetido: se responde 200 con lo guardado
  (`replayed: true`) en vez de un 409 falso «otra persona corrigió esta nota». Lo mismo si los dos envíos chocan en
  la restricción `UNIQUE` (dos pestañas, un doble clic que pasó el botón desactivado). No hace falta una
  `Idempotency-Key` ni una tabla nueva: el cambio mismo es la clave, y dos cambios idénticos de la misma persona
  sobre la misma revisión son, por definición, la misma intención. La consola repite una vez, tras una pausa corta y
  al azar, solo si `fetch` falló sin respuesta; un error con estado HTTP no se repite.
- **Subidas de documentos.** La clave es `(documento, sha256)`. Si D1 ya tiene esa subida con su commit, se
  responde 200 sin mandar nada a GitHub ni gastar el tope por hora. Si el commit se hizo pero D1 no llegó a anotarlo
  (la función se cortó), `commitUpload` ve el mismo archivo en el índice de la rama y no crea otro commit. La
  consola dice que volver a subir es seguro cuando la red se corta.

### Bandeja de salida (outbox) para pedir la actualización

Subir un documento son tres efectos en dos sistemas: el commit en GitHub, la fila en D1 y el `repository_dispatch`.
No hay transacción que los abarque. Antes el orden era commit → dispatch → D1, y un fallo de red en el dispatch
(una excepción de `fetch`, no un estado HTTP) respondía 500 **sin anotar** un commit que ya estaba en la rama; al
reintentar se creaba otro.

Ahora, como en el patrón *transactional outbox*:

1. El commit (idempotente, ver arriba).
2. Una sola transacción en D1 con la subida (`dispatched = 0`: el mensaje pendiente), el contador y el registro.
3. El dispatch. Si responde 204, `UPDATE … SET dispatched = 1 WHERE dispatched = 0`.
4. **Relevo:** cada vez que se abre la consola de documentos (`status`), las subidas de las últimas 24 h con
   `dispatched = 0` se piden en un solo envío. Pasadas 24 h ya las leyó la corrida diaria de las 23:37.

La entrega es «al menos una vez»: si la marca no llega a escribirse se pide otra vez, y eso no hace daño porque
`observatory.yml` tiene un grupo de concurrencia sin cancelación (una corrida en curso y, como mucho, una en espera).
No hay un proceso aparte que vacíe la bandeja: Pages Functions no tiene tareas programadas sin un Worker más, y la
corrida diaria es la red de seguridad.

### Reintentos con espera exponencial y azar

- **Pipeline (`enso/fetch.py`).** Ya reintentaba con espera exponencial, contaba fallos por servidor (tras 3 da una
  sola oportunidad por URL, tras 5 deja de pedirle: un cortacircuitos por corrida) y respetaba `Retry-After` en
  segundos. Ahora también entiende `Retry-After` como **fecha HTTP** (RFC 9110 §10.2.3), que antes se ignoraba y se
  reintentaba antes de lo pedido, y la espera exponencial lleva la mitad al azar («equal jitter»: entre la mitad y
  el total), para que dos corridas que fallan a la vez contra el mismo servidor no vuelvan al mismo segundo.
- **Correcciones vigentes para el pipeline (`enso/geo_overrides.py`).** Era un solo pedido: un 503 pasajero de
  Cloudflare dejaba la publicación del día con las correcciones de ayer. Ahora son hasta 3, con la misma espera, y
  solo para fallos de red, 429 y 5xx; un 4xx o un cuerpo que no es JSON es definitivo. Sin respuesta buena se usan
  las de la publicación anterior, como antes.
- **Commit de la rama `data-manual`.** El avance sin forzar (`force: false`) es un compare-and-swap: si otra subida
  movió la rama, GitHub responde 422 y se rehace sobre la nueva punta. Eran 2 intentos; ahora 3, con una pausa
  corta al azar entre ellos.

### Escrituras atómicas en disco

Ya estaban: la publicación se arma en una carpeta temporal, y los cachés de la cosecha y el estado de los feeds se
escriben en un archivo temporal que reemplaza al anterior con `os.replace`. Una corrida que se corta no deja un
archivo a medias. No se agrega `fsync`: los archivos viven en el disco efímero del runner y lo que importa se
sube por git, que sí verifica lo que guarda.

## Patrones que se revisaron y no aplican

- **Pool de conexiones.** D1 se usa a través de un *binding* de Cloudflare, no de una conexión TCP: no hay pool que
  administrar, y cada solicitud hace como mucho 3 viajes a la base (lo prueban `geo_console.test.mjs` y
  `doc_uploads.test.mjs`). Los `fetch` de un Worker a GitHub reutilizan conexiones por su cuenta. En Python, cada
  `Fetcher` tiene un solo `httpx.Client` para toda la corrida (keep-alive y pool por servidor), y las herramientas
  abren un cliente por ejecución con `with`. No se encontró ningún cliente creado por pedido en un bucle.
- **Candados pesimistas.** D1 no tiene `SELECT … FOR UPDATE` entre solicitudes, y un candado guardado en una tabla
  quedaría puesto si el Worker muere. La restricción `UNIQUE` y los lotes transaccionales cubren lo mismo sin ese
  riesgo.
- **Idempotencia y reintentos en la analítica (`/api/ab/e`, `/api/uso/e`).** Se envía con `sendBeacon` al
  ocultarse la página, una vez, sin reintentos: «como mucho una vez». Un reintento podría contar dos veces una visita
  y una clave de idempotencia exigiría un identificador por visita, que la medición evita a propósito (sin
  cookies ni identificadores). Perder un envío cuando la red se corta al cerrar la pestaña es aceptable para
  contadores agregados.
- **Topes diarios exactos.** `DAILY_CAP` (versiones) y `ROW_CAP` (uso) se leen y luego se escribe: dos envíos
  simultáneos pueden pasar el tope por unas filas. Son un freno para que una avalancha no gaste las 100 000
  escrituras diarias que comparten con la consola, no un límite contable; hacerlos exactos costaría una escritura
  condicional más por envío.
- **Tope de correcciones por hora.** Igual: se lee y se suma en el mismo lote de la corrección; dos correcciones
  simultáneas pueden pasar de 600 por una.
- **Colas o Durable Objects.** Resolverían el relevo de la bandeja de salida sin depender de que alguien abra la
  consola, pero agregan un Worker y un servicio de pago para un caso que la corrida diaria ya cubre.

## Pruebas

| Qué | Prueba |
|---|---|
| Sin `expectedRev` no se escribe (428) | `js/geo_console.test.mjs` «exige la revisión esperada…» |
| Repetir la misma corrección: 200, sin otra revisión ni escritura | `js/geo_console.test.mjs` «repetir el mismo envío…» |
| Carrera exacta (el otro escribe entre la lectura y la escritura) del mismo envío y de otro revisor | `js/geo_console.test.mjs` «dos envíos iguales…», «el 409 trae la revisión vigente…» |
| La respuesta se pierde en el navegador: un reintento, una sola revisión | `test_geo_console.py::test_a_correction_whose_reply_is_lost_is_retried_once_and_saved_once` |
| Subir dos veces el mismo PDF; commit hecho sin fila en D1 | `js/doc_uploads.test.mjs` «volver a subir…», «si el commit se hizo…» |
| Dispatch que falla: 201, fila pendiente, relevo al abrir la consola, una sola vez | `js/doc_uploads.test.mjs` «bandeja de salida…» |
| Dos choques seguidos en la rama | `js/doc_uploads.test.mjs` «aguanta varias subidas…» |
| `Retry-After` con fecha, espera con azar | `test_channels.py::test_retry_after_dates_and_jittered_backoff` |
| Correcciones vigentes: reintento, `Retry-After`, 4xx definitivo | `test_geo.py::test_overrides_retry_a_passing_failure_and_respect_retry_after` |

Las pruebas de carrera se comprobaron quitando cada arreglo: fallan sin él.

## Al agregar una escritura

Antes de agregar una ruta que escribe, responda: ¿qué pasa si la misma solicitud llega dos veces? ¿Si dos personas la
mandan sobre el mismo dato? ¿Si la función se corta entre dos efectos en sistemas distintos? Si hay un efecto
externo (GitHub, un correo), anote primero en D1 lo que falta hacer y márquelo hecho después.
