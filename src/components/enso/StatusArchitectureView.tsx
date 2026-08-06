"use client";

import * as React from "react";
import { evaluateBothPolicies, thresholdColorCSS, type ThresholdResult } from "@/lib/enso/thresholds";
import { buildCurrentStatus } from "@/lib/enso/derived";
import { generateAllSeries, latest } from "@/lib/enso/series";
import { INDICATOR_BY_ID } from "@/lib/enso/methodology";
import { SectionCard, ScopeBadge, InfoNote, StatusPill, FieldLine } from "./primitives";
import { fmtValue, fmtMonth } from "@/lib/enso/ui";
import { ShieldCheck, Eye, Activity, AlertTriangle, GitBranch } from "lucide-react";

export function StatusArchitectureView() {
  const all = React.useMemo(() => generateAllSeries(), []);
  const status = React.useMemo(() => buildCurrentStatus(), []);
  const [showExpert, setShowExpert] = React.useState(true);
  const [showOfficial, setShowOfficial] = React.useState(true);

  const indicators = [
    { id: "nino12", label: "Niño 1+2 (costero)", scope: "coastal" as const, value: latest(all.nino12)?.point.value ?? null, month: latest(all.nino12)?.point.month ?? "", units: "degC" },
    { id: "icen", label: "ICEN (costero)", scope: "coastal" as const, value: latest(all.icen)?.point.value ?? null, month: latest(all.icen)?.point.month ?? "", units: "degC" },
    { id: "nino34", label: "Niño 3.4 (cuenca)", scope: "basin" as const, value: latest(all.nino34)?.point.value ?? null, month: latest(all.nino34)?.point.month ?? "", units: "degC" },
    { id: "roni", label: "RONI (cuenca)", scope: "basin" as const, value: latest(all.roni)?.point.value ?? null, month: latest(all.roni)?.point.month ?? "", units: "degC" },
    { id: "d20", label: "D20 (termoclina)", scope: "basin" as const, value: latest(all.d20)?.point.value ?? null, month: latest(all.d20)?.point.month ?? "", units: "m" },
    { id: "soi", label: "SOI (presión)", scope: "basin" as const, value: latest(all.soi)?.point.value ?? null, month: latest(all.soi)?.point.month ?? "", units: "dimensionless" },
  ];

  return (
    <div className="space-y-5">
      <InfoNote tone="warn" title="Arquitectura de estado — tres capas separadas">
        Cada indicador muestra tres capas independientes:
        <strong> (1) Estado oficial</strong> (NOAA/CPC o ENFEN),
        <strong> (2) Señal operativa del experto</strong> (política expert-grd-image-v1, NO oficial),
        y <strong> (3) Calidad y vigencia del dato</strong>.
        La señal del experto no equivale al sistema oficial de alertas.
      </InfoNote>

      {/* Toggle para mostrar políticas */}
      <SectionCard title="Políticas de umbral a mostrar" right={<GitBranch className="h-4 w-4" />}>
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={() => setShowExpert(!showExpert)}
            className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium enso-focus-ring ${showExpert ? "border-[color:var(--enso-warm)] bg-[color:var(--enso-warm)]/10" : "opacity-50"}`}
            aria-pressed={showExpert}
          >
            <Eye className="h-4 w-4" />
            Señal operativa del experto (GRD v1)
          </button>
          <button
            onClick={() => setShowOfficial(!showOfficial)}
            className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium enso-focus-ring ${showOfficial ? "border-[color:var(--enso-basin)] bg-[color:var(--enso-basin)]/10" : "opacity-50"}`}
            aria-pressed={showOfficial}
          >
            <ShieldCheck className="h-4 w-4" />
            Clasificación oficial ICEN (ENFEN)
          </button>
          <span className="ml-auto text-xs text-muted-foreground">
            Mostrando: {showExpert && showOfficial ? "ambas" : showExpert ? "solo experto" : showOfficial ? "solo oficial" : "ninguna"}
          </span>
        </div>
      </SectionCard>

      {/* Tarjetas de estado por indicador */}
      <div className="grid gap-4 lg:grid-cols-2">
        {indicators.map((ind) => {
          const policies = evaluateBothPolicies(ind.id, ind.value);
          return (
            <IndicatorStatusCard
              key={ind.id}
              label={ind.label}
              scope={ind.scope}
              value={ind.value}
              month={ind.month}
              units={ind.units}
              expert={showExpert ? policies.expert : null}
              official={showOfficial ? policies.official : null}
              officialStatus={ind.scope === "coastal" ? status.coastal.alert : ind.id === "icen" ? status.coastal.alert : status.basin.alert}
            />
          );
        })}
      </div>

      {/* Leyenda */}
      <SectionCard title="Leyenda de colores y estados">
        <div className="grid gap-3 md:grid-cols-2 text-xs">
          <div>
            <p className="font-semibold mb-1">Señal operativa del experto (GRD v1)</p>
            <div className="space-y-1">
              <LegendItem color="green" label="Normal — dentro del rango definido por el experto" />
              <LegendItem color="yellow" label="Amarillo — precaución según umbral del experto" />
              <LegendItem color="red" label="Rojo — alerta operativa según umbral del experto" />
              <LegendItem color="gray" label="Gris — sin clasificar (hueco de la política, dato faltante o métrica incompatible)" />
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground italic">
              Esta señal NO equivale al sistema oficial de alertas de NOAA ni de ENFEN.
            </p>
          </div>
          <div>
            <p className="font-semibold mb-1">Clasificación oficial ICEN (ENFEN)</p>
            <div className="space-y-1">
              <LegendItem color="blue" label="Frío intenso (La Niña Costera fuerte)" />
              <LegendItem color="lightblue" label="Frío moderado" />
              <LegendItem color="lightcyan" label="Frío débil" />
              <LegendItem color="green" label="Normal" />
              <LegendItem color="yellow" label="Cálido débil" />
              <LegendItem color="orange" label="Cálido moderado" />
              <LegendItem color="red" label="Cálido fuerte" />
              <LegendItem color="darkred" label="Cálido extraordinario" />
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground italic">
              Solo aplica al ICEN (media móvil de 3 meses), no a Niño 1+2 semanal.
            </p>
          </div>
        </div>
      </SectionCard>

      {/* Documentación de ambigüedades */}
      <SectionCard title="Ambigüedades documentadas de la política experto GRD">
        <div className="space-y-3 text-xs">
          <div className="rounded-lg border p-3">
            <p className="font-semibold text-[color:var(--enso-coastal)]">SST Costero (Niño 1+2)</p>
            <ul className="mt-1 space-y-0.5 text-muted-foreground list-disc pl-4">
              <li>¿Es semanal, mensual, ICEN o ICEN temporal?</li>
              <li>¿Los extremos son inclusivos?</li>
              <li>¿Cómo manejar el intervalo +2.0 a +2.1?</li>
              <li>¿Cómo manejar entre +0.5 y +1.3?</li>
              <li>¿Cómo clasificar anomalías frías &lt; −0.7?</li>
            </ul>
            <p className="mt-1 text-[11px] italic">Los huecos se preservan como UNCLASSIFIED_BY_EXPERT_POLICY.</p>
          </div>
          <div className="rounded-lg border p-3">
            <p className="font-semibold text-[color:var(--enso-basin)]">SST Cuenca (Niño 3.4)</p>
            <ul className="mt-1 space-y-0.5 text-muted-foreground list-disc pl-4">
              <li>Intervalo &gt; +0.5 a ≤ +1.0: sin clasificar.</li>
              <li>Anomalías frías &lt; −0.5: sin clasificar.</li>
            </ul>
          </div>
          <div className="rounded-lg border p-3">
            <p className="font-semibold">Termoclina (D20)</p>
            <ul className="mt-1 space-y-0.5 text-muted-foreground list-disc pl-4">
              <li>Intervalo &gt; +20 a &lt; 30: sin clasificar.</li>
              <li>Valores &lt; −20: sin clasificar.</li>
              <li>Identificar el producto D20 exacto para cada alcance.</li>
            </ul>
          </div>
          <div className="rounded-lg border p-3">
            <p className="font-semibold">SOI</p>
            <ul className="mt-1 space-y-0.5 text-muted-foreground list-disc pl-4">
              <li>No hay regla para el lado positivo (&gt; +7): sin clasificar.</li>
              <li>No crear «SOI costero».</li>
              <li>Confirmar formulación (mensual, 30/60/90 días, NOAA CPC o BoM Troup).</li>
            </ul>
          </div>
        </div>
      </SectionCard>
    </div>
  );
}

