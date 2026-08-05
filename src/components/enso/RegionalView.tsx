"use client";

import * as React from "react";
import { generateRegionImpacts, type RegionImpact } from "@/lib/enso/series";
import { SectionCard, ScopeBadge, InfoNote, BigValue, StatusPill, FieldLine } from "./primitives";
import { anomalyColor } from "@/lib/enso/ui";
import { MapPin, AlertTriangle, CloudRain, Thermometer } from "lucide-react";

const RISK_COLORS = {
  1: "var(--enso-cool)",
  2: "var(--enso-coastal)",
  3: "var(--enso-warm)",
  4: "#dc2626",
};

export function RegionalView() {
  const regions = React.useMemo(() => generateRegionImpacts(), []);
  const sorted = [...regions].sort((a, b) => b.riskLevel - a.riskLevel);

  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(640);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => { for (const x of e) setW(Math.max(320, x.contentRect.width)); });
    ro.observe(ref.current); return () => ro.disconnect();
  }, []);

  // Mapa esquemático de la costa peruana (lat -3 a -18, lon -82 to -70)
  const h = 460;
  const padL = 40, padR = 16, padT = 16, padB = 28;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  const latMin = -19, latMax = -2, lonMin = -82.5, lonMax = -69.5;
  const sx = (lon: number) => padL + ((lon - lonMin) / (lonMax - lonMin)) * plotW;
  const sy = (lat: number) => padT + ((latMax - lat) / (latMax - latMin)) * plotH;

  return (
    <div className="space-y-5">
      <InfoNote tone="warn" title="Impacto regional — interpretación generada por el observatorio">
        Esta vista sintetiza el impacto relativo estimado de El Niño Costero en los departamentos
        costeros del Perú, coherente con el estado actual. <strong>No es un pronóstico oficial de
        impacto</strong> ni una alerta operativa. Para emergencias y alertas oficiales consulte
        INDECI, CENEPRED, SENAMHI y la Comisión Multisectorial ENFEN. La influencia de El Niño
        Costero es mayor en el norte (Tumbes, Piura, Lambayeque) y decae hacia el sur.
      </InfoNote>

      {/* Mapa de departamentos costeros */}
      <SectionCard
        title={<span className="flex items-center gap-2"><MapPin className="h-4 w-4" /> Mapa de impacto relativo — costa peruana</span>}
        description="Cada marcador representa un departamento costero. El color indica el nivel de riesgo relativo derivado (1=bajo, 4=muy alto). Interpretación del observatorio."
      >
        <div ref={ref} className="w-full">
          <svg width={w} height={h} role="img" aria-label="Mapa de impacto regional en la costa peruana">
            {/* línea de costa esquemática (continente a la izquierda, océano a la derecha) */}
            <path
              d={`M ${sx(lonMin + 1)} ${sy(latMax - 0.5)}
                  C ${sx(-80)} ${sy(-4)}, ${sx(-79.5)} ${sy(-8)}, ${sx(-79)} ${sy(-12)}
                  S ${sx(-77)} ${sy(-16)}, ${sx(lonMax - 1)} ${sy(latMin + 0.5)}`}
              fill="none" stroke="var(--enso-basin)" strokeWidth={2} strokeOpacity={0.5}
            />
            {/* sombreado continental (oeste de la línea de costa) */}
            <path
              d={`M ${padL} ${padT}
                  L ${padL} ${padT + plotH}
                  L ${sx(lonMin + 1)} ${sy(latMin + 0.5)}
                  C ${sx(-77)} ${sy(-16)}, ${sx(-79)} ${sy(-12)}, ${sx(-79.5)} ${sy(-8)}
                  C ${sx(-80)} ${sy(-4)}, ${sx(lonMin + 1)} ${sy(latMax - 0.5)}
                  L ${padL} ${padT} Z`}
              fill="var(--muted)" fillOpacity={0.25}
            />
            {/* océano */}
            <text x={sx(-74)} y={sy(-5)} textAnchor="middle" fontSize={11} fill="var(--enso-basin)" fillOpacity={0.5} fontStyle="italic">Océano Pacífico</text>
            <text x={padL + 8} y={padT + plotH / 2} textAnchor="middle" fontSize={11} fill="currentColor" fillOpacity={0.4} transform={`rotate(-90 ${padL + 8} ${padT + plotH / 2})`}>Perú (continente)</text>

            {/* marcadores de departamentos */}
            {regions.map((r) => {
              const cx = sx(r.lon), cy = sy(r.lat);
              const color = RISK_COLORS[r.riskLevel];
              const radius = 8 + r.riskLevel * 2;
              return (
                <g key={r.code}>
                  <circle cx={cx} cy={cy} r={radius} fill={color} fillOpacity={0.7} stroke="var(--card)" strokeWidth={1.5} />
                  <circle cx={cx} cy={cy} r={radius + 3} fill="none" stroke={color} strokeOpacity={0.3} strokeWidth={2} className="enso-pulse" style={{ color }} />
                  <text x={cx} y={cy + 3} textAnchor="middle" fontSize={8} fill="var(--card)" fontWeight="bold">{r.code}</text>
                  <text x={cx} y={cy - radius - 4} textAnchor="middle" fontSize={9} fill="currentColor" fillOpacity={0.8}>{r.name}</text>
                </g>
              );
            })}
            {/* ejes */}
            {[-82, -78, -74, -70].map((lon) => (
              <text key={lon} x={sx(lon)} y={h - 10} textAnchor="middle" fontSize={9} fill="currentColor" fillOpacity={0.6}>{lon}°O</text>
            ))}
            {[-3, -6, -9, -12, -15, -18].map((lat) => (
              <text key={lat} x={6} y={sy(lat) + 3} fontSize={9} fill="currentColor" fillOpacity={0.6}>{lat}°S</text>
            ))}
          </svg>
          {/* Leyenda */}
          <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
            <span className="font-medium">Nivel de riesgo relativo:</span>
            {([1, 2, 3, 4] as const).map((lvl) => (
              <span key={lvl} className="flex items-center gap-1">
                <span className="h-3 w-3 rounded-full" style={{ background: RISK_COLORS[lvl] }} />
                {lvl === 1 ? "Bajo" : lvl === 2 ? "Moderado" : lvl === 3 ? "Alto" : "Muy alto"}
              </span>
            ))}
          </div>
        </div>
      </SectionCard>

      {/* Tabla de departamentos */}
      <SectionCard title="Detalle por departamento costero" description="Ordenado por nivel de riesgo relativo descendente.">
        <div className="overflow-x-auto enso-scroll">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="py-2 pr-3 font-medium">Departamento</th>
                <th className="py-2 pr-3 font-medium text-right">TSM anom. (°C)</th>
                <th className="py-2 pr-3 font-medium text-right">Precip. anom. (%)</th>
                <th className="py-2 pr-3 font-medium">Riesgo relativo</th>
                <th className="py-2 font-medium">Nota</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => (
                <tr key={r.code} className="border-b last:border-0 hover:bg-muted/40">
                  <td className="py-2 pr-3 font-medium">{r.name}</td>
                  <td className="py-2 pr-3 text-right enso-num" style={{ color: r.sstAnom > 0.5 ? "var(--enso-warm)" : r.sstAnom < -0.5 ? "var(--enso-cool)" : undefined }}>
                    {r.sstAnom > 0 ? "+" : ""}{r.sstAnom.toFixed(2)}
                  </td>
                  <td className="py-2 pr-3 text-right enso-num" style={{ color: r.precipAnom > 20 ? "var(--enso-warm)" : r.precipAnom < -10 ? "var(--enso-cool)" : undefined }}>
                    {r.precipAnom > 0 ? "+" : ""}{r.precipAnom.toFixed(1)}%
                  </td>
                  <td className="py-2 pr-3">
                    <StatusPill label={r.riskLabel} tone={r.riskLevel >= 3 ? "warm" : r.riskLevel === 2 ? "warn" : "cool"} />
                  </td>
                  <td className="py-2 text-muted-foreground text-[11px]">{r.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>

      {/* Cards de mayor riesgo */}
      <div className="grid gap-4 md:grid-cols-3">
        {sorted.slice(0, 3).map((r) => (
          <SectionCard key={r.code} title={r.name} right={<StatusPill label={r.riskLabel} tone={r.riskLevel >= 3 ? "warm" : "warn"} />}>
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-xs">
                <Thermometer className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-muted-foreground">TSM:</span>
                <span className="font-medium enso-num" style={{ color: r.sstAnom > 0.5 ? "var(--enso-warm)" : undefined }}>
                  {r.sstAnom > 0 ? "+" : ""}{r.sstAnom.toFixed(2)} °C
                </span>
              </div>
              <div className="flex items-center gap-2 text-xs">
                <CloudRain className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-muted-foreground">Precip.:</span>
                <span className="font-medium enso-num" style={{ color: r.precipAnom > 20 ? "var(--enso-warm)" : undefined }}>
                  {r.precipAnom > 0 ? "+" : ""}{r.precipAnom.toFixed(1)}%
                </span>
              </div>
              <p className="pt-1 text-[11px] text-muted-foreground border-t">{r.note}</p>
            </div>
          </SectionCard>
        ))}
      </div>

      <InfoNote tone="muted" title="Metodología del impacto regional">
        La anomalía de TSM costera se estima combinando el índice Niño 1+2 con un peso latitudinal
        (mayor en el norte). La anomalía de precipitación se deriva de la TSM costera escalada. El
        nivel de riesgo relativo (1-4) es una categorización del observatorio basada en la anomalía
        de precipitación. Estas son interpretaciones de divulgación; los productos oficiales de
        SENAMHI e IGP ofrecen evaluaciones detalladas del impacto.
      </InfoNote>
    </div>
  );
}
