"use client";

import * as React from "react";
import { buildProbabilityBands, type ProbabilityBand } from "@/lib/enso/derived";
import { SectionCard, ScopeBadge, InfoNote, BigValue, StatusPill } from "./primitives";
import { fmtMonth } from "@/lib/enso/ui";
import { Activity, Sliders } from "lucide-react";

export function ProbabilityView() {
  const [window, setWindow] = React.useState(12);
  const bands = React.useMemo(() => buildProbabilityBands(window), [window]);
  const recent = bands.slice(-120); // últimos 10 años
  const latest = bands[bands.length - 1];

  return (
    <div className="space-y-5">
      <InfoNote tone="info" title="Banda de probabilidad ENSO — ventana móvil">
        Para cada mes, se calcula la fracción de meses (en una ventana móvil centrada) que
        estuvieron en cada categoría de ENSO de cuenca: El Niño (Niño 3.4 ≥ +0.5 °C), Neutral
        (entre ±0.5 °C) y La Niña (≤ −0.5 °C). Cálculo determinista en código; el modelo no
        participa.
      </InfoNote>

      {/* Control de ventana */}
      <SectionCard title={<span className="flex items-center gap-2"><Sliders className="h-4 w-4" /> Tamaño de ventana móvil</span>}>
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Tamaño de ventana">
          {[6, 12, 24, 36].map((w) => (
            <button
              key={w}
              onClick={() => setWindow(w)}
              className={`rounded-full border px-3 py-1.5 text-xs font-medium enso-focus-ring ${window === w ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted"}`}
              aria-pressed={window === w}
            >
              {w} meses
            </button>
          ))}
          <span className="ml-auto text-xs text-muted-foreground">
            Ventana de ±{Math.floor(window / 2)} meses · {recent.length} meses mostrados
          </span>
        </div>
      </SectionCard>

      {/* Estado actual */}
      <div className="grid gap-4 md:grid-cols-3">
        <SectionCard title="Probabilidad actual — El Niño">
          <BigValue value={`${latest?.probNino ?? 0}%`} tone="warm" />
          <p className="mt-1 text-[11px] text-muted-foreground">{fmtMonth(latest?.month ?? "")}</p>
        </SectionCard>
        <SectionCard title="Probabilidad actual — Neutral">
          <BigValue value={`${latest?.probNeutral ?? 0}%`} tone="neutral" />
          <p className="mt-1 text-[11px] text-muted-foreground">{fmtMonth(latest?.month ?? "")}</p>
        </SectionCard>
        <SectionCard title="Probabilidad actual — La Niña">
          <BigValue value={`${latest?.probNina ?? 0}%`} tone="cool" />
          <p className="mt-1 text-[11px] text-muted-foreground">{fmtMonth(latest?.month ?? "")}</p>
        </SectionCard>
      </div>

      {/* Gráfico de bandas apiladas */}
      <SectionCard
        title={<span className="flex items-center gap-2"><Activity className="h-4 w-4" /> Banda de probabilidad por categoría</span>}
        description={`Últimos 10 años. Ventana móvil de ${window} meses. Cálido (El Niño), gris (Neutral), frío (La Niña). Las probabilidades suman 100%.`}
      >
        <ProbabilityChart bands={recent} />
      </SectionCard>

      {/* Serie temporal del valor medio */}
      <SectionCard title="Valor medio de Niño 3.4 en la ventana móvil" description="Promedio de Niño 3.4 sobre la ventana móvil centrada en cada mes.">
        <MeanChart bands={recent} />
      </SectionCard>

      {/* Tabla de periodos destacados */}
      <SectionCard title="Periodos con alta probabilidad de El Niño (>80%)" description="Meses donde la ventana móvil mostró >80% de meses en categoría El Niño.">
        <div className="max-h-64 overflow-y-auto enso-scroll rounded-md border">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-muted/80 backdrop-blur">
              <tr className="text-left">
                <th className="px-2 py-1.5 font-medium">Mes</th>
                <th className="px-2 py-1.5 font-medium text-right">P(El Niño)</th>
                <th className="px-2 py-1.5 font-medium text-right">P(Neutral)</th>
                <th className="px-2 py-1.5 font-medium text-right">P(La Niña)</th>
                <th className="px-2 py-1.5 font-medium text-right">Niño 3.4 medio</th>
              </tr>
            </thead>
            <tbody>
              {bands.filter((b) => b.probNino > 80).slice(-20).map((b) => (
                <tr key={b.month} className="border-b last:border-0 hover:bg-muted/40">
                  <td className="px-2 py-1.5 font-medium enso-num">{fmtMonth(b.month)}</td>
                  <td className="px-2 py-1.5 text-right enso-num font-bold text-[color:var(--enso-warm)]">{b.probNino}%</td>
                  <td className="px-2 py-1.5 text-right enso-num text-muted-foreground">{b.probNeutral}%</td>
                  <td className="px-2 py-1.5 text-right enso-num text-[color:var(--enso-cool)]">{b.probNina}%</td>
                  <td className="px-2 py-1.5 text-right enso-num">{b.meanN34 !== null ? (b.meanN34 > 0 ? "+" : "") + b.meanN34.toFixed(2) : "—"}</td>
                </tr>
              ))}
              {bands.filter((b) => b.probNino > 80).length === 0 && (
                <tr><td colSpan={5} className="px-2 py-4 text-center text-muted-foreground">No hay periodos con más de 80% en la ventana actual.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </SectionCard>
    </div>
  );
}

/** Gráfico de bandas apiladas (SVG). */
function ProbabilityChart({ bands }: { bands: ProbabilityBand[] }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(640);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => { for (const x of e) setW(Math.max(320, x.contentRect.width)); });
    ro.observe(ref.current); return () => ro.disconnect();
  }, []);
  const h = 280;
  const padL = 36, padR = 12, padT = 12, padB = 28;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  const n = bands.length;
  const barW = plotW / n;
  const ticks = bands.filter((_, i) => i % Math.max(1, Math.floor(n / 8)) === 0);

  return (
    <div ref={ref} className="w-full">
      <svg width={w} height={h} role="img" aria-label="Banda de probabilidad ENSO por categoría">
        {/* bandas apiladas */}
        {bands.map((b, i) => {
          const x = padL + i * barW;
          const ninoH = (b.probNino / 100) * plotH;
          const neutralH = (b.probNeutral / 100) * plotH;
          const ninaH = (b.probNina / 100) * plotH;
          return (
            <g key={b.month}>
              <rect x={x} y={padT} width={Math.max(barW, 0.5)} height={ninoH} fill="var(--enso-warm)" fillOpacity={0.85} />
              <rect x={x} y={padT + ninoH} width={Math.max(barW, 0.5)} height={neutralH} fill="var(--muted-foreground)" fillOpacity={0.3} />
              <rect x={x} y={padT + ninoH + neutralH} width={Math.max(barW, 0.5)} height={ninaH} fill="var(--enso-cool)" fillOpacity={0.85} />
            </g>
          );
        })}
        {/* ejes */}
        <line x1={padL} y1={padT} x2={padL} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.3} />
        <line x1={padL} y1={padT + plotH} x2={padL + plotW} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.3} />
        {[0, 50, 100].map((p) => (
          <text key={p} x={padL - 6} y={padT + plotH - (p / 100) * plotH + 3} textAnchor="end" fontSize={9} fill="currentColor" fillOpacity={0.6}>{p}%</text>
        ))}
        {ticks.map((b) => {
          const i = bands.indexOf(b);
          return (
            <text key={b.month} x={padL + i * barW + barW / 2} y={h - 10} textAnchor="middle" fontSize={9} fill="currentColor" fillOpacity={0.6}>{fmtMonth(b.month).slice(0, 3)}</text>
          );
        })}
      </svg>
      <div className="mt-2 flex items-center gap-3 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1"><span className="h-3 w-3 rounded" style={{ background: "var(--enso-warm)" }} /> El Niño</span>
        <span className="flex items-center gap-1"><span className="h-3 w-3 rounded bg-[color:var(--muted-foreground)] opacity-30" /> Neutral</span>
        <span className="flex items-center gap-1"><span className="h-3 w-3 rounded" style={{ background: "var(--enso-cool)" }} /> La Niña</span>
      </div>
    </div>
  );
}

