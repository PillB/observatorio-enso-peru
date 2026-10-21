# Informes en texto libre y vigencia de los datos

Qué informes de las instituciones peruanas se publican como texto (PDF o HTML sin estructura), cuáles necesita
el observatorio, cómo se leen y qué pasa cuando cambian de formato. Al final, cómo se calcula la vigencia que
muestra cada vista.

## Inventario

| Informe | Formato | ¿Se usa? | Qué se extrae |
| --- | --- | --- | --- |
| Comunicado oficial del ENFEN | PDF (texto) | Sí | Estado, número, fecha de emisión, próximo comunicado y la **perspectiva** por región (magnitud esperada y hasta cuándo). Las probabilidades del comunicado son imágenes: se toman del informe técnico. |
| Informe técnico del ENFEN | PDF de 10–17 MB (texto) | Sí | **ICEN temporal** (estimado del ENFEN antes del ICEN oficial del IGP) y **probabilidades mensuales** por región (Niño 1+2 y Niño 3.4). |
| ICEN del IGP | `ICEN.txt` | Sí, ya estructurado | Serie mensual oficial. |
| Avisos del SENAMHI | Telegram y capa ArcGIS (GEOSINPAD) | Sí, ya estructurado | Se leen como alertas con su vigencia. |
| COEN / INDECI | RSS | Sí, ya estructurado | Alertas y reportes. |
| Escenarios de riesgo del CENEPRED | PDF | No como dato | El comunicado los cita; el sitio enlaza el comunicado. |
| Boletines de la ANA y del SENAMHI (hidrológicos) | PDF, solo desde el Perú | No como dato | Fuera del alcance de las vistas actuales; si se agregan, van por el recolector del Perú. |

## Cómo se leen (`python/enso/reports.py`)

1. **Determinista primero.** Se extrae el texto con `pypdf` y se leen las tablas con expresiones tolerantes a
   cambios de diagramación: las columnas salen del encabezado de cada tabla, la región del título y los meses de
   la frase «entre X de Y y Z de W». Se probó con cinco informes reales de 2024 a 2026
   (`python/tests/fixtures/reports/`).
2. **Cuál es el informe del comunicado.** El número del informe no sigue al del comunicado (2022 va uno
   atrás; 2025, uno adelante: el comunicado 05-2025 cita el informe N° 06). Se usa el enlace que trae el
   comunicado y, si no lo trae, el listado del portal, eligiendo por la fecha de corte de datos (de 3 días
   después a `INFORME_LAG_DAYS` = 10 días antes de la emisión; en 2024–2026 fue de 0 a 5). Sin listado del
   portal, el de la réplica de la DHN (el número más alto del año), que la validación descarta si es de otro
   periodo. Un informe ya leído no se vuelve a bajar mientras siga el mismo comunicado.
3. **De dónde se baja.** El portal del ENFEN no responde desde GitHub Actions ni desde n8n (DNS). Se prueba,
   en orden: el portal, la réplica de la DHN (`informe-tecnico/NN-AAAA.pdf`), las copias del recolector del
   Perú y el Internet Archive. La DHN hoy responde a GitHub Actions y a n8n con una página de verificación
   humana: solo vale un cuerpo que empiece con `%PDF-`, así que esa página no se lee y la búsqueda sigue en
   las copias (nunca se intenta pasar la verificación). El recolector del Perú baja el listado de informes y
   los PDF de los dos más recientes (hasta 20 MB) con la misma URL que cita el comunicado. Mientras no haya
   copia del Perú, el sitio conserva el último informe leído marcado como atrasado o, si nunca se leyó uno,
   muestra «sin dato». La copia del PDF se publica en `data/archive` (enlace «Copia archivada»). Si
   ninguna ruta responde queda una advertencia, no un error: la publicación no se marca degradada.
   Entonces el documento queda pendiente en la consola de documentos para que una persona lo baje en su
   navegador y lo suba ([documentos-manuales.md](documentos-manuales.md)); lo mismo con el comunicado.
