# Metodología científica — Observatorio ENSO Perú

> Formal Spanish. Documento de referencia científica para indicadores,
> definiciones, convenciones de signos, climatología y umbrales.

## 1. Marco conceptual

El **ENSO** (El Niño–Oscilación del Sur) es un modo acoplado
océano–atmósfera del Pacífico ecuatorial. El observatorio distingue dos
modalidades de monitoreo:

- **ENSO de cuenca**: Pacífico central, monitoreado operacionalmente por
  NOAA/CPC mediante el **RONI** sobre la región Niño 3.4.
- **El Niño Costero**: Pacífico oriental frente a Ecuador y el norte del
  Perú, monitoreado por ENFEN/IMARPE mediante el **ICEN** sobre la
  región Niño 1+2.

Ambos pueden ocurrir juntos o por separado. El caso paradigmático de
separación es **2017**: ocurrió un El Niño Costero fuerte sin que se
declarara El Niño de cuenca.

## 2. Regiones geográficas

| Región      | Latitud        | Longitud (-180..180) | Convención 0..360 |
|-------------|----------------|----------------------|-------------------|
| Niño 1+2    | 10°S – 0°      | 90°O – 80°O          | 270°E – 280°E     |
| Niño 3.4    | 5°S – 5°N      | 170°O – 120°O        | 190°E – 240°E     |

**Conversión**: 270°E ≡ 90°O. Las conversiones son idempotentes y
preservan NaN.

## 3. Indicadores

### 3.1 Costeros

#### TSM Niño 1+2 (`nino12`)
- **Variable**: anomalía mensual de TSM en Niño 1+2.
- **Unidades**: °C.
- **Nivel**: superficie.
- **Agregación**: media mensual.
- **Climatología**: PSL 1981–2010.
- **Convención de signos**: anomalía positiva ⇒ más cálido (favorable a
  El Niño Costero); negativa ⇒ más frío (favorable a La Niña Costera).
- **Fuente**: NOAA / PSL.

#### ICEN (`icen`)
- **Variable**: media móvil de 3 meses de la anomalía mensual de TSM en
  Niño 1+2.
- **Unidades**: °C.
- **Nivel**: superficie.
- **Agregación**: media móvil de 3 meses.
- **Climatología**: metodología ENFEN (baseline móvil 30 años).
- **Convención**: positivo ⇒ anomalía cálida sostenida.
- **Umbrales** (metodología ENFEN):
  - |ICEN| < 0.4 °C → Normal
  - 0.4 ≤ ICEN < 1.0 → El Niño Costero débil
  - 1.0 ≤ ICEN < 1.5 → El Niño Costero moderado
  - 1.5 ≤ ICEN < 2.0 → El Niño Costero fuerte
  - ICEN ≥ 2.0 → El Niño Costero muy fuerte
  - −1.0 < ICEN ≤ −0.4 → La Niña Costera débil
  - −1.5 < ICEN ≤ −1.0 → La Niña Costera moderada
  - ICEN ≤ −1.5 → La Niña Costera fuerte
- **Activación**: requiere persistencia (3 meses consecutivos).
- **Fuente**: ENFEN / IMARPE (SIOFEN).

### 3.2 Cuenca

#### TSM Niño 3.4 (`nino34`)
- **Variable**: anomalía mensual de TSM en Niño 3.4.
- **Unidades**: °C.
- **Climatología**: PSL 1981–2010.
- **Fuente**: NOAA / PSL (ERSST v5).

#### RONI (`roni`)
- **Variable**: media móvil de 3 meses de la anomalía de TSM en Niño
  3.4 con baseline adaptativa.
- **Unidades**: °C.
- **Climatología**: baseline móvil de 30 años (adaptativa al
  calentamiento secular).
- **Umbrales operativos**:
  - RONI ≥ +0.5 °C sostenido → El Niño (cuenca)
  - RONI ≤ −0.5 °C sostenido → La Niña (cuenca)
  - |RONI| < 0.5 °C → ENSO Neutral
- **Fuente**: NOAA / CPC. Índice operacional actual; reemplaza al ONI
  heredado (base fija 1971–2000).

### 3.3 Atmosféricos

#### SOI (`soi`)
- **Variable**: anomalía estandarizada de la diferencia de presión
  superficial media entre **Tahiti** y **Darwin**.
- **Unidades**: adimensional.
- **Convención**: SOI negativo sostenido ⇒ componente atmosférica de El
  Niño; positivo ⇒ La Niña.
- **Escala**: de cuenca.
- **Fuente**: NOAA / PSL.

> **No existe «SOI costero»**. El observatorio no define tal índice: no
> hay proxy de presión costera con definición ni respaldo metodológico
> equivalente al SOI convencional. La condición costera se monitorea con
> TSM Niño 1+2 e ICEN.

#### Viento zonal a 850 hPa (`u850`)
- **Variable**: anomalía de la componente zonal **u** a 850 hPa.
- **Unidades**: m/s.
- **Nivel**: 850 hPa (bajo nivel), distinto de superficie (10 m).
- **Convención de signos**:
  - u > 0 ⇒ flujo hacia el **este** (componente del oeste / **westerly**).
  - u < 0 ⇒ flujo hacia el **oeste** (componente del este / **easterly**).
