# Definiciones de indicadores — Observatorio ENSO Perú

> Formal Spanish. Definiciones científicas completas, espejo de
> `src/lib/enso/methodology.ts` y `python/enso/methodology.py`.

## 1. TSM Niño 1+2 — `nino12`

**Nombre completo**: Anomalía de la temperatura superficial del mar —
región Niño 1+2.

- **Variable**: anomalía mensual de TSM.
- **Unidades**: °C.
- **Región**: Niño 1+2 (frente a Ecuador y norte del Perú).
- **Límites**: 10°S – 0°, 90°O – 80°O.
- **Nivel**: superficie.
- **Agregación**: media mensual.
- **Climatología**: variable según fuente (PSL: 1981–2010).
- **Dataset**: NOAA / PSL (ERSST v5 / OISST).
- **Convención de signos**: anomalía respecto a la climatología.
  Positiva ⇒ más cálido que lo normal. Negativa ⇒ más frío que lo
  normal.
- **Signo positivo significa**: mar más cálido de lo normal (favorable
  a El Niño Costero).
- **Signo negativo significa**: mar más frío de lo normal (favorable a
  La Niña Costera).
- **Fuente**: `noaa-psl-nino12-anom`.
- **Es oficial**: sí.
- **Notas**: indicador primario de la condición costera. Insumo directo
  del ICEN.

## 2. ICEN — `icen`

**Nombre completo**: Índice Costero El Niño (ICEN).

- **Variable**: media móvil de 3 meses de la anomalía de TSM en Niño
  1+2.
- **Unidades**: °C.
- **Región**: Niño 1+2 (90–80°O, 10°S–0°).
- **Nivel**: superficie.
- **Agregación**: media móvil de 3 meses.
- **Climatología**: metodología ENFEN (baseline móvil 30 años).
- **Dataset**: ENFEN / IMARPE (a partir de TSM Niño 1+2).
- **Convención de signos**: positivo ⇒ anomalía cálida sostenida en la
  costa.
- **Signo positivo**: condición cálida costera.
- **Signo negativo**: condición fría costera.
- **Umbrales** (metodología ENFEN):
  - |ICEN| < 0.4 °C → Normal
  - 0.4 ≤ ICEN < 1.0 → El Niño Costero débil
  - 1.0 ≤ ICEN < 1.5 → El Niño Costero moderado
  - 1.5 ≤ ICEN < 2.0 → El Niño Costero fuerte
  - ICEN ≥ 2.0 → El Niño Costero muy fuerte
  - −1.0 < ICEN ≤ −0.4 → La Niña Costera débil
  - −1.5 < ICEN ≤ −1.0 → La Niña Costera moderada
  - ICEN ≤ −1.5 → La Niña Costera fuerte
- **Fuente**: `enfen-imarpe-icen`.
- **Es oficial**: sí.
- **Notas**: categorías de intensidad según metodología ENFEN
  documentada. La activación de un evento costero requiere persistencia
  (3 meses consecutivos). Las etiquetas de magnitud son interpretación
  generada por el observatorio sujeta a la publicación oficial de ENFEN.

## 3. TSM Niño 3.4 — `nino34`

**Nombre completo**: Anomalía de la temperatura superficial del mar —
región Niño 3.4.

- **Variable**: anomalía mensual de TSM.
- **Unidades**: °C.
- **Región**: Niño 3.4 (5°S–5°N, 120–170°O).
- **Nivel**: superficie.
- **Agregación**: media mensual.
- **Climatología**: PSL 1981–2010.
- **Dataset**: NOAA / PSL (ERSST v5).
- **Convención de signos**: anomalía respecto a la climatología.
  Positiva ⇒ más cálido.
- **Signo positivo**: Pacífico central más cálido (favorable a El Niño
  de cuenca).
- **Signo negativo**: Pacífico central más frío (favorable a La Niña de
  cuenca).
- **Fuente**: `noaa-psl-nino34-ersst`.
- **Es oficial**: sí.
- **Notas**: insumo de los índices operacionales ONI/RONI. Distinguido
  del ICEN costero: un evento de cuenca puede ocurrir sin evento costero
  y viceversa (ej. 2017 fue costero fuerte sin El Niño de cuenca).

## 4. RONI — `roni`

**Nombre completo**: Índice Oceánico Relativo del Niño (RONI).

- **Variable**: media móvil de 3 meses de anomalía de TSM en Niño 3.4
  con baseline adaptativa.
- **Unidades**: °C.
- **Región**: Niño 3.4 (5°S–5°N, 120–170°O).
- **Nivel**: superficie.
- **Agregación**: media móvil de 3 meses.
- **Climatología**: baseline móvil de 30 años (adaptativa al
  calentamiento secular).