/** Gráfico del valor medio de Niño 3.4 en la ventana. */
function MeanChart({ bands }: { bands: ProbabilityBand[] }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(640);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => { for (const x of e) setW(Math.max(320, x.contentRect.width)); });
    ro.observe(ref.current); return () => ro.disconnect();
  }, []);
  const h = 200;
  const padL = 36, padR = 12, padT = 12, padB = 28;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  const n = bands.length;
  const vals = bands.map((b) => b.meanN34).filter((v): v is number => v !== null);
  if (vals.length === 0) return <div className="text-sm text-muted-foreground">Sin datos.</div>;
  const min = Math.min(...vals) - 0.3, max = Math.max(...vals) + 0.3;
  const sx = (i: number) => padL + (i / Math.max(1, n - 1)) * plotW;
  const sy = (v: number) => padT + ((max - v) / (max - min)) * plotH;
  const pts = bands.map((b, i) => b.meanN34 === null ? null : `${sx(i)},${sy(b.meanN34)}`).filter(Boolean).join(" ");
  const ticks = bands.filter((_, i) => i % Math.max(1, Math.floor(n / 8)) === 0);

  return (
    <div ref={ref} className="w-full">
      <svg width={w} height={h} role="img" aria-label="Valor medio de Niño 3.4 en la ventana móvil">
        <rect x={padL} y={sy(0.5)} width={plotW} height={sy(0) - sy(0.5)} fill="var(--enso-warm)" fillOpacity={0.08} />
        <rect x={padL} y={sy(-0.5)} width={plotW} height={sy(min) - sy(-0.5)} fill="var(--enso-cool)" fillOpacity={0.08} />
        <line x1={padL} y1={sy(0.5)} x2={padL + plotW} y2={sy(0.5)} stroke="var(--enso-warm)" strokeWidth={1} strokeDasharray="4 3" strokeOpacity={0.4} />
        <line x1={padL} y1={sy(0)} x2={padL + plotW} y2={sy(0)} stroke="currentColor" strokeOpacity={0.3} />
        <line x1={padL} y1={sy(-0.5)} x2={padL + plotW} y2={sy(-0.5)} stroke="var(--enso-cool)" strokeWidth={1} strokeDasharray="4 3" strokeOpacity={0.4} />
        <polyline points={pts} fill="none" stroke="var(--enso-basin)" strokeWidth={2} />
        <line x1={padL} y1={padT} x2={padL} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.3} />
        <line x1={padL} y1={padT + plotH} x2={padL + plotW} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.3} />
        {[max, 0.5, 0, -0.5, min].map((v, i) => (
          <text key={i} x={padL - 6} y={sy(v) + 3} textAnchor="end" fontSize={9} fill="currentColor" fillOpacity={0.6}>{v.toFixed(1)}</text>
        ))}
        {ticks.map((b) => {
          const i = bands.indexOf(b);
          return <text key={b.month} x={sx(i)} y={h - 10} textAnchor="middle" fontSize={9} fill="currentColor" fillOpacity={0.6}>{fmtMonth(b.month).slice(0, 3)}</text>;
        })}
      </svg>
    </div>
  );
}
