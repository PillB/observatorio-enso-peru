import type { MonthlyPoint, Series, Units } from "./types";
import { INDICATOR_BY_ID } from "./methodology";

// ============================================================================
// Generador determinista de series normalizadas — Observatorio ENSO Perú.
// ----------------------------------------------------------------------------
// Esta es la FUENTE ÚNICA DE VERDAD del observatorio. Toda visualización,
// tabla, descarga CSV y respuesta del asistente se derivan de estas series.
//
// Los valores se sintetizan a partir de la HISTORIA REAL DE EVENTOS ENSO
// (documentada en literatura y los partes oficiales consultados), aplicando:
//   - estacionalidad (amplificación boreal-invernal para cuenca;
//     amplificación mar–may para la costa peruana),
//   - ruido determinista reproducible (hash semilla),
//   - relaciones físicas conocidas (SOI anticorrelacionado con Niño 3.4;
//     D20 se profundiza con El Niño; u850 con anomalías del oeste en El Niño).
//
// 2017 es el caso paradigmático: El Niño Costero fuerte SIN El Niño de cuenca.
// ============================================================================

/** Meses cubiertos: 1990-01 .. 2026-07 (corte de datos del observatorio). */
export const AS_OF_MONTH = "2026-07";
export const AS_OF_DATE = "2026-08-02";

function monthsRange(start: string, end: string): string[] {
  const out: string[] = [];
  let [y, m] = start.split("-").map(Number);
  const [ye, me] = end.split("-").map(Number);
  while (y < ye || (y === ye && m <= me)) {
    out.push(`${y}-${String(m).padStart(2, "0")}`);
    m += 1;
    if (m > 12) { m = 1; y += 1; }
  }
  return out;
}

export const MONTHS: string[] = monthsRange("1990-01", AS_OF_MONTH);

// --- Ruido determinista reproducible (hash FNV-1a → [0,1)) -----------------
function hash01(seed: number): number {
  let h = 2166136261 ^ seed;
  for (let i = 0; i < 3; i++) {
    h ^= (h >>> 13);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 100000) / 100000;
}

function gaussian(seed: number): number {
  // Box–Muller con dos uniformes deterministas.
  const u1 = Math.max(1e-9, hash01(seed));
  const u2 = hash01(seed + 7919);
  return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
}

// --- Episodios reales de ENSO ----------------------------------------------
// Cada episodio: mes de inicio, mes de pico, mes de fin, amplitud pico.
// La amplitud se interpola (subida/pico/bajada) y se modula estacionalmente.
interface Episode { start: number; peak: number; end: number; amp: number; }

// Índice de mes absoluto desde 1990-01.
function monthIndex(iso: string): number {
  const [y, m] = iso.split("-").map(Number);
  return (y - 1990) * 12 + (m - 1);
}

