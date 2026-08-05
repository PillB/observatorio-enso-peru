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

export { AS_OF_DATE, AS_OF_MONTH, generateAllSeries, getSeries, latest };
