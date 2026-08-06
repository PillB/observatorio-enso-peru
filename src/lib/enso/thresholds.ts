// Motor de umbrales del Observatorio ENSO Perú.
// ============================================================================
// Implementa dos conjuntos de políticas de umbrales:
//   1. expert-grd-image-v1: señal operativa del experto GRD (imagen)
//   2. enfen-icen-official-v1: clasificación científica oficial ICEN (ENFEN)
//
// Mantiene ambas separadas. Permite al usuario mostrar una, la otra o ambas.
// Los intervalos no definidos se marcan como UNCLASSIFIED, no como normal.
// ============================================================================

export type ThresholdColor = "green" | "yellow" | "red" | "blue" | "lightblue" | "lightcyan" | "orange" | "darkred" | "gray";
export type PolicySource = "EXPERT_POLICY" | "VERIFIED" | "OFFICIAL";

export interface ThresholdRule {
  label: string;
  color: ThresholdColor;
  min: number | null;
  max: number | null;
  min_inclusive: boolean;
  max_inclusive: boolean;
  note?: string;
}

export interface ThresholdResult {
  policy_id: string;
  policy_name: string;
  source_type: PolicySource;
  classification: string;
  color: ThresholdColor;
  value: number | null;
  is_unclassified: boolean;
  unclassified_reason?: string;
  note?: string;
}

// ---------------------------------------------------------------------------
// Política experto GRD — imagen v1
// ---------------------------------------------------------------------------

export const EXPERT_GRD_POLICY = {
  policy_id: "expert-grd-image-v1",
  policy_name: "Señal operativa del experto GRD (imagen v1)",
  source_type: "EXPERT_POLICY" as PolicySource,
  coastal_sst: {
    rules: [
      { label: "Normal", color: "green" as ThresholdColor, min: -0.7, max: 0.5, min_inclusive: true, max_inclusive: true },
      { label: "Amarillo", color: "yellow" as ThresholdColor, min: 1.3, max: 2.0, min_inclusive: true, max_inclusive: true },
      { label: "Rojo", color: "red" as ThresholdColor, min: 2.1, max: null, min_inclusive: true, max_inclusive: false },
    ],
  },
  basin_sst: {
    rules: [
      { label: "Normal", color: "green" as ThresholdColor, min: -0.5, max: 0.5, min_inclusive: true, max_inclusive: true },
      { label: "Amarillo", color: "yellow" as ThresholdColor, min: 1.0, max: 1.5, min_inclusive: false, max_inclusive: true },
      { label: "Rojo", color: "red" as ThresholdColor, min: 1.5, max: null, min_inclusive: false, max_inclusive: false },
    ],
  },
  thermocline: {
    rules: [
      { label: "Normal", color: "green" as ThresholdColor, min: -20, max: 20, min_inclusive: true, max_inclusive: true },
      { label: "Amarillo", color: "yellow" as ThresholdColor, min: 30, max: 50, min_inclusive: true, max_inclusive: true },
      { label: "Rojo", color: "red" as ThresholdColor, min: 50, max: null, min_inclusive: false, max_inclusive: false },
    ],
  },
  soi: {
    rules: [
      { label: "Normal", color: "green" as ThresholdColor, min: -7, max: 7, min_inclusive: true, max_inclusive: true },
      { label: "Rojo", color: "red" as ThresholdColor, min: null, max: -7, min_inclusive: false, max_inclusive: false },
    ],
  },
} as const;

// ---------------------------------------------------------------------------
// Política oficial ICEN (ENFEN) — v1
// ---------------------------------------------------------------------------

export const ENFEN_ICEN_POLICY = {
  policy_id: "enfen-icen-official-v1",
  policy_name: "Clasificación oficial ICEN (ENFEN)",
  source_type: "VERIFIED" as PolicySource,
  rules: [
    { label: "Frío intenso", color: "blue" as ThresholdColor, min: null, max: -1.3, min_inclusive: false, max_inclusive: false },
    { label: "Frío moderado", color: "lightblue" as ThresholdColor, min: -1.3, max: -1.1, min_inclusive: true, max_inclusive: false },
    { label: "Frío débil", color: "lightcyan" as ThresholdColor, min: -1.1, max: -0.7, min_inclusive: true, max_inclusive: false },
    { label: "Normal", color: "green" as ThresholdColor, min: -0.7, max: 0.5, min_inclusive: true, max_inclusive: true },
    { label: "Cálido débil", color: "yellow" as ThresholdColor, min: 0.5, max: 1.3, min_inclusive: false, max_inclusive: true },
    { label: "Cálido moderado", color: "orange" as ThresholdColor, min: 1.3, max: 2.1, min_inclusive: false, max_inclusive: true },
    { label: "Cálido fuerte", color: "red" as ThresholdColor, min: 2.1, max: 3.5, min_inclusive: false, max_inclusive: true },
    { label: "Cálido extraordinario", color: "darkred" as ThresholdColor, min: 3.5, max: null, min_inclusive: false, max_inclusive: false },
  ],
} as const;