function IndicatorStatusCard({
  label, scope, value, month, units, expert, official, officialStatus,
}: {
  label: string;
  scope: "coastal" | "basin";
  value: number | null;
  month: string;
  units: string;
  expert: ThresholdResult | null;
  official: ThresholdResult | null;
  officialStatus: string;
}) {
  return (
    <SectionCard
      title={<span className="flex items-center gap-2">{label} <ScopeBadge scope={scope} /></span>}
    >
      <div className="space-y-3">
        {/* Valor actual */}
        <div className="flex items-baseline justify-between border-b pb-2">
          <div>
            <p className="text-[11px] text-muted-foreground">Valor actual ({fmtMonth(month)})</p>
            <p className="text-xl font-bold enso-num">{fmtValue(value, units)}</p>
          </div>
          <div className="text-right">
            <p className="text-[11px] text-muted-foreground">Preliminar</p>
            <StatusPill label="Dato preliminar" tone="warn" />
          </div>
        </div>

        {/* Capa 1: Estado oficial */}
        <div>
          <p className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            <ShieldCheck className="h-3 w-3" /> Estado oficial
          </p>
          <div className="mt-1 flex items-center gap-2">
            <StatusPill label={officialStatus} tone="warm" />
            <span className="text-[11px] text-muted-foreground">
              {scope === "coastal" ? "ENFEN / IMARPE" : "NOAA / CPC"}
            </span>
          </div>
        </div>

        {/* Capa 2: Señal operativa del experto */}
        {expert && (
          <div>
            <p className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              <Eye className="h-3 w-3" /> Señal operativa del experto
            </p>
            <div className="mt-1 flex items-center gap-2">
              <span
                className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium"
                style={{
                  background: `color-mix(in oklch, ${thresholdColorCSS(expert.color)} 15%, transparent)`,
                  color: thresholdColorCSS(expert.color),
                  border: `1px solid color-mix(in oklch, ${thresholdColorCSS(expert.color)} 30%, transparent)`,
                }}
              >
                {expert.classification}
              </span>
              <span className="text-[11px] text-muted-foreground">
                Política: {expert.policy_id}
              </span>
            </div>
            {expert.is_unclassified && (
              <p className="mt-0.5 text-[11px] text-amber-600 dark:text-amber-400">
                ⚠ {expert.unclassified_reason}
              </p>
            )}
            <p className="mt-0.5 text-[11px] italic text-muted-foreground">
              Esta señal no equivale al sistema oficial de alertas.
            </p>
          </div>
        )}

        {/* Capa 2b: Clasificación oficial ICEN (si aplica) */}
        {official && (
          <div>
            <p className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              <Activity className="h-3 w-3" /> Clasificación oficial ICEN (ENFEN)
            </p>
            <div className="mt-1 flex items-center gap-2">
              <span
                className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium"
                style={{
                  background: `color-mix(in oklch, ${thresholdColorCSS(official.color)} 15%, transparent)`,
                  color: thresholdColorCSS(official.color),
                  border: `1px solid color-mix(in oklch, ${thresholdColorCSS(official.color)} 30%, transparent)`,
                }}
              >
                {official.classification}
              </span>
              <span className="text-[11px] text-muted-foreground">
                {official.policy_id}
              </span>
            </div>
          </div>
        )}

        {/* Capa 3: Calidad y vigencia */}
        <div>
          <p className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            <AlertTriangle className="h-3 w-3" /> Calidad y vigencia del dato
          </p>
          <div className="mt-1 space-y-0.5 text-[11px]">
            <FieldLine label="Estado">Dato vigente, preliminar</FieldLine>
            <FieldLine label="Periodo de validez">{fmtMonth(month)}</FieldLine>
            <FieldLine label="Fuente">{INDICATOR_BY_ID[value !== null ? "nino34" : "nino34"]?.dataset ?? "—"}</FieldLine>
          </div>
        </div>
      </div>
    </SectionCard>
  );
}

function LegendItem({ color, label }: { color: string; label: string }) {
  const colors: Record<string, string> = {
    green: "var(--enso-cool)",
    yellow: "#eab308",
    red: "#dc2626",
    blue: "#1e40af",
    lightblue: "#3b82f6",
    lightcyan: "#67e8f9",
    orange: "#f97316",
    darkred: "#7f1d1d",
    gray: "var(--muted-foreground)",
  };
  return (
    <div className="flex items-center gap-2">
      <span className="h-3 w-3 rounded" style={{ background: colors[color] ?? color }} />
      <span>{label}</span>
    </div>
  );
}
