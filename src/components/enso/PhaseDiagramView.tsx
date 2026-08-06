"use client";

import * as React from "react";
import { buildPhaseSpace, type PhasePoint } from "@/lib/enso/derived";
import { SectionCard, ScopeBadge, InfoNote, BigValue } from "./primitives";
import { fmtMonth } from "@/lib/enso/ui";
import { ScatterChart, Activity } from "lucide-react";

export function PhaseDiagramView() {
  const [windowMonths, setWindowMonths] = React.useState(60);
  const points = React.useMemo(() => buildPhaseSpace(windowMonths), [windowMonths]);
  const [hovered, setHovered] = React.useState<number | null>(null);
  const last = points[points.length - 1];

  return (
    <div className="space-y-5">
      <InfoNote tone="info" title="Diagrama de fases ENSO — espacio de fase océano-atmósfera">
        Cada punto representa un mes en el espacio (Niño 3.4, SOI). La trayectoria muestra la
        evolución temporal del sistema acoplado. La anticorrelación esperada (Niño 3.4 cálido ↔ SOI
        negativo) produce una diagonal descendente. Los cuadrantes indican la coherencia
        océano-atmósfera. Cálculo determinista en código; el modelo no participa.
      </InfoNote>

      {/* Selector de ventana */}
      <SectionCard title="Ventana temporal">
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Ventana temporal">
          {[24, 60, 120, 240].map((w) => (
            <button
              key={w}
              onClick={() => setWindowMonths(w)}
              className={`rounded-full border px-3 py-1.5 text-xs font-medium enso-focus-ring ${windowMonths === w ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted"}`}
              aria-pressed={windowMonths === w}
            >
              {w} meses ({Math.floor(w / 12)} años)
            </button>
          ))}
          <span className="ml-auto text-xs text-muted-foreground">{points.length} puntos</span>
        </div>
      </SectionCard>

      {/* Estado actual */}
      <div className="grid gap-4 md:grid-cols-3">
        <SectionCard title="Posición actual (Niño 3.4)">
          <BigValue value={last?.nino34 !== null && last?.nino34 !== undefined ? `${last.nino34 > 0 ? "+" : ""}${last.nino34.toFixed(2)}` : "—"} units="°C" tone={last?.nino34 && last.nino34 > 0 ? "warm" : "cool"} />
          <p className="mt-1 text-[11px] text-muted-foreground">{last ? fmtMonth(last.month) : ""}</p>
        </SectionCard>
        <SectionCard title="Posición actual (SOI)">
          <BigValue value={last?.soi !== null && last?.soi !== undefined ? `${last.soi > 0 ? "+" : ""}${last.soi.toFixed(2)}` : "—"} tone={last?.soi && last.soi < 0 ? "warm" : "cool"} />
          <p className="mt-1 text-[11px] text-muted-foreground">{last ? fmtMonth(last.month) : ""}</p>
        </SectionCard>
        <SectionCard title="Cuadrante actual">
          <p className="text-sm font-bold" style={{ color: quadrantColor(last) }}>{quadrantLabel(last)}</p>
          <p className="mt-1 text-[11px] text-muted-foreground">{quadrantDesc(last)}</p>
        </SectionCard>
      </div>

      {/* Diagrama de dispersión con trayectoria */}
      <SectionCard
        title={<span className="flex items-center gap-2"><ScatterChart className="h-4 w-4" /> Espacio de fase Niño 3.4 vs SOI</span>}
        description="Eje X: Niño 3.4 (°C). Eje Y: SOI (adimensional). La trayectoria conecta los meses cronológicamente. Pasa el cursor sobre un punto para ver el mes."
      >
        <PhaseScatter points={points} hovered={hovered} setHovered={setHovered} />
      </SectionCard>

      {/* Distribución por cuadrante */}
      <SectionCard title="Distribución por cuadrante" description="Número de meses en cada cuadrante del espacio de fase durante la ventana seleccionada.">
        <QuadrantStats points={points} />
      </SectionCard>

      <InfoNote tone="muted" title="Interpretación de cuadrantes">
        <ul className="space-y-1 list-disc pl-4">
          <li><strong>Cuadrante inferior derecho</strong> (Niño 3.4 +, SOI −): El Niño con coherencia océano-atmósfera — el océano cálido acompaña una componente atmosférica de El Niño.</li>
          <li><strong>Cuadrante superior izquierdo</strong> (Niño 3.4 −, SOI +): La Niña con coherencia — océano frío y SOI positivo.</li>
          <li><strong>Cuadrantes superior derecho e inferior izquierdo</strong>: estados incoherentes; el océano y la atmósfera no están alineados. Pueden indicar transiciones o acoplamiento débil.</li>
          <li>La trayectoria tiende a seguir una diagonal descendente (anticorrelación SOI–Niño 3.4) cuando el sistema está acoplado.</li>
        </ul>
      </InfoNote>
    </div>
  );
}

