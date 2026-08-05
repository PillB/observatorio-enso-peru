"use client";

import * as React from "react";
import { OverviewView } from "@/components/enso/Overview";
import { SstView } from "@/components/enso/SstView";
import { WindsView } from "@/components/enso/WindsView";
import { ThermoclineView } from "@/components/enso/ThermoclineView";
import { SoiView } from "@/components/enso/SoiView";
import { HistoricalView } from "@/components/enso/HistoricalView";
import { MapsView } from "@/components/enso/MapsView";
import { WindMapView } from "@/components/enso/WindMapView";
import { TimelapseView } from "@/components/enso/TimelapseView";
import { ForecastsView } from "@/components/enso/ForecastsView";
import { RegionalView } from "@/components/enso/RegionalView";
import { AlertsView } from "@/components/enso/AlertsView";
import { CorrelationsView } from "@/components/enso/CorrelationsView";
import { GlossaryView } from "@/components/enso/GlossaryView";
import { CompositeView } from "@/components/enso/CompositeView";
import { SeasonalityView } from "@/components/enso/SeasonalityView";
import { EventComparisonView } from "@/components/enso/EventComparisonView";
import { DownloadsView } from "@/components/enso/DownloadsView";
import { ChatView } from "@/components/enso/ChatView";
import { MethodologyView } from "@/components/enso/MethodologyView";
import { SourcesView } from "@/components/enso/SourcesView";
import { ThemeToggle } from "@/components/enso/ThemeToggle";
import { buildCurrentStatus } from "@/lib/enso/derived";
import { AS_OF_DATE } from "@/lib/enso/series";
import {
  LayoutDashboard, Waves, Wind, Thermometer, Gauge, History, Map, Database,
  Bot, BookOpen, ShieldCheck, Menu, X, Anchor, Clock, Film, Wind as WindIcon,
  TrendingUp, MapPin, AlertTriangle, GitCompare, BookA, Layers, Calendar, Layers3,
} from "lucide-react";

type ViewId =
  | "overview" | "tsm" | "vientos" | "termoclina" | "soi"
  | "historico" | "mapas" | "viento-mapa" | "animacion" | "pronostico" | "regional"
  | "alertas" | "correlaciones" | "compuesto" | "eventos-comparar" | "estacionalidad"
  | "datos" | "asistente" | "metodologia" | "glosario" | "fuentes";

const NAV: { id: ViewId; label: string; icon: React.ElementType; scope?: "coastal" | "basin" }[] = [
  { id: "overview", label: "Resumen", icon: LayoutDashboard },
  { id: "tsm", label: "TSM", icon: Waves },
  { id: "vientos", label: "Vientos", icon: Wind },
  { id: "termoclina", label: "Termoclina", icon: Thermometer },
  { id: "soi", label: "SOI y presión", icon: Gauge },
  { id: "historico", label: "Histórico", icon: History },
  { id: "eventos-comparar", label: "Comparar eventos", icon: Layers3 },
  { id: "estacionalidad", label: "Estacionalidad", icon: Calendar },
  { id: "mapas", label: "Mapas", icon: Map },
  { id: "viento-mapa", label: "Viento mapa", icon: WindIcon },
  { id: "animacion", label: "Animación", icon: Film },
  { id: "pronostico", label: "Pronóstico", icon: TrendingUp },
  { id: "regional", label: "Perú regional", icon: MapPin },
  { id: "alertas", label: "Alertas", icon: AlertTriangle },
  { id: "correlaciones", label: "Correlaciones", icon: GitCompare },
  { id: "compuesto", label: "Índice compuesto", icon: Layers },
  { id: "datos", label: "Datos", icon: Database },
  { id: "asistente", label: "Asistente", icon: Bot },
  { id: "metodologia", label: "Metodología", icon: BookOpen },
  { id: "glosario", label: "Glosario", icon: BookA },
  { id: "fuentes", label: "Fuentes", icon: ShieldCheck },
];

