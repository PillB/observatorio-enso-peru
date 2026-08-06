"use client";

import * as React from "react";
import { generateAllSeries, latest } from "@/lib/enso/series";
import { u850Direction } from "@/lib/enso/derived";
import { INDICATOR_BY_ID } from "@/lib/enso/methodology";
import { EnsoTimeSeries, MonthlyHeatmap } from "./charts";
import { SectionCard, ScopeBadge, InfoNote, BigValue, FieldLine, StatusPill } from "./primitives";
import { fmtMonth, fmtValue, COLOR_BASIN } from "@/lib/enso/ui";
import { ArrowRight, ArrowLeft } from "lucide-react";

export function WindsView() {
  const all = generateAllSeries();
  const u850 = latest(all.u850);
  const dir = u850Direction(u850?.point.value ?? null);

  return (
    <div className="space-y-5">
      <InfoNote tone="info" title="Convención del viento zonal">
        Para la componente zonal <strong>u</strong>: <strong>u &gt; 0</strong> significa flujo hacia
        el <strong>este</strong> (componente del oeste / <em>westerly</em>); <strong>u &lt; 0</strong>
        significa flujo hacia el <strong>oeste</strong> (componente del este / <em>easterly</em>). Se
        distingue el <strong>valor observado</strong> de la <strong>anomalía</strong>, y el viento de
        <strong> superficie (10 m)</strong> del de <strong>bajo nivel (850 hPa)</strong>. No se
        etiqueta todo viento costero como «alisios»: se respeta la terminología de la fuente.
      </InfoNote>

      <SectionCard
        title={<span className="flex items-center gap-2">Anomalía del viento zonal a 850 hPa <ScopeBadge scope="basin" /></span>}
        description="Promedio ecuatorial (5°S–5°N). Fuente: NOAA/CPC (NCEP/NCAR Reanalysis)."
        right={<StatusPill label={dir.label} tone={dir.signMeaning.includes("oeste") ? "warm" : dir.signMeaning.includes("este") ? "cool" : "neutral"} />}
      >
        <div className="mb-3 grid grid-cols-2 gap-4">
          <div>
            <p className="text-[11px] text-muted-foreground">Último valor ({fmtMonth(u850?.point.month ?? "")})</p>
            <BigValue value={fmtValue(u850?.point.value ?? null, "m_per_s").replace(" m/s", "")} units="m/s" tone={dir.signMeaning.includes("oeste") ? "warm" : dir.signMeaning.includes("este") ? "cool" : "neutral"} />
          </div>
          <div>
            <p className="text-[11px] text-muted-foreground">Interpretación</p>
            <p className="text-sm font-medium leading-snug">{dir.label}</p>
          </div>
        </div>
        <EnsoTimeSeries
          series={[{ id: "u850", label: "u850 (anomalía)", color: COLOR_BASIN, data: all.u850.points }]}
          units="m_per_s" yLabel="m/s" height={320}
          thresholds={[
            { min: 0.5, max: 999, label: "Anomalía del oeste (westerly)", color: "var(--enso-warm)", fillOpacity: 0.08 },
            { min: -999, max: -0.5, label: "Anomalía del este (easterly)", color: "var(--enso-cool)", fillOpacity: 0.08 },
          ]}
        />
      </SectionCard>

      {/* Leyenda de dirección */}
      <SectionCard title="Lectura de la dirección del viento zonal">
        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-lg border border-[color:var(--enso-warm)]/30 bg-[color:var(--enso-warm)]/5 p-3">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <ArrowRight className="h-4 w-4" /> u &gt; 0
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              <strong>Flujo hacia el este</strong> · componente del <strong>oeste</strong> (westerly).
              Anomalía típica de El Niño de cuenca: favorece el desplazamiento hacia el este de la
              masa de agua cálida.
            </p>
          </div>
          <div className="rounded-lg border border-[color:var(--enso-cool)]/30 bg-[color:var(--enso-cool)]/5 p-3">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <ArrowLeft className="h-4 w-4" /> u &lt; 0
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              <strong>Flujo hacia el oeste</strong> · componente del <strong>este</strong> (easterly).
              Anomalía típica de La Niña de cuenca: refuerza el transporte ecuatorial hacia el oeste.
            </p>
          </div>
        </div>
      </SectionCard>

      {/* Heatmap */}
      <SectionCard title="Mapa de calor mensual — anomalía u850" description="Últimos 15 años. Escala ±6 m/s.">
        <div className="overflow-x-auto enso-scroll">
          <MonthlyHeatmap series={all.u850} scale={6} />
        </div>
      </SectionCard>

      {/* Metadatos */}
      <SectionCard title="Metadatos del indicador de viento">
        <div className="grid gap-4 md:grid-cols-2 text-xs">
          <div>
            <FieldLine label="Indicador">{INDICATOR_BY_ID.u850.name}</FieldLine>
            <FieldLine label="Nivel">{INDICATOR_BY_ID.u850.level}</FieldLine>
            <FieldLine label="Región">{INDICATOR_BY_ID.u850.region}</FieldLine>
            <FieldLine label="Agregación">{INDICATOR_BY_ID.u850.aggregation}</FieldLine>
          </div>
          <div>
            <FieldLine label="Climatología">{INDICATOR_BY_ID.u850.climatology}</FieldLine>
            <FieldLine label="Dataset">{INDICATOR_BY_ID.u850.dataset}</FieldLine>
            <FieldLine label="Unidades">m/s (anomalía)</FieldLine>
            <FieldLine label="Convención">{INDICATOR_BY_ID.u850.signConvention.slice(0, 80)}…</FieldLine>
          </div>
        </div>
      </SectionCard>
    </div>
  );
}
