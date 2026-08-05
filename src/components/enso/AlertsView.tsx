"use client";

import * as React from "react";
import { buildAlertStates, type AlertState } from "@/lib/enso/derived";
import { generateAllSeries, MONTHS } from "@/lib/enso/series";
import { SectionCard, ScopeBadge, InfoNote, BigValue, StatusPill, FieldLine } from "./primitives";
import { EnsoTimeSeries } from "./charts";
import { fmtMonth, fmtValue, COLOR_BASIN, COLOR_COASTAL } from "@/lib/enso/ui";
import { AlertTriangle, ShieldCheck, Eye, TrendingUp, Activity } from "lucide-react";

export function AlertsView() {
  const alerts = React.useMemo(() => buildAlertStates(), []);
  const all = React.useMemo(() => generateAllSeries(), []);

  return (
    <div className="space-y-5">
      <InfoNote tone="warn" title="Umbrales de activación — interpretación derivada del observatorio">
        Esta vista evalúa si los indicadores cumplen las condiciones operacionales de activación de
        evento (meses consecutivos sobre umbral). <strong>Estas condiciones son derivadas por el
        observatorio</strong> con fines de seguimiento; la <strong>declaración oficial</strong> de
        El Niño/La Niña corresponde a ENFEN (costero) y NOAA/CPC (cuenca). Ante emergencias,
        consulte INDECI, CENEPRED, SENAMHI y ENFEN.
      </InfoNote>

      {/* Tarjetas de estado de activación */}
      <div className="grid gap-4 md:grid-cols-2">
        {alerts.map((a) => (
          <AlertCard key={a.indicatorId} alert={a} series={all[a.indicatorId]} />
        ))}
      </div>

      {/* Resumen visual de progreso */}
      <SectionCard title={<span className="flex items-center gap-2"><Activity className="h-4 w-4" /> Progreso hacia la activación</span>} description="Meses consecutivos sobre el umbral (misma dirección) frente a los requeridos.">
        <div className="space-y-4">
          {alerts.map((a) => (
            <div key={a.indicatorId}>
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="flex items-center gap-2">
                  <ScopeBadge scope={a.scope} />
                  <span className="font-medium">{a.label}</span>
                </span>
                <span className="enso-num text-muted-foreground">
                  {a.consecutiveMonths} / {a.requiredMonths} meses · {a.status}
                </span>
              </div>
              <div className="h-3 w-full rounded-full bg-muted overflow-hidden relative">
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${Math.max(2, a.progress)}%`,
                    background: a.direction === "warm"
                      ? "linear-gradient(90deg, var(--enso-warm), color-mix(in oklch, var(--enso-warm) 70%, var(--enso-coastal)))"
                      : a.direction === "cool"
                      ? "linear-gradient(90deg, var(--enso-cool), color-mix(in oklch, var(--enso-cool) 70%, var(--enso-basin)))"
                      : "var(--muted-foreground)",
                  }}
                />
                {/* Marcador del umbral requerido */}
                <div className="absolute top-0 h-full w-0.5 bg-foreground/40" style={{ left: "100%" }} title={`${a.requiredMonths} meses requeridos`} />
              </div>
              <p className="mt-1 text-[11px] text-muted-foreground">{a.note}</p>
            </div>
          ))}
        </div>
      </SectionCard>

      {/* Serie temporal con umbral */}
      <SectionCard title="ICEN con umbral de activación costera" description="Últimos 36 meses. Bandas de ±0.4 °C (umbral de activación derivado).">
        <EnsoTimeSeries
          series={[{ id: "icen", label: "ICEN (costero)", color: COLOR_COASTAL, data: all.icen.points.slice(-36) }]}
          units="degC" yLabel="°C" height={260}
          thresholds={[
            { min: 0.4, max: 999, label: "Umbral El Niño Costero", color: "var(--enso-warm)", fillOpacity: 0.1 },
            { min: -999, max: -0.4, label: "Umbral La Niña Costera", color: "var(--enso-cool)", fillOpacity: 0.1 },
          ]}
        />
      </SectionCard>

      <SectionCard title="RONI con umbral de activación de cuenca" description="Últimos 36 meses. Bandas de ±0.5 °C (umbral operacional NOAA/CPC).">
        <EnsoTimeSeries
          series={[{ id: "roni", label: "RONI (cuenca)", color: COLOR_BASIN, data: all.roni.points.slice(-36) }]}
          units="degC" yLabel="°C" height={260}
          thresholds={[
            { min: 0.5, max: 999, label: "Umbral El Niño", color: "var(--enso-warm)", fillOpacity: 0.1 },
            { min: -999, max: -0.5, label: "Umbral La Niña", color: "var(--enso-cool)", fillOpacity: 0.1 },
          ]}
        />
      </SectionCard>

      {/* Tabla de definiciones */}
      <SectionCard title="Definiciones operacionales de activación" description="Condiciones derivadas por el observatorio; la declaración oficial corresponde a las instituciones competentes.">
        <div className="overflow-x-auto enso-scroll">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="py-2 pr-3 font-medium">Indicador</th>
                <th className="py-2 pr-3 font-medium">Alcance</th>
                <th className="py-2 pr-3 font-medium">Umbral</th>
                <th className="py-2 pr-3 font-medium">Persistencia</th>
                <th className="py-2 pr-3 font-medium">Estado actual</th>
                <th className="py-2 font-medium">Declaración oficial</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b last:border-0">
                <td className="py-2 pr-3 font-medium">ICEN</td>
                <td className="py-2 pr-3"><ScopeBadge scope="coastal" /></td>
                <td className="py-2 pr-3 enso-num">±0.4 °C</td>
                <td className="py-2 pr-3">3 meses consecutivos</td>
                <td className="py-2 pr-3">{alerts[0]?.status ?? "—"}</td>
                <td className="py-2 text-muted-foreground">ENFEN / IMARPE</td>
              </tr>
              <tr className="border-b last:border-0">
                <td className="py-2 pr-3 font-medium">RONI</td>
                <td className="py-2 pr-3"><ScopeBadge scope="basin" /></td>
                <td className="py-2 pr-3 enso-num">±0.5 °C</td>
                <td className="py-2 pr-3">3 meses consecutivos</td>
                <td className="py-2 pr-3">{alerts[1]?.status ?? "—"}</td>
                <td className="py-2 text-muted-foreground">NOAA / CPC</td>
              </tr>
            </tbody>
          </table>
        </div>
      </SectionCard>
    </div>
  );
}

function AlertCard({ alert, series }: { alert: AlertState; series: import("@/lib/enso/types").Series }) {
  const icon = alert.status === "Cumplido" ? <ShieldCheck className="h-4 w-4" /> : alert.status === "En vigilancia" ? <Eye className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />;
  const tone = alert.direction === "warm" ? "warm" : alert.direction === "cool" ? "cool" : "neutral";
  const tonePill = alert.status === "Cumplido" ? (alert.direction === "warm" ? "warm" : "cool") : alert.status === "En vigilancia" ? "warn" : "neutral";

  return (
    <SectionCard
      title={<span className="flex items-center gap-2">{icon} {alert.label} — {alert.scope === "coastal" ? "activación costera" : "activación de cuenca"}</span>}
      right={<ScopeBadge scope={alert.scope} />}
    >
      <div className="space-y-3">
        <div className="flex items-baseline justify-between">
          <div>
            <p className="text-[11px] text-muted-foreground">Valor actual ({fmtMonth(alert.currentMonth)})</p>
            <BigValue
              value={fmtValue(alert.current, "degC").replace(" °C", "")}
              units="°C"
              tone={tone === "warm" ? "warm" : tone === "cool" ? "cool" : "neutral"}
            />
          </div>
          <StatusPill label={alert.status} tone={tonePill as "warm" | "cool" | "neutral" | "warn"} />
        </div>
        <div className="space-y-1 text-xs">
          <FieldLine label="Umbral">±{alert.threshold} °C</FieldLine>
          <FieldLine label="Meses consecutivos">{alert.consecutiveMonths} de {alert.requiredMonths}</FieldLine>
          <FieldLine label="Dirección">
            {alert.direction === "warm" ? (alert.scope === "coastal" ? "El Niño Costero" : "El Niño de cuenca") : alert.direction === "cool" ? (alert.scope === "coastal" ? "La Niña Costera" : "La Niña de cuenca") : "Neutral"}
          </FieldLine>
          <FieldLine label="Progreso">{alert.progress}%</FieldLine>
        </div>
        <p className="text-[11px] text-muted-foreground border-t pt-2">{alert.note}</p>
      </div>
    </SectionCard>
  );
}
