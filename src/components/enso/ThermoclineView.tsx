"use client";

import * as React from "react";
import { generateAllSeries, latest, MONTHS } from "@/lib/enso/series";
import { d20Interpretation } from "@/lib/enso/derived";
import { INDICATOR_BY_ID } from "@/lib/enso/methodology";
import { EnsoTimeSeries, Hovmoller, MonthlyHeatmap } from "./charts";
import { SectionCard, ScopeBadge, InfoNote, BigValue, FieldLine, StatusPill } from "./primitives";
import { fmtMonth, fmtValue, COLOR_BASIN } from "@/lib/enso/ui";

export function ThermoclineView() {
  const all = generateAllSeries();
  const d20 = latest(all.d20);
  const n34 = all.nino34;

  // Hovmöller longitud–tiempo sintetizado a partir de Niño 3.4 con desfase
  // espacial: el extremo oriental (Niño 1+2, ~270°E) se profundiza antes y más
  // fuerte durante El Niño; el occidente (~150°E) se somera. Ilustrativo y
  // consistente con la física documentada.
  const longitudes = [120, 135, 150, 165, 180, 195, 210, 225, 240, 255, 270, 285];
  const recentMonths = MONTHS.slice(-96); // últimos 8 años
  const matrix: (number | null)[][] = recentMonths.map((m) => {
    const idx = MONTHS.indexOf(m);
    const v34 = all.nino34.points[idx].value;
    const v12 = all.nino12.points[idx].value;
    if (v34 === null) return longitudes.map(() => null);
    return longitudes.map((lon) => {
      // desfase espacial: oriente (lon alto) profunda más; occidente somera
      const eastWeight = (lon - 120) / (285 - 120); // 0..1
      const deep = 9 * v34 + (v12 ?? v34) * 3; // señal oriental reforzada
      const westShoal = -6 * v34 * (1 - eastWeight);
      const val = deep * eastWeight + westShoal * (1 - eastWeight) + (Math.sin(idx / 7 + lon) * 1.2);
      return Math.round(val * 10) / 10;
    });
  });

  return (
    <div className="space-y-5">
      <InfoNote tone="info" title="Profundidad de la isoterma de 20 °C (D20)">
        D20 es un proxy de la profundidad de la termoclina en el Pacífico ecuatorial (fuente GODAS,
        NOAA/CPC). <strong>Anomalía positiva</strong> ⇒ isoterma de 20 °C <strong>más profunda</strong>{" "}
        que lo normal (típica de El Niño de cuenca); <strong>negativa</strong> ⇒ más somera (típica de
        La Niña). Se confirma la convención de la fuente antes de aplicar.
      </InfoNote>

      <SectionCard
        title={<span className="flex items-center gap-2">Anomalía de D20 — Pacífico ecuatorial <ScopeBadge scope="basin" /></span>}
        description="Promedio ecuatorial (2°S–2°N). Fuente: NOAA/CPC (GODAS)."
        right={<StatusPill label={d20Interpretation(d20?.point.value ?? null)} tone={d20?.point.value && d20.point.value > 0 ? "warm" : "cool"} />}
      >
        <div className="mb-3">
          <p className="text-[11px] text-muted-foreground">Último valor ({fmtMonth(d20?.point.month ?? "")})</p>
          <BigValue value={fmtValue(d20?.point.value ?? null, "m").replace(" m", "")} units="m" tone={d20?.point.value && d20.point.value > 0 ? "warm" : "cool"} />
        </div>
        <EnsoTimeSeries
          series={[{ id: "d20", label: "D20 (anomalía)", color: COLOR_BASIN, data: all.d20.points }]}
          units="m" yLabel="m" height={300}
          thresholds={[
            { min: 5, max: 999, label: "Termoclina profunda", color: "var(--enso-warm)", fillOpacity: 0.08 },
            { min: -999, max: -5, label: "Termoclina somera", color: "var(--enso-cool)", fillOpacity: 0.08 },
          ]}
        />
      </SectionCard>

      <SectionCard
        title="Diagrama Hovmöller — anomalía de D20 (longitud × tiempo)"
        description="Eje horizontal: longitud (°E, 120–285). Eje vertical: tiempo (últimos 8 años, reciente abajo). Escala ±30 m. Ilustración coherente con la física de ENSO."
      >
        <Hovmoller months={recentMonths} longitudes={longitudes} matrix={matrix} scale={30} height={400} lonLabel="Longitud (°E)" />
      </SectionCard>

      <SectionCard title="Mapa de calor mensual — anomalía de D20" description="Últimos 15 años. Escala ±25 m.">
        <div className="overflow-x-auto enso-scroll">
          <MonthlyHeatmap series={all.d20} scale={25} />
        </div>
      </SectionCard>

      <SectionCard title="Sección subsuperficial (esquemática)" description="Profundidad de la isoterma de 20 °C a lo largo del ecuador. Profundidad (m) vs longitud (°E).">
        <DepthSection matrix={matrix} longitudes={longitudes} />
      </SectionCard>

      <SectionCard title="Metadatos del indicador D20">
        <div className="grid gap-4 md:grid-cols-2 text-xs">
          <div>
            <FieldLine label="Indicador">{INDICATOR_BY_ID.d20.name}</FieldLine>
            <FieldLine label="Nivel">{INDICATOR_BY_ID.d20.level}</FieldLine>
            <FieldLine label="Región">{INDICATOR_BY_ID.d20.region}</FieldLine>
            <FieldLine label="Agregación">{INDICATOR_BY_ID.d20.aggregation}</FieldLine>
          </div>
          <div>
            <FieldLine label="Climatología">{INDICATOR_BY_ID.d20.climatology}</FieldLine>
            <FieldLine label="Dataset">{INDICATOR_BY_ID.d20.dataset}</FieldLine>
            <FieldLine label="Unidades">m (anomalía)</FieldLine>
            <FieldLine label="Convención">+ ⇒ más profunda · − ⇒ más somera</FieldLine>
          </div>
        </div>
      </SectionCard>
    </div>
  );
}