4. **Validación.** Cada extracción pasa por un esquema (`SCHEMAS`) y por reglas de plausibilidad:
   - meses consecutivos en la tabla de índices;
   - el ICEN temporal es de 0 a 2 meses antes del corte de datos y la primera columna de probabilidades, de
     un mes antes a tres después;
   - cada mes (columna) de probabilidades suma 100 % (±2) y hay al menos 7 categorías;
   - el ICEN temporal no salta más de 1,5 respecto del último ICEN oficial;
   - el ICEN oficial que repite el informe coincide con el del IGP (±0,05);
   - la fecha de corte encaja con la emisión del comunicado (si no, no es su informe y no se usa) y el
     informe tiene menos de 45 días.
   Un error de esquema bloquea solo la parte donde está (una tabla estacional mal leída no retiene el ICEN
   temporal ni las probabilidades); lo mismo con el periodo (`informe-period-provisional` y
   `informe-period-probabilities`). Un informe de otro periodo (la réplica se atrasa) es una advertencia, no un
   error, y su PDF no se archiva. El informe anterior solo se reutiliza sin bajarlo si el comunicado cita su
   URL o el listado del portal lo eligió por fecha; un número de la DHN sin fecha se baja y se valida.
5. **Procedencia.** Todo valor publicado lleva la URL del PDF, la página y la cita textual de donde salió, y
   la copia archivada del PDF; el sitio enlaza las dos a la página citada.
6. **Si algo falla.** Si el informe no se encuentra o no se baja, cambió el formato o nada de lo leído pasa
   las reglas, se conserva el informe anterior marcado como arrastrado, la vista lo muestra como «atrasado»
   y queda una incidencia en `run-report.json`, que abre un issue en GitHub. Si falla solo una parte (una
   región que no suma 100, un ICEN temporal implausible), esa parte no se publica, queda su incidencia y el
   panel de vigencia lo anota; el resto del informe sí se publica.
7. **El ICEN temporal se retira solo** cuando el IGP publica el ICEN oficial de ese mes; entonces el panel
   de vigencia lo marca «no aplica».
8. **Perspectiva del comunicado.** La fase (El Niño o La Niña) sale del sujeto de la oración de cada región
   (entre la región y «magnitud» o justo antes de la región) y, si no lo hay, del estado de alerta; el nombre
   del sistema de alerta y las transiciones posteriores no cuentan. Cada oración con una magnitud («magnitud
   fuerte», «categoría extraordinaria», «evento muy fuerte», «condiciones cálidas moderadas») cuenta para las
   regiones que nombra: si alguna no se pudo leer, aunque la otra sí, queda la incidencia `outlook-unread` en
   cada corrida mientras siga ese comunicado y, con el modelo configurado, una propuesta en `outlookReview`.
   En un comunicado «No activo» sin perspectiva el panel dice «no aplica»; en alerta o vigilancia, «sin dato».
   No se arrastra la perspectiva del comunicado anterior: es de otro comunicado.

## Respaldo con un modelo de lenguaje (opcional, apagado)

Solo se usa cuando la lectura determinista falla por cambio de formato. Nunca publica: deja una **propuesta**
en `informe.review` (o `outlookReview` para la perspectiva) para que una persona la revise, aunque no haya un
informe anterior. El mismo PDF no se le vuelve a pasar al modelo en las corridas siguientes, salvo que la vez
anterior el servicio no respondiera (error HTTP, plazo, conexión): eso se reintenta. Una falla posterior de
descarga no borra la propuesta. Del error solo se publica el tipo y el código HTTP, nunca el texto de la
excepción, que trae la URL secreta del webhook.

- Variables: `ENSO_LLM_EXTRACT_URL` (por ejemplo, un webhook de n8n con un nodo AI Agent) y
  `ENSO_LLM_EXTRACT_TOKEN` (cabecera `Authorization: Bearer`).
- Petición `POST` JSON: `{kind, schema, text, url, published}`; `kind` es `enfen-informe` o
  `enfen-perspectiva`, `schema` es el esquema JSON esperado y `text` el texto extraído del PDF.
- Respuesta: `{data, model, evidence}` (`evidence`: ruta del campo → cita del texto, hasta 300 caracteres). `data` se valida con el mismo esquema; los errores quedan en `schemaErrors`.
- Si el servicio no responde, devuelve algo inválido o no está configurado, el pipeline sigue igual.
- En GitHub Actions se configuran como *secrets* del repositorio con esos mismos nombres
  (`observatory.yml` los pasa al pipeline). Sin ellos el respaldo queda apagado.
