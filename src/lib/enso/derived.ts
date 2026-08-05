import type { CurrentStatus, Series } from "./types";
import { INDICATOR_BY_ID } from "./methodology";
import { generateAllSeries, getSeries, latest, AS_OF_MONTH, AS_OF_DATE, MONTHS } from "./series";

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

// ============================================================================
// Índice compuesto ENSO del observatorio.
// ----------------------------------------------------------------------------
// Síntesis integrada que combina los principales indicadores oceánicos y
// atmosféricos en un único índice adimensional. Es INTERPRETACIÓN GENERADA
// POR EL OBSERVATORIO, no un índice oficial. Combina:
//   - Niño 3.4 (cuenca oceánica) y Niño 1+2 (costero oceánico)
//   - SOI (componente atmosférica, invertido)
//   - D20 (termoclina, normalizado)
//   - u850 (viento, normalizado)
// Cada componente se normaliza por su escala típica y se pondera.
// ============================================================================

export interface CompositeIndex {
  /** Mes ISO. */
  month: string;
  /** Valor del índice compuesto (adimensional, típico -3..+3). */
  value: number;
  /** Componentes individuales normalizados. */
  components: {
    nino34: number;
    nino12: number;
    soi: number; // invertido (SOI negativo → cálido)
    d20: number;
    u850: number;
  };
  /** Categoría derivada. */
  category: string;
}

export function buildCompositeIndex(): CompositeIndex[] {
  const all = generateAllSeries();
  const scales = { nino34: 1.0, nino12: 1.2, soi: 1.5, d20: 8.0, u850: 2.0 };
  const weights = { nino34: 0.30, nino12: 0.25, soi: 0.20, d20: 0.15, u850: 0.10 };

  return MONTHS.map((month, i) => {
    const n34 = all.nino34.points[i].value;
    const n12 = all.nino12.points[i].value;
    const soi = all.soi.points[i].value;
    const d20 = all.d20.points[i].value;
    const u850 = all.u850.points[i].value;
    if (n34 === null || n12 === null || soi === null || d20 === null || u850 === null) {
      // Saltar meses con datos faltantes (sin interpolar).
      return null;
    }
    const cN34 = n34 / scales.nino34;
    const cN12 = n12 / scales.nino12;
    const cSOI = -soi / scales.soi; // invertido: SOI negativo → cálido
    const cD20 = d20 / scales.d20;
    const cU850 = u850 / scales.u850;
    const value = cN34 * weights.nino34 + cN12 * weights.nino12 + cSOI * weights.soi + cD20 * weights.d20 + cU850 * weights.u850;
    const cat = compositeCategory(value);
    return {
      month,
      value: Math.round(value * 100) / 100,
      components: {
        nino34: Math.round(cN34 * 100) / 100,
        nino12: Math.round(cN12 * 100) / 100,
        soi: Math.round(cSOI * 100) / 100,
        d20: Math.round(cD20 * 100) / 100,
        u850: Math.round(cU850 * 100) / 100,
      },
      category: cat,
    } as CompositeIndex;
  }).filter((x): x is CompositeIndex => x !== null);
}

export function compositeCategory(v: number): string {
  if (v >= 1.5) return "El Niño fuerte (cuenca)";
  if (v >= 0.8) return "El Niño (cuenca)";
  if (v >= 0.3) return "Tendencia cálida";
  if (v <= -1.5) return "La Niña fuerte (cuenca)";
  if (v <= -0.8) return "La Niña (cuenca)";
  if (v <= -0.3) return "Tendencia fría";
  return "Neutral";
}

// ============================================================================
// Estacionalidad: climatología mensual por indicador.
// ----------------------------------------------------------------------------
// Calcula el promedio y desviación estándar de cada mes calendario (1..12)
// sobre toda la historia disponible. Permite comparar el valor actual con su
// estacionalidad típica. Es cálculo determinista en código.
// ============================================================================

export interface MonthlyClimatology {
  month: number; // 1..12
  monthLabel: string;
  mean: number;
  std: number;
  min: number;
  max: number;
  count: number;
}

export interface SeasonalityResult {
  indicatorId: string;
  label: string;
  units: string;
  climatology: MonthlyClimatology[];
  /** Valor del mes más reciente para comparación. */
  latestMonth: number;
  latestValue: number | null;
}

const MONTH_LABELS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];

