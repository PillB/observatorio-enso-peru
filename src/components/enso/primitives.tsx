"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/** Tarjeta de sección con título y descripción. */
export function SectionCard({
  title, description, children, className, right, id,
}: {
  title?: React.ReactNode;
  description?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  right?: React.ReactNode;
  id?: string;
}) {
  return (
    <section
      id={id}
      className={cn("rounded-xl border bg-card text-card-foreground shadow-sm", className)}
    >
      {(title || right) && (
        <header className="flex items-start justify-between gap-3 border-b px-4 py-3 sm:px-5">
          <div>
            {title && <h3 className="text-sm font-semibold leading-tight">{title}</h3>}
            {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
          </div>
          {right}
        </header>
      )}
      <div className="p-4 sm:p-5">{children}</div>
    </section>
  );
}

/** Etiqueta de alcance costero/cuenca. */
export function ScopeBadge({ scope }: { scope: "coastal" | "basin" }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide",
        scope === "coastal" ? "enso-badge-coastal" : "enso-badge-basin"
      )}
    >
      {scope === "coastal" ? "Costero" : "Cuenca"}
    </span>
  );
}

/** Etiqueta de estado con color semántico. */
export function StatusPill({ label, tone = "neutral" }: { label: string; tone?: "warm" | "cool" | "neutral" | "warn" }) {
  const cls = {
    warm: "bg-[color:var(--enso-warm)]/15 text-[color:var(--enso-warm)] border-[color:var(--enso-warm)]/30",
    cool: "bg-[color:var(--enso-cool)]/15 text-[color:var(--enso-cool)] border-[color:var(--enso-cool)]/30",
    neutral: "bg-muted text-muted-foreground border-border",
    warn: "bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-950/40 dark:text-amber-200 dark:border-amber-800",
  }[tone];
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium", cls)}>
      {label}
    </span>
  );
}

/** Bloque de nota informativa. */
export function InfoNote({ tone = "info", title, children }: { tone?: "info" | "warn" | "muted"; title?: string; children: React.ReactNode }) {
  const cls = {
    info: "border-[color:var(--enso-basin)]/30 bg-[color:var(--enso-basin)]/5 text-foreground",
    warn: "border-amber-300 bg-amber-50 text-foreground dark:bg-amber-950/20 dark:border-amber-800",
    muted: "border-border bg-muted/40 text-muted-foreground",
  }[tone];
  return (
    <div className={cn("rounded-lg border px-3 py-2 text-xs leading-relaxed", cls)}>
      {title && <p className="font-semibold mb-0.5">{title}</p>}
      {children}
    </div>
  );
}

/** Etiqueta de dato preliminar. */
export function PreliminaryTag({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <span className="inline-flex items-center rounded border border-amber-400 bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800 dark:bg-amber-950/40 dark:text-amber-200 dark:border-amber-700">
      Dato preliminar
    </span>
  );
}

/** Valor grande destacado. */
export function BigValue({ value, units, tone = "neutral" }: { value: string; units?: string; tone?: "warm" | "cool" | "neutral" }) {
  const cls = {
    warm: "text-[color:var(--enso-warm)]",
    cool: "text-[color:var(--enso-cool)]",
    neutral: "text-foreground",
  }[tone];
  return (
    <div className="flex items-baseline gap-1">
      <span className={cn("text-2xl font-bold tabular-nums enso-num", cls)}>{value}</span>
      {units && <span className="text-xs text-muted-foreground">{units}</span>}
    </div>
  );
}

/** Separador con etiqueta. */
export function FieldLine({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-2 py-1 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{children}</span>
    </div>
  );
}
