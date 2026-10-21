# Operación diaria, incidencias y recuperación

## Flujos de GitHub Actions

| Flujo | Cuándo | Qué hace |
|---|---|---|
| `observatory.yml` | Todos los días a las 04:37 UTC (23:37 en Lima), al fusionar en `main`, a pedido del vigilante o a mano | Pruebas → pipeline con datos en vivo → recorridos de navegador → despliegue en GitHub Pages o Cloudflare Pages ([despliegue-cloudflare](despliegue-cloudflare.md)) → verificación del sitio en vivo → sincronización de incidencias → archivo de respuestas originales |
| `watchdog.yml` | Cada 6 horas (minuto 17) | Lee el sitio en vivo; si la publicación tiene más de 30 horas, reactiva y relanza el flujo diario y abre un issue |
| `ci.yml` | En cada PR y en ramas `claude/**` | Pruebas, publicación sin red con las respuestas capturadas y recorridos de navegador |
| `probe-sources.yml` | Lunes 09:17 UTC, a mano y al cambiar el medidor en ramas `claude/**` | Mide desde GitHub Actions qué URL del registro responden, suma lo que bajaron el recolector del Perú (`data-peru`) y n8n (`data-n8n`) y regenera `registry/sources.json` con los canales de cada URL (en `main`; en otras ramas, en `bot/registry/<rama>`). Las mediciones del flujo de validación de n8n se suman con `python -m tools.probe_sources --no-probe --import <archivo>` |
| `capture-fixtures.yml` | A mano o al cambiar la herramienta de captura | Captura las respuestas reales usadas en el backtesting, en la rama `bot/fixtures/<rama>` y como artefacto |
| `probe-feeds.yml` | A mano o al cambiar el sondeo o la lista de feeds candidatos | Sondea feeds candidatos; informe en `bot/news-probe/<rama>` y como artefacto |
| `scrape-ladder.yml` | A mano o al cambiar la escalera o sus candidatos | Para fuentes sin API ni feed: prueba `robots.txt`, una petición simple, cabeceras de navegador, Chromium y (si hay clave) Firecrawl, en ese orden, y se detiene en el primer paso que funciona o ante una verificación anti-robots; informe en `bot/scrape-ladder/<rama>` y como artefacto |
| `device-screens.yml` | A mano o al cambiar la herramienta de capturas | Capturas de Noticias en los dispositivos de referencia, en `bot/screens/<rama>` y como artefacto |

Las corridas que publican no se cruzan: la diaria, la que pide el vigilante y
las que piden el recolector del Perú (al subir su copia, entre las 21:00 y las
23:30 de Lima) o n8n (22:50, si se activa su aviso) comparten el grupo de
concurrencia `enso-production-publication` sin cancelar la que está en curso.
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
| `relay-missing` | La rama `data-peru` no existe, o existe pero su `index.json` no se pudo leer. Dice cuántas URL del registro solo responden desde el Perú | Instalar el recolector ([servidor-peru](servidor-peru.md)) o revisar su última subida |
| `relay-n8n-missing` | La rama `data-n8n` no existe o no se pudo leer: no hay segundo canal si Actions no alcanza una fuente | Revisar el flujo «ENSO · Recolector n8n» ([n8n](n8n.md)) |
| `relay-n8n-stale` | La última corrida de n8n tiene más de 36 h | Revisar que el flujo siga activo en n8n |
| `relay-n8n-sources-down` | n8n corrió hoy, pero ninguna fuente le respondió | Nada en n8n: son las fuentes o la red de su nube; se usan copias de hasta 72 h |
| `news-history-missing` | La publicación anterior no trajo el histórico de noticias tras tres intentos. Advertencia si se rehízo con la copia de `data-archive` (`sources/news/items.jsonl`); error si tampoco había copia: se publican solo las notas de hoy y el histórico queda marcado `restarted` | Revisar el sitio publicado y la rama `data-archive` |
| `news-history-restored` | Una corrida anterior publicó el histórico incompleto (`restarted`); esta le agregó al final las notas de la copia de `data-archive` | Ninguna: se resolvió sola |
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