export function buildSeasonality(indicatorId: string): SeasonalityResult | null {
  const all = generateAllSeries();
  const s = all[indicatorId];
  if (!s) return null;
  const byMonth: Record<number, number[]> = {};
  for (let m = 1; m <= 12; m++) byMonth[m] = [];
  for (const p of s.points) {
    if (p.value === null) continue;
    const m = Number(p.month.split("-")[1]);
    byMonth[m].push(p.value);
  }
  const clim: MonthlyClimatology[] = [];
  for (let m = 1; m <= 12; m++) {
    const vals = byMonth[m];
    if (vals.length === 0) {
      clim.push({ month: m, monthLabel: MONTH_LABELS[m - 1], mean: 0, std: 0, min: 0, max: 0, count: 0 });
      continue;
    }
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    const variance = vals.reduce((a, b) => a + (b - mean) ** 2, 0) / vals.length;
    const std = Math.sqrt(variance);
    clim.push({
      month: m,
      monthLabel: MONTH_LABELS[m - 1],
      mean: Math.round(mean * 100) / 100,
      std: Math.round(std * 100) / 100,
      min: Math.round(Math.min(...vals) * 100) / 100,
      max: Math.round(Math.max(...vals) * 100) / 100,
      count: vals.length,
    });
  }
  const lp = s.points[s.points.length - 1];
  return {
    indicatorId,
    label: s.label,
    units: s.units,
    climatology: clim,
    latestMonth: lp ? Number(lp.month.split("-")[1]) : 1,
    latestValue: lp?.value ?? null,
  };
}

// ============================================================================
// Comparación de eventos: extrae las series de un evento para comparación.
// ============================================================================

export interface EventSeries {
  eventId: string;
  label: string;
  type: string;
  months: string[]; // meses relativos -24..+24 desde el pico
  nino34: (number | null)[];
  nino12: (number | null)[];
  icen: (number | null)[];
}

export function buildEventSeries(eventId: string): EventSeries | null {
  const event = HISTORICAL_EVENTS.find((e) => e.id === eventId);
  if (!event) return null;
  const all = generateAllSeries();
  const peakIdx = MONTHS.indexOf(event.peakMonth);
  if (peakIdx < 0) return null;
  const window = 24; // ±24 meses desde el pico
  const months: string[] = [];
  const nino34: (number | null)[] = [];
  const nino12: (number | null)[] = [];
  const icen: (number | null)[] = [];
  for (let offset = -window; offset <= window; offset++) {
    const idx = peakIdx + offset;
    if (idx < 0 || idx >= MONTHS.length) {
      months.push(`+${offset}`);
      nino34.push(null);
      nino12.push(null);
      icen.push(null);
    } else {
      months.push(offset === 0 ? "Pico" : offset > 0 ? `+${offset}` : `${offset}`);
      nino34.push(all.nino34.points[idx].value);
      nino12.push(all.nino12.points[idx].value);
      icen.push(all.icen.points[idx].value);
    }
  }
  return {
    eventId: event.id,
    label: event.label,
    type: event.type,
    months,
    nino34,
    nino12,
    icen,
  };
}

// ============================================================================
// Banda de probabilidad ENSO (ventana móvil).
// ----------------------------------------------------------------------------
// Para cada mes, calcula la fracción de meses (en una ventana móvil de N meses
// alrededor) que estuvieron en cada categoría (El Niño / Neutral / La Niña).
// Es cálculo determinista en código; el modelo no participa.
// ============================================================================

export interface ProbabilityBand {
  month: string;
  probNino: number; // 0-100
  probNeutral: number;
  probNina: number;
  /** Valor central de Niño 3.4 en la ventana. */
  meanN34: number | null;
}

export function buildProbabilityBands(windowMonths = 12): ProbabilityBand[] {
  const all = generateAllSeries();
  const n34 = all.nino34.points;
  const result: ProbabilityBand[] = [];
  const half = Math.floor(windowMonths / 2);
  for (let i = 0; i < n34.length; i++) {
    const start = Math.max(0, i - half);
    const end = Math.min(n34.length - 1, i + half);
    let nino = 0, neutral = 0, nina = 0, count = 0, sum = 0;
    for (let j = start; j <= end; j++) {
      const v = n34[j].value;
      if (v === null) continue;
      count++;
      sum += v;
      if (v >= 0.5) nino++;
      else if (v <= -0.5) nina++;
      else neutral++;
    }
    if (count === 0) {
      result.push({ month: n34[i].month, probNino: 0, probNeutral: 0, probNina: 0, meanN34: null });
    } else {
      result.push({
        month: n34[i].month,
        probNino: Math.round((nino / count) * 100),
        probNeutral: Math.round((neutral / count) * 100),
        probNina: Math.round((nina / count) * 100),
        meanN34: Math.round((sum / count) * 100) / 100,
      });
    }
  }
  return result;
}

