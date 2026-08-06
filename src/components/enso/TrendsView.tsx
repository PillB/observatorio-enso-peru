"use client";

import * as React from "react";
import { buildTrend, buildPhaseChanges, type TrendResult, type PhaseChange } from "@/lib/enso/derived";
import { INDICATOR_BY_ID } from "@/lib/enso/methodology";
import { SectionCard, ScopeBadge, InfoNote, BigValue, StatusPill, FieldLine } from "./primitives";
import { fmtMonth, fmtValue } from "@/lib/enso/ui";
import { TrendingUp, TrendingDown, Minus, GitBranch } from "lucide-react";

const INDICATOR_OPTIONS = ["nino12", "icen", "nino34", "roni", "soi", "u850", "d20"];

export function TrendsView() {
  const [indicatorId, setIndicatorId] = React.useState("nino34");
  const [windowMonths, setWindowMonths] = React.useState(24);
  const trend = React.useMemo(() => buildTrend(indicatorId, windowMonths), [indicatorId, windowMonths]);
  const phaseChanges = React.useMemo(() => buildPhaseChanges(), []);
  if (!trend) return null;

  const recent = trend.points.slice(-120);
  const slopeTone = trend.currentSlope > 0.01 ? "warm" : trend.currentSlope < -0.01 ? "cool" : "neutral";
  const slopeIcon = trend.currentSlope > 0.01 ? <TrendingUp className="h-4 w-4" /> : trend.currentSlope < -0.01 ? <TrendingDown className="h-4 w-4" /> : <Minus className="h-4 w-4" />;

  return (
    <div className="space-y-5">
      <InfoNote tone="info" title="Análisis de tendencias — regresión lineal y cambio de fase">
        Para cada indicador, se calcula la pendiente de la regresión lineal sobre una ventana móvil
        configurable, junto con el coeficiente de determinación R². Se detectan además los cambios de
        fase ENSO (transiciones entre El Niño, Neutral y La Niña sobre Niño 3.4). Cálculo determinista
        en código; el modelo no participa.
      </InfoNote>

      {/* Selectores */}
      <SectionCard title="Configuración del análisis">
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <p className="mb-1 text-[11px] text-muted-foreground">Indicador</p>
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Selector de indicador">
              {INDICATOR_OPTIONS.map((id) => (
                <button
                  key={id}
                  onClick={() => setIndicatorId(id)}
                  className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium enso-focus-ring ${indicatorId === id ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted"}`}
                  aria-pressed={indicatorId === id}
                >
                  <ScopeBadge scope={INDICATOR_BY_ID[id].scope} />
                  {INDICATOR_BY_ID[id].shortName}
                </button>
              ))}
            </div>
          </div>
          <div>
            <p className="mb-1 text-[11px] text-muted-foreground">Ventana (meses)</p>
            <div className="flex gap-1.5" role="group" aria-label="Tamaño de ventana">
              {[12, 24, 36, 60].map((w) => (
                <button
                  key={w}
                  onClick={() => setWindowMonths(w)}
                  className={`rounded-full border px-2.5 py-1 text-xs font-medium enso-focus-ring ${windowMonths === w ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted"}`}
                  aria-pressed={windowMonths === w}
                >
                  {w}
                </button>
              ))}
            </div>
          </div>
        </div>
      </SectionCard>

      {/* Resumen de tendencia actual */}
      <div className="grid gap-4 md:grid-cols-3">
        <SectionCard title="Tendencia actual (pendiente)">
          <div className="flex items-center gap-2">
            {slopeIcon}
            <BigValue
              value={`${trend.currentSlope > 0 ? "+" : ""}${(trend.currentSlope * 12).toFixed(3)}`}
              units={`/año`}
              tone={slopeTone}
            />
          </div>
          <p className="mt-1 text-[11px] text-muted-foreground">{trend.interpretation}</p>
        </SectionCard>
        <SectionCard title="Calidad del ajuste (R²)">
          <BigValue value={trend.currentR2.toFixed(2)} tone="neutral" />
          <p className="mt-1 text-[11px] text-muted-foreground">
            {trend.currentR2 >= 0.5 ? "Ajuste bueno" : trend.currentR2 >= 0.2 ? "Ajuste moderado" : "Ajuste débil"}
          </p>
        </SectionCard>
        <SectionCard title="Valor medio en la ventana">
          <BigValue value={fmtValue(recent[recent.length - 1]?.mean ?? null, trend.units).replace(/ (°C|m\/s|m)$/, "")} units={trend.units === "degC" ? "°C" : trend.units === "m_per_s" ? "m/s" : trend.units === "m" ? "m" : ""} tone="neutral" />
          <p className="mt-1 text-[11px] text-muted-foreground">Últimos {windowMonths} meses</p>
        </SectionCard>
      </div>

      {/* Gráfico de pendiente */}
      <SectionCard
        title={<span className="flex items-center gap-2"><TrendingUp className="h-4 w-4" /> Evolución de la tendencia (pendiente móvil)</span>}
        description={`Pendiente de la regresión lineal sobre ventana de ${windowMonths} meses, por mes. Cálido = creciente, frío = decreciente.`}
      >
        <SlopeChart trend={trend} recent={recent} />
      </SectionCard>

      {/* Gráfico de R² */}
      <SectionCard title="Calidad del ajuste (R²) en el tiempo" description="R² de la regresión móvil. Valores cercanos a 1 indican tendencia lineal clara.">
        <R2Chart recent={recent} />
      </SectionCard>

      {/* Cambios de fase */}
      <SectionCard
        title={<span className="flex items-center gap-2"><GitBranch className="h-4 w-4" /> Cambios de fase ENSO (sobre Niño 3.4)</span>}
        description="Transiciones entre categorías El Niño / Neutral / La Niña (umbral ±0.5 °C). Últimos 20 cambios."
      >
        <div className="max-h-80 overflow-y-auto enso-scroll rounded-md border">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-muted/80 backdrop-blur">
              <tr className="text-left">
                <th className="px-2 py-1.5 font-medium">Mes</th>
                <th className="px-2 py-1.5 font-medium">Desde</th>
                <th className="px-2 py-1.5 font-medium">Hacia</th>
                <th className="px-2 py-1.5 font-medium text-right">Niño 3.4</th>
              </tr>
            </thead>
            <tbody>
              {phaseChanges.slice(-20).reverse().map((c, i) => (
                <tr key={i} className="border-b last:border-0 hover:bg-muted/40">
                  <td className="px-2 py-1.5 font-medium enso-num">{fmtMonth(c.month)}</td>
                  <td className="px-2 py-1.5">
                    <StatusPill label={c.fromPhase} tone={c.fromPhase === "El Niño" ? "warm" : c.fromPhase === "La Niña" ? "cool" : "neutral"} />
                  </td>
                  <td className="px-2 py-1.5">
                    <StatusPill label={c.toPhase} tone={c.toPhase === "El Niño" ? "warm" : c.toPhase === "La Niña" ? "cool" : "neutral"} />
                  </td>
                  <td className="px-2 py-1.5 text-right enso-num" style={{ color: c.value > 0 ? "var(--enso-warm)" : "var(--enso-cool)" }}>
                    {c.value > 0 ? "+" : ""}{c.value.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>
    </div>
  );
}

function SlopeChart({ trend, recent }: { trend: TrendResult; recent: TrendResult["points"] }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(640);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => { for (const x of e) setW(Math.max(320, x.contentRect.width)); });
    ro.observe(ref.current); return () => ro.disconnect();
  }, []);
  const h = 260;
  const padL = 44, padR = 16, padT = 12, padB = 28;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  const vals = recent.map((p) => p.slope);
  const max = Math.max(...vals.map(Math.abs), 0.01);
  const sx = (i: number) => padL + (i / Math.max(1, recent.length - 1)) * plotW;
  const sy = (v: number) => padT + ((max - v) / (2 * max)) * plotH;
  const pts = recent.map((p, i) => `${sx(i)},${sy(p.slope)}`).join(" ");
  const ticks = recent.filter((_, i) => i % Math.max(1, Math.floor(recent.length / 8)) === 0);

  return (
    <div ref={ref} className="w-full">
      <svg width={w} height={h} role="img" aria-label="Evolución de la pendiente de tendencia">
        <line x1={padL} y1={sy(0)} x2={padL + plotW} y2={sy(0)} stroke="currentColor" strokeOpacity={0.4} strokeWidth={1} />
        <rect x={padL} y={padT} width={plotW} height={sy(0) - padT} fill="var(--enso-warm)" fillOpacity={0.06} />
        <rect x={padL} y={sy(0)} width={plotW} height={padT + plotH - sy(0)} fill="var(--enso-cool)" fillOpacity={0.06} />
        <polyline points={pts} fill="none" stroke="var(--enso-basin)" strokeWidth={2} />
        {recent.map((p, i) => (
          <circle key={i} cx={sx(i)} cy={sy(p.slope)} r={2} fill={p.slope > 0 ? "var(--enso-warm)" : "var(--enso-cool)"} />
        ))}
        <line x1={padL} y1={padT} x2={padL} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.3} />
        <line x1={padL} y1={padT + plotH} x2={padL + plotW} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.3} />
        {[max, 0, -max].map((v, i) => (
          <text key={i} x={padL - 6} y={sy(v) + 3} textAnchor="end" fontSize={9} fill="currentColor" fillOpacity={0.6}>{(v * 12).toFixed(2)}</text>
        ))}
        {ticks.map((p) => {
          const i = recent.indexOf(p);
          return <text key={p.month} x={sx(i)} y={h - 8} textAnchor="middle" fontSize={9} fill="currentColor" fillOpacity={0.6}>{fmtMonth(p.month).slice(0, 3)}</text>;
        })}
      </svg>
      <p className="mt-1 text-[11px] text-muted-foreground">Pendiente anualizada (por año). Eje Y: {trend.units}/año.</p>
    </div>
  );
}

