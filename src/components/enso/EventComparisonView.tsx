"use client";

import * as React from "react";
import { HISTORICAL_EVENTS, buildEventSeries, type EventSeries } from "@/lib/enso/derived";
import { SectionCard, ScopeBadge, InfoNote, StatusPill } from "./primitives";
import { fmtValue, COLOR_COASTAL, COLOR_BASIN } from "@/lib/enso/ui";
import { GitCompare, Plus, X } from "lucide-react";

const EVENT_COLORS = [
  "var(--enso-warm)", "var(--enso-cool)", "var(--enso-basin)",
  "var(--enso-coastal)", "#7c3aed", "#059669", "#dc2626",
];

export function EventComparisonView() {
  const [selectedIds, setSelectedIds] = React.useState<string[]>(["1997-98", "2015-16", "2017"]);
  const [metric, setMetric] = React.useState<"nino34" | "nino12" | "icen">("nino34");

  const events = React.useMemo(
    () => selectedIds.map((id) => buildEventSeries(id)).filter((e): e is EventSeries => e !== null),
    [selectedIds]
  );

  function toggleEvent(id: string) {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : prev.length < 5 ? [...prev, id] : prev
    );
  }

  return (
    <div className="space-y-5">
      <InfoNote tone="info" title="Comparador de eventos ENSO">
        Seleccione hasta 5 eventos históricos para comparar su evolución. Las series se alinean por
        el mes de pico (offset 0) y se muestran ±24 meses alrededor. Esto permite contrastar la
        intensidad y duración de diferentes eventos. Los valores provienen de las series
        normalizadas del observatorio.
      </InfoNote>

      {/* Selector de métrica */}
      <SectionCard title={<span className="flex items-center gap-2"><GitCompare className="h-4 w-4" /> Métrica a comparar</span>}>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Métrica a comparar">
          {([
            { id: "nino34", label: "Niño 3.4 (cuenca)", scope: "basin" },
            { id: "nino12", label: "Niño 1+2 (costero)", scope: "coastal" },
            { id: "icen", label: "ICEN (costero)", scope: "coastal" },
          ] as const).map((m) => (
            <button
              key={m.id}
              onClick={() => setMetric(m.id)}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium enso-focus-ring ${metric === m.id ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted"}`}
              aria-pressed={metric === m.id}
            >
              <ScopeBadge scope={m.scope} />
              {m.label}
            </button>
          ))}
        </div>
      </SectionCard>

      {/* Selector de eventos */}
      <SectionCard title="Eventos seleccionados" description={` ${selectedIds.length}/5 seleccionados. Click para añadir o quitar.`}>
        <div className="flex flex-wrap gap-1.5">
          {HISTORICAL_EVENTS.map((e, i) => {
            const selected = selectedIds.includes(e.id);
            const color = EVENT_COLORS[selectedIds.indexOf(e.id) % EVENT_COLORS.length];
            return (
              <button
                key={e.id}
                onClick={() => toggleEvent(e.id)}
                className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium enso-focus-ring ${selected ? "text-primary-foreground" : "hover:bg-muted"}`}
                style={selected ? { background: color, borderColor: color } : {}}
                aria-pressed={selected}
              >
                {selected ? <X className="h-3 w-3" /> : <Plus className="h-3 w-3" />}
                {e.label}
              </button>
            );
          })}
        </div>
      </SectionCard>

      {/* Gráfico de comparación */}
      <SectionCard
        title={`Comparación alineada por pico — ${metric === "nino34" ? "Niño 3.4" : metric === "nino12" ? "Niño 1+2" : "ICEN"}`}
        description="Eje X: meses relativos al pico del evento (0 = pico). Eje Y: anomalía (°C). Cada línea es un evento."
      >
        <ComparisonChart events={events} metric={metric} />
      </SectionCard>

      {/* Tabla de eventos seleccionados */}
      <SectionCard title="Detalle de eventos seleccionados">
        <div className="overflow-x-auto enso-scroll">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="py-2 pr-3 font-medium">Color</th>
                <th className="py-2 pr-3 font-medium">Evento</th>
                <th className="py-2 pr-3 font-medium">Tipo</th>
                <th className="py-2 pr-3 font-medium">Inicio</th>
                <th className="py-2 pr-3 font-medium">Pico</th>
                <th className="py-2 pr-3 font-medium text-right">Niño 3.4 pico</th>
                <th className="py-2 pr-3 font-medium text-right">Niño 1+2 pico</th>
                <th className="py-2 font-medium">Nota</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e, i) => {
                const ev = HISTORICAL_EVENTS.find((x) => x.id === e.eventId)!;
                const color = EVENT_COLORS[i % EVENT_COLORS.length];
                return (
                  <tr key={e.eventId} className="border-b last:border-0 hover:bg-muted/40">
                    <td className="py-2 pr-3"><span className="block h-3 w-3 rounded-full" style={{ background: color }} /></td>
                    <td className="py-2 pr-3 font-medium">{e.label}</td>
                    <td className="py-2 pr-3">
                      {ev.type === "coastal" ? <ScopeBadge scope="coastal" /> : ev.type === "basin" ? <ScopeBadge scope="basin" /> : <span className="text-[10px] font-medium uppercase">Mixto</span>}
                    </td>
                    <td className="py-2 pr-3 enso-num">{ev.startMonth}</td>
                    <td className="py-2 pr-3 enso-num font-medium">{ev.peakMonth}</td>
                    <td className="py-2 pr-3 text-right enso-num" style={{ color: ev.peakNino34 && ev.peakNino34 > 0 ? "var(--enso-warm)" : "var(--enso-cool)" }}>
                      {fmtValue(ev.peakNino34, "degC")}
                    </td>
                    <td className="py-2 pr-3 text-right enso-num" style={{ color: ev.peakNino12 && ev.peakNino12 > 0 ? "var(--enso-warm)" : "var(--enso-cool)" }}>
                      {fmtValue(ev.peakNino12, "degC")}
                    </td>
                    <td className="py-2 text-muted-foreground text-[11px]">{ev.note}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </SectionCard>

      <InfoNote tone="muted" title="Interpretación de la comparación">
        <ul className="space-y-1 list-disc pl-4">
          <li><strong>1997–98 vs 2015–16</strong>: ambos El Niño de cuenca muy fuertes; 1997–98 con mayor expresión costera.</li>
          <li><strong>2017</strong>: El Niño Costero fuerte <strong>sin</strong> El Niño de cuenca — la curva de Niño 3.4 se mantiene cerca de 0 mientras Niño 1+2/ICEN se disparan.</li>
          <li><strong>2020–22</strong>: La Niña triple — valores negativos sostenidos en Niño 3.4 durante 3 años.</li>
          <li>La alineación por pico permite comparar la velocidad de desarrollo y declive de cada evento.</li>
        </ul>
      </InfoNote>
    </div>
  );
}

/** Gráfico de comparación de eventos alineados por pico (SVG). */
function ComparisonChart({ events, metric }: { events: EventSeries[]; metric: "nino34" | "nino12" | "icen" }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(640);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => { for (const x of e) setW(Math.max(320, x.contentRect.width)); });
    ro.observe(ref.current); return () => ro.disconnect();
  }, []);
  const h = 340;
  const padL = 44, padR = 16, padT = 12, padB = 36;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  const n = 49; // -24..+24
  const allVals = events.flatMap((e) => e[metric].filter((v): v is number => v !== null));
  if (allVals.length === 0) return <div ref={ref} className="text-sm text-muted-foreground">Seleccione al menos un evento.</div>;
  const min = Math.min(...allVals) - 0.3;
  const max = Math.max(...allVals) + 0.3;
  const sx = (i: number) => padL + (i / (n - 1)) * plotW;
  const sy = (v: number) => padT + ((max - v) / (max - min)) * plotH;

  return (
    <div ref={ref} className="w-full">
      <svg width={w} height={h} role="img" aria-label="Comparación de eventos alineados por pico">
        {/* bandas de umbral */}
        <rect x={padL} y={sy(0.5)} width={plotW} height={sy(0) - sy(0.5)} fill="var(--enso-warm)" fillOpacity={0.05} />
        <rect x={padL} y={sy(0)} width={plotW} height={sy(-0.5) - sy(0)} fill="var(--muted-foreground)" fillOpacity={0.03} />
        <rect x={padL} y={sy(-0.5)} width={plotW} height={sy(min) - sy(-0.5)} fill="var(--enso-cool)" fillOpacity={0.05} />
        {/* líneas de umbral */}
        <line x1={padL} y1={sy(0.5)} x2={padL + plotW} y2={sy(0.5)} stroke="var(--enso-warm)" strokeWidth={1} strokeDasharray="4 3" strokeOpacity={0.4} />
        <line x1={padL} y1={sy(0)} x2={padL + plotW} y2={sy(0)} stroke="currentColor" strokeOpacity={0.3} />
        <line x1={padL} y1={sy(-0.5)} x2={padL + plotW} y2={sy(-0.5)} stroke="var(--enso-cool)" strokeWidth={1} strokeDasharray="4 3" strokeOpacity={0.4} />
        {/* línea del pico (offset 0) */}
        <line x1={sx(24)} y1={padT} x2={sx(24)} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.2} strokeDasharray="2 4" />
        <text x={sx(24)} y={padT + 10} textAnchor="middle" fontSize={9} fill="currentColor" fillOpacity={0.5}>Pico</text>
        {/* trayectorias de eventos */}
        {events.map((e, i) => {
          const color = EVENT_COLORS[i % EVENT_COLORS.length];
          const pts = e[metric].map((v, j) => v === null ? null : `${sx(j)},${sy(v)}`).filter(Boolean).join(" ");
          return (
            <g key={e.eventId}>
              <polyline points={pts} fill="none" stroke={color} strokeWidth={2} />
              {/* etiqueta al final */}
              {e[metric][n - 1] !== null && (
                <text x={sx(n - 1) + 4} y={sy(e[metric][n - 1] as number) + 3} fontSize={9} fill={color} fontWeight="bold">{e.label.slice(0, 12)}</text>
              )}
            </g>
          );
        })}
        {/* ejes */}
        <line x1={padL} y1={padT} x2={padL} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.3} />
        <line x1={padL} y1={padT + plotH} x2={padL + plotW} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.3} />
        {/* etiquetas eje X (cada 6 meses) */}
        {[-24, -18, -12, -6, 0, 6, 12, 18, 24].map((offset) => {
          const i = offset + 24;
          return (
            <text key={offset} x={sx(i)} y={h - 20} textAnchor="middle" fontSize={9} fill="currentColor" fillOpacity={0.6}>
              {offset === 0 ? "Pico" : offset > 0 ? `+${offset}` : offset}
            </text>
          );
        })}
        <text x={padL + plotW / 2} y={h - 4} textAnchor="middle" fontSize={10} fill="currentColor" fillOpacity={0.6}>Meses relativos al pico</text>
        {/* etiquetas eje Y */}
        {[max, 0.5, 0, -0.5, min].map((v, i) => (
          <text key={i} x={padL - 6} y={sy(v) + 3} textAnchor="end" fontSize={9} fill="currentColor" fillOpacity={0.6}>{v.toFixed(1)}</text>
        ))}
      </svg>
      <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
        {events.map((e, i) => (
          <span key={e.eventId} className="flex items-center gap-1">
            <span className="h-0.5 w-4" style={{ background: EVENT_COLORS[i % EVENT_COLORS.length] }} />
            {e.label}
          </span>
        ))}
      </div>
    </div>
  );
}
