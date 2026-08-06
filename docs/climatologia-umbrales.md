# Climatología y umbrales — Observatorio ENSO Perú

> Formal Spanish. Documenta las climatologías y los umbrales de
> categorización de cada indicador.

## 1. Climatologías por fuente

| Fuente / producto | Climatología | Notas |
|-------------------|--------------|-------|
| NOAA / PSL (Niño 1+2, 3.4) | 1981–2010 | Publicada por PSL. |
| NOAA / CPC (ONI heredado) | 1971–2000 (fija) | Base fija del ONI histórico. |
| NOAA / CPC (RONI) | Móvil de 30 años (adaptativa) | Reduce el sesgo por calentamiento secular. |
| ENFEN (ICEN) | Móvil de 30 años (metodología ENFEN) | Reproduce la metodología oficial. |
| NCEP/NCAR Reanalysis (u850) | Reanálisis | Climatología del propio reanálisis. |
| GODAS (D20) | GODAS | Climatología del sistema GODAS. |
| SOI (Tahiti, Darwin) | Estandarizada de las estaciones | Climatología de las propias estaciones. |

## 2. Umbrales ICEN (costero, metodología ENFEN)

| Etiqueta | Mín (°C) | Máx (°C) | Clasificación |
|----------|----------|----------|---------------|
| Normal | −0.4 | 0.4 | Normal |
| Débil | 0.4 | 1.0 | El Niño Costero débil |
| Moderado | 1.0 | 1.5 | El Niño Costero moderado |
| Fuerte | 1.5 | 2.0 | El Niño Costero fuerte |
| Muy fuerte | 2.0 | +∞ | El Niño Costero muy fuerte |
| La Niña Costera débil | −1.0 | −0.4 | La Niña Costera débil |
| La Niña Costera moderada | −1.5 | −1.0 | La Niña Costera moderada |
| La Niña Costera fuerte | −∞ | −1.5 | La Niña Costera fuerte |

**Activación de evento**: requiere persistencia (3 meses consecutivos
en la categoría). Las etiquetas de magnitud son interpretación del
observatorio, sujetas a la publicación oficial de ENFEN.

## 3. Umbrales RONI (cuenca, operativo NOAA/CPC)

| Etiqueta | Mín (°C) | Máx (°C) | Clasificación |
|----------|----------|----------|---------------|
| Neutral | −0.5 | 0.5 | ENSO Neutral |
| El Niño | 0.5 | +∞ | El Niño |
| La Niña | −∞ | −0.5 | La Niña |

**Activación**: umbral operativo ±0.5 °C sostenido (3 meses). El RONI
reemplaza al ONI heredado en el monitoreo oficial.

## 4. Umbrales cualitativos de interpretación

### 4.1 SOI
- SOI ≤ −0.5 (sostenido) ⇒ componente atmosférica de El Niño.
- SOI ≥ +0.5 (sostenido) ⇒ componente atmosférica de La Niña.
- |SOI| < 0.5 ⇒ componente atmosférica neutral.

### 4.2 Viento zonal a 850 hPa (anomalía)
- u > +0.5 m/s ⇒ anomalía del oeste (westerly), hacia el este. Típico
  de El Niño de cuenca.
- u < −0.5 m/s ⇒ anomalía del este (easterly), hacia el oeste. Típico
  de La Niña de cuenca.
- |u| ≤ 0.5 m/s ⇒ anomalía zonal débil / neutral.

### 4.3 D20 (anomalía, m)
- D20 > +5 m ⇒ termoclina más profunda (señal de El Niño de cuenca).
- D20 < −5 m ⇒ termoclina más somera (señal de La Niña de cuenca).
- |D20| ≤ 5 m ⇒ profundidad cerca de lo normal.

## 5. Cambios de baseline

El RONI difiere del ONI heredado por la baseline:

- **ONI heredado**: ERSST v5 con base fija 1971–2000.
- **RONI**: ERSST v5 con baseline móvil de 30 años (adaptativa).

El RONI reduce el sesgo por el calentamiento secular de la TSM del
Pacífico, evitando que la tendencia a largo plazo se interprete como
un sesgo sistemático hacia El Niño. **No deben confundirse** ambos
índices al comparar eventos históricos.

## 6. Frescura y obsolescencia

- **Mes de corte del observatorio**: 2026-07.
- **Fecha de corte**: 2026-08-02.
- **Umbral de obsolescencia** (`STALE_HOURS_THRESHOLD`): 72 horas
  entre el fin del mes del dato y la fecha de corte.
- Un indicador se marca `stale=True` si:
  - `freshness_hours > 72`, o
  - el dato proviene del caché (fallo de red o esquema).

## 7. Datos preliminares

- Los últimos meses pueden marcarse `flag=preliminary` según la fuente.
- Una revisión posterior actualiza la marca a `final`.
- El estado consolidado propaga la marca preliminar (por ejemplo, el
  dato de ICEN preliminar muestra «Dato preliminar · corte 2026-08-02»).

## 8. Conversiones y normalizaciones

- **Longitud**: 0..360 ↔ −180..180 idempotentes; 270°E ≡ 90°O.
- **NaN**: se preserva; no se rellena.
- **Signos del viento**: u > 0 ⇒ hacia el este (westerly); distinto de
  superficie (10 m).
- **Signos de D20**: + ⇒ más profunda.

## 9. Comparabilidad histórica

Al comparar eventos históricos, tener en cuenta:

1. El RONI y el ONI no son directly comparables por la baseline.
2. El ICEN actual usa la metodología ENFEN vigente; series muy largas
   pueden tener discontinuidades metodológicas.
3. D20 y u850 provienen de reanálisis/asimilación; su incertidumbre
   aumenta hacia el pasado.
4. La cobertura de boyas TAO/TRITON es irregular; los huecos se
   preservan.
