"use client";

import * as React from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceArea, ReferenceLine, Legend, BarChart, Bar, Cell,
} from "recharts";
import type { MonthlyPoint, Series } from "@/lib/enso/types";
import { fmtMonth, fmtValue, anomalyColor } from "@/lib/enso/ui";

// ============== Serie temporal con bandas de umbral =========================
export interface ThresholdBand {
  min: number;
  max: number;
  label: string;
  color: string; // color del área
  fillOpacity?: number;
}

interface EnsoTimeSeriesProps {
  series: { id: string; label: string; color: string; data: MonthlyPoint[] }[];
  units: string;
  yLabel?: string;
  thresholds?: ThresholdBand[];
  zeroLine?: boolean;
  height?: number;
  /** Últimos N meses a mostrar; undefined = todo. */
  windowMonths?: number;
}

export function EnsoTimeSeries({
  series, units, yLabel, thresholds = [], zeroLine = true,
  height = 320, windowMonths,
}: EnsoTimeSeriesProps) {
  // Construir datos por mes (eje X = ISO). Recortar ventana si se pide.
  const allMonths = series[0]?.data.map((p) => p.month) ?? [];
  const months = windowMonths ? allMonths.slice(Math.max(0, allMonths.length - windowMonths)) : allMonths;
  const monthSet = new Set(months);
  const data = months.map((m) => {
    const row: Record<string, number | null | string> = { month: m };
    for (const s of series) {
      const p = s.data.find((q) => q.month === m);
      row[s.id] = p && monthSet.has(p.month) ? p.value : null;
    }
    return row;
  });

  const ticks = months.filter((_, i) => i % Math.max(1, Math.floor(months.length / 8)) === 0);

  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
          <XAxis
            dataKey="month"
            ticks={ticks}
            tickFormatter={fmtMonth}
            tick={{ fontSize: 11 }}
            minTickGap={16}
          />
          <YAxis
            tick={{ fontSize: 11 }}
            label={yLabel ? { value: yLabel, angle: -90, position: "insideLeft", style: { fontSize: 11 } } : undefined}
            width={48}
          />
          {thresholds.map((t, i) => (
            <ReferenceArea
              key={i}
              y1={t.min}
              y2={t.max}
              fill={t.color}
              fillOpacity={t.fillOpacity ?? 0.12}
              stroke="none"
              ifOverflow="extendDomain"
            />
          ))}
          {zeroLine && <ReferenceLine y={0} stroke="currentColor" strokeOpacity={0.4} strokeDasharray="4 4" />}
          <Tooltip
            contentStyle={{ fontSize: 12, borderRadius: 8 }}
            labelFormatter={(l) => fmtMonth(String(l))}
            formatter={(val: number | null, name: string) => [
              fmtValue(val, units),
              series.find((s) => s.id === name)?.label ?? name,
            ]}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {series.map((s) => (
            <Line
              key={s.id}
              type="monotone"
              dataKey={s.id}
              name={s.label}
              stroke={s.color}
              strokeWidth={2}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ============== Hovmöller longitud–tiempo (SVG) =============================
interface HovmollerProps {
  /** Filas = meses (más reciente abajo o arriba). */
  months: string[];
  /** Columnas = longitudes (°E, 120..290). */
  longitudes: number[];
  /** matriz[mesIdx][lonIdx] = valor. */
  matrix: (number | null)[][];
  scale: number;
  height?: number;
  title?: string;
  /** Etiqueta del eje de longitud. */
  lonLabel?: string;
}

export function Hovmoller({ months, longitudes, matrix, scale, height = 360, title, lonLabel = "Longitud (°E)" }: HovmollerProps) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(640);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) setW(Math.max(320, e.contentRect.width));
    });
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);

  const padL = 56, padR = 12, padT = 8, padB = 28;
  const plotW = w - padL - padR;
  const plotH = height - padT - padB;
  const cellW = plotW / longitudes.length;
  const cellH = plotH / months.length;

  const lonTicks = longitudes.filter((_, i) => i % Math.max(1, Math.floor(longitudes.length / 7)) === 0);
  const monthTicks = months.filter((_, i) => i % Math.max(1, Math.floor(months.length / 8)) === 0);

  return (
    <div ref={ref} className="w-full">
      {title && <p className="text-xs text-muted-foreground mb-1">{title}</p>}
      <svg width={w} height={height} role="img" aria-label={title ?? "Diagrama Hovmöller"}>
        {/* celdas */}
        {matrix.map((row, mi) =>
          row.map((v, li) => {
            if (v === null) return null;
            const x = padL + li * cellW;
            const y = padT + mi * cellH;
            return (
              <rect
                key={`${mi}-${li}`}
                x={x} y={y} width={cellW + 0.5} height={cellH + 0.5}
                fill={anomalyColor(v, scale)}
              />
            );
          })
        )}
        {/* ejes */}
        <line x1={padL} y1={padT} x2={padL} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.4} />
        <line x1={padL} y1={padT + plotH} x2={padL + plotW} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.4} />
        {lonTicks.map((lon) => {
          const i = longitudes.indexOf(lon);
          const x = padL + i * cellW + cellW / 2;
          return (
            <g key={lon}>
              <line x1={x} y1={padT + plotH} x2={x} y2={padT + plotH + 4} stroke="currentColor" strokeOpacity={0.4} />
              <text x={x} y={padT + plotH + 16} textAnchor="middle" fontSize={10} fill="currentColor" fillOpacity={0.7}>{lon}</text>
            </g>
          );
        })}
        {monthTicks.map((m) => {
          const i = months.indexOf(m);
          const y = padT + i * cellH + cellH / 2;
          return (
            <g key={m}>
              <text x={padL - 6} y={y + 3} textAnchor="end" fontSize={9} fill="currentColor" fillOpacity={0.7}>{fmtMonth(m)}</text>
            </g>
          );
        })}
        <text x={padL + plotW / 2} y={height - 2} textAnchor="middle" fontSize={10} fill="currentColor" fillOpacity={0.6}>{lonLabel}</text>
        <text x={10} y={padT + plotH / 2} textAnchor="middle" fontSize={10} fill="currentColor" fillOpacity={0.6} transform={`rotate(-90 10 ${padT + plotH / 2})`}>Tiempo</text>
      </svg>
      <ColorBar scale={scale} units="" />
    </div>
  );
}

