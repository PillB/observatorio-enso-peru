"use client";

import * as React from "react";
import { generateAllSeries, MONTHS } from "@/lib/enso/series";
import { INDICATOR_BY_ID } from "@/lib/enso/methodology";
import { getSource } from "@/lib/enso/sources";
import { SectionCard, ScopeBadge, InfoNote } from "./primitives";
import { fmtMonth, fmtValue } from "@/lib/enso/ui";
import { Download, FileSpreadsheet, Filter } from "lucide-react";

type Row = { month: string } & Record<string, number | null>;

export function DownloadsView() {
  const all = generateAllSeries();
  const ids = Object.keys(all);

  // Filtros
  const [from, setFrom] = React.useState("");
  const [to, setTo] = React.useState("");
  const [q, setQ] = React.useState("");
  const [sortKey, setSortKey] = React.useState<string>("month");
  const [sortDir, setSortDir] = React.useState<"asc" | "desc">("desc");
  const [page, setPage] = React.useState(0);
  const pageSize = 24;

  // Construye filas + aplica filtros y orden. El conjunto es pequeño (~440
  // filas mensuales) y estable; se calcula en cada render sin memoización
  // manual para evitar conflictos con el React Compiler.
  const filtered = (() => {
    let rows: Row[] = MONTHS.map((m, i) => {
      const r: Row = { month: m };
      for (const id of ids) r[id] = all[id].points[i].value;
      return r;
    });
    if (from) rows = rows.filter((r) => r.month >= from);
    if (to) rows = rows.filter((r) => r.month <= to);
    if (q.trim()) rows = rows.filter((r) => r.month.includes(q.trim()));
    const sorted = [...rows].sort((a, b) => {
      const av = a[sortKey]; const bv = b[sortKey];
      if (sortKey === "month") return sortDir === "asc" ? a.month.localeCompare(b.month) : b.month.localeCompare(a.month);
      const an = av === null ? -Infinity : (av as number);
      const bn = bv === null ? -Infinity : (bv as number);
      return sortDir === "asc" ? an - bn : bn - an;
    });
    return sorted;
  })();

  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const pageRows = filtered.slice(safePage * pageSize, (safePage + 1) * pageSize);

  function toggleSort(key: string) {
    if (sortKey === key) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDir("desc"); }
  }

  function downloadCSV(scope: "all" | string) {
    const header = ["month", ...ids];
    const esc = (v: unknown) => (v === null || v === undefined ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
    const lines = filtered.map((r) => header.map((h) => esc(h === "month" ? r.month : r[h])).join(","));
    const csv = `${header.join(",")}\n${lines.join("\n")}`;
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = scope === "all" ? "observatorio-enso-filtrado.csv" : `${scope}-filtrado.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function downloadSeriesCSV(id: string) {
    const s = all[id];
    const ind = INDICATOR_BY_ID[id];
    const src = getSource(s.sourceId);
    const meta = [
      `# Observatorio ENSO Perú — ${ind.name}`,
      `# Unidades: ${ind.units}`,
      `# Región: ${ind.region}`,
      `# Climatología: ${ind.climatology}`,
      `# Dataset: ${ind.dataset}`,
      `# Fuente: ${src ? src.institution + " — " + src.product : s.sourceId}`,
      `# URL: ${src?.url ?? ""}`,
      `# Convención: ${ind.signConvention}`,
      `# Checksum: ${s.checksum}`,
    ].join("\n");
    const lines = s.points.map((p) => `${p.month},${p.value === null ? "" : p.value},${p.flag ?? ""}`);
    const csv = `${meta}\nmonth,value,flag\n${lines.join("\n")}`;
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `${id}.csv`; a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-5">
      <InfoNote tone="info" title="Descargas de datos normalizados">
        Todas las tablas, gráficos, descargas y respuestas del asistente se derivan de la{" "}
        <strong>misma fuente única de verdad</strong>. Los CSV incluyen metadatos (unidades, región,
        climatología, fuente, convención de signos y suma de comprobación). Los datos faltantes se
        preservan como celdas vacías, nunca se sustituyen por valores fabricados.
      </InfoNote>

      {/* Descargas por serie */}
      <SectionCard title="Descargar series individuales" description="CSV completo con metadatos y suma de comprobación (checksum).">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {ids.map((id) => {
            const s = all[id];
            const ind = INDICATOR_BY_ID[id];
            return (
              <button
                key={id}
                onClick={() => downloadSeriesCSV(id)}
                className="group flex items-center justify-between gap-2 rounded-lg border px-3 py-2 text-left text-xs hover:bg-muted"
              >
                <span>
                  <span className="flex items-center gap-2 font-medium">{s.label} <ScopeBadge scope={s.scope} /></span>
                  <span className="text-muted-foreground">{ind.region}</span>
                </span>
                <FileSpreadsheet className="h-4 w-4 text-muted-foreground group-hover:text-foreground" />
              </button>
            );
          })}
        </div>
      </SectionCard>

      {/* Tabla filtrable */}
      <SectionCard
        title="Tabla histórica combinada"
        description="Filtrar por rango de meses, buscar, ordenar y descargar el resultado filtrado."
        right={
          <button onClick={() => downloadCSV("all")} className="inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-medium hover:bg-muted">
            <Download className="h-3.5 w-3.5" /> CSV filtrado
          </button>
        }
      >
        <div className="mb-3 flex flex-wrap items-end gap-3">
          <label className="text-xs">
            <span className="block text-muted-foreground mb-1">Desde</span>
            <input type="month" value={from} onChange={(e) => { setFrom(e.target.value); setPage(0); }} className="rounded-md border bg-background px-2 py-1 text-xs" />
          </label>
          <label className="text-xs">
            <span className="block text-muted-foreground mb-1">Hasta</span>
            <input type="month" value={to} onChange={(e) => { setTo(e.target.value); setPage(0); }} className="rounded-md border bg-background px-2 py-1 text-xs" />
          </label>
          <label className="text-xs">
            <span className="block text-muted-foreground mb-1">Buscar mes (AAAA-MM)</span>
            <div className="flex items-center gap-1 rounded-md border px-2 py-1">
              <Filter className="h-3 w-3 text-muted-foreground" />
              <input value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} placeholder="2023" className="bg-transparent text-xs outline-none w-24" />
            </div>
          </label>
          <span className="ml-auto text-xs text-muted-foreground">{filtered.length} filas</span>
        </div>

        <div className="max-h-[28rem] overflow-auto enso-scroll rounded-md border">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-muted/80 backdrop-blur">
              <tr className="text-left">
                <Th label="Mes" k="month" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                {ids.map((id) => (
                  <Th key={id} label={INDICATOR_BY_ID[id].shortName} k={id} sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                ))}
              </tr>
            </thead>
            <tbody>
              {pageRows.map((r) => (
                <tr key={r.month} className="border-b last:border-0 hover:bg-muted/40">
                  <td className="px-2 py-1.5 font-medium enso-num whitespace-nowrap">{fmtMonth(r.month)}</td>
                  {ids.map((id) => (
                    <td key={id} className="px-2 py-1.5 enso-num text-right">
                      {r[id] === null ? <span className="text-muted-foreground">—</span> : fmtValue(r[id] as number, all[id].units).replace(/ (°C|m\/s|m)$/, "")}
                    </td>
                  ))}
                </tr>
              ))}
              {pageRows.length === 0 && (
                <tr><td colSpan={ids.length + 1} className="px-2 py-6 text-center text-muted-foreground">Sin datos para el filtro aplicado.</td></tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Paginación */}
        <div className="mt-3 flex items-center justify-between text-xs">
          <span className="text-muted-foreground">Página {safePage + 1} de {pageCount}</span>
          <div className="flex gap-1">
            <button onClick={() => setPage(Math.max(0, safePage - 1))} disabled={safePage === 0} className="rounded-md border px-2 py-1 disabled:opacity-40 hover:bg-muted">Anterior</button>
            <button onClick={() => setPage(Math.min(pageCount - 1, safePage + 1))} disabled={safePage >= pageCount - 1} className="rounded-md border px-2 py-1 disabled:opacity-40 hover:bg-muted">Siguiente</button>
          </div>
        </div>
      </SectionCard>
    </div>
  );
}

function Th({ label, k, sortKey, sortDir, onSort }: { label: string; k: string; sortKey: string; sortDir: "asc" | "desc"; onSort: (k: string) => void }) {
  const active = sortKey === k;
  return (
    <th className="px-2 py-1.5 font-medium whitespace-nowrap">
      <button onClick={() => onSort(k)} className={`inline-flex items-center gap-1 hover:text-foreground ${active ? "text-foreground" : "text-muted-foreground"}`}>
        {label}
        <span aria-hidden>{active ? (sortDir === "asc" ? "▲" : "▼") : "↕"}</span>
      </button>
    </th>
  );
}