// ============================================================================
// Teleconexiones e impactos globales de ENSO.
// ----------------------------------------------------------------------------
// Describe los impactos típicos de El Niño y La Niña sobre diferentes regiones
// del mundo. Es conocimiento climático curado, no un pronóstico.
// ============================================================================

export interface TeleconnectionImpact {
  region: string;
  lat: number;
  lon: number;
  /** Impacto durante El Niño. */
  ninoImpact: string;
  /** Impacto durante La Niña. */
  ninaImpact: string;
  /** Confianza en la teleconexión (Alta/Media/Baja). */
  confidence: "Alta" | "Media" | "Baja";
  /** Variables afectadas. */
  variables: string[];
}

export const TELECONNECTIONS: TeleconnectionImpact[] = [
  {
    region: "Perú — costa norte",
    lat: -5, lon: -81,
    ninoImpact: "Lluvias intensas, inundaciones, calentamiento costero (El Niño Costero).",
    ninaImpact: "Condiciones más secas, enfriamiento costero.",
    confidence: "Alta",
    variables: ["Precipitación", "TSM costera"],
  },
  {
    region: "Perú — sierra sur",
    lat: -14, lon: -72,
    ninoImpact: "Sequías, déficit de precipitación en altiplano.",
    ninaImpact: "Lluvias cercanas a lo normal o superiores.",
    confidence: "Media",
    variables: ["Precipitación"],
  },
  {
    region: "Ecuador — costa",
    lat: -1, lon: -80,
    ninoImpact: "Lluvias intensas, inundaciones (junto con Perú costa norte).",
    ninaImpact: "Condiciones secas.",
    confidence: "Alta",
    variables: ["Precipitación", "TSM"],
  },
  {
    region: "Brasil — Amazonía nororiental",
    lat: -5, lon: -50,
    ninoImpact: "Sequías, riesgo de incendios.",
    ninaImpact: "Lluvias abundantes.",
    confidence: "Alta",
    variables: ["Precipitación"],
  },
  {
    region: "Brasil — sur",
    lat: -30, lon: -52,
    ninoImpact: "Lluvias por encima de lo normal.",
    ninaImpact: "Sequías.",
    confidence: "Alta",
    variables: ["Precipitación"],
  },
  {
    region: "Australia — este",
    lat: -30, lon: 145,
    ninoImpact: "Sequías, olas de calor, riesgo de incendios.",
    ninaImpact: "Lluvias abundantes, riesgo de inundaciones.",
    confidence: "Alta",
    variables: ["Precipitación", "Temperatura"],
  },
  {
    region: "Indonesia",
    lat: -2, lon: 118,
    ninoImpact: "Sequías, riesgo de incendios forestales.",
    ninaImpact: "Lluvias abundantes.",
    confidence: "Alta",
    variables: ["Precipitación"],
  },
  {
    region: "India — monzón",
    lat: 22, lon: 78,
    ninoImpact: "Monzón debilitado, menos precipitación.",
    ninaImpact: "Monzón fortalecido.",
    confidence: "Alta",
    variables: ["Precipitación"],
  },
  {
    region: "EE. UU. — sur",
    lat: 32, lon: -97,
    ninoImpact: "Invierno más húmedo y fresco en el sur.",
    ninaImpact: "Invierno más seco y cálido.",
    confidence: "Alta",
    variables: ["Precipitación", "Temperatura"],
  },
  {
    region: "EE. UU. — noreste",
    lat: 42, lon: -75,
    ninoImpact: "Invierno más cálido.",
    ninaImpact: "Invierno más frío y nevoso.",
    confidence: "Media",
    variables: ["Temperatura"],
  },
  {
    region: "África oriental",
    lat: 0, lon: 38,
    ninoImpact: "Lluvias por encima de lo normal en cortas estaciones (oct-dic, mar-may).",
    ninaImpact: "Sequías.",
    confidence: "Media",
    variables: ["Precipitación"],
  },
  {
    region: "África austral",
    lat: -20, lon: 28,
    ninoImpact: "Sequías.",
    ninaImpact: "Lluvias por encima de lo normal.",
    confidence: "Media",
    variables: ["Precipitación"],
  },
  {
    region: "Argentina — pampa",
    lat: -35, lon: -63,
    ninoImpact: "Lluvias por encima de lo normal.",
    ninaImpact: "Sequías.",
    confidence: "Media",
    variables: ["Precipitación"],
  },
  {
    region: "Asia oriental (China/Japón)",
    lat: 35, lon: 115,
    ninoImpact: "Verano más fresco, anomalías en el monzón.",
    ninaImpact: "Verano más cálido.",
    confidence: "Media",
    variables: ["Temperatura", "Precipitación"],
  },
];