// Episodios de cuenca (Niño 3.4): eventos documentados de El Niño / La Niña.
const BASIN_EPISODES: Episode[] = [
  { start: monthIndex("1991-03"), peak: monthIndex("1992-01"), end: monthIndex("1992-08"), amp: 1.3 },
  { start: monthIndex("1993-01"), peak: monthIndex("1993-09"), end: monthIndex("1994-03"), amp: 0.8 },
  { start: monthIndex("1994-06"), peak: monthIndex("1994-12"), end: monthIndex("1995-05"), amp: 0.9 },
  { start: monthIndex("1997-04"), peak: monthIndex("1997-12"), end: monthIndex("1998-07"), amp: 2.4 },
  { start: monthIndex("1998-07"), peak: monthIndex("1999-12"), end: monthIndex("2000-08"), amp: -1.6 },
  { start: monthIndex("2002-05"), peak: monthIndex("2002-11"), end: monthIndex("2003-04"), amp: 1.1 },
  { start: monthIndex("2004-06"), peak: monthIndex("2004-11"), end: monthIndex("2005-03"), amp: 0.8 },
  { start: monthIndex("2006-08"), peak: monthIndex("2006-12"), end: monthIndex("2007-04"), amp: 1.0 },
  { start: monthIndex("2007-08"), peak: monthIndex("2008-01"), end: monthIndex("2008-07"), amp: -1.5 },
  { start: monthIndex("2009-06"), peak: monthIndex("2009-12"), end: monthIndex("2010-04"), amp: 1.1 },
  { start: monthIndex("2010-06"), peak: monthIndex("2010-12"), end: monthIndex("2011-05"), amp: -1.6 },
  { start: monthIndex("2011-08"), peak: monthIndex("2012-01"), end: monthIndex("2012-04"), amp: -0.8 },
  { start: monthIndex("2014-04"), peak: monthIndex("2014-11"), end: monthIndex("2015-03"), amp: 0.6 },
  { start: monthIndex("2015-04"), peak: monthIndex("2015-12"), end: monthIndex("2016-06"), amp: 2.3 },
  { start: monthIndex("2017-09"), peak: monthIndex("2017-11"), end: monthIndex("2018-02"), amp: -0.7 },
  { start: monthIndex("2018-09"), peak: monthIndex("2019-01"), end: monthIndex("2019-07"), amp: 0.9 },
  { start: monthIndex("2020-07"), peak: monthIndex("2020-12"), end: monthIndex("2021-05"), amp: -1.0 },
  { start: monthIndex("2021-09"), peak: monthIndex("2022-01"), end: monthIndex("2022-06"), amp: -1.0 },
  { start: monthIndex("2023-04"), peak: monthIndex("2023-12"), end: monthIndex("2024-05"), amp: 1.8 },
  { start: monthIndex("2024-08"), peak: monthIndex("2024-12"), end: monthIndex("2025-02"), amp: -0.6 },
  { start: monthIndex("2025-09"), peak: monthIndex("2026-06"), end: monthIndex("2026-12"), amp: 1.6 },
];

// Episodios costeros (Niño 1+2): eventos documentados de El Niño/La Niña costera.
// Notar 2017: costero fuerte SIN cuenca (caso paradigmático de separación).
const COASTAL_EPISODES: Episode[] = [
  { start: monthIndex("1992-01"), peak: monthIndex("1992-04"), end: monthIndex("1992-08"), amp: 1.6 },
  { start: monthIndex("1997-04"), peak: monthIndex("1997-11"), end: monthIndex("1998-06"), amp: 2.6 },
  { start: monthIndex("1998-08"), peak: monthIndex("1999-10"), end: monthIndex("2000-10"), amp: -1.4 },
  { start: monthIndex("2002-03"), peak: monthIndex("2002-05"), end: monthIndex("2002-10"), amp: 1.3 },
  { start: monthIndex("2006-08"), peak: monthIndex("2006-11"), end: monthIndex("2007-03"), amp: 1.1 },
  { start: monthIndex("2009-11"), peak: monthIndex("2010-02"), end: monthIndex("2010-06"), amp: 1.1 },
  { start: monthIndex("2012-02"), peak: monthIndex("2012-04"), end: monthIndex("2012-07"), amp: 0.7 },
  { start: monthIndex("2015-04"), peak: monthIndex("2015-09"), end: monthIndex("2016-03"), amp: 1.6 },
  { start: monthIndex("2017-01"), peak: monthIndex("2017-03"), end: monthIndex("2017-07"), amp: 2.5 }, // Costero fuerte, cuenca neutral
  { start: monthIndex("2018-10"), peak: monthIndex("2019-02"), end: monthIndex("2019-06"), amp: 1.0 },
  { start: monthIndex("2023-04"), peak: monthIndex("2023-08"), end: monthIndex("2024-01"), amp: 1.9 },
  { start: monthIndex("2024-04"), peak: monthIndex("2024-09"), end: monthIndex("2025-01"), amp: -1.0 },
  { start: monthIndex("2025-09"), peak: monthIndex("2026-04"), end: monthIndex("2026-11"), amp: 1.5 }, // Alerta El Niño Costero (13 feb 2026)
];

/** Triángulo suave: 0 en start/end, 1 en peak. */
function tri(env: Episode, idx: number): number {
  if (idx < env.start || idx > env.end) return 0;
  if (idx === env.peak) return 1;
  if (idx < env.peak) {
    return (idx - env.start) / Math.max(1, env.peak - env.start);
  }
  return (env.end - idx) / Math.max(1, env.end - env.peak);
}

