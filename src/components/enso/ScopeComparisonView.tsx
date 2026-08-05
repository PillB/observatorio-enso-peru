"use client";

import * as React from "react";
import { buildScopeComparison, buildCurrentStatus, type ScopeComparison } from "@/lib/enso/derived";
import { generateAllSeries, MONTHS } from "@/lib/enso/series";
import { SectionCard, ScopeBadge, InfoNote, BigValue, StatusPill, FieldLine } from "./primitives";
import { EnsoTimeSeries } from "./charts";
import { fmtMonth, fmtValue, COLOR_COASTAL, COLOR_BASIN } from "@/lib/enso/ui";
import { Columns2, GitCompare, Waves, Gauge } from "lucide-react";

export function ScopeComparisonView() {
  const comparisons = React.useMemo(() => buildScopeComparison(), []);
  const status = React.useMemo(() => buildCurrentStatus(), []);
  const all = React.useMemo(() => generateAllSeries(), []);
  const recent = all.nino12.points.slice(-120);
  const recent34 = all.nino34.points.slice(-120);

  return (
    <div className="space-y-5">
      <InfoNote tone="info" title="Comparación costero vs cuenca — panel lado a lado">
        El Niño Costero (escala del Pacífico oriental frente a Perú, monitoreado por ENFEN vía ICEN
        sobre Niño 1+2) y el ENSO de cuenca (Pacífico ecuatorial, monitoreado por NOAA/CPC vía RONI
        sobre Niño 3.4) son conceptos distintos. Pueden coexistir o presentarse por separado (caso
        paradigmático: 2017, costero fuerte sin cuenca).
      </InfoNote>

      {/* Panel lado a lado: estado actual */}
      <div className="grid gap-4 md:grid-cols-2">
        {/* Costero */}
        <SectionCard
          title={<span className="flex items-center gap-2"><Waves className="h-4 w-4" /> El Niño Costero</span>}
          right={<ScopeBadge scope="coastal" />}
          className="border-l-4 border-l-[color:var(--enso-coastal)]"
        >
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <StatusPill label={status.coastal.alert} tone="warm" />
              <span className="text-[11px] text-muted-foreground">desde {fmtMonth(status.coastal.alertSince ?? "")}</span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="text-[11px] text-muted-foreground">ICEN ({status.coastal.icenWindow})</p>
                <BigValue value={fmtValue(status.coastal.icen, "degC").replace(" °C", "")} units="°C" tone="warm" />
              </div>
              <div>
                <p className="text-[11px] text-muted-foreground">Niño 1+2 ({fmtMonth(status.coastal.nino12Month)})</p>
                <BigValue value={fmtValue(status.coastal.nino12Anom, "degC").replace(" °C", "")} units="°C" tone="warm" />
              </div>
            </div>
            <div className="space-y-1 text-xs">
              <FieldLine label="Categoría derivada">{status.coastal.icenCategory}</FieldLine>
              <FieldLine label="Umbral de activación">±0.4 °C (ICEN)</FieldLine>
              <FieldLine label="Persistencia">3 meses consecutivos</FieldLine>
              <FieldLine label="Fuente oficial">ENFEN / IMARPE</FieldLine>
              <FieldLine label="Región">Niño 1+2 (90–80°O, 10°S–0°)</FieldLine>
            </div>
            <div className="border-t pt-2">
              <EnsoTimeSeries
                series={[{ id: "nino12", label: "Niño 1+2 (costero)", color: COLOR_COASTAL, data: recent }]}
                units="degC" yLabel="°C" height={140} windowMonths={120}
                thresholds={[
                  { min: 0.4, max: 999, label: "Umbral", color: "var(--enso-warm)", fillOpacity: 0.08 },
                  { min: -999, max: -0.4, label: "Umbral", color: "var(--enso-cool)", fillOpacity: 0.08 },
                ]}
              />
            </div>
          </div>
        </SectionCard>

        {/* Cuenca */}
        <SectionCard
          title={<span className="flex items-center gap-2"><Gauge className="h-4 w-4" /> ENSO de cuenca</span>}
          right={<ScopeBadge scope="basin" />}
          className="border-l-4 border-l-[color:var(--enso-basin)]"
        >
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <StatusPill label={status.basin.alert} tone="warm" />
              <span className="text-[11px] text-muted-foreground">desde {fmtMonth(status.basin.alertSince ?? "")}</span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="text-[11px] text-muted-foreground">RONI ({status.basin.roniWindow})</p>
                <BigValue value={fmtValue(status.basin.roni, "degC").replace(" °C", "")} units="°C" tone="warm" />
              </div>
              <div>
                <p className="text-[11px] text-muted-foreground">Niño 3.4 ({fmtMonth(status.basin.nino34Month)})</p>
                <BigValue value={fmtValue(status.basin.nino34Anom, "degC").replace(" °C", "")} units="°C" tone="warm" />
              </div>
            </div>
            <div className="space-y-1 text-xs">
              <FieldLine label="Categoría derivada">{status.basin.roniCategory}</FieldLine>
              <FieldLine label="Umbral de activación">±0.5 °C (RONI)</FieldLine>
              <FieldLine label="Persistencia">3 meses consecutivos</FieldLine>
              <FieldLine label="Fuente oficial">NOAA / CPC</FieldLine>
              <FieldLine label="Región">Niño 3.4 (5°S–5°N, 120–170°O)</FieldLine>
            </div>
            <div className="border-t pt-2">
              <EnsoTimeSeries
                series={[{ id: "nino34", label: "Niño 3.4 (cuenca)", color: COLOR_BASIN, data: recent34 }]}
                units="degC" yLabel="°C" height={140} windowMonths={120}
                thresholds={[
                  { min: 0.5, max: 999, label: "Umbral", color: "var(--enso-warm)", fillOpacity: 0.08 },
                  { min: -999, max: -0.5, label: "Umbral", color: "var(--enso-cool)", fillOpacity: 0.08 },
                ]}
              />
            </div>
          </div>
        </SectionCard>
      </div>

      {/* Serie comparada */}
      <SectionCard
        title={<span className="flex items-center gap-2"><Columns2 className="h-4 w-4" /> Serie comparada (últimos 10 años)</span>}
        description="Niño 1+2 (costero, ámbar) vs Niño 3.4 (cuenca, teal). Identifique periodos de divergencia."
      >
        <EnsoTimeSeries
          series={[
            { id: "nino12", label: "Niño 1+2 (costero)", color: COLOR_COASTAL, data: recent },
            { id: "nino34", label: "Niño 3.4 (cuenca)", color: COLOR_BASIN, data: recent34 },
          ]}
          units="degC" yLabel="°C" height={280} windowMonths={120}
          thresholds={[
            { min: 0.5, max: 999, label: "El Niño", color: "var(--enso-warm)", fillOpacity: 0.06 },
            { min: -999, max: -0.5, label: "La Niña", color: "var(--enso-cool)", fillOpacity: 0.06 },
          ]}
        />
      </SectionCard>

      {/* Tabla de métricas comparativas */}
      <SectionCard
        title={<span className="flex items-center gap-2"><GitCompare className="h-4 w-4" /> Métricas comparativas</span>}
        description="Comparación lado a lado de métricas clave entre las dos escalas."
      >
        <div className="overflow-x-auto enso-scroll">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="py-2 pr-3 font-medium">Métrica</th>
                <th className="py-2 pr-3 font-medium"><span className="flex items-center gap-1"><ScopeBadge scope="coastal" /> Costero</span></th>
                <th className="py-2 pr-3 font-medium"><span className="flex items-center gap-1"><ScopeBadge scope="basin" /> Cuenca</span></th>
                <th className="py-2 font-medium">Nota</th>
              </tr>
            </thead>
            <tbody>
              {comparisons.map((c, i) => (
                <tr key={i} className="border-b last:border-0 hover:bg-muted/40">
                  <td className="py-2 pr-3 font-medium">{c.metric}</td>
                  <td className="py-2 pr-3 enso-num" style={{ color: typeof c.coastal === "number" && c.coastal > 0 ? "var(--enso-warm)" : undefined }}>{c.coastal}</td>
                  <td className="py-2 pr-3 enso-num" style={{ color: typeof c.basin === "number" && c.basin > 0 ? "var(--enso-warm)" : undefined }}>{c.basin}</td>
                  <td className="py-2 text-muted-foreground text-[11px]">{c.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>

      <InfoNote tone="muted" title="Clave de interpretación">
        <ul className="space-y-1 list-disc pl-4">
          <li><strong>Convergencia</strong>: ambas escalas en la misma fase (ej. 1997-98, El Niño muy fuerte en ambas).</li>
          <li><strong>Divergencia costera</strong>: costero activo sin cuenca (ej. 2017, El Niño Costero fuerte sin El Niño de cuenca).</li>
          <li><strong>Divergencia de cuenca</strong>: cuenca activa sin costero (más frecuente; la cuenca no siempre se expresa en la costa peruana).</li>
          <li>Los umbrales difieren: ±0.4 °C (ICEN) vs ±0.5 °C (RONI), pero ambos requieren 3 meses consecutivos.</li>
        </ul>
      </InfoNote>
    </div>
  );
}
