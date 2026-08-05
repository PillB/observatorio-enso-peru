import type { CurrentStatus, Series } from "./types";
import { INDICATOR_BY_ID } from "./methodology";
import { generateAllSeries, getSeries, latest, AS_OF_MONTH, AS_OF_DATE } from "./series";

// Categorías derivadas por el observatorio. Se distinguen claramente las
// clasificaciones OFICIALES (alerta ENFEN / NOAA-CPC) de las categorías de
// intensidad derivadas por el observatorio.

export function icenCategory(icen: number | null): string {
  if (icen === null) return "Sin datos";
  const a = Math.abs(icen);
  const sign = icen >= 0 ? "El Niño Costero" : "La Niña Costera";
  if (a < 0.4) return "Normal";
  if (a < 1.0) return `${sign} débil`;
  if (a < 1.5) return `${sign} moderado`;
  if (a < 2.0) return `${sign} fuerte`;
  return `${sign} muy fuerte`;
}

export function roniCategory(roni: number | null): string {
  if (roni === null) return "Sin datos";
  if (roni >= 0.5) return "El Niño (cuenca)";
  if (roni <= -0.5) return "La Niña (cuenca)";
  return "ENSO Neutral (cuenca)";
}

export function soiCategory(soi: number | null): string {
  if (soi === null) return "Sin datos";
  if (soi <= -0.5) return "Componente atmosférica de El Niño";
  if (soi >= 0.5) return "Componente atmosférica de La Niña";
  return "Componente atmosférica neutral";
}

export function u850Direction(uAnom: number | null): {
  label: string;
  signMeaning: string;
} {
  if (uAnom === null) return { label: "Sin datos", signMeaning: "" };
  // u > 0 ⇒ flujo hacia el este (componente del oeste / westerly)
  if (uAnom > 0.5)
    return {
      label: "Anomalía del oeste (flujo hacia el este)",
      signMeaning: "u > 0 ⇒ componente del oeste (westerly), hacia el este. Típico de El Niño de cuenca.",
    };
  if (uAnom < -0.5)
    return {
      label: "Anomalía del este (flujo hacia el oeste)",
      signMeaning: "u < 0 ⇒ componente del este (easterly), hacia el oeste. Típico de La Niña de cuenca.",
    };
  return {
    label: "Anomalía zonal débil / neutral",
    signMeaning: "u ≈ 0 ⇒ sin anomalía zonal significativa.",
  };
}

export function d20Interpretation(d20: number | null): string {
  if (d20 === null) return "Sin datos";
  if (d20 > 5) return "Termoclina más profunda de lo normal (señal de El Niño de cuenca)";
  if (d20 < -5) return "Termoclina más somera de lo normal (señal de La Niña de cuenca)";
  return "Profundidad de la termoclina cerca de lo normal";
}

/** Percentil de un valor dentro de la historia de su serie (misma firma que el dato). */
export function percentile(series: Series, value: number | null): number | null {
  if (value === null) return null;
  const vals = series.points
    .map((p) => p.value)
    .filter((v): v is number => v !== null)
    .sort((a, b) => a - b);
  if (vals.length === 0) return null;
  let below = 0;
  for (const v of vals) if (v < value) below++;
  return Math.round((below / vals.length) * 100);
}

