"""Motor de umbrales del Observatorio ENSO Perú.

Implementa dos conjuntos de políticas:
  1. expert-grd-image-v1: señal operativa del experto GRD (imagen)
  2. enfen-icen-official-v1: clasificación científica oficial ICEN (ENFEN)

Los intervalos no definidos se marcan como UNCLASSIFIED, no como normal.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ThresholdColor(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    BLUE = "blue"
    LIGHTBLUE = "lightblue"
    LIGHTCYAN = "lightcyan"
    ORANGE = "orange"
    DARKRED = "darkred"
    GRAY = "gray"


@dataclass
class ThresholdRule:
    label: str
    color: ThresholdColor
    min: Optional[float]
    max: Optional[float]
    min_inclusive: bool = True
    max_inclusive: bool = True
    note: str = ""


@dataclass
class ThresholdResult:
    policy_id: str
    policy_name: str
    source_type: str
    classification: str
    color: ThresholdColor
    value: Optional[float]
    is_unclassified: bool = False
    unclassified_reason: str = ""
    note: str = ""

    def matches(self, label: str = None, color: str = None, unclassified: bool = None) -> bool:
        if label is not None and self.classification != label:
            return False
        if color is not None and self.color.value != color:
            return False
        if unclassified is not None and self.is_unclassified != unclassified:
            return False
        return True


# ---------------------------------------------------------------------------
# Política experto GRD — imagen v1
# ---------------------------------------------------------------------------

EXPERT_COASTAL_SST_RULES = [
    ThresholdRule("Normal", ThresholdColor.GREEN, -0.7, 0.5, True, True),
    ThresholdRule("Amarillo", ThresholdColor.YELLOW, 1.3, 2.0, True, True),
    ThresholdRule("Rojo", ThresholdColor.RED, 2.1, None, True, False),
]

EXPERT_BASIN_SST_RULES = [
    ThresholdRule("Normal", ThresholdColor.GREEN, -0.5, 0.5, True, True),
    ThresholdRule("Amarillo", ThresholdColor.YELLOW, 1.0, 1.5, False, True),
    ThresholdRule("Rojo", ThresholdColor.RED, 1.5, None, False, False),
]

EXPERT_THERMOCLINE_RULES = [
    ThresholdRule("Normal", ThresholdColor.GREEN, -20, 20, True, True),
    ThresholdRule("Amarillo", ThresholdColor.YELLOW, 30, 50, True, True),
    ThresholdRule("Rojo", ThresholdColor.RED, 50, None, False, False),
]

EXPERT_SOI_RULES = [
    ThresholdRule("Normal", ThresholdColor.GREEN, -7, 7, True, True),
    ThresholdRule("Rojo", ThresholdColor.RED, None, -7, False, False),
]

# ---------------------------------------------------------------------------
# Política oficial ICEN (ENFEN) — v1
# ---------------------------------------------------------------------------

ENFEN_ICEN_RULES = [
    ThresholdRule("Frío intenso", ThresholdColor.BLUE, None, -1.3, False, False),
    ThresholdRule("Frío moderado", ThresholdColor.LIGHTBLUE, -1.3, -1.1, True, False),
    ThresholdRule("Frío débil", ThresholdColor.LIGHTCYAN, -1.1, -0.7, True, False),
    ThresholdRule("Normal", ThresholdColor.GREEN, -0.7, 0.5, True, True),
    ThresholdRule("Cálido débil", ThresholdColor.YELLOW, 0.5, 1.3, False, True),
    ThresholdRule("Cálido moderado", ThresholdColor.ORANGE, 1.3, 2.1, False, True),
    ThresholdRule("Cálido fuerte", ThresholdColor.RED, 2.1, 3.5, False, True),
    ThresholdRule("Cálido extraordinario", ThresholdColor.DARKRED, 3.5, None, False, False),
]


# ---------------------------------------------------------------------------
# Función de evaluación
# ---------------------------------------------------------------------------

def evaluate_threshold(
    value: Optional[float],
    rules: list[ThresholdRule],
    policy_id: str,
    policy_name: str,
    source_type: str,
) -> ThresholdResult:
    """Evalúa un valor contra reglas de umbral.

    Devuelve UNCLASSIFIED si el valor cae en un intervalo no definido.
    Nunca devuelve green para huecos o datos faltantes.
    """
    if value is None or (isinstance(value, float) and value != value):  # NaN check
        return ThresholdResult(
            policy_id=policy_id,
            policy_name=policy_name,
            source_type=source_type,
            classification="Sin datos",
            color=ThresholdColor.GRAY,
            value=None,
            is_unclassified=True,
            unclassified_reason="Dato faltante o no disponible",
        )

    for rule in rules:
        min_ok = True if rule.min is None else (value >= rule.min if rule.min_inclusive else value > rule.min)
        max_ok = True if rule.max is None else (value <= rule.max if rule.max_inclusive else value < rule.max)
        if min_ok and max_ok:
            return ThresholdResult(
                policy_id=policy_id,
                policy_name=policy_name,
                source_type=source_type,
                classification=rule.label,
                color=rule.color,
                value=value,
                is_unclassified=False,
                note=rule.note,
            )

    return ThresholdResult(
        policy_id=policy_id,
        policy_name=policy_name,
        source_type=source_type,
        classification="Sin clasificar",
        color=ThresholdColor.GRAY,
        value=value,
        is_unclassified=True,
        unclassified_reason="El valor cae en un intervalo no definido por la política",
    )


def evaluate_coastal_sst_expert(value: Optional[float]) -> ThresholdResult:
    return evaluate_threshold(value, EXPERT_COASTAL_SST_RULES, "expert-grd-image-v1", "Señal operativa del experto GRD", "EXPERT_POLICY")


def evaluate_basin_sst_expert(value: Optional[float]) -> ThresholdResult:
    return evaluate_threshold(value, EXPERT_BASIN_SST_RULES, "expert-grd-image-v1", "Señal operativa del experto GRD", "EXPERT_POLICY")


def evaluate_thermocline_expert(value: Optional[float]) -> ThresholdResult:
    return evaluate_threshold(value, EXPERT_THERMOCLINE_RULES, "expert-grd-image-v1", "Señal operativa del experto GRD", "EXPERT_POLICY")


def evaluate_soi_expert(value: Optional[float]) -> ThresholdResult:
    return evaluate_threshold(value, EXPERT_SOI_RULES, "expert-grd-image-v1", "Señal operativa del experto GRD", "EXPERT_POLICY")


def evaluate_icen_official(value: Optional[float]) -> ThresholdResult:
    return evaluate_threshold(value, ENFEN_ICEN_RULES, "enfen-icen-official-v1", "Clasificación oficial ICEN (ENFEN)", "VERIFIED")
