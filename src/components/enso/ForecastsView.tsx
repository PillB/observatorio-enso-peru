"use client";

import * as React from "react";
import { generateForecasts, type ForecastSeason, MONTHS, generateAllSeries } from "@/lib/enso/series";
import { SectionCard, ScopeBadge, InfoNote, BigValue, StatusPill, FieldLine } from "./primitives";
import { EnsoTimeSeries } from "./charts";
import { fmtValue, COLOR_BASIN, COLOR_COASTAL, COLOR_WARM, COLOR_COOL } from "@/lib/enso/ui";
import { TrendingUp, AlertCircle, BarChart3 } from "lucide-react";

export function ForecastsView() {
  const forecasts = React.useMemo(() => generateForecasts(), []);
  const all = React.useMemo(() => generateAllSeries(), []);
  const first = forecasts[0];
  const peak = [...forecasts].sort((a, b) => b.probNino - a.probNino)[0];

  // Serie histórica reciente de Niño 3.4 + pronóstico central
  const histN34 = all.nino34.points.slice(-36).map((p) => ({ month: p.month, value: p.value }));
  const lastMonth = MONTHS[MONTHS.length - 1];

  return (
    <div className="space-y-5">
      <InfoNote tone="warn" title="Pronósticos — interpretación generada por el observatorio">
        Estos pronósticos son una <strong>síntesis determinista del observatorio</strong> coherente
        con el estado actual, con fines de divulgación. <strong>No sustituyen los pronósticos
        oficiales</strong> de IRI, NOAA/CPC o NMME. Para decisiones operativas, consulte las fuentes
        oficiales. Las probabilidades categorizadas (El Niño / Neutral / La Niña) siguen el umbral
        operacional de ±0.5 °C sobre Niño 3.4.
      </InfoNote>

      {/* Tarjetas resumen */}
      <div className="grid gap-4 md:grid-cols-3">
        <SectionCard title="Trimestre inicial" right={<ScopeBadge scope="basin" />}>
          <p className="text-[11px] text-muted-foreground">{first.label}</p>
          <BigValue value={fmtValue(first.forecastN34, "degC").replace(" °C", "")} units="°C" tone="warm" />
          <div className="mt-2 space-y-1 text-[11px]">
            <ProbBar label="El Niño" value={first.probNino} color="var(--enso-warm)" />
            <ProbBar label="Neutral" value={first.probNeutral} color="var(--muted-foreground)" />
            <ProbBar label="La Niña" value={first.probNina} color="var(--enso-cool)" />
          </div>
        </SectionCard>

        <SectionCard title="Mayor probabilidad de El Niño" right={<TrendingUp className="h-4 w-4 text-[color:var(--enso-warm)]" />}>
          <p className="text-[11px] text-muted-foreground">{peak.label}</p>
          <BigValue value={`${peak.probNino}%`} tone="warm" />
          <p className="mt-2 text-[11px] text-muted-foreground">
            Niño 3.4 central: {fmtValue(peak.forecastN34, "degC")}
          </p>
        </SectionCard>

        <SectionCard title="Estado actual (observado)" right={<ScopeBadge scope="basin" />}>
          <p className="text-[11px] text-muted-foreground">Mes de referencia: {lastMonth}</p>
          <BigValue value={fmtValue(all.nino34.points[all.nino34.points.length - 1].value, "degC").replace(" °C", "")} units="°C" tone="warm" />
          <StatusPill label="El Niño Advisory" tone="warm" />
        </SectionCard>
      </div>

      {/* Plume de trayectorias */}
      <SectionCard
        title={<span className="flex items-center gap-2"><BarChart3 className="h-4 w-4" /> Ensamble de trayectorias (Niño 3.4)</span>}
        description="Valores pronosticados por trimestre. Bandas de ±0.5 °C (El Niño/La Niña). Interpretación del observatorio."
      >
        <PlumeChart forecasts={forecasts} lastObserved={histN34[histN34.length - 1]?.value ?? null} lastObservedMonth={histN34[histN34.length - 1]?.month ?? lastMonth} />
      </SectionCard>

      {/* Tabla de probabilidades */}
      <SectionCard title="Probabilidades por trimestre (categorías de cuenca)" description="El Niño: ≥ +0.5 °C · Neutral: entre ±0.5 °C · La Niña: ≤ −0.5 °C. Suma 100%.">
        <div className="overflow-x-auto enso-scroll">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="py-2 pr-3 font-medium">Trimestre</th>
                <th className="py-2 pr-3 font-medium text-right">Niño 3.4 (°C)</th>
                <th className="py-2 pr-3 font-medium">El Niño</th>
                <th className="py-2 pr-3 font-medium">Neutral</th>
                <th className="py-2 pr-3 font-medium">La Niña</th>
                <th className="py-2 font-medium">Categoría dominante</th>
              </tr>
            </thead>
            <tbody>
              {forecasts.map((f) => {
                const dom = f.probNino >= f.probNeutral && f.probNino >= f.probNina ? "El Niño" : f.probNina > f.probNeutral ? "La Niña" : "Neutral";
                const tone = dom === "El Niño" ? "warm" : dom === "La Niña" ? "cool" : "neutral";
                return (
                  <tr key={f.label} className="border-b last:border-0 hover:bg-muted/40">
                    <td className="py-2 pr-3 font-medium enso-num">{f.label}</td>
                    <td className="py-2 pr-3 text-right enso-num">{fmtValue(f.forecastN34, "degC")}</td>
                    <td className="py-2 pr-3"><MiniProb value={f.probNino} color="var(--enso-warm)" /></td>
                    <td className="py-2 pr-3"><MiniProb value={f.probNeutral} color="var(--muted-foreground)" /></td>
                    <td className="py-2 pr-3"><MiniProb value={f.probNina} color="var(--enso-cool)" /></td>
                    <td className="py-2"><StatusPill label={dom} tone={tone} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </SectionCard>

      {/* Serie histórica + proyección */}
      <SectionCard title="Serie observada reciente (Niño 3.4)" description="Últimos 36 meses. El pronóstico continúa desde el último mes observado.">
        <EnsoTimeSeries
          series={[{ id: "nino34", label: "Niño 3.4 (observado)", color: COLOR_BASIN, data: all.nino34.points.slice(-36) }]}
          units="degC" yLabel="°C" height={240}
          thresholds={[
            { min: 0.5, max: 999, label: "El Niño", color: "var(--enso-warm)", fillOpacity: 0.08 },
            { min: -999, max: -0.5, label: "La Niña", color: "var(--enso-cool)", fillOpacity: 0.08 },
          ]}
        />
      </SectionCard>

      <InfoNote tone="muted" title="Metodología del pronóstico del observatorio">
        El pronóstico usa un decaimiento exponencial de la señal observada hacia el futuro, una
        modulación estacional y un ensamble de 9 trayectorias con incertidumbre creciente. Las
        probabilidades se derivan de una CDF normal sobre el umbral ±0.5 °C. Es una herramienta de
        divulgación; los pronósticos oficiales usan modelos acoplados (NMME, CFS) y consolidación
        estadística (IRI).
      </InfoNote>
    </div>
  );
}

function ProbBar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-16 text-muted-foreground">{label}</span>
      <div className="h-2 flex-1 rounded-full bg-muted overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${value}%`, background: color }} />
      </div>
      <span className="w-8 text-right enso-num font-medium">{value}%</span>
    </div>
  );
}

function MiniProb({ value, color }: { value: number; color: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <div className="h-1.5 w-16 rounded-full bg-muted overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${value}%`, background: color }} />
      </div>
      <span className="enso-num text-[11px]">{value}%</span>
    </div>
  );
}

/** Gráfico de pluma (ensamble) en SVG. */
function PlumeChart({ forecasts, lastObserved, lastObservedMonth }: { forecasts: ForecastSeason[]; lastObserved: number | null; lastObservedMonth: string }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(640);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => { for (const x of e) setW(Math.max(320, x.contentRect.width)); });
    ro.observe(ref.current); return () => ro.disconnect();
  }, []);
  const h = 280;
  const padL = 44, padR = 16, padT = 12, padB = 32;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  const n = forecasts.length;
  const allVals = forecasts.flatMap((f) => f.plume).concat(lastObserved ?? 0);
  const min = Math.min(...allVals) - 0.3, max = Math.max(...allVals) + 0.3;
  const sx = (i: number) => padL + (i / (n - 1)) * plotW;
  const sy = (v: number) => padT + ((max - v) / (max - min)) * plotH;

  return (
    <div ref={ref} className="w-full">
      <svg width={w} height={h} role="img" aria-label="Ensamble de pronósticos Niño 3.4">
        {/* bandas de umbral */}
        <rect x={padL} y={sy(0.5)} width={plotW} height={sy(0) - sy(0.5)} fill="var(--enso-warm)" fillOpacity={0.07} />
        <rect x={padL} y={sy(0)} width={plotW} height={sy(-0.5) - sy(0)} fill="var(--muted-foreground)" fillOpacity={0.05} />
        <rect x={padL} y={sy(-0.5)} width={plotW} height={sy(min) - sy(-0.5)} fill="var(--enso-cool)" fillOpacity={0.07} />
        {/* líneas de umbral */}
        <line x1={padL} y1={sy(0.5)} x2={padL + plotW} y2={sy(0.5)} stroke="var(--enso-warm)" strokeWidth={1} strokeDasharray="4 3" strokeOpacity={0.6} />
        <line x1={padL} y1={sy(0)} x2={padL + plotW} y2={sy(0)} stroke="currentColor" strokeOpacity={0.3} strokeWidth={1} />
        <line x1={padL} y1={sy(-0.5)} x2={padL + plotW} y2={sy(-0.5)} stroke="var(--enso-cool)" strokeWidth={1} strokeDasharray="4 3" strokeOpacity={0.6} />
        {/* trayectorias del ensamble */}
        {forecasts[0].plume.map((_, memberIdx) => {
          const pts = forecasts.map((f, i) => `${sx(i)},${sy(f.plume[memberIdx])}`).join(" ");
          return <polyline key={memberIdx} points={pts} fill="none" stroke="var(--enso-basin)" strokeWidth={1} strokeOpacity={0.25} />;
        })}
        {/* valor central */}
        <polyline
          points={forecasts.map((f, i) => `${sx(i)},${sy(f.forecastN34)}`).join(" ")}
          fill="none" stroke="var(--enso-basin)" strokeWidth={2.5}
        />
        {/* punto de partida observado */}
        {lastObserved !== null && (
          <circle cx={padL} cy={sy(lastObserved)} r={4} fill="var(--enso-coastal)" stroke="var(--card)" strokeWidth={1.5} />
        )}
        {/* ejes */}
        <line x1={padL} y1={padT} x2={padL} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.3} />
        <line x1={padL} y1={padT + plotH} x2={padL + plotW} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.3} />
        {[max, 0.5, 0, -0.5, min].map((v) => (
          <text key={v} x={padL - 6} y={sy(v) + 3} textAnchor="end" fontSize={9} fill="currentColor" fillOpacity={0.6}>{v.toFixed(1)}</text>
        ))}
        {forecasts.map((f, i) => i % 2 === 0 && (
          <text key={f.label} x={sx(i)} y={h - 12} textAnchor="middle" fontSize={9} fill="currentColor" fillOpacity={0.6}>{f.label}</text>
        ))}
        <text x={padL + plotW / 2} y={h - 1} textAnchor="middle" fontSize={10} fill="currentColor" fillOpacity={0.6}>Trimestre pronosticado</text>
      </svg>
      <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1"><span className="h-0.5 w-4 bg-[color:var(--enso-basin)]" /> Valor central</span>
        <span className="flex items-center gap-1"><span className="h-0.5 w-4 bg-[color:var(--enso-basin)] opacity-25" /> Ensamble (9 miembros)</span>
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-[color:var(--enso-coastal)]" /> Último observado ({lastObservedMonth})</span>
      </div>
    </div>
  );
}