/** Construye el estado actual consolidado del observatorio. */
export function buildCurrentStatus(): CurrentStatus {
  const all = generateAllSeries();
  const n12 = latest(all.nino12);
  const icen = latest(all.icen);
  const n34 = latest(all.nino34);
  const roni = latest(all.roni);
  const soi = latest(all.soi);
  const u850 = latest(all.u850);
  const d20 = latest(all.d20);

  const icenWindow = window3Label(icen?.point.month ?? AS_OF_MONTH);
  const roniWindow = window3Label(roni?.point.month ?? AS_OF_MONTH);
  const dir = u850Direction(u850?.point.value ?? null);

  return {
    asOf: AS_OF_DATE,
    coastal: {
      // Estado OFICIAL tomado textualmente de ENFEN (verificado).
      alert: "Alerta de El Niño Costero",
      alertSource: "ENFEN / IMARPE (siofen.imarpe.gob.pe)",
      alertSince: "2026-02-13",
      nino12Anom: n12?.point.value ?? null,
      nino12Month: n12?.point.month ?? AS_OF_MONTH,
      icen: icen?.point.value ?? null,
      icenWindow,
      icenCategory: icenCategory(icen?.point.value ?? null),
      freshness: `${n12?.point.flag === "preliminary" ? "Dato preliminar" : "Dato final"} · corte ${AS_OF_DATE}`,
      preliminary: n12?.point.flag === "preliminary",
    },
    basin: {
      // Estado OFICIAL tomado de NOAA/CPC ENSO Diagnostic Discussion.
      alert: "El Niño Advisory",
      alertSource: "NOAA / CPC — ENSO Diagnostic Discussion",
      alertSince: "2026-06",
      nino34Anom: n34?.point.value ?? null,
      nino34Month: n34?.point.month ?? AS_OF_MONTH,
      roni: roni?.point.value ?? null,
      roniWindow,
      roniCategory: roniCategory(roni?.point.value ?? null),
      freshness: `${n34?.point.flag === "preliminary" ? "Dato preliminar" : "Dato final"} · corte ${AS_OF_DATE}`,
      preliminary: n34?.point.flag === "preliminary",
    },
    winds: {
      u850Anom: u850?.point.value ?? null,
      u850Month: u850?.point.month ?? AS_OF_MONTH,
      direction: dir.label,
      signMeaning: dir.signMeaning,
    },
    thermocline: {
      d20Anom: d20?.point.value ?? null,
      d20Month: d20?.point.month ?? AS_OF_MONTH,
      interpretation: d20Interpretation(d20?.point.value ?? null),
    },
    soi: {
      value: soi?.point.value ?? null,
      month: soi?.point.month ?? AS_OF_MONTH,
      interpretation: soiCategory(soi?.point.value ?? null),
      note:
        "El SOI es un índice de escala de cuenca. El observatorio NO define " +
        "un «SOI costero»: no existe un proxy de presión costera con respaldo " +
        "metodológico equivalente.",
    },
    dataVersion: "1.0.0",
    generatedAt: new Date().toISOString(),
  };
}

function window3Label(lastMonthIso: string): string {
  const [y, m] = lastMonthIso.split("-").map(Number);
  const idx = (y - 1990) * 12 + (m - 1);
  const months = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];
  const labels: string[] = [];
  for (let k = 2; k >= 0; k--) {
    const i = idx - k;
    const yy = 1990 + Math.floor(i / 12);
    const mm = i % 12;
    labels.push(`${months[mm]} ${yy}`);
  }
  return labels.join("–");
}

/** Comparación de eventos históricos para la vista de comparación. */
export interface EventComparison {
  id: string;
  label: string;
  type: "basin" | "coastal" | "mixed";
  startMonth: string;
  peakMonth: string;
  peakNino34: number | null;
  peakNino12: number | null;
  note: string;
}

export const HISTORICAL_EVENTS: EventComparison[] = [
  { id: "1997-98", label: "El Niño 1997–98", type: "mixed", startMonth: "1997-04", peakMonth: "1997-12", peakNino34: 2.4, peakNino12: 2.6, note: "Evento de cuenca muy fuerte con fuerte expresión costera." },
  { id: "2010-11", label: "La Niña 2010–11", type: "basin", startMonth: "2010-06", peakMonth: "2010-12", peakNino34: -1.6, peakNino12: -1.4, note: "La Niña de cuenca fuerte." },
  { id: "2015-16", label: "El Niño 2015–16", type: "basin", startMonth: "2015-04", peakMonth: "2015-12", peakNino34: 2.3, peakNino12: 1.6, note: "El Niño de cuenca muy fuerte; expresión costera moderada." },
  { id: "2017", label: "El Niño Costero 2017", type: "coastal", startMonth: "2017-01", peakMonth: "2017-03", peakNino34: 0.3, peakNino12: 2.5, note: "Caso paradigmático: El Niño Costero fuerte SIN El Niño de cuenca." },
  { id: "2020-22", label: "La Niña triple 2020–22", type: "basin", startMonth: "2020-07", peakMonth: "2022-01", peakNino34: -1.0, peakNino12: -0.8, note: "Tres años consecutivos de La Niña de cuenca." },
  { id: "2023", label: "El Niño 2023", type: "mixed", startMonth: "2023-04", peakMonth: "2023-12", peakNino34: 1.8, peakNino12: 1.9, note: "El Niño de cuenca moderado-fuerte con expresión costera." },
  { id: "2026", label: "El Niño 2026 (en curso)", type: "mixed", startMonth: "2025-09", peakMonth: "2026-06", peakNino34: 1.6, peakNino12: 1.5, note: "Cuenca en desarrollo (El Niño Advisory); Alerta de El Niño Costero desde 13 feb 2026." },
];

