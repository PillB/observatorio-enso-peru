"use client";

import * as React from "react";
import { buildBoxPlot, type BoxPlotResult, type BoxStats } from "@/lib/enso/derived";
import { INDICATOR_BY_ID } from "@/lib/enso/methodology";
import { SectionCard, ScopeBadge, InfoNote, FieldLine } from "./primitives";
import { fmtValue } from "@/lib/enso/ui";
import { BarChart3, Box } from "lucide-react";

const INDICATOR_OPTIONS = ["nino12", "icen", "nino34", "roni", "soi", "u850", "d20"];
const CATEGORY_COLORS: Record<string, string> = {
  "El Niño": "var(--enso-warm)",
  "Neutral": "var(--muted-foreground)",
  "La Niña": "var(--enso-cool)",
};

export function BoxPlotView() {
  const [indicatorId, setIndicatorId] = React.useState("nino34");
  const result = React.useMemo(() => buildBoxPlot(indicatorId), [indicatorId]);
  if (!result) return null;

  return (
    <div className="space-y-5">
      <InfoNote tone="info" title="Caja de bigotes — distribución por categoría de evento">
        Para cada indicador, se agrupan los valores mensuales por la fase ENSO de cuenca vigente en
        ese mes (El Niño / Neutral / La Niña, según Niño 3.4 ±0.5 °C) y se calculan los estadísticos
        de caja: mediana, cuartiles Q1/Q3, bigotes (1.5×RIC) y atípicos. Permite comparar la
        distribución del indicador entre fases. Cálculo determinista en código; el modelo no participa.
      </InfoNote>

      {/* Selector */}
      <SectionCard title={<span className="flex items-center gap-2"><Box className="h-4 w-4" /> Seleccionar indicador</span>}>
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

      {/* Gráfico de caja */}
      <SectionCard
        title={<span className="flex items-center gap-2"><BarChart3 className="h-4 w-4" /> Distribución de {result.label} por fase ENSO</span>}
        description="Caja: Q1–Q3 con mediana. Bigotes: 1.5×RIC. Puntos: atípicos. La fase se define por Niño 3.4 ±0.5 °C."
      >
        <BoxPlotChart result={result} />
      </SectionCard>

      {/* Tabla de estadísticos */}
      <SectionCard title="Estadísticos por categoría" description="Mediana, cuartiles, bigotes, extremos y conteo.">
        <div className="overflow-x-auto enso-scroll">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="py-2 pr-3 font-medium">Categoría</th>
                <th className="py-2 pr-3 font-medium text-right">Mínimo</th>
                <th className="py-2 pr-3 font-medium text-right">Q1</th>
                <th className="py-2 pr-3 font-medium text-right">Mediana</th>
                <th className="py-2 pr-3 font-medium text-right">Q3</th>
                <th className="py-2 pr-3 font-medium text-right">Máximo</th>
                <th className="py-2 pr-3 font-medium text-right">Bigote min</th>
                <th className="py-2 pr-3 font-medium text-right">Bigote max</th>
                <th className="py-2 pr-3 font-medium text-right">Atípicos</th>
                <th className="py-2 pr-3 font-medium text-right">N° meses</th>
              </tr>
            </thead>
            <tbody>
              {result.boxes.map((b) => (
                <tr key={b.category} className="border-b last:border-0 hover:bg-muted/40">
                  <td className="py-2 pr-3">
                    <span className="inline-flex items-center gap-1.5">
                      <span className="h-3 w-3 rounded" style={{ background: CATEGORY_COLORS[b.category] }} />
                      <span className="font-medium">{b.category}</span>
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-right enso-num">{b.min > 0 ? "+" : ""}{b.min}</td>
                  <td className="py-2 pr-3 text-right enso-num">{b.q1 > 0 ? "+" : ""}{b.q1}</td>
                  <td className="py-2 pr-3 text-right enso-num font-bold">{b.median > 0 ? "+" : ""}{b.median}</td>
                  <td className="py-2 pr-3 text-right enso-num">{b.q3 > 0 ? "+" : ""}{b.q3}</td>
                  <td className="py-2 pr-3 text-right enso-num">{b.max > 0 ? "+" : ""}{b.max}</td>
                  <td className="py-2 pr-3 text-right enso-num text-muted-foreground">{b.whiskerMin > 0 ? "+" : ""}{b.whiskerMin}</td>
                  <td className="py-2 pr-3 text-right enso-num text-muted-foreground">{b.whiskerMax > 0 ? "+" : ""}{b.whiskerMax}</td>
                  <td className="py-2 pr-3 text-right enso-num">{b.outliers.length}</td>
                  <td className="py-2 pr-3 text-right enso-num">{b.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>

      <InfoNote tone="muted" title="Interpretación">
        <ul className="space-y-1 list-disc pl-4">
          <li>La <strong>mediana</strong> (línea central) muestra el valor típico del indicador en cada fase.</li>
          <li>La <strong>caja</strong> (Q1–Q3) contiene el 50% central de los valores; su amplitud indica la dispersión.</li>
          <li>Los <strong>bigotes</strong> se extienden hasta 1.5× el rango intercuartílico (RIC).</li>
          <li>Los <strong>atípicos</strong> (puntos) son valores fuera de los bigotes; pueden corresponder a eventos extremos.</li>
          <li>La separación de cajas entre fases indica la capacidad del indicador para discriminar fases ENSO.</li>
        </ul>
      </InfoNote>
    </div>
  );
}

/** Gráfico de caja de bigotes en SVG. */
function BoxPlotChart({ result }: { result: BoxPlotResult }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(640);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => { for (const x of e) setW(Math.max(320, x.contentRect.width)); });
    ro.observe(ref.current); return () => ro.disconnect();
  }, []);
  const h = 320;
  const padL = 48, padR = 16, padT = 16, padB = 36;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  const allVals = result.boxes.flatMap((b) => [b.min, b.max, ...b.outliers]);
  const min = Math.min(...allVals) - 0.3;
  const max = Math.max(...allVals) + 0.3;
  const boxWidth = plotW / (result.boxes.length * 2);
  const sx = (i: number) => padL + (i + 0.5) * (plotW / result.boxes.length);
  const sy = (v: number) => padT + ((max - v) / (max - min)) * plotH;

  return (
    <div ref={ref} className="w-full">
      <svg width={w} height={h} role="img" aria-label={`Caja de bigotes de ${result.label}`}>
        {/* línea cero */}
        {min < 0 && max > 0 && (
          <line x1={padL} y1={sy(0)} x2={padL + plotW} y2={sy(0)} stroke="currentColor" strokeOpacity={0.3} strokeDasharray="4 3" />
        )}
        {/* cajas */}
        {result.boxes.map((b, i) => {
          if (b.count === 0) return null;
          const cx = sx(i);
          const color = CATEGORY_COLORS[b.category];
          return (
            <g key={b.category}>
              {/* bigote vertical */}
              <line x1={cx} y1={sy(b.whiskerMax)} x2={cx} y2={sy(b.whiskerMin)} stroke={color} strokeWidth={1.5} />
              {/* bigotes horizontales */}
              <line x1={cx - boxWidth / 4} y1={sy(b.whiskerMax)} x2={cx + boxWidth / 4} y2={sy(b.whiskerMax)} stroke={color} strokeWidth={1.5} />
              <line x1={cx - boxWidth / 4} y1={sy(b.whiskerMin)} x2={cx + boxWidth / 4} y2={sy(b.whiskerMin)} stroke={color} strokeWidth={1.5} />
              {/* caja */}
              <rect
                x={cx - boxWidth / 2} y={sy(b.q3)}
                width={boxWidth} height={sy(b.q1) - sy(b.q3)}
                fill={color} fillOpacity={0.25} stroke={color} strokeWidth={1.5} rx={2}
              />
              {/* mediana */}
              <line x1={cx - boxWidth / 2} y1={sy(b.median)} x2={cx + boxWidth / 2} y2={sy(b.median)} stroke={color} strokeWidth={2.5} />
              {/* atípicos */}
              {b.outliers.map((v, j) => (
                <circle key={j} cx={cx + (Math.random() - 0.5) * boxWidth * 0.6} cy={sy(v)} r={2.5} fill={color} fillOpacity={0.6} />
              ))}
              {/* etiqueta */}
              <text x={cx} y={h - 18} textAnchor="middle" fontSize={11} fill={color} fontWeight="bold">{b.category}</text>
              <text x={cx} y={h - 6} textAnchor="middle" fontSize={9} fill="currentColor" fillOpacity={0.6}>n={b.count} · mediana {b.median > 0 ? "+" : ""}{b.median}</text>
            </g>
          );
        })}
        {/* ejes */}
        <line x1={padL} y1={padT} x2={padL} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.3} />
        <line x1={padL} y1={padT + plotH} x2={padL + plotW} y2={padT + plotH} stroke="currentColor" strokeOpacity={0.3} />
        {[max, (max + min) / 2, min].map((v, i) => (
          <text key={i} x={padL - 6} y={sy(v) + 3} textAnchor="end" fontSize={9} fill="currentColor" fillOpacity={0.6}>{v.toFixed(1)}</text>
        ))}
      </svg>
    </div>
  );
}