function quadrantColor(p: PhasePoint | undefined): string {
  if (!p || p.nino34 === null || p.soi === null) return "var(--muted-foreground)";
  if (p.nino34 > 0 && p.soi < 0) return "var(--enso-warm)"; // El Niño coherente
  if (p.nino34 < 0 && p.soi > 0) return "var(--enso-cool)"; // La Niña coherente
  return "var(--muted-foreground)"; // incoherente
}

function quadrantLabel(p: PhasePoint | undefined): string {
  if (!p || p.nino34 === null || p.soi === null) return "Sin datos";
  if (p.nino34 > 0 && p.soi < 0) return "El Niño coherente";
  if (p.nino34 < 0 && p.soi > 0) return "La Niña coherente";
  if (p.nino34 > 0 && p.soi > 0) return "Océano cálido / atmósfera incoherente";
  if (p.nino34 < 0 && p.soi < 0) return "Océano frío / atmósfera incoherente";
  return "Neutral";
}

function quadrantDesc(p: PhasePoint | undefined): string {
  if (!p || p.nino34 === null || p.soi === null) return "";
  if (p.nino34 > 0 && p.soi < 0) return "Niño 3.4 positivo y SOI negativo: acoplamiento típico de El Niño.";
  if (p.nino34 < 0 && p.soi > 0) return "Niño 3.4 negativo y SOI positivo: acoplamiento típico de La Niña.";
  return "El océano y la atmósfera no están alineados; posible transición.";
}

/** Diagrama de dispersión con trayectoria (SVG). */
function PhaseScatter({ points, hovered, setHovered }: { points: PhasePoint[]; hovered: number | null; setHovered: (i: number | null) => void }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(640);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => { for (const x of e) setW(Math.max(320, x.contentRect.width)); });
    ro.observe(ref.current); return () => ro.disconnect();
  }, []);
  const h = 380;
  const padL = 44, padR = 16, padT = 12, padB = 36;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  const valid = points.filter((p) => p.nino34 !== null && p.soi !== null);
  if (valid.length === 0) return <div className="text-sm text-muted-foreground">Sin datos.</div>;
  const xs = valid.map((p) => p.nino34 as number);
  const ys = valid.map((p) => p.soi as number);
  const minX = Math.min(...xs) - 0.3, maxX = Math.max(...xs) + 0.3;
  const minY = Math.min(...ys) - 0.3, maxY = Math.max(...ys) + 0.3;
  const sx = (v: number) => padL + ((v - minX) / (maxX - minX)) * plotW;
  const sy = (v: number) => padT + ((maxY - v) / (maxY - minY)) * plotH;

  // Trayectoria conectando puntos
  const path = valid.map((p, i) => `${i === 0 ? "M" : "L"} ${sx(p.nino34 as number)},${sy(p.soi as number)}`).join(" ");

  return (
    <div ref={ref} className="w-full">
      <svg width={w} height={h} role="img" aria-label="Diagrama de fases Niño 3.4 vs SOI">
        {/* cuadrantes con colores de fondo */}
        <rect x={sx(0)} y={sy(0)} width={sx(maxX) - sx(0)} height={sy(minY) - sy(0)} fill="var(--enso-warm)" fillOpacity={0.05} />
        <rect x={sx(minX)} y={sy(maxY)} width={sx(0) - sx(minX)} height={sy(0) - sy(maxY)} fill="var(--enso-cool)" fillOpacity={0.05} />
        {/* líneas de umbral */}
        <line x1={sx(0)} y1={padT} x2={sx(0)} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.3} />
        <line x1={padL} y1={sy(0)} x2={padL + plotW} y2={sy(0)} stroke="currentColor" strokeOpacity={0.3} />
        <line x1={sx(0.5)} y1={padT} x2={sx(0.5)} y2={padT + plotH} stroke="var(--enso-warm)" strokeDasharray="4 3" strokeOpacity={0.3} />
        <line x1={sx(-0.5)} y1={padT} x2={sx(-0.5)} y2={padT + plotH} stroke="var(--enso-cool)" strokeDasharray="4 3" strokeOpacity={0.3} />
        {/* trayectoria */}
        <path d={path} fill="none" stroke="var(--enso-basin)" strokeWidth={1} strokeOpacity={0.3} />
        {/* puntos */}
        {valid.map((p, i) => {
          const color = p.phase === "El Niño" ? "var(--enso-warm)" : p.phase === "La Niña" ? "var(--enso-cool)" : "var(--muted-foreground)";
          const isLast = i === valid.length - 1;
          const isHovered = hovered === i;
          return (
            <g key={i} onMouseEnter={() => setHovered(i)} onMouseLeave={() => setHovered(null)} style={{ cursor: "pointer" }}>
              <circle
                cx={sx(p.nino34 as number)} cy={sy(p.soi as number)}
                r={isLast ? 6 : isHovered ? 5 : 3}
                fill={isLast ? "var(--enso-coastal)" : color}
                fillOpacity={isLast ? 1 : 0.7}
                stroke={isLast || isHovered ? "var(--card)" : "none"}
                strokeWidth={1.5}
              />
              {(isHovered || isLast) && (
                <g>
                  <rect x={sx(p.nino34 as number) - 40} y={sy(p.soi as number) - 22} width={80} height={16} rx={3} fill="var(--card)" stroke="var(--border)" />
                  <text x={sx(p.nino34 as number)} y={sy(p.soi as number) - 10} textAnchor="middle" fontSize={9} fill="currentColor">{fmtMonth(p.month)}</text>
                </g>
              )}
            </g>
          );
        })}
        {/* ejes */}
        <line x1={padL} y1={padT} x2={padL} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.3} />
        <line x1={padL} y1={padT + plotH} x2={padL + plotW} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.3} />
        {[minX, 0, maxX].map((v) => (
          <text key={v} x={sx(v)} y={h - 18} textAnchor="middle" fontSize={9} fill="currentColor" fillOpacity={0.6}>{v.toFixed(1)}</text>
        ))}
        {[minY, 0, maxY].map((v) => (
          <text key={v} x={padL - 6} y={sy(v) + 3} textAnchor="end" fontSize={9} fill="currentColor" fillOpacity={0.6}>{v.toFixed(1)}</text>
        ))}
        <text x={padL + plotW / 2} y={h - 2} textAnchor="middle" fontSize={10} fill="currentColor" fillOpacity={0.6}>Niño 3.4 (°C)</text>
        <text x={10} y={padT + plotH / 2} textAnchor="middle" fontSize={10} fill="currentColor" fillOpacity={0.6} transform={`rotate(-90 10 ${padT + plotH / 2})`}>SOI</text>
      </svg>
      <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full" style={{ background: "var(--enso-warm)" }} /> El Niño</span>
        <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full" style={{ background: "var(--enso-cool)" }} /> La Niña</span>
        <span className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-[color:var(--muted-foreground)] opacity-50" /> Neutral</span>
        <span className="flex items-center gap-1"><span className="h-3 w-3 rounded-full" style={{ background: "var(--enso-coastal)" }} /> Mes actual</span>
      </div>
    </div>
  );
}