// ============================================================================
// Análisis de tendencias: regresión lineal y detección de cambio de fase.
// ----------------------------------------------------------------------------
// Para cada indicador, calcula la tendencia lineal (pendiente por mes) sobre
// ventanas móviles, y detecta cambios de fase (transiciones entre categorías).
// Es cálculo determinista en código; el modelo no participa.
// ============================================================================

export interface TrendPoint {
  month: string;
  /** Pendiente de la regresión lineal sobre la ventana (por mes). */
  slope: number;
  /** R² del ajuste (0-1). */
  r2: number;
  /** Valor medio en la ventana. */
  mean: number;
}

export interface TrendResult {
  indicatorId: string;
  label: string;
  units: string;
  /** Tendencia sobre los últimos N meses. */
  windowMonths: number;
  points: TrendPoint[];
  /** Tendencia actual (última ventana). */
  currentSlope: number;
  currentR2: number;
  /** Interpretación de la tendencia. */
  interpretation: string;
}

export function buildTrend(indicatorId: string, windowMonths = 24): TrendResult | null {
  const all = generateAllSeries();
  const s = all[indicatorId];
  if (!s) return null;
  const points: TrendPoint[] = [];
  for (let i = windowMonths - 1; i < s.points.length; i++) {
    const window = s.points.slice(i - windowMonths + 1, i + 1);
    const vals = window.map((p) => p.value).filter((v): v is number => v !== null);
    if (vals.length < windowMonths / 2) continue;
    const xs = vals.map((_, j) => j);
    const n = vals.length;
    const mx = xs.reduce((a, b) => a + b, 0) / n;
    const my = vals.reduce((a, b) => a + b, 0) / n;
    let num = 0, dx = 0, dy = 0;
    for (let j = 0; j < n; j++) {
      const a = xs[j] - mx, b = vals[j] - my;
      num += a * b; dx += a * a; dy += b * b;
    }
    const slope = dx === 0 ? 0 : num / dx;
    const r2 = dy === 0 ? 0 : Math.max(0, (num * num) / (dx * dy));
    points.push({
      month: s.points[i].month,
      slope: Math.round(slope * 10000) / 10000,
      r2: Math.round(r2 * 100) / 100,
      mean: Math.round(my * 100) / 100,
    });
  }
  const last = points[points.length - 1];
  const interp = last
    ? last.slope > 0.01
      ? `Tendencia creciente (${(last.slope * 12).toFixed(2)} por año)`
      : last.slope < -0.01
      ? `Tendencia decreciente (${(last.slope * 12).toFixed(2)} por año)`
      : "Tendencia estable"
    : "Sin datos suficientes";
  return {
    indicatorId,
    label: s.label,
    units: s.units,
    windowMonths,
    points,
    currentSlope: last?.slope ?? 0,
    currentR2: last?.r2 ?? 0,
    interpretation: interp,
  };
}

// ============================================================================
// Detección de cambios de fase (transiciones entre categorías ENSO).
// ============================================================================

export interface PhaseChange {
  month: string;
  fromPhase: "El Niño" | "Neutral" | "La Niña";
  toPhase: "El Niño" | "Neutral" | "La Niña";
  value: number;
}

export function buildPhaseChanges(): PhaseChange[] {
  const all = generateAllSeries();
  const n34 = all.nino34.points;
  const changes: PhaseChange[] = [];
  let prevPhase: "El Niño" | "Neutral" | "La Niña" | null = null;
  for (const p of n34) {
    if (p.value === null) continue;
    const phase: "El Niño" | "Neutral" | "La Niña" =
      p.value >= 0.5 ? "El Niño" : p.value <= -0.5 ? "La Niña" : "Neutral";
    if (prevPhase !== null && phase !== prevPhase) {
      changes.push({
        month: p.month,
        fromPhase: prevPhase,
        toPhase: phase,
        value: Math.round(p.value * 100) / 100,
      });
    }
    prevPhase = phase;
  }
  return changes;
}

// ============================================================================
// Fichas técnicas por indicador: estadísticas completas.
// ============================================================================

export interface IndicatorFactSheet {
  indicatorId: string;
  label: string;
  name: string;
  scope: "coastal" | "basin";
  units: string;
  region: string;
  level: string | undefined;
  aggregation: string;
  climatology: string;
  dataset: string;
  signConvention: string;
  sourceId: string;
  latestValue: number | null;
  latestMonth: string;
  mean: number;
  std: number;
  min: number;
  max: number;
  percentileLatest: number | null;
  trend12m: number;
  trend24m: number;
  positiveMonths: number;
  negativeMonths: number;
  totalMonths: number;
  isOfficial: boolean;
}

