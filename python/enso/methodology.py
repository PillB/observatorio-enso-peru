"""Definiciones de indicadores — espejo de ``src/lib/enso/methodology.ts``.

Mantiene los mismos identificadores, regiones, niveles, climatologías,
umbrales y convenciones de signos que la pila TypeScript.
"""

from __future__ import annotations

from typing import Optional

from .models import IndicatorDef, RegionBounds, Threshold

INDICATORS: list[IndicatorDef] = [
    # ===== COSTERO =====
    IndicatorDef(
        id="nino12",
        scope="coastal",
        name="Anomalía de la temperatura superficial del mar — región Niño 1+2",
        shortName="TSM Niño 1+2",
        variable="Anomalía mensual de TSM",
        units="degC",
        region="Niño 1+2 (frente a Ecuador y norte del Perú)",
        regionBounds=RegionBounds(latMin=-10, latMax=0, lonMin=-90, lonMax=-80),
        level="superficie",
        aggregation="Media mensual",
        climatology="Variable según fuente (PSL: 1981–2010)",
        dataset="NOAA / PSL (ERSST v5 / OISST)",
        signConvention="Anomalía respecto a la climatología. Positiva ⇒ más cálido que lo normal.",
        positiveMeans="Mar más cálido de lo normal (favorable a El Niño Costero)",
        negativeMeans="Mar más frío de lo normal (favorable a La Niña Costera)",
        sourceId="noaa-psl-nino12-anom",
        isOfficial=True,
        notes="Indicador primario de la condición costera. Insumo directo del ICEN.",
    ),
    IndicatorDef(
        id="icen",
        scope="coastal",
        name="Índice Costero El Niño (ICEN)",
        shortName="ICEN",
        variable="Media móvil de 3 meses de la anomalía de TSM en Niño 1+2",
        units="degC",
        region="Niño 1+2 (90–80°O, 10°S–0°)",
        regionBounds=RegionBounds(latMin=-10, latMax=0, lonMin=-90, lonMax=-80),
        level="superficie",
        aggregation="Media móvil de 3 meses",
        climatology="Metodología ENFEN (baseline móvil 30 años)",
        dataset="ENFEN / IMARPE (a partir de TSM Niño 1+2)",
        signConvention="Positivo ⇒ anomalía cálida sostenida en la costa.",
        positiveMeans="Condición cálida costera",
        negativeMeans="Condición fría costera",
        thresholds=[
            Threshold(label="Normal", min=-0.4, max=0.4, classification="Normal"),
            Threshold(label="Débil", min=0.4, max=1.0, classification="El Niño Costero débil"),
            Threshold(label="Moderado", min=1.0, max=1.5, classification="El Niño Costero moderado"),
            Threshold(label="Fuerte", min=1.5, max=2.0, classification="El Niño Costero fuerte"),
            Threshold(label="Muy fuerte", min=2.0, max=float("inf"), classification="El Niño Costero muy fuerte"),
            Threshold(label="La Niña Costera débil", min=-1.0, max=-0.4, classification="La Niña Costera débil"),
            Threshold(label="La Niña Costera moderada", min=-1.5, max=-1.0, classification="La Niña Costera moderada"),
            Threshold(label="La Niña Costera fuerte", min=float("-inf"), max=-1.5, classification="La Niña Costera fuerte"),
        ],
        sourceId="enfen-imarpe-icen",
        isOfficial=True,
        notes=(
            "Categorías de intensidad según metodología ENFEN documentada. "
            "El observatorio reproduce los umbrales oficiales; la "
            "activación de un evento costero requiere persistencia (3 meses "
            "consecutivos). Las etiquetas de magnitud son interpretación "
            "generada por el observatorio sujeta a la publicación oficial "
            "de ENFEN."
        ),
    ),
    # ===== CUENCA =====
    IndicatorDef(
        id="nino34",
        scope="basin",
        name="Anomalía de la temperatura superficial del mar — región Niño 3.4",
        shortName="TSM Niño 3.4",
        variable="Anomalía mensual de TSM",
        units="degC",
        region="Niño 3.4 (5°S–5°N, 120–170°O)",
        regionBounds=RegionBounds(latMin=-5, latMax=5, lonMin=-170, lonMax=-120),
        level="superficie",
        aggregation="Media mensual",
        climatology="PSL: 1981–2010",
        dataset="NOAA / PSL (ERSST v5)",
        signConvention="Anomalía respecto a la climatología. Positiva ⇒ más cálido que lo normal.",
        positiveMeans="Pacífico central más cálido (favorable a El Niño de cuenca)",
        negativeMeans="Pacífico central más frío (favorable a La Niña de cuenca)",
        sourceId="noaa-psl-nino34-ersst",
        isOfficial=True,
        notes=(
            "Insumo de los índices operacionales ONI/RONI. Distinguido del "
            "ICEN costero: un evento de cuenca puede ocurrir sin evento "
            "costero y viceversa (ej. 2017 fue costero fuerte sin El Niño "
            "de cuenca)."
        ),
    ),
    IndicatorDef(
        id="roni",
        scope="basin",
        name="Índice Oceánico Relativo del Niño (RONI)",
        shortName="RONI",
        variable="Media móvil de 3 meses de anomalía de TSM en Niño 3.4 con baseline adaptativa",
        units="degC",
        region="Niño 3.4 (5°S–5°N, 120–170°O)",
        regionBounds=RegionBounds(latMin=-5, latMax=5, lonMin=-170, lonMax=-120),
        level="superficie",
        aggregation="Media móvil de 3 meses",
        climatology="Baseline móvil de 30 años (adaptativa al calentamiento secular)",
        dataset="NOAA / CPC (RONI)",
        signConvention="Positivo ⇒ anomalía cálida sostenida en el Pacífico central.",
        positiveMeans="El Niño de cuenca",
        negativeMeans="La Niña de cuenca",
        thresholds=[
            Threshold(label="Neutral", min=-0.5, max=0.5, classification="ENSO Neutral"),
            Threshold(label="El Niño", min=0.5, max=float("inf"), classification="El Niño"),
            Threshold(label="La Niña", min=float("-inf"), max=-0.5, classification="La Niña"),
        ],
        sourceId="noaa-cpc-reroni",
        isOfficial=True,
        notes=(
            "Índice operacional actual de NOAA/CPC para ENSO de cuenca. "
            "Reemplaza al ONI heredado en el monitoreo oficial. Umbral "
            "operativo ±0.5 °C sostenido. No confundir con el ONI de base "
            "fija 1971–2000."
        ),
    ),
    # ===== SOI =====
    IndicatorDef(
        id="soi",
        scope="basin",
        name="Índice de Oscilación del Sur (SOI)",
        shortName="SOI",
        variable="Anomalía estandarizada de la diferencia de presión (Tahiti − Darwin)",
        units="dimensionless",
        region="Tahiti (Pacífico central-sur) y Darwin (norte de Australia)",
        regionBounds=RegionBounds(latMin=-30, latMax=-10, lonMin=-150, lonMax=130),
        level="superficie (presión media al nivel del mar)",
        aggregation="Media mensual",
        climatology="Climatología estandarizada de las estaciones",
        dataset="NOAA / PSL (Tahiti y Darwin)",
        signConvention=(
            "SOI negativo ⇒ presión relativamente más baja en Tahiti que "
            "en Darwin (componente atmosférica de El Niño). SOI positivo ⇒ "
            "lo contrario (La Niña)."
        ),
        positiveMeans="La Niña (componente atmosférica)",
        negativeMeans="El Niño (componente atmosférica)",
        sourceId="noaa-psl-soi",
        isOfficial=True,
        notes=(
            "Índice de escala de cuenca basado en el gradiente de presión "
            "superficial entre Tahiti y Darwin. El observatorio NO define "
            "un «SOI costero»: no existe un proxy de presión costera con "
            "la misma definición ni respaldo metodológico equivalente. "
            "Cualquier indicador de presión costera se etiqueta por "
            "separado y con salvedades."
        ),
    ),
    # ===== VIENTO =====
    IndicatorDef(
        id="u850",
        scope="basin",
        name="Anomalía del viento zonal a 850 hPa — Pacífico ecuatorial",
        shortName="Viento zonal 850 hPa",
        variable="Anomalía de la componente zonal u a 850 hPa",
        units="m_per_s",
        region="Promedio ecuatorial (5°S–5°N) del Pacífico",
        regionBounds=RegionBounds(latMin=-5, latMax=5, lonMin=-180, lonMax=-120),
        level="850 hPa (bajo nivel)",
        aggregation="Media mensual / anomalía",
        climatology="NCEP/NCAR Reanalysis",
        dataset="NOAA / CPC (NCEP/NCAR Reanalysis)",
        signConvention=(
            "u > 0 ⇒ flujo hacia el este (componente del oeste / westerly). "
            "u < 0 ⇒ flujo hacia el oeste (componente del este / easterly). "
            "Se distingue: valor observado vs anomalía; superficie (10 m) "
            "vs 850 hPa; componente zonal vs vectorial."
        ),
        positiveMeans="Anomalía del oeste / westerly (hacia el este)",
        negativeMeans="Anomalía del este / easterly (hacia el oeste)",
        sourceId="noaa-cpc-u850",
        isOfficial=True,
        notes=(
            "Las anomalías del oeste (westerly) favorecen el desplazamiento "
            "hacia el este de la masa de agua cálida, típico de El Niño de "
            "cuenca. No se etiqueta todo viento costero como «alisios»: se "
            "respeta la terminología de la fuente."
        ),
    ),
    # ===== TERMOCLINA =====
    IndicatorDef(
        id="d20",
        scope="basin",
        name="Anomalía de la profundidad de la isoterma de 20 °C (D20)",
        shortName="D20",
        variable="Anomalía de la profundidad de la isoterma de 20 °C",
        units="m",
        region="Promedio ecuatorial (2°S–2°N) del Pacífico",
        regionBounds=RegionBounds(latMin=-2, latMax=2, lonMin=-180, lonMax=-120),
        level="subsuperficie (termoclina)",
        aggregation="Media mensual / anomalía",
        climatology="GODAS",
        dataset="NOAA / CPC (GODAS)",
        signConvention=(
            "Anomalía positiva ⇒ isoterma de 20 °C más profunda que lo "
            "normal (termoclina profunda, típico de El Niño de cuenca). "
            "Anomalía negativa ⇒ isoterma más somera (típico de La Niña)."
        ),
        positiveMeans="Termoclina más profunda",
        negativeMeans="Termoclina más somera",
        sourceId="noaa-cpc-godas",
        isOfficial=True,
        notes=(
            "D20 como proxy de la profundidad de la termoclina en el "
            "Pacífico ecuatorial, confirmada su metodología en GODAS. La "
            "señal en el Pacífico oriental y Niño 1+2 se reporta por "
            "separado cuando los datos lo permiten."
        ),
    ),
]


INDICATOR_BY_ID: dict[str, IndicatorDef] = {i.id: i for i in INDICATORS}


def get_indicator(indicator_id: str) -> Optional[IndicatorDef]:
    """Devuelve el indicador con el identificador dado, o ``None``."""
    return INDICATOR_BY_ID.get(indicator_id)
