# Auditoría de deriva de las fuentes (20 de noviembre de 2026)

Revisión adversarial de cada recolector (corrida diaria en GitHub Actions, flujo de n8n y recolector del Perú):
para cada fuente se bajó la respuesta actual, se pasó por el lector que usa el sitio y se comparó con lo que el lector
espera y con lo publicado. La pregunta no era «¿falla?» (eso ya lo vigilan `format-changed`, `format-drift`, los
`stale-*` y el vigilante) sino «¿qué puede estar mal sin que nada falle?».

## Cómo se hizo

| Red | Qué se leyó | Cómo |
|---|---|---|
| Directo (EE. UU.) | NOAA/CPC (14 archivos), PSL (Niño 1+2 y 3.4), discusión ENSO, GEOSINPAD (capas del SENAMHI) | Bajados el 20-11-2026 y leídos con `SOURCES[*].parse`; huella comparada con la publicada |
| Recolector del Perú | ENFEN (WP JSON, portal, informes, PDF del comunicado 20 y del informe técnico 20), ICEN del IGP, tabla de avisos del SENAMHI, IDESEP, repositorio del IMARPE, SIGRID | Copia del 19-11-2026 02:47 (`data-peru`) |
| n8n | 154 URL (noticias, NOAA, ENFEN/DHN, SENAMHI, INDECI, IGP, DHN) | Copia del 19-11-2026 03:53 (`data-n8n`) |
| Archivo | 187 fuentes, todas sus versiones | `data-archive`, releídas con `python -m tools.drift_audit` |

## Hallazgos

