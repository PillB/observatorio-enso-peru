"use client";

import * as React from "react";
import { TELECONNECTIONS, type TeleconnectionImpact } from "@/lib/enso/derived";
import { buildCurrentStatus } from "@/lib/enso/derived";
import { SectionCard, ScopeBadge, InfoNote, StatusPill } from "./primitives";
import { Globe, AlertTriangle, CloudRain, Sun } from "lucide-react";

export function TeleconnectionsView() {
  const status = React.useMemo(() => buildCurrentStatus(), []);
  const [filter, setFilter] = React.useState<"all" | "nino" | "nina">("nino");

  const isNinoActive = status.basin.alert.toLowerCase().includes("el niño");
  const isNinaActive = status.basin.alert.toLowerCase().includes("la niña");

  return (
    <div className="space-y-5">
      <InfoNote tone="warn" title="Teleconexiones e impactos globales — conocimiento climático curado">
        Esta vista describe los <strong>impactos típicos</strong> de El Niño y La Niña sobre
        diferentes regiones del mundo, basados en conocimiento climático documentado. Son patrones
        generales, <strong>no pronósticos</strong> ni alertas oficiales. La ocurrencia real depende
        de la intensidad del evento y de otros factores climáticos. Para alertas oficiales consulte
        los servicios meteorológicos nacionales.
      </InfoNote>

      {/* Estado actual */}
      <SectionCard title="Estado ENSO actual y relevancia">
        <div className="flex flex-wrap items-center gap-3">
          <StatusPill label={status.basin.alert} tone="warm" />
          <span className="text-xs text-muted-foreground">
            {isNinoActive
              ? "Con El Niño activo, son relevantes los impactos de la columna «Durante El Niño»."
              : isNinaActive
              ? "Con La Niña activa, son relevantes los impactos de la columna «Durante La Niña»."
              : "Condiciones neutrales: los impactos típicos pueden no aplicarse."}
          </span>
        </div>
      </SectionCard>

      {/* Mapa mundial de teleconexiones */}
      <SectionCard
        title={<span className="flex items-center gap-2"><Globe className="h-4 w-4" /> Mapa mundial de teleconexiones ENSO</span>}
        description="Regiones con impactos típicos documentados. Click en un marcador para ver el detalle."
      >
        <WorldMap teleconnections={TELECONNECTIONS} activePhase={isNinoActive ? "nino" : isNinaActive ? "nina" : "neutral"} />
      </SectionCard>

      {/* Filtro */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">Mostrar impactos de:</span>
        <div className="inline-flex rounded-lg border p-0.5" role="group" aria-label="Filtro de fase">
          <button
            onClick={() => setFilter("nino")}
            className={`rounded-md px-3 py-1.5 text-xs font-medium ${filter === "nino" ? "bg-[color:var(--enso-warm)] text-white" : "hover:bg-muted"}`}
            aria-pressed={filter === "nino"}
          >
            El Niño
          </button>
          <button
            onClick={() => setFilter("nina")}
            className={`rounded-md px-3 py-1.5 text-xs font-medium ${filter === "nina" ? "bg-[color:var(--enso-cool)] text-white" : "hover:bg-muted"}`}
            aria-pressed={filter === "nina"}
          >
            La Niña
          </button>
          <button
            onClick={() => setFilter("all")}
            className={`rounded-md px-3 py-1.5 text-xs font-medium ${filter === "all" ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}
            aria-pressed={filter === "all"}
          >
            Ambos
          </button>
        </div>
      </div>

      {/* Tarjetas de impacto por región */}
      <div className="grid gap-3 md:grid-cols-2">
        {TELECONNECTIONS.map((t) => (
          <TeleconnectionCard key={t.region} t={t} filter={filter} />
        ))}
      </div>

      <InfoNote tone="muted" title="Notas sobre las teleconexiones">
        <ul className="space-y-1 list-disc pl-4">
          <li>Las teleconexiones son patrones estadísticos; no garantizan un resultado en cada evento.</li>
          <li>La intensidad del evento ENSO modula la magnitud del impacto.</li>
          <li>El Niño Costero afecta principalmente a Perú y Ecuador; el de cuenca tiene alcance global.</li>
          <li>La confianza «Alta» indica teleconexiones bien documentadas en literatura científica.</li>
          <li>Para impactos específicos en Perú, consulte SENAMHI e IGP; para emergencias, INDECI y CENEPRED.</li>
        </ul>
      </InfoNote>
    </div>
  );
}

function TeleconnectionCard({ t, filter }: { t: TeleconnectionImpact; filter: "all" | "nino" | "nina" }) {
  return (
    <div className="rounded-lg border bg-card p-3 hover:bg-muted/30 transition-colors">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-sm font-semibold">{t.region}</h4>
        <StatusPill label={t.confidence} tone={t.confidence === "Alta" ? "warm" : t.confidence === "Media" ? "warn" : "neutral"} />
      </div>
      <div className="mt-2 space-y-2">
        {(filter === "all" || filter === "nino") && (
          <div className="flex items-start gap-2 text-xs">
            <CloudRain className="h-3.5 w-3.5 mt-0.5 shrink-0 text-[color:var(--enso-warm)]" />
            <div>
              <span className="font-medium text-[color:var(--enso-warm)]">El Niño: </span>
              <span className="text-muted-foreground">{t.ninoImpact}</span>
            </div>
          </div>
        )}
        {(filter === "all" || filter === "nina") && (
          <div className="flex items-start gap-2 text-xs">
            <Sun className="h-3.5 w-3.5 mt-0.5 shrink-0 text-[color:var(--enso-cool)]" />
            <div>
              <span className="font-medium text-[color:var(--enso-cool)]">La Niña: </span>
              <span className="text-muted-foreground">{t.ninaImpact}</span>
            </div>
          </div>
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-1 border-t pt-2">
        {t.variables.map((v) => (
          <span key={v} className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">{v}</span>
        ))}
      </div>
    </div>
  );
}

/** Mapa mundial esquemático SVG con marcadores de teleconexiones. */
function WorldMap({ teleconnections, activePhase }: { teleconnections: TeleconnectionImpact[]; activePhase: "nino" | "nina" | "neutral" }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(640);
  const [selected, setSelected] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => { for (const x of e) setW(Math.max(320, x.contentRect.width)); });
    ro.observe(ref.current); return () => ro.disconnect();
  }, []);
  const h = 320;
  const padL = 24, padR = 12, padT = 12, padB = 28;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  // Proyección equirectangular simple: lon -180..180 → x, lat 90..-90 → y
  const sx = (lon: number) => padL + ((lon + 180) / 360) * plotW;
  const sy = (lat: number) => padT + ((90 - lat) / 180) * plotH;

  const selectedT = selected ? teleconnections.find((t) => t.region === selected) : null;

  return (
    <div ref={ref} className="w-full">
      <svg width={w} height={h} role="img" aria-label="Mapa mundial de teleconexiones ENSO">
        {/* fondo del océano */}
        <rect x={padL} y={padT} width={plotW} height={plotH} fill="var(--enso-basin)" fillOpacity={0.06} />
        {/* continentes esquemáticos (siluetas muy simplificadas) */}
        <g fill="var(--muted-foreground)" fillOpacity={0.18}>
          {/* América del Norte */}
          <path d={`M ${sx(-130)} ${sy(60)} L ${sx(-60)} ${sy(60)} L ${sx(-80)} ${sy(25)} L ${sx(-110)} ${sy(30)} L ${sx(-125)} ${sy(45)} Z`} />
          {/* América del Sur */}
          <path d={`M ${sx(-80)} ${sy(10)} L ${sx(-35)} ${sy(10)} L ${sx(-45)} ${sy(-55)} L ${sx(-75)} ${sy(-50)} Z`} />
          {/* África */}
          <path d={`M ${sx(-15)} ${sy(35)} L ${sx(50)} ${sy(35)} L ${sx(45)} ${sy(-35)} L ${sx(10)} ${sy(-35)} Z`} />
          {/* Europa */}
          <path d={`M ${sx(-10)} ${sy(70)} L ${sx(40)} ${sy(70)} L ${sx(30)} ${sy(45)} L ${sx(0)} ${sy(45)} Z`} />
          {/* Asia */}
          <path d={`M ${sx(40)} ${sy(75)} L ${sx(150)} ${sy(75)} L ${sx(140)} ${sy(20)} L ${sx(60)} ${sy(30)} L ${sx(45)} ${sy(50)} Z`} />
          {/* Australia */}
          <path d={`M ${sx(115)} ${sy(-15)} L ${sx(155)} ${sy(-15)} L ${sx(150)} ${sy(-40)} L ${sx(120)} ${sy(-38)} Z`} />
        </g>
        {/* marcadores de teleconexiones */}
        {teleconnections.map((t) => {
          const cx = sx(t.lon), cy = sy(t.lat);
          const color = activePhase === "nino" ? "var(--enso-warm)" : activePhase === "nina" ? "var(--enso-cool)" : "var(--enso-coastal)";
          const isSelected = selected === t.region;
          return (
            <g key={t.region} onClick={() => setSelected(isSelected ? null : t.region)} style={{ cursor: "pointer" }}>
              <circle cx={cx} cy={cy} r={isSelected ? 8 : 5} fill={color} fillOpacity={0.85} stroke="var(--card)" strokeWidth={1.5} />
              {isSelected && <circle cx={cx} cy={cy} r={12} fill="none" stroke={color} strokeWidth={2} strokeOpacity={0.4} />}
              {isSelected && (
                <text x={cx} y={cy - 14} textAnchor="middle" fontSize={9} fill="currentColor" fontWeight="bold">{t.region}</text>
              )}
            </g>
          );
        })}
        {/* ejes */}
        {[-180, -90, 0, 90, 180].map((lon) => (
          <text key={lon} x={sx(lon)} y={h - 10} textAnchor="middle" fontSize={8} fill="currentColor" fillOpacity={0.5}>{lon}°</text>
        ))}
        {[90, 0, -90].map((lat) => (
          <text key={lat} x={4} y={sy(lat) + 3} fontSize={8} fill="currentColor" fillOpacity={0.5}>{lat}°</text>
        ))}
      </svg>
      {/* panel de detalle del seleccionado */}
      {selectedT && (
        <div className="mt-3 rounded-lg border bg-muted/30 p-3 text-xs">
          <div className="flex items-center justify-between">
            <h4 className="font-semibold">{selectedT.region}</h4>
            <StatusPill label={selectedT.confidence} tone={selectedT.confidence === "Alta" ? "warm" : "warn"} />
          </div>
          <p className="mt-1"><strong className="text-[color:var(--enso-warm)]">El Niño:</strong> {selectedT.ninoImpact}</p>
          <p className="mt-0.5"><strong className="text-[color:var(--enso-cool)]">La Niña:</strong> {selectedT.ninaImpact}</p>
          <div className="mt-1 flex flex-wrap gap-1">
            {selectedT.variables.map((v) => (
              <span key={v} className="rounded bg-card px-1.5 py-0.5 text-[10px]">{v}</span>
            ))}
          </div>
        </div>
      )}
      <div className="mt-2 text-[11px] text-muted-foreground">
        {selected ? "Click en el marcador para cerrar." : "Click en un marcador para ver el detalle."} Mapa esquemático; las posiciones son aproximadas.
      </div>
    </div>
  );
}
