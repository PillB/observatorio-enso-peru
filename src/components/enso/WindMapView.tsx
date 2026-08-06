"use client";

import * as React from "react";
import { MONTHS, windGridForMonth, generateAllSeries, latest } from "@/lib/enso/series";
import { INDICATOR_BY_ID } from "@/lib/enso/methodology";
import { SectionCard, ScopeBadge, InfoNote, BigValue, FieldLine } from "./primitives";
import { fmtMonth, fmtValue, anomalyColor } from "@/lib/enso/ui";
import { ColorBar } from "./charts";
import { ArrowRight, ArrowLeft, Compass } from "lucide-react";

const REGIONS = [
  { name: "Niño 1+2", bounds: { latMin: -10, latMax: 0, lonMin: -90, lonMax: -80 }, color: "var(--enso-coastal)" },
  { name: "Niño 3.4", bounds: { latMin: -5, latMax: 5, lonMin: -170, lonMax: -120 }, color: "var(--enso-basin)" },
];

export function WindMapView() {
  const all = generateAllSeries();
  const u850 = latest(all.u850);
  const lastIdx = MONTHS.length - 1;
  const vectors = React.useMemo(() => windGridForMonth(lastIdx), [lastIdx]);

  const ref = React.useRef<HTMLDivElement>(null);
  const [w, setW] = React.useState(640);
  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => { for (const x of e) setW(Math.max(320, x.contentRect.width)); });
    ro.observe(ref.current); return () => ro.disconnect();
  }, []);

  const h = 280;
  const padL = 36, padR = 12, padT = 12, padB = 30;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  const lonMin = -180, lonMax = -70, latMin = -15, latMax = 15;
  const sx = (lon: number) => padL + ((lon - lonMin) / (lonMax - lonMin)) * plotW;
  const sy = (lat: number) => padT + ((latMax - lat) / (latMax - latMin)) * plotH;

  // Escala de longitud de flecha por magnitud
  const maxSpeed = Math.max(...vectors.map((v) => v.speed), 1);
  const arrowScale = Math.min(plotW / 16, plotH / 10) * 0.9;

  return (
    <div className="space-y-5">
      <InfoNote tone="info" title="Mapa de vectores de viento — convención de signos">
        Cada flecha representa el vector de anomalía del viento a 850 hPa. Convención:{" "}
        <strong>u &gt; 0</strong> ⇒ flecha hacia el <strong>este</strong> (componente del oeste /
        westerly); <strong>u &lt; 0</strong> ⇒ flecha hacia el <strong>oeste</strong> (componente del
        este / easterly). El color indica la magnitud de la anomalía zonal. Se distingue valor
        observado de anomalía y viento de superficie (10 m) de bajo nivel (850 hPa).
      </InfoNote>

      <SectionCard
        title={<span className="flex items-center gap-2">Mapa de vectores de viento a 850 hPa <ScopeBadge scope="basin" /></span>}
        description={`Pacífico ecuatorial · mes más reciente: ${fmtMonth(MONTHS[lastIdx])} · fuente: NOAA/CPC (NCEP/NCAR Reanalysis).`}
      >
        <div ref={ref} className="w-full">
          <svg width={w} height={h} role="img" aria-label="Mapa de vectores de viento a 850 hPa">
            {/* regiones Niño de fondo */}
            {REGIONS.map((r, i) => (
              <rect key={`bg${i}`}
                x={sx(r.bounds.lonMin)} y={sy(r.bounds.latMax)}
                width={sx(r.bounds.lonMax) - sx(r.bounds.lonMin)}
                height={sy(r.bounds.latMin) - sy(r.bounds.latMax)}
                fill={r.color} fillOpacity={0.05} stroke={r.color} strokeOpacity={0.4} strokeWidth={1} strokeDasharray="4 3" />
            ))}
            {REGIONS.map((r, i) => (
              <text key={`l${i}`} x={(sx(r.bounds.lonMin) + sx(r.bounds.lonMax)) / 2} y={sy(r.bounds.latMin) - 3}
                textAnchor="middle" fontSize={9} fill={r.color} fillOpacity={0.9}>{r.name}</text>
            ))}

            {/* vectores */}
            {vectors.map((v, i) => {
              const cx = sx(v.lon), cy = sy(v.lat);
              const len = (v.speed / maxSpeed) * arrowScale;
              const ang = Math.atan2(v.v, v.u); // radianes; SVG y hacia abajo
              // En pantalla, y crece hacia abajo. v positivo (hacia el norte) => flecha hacia arriba
              const dx = Math.cos(ang) * len;
              const dy = -Math.sin(ang) * len; // invertir y de pantalla
              const ex = cx + dx, ey = cy + dy;
              const color = anomalyColor(v.u, 6);
              const ah = Math.min(7, len * 0.4);
              const aAng = Math.atan2(dy, dx);
              return (
                <g key={i}>
                  <line x1={cx} y1={cy} x2={ex} y2={ey} stroke={color} strokeWidth={1.6} strokeLinecap="round" />
                  <polygon
                    points={`${ex},${ey} ${ex - ah * Math.cos(aAng - 0.4)},${ey - ah * Math.sin(aAng - 0.4)} ${ex - ah * Math.cos(aAng + 0.4)},${ey - ah * Math.sin(aAng + 0.4)}`}
                    fill={color}
                  />
                  <circle cx={cx} cy={cy} r={1.2} fill={color} fillOpacity={0.5} />
                </g>
              );
            })}

            {/* ejes */}
            {[-180, -150, -120, -90].map((lon) => (
              <text key={lon} x={sx(lon)} y={h - 12} textAnchor="middle" fontSize={9} fill="currentColor" fillOpacity={0.6}>{lon}°</text>
            ))}
            {[15, 0, -15].map((lat) => (
              <text key={lat} x={6} y={sy(lat) + 3} fontSize={9} fill="currentColor" fillOpacity={0.6}>{lat}°</text>
            ))}
            <text x={padL + plotW / 2} y={h - 1} textAnchor="middle" fontSize={10} fill="currentColor" fillOpacity={0.6}>Longitud (°O)</text>
          </svg>
          <ColorBar scale={6} units=" m/s" />
        </div>
      </SectionCard>

      {/* Leyenda de dirección */}
      <SectionCard title={<span className="flex items-center gap-2"><Compass className="h-4 w-4" /> Lectura de los vectores</span>}>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-lg border border-[color:var(--enso-warm)]/30 bg-[color:var(--enso-warm)]/5 p-3">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <ArrowRight className="h-4 w-4" /> Flecha hacia el este
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              <strong>u &gt; 0</strong> · componente del <strong>oeste</strong> (westerly). Anomalía
              típica de El Niño de cuenca: desplaza la masa de agua cálida hacia el este.
            </p>
          </div>
          <div className="rounded-lg border border-[color:var(--enso-cool)]/30 bg-[color:var(--enso-cool)]/5 p-3">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <ArrowLeft className="h-4 w-4" /> Flecha hacia el oeste
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              <strong>u &lt; 0</strong> · componente del <strong>este</strong> (easterly). Anomalía
              típica de La Niña de cuenca: refuerza el transporte ecuatorial hacia el oeste.
            </p>
          </div>
        </div>
        <div className="mt-3 rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground">
          <p>
            La <strong>longitud</strong> de cada flecha es proporcional a la magnitud del vector de
            anomalía; el <strong>color</strong> refleja la componente zonal u (cálido = del oeste,
            frío = del este). Los vectores representan <strong>anomalías</strong> respecto a la
            climatología, no el viento observado.
          </p>
        </div>
      </SectionCard>

      {/* Resumen del mes */}
      <SectionCard title="Resumen del viento zonal — mes más reciente">
        <div className="grid gap-4 md:grid-cols-2 text-xs">
          <div>
            <p className="text-[11px] text-muted-foreground">Anomalía u850 promedio ecuatorial</p>
            <BigValue value={fmtValue(u850?.point.value ?? null, "m_per_s").replace(" m/s", "")} units="m/s" tone={u850?.point.value && u850.point.value > 0 ? "warm" : "cool"} />
            <p className="mt-1 text-[11px] text-muted-foreground">{fmtMonth(u850?.point.month ?? "")}</p>
          </div>
          <div>
            <FieldLine label="Nivel">{INDICATOR_BY_ID.u850.level}</FieldLine>
            <FieldLine label="Región">{INDICATOR_BY_ID.u850.region}</FieldLine>
            <FieldLine label="Convención">u &gt; 0 ⇒ este (oeste) · u &lt; 0 ⇒ oeste (este)</FieldLine>
            <FieldLine label="Tipo">Anomalía (no valor observado)</FieldLine>
          </div>
        </div>
      </SectionCard>
    </div>
  );
}