| # | Fuente | Qué pasaba | Por qué nadie lo vio | Qué se hizo |
|---|---|---|---|---|
| 1 | 13 feeds en WordPress con Imunify360 (Sol TV ×4, Radio Huancayo, CIIFEN, Los Andes, Diario del Cusco, Radio Yaraví, Pregón, Reina de la Selva, Callao TV, Santa Rosa) | Desde fines de octubre responden de vez en cuando a Actions con «One moment, please...» y **HTTP 200**. El cliente lo tomaba por respuesta válida: el feed quedaba «caído» aunque n8n tenía el feed bueno, y la página quedaba archivada como si fuera el feed (38 copias en `data-archive`). CIIFEN, fuente de peligros, lleva desde el 30 de octubre sin leerse | La página no tenía ninguna firma de bloqueo conocida; un 200 no se cuestionaba; el error se anotaba como `info` | Firma `imunify360` en `reach.py` y `n8n/lib/classify.js`; `Fetcher.get` descarta un 200 que es página de verificación (no se evade), lo anota como `challenge` y sigue con las copias de n8n y del Perú; `Relay.get` tampoco sirve una copia así |
| 2 | PSL, Niño 3.4 ERSSTv6 (`nina34.anom.data`) | Entre el 6 y el 18 de noviembre PSL reescribió toda la serie con la misma cabecera: 51 de 922 meses antiguos cambiaron más de 0,25 °C (1997-12: +1,78 → +2,36; 2026-10: +2,30 → +2,72). La versión nueva se acerca más al ONI (error cuadrático 0,26 frente a 0,31), así que parece una corrección de PSL, pero el sitio cambió su serie Niño 3.4 sin aviso | La huella solo mira la estructura; no se comparaban valores con la publicación anterior | Guardia de regresión `enso/drift.py` en cada lectura: `history-rewritten` (no se cierra solo), `series-shrunk`, `series-regressed`, `series-missing` |
| 3 | ENFEN, informe técnico N° 20 | La tabla 3 da ICEN Set-26 = +4,98; el IGP publica +4,50. El temporal de Oct-26 del mismo informe (+4,69) y la subida de Niño 1+2 indican errata en el informe | Ya se detectaba (issue #116), pero el aviso no decía cuál valor era el coherente | El aviso ahora lo dice (`icenMismatch.consistentWith`); el sitio sigue publicando el del IGP. El informe N° 20 queda como prueba |
| 4 | ENFEN, informe técnico N° 20 | Las tablas de probabilidades pasaron de 9 a 10 meses (noviembre 2026 a agosto 2027) | El lector ya toma los meses de la cabecera; la prueba suponía 9 | Prueba ajustada a 9 o 10 meses y a que cada fila tenga tantos valores como meses |
| 5 | ENFEN, informe técnico (ONI y RONI) | Sin problema hoy (coinciden con NOAA), pero una columna corrida en la tabla de índices pasaría la validación de rangos | No había contraste | `informe-oni-mismatch` e `informe-roni-mismatch` si difieren de NOAA en más de 0,1 |
| 6 | NOAA, discusión ENSO | Los valores de Niño que cita el texto (+2,5 en 3.4) ya no son las anomalías semanales tradicionales (+3,2) sino las **relativas del último mes** (`rel_mthsst9120.txt`), desde la adopción del RONI | El campo se llamaba `weekly_values_in_text`; no se muestra en el sitio, pero cualquiera que lo comparara con las series vería casi 1 °C de diferencia | `valuesInTextBasis` (`traditional-weekly`, `traditional-monthly` u `other`) en `official.noaa` |
| 7 | Feeds oficiales de peligros | Una fuente de avisos caída (SENAMHI, COEN, DHN, IGP, PTWC, FIRMS, CIIFEN…) solo dejaba un `info` | Las `info` no abren issue | `hazard-feed-down` (aviso, un issue por fuente) si no da un feed dos corridas seguidas, ni directo ni por copias |
| 8 | ENFEN, API de WordPress | Ya no está congelada en el N° 13: llega al 19 (el portal va por el 20) | Documentación | `catalogo-fuentes.md` actualizado; el código ya la trataba como candidata |

## Fuentes revisadas sin deriva

- **NOAA/CPC** (`wksst9120.for`, `sstoi.indices`, `RONI.ascii.txt`, `oni.ascii.txt`, `soi`, `tahiti`, `darwin`,
  `wpac850`, `cpac850`, `epac850`, `heat_content_index.txt`, `ensodisc.shtml`): las 14 huellas en vivo coinciden con
  las publicadas; último dato semanal 11-11-2026 y mensual 2026-10, al día con el calendario de CPC. Los valores
  extremos de 2026 (alisios en Pacífico central −8,6 m/s de anomalía, Niño 1+2 +5,4 °C) están en el archivo original.
- **IGP, ICEN**: formato igual; Set-26 publicado el 4 de noviembre.
- **ENFEN**: listado del portal (solo el último comunicado, como antes), réplica de la DHN (20 a 13), WP JSON,
  informe técnico 20 (índices, probabilidades, termoclina) y comunicado 20 se leen bien.
- **SENAMHI, tabla de avisos** (`?p=aviso-meteorologico`): se leen niveles, fechas y extensiones; avisos vigentes
  del 19 al 21 de noviembre.
- **GEOSINPAD** (capas del SENAMHI en el servidor del INDECI): las capas 2, 4 y 5 responden con datos del 18 y 19 de
  noviembre. La capa 3 (FWI) está vacía en el servidor; el registro ya no dice «¿?» sino que respondió sin entradas.

## Riesgos que quedan (anotados, sin cambio de código)

- **IDESEP del SENAMHI**, capa `view_aviso_24horas_5dias_ultimos`: devuelve 0 avisos con avisos vigentes en la
  tabla. El recolector la sigue bajando solo como medición; ningún dato del sitio sale de ella.
- **DHN, PDF de comunicados**: verificación humana a servidores desde el 20 de octubre (conocido); el PDF llega del
  portal del ENFEN vía el recolector del Perú.
- **Radio Santa Rosa** respondió una vez «Account Suspended» y **GDACS** una vez su página de administración: no son
  verificaciones; si se repiten, `hazard-feed-down` (GDACS) o `feed-down` lo registran.
- **IGP, alertas del CENVUL**: la más reciente es del 1 de junio de 2026; puede ser real (sin alertas nuevas).

## Cómo repetirla

```bash
cd python
git fetch origin data-archive
python -m tools.drift_audit            # releer todo el archivo con los lectores y las firmas actuales
python -m pytest tests/test_drift.py tests/test_block_pages.py tests/test_cross_checks.py tests/test_reports.py
node --test ../n8n/test/lib.test.mjs   # la misma firma en n8n
```

`tools.drift_audit` sale con 1 si encuentra algo. Cada lunes, `.github/workflows/drift-audit.yml` lo corre sobre las
copias de la última semana (`--days 8`) y la corrida falla si aparece algo nuevo; la corrida diaria, además, compara
cada lectura con la publicación anterior y abre un issue por cada hallazgo. Las copias que muestran cada caso están en
`python/tests/fixtures/drift/` (PSL), `python/tests/fixtures/sources/blocked/` (Imunify360) y
`python/tests/fixtures/reports/` (informe N° 20).