const VIEW_TITLES: Record<ViewId, { title: string; subtitle: string }> = {
  overview: { title: "Resumen ejecutivo", subtitle: "Estado costero y de cuenca, indicadores clave y frescura." },
  tsm: { title: "Temperatura superficial del mar", subtitle: "Anomalía de TSM costera (Niño 1+2, ICEN) y de cuenca (Niño 3.4, RONI)." },
  vientos: { title: "Viento zonal", subtitle: "Anomalía del viento zonal a 850 hPa con convención de signos explícita." },
  termoclina: { title: "Termoclina (D20)", subtitle: "Profundidad de la isoterma de 20 °C, Hovmöller y sección subsuperficial." },
  soi: { title: "SOI y presión", subtitle: "Índice de Oscilación del Sur (escala de cuenca). Sin «SOI costero»." },
  historico: { title: "Comparación histórica", subtitle: "Eventos ENSO, percentiles y caso 2017 (costero sin cuenca)." },
  mapas: { title: "Mapas de anomalía", subtitle: "TSM y D20 sobre el Pacífico ecuatorial." },
  "viento-mapa": { title: "Mapa de viento", subtitle: "Vectores de anomalía del viento a 850 hPa con convención de signos." },
  animacion: { title: "Animación temporal", subtitle: "Evolución mensual del campo de anomalía con controles accesibles." },
  pronostico: { title: "Pronóstico ENSO", subtitle: "Ensamble probabilístico por trimestre (interpretación del observatorio)." },
  regional: { title: "Impacto regional — Perú", subtitle: "Departamentos costeros: TSM, precipitación y riesgo relativo derivado." },
  alertas: { title: "Alertas y umbrales", subtitle: "Seguimiento de condiciones de activación de evento (derivadas del observatorio)." },
  correlaciones: { title: "Correlaciones entre indicadores", subtitle: "Coeficientes de Pearson calculados en código sobre la historia completa." },
  compuesto: { title: "Índice compuesto ENSO", subtitle: "Síntesis integrada de indicadores oceánicos y atmosféricos (interpretación del observatorio)." },
  "eventos-comparar": { title: "Comparador de eventos", subtitle: "Seleccione y compare eventos históricos alineados por mes de pico." },
  estacionalidad: { title: "Estacionalidad", subtitle: "Climatología mensual por indicador: promedio, dispersión y valor actual." },
  datos: { title: "Datos y descargas", subtitle: "Tabla histórica filtrable, CSV por serie y del resultado filtrado." },
  asistente: { title: "Asistente conversacional", subtitle: "Respuestas con base determinista (grounded) en los datos del observatorio." },
  metodologia: { title: "Metodología", subtitle: "Definiciones, convenciones, climatología y comparación de fuentes." },
  glosario: { title: "Glosario climático", subtitle: "Términos ENSO en español formal con definiciones y referencias." },
  fuentes: { title: "Fuentes", subtitle: "Catálogo de fuentes verificadas con atribución y licencias." },
};