- **Dataset**: NOAA / CPC (RONI).
- **Convención de signos**: positivo ⇒ anomalía cálida sostenida en el
  Pacífico central.
- **Signo positivo**: El Niño de cuenca.
- **Signo negativo**: La Niña de cuenca.
- **Umbrales operativos**:
  - RONI ≥ +0.5 °C sostenido → El Niño
  - RONI ≤ −0.5 °C sostenido → La Niña
  - |RONI| < 0.5 °C → ENSO Neutral
- **Fuente**: `noaa-cpc-reroni`.
- **Es oficial**: sí.
- **Notas**: índice operacional actual de NOAA/CPC para ENSO de cuenca.
  Reemplaza al ONI heredado en el monitoreo oficial. No confundir con
  el ONI de base fija 1971–2000.

## 5. SOI — `soi`

**Nombre completo**: Índice de Oscilación del Sur (SOI).

- **Variable**: anomalía estandarizada de la diferencia de presión
  (Tahiti − Darwin).
- **Unidades**: adimensional.
- **Región**: Tahiti (Pacífico central-sur) y Darwin (norte de
  Australia).
- **Nivel**: superficie (presión media al nivel del mar).
- **Agregación**: media mensual.
- **Climatología**: climatología estandarizada de las estaciones.
- **Dataset**: NOAA / PSL (Tahiti y Darwin).
- **Convención de signos**: SOI negativo ⇒ presión relativamente más
  baja en Tahiti que en Darwin (componente atmosférica de El Niño). SOI
  positivo ⇒ lo contrario (La Niña).
- **Signo positivo**: La Niña (componente atmosférica).
- **Signo negativo**: El Niño (componente atmosférica).
- **Fuente**: `noaa-psl-soi`.
- **Es oficial**: sí.
- **Notas**: índice de escala de cuenca basado en el gradiente de
  presión superficial entre Tahiti y Darwin. **El observatorio NO define
  un «SOI costero»**: no existe un proxy de presión costera con la misma
  definición ni respaldo metodológico equivalente. Cualquier indicador
  de presión costera se etiqueta por separado y con salvedades.

## 6. Viento zonal a 850 hPa — `u850`

**Nombre completo**: Anomalía del viento zonal a 850 hPa — Pacífico
ecuatorial.

- **Variable**: anomalía de la componente zonal u a 850 hPa.
- **Unidades**: m/s.
- **Región**: promedio ecuatorial (5°S–5°N) del Pacífico.
- **Nivel**: 850 hPa (bajo nivel).
- **Agregación**: media mensual / anomalía.
- **Climatología**: NCEP/NCAR Reanalysis.
- **Dataset**: NOAA / CPC (NCEP/NCAR Reanalysis).
- **Convención de signos**:
  - u > 0 ⇒ flujo hacia el **este** (componente del oeste / westerly).
  - u < 0 ⇒ flujo hacia el **oeste** (componente del este / easterly).
  - Se distingue: valor observado vs anomalía; superficie (10 m) vs
    850 hPa; componente zonal vs vectorial.
- **Signo positivo**: anomalía del oeste / westerly (hacia el este).
- **Signo negativo**: anomalía del este / easterly (hacia el oeste).
- **Fuente**: `noaa-cpc-u850`.
- **Es oficial**: sí.
- **Notas**: las anomalías del oeste (westerly) favorecen el
  desplazamiento hacia el este de la masa de agua cálida, típico de El
  Niño de cuenca. No se etiqueta todo viento costero como «alisios»: se
  respeta la terminología de la fuente.

## 7. D20 — `d20`

**Nombre completo**: Anomalía de la profundidad de la isoterma de 20 °C
(D20).

- **Variable**: anomalía de la profundidad de la isoterma de 20 °C.
- **Unidades**: m.
- **Región**: promedio ecuatorial (2°S–2°N) del Pacífico.
- **Nivel**: subsuperficie (termoclina).
- **Agregación**: media mensual / anomalía.
- **Climatología**: GODAS.
- **Dataset**: NOAA / CPC (GODAS).
- **Convención de signos**:
  - Anomalía positiva ⇒ isoterma de 20 °C más **profunda** que lo
    normal (termoclina profunda, típica de El Niño de cuenca).
  - Anomalía negativa ⇒ isoterma más **somera** (típica de La Niña).
- **Signo positivo**: termoclina más profunda.
- **Signo negativo**: termoclina más somera.
- **Fuente**: `noaa-cpc-godas`.
- **Es oficial**: sí.
- **Notas**: D20 como proxy de la profundidad de la termoclina en el
  Pacífico ecuatorial, confirmada su metodología en GODAS. La señal en
  el Pacífico oriental y Niño 1+2 se reporta por separado cuando los
  datos lo permiten.