export function buildFactSheet(indicatorId: string): IndicatorFactSheet | null {
  const all = generateAllSeries();
  const s = all[indicatorId];
  const ind = INDICATOR_BY_ID[indicatorId];
  if (!s || !ind) return null;
  const vals = s.points.map((p) => p.value).filter((v): v is number => v !== null);
  if (vals.length === 0) return null;
  const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
  const std = Math.sqrt(vals.reduce((a, b) => a + (b - mean) ** 2, 0) / vals.length);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const lp = s.points[s.points.length - 1];
  let below = 0;
  for (const v of vals) if (v < (lp?.value ?? 0)) below++;
  const pct = lp?.value !== null ? Math.round((below / vals.length) * 100) : null;
  const trend12 = buildTrend(indicatorId, 12);
  const trend24 = buildTrend(indicatorId, 24);
  const positive = vals.filter((v) => v > 0).length;
  const negative = vals.filter((v) => v < 0).length;
  return {
    indicatorId,
    label: s.label,
    name: ind.name,
    scope: ind.scope,
    units: ind.units,
    region: ind.region,
    level: ind.level,
    aggregation: ind.aggregation,
    climatology: ind.climatology,
    dataset: ind.dataset,
    signConvention: ind.signConvention,
    sourceId: ind.sourceId,
    latestValue: lp?.value ?? null,
    latestMonth: lp?.month ?? "",
    mean: Math.round(mean * 100) / 100,
    std: Math.round(std * 100) / 100,
    min: Math.round(min * 100) / 100,
    max: Math.round(max * 100) / 100,
    percentileLatest: pct,
    trend12m: trend12?.currentSlope ?? 0,
    trend24m: trend24?.currentSlope ?? 0,
    positiveMonths: positive,
    negativeMonths: negative,
    totalMonths: vals.length,
    isOfficial: ind.isOfficial,
  };
}

// ============================================================================
// Historial de alertas: línea de tiempo de estados ENSO oficiales y derivados.
// ----------------------------------------------------------------------------
// Reconstruye el historial de alertas a partir de las series normalizadas,
// etiquetando periodos por categoría. Las alertas OFICIALES se citan
// textualmente de ENFEN y NOAA/CPC; este historial es una reconstrucción
// derivada del observatorio con fines de seguimiento.
// ============================================================================

export interface AlertPeriod {
  startMonth: string;
  endMonth: string;
  phase: "El Niño" | "Neutral" | "La Niña";
  scope: "costero" | "cuenca";
  /** Intensidad pico en el periodo. */
  peakValue: number;
  peakMonth: string;
  /** Duración en meses. */
  durationMonths: number;
  /** Categoría de intensidad derivada. */
  intensity: string;
}

export function buildAlertHistory(): AlertPeriod[] {
  const all = generateAllSeries();
  const periods: AlertPeriod[] = [];

  // Cuenca: sobre Niño 3.4 con umbral ±0.5 °C
  periods.push(...extractPeriods(all.nino34.points, "cuenca"));
  // Costero: sobre ICEN con umbral ±0.4 °C
  periods.push(...extractPeriods(all.icen.points, "costero", 0.4));

  return periods.sort((a, b) => a.startMonth.localeCompare(b.startMonth));
}

function extractPeriods(
  points: { month: string; value: number | null }[],
  scope: "costero" | "cuenca",
  threshold = 0.5
): AlertPeriod[] {
  const out: AlertPeriod[] = [];
  let current: { phase: "El Niño" | "La Niña"; start: string; peak: number; peakMonth: string } | null = null;
  for (const p of points) {
    if (p.value === null) continue;
    const phase: "El Niño" | "Neutral" | "La Niña" =
      p.value >= threshold ? "El Niño" : p.value <= -threshold ? "La Niña" : "Neutral";
    if (phase === "Neutral") {
      if (current) {
        out.push({
          startMonth: current.start,
          endMonth: p.month,
          phase: current.phase,
          scope,
          peakValue: Math.round(current.peak * 100) / 100,
          peakMonth: current.peakMonth,
          durationMonths: monthDiff(current.start, p.month),
          intensity: intensityLabel(current.peak, scope, threshold),
        });
        current = null;
      }
    } else {
      if (!current) {
        current = { phase, start: p.month, peak: p.value, peakMonth: p.month };
      } else if (current.phase === phase) {
        if (Math.abs(p.value) > Math.abs(current.peak)) {
          current.peak = p.value;
          current.peakMonth = p.month;
        }
      } else {
        // cambio de fase (Niño→Niña o viceversa)
        out.push({
          startMonth: current.start,
          endMonth: p.month,
          phase: current.phase,
          scope,
          peakValue: Math.round(current.peak * 100) / 100,
          peakMonth: current.peakMonth,
          durationMonths: monthDiff(current.start, p.month),
          intensity: intensityLabel(current.peak, scope, threshold),
        });
        current = { phase, start: p.month, peak: p.value, peakMonth: p.month };
      }
    }
  }
  if (current) {
    const last = points[points.length - 1];
    out.push({
      startMonth: current.start,
      endMonth: last?.month ?? current.start,
      phase: current.phase,
      scope,
      peakValue: Math.round(current.peak * 100) / 100,
      peakMonth: current.peakMonth,
      durationMonths: monthDiff(current.start, last?.month ?? current.start),
      intensity: intensityLabel(current.peak, scope, threshold),
    });
  }
  return out;
}