export default function Home() {
  const [view, setView] = React.useState<ViewId>("overview");
  const [navOpen, setNavOpen] = React.useState(false);
  const status = React.useMemo(() => buildCurrentStatus(), []);

  const mainRef = React.useRef<HTMLElement>(null);
  React.useEffect(() => {
    mainRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, [view]);

  function navigate(v: string) {
    setView(v as ViewId);
    setNavOpen(false);
  }

  const meta = VIEW_TITLES[view];

  return (
    <div className="enso-shell text-foreground">
      {/* ===== Encabezado ===== */}
      <header className="enso-header-glass sticky top-0 z-30 border-b">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-2.5">
          <div className="flex items-center gap-2.5">
            <span className="grid h-9 w-9 place-items-center rounded-lg bg-primary text-primary-foreground shadow-sm" style={{ background: "linear-gradient(135deg, var(--enso-basin), color-mix(in oklch, var(--enso-basin) 60%, var(--enso-coastal)))" }}>
              <Anchor className="h-5 w-5" />
            </span>
            <div className="leading-tight">
              <h1 className="text-sm font-bold sm:text-base">Observatorio ENSO Perú</h1>
              <p className="hidden text-[11px] text-muted-foreground sm:block">
                Monitoreo costero y de cuenca · fuentes NOAA y ENFEN
              </p>
            </div>
          </div>

          {/* Estado rápido en el header */}
          <div className="ml-auto hidden items-center gap-2 lg:flex">
            <span className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] enso-badge-coastal">
              <span className="h-1.5 w-1.5 rounded-full bg-[color:var(--enso-coastal-fg)] enso-pulse" aria-hidden />
              <span className="font-semibold">Costero:</span> {status.coastal.alert}
            </span>
            <span className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] enso-badge-basin">
              <span className="h-1.5 w-1.5 rounded-full bg-[color:var(--enso-basin-fg)] enso-pulse" aria-hidden />
              <span className="font-semibold">Cuenca:</span> {status.basin.alert}
            </span>
            <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
              <Clock className="h-3 w-3" /> {AS_OF_DATE}
            </span>
          </div>

          {/* Toggle de tema (claro/oscuro) */}
          <div className="lg:ml-2">
            <ThemeToggle />
          </div>

          {/* Botón menú móvil */}
          <button
            onClick={() => setNavOpen((v) => !v)}
            className="inline-flex items-center justify-center rounded-md border p-2 lg:hidden enso-focus-ring"
            aria-label="Abrir menú de navegación"
            aria-expanded={navOpen}
          >
            {navOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
          </button>
        </div>

        {/* Navegación móvil desplegable */}
        {navOpen && (
          <nav className="border-t bg-background px-4 py-2 lg:hidden" aria-label="Navegación móvil">
            <div className="grid grid-cols-2 gap-1.5">
              {NAV.map((n) => (
                <button
                  key={n.id}
                  onClick={() => navigate(n.id)}
                  className={`flex items-center gap-2 rounded-md px-2.5 py-2 text-xs font-medium ${view === n.id ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}
                >
                  <n.icon className="h-4 w-4" /> {n.label}
                </button>
              ))}
            </div>
          </nav>
        )}
      </header>

      <div className="enso-main mx-auto flex w-full max-w-7xl gap-5 px-4 py-5">
        {/* ===== Sidebar de escritorio ===== */}
        <aside className="hidden w-52 shrink-0 lg:block" aria-label="Navegación principal">
          <nav className="sticky top-20 space-y-0.5">
            {NAV.map((n) => (
              <button
                key={n.id}
                onClick={() => navigate(n.id)}
                aria-current={view === n.id ? "page" : undefined}
                className={`enso-focus-ring flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-all ${
                  view === n.id
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "text-foreground/80 hover:bg-muted hover:text-foreground hover:translate-x-0.5"
                }`}
              >
                <n.icon className="h-4 w-4 shrink-0" />
                <span className="truncate">{n.label}</span>
              </button>
            ))}
            <div className="mt-3 rounded-lg border bg-muted/40 p-2.5 text-[11px] text-muted-foreground">
              <p className="font-medium text-foreground">Periodo de validez</p>
              <p className="mt-0.5">Corte: {AS_OF_DATE}</p>
              <p className="mt-0.5">Mes ref.: {status.coastal.nino12Month}</p>
              <p className="mt-0.5">Versión datos: {status.dataVersion}</p>
            </div>
          </nav>
        </aside>

        {/* ===== Contenido principal ===== */}
        <main ref={mainRef} className="min-w-0 flex-1">
          <div key={view} className="enso-view-enter mb-4">
            <div className="flex items-center gap-2">
              <span className="h-6 w-1 rounded-full" style={{ background: "linear-gradient(180deg, var(--enso-basin), var(--enso-coastal))" }} aria-hidden />
              <h2 className="text-xl font-bold tracking-tight sm:text-2xl">{meta.title}</h2>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">{meta.subtitle}</p>
          </div>

          <div className="lg:hidden -mx-1 mb-4 overflow-x-auto enso-scroll">
            <div className="flex gap-1.5 px-1">
              {NAV.map((n) => (
                <button
                  key={n.id}
                  onClick={() => navigate(n.id)}
                  className={`flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium enso-focus-ring ${view === n.id ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted"}`}
                >
                  <n.icon className="h-3.5 w-3.5" /> {n.label}
                </button>
              ))}
            </div>
          </div>

          {view === "overview" && <OverviewView onNavigate={navigate} />}
          {view === "tsm" && <SstView />}
          {view === "vientos" && <WindsView />}
          {view === "termoclina" && <ThermoclineView />}
          {view === "soi" && <SoiView />}
          {view === "historico" && <HistoricalView />}
          {view === "mapas" && <MapsView />}
          {view === "viento-mapa" && <WindMapView />}
          {view === "animacion" && <TimelapseView />}
          {view === "pronostico" && <ForecastsView />}
          {view === "regional" && <RegionalView />}
          {view === "alertas" && <AlertsView />}
          {view === "correlaciones" && <CorrelationsView />}
          {view === "compuesto" && <CompositeView />}
          {view === "eventos-comparar" && <EventComparisonView />}
          {view === "estacionalidad" && <SeasonalityView />}
          {view === "datos" && <DownloadsView />}
          {view === "asistente" && <ChatView />}
          {view === "metodologia" && <MethodologyView />}
          {view === "glosario" && <GlossaryView />}
          {view === "fuentes" && <SourcesView />}
        </main>
      </div>

      {/* ===== Pie de página adherido ===== */}
      <footer className="mt-auto border-t bg-muted/30">
        <div className="mx-auto max-w-7xl px-4 py-5">
          <div className="grid gap-4 text-xs text-muted-foreground md:grid-cols-3">
            <div>
              <p className="font-semibold text-foreground">Observatorio ENSO Perú</p>
              <p className="mt-1">
                Monitoreo de indicadores costeros (El Niño Costero, ICEN, Niño 1+2) y de cuenca
                (Niño 3.4, RONI, SOI, D20, viento zonal 850 hPa). Divulgación científica con fuentes
                oficiales NOAA y ENFEN.
              </p>
            </div>
            <div>
              <p className="font-semibold text-foreground">Aviso importante</p>
              <p className="mt-1">
                Este observatorio <strong>no es un servicio oficial de alerta</strong>. Para
                emergencias y alertas oficiales consulte INDECI, CENEPRED, SENAMHI y la Comisión
                Multisectorial ENFEN. Las interpretaciones son generadas por el observatorio.
              </p>
            </div>
            <div>
              <p className="font-semibold text-foreground">Datos y atribución</p>
              <p className="mt-1">
                Corte de datos: {AS_OF_DATE} · versión {status.dataVersion}. Datos derivados de
                NOAA/CPC, NOAA/PSL, NOAA/PMEL, ENFEN/IMARPE, SENAMHI e IGP. Los datos preliminares
                pueden revisarse.
              </p>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-[11px] text-muted-foreground">
            <span>© {new Date().getFullYear()} Observatorio ENSO Perú · uso educativo y de divulgación.</span>
            <span className="flex items-center gap-3">
              <button onClick={() => navigate("metodologia")} className="hover:text-foreground hover:underline">Metodología</button>
              <button onClick={() => navigate("fuentes")} className="hover:text-foreground hover:underline">Fuentes</button>
              <button onClick={() => navigate("datos")} className="hover:text-foreground hover:underline">Descargas</button>
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}
