# Boletín de eventos El Niño

Una hoja con lo que pasa hoy por El Niño en el Perú: arriba el país (mapa por nivel, cuántos departamentos hay en
cada nivel y qué se viene), abajo los diez departamentos más críticos con qué podría pasar, cuándo y quién lo dice.
Está en la pestaña **Boletín** (`#/boletin`), sale en cada actualización diaria y es la misma que llega por correo.

La revisión de noviembre de 2026 (seis problemas por sección, con su arreglo y las fuentes) está en
[boletin-revision.md](boletin-revision.md).

Código:

| Archivo | Qué hace |
| --- | --- |
| `python/enso/boletin.py` | Arma `data/boletin.json` desde lo que ya publica el sitio: el mapa de alertas (`feed.json`), el ENFEN (`dashboard.json`) y el escenario del CENEPRED. También el correo (`data/boletin-correo.html`), el texto para WhatsApp, dos CSV y el canal Atom de ediciones (`data/boletin.xml`) |
| `python/enso/observatory.py` | Lo llama al final de la publicación; si falla, la publicación sigue sin boletín (`boletin-exception`) |
| `public/assets/js/boletin.js` | La pestaña. No calcula nada: presenta el JSON |
| `python/enso/boletin_img.py` | La imagen para compartir (`data/boletin.png`, 1200 × 630: mosaico, contadores, ENFEN y qué cambió) y su página con Open Graph (`data/boletin-compartir.html`), sin dependencias |
| `functions/_lib/boletin-subs.js` (`/api/boletin/*`) | La suscripción por correo: doble confirmación, preferencias, baja en un clic y la lista que lee n8n |
| `n8n/lib/boletin.js`, `n8n/nodes/boletin*.js` | Cuándo y a quién se manda el correo (flujos «ENSO · Boletín de eventos El Niño por correo» y «ENSO · Boletín: correo de confirmación de la suscripción») |
| `python/tests/test_boletin.py`, `python/tests/js/boletin-subs.test.mjs`, `n8n/test/boletin.test.mjs`, `n8n/test/e2e-boletin.sh` | Pruebas, con la publicación real del 10 de noviembre de 2026 (`python/tests/fixtures/boletin/`) |

## Qué se muestra y de dónde sale

| Parte | Fuente | Regla |
| --- | --- | --- |
| Color de cada departamento | Los avisos vigentes o próximos del mapa de alertas (SENAMHI, INDECI/COEN, DHN, ANA, IGP) | El nivel más alto que la **institución** le dio a un aviso de un peligro de El Niño: lluvias, huaicos, inundaciones, oleaje, sequía o emergencia. No se inventa ningún nivel: un aviso sin nivel queda gris, «sin nivel» |
| Rojo | Nivel 3 de la institución | Peligro alto: actuar según las indicaciones de las autoridades |
| Naranja | Nivel 2 | Peligro: prepararse |
| Amarillo | Nivel 1 | Estar atento |
| Verde | Sin avisos de El Niño vigentes | Que no haya aviso no quiere decir que no haya riesgo |
| Rayado | El aviso todavía no empieza | Se espera, aún no rige |
| Qué se viene | Estado del ENFEN y su comunicado | Las probabilidades salen **solo** de la tabla del informe técnico del ENFEN, con su página; si el informe está vencido o no se leyó, no se muestra ninguna |
| Riesgo de fondo | Escenario de riesgo por lluvias del CENEPRED | Distritos en riesgo muy alto y alto, sin cambios |
| Daños | Reportes del INDECI de las últimas 72 horas | Se cuentan, con su enlace |

Un mismo aviso del SENAMHI difundido también por el INDECI cuenta una vez («también INDECI»). Los avisos que no son de
El Niño (heladas, friaje, calor en la selva, volcanes) se cuentan aparte y no pintan el mapa.

### Orden de los departamentos

1. El nivel más alto de un aviso oficial vigente o próximo.
2. Si ese nivel rige ya o solo se espera.
3. Cuántos avisos tienen ese nivel.
4. Cuántos avisos relacionados con El Niño tiene en total.
5. Cuántos reportes de daños del INDECI hubo en 72 horas.
6. Qué parte de sus distritos el CENEPRED pone en riesgo muy alto.

El mismo orden está escrito al pie de la tabla y en el JSON (`order`).

