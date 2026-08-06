"use client";

import * as React from "react";
import { generateAllSeries, latest } from "@/lib/enso/series";
import { icenCategory, roniCategory } from "@/lib/enso/derived";
import { INDICATOR_BY_ID } from "@/lib/enso/methodology";
import { EnsoTimeSeries, SimpleBars, MonthlyHeatmap } from "./charts";
import { SectionCard, ScopeBadge, StatusPill, InfoNote, BigValue, FieldLine } from "./primitives";
import { fmtMonth, fmtValue, COLOR_COASTAL, COLOR_BASIN } from "@/lib/enso/ui";

export function SstView() {
  const all = generateAllSeries();
  const n12 = latest(all.nino12);
  const n34 = latest(all.nino34);
  const icen = latest(all.icen);
  const roni = latest(all.roni);

  // Últimos 24 meses para barras de ICEN/RONI
  const icenBars = all.icen.points.slice(-24).map((p) => ({ label: fmtMonth(p.month).slice(0, 6), value: p.value }));
  const roniBars = all.roni.points.slice(-24).map((p) => ({ label: fmtMonth(p.month).slice(0, 6), value: p.value }));

  return (
    <div className="space-y-5">
      <InfoNote tone="info" title="Anomalía de la temperatura superficial del mar (TSM)">
        Se muestran dos escalas separadas: <strong>costera</strong> (Niño 1+2, ICEN) y <strong>de
        cuenca</strong> (Niño 3.4, RONI). Un evento puede ocurrir en una escala sin presentarse en la
        otra. Las anomalías se reportan en grados Celsius respecto a la climatología de cada fuente.
      </InfoNote>

      {/* Comparación costero vs cuenca */}
      <SectionCard
        title="Comparación costero vs cuenca"
        description="Niño 1+2 (costero, ámbar) y Niño 3.4 (cuenca, teal). Bandas de umbral ±0.5 °C."
      >
        <EnsoTimeSeries
          series={[
            { id: "nino12", label: "Niño 1+2 (costero)", color: COLOR_COASTAL, data: all.nino12.points },
            { id: "nino34", label: "Niño 3.4 (cuenca)", color: COLOR_BASIN, data: all.nino34.points },
          ]}
          units="degC"
          yLabel="°C"
          thresholds={[
            { min: 0.5, max: 999, label: "El Niño", color: "var(--enso-warm)", fillOpacity: 0.08 },
            { min: -999, max: -0.5, label: "La Niña", color: "var(--enso-cool)", fillOpacity: 0.08 },
          ]}
          height={340}
        />
      </SectionCard>

      {/* Detalle costero */}
      <div className="grid gap-4 lg:grid-cols-2">
        <SectionCard
          title={<span className="flex items-center gap-2">TSM Niño 1+2 e ICEN <ScopeBadge scope="coastal" /></span>}
          description="Región 90–80°O, 10°S–0°. ICEN = media móvil de 3 meses (metodología ENFEN)."
        >
          <div className="mb-3 grid grid-cols-2 gap-3">
            <div>
              <p className="text-[11px] text-muted-foreground">TSM Niño 1+2 ({fmtMonth(n12?.point.month ?? "")})</p>
              <BigValue value={fmtValue(n12?.point.value ?? null, "degC").replace(" °C", "")} units="°C" tone="warm" />
            </div>
            <div>
              <p className="text-[11px] text-muted-foreground">ICEN (media móvil 3 meses)</p>
              <BigValue value={fmtValue(icen?.point.value ?? null, "degC").replace(" °C", "")} units="°C" tone="warm" />
              <StatusPill label={icenCategory(icen?.point.value ?? null)} tone="warm" />
            </div>
          </div>
          <SimpleBars data={icenBars} color={COLOR_COASTAL} units="degC" height={180} />
          <p className="mt-2 text-[11px] text-muted-foreground">
            Categorías de intensidad según metodología ENFEN documentada. La activación de un evento
            costero requiere persistencia (3 meses consecutivos). <em>Interpretación generada por el observatorio.</em>
          </p>
        </SectionCard>

        {/* Detalle cuenca */}
        <SectionCard
          title={<span className="flex items-center gap-2">TSM Niño 3.4 y RONI <ScopeBadge scope="basin" /></span>}
          description="Región 5°S–5°N, 120–170°O. RONI = media móvil de 3 meses con baseline adaptativa (NOAA/CPC)."
        >
          <div className="mb-3 grid grid-cols-2 gap-3">
            <div>
              <p className="text-[11px] text-muted-foreground">TSM Niño 3.4 ({fmtMonth(n34?.point.month ?? "")})</p>
              <BigValue value={fmtValue(n34?.point.value ?? null, "degC").replace(" °C", "")} units="°C" tone="warm" />
            </div>
            <div>
              <p className="text-[11px] text-muted-foreground">RONI (media móvil 3 meses)</p>
              <BigValue value={fmtValue(roni?.point.value ?? null, "degC").replace(" °C", "")} units="°C" tone="warm" />
              <StatusPill label={roniCategory(roni?.point.value ?? null)} tone="warm" />
            </div>
          </div>
          <SimpleBars data={roniBars} color={COLOR_BASIN} units="degC" height={180} />
          <p className="mt-2 text-[11px] text-muted-foreground">
            RONI es el índice operacional actual de NOAA/CPC (no el ONI heredado de base 1971–2000).
            Umbral operativo ±0.5 °C sostenido.
          </p>
        </SectionCard>
      </div>

      {/* Series largas */}
      <div className="grid gap-4 lg:grid-cols-2">
        <SectionCard title="Serie larga — Niño 1+2 (costero)" description={`${INDICATOR_BY_ID.nino12.climatology} · ${INDICATOR_BY_ID.nino12.dataset}`}>
          <EnsoTimeSeries
            series={[{ id: "nino12", label: "Niño 1+2", color: COLOR_COASTAL, data: all.nino12.points }]}
            units="degC" yLabel="°C" height={240}
            thresholds={[
              { min: 0.5, max: 999, label: "Cálido", color: "var(--enso-warm)", fillOpacity: 0.08 },
              { min: -999, max: -0.5, label: "Frío", color: "var(--enso-cool)", fillOpacity: 0.08 },
            ]}
          />
        </SectionCard>
        <SectionCard title="Serie larga — Niño 3.4 (cuenca)" description={`${INDICATOR_BY_ID.nino34.climatology} · ${INDICATOR_BY_ID.nino34.dataset}`}>
          <EnsoTimeSeries
            series={[{ id: "nino34", label: "Niño 3.4", color: COLOR_BASIN, data: all.nino34.points }]}
            units="degC" yLabel="°C" height={240}
            thresholds={[
              { min: 0.5, max: 999, label: "El Niño", color: "var(--enso-warm)", fillOpacity: 0.08 },
              { min: -999, max: -0.5, label: "La Niña", color: "var(--enso-cool)", fillOpacity: 0.08 },
            ]}
          />
        </SectionCard>
      </div>

      {/* Mapas de calor mensuales */}
      <div className="grid gap-4 lg:grid-cols-2">
        <SectionCard title="Mapa de calor mensual — Niño 1+2 (costero)" description="Anomalía por año y mes (últimos 15 años).">
          <div className="overflow-x-auto enso-scroll">
            <MonthlyHeatmap series={all.nino12} scale={2.5} />
          </div>
        </SectionCard>
        <SectionCard title="Mapa de calor mensual — Niño 3.4 (cuenca)" description="Anomalía por año y mes (últimos 15 años).">
          <div className="overflow-x-auto enso-scroll">
            <MonthlyHeatmap series={all.nino34} scale={2.5} />
          </div>
        </SectionCard>
      </div>

      {/* Metadatos */}
      <SectionCard title="Metadatos de las series de TSM">
        <div className="grid gap-4 md:grid-cols-2 text-xs">
          <div>
            <FieldLine label="Indicador">{INDICATOR_BY_ID.nino12.name}</FieldLine>
            <FieldLine label="Región">{INDICATOR_BY_ID.nino12.region}</FieldLine>
            <FieldLine label="Agregación">{INDICATOR_BY_ID.nino12.aggregation}</FieldLine>
            <FieldLine label="Climatología">{INDICATOR_BY_ID.nino12.climatology}</FieldLine>
            <FieldLine label="Dataset">{INDICATOR_BY_ID.nino12.dataset}</FieldLine>
          </div>
          <div>
            <FieldLine label="Indicador">{INDICATOR_BY_ID.nino34.name}</FieldLine>
            <FieldLine label="Región">{INDICATOR_BY_ID.nino34.region}</FieldLine>
            <FieldLine label="Agregación">{INDICATOR_BY_ID.nino34.aggregation}</FieldLine>
            <FieldLine label="Climatología">{INDICATOR_BY_ID.nino34.climatology}</FieldLine>
            <FieldLine label="Dataset">{INDICATOR_BY_ID.nino34.dataset}</FieldLine>
          </div>
        </div>
      </SectionCard>
    </div>
  );
}