function QuadrantStats({ points }: { points: PhasePoint[] }) {
  const valid = points.filter((p) => p.nino34 !== null && p.soi !== null);
  const q = {
    ninoCoherent: valid.filter((p) => (p.nino34 as number) > 0 && (p.soi as number) < 0).length,
    ninaCoherent: valid.filter((p) => (p.nino34 as number) < 0 && (p.soi as number) > 0).length,
    ninoIncoherent: valid.filter((p) => (p.nino34 as number) > 0 && (p.soi as number) > 0).length,
    ninaIncoherent: valid.filter((p) => (p.nino34 as number) < 0 && (p.soi as number) < 0).length,
  };
  const total = valid.length || 1;
  const stats = [
    { label: "El Niño coherente (+,−)", count: q.ninoCoherent, color: "var(--enso-warm)", desc: "Océano cálido + SOI negativo" },
    { label: "La Niña coherente (−,+)", count: q.ninaCoherent, color: "var(--enso-cool)", desc: "Océano frío + SOI positivo" },
    { label: "Incoherente cálido (+,+)", count: q.ninoIncoherent, color: "var(--muted-foreground)", desc: "Océano cálido pero SOI positivo" },
    { label: "Incoherente frío (−,−)", count: q.ninaIncoherent, color: "var(--muted-foreground)", desc: "Océano frío pero SOI negativo" },
  ];
  return (
    <div className="space-y-3">
      {stats.map((s) => (
        <div key={s.label}>
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="font-medium" style={{ color: s.color }}>{s.label}</span>
            <span className="text-muted-foreground">{s.count} meses ({Math.round((s.count / total) * 100)}%)</span>
          </div>
          <div className="h-2.5 w-full rounded-full bg-muted overflow-hidden">
            <div className="h-full rounded-full transition-all" style={{ width: `${(s.count / total) * 100}%`, background: s.color }} />
          </div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">{s.desc}</p>
        </div>
      ))}
    </div>
  );
}
