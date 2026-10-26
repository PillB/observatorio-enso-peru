# Operación diaria, incidencias y recuperación

## Flujos de GitHub Actions

| Flujo | Cuándo | Qué hace |
|---|---|---|
| `observatory.yml` | Todos los días a las 04:37 UTC (23:37 en Lima), al fusionar en `main` (salvo cambios solo en `.md` o `docs/`), al recibir `enso-refresh` (lo manda el recolector del Perú tras subir su copia; la consola de documentos tras cada subida; n8n, si se activa su aviso), a pedido del vigilante o a mano | Pruebas → pipeline con datos en vivo → recorridos de navegador → despliegue en GitHub Pages o Cloudflare Pages ([despliegue-cloudflare](despliegue-cloudflare.md)) y verificación del sitio en vivo, a la par del archivo de respuestas originales (solo en `main`) → sincronización de incidencias |
| `watchdog.yml` | Cada 6 horas (minuto 17) | Reactiva `observatory.yml`, `watchdog.yml` y `probe-sources.yml` (no `n8n.yml`, que también es programado) y lee el sitio en vivo; si la publicación tiene más de 30 horas, relanza el flujo diario y abre un issue. También lee el `heartbeat.json` de `data-peru` y de `data-n8n`: si un recolector lleva más de 36 h sin latido (o el latido no se puede leer), abre «[datos] … no da señales» (huella `collector-silent-<rama>`), lo recuerda una vez al día y lo cierra cuando el recolector vuelve a latir. Una rama que todavía no existe (404) no se revisa. Si `probe-sources.yml` no terminó bien en `main` en 8 días (GitHub puede saltarse una corrida programada), la relanza en `main`, como mucho una vez al día, sin abrir issue; si la relanzada falla, lo dice en el registro del vigilante |
| `ci.yml` | En cada PR y en ramas `claude/**` | Pruebas, publicación sin red con las respuestas capturadas y recorridos de navegador |
| `probe-sources.yml` | Lunes 09:17 UTC, a mano y al cambiar el medidor en ramas `claude/**` | Mide desde GitHub Actions qué URL del registro responden, suma lo que bajaron el recolector del Perú (`data-peru`) y n8n (`data-n8n`) y regenera `registry/sources.json` con los canales de cada URL (en `main`; en otras ramas, en `bot/registry/<rama>`). Antes de escribir, corre con el registro nuevo `build_registry --check`, las pruebas sin navegador y las de `n8n/`: si alguna falla, el registro no llega a `main`, queda en `bot/registry/main`, la corrida termina en rojo y se abre «[datos] El registro medido no pasa las pruebas» (huella `registry-gate`), que se cierra solo con el próximo registro que las pasa. Si `main` cambió mientras se medía, `registry/sources.json` y `n8n/dist` se regeneran sobre lo rebasado si chocan (salen de `reachability.json` y del código; si choca `reachability.json`, se aborta) y las pruebas corren otra vez antes de escribir (`.github/scripts/registry-gate.sh`). Lo que la medición restringe por robots.txt (una URL que pasa a `robots-disallowed`, a `unknown` o con un `hop` nuevo) llega igual a `main`, y solo eso: `tools/registry_restrict.py` toma la `reachability.json` de `main` con las mediciones nuevas de esas URL (y de las que la medición sigue restringiendo, para que lo de `main` de más de 45 días no se libere), porque n8n pide sin leer robots.txt lo que el registro de `main` da por permitido; el issue las lista. Las mediciones del flujo de validación de n8n (el CSV que baja n8n o el `validacion-actions.json` que deja `n8n.yml`) se suman con `python -m tools.probe_sources --no-probe --import <archivo> --import-vantage n8n-aws` (`n8n-actions-azure` para el de `n8n.yml`) |
| `capture-fixtures.yml` | A mano o al cambiar la herramienta de captura | Captura las respuestas reales usadas en el backtesting, en la rama `bot/fixtures/<rama>` y como artefacto |
| `probe-feeds.yml` | A mano o al cambiar el sondeo o la lista de feeds candidatos | Sondea feeds candidatos; informe en `bot/news-probe/<rama>` y como artefacto |
| `scrape-ladder.yml` | A mano o al cambiar la escalera o sus candidatos | Para fuentes sin API ni feed: prueba `robots.txt`, una petición simple, cabeceras de navegador, Chromium y (si hay clave, y Chromium no tocó rutas que robots.txt prohíbe) Firecrawl, en ese orden, y se detiene en el primer paso que funciona o ante una verificación anti-robots; informe en `bot/scrape-ladder/<rama>` y como artefacto |
| `device-screens.yml` | A mano o al cambiar la herramienta de capturas | Capturas de Noticias en los dispositivos de referencia, en `bot/screens/<rama>` y como artefacto |
| `n8n.yml` | Lunes 13:17 UTC (08:17 en Lima), a mano y al cambiar `n8n/`, el registro o `fetch.py` | Pruebas de los nodos de n8n, armado de `n8n/dist/` y una corrida real del flujo de validación en un n8n en Docker ([n8n](n8n.md)) |
| `recolector-kit.yml` | Al cambiar el kit, el recolector, `python/enso/` o el registro (en PR y en `main`) | Arma el kit del recolector del Perú, lo instala de verdad en Windows, macOS y Linux y, en `main`, publica el zip en la versión «recolector-kit» ([servidor-peru](servidor-peru.md)) |

