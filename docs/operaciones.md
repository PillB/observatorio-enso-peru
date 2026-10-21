# Operación diaria, incidencias y recuperación

## Flujos de GitHub Actions

| Flujo | Cuándo | Qué hace |
|---|---|---|
| `observatory.yml` | Todos los días a las 04:37 UTC (23:37 en Lima), al fusionar en `main`, a pedido del vigilante o a mano | Pruebas → pipeline con datos en vivo → recorridos de navegador → despliegue en Pages → verificación del sitio en vivo → sincronización de incidencias → archivo de respuestas originales |
| `watchdog.yml` | Cada 6 horas (minuto 17) | Lee el sitio en vivo; si la publicación tiene más de 30 horas, reactiva y relanza el flujo diario y abre un issue |
| `ci.yml` | En cada PR y en ramas `claude/**` | Pruebas, publicación sin red con las respuestas capturadas y recorridos de navegador |
| `probe-sources.yml` | Lunes 09:17 UTC y a mano | Mide desde EE. UU. qué fuentes del registro responden, suma lo que bajó el recolector del Perú y regenera `registry/sources.json` (en `main`; en otras ramas, en `bot/registry/<rama>`) |
| `capture-fixtures.yml` | A mano o al cambiar la herramienta de captura | Captura las respuestas reales usadas en el backtesting, en la rama `bot/fixtures/<rama>` y como artefacto |
| `probe-feeds.yml` | A mano o al cambiar el sondeo o la lista de feeds candidatos | Sondea feeds candidatos; informe en `bot/news-probe/<rama>` y como artefacto |
| `device-screens.yml` | A mano o al cambiar la herramienta de capturas | Capturas de Noticias en los dispositivos de referencia, en `bot/screens/<rama>` y como artefacto |

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
  reinicia el plazo.
- El vigilante (cada 6 horas) reactiva los mismos tres, incluido él mismo.
  Basta con que uno de los dos siga corriendo para que el otro vuelva.
- Fuera de GitHub, el recolector del Perú deja de ver la actualización de
  las 23:37 y el sitio envejece: el vigilante externo (n8n, si está activo)
  revisa `data/dashboard.json` y avisa si la publicación tiene más de 30 horas.
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
- Cuando deja de aparecer, el issue se cierra con un comentario.
- Una corrida que falla abre «La actualización diaria falló», que se
  cierra sola con la siguiente corrida buena.

Códigos frecuentes:

| Código | Significado | Qué hacer |
|---|---|---|
| `unreachable` | La fuente no respondió por ningún canal | Normalmente es temporal; si dura más de unos días, revisar si cambió la URL |
| `archive-channel` | Se usó la copia del Internet Archive | Nada, salvo que sea permanente |
| `relay-stale` | La última copia del recolector desde el Perú y su último latido tienen más de 36 h: el equipo no está corriendo | Pedir en el equipo del recolector que ejecuten VERIFICAR y envíen el informe ([servidor-peru](servidor-peru.md#si-algo-falla)) |
| `relay-sources-down` | El recolector sigue subiendo su latido, pero hace más de 36 h que ninguna fuente peruana le responde | Nada en el equipo: son las instituciones. `heartbeat.json` en `data-peru` dice qué respondió cada una |
| `relay-missing` | La rama `data-peru` existe pero su `index.json` no se pudo leer | Revisar la última subida del recolector |
| `relay-token-expiring` | El token de GitHub del recolector vence en menos de 21 días | Crear un token nuevo y ejecutar INSTALAR en el equipo del recolector con ese token ([servidor-peru](servidor-peru.md#1-token-de-github)) |
| `carried-forward` | Se conservó el dato de la publicación anterior | Revisar la fuente si persiste |
| `format-drift` | Cambió la huella del formato pero se pudo leer | Revisar que los valores sigan siendo correctos y actualizar las pruebas |
| `format-changed` | El formato ya no se puede leer | Ajustar el lector en `python/enso/feeds/` y añadir la nueva respuesta a las fixtures |
| `stale-*`, `official-overdue` | El dato o el comunicado está vencido | Comprobar en la fuente si realmente no hay uno nuevo |
| `newer-communique-unparsed` | Hay un comunicado del ENFEN más nuevo que no se pudo leer | Revisar el PDF y el lector de comunicados |
| `no-data` | Una serie quedó vacía | Si la fuente es crítica, no se despliega |

## Recuperación

- **Relanzar a mano:** Actions → `observatory` → Run workflow. La opción
  `archive_save` pide copias nuevas al Internet Archive.
- **Probar sin red:** ver el README (publicación con `--fixtures`).
- **Volver a una publicación anterior:** relanzar el despliegue de una
  corrida anterior desde Actions, o revertir el commit en `main`.
- **Fuente que cambió de URL:** editar su entrada en `SOURCES` y añadir la
  URL nueva al principio de la lista; las anteriores quedan como respaldo.
- **Respuestas originales:** la rama `data-archive` guarda cada respuesta
  nueva por fuente y SHA-256, útil para reconstruir o añadir pruebas.