/** Resumen de frescura y calidad por indicador. */
export interface QualityRow {
  indicatorId: string;
  label: string;
  scope: "coastal" | "basin";
  lastMonth: string;
  lastValue: number | null;
  units: string;
  preliminary: boolean;
  freshnessHours: number;
  source: string;
}

export function buildQualitySummary(): QualityRow[] {
  const all = generateAllSeries();
  const now = Date.now();
  const asOfMs = new Date(AS_OF_DATE).getTime();
  const rows: QualityRow[] = [];
  for (const ind of Object.values(INDICATOR_BY_ID)) {
    const s = all[ind.id];
    if (!s) continue;
    const lp = latest(s);
    const monthEnd = monthEndMs(lp?.point.month ?? AS_OF_MONTH);
    rows.push({
      indicatorId: ind.id,
      label: ind.shortName,
      scope: ind.scope,
      lastMonth: lp?.point.month ?? AS_OF_MONTH,
      lastValue: lp?.point.value ?? null,
      units: ind.units,
      preliminary: lp?.point.flag === "preliminary",
      freshnessHours: Math.max(0, Math.round((asOfMs - monthEnd) / 3.6e6)),
      source: INDICATOR_BY_ID[ind.id].sourceId,
    });
  }
  return rows;
}

function monthEndMs(monthIso: string): number {
  const [y, m] = monthIso.split("-").map(Number);
  const next = m === 12 ? new Date(y + 1, 0, 1) : new Date(y, m, 1);
  return next.getTime();
}

// ============================================================================
// Alertas y umbrales de activación de evento.
// ----------------------------------------------------------------------------
// Sigue las definiciones operacionales: ICEN requiere 3 meses consecutivos con
// anomalía ≥ +0.4 °C (El Niño Costero) o ≤ −0.4 °C (La Niña Costera); RONI
// requiere media móvil de 3 meses ≥ +0.5 °C (El Niño de cuenca) o ≤ −0.5 °C
// (La Niña de cuenca). Estas son condiciones de activación derivadas por el
// observatorio; la declaración oficial corresponde a ENFEN y NOAA/CPC.
// ============================================================================

export interface AlertState {
  indicatorId: string;
  label: string;
  scope: "coastal" | "basin";
  threshold: number;
  current: number | null;
  currentMonth: string;
  /** Meses consecutivos actuales sobre el umbral (misma dirección). */
  consecutiveMonths: number;
  /** Meses consecutivos requeridos para activación. */
  requiredMonths: number;
  /** Dirección: 'warm' (El Niño) o 'cool' (La Niña) o 'neutral'. */
  direction: "warm" | "cool" | "neutral";
  /** Estado de activación derivado. */
  status: "Cumplido" | "En vigilancia" | "Neutral";
  /** Porcentaje de progreso hacia la activación (0-100). */
  progress: number;
  note: string;
}

export function buildAlertStates(): AlertState[] {
  const all = generateAllSeries();
  const states: AlertState[] = [];

  // ICEN: 3 meses consecutivos ≥ +0.4 (El Niño Costero) o ≤ −0.4 (La Niña Costera)
  states.push(buildAlertFromSeries(all.icen, "icen", "ICEN", "coastal", 0.4, 3));
  // RONI: 3 meses consecutivos ≥ +0.5 (El Niño de cuenca) o ≤ −0.5 (La Niña de cuenca)
  states.push(buildAlertFromSeries(all.roni, "roni", "RONI", "basin", 0.5, 3));

  return states;
}