Las corridas que publican no se cruzan: la diaria, la que pide el vigilante y
las que piden el recolector del Perú (al subir su copia, entre las 21:00 y las
23:30 de Lima), la consola de documentos (tras cada subida,
[documentos-manuales](documentos-manuales.md)) o n8n (22:50, si se activa su
aviso) comparten el grupo de concurrencia `enso-production-publication` sin
cancelar la que está en curso. Una corrida a mano en otra rama (que no despliega) va a su propio grupo,
`enso-test-<rama>`: en el de producción, al quedar en espera, cancelaría la de `main` que esperaba.
Una copia que llega tarde espera a que termine la publicación y la siguiente
corrida la usa.

Los flujos de desarrollo nunca escriben en la rama de trabajo: sus commits
dejaban las comprobaciones del PR en «action_required» y llenaban el diff.
Para traer un resultado: `git fetch origin bot/fixtures/<rama> && git
checkout FETCH_HEAD -- python/tests/fixtures/sources` (igual con las otras
ramas `bot/...`), revisar y hacer commit.

Si las pruebas, el pipeline o los recorridos fallan, **no se despliega** y
el sitio sigue mostrando la publicación anterior.

### Que GitHub no apague los flujos programados

GitHub desactiva los flujos programados de un repositorio público tras 60
días sin actividad, y un flujo desactivado no corre ni a mano ni por
`repository_dispatch`. Así le pasó en `main` a la versión
anterior (sin corridas desde el 2026-10-08). Defensas:

- El trabajo `keepalive` del flujo diario reactiva por API `observatory.yml`,
  `watchdog.yml` y `probe-sources.yml` en cada corrida programada; reactivar
  reinicia el plazo. La validación semanal de `n8n.yml` no está en esa lista:
  si GitHub la apaga, solo deja de correr esa validación.
- El vigilante (cada 6 horas) reactiva los mismos tres, incluido él mismo.
  Basta con que uno de los dos siga corriendo para que el otro vuelva.
- Fuera de GitHub, el recolector del Perú deja de ver la actualización de
  las 23:37 y el sitio envejece: el vigilante externo (n8n, si está activo)
  revisa `data/manifest.json` y avisa si la publicación tiene más de 30 horas.
- Revisión manual mensual: en *Actions*, ningún flujo debe aparecer como
  *disabled*; si alguno lo está, *Enable workflow* y luego *Run workflow*
  en `observatory.yml`.

## Registro de incidencias

