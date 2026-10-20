// Formato de números, fechas y periodos en español (Perú).

export const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'setiembre', 'octubre', 'noviembre', 'diciembre'];
export const MES_CORTO = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'set', 'oct', 'nov', 'dic'];
const SEASONS = ['DEF', 'EFM', 'FMA', 'MAM', 'AMJ', 'MJJ', 'JJA', 'JAS', 'ASO', 'SON', 'OND', 'NDE'];

const UNIT = { degC: '°C', m: 'm', m_per_s: 'm/s', 'm/s': 'm/s', dimensionless: '' };

export function unitLabel(units) { return UNIT[units] ?? units ?? ''; }

export function isNum(v) { return typeof v === 'number' && Number.isFinite(v); }

export function decimalsFor(units) { return units === 'm' ? 1 : units === 'dimensionless' ? 1 : 2; }

/** Valor con signo explícito y unidad: «+1,37 °C». */
export function fmtValue(v, units, { sign = true, unit = true, digits } = {}) {
  if (!isNum(v)) return 'N/D';
  const d = digits ?? decimalsFor(units);
  const n = Math.abs(v).toLocaleString('es-PE', { minimumFractionDigits: d, maximumFractionDigits: d });
  const s = v > 0 && sign ? '+' : v < 0 ? '−' : '';
  const u = unit && unitLabel(units) ? ` ${unitLabel(units)}` : '';
  return `${s}${n}${u}`;
}

export function fmtNumber(v, digits = 0) {
  return isNum(v) ? v.toLocaleString('es-PE', { maximumFractionDigits: digits }) : 'N/D';
}

/** «2026-06» → «junio 2026». */
export function fmtMonth(period, { short = false } = {}) {
  const m = /^(\d{4})-(\d{2})/.exec(period || '');
  if (!m) return '—';
  const i = Number(m[2]) - 1;
  return `${(short ? MES_CORTO : MESES)[i]} ${m[1]}`;
}

/** Trimestre centrado en el mes: «2026-06» → «MJJ 2026». */
export function fmtSeason(period) {
  const m = /^(\d{4})-(\d{2})/.exec(period || '');
  if (!m) return '—';
  return `${SEASONS[Number(m[2]) - 1]} ${m[1]}`;
}

export function parseDate(s) {
  if (!s) return null;
  const m = /^(\d{4})-(\d{2})(?:-(\d{2}))?/.exec(s);
  if (!m) { const d = new Date(s); return Number.isNaN(d.getTime()) ? null : d; }
  return new Date(Date.UTC(+m[1], +m[2] - 1, m[3] ? +m[3] : 15));
}

/** «2026-10-15» → «15 de octubre de 2026». */
export function fmtDate(s, { year = true } = {}) {
  const d = parseDate(s);
  if (!d) return '—';
  if (!/^\d{4}-\d{2}-\d{2}/.test(s) && /^\d{4}-\d{2}$/.test(s)) return fmtMonth(s);
  const txt = `${d.getUTCDate()} de ${MESES[d.getUTCMonth()]}`;
  return year ? `${txt} de ${d.getUTCFullYear()}` : txt;
}

export function fmtDateShort(s) {
  const d = parseDate(s);
  if (!d) return '—';
  return `${d.getUTCDate()} ${MES_CORTO[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

export function fmtDateTime(iso) {
  const d = iso ? new Date(iso) : null;
  if (!d || Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString('es-PE', { timeZone: 'America/Lima', dateStyle: 'long', timeStyle: 'short' }) + ' (hora de Lima)';
}

export function daysBetween(a, b = new Date()) {
  const da = a instanceof Date ? a : parseDate(a);
  if (!da) return null;
  return Math.floor((b.getTime() - da.getTime()) / 86400000);
}

export function relativeDays(n) {
  if (n === null || n === undefined) return '';
  if (n <= 0) return 'hoy';
  if (n === 1) return 'hace 1 día';
  if (n < 45) return `hace ${n} días`;
  const m = Math.round(n / 30.4);
  return m < 18 ? `hace ${m} meses` : `hace ${Math.round(n / 365)} años`;
}

export function monthIndex(period) {
  const m = /^(\d{4})-(\d{2})/.exec(period || '');
  return m ? Number(m[1]) * 12 + Number(m[2]) - 1 : NaN;
}
