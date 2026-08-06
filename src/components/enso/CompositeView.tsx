"use client";

import * as React from "react";
import { buildCompositeIndex, compositeCategory, type CompositeIndex } from "@/lib/enso/derived";
import { SectionCard, ScopeBadge, InfoNote, BigValue, StatusPill, FieldLine } from "./primitives";
import { EnsoTimeSeries } from "./charts";
import { COLOR_BASIN, COLOR_COASTAL, COLOR_WARM, COLOR_COOL } from "@/lib/enso/ui";
import { fmtMonth } from "@/lib/enso/ui";
import { Layers, TrendingUp, Info } from "lucide-react";

export function CompositeView() {
  const index = React.useMemo(() => buildCompositeIndex(), []);
  const latestIdx = index[index.length - 1];
  const recent = index.slice(-120); // últimos 10 años

  return (
    <div className="space-y-5">
      <InfoNote tone="warn" title="Índice compuesto ENSO — interpretación generada por el observatorio">
        Este índice integra los principales indicadores oceánicos y atmosféricos en un único valor
        adimensional. Es una <strong>síntesis del observatorio</strong>, no un índice oficial. NO
        sustituye al RONI (cuenca) ni al ICEN (costero); los combina con SOI, D20 y u850 para
        ofrecer una visión integrada del estado del sistema ENSO. Las alertas oficiales provienen de
        ENFEN y NOAA/CPC.
      </InfoNote>

      {/* Valor actual */}
      <div className="grid gap-4 md:grid-cols-3">
        <SectionCard title={<span className="flex items-center gap-2"><Layers className="h-4 w-4" /> Índice compuesto actual</span>}>
          <p className="text-[11px] text-muted-foreground">{fmtMonth(latestIdx.month)}</p>
          <BigValue
            value={`${latestIdx.value > 0 ? "+" : ""}${latestIdx.value.toFixed(2)}`}
            tone={latestIdx.value > 0.3 ? "warm" : latestIdx.value < -0.3 ? "cool" : "neutral"}
          />
          <StatusPill
            label={latestIdx.category}
            tone={latestIdx.value > 0.3 ? "warm" : latestIdx.value < -0.3 ? "cool" : "neutral"}
          />
          <p className="mt-2 text-[11px] text-muted-foreground">Índice adimensional (típico −3..+3)</p>
        </SectionCard>

        <SectionCard title="Componentes actuales (normalizados)">
          <div className="space-y-1.5 text-xs">
            <ComponentBar label="Niño 3.4 (cuenca)" value={latestIdx.components.nino34} weight={0.30} />
            <ComponentBar label="Niño 1+2 (costero)" value={latestIdx.components.nino12} weight={0.25} />
            <ComponentBar label="SOI (invertido)" value={latestIdx.components.soi} weight={0.20} />
            <ComponentBar label="D20 (termoclina)" value={latestIdx.components.d20} weight={0.15} />
            <ComponentBar label="u850 (viento)" value={latestIdx.components.u850} weight={0.10} />
          </div>
        </SectionCard>

        <SectionCard title="Ponderación">
          <div className="space-y-1 text-xs">
            <FieldLine label="Niño 3.4 (cuenca oceánica)">30%</FieldLine>
            <FieldLine label="Niño 1+2 (costero oceánico)">25%</FieldLine>
            <FieldLine label="SOI (atmosférica, invertido)">20%</FieldLine>
            <FieldLine label="D20 (termoclina)">15%</FieldLine>
            <FieldLine label="u850 (viento zonal)">10%</FieldLine>
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground border-t pt-2">
            Cada componente se normaliza por su escala típica antes de ponderar.
          </p>
        </SectionCard>
      </div>

      {/* Serie temporal */}
      <SectionCard
        title={<span className="flex items-center gap-2"><TrendingUp className="h-4 w-4" /> Serie temporal del índice compuesto</span>}
        description="Últimos 10 años. Bandas de categoría (Neutral ±0.3, evento ±0.8, fuerte ±1.5). Interpretación del observatorio."
      >
        <EnsoTimeSeries
          series={[{
            id: "composite",
            label: "Índice compuesto ENSO",
            color: "var(--enso-basin)",
            data: recent.map((r) => ({ month: r.month, value: r.value, flag: "final" as const })),
          }]}
          units="degC" yLabel="Índice" height={320}
          thresholds={[
            { min: 1.5, max: 999, label: "El Niño fuerte", color: "var(--enso-warm)", fillOpacity: 0.1 },
            { min: 0.8, max: 1.5, label: "El Niño", color: "var(--enso-warm)", fillOpacity: 0.07 },
            { min: -0.3, max: 0.3, label: "Neutral", color: "var(--muted-foreground)", fillOpacity: 0.05 },
            { min: -1.5, max: -0.8, label: "La Niña", color: "var(--enso-cool)", fillOpacity: 0.07 },
            { min: -999, max: -1.5, label: "La Niña fuerte", color: "var(--enso-cool)", fillOpacity: 0.1 },
          ]}
        />
      </SectionCard>

      {/* Serie larga */}
      <SectionCard title="Serie larga (1990–2026)" description="Historia completa del índice compuesto. Identifique eventos intensos.">
        <EnsoTimeSeries
          series={[{
            id: "composite",
            label: "Índice compuesto",
            color: "var(--enso-basin)",
            data: index.map((r) => ({ month: r.month, value: r.value, flag: "final" as const })),
          }]}
          units="degC" yLabel="Índice" height={260}
          thresholds={[
            { min: 0.8, max: 999, label: "Cálido", color: "var(--enso-warm)", fillOpacity: 0.07 },
            { min: -999, max: -0.8, label: "Frío", color: "var(--enso-cool)", fillOpacity: 0.07 },
          ]}
        />
      </SectionCard>

      {/* Tabla de eventos intensos */}
      <SectionCard title="Meses con índice extremo (|valor| ≥ 1.5)" description="Ordenados por valor absoluto descendente. Interpretación del observatorio.">
        <div className="max-h-80 overflow-y-auto enso-scroll rounded-md border">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-muted/80 backdrop-blur">
              <tr className="text-left">
                <th className="px-2 py-1.5 font-medium">Mes</th>
                <th className="px-2 py-1.5 font-medium text-right">Índice</th>
                <th className="px-2 py-1.5 font-medium">Categoría</th>
                <th className="px-2 py-1.5 font-medium">Niño 3.4</th>
                <th className="px-2 py-1.5 font-medium">Niño 1+2</th>
                <th className="px-2 py-1.5 font-medium">SOI</th>
                <th className="px-2 py-1.5 font-medium">D20</th>
                <th className="px-2 py-1.5 font-medium">u850</th>
              </tr>
            </thead>
            <tbody>
              {index.filter((r) => Math.abs(r.value) >= 1.5).sort((a, b) => Math.abs(b.value) - Math.abs(a.value)).slice(0, 30).map((r) => (
                <tr key={r.month} className="border-b last:border-0 hover:bg-muted/40">
                  <td className="px-2 py-1.5 font-medium enso-num">{fmtMonth(r.month)}</td>
                  <td className="px-2 py-1.5 text-right enso-num font-bold" style={{ color: r.value > 0 ? "var(--enso-warm)" : "var(--enso-cool)" }}>
                    {r.value > 0 ? "+" : ""}{r.value.toFixed(2)}
                  </td>
                  <td className="px-2 py-1.5">{r.category}</td>
                  <td className="px-2 py-1.5 text-right enso-num">{r.components.nino34 > 0 ? "+" : ""}{r.components.nino34.toFixed(2)}</td>
                  <td className="px-2 py-1.5 text-right enso-num">{r.components.nino12 > 0 ? "+" : ""}{r.components.nino12.toFixed(2)}</td>
                  <td className="px-2 py-1.5 text-right enso-num">{r.components.soi > 0 ? "+" : ""}{r.components.soi.toFixed(2)}</td>
                  <td className="px-2 py-1.5 text-right enso-num">{r.components.d20 > 0 ? "+" : ""}{r.components.d20.toFixed(2)}</td>
                  <td className="px-2 py-1.5 text-right enso-num">{r.components.u850 > 0 ? "+" : ""}{r.components.u850.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>

      <InfoNote tone="muted" title="Metodología del índice compuesto">
        <div className="space-y-1">
          <p>El índice se calcula como:</p>
          <p className="font-mono text-[11px] bg-muted/50 rounded p-2">
            I = 0.30·(Niño 3.4/1.0) + 0.25·(Niño 1+2/1.2) − 0.20·(SOI/1.5) + 0.15·(D20/8.0) + 0.10·(u850/2.0)
          </p>
          <p>
            El SOI se invierte (negativo → cálido) por ser la componente atmosférica. Las escalas
            normalizan cada componente a su variabilidad típica. Los meses con datos faltantes se
            omiten (sin interpolación). Las categorías: Neutral (|I|&lt;0.3), Tendencia (0.3–0.8),
            Evento (0.8–1.5), Fuerte (≥1.5).
          </p>
        </div>
      </InfoNote>
    </div>
  );
}

function ComponentBar({ label, value, weight }: { label: string; value: number; weight: number }) {
  const max = 3;
  const pct = Math.min(100, (Math.abs(value) / max) * 100);
  const color = value > 0 ? "var(--enso-warm)" : value < 0 ? "var(--enso-cool)" : "var(--muted-foreground)";
  return (
    <div>
      <div className="flex items-center justify-between text-[11px]">
        <span className="text-muted-foreground">{label} <span className="text-[10px]">({Math.round(weight * 100)}%)</span></span>
        <span className="font-medium enso-num" style={{ color }}>{value > 0 ? "+" : ""}{value.toFixed(2)}</span>
      </div>
      <div className="mt-0.5 h-1.5 w-full rounded-full bg-muted overflow-hidden flex">
        <div className="flex-1 flex justify-end">
          {value < 0 && <div className="h-full rounded-l-full" style={{ width: `${pct / 2}%`, background: color }} />}
        </div>
        <div className="w-px bg-foreground/30" />
        <div className="flex-1">
          {value > 0 && <div className="h-full rounded-r-full" style={{ width: `${pct / 2}%`, background: color }} />}
        </div>
      </div>
    </div>
  );
}
