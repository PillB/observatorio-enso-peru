import { NextRequest, NextResponse } from "next/server";
import { generateAllSeries, MONTHS } from "@/lib/enso/series";
import { INDICATOR_BY_ID } from "@/lib/enso/methodology";
import { getSource } from "@/lib/enso/sources";

// Exportación de datos normalizados del observatorio.
// Formatos: json (por defecto) o csv. Un único origen de verdad.

export const runtime = "nodejs";

function toCSV(header: string[], rows: (string | number | null)[][]): string {
  const esc = (v: string | number | null) => {
    if (v === null || v === undefined) return "";
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [header, ...rows].map((r) => r.map(esc).join(",")).join("\n");
}

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const format = (url.searchParams.get("format") ?? "json").toLowerCase();
  const dataset = (url.searchParams.get("dataset") ?? "all").toLowerCase();

  const all = generateAllSeries();
  const ids = Object.keys(all);

  if (format === "csv") {
    if (dataset !== "all" && all[dataset]) {
      const s = all[dataset];
      const ind = INDICATOR_BY_ID[dataset];
      const src = getSource(s.sourceId);
      const meta = [
        `# Observatorio ENSO Perú — ${ind?.name ?? dataset}`,
        `# Unidades: ${ind?.units ?? ""}`,
        `# Región: ${ind?.region ?? ""}`,
        `# Agregación: ${ind?.aggregation ?? ""}`,
        `# Climatología: ${ind?.climatology ?? ""}`,
        `# Dataset: ${ind?.dataset ?? ""}`,
        `# Fuente: ${src ? src.institution + " — " + src.product : s.sourceId}`,
        `# URL: ${src?.url ?? ""}`,
        `# Convención de signos: ${ind?.signConvention ?? ""}`,
        `# Suma de comprobación: ${s.checksum}`,
        `# Fecha de corte: ${"2026-08-02"}`,
      ].join("\n");
      const rows = s.points.map((p) => [p.month, p.value, p.flag ?? ""]);
      const csv = `${meta}\nmonth,value,flag\n${toCSV([], rows)}`;
      return new NextResponse(csv, {
        headers: {
          "Content-Type": "text/csv; charset=utf-8",
          "Content-Disposition": `attachment; filename="${dataset}.csv"`,
        },
      });
    }
    // CSV combinado (todas las series en columnas por mes).
    const header = ["month", ...ids];
    const rows = MONTHS.map((m, i) => {
      const row: (string | number | null)[] = [m];
      for (const id of ids) row.push(all[id].points[i].value);
      return row;
    });
    const csv = toCSV(header, rows);
    return new NextResponse(csv, {
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": `attachment; filename="observatorio-enso-todas-las-series.csv"`,
      },
    });
  }

  // JSON por defecto
  const payload = {
    generatedAt: new Date().toISOString(),
    asOf: "2026-08-02",
    dataVersion: "1.0.0",
    series: Object.fromEntries(
      Object.entries(all).map(([id, s]) => [
        id,
        {
          indicatorId: id,
          label: s.label,
          units: s.units,
          scope: s.scope,
          sourceId: s.sourceId,
          checksum: s.checksum,
          points: s.points,
        },
      ])
    ),
  };
  return NextResponse.json(payload);
}
