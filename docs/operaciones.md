# Operación diaria, incidencias y recuperación

## Flujos de GitHub Actions

| Flujo | Cuándo | Qué hace |
|---|---|---|
| `observatory.yml` | Todos los días a las 04:37 UTC (23:37 en Lima), al fusionar en `main`, a pedido del vigilante o a mano | Pruebas → pipeline con datos en vivo → recorridos de navegador → despliegue en Pages → verificación del sitio en vivo → sincronización de incidencias → archivo de respuestas originales |
| `watchdog.yml` | Cada 6 horas (minuto 17) | Lee el sitio en vivo; si la publicación tiene más de 30 horas, reactiva y relanza el flujo diario y abre un issue |
| `ci.yml` | En cada PR y en ramas `claude/**` | Pruebas, publicación sin red con las respuestas capturadas y recorridos de navegador |
| `capture-fixtures.yml` | A mano o al cambiar la herramienta de captura | Actualiza las respuestas reales usadas en el backtesting |

Si las pruebas, el pipeline o los recorridos fallan, **no se despliega** y
el sitio sigue mostrando la publicación anterior. GitHub desactiva los
flujos programados tras 60 días sin actividad en el repositorio; el
trabajo `keepalive` y el vigilante los reactivan.

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
| `relay-stale` | La última copia del recolector desde el Perú tiene más de 36 h | Pedir en el equipo del recolector que ejecuten VERIFICAR y envíen el informe ([servidor-peru](servidor-peru.md#si-algo-falla)) |
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
