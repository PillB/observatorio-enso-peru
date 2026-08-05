# Diccionario de datos — Observatorio ENSO Perú

> Formal Spanish. Una fila por indicador con todos sus metadatos.

## Esquema de una serie normalizada

Cada serie (`Series`) tiene:

| Campo          | Tipo                        | Descripción |
|----------------|-----------------------------|-------------|
| `indicatorId`  | string                      | Identificador del indicador (ver tabla). |
| `label`        | string                      | Etiqueta corta en español. |
| `units`        | enum (`degC`, `m`, `m_per_s`, `dimensionless`) | Unidades. |
| `scope`        | enum (`coastal`, `basin`)   | Escala del indicador. |
| `points`       | `MonthlyPoint[]`            | Lista de puntos mensuales. |
| `sourceId`     | string                      | Identificador de la fuente (`SOURCES`). |
| `checksum`     | string (`fnv1a:XXXXXXXX`)   | Checksum FNV-1a 32 bits. |

Cada `MonthlyPoint` tiene:

| Campo   | Tipo                          | Descripción |
|---------|-------------------------------|-------------|
| `month` | string (`YYYY-MM`)            | Mes ISO. |
| `value` | number \| null                | Valor; `null` = sin datos. |
| `flag`  | enum (`final`, `preliminary`) | Marca de revisión. |

## Diccionario de indicadores

| id | scope | units | región | nivel | agregación | climatología | signo | fuente |
|----|-------|-------|--------|-------|------------|--------------|-------|--------|
| `nino12` | coastal | degC | Niño 1+2 (90–80°O, 10°S–0°) | superficie | Media mensual | PSL 1981–2010 | + ⇒ más cálido | `noaa-psl-nino12-anom` |
| `icen` | coastal | degC | Niño 1+2 (90–80°O, 10°S–0°) | superficie | Media móvil 3 meses | ENFEN (baseline móvil 30 a.) | + ⇒ anomalía cálida sostenida | `enfen-imarpe-icen` |
| `nino34` | basin | degC | Niño 3.4 (170–120°O, 5°S–5°N) | superficie | Media mensual | PSL 1981–2010 | + ⇒ más cálido | `noaa-psl-nino34-ersst` |
| `roni` | basin | degC | Niño 3.4 (170–120°O, 5°S–5°N) | superficie | Media móvil 3 meses | Baseline móvil 30 a. (adaptativa) | + ⇒ El Niño cuenca | `noaa-cpc-reroni` |
| `soi` | basin | dimensionless | Tahiti – Darwin | superficie (presión MSL) | Media mensual | Estandarizada estaciones | − ⇒ El Niño | `noaa-psl-soi` |
| `u850` | basin | m_per_s | Pacífico ecuatorial (5°S–5°N) | 850 hPa | Media mensual / anomalía | NCEP/NCAR Reanalysis | + ⇒ hacia el este (westerly) | `noaa-cpc-u850` |
| `d20` | basin | m | Pacífico ecuatorial (2°S–2°N) | subsuperficie (termoclina) | Media mensual / anomalía | GODAS | + ⇒ más profunda | `noaa-cpc-godas` |

## Detalle por indicador

### `nino12` — TSM Niño 1+2
- **Definición**: anomalía mensual de la temperatura superficial del
  mar en la región Niño 1+2 (frente a Ecuador y norte del Perú).
- **Convención**: anomalía respecto a la climatología. Positiva ⇒ más
  cálido (favorable a El Niño Costero); negativa ⇒ más frío (favorable a
  La Niña Costera).
- **Es oficial**: sí.
- **Insumo directo del ICEN**.

### `icen` — Índice Costero El Niño
- **Definición**: media móvil de 3 meses de la anomalía mensual de TSM
  en Niño 1+2.
- **Categorías (umbrales ENFEN)**: Normal (|ICEN|<0.4), Débil
  (0.4–1.0), Moderado (1.0–1.5), Fuerte (1.5–2.0), Muy fuerte (≥2.0),
  y sus equivalentes en frío para La Niña Costera.
- **Activación**: requiere persistencia (3 meses consecutivos).
- **Es oficial**: sí.

### `nino34` — TSM Niño 3.4
- **Definición**: anomalía mensual de TSM en Niño 3.4 (Pacífico
  central).
- **Insumo de los índices operacionales ONI/RONI**.
- **Distinguido del ICEN costero**: un evento de cuenca puede ocurrir
  sin evento costero y viceversa.

### `roni` — Índice Oceánico Relativo del Niño
- **Definición**: media móvil de 3 meses de la anomalía de TSM en
  Niño 3.4 con baseline adaptativa.
- **Umbral operativo**: ±0.5 °C sostenido.
- **Reemplaza al ONI heredado** (base fija 1971–2000) en el monitoreo
  oficial.

### `soi` — Índice de Oscilación del Sur
- **Definición**: anomalía estandarizada de la diferencia de presión
  superficial media entre Tahiti y Darwin.
- **Escala**: cuenca. **No existe «SOI costero»**.

### `u850` — Viento zonal a 850 hPa
- **Definición**: anomalía de la componente zonal u a 850 hPa sobre el
  Pacífico ecuatorial.
- **Convención**: u > 0 ⇒ hacia el este (westerly); u < 0 ⇒ hacia el
  oeste (easterly). Distinto de superficie (10 m) y del valor observado.
- **Interpretación**: las anomalías del oeste favorecen El Niño de
  cuenca.

### `d20` — Profundidad de la isoterma de 20 °C
- **Definición**: anomalía de la profundidad de la isoterma de 20 °C
  (proxy de la termoclina).
- **Convención**: + ⇒ más profunda; − ⇒ más somera.

## Formato de los CSV emitidos por el pipeline

Cada CSV (`python/out/<indicator>.csv`) tiene cabeceras de metadatos +
tabla de datos + checksum final:

```
# indicator_id=nino12
# label=TSM Niño 1+2
# units=degC
# scope=coastal
# source_id=noaa-psl-nino12-anom
# checksum=fnv1a:XXXXXXXX
# data_version=1.0.0
# as_of_month=2026-07
# generated_at=2026-08-02T13:17:00+00:00
# fetched_at=2026-08-02T13:17:00+00:00
# from_cache=false
# preliminary=true
# climatology=PSL 1981–2010
# sign_convention=Anomalía respecto a la climatología. Positiva ⇒ más cálido que lo normal.
month,value,flag
1990-01,-0.20,final
1990-02,-0.10,final
...
2026-07,1.70,preliminary
# file_sha256=<hex>
```

## Manifiesto (`manifest.json`)

```json
{
  "data_version": "1.0.0",
  "as_of_month": "2026-07",
  "as_of_date": "2026-08-02",
  "started_at": "2026-08-02T13:17:00+00:00",
  "finished_at": "2026-08-02T13:17:05+00:00",
  "ok": true,
  "indicators": [
    {"id": "nino12", "ok": true, "stale": false, "from_cache": false,
     "preliminary": true, "last_month": "2026-07", "last_value": 1.70,
     "checksum": "fnv1a:XXXXXXXX", "error": null}
  ]
}
```

## Estado consolidado (`status.json`)

Incluye `coastal`, `basin`, `winds`, `thermocline`, `soi`,
`freshness` (resumen por indicador con `freshness_hours` y `stale`),
`dataVersion` y `generatedAt`. Ver `docs/operaciones-recuperacion.md`
para el manejo de `stale`.
