"""Grafo de fallbacks explícito para métricas ENSO.

Niveles:
  Level 0: Fuente primaria estructurada autoritativa
  Level 1: Fuente equivalente autoritativa (misma métrica, agregación, región, unidad, climatología)
  Level 2: Fuente de menor cadencia autoritativa, con fecha clara
  Level 3: Último válido histórico (excluido de estado actual cuando stale)
  Level 4: Métrica no disponible

Sustituciones PROHIBIDAS:
  - Weekly Niño 1+2 NO sustituye ICEN
  - Niño 3.4 NO sustituye RONI
  - D20 puntual NO sustituye promedio de cuenca
  - Viento superficial NO sustituye viento 850 hPa
  - Anomalía NO sustituye viento real
  - Señal operativa NO sustituye clasificación oficial
  - Narrativa NO sustituye medición exacta
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class FallbackLevel(IntEnum):
    """Niveles de fallback."""
    PRIMARY = 0       # Fuente primaria estructurada
    EQUIVALENT = 1    # Fuente equivalente autoritativa
    LOWER_CADENCE = 2 # Fuente de menor cadencia
    LAST_VALID = 3    # Último válido histórico
    UNAVAILABLE = 4   # No disponible


@dataclass(frozen=True)
class FallbackNode:
    """Nodo en el grafo de fallbacks."""
    level: FallbackLevel
    source_id: str
    description: str
    scientific_notes: str = ""


@dataclass(frozen=True)
class MetricFallbackGraph:
    """Grafo de fallbacks para una métrica específica."""
    metric_id: str
    nodes: tuple[FallbackNode, ...]
    prohibited_substitutions: tuple[str, ...] = ()

    def get_fallback_chain(self) -> list[FallbackNode]:
        """Devuelve la cadena de fallbacks ordenada por nivel."""
        return sorted(self.nodes, key=lambda n: n.level)

    def get_level(self, level: FallbackLevel) -> Optional[FallbackNode]:
        """Devuelve el nodo de un nivel específico."""
        for n in self.nodes:
            if n.level == level:
                return n
        return None


# ----------------------------------------------------------------------------
# Grafos de fallback por métrica
# ----------------------------------------------------------------------------
FALLBACK_GRAPHS: dict[str, MetricFallbackGraph] = {
    "roni": MetricFallbackGraph(
        metric_id="roni",
        nodes=(
            FallbackNode(
                level=FallbackLevel.PRIMARY,
                source_id="noaa-cpc-roni",
                description="RONI oficial (RONI.ascii.txt, seasonal)",
                scientific_notes="Producto oficial NOAA/CPC con ajuste de media tropical relativa. NO es rolling mean de Niño 3.4.",
            ),
            FallbackNode(
                level=FallbackLevel.LAST_VALID,
                source_id="noaa-cpc-roni",
                description="Último RONI oficial válido en caché",
                scientific_notes="Preservado con fecha original. Marcado STALE si excede SLO.",
            ),
            FallbackNode(
                level=FallbackLevel.UNAVAILABLE,
                source_id="",
                description="RONI no disponible",
                scientific_notes="Mostrar 'Dato actual no disponible'. NO sustituir con Niño 3.4 rolling mean.",
            ),
        ),
        prohibited_substitutions=(
            "Niño 3.4 rolling mean NO sustituye RONI",
            "ONI NO sustituye RONI (baseline diferente)",
        ),
    ),
    "icen": MetricFallbackGraph(
        metric_id="icen",
        nodes=(
            FallbackNode(
                level=FallbackLevel.PRIMARY,
                source_id="enfen-imarpe-icen",
                description="ICEN oficial de ENFEN/IMARPE",
                scientific_notes="Media móvil de 3 meses de anomalías de TSM en Niño 1+2. Metodología ENFEN.",
            ),
            FallbackNode(
                level=FallbackLevel.EQUIVALENT,
                source_id="noaa-psl-nino12",
                description="ICEN calculado desde Niño 1+2 de PSL (misma metodología)",
                scientific_notes="Aplica la misma fórmula: 3-month rolling mean de Niño 1+2. Científicamente equivalente.",
            ),
            FallbackNode(
                level=FallbackLevel.LAST_VALID,
                source_id="enfen-imarpe-icen",
                description="Último ICEN válido en caché",
                scientific_notes="Preservado con fecha. Marcado STALE si excede SLO.",
            ),
            FallbackNode(
                level=FallbackLevel.UNAVAILABLE,
                source_id="",
                description="ICEN no disponible",
                scientific_notes="Mostrar 'Dato actual no disponible'. NO sustituir con weekly Niño 1+2.",
            ),
        ),
        prohibited_substitutions=(
            "Weekly Niño 1+2 NO sustituye ICEN (cadencia incompatible)",
            "Niño 3.4 NO sustituye ICEN (región diferente)",
        ),
    ),
    "nino12": MetricFallbackGraph(
        metric_id="nino12",
        nodes=(
            FallbackNode(
                level=FallbackLevel.PRIMARY,
                source_id="noaa-psl-nino12",
                description="Niño 1+2 mensual (PSL CSV)",
                scientific_notes="Anomalía mensual de TSM en región Niño 1+2 (90°W-80°W, 10°S-0°).",
            ),
            FallbackNode(
                level=FallbackLevel.LOWER_CADENCE,
                source_id="noaa-cpc-wksst",
                description="Niño 1+2 semanal (wksst8110.for)",
                scientific_notes="Cadencia semanal, no sustituye mensual directamente pero complementa.",
            ),
            FallbackNode(
                level=FallbackLevel.LAST_VALID,
                source_id="noaa-psl-nino12",
                description="Último Niño 1+2 válido en caché",
                scientific_notes="Preservado con fecha.",
            ),
            FallbackNode(
                level=FallbackLevel.UNAVAILABLE,
                source_id="",
                description="Niño 1+2 no disponible",
                scientific_notes="Mostrar 'Dato actual no disponible'.",
            ),
        ),
    ),
    "nino34": MetricFallbackGraph(
        metric_id="nino34",
        nodes=(
            FallbackNode(
                level=FallbackLevel.PRIMARY,
                source_id="noaa-psl-nino34",
                description="Niño 3.4 mensual (PSL CSV)",
                scientific_notes="Anomalía mensual de TSM en región Niño 3.4 (170°W-120°W, 5°S-5°N).",
            ),
            FallbackNode(
                level=FallbackLevel.LOWER_CADENCE,
                source_id="noaa-cpc-wksst",
                description="Niño 3.4 semanal (wksst8110.for)",
                scientific_notes="Cadencia semanal, complementa el mensual.",
            ),
            FallbackNode(
                level=FallbackLevel.LAST_VALID,
                source_id="noaa-psl-nino34",
                description="Último Niño 3.4 válido en caché",
                scientific_notes="Preservado con fecha.",
            ),
            FallbackNode(
                level=FallbackLevel.UNAVAILABLE,
                source_id="",
                description="Niño 3.4 no disponible",
                scientific_notes="Mostrar 'Dato actual no disponible'.",
            ),
        ),
    ),
    "soi": MetricFallbackGraph(
        metric_id="soi",
        nodes=(
            FallbackNode(
                level=FallbackLevel.PRIMARY,
                source_id="noaa-cpc-soi",
                description="SOI mensual (CPC, Tahiti-Darwin standardized)",
                scientific_notes="Índice de escala de cuenca. NO existe 'SOI costero'.",
            ),
            FallbackNode(
                level=FallbackLevel.LAST_VALID,
                source_id="noaa-cpc-soi",
                description="Último SOI válido en caché",
                scientific_notes="Preservado con fecha.",
            ),
            FallbackNode(
                level=FallbackLevel.UNAVAILABLE,
                source_id="",
                description="SOI no disponible",
                scientific_notes="Mostrar 'Dato actual no disponible'. NO definir 'SOI costero'.",
            ),
        ),
        prohibited_substitutions=(
            "NO existe 'SOI costero' — no definir proxy de presión costera",
        ),
    ),
    "u850": MetricFallbackGraph(
        metric_id="u850",
        nodes=(
            FallbackNode(
                level=FallbackLevel.PRIMARY,
                source_id="noaa-cpc-cpac850",
                description="850 hPa trade wind index — Central Pacific (CPC)",
                scientific_notes="Viento real (no anomalía). Región: 175°W-140°W, 5°S-5°N. Nivel: 850 hPa.",
            ),
            FallbackNode(
                level=FallbackLevel.EQUIVALENT,
                source_id="noaa-cpc-wpac850",
                description="850 hPa trade wind index — Western Pacific (CPC)",
                scientific_notes="Viento real. Región: 135°E-180°W. Nivel: 850 hPa. Equivalente pero región diferente.",
            ),
            FallbackNode(
                level=FallbackLevel.LAST_VALID,
                source_id="noaa-cpc-cpac850",
                description="Último cpac850 válido en caché",
                scientific_notes="Preservado con fecha.",
            ),
            FallbackNode(
                level=FallbackLevel.UNAVAILABLE,
                source_id="",
                description="Viento 850 hPa no disponible",
                scientific_notes="Mostrar 'Dato actual no disponible'. NO sustituir con viento superficial.",
            ),
        ),
        prohibited_substitutions=(
            "Viento superficial NO sustituye viento 850 hPa (nivel diferente)",
            "Anomalía NO sustituye viento real (tipo diferente)",
            "Viento de otra región NO sustituye cpac850 sin etiquetar claramente",
        ),
    ),
    "d20": MetricFallbackGraph(
        metric_id="d20",
        nodes=(
            FallbackNode(
                level=FallbackLevel.PRIMARY,
                source_id="noaa-cpc-godas-d20",
                description="D20 anomaly (GODAS dbss_obil) — Niño 3.4 area average",
                scientific_notes="Profundidad de isoterma de 20°C. Promedio areal sobre Niño 3.4. Anomalía vs 1991-2020.",
            ),
            FallbackNode(
                level=FallbackLevel.LAST_VALID,
                source_id="noaa-cpc-godas-d20",
                description="Último D20 válido en caché",
                scientific_notes="Preservado con fecha.",
            ),
            FallbackNode(
                level=FallbackLevel.UNAVAILABLE,
                source_id="",
                description="D20 no disponible",
                scientific_notes="Mostrar 'Dato actual no disponible'. NO sustituir con D20 puntual.",
            ),
        ),
        prohibited_substitutions=(
            "D20 puntual NO sustituye promedio de cuenca (agregación diferente)",
            "No inferir D20 de colores de gráfico",
        ),
    ),
    "basin_official_status": MetricFallbackGraph(
        metric_id="basin_official_status",
        nodes=(
            FallbackNode(
                level=FallbackLevel.PRIMARY,
                source_id="noaa-cpc-enso-advisory",
                description="NOAA/CPC ENSO Alert System Status (official)",
                scientific_notes="Texto oficial: El Niño Advisory / La Niña Advisory / ENSO-Neutral / Watch. NO inferir de observaciones.",
            ),
            FallbackNode(
                level=FallbackLevel.LAST_VALID,
                source_id="noaa-cpc-enso-advisory",
                description="Último advisory oficial en caché",
                scientific_notes="Preservado con fecha de publicación.",
            ),
            FallbackNode(
                level=FallbackLevel.UNAVAILABLE,
                source_id="",
                description="Estado oficial de cuenca no disponible",
                scientific_notes="Mostrar 'Consulte NOAA/CPC'. NO inferir alerta de observaciones rápidas.",
            ),
        ),
        prohibited_substitutions=(
            "Señal operativa del equipo GRD NO sustituye clasificación oficial",
            "RONI > 0.5 NO implica 'El Niño Advisory' automáticamente",
            "Observación rápida NO sustituye comunicado oficial",
        ),
    ),
    "coastal_official_status": MetricFallbackGraph(
        metric_id="coastal_official_status",
        nodes=(
            FallbackNode(
                level=FallbackLevel.PRIMARY,
                source_id="enfen-imarpe-status",
                description="ENFEN/IMARPE estado oficial El Niño Costero",
                scientific_notes="Texto oficial: Alerta / Vigilancia / Normal. Event-driven.",
            ),
            FallbackNode(
                level=FallbackLevel.LAST_VALID,
                source_id="enfen-imarpe-status",
                description="Último estado ENFEN válido (fallback manual)",
                scientific_notes="config/enfen-status.json. Cloudflare bloquea automatización. Etiquetar source=fallback.",
            ),
            FallbackNode(
                level=FallbackLevel.UNAVAILABLE,
                source_id="",
                description="Estado oficial costero no disponible",
                scientific_notes="Mostrar 'Consulte ENFEN'. NO inferir de ICEN.",
            ),
        ),
        prohibited_substitutions=(
            "ICEN NO sustituye clasificación oficial ENFEN",
            "Niño 1+2 alto NO implica 'Alerta de El Niño Costero' automáticamente",
        ),
    ),
}


def get_fallback_graph(metric_id: str) -> Optional[MetricFallbackGraph]:
    """Devuelve el grafo de fallback para una métrica."""
    return FALLBACK_GRAPHS.get(metric_id)


def get_all_metric_ids() -> tuple[str, ...]:
    """Devuelve todas las métricas con grafo de fallback."""
    return tuple(FALLBACK_GRAPHS.keys())
