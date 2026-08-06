"use client";

import * as React from "react";
import { MONTHS, sstGridForMonth, d20GridForMonth, valueAt, generateAllSeries } from "@/lib/enso/series";
import { ColorBar, AnomalyMap } from "./charts";
import { SectionCard, ScopeBadge, InfoNote, BigValue } from "./primitives";
import { fmtMonth, fmtValue, COLOR_COASTAL, COLOR_BASIN } from "@/lib/enso/ui";
import { Play, Pause, SkipBack, SkipForward, ChevronLeft, ChevronRight, Keyboard, Gauge } from "lucide-react";

const REGIONS = [
  { name: "Niño 1+2", bounds: { latMin: -10, latMax: 0, lonMin: -90, lonMax: -80 }, color: "var(--enso-coastal)" },
  { name: "Niño 3.4", bounds: { latMin: -5, latMax: 5, lonMin: -170, lonMax: -120 }, color: "var(--enso-basin)" },
];

const SPEEDS = [
  { label: "0.5×", ms: 1400 },
  { label: "1×", ms: 700 },
  { label: "2×", ms: 350 },
  { label: "4×", ms: 175 },
];

type FieldKind = "sst" | "d20";

export function TimelapseView() {
  const all = React.useMemo(() => generateAllSeries(), []);
  // Ventana de animación: últimos 10 años (120 meses) para que sea representativa.
  const windowStart = Math.max(0, MONTHS.length - 120);
  const windowEnd = MONTHS.length - 1;
  const totalFrames = windowEnd - windowStart + 1;

  const [frame, setFrame] = React.useState(windowEnd);
  const [playing, setPlaying] = React.useState(false);
  const [speedIdx, setSpeedIdx] = React.useState(1);
  const [field, setField] = React.useState<FieldKind>("sst");
  const [reducedMotion, setReducedMotion] = React.useState(false);

  // Detección de prefers-reduced-motion
  React.useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReducedMotion(mq.matches);
    const handler = (e: MediaQueryListEvent) => setReducedMotion(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  // Bucle de animación con requestAnimationFrame y paso temporal.
  React.useEffect(() => {
    if (!playing || reducedMotion) return;
    let raf = 0;
    let last = performance.now();
    let acc = 0;
    const interval = SPEEDS[speedIdx].ms;
    const tick = (now: number) => {
      acc += now - last;
      last = now;
      if (acc >= interval) {
        acc = 0;
        setFrame((f) => {
          if (f >= windowEnd) return windowStart; // bucle
          return f + 1;
        });
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, speedIdx, reducedMotion, windowStart, windowEnd]);

  // Atajos de teclado para accesibilidad.
  const onKeyDown = React.useCallback((e: React.KeyboardEvent) => {
    switch (e.key) {
      case " ":
      case "k":
        e.preventDefault();
        setPlaying((p) => !p);
        break;
      case "ArrowLeft":
        e.preventDefault();
        setPlaying(false);
        setFrame((f) => Math.max(windowStart, f - (e.shiftKey ? 6 : 1)));
        break;
      case "ArrowRight":
        e.preventDefault();
        setPlaying(false);
        setFrame((f) => Math.min(windowEnd, f + (e.shiftKey ? 6 : 1)));
        break;
      case "Home":
        e.preventDefault();
        setPlaying(false);
        setFrame(windowStart);
        break;
      case "End":
        e.preventDefault();
        setPlaying(false);
        setFrame(windowEnd);
        break;
      case "+":
      case "=":
        e.preventDefault();
        setSpeedIdx((s) => Math.min(SPEEDS.length - 1, s + 1));
        break;
      case "-":
        e.preventDefault();
        setSpeedIdx((s) => Math.max(0, s - 1));
        break;
    }
  }, [windowStart, windowEnd]);

  const monthIdx = windowStart + frame - windowStart;
  const actualIdx = frame; // frame ya es índice absoluto en MONTHS
  const month = MONTHS[actualIdx];

  const cells = React.useMemo(() => {
    return field === "sst" ? sstGridForMonth(actualIdx) : d20GridForMonth(actualIdx);
  }, [field, actualIdx]);

  const scale = field === "sst" ? 2.5 : 25;
  const units = field === "sst" ? "°C" : "m";

  // Valores regionales para el mes actual
  const n12Val = valueAt(all.nino12, month);
  const n34Val = valueAt(all.nino34, month);
  const icenVal = valueAt(all.icen, month);
  const roniVal = valueAt(all.roni, month);

  // Indicador de mes con datos faltantes (huecos preservados, no interpolados)
  const hasGap = n12Val === null || n34Val === null;

  return (
    <div className="space-y-5" onKeyDown={onKeyDown} tabIndex={0} role="application" aria-label="Animación temporal de anomalías ENSO">
      <InfoNote tone="muted" title="Animación temporal (timelapse)">
        Recorra la evolución mensual del campo de anomalía sobre el Pacífico ecuatorial. Controles:
        reproducir/pausar (<kbd className="rounded border bg-muted px-1 text-[10px]">Espacio</kbd>),
        avanzar/retroceder (<kbd className="rounded border bg-muted px-1 text-[10px]">← →</kbd>, con
        <kbd className="rounded border bg-muted px-1 text-[10px]">Mayús</kbd> salta 6 meses),
        ir al inicio/fin (<kbd className="rounded border bg-muted px-1 text-[10px]">Inicio/Fin</kbd>),
        velocidad (<kbd className="rounded border bg-muted px-1 text-[10px]">+ −</kbd>). Se respetan
        las preferencias de movimiento reducido del sistema. Los meses sin datos se muestran como
        huecos (sin interpolación temporal).
      </InfoNote>

      {/* Selector de campo */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-lg border p-0.5" role="group" aria-label="Campo a animar">
          <button
            onClick={() => setField("sst")}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${field === "sst" ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}
            aria-pressed={field === "sst"}
          >
            TSM (anomalía)
          </button>
          <button
            onClick={() => setField("d20")}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${field === "d20" ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}
            aria-pressed={field === "d20"}
          >
            D20 (termoclina)
          </button>
        </div>
        {reducedMotion && (
          <span className="inline-flex items-center gap-1 rounded-full border border-amber-400 bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700 dark:bg-amber-950/30 dark:text-amber-300">
            <Gauge className="h-3 w-3" /> Movimiento reducido activo
          </span>
        )}
      </div>

      {/* Mapa animado */}
      <SectionCard
        title={<span className="flex items-center gap-2">Evolución temporal — {field === "sst" ? "anomalía de TSM" : "anomalía de D20"}</span>}
        description={`Mes mostrado: ${fmtMonth(month)}${hasGap ? " · (algunas series sin datos este mes)" : ""}`}
        right={
          <div className="flex items-baseline gap-3">
            <div className="text-right">
              <p className="text-[10px] text-muted-foreground">Niño 1+2</p>
              <p className="text-sm font-bold enso-num" style={{ color: n12Val !== null && n12Val > 0 ? "var(--enso-warm)" : n12Val !== null && n12Val < 0 ? "var(--enso-cool)" : undefined }}>
                {fmtValue(n12Val, "degC")}
              </p>
            </div>
            <div className="text-right">
              <p className="text-[10px] text-muted-foreground">Niño 3.4</p>
              <p className="text-sm font-bold enso-num" style={{ color: n34Val !== null && n34Val > 0 ? "var(--enso-warm)" : n34Val !== null && n34Val < 0 ? "var(--enso-cool)" : undefined }}>
                {fmtValue(n34Val, "degC")}
              </p>
            </div>
          </div>
        }
      >
        <div className="relative">
          <AnomalyMap cells={cells} scale={scale} regions={REGIONS} title={`Anomalía de ${field === "sst" ? "TSM (°C)" : "D20 (m)"} — ${fmtMonth(month)}`} />
          {hasGap && (
            <div className="pointer-events-none absolute inset-0 flex items-start justify-center pt-2">
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-800 dark:bg-amber-950/60 dark:text-amber-200">
                Mes con datos parciales
              </span>
            </div>
          )}
        </div>

        {/* Controles de reproducción */}
        <div className="mt-4 space-y-3">
          {/* Botones */}
          <div className="flex items-center justify-center gap-2">
            <button
              onClick={() => { setPlaying(false); setFrame(windowStart); }}
              className="inline-flex h-9 w-9 items-center justify-center rounded-full border hover:bg-muted"
              aria-label="Ir al inicio"
              title="Inicio (tecla Inicio)"
            >
              <SkipBack className="h-4 w-4" />
            </button>
            <button
              onClick={() => setFrame((f) => Math.max(windowStart, f - 1))}
              className="inline-flex h-9 w-9 items-center justify-center rounded-full border hover:bg-muted"
              aria-label="Mes anterior"
              title="Anterior (←)"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button
              onClick={() => setPlaying((p) => !p)}
              className="inline-flex h-11 w-11 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-sm hover:opacity-90"
              aria-label={playing ? "Pausar" : "Reproducir"}
              title={playing ? "Pausar (Espacio)" : "Reproducir (Espacio)"}
            >
              {playing ? <Pause className="h-5 w-5" /> : <Play className="h-5 w-5 translate-x-0.5" />}
            </button>
            <button
              onClick={() => setFrame((f) => Math.min(windowEnd, f + 1))}
              className="inline-flex h-9 w-9 items-center justify-center rounded-full border hover:bg-muted"
              aria-label="Mes siguiente"
              title="Siguiente (→)"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
            <button
              onClick={() => { setPlaying(false); setFrame(windowEnd); }}
              className="inline-flex h-9 w-9 items-center justify-center rounded-full border hover:bg-muted"
              aria-label="Ir al final"
              title="Final (tecla Fin)"
            >
              <SkipForward className="h-4 w-4" />
            </button>
          </div>

          {/* Slider temporal */}
          <div className="flex items-center gap-3">
            <span className="w-16 text-right text-[11px] text-muted-foreground enso-num">{fmtMonth(MONTHS[windowStart])}</span>
            <input
              type="range"
              min={windowStart}
              max={windowEnd}
              value={frame}
              onChange={(e) => { setPlaying(false); setFrame(Number(e.target.value)); }}
              className="flex-1 accent-[color:var(--enso-basin)]"
              aria-label="Deslizador temporal"
              aria-valuetext={fmtMonth(month)}
            />
            <span className="w-16 text-[11px] text-muted-foreground enso-num">{fmtMonth(MONTHS[windowEnd])}</span>
          </div>

          {/* Velocidad + progreso */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-1" role="group" aria-label="Velocidad de reproducción">
              <span className="mr-1 text-[11px] text-muted-foreground">Velocidad:</span>
              {SPEEDS.map((s, i) => (
                <button
                  key={s.label}
                  onClick={() => setSpeedIdx(i)}
                  className={`rounded-md px-2 py-1 text-[11px] font-medium ${speedIdx === i ? "bg-primary text-primary-foreground" : "border hover:bg-muted"}`}
                  aria-pressed={speedIdx === i}
                >
                  {s.label}
                </button>
              ))}
            </div>
            <span className="text-[11px] text-muted-foreground enso-num">
              Mes {actualIdx - windowStart + 1} de {totalFrames}
            </span>
          </div>

          {/* Ayuda de teclado */}
          <div className="flex items-center gap-2 rounded-lg border border-dashed bg-muted/30 px-3 py-2 text-[11px] text-muted-foreground">
            <Keyboard className="h-3.5 w-3.5 shrink-0" />
            <span>
              Atajos: <kbd className="rounded border bg-card px-1">Espacio</kbd> play/pausa ·{" "}
              <kbd className="rounded border bg-card px-1">←</kbd>/<kbd className="rounded border bg-card px-1">→</kbd> paso ·{" "}
              <kbd className="rounded border bg-card px-1">Mayús+←/→</kbd> 6 meses ·{" "}
              <kbd className="rounded border bg-card px-1">Inicio/Fin</kbd> extremos ·{" "}
              <kbd className="rounded border bg-card px-1">+/−</kbd> velocidad
            </span>
          </div>
        </div>
      </SectionCard>

      {/* Resumen del mes actual */}
      <div className="grid gap-4 md:grid-cols-4">
        <MiniStat label="TSM Niño 1+2 (costero)" value={fmtValue(n12Val, "degC")} scope="coastal" />
        <MiniStat label="ICEN" value={fmtValue(icenVal, "degC")} scope="coastal" />
        <MiniStat label="TSM Niño 3.4 (cuenca)" value={fmtValue(n34Val, "degC")} scope="basin" />
        <MiniStat label="RONI" value={fmtValue(roniVal, "degC")} scope="basin" />
      </div>
    </div>
  );
}

function MiniStat({ label, value, scope }: { label: string; value: string; scope: "coastal" | "basin" }) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-muted-foreground">{label}</span>
        <ScopeBadge scope={scope} />
      </div>
      <p className="mt-1 text-lg font-bold enso-num">{value}</p>
    </div>
  );
}