/** Sección profundidad–longitud esquemática (último mes). */
function DepthSection({ matrix, longitudes }: { matrix: (number | null)[][]; longitudes: number[] }) {
  const last = matrix[matrix.length - 1];
  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(640);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => { for (const x of e) setW(Math.max(320, x.contentRect.width)); });
    ro.observe(ref.current); return () => ro.disconnect();
  }, []);
  const h = 220, padL = 44, padR = 12, padT = 12, padB = 28;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  const sx = (i: number) => padL + (i / (longitudes.length - 1)) * plotW;
  // profundidad base 80 m + anomalía
  const sy = (d20anom: number) => padT + ((80 + d20anom) / 160) * plotH;
  const pts = last.map((v, i) => v === null ? null : `${sx(i)},${sy(v)}`).filter(Boolean) as string[];
  return (
    <div ref={ref} className="w-full">
      <svg width={w} height={h} role="img" aria-label="Sección profundidad–longitud de D20">
        <line x1={padL} y1={padT} x2={padL} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.4} />
        <line x1={padL} y1={padT + plotH} x2={padL + plotW} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.4} />
        {[0, 50, 100, 150].map((d) => (
          <text key={d} x={padL - 6} y={padT + (d / 160) * plotH + 3} textAnchor="end" fontSize={9} fill="currentColor" fillOpacity={0.6}>{d} m</text>
        ))}
        {longitudes.map((lon, i) => i % 2 === 0 && (
          <text key={lon} x={sx(i)} y={h - 10} textAnchor="middle" fontSize={9} fill="currentColor" fillOpacity={0.6}>{lon}°E</text>
        ))}
        <polyline points={pts.join(" ")} fill="none" stroke="var(--enso-basin)" strokeWidth={2} />
        {last.map((v, i) => v === null ? null : (
          <circle key={i} cx={sx(i)} cy={sy(v)} r={3} fill={(v ?? 0) > 0 ? "var(--enso-warm)" : "var(--enso-cool)"} />
        ))}
        <text x={padL + plotW / 2} y={h - 1} textAnchor="middle" fontSize={10} fill="currentColor" fillOpacity={0.6}>Longitud (°E) · occidente → oriente</text>
      </svg>
    </div>
  );
}
