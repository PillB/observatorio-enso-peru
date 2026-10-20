# Catálogo de fuentes

El catálogo ejecutable está en `SOURCES` (`python/enso/observatory.py`);
esta tabla lo resume. «Antigüedad máxima» es la edad máxima, en días, del
último periodo observado antes de marcar el dato como vencido.

| ID | Institución | Producto | Archivo | Antigüedad máxima | Crítica |
|---|---|---|---|---|---|
| `enfen-comunicados` | ENFEN | Comunicados oficiales: listado y PDF del más reciente | `enfen.imarpe.gob.pe` (WordPress JSON y página de comunicados) | 30 | — |
| `igp-icen` | ENFEN / IGP | ICEN | `met.igp.gob.pe/datos/ICEN.txt` | 100 | — |
| `cpc-ensodisc` | NOAA / CPC | ENSO Diagnostic Discussion | `ensodisc.shtml` | 40 | Sí |
| `cpc-wksst` | NOAA / CPC | TSM semanal por región Niño (OISST v2.1) | `wksst9120.for` | 16 | Sí |
| `cpc-sstoi` | NOAA / CPC | TSM mensual por región (OISST v2.1) | `sstoi.indices` | 50 | — |
| `cpc-ersst` | NOAA / CPC | TSM mensual por región (ERSSTv5) | `ersst5.nino.mth.91-20.ascii` | 80 | Sí |
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

Los servidores del ENFEN no siempre resuelven desde GitHub Actions; en
ese caso se usan las copias del Internet Archive (y se pide una nueva).

## Backtesting de formatos

`python/tools/capture_sources.py` (flujo `capture-fixtures`) descarga la
versión actual de cada fuente y versiones históricas del Internet Archive,
y las guarda en `python/tests/fixtures/`. Las pruebas pasan cada lector
por todas esas versiones. El flujo diario además guarda cada respuesta
nueva en la rama `data-archive`, de modo que el corpus crece solo.

## Fuentes evaluadas y no usadas

| Producto | Motivo |
|---|---|
| D20 de GODAS (`dbss_obil`) | Es la profundidad de la capa isotérmica, no la isoterma de 20 °C |
| ERSSTv6 | NOAA lo está adoptando; el flujo de captura lo vigila y se incorporará cuando haya archivos de índices estables |
| Estado de alerta en la portada del ENFEN | Se toma del comunicado, que es el documento oficial |
| BoM SOI | Se usa solo para validar el SOI Troup calculado |