// ============== Barra de color divergente ===================================
export function ColorBar({ scale, units }: { scale: number; units: string }) {
  const stops = [-1, -0.5, 0, 0.5, 1].map((t) => ({
    t,
    c: anomalyColor(t * scale, scale),
  }));
  return (
    <div className="flex items-center gap-2 mt-1">
      <span className="text-[10px] text-muted-foreground">−{scale}{units}</span>
      <div
        className="h-2.5 flex-1 rounded-full"
        style={{
          background: `linear-gradient(to right, ${stops.map((s) => s.c).join(",")})`,
        }}
      />
      <span className="text-[10px] text-muted-foreground">+{scale}{units}</span>
    </div>
  );
}

// ============== Mini sparkline ==============================================
export function MiniSpark({ data, color, height = 40 }: { data: (number | null)[]; color: string; height?: number }) {
  const w = 120;
  const vals = data.filter((v): v is number => v !== null);
  if (vals.length < 2) return <div style={{ height }} className="flex items-center text-[10px] text-muted-foreground">Sin datos</div>;
  const min = Math.min(...vals), max = Math.max(...vals);
  const range = max - min || 1;
  const pts = data.map((v, i) => {
    if (v === null) return null;
    const x = (i / (data.length - 1)) * w;
    const y = height - ((v - min) / range) * (height - 4) - 2;
    return `${x},${y}`;
  }).filter(Boolean) as string[];
  return (
    <svg width={w} height={height} role="img" aria-label="Tendencia reciente">
      <polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth={1.6} />
    </svg>
  );
}

// ============== Mapa de anomalía del Pacífico (SVG) ========================
interface AnomalyMapProps {
  /** Lista de celdas {lat, lon, value}. lon en -180..180. */
  cells: { lat: number; lon: number; value: number | null }[];
  scale: number;
  title?: string;
  /** Resaltar regiones Niño. */
  regions?: { name: string; bounds: { latMin: number; latMax: number; lonMin: number; lonMax: number }; color: string }[];
}

