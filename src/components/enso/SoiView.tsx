"use client";

import * as React from "react";
import { generateAllSeries, latest } from "@/lib/enso/series";
import { soiCategory } from "@/lib/enso/derived";
import { INDICATOR_BY_ID } from "@/lib/enso/methodology";
import { EnsoTimeSeries, MonthlyHeatmap } from "./charts";
import { SectionCard, ScopeBadge, InfoNote, BigValue, FieldLine, StatusPill } from "./primitives";
import { fmtMonth, fmtValue, COLOR_BASIN } from "@/lib/enso/ui";

export function SoiView() {
  const all = generateAllSeries();
  const soi = latest(all.soi);

  return (
    <div className="space-y-5">
      <InfoNote tone="warn" title="SOI: índice de escala de cuenca. No existe «SOI costero»">
        El Índice de Oscilación del Sur (SOI) es la anomalía estandarizada de la diferencia de
        presión superficial media entre <strong>Tahiti</strong> y <strong>Darwin</strong>. Es la
        componente atmosférica del ENSO y se interpreta a <strong>escala de cuenca</strong>. El
        observatorio <strong>NO define un «SOI costero»</strong>: no existe un proxy de presión
        costera con definición ni respaldo metodológico equivalente. La condición costera se monitorea
        con TSM Niño 1+2 e ICEN.
      </InfoNote>

      <SectionCard
        title={<span className="flex items-center gap-2">SOI — Oscilación del Sur <ScopeBadge scope="basin" /></span>}
        description="Anomalía estandarizada de la diferencia de presión (Tahiti − Darwin). Fuente: NOAA/PSL."
        right={<StatusPill label={soiCategory(soi?.point.value ?? null)} tone={soi?.point.value && soi.point.value < 0 ? "warm" : "cool"} />}
      >
        <div className="mb-3">
          <p className="text-[11px] text-muted-foreground">Último valor ({fmtMonth(soi?.point.month ?? "")})</p>
          <BigValue value={fmtValue(soi?.point.value ?? null, "dimensionless")} tone={soi?.point.value && soi.point.value < 0 ? "warm" : "cool"} />
          <p className="text-[11px] text-muted-foreground mt-1">{soiCategory(soi?.point.value ?? null)}</p>
        </div>
        <EnsoTimeSeries
          series={[{ id: "soi", label: "SOI", color: COLOR_BASIN, data: all.soi.points }]}
          units="dimensionless" yLabel="SOI" height={320}
          thresholds={[
            { min: -999, max: -0.5, label: "Componente de El Niño", color: "var(--enso-warm)", fillOpacity: 0.08 },
            { min: 0.5, max: 999, label: "Componente de La Niña", color: "var(--enso-cool)", fillOpacity: 0.08 },
          ]}
        />
      </SectionCard>

      <SectionCard title="Interpretación atmosférica">
        <div className="grid gap-3 md:grid-cols-2 text-xs">
          <div className="rounded-lg border border-[color:var(--enso-warm)]/30 bg-[color:var(--enso-warm)]/5 p-3">
            <p className="font-semibold">SOI negativo sostenido</p>
            <p className="mt-1 text-muted-foreground">
              Presión relativamente más baja en Tahiti que en Darwin. Componente atmosférica de{" "}
              <strong>El Niño</strong> de cuenca. Suele acompañar anomalías cálidas en Niño 3.4.
            </p>
          </div>
          <div className="rounded-lg border border-[color:var(--enso-cool)]/30 bg-[color:var(--enso-cool)]/5 p-3">
            <p className="font-semibold">SOI positivo sostenido</p>
            <p className="mt-1 text-muted-foreground">
              Presión relativamente más alta en Tahiti que en Darwin. Componente atmosférica de{" "}
              <strong>La Niña</strong> de cuenca. Suele acompañar anomalías frías en Niño 3.4.
            </p>
          </div>
        </div>
      </SectionCard>

      <SectionCard title="Correlación SOI vs Niño 3.4" description="Visualización conjunta: el SOI suele anticorrelacionarse con la TSM de Niño 3.4.">
        <EnsoTimeSeries
          series={[
            { id: "soi", label: "SOI (cuenca)", color: COLOR_BASIN, data: all.soi.points },
            { id: "nino34", label: "Niño 3.4 (°C)", color: "var(--enso-warm)", data: all.nino34.points },
          ]}
          units="dimensionless" height={260} windowMonths={120}
        />
        <p className="mt-2 text-[11px] text-muted-foreground">
          Nota: las unidades difieren (SOI adimensional vs °C); la gráfica es sólo cualitativa para
          mostrar la anticorrelación. Los valores exactos están en la vista de Datos.
        </p>
      </SectionCard>

      <SectionCard title="Mapa de calor mensual — SOI" description="Últimos 15 años. Escala ±3 (estandarizado).">
        <div className="overflow-x-auto enso-scroll">
          <MonthlyHeatmap series={all.soi} scale={3} />
        </div>
      </SectionCard>

      <SectionCard title="Metadatos del indicador SOI">
        <div className="grid gap-4 md:grid-cols-2 text-xs">
          <div>
            <FieldLine label="Indicador">{INDICATOR_BY_ID.soi.name}</FieldLine>
            <FieldLine label="Nivel">{INDICATOR_BY_ID.soi.level}</FieldLine>
            <FieldLine label="Región">{INDICATOR_BY_ID.soi.region}</FieldLine>
            <FieldLine label="Agregación">{INDICATOR_BY_ID.soi.aggregation}</FieldLine>
          </div>
          <div>
            <FieldLine label="Climatología">{INDICATOR_BY_ID.soi.climatology}</FieldLine>
            <FieldLine label="Dataset">{INDICATOR_BY_ID.soi.dataset}</FieldLine>
            <FieldLine label="Unidades">adimensional (estandarizado)</FieldLine>
            <FieldLine label="Definición">{INDICATOR_BY_ID.soi.signConvention.slice(0, 70)}…</FieldLine>
          </div>
        </div>
      </SectionCard>
    </div>
  );
}
