"use client";

import * as React from "react";
import { buildEventCatalog, type CatalogEntry } from "@/lib/enso/derived";
import { SectionCard, ScopeBadge, InfoNote, StatusPill } from "./primitives";
import { fmtMonth } from "@/lib/enso/ui";
import { Download, Filter, Table } from "lucide-react";

const INTENSITY_RANK: Record<number, { label: string; color: string }> = {
  1: { label: "Débil", color: "var(--enso-coastal)" },
  2: { label: "Moderado", color: "var(--enso-warm)" },
  3: { label: "Fuerte", color: "var(--enso-warm)" },
  4: { label: "Muy fuerte", color: "#dc2626" },
};

export function EventCatalogView() {
  const catalog = React.useMemo(() => buildEventCatalog(), []);
  const [scope, setScope] = React.useState<"all" | "costero" | "cuenca">("all");
  const [phase, setPhase] = React.useState<"all" | "nino" | "nina">("all");
  const [minRank, setMinRank] = React.useState<1 | 2 | 3 | 4>(1);
  const [sortBy, setSortBy] = React.useState<"startMonth" | "peakValue" | "durationMonths">("startMonth");
  const [sortDir, setSortDir] = React.useState<"asc" | "desc">("desc");

  const filtered = React.useMemo(() => {
    let out = catalog;
    if (scope !== "all") out = out.filter((e) => e.scope === scope);
    if (phase !== "all") out = out.filter((e) => (phase === "nino" ? e.phase === "El Niño" : e.phase === "La Niña"));
    out = out.filter((e) => e.intensityRank >= minRank);
    out = [...out].sort((a, b) => {
      const av = a[sortBy], bv = b[sortBy];
      if (sortBy === "peakValue" || sortBy === "durationMonths") {
        return sortDir === "asc" ? (av as number) - (bv as number) : (bv as number) - (av as number);
      }
      return sortDir === "asc" ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
    });
    return out;
  }, [catalog, scope, phase, minRank, sortBy, sortDir]);

  function downloadCSV() {
    const header = ["id", "scope", "phase", "startMonth", "endMonth", "peakMonth", "peakValue", "durationMonths", "intensity", "intensityRank", "year", "decade"];
    const esc = (v: unknown) => (v === null || v === undefined ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
    const rows = filtered.map((e) => [e.id, e.scope, e.phase, e.startMonth, e.endMonth, e.peakMonth, e.peakValue, e.durationMonths, e.intensity, e.intensityRank, e.year, e.decade].map(esc).join(","));
    const csv = `${header.join(",")}\n${rows.join("\n")}`;
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "catalogo-eventos-enso.csv"; a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-5">
      <InfoNote tone="info" title="Catálogo maestro de eventos ENSO">
        Tabla exhaustiva de todos los periodos ENSO reconstruidos (costero y cuenca) con estadísticas
        completas. Filtrable por alcance, fase, intensidad y ordenamiento. Descargable en CSV.
        <strong> Reconstrucción derivada del observatorio</strong>; las declaraciones oficiales
        provienen de ENFEN y NOAA/CPC.
      </InfoNote>

      {/* Filtros */}
      <SectionCard title={<span className="flex items-center gap-2"><Filter className="h-4 w-4" /> Filtros</span>}>
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <p className="mb-1 text-[11px] text-muted-foreground">Alcance</p>
            <div className="inline-flex rounded-lg border p-0.5" role="group">
              {([["all", "Todos"], ["costero", "Costero"], ["cuenca", "Cuenca"]] as const).map(([id, label]) => (
                <button key={id} onClick={() => setScope(id)} className={`rounded-md px-2.5 py-1 text-xs font-medium ${scope === id ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`} aria-pressed={scope === id}>{label}</button>
              ))}
            </div>
          </div>
          <div>
            <p className="mb-1 text-[11px] text-muted-foreground">Fase</p>
            <div className="inline-flex rounded-lg border p-0.5" role="group">
              {([["all", "Todas"], ["nino", "El Niño"], ["nina", "La Niña"]] as const).map(([id, label]) => (
                <button key={id} onClick={() => setPhase(id)} className={`rounded-md px-2.5 py-1 text-xs font-medium ${phase === id ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`} aria-pressed={phase === id}>{label}</button>
              ))}
            </div>
          </div>
          <div>
            <p className="mb-1 text-[11px] text-muted-foreground">Intensidad mínima</p>
            <div className="inline-flex rounded-lg border p-0.5" role="group">
              {([1, 2, 3, 4] as const).map((r) => (
                <button key={r} onClick={() => setMinRank(r)} className={`rounded-md px-2.5 py-1 text-xs font-medium ${minRank === r ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`} aria-pressed={minRank === r}>{INTENSITY_RANK[r].label}</button>
              ))}
            </div>
          </div>
          <span className="ml-auto text-xs text-muted-foreground">{filtered.length} eventos</span>
        </div>
      </SectionCard>

      {/* Tabla */}
      <SectionCard
        title={<span className="flex items-center gap-2"><Table className="h-4 w-4" /> Catálogo de eventos</span>}
        right={
          <button onClick={downloadCSV} className="inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-medium hover:bg-muted" title="Descargar catálogo filtrado en CSV">
            <Download className="h-3.5 w-3.5" /> CSV
          </button>
        }
      >
        <div className="max-h-[32rem] overflow-auto enso-scroll rounded-md border">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-muted/80 backdrop-blur z-10">
              <tr className="text-left">
                <th className="px-2 py-1.5 font-medium"><SortButton label="Inicio" k="startMonth" sortBy={sortBy} sortDir={sortDir} onSort={(k) => { if (sortBy === k) setSortDir(sortDir === "asc" ? "desc" : "asc"); else { setSortBy(k); setSortDir("desc"); } }} /></th>
                <th className="px-2 py-1.5 font-medium">Fin</th>
                <th className="px-2 py-1.5 font-medium">Alcance</th>
                <th className="px-2 py-1.5 font-medium">Fase</th>
                <th className="px-2 py-1.5 font-medium"><SortButton label="Pico" k="peakValue" sortBy={sortBy} sortDir={sortDir} onSort={(k) => { if (sortBy === k) setSortDir(sortDir === "asc" ? "desc" : "asc"); else { setSortBy(k); setSortDir("desc"); } }} /></th>
                <th className="px-2 py-1.5 font-medium">Mes pico</th>
                <th className="px-2 py-1.5 font-medium"><SortButton label="Duración" k="durationMonths" sortBy={sortBy} sortDir={sortDir} onSort={(k) => { if (sortBy === k) setSortDir(sortDir === "asc" ? "desc" : "asc"); else { setSortBy(k); setSortDir("desc"); } }} /></th>
                <th className="px-2 py-1.5 font-medium">Intensidad</th>
                <th className="px-2 py-1.5 font-medium">Rango</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((e) => (
                <tr key={e.id} className="border-b last:border-0 hover:bg-muted/40">
                  <td className="px-2 py-1.5 enso-num font-medium">{fmtMonth(e.startMonth)}</td>
                  <td className="px-2 py-1.5 enso-num">{fmtMonth(e.endMonth)}</td>
                  <td className="px-2 py-1.5"><ScopeBadge scope={e.scope} /></td>
                  <td className="px-2 py-1.5"><StatusPill label={e.phase} tone={e.phase === "El Niño" ? "warm" : "cool"} /></td>
                  <td className="px-2 py-1.5 text-right enso-num font-bold" style={{ color: e.peakValue > 0 ? "var(--enso-warm)" : "var(--enso-cool)" }}>{e.peakValue > 0 ? "+" : ""}{e.peakValue}</td>
                  <td className="px-2 py-1.5 enso-num">{fmtMonth(e.peakMonth)}</td>
                  <td className="px-2 py-1.5 text-right enso-num">{e.durationMonths}</td>
                  <td className="px-2 py-1.5">{e.intensity}</td>
                  <td className="px-2 py-1.5">
                    <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium" style={{ background: `color-mix(in oklch, ${INTENSITY_RANK[e.intensityRank].color} 15%, transparent)`, color: INTENSITY_RANK[e.intensityRank].color }}>
                      {INTENSITY_RANK[e.intensityRank].label}
                    </span>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr><td colSpan={9} className="px-2 py-6 text-center text-muted-foreground">No hay eventos que coincidan con los filtros.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </SectionCard>

      {/* Resumen por década */}
      <SectionCard title="Resumen por década" description="Número de eventos por década y alcance.">
        <DecadeSummary catalog={catalog} />
      </SectionCard>
    </div>
  );
}

function SortButton({ label, k, sortBy, sortDir, onSort }: { label: string; k: string; sortBy: string; sortDir: "asc" | "desc"; onSort: (k: string) => void }) {
  const active = sortBy === k;
  return (
    <button onClick={() => onSort(k)} className={`inline-flex items-center gap-1 hover:text-foreground ${active ? "text-foreground" : "text-muted-foreground"}`}>
      {label}
      <span aria-hidden>{active ? (sortDir === "asc" ? "▲" : "▼") : "↕"}</span>
    </button>
  );
}

function DecadeSummary({ catalog }: { catalog: CatalogEntry[] }) {
  const decades = Array.from(new Set(catalog.map((e) => e.decade))).sort();
  const max = Math.max(...decades.map((d) => catalog.filter((e) => e.decade === d).length), 1);
  return (
    <div className="space-y-2">
      {decades.map((d) => {
        const events = catalog.filter((e) => e.decade === d);
        const nino = events.filter((e) => e.phase === "El Niño").length;
        const nina = events.filter((e) => e.phase === "La Niña").length;
        return (
          <div key={d} className="flex items-center gap-3 text-xs">
            <span className="w-12 font-medium">{d}s</span>
            <div className="flex h-5 flex-1 rounded-full overflow-hidden bg-muted">
              <div className="bg-[color:var(--enso-warm)]" style={{ width: `${(nino / max) * 100}%` }} title={`${nino} El Niño`} />
              <div className="bg-[color:var(--enso-cool)]" style={{ width: `${(nina / max) * 100}%` }} title={`${nina} La Niña`} />
            </div>
            <span className="w-20 text-right enso-num text-muted-foreground">{events.length} eventos ({nino}Niño/{nina}Niña)</span>
          </div>
        );
      })}
    </div>
  );
}