function buildAlertFromSeries(
  series: Series,
  indicatorId: string,
  label: string,
  scope: "coastal" | "basin",
  threshold: number,
  requiredMonths: number
): AlertState {
  const points = series.points;
  let current: number | null = null;
  let currentMonth = "";
  let consecutive = 0;
  let direction: "warm" | "cool" | "neutral" = "neutral";

  for (let i = points.length - 1; i >= 0; i--) {
    const v = points[i].value;
    if (v === null) continue;
    if (current === null) {
      current = v;
      currentMonth = points[i].month;
      if (v >= threshold) direction = "warm";
      else if (v <= -threshold) direction = "cool";
      else direction = "neutral";
    }
    // Contar consecutivos hacia atrás en la misma dirección.
    if (direction === "warm" && v >= threshold) consecutive++;
    else if (direction === "cool" && v <= -threshold) consecutive++;
    else if (direction === "neutral" && Math.abs(v) < threshold) {
      // neutral: no cuenta para activación
    } else break;
  }

  const progress = direction === "neutral" ? 0 : Math.min(100, Math.round((consecutive / requiredMonths) * 100));
  const status: AlertState["status"] =
    direction === "neutral" ? "Neutral" : consecutive >= requiredMonths ? "Cumplido" : "En vigilancia";
  const dirLabel = direction === "warm" ? (scope === "coastal" ? "El Niño Costero" : "El Niño de cuenca") : direction === "cool" ? (scope === "coastal" ? "La Niña Costera" : "La Niña de cuenca") : "Neutral";
  const note =
    direction === "neutral"
      ? `Valor actual dentro del rango neutral (|valor| < ${threshold}). Sin condición de activación.`
      : `${dirLabel}: ${consecutive} de ${requiredMonths} meses consecutivos sobre el umbral (${threshold}). ${status === "Cumplido" ? "Condición de activación derivada cumplida." : "En vigilancia."} Interpretación del observatorio; la declaración oficial corresponde a ${scope === "coastal" ? "ENFEN" : "NOAA/CPC"}.`;

  return {
    indicatorId,
    label,
    scope,
    threshold,
    current,
    currentMonth,
    consecutiveMonths: consecutive,
    requiredMonths,
    direction,
    status,
    progress,
    note,
  };
}

// ============================================================================
// Correlaciones entre indicadores (cálculo determinista en código).
// ============================================================================

export interface CorrelationPair {
  idA: string;
  idB: string;
  labelA: string;
  labelB: string;
  /** Coeficiente de Pearson en [-1, 1]. */
  pearson: number;
  /** Etiqueta cualitativa. */
  strength: string;
  /** Interpretación en español. */
  interpretation: string;
}

export function buildCorrelations(): CorrelationPair[] {
  const all = generateAllSeries();
  const ids = Object.keys(all);
  const pairs: CorrelationPair[] = [];
  const labels: Record<string, string> = {
    nino12: "Niño 1+2", icen: "ICEN", nino34: "Niño 3.4", roni: "RONI",
    soi: "SOI", u850: "u850", d20: "D20",
  };
  const expectations: Record<string, string> = {
    "nino34-soi": "Anticorrelación esperada: SOI negativo acompaña a El Niño de cuenca.",
    "nino34-d20": "Correlación positiva esperada: D20 se profundiza con El Niño de cuenca.",
    "nino34-u850": "Correlación positiva esperada: anomalías del oeste acompañan a El Niño de cuenca.",
    "nino12-nino34": "Correlación parcial: la costa y la cuenca pueden divergir (caso 2017).",
    "icen-nino12": "Alta correlación esperada: ICEN se deriva de Niño 1+2.",
    "roni-nino34": "Alta correlación esperada: RONI se deriva de Niño 3.4.",
  };

  for (let i = 0; i < ids.length; i++) {
    for (let j = i + 1; j < ids.length; j++) {
      const a = all[ids[i]], b = all[ids[j]];
      const vals = a.points
        .map((p, k) => [p.value, b.points[k].value])
        .filter(([x, y]) => x !== null && y !== null) as [number, number][];
      if (vals.length < 10) continue;
      const r = pearson(vals.map((v) => v[0]), vals.map((v) => v[1]));
      const abs = Math.abs(r);
      const strength = abs >= 0.7 ? "Fuerte" : abs >= 0.4 ? "Moderada" : abs >= 0.2 ? "Débil" : "Nula";
      const key = `${ids[i]}-${ids[j]}`;
      const interp = expectations[key] ?? `Coeficiente de Pearson r = ${r.toFixed(2)}. Interpretación del observatorio.`;
      pairs.push({
        idA: ids[i], idB: ids[j],
        labelA: labels[ids[i]] ?? ids[i], labelB: labels[ids[j]] ?? ids[j],
        pearson: Math.round(r * 100) / 100,
        strength, interpretation: interp,
      });
    }
  }
  return pairs.sort((a, b) => Math.abs(b.pearson) - Math.abs(a.pearson));
}

function pearson(x: number[], y: number[]): number {
  const n = x.length;
  if (n === 0) return 0;
  const mx = x.reduce((a, b) => a + b, 0) / n;
  const my = y.reduce((a, b) => a + b, 0) / n;
  let num = 0, dx = 0, dy = 0;
  for (let i = 0; i < n; i++) {
    const a = x[i] - mx, b = y[i] - my;
    num += a * b; dx += a * a; dy += b * b;
  }
  const den = Math.sqrt(dx * dy);
  return den === 0 ? 0 : num / den;
}

export { AS_OF_DATE, AS_OF_MONTH, generateAllSeries, getSeries, latest };
