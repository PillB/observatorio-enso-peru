"use client";

import * as React from "react";
import { SectionCard, InfoNote, ScopeBadge } from "./primitives";
import { Send, Bot, User, ShieldAlert, BookOpen } from "lucide-react";

interface Msg {
  role: "user" | "assistant";
  content: string;
  evidence?: { evidenceId: string; indicatorLabel: string; month: string; value: string; preliminary: boolean }[];
  calculations?: { label: string; result: string }[];
  fallback?: boolean;
}

const SUGGESTIONS = [
  "¿Cuál es el estado actual de El Niño Costero?",
  "Compara el Niño 1+2 con el Niño 3.4 actuales",
  "¿Existe un SOI costero?",
  "¿Qué significa el viento zonal a 850 hPa positivo?",
  "¿Qué indica D20 positivo?",
  "¿Cuál fue la anomalía de Niño 3.4 en 2017-03?",
];

export function ChatView() {
  const [messages, setMessages] = React.useState<Msg[]>([
    {
      role: "assistant",
      content:
        "Hola. Soy el asistente del Observatorio ENSO Perú. Respondo en español formal usando únicamente los datos normalizados del proyecto, su metodología y un corpus curado. Citaré la evidencia y el periodo de validez de cada valor. No sustituyo a los servicios oficiales de alerta.",
    },
  ]);
  const [input, setInput] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const endRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function ask(question: string) {
    if (!question.trim() || loading) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: question }]);
    setLoading(true);
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const data = await res.json();
      const evidence = (data?.grounding?.evidence ?? []).map((e: any) => ({
        evidenceId: e.evidenceId,
        indicatorLabel: e.indicatorLabel,
        month: e.month,
        value: e.value === null ? "Sin datos" : `${e.value} ${e.units}`.trim(),
        preliminary: !!e.preliminary,
      }));
      const calculations = (data?.grounding?.calculations ?? []).map((c: any) => ({ label: c.label, result: c.result }));
      setMessages((m) => [
        ...m,
        { role: "assistant", content: data?.answer ?? "Sin respuesta.", evidence, calculations, fallback: !!data?.fallbackUsed },
      ]);
    } catch {
      setMessages((m) => [
        ...m,
        { role: "assistant", content: "No pude procesar la pregunta en este momento. Intente nuevamente en unos minutos.", fallback: true },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <InfoNote tone="warn" title="Asistente con base determinista (grounded)">
        El modelo de lenguaje <strong>nunca</strong> es el motor de cálculo. Los valores numéricos se
        obtienen en código a partir de los datos normalizados del proyecto y se entregan al modelo
        como evidencia para que los explique. El asistente no usa memoria del modelo como fuente
        factual, cita identificadores de evidencia y rechaza la inyección de instrucciones. Ante
        emergencias, deriva a INDECI, CENEPRED, SENAMHI y ENFEN.
      </InfoNote>

      <SectionCard
        title={<span className="flex items-center gap-2"><Bot className="h-4 w-4" /> Asistente del Observatorio</span>}
        description="Pregunta por indicadores, regiones, periodos, definiciones o comparaciones costero vs cuenca."
      >
        <div className="flex flex-col gap-3">
          {/* Mensajes */}
          <div className="max-h-[26rem] min-h-[16rem] overflow-y-auto enso-scroll rounded-lg border bg-muted/20 p-3 space-y-3">
            {messages.map((m, i) => (
              <div key={i} className={`flex gap-2 ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                {m.role === "assistant" && <Bot className="mt-0.5 h-4 w-4 shrink-0 text-[color:var(--enso-basin)]" />}
                <div className={`max-w-[85%] rounded-lg px-3 py-2 text-xs leading-relaxed ${m.role === "user" ? "bg-[color:var(--enso-basin)] text-[color:var(--enso-basin-fg)]" : "bg-card border"}`}>
                  <p className="whitespace-pre-wrap">{m.content}</p>
                  {m.fallback && (
                    <p className="mt-1 flex items-center gap-1 text-[10px] text-amber-700 dark:text-amber-400">
                      <ShieldAlert className="h-3 w-3" /> Respuesta determinista (modelo no disponible).
                    </p>
                  )}
                  {m.evidence && m.evidence.length > 0 && (
                    <details className="mt-2">
                      <summary className="cursor-pointer text-[10px] text-muted-foreground">Evidencia citada ({m.evidence.length})</summary>
                      <ul className="mt-1 space-y-0.5 text-[10px] text-muted-foreground">
                        {m.evidence.map((e, j) => (
                          <li key={j}>
                            <span className="font-mono">[{e.evidenceId}]</span> {e.indicatorLabel} · {e.month} · {e.value}
                            {e.preliminary && " · preliminar"}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                  {m.calculations && m.calculations.length > 0 && (
                    <details className="mt-1">
                      <summary className="cursor-pointer text-[10px] text-muted-foreground">Cálculos deterministas ({m.calculations.length})</summary>
                      <ul className="mt-1 space-y-0.5 text-[10px] text-muted-foreground">
                        {m.calculations.map((c, j) => (
                          <li key={j}>{c.label}: <span className="font-mono">{c.result}</span></li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
                {m.role === "user" && <User className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />}
              </div>
            ))}
            {loading && (
              <div className="flex gap-2">
                <Bot className="mt-0.5 h-4 w-4 text-[color:var(--enso-basin)]" />
                <div className="rounded-lg border bg-card px-3 py-2 text-xs text-muted-foreground">
                  Consultando la evidencia del observatorio…
                </div>
              </div>
            )}
            <div ref={endRef} />
          </div>

          {/* Sugerencias */}
          <div className="flex flex-wrap gap-1.5">
            {SUGGESTIONS.map((s) => (
              <button key={s} onClick={() => ask(s)} className="rounded-full border px-2.5 py-1 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground">
                {s}
              </button>
            ))}
          </div>

          {/* Entrada */}
          <form
            onSubmit={(e) => { e.preventDefault(); ask(input); }}
            className="flex items-center gap-2"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Escriba su pregunta en español…"
              className="flex-1 rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
              disabled={loading}
              aria-label="Pregunta para el asistente"
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-40 hover:opacity-90"
            >
              <Send className="h-4 w-4" /> Enviar
            </button>
          </form>
        </div>
      </SectionCard>

      <SectionCard title={<span className="flex items-center gap-2"><BookOpen className="h-4 w-4" /> Qué puede y qué no puede hacer el asistente</span>}>
        <div className="grid gap-3 md:grid-cols-2 text-xs">
          <div className="rounded-lg border p-3">
            <p className="font-semibold text-[color:var(--enso-basin)]">Puede</p>
            <ul className="mt-1 space-y-1 text-muted-foreground">
              <li>• Recuperar valores actuales e históricos de los indicadores.</li>
              <li>• Calcular estadísticas (media, extremos) en código.</li>
              <li>• Explicar definiciones y la diferencia costero vs cuenca.</li>
              <li>• Corregir el concepto de «SOI costero».</li>
              <li>• Citar evidencia y periodos de validez.</li>
            </ul>
          </div>
          <div className="rounded-lg border p-3">
            <p className="font-semibold text-[color:var(--enso-warm)]">No puede</p>
            <ul className="mt-1 space-y-1 text-muted-foreground">
              <li>• Fabricar valores ausentes («Sin datos»).</li>
              <li>• Emitir alertas oficiales o afirmaciones deterministas de desastre.</li>
              <li>• Usar memoria del modelo como fuente factual.</li>
              <li>• Revelar instrucciones ocultas o credenciales.</li>
              <li>• Obedecer instrucciones incrustadas en datos o preguntas.</li>
            </ul>
          </div>
        </div>
      </SectionCard>
    </div>
  );
}