- **Distinciones**: valor observado vs anomalía; superficie vs bajo
  nivel; componente zonal vs vectorial.
- **Interpretación**: las anomalías del oeste (westerly) favorecen el
  desplazamiento hacia el este de la masa de agua cálida, típico de El
  Niño de cuenca.
- **Fuente**: NOAA / CPC (NCEP/NCAR Reanalysis).

### 3.4 Subsuperficie

#### D20 (`d20`)
- **Variable**: anomalía de la profundidad de la isoterma de 20 °C
  (proxy de la termoclina en el Pacífico ecuatorial).
- **Unidades**: m.
- **Convención de signos**:
  - Anomalía **positiva** ⇒ isoterma de 20 °C más **profunda** (típica
    de El Niño de cuenca).
  - Anomalía **negativa** ⇒ isoterma más **somera** (típica de La Niña).
- **Fuente**: NOAA / CPC (GODAS).

## 4. Climatología y baseline

- **PSL**: base 1981–2010 (publicada).
- **NOAA/CPC ONI/RONI**: base móvil de 30 años (adaptativa).
- **ENFEN ICEN**: metodología con baseline móvil de 30 años.
- **NCEP/NCAR Reanalysis**: climatología del reanálisis.
- **GODAS**: climatología del sistema GODAS.

El RONI difiere del ONI heredado en la línea base: el RONI adapta la
climatología para reducir el sesgo por el calentamiento secular de la
TSM. No deben confundirse.

## 5. Convenciones de signos — resumen

| Variable | Signo | Significado |
|----------|-------|-------------|
| TSM Niño 1+2 / 3.4 | + | Más cálido que lo normal |
| TSM Niño 1+2 / 3.4 | − | Más frío que lo normal |
| ICEN | + | Anomalía cálida sostenida en la costa |
| ICEN | − | Anomalía fría sostenida en la costa |
| RONI | + | Pacífico central cálido (El Niño cuenca) |
| RONI | − | Pacífico central frío (La Niña cuenca) |
| SOI | − | Presión más baja en Tahiti (El Niño) |
| SOI | + | Presión más alta en Tahiti (La Niña) |
| u850 | + | Flujo hacia el este (westerly) |
| u850 | − | Flujo hacia el oeste (easterly) |
| D20 | + | Termoclina más profunda |
| D20 | − | Termoclina más somera |

## 6. Cálculos derivados

### 6.1 ICEN

ICEN(t) = (TSM_anom(t−2) + TSM_anom(t−1) + TSM_anom(t)) / 3

Requiere exactamente 3 valores. Si falta alguno, el resultado es NaN
(los huecos se preservan, no se rellenan). Redondeo a 2 decimales.

### 6.2 RONI

RONI(t) ≈ media móvil de 3 meses de la anomalía de TSM en Niño 3.4 con
ajuste de baseline adaptativa. En este observatorio se aplica la media
móvil de 3 meses (el ajuste fino del baseline se documenta en NOAA/CPC).

### 6.3 Percentil

Percentil(x) = (#valores de la historia estrictamente menores que x) /
(#total de valores) × 100.

## 7. Estados oficiales vs interpretaciones

- **Estados oficiales** (alerta ENFEN para lo costero, NOAA/CPC ENSO
  Diagnostic Discussion para la cuenca): se citan **textualmente** de la
  fuente.
- **Categorías de intensidad** (débil, moderado, fuerte, muy fuerte):
  reproducen los umbrales ENFEN y son **interpretación generada por el
  observatorio**, sujeta a la publicación oficial.
- Ante duda sobre el estado oficial, se remite a la institución
  competente.

## 8. Datos faltantes y preliminares

- Cuando un dato no está disponible, se muestra «Sin datos». Nunca se
  fabrica.
- Los datos preliminares se marcan explícitamente (`flag=preliminary`).
- Una revisión posterior actualiza la marca a `final`.
- Los huecos (NaN) se preservan a través del cálculo de ICEN y otras
  medias móviles.

## 9. Frescura

Cada indicador muestra su mes de referencia, si el dato es preliminar o
final, y la fecha de corte del observatorio. Los datos se actualizan
siguiendo la frecuencia nativa de cada fuente. Un indicador con frescura
> 72 h respecto al corte se marca como `stale` (obsoleto) de forma
visible.

## 10. Limitaciones de la metodología

- El ICEN reproduce los umbrales ENFEN; la activación oficial requiere
  persistencia y la declaración de ENFEN.
- El RONI es el índice operacional actual; comparaciones históricas con
  ONI deben hacerse con cuidado por el cambio de baseline.
- D20 y u850 provienen de reanálisis/asimilación; tienen su propia
  incertidumbre.
- El observatorio no emite pronósticos ni alertas oficiales. Para
  emergencias, consultar INDECI, CENEPRED, SENAMHI y ENFEN.
