"use client";

import * as React from "react";
import { buildAlertHistory, type AlertPeriod } from "@/lib/enso/derived";
import { SectionCard, ScopeBadge, InfoNote, StatusPill } from "./primitives";
import { fmtMonth } from "@/lib/enso/ui";
import { History, AlertTriangle, Clock } from "lucide-react";

export function AlertHistoryView() {
  const periods = React.useMemo(() => buildAlertHistory(), []);
  const coastal = periods.filter((p) => p.scope === "coastal");
  const basin = periods.filter((p) => p.scope === "cuenca");

  return (
    <div className="space-y-5">
      <InfoNote tone="warn" title="Historial de alertas — reconstrucción derivada del observatorio">
        Esta vista reconstruye el historial de periodos ENSO a partir de las series normalizadas,
        etiquetando periodos por categoría (El Niño / La Niña / Neutral) e intensidad pico.
        <strong> Es una reconstrucción derivada del observatorio</strong>; las alertas oficiales se
        citan textualmente de ENFEN (costero) y NOAA/CPC (cuenca). Para declaraciones oficiales
        históricas consulte los archivos de estas instituciones.
      </InfoNote>

      {/* Resumen */}
      <div className="grid gap-4 md:grid-cols-4">
        <SummaryCard label="Periodos costeros" value={coastal.length} icon={<History className="h-4 w-4" />} />
        <SummaryCard label="Periodos de cuenca" value={basin.length} icon={<History className="h-4 w-4" />} />
        <SummaryCard label="Eventos El Niño (total)" value={periods.filter((p) => p.phase === "El Niño").length} icon={<AlertTriangle className="h-4 w-4" />} tone="warm" />
        <SummaryCard label="Eventos La Niña (total)" value={periods.filter((p) => p.phase === "La Niña").length} icon={<AlertTriangle className="h-4 w-4" />} tone="cool" />
      </div>

      {/* Línea de tiempo visual */}
      <SectionCard
        title={<span className="flex items-center gap-2"><Clock className="h-4 w-4" /> Línea de tiempo de alertas</span>}
        description="Cada bloque representa un periodo activo (El Niño en cálido, La Niña en frío). Costero (arriba) vs cuenca (abajo)."
      >
        <Timeline periods={periods} />
      </SectionCard>

      {/* Tabla de periodos costeros */}
      <SectionCard title="Periodos costeros (ICEN, umbral ±0.4 °C)" description="Reconstrucción derivada del observatorio.">
        <PeriodTable periods={coastal} />
      </SectionCard>

      {/* Tabla de periodos de cuenca */}
      <SectionCard title="Periodos de cuenca (Niño 3.4, umbral ±0.5 °C)" description="Reconstrucción derivada del observatorio.">
        <PeriodTable periods={basin} />
      </SectionCard>
    </div>
  );
}

function SummaryCard({ label, value, icon, tone = "neutral" }: { label: string; value: number; icon: React.ReactNode; tone?: "neutral" | "warm" | "cool" }) {
  const color = tone === "warm" ? "var(--enso-warm)" : tone === "cool" ? "var(--enso-cool)" : "var(--enso-basin)";
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="flex items-center gap-2" style={{ color }}>
        {icon}
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
      </div>
      <p className="mt-1 text-2xl font-bold enso-num" style={{ color }}>{value}</p>
    </div>
  );
}

