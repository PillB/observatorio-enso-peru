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
2. **Validación.** Cada extracción pasa por un esquema (`SCHEMAS`) y por reglas de plausibilidad:
   - meses consecutivos y periodos que encajan con la fecha del informe;
   - cada fila de probabilidades suma 100 % (±2); si no, la tabla no se publica;
   - el ICEN temporal no salta más de 1,5 respecto del último ICEN oficial;
   - el ICEN oficial que repite el informe coincide con el del IGP (±0,05);
   - el número del informe corresponde al comunicado vigente y el informe tiene menos de 45 días.
3. **Procedencia.** Todo valor publicado lleva la URL del PDF, la página y la cita textual de donde salió; el
   sitio la muestra bajo cada tabla.
4. **Si algo falla** (no se encuentra el informe, cambió el formato, un valor es implausible): se conserva el
   último valor bueno marcado como arrastrado, la vista lo muestra como «atrasado» y queda una incidencia en
   `run-report.json`, que abre un issue en GitHub.
5. **El ICEN temporal se retira solo** cuando el IGP publica el ICEN oficial de ese mes.

## Respaldo con un modelo de lenguaje (opcional, apagado)

Solo se usa cuando la lectura determinista falla por cambio de formato. Nunca publica: deja una **propuesta**
en `informe.review` para que una persona la revise.

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
- **sin dato**: la fuente no dio nada en esta publicación.

El resultado va en `dashboard.json` (`freshness`). Cada vista muestra un panel «Vigencia de los datos» con el
peor estado de sus paneles y, desplegado, cada dato con su fecha, fuente y próxima publicación esperada. Los
datos atrasados quedan como incidencia `late-<id>`.
