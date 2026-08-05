import type { ChatEvidence, ChatGrounding } from "./types";
import { generateAllSeries, getSeries, latest, AS_OF_DATE, valueAt } from "./series";
import { INDICATOR_BY_ID } from "./methodology";
import { getSource } from "./sources";
import { KNOWLEDGE } from "./knowledge";
import {
  icenCategory,
  roniCategory,
  soiCategory,
  u850Direction,
  d20Interpretation,
  buildCurrentStatus,
} from "./derived";

// Motor de grounding determinista del asistente.
// 1. Detecta indicadores/región/periodo en la pregunta.
// 2. Consulta los datos normalizados del proyecto.
// 3. Calcula estadísticas en código.
// 4. Recupera fragmentos de conocimiento relevantes.
// 5. Construye un objeto de evidencia compacto.

const KEYWORDS: Record<string, string[]> = {
  nino12: ["niño 1+2", "nino 1+2", "1+2", "costero", "costa", "icen", "tsm costa", "tsm niño 1+2"],
  icen: ["icen", "índice costero", "indice costero"],
  nino34: ["niño 3.4", "nino 3.4", "3.4", "cuenca", "roni", "oni", "tsm cuenca", "tsm niño 3.4"],
  roni: ["roni", "índice oceánico relativo", "indice oceanico relativo"],
  soi: ["soi", "oscilación del sur", "oscilacion del sur", "tahiti", "darwin", "presión", "presion"],
  u850: ["viento", "850", "zonal", "alisio", "alisios", "westerly", "easterly", "del oeste", "del este"],
  d20: ["d20", "termoclina", "isoterma de 20", "isoterma 20", "subsuperficie", "subsuperficial"],
};

function detectIndicators(q: string): string[] {
  const lower = q.toLowerCase();
  const hits = new Set<string>();
  for (const [id, kws] of Object.entries(KEYWORDS)) {
    if (kws.some((k) => lower.includes(k))) hits.add(id);
  }
  // Si menciona "el niño" sin región, incluir cuenca y costero para comparar.
  if (lower.includes("el niño") || lower.includes("la niña")) {
    hits.add("nino34"); hits.add("icen");
  }
  if (lower.includes("compar") || lower.includes("diferencia") || lower.includes("versus") || lower.includes("vs")) {
    hits.add("nino34"); hits.add("icen");
  }
  return Array.from(hits);
}

function evidenceFor(indicatorId: string): ChatEvidence | null {
  const s = getSeries(indicatorId);
  const ind = INDICATOR_BY_ID[indicatorId];
  if (!s || !ind) return null;
  const lp = latest(s);
  if (!lp) return null;
  const src = getSource(ind.sourceId);
  return {
    evidenceId: `EVID-${indicatorId}`,
    indicatorId,
    indicatorLabel: ind.shortName,
    month: lp.point.month,
    value: lp.point.value,
    units: unitsLabel(ind.units),
    source: src ? `${src.institution} — ${src.product}` : ind.sourceId,
    sourceUrl: src ? src.url : "",
    retrievalDate: AS_OF_DATE,
    preliminary: lp.point.flag === "preliminary",
    derivedNote: derivedNote(indicatorId, lp.point.value),
  };
}

function derivedNote(indicatorId: string, value: number | null): string {
  switch (indicatorId) {
    case "icen": return value === null ? "" : `Categoría derivada: ${icenCategory(value)}. Interpretación generada por el observatorio.`;
    case "roni": return value === null ? "" : `Categoría derivada: ${roniCategory(value)}.`;
    case "soi": return value === null ? "" : `${soiCategory(value)}. Índice de cuenca; no existe «SOI costero».`;
    case "u850": return value === null ? "" : u850Direction(value).label;
    case "d20": return value === null ? "" : d20Interpretation(value);
    default: return "";
  }
}

function unitsLabel(u: string): string {
  switch (u) {
    case "degC": return "°C";
    case "m": return "m";
    case "m_per_s": return "m/s";
    default: return "(adimensional)";
  }
}