function Timeline({ periods }: { periods: AlertPeriod[] }) {
  // Encontrar rango de fechas
  const allMonths = periods.flatMap((p) => [p.startMonth, p.endMonth]).sort();
  const minMonth = allMonths[0] ?? "1990-01";
  const maxMonth = allMonths[allMonths.length - 1] ?? "2026-07";
  const totalMonths = (Number(maxMonth.split("-")[0]) - Number(minMonth.split("-")[0])) * 12 +
    (Number(maxMonth.split("-")[1]) - Number(minMonth.split("-")[1])) + 1;

  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(640);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => { for (const x of e) setW(Math.max(320, x.contentRect.width)); });
    ro.observe(ref.current); return () => ro.disconnect();
  }, []);

  const padL = 60, padR = 12, padT = 16, padB = 28;
  const plotW = w - padL - padR;
  const trackH = 24;
  const gap = 8;
  const coastalH = trackH;
  const basinH = trackH;
  const h = padT + coastalH + gap + basinH + padB;

  const monthToX = (month: string) => {
    const [y, m] = month.split("-").map(Number);
    const [y0, m0] = minMonth.split("-").map(Number);
    const offset = (y - y0) * 12 + (m - m0);
    return padL + (offset / totalMonths) * plotW;
  };

  return (
    <div ref={ref} className="w-full">
      <svg width={w} height={h} role="img" aria-label="Línea de tiempo de alertas ENSO">
        {/* etiquetas */}
        <text x={padL - 8} y={padT + coastalH / 2 + 3} textAnchor="end" fontSize={10} fill="var(--enso-coastal)" fontWeight="bold">Costero</text>
        <text x={padL - 8} y={padT + coastalH + gap + basinH / 2 + 3} textAnchor="end" fontSize={10} fill="var(--enso-basin)" fontWeight="bold">Cuenca</text>
        {/* tracks de fondo */}
        <rect x={padL} y={padT} width={plotW} height={coastalH} fill="var(--muted)" fillOpacity={0.15} rx={4} />
        <rect x={padL} y={padT + coastalH + gap} width={plotW} height={basinH} fill="var(--muted)" fillOpacity={0.15} rx={4} />
        {/* periodos costeros */}
        {periods.filter((p) => p.scope === "coastal").map((p, i) => {
          const x = monthToX(p.startMonth);
          const xEnd = monthToX(p.endMonth);
          const width = Math.max(2, xEnd - x);
          const fill = p.phase === "El Niño" ? "var(--enso-warm)" : "var(--enso-cool)";
          return <rect key={`c${i}`} x={x} y={padT} width={width} height={coastalH} fill={fill} fillOpacity={0.8} rx={2} title={`${p.phase} costero ${p.startMonth}–${p.endMonth} (${p.intensity})`} />;
        })}
        {/* periodos de cuenca */}
        {periods.filter((p) => p.scope === "basin").map((p, i) => {
          const x = monthToX(p.startMonth);
          const xEnd = monthToX(p.endMonth);
          const width = Math.max(2, xEnd - x);
          const fill = p.phase === "El Niño" ? "var(--enso-warm)" : "var(--enso-cool)";
          return <rect key={`b${i}`} x={x} y={padT + coastalH + gap} width={width} height={basinH} fill={fill} fillOpacity={0.8} rx={2} title={`${p.phase} cuenca ${p.startMonth}–${p.endMonth} (${p.intensity})`} />;
        })}
        {/* eje de años */}
        {(() => {
          const y0 = Number(minMonth.split("-")[0]);
          const y1 = Number(maxMonth.split("-")[0]);
          const ticks: number[] = [];
          for (let y = y0; y <= y1; y += Math.max(1, Math.floor((y1 - y0) / 8))) ticks.push(y);
          return ticks.map((y) => (
            <g key={y}>
              <line x1={monthToX(`${y}-01`)} y1={padT} x2={monthToX(`${y}-01`)} y2={padT + coastalH + gap + basinH} stroke="currentColor" strokeOpacity={0.15} />
              <text x={monthToX(`${y}-01`)} y={h - 8} textAnchor="middle" fontSize={9} fill="currentColor" fillOpacity={0.6}>{y}</text>
            </g>
          ));
        })()}
      </svg>
      <div className="mt-2 flex items-center gap-3 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1"><span className="h-3 w-3 rounded" style={{ background: "var(--enso-warm)" }} /> El Niño</span>
        <span className="flex items-center gap-1"><span className="h-3 w-3 rounded" style={{ background: "var(--enso-cool)" }} /> La Niña</span>
        <span className="flex items-center gap-1"><span className="h-3 w-3 rounded bg-[color:var(--muted)] opacity-15" /> Neutral</span>
      </div>
    </div>
  );
}

function PeriodTable({ periods }: { periods: AlertPeriod[] }) {
  const sorted = [...periods].sort((a, b) => b.startMonth.localeCompare(a.startMonth));
  return (
    <div className="max-h-96 overflow-y-auto enso-scroll rounded-md border">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-muted/80 backdrop-blur">
          <tr className="text-left">
            <th className="px-2 py-1.5 font-medium">Inicio</th>
            <th className="px-2 py-1.5 font-medium">Fin</th>
            <th className="px-2 py-1.5 font-medium">Fase</th>
            <th className="px-2 py-1.5 font-medium">Intensidad</th>
            <th className="px-2 py-1.5 font-medium text-right">Pico</th>
            <th className="px-2 py-1.5 font-medium">Mes pico</th>
            <th className="px-2 py-1.5 font-medium text-right">Duración</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((p, i) => (
            <tr key={i} className="border-b last:border-0 hover:bg-muted/40">
              <td className="px-2 py-1.5 enso-num">{fmtMonth(p.startMonth)}</td>
              <td className="px-2 py-1.5 enso-num">{fmtMonth(p.endMonth)}</td>
              <td className="px-2 py-1.5">
                <StatusPill label={p.phase} tone={p.phase === "El Niño" ? "warm" : p.phase === "La Niña" ? "cool" : "neutral"} />
              </td>
              <td className="px-2 py-1.5">{p.intensity}</td>
              <td className="px-2 py-1.5 text-right enso-num font-bold" style={{ color: p.peakValue > 0 ? "var(--enso-warm)" : "var(--enso-cool)" }}>
                {p.peakValue > 0 ? "+" : ""}{p.peakValue}
              </td>
              <td className="px-2 py-1.5 enso-num">{fmtMonth(p.peakMonth)}</td>
              <td className="px-2 py-1.5 text-right enso-num">{p.durationMonths} meses</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