function R2Chart({ recent }: { recent: TrendResult["points"] }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(640);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => { for (const x of e) setW(Math.max(320, x.contentRect.width)); });
    ro.observe(ref.current); return () => ro.disconnect();
  }, []);
  const h = 180;
  const padL = 36, padR = 16, padT = 12, padB = 28;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  const sx = (i: number) => padL + (i / Math.max(1, recent.length - 1)) * plotW;
  const sy = (v: number) => padT + ((1 - v) / 1) * plotH;
  const pts = recent.map((p, i) => `${sx(i)},${sy(p.r2)}`).join(" ");
  const ticks = recent.filter((_, i) => i % Math.max(1, Math.floor(recent.length / 8)) === 0);

  return (
    <div ref={ref} className="w-full">
      <svg width={w} height={h} role="img" aria-label="Calidad del ajuste R² en el tiempo">
        <rect x={padL} y={padT} width={plotW} height={plotH} fill="var(--muted-foreground)" fillOpacity={0.04} />
        {[0.5, 0.25].map((v) => (
          <line key={v} x1={padL} y1={sy(v)} x2={padL + plotW} y2={sy(v)} stroke="currentColor" strokeOpacity={0.2} strokeDasharray="4 3" />
        ))}
        <polyline points={pts} fill="none" stroke="var(--enso-coastal)" strokeWidth={2} />
        <line x1={padL} y1={padT} x2={padL} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.3} />
        <line x1={padL} y1={padT + plotH} x2={padL + plotW} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.3} />
        {[1, 0.5, 0].map((v) => (
          <text key={v} x={padL - 6} y={sy(v) + 3} textAnchor="end" fontSize={9} fill="currentColor" fillOpacity={0.6}>{v.toFixed(2)}</text>
        ))}
        {ticks.map((p) => {
          const i = recent.indexOf(p);
          return <text key={p.month} x={sx(i)} y={h - 8} textAnchor="middle" fontSize={9} fill="currentColor" fillOpacity={0.6}>{fmtMonth(p.month).slice(0, 3)}</text>;
        })}
      </svg>
    </div>
  );
}
