"use client";

import * as React from "react";
import { generateAllSeries, latest, MONTHS } from "@/lib/enso/series";
import { INDICATOR_BY_ID } from "@/lib/enso/methodology";
import { AnomalyMap } from "./charts";
import { SectionCard, ScopeBadge, InfoNote, FieldLine } from "./primitives";
import { fmtMonth } from "@/lib/enso/ui";

export function MapsView() {
  const all = generateAllSeries();
  const n12 = latest(all.nino12);
  const n34 = latest(all.nino34);
  const d20 = latest(all.d20);

  // Síntesis de celdas a partir de los índices regionales.
  // Para el mes más reciente, construimos un campo de anomalía espacial
  // coherente: oriente (frente a Perú) refleja Niño 1+2; centro refleja Niño 3.4.
  const lastIdx = MONTHS.length - 1;
  const sstCells = buildSstCells(n12?.point.value ?? 0, n34?.point.value ?? 0);
  const d20Cells = buildD20Cells(d20?.point.value ?? 0, n34?.point.value ?? 0);

  const regions = [
    { name: "Niño 1+2", bounds: { latMin: -10, latMax: 0, lonMin: -90, lonMax: -80 }, color: "var(--enso-coastal)" },
    { name: "Niño 3.4", bounds: { latMin: -5, latMax: 5, lonMin: -170, lonMax: -120 }, color: "var(--enso-basin)" },
  ];

  return (
    <div className="space-y-5">
      <InfoNote tone="muted" title="Mapas de anomalía (síntesis)">
        Los mapas sintetizan el campo de anomalía a partir de los índices regionales normalizados del
        observatorio para el mes más reciente ({fmtMonth(MONTHS[lastIdx])}). Son una representación
        coherente con la física de ENSO; los productos oficiales grilleados (OISST, GODAS) ofrecen
        mayor detalle espacial y se citan en la ficha de cada indicador.
      </InfoNote>

      <SectionCard
        title={<span className="flex items-center gap-2">Mapa de anomalía de TSM <ScopeBadge scope="coastal" /></span>}
        description={`Mes más reciente: ${fmtMonth(MONTHS[lastIdx])}. Escala ±2.5 °C. Se marcan las regiones Niño 1+2 y Niño 3.4.`}
      >
        <AnomalyMap cells={sstCells} scale={2.5} regions={regions} title="Anomalía de TSM (°C)" />
      </SectionCard>

      <SectionCard
        title={<span className="flex items-center gap-2">Mapa de anomalía de D20 <ScopeBadge scope="basin" /></span>}
        description="Profundidad de la isoterma de 20 °C (anomalía, m). Escala ±25 m. Fuente: GODAS."
      >
        <AnomalyMap cells={d20Cells} scale={25} title="Anomalía de D20 (m)" />
      </SectionCard>

      <SectionCard title="Regiones de monitoreo ENSO">
        <div className="grid gap-4 md:grid-cols-2 text-xs">
          <div>
            <FieldLine label="Niño 1+2 (costero)">{INDICATOR_BY_ID.nino12.region}</FieldLine>
            <FieldLine label="Límites">{`10°S–0°, 90–80°O`}</FieldLine>
            <FieldLine label="Última anomalía">{fmtMonth(n12?.point.month ?? "")}: {n12?.point.value ?? "n/d"} °C</FieldLine>
          </div>
          <div>
            <FieldLine label="Niño 3.4 (cuenca)">{INDICATOR_BY_ID.nino34.region}</FieldLine>
            <FieldLine label="Límites">{`5°S–5°N, 170–120°O`}</FieldLine>
            <FieldLine label="Última anomalía">{fmtMonth(n34?.point.month ?? "")}: {n34?.point.value ?? "n/d"} °C</FieldLine>
          </div>
        </div>
      </SectionCard>
    </div>
  );
}

/** Construye celdas de TSM a partir de anomalías regionales. */
function buildSstCells(n12Anom: number, n34Anom: number) {
  const cells: { lat: number; lon: number; value: number | null }[] = [];
  // Grilla 5° lat × 10° lon sobre el Pacífico -180..-70, -15..15
  for (let lat = 15; lat >= -15; lat -= 5) {
    for (let lon = -175; lon <= -75; lon += 10) {
      // peso de la costa (oriente) vs cuenca (centro)
      const eastWeight = Math.max(0, Math.min(1, (lon + 120) / 50)); // 0 occidente..1 oriente
      const latWeight = 1 - Math.min(1, Math.abs(lat) / 15); // máx en ecuador
      const val = n34Anom * (1 - eastWeight) * latWeight + n12Anom * eastWeight * (1 - Math.abs(lat) / 12);
      cells.push({ lat, lon, value: Math.round(val * 100) / 100 });
    }
  }
  return cells;
}

function buildD20Cells(d20Anom: number, n34Anom: number) {
  const cells: { lat: number; lon: number; value: number | null }[] = [];
  for (let lat = 15; lat >= -15; lat -= 5) {
    for (let lon = -175; lon <= -75; lon += 10) {
      const eastWeight = Math.max(0, Math.min(1, (lon + 120) / 50));
      const latWeight = 1 - Math.min(1, Math.abs(lat) / 15);
      const val = d20Anom * latWeight * (0.5 + 0.5 * eastWeight) + n34Anom * 4 * (1 - eastWeight) * latWeight;
      cells.push({ lat, lon, value: Math.round(val * 10) / 10 });
    }
  }
  return cells;
}