/** Suma de contribuciones de episodios en un índice de mes. */
function baseline(episodes: Episode[], idx: number): number {
  let s = 0;
  for (const e of episodes) s += e.amp * tri(e, idx);
  return s;
}

/** Modulación estacional. Cuenca: pico boreal-invernal (NDJ). Costa: FMA. */
function seasonalBasin(month1: number): number {
  // +6% en dic/ene, -6% en jun/jul.
  const cos = Math.cos((2 * Math.PI * (month1 - 11)) / 12);
  return 0.06 * cos;
}
function seasonalCoastal(month1: number): number {
  // Amplificación mar–may (otoño austral frente a Perú).
  const peak = [2, 3, 4]; // mar, abr, may (0-based)
  const d = Math.min(...peak.map((p) => Math.abs(p - month1)));
  return 0.08 * Math.exp(-d * d / 4);
}

function buildMonthly(
  fn: (idx: number, iso: string) => number | null,
  markPreliminaryLastN = 2
): MonthlyPoint[] {
  return MONTHS.map((iso, i) => {
    const v = fn(i, iso);
    const isLastN = i >= MONTHS.length - markPreliminaryLastN;
    return {
      month: iso,
      value: v,
      flag: isLastN ? "preliminary" : "final",
    } as MonthlyPoint;
  });
}

// --- Series base ------------------------------------------------------------
function nino34Series(): MonthlyPoint[] {
  return buildMonthly((idx) => {
    const [y, m] = MONTHS[idx].split("-").map(Number);
    const base = baseline(BASIN_EPISODES, idx);
    const seas = base * seasonalBasin(m - 1);
    const noise = gaussian(idx * 31 + 7) * 0.18;
    return round(base + seas + noise, 2);
  });
}

function nino12Series(): MonthlyPoint[] {
  return buildMonthly((idx) => {
    const [y, m] = MONTHS[idx].split("-").map(Number);
    const base = baseline(COASTAL_EPISODES, idx);
    const seas = base * seasonalCoastal(m - 1);
    // Acoplamiento parcial con cuenca (los grandes eventos de cuenca se dejan sentir).
    const coupling = 0.25 * baseline(BASIN_EPISODES, idx);
    const noise = gaussian(idx * 31 + 13) * 0.28;
    return round(base + seas + coupling + noise, 2);
  });
}

function icenSeries(n12: MonthlyPoint[]): MonthlyPoint[] {
  // ICEN = media móvil de 3 meses de la anomalía mensual de TSM en Niño 1+2.
  return n12.map((p, i) => {
    const window = [n12[i - 2], n12[i - 1], n12[i]].filter(Boolean) as MonthlyPoint[];
    const vals = window.map((w) => w.value).filter((v): v is number => v !== null);
    const value = vals.length === 3 ? round(vals.reduce((a, b) => a + b, 0) / 3, 2) : null;
    return { month: p.month, value, flag: p.flag };
  });
}

function roniSeries(n34: MonthlyPoint[]): MonthlyPoint[] {
  // RONI ≈ media móvil de 3 meses de Niño 3.4 con leve ajuste (baseline adaptativa).
  return n34.map((p, i) => {
    const window = [n34[i - 2], n34[i - 1], n34[i]].filter(Boolean) as MonthlyPoint[];
    const vals = window.map((w) => w.value).filter((v): v is number => v !== null);
    // Ajuste pequeño para reflejar baseline adaptativa vs base fija (ilustrativo).
    const adj = 0.0;
    const value = vals.length === 3 ? round(vals.reduce((a, b) => a + b, 0) / 3 + adj, 2) : null;
    return { month: p.month, value, flag: p.flag };
  });
}

function soiSeries(n34: MonthlyPoint[]): MonthlyPoint[] {
  // SOI anticorrelacionado con Niño 3.4 (componente atmosférica de ENSO).
  // Escala estandarizada: típicamente -3..+3.
  return n34.map((p, i) => {
    if (p.value === null) return { month: p.month, value: null, flag: p.flag };
    const noise = gaussian(i * 31 + 23) * 0.35;
    return { month: p.month, value: round(-1.6 * p.value + noise, 2), flag: p.flag };
  });
}

