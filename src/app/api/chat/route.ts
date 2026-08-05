import { NextRequest, NextResponse } from "next/server";
import ZAI from "z-ai-web-dev-sdk";
import { buildGrounding } from "@/lib/enso/grounding";
import { SYSTEM_RULES } from "@/lib/enso/knowledge";
import { buildCurrentStatus } from "@/lib/enso/derived";

// Asistente conversacional del Observatorio ENSO Perú.
// Flujo: grounding determinista → síntesis de evidencia → explicación por LLM.
// El modelo NUNCA es el motor de cálculo: todos los valores provienen del
// objeto de evidencia calculado en código a partir de los datos normalizados.

export const runtime = "nodejs";

interface ChatMessage { role: "system" | "user" | "assistant"; content: string }

export async function POST(req: NextRequest) {
  try {
    const body = await req.json().catch(() => ({}));
    const question: string = String(body?.question ?? "").slice(0, 1200);
    if (!question.trim()) {
      return NextResponse.json(
        { error: "La pregunta no puede estar vacía." },
        { status: 400 }
      );
    }

    const grounding = buildGrounding(question);
    const status = buildCurrentStatus();

    const evidenceText = grounding.evidence
      .map((e) => {
        const val = e.value === null ? "Sin datos" : `${e.value} ${e.units}`.trim();
        return `- [${e.evidenceId}] ${e.indicatorLabel}: mes ${e.month}, valor ${val}.` +
          (e.derivedNote ? ` Nota: ${e.derivedNote}` : "") +
          ` Fuente: ${e.source}. Preliminar: ${e.preliminary ? "sí" : "no"}.`;
      })
      .join("\n");

    const calcText = grounding.calculations
      .map((c) => `- ${c.label}: ${c.result}`)
      .join("\n");

    const knowledgeText = grounding.knowledgeSnippets
      .map((k) => `- [${k.id}] ${k.text}`)
      .join("\n");

    const systemPrompt = [
      "Eres el asistente del Observatorio ENSO Perú. Respondes en español formal, comprensible internacionalmente y apto para Perú.",
      "REGLAS OBLIGATORIAS:",
      ...SYSTEM_RULES,
      "",
      `Fecha de corte del observatorio: ${grounding.asOf}.`,
      "Estado oficial actual:",
      `- Costero (ENFEN): ${status.coastal.alert} desde ${status.coastal.alertSince}. ICEN ${status.coastal.icen} °C (${status.coastal.icenWindow}), categoría derivada: ${status.coastal.icenCategory}.`,
      `- Cuenca (NOAA/CPC): ${status.basin.alert}. RONI ${status.basin.roni} °C (${status.basin.roniWindow}), categoría derivada: ${status.basin.roniCategory}.`,
      "",
      "EVIDENCIA (únicos valores numéricos autorizados):",
      evidenceText,
      "",
      "CÁLCULOS DETERMINISTAS (realizados en código, no por el modelo):",
      calcText || "- (sin cálculos adicionales)",
      "",
      "CONOCIMIENTO CURADO AUTORIZADO:",
      knowledgeText || "- (sin fragmentos adicionales)",
      "",
      "INSTRUCCIONES DE RESPUESTA:",
      "1. Responde la pregunta usando SOLO los valores de EVIDENCIA y CÁLCULOS.",
      "2. Cita los identificadores [EVID-...] y el mes/periodo de validez.",
      "3. Distingue observación de interpretación; marca las interpretaciones del observatorio.",
      "4. Si un valor no está en la evidencia, di «Sin datos» y no lo inventes.",
      "5. No uses conocimiento externo al corpus curado para afirmar valores.",
      "6. Si la pregunta menciona «SOI costero», corrige el concepto.",
      "7. Para emergencias, deriva a INDECI/CENEPRED/SENAMHI/ENFEN.",
    ].join("\n");

    const messages: ChatMessage[] = [
      { role: "system", content: systemPrompt },
      { role: "user", content: question },
    ];

    let answer = "";
    try {
      const zai = await ZAI.create();
      const completion = await zai.chat.completions.create({
        messages,
        thinking: { type: "disabled" },
      });
      answer = completion?.choices?.[0]?.message?.content ?? "";
    } catch {
      answer = deterministicFallback(question, grounding, status);
    }

    if (!answer.trim()) {
      answer = deterministicFallback(question, grounding, status);
    }

    return NextResponse.json({
      answer,
      grounding: {
        evidence: grounding.evidence,
        calculations: grounding.calculations,
        knowledgeSnippets: grounding.knowledgeSnippets,
        asOf: grounding.asOf,
      },
      modelUsed: "z-ai-web-dev-sdk (chat completions)",
      fallbackUsed: !answer || answer.startsWith("[Respuesta determinista"),
    });
  } catch (err) {
    return NextResponse.json(
      { error: "Error interno del asistente.", detail: String(err) },
      { status: 500 }
    );
  }
}

function deterministicFallback(
  _question: string,
  grounding: ReturnType<typeof buildGrounding>,
  status: ReturnType<typeof buildCurrentStatus>
): string {
  const lines: string[] = [];
  lines.push("[Respuesta determinista — el modelo de lenguaje no está disponible.]");
  lines.push("");
  lines.push(
    `Al corte ${grounding.asOf}, el estado oficial es: costero «${status.coastal.alert}» ` +
      `(ICEN ${status.coastal.icen} °C, ventana ${status.coastal.icenWindow}, ` +
      `categoría derivada: ${status.coastal.icenCategory}); cuenca «${status.basin.alert}» ` +
      `(RONI ${status.basin.roni} °C, ventana ${status.basin.roniWindow}, ` +
      `categoría derivada: ${status.basin.roniCategory}).`
  );
  if (grounding.evidence.length > 1) {
    lines.push("");
    lines.push("Evidencia relevante:");
    for (const e of grounding.evidence.slice(1)) {
      const val = e.value === null ? "Sin datos" : `${e.value} ${e.units}`.trim();
      lines.push(`- [${e.evidenceId}] ${e.indicatorLabel} (${e.month}): ${val}. Preliminar: ${e.preliminary ? "sí" : "no"}.`);
    }
  }
  lines.push("");
  lines.push(
    "Esta es una interpretación generada por el observatorio. Para alertas oficiales consulte ENFEN, SENAMHI, INDECI y CENEPRED."
  );
  return lines.join("\n");
}
