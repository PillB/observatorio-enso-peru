// Memoria de desastres: modelo de datos (sin DOM), compartido por la vista y las pruebas (node --test).
//
// Los indicadores son los mismos que calcula python/enso/historico/indicadores.py para los CSV del
// equipo de prevención; las pruebas comparan ambos sobre el catálogo publicado. Aquí se recalculan para
// los filtros que elige cada persona (peligro, evento, periodo).

export const Z = 1.959964;
export const LEVELS = { departamento: 2, provincia: 4, distrito: 6 };

/** eventos.json → registros con campos cortos. */
export function decode(ev) {
  const D = ev.dict;
  return ev.rows.map((r) => {
    const [d, t, u, e, f, o, c, muertos, afect, viv, i] = r;
    // La fecha trae solo lo que se sabe: «1998-03-12», «1998-03» (mes) o «1998» (año).
    const y = +d.slice(0, 4), m = d.length >= 7 ? +d.slice(5, 7) : 0;
    return { d, y, m, hy: m ? (m >= 7 ? y : y - 1) : null, t: D.DangerType[t], u, e: D.TipoEvento[e], f: D.FaseENSO[f], o: D.Origen[o], c: D.Confianza[c], muertos, afect, viv, i };
  });
}

/** Código del área de un registro en un nivel, o null si el registro es más grueso que ese nivel. */
export function areaOf(u, level) {
  if (level === 'region') return null;
  const n = LEVELS[level];
  return u.length >= n ? u.slice(0, n) : null;
}

export function wilson(y, t) {
  if (!t) return [null, null];
  const p = y / t, den = 1 + (Z * Z) / t;
  const centre = (p + (Z * Z) / (2 * t)) / den;
  const half = (Z * Math.sqrt((p * (1 - p)) / t + (Z * Z) / (4 * t * t))) / den;
  return [round(Math.max(0, centre - half), 4), round(Math.min(1, centre + half), 4)];
}

/** Razón de tasas con IC 95 % logarítmico; phi multiplica la varianza (sobredispersión, 1 = Poisson). */
export function rateRatio(a, t1, b, t0, phi = 1) {
  if (!(a && b && t1 && t0)) return [null, null, null];
  const rr = (a / t1) / (b / t0), se = Math.sqrt(phi * (1 / a + 1 / b));
  return [round(rr, 3), round(rr * Math.exp(-Z * se), 3), round(rr * Math.exp(Z * se), 3)];
}

/**
 * Factor de sobredispersión (cuasi-Poisson) de los conteos por año, con una media para los años con Niño y otra
 * para los demás: Pearson / grados de libertad, mínimo 1 (igual que indicadores.dispersion).
 */
export function dispersion(perYear, years, ninoYears) {
  const groups = [[], []];
  for (const y of years) groups[ninoYears.has(y) ? 0 : 1].push(perYear.get(y) || 0);
  let chi = 0, n = 0, k = 0;
  for (const v of groups) {
    if (!v.length) continue;
    n += v.length; k++;
    const mu = v.reduce((s, x) => s + x, 0) / v.length;
    if (mu > 0) chi += v.reduce((s, x) => s + (x - mu) ** 2, 0) / mu;
  }
  return n > k ? round(Math.max(1, chi / (n - k)), 4) : 1;
}

/** Intervalos del periodo de retorno y de la probabilidad en 5 años a partir del de Wilson. */
export const returnPeriodCI = (lo, hi) => [hi ? round(1 / hi, 1) : null, lo ? round(1 / lo, 1) : null];
export const prob5CI = (lo, hi) => [lo === null ? null : round(1 - (1 - lo) ** 5, 4), hi === null ? null : round(1 - (1 - hi) ** 5, 4)];

export const round = (v, n = 0) => { const k = 10 ** n; return Math.round(v * k) / k; };

/** Temporada (julio a junio, por su año de inicio) de un registro; si solo se sabe el año, ese año. */
export const seasonOf = (r) => (r.hy === null ? r.y : r.hy);

/**
 * Filtro de registros.
 * f.types: Set de DangerType (vacío = todos); f.event: '' | 'nino' | 'nina' | 'neutro' | 'grandes' | nombre de TipoEvento;
 * f.from / f.to: temporadas por su año de inicio (1997 = julio de 1997 a junio de 1998), las mismas con las que se
 * cuentan los años de cobertura: así un periodo nunca deja una temporada a medias; f.great: lista de grandes Niños.
 */
export function filter(recs, f) {
  const types = f.types && f.types.size ? f.types : null;
  return recs.filter((r) => {
    if (types && !types.has(r.t)) return false;
    if (f.from && seasonOf(r) < f.from) return false;
    if (f.to && seasonOf(r) > f.to) return false;
    if (!f.event) return true;
    if (f.event === 'nino') return r.f === 'El Niño costero' || /^(FEN|Niño Costero|Ciclón)/.test(r.e);
    if (f.event === 'nina') return r.f === 'La Niña costera';
    if (f.event === 'neutro') return r.f === 'Neutro' && !/^(FEN|Niño Costero|Ciclón)/.test(r.e);
    if (f.event === 'grandes') return (f.great || []).includes(r.e);
    return r.e === f.event;
  });
}