function detectMonth(q: string): string | null {
  // Busca un mes ISO YYYY-MM en la pregunta.
  const m = q.match(/\b(19\d{2}|20\d{2})-(0[1-9]|1[0-2])\b/);
  return m ? `${m[1]}-${m[2]}` : null;
}

function knowledgeFor(q: string): { id: string; text: string }[] {
  const lower = q.toLowerCase();
  const out: { id: string; text: string }[] = [];
  for (const k of KNOWLEDGE) {
    const words = k.topic.toLowerCase().split(/[\s/]+/);
    if (words.some((w) => lower.includes(w)) || lower.includes(k.topic.toLowerCase())) {
      out.push({ id: k.id, text: k.text });
    }
  }
  if (lower.includes("soi") && lower.includes("costero")) {
    const k = KNOWLEDGE.find((x) => x.id === "k-no-coastal-soi");
    if (k) out.push({ id: k.id, text: k.text });
  }
  if (lower.includes("emergencia") || lower.includes("alerta oficial") || lower.includes("peligro") || lower.includes("desastre")) {
    const k = KNOWLEDGE.find((x) => x.id === "k-disclaimer");
    if (k) out.push({ id: k.id, text: k.text });
  }
  // De-duplica.
  const seen = new Set<string>();
  return out.filter((x) => (seen.has(x.id) ? false : (seen.add(x.id), true)));
}

function calculationsFor(indicators: string[], month: string | null): { label: string; expression: string; result: string }[] {
  const out: { label: string; expression: string; result: string }[] = [];
  const all = generateAllSeries();
  for (const id of indicators) {
    const s = all[id];
    if (!s) continue;
    if (month) {
      const v = valueAt(s, month);
      out.push({
        label: `${INDICATOR_BY_ID[id]?.shortName ?? id} en ${month}`,
        expression: `valueAt(${id}, "${month}")`,
        result: v === null ? "Sin datos" : `${v} ${unitsLabel(INDICATOR_BY_ID[id].units)}`,
      });
    }
    // Media y extremos históricos.
    const vals = s.points.map((p) => p.value).filter((v): v is number => v !== null);
    if (vals.length) {
      const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
      const min = Math.min(...vals);
      const max = Math.max(...vals);
      out.push({
        label: `Estadísticas históricas de ${INDICATOR_BY_ID[id]?.shortName ?? id}`,
        expression: `mean/min/max(${id}, 1990-01..${AS_OF_DATE})`,
        result: `media ${mean.toFixed(2)} · mínimo ${min.toFixed(2)} · máximo ${max.toFixed(2)} ${unitsLabel(INDICATOR_BY_ID[id].units)}`,
      });
    }
  }
  return out;
}

export function buildGrounding(question: string): ChatGrounding {
  const indicators = detectIndicators(question);
  const month = detectMonth(question);
  const evidence: ChatEvidence[] = [];
  for (const id of (indicators.length ? indicators : ["icen", "nino34"])) {
    const e = evidenceFor(id);
    if (e) evidence.push(e);
  }
  const calcs = calculationsFor(indicators, month);
  const snippets = knowledgeFor(question);
  const status = buildCurrentStatus();
  // Incluye siempre resumen de estado actual para contexto.
  const statusEvidence: ChatEvidence = {
    evidenceId: "EVID-status",
    indicatorId: "status",
    indicatorLabel: "Estado consolidado",
    month: status.asOf,
    value: null,
    units: "",
    source: "Observatorio ENSO Perú (síntesis de fuentes oficiales)",
    sourceUrl: "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml",
    retrievalDate: status.asOf,
    preliminary: false,
    derivedNote: `Costero: ${status.coastal.alert} (ICEN ${status.coastal.icen} °C, ${status.coastal.icenCategory}); Cuenca: ${status.basin.alert} (RONI ${status.basin.roni} °C, ${status.basin.roniCategory}). Interpretación generada por el observatorio.`,
  };
  return {
    question,
    evidence: [statusEvidence, ...evidence],
    calculations: calcs,
    knowledgeSnippets: snippets,
    systemRules: [],
    asOf: status.asOf,
  };
}