export function AnomalyMap({ cells, scale, title, regions = [] }: AnomalyMapProps) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(640);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => { for (const x of e) setW(Math.max(320, x.contentRect.width)); });
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  const h = 240;
  const padL = 36, padR = 12, padT = 12, padB = 28;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  // Dominio: lon -180..-70 (Pacífico), lat -15..15
  const lonMin = -180, lonMax = -70, latMin = -15, latMax = 15;
  const sx = (lon: number) => padL + ((lon - lonMin) / (lonMax - lonMin)) * plotW;
  const sy = (lat: number) => padT + ((latMax - lat) / (latMax - latMin)) * plotH;
  const cellW = plotW / Math.ceil((lonMax - lonMin) / 10);
  const cellH = plotH / Math.ceil((latMax - latMin) / 5);

  return (
    <div ref={ref} className="w-full">
      {title && <p className="text-xs text-muted-foreground mb-1">{title}</p>}
      <svg width={w} height={h} role="img" aria-label={title ?? "Mapa de anomalía"}>
        {/* celdas */}
        {cells.map((c, i) => {
          if (c.value === null) return null;
          return (
            <rect key={i} x={sx(c.lon) - cellW / 2} y={sy(c.lat) - cellH / 2} width={cellW} height={cellH}
              fill={anomalyColor(c.value, scale)} stroke="none" />
          );
        })}
        {/* regiones Niño */}
        {regions.map((r, i) => (
          <rect key={i}
            x={sx(r.bounds.lonMin)} y={sy(r.bounds.latMax)}
            width={sx(r.bounds.lonMax) - sx(r.bounds.lonMin)}
            height={sy(r.bounds.latMin) - sy(r.bounds.latMax)}
            fill="none" stroke={r.color} strokeWidth={1.5} strokeDasharray="4 3" />
        ))}
        {/* etiquetas de regiones */}
        {regions.map((r, i) => (
          <text key={`l${i}`} x={(sx(r.bounds.lonMin) + sx(r.bounds.lonMax)) / 2} y={sy(r.bounds.latMin) - 3}
            textAnchor="middle" fontSize={9} fill={r.color} fillOpacity={0.9}>{r.name}</text>
        ))}
        {/* ejes */}
        {[-180, -150, -120, -90].map((lon) => (
          <g key={lon}>
            <text x={sx(lon)} y={h - 10} textAnchor="middle" fontSize={9} fill="currentColor" fillOpacity={0.6}>{lon}°</text>
          </g>
        ))}
        {[15, 0, -15].map((lat) => (
          <text key={lat} x={6} y={sy(lat) + 3} fontSize={9} fill="currentColor" fillOpacity={0.6}>{lat}°</text>
        ))}
      </svg>
      <ColorBar scale={scale} units="°C" />
    </div>
  );
}

// ============== Heatmap mensual (año × mes) =================================
export function MonthlyHeatmap({ series, scale, years }: { series: Series; scale: number; years?: number[] }) {
  const byYear = new Map<string, (number | null)[]>();
  for (const p of series.points) {
    const [y] = p.month.split("-");
    if (years && !years.includes(Number(y))) continue;
    if (!byYear.has(y)) byYear.set(y, Array(12).fill(null));
    const m = Number(p.month.split("-")[1]) - 1;
    byYear.get(y)![m] = p.value;
  }
  const yrs = Array.from(byYear.keys()).sort();
  const recent = yrs.slice(-15);
  const cell = 26;
  const w = 12 * cell + 48;
  const h = recent.length * cell + 28;
  return (
    <svg width={w} height={h} role="img" aria-label={`Mapa de calor mensual de ${series.label}`}>
      {["E","F","M","A","M","J","J","A","S","O","N","D"].map((mo, i) => (
        <text key={i} x={48 + i * cell + cell / 2} y={16} textAnchor="middle" fontSize={10} fill="currentColor" fillOpacity={0.6}>{mo}</text>
      ))}
      {recent.map((y, ri) => {
        const row = byYear.get(y)!;
        return (
          <g key={y}>
            <text x={4} y={28 + ri * cell + cell / 2 + 3} fontSize={9} fill="currentColor" fillOpacity={0.6}>{y}</text>
            {row.map((v, mi) => (
              <rect key={mi} x={48 + mi * cell} y={24 + ri * cell} width={cell - 1} height={cell - 1}
                fill={anomalyColor(v, scale)} rx={2} />
            ))}
          </g>
        );
      })}
    </svg>
  );
}

// ============== Barras simples (p. ej. ICEN) ================================
export function SimpleBars({ data, color, height = 200, units }: { data: { label: string; value: number | null }[]; color: string; height?: number; units: string }) {
  const cdata = data.map((d) => ({ ...d }));
  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={cdata} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
          <XAxis dataKey="label" tick={{ fontSize: 10 }} interval="preserveStartEnd" minTickGap={10} />
          <YAxis tick={{ fontSize: 11 }} width={40} />
          <ReferenceLine y={0} stroke="currentColor" strokeOpacity={0.4} />
          <Tooltip
            contentStyle={{ fontSize: 12, borderRadius: 8 }}
            formatter={(v: number | null) => fmtValue(v, units)}
          />
          <Bar dataKey="value" radius={[3, 3, 0, 0]} isAnimationActive={false}>
            {cdata.map((d, i) => (
              <Cell key={i} fill={(d.value ?? 0) >= 0 ? color : "var(--enso-cool)"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
