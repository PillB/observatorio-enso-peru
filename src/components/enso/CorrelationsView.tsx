"use client";

import * as React from "react";
import { buildCorrelations, type CorrelationPair } from "@/lib/enso/derived";
import { generateAllSeries } from "@/lib/enso/series";
import { SectionCard, ScopeBadge, InfoNote, FieldLine } from "./primitives";
import { EnsoTimeSeries, MiniSpark } from "./charts";
import { COLOR_BASIN, COLOR_COASTAL, COLOR_WARM, COLOR_COOL } from "@/lib/enso/ui";
import { GitCompare, TrendingDown, TrendingUp } from "lucide-react";

const COLORS: Record<string, string> = {
  nino12: "var(--enso-coastal)", icen: "var(--enso-coastal)",
  nino34: "var(--enso-basin)", roni: "var(--enso-basin)",
  soi: "var(--enso-cool)", u850: "var(--enso-warm)", d20: "#7c3aed",
};

export function CorrelationsView() {
  const pairs = React.useMemo(() => buildCorrelations(), []);
  const all = React.useMemo(() => generateAllSeries(), []);

  // Top 4 pares para scatter
  const top = pairs.slice(0, 4);

  return (
    <div className="space-y-5">
      <InfoNote tone="info" title="Correlaciones entre indicadores — cálculo determinista">
        Los coeficientes de Pearson se calculan en código sobre toda la historia disponible
        (1990–2026). El modelo no participa en el cálculo. Las correlaciones no implican
        causalidad; reflejan relaciones físicas conocidas del sistema ENSO. La anticorrelación SOI–
        Niño 3.4 y la profundización de D20 con El Niño son signatures físicas esperadas.
      </InfoNote>

      {/* Matriz de correlación */}
      <SectionCard title={<span className="flex items-center gap-2"><GitCompare className="h-4 w-4" /> Matriz de correlación (Pearson)</span>} description="Coeficiente r en [-1, 1] sobre la historia completa. Azul = anticorrelación, cálido = correlación positiva.">
        <CorrelationMatrix pairs={pairs} />
      </SectionCard>

      {/* Top correlaciones */}
      <div className="grid gap-4 md:grid-cols-2">
        {top.map((p) => (
          <CorrelationCard key={`${p.idA}-${p.idB}`} pair={p} all={all} />
        ))}
      </div>

      {/* Tabla completa */}
      <SectionCard title="Tabla completa de correlaciones" description="Ordenadas por valor absoluto del coeficiente descendente.">
        <div className="max-h-96 overflow-y-auto enso-scroll rounded-md border">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-muted/80 backdrop-blur">
              <tr className="text-left">
                <th className="px-2 py-1.5 font-medium">Par</th>
                <th className="px-2 py-1.5 font-medium text-right">r (Pearson)</th>
                <th className="px-2 py-1.5 font-medium">Fuerza</th>
                <th className="px-2 py-1.5 font-medium">Interpretación</th>
              </tr>
            </thead>
            <tbody>
              {pairs.map((p) => (
                <tr key={`${p.idA}-${p.idB}`} className="border-b last:border-0 hover:bg-muted/40">
                  <td className="px-2 py-1.5 font-medium whitespace-nowrap">{p.labelA} ↔ {p.labelB}</td>
                  <td className="px-2 py-1.5 text-right enso-num" style={{ color: p.pearson < -0.3 ? "var(--enso-cool)" : p.pearson > 0.3 ? "var(--enso-warm)" : undefined }}>
                    {p.pearson > 0 ? "+" : ""}{p.pearson.toFixed(2)}
                  </td>
                  <td className="px-2 py-1.5">{p.strength}</td>
                  <td className="px-2 py-1.5 text-muted-foreground text-[11px]">{p.interpretation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>

      <InfoNote tone="muted" title="Notas físicas">
        <ul className="space-y-1 list-disc pl-4">
          <li><strong>SOI ↔ Niño 3.4</strong>: anticorrelación esperada (componente atmosférica vs oceánica del ENSO de cuenca).</li>
          <li><strong>D20 ↔ Niño 3.4</strong>: correlación positiva (termoclina se profundiza con El Niño de cuenca).</li>
          <li><strong>u850 ↔ Niño 3.4</strong>: correlación positiva (anomalías del oeste acompañan a El Niño).</li>
          <li><strong>Niño 1+2 ↔ Niño 3.4</strong>: correlación parcial — la costa y la cuenca pueden divergir (caso paradigmático: 2017).</li>
          <li><strong>ICEN ↔ Niño 1+2</strong> y <strong>RONI ↔ Niño 3.4</strong>: alta correlación por construcción (son medias móviles).</li>
        </ul>
      </InfoNote>
    </div>
  );
}

function CorrelationCard({ pair, all }: { pair: CorrelationPair; all: ReturnType<typeof generateAllSeries> }) {
  const isAnti = pair.pearson < 0;
  const colorA = COLORS[pair.idA] ?? "var(--enso-basin)";
  const colorB = COLORS[pair.idB] ?? "var(--enso-coastal)";
  const dataA = all[pair.idA].points.slice(-120);
  const dataB = all[pair.idB].points.slice(-120);

  return (
    <SectionCard
      title={<span className="flex items-center gap-2">{pair.labelA} ↔ {pair.labelB}</span>}
      right={
        <span className="flex items-center gap-1 text-xs font-medium" style={{ color: isAnti ? "var(--enso-cool)" : "var(--enso-warm)" }}>
          {isAnti ? <TrendingDown className="h-3.5 w-3.5" /> : <TrendingUp className="h-3.5 w-3.5" />}
          r = {pair.pearson > 0 ? "+" : ""}{pair.pearson.toFixed(2)}
        </span>
      }
    >
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted-foreground">Fuerza</span>
          <span className="font-medium">{pair.strength}</span>
        </div>
        <EnsoTimeSeries
          series={[
            { id: pair.idA, label: pair.labelA, color: colorA, data: dataA },
            { id: pair.idB, label: pair.labelB, color: colorB, data: dataB },
          ]}
          units={all[pair.idA].units} yLabel="" height={180} windowMonths={120}
        />
        <p className="text-[11px] text-muted-foreground border-t pt-2">{pair.interpretation}</p>
      </div>
    </SectionCard>
  );
}

/** Matriz de correlación N×N en SVG con celdas coloreadas. */
function CorrelationMatrix({ pairs }: { pairs: CorrelationPair[] }) {
  const ids = Array.from(new Set(pairs.flatMap((p) => [p.idA, p.idB])));
  const labels: Record<string, string> = {
    nino12: "Niño 1+2", icen: "ICEN", nino34: "Niño 3.4", roni: "RONI",
    soi: "SOI", u850: "u850", d20: "D20",
  };
  const n = ids.length;
  const lookup = new Map<string, number>();
  for (const p of pairs) {
    lookup.set(`${p.idA}-${p.idB}`, p.pearson);
    lookup.set(`${p.idB}-${p.idA}`, p.pearson);
  }

  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(560);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => { for (const x of e) setW(Math.max(360, x.contentRect.width)); });
    ro.observe(ref.current); return () => ro.disconnect();
  }, []);

  const cell = Math.min(48, Math.max(32, (w - 120) / n));
  const labelW = 70;
  const h = cell * n + 28;
  const color = (r: number) => {
    if (r > 0) return `color-mix(in oklch, var(--card) ${(1 - r) * 100}%, var(--enso-warm) ${r * 100}%)`;
    return `color-mix(in oklch, var(--card) ${(1 - Math.abs(r)) * 100}%, var(--enso-cool) ${Math.abs(r) * 100}%)`;
  };

  return (
    <div ref={ref} className="w-full overflow-x-auto enso-scroll">
      <svg width={labelW + cell * n + 8} height={h + cell + 8} role="img" aria-label="Matriz de correlación entre indicadores">
        {/* etiquetas de columna */}
        {ids.map((id, j) => (
          <text key={id} x={labelW + j * cell + cell / 2} y={cell - 4} textAnchor="middle" fontSize={9} fill="currentColor" fillOpacity={0.7} transform={`rotate(-35 ${labelW + j * cell + cell / 2} ${cell - 4})`}>
            {labels[id] ?? id}
          </text>
        ))}
        {/* filas */}
        {ids.map((idA, i) => (
          <g key={idA}>
            <text x={labelW - 4} y={cell + i * cell + cell / 2 + 3} textAnchor="end" fontSize={9} fill="currentColor" fillOpacity={0.7}>{labels[idA] ?? idA}</text>
            {ids.map((idB, j) => {
              const r = i === j ? 1 : (lookup.get(`${idA}-${idB}`) ?? 0);
              return (
                <g key={idB}>
                  <rect x={labelW + j * cell} y={cell + i * cell} width={cell - 1} height={cell - 1} fill={color(r)} rx={2} />
                  <text x={labelW + j * cell + cell / 2} y={cell + i * cell + cell / 2 + 3} textAnchor="middle" fontSize={9} fill="var(--foreground)" fillOpacity={0.85} fontWeight={Math.abs(r) >= 0.6 ? "bold" : "normal"}>
                    {i === j ? "1.00" : (r > 0 ? "+" : "") + r.toFixed(2)}
                  </text>
                </g>
              );
            })}
          </g>
        ))}
      </svg>
      <div className="mt-2 flex items-center gap-3 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1"><span className="h-3 w-3 rounded" style={{ background: "var(--enso-cool)" }} /> −1 (anticorrelación)</span>
        <span className="flex items-center gap-1"><span className="h-3 w-3 rounded border" style={{ background: "var(--card)" }} /> 0</span>
        <span className="flex items-center gap-1"><span className="h-3 w-3 rounded" style={{ background: "var(--enso-warm)" }} /> +1 (correlación)</span>
      </div>
    </div>
  );
}