function monthDiff(start: string, end: string): number {
  const [y1, m1] = start.split("-").map(Number);
  const [y2, m2] = end.split("-").map(Number);
  return (y2 - y1) * 12 + (m2 - m1) + 1;
}

function intensityLabel(peak: number, scope: "costero" | "cuenca", threshold: number): string {
  const a = Math.abs(peak);
  const sign = peak >= 0 ? (scope === "costero" ? "El Niño Costero" : "El Niño") : (scope === "costero" ? "La Niña Costera" : "La Niña");
  if (scope === "costero") {
    if (a < 0.4) return "Normal";
    if (a < 1.0) return `${sign} débil`;
    if (a < 1.5) return `${sign} moderado`;
    if (a < 2.0) return `${sign} fuerte`;
    return `${sign} muy fuerte`;
  }
  // cuenca
  if (a < threshold) return "Neutral";
  if (a < 1.0) return `${sign} débil`;
  if (a < 1.5) return `${sign} moderado`;
  if (a < 2.0) return `${sign} fuerte`;
  return `${sign} muy fuerte`;
}

// ============================================================================
// Diagrama de fases ENSO: espacio de fase Niño 3.4 vs SOI.
// ----------------------------------------------------------------------------
// Cada punto es un mes; la trayectoria muestra la evolución temporal del
// sistema acoplado océano-atmósfera. Útil para visualizar la coherencia
// entre la componente oceánica (Niño 3.4) y atmosférica (SOI).
// ============================================================================

export interface PhasePoint {
  month: string;
  nino34: number | null;
  soi: number | null;
  /** Etiqueta de fase ENSO. */
  phase: "El Niño" | "Neutral" | "La Niña";
}

export function buildPhaseSpace(windowMonths = 60): PhasePoint[] {
  const all = generateAllSeries();
  const n = Math.min(windowMonths, all.nino34.points.length);
  const start = all.nino34.points.length - n;
  const out: PhasePoint[] = [];
  for (let i = start; i < all.nino34.points.length; i++) {
    const v34 = all.nino34.points[i].value;
    const vsoi = all.soi.points[i].value;
    if (v34 === null) continue;
    const phase: "El Niño" | "Neutral" | "La Niña" =
      v34 >= 0.5 ? "El Niño" : v34 <= -0.5 ? "La Niña" : "Neutral";
    out.push({
      month: all.nino34.points[i].month,
      nino34: v34,
      soi: vsoi,
      phase,
    });
  }
  return out;
}

// ============================================================================
// Catálogo maestro de eventos ENSO.
// ----------------------------------------------------------------------------
// Tabla exhaustiva de todos los periodos ENSO (costero y cuenca) con
// estadísticas completas para filtrado y comparación. Es cálculo determinista
// en código; el modelo no participa.
// ============================================================================

export interface CatalogEntry {
  id: string;
  scope: "costero" | "cuenca";
  phase: "El Niño" | "La Niña";
  startMonth: string;
  endMonth: string;
  peakMonth: string;
  peakValue: number;
  durationMonths: number;
  intensity: string;
  /** Año de inicio. */
  year: number;
  /** Década. */
  decade: number;
  /** Intensidad numérica (1=débil, 2=moderado, 3=fuerte, 4=muy fuerte). */
  intensityRank: 1 | 2 | 3 | 4;
}

export function buildEventCatalog(): CatalogEntry[] {
  const history = buildAlertHistory();
  return history
    .filter((p) => p.phase !== "Neutral")
    .map((p, i) => {
      const year = Number(p.startMonth.split("-")[0]);
      const decade = Math.floor(year / 10) * 10;
      const rank = intensityToRank(p.peakValue, p.scope);
      return {
        id: `${p.scope}-${i}-${p.startMonth}`,
        scope: p.scope,
        phase: p.phase as "El Niño" | "La Niña",
        startMonth: p.startMonth,
        endMonth: p.endMonth,
        peakMonth: p.peakMonth,
        peakValue: p.peakValue,
        durationMonths: p.durationMonths,
        intensity: p.intensity,
        year,
        decade,
        intensityRank: rank,
      };
    });
}