Cada corrida escribe `run-report.json` con todas las incidencias:
severidad (`info`, `warning`, `error`, `critical`), fuente, etapa
(`fetch`, `parse`, `validate`, `derive`, `publish`), código y huella.
El trabajo `incidents` las convierte en issues con la etiqueta
`incidente-datos`:

- Una incidencia nueva abre un issue con el mensaje, la corrida y la
  fecha en que apareció.
- Si se repite, se actualiza el mismo issue (contador y última corrida)
  en lugar de abrir otro.
- Cuando deja de aparecer, el issue se cierra con un comentario. La
  excepción es `format-drift`: que la huella vuelva a ser estable no dice
  que los valores estén bien, así que su issue recibe un solo comentario
  («ya no se detectó») y lo cierra una persona después de revisar los
  valores. Si el cambio vuelve a aparecer con el issue abierto, se agrega
  un comentario «volvió a detectarse» (editar el cuerpo no le avisa a nadie)
  y sale en el correo como incidencia que se repite.
- Solo las corridas de `main` sincronizan issues, abren «La actualización
  diaria falló», mandan el correo y despliegan. Una corrida de
  `observatory.yml` lanzada en otra rama (a mano o por `enso-refresh` con
  otra referencia) solo imprime el plan de `python -m tools.sync_issues
  --dry-run` y no toca el sitio.
- Una corrida que falla abre «La actualización diaria falló», que se
  cierra sola con la siguiente corrida buena. Vale para todas las corridas
  de `observatory.yml`, también la que se lanza al fusionar en `main`. También si un job pasó su
  límite de tiempo (GitHub lo marca «cancelled»): el pipeline tiene 26 min
  y el build 36. También si solo falló el job
  `archive`: el sitio se actualizó, pero `data-archive` y su copia del
  histórico de noticias no. El despliegue no espera al archivo a propósito:
  los datos y avisos oficiales salen aunque `data-archive` falle; a cambio,
  si en la corrida siguiente el sitio tampoco responde, el histórico se
  rehace con una copia a la que le faltan las notas de esa corrida.

### Avisos por correo a otras direcciones

GitHub ya avisa por correo de cada issue a quien sigue el repositorio. Para
que el aviso llegue también a otras direcciones (sin cuenta de GitHub), la
actualización diaria y el vigilante mandan un correo propio al terminar:

- **Una vez por corrida y solo si algo cambió:** incidencias nuevas (con
  su detalle y enlace), las que se repiten («La actualización diaria
  falló», «El sitio publicado está desactualizado», el recordatorio diario
  de un recolector que no da señales y un `format-drift` que volvió a
  detectarse) y las resueltas. Una incidencia que sigue igual que el día
  anterior no vuelve a mandar correo.
- **A quién:** la variable del repositorio `ALERT_EMAILS` (Settings →
  Secrets and variables → Actions → Variables), con las direcciones
  separadas por comas. Se cambia ahí, sin tocar el código; vacía o sin
  definir, no se envía nada. Van en copia oculta.
- **Por dónde sale:** cualquier servidor SMTP (el de la institución, Gmail
  con contraseña de aplicación, SendGrid, Resend…), con los secretos
  `SMTP_HOST`, `SMTP_PORT` (465 o 587), `SMTP_USERNAME` y `SMTP_PASSWORD`.
  El remitente es la variable `ALERT_FROM` o, sin ella, `SMTP_USERNAME`.
- Si `ALERT_EMAILS` tiene direcciones pero falta `SMTP_HOST`, o el envío
  falla, la corrida lo anota como advertencia y no se detiene.

Para probarlo sin enviar: `python -m tools.alert_email --since
2026-10-22T00:00:00Z --dry-run` (desde `python/`, con `GITHUB_TOKEN`,
`GITHUB_REPOSITORY` y `ALERT_EMAILS`) muestra el correo que saldría.

Códigos de aviso y error. `python/tests/test_docs_codes.py` exige que cada
código que registra el pipeline esté en esta tabla. `archive-channel`,
`carried-forward` y `probe-found` son esperados y no abren issue (`IGNORE` en
`python/tools/sync_issues.py`):

