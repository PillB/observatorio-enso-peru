"use client";

import * as React from "react";
import { buildRollingCorrelations, type RollingCorrelationPoint } from "@/lib/enso/derived";
import { SectionCard, InfoNote } from "./primitives";
import { fmtMonth } from "@/lib/enso/ui";
import { Grid3x3, Activity } from "lucide-react";

const PAIR_LABELS: Record<string, string> = {
  "nino12-icen": "Niño 1+2 ↔ ICEN",
  "nino12-nino34": "Niño 1+2 ↔ Niño 3.4",
  "nino34-roni": "Niño 3.4 ↔ RONI",
  "nino34-soi": "Niño 3.4 ↔ SOI",
  "nino34-d20": "Niño 3.4 ↔ D20",
  "nino34-u850": "Niño 3.4 ↔ u850",
  "soi-u850": "SOI ↔ u850",
  "d20-u850": "D20 ↔ u850",
};

export function RollingCorrelationView() {
  const [windowMonths, setWindowMonths] = React.useState(36);
  const [selectedPairs, setSelectedPairs] = React.useState<string[]>(["nino34-soi", "nino34-d20", "nino34-u850"]);
  const data = React.useMemo(() => buildRollingCorrelations(windowMonths), [windowMonths]);
  const recent = data.slice(-120);

  function togglePair(pair: string) {
    setSelectedPairs((prev) =>
      prev.includes(pair) ? prev.filter((p) => p !== pair) : prev.length < 6 ? [...prev, pair] : prev
    );
  }

  return (
    <div className="space-y-5">
      <InfoNote tone="info" title="Correlación móvil — evolución temporal de la coherencia ENSO">
        Calcula la correlación de Pearson entre pares de indicadores en ventanas móviles, mostrando
        cómo evoluciona la coherencia del sistema acoplado océano-atmósfera. La anticorrelación
        SOI–Niño 3.4 y la correlación D20–Niño 3.4 son signatures físicas esperadas; su fortaleza
        varía con el tiempo. Cálculo determinista en código; el modelo no participa.
      </InfoNote>

      {/* Selector de ventana */}
      <SectionCard title="Ventana temporal">
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Ventana temporal">
          {[24, 36, 60, 120].map((w) => (
            <button
              key={w}
              onClick={() => setWindowMonths(w)}
              className={`rounded-full border px-3 py-1.5 text-xs font-medium enso-focus-ring ${windowMonths === w ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted"}`}
              aria-pressed={windowMonths === w}
            >
              {w} meses ({Math.floor(w / 12)} años)
            </button>
          ))}
          <span className="ml-auto text-xs text-muted-foreground">{recent.length} puntos · {selectedPairs.length}/6 pares</span>
        </div>
      </SectionCard>

      {/* Selector de pares */}
      <SectionCard title={<span className="flex items-center gap-2"><Grid3x3 className="h-4 w-4" /> Pares a visualizar</span>}>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(PAIR_LABELS).map(([key, label]) => {
            const selected = selectedPairs.includes(key);
            const color = PAIR_COLORS[selectedPairs.indexOf(key) % PAIR_COLORS.length];
            return (
              <button
                key={key}
                onClick={() => togglePair(key)}
                className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium enso-focus-ring ${selected ? "text-primary-foreground" : "hover:bg-muted"}`}
                style={selected ? { background: color, borderColor: color } : {}}
                aria-pressed={selected}
              >
                <span className="h-2 w-2 rounded-full" style={{ background: selected ? "var(--card)" : color }} />
                {label}
              </button>
            );
          })}
        </div>
      </SectionCard>

      {/* Gráfico de líneas de correlación */}
      <SectionCard
        title={<span className="flex items-center gap-2"><Activity className="h-4 w-4" /> Evolución de correlaciones móviles</span>}
        description={`Correlación de Pearson en ventana de ${windowMonths} meses. Rango [-1, 1]. Cálido = correlación positiva, frío = anticorrelación.`}
      >
        <RollingChart data={recent} pairs={selectedPairs} />
      </SectionCard>

      {/* Mapa de calor */}
      <SectionCard title="Mapa de calor de correlaciones" description="Correlación actual (última ventana) para los pares seleccionados.">
        <CurrentHeatmap data={recent} pairs={selectedPairs} />
      </SectionCard>

      <InfoNote tone="muted" title="Interpretación">
        <ul className="space-y-1 list-disc pl-4">
          <li><strong>Niño 3.4 ↔ SOI</strong>: anticorrelación esperada (componente atmosférica vs oceánica); se fortalece durante eventos acoplados.</li>
          <li><strong>Niño 3.4 ↔ D20</strong>: correlación positiva (termoclina se profundiza con El Niño); refleja el acoplamiento océano.</li>
          <li><strong>Niño 3.4 ↔ u850</strong>: correlación positiva (anomalías del oeste acompañan a El Niño); refleja el acoplamiento atmósfera.</li>
          <li>Variaciones en la fortaleza de la correlación indican periodos de mayor o menor coherencia del sistema ENSO.</li>
        </ul>
      </InfoNote>
    </div>
  );
}

const PAIR_COLORS = [
  "var(--enso-warm)", "var(--enso-cool)", "var(--enso-basin)",
  "var(--enso-coastal)", "#7c3aed", "#059669",
];

/** Gráfico de líneas de correlación móvil. */
function RollingChart({ data, pairs }: { data: RollingCorrelationPoint[]; pairs: string[] }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(640);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => { for (const x of e) setW(Math.max(320, x.contentRect.width)); });
    ro.observe(ref.current); return () => ro.disconnect();
  }, []);
  const h = 320;
  const padL = 36, padR = 16, padT = 12, padB = 28;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  const n = data.length;
  const sx = (i: number) => padL + (i / Math.max(1, n - 1)) * plotW;
  const sy = (v: number) => padT + ((1 - v) / 2) * plotH; // r en [-1,1]
  const ticks = data.filter((_, i) => i % Math.max(1, Math.floor(n / 8)) === 0);

  return (
    <div ref={ref} className="w-full">
      <svg width={w} height={h} role="img" aria-label="Evolución de correlaciones móviles">
        {/* bandas de umbral */}
        <rect x={padL} y={padT} width={plotW} height={sy(0) - padT} fill="var(--enso-warm)" fillOpacity={0.04} />
        <rect x={padL} y={sy(0)} width={plotW} height={padT + plotH - sy(0)} fill="var(--enso-cool)" fillOpacity={0.04} />
        {/* líneas de referencia */}
        {[1, 0.5, 0, -0.5, -1].map((v) => (
          <g key={v}>
            <line x1={padL} y1={sy(v)} x2={padL + plotW} y2={sy(v)} stroke="currentColor" strokeOpacity={v === 0 ? 0.4 : 0.15} strokeDasharray={v === 0 ? "none" : "4 3"} />
            <text x={padL - 6} y={sy(v) + 3} textAnchor="end" fontSize={9} fill="currentColor" fillOpacity={0.6}>{v.toFixed(1)}</text>
          </g>
        ))}
        {/* líneas por par */}
        {pairs.map((pair, pi) => {
          const color = PAIR_COLORS[pi % PAIR_COLORS.length];
          const pts = data.map((d, i) => {
            const c = d.correlations.find((c) => c.pair === pair);
            return c ? `${sx(i)},${sy(c.value)}` : null;
          }).filter(Boolean).join(" ");
          return <polyline key={pair} points={pts} fill="none" stroke={color} strokeWidth={2} />;
        })}
        {/* ejes */}
        <line x1={padL} y1={padT} x2={padL} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.3} />
        <line x1={padL} y1={padT + plotH} x2={padL + plotW} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.3} />
        {ticks.map((d) => {
          const i = data.indexOf(d);
          return <text key={d.month} x={sx(i)} y={h - 8} textAnchor="middle" fontSize={9} fill="currentColor" fillOpacity={0.6}>{fmtMonth(d.month).slice(0, 3)}</text>;
        })}
      </svg>
      <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
        {pairs.map((pair, pi) => (
          <span key={pair} className="flex items-center gap-1">
            <span className="h-0.5 w-4" style={{ background: PAIR_COLORS[pi % PAIR_COLORS.length] }} />
            {PAIR_LABELS[pair] ?? pair}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Mapa de calor de correlación actual. */
function CurrentHeatmap({ data, pairs }: { data: RollingCorrelationPoint[]; pairs: string[] }) {
  if (data.length === 0) return <div className="text-sm text-muted-foreground">Sin datos.</div>;
  const last = data[data.length - 1];
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">Mes: {fmtMonth(last.month)}</p>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {pairs.map((pair, pi) => {
          const c = last.correlations.find((c) => c.pair === pair);
          const v = c?.value ?? 0;
          const color = v > 0
            ? `color-mix(in oklch, var(--card) ${(1 - v) * 100}%, var(--enso-warm) ${v * 100}%)`
            : `color-mix(in oklch, var(--card) ${(1 - Math.abs(v)) * 100}%, var(--enso-cool) ${Math.abs(v) * 100}%)`;
          return (
            <div key={pair} className="rounded-lg border p-3" style={{ background: color }}>
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium">{PAIR_LABELS[pair] ?? pair}</span>
                <span className="text-lg font-bold enso-num">{v > 0 ? "+" : ""}{v.toFixed(2)}</span>
              </div>
              <div className="mt-1 h-1.5 w-full rounded-full bg-black/10 overflow-hidden">
                <div className="h-full rounded-full" style={{ width: `${Math.abs(v) * 100}%`, background: v > 0 ? "var(--enso-warm)" : "var(--enso-cool)" }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