function intensityToRank(peak: number, scope: "costero" | "cuenca"): 1 | 2 | 3 | 4 {
  const a = Math.abs(peak);
  if (scope === "costero") {
    if (a < 1.0) return 1;
    if (a < 1.5) return 2;
    if (a < 2.0) return 3;
    return 4;
  }
  // cuenca
  if (a < 1.0) return 1;
  if (a < 1.5) return 2;
  if (a < 2.0) return 3;
  return 4;
}

// ============================================================================
// Comparación costero vs cuenca: métricas lado a lado.
// ============================================================================

export interface ScopeComparison {
  metric: string;
  coastal: string | number;
  basin: string | number;
  note: string;
}

export function buildScopeComparison(): ScopeComparison[] {
  const all = generateAllSeries();
  const coastalEvents = buildAlertHistory().filter((p) => p.scope === "costero" && p.phase !== "Neutral");
  const basinEvents = buildAlertHistory().filter((p) => p.scope === "basin" && p.phase !== "Neutral");
  const coastalNino = coastalEvents.filter((p) => p.phase === "El Niño");
  const basinNino = basinEvents.filter((p) => p.phase === "El Niño");
  const coastalNina = coastalEvents.filter((p) => p.phase === "La Niña");
  const basinNina = basinEvents.filter((p) => p.phase === "La Niña");

  const coastalDurations = coastalEvents.map((p) => p.durationMonths);
  const basinDurations = basinEvents.map((p) => p.durationMonths);
  const coastalPeaks = coastalEvents.map((p) => Math.abs(p.peakValue));
  const basinPeaks = basinEvents.map((p) => Math.abs(p.peakValue));

  return [
    {
      metric: "Total de eventos (Niño + Niña)",
      coastal: coastalEvents.length,
      basin: basinEvents.length,
      note: "Número de periodos activos reconstruidos sobre la historia.",
    },
    {
      metric: "Eventos El Niño",
      coastal: coastalNino.length,
      basin: basinNino.length,
      note: "Periodos cálidos por escala.",
    },
    {
      metric: "Eventos La Niña",
      coastal: coastalNina.length,
      basin: basinNina.length,
      note: "Periodos fríos por escala.",
    },
    {
      metric: "Duración media (meses)",
      coastal: coastalDurations.length ? (coastalDurations.reduce((a, b) => a + b, 0) / coastalDurations.length).toFixed(1) : "—",
      basin: basinDurations.length ? (basinDurations.reduce((a, b) => a + b, 0) / basinDurations.length).toFixed(1) : "—",
      note: "Duración típica de los periodos activos.",
    },
    {
      metric: "Intensidad pico media (°C)",
      coastal: coastalPeaks.length ? (coastalPeaks.reduce((a, b) => a + b, 0) / coastalPeaks.length).toFixed(2) : "—",
      basin: basinPeaks.length ? (basinPeaks.reduce((a, b) => a + b, 0) / basinPeaks.length).toFixed(2) : "—",
      note: "Valor absoluto pico medio de los eventos.",
    },
    {
      metric: "Intensidad pico máxima (°C)",
      coastal: coastalPeaks.length ? Math.max(...coastalPeaks).toFixed(2) : "—",
      basin: basinPeaks.length ? Math.max(...basinPeaks).toFixed(2) : "—",
      note: "Evento más intenso registrado en cada escala.",
    },
    {
      metric: "Umbral de activación",
      coastal: "±0.4 °C (ICEN)",
      basin: "±0.5 °C (Niño 3.4)",
      note: "Umbral operacional derivado del observatorio.",
    },
    {
      metric: "Persistencia requerida",
      coastal: "3 meses consecutivos",
      basin: "3 meses consecutivos",
      note: "Condición de activación derivada.",
    },
    {
      metric: "Índice actual",
      coastal: `ICEN ${all.icen.points[all.icen.points.length - 1].value ?? "—"} °C`,
      basin: `RONI ${all.roni.points[all.roni.points.length - 1].value ?? "—"} °C`,
      note: "Valor más reciente disponible.",
    },
    {
      metric: "Estado oficial actual",
      coastal: "Alerta de El Niño Costero",
      basin: "El Niño Advisory",
      note: "Cita textual de ENFEN y NOAA/CPC.",
    },
  ];
}

// ============================================================================
// Caja de bigotes: distribución de valores por categoría de evento.
// ----------------------------------------------------------------------------
// Para cada indicador, agrupa los valores mensuales por categoría de evento
// (El Niño / Neutral / La Niña) y calcula los estadísticos de caja: mediana,
// cuartiles Q1/Q3, bigotes (1.5×RIC), atípicos. Es cálculo determinista.
// ============================================================================

