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
| 2 | PSL, Niño 3.4 ERSSTv6 (`nina34.anom.data`) | Entre el 6 y el 18 de noviembre PSL reescribió toda la serie con la misma cabecera: 51 de 922 meses antiguos cambiaron más de 0,25 °C (1997-12: +1,78 → +2,36; 2026-10: +2,30 → +2,72). Causa (recalculada desde la malla ERSSTv6 `sst.mnmean.nc`, base 1981-2010): la versión anterior corresponde a la caja 5N-5S **170°E**-120°W (error 0,003 °C) y la nueva a la 170°W-120°W de la cabecera (error 0,003 °C; coincide también con `ersst.v6.el_nino.sst.dat` de NCEI). PSL corrigió un error de longitud sin publicar aviso; la serie del sitio estuvo hasta ~0,6 °C por debajo hasta la corrección. `nina1` (Niño 1+2) no tenía el error | La huella solo mira la estructura; no se comparaban valores con la publicación anterior | Guardia de regresión `enso/drift.py` en cada lectura: `history-rewritten` (no se cierra solo), `series-shrunk`, `series-regressed`, `series-missing` |
| 3 | ENFEN, informe técnico N° 20 | La tabla 3 da ICEN Set-26 = +4,98; el IGP publica +4,50. El temporal de Oct-26 del mismo informe (+4,69) coincide con el del IGP (informe PpR/El Niño-IGP/2026-10, 18-11-2026), los demás meses de la tabla son idénticos al IGP, los temporales previos de septiembre fueron 4,15 (N° 18) y 4,58 (N° 19), y con ERSSTv5 la media ago-oct de Niño 1+2 ronda 4,3: llegar a 4,98 exigiría una anomalía de octubre de ~6,7 °C. Es errata del informe (sin fe de erratas al 20-11) | Ya se detectaba (issue #116), pero el aviso no decía cuál valor era el coherente | El aviso ahora lo dice (`icenMismatch.consistentWith`); el sitio sigue publicando el del IGP. El informe N° 20 queda como prueba |
| 4 | ENFEN, informe técnico N° 20 | Las tablas de probabilidades pasaron de 9 a 10 meses (noviembre 2026 a agosto 2027) | El lector ya toma los meses de la cabecera; la prueba suponía 9 | Prueba ajustada a 9 o 10 meses y a que cada fila tenga tantos valores como meses |
| 5 | ENFEN, informe técnico (ONI y RONI) | Sin problema hoy (coinciden con NOAA), pero una columna corrida en la tabla de índices pasaría la validación de rangos | No había contraste | `informe-oni-mismatch` e `informe-roni-mismatch` si difieren de NOAA en más de 0,1 |
| 6 | NOAA, discusión ENSO | Los valores de Niño que cita el texto (+2,5 en 3.4) ya no son las anomalías semanales tradicionales (+3,2) sino las **relativas del último mes** (`rel_mthsst9120.txt`), desde la adopción del RONI | El campo se llamaba `weekly_values_in_text`; no se muestra en el sitio, pero cualquiera que lo comparara con las series vería casi 1 °C de diferencia | `valuesInTextBasis` (`traditional-weekly`, `traditional-monthly` u `other`) en `official.noaa` |
| 7 | Feeds oficiales de peligros | Una fuente de avisos caída (SENAMHI, COEN, DHN, IGP, PTWC, FIRMS, CIIFEN…) solo dejaba un `info` | Las `info` no abren issue | `hazard-feed-down` (aviso, un issue por fuente) si no da un feed dos corridas seguidas, ni directo ni por copias |
| 8 | ENFEN, API de WordPress | Ya no está congelada en el N° 13: llega al 19 (el portal va por el 20) | Documentación | `catalogo-fuentes.md` actualizado; el código ya la trataba como candidata |
| 9 | Feeds de noticias inactivos por semanas (Nacional Callao TV, RPP · Huancavelica, Altavoz · tema Huancavelica, Noticias SER, Peru Reports) | El feed, la página del medio y la API de WordPress (`/wp-json/wp/v2/posts`) dan la misma última fecha: el lector no pierde entradas y ninguna URL cambió. Cuatro medios publican a rachas (huecos de 70 a 173 días) con un `stale_days` de 7 o 21; `www.noticiasser.pe` publica desde el 17-04-2026 guías de finanzas en tandas (143 entradas), no noticias de la Asociación SER | `feed-inactive` es `info` y no abre issue; no había umbral para «callado demasiado tiempo» | Noticias SER quitado; `stale_days` de Peru Reports (21), Nacional Callao TV (60) y Altavoz · Huancavelica (60) según sus fechas; `longestGapDays` en `news/feeds.json` y `feed-stale` (aviso, un issue por feed) pasado el doble de `stale_days` y su hueco más largo (hasta 180 días). Repasado con las 8868 copias de `data-archive`: no habría saltado ninguna vez |

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

- **CPC, `ersst5.nino.mth.91-20.ascii`**: dejó de actualizarse en 2026-06 (NCEI retiró ERSSTv5 de CPC; el IGP sigue calculando el ICEN con ERSSTv5). El ICEN del sitio sale del archivo del IGP, no de ese.
- **PSL, `nina1.anom.data`**: la cabecera dice «270W-280E» (debería ser 90W-80W); los valores sí son Niño 1+2.

- **IDESEP del SENAMHI**, capa `view_aviso_24horas_5dias_ultimos`: devuelve 0 avisos con avisos vigentes en la
  tabla. El recolector la sigue bajando solo como medición; ningún dato del sitio sale de ella.
- **DHN, PDF de comunicados**: verificación humana a servidores desde el 20 de octubre (conocido); el PDF llega del
  portal del ENFEN vía el recolector del Perú.
- **Radio Santa Rosa** respondió una vez «Account Suspended» y **GDACS** una vez su página de administración: no son
  verificaciones; si se repiten, `hazard-feed-down` (GDACS) o `feed-down` lo registran.
- **IGP, alertas del CENVUL**: la más reciente es del 1 de junio de 2026; es real: la página la pone primera en sus dos variantes (21-11-2026).

## Revisión del 21 de noviembre (después de fusionar)

Segunda pasada adversarial, con las tres corridas diarias posteriores a la fusión: las guardias corren en todas las
fuentes con series y la auditoría completa de `data-archive` no da falsos positivos, pero el fallback antirobots aún no
se usó en producción (los 13 feeds respondieron directo). Se corrigió:

- **La guardia se saltaba** el día en que una fuente volvía después de una corrida que arrastró el dato, y sin aviso si
  la publicación anterior no se podía leer: ahora compara también con la base arrastrada y anota `drift-unchecked`.
- **Los avisos de `enso.drift` se cerraban solos** al día siguiente (solo aparecen el día del cambio) con el dato malo
  publicado: ahora no se cierran solos, y el issue dice «reescritura del histórico», no «cambio de formato».
- **Copias que n8n arrastra**: el IGP (CENVUL) daba HTTP 500 a n8n y el sitio mostraba el feed como bueno con la copia
  del día anterior. Esa copia ahora cuenta como caída para `hazard-feed-down`, que además exige 6 h entre las dos
  corridas e ignora los feeds que no se pidieron.
- **Internet Archive**: sus copias de una página de verificación ya no se usan como fuente.
- **CENVUL «sin entradas con fecha»**: el servidor (Nuxt) escribe las fechas en inglés o en castellano según la
  instancia que atiende, al azar y sin hacer caso de `Accept-Language` (24 lecturas el 21-11: 12 en inglés y 12 en
  castellano; data-archive guarda las dos variantes casi todos los días desde el 21-10). El lector solo entendía la
  inglesa: con la castellana los boletines salían sin fecha y las 10 alertas se fundían en 2. Ahora lee las dos, y una
  fecha que no reconoce en ninguna tarjeta es un error de formato (`formatError`), no un feed «inactivo».
- **Firmas**: Imunify360 por el formulario `wsidchk`, la cabecera `server: imunify360-webshield` y su página de
  captcha; Sucuri CloudProxy (`sucuri_cloudproxy_js`), Wordfence, SiteGround (`sgcaptcha`), GoDaddy y Vercel. Paridad
  con n8n en `fixtures/reach-parity.json`.
- **DHN**: desde noviembre todos los PDF de `/Archivos` redirigen a `/human-check.php` (Turnstile); se reconoce como
  verificación y los PDF del ENFEN dependían de la copia del recolector del Perú. Ahora hay una ruta directa y
  oficial: gob.pe, donde el SENAMHI publica el mismo PDF el mismo día (`feeds/gobpe_enfen.py`); y si ningún listado
  de comunicados responde en vivo con la copia del Perú de más de 36 h, queda `listing-stale`.
- **PTWC**: el simulacro PACWAVE26 (5-11-2026) salía como aviso de tsunami; los mensajes de prueba ya no son entradas.
- `valuesInTextBasis` se calcula con las semanas y meses anteriores a la fecha de la discusión (antes pasaba a
  `other` dos semanas después); el contraste del ICEN dice `undetermined` cuando el temporal queda a igual distancia;
  los umbrales (0,05, 0,1 y 0,25) ya no fallan por redondeo en el valor exacto.
- **Auditoría semanal**: los 39 hallazgos ya revisados (38 páginas de Imunify360 y la corrección de PSL) están en
  `python/tools/drift_audit_known.json` y no la hacen fallar (la primera corrida, el lunes 23, habría fallado con 26);
  `--days` lee solo la ventana más la versión anterior, `--source` limita todo, revisa también `.html` y `.csv`, sale
  con 2 si no puede auditar y, si encuentra algo, abre un issue `incidente-datos`.

Sin cambio: la ventana del ICEN si el IGP pasa a ERSSTv6 (el aviso ya dice que el archivo del IGP podría estar
revisado) y un cambio de base de PSL (el sitio recalcula la base: no se usa la del archivo).

## Huecos de las pruebas (21 de noviembre)

La revisión adversarial encontró tres huecos; se corrigieron con pruebas que fallan con el error y pasan sin él
(`tests/test_guard_thresholds.py`, `tests/test_block_pages.py`, `tests/test_drift_audit.py`):

- **Formularios con reCAPTCHA**: `fetch.block_page` descartaba como verificación cualquier página HTML de menos de
  40 KB con «g-recaptcha», «h-captcha» o «security check», también un aviso o un listado con un formulario de
  suscripción: `Fetcher.get` la tomaba por bloqueo y perdía la fuente. Esas dos familias (`GENERIC_BLOCKS`) ahora
  necesitan una prueba de que la página es la verificación (`challenge_evidence`): menos de 600 caracteres de texto
  visible, una recarga (`<meta http-equiv=refresh>`, `location.replace(…)`, `location.reload()`) o HTML cuando se pedía
  otra cosa (un PDF). Las familias propias (Cloudflare, Imunify360, AWS WAF, DHN por su texto y su tamaño) bastan,
  aunque la página nombre también reCAPTCHA. `reach.classify` no cambia (paridad con n8n). Las 38 páginas de
  Imunify360 de `data-archive` y las verificaciones de `fixtures` se siguen reconociendo; ninguna copia archivada
  tenía solo una marca genérica.
- **Copias del mismo día**: la auditoría las ordenaba por nombre (`AAAA-MM-DD-<sha>`), y el hash no dice cuál llegó
  primero: en 1.352 de los 1.998 días con varias copias de una fuente el orden quedaba al revés (casi todos feeds
  de noticias, que no tienen series; en las fuentes con series hubo un solo caso y en el orden correcto, así que no
  produjo hallazgos falsos todavía). Ahora se ordenan por la hora del commit que agregó cada copia (`added_times`);
  con una ref sin historia, por nombre y con un aviso. El job semanal trae 12 días de historia
  (`--shallow-since`). Una respuesta igual a una ya archivada no se vuelve a guardar: si una fuente vuelve por la
  tarde a la versión de la mañana, el archivo no lo registra.
- **Umbrales sin pruebas en su borde**: `REWRITE_MIN_POINTS`, `REWRITE_FRACTION`, el punto de corte de los recientes,
  `SHRINK_TOLERANCE`, el tipo de fuente de `official_alerts`, la penúltima semana y el penúltimo mes de
  `ensodisc_basis` y el tamaño de `block_page` se podían cambiar sin que fallara ninguna prueba. Ahora cada uno tiene
  una prueba en su borde.

## Errores de la misma clase (21 de noviembre, tercera pasada)

Se buscaron en todo el código las mismas clases de error que los hallazgos anteriores: servidores que responden
distinto según el pedido, lectura de fechas que depende del idioma, claves de identidad hechas con campos que
cambian, umbrales con decimales, valores por omisión que callan un problema y el día de Lima. Se corrigió:

- **La misma nota, varias veces en el histórico**: el `id` de cada nota sale del enlace y del titular tal como
  llegan. El feed de Pro & Contra arma los enlaces con el esquema y el servidor del pedido (57 copias en
  `data-archive` con cuatro variantes: `http`/`https`, con y sin `www`), GDACS alterna `http` y `https`, Google
  Noticias cambia el nombre del medio que agrega al titular y los medios corrigen titulares: 397 de las 13.458
  notas del histórico eran otra copia de una nota ya guardada (la nota «Defensora ambiental…» estaba cuatro
  veces, el sismo `us6000u1kt` del USGS dos, una con la magnitud preliminar). `news.new_lines` ahora reconoce la
  nota por su enlace canónico (`news.canonical_link`: `https`, sin `www`, sin parámetros de seguimiento; la ruta,
  la consulta y el fragmento se conservan, porque distinguen avisos de la DHN y del CENVUL y notas de Google
  Noticias). Una variante con el mismo titular no se agrega; un titular distinto es una corrección y se agrega
  con `revises` (el `id` de la primera versión), y los grupos (`news.cluster`) muestran la última versión. FIRMS,
  cuyo resumen diario enlaza siempre al mismo mapa, sigue por `id` (`Feed.link_is_id`), y también un enlace que
  un feed pone a dos titulares en la misma lectura. Repasado con el histórico entero: 66 notas no se habrían
  repetido y 273 habrían quedado como corrección. Entre las correcciones hay entradas que el medio o la institución publica en el mismo enlace pero que no son la misma nota: los en vivo de RPP y El Comercio («Temblor en Perú, hoy 22 de octubre» → «hoy 24 de octubre» en la misma dirección) y los reportes sucesivos del COEN de una misma emergencia (Reporte N° 02 → N° 03). El histórico guarda cada una; los grupos muestran solo la última. El registro dice cuántas cada
  día (`news-same-story`, `info`). Los `id` no cambian: las anclas del archivo y el histórico publicado siguen
  sirviendo.
- **Fechas en inglés del CENVUL según el idioma del proceso**: se leían con `strptime("%A, %B %d, %Y")`, cuyos
  nombres salen del `LC_TIME` del proceso; con el sistema en castellano (un recolector en una máquina en es_PE,
  o una biblioteca que llame a `locale.setlocale`) la variante inglesa dejaba de leerse. Ahora con tabla propia.
- **El día de la corrida era el UTC**: la corrida diaria empieza a las 04:37 UTC, las 23:37 del día anterior en
  Lima, así que cada noche el sitio contaba un día de más y el último día de cada mes daba por vencido el
  escenario del CENEPRED (`observatory.run_date`). El archivo crudo sigue nombrado por la fecha UTC.

Pruebas: `tests/test_news_identity.py` (copias reales de Pro & Contra y del USGS, y tres líneas reales del
histórico), `tests/test_hazards.py::test_cenvul_english_dates_do_not_depend_on_the_process_locale` y
`tests/test_lima_day.py` (con la hora del cron real). Cada una falla con el error.

## Cómo repetirla

```bash
cd python
git fetch --shallow-since="$(date -u -d '12 days ago' +%F)" origin data-archive  # con historia: orden del mismo día
python -m tools.drift_audit --ref FETCH_HEAD          # 0: nada nuevo; 1: hallazgos; 2: no pudo auditar
python -m tools.drift_audit --ref FETCH_HEAD --all    # también los ya revisados (39 al 21-11-2026)
python -m pytest tests/test_drift.py tests/test_drift_followup.py tests/test_drift_audit.py tests/test_block_pages.py \
  tests/test_cross_checks.py tests/test_reports.py tests/test_reach_parity.py tests/test_guard_thresholds.py
node --test ../n8n/test/lib.test.mjs   # las mismas firmas en n8n
```

Cada lunes, `.github/workflows/drift-audit.yml` corre la auditoría sobre las copias de la última semana (`--days 7`) y
falla, con un issue, si aparece algo nuevo; la corrida diaria, además, compara cada lectura con la publicación anterior
y abre un issue por cada hallazgo. Lo revisado se agrega a `python/tools/drift_audit_known.json` con una nota. Las
copias que muestran cada caso están en `python/tests/fixtures/drift/` (PSL), `python/tests/fixtures/sources/blocked/`
(Imunify360, DHN) y `python/tests/fixtures/reports/` (informe N° 20).
