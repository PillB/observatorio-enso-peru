"use client";

import * as React from "react";
import { SOURCES } from "@/lib/enso/sources";
import { SectionCard, InfoNote, StatusPill } from "./primitives";
import { ExternalLink } from "lucide-react";

export function SourcesView() {
  return (
    <div className="space-y-5">
      <InfoNote tone="info" title="Catálogo de fuentes verificadas">
        Cada fuente documenta institución, producto, endpoint, frecuencia, latencia, licencia y
        estado de verificación (VERIFIED / ASSUMED / UNRESOLVED / REJECTED). El observatorio prioriza
        fuentes oficiales y abiertas; registra fecha de recuperación y fuente de respaldo.
      </InfoNote>

      <SectionCard title="Fuentes primarias" description={`${SOURCES.length} fuentes documentadas.`}>
        <div className="space-y-3">
          {SOURCES.map((s) => (
            <div key={s.id} className="rounded-lg border p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <h4 className="text-sm font-semibold">{s.institution}</h4>
                  <p className="text-xs text-muted-foreground">{s.product}</p>
                </div>
                <StatusPill
                  label={s.status}
                  tone={s.status === "VERIFIED" ? "warm" : s.status === "REJECTED" ? "cool" : "neutral"}
                />
              </div>
              <div className="mt-2 grid gap-x-6 gap-y-1 md:grid-cols-2 text-xs">
                <div><span className="text-muted-foreground">Endpoint:</span> <a href={s.url} target="_blank" rel="noopener noreferrer" className="font-mono text-[11px] text-[color:var(--enso-basin)] hover:underline break-all inline-flex items-center gap-0.5">{s.url} <ExternalLink className="h-3 w-3" /></a></div>
                <div><span className="text-muted-foreground">Recuperación:</span> {s.retrievalDate}</div>
                <div><span className="text-muted-foreground">Formato:</span> {s.format}</div>
                <div><span className="text-muted-foreground">Frecuencia:</span> {s.updateFrequency}</div>
                <div><span className="text-muted-foreground">Latencia:</span> {s.latency}</div>
                <div><span className="text-muted-foreground">Licencia:</span> {s.license}</div>
                <div><span className="text-muted-foreground">Atribución:</span> {s.attribution}</div>
                {s.fallbackSourceId && <div><span className="text-muted-foreground">Respaldo:</span> {s.fallbackSourceId}</div>}
              </div>
              <p className="mt-2 text-[11px] italic text-muted-foreground">{s.notes}</p>
            </div>
          ))}
        </div>
      </SectionCard>

      <SectionCard title="Atribución y licencias">
        <p className="text-xs leading-relaxed text-muted-foreground">
          Los datos del observatorio se derivan de fuentes oficiales abiertas (NOAA/CPC, NOAA/PSL,
          NOAA/PMEL, ENFEN/IMARPE, SENAMHI, IGP). Las series de NOAA son de dominio público (trabajo
          del Gobierno de EE. UU.). Los productos de ENFEN, SENAMHI e IGP requieren atribución a la
          institución correspondiente. El observatorio es una herramienta de divulgación científica y
          no sustituye a los servicios oficiales. Los datos preliminares pueden revisarse.
        </p>
      </SectionCard>
    </div>
  );
}
