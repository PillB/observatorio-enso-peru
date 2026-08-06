"""Observatorio ENSO Perú — pipeline de adquisición y procesamiento.

Capa de datos en Python que refleja la capa normalizada en TypeScript
(``src/lib/enso``). Mantiene los mismos identificadores de fuente e
indicadores para asegurar consistencia entre el frontend y los artefactos
generados por CI.

Submódulos:
    models     — modelos pydantic (SourceRef, IndicatorDef, MonthlyPoint, …).
    sources    — registro de fuentes (espejo de ``src/lib/enso/sources.ts``).
    fetchers   — descargadores con reintentos, caché y validación.
    normalize  — conversiones de longitud/tiempo y verificación de signos.
    derived    — ICEN, RONI, SOI, D20, viento, percentiles.
    pipeline   — orquestador idempotente.
    cli        — interfaz de línea de comandos.

El pipeline está diseñado para degradar de forma graceful cuando la red no
está disponible: nunca fabrica valores, preserva el último conjunto válido
y marca los datos como obsoletos (``stale``).
"""

from .models import (  # noqa: F401
    SourceRef,
    SourceStatus,
    IndicatorDef,
    Threshold,
    RegionBounds,
    MonthlyPoint,
    SeriesFlag,
    Series,
    CurrentStatus,
    CoastalStatus,
    BasinStatus,
    WindsStatus,
    ThermoclineStatus,
    SoiStatus,
)
from .sources import SOURCES, SOURCE_BY_ID, get_source  # noqa: F401
from .methodology import INDICATORS, INDICATOR_BY_ID, get_indicator  # noqa: F401

__version__ = "1.0.0"
__all__ = [
    "__version__",
    "SourceRef",
    "SourceStatus",
    "IndicatorDef",
    "Threshold",
    "RegionBounds",
    "MonthlyPoint",
    "SeriesFlag",
    "Series",
    "CurrentStatus",
    "CoastalStatus",
    "BasinStatus",
    "WindsStatus",
    "ThermoclineStatus",
    "SoiStatus",
    "SOURCES",
    "SOURCE_BY_ID",
    "get_source",
    "INDICATORS",
    "INDICATOR_BY_ID",
    "get_indicator",
]
