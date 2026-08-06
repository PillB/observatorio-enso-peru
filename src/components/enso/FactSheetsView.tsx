"use client";

import * as React from "react";
import { buildFactSheet, type IndicatorFactSheet } from "@/lib/enso/derived";
import { INDICATOR_BY_ID } from "@/lib/enso/methodology";
import { getSource } from "@/lib/enso/sources";
import { SectionCard, ScopeBadge, InfoNote, BigValue, StatusPill, FieldLine } from "./primitives";
import { fmtMonth, fmtValue } from "@/lib/enso/ui";
import { FileText, TrendingUp, TrendingDown, Minus, Download } from "lucide-react";

const INDICATOR_OPTIONS = ["nino12", "icen", "nino34", "roni", "soi", "u850", "d20"];

export function FactSheetsView() {
  const [indicatorId, setIndicatorId] = React.useState("nino34");
  const fact = React.useMemo(() => buildFactSheet(indicatorId), [indicatorId]);
  if (!fact) return null;
  const ind = INDICATOR_BY_ID[indicatorId];
  const src = getSource(fact.sourceId);

  const trend12Tone = fact.trend12m > 0.005 ? "warm" : fact.trend12m < -0.005 ? "cool" : "neutral";
  const trendIcon = fact.trend12m > 0.005 ? <TrendingUp className="h-3.5 w-3.5" /> : fact.trend12m < -0.005 ? <TrendingDown className="h-3.5 w-3.5" /> : <Minus className="h-3.5 w-3.5" />;

  function downloadFactSheet() {
    const lines = [
      `# Ficha técnica — ${fact.name}`,
      `# Observatorio ENSO Perú`,
      `# Fecha de generación: ${new Date().toISOString()}`,
      `# Indicador: ${fact.indicatorId}`,
      `# Alcance: ${fact.scope}`,
      `# Unidades: ${fact.units}`,
      `# Región: ${fact.region}`,
      `# Nivel: ${fact.level ?? "—"}`,
      `# Agregación: ${fact.aggregation}`,
      `# Climatología: ${fact.climatology}`,
      `# Dataset: ${fact.dataset}`,
      `# Fuente: ${src ? src.institution + " — " + src.product : fact.sourceId}`,
      `# URL: ${src?.url ?? ""}`,
      `# Convención de signos: ${fact.signConvention}`,
      `# Clasificación: ${fact.isOfficial ? "Oficial" : "Derivada por el observatorio"}`,
      ``,
      `## Estadísticas (historia completa: ${fact.totalMonths} meses)`,
      `valor_actual,${fact.latestValue ?? ""}`,
      `mes_actual,${fact.latestMonth}`,
      `media,${fact.mean}`,
      `desviacion_estandar,${fact.std}`,
      `minimo,${fact.min}`,
      `maximo,${fact.max}`,
      `percentil_actual,${fact.percentileLatest ?? ""}`,
      `tendencia_12m_por_mes,${fact.trend12m}`,
      `tendencia_24m_por_mes,${fact.trend24m}`,
      `meses_positivos,${fact.positiveMonths}`,
      `meses_negativos,${fact.negativeMonths}`,
      `meses_totales,${fact.totalMonths}`,
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `ficha-tecnica-${fact.indicatorId}.csv`; a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-5">
      <InfoNote tone="info" title="Fichas técnicas por indicador">
        Informe detallado de cada indicador con estadísticas completas (media, desviación, extremos,
        percentil del valor actual, tendencias a 12 y 24 meses), metadatos científicos y fuente. Cálculo
        determinista en código; el modelo no participa. Descargable en CSV.
      </InfoNote>

      {/* Selector */}
      <SectionCard title={<span className="flex items-center gap-2"><FileText className="h-4 w-4" /> Seleccionar indicador</span>}>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Selector de indicador">
          {INDICATOR_OPTIONS.map((id) => (
            <button
              key={id}
              onClick={() => setIndicatorId(id)}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium enso-focus-ring ${indicatorId === id ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted"}`}
              aria-pressed={indicatorId === id}
            >
              <ScopeBadge scope={INDICATOR_BY_ID[id].scope} />
              {INDICATOR_BY_ID[id].shortName}
            </button>
          ))}
        </div>
      </SectionCard>

      {/* Cabecera de la ficha */}
      <SectionCard
        title={<span className="flex items-center gap-2"><FileText className="h-4 w-4" /> {fact.name}</span>}
        right={
          <div className="flex items-center gap-2">
            <ScopeBadge scope={fact.scope} />
            <StatusPill label={fact.isOfficial ? "Oficial" : "Derivada"} tone={fact.isOfficial ? "warm" : "neutral"} />
            <button onClick={downloadFactSheet} className="inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-medium hover:bg-muted" title="Descargar ficha en CSV">
              <Download className="h-3.5 w-3.5" /> CSV
            </button>
          </div>
        }
      >
        <div className="grid gap-4 md:grid-cols-3">
          {/* Valor actual */}
          <div>
            <p className="text-[11px] text-muted-foreground">Valor actual ({fmtMonth(fact.latestMonth)})</p>
            <BigValue
              value={fmtValue(fact.latestValue, fact.units).replace(/ (°C|m\/s|m)$/, "")}
              units={fact.units === "degC" ? "°C" : fact.units === "m_per_s" ? "m/s" : fact.units === "m" ? "m" : ""}
              tone={fact.latestValue !== null && fact.latestValue > 0 ? "warm" : fact.latestValue !== null && fact.latestValue < 0 ? "cool" : "neutral"}
            />
            <p className="mt-1 text-[11px] text-muted-foreground">
              Percentil histórico: P{fact.percentileLatest ?? "—"}
            </p>
          </div>
          {/* Media y dispersión */}
          <div className="space-y-1 text-xs">
            <FieldLine label="Media histórica">{fact.mean > 0 ? "+" : ""}{fact.mean}</FieldLine>
            <FieldLine label="Desviación estándar">±{fact.std}</FieldLine>
            <FieldLine label="Mínimo">{fact.min > 0 ? "+" : ""}{fact.min}</FieldLine>
            <FieldLine label="Máximo">{fact.max > 0 ? "+" : ""}{fact.max}</FieldLine>
          </div>
          {/* Tendencias */}
          <div className="space-y-2">
            <div>
              <p className="text-[11px] text-muted-foreground">Tendencia 12 meses</p>
              <div className="flex items-center gap-2">
                {trendIcon}
                <span className="text-sm font-bold enso-num" style={{ color: trend12Tone === "warm" ? "var(--enso-warm)" : trend12Tone === "cool" ? "var(--enso-cool)" : undefined }}>
                  {fact.trend12m > 0 ? "+" : ""}{(fact.trend12m * 12).toFixed(3)}/año
                </span>
              </div>
            </div>
            <div>
              <p className="text-[11px] text-muted-foreground">Tendencia 24 meses</p>
              <span className="text-sm font-bold enso-num" style={{ color: fact.trend24m > 0.005 ? "var(--enso-warm)" : fact.trend24m < -0.005 ? "var(--enso-cool)" : undefined }}>
                {fact.trend24m > 0 ? "+" : ""}{(fact.trend24m * 12).toFixed(3)}/año
              </span>
            </div>
          </div>
        </div>
      </SectionCard>

      {/* Metadatos científicos */}
      <div className="grid gap-4 md:grid-cols-2">
        <SectionCard title="Definición y metodología">
          <div className="space-y-1 text-xs">
            <FieldLine label="Indicador">{fact.indicatorId}</FieldLine>
            <FieldLine label="Nombre formal">{fact.name}</FieldLine>
            <FieldLine label="Variable">{ind.variable}</FieldLine>
            <FieldLine label="Alcance">{fact.scope === "coastal" ? "Costero" : "Cuenca"}</FieldLine>
            <FieldLine label="Región">{fact.region}</FieldLine>
            <FieldLine label="Nivel">{fact.level ?? "—"}</FieldLine>
            <FieldLine label="Agregación">{fact.aggregation}</FieldLine>
            <FieldLine label="Climatología">{fact.climatology}</FieldLine>
            <FieldLine label="Dataset">{fact.dataset}</FieldLine>
          </div>
        </SectionCard>
        <SectionCard title="Convención y fuente">
          <div className="space-y-2 text-xs">
            <div>
              <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Convención de signos</p>
              <p className="mt-0.5 leading-relaxed">{fact.signConvention}</p>
            </div>
            <div className="border-t pt-2">
              <FieldLine label="Fuente">{src ? src.institution : fact.sourceId}</FieldLine>
              <FieldLine label="Producto">{src ? src.product : "—"}</FieldLine>
              <FieldLine label="Licencia">{src ? src.license : "—"}</FieldLine>
              <FieldLine label="Frecuencia">{src ? src.updateFrequency : "—"}</FieldLine>
              {src && (
                <a href={src.url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-flex items-center gap-1 text-[11px] text-[color:var(--enso-basin)] hover:underline break-all">
                  {src.url.slice(0, 60)}…
                </a>
              )}
            </div>
          </div>
        </SectionCard>
      </div>

      {/* Distribución de signos */}
      <SectionCard title="Distribución de valores" description="Proporción de meses positivos vs negativos en la historia completa.">
        <div className="space-y-3">
          <div>
            <div className="flex items-center justify-between text-xs mb-1">
              <span className="text-[color:var(--enso-warm)] font-medium">Positivos ({fact.positiveMonths})</span>
              <span className="text-muted-foreground">{Math.round((fact.positiveMonths / fact.totalMonths) * 100)}%</span>
              <span className="text-[color:var(--enso-cool)] font-medium">Negativos ({fact.negativeMonths})</span>
            </div>
            <div className="flex h-4 rounded-full overflow-hidden">
              <div className="bg-[color:var(--enso-warm)]" style={{ width: `${(fact.positiveMonths / fact.totalMonths) * 100}%` }} />
              <div className="bg-[color:var(--enso-cool)]" style={{ width: `${(fact.negativeMonths / fact.totalMonths) * 100}%` }} />
            </div>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Total: {fact.totalMonths} meses con datos (1990–2026). La distribución refleja el sesgo
            histórico del indicador.
          </p>
        </div>
      </SectionCard>

      {/* Umbrales si existen */}
      {ind.thresholds && (
        <SectionCard title="Umbrales y categorías" description="Condiciones de clasificación derivadas por el observatorio.">
          <div className="overflow-x-auto enso-scroll">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">Etiqueta</th>
                  <th className="py-2 pr-3 font-medium text-right">Mínimo</th>
                  <th className="py-2 pr-3 font-medium text-right">Máximo</th>
                  <th className="py-2 font-medium">Clasificación</th>
                </tr>
              </thead>
              <tbody>
                {ind.thresholds.map((t) => (
                  <tr key={t.label} className="border-b last:border-0 hover:bg-muted/40">
                    <td className="py-2 pr-3 font-medium">{t.label}</td>
                    <td className="py-2 pr-3 text-right enso-num">{t.min === -Infinity ? "−∞" : t.min}</td>
                    <td className="py-2 pr-3 text-right enso-num">{t.max === Infinity ? "+∞" : t.max}</td>
                    <td className="py-2">{t.classification}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>
      )}
    </div>
  );
}
