# Catálogo de fuentes

El catálogo ejecutable está en `SOURCES` (`python/enso/observatory.py`);
esta tabla lo resume. «Antigüedad máxima» es la edad máxima, en días, del
último periodo observado antes de marcar el dato como vencido.

| ID | Institución | Producto | Archivo | Antigüedad máxima | Crítica |
|---|---|---|---|---|---|
| `enfen-comunicados` | ENFEN | Comunicados oficiales: listado y PDF del más reciente | `enfen.imarpe.gob.pe` (WordPress JSON y página de comunicados); réplica de la DHN `dhn.mil.pe/portal/comunicados-oficiales-enfen` | 30 | — |
| `igp-icen` | ENFEN / IGP | ICEN | `met.igp.gob.pe/datos/ICEN.txt` | 100 | — |
| `cpc-ensodisc` | NOAA / CPC | ENSO Diagnostic Discussion | `ensodisc.shtml` | 40 | Sí |
| `cpc-wksst` | NOAA / CPC | TSM semanal por región Niño (OISST v2.1) | `wksst9120.for` | 16 | Sí |
| `cpc-sstoi` | NOAA / CPC | TSM mensual por región (OISST v2.1) | `sstoi.indices` | 50 | — |
| `psl-ersst6-nino12`, `psl-ersst6-nino34` | NOAA / PSL | TSM mensual Niño 1+2 y 3.4 (ERSSTv6) | `nina1.anom.data`, `nina34.anom.data` | 50 | — |
| `cpc-roni` | NOAA / CPC | RONI (oficial) | `RONI.ascii.txt` | 80 | Sí |
| `cpc-oni` | NOAA / CPC | ONI (referencia) | `oni.ascii.txt` | 80 | — |
| `cpc-soi` | NOAA / CPC | SOI estandarizado | `soi` | 50 | — |
| `cpc-tahiti`, `cpc-darwin` | NOAA / CPC | Presión a nivel del mar (para el SOI Troup) | `tahiti`, `darwin` | 50 | — |
| `cpc-wpac850`, `cpc-cpac850`, `cpc-epac850` | NOAA / CPC | Vientos alisios a 850 hPa | `wpac850`, `cpac850`, `epac850` | 50 | — |
| `cpc-heat` | NOAA / CPC | Contenido de calor 0–300 m (GODAS) | `heat_content_index.txt` | 50 | — |

Una fuente «crítica» sin ningún dato (ni directo, ni de archivo, ni de la
publicación anterior) detiene el despliegue.

## Cómo se obtiene lo más reciente del ENFEN

El ENFEN publica sus comunicados como PDF en un sitio WordPress cuyo
formato ha cambiado varias veces (2018, 2021, 2024). Para no depender de
una sola página:

1. Se lee el listado (WordPress JSON o HTML) y se toma el número más alto.
2. Se sondean los dos números siguientes por su página de descarga
   (`/download/comunicado-oficial-enfen-n-NN-AAAA/`), y en enero el n.º 01
   del año nuevo. Así se detecta un comunicado nuevo aunque el listado
   todavía no lo muestre.
3. Se descarga el PDF y se extrae el tipo de alerta, el número, la fecha
   y la fecha del siguiente comunicado.
4. Si el listado muestra un número más nuevo que el que se pudo leer, el
   estado se marca vencido y se registra la incidencia.

Los servidores del ENFEN no resuelven desde GitHub Actions y tampoco
responden al Internet Archive (HTTP 523 al pedir una copia nueva). Por eso
el listado se lee también de la réplica de la Dirección de Hidrografía y
Navegación (DHN), miembro del ENFEN, que publica cada comunicado como PDF
directo (`/Archivos/oceanografia/enfen/comunicado-oficial/NN-AAAA.pdf`,
formato estable desde 2022). Los sondeos de números nuevos prueban
primero ese PDF. Si nada responde, se usa la copia más reciente del
Internet Archive. El listado también reconoce los comunicados
extraordinarios, que el ENFEN emite durante los eventos con numeración
propia.

## Backtesting de formatos

`python/tools/capture_sources.py` (flujo `capture-fixtures`) descarga la
versión actual de cada fuente y versiones históricas del Internet Archive,
y las guarda en `python/tests/fixtures/`. Las pruebas pasan cada lector
por todas esas versiones. El flujo diario además guarda cada respuesta
nueva en la rama `data-archive`, de modo que el corpus crece solo.

## Acceso verificado desde GitHub Actions (20 de octubre de 2026)

| Institución | Resultado | Uso |
|---|---|---|
| NOAA CPC, PSL, NCEI, ERDDAP | Responden | En uso (CPC, PSL); NCEI y ERDDAP disponibles para mapas |
| IGP (`met.igp.gob.pe`) | Responde | En uso (ICEN) |
| DHN (comunicados ENFEN) | Responde | En uso como réplica |
| ENFEN (`enfen.imarpe.gob.pe`) | No resuelve el nombre | Réplica DHN e Internet Archive |
| IMARPE | HTTP 403 (bloqueo) | No disponible |
| SENAMHI (avisos, estaciones, boletines) | Tiempo de espera agotado | No disponible desde Actions |
| ANA (caudales, SNIRH) | Tiempo de espera agotado | No disponible desde Actions |
| INDECI, CENEPRED (SIGRID) | Responden | Candidatos |
| CHIRPS (lluvia satelital) | Responde | Candidato |
| NASA GPM IMERG | El índice responde; los datos piden cuenta Earthdata | Requiere credencial |
| CIIFEN, INAMHI, INOCAR, IDEAM | Responden | Candidatos regionales |
| CPPS (ERFEN), SHOA, DMC Chile | URL probada no válida (404/405) | Por revisar |

## Fuentes evaluadas y no usadas

| Producto | Motivo |
|---|---|
| D20 de GODAS (`dbss_obil`) | Es la profundidad de la capa isotérmica, no la isoterma de 20 °C |
| ERSSTv5 (`ersst5.nino.mth.91-20.ascii`) | NOAA dejó de actualizarlo en junio de 2026; se conserva solo en las pruebas |
| ERSSTv6 Niño 1+2 en el CPC | El CPC solo publica Niño 3.4 en v6; Niño 1+2 se toma de PSL |
| Estado de alerta en la portada del ENFEN | Se toma del comunicado, que es el documento oficial |
| BoM SOI | Se usa solo para validar el SOI Troup calculado |
