"use client";

import * as React from "react";
import { buildSeasonality, type SeasonalityResult } from "@/lib/enso/derived";
import { INDICATOR_BY_ID } from "@/lib/enso/methodology";
import { SectionCard, ScopeBadge, InfoNote, BigValue, FieldLine } from "./primitives";
import { fmtValue } from "@/lib/enso/ui";
import { Calendar, BarChart3, TrendingUp } from "lucide-react";

const INDICATOR_OPTIONS = ["nino12", "icen", "nino34", "roni", "soi", "u850", "d20"];

export function SeasonalityView() {
  const [indicatorId, setIndicatorId] = React.useState("nino34");
  const result = React.useMemo(() => buildSeasonality(indicatorId), [indicatorId]);
  if (!result) return null;

  const ind = INDICATOR_BY_ID[indicatorId];
  const latestClim = result.climatology.find((c) => c.month === result.latestMonth);

  return (
    <div className="space-y-5">
      <InfoNote tone="info" title="Estacionalidad — climatología mensual por indicador">
        Para cada mes calendario (enero a diciembre) se calcula el promedio y la dispersión sobre
        toda la historia disponible (1990–2026). Esto permite comparar el valor más reciente con su
        estacionalidad típica. Cálculo determinista en código; el modelo no participa.
      </InfoNote>

      {/* Selector de indicador */}
      <SectionCard title={<span className="flex items-center gap-2"><Calendar className="h-4 w-4" /> Seleccionar indicador</span>}>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Selector de indicador">
          {INDICATOR_OPTIONS.map((id) => (
            <button
              key={id}
              onClick={() => setIndicatorId(id)}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium enso-focus-ring ${indicatorId === id ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted"}`}
              aria-pressed={indicatorId === id}
            >
              <ScopeBadge scope={INDICATOR_BY_ID[id].scope} />
              {INDICATOR_BY_ID[id].shortName}
            </button>
          ))}
        </div>
      </SectionCard>

      {/* Resumen del mes actual vs climatología */}
      <div className="grid gap-4 md:grid-cols-3">
        <SectionCard title="Valor más reciente">
          <p className="text-[11px] text-muted-foreground">Mes {result.latestMonth} ({latestClim?.monthLabel})</p>
          <BigValue
            value={fmtValue(result.latestValue, result.units).replace(/ (°C|m\/s|m)$/, "")}
            units={result.units === "degC" ? "°C" : result.units === "m_per_s" ? "m/s" : result.units === "m" ? "m" : ""}
            tone={result.latestValue !== null && result.latestValue > 0 ? "warm" : result.latestValue !== null && result.latestValue < 0 ? "cool" : "neutral"}
          />
        </SectionCard>
        <SectionCard title="Climatología del mismo mes">
          {latestClim && (
            <>
              <p className="text-[11px] text-muted-foreground">{latestClim.monthLabel} (promedio histórico)</p>
              <BigValue value={fmtValue(latestClim.mean, result.units).replace(/ (°C|m\/s|m)$/, "")} units={result.units === "degC" ? "°C" : result.units === "m_per_s" ? "m/s" : result.units === "m" ? "m" : ""} tone="neutral" />
              <p className="mt-1 text-[11px] text-muted-foreground">±{latestClim.std.toFixed(2)} · min {latestClim.min} · max {latestClim.max}</p>
            </>
          )}
        </SectionCard>
        <SectionCard title="Anomalía respecto a la climatología">
          {latestClim && result.latestValue !== null && (
            <>
              <p className="text-[11px] text-muted-foreground">Diferencia del valor actual vs el promedio histórico de {latestClim.monthLabel}</p>
              <BigValue
                value={`${result.latestValue - latestClim.mean > 0 ? "+" : ""}${(result.latestValue - latestClim.mean).toFixed(2)}`}
                units={result.units === "degC" ? "°C" : result.units === "m_per_s" ? "m/s" : result.units === "m" ? "m" : ""}
                tone={result.latestValue - latestClim.mean > 0 ? "warm" : "cool"}
              />
              <p className="mt-1 text-[11px] text-muted-foreground">
                {(Math.abs(result.latestValue - latestClim.mean) > latestClim.std * 1.5) ? "Fuera del rango normal (>|1.5σ|)" : "Dentro del rango normal"}
              </p>
            </>
          )}
        </SectionCard>
      </div>

      {/* Gráfico de estacionalidad */}
      <SectionCard
        title={<span className="flex items-center gap-2"><BarChart3 className="h-4 w-4" /> Ciclo estacional — {result.label}</span>}
        description={`Promedio mensual (línea) ±1 desviación estándar (banda) sobre la historia completa. Mes actual resaltado. Unidades: ${result.units}.`}
      >
        <SeasonalityChart result={result} />
      </SectionCard>

      {/* Tabla de climatología */}
      <SectionCard title="Tabla de climatología mensual" description="Promedio, desviación estándar, mínimo y máximo por mes calendario.">
        <div className="overflow-x-auto enso-scroll">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="py-2 pr-3 font-medium">Mes</th>
                <th className="py-2 pr-3 font-medium text-right">Promedio</th>
                <th className="py-2 pr-3 font-medium text-right">Desv. estándar</th>
                <th className="py-2 pr-3 font-medium text-right">Mínimo</th>
                <th className="py-2 pr-3 font-medium text-right">Máximo</th>
                <th className="py-2 pr-3 font-medium text-right">N° años</th>
                <th className="py-2 font-medium">Mes actual</th>
              </tr>
            </thead>
            <tbody>
              {result.climatology.map((c) => {
                const isLatest = c.month === result.latestMonth;
                return (
                  <tr key={c.month} className={`border-b last:border-0 ${isLatest ? "bg-[color:var(--enso-basin)]/5" : "hover:bg-muted/40"}`}>
                    <td className="py-2 pr-3 font-medium">{c.monthLabel}</td>
                    <td className="py-2 pr-3 text-right enso-num">{c.mean > 0 ? "+" : ""}{c.mean.toFixed(2)}</td>
                    <td className="py-2 pr-3 text-right enso-num text-muted-foreground">±{c.std.toFixed(2)}</td>
                    <td className="py-2 pr-3 text-right enso-num">{c.min > 0 ? "+" : ""}{c.min.toFixed(2)}</td>
                    <td className="py-2 pr-3 text-right enso-num">{c.max > 0 ? "+" : ""}{c.max.toFixed(2)}</td>
                    <td className="py-2 pr-3 text-right enso-num text-muted-foreground">{c.count}</td>
                    <td className="py-2">
                      {isLatest && result.latestValue !== null ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-[color:var(--enso-basin)]/15 px-2 py-0.5 text-[11px] font-medium text-[color:var(--enso-basin)]">
                          <TrendingUp className="h-3 w-3" /> {result.latestValue > 0 ? "+" : ""}{result.latestValue.toFixed(2)}
                        </span>
                      ) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </SectionCard>

      <SectionCard title="Metadatos del indicador">
        <div className="grid gap-4 md:grid-cols-2 text-xs">
          <FieldLine label="Indicador">{ind.name}</FieldLine>
          <FieldLine label="Región">{ind.region}</FieldLine>
          <FieldLine label="Agregación">{ind.aggregation}</FieldLine>
          <FieldLine label="Climatología">{ind.climatology}</FieldLine>
        </div>
      </SectionCard>
    </div>
  );
}

/** Gráfico de estacionalidad (SVG) con banda de ±1σ y mes actual resaltado. */
function SeasonalityChart({ result }: { result: SeasonalityResult }) {
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
  const allVals = result.climatology.flatMap((c) => [c.mean - c.std, c.mean + c.std, c.min, c.max]);
  if (result.latestValue !== null) allVals.push(result.latestValue);
  const min = Math.min(...allVals) - 0.3;
  const max = Math.max(...allVals) + 0.3;
  const sx = (i: number) => padL + (i / 11) * plotW;
  const sy = (v: number) => padT + ((max - v) / (max - min)) * plotH;

  const meanPts = result.climatology.map((c, i) => `${sx(i)},${sy(c.mean)}`).join(" ");
  const upperBand = result.climatology.map((c, i) => `${sx(i)},${sy(c.mean + c.std)}`).join(" ");
  const lowerBand = result.climatology.map((c, i) => `${sx(i)},${sy(c.mean - c.std)}`).reverse().join(" ");

  return (
    <div ref={ref} className="w-full">
      <svg width={w} height={h} role="img" aria-label={`Ciclo estacional de ${result.label}`}>
        {/* banda ±1σ */}
        <polygon points={`${upperBand} ${lowerBand}`} fill="var(--enso-basin)" fillOpacity={0.12} stroke="none" />
        {/* línea cero si aplica */}
        {min < 0 && max > 0 && (
          <line x1={padL} y1={sy(0)} x2={padL + plotW} y2={sy(0)} stroke="currentColor" strokeOpacity={0.3} strokeDasharray="4 3" />
        )}
        {/* línea de promedio */}
        <polyline points={meanPts} fill="none" stroke="var(--enso-basin)" strokeWidth={2.5} />
        {/* puntos por mes */}
        {result.climatology.map((c, i) => (
          <circle key={i} cx={sx(i)} cy={sy(c.mean)} r={3} fill="var(--enso-basin)" />
        ))}
        {/* mes actual resaltado */}
        {result.latestValue !== null && (
          <g>
            <line
              x1={sx(result.latestMonth - 1)} y1={padT}
              x2={sx(result.latestMonth - 1)} y2={padT + plotH}
              stroke="var(--enso-warm)" strokeWidth={1.5} strokeDasharray="3 3" strokeOpacity={0.6}
            />
            <circle cx={sx(result.latestMonth - 1)} cy={sy(result.latestValue)} r={6} fill="var(--enso-warm)" stroke="var(--card)" strokeWidth={2} />
            <text x={sx(result.latestMonth - 1)} y={sy(result.latestValue) - 10} textAnchor="middle" fontSize={10} fill="var(--enso-warm)" fontWeight="bold">
              {result.latestValue > 0 ? "+" : ""}{result.latestValue.toFixed(2)}
            </text>
          </g>
        )}
        {/* ejes */}
        <line x1={padL} y1={padT} x2={padL} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.3} />
        <line x1={padL} y1={padT + plotH} x2={padL + plotW} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.3} />
        {result.climatology.map((c, i) => (
          <text key={c.month} x={sx(i)} y={h - 12} textAnchor="middle" fontSize={9} fill="currentColor" fillOpacity={0.7}>{c.monthLabel}</text>
        ))}
        {[max, (max + min) / 2, min].map((v, i) => (
          <text key={i} x={padL - 6} y={sy(v) + 3} textAnchor="end" fontSize={9} fill="currentColor" fillOpacity={0.6}>{v.toFixed(1)}</text>
        ))}
      </svg>
      <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1"><span className="h-0.5 w-4 bg-[color:var(--enso-basin)]" /> Promedio histórico</span>
        <span className="flex items-center gap-1"><span className="h-2.5 w-4 bg-[color:var(--enso-basin)] opacity-15" /> Banda ±1σ</span>
        <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-[color:var(--enso-warm)]" /> Mes actual ({result.latestValue !== null ? `${result.latestValue > 0 ? "+" : ""}${result.latestValue.toFixed(2)}` : "n/d"})</span>
      </div>
    </div>
  );
}