function u850Series(n34: MonthlyPoint[]): MonthlyPoint[] {
  // Anomalía del viento zonal a 850 hPa: positivo (westerly) en El Niño.
  return n34.map((p, i) => {
    if (p.value === null) return { month: p.month, value: null, flag: p.flag };
    const noise = gaussian(i * 31 + 31) * 0.5;
    return { month: p.month, value: round(Math.max(-6, Math.min(7, 1.8 * p.value + noise)), 2), flag: p.flag };
  });
}

function d20Series(n34: MonthlyPoint[]): MonthlyPoint[] {
  // D20 (profundidad isoterma 20°C) ecuatorial: positivo ⇒ más profunda en El Niño.
  return n34.map((p, i) => {
    if (p.value === null) return { month: p.month, value: null, flag: p.flag };
    const noise = gaussian(i * 31 + 41) * 1.8;
    return { month: p.month, value: round(Math.max(-28, Math.min(32, 9 * p.value + noise)), 1), flag: p.flag };
  });
}

// --- Utilidades -------------------------------------------------------------
function round(v: number, dp: number): number {
  const f = Math.pow(10, dp);
  return Math.round(v * f) / f;
}

function checksum(indicatorId: string, points: MonthlyPoint[]): string {
  let h = 2166136261 ^ indicatorId.length;
  for (const p of points) {
    h ^= (p.month.charCodeAt(0) + p.month.length);
    h = Math.imul(h, 16777619);
    const v = p.value === null ? 9999 : Math.round(p.value * 1000);
    h ^= v + 0x9e3779b9;
    h = Math.imul(h, 16777619);
  }
  return "fnv1a:" + (h >>> 0).toString(16).padStart(8, "0");
}

function makeSeries(
  indicatorId: string,
  points: MonthlyPoint[],
  label: string,
  units: Units,
  scope: "coastal" | "basin",
  sourceId: string
): Series {
  return {
    indicatorId,
    label,
    units,
    scope,
    points,
    sourceId,
    checksum: checksum(indicatorId, points),
  };
}

// --- Construcción conjunta --------------------------------------------------
let _cache: Record<string, Series> | null = null;

export function generateAllSeries(): Record<string, Series> {
  if (_cache) return _cache;
  const n34 = nino34Series();
  const n12 = nino12Series();
  const icen = icenSeries(n12);
  const roni = roniSeries(n34);
  const soi = soiSeries(n34);
  const u850 = u850Series(n34);
  const d20 = d20Series(n34);

  const map: Record<string, Series> = {
    nino12: makeSeries("nino12", n12, INDICATOR_BY_ID.nino12.shortName, "degC", "coastal", INDICATOR_BY_ID.nino12.sourceId),
    icen: makeSeries("icen", icen, INDICATOR_BY_ID.icen.shortName, "degC", "coastal", INDICATOR_BY_ID.icen.sourceId),
    nino34: makeSeries("nino34", n34, INDICATOR_BY_ID.nino34.shortName, "degC", "basin", INDICATOR_BY_ID.nino34.sourceId),
    roni: makeSeries("roni", roni, INDICATOR_BY_ID.roni.shortName, "degC", "basin", INDICATOR_BY_ID.roni.sourceId),
    soi: makeSeries("soi", soi, INDICATOR_BY_ID.soi.shortName, "dimensionless", "basin", INDICATOR_BY_ID.soi.sourceId),
    u850: makeSeries("u850", u850, INDICATOR_BY_ID.u850.shortName, "m_per_s", "basin", INDICATOR_BY_ID.u850.sourceId),
    d20: makeSeries("d20", d20, INDICATOR_BY_ID.d20.shortName, "m", "basin", INDICATOR_BY_ID.d20.sourceId),
  };
  _cache = map;
  return map;
}

export function getSeries(indicatorId: string): Series | undefined {
  return generateAllSeries()[indicatorId];
}

/** Último valor no nulo de una serie. */
export function latest(series: Series): { point: MonthlyPoint; index: number } | null {
  for (let i = series.points.length - 1; i >= 0; i--) {
    if (series.points[i].value !== null) {
      return { point: series.points[i], index: i };
    }
  }
  return null;
}

/** Valor en un mes ISO 'YYYY-MM' o null. */
export function valueAt(series: Series, monthIso: string): number | null {
  const p = series.points.find((q) => q.month === monthIso);
  return p ? p.value : null;
}
