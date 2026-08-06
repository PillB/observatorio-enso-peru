# Catálogo de fuentes — Observatorio ENSO Perú

> Formal Spanish. Catálogo de fuentes verificadas con endpoint,
> frecuencia, licencia y estado de verificación.

## Resumen de estados

| Estado      | Significado |
|-------------|-------------|
| VERIFIED    | Fuente verificada por investigación directa; endpoint responde y el esquema es estable. |
| ASSUMED     | Se asume correcta pero no se ha verificado completamente. |
| UNRESOLVED  | Hay dudas sobre la disponibilidad o el esquema; en investigación. |
| REJECTED    | Fuente rechazada por inviable o no autoritativa. |

Todas las fuentes del observatorio están en estado **VERIFIED** a fecha
de corte 2026-08-02.

## Catálogo

| ID | Institución | Producto | Endpoint | Formato | Frecuencia | Latencia | Licencia | Estado | Respaldo |
|----|-------------|----------|----------|---------|------------|----------|----------|--------|----------|
| `noaa-cpc-enso-discussion` | NOAA / CPC | ENSO Diagnostic Discussion — ENSO Alert System | https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml | HTML | Mensual (2.º jueves) | Días | Dominio público (EE. UU.) | VERIFIED | `noaa-cpc-enso-evolution-pdf` |
| `noaa-cpc-reroni` | NOAA / CPC | Relative Oceanic Niño Index (RONI) / ONI v5 | https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/ | HTML + tablas | Mensual | Semanas | Dominio público (EE. UU.) | VERIFIED | `noaa-psl-nino34-ersst` |
| `noaa-cpc-enso-evolution-pdf` | NOAA / CPC | ENSO: Recent Evolution, Current Status and Predictions (PDF) | https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/lanina/enso_evolution-status-fcsts-web.pdf | PDF | Semanal (lunes) | 1–2 días | Dominio público (EE. UU.) | VERIFIED | `noaa-cpc-enso-discussion` |
| `noaa-psl-nino34-ersst` | NOAA / PSL | Niño 3.4 SST Index — ERSST v5 | https://psl.noaa.gov/data/timeseries/month/Nino34_CPC | CSV / texto / NetCDF | Mensual | Semanas | Dominio público (EE. UU.) | VERIFIED | `noaa-psl-nino12-anom` |
| `noaa-psl-nino12-anom` | NOAA / PSL | Niño 1+2 SST Anomaly (long record) | https://psl.noaa.gov/data/timeseries/month/data/nino12.long.anom.csv | CSV | Mensual | Semanas | Dominio público (EE. Uu.) | VERIFIED | `noaa-psl-nino34-ersst` |
| `noaa-psl-soi` | NOAA / PSL | Southern Oscillation Index (Tahiti – Darwin) | https://psl.noaa.gov/data/timeseries/month/data/soi.long.data | Texto | Mensual | Semanas | Dominio público (EE. Uu.) | VERIFIED | `noaa-cpc-enso-discussion` |
| `noaa-cpc-godas` | NOAA / CPC — GODAS | D20 (isoterma 20 °C) — Pacífico ecuatorial | https://www.cpc.ncep.noaa.gov/products/GODAS/ | NetCDF / gráficos | Semanal | 1–2 semanas | Dominio público (EE. UU.) | VERIFIED | `pmel-tao-triton` |
| `noaa-cpc-u850` | NOAA / CPC — NCEP/NCAR Reanalysis | Anomalía del viento zonal a 850 hPa | https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_update/usswanim.shtml | HTML / derivados | Semanal | Días | Dominio público (EE. UU.) | VERIFIED | `pmel-tao-triton` |
| `pmel-tao-triton` | NOAA / PMEL — TAO/TRITON | Array de boyas ecuatoriales | https://www.pmel.noaa.gov/tao/drupal/disdel/ | NetCDF / boya | Diaria (con vacíos) | Variable | Dominio público (EE. UU.) | VERIFIED | `noaa-cpc-godas` |
| `enfen-imarpe-icen` | ENFEN / IMARPE (SIOFEN) | ICEN y estado de alerta costera | https://siofen.imarpe.gob.pe/nivel2/indice-costero-el-nino-icen | HTML / panel | Mensual | Semanas | Datos abiertos institucionales (atribución) | VERIFIED | `senamhi-fenomeno-el-nino` |
| `senamhi-fenomeno-el-nino` | SENAMHI Perú | Seguimiento del Fenómeno El Niño | https://www.senamhi.gob.pe/?p=fenomeno-el-nino | HTML | Variable | Días–semanas | Datos abiertos institucionales (atribución) | VERIFIED | `enfen-imarpe-icen` |
| `igp-indices-clim` | IGP | Índices climáticos (ENFEN, IGP) | http://met.igp.gob.pe/variabclim/indices.html | HTML | Variable | Variable | Datos abiertos institucionales (atribución) | VERIFIED | `enfen-imarpe-icen` |

## Notas por fuente

### NOAA / CPC — ENSO Diagnostic Discussion
Fuente oficial del estado de alerta ENSO de cuenca. La discusión de
julio 2026 indica «El Niño Advisory» vigente. Se extrae el estado de
alerta textual; los valores numéricos provienen de RONI/Niño 3.4.

### NOAA / CPC — RONI
Índice operacional actual de NOAA/CPC para ENSO de cuenca. Adapta la
línea base para reducir el sesgo por el calentamiento secular de la TSM.
Región Niño 3.4 (5°S–5°N, 120–170°O). No confundir con el ONI heredado
basado en ERSST.v5 con base 1971–2000.

### NOAA / PSL — Niño 1+2 / 3.4 / SOI
Series mensuales públicas en formato CSV/texto. La climatología PSL
publicada es 1981–2010. El SOI usa estaciones Tahiti y Darwin; **no
existe variante costera autorizada**.

### NOAA / CPC — GODAS
D20 como proxy de la profundidad de la termoclina. Anomalía positiva ⇒
termoclina más profunda (típica de El Niño de cuenca).

### NOAA / CPC — u850 (NCEP/NCAR Reanalysis)
Componente zonal u a 850 hPa. Convención: u > 0 ⇒ flujo hacia el este
(westerly); u < 0 ⇒ flujo hacia el oeste (easterly). Distinto de
superficie (10 m) y del valor observado.

### ENFEN / IMARPE — ICEN
ICEN = media móvil de 3 meses de las anomalías mensuales de TSM en
Niño 1+2 (90–80°O, 10°S–0°). Estado «Alerta de El Niño Costero» activo
desde el 13 de febrero de 2026.

### SENAMHI / IGP
Divulgación oficial peruana y validación cruzada de índices costeros y
pronósticos estacionales para Perú.

## Estrategia de respaldo

Cada fuente declara un `fallbackSourceId`. Ante fallo persistente:

1. Reintentos con backoff exponencial + jitter.
2. Caché local marcado `from_cache=True`.
3. Último conjunto válido preservado y marcado `stale=True`.
4. Si la fuente principal cae definitivamente, se puede usar el
   respaldo declarado manteniendo la trazabilidad.

## Verificación periódica

- El pipeline corre diariamente (cron 13:17 UTC).
- Cada corrida produce `manifest.json` con el estado de cada indicador.
- En PR se valida la paridad Python ↔ TS de identificadores.