### Tres formas (experimento A/B/C)

Cada visita ve una de tres formas, al azar y en partes iguales; quien elige una a mano la conserva. La analítica
anónima es la del mapa de alertas ([mapa-alertas](mapa-alertas.md)), experimento `boletin`: vistas, selecciones,
detalle y elección.

| Forma | Qué es |
| --- | --- |
| A · `mapa` | El mapa real del Perú, con la tabla de los diez debajo |
| B · `mosaico` | Un cuadrado por departamento (norte arriba, costa a la izquierda), que se lee igual en un celular y es el que va en el correo, porque Gmail no muestra SVG. Se recorre con las flechas |
| C · `ficha` | Ficha de impacto, armada con lo que hacen los mejores boletines (abajo): el estado del ENFEN en su escalera (No activo → Vigilancia → Alerta), «El boletín en 30 segundos», cuándo (hoy, próximas 24 h, 24 a 72 h, más adelante), qué hacer según el color y una tarjeta por departamento |

Las tres comparten: una frase de resumen arriba, contadores que filtran la tabla, la ficha del departamento elegido
(también con `#/boletin?dep=20`), los avisos vencidos atenuados, la nota de empate cuando hay más de diez en rojo y
«Qué hacer según el color» (orientación de INDECI y SENAMHI, nunca una alerta propia).

