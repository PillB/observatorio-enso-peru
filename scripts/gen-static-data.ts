// Generador de artefactos estáticos para public/data/.
// Ejecutar con: bun run scripts/gen-static-data.ts
// Produce CSV y JSON a partir de la fuente única de verdad (src/lib/enso).

import { generateAllSeries, MONTHS, AS_OF_DATE, AS_OF_MONTH, sstGridForMonth, d20GridForMonth, windGridForMonth, generateForecasts, generateRegionImpacts } from "../src/lib/enso/series";
import { buildCurrentStatus, buildQualitySummary } from "../src/lib/enso/derived";
import { INDICATORS } from "../src/lib/enso/methodology";
import { SOURCES } from "../src/lib/enso/sources";
import { writeFileSync, mkdirSync } from "fs";
import { join } from "path";

const OUT = join(import.meta.dir, "..", "public", "data");
mkdirSync(OUT, { recursive: true });

function esc(v: unknown): string {
  if (v === null || v === undefined) return "";
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

const all = generateAllSeries();
const ids = Object.keys(all);

// 1) CSV combinado (todas las series por mes)
{
  const header = ["month", ...ids];
  const rows = MONTHS.map((m, i) => {
    const row = [m];
    for (const id of ids) row.push(all[id].points[i].value ?? "");
    return row.map(esc).join(",");
  });
  const csv = `${header.join(",")}\n${rows.join("\n")}`;
  writeFileSync(join(OUT, "observatorio-enso-todas-las-series.csv"), csv);
}

// 2) CSV por indicador con metadatos
for (const id of ids) {
  const s = all[id];
  const ind = INDICATORS.find((x) => x.id === id)!;
  const src = SOURCES.find((x) => x.id === s.sourceId)!;
  const meta = [
    `# Observatorio ENSO Perú — ${ind.name}`,
    `# Unidades: ${ind.units}`,
    `# Región: ${ind.region}`,
    `# Agregación: ${ind.aggregation}`,
    `# Climatología: ${ind.climatology}`,
    `# Dataset: ${ind.dataset}`,
    `# Fuente: ${src.institution} — ${src.product}`,
    `# URL: ${src.url}`,
    `# Convención de signos: ${ind.signConvention}`,
    `# Checksum: ${s.checksum}`,
    `# Fecha de corte: ${AS_OF_DATE}`,
  ].join("\n");
  const rows = s.points.map((p) => [p.month, p.value ?? "", p.flag ?? ""].map(esc).join(","));
  const csv = `${meta}\nmonth,value,flag\n${rows.join("\n")}`;
  writeFileSync(join(OUT, `${id}.csv`), csv);
}

// 3) status.json
{
  const status = buildCurrentStatus();
  writeFileSync(join(OUT, "status.json"), JSON.stringify(status, null, 2));
}

// 4) manifest.json
{
  const manifest = {
    name: "Observatorio ENSO Perú",
    dataVersion: "1.0.0",
    generatedAt: new Date().toISOString(),
    asOf: AS_OF_DATE,
    asOfMonth: AS_OF_MONTH,
    coverage: `${MONTHS[0]} .. ${MONTHS[MONTHS.length - 1]} (mensual)`,
    indicators: ids.map((id) => ({
      id,
      label: all[id].label,
      units: all[id].units,
      scope: all[id].scope,
      sourceId: all[id].sourceId,
      checksum: all[id].checksum,
      file: `${id}.csv`,
    })),
    files: {
      combined: "observatorio-enso-todas-las-series.csv",
      status: "status.json",
      quality: "quality.json",
      sources: "sources.json",
      indicators: "indicators.json",
      allSeries: "all-series.json",
      latestGrid: "latest-grid.json",
    },
  };
  writeFileSync(join(OUT, "manifest.json"), JSON.stringify(manifest, null, 2));
}

// 5) quality.json
writeFileSync(join(OUT, "quality.json"), JSON.stringify(buildQualitySummary(), null, 2));

// 6) sources.json + indicators.json
writeFileSync(join(OUT, "sources.json"), JSON.stringify(SOURCES, null, 2));
writeFileSync(join(OUT, "indicators.json"), JSON.stringify(INDICATORS, null, 2));

// 7) all-series.json
{
  const payload = {
    asOf: AS_OF_DATE,
    dataVersion: "1.0.0",
    series: Object.fromEntries(
      Object.entries(all).map(([id, s]) => [
        id,
        { indicatorId: id, label: s.label, units: s.units, scope: s.scope, sourceId: s.sourceId, checksum: s.checksum, points: s.points },
      ])
    ),
  };
  writeFileSync(join(OUT, "all-series.json"), JSON.stringify(payload, null, 2));
}

// 8) latest-grid.json
{
  const lastIdx = MONTHS.length - 1;
  const grids = {
    month: MONTHS[lastIdx],
    sst: sstGridForMonth(lastIdx),
    d20: d20GridForMonth(lastIdx),
    wind: windGridForMonth(lastIdx),
  };
  writeFileSync(join(OUT, "latest-grid.json"), JSON.stringify(grids, null, 2));
}

// 9) forecasts.json + regional-impact.json
writeFileSync(join(OUT, "forecasts.json"), JSON.stringify(generateForecasts(), null, 2));
writeFileSync(join(OUT, "regional-impact.json"), JSON.stringify(generateRegionImpacts(), null, 2));

console.log(`Artefactos estáticos generados en public/data/ (${ids.length} CSV + 10 JSON)`);