| Código | Significado | Qué hacer |
|---|---|---|
| `unreachable` | La fuente no respondió por ningún canal | Normalmente es temporal; si dura más de unos días, revisar si cambió la URL |
| `archive-channel` | Se usó la copia del Internet Archive | Nada, salvo que sea permanente |
| `relay-stale` | La última copia del recolector desde el Perú y su último latido tienen más de 36 h: el equipo no está corriendo | Pedir en el equipo del recolector que ejecuten VERIFICAR y envíen el informe ([servidor-peru](servidor-peru.md#si-algo-falla)) |
| `relay-sources-down` | El recolector sigue subiendo su latido, pero hace más de 36 h que ninguna fuente peruana le responde | Nada en el equipo: son las instituciones. `heartbeat.json` en `data-peru` dice qué respondió cada una |
| `relay-missing` | La rama `data-peru` no existe, o existe pero su `index.json` no se pudo leer. Dice cuántas URL del registro solo responden desde el Perú | Instalar el recolector ([servidor-peru](servidor-peru.md)) o revisar su última subida |
| `relay-goal-missed` | La copia del Perú de esa noche no trae el PDF del comunicado o de los informes técnicos más recientes, que el recolector debía guardar. Junto a cada documento va lo que anotó el recolector de su último intento (clase, estado HTTP, motivo y servidor) | Pedir en el equipo del recolector que ejecuten VERIFICAR y envíen el informe ([servidor-peru](servidor-peru.md#si-algo-falla)); si el documento hace falta antes, subirlo en la consola de documentos |
| `relay-n8n-missing` | La rama `data-n8n` no existe o no se pudo leer: no hay segundo canal si Actions no alcanza una fuente | Revisar el flujo «ENSO · Recolector n8n» ([n8n](n8n.md)) |
| `relay-n8n-stale` | La última corrida de n8n tiene más de 36 h | Revisar que el flujo siga activo en n8n |
| `relay-n8n-sources-down` | n8n corrió hoy, pero ninguna fuente le respondió | Nada en n8n: son las fuentes o la red de su nube; se usan copias de hasta 72 h |
| `news-history-missing` | La publicación anterior no trajo el histórico de noticias tras tres intentos (el mensaje dice si no existe o si el sitio no respondió). Advertencia si se rehízo con la copia de `data-archive` (`sources/news/items.jsonl.gz`); error si tampoco se pudo leer la copia: se publican solo las notas de hoy y el histórico queda marcado `restarted`. El error se repite en cada corrida hasta que se lea la copia (la copia no pierde notas: el job `archive` solo le agrega) | Revisar el sitio publicado y el paso «News history backup» de la corrida |
| `news-history-restored` | Esta corrida le agregó al histórico publicado notas de la copia de `data-archive` que no tenía (una corrida anterior no llegó a desplegar o lo publicó incompleto), o aceptó como está un histórico `restarted` porque `data-archive` no tiene copia | Ninguna: se resolvió sola |
| `news-reader-restored` | Informativa: notas de feeds que se leen una vez al día que vienen de su última lectura (guardada en la caché de Actions), porque la corrida que las leyó no llegó a publicar | Ninguna |
| `feeds-reader-unknown` | Los feeds que se leen una vez al día no se pidieron: no había estado guardado (la caché de Actions no se leyó) y la publicación anterior no bastaba (el sitio no respondió, o una corrida que no llegó a publicar pudo haberlos pedido), así que no se sabía cuándo se pidieron por última vez. Esa corrida cuenta como su pedido: se vuelven a pedir 20 h después | Ninguna si es aislada; si se repite, revisar el sitio y el paso «Restore the reader-feed state» |
| `news-history-large` | `news/items.jsonl` pasa de 20 MiB; Cloudflare Pages no sirve archivos de más de 25 MiB | Dividir el histórico (por ejemplo, un archivo por mes) antes de que llegue al límite |
| `relay-token-expiring` | El token de GitHub de un recolector vence en menos de 21 días: el del Perú (fuente `relay-peru`) o la credencial de n8n (`relay-n8n`). Ambos anotan su vencimiento en `collector.token_expires_at` | Perú: crear un token nuevo y ejecutar INSTALAR en el equipo con ese token ([servidor-peru](servidor-peru.md#1-token-de-github)). n8n: crear otro token y actualizar la credencial «GitHub ENSO (n8n)» ([n8n](n8n.md), pasos 2 y 3) |
| `relay-kit-outdated` | El kit del recolector del Perú es anterior a lo que el sitio necesita (su `contract` es menor que `MIN_COLLECTOR_CONTRACT`): sigue subiendo copias, pero sin lo nuevo | Ejecutar `otras-acciones/ACTUALIZAR` en el equipo del recolector ([servidor-peru](servidor-peru.md#mantenimiento)) |
| `senamhi-avisos-unread` | La copia del Perú no trae la tabla de avisos del SENAMHI (`?p=aviso-meteorologico`) o no tiene filas legibles: los avisos del SENAMHI de Telegram y del COEN quedan «sin nivel» en el mapa | Ver esa URL en `logs/recolector.log` del equipo; si respondió y no se lee, ajustar `python/enso/senamhi_avisos.py` |
| `senamhi-avisos-stale` | La tabla de avisos del SENAMHI que da el nivel tiene más de 36 h (la última noche no se pudo bajar) | Normalmente es temporal; los avisos emitidos después quedan sin nivel hasta la próxima copia |
| `manual-download-needed` | Uno o más documentos (comunicado o informe técnico del ENFEN, boletín semanal del IMARPE) no llegaron por ninguna ruta automática y quedaron pendientes en `data/manual-needed.json`. El mensaje dice cuáles y qué URL abrir | Abrir cada URL en un navegador (pasar la verificación si aparece), guardar el PDF y subirlo en `/admin/documentos.html` ([documentos-manuales](documentos-manuales.md)); la actualización que se inicia al subirlo lo lee y lo valida. Es un solo issue para todos: se cierra solo cuando ya no falta ninguno |
| `manual-unreadable` | La rama `data-manual` tiene un `index.json` que no se pudo leer: los PDF subidos a mano no se usan en esta corrida | Revisar el último commit de la consola de documentos en `data-manual` ([documentos-manuales](documentos-manuales.md)) |
| `carried-forward` | Se conservó el dato de la publicación anterior | Revisar la fuente si persiste |
| `format-drift` | Cambió la huella del formato de la misma URL pero se pudo leer. Su issue no se cierra solo (ver arriba) | Revisar que los valores sigan siendo correctos, actualizar las pruebas y cerrar el issue |
| `format-changed` | El formato ya no se puede leer | Ajustar el lector en `python/enso/feeds/` y añadir la nueva respuesta a las fixtures |
| `implausible-value` | El lector anotó una advertencia sin dejar de leer la fuente (el mensaje dice cuál): unos pocos valores fuera del rango plausible (en las series mensuales y en el D20 se descartan; con muchos, la fuente pasa a `format-changed`; en la semanal OISST, `cpc-wksst`, se conservan y solo se anotan), o una fecha que falta o no cuadra (`ensodisc:` la fecha de emisión de la discusión de NOAA; `enfen:` la del comunicado en la entrada de WordPress del ENFEN) | Con un valor: compararlo con la fuente y, si es real, ampliar el rango del lector en `python/enso/feeds/`. Con una fecha: revisar el documento y el lector de fechas (`parse_enso_discussion` en `cpc.py`, `parse_enfen_communique` en `peru.py`) |
| `exception` | Un lector falló por un error de programa, no de formato: la fuente queda sin dato nuevo (`error`) o, con la fuente `news`, no se leyeron las noticias de esta corrida (`warning`) | Revisar la traza en el registro de la corrida, corregir el lector y añadir la respuesta a las fixtures |
| `rebase-failed` | No se pudo llevar ERSSTv6 a la base 1991–2020: la serie larga de Niño 1+2 o 3.4 no se publica en esta corrida | Revisar la respuesta de PSL y `rebase_anomalies` en `python/enso/feeds/cpc.py` |
| `empty-series` | Una serie quedó sin puntos al armarla y no se publica | Revisar la fuente y su lector; si la fuente falló del todo, ver `no-data` |
| `stale-*` (`stale-<serie>`, `stale-weekly`), `official-overdue` | El dato o el comunicado está vencido | Comprobar en la fuente si realmente no hay uno nuevo |
| `late-*` (`late-<dato>`) | El panel de vigencia marca el dato como atrasado: según el calendario de la institución ya debió llegar uno más reciente, o se usó una copia o el último dato conservado. Los vencidos ya tienen `stale-*` u `official-overdue` | Comprobar en la fuente si ya publicó el siguiente; el cálculo está en `python/enso/freshness.py` («Vigencia por vista» en [informes-texto](informes-texto.md)) |
| `newer-communique-unparsed` | Hay un comunicado del ENFEN más nuevo que no se pudo leer | Revisar el PDF y el lector de comunicados |
| `communique-unread` | No se pudo leer el PDF de un comunicado del listado: ninguna ruta lo dio, o lo que llegó no era un PDF legible del número buscado (el mensaje da cada intento). Si es el más reciente, queda pendiente en la consola de documentos | Si aparece `manual-download-needed`, subir el PDF en la consola; si el PDF llegó y no se leyó, revisar el lector de comunicados (`python/enso/feeds/peru.py`) |
| `communique-warning` | El comunicado se leyó, pero sin fecha de emisión o con una fecha que no cuadra con su año | Revisar el PDF y el estado publicado |
| `latest-exception` | La búsqueda del último comunicado falló por un error de programa; queda lo que dio el listado o el comunicado anterior | Revisar la traza de la corrida y `enfen_latest` en `python/enso/observatory.py` |
| `status-unknown` | No se pudo determinar el estado del sistema de alerta del ENFEN en esta corrida | Ver las incidencias del ENFEN de la misma corrida (`unreachable`, `communique-unread`) y el comunicado vigente en la fuente |
| `outlook-unread` | El comunicado trae una perspectiva con magnitud que no se pudo leer (toda o una región): la vista El Niño costero no la muestra. Se repite en cada corrida mientras siga ese comunicado | Revisar la oración en el PDF y las reglas de `python/enso/reports.py` ([informes-texto](informes-texto.md)); con el modelo de lenguaje configurado queda una propuesta para revisión |
| `informe-*` (`informe-unread`, `informe-exception`, `informe-icen-mismatch`, `informe-probability-sum`, `informe-period-*`, `informe-schema*`…) | El informe técnico del ENFEN no se encontró, no se bajó o no se leyó (`informe-unread`, `informe-exception`), o una parte no pasó la validación (sumas de probabilidades, meses, periodo, saltos, el ICEN del IGP). Solo se retiene la parte afectada; sin informe nuevo se conserva el último leído, marcado atrasado | Revisar el PDF (el mensaje da la URL) y `python/enso/reports.py` ([informes-texto](informes-texto.md)); si el PDF no llega por ninguna ruta, subirlo en la consola de documentos |
| `bsobp-unreadable` | El repositorio del IMARPE listó un boletín semanal (BS-OBP) cuyo PDF no se pudo bajar o leer, o que dice otro número. Queda también en la consola de documentos | Abrir la página del boletín que trae el mensaje, bajar el PDF y subirlo en la consola de documentos; la actualización siguiente lo lee. El issue se cierra solo |
| `bsobp-overdue` | Más de 12 días sin un boletín semanal nuevo en el repositorio del IMARPE (sale cada domingo) | Ver si el IMARPE dejó de depositarlo o cambió el título; si cambió, ajustar `QUERY`/`TITLE_RE` en `python/enso/feeds/imarpe_bsobp.py` |
| `bsobp-unreachable` | El repositorio del IMARPE no listó boletines; se conservan los ya leídos. Entre paréntesis va la causa con el error de red (por ejemplo «conexión: ConnectError: … Name or service not known», que es el DNS) | Ver `repository-unreachable` |
| `repository-unreachable` | El repositorio del IMARPE (`repositorio.imarpe.gob.pe`, DSpace) no sirvió los comunicados o los informes técnicos del ENFEN. La causa va entre paréntesis: `conexión` con el error de red (DNS, plazo, conexión rechazada), `tls` (el certificado no se pudo verificar) o `http-<código>`. Queda abierta mientras dure | Con `conexión`, el servidor no responde a GitHub Actions: las búsquedas del registro (`imarpe-repositorio-enfen`, `imarpe-repositorio-bsobp`) se leen de la copia del Perú cuando la hay. Con `tls`, revisar la cadena con `openssl s_client -showcerts -connect repositorio.imarpe.gob.pe:443` y actualizar `python/enso/data/ca-intermedios.pem` |
| `repository-format` | El repositorio del IMARPE respondió, pero no con la búsqueda o los paquetes de DSpace | Revisar la respuesta y `python/enso/feeds/imarpe_repo.py` |
| `month-unread` | GODAS (`cpc-godas-d20`): CPC respondió pero un mes no se pudo leer; se publica sin ese mes | Si se repite, revisar el archivo `godas.M.AAAAMM.grb` que nombra el mensaje |
| `history-old` | GODAS: el histórico `python/enso/data/godas-d20.json` tiene más de 12 meses de atraso | Regenerarlo (ver «Histórico de D20» abajo) |
| `bsobp-exception` | La lectura del boletín semanal falló por un error de programa; se conserva lo publicado | Revisar la traza y `python/enso/feeds/imarpe_bsobp.py` |
| `news-degraded` | Menos de la mitad de los feeds de noticias pedidos están activos | Revisar `news/feeds.json` (qué falló en cada uno) |
| `alerts-places` | Sin noticias en esta corrida, las alertas de la publicación anterior no se pudieron volver a ubicar: quedan con el lugar con que se guardaron | Ninguna si es aislada; si se repite, revisar la traza |
| `overrides-http`, `overrides-down` | La consola de lugares (`/api/geo/overrides`) respondió con error o no respondió: se usan las correcciones de la publicación anterior | Revisar la Function y `GEO_OVERRIDES_URL` ([despliegue-cloudflare](despliegue-cloudflare.md)) |
| `overrides-rejected` | Algunas correcciones de lugar de la consola traen códigos inválidos y no se aplicaron | Revisarlas en la consola de lugares ([georreferenciacion](georreferenciacion.md)) |
| `no-data` | La fuente falló y no hay un dato anterior que conservar (`critical` si la fuente es crítica) | Si la fuente es crítica, no se despliega |
| `previous-unreachable` | La fuente falló y tampoco se pudo leer su último dato (`sources/<id>.json`) de la publicación anterior, porque el sitio falló o no respondió tras sus reintentos: esta publicación sale sin dato de la fuente | Revisar el sitio publicado y la fuente; la corrida siguiente vuelve a intentarlo |
| `archive-carry-failed` | La publicación anterior tenía una copia archivada (el mensaje da la ruta) que no se pudo volver a leer: esta publicación sale sin ese enlace «copia archivada» | Revisar el sitio publicado; la copia original sigue en la rama `data-archive` |
| `archive-too-large` | Un documento supera el límite de la copia archivada: se publica sin copia | Si el documento importa, guardarlo a mano en `data-archive`; el enlace a la fuente en vivo sigue publicado |
| `alerts-unread` | Ninguna fuente de alertas de peligros respondió (`error`): el mapa y la lista de alertas no se actualizaron | Ver las incidencias de cada fuente de alertas de la misma corrida y el estado de la red de Actions |
| `alert-source-down`, `alert-source-format` | Una fuente de alertas vigilada (las del SENAMHI y el COEN del INDECI) no respondió, o respondió con otra forma | `down`: normalmente es temporal. `format`: revisar el lector de la fuente (`python/enso/news.py`, `hazardparse.py`) |
| `llm-extract-unavailable` | El extractor con modelo de lenguaje (flujo de n8n) no respondió cuando el lector fijo falló: no queda propuesta para revisión | Revisar el flujo «ENSO · Extractor de informes (OpenAI)» en n8n y los secretos `ENSO_LLM_EXTRACT_URL` y `ENSO_LLM_EXTRACT_TOKEN` ([n8n](n8n.md)) |

## Histórico de D20 (GODAS)

`python/enso/data/godas-d20.json` guarda el D20 mensual de 1980 en
adelante y su climatología 1991–2020. Cada corrida lee de CPC solo los
meses posteriores al último guardado (≈6,5 MB por mes, hasta 24 meses: el último
guardado y los más recientes). Un mes ya leído en la publicación anterior que
terminó hace más de 60 días no se vuelve a bajar: un pedido de 1 byte comprueba
que el archivo siga ahí (el último mes guardado se vuelve a bajar los lunes).
Una vez al año, o si CPC reprocesa GODAS, conviene regenerarlo:

```bash
cd python
python -m tools.godas_d20_climatology --cache /tmp/godas-cache   # ≈5 min, ≈3,6 GB descargados
```

y revisar en el diff que la climatología no haya cambiado más de 1–2 m.
CPC responde 403 a algunos índices `.grb.inv` (2024-09, 2024-10); por eso
el código no los usa y recorre los mensajes del propio GRIB.

## Recuperación

- **Relanzar a mano:** Actions → `observatory` → Run workflow. La opción
  `archive_save` pide copias nuevas al Internet Archive.
- **Probar sin red:** ver el README (publicación con `--fixtures`).
- **Volver a una publicación anterior:** relanzar el despliegue de una
  corrida anterior desde Actions, o revertir el commit en `main`.
- **Fuente que cambió de URL:** editar su entrada en `SOURCES` y añadir la
  URL nueva al principio de la lista; las anteriores quedan como respaldo.
- **Conflicto en `registry/sources.json` o `n8n/dist/`:** son archivos
  generados y se resuelven regenerándolos, nunca a mano. Resolver antes los
  demás conflictos (también `registry/reachability.json`, del que sale el
  registro), tomar cualquiera de las dos versiones (`git checkout --theirs --
  registry/sources.json n8n/dist`), correr `cd python && python -m
  tools.build_registry` y, desde la raíz, `node n8n/build.mjs` (sin las
  variables `N8N_*_CRED_ID`, para que salga igual a la copia versionada), y
  hacer commit. `python/tests/test_registry.py` (`build_registry --check`) y
  `n8n.yml` (`node n8n/build.mjs --check`) fallan si quedan desactualizados.
- **Respuestas originales:** la rama `data-archive` guarda cada respuesta
  nueva por fuente y SHA-256, útil para reconstruir o añadir pruebas. Una
  respuesta igual a una que ya tiene (mismo SHA-256 en la misma fuente) no
  se vuelve a guardar con otra fecha. El job `archive` corre solo en `main` (una corrida
  de prueba en otra rama no agrega notas a la copia del histórico), baja solo la lista
  de archivos y `sources/news` (copia parcial: la rama crece cada día) y no
  sube un commit que borre archivos. Para mirar la rama entera:
  `git fetch origin data-archive && git switch data-archive`.
- **Quitar una nota del histórico de noticias** (p. ej. a pedido de un
  medio): hoy no se puede sin tocar el código. El histórico publicado es de
  solo anexar y su copia en `data-archive` (`sources/news/items.jsonl.gz`)
  lo completa en cada corrida, así que una nota borrada en un lado vuelve
  desde el otro. Haría falta una lista de notas retiradas que el pipeline
  filtre al leer los dos.