export interface BoxStats {
  category: string;
  q1: number;
  median: number;
  q3: number;
  whiskerMin: number;
  whiskerMax: number;
  min: number;
  max: number;
  count: number;
  outliers: number[];
}

export interface BoxPlotResult {
  indicatorId: string;
  label: string;
  units: string;
  boxes: BoxStats[];
}

export function buildBoxPlot(indicatorId: string): BoxPlotResult | null {
  const all = generateAllSeries();
  const s = all[indicatorId];
  if (!s) return null;
  const groups: Record<string, number[]> = { "El Niño": [], "Neutral": [], "La Niña": [] };
  // Usar Niño 3.4 como referencia de fase para todos los indicadores
  const n34 = all.nino34.points;
  for (let i = 0; i < s.points.length; i++) {
    const v = s.points[i].value;
    const phase = n34[i]?.value;
    if (v === null || phase === null || phase === undefined) continue;
    const cat = phase >= 0.5 ? "El Niño" : phase <= -0.5 ? "La Niña" : "Neutral";
    groups[cat].push(v);
  }
  const boxes: BoxStats[] = [];
  for (const cat of ["El Niño", "Neutral", "La Niña"]) {
    const vals = groups[cat].sort((a, b) => a - b);
    if (vals.length === 0) {
      boxes.push({ category: cat, q1: 0, median: 0, q3: 0, whiskerMin: 0, whiskerMax: 0, min: 0, max: 0, count: 0, outliers: [] });
      continue;
    }
    const q = (p: number) => {
      const idx = (vals.length - 1) * p;
      const lo = Math.floor(idx), hi = Math.ceil(idx);
      return lo === hi ? vals[lo] : vals[lo] * (hi - idx) + vals[hi] * (idx - lo);
    };
    const q1 = q(0.25), median = q(0.5), q3 = q(0.75);
    const iqr = q3 - q1;
    const whiskerMin = Math.max(vals[0], q1 - 1.5 * iqr);
    const whiskerMax = Math.min(vals[vals.length - 1], q3 + 1.5 * iqr);
    const outliers = vals.filter((v) => v < whiskerMin || v > whiskerMax);
    boxes.push({
      category: cat,
      q1: Math.round(q1 * 100) / 100,
      median: Math.round(median * 100) / 100,
      q3: Math.round(q3 * 100) / 100,
      whiskerMin: Math.round(whiskerMin * 100) / 100,
      whiskerMax: Math.round(whiskerMax * 100) / 100,
      min: Math.round(vals[0] * 100) / 100,
      max: Math.round(vals[vals.length - 1] * 100) / 100,
      count: vals.length,
      outliers: outliers.slice(0, 20).map((v) => Math.round(v * 100) / 100),
    });
  }
  return { indicatorId, label: s.label, units: s.units, boxes };
}

// ============================================================================
// Correlación móvil: matriz de correlación en ventanas temporales.
// ----------------------------------------------------------------------------
// Calcula la correlación de Pearson entre pares de indicadores en ventanas
// móviles, mostrando cómo evoluciona la coherencia del sistema ENSO.
// ============================================================================

export interface RollingCorrelationPoint {
  month: string;
  correlations: { pair: string; value: number }[];
}

export function buildRollingCorrelations(windowMonths = 36): RollingCorrelationPoint[] {
  const all = generateAllSeries();
  const ids = Object.keys(all);
  const pairs: [string, string][] = [];
  for (let i = 0; i < ids.length; i++) {
    for (let j = i + 1; j < ids.length; j++) {
      pairs.push([ids[i], ids[j]]);
    }
  }
  const result: RollingCorrelationPoint[] = [];
  for (let i = windowMonths - 1; i < all[ids[0]].points.length; i++) {
    const month = all[ids[0]].points[i].month;
    const correlations: { pair: string; value: number }[] = [];
    for (const [a, b] of pairs) {
      const xs: number[] = [], ys: number[] = [];
      for (let k = i - windowMonths + 1; k <= i; k++) {
        const va = all[a].points[k].value, vb = all[b].points[k].value;
        if (va !== null && vb !== null) { xs.push(va); ys.push(vb); }
      }
      if (xs.length < windowMonths / 2) { correlations.push({ pair: `${a}-${b}`, value: 0 }); continue; }
      correlations.push({ pair: `${a}-${b}`, value: Math.round(pearson(xs, ys) * 100) / 100 });
    }
    result.push({ month, correlations });
  }
  return result;
}

export { AS_OF_DATE, AS_OF_MONTH, generateAllSeries, getSeries, latest };