/** Temporadas (por su año de inicio) del periodo homogéneo dentro de [from, to]. */
export function coverageYears(hom, from, to) {
  const a = Math.max(hom[0], from || hom[0]), b = Math.min(hom[1], to || hom[1]);
  const out = [];
  for (let y = a; y <= b; y++) if (y >= hom[0] && y <= hom[1]) out.push(y);
  return out;
}

/**
 * Indicadores de un grupo de registros (misma definición que indicadores.summarize). La frecuencia, los
 * distrito-años y la razón de tasas usan solo los registros de la fuente homogénea (hom: Set de Origen;
 * null = todos); registros, impactos y grandes Niños usan todos.
 */
export function summarize(recs, years, ninoYears, great, hom = null) {
  const yr = new Set(years), T = years.length;
  const tn = years.filter((y) => ninoYears.has(y)).length, to = T - tn;
  const ys = new Set(), da = new Set(), perYear = new Map();
  let dn = 0;
  for (const r of recs) if (yr.has(r.hy) && (!hom || hom.has(r.o))) {
    ys.add(r.hy);
    const k = `${r.u}|${r.hy}`;
    if (!da.has(k)) { da.add(k); perYear.set(r.hy, (perYear.get(r.hy) || 0) + 1); if (ninoYears.has(r.hy)) dn++; }
  }
  const Y = ys.size, p = T ? Y / T : null;
  const [lo, hi] = wilson(Y, T);
  const phi = dispersion(perYear, years, ninoYears);
  const [rr, rrLo, rrHi] = rateRatio(dn, tn, da.size - dn, to, phi);
  const hit = great.filter((g) => recs.some((r) => r.e === g));
  let muertos = 0, afect = 0, viv = 0;
  const hz = new Map();
  let last = null;
  for (const r of recs) {
    muertos += r.muertos; afect += r.afect; viv += r.viv;
    hz.set(r.t, (hz.get(r.t) || 0) + 1);
    if (!last || r.d > last.d) last = r;
  }
  return {
    registros: recs.length, aniosConEvento: Y, aniosCobertura: T, frecuenciaAnual: p === null ? null : round(p, 4),
    frecuenciaIC: [lo, hi], periodoRetorno: Y ? round(T / Y, 1) : null, periodoRetornoIC: returnPeriodCI(lo, hi),
    prob5Anios: p === null ? null : round(1 - (1 - p) ** 5, 4), prob5AniosIC: prob5CI(lo, hi),
    distritoAnios: da.size, razonNino: rr, razonNinoIC: [rrLo, rrHi], dispersionNino: phi, grandesNinos: hit, muestraPequena: Y < 5,
    muertos, afectados: afect, viviendas: viv,
    peligros: [...hz.entries()].sort((a, b) => b[1] - a[1]), ultimo: last,
  };
}

/** Agrupa por área de un nivel y resume cada una. */
export function byArea(recs, level, years, ninoYears, great, hom = null) {
  const groups = new Map();
  for (const r of recs) {
    const c = areaOf(r.u, level);
    if (!c) continue;
    if (!groups.has(c)) groups.set(c, []);
    groups.get(c).push(r);
  }
  const out = new Map();
  for (const [c, rs] of groups) out.set(c, summarize(rs, years, ninoYears, great, hom));
  return out;
}

/** Registros por año hidrológico (para la línea de tiempo): {hy: {n, da, muertos}}. */
export function byYear(recs) {
  const out = new Map();
  for (const r of recs) {
    if (r.hy === null) continue;
    if (!out.has(r.hy)) out.set(r.hy, { n: 0, da: new Set(), muertos: 0 });
    const o = out.get(r.hy);
    o.n++; o.da.add(r.u); o.muertos += r.muertos;
  }
  return out;
}

/** Cortes por cuantiles (k clases) sobre los valores positivos; devuelve los límites superiores. */
export function quantileBreaks(values, k = 5) {
  const v = values.filter((x) => x > 0).sort((a, b) => a - b);
  if (!v.length) return [];
  const out = [];
  for (let i = 1; i < k; i++) out.push(v[Math.min(v.length - 1, Math.floor((i * v.length) / k))]);
  out.push(v[v.length - 1]);
  return [...new Set(out)];
}

export function classOf(v, breaks) {
  if (!(v > 0)) return -1;
  for (let i = 0; i < breaks.length; i++) if (v <= breaks[i]) return i;
  return breaks.length - 1;
}

/** Lugares golpeados en varios grandes Niños: [{code, hit:[...], n}] ordenados. */
export function repeatHotspots(recs, level, great) {
  const hit = new Map();
  for (const r of recs) {
    if (!great.includes(r.e)) continue;
    const c = areaOf(r.u, level);
    if (!c) continue;
    if (!hit.has(c)) hit.set(c, new Set());
    hit.get(c).add(r.e);
  }
  return [...hit.entries()].map(([code, s]) => ({ code, hit: great.filter((g) => s.has(g)), n: s.size }))
    .sort((a, b) => b.n - a.n || a.code.localeCompare(b.code));
}
