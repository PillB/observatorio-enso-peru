"use client";

import * as React from "react";
import { GLOSSARY, GLOSSARY_CATEGORIES, searchGlossary, type GlossaryEntry } from "@/lib/enso/glossary";
import { SectionCard, ScopeBadge, InfoNote } from "./primitives";
import { INDICATOR_BY_ID } from "@/lib/enso/methodology";
import { Search, BookOpen, ExternalLink } from "lucide-react";

const CATEGORY_TONE: Record<GlossaryEntry["category"], string> = {
  costero: "enso-badge-coastal",
  cuenca: "enso-badge-basin",
  general: "bg-muted text-muted-foreground border-border",
  físico: "bg-[color:var(--enso-cool)]/15 text-[color:var(--enso-cool)] border-[color:var(--enso-cool)]/30",
  institucional: "bg-[color:var(--enso-warm)]/15 text-[color:var(--enso-warm)] border-[color:var(--enso-warm)]/30",
};

export function GlossaryView() {
  const [query, setQuery] = React.useState("");
  const [activeCat, setActiveCat] = React.useState<GlossaryEntry["category"] | "all">("all");
  const [selected, setSelected] = React.useState<string | null>(null);

  const results = React.useMemo(() => {
    let list = searchGlossary(query);
    if (activeCat !== "all") list = list.filter((e) => e.category === activeCat);
    return list.sort((a, b) => a.term.localeCompare(b.term, "es"));
  }, [query, activeCat]);

  const selectedEntry = selected ? GLOSSARY.find((e) => e.id === selected) : null;

  return (
    <div className="space-y-5">
      <InfoNote tone="info" title="Glosario climático del observatorio">
        Términos ENSO en español formal, comprensible internacionalmente y apto para Perú. Cada " +
        entrada incluye definición, categoría y referencias a los indicadores del observatorio. " +
        Para definiciones oficiales, consulte la metodología de ENFEN y NOAA/CPC.
      </InfoNote>

      {/* Buscador y filtros */}
      <SectionCard title={<span className="flex items-center gap-2"><Search className="h-4 w-4" /> Buscar término</span>}>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex flex-1 items-center gap-2 rounded-lg border px-3 py-2 min-w-[200px]">
            <Search className="h-4 w-4 text-muted-foreground" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Buscar (p. ej. El Niño, SOI, termoclina, ENFEN)…"
              className="flex-1 bg-transparent text-sm outline-none"
              aria-label="Buscar en el glosario"
            />
            {query && (
              <button onClick={() => setQuery("")} className="text-xs text-muted-foreground hover:text-foreground" aria-label="Limpiar búsqueda">✕</button>
            )}
          </div>
          <span className="text-xs text-muted-foreground">{results.length} términos</span>
        </div>

        {/* Filtros por categoría */}
        <div className="mt-3 flex flex-wrap gap-1.5" role="group" aria-label="Filtrar por categoría">
          <button
            onClick={() => setActiveCat("all")}
            className={`rounded-full border px-2.5 py-1 text-xs font-medium ${activeCat === "all" ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted"}`}
            aria-pressed={activeCat === "all"}
          >
            Todos
          </button>
          {GLOSSARY_CATEGORIES.map((c) => (
            <button
              key={c.id}
              onClick={() => setActiveCat(c.id)}
              className={`rounded-full border px-2.5 py-1 text-xs font-medium ${activeCat === c.id ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted"}`}
              aria-pressed={activeCat === c.id}
            >
              {c.label}
            </button>
          ))}
        </div>
      </SectionCard>

      {/* Listado de términos */}
      <div className="grid gap-3 md:grid-cols-2">
        {results.map((e) => (
          <button
            key={e.id}
            onClick={() => setSelected(e.id)}
            className="group text-left rounded-lg border bg-card p-3 hover:bg-muted/50 transition-colors enso-focus-ring"
          >
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">{e.term}</h3>
              <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${CATEGORY_TONE[e.category]}`}>
                {GLOSSARY_CATEGORIES.find((c) => c.id === e.category)?.label}
              </span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground leading-snug">{e.shortDef}</p>
            {e.related && e.related.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {e.related.map((r) => (
                  <span key={r} className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground">
                    {INDICATOR_BY_ID[r]?.shortName ?? r}
                  </span>
                ))}
              </div>
            )}
          </button>
        ))}
        {results.length === 0 && (
          <div className="md:col-span-2 rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
            No se encontraron términos para «{query}».
          </div>
        )}
      </div>

      {/* Panel de detalle */}
      {selectedEntry && (
        <SectionCard
          title={<span className="flex items-center gap-2"><BookOpen className="h-4 w-4" /> {selectedEntry.term}</span>}
          right={<span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${CATEGORY_TONE[selectedEntry.category]}`}>{GLOSSARY_CATEGORIES.find((c) => c.id === selectedEntry.category)?.label}</span>}
        >
          <div className="space-y-3">
            <div>
              <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Definición breve</p>
              <p className="text-sm mt-0.5">{selectedEntry.shortDef}</p>
            </div>
            <div>
              <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Definición completa</p>
              <p className="text-sm mt-0.5 leading-relaxed">{selectedEntry.fullDef}</p>
            </div>
            {selectedEntry.related && selectedEntry.related.length > 0 && (
              <div>
                <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Indicadores relacionados</p>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {selectedEntry.related.map((r) => {
                    const ind = INDICATOR_BY_ID[r];
                    return ind ? (
                      <span key={r} className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs">
                        <ScopeBadge scope={ind.scope} />
                        {ind.shortName}
                      </span>
                    ) : null;
                  })}
                </div>
              </div>
            )}
            {selectedEntry.seeAlso && selectedEntry.seeAlso.length > 0 && (
              <div>
                <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Véase también</p>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {selectedEntry.seeAlso.map((s) => {
                    const other = GLOSSARY.find((g) => g.id === s);
                    return other ? (
                      <button
                        key={s}
                        onClick={() => setSelected(s)}
                        className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs hover:bg-muted"
                      >
                        <ExternalLink className="h-3 w-3" />
                        {other.term}
                      </button>
                    ) : null;
                  })}
                </div>
              </div>
            )}
            <button
              onClick={() => setSelected(null)}
              className="mt-2 text-xs text-muted-foreground hover:text-foreground"
            >
              ✕ Cerrar detalle
            </button>
          </div>
        </SectionCard>
      )}
    </div>
  );
}
