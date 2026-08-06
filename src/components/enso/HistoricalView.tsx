"use client";

import * as React from "react";
import { generateAllSeries, MONTHS } from "@/lib/enso/series";
import { HISTORICAL_EVENTS, percentile } from "@/lib/enso/derived";
import { EnsoTimeSeries } from "./charts";
import { SectionCard, ScopeBadge, InfoNote, StatusPill } from "./primitives";
import { fmtValue, COLOR_COASTAL, COLOR_BASIN } from "@/lib/enso/ui";
import { valueAt } from "@/lib/enso/series";

export function HistoricalView() {
  const all = generateAllSeries();

  return (
    <div className="space-y-5">
      <InfoNote tone="info" title="Comparación histórica de eventos ENSO">
        Cada evento se etiqueta como <strong>de cuenca</strong>, <strong>costero</strong> o{" "}
        <strong>mixto</strong>. El caso de 2017 es paradigmático: El Niño Costero fuerte{" "}
        <strong>sin</strong> El Niño de cuenca. Los valores de pico provienen de las series
        normalizadas del observatorio.
      </InfoNote>

      {/* Tabla de eventos */}
      <SectionCard title="Eventos ENSO destacados (1990–2026)">
        <div className="overflow-x-auto enso-scroll">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="py-2 pr-3 font-medium">Evento</th>
                <th className="py-2 pr-3 font-medium">Tipo</th>
                <th className="py-2 pr-3 font-medium">Inicio</th>
                <th className="py-2 pr-3 font-medium">Pico</th>
                <th className="py-2 pr-3 font-medium">Niño 3.4 pico</th>
                <th className="py-2 pr-3 font-medium">Niño 1+2 pico</th>
                <th className="py-2 font-medium">Nota</th>
              </tr>
            </thead>
            <tbody>
              {HISTORICAL_EVENTS.map((e) => (
                <tr key={e.id} className="border-b last:border-0">
                  <td className="py-2 pr-3 font-medium">{e.label}</td>
                  <td className="py-2 pr-3">
                    {e.type === "coastal" ? <ScopeBadge scope="coastal" /> : e.type === "basin" ? <ScopeBadge scope="basin" /> : <span className="text-[10px] font-medium uppercase">Mixto</span>}
                  </td>
                  <td className="py-2 pr-3 enso-num">{e.startMonth}</td>
                  <td className="py-2 pr-3 enso-num">{e.peakMonth}</td>
                  <td className="py-2 pr-3 enso-num">{fmtValue(e.peakNino34, "degC")}</td>
                  <td className="py-2 pr-3 enso-num">{fmtValue(e.peakNino12, "degC")}</td>
                  <td className="py-2 text-muted-foreground">{e.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>

      {/* Comparación costero vs cuenca completa */}
      <SectionCard title="Serie completa 1990–2026" description="Niño 1+2 (costero) vs Niño 3.4 (cuenca). Identifique eventos donde ambas escalas difieren.">
        <EnsoTimeSeries
          series={[
            { id: "nino12", label: "Niño 1+2 (costero)", color: COLOR_COASTAL, data: all.nino12.points },
            { id: "nino34", label: "Niño 3.4 (cuenca)", color: COLOR_BASIN, data: all.nino34.points },
          ]}
          units="degC" yLabel="°C" height={340}
          thresholds={[
            { min: 0.5, max: 999, label: "Cálido", color: "var(--enso-warm)", fillOpacity: 0.07 },
            { min: -999, max: -0.5, label: "Frío", color: "var(--enso-cool)", fillOpacity: 0.07 },
          ]}
        />
      </SectionCard>

      {/* Percentiles actuales */}
      <SectionCard title="Percentiles históricos del valor más reciente" description="Posición del último valor respecto a toda la historia de cada indicador.">
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {Object.values(all).map((s) => {
            const last = s.points[s.points.length - 1];
            const p = percentile(s, last.value);
            const tone = last.value === null ? "neutral" : (last.value > 0 ? "warm" : "cool");
            return (
              <div key={s.indicatorId} className="rounded-lg border p-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium">{s.label}</span>
                  <ScopeBadge scope={s.scope} />
                </div>
                <p className="mt-1 text-lg font-bold enso-num">{fmtValue(last.value, s.units)}</p>
                <div className="mt-1 flex items-center justify-between">
                  <span className="text-[11px] text-muted-foreground">Percentil</span>
                  <StatusPill label={p === null ? "n/d" : `P${p}`} tone={tone} />
                </div>
                <div className="mt-2 h-1.5 w-full rounded-full bg-muted">
                  <div
                    className="h-1.5 rounded-full"
                    style={{
                      width: `${p ?? 0}%`,
                      background: last.value && last.value > 0 ? "var(--enso-warm)" : "var(--enso-cool)",
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </SectionCard>

      {/* Eventos específicos: 2017 */}
      <SectionCard title="Caso 2017: El Niño Costero sin El Niño de cuenca" description="Ventana 2016-09 a 2017-12. La costa se calienta fuertemente mientras el Pacífico central permanece neutral.">
        <EventWindow start="2016-09" end="2017-12" />
      </SectionCard>
    </div>
  );
}

function EventWindow({ start, end }: { start: string; end: string }) {
  const all = generateAllSeries();
  const startIdx = MONTHS.indexOf(start);
  const endIdx = MONTHS.indexOf(end);
  const n12 = all.nino12.points.slice(startIdx, endIdx + 1);
  const n34 = all.nino34.points.slice(startIdx, endIdx + 1);
  return (
    <EnsoTimeSeries
      series={[
        { id: "nino12", label: "Niño 1+2 (costero)", color: COLOR_COASTAL, data: n12 },
        { id: "nino34", label: "Niño 3.4 (cuenca)", color: COLOR_BASIN, data: n34 },
      ]}
      units="degC" yLabel="°C" height={260}
      thresholds={[
        { min: 0.5, max: 999, label: "Cálido", color: "var(--enso-warm)", fillOpacity: 0.08 },
        { min: -999, max: -0.5, label: "Frío", color: "var(--enso-cool)", fillOpacity: 0.08 },
      ]}
    />
  );
}