// ---------------------------------------------------------------------------
// Función de evaluación de umbrales
// ---------------------------------------------------------------------------

/**
 * Evalúa un valor contra un conjunto de reglas de umbral.
 * Devuelve UNCLASSIFIED si el valor cae en un intervalo no definido.
 * Nunca devuelve "green" para huecos o datos faltantes.
 */
export function evaluateThreshold(
  value: number | null,
  rules: readonly ThresholdRule[],
  policy_id: string,
  policy_name: string,
  source_type: PolicySource
): ThresholdResult {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return {
      policy_id,
      policy_name,
      source_type,
      classification: "Sin datos",
      color: "gray",
      value: null,
      is_unclassified: true,
      unclassified_reason: "Dato faltante o no disponible",
    };
  }

  for (const rule of rules) {
    const minOk = rule.min === null ? true : rule.min_inclusive ? value >= rule.min : value > rule.min;
    const maxOk = rule.max === null ? true : rule.max_inclusive ? value <= rule.max : value < rule.max;
    if (minOk && maxOk) {
      return {
        policy_id,
        policy_name,
        source_type,
        classification: rule.label,
        color: rule.color,
        value,
        is_unclassified: false,
        note: rule.note,
      };
    }
  }

  // No coincide con ninguna regla → UNCLASSIFIED
  return {
    policy_id,
    policy_name,
    source_type,
    classification: "Sin clasificar",
    color: "gray",
    value,
    is_unclassified: true,
    unclassified_reason: "El valor cae en un intervalo no definido por la política",
  };
}

/**
 * Evalúa el Niño 1+2 costero con la política del experto GRD.
 */
export function evaluateCoastalSSTExpert(value: number | null): ThresholdResult {
  return evaluateThreshold(value, EXPERT_GRD_POLICY.coastal_sst.rules, EXPERT_GRD_POLICY.policy_id, EXPERT_GRD_POLICY.policy_name, "EXPERT_POLICY");
}

/**
 * Evalúa el Niño 3.4 de cuenca con la política del experto GRD.
 */
export function evaluateBasinSSTExpert(value: number | null): ThresholdResult {
  return evaluateThreshold(value, EXPERT_GRD_POLICY.basin_sst.rules, EXPERT_GRD_POLICY.policy_id, EXPERT_GRD_POLICY.policy_name, "EXPERT_POLICY");
}

/**
 * Evalúa la termoclina (D20) con la política del experto GRD.
 */
export function evaluateThermoclineExpert(value: number | null): ThresholdResult {
  return evaluateThreshold(value, EXPERT_GRD_POLICY.thermocline.rules, EXPERT_GRD_POLICY.policy_id, EXPERT_GRD_POLICY.policy_name, "EXPERT_POLICY");
}

/**
 * Evalúa el SOI con la política del experto GRD.
 */
export function evaluateSOIExpert(value: number | null): ThresholdResult {
  return evaluateThreshold(value, EXPERT_GRD_POLICY.soi.rules, EXPERT_GRD_POLICY.policy_id, EXPERT_GRD_POLICY.policy_name, "EXPERT_POLICY");
}

/**
 * Evalúa el ICEN con la clasificación oficial ENFEN.
 * Solo aplicar a ICEN (media móvil de 3 meses), no a Niño 1+2 semanal.
 */
export function evaluateICENOfficial(value: number | null): ThresholdResult {
  return evaluateThreshold(value, ENFEN_ICEN_POLICY.rules, ENFEN_ICEN_POLICY.policy_id, ENFEN_ICEN_POLICY.policy_name, "VERIFIED");
}

/**
 * Devuelve ambas evaluaciones (experto + oficial) para un indicador.
 */
export function evaluateBothPolicies(
  indicatorId: string,
  value: number | null
): { expert: ThresholdResult | null; official: ThresholdResult | null } {
  let expert: ThresholdResult | null = null;
  let official: ThresholdResult | null = null;

  switch (indicatorId) {
    case "nino12":
      expert = evaluateCoastalSSTExpert(value);
      break;
    case "icen":
      expert = evaluateCoastalSSTExpert(value);
      official = evaluateICENOfficial(value);
      break;
    case "nino34":
    case "roni":
      expert = evaluateBasinSSTExpert(value);
      break;
    case "d20":
      expert = evaluateThermoclineExpert(value);
      break;
    case "soi":
      expert = evaluateSOIExpert(value);
      break;
  }

  return { expert, official };
}

/**
 * Color CSS para un ThresholdColor.
 */
export function thresholdColorCSS(color: ThresholdColor): string {
  const map: Record<ThresholdColor, string> = {
    green: "var(--enso-cool)",
    yellow: "#eab308",
    red: "#dc2626",
    blue: "#1e40af",
    lightblue: "#3b82f6",
    lightcyan: "#67e8f9",
    orange: "#f97316",
    darkred: "#7f1d1d",
    gray: "var(--muted-foreground)",
  };
  return map[color] ?? "var(--muted-foreground)";
}