- El flujo de n8n usa la credencial de OpenAI del colega: recibe la petición en un Webhook con autenticación
  por cabecera, pide al modelo un JSON (temperatura 0) que siga el esquema y cite el texto de origen, y
  responde `{data, model, evidence}`. Es el flujo `enso-n8n-extractor` (webhook `/webhook/enso-extraer`); su
  instalación está en [n8n.md](n8n.md). El pipeline vuelve a validar todo; el modelo nunca decide qué se publica.

## Vigencia por vista (`python/enso/freshness.py`)

Cada dato del sitio tiene uno de cuatro estados, según el calendario de su institución:

| Dato | Se espera el siguiente | Margen |
| --- | --- | --- |
| Índices mensuales de NOAA | día 10 del mes M+2 | 5 días |
| ICEN del IGP | día 15 del mes M+3 | 5 días |
| RONI / ONI (trimestre por su mes central) | día 10 del mes M+3 | 5 días |
| OISST semanal | 12 días después del centro de la semana | 2 días |
| Comunicado ENFEN y discusión de NOAA | la fecha anunciada del próximo | 1 día |
| Informe técnico del ENFEN | con el comunicado vigente | — |

- **al día**: es lo más reciente que la institución debía haber publicado;
- **atrasado**: ya pasó la fecha esperada más el margen, o el dato viene de una copia o del último valor conservado;
- **vencido**: supera la antigüedad máxima de su fuente;
- **sin dato**: la fuente no dio nada en esta publicación (una serie que no llegó también aparece, no se omite);
- **no aplica**: el ICEN temporal ya retirado o la perspectiva de un comunicado que no la trae. No cuenta para el
  estado de la vista.

El resultado va en `dashboard.json` (`freshness`). Cada vista muestra un panel «Vigencia de los datos» con el
peor estado de sus paneles, un resumen que nombra lo atrasado y lo que falta y, desplegado, cada dato con su
fecha, fuente y próxima publicación esperada. El mapa reporta el OISST semanal, que es lo que dibuja. Un dato
del informe que el panel da por vencido no se muestra como actual. Los datos atrasados quedan como
incidencia `late-<id>`. Las noticias cuentan como fallidas las fuentes omitidas por servidor caído o por
tiempo; solo no cuentan las que `robots.txt` no permite.

## Causas raíz y prevención (octubre de 2026)

Los fallos del 21 de octubre de 2026 (comunicado 18-2026 sin leer, informe técnico sin bajar) tuvieron cuatro causas
de fondo. Cada una tiene ahora un resguardo que falla de forma visible si vuelve a ocurrir:

| Causa | Qué pasó | Resguardo |
| --- | --- | --- |
| Lógica duplicada que se separó | La actualización diaria, el informe técnico y el recolector del Perú leían las páginas de descarga del portal cada uno a su manera; uno tomaba el enlace canónico (la propia página) en vez del botón «Descargar», otro se quedaba con la API de WordPress atrasada. | Un único lector: `peru.download_button` (solo el `?wpdmdl=` del mismo slug) y `merge_enfen_listings` (todos los listados, no el primero que responde). |
| Pruebas con páginas inventadas | Las páginas de prueba no traían el enlace canónico ni la barra lateral, así que el error no aparecía en las pruebas. | Pruebas con capturas reales del portal (`tests/fixtures/reports/enfen-download-n14-2026-20261021.html`, listados del 21-10-2026) y con la página de verificación de la DHN. |
| Supuestos de acceso sin comprobar | Se suponía que la réplica de la DHN servía PDF; sirve una verificación humana, que se aceptaba como HTML y cortaba la búsqueda. | Solo cuenta un cuerpo que empiece con `%PDF-`; el resto sigue a la ruta siguiente (nunca se intenta pasar la verificación). |
| Fallos parciales silenciosos | La recolección decía «ok» con `enfen-docs 4/8`, sin decir que faltaba justo el comunicado más reciente. | Metas de la recolección (`goals` en `index.json`): el PDF del comunicado y del informe más recientes. Si falta uno, el recolector anota un AVISO y la actualización diaria abre la incidencia `relay-goal-missed`. |
