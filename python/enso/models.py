"""Modelos pydantic del Observatorio ENSO Perú.

Espejo de los tipos TypeScript definidos en ``src/lib/enso/types.ts`` (no
incluido en este repositorio como archivo físico, pero usado por
``sources.ts`` y ``methodology.ts``). Los identificadores y estructuras se
mantienen idénticos para que la pila Python y la pila TS sean consistentes.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, HttpUrl, ConfigDict


# ----------------------------------------------------------------------------
# Fuentes
# ----------------------------------------------------------------------------
class SourceStatus(str, Enum):
    """Estado de verificación de una fuente según el protocolo de evidencia."""

    VERIFIED = "VERIFIED"
    ASSUMED = "ASSUMED"
    UNRESOLVED = "UNRESOLVED"
    REJECTED = "REJECTED"


class SourceRef(BaseModel):
    """Referencia a una fuente de datos externa."""

    model_config = ConfigDict(extra="forbid")

    id: str
    institution: str
    product: str
    url: str
    retrievalDate: str
    format: str
    updateFrequency: str
    latency: str
    license: str
    attribution: str
    status: SourceStatus
    notes: str
    fallbackSourceId: str


# ----------------------------------------------------------------------------
# Indicadores
# ----------------------------------------------------------------------------
Scope = Literal["coastal", "basin"]
Units = Literal["degC", "m", "m_per_s", "dimensionless"]


class RegionBounds(BaseModel):
    """Caja geográfica (lat/lon en grados, longitud en -180..180)."""

    model_config = ConfigDict(extra="forbid")
    latMin: float
    latMax: float
    lonMin: float
    lonMax: float


class Threshold(BaseModel):
    """Umbral de categorización de un indicador."""

    model_config = ConfigDict(extra="forbid")
    label: str
    min: float
    max: float
    classification: str


class IndicatorDef(BaseModel):
    """Definición científica de un indicador."""

    model_config = ConfigDict(extra="forbid")

    id: str
    scope: Scope
    name: str
    shortName: str
    variable: str
    units: Units
    region: str
    regionBounds: RegionBounds
    level: str
    aggregation: str
    climatology: str
    dataset: str
    signConvention: str
    positiveMeans: str
    negativeMeans: str
    sourceId: str
    isOfficial: bool
    notes: str
    thresholds: Optional[list[Threshold]] = None


# ----------------------------------------------------------------------------
# Series temporales mensuales
# ----------------------------------------------------------------------------
class SeriesFlag(str, Enum):
    """Marca de revisión de un dato mensual."""

    FINAL = "final"
    PRELIMINARY = "preliminary"


class MonthlyPoint(BaseModel):
    """Punto mensual (mes ISO ``YYYY-MM`` + valor + marca)."""

    model_config = ConfigDict(extra="forbid")
    month: str
    value: Optional[float] = None
    flag: SeriesFlag = SeriesFlag.FINAL


class Series(BaseModel):
    """Serie mensual normalizada de un indicador."""

    model_config = ConfigDict(extra="forbid")
    indicatorId: str
    label: str
    units: Units
    scope: Scope
    points: list[MonthlyPoint]
    sourceId: str
    checksum: str


# ----------------------------------------------------------------------------
# Estado consolidado
# ----------------------------------------------------------------------------
class CoastalStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alert: str
    alertSource: str
    alertSince: str
    nino12Anom: Optional[float] = None
    nino12Month: str
    icen: Optional[float] = None
    icenWindow: str
    icenCategory: str
    freshness: str
    preliminary: bool


class BasinStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alert: str
    alertSource: str
    alertSince: str
    nino34Anom: Optional[float] = None
    nino34Month: str
    roni: Optional[float] = None
    roniWindow: str
    roniCategory: str
    freshness: str
    preliminary: bool


class WindsStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    u850Anom: Optional[float] = None
    u850Month: str
    direction: str
    signMeaning: str


class ThermoclineStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    d20Anom: Optional[float] = None
    d20Month: str
    interpretation: str


class SoiStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: Optional[float] = None
    month: str
    interpretation: str
    note: str


class CurrentStatus(BaseModel):
    """Estado consolidado del observatorio."""

    model_config = ConfigDict(extra="forbid")
    asOf: str
    coastal: CoastalStatus
    basin: BasinStatus
    winds: WindsStatus
    thermocline: ThermoclineStatus
    soi: SoiStatus
    dataVersion: str
    generatedAt: str
