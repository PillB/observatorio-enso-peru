"use client";

import * as React from "react";
import { generateAllSeries, latest, AS_OF_DATE } from "@/lib/enso/series";
import { buildCurrentStatus } from "@/lib/enso/derived";
import { EnsoTimeSeries, MiniSpark } from "./charts";
import { SectionCard, ScopeBadge, StatusPill, InfoNote, PreliminaryTag, BigValue, FieldLine } from "./primitives";
import { fmtMonth, fmtValue, COLOR_COASTAL, COLOR_BASIN } from "@/lib/enso/ui";
import { Waves, Wind, Thermometer, Gauge, AlertTriangle, ShieldCheck, Clock, BookOpen } from "lucide-react";

export function OverviewView({ onNavigate }: { onNavigate: (v: string) => void }) {
  const all = generateAllSeries();
  const status = React.useMemo(() => buildCurrentStatus(), []);

  const n12 = latest(all.nino12);
  const n34 = latest(all.nino34);
  const icen = latest(all.icen);
  const roni = latest(all.roni);
  const soi = latest(all.soi);
  const u850 = latest(all.u850);
  const d20 = latest(all.d20);

  const recentN12 = all.nino12.points.slice(-60).map((p) => p.value);
  const recentN34 = all.nino34.points.slice(-60).map((p) => p.value);

  return (
    <div className="space-y-5">
      {/* Aviso de interpretación */}
      <InfoNote tone="info" title="Estado oficial vs interpretación del observatorio">
        Las alertas oficiales se citan textualmente de ENFEN (costero) y NOAA/CPC (cuenca). Las
        categorías de intensidad y las interpretaciones cualitativas son <strong>generadas por el
        observatorio</strong> y se etiquetan como tales. Ante emergencias, consulte INDECI, CENEPRED,
        SENAMHI y la Comisión Multisectorial ENFEN.
      </InfoNote>

      {/* Tarjetas de estado */}
      <div className="grid gap-4 md:grid-cols-2">
        {/* Costero */}
        <SectionCard
          title={<span className="flex items-center gap-2"><Waves className="h-4 w-4" /> El Niño Costero — escala costera</span>}
          description="Fuente oficial: ENFEN / IMARPE (siofen.imarpe.gob.pe)"
          right={<ScopeBadge scope="coastal" />}
        >
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <StatusPill label={status.coastal.alert} tone="warm" />
              <span className="text-[11px] text-muted-foreground">desde {fmtMonth(status.coastal.alertSince ?? "")}</span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="text-[11px] text-muted-foreground">TSM Niño 1+2 ({fmtMonth(status.coastal.nino12Month)})</p>
                <BigValue value={fmtValue(status.coastal.nino12Anom, "degC").replace(" °C", "")} units="°C" tone="warm" />
                <PreliminaryTag show={status.coastal.preliminary} />
              </div>
              <div>
                <p className="text-[11px] text-muted-foreground">ICEN ({status.coastal.icenWindow})</p>
                <BigValue value={fmtValue(status.coastal.icen, "degC").replace(" °C", "")} units="°C" tone="warm" />
                <p className="text-[11px] text-muted-foreground">Categoría: {status.coastal.icenCategory}</p>
              </div>
            </div>
            <MiniSpark data={recentN12} color={COLOR_COASTAL} />
            <button
              onClick={() => onNavigate("tsm")}
              className="text-xs font-medium text-[color:var(--enso-basin)] hover:underline"
            >
              Ver detalle de TSM →
            </button>
          </div>
        </SectionCard>

        {/* Cuenca */}
        <SectionCard
          title={<span className="flex items-center gap-2"><Gauge className="h-4 w-4" /> ENSO de cuenca — Pacífico ecuatorial</span>}
          description="Fuente oficial: NOAA / CPC — ENSO Diagnostic Discussion"
          right={<ScopeBadge scope="basin" />}
        >
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <StatusPill label={status.basin.alert} tone="warm" />
              <span className="text-[11px] text-muted-foreground">desde {fmtMonth(status.basin.alertSince ?? "")}</span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="text-[11px] text-muted-foreground">TSM Niño 3.4 ({fmtMonth(status.basin.nino34Month)})</p>
                <BigValue value={fmtValue(status.basin.nino34Anom, "degC").replace(" °C", "")} units="°C" tone="warm" />
                <PreliminaryTag show={status.basin.preliminary} />
              </div>
              <div>
                <p className="text-[11px] text-muted-foreground">RONI ({status.basin.roniWindow})</p>
                <BigValue value={fmtValue(status.basin.roni, "degC").replace(" °C", "")} units="°C" tone="warm" />
                <p className="text-[11px] text-muted-foreground">Categoría: {status.basin.roniCategory}</p>
              </div>
            </div>
            <MiniSpark data={recentN34} color={COLOR_BASIN} />
            <button
              onClick={() => onNavigate("tsm")}
              className="text-xs font-medium text-[color:var(--enso-basin)] hover:underline"
            >
              Ver comparación costero vs cuenca →
            </button>
          </div>
        </SectionCard>
      </div>

      {/* Indicadores complementarios */}
      <div className="grid gap-4 md:grid-cols-3">
        <CompactCard
          icon={<Wind className="h-4 w-4" />}
          title="Viento zonal 850 hPa"
          scope="basin"
          value={fmtValue(status.winds.u850Anom, "m_per_s")}
          month={fmtMonth(status.winds.u850Month)}
          detail={status.winds.direction}
          onClick={() => onNavigate("vientos")}
        />
        <CompactCard
          icon={<Thermometer className="h-4 w-4" />}
          title="Termoclina (D20)"
          scope="basin"
          value={fmtValue(status.thermocline.d20Anom, "m")}
          month={fmtMonth(status.thermocline.d20Month)}
          detail={status.thermocline.interpretation}
          onClick={() => onNavigate("termoclina")}
        />
        <CompactCard
          icon={<Gauge className="h-4 w-4" />}
          title="SOI (Oscilación del Sur)"
          scope="basin"
          value={fmtValue(status.soi.value, "dimensionless")}
          month={fmtMonth(status.soi.month)}
          detail={status.soi.interpretation}
          onClick={() => onNavigate("soi")}
        />
      </div>

      {/* Mini historial comparado */}
      <SectionCard
        title="Costero vs cuenca — últimos 10 años"
        description="Anomalía de TSM mensual. Costero (Niño 1+2, ámbar) y cuenca (Niño 3.4, teal). 2017 muestra El Niño Costero sin El Niño de cuenca."
      >
        <EnsoTimeSeries
          series={[
            { id: "nino12", label: "Niño 1+2 (costero)", color: COLOR_COASTAL, data: all.nino12.points },
            { id: "nino34", label: "Niño 3.4 (cuenca)", color: COLOR_BASIN, data: all.nino34.points },
          ]}
          units="degC"
          yLabel="°C"
          windowMonths={120}
          thresholds={[
            { min: 0.5, max: 999, label: "El Niño", color: "var(--enso-warm)", fillOpacity: 0.08 },
            { min: -999, max: -0.5, label: "La Niña", color: "var(--enso-cool)", fillOpacity: 0.08 },
          ]}
          height={300}
        />
      </SectionCard>

      {/* Frescura y enlace a metodología */}
      <div className="grid gap-4 md:grid-cols-2">
        <SectionCard title={<span className="flex items-center gap-2"><Clock className="h-4 w-4" /> Frescura de los datos</span>}>
          <FieldLine label="Fecha de corte del observatorio">{AS_OF_DATE}</FieldLine>
          <FieldLine label="Mes más reciente (TSM)">{fmtMonth(n34?.point.month ?? "")}</FieldLine>
          <FieldLine label="Dato preliminar">
            {n34?.point.flag === "preliminary" ? "Sí (puede revisarse)" : "No (final)"}
          </FieldLine>
          <FieldLine label="ICEN más reciente">{fmtValue(icen?.point.value ?? null, "degC")} · {status.coastal.icenWindow}</FieldLine>
          <FieldLine label="RONI más reciente">{fmtValue(roni?.point.value ?? null, "degC")} · {status.basin.roniWindow}</FieldLine>
          <FieldLine label="SOI más reciente">{fmtValue(soi?.point.value ?? null, "dimensionless")}</FieldLine>
        </SectionCard>

        <SectionCard title={<span className="flex items-center gap-2"><ShieldCheck className="h-4 w-4" /> Incertidumbre y alcance</span>}>
          <ul className="space-y-2 text-xs text-muted-foreground">
            <li>• Los datos preliminares pueden revisarse en publicaciones posteriores.</li>
            <li>• Los valores se actualizan siguiendo la frecuencia nativa de cada fuente (mensual/semanal).</li>
            <li>• El observatorio no sustituye datos faltantes con valores fabricados.</li>
            <li>• Costero y cuenca son conceptos separados; no se infiere uno del otro.</li>
            <li>• No existe un «SOI costero»; el SOI es de escala de cuenca.</li>
          </ul>
          <div className="mt-3 flex flex-wrap gap-2">
            <button onClick={() => onNavigate("metodologia")} className="inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-medium hover:bg-muted">
              <BookOpen className="h-3.5 w-3.5" /> Metodología
            </button>
            <button onClick={() => onNavigate("fuentes")} className="inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-medium hover:bg-muted">
              <AlertTriangle className="h-3.5 w-3.5" /> Fuentes y notas
            </button>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}

function CompactCard({ icon, title, scope, value, month, detail, onClick }: {
  icon: React.ReactNode; title: string; scope: "coastal" | "basin"; value: string; month: string; detail: string; onClick: () => void;
}) {
  return (
    <SectionCard title={<span className="flex items-center gap-2">{icon} {title}</span>} right={<ScopeBadge scope={scope} />}>
      <button onClick={onClick} className="w-full text-left">
        <div className="flex items-baseline justify-between">
          <BigValue value={value.replace(/ (°C|m\/s|m)$/, "")} units={value.includes(" ") ? value.split(" ").pop() : ""} />
          <span className="text-[11px] text-muted-foreground">{month}</span>
        </div>
        <p className="mt-1 text-xs text-muted-foreground leading-snug">{detail}</p>
      </button>
    </SectionCard>
  );
}
