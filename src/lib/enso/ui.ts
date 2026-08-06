// Utilidades de interfaz y paleta del Observatorio ENSO Perú.

/** Etiquetas en español para los meses. */
export const MESES_ES = [
  "ene", "feb", "mar", "abr", "may", "jun",
  "jul", "ago", "sep", "oct", "nov", "dic",
];

/** Formatea un mes ISO 'YYYY-MM' como 'mar 2026'. */
export function fmtMonth(iso: string): string {
  const [y, m] = iso.split("-").map(Number);
  return `${MESES_ES[m - 1]} ${y}`;
}

/** Formatea un valor con unidades. */
export function fmtValue(v: number | null, units: string): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "Sin datos";
  const dp = units === "m" ? 1 : 2;
  const sign = v > 0 && (units === "degC" || units === "m" || units === "m_per_s") ? "+" : "";
  const u = units === "degC" ? "°C" : units === "m" ? "m" : units === "m_per_s" ? "m/s" : "";
  return `${sign}${v.toFixed(dp)}${u ? " " + u : ""}`;
}

/** Color divergente ciego al color (azul→blanco→naranja) centrado en 0. */
export function anomalyColor(v: number | null, scale: number): string {
  if (v === null || Number.isNaN(v)) return "var(--muted)";
  const t = Math.max(-1, Math.min(1, v / scale)); // -1..1
  if (t >= 0) {
    // blanco → naranja cálido
    const a = t;
    return `color-mix(in oklch, var(--card) ${(1 - a) * 100}%, var(--enso-warm) ${a * 100}%)`;
  }
  const a = -t;
  return `color-mix(in oklch, var(--card) ${(1 - a) * 100}%, var(--enso-cool) ${a * 100}%)`;
}

export const COLOR_COASTAL = "var(--enso-coastal)";
export const COLOR_BASIN = "var(--enso-basin)";
export const COLOR_WARM = "var(--enso-warm)";
export const COLOR_COOL = "var(--enso-cool)";

/** Convierte 'YYYY-MM' a epoch de mes (para ejes temporales). */
export function monthToMs(iso: string): number {
  const [y, m] = iso.split("-").map(Number);
  return new Date(y, m - 1, 1).getTime();
}

/** Devuelve los últimos N meses de una lista de meses ISO. */
export function lastN(months: string[], n: number): string[] {
  return months.slice(Math.max(0, months.length - n));
}