**De dónde sale la forma C.** El *ENSO Diagnostic Discussion* de la NOAA abre con el estado del sistema de alerta, una
sinopsis de una frase y la fecha de la próxima edición; la Met Office y la OMM (avisos basados en impactos) dicen,
por color, qué se espera y qué hacer; Meteoalarm junta los avisos oficiales sin crear niveles propios; el BoM de
Australia retiró en 2024 su «dial» de vigilancia/alerta porque se leía como pronóstico, por eso la escalera del ENFEN
se presenta como su estado oficial y no como una probabilidad. Detalle y enlaces en
[boletin-revision.md](boletin-revision.md#investigación).

### Impresión

«Imprimir o PDF» deja una sola hoja A4 con los diez primeros en las tres formas (dos con los 25). Las pruebas de navegador
lo comprueban con el PDF de Chromium.

## Ediciones y reglas de aviso

Cada actualización diaria compara con el boletín anterior. Si nada cambió, la edición sigue igual («sin cambios
desde …»); si algo cambió, sale una edición nueva con la lista de cambios y la regla de cada uno. `recent` guarda las
últimas 14 ediciones con sus cambios.

| Situación | Regla | Qué se hace |
| --- | --- | --- |
| Un aviso oficial nuevo, rojo o naranja | `aviso-nuevo` | Correo inmediato |
| Un departamento sube a naranja o a rojo | `departamento-sube` | Correo inmediato |
| Un aviso sube a naranja o a rojo | `aviso-sube` | Correo inmediato |
| Un aviso naranja o rojo que se esperaba empieza a regir | `aviso-empieza` | Correo inmediato (amarillo o sin nivel: resumen) |
| El ENFEN cambia de estado | `enfen-estado` | Correo inmediato |
| Se cancela un aviso naranja o rojo ya comunicado | `aviso-cancelado` | Correo inmediato |
| Avisos amarillos o sin nivel, departamentos que bajan, un comunicado del ENFEN sin cambio de estado, un escenario nuevo del CENEPRED, otro estado de la NOAA | `resumen` | Van en el resumen diario |
| El mismo aviso difundido por dos instituciones, o una publicación sin cambios | `duplicado` | Nada |

## Correo con n8n y Gmail

El sitio lo publica todo; n8n solo lee `data/boletin.json` del sitio (no depende de que la fuente esté geobloqueada:
lo que solo responde desde el Perú ya llegó por el recolector del Perú) y decide:

- **Primera vez**: manda el boletín completo como «Primer boletín».
- **Algún cambio inmediato**: lo manda ya, con «[Aviso]» en el asunto.
- **Solo cambios de resumen**: espera a la hora del resumen (`digest_hour`, 7:00 en Lima) y manda uno al día con
  «[Resumen]».
- **Sin edición nueva**: nada.

Si la actualización diaria no pudo leer el boletín anterior, la numeración vuelve a la N° 1 (incidencia
`boletin-sin-anterior`); n8n reconoce esa serie nueva porque su fecha (`editionAt`) es posterior a la de la última
edición enviada, y la manda completa.

Compara con la última edición que **ese n8n** mandó y junta los cambios de todas las ediciones nuevas, así no se
pierde ninguno si salieron dos entre dos revisiones. Si el boletín publicado tiene más de 36 h, la ejecución falla
(lo ve el «Error workflow» de n8n): la actualización diaria no corrió.

El flujo es `n8n/dist/enso-n8n-boletin.json`: **Cada hora** → **Configuración** → **Leer boletín** → **¿Con lista?**
(→ **Leer suscripciones**) → **Decidir envío** → **¿Enviar?** → **Repartir correos** → **Enviar por Gmail** →
**Guardar estado**. El estado se guarda solo después de que Gmail respondió bien: si Gmail falla, la hora siguiente
lo vuelve a intentar.

Cada correo sale por el nodo Gmail de n8n (*Send a message*, sin la firma de n8n), con la credencial Gmail OAuth2
como cualquier nodo Gmail. Ese nodo no deja poner cabeceras propias, así que no lleva `List-Unsubscribe` (la baja en
un clic que Gmail y Yahoo exigen a quien manda más de 5000 correos al día): la baja es el enlace del pie de cada
correo. A cada suscriptor le llega su propio correo, con su enlace de baja y solo lo que pidió:

| Frecuencia | Qué recibe |
| --- | --- |
| `todo` | Lo mismo que la lista fija: lo importante al momento y el resumen diario |
| `importantes` | Solo los cambios importantes (naranja o rojo, estado del ENFEN), al momento |
| `diario` | Un solo correo al día, a la hora del resumen, con todo lo que cambió |
| `semanal` | Un solo correo a la semana, el lunes a la hora del resumen, con todo lo que cambió |

El flujo es uno solo y corre cada hora, pero solo manda cuando hay algo: una edición nueva con cambios para esa
suscripción, o una suscripción nueva. Las suscripciones `diario` y `semanal` tienen su propio puntero de edición
(`dailyEdition`, `weeklyEdition`) y en las demás revisiones no reciben nada. Si el lunes n8n estuvo apagado, el resumen
semanal sale en la primera revisión posterior a la hora del resumen de esa semana.

**Bienvenida.** Una suscripción que este flujo no conoce (la lista trae el `id` de cada una) recibe el boletín
completo en la revisión siguiente, a cualquier hora, con una línea que dice qué le llegará desde ahora. Después solo
recibe los cambios de ediciones posteriores a esa bienvenida. El flujo guarda en sus datos estáticos (`welcomed`) el
`id` de cada suscripción activa con la edición de su bienvenida; las bajas salen solas de ahí.

Si eligió departamentos, solo le llegan los cambios de esos (los del ENFEN le llegan siempre).

### Qué lleva cada correo (sin repetir)

Quien recibe varios correos al día no debe leer cinco veces lo mismo. Por eso:

| Correo | Lleva | No lleva |
| --- | --- | --- |
| Primero, bienvenida de una suscripción nueva (o serie reiniciada) | El boletín completo | — |
| Aviso, resumen, resumen diario y semanal | «Qué cambió desde el último correo», la frase y los contadores de ahora, el botón al boletín completo; el recuadro del ENFEN solo si el ENFEN cambió | El mosaico, «Qué se viene», «Qué hacer según el color» y los diez más críticos (iguales a los del correo anterior y a un clic) |

- **Cambios netos.** Entre dos correos se dice el cambio neto: un departamento que subió y volvió a su nivel, un aviso
  que salió y se canceló, o el ENFEN que cambió y volvió, no se cuentan; de dos comunicados seguidos queda el último;
  con un cambio de estado del ENFEN no se repite su comunicado (`consolidate` en `n8n/lib/boletin.js`).
- **Una línea por aviso.** Un aviso nuevo para quince departamentos era una línea del aviso y quince de «sube a
  naranja»; ahora es una: «Nuevo aviso naranja de SENAMHI: … (suben a naranja: Piura, Tumbes y …)» (`fold_departments`
  en `python/enso/boletin.py`). Igual con un aviso cancelado y los departamentos que bajan.
- **El asunto dice el cambio**, no el estado de siempre: «[Aviso] Nuevo aviso rojo de SENAMHI: … (+1 cambio) ·
  Boletín El Niño N° 6». «Importante» solo marca cuando el correo mezcla cambios importantes y menores.
- **Sin repetir dentro del correo.** «Qué se viene» ya no repite el estado del ENFEN, el comunicado y las
  probabilidades (están en su recuadro) ni los conteos por nivel (están en la frase y los contadores): cada línea
  tiene su versión corta (`brief`), que usan también las formas A y B de la página.

Un correo de cambios pesa unos 14 KB, contra 41 KB del completo.

### Paso de configuración (lo hace Pablo o el colega de n8n)

Viene con `send = false`: hasta que se cambie, arma el correo y no lo manda (simulacro). Para ponerlo en marcha:

1. En n8n, **Credentials → Add credential → Gmail OAuth2 API** con la cuenta de Gmail que va a mandar los correos.
   Nombre: `Gmail boletín ENSO`. En n8n Cloud basta con «Sign in with Google»; en un n8n propio hay que crear el
   cliente OAuth en Google Cloud con la API de Gmail activa ([guía de n8n](https://docs.n8n.io/integrations/builtin/credentials/google/oauth-single-service/)).
2. Importar `n8n/dist/enso-n8n-boletin.json` y, en **Enviar por Gmail**, elegir esa credencial. (Con
   `N8N_GMAIL_CRED_ID=<id> node n8n/build.mjs` el flujo ya la trae elegida.)
3. En **Configuración**:
   - `to`: las direcciones que reciben, separadas por comas.
   - `bcc`: copias ocultas (para una lista más larga sin mostrar las direcciones).
   - `use_list`: `true` para mandar también a las suscripciones confirmadas del sitio (ver abajo); `list_url` solo si
     la lista no está en `<site>/api/boletin/lista`.
   - `sender_name` (el nombre del remitente; la dirección es la de la cuenta de Gmail), `digest_hour` (hora de Lima del resumen) y `site` si el sitio cambia de dirección.
4. Probar con **Ejecutar a mano** y `send = false`: la salida de **Decidir envío** muestra el asunto, a quién iría
   y el HTML. Con `send = true` y solo la propia dirección en `to`, llega un correo de prueba.
5. Poner `send = true` y activar el flujo (n8n 1.x) o publicarlo (n8n 2.x).

n8n guarda la última edición enviada solo en las ejecuciones del disparador (no en las manuales): por eso, las
pruebas a mano siempre se comportan como «primer boletín», y la primera hora con el flujo activo manda el boletín
completo una vez.

Gmail permite unos 500 destinatarios por día en una cuenta gratuita y unos 2000 en Google Workspace; para una lista
mayor conviene un grupo de Google como único destinatario.

Prueba con n8n real (sin Gmail de verdad: la credencial es falsa y se comprueba que el correo llega al nodo y que el
estado no se guarda si Gmail falla): `n8n/test/e2e-boletin.sh n8nio/n8n:2.44.4 /tmp/bol`. Corre en `n8n.yml`.

## Suscripción por correo

Cualquiera puede suscribirse desde la pestaña (**Recibir por correo**): pone su correo, elige frecuencia y,
si quiere, departamentos, y acepta el aviso de privacidad. Nada se activa hasta que pulsa **Confirmar** en el correo
que le llega (doble confirmación). Cada correo trae **Cambiar preferencias** y **Darse de baja**; la baja borra la
fila al momento.

| Riesgo | Qué lo evita |
| --- | --- |
| Suscribir a otro | Doble confirmación; una dirección recibe como máximo 3 correos de confirmación por día |
| Averiguar quién está suscrito | La respuesta es la misma para una dirección nueva y una ya suscrita (a esta le llega «ya está suscrito» con su enlace de preferencias) |
| Programas que llenan formularios | Campo trampa invisible, tiempo mínimo de llenado, 5 pedidos por conexión al día y un tope diario total |
| Enlaces falsificados | Cada enlace lleva una firma (HMAC) con su uso (confirmar, baja, preferencias); uno alterado o de otro uso no sirve |
| Pedidos desde otra web | Confirmar y cambiar preferencias exigen el mismo origen; la baja en un clic no (así funciona en Gmail) |
| Datos personales (Ley 29733 y su reglamento, DS 016-2024-JUS) | Solo se guarda el correo, las preferencias y las fechas; se usan solo para el boletín; las pendientes se borran a los 7 días; el aviso de privacidad está junto al formulario |

### Puesta en marcha (una vez)

1. En Cloudflare (*Workers & Pages → el proyecto → Settings → Variables and Secrets*), crear los secretos
   `BOLETIN_SECRET` (32 caracteres al azar o más: `openssl rand -base64 36`) y `BOLETIN_LIST_TOKEN` (24 o más). La
   base `GEO_DB` ya está vinculada. Ver [despliegue-cloudflare.md](despliegue-cloudflare.md).
2. Para el correo de confirmación, una de dos:
   - **Con n8n y la misma cuenta de Gmail (recomendado, sin costo):** importar
     `n8n/dist/enso-n8n-boletin-confirmar.json`; crear una credencial **Header Auth** llamada
     `Boletín: secreto del sitio` con nombre `X-Enso-Secret` y un valor al azar; elegirla en **Pedido del sitio** y la
     de Gmail en **Enviar por Gmail**; activar el flujo. En Cloudflare: `BOLETIN_MAIL_WEBHOOK` = la *Production URL*
     del disparador y `BOLETIN_MAIL_WEBHOOK_SECRET` = el mismo valor.
   - **Con Resend:** `RESEND_API_KEY` y `BOLETIN_FROM` (una dirección de un dominio verificado en Resend).
3. En el flujo del boletín: crear una credencial **Header Auth** `Lista del boletín ENSO` con nombre `Authorization`
   y valor `Bearer <BOLETIN_LIST_TOKEN>`, elegirla en **Leer suscripciones** y poner `use_list = true`.
4. Volver a publicar el sitio. La pestaña muestra el formulario solo cuando `/api/boletin/estado` dice que está
   habilitada; si falta algo, ofrece el canal Atom y el correo de ejemplo.

Sin backend (por ejemplo, en GitHub Pages) el formulario no aparece y nada se rompe.

### «No se pudo mandar el correo de confirmación»

El sitio pidió el correo y la vía de envío no respondió bien. El motivo queda en el registro de la función
(Cloudflare: *Workers & Pages → enso-peru → Functions → Real-time logs*, o *Deployments → el último → Functions*), en
una línea que empieza con `boletin:`:

| Lo que dice | Qué hacer |
| --- | --- |
| `HTTP 404` | El flujo «correo de confirmación» de n8n no está publicado (activo). Publicarlo. Revisar que `BOLETIN_MAIL_WEBHOOK` termine en `/webhook/enso-boletin-confirmar` |
| `webhook-test` | `BOLETIN_MAIL_WEBHOOK` tiene la *Test URL*: cambiarla por la *Production URL* y volver a desplegar |
| `HTTP 403` con una página HTML («403 Forbidden», de nginx) | Un servidor delante de n8n corta el pedido antes de que llegue a n8n (reglas contra robots, por país o por IP). Por eso cada pedido lleva `User-Agent: EnsoPeru-Boletin/1`: un fetch de Cloudflare no lo manda y ese nginx corta los pedidos sin él |
| `HTTP 401` o `403` | El valor de `BOLETIN_MAIL_WEBHOOK_SECRET` no es el de la credencial `X-Enso-Secret` del disparador |
| `HTTP 500` | El flujo corrió y falló: ver la ejecución en n8n (casi siempre la credencial de Gmail en **Enviar por Gmail**) |
| Sin `HTTP` | La dirección no responde: n8n no es accesible desde internet o la URL está mal escrita |

Cambiar un secreto en Cloudflare pide volver a desplegar (correr el flujo `observatory` a mano).

### Diagnóstico (`#/boletin?diagnostico`)

Abrir `https://enso-peru.pages.dev/#/boletin?diagnostico`, poner como clave el valor de `BOLETIN_LIST_TOKEN` y pulsar
**Probar** (`POST /api/boletin/diagnostico`). Muestra, sin mostrar ningún valor:

- el largo y la huella (SHA-256, 12 caracteres) de cada secreto de Cloudflare, y avisa si tiene espacios, saltos de
  línea o comillas de más o si es más corto de lo debido;
- la huella de `Bearer <BOLETIN_LIST_TOKEN>`, que debe ser igual a la del valor de la credencial «Lista del boletín
  ENSO» en n8n;
- qué contesta el webhook de n8n sin secreto, con uno falso y con el de Cloudflare, y qué quiere decir (sin publicar,
  secreto distinto, disparador sin credencial o todo bien);
- con una dirección en «Mandar un correo de prueba», un correo de verdad por la misma vía que la confirmación.

Para sacar la huella de un valor de n8n: `printf %s 'VALOR' | shasum -a 256 | cut -c1-12`.

**«Node … does not have access to the credential» en n8n.** El flujo importado trae el *id* de la credencial con que se
armó, que en otro n8n no existe, aunque el nodo muestre el mismo nombre. En cada nodo con credencial (**Enviar por
Gmail**, **Leer suscripciones**, **Pedido del sitio**) hay que abrir el desplegable y elegirla de nuevo (si ya parece
elegida, elegir otra y volver a la buena), guardar y publicar. Con `N8N_GMAIL_CRED_ID`, `N8N_LIST_CRED_ID` y
`N8N_BOL_HOOK_CRED_ID` al correr `node n8n/build.mjs`, el flujo sale con los *id* de ese n8n.

## Correo: formato y pruebas

El correo es una sola columna fluida de hasta 600 px (tabla para Outlook de escritorio), sin CSS que Gmail quite
(nada de grid, flex ni degradados), con modo oscuro (`color-scheme`), un texto previo para la bandeja, un resumen
de una frase arriba, una tarjeta por departamento en vez de una tabla ancha y el pie con el enlace de baja. Pesa muy
por debajo de los 102 KB a partir de los cuales Gmail lo corta. Las pruebas (`python/tests/test_boletin.py` y
`test_browser.py`) lo
revisan a 320, 375, 414, 600 y 1024 px de ancho, en claro y oscuro, y sin la hoja de estilos (como lo muestran
algunos clientes), sin desborde horizontal; también el contraste (AA) de los colores.

## Imagen para compartir y vista previa

Cada edición publica `data/boletin.png` (1200 × 630): el mosaico del Perú con el color de cada departamento, los
contadores, el estado del ENFEN, los más críticos y, si hubo, qué cambió. Se dibuja en Python sin dependencias.

- **WhatsApp, Telegram, Slack, Teams, Facebook:** el texto para WhatsApp termina con
  `data/boletin-compartir.html?n=<edición>`, una página con etiquetas Open Graph: al pegar el enlace, la aplicación
  muestra la imagen del mapa como vista previa, y quien lo abre va a `#/boletin`. El número de edición evita que
  WhatsApp muestre la imagen de una edición vieja (la guarda por dirección).
- **«Compartir» en el teléfono** manda la imagen junto con el texto (Web Share con archivos); donde no se puede,
  manda el texto y el enlace.
- **«Más → Imagen para compartir (PNG)»** la descarga, para un estado de WhatsApp, una presentación o un grupo.

## Canal Atom

`data/boletin.xml` lista las últimas ediciones con sus cambios, para lectores de noticias, Slack, Teams o cualquier
automatización; la edición actual lleva la imagen del mapa. Se anuncia en la página (`<link rel="alternate">`).

## WhatsApp

**Elegido: compartir a mano, gratis.** La pestaña tiene «Compartir por WhatsApp» (un enlace `wa.me` con el resumen
ya escrito, que abre WhatsApp para elegir el chat o el grupo) y «Copiar resumen». El texto es `whatsapp` del JSON:
primero «Qué cambió» (hasta tres cambios), después el estado de ahora (ENFEN, conteos y hasta cinco departamentos) y
el enlace que muestra el mapa como vista previa.

**Fase 2, automática: no es gratis.** Mandar mensajes sin que alguien los pulse exige la API de WhatsApp Business
(Cloud API de Meta): un número dedicado, verificación de la empresa, plantillas aprobadas y, desde el 1 de julio de
2025, pago por cada mensaje de plantilla entregado; una alerta a quien no escribió en las últimas 24 h es una
plantilla de «utilidad» y se cobra ([precios de Meta](https://developers.facebook.com/docs/whatsapp/pricing/)).
n8n tiene el nodo «WhatsApp Business Cloud» para cuando se decida: se agregaría a este mismo flujo detrás de
**¿Enviar?**, con el mismo texto. Las vías no oficiales (bots con WhatsApp Web) incumplen las condiciones de WhatsApp
y pueden bloquear el número, así que no se usan.
