"use client";

import * as React from "react";
import { INDICATORS } from "@/lib/enso/methodology";
import { SOURCES } from "@/lib/enso/sources";
import { SectionCard, ScopeBadge, InfoNote, FieldLine } from "./primitives";

export function MethodologyView() {
  return (
    <div className="space-y-5">
      <InfoNote tone="info" title="Metodología científica del observatorio">
        El observatorio mantiene separadas las escalas <strong>costera</strong> y <strong>de cuenca</strong>.
        Las alertas oficiales se citan de ENFEN y NOAA/CPC; las categorías de intensidad y las
        interpretaciones son generadas por el observatorio. Todas las transformaciones son
        deterministas, documentadas y reproducibles.
      </InfoNote>

      {/* Principios científicos */}
      <SectionCard title="Principios científicos">
        <div className="space-y-3 text-xs leading-relaxed text-muted-foreground">
          <p>
            <strong className="text-foreground">1. No conflatear costero y cuenca.</strong> El Niño
            Costero (escala del Pacífico oriental frente a Perú, monitoreado por ENFEN vía ICEN sobre
            Niño 1+2) y el ENSO de cuenca (Pacífico ecuatorial, monitoreado por NOAA/CPC vía RONI sobre
            Niño 3.4) son conceptos distintos. Pueden coexistir o presentarse por separado (p. ej.,
            2017 fue costero fuerte sin cuenca).
          </p>
          <p>
            <strong className="text-foreground">2. Convención del viento zonal.</strong> Para la
            componente u: <code>u &gt; 0</code> = flujo hacia el este (componente del oeste /
            westerly); <code>u &lt; 0</code> = flujo hacia el oeste (componente del este / easterly).
            Se distingue valor observado de anomalía, y superficie (10 m) de bajo nivel (850 hPa).
          </p>
          <p>
            <strong className="text-foreground">3. D20 como proxy de la termoclina.</strong> La
            profundidad de la isoterma de 20 °C aproxima la profundidad de la termoclina en el
            Pacífico ecuatorial. Anomalía positiva ⇒ más profunda (El Niño de cuenca); negativa ⇒ más
            somera (La Niña). Convención confirmada en GODAS.
          </p>
          <p>
            <strong className="text-foreground">4. SOI de cuenca; sin «SOI costero».</strong> El SOI
            convencional (Tahiti − Darwin) es de escala de cuenca. No se define un «SOI costero»: no
            existe un proxy de presión costera con respaldo metodológico equivalente.
          </p>
          <p>
            <strong className="text-foreground">5. Índice operacional vigente.</strong> NOAA/CPC
            emplea el RONI (baseline adaptativa) como índice operacional actual, no el ONI heredado de
            base 1971–2000. No se hard-codean versiones obsoletas.
          </p>
          <p>
            <strong className="text-foreground">6. Sin valores fabricados.</strong> Los datos
            faltantes se preservan; los datos preliminares se marcan; los fallos de fuente no
            reemplazan datos válidos previos.
          </p>
        </div>
      </SectionCard>

      {/* Definiciones de indicadores */}
      <SectionCard title="Definiciones de indicadores" description="Región, nivel, agregación, climatología, convención de signos y fuente.">
        <div className="space-y-3">
          {INDICATORS.map((ind) => (
            <div key={ind.id} className="rounded-lg border p-3">
              <div className="flex items-center justify-between gap-2">
                <h4 className="text-sm font-semibold">{ind.name}</h4>
                <ScopeBadge scope={ind.scope} />
              </div>
              <div className="mt-2 grid gap-x-6 gap-y-1 md:grid-cols-2 text-xs">
                <FieldLine label="Variable">{ind.variable}</FieldLine>
                <FieldLine label="Unidades">{ind.units}</FieldLine>
                <FieldLine label="Región">{ind.region}</FieldLine>
                <FieldLine label="Nivel">{ind.level ?? "—"}</FieldLine>
                <FieldLine label="Agregación">{ind.aggregation}</FieldLine>
                <FieldLine label="Climatología">{ind.climatology}</FieldLine>
                <FieldLine label="Dataset">{ind.dataset}</FieldLine>
                <FieldLine label="Oficial">{ind.isOfficial ? "Sí (clasificación oficial)" : "Derivada por el observatorio"}</FieldLine>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                <strong>Convención de signos:</strong> {ind.signConvention}
              </p>
              {ind.positiveMeans && (
                <p className="text-xs text-muted-foreground"><strong>Positivo:</strong> {ind.positiveMeans}</p>
              )}
              {ind.negativeMeans && (
                <p className="text-xs text-muted-foreground"><strong>Negativo:</strong> {ind.negativeMeans}</p>
              )}
              {ind.thresholds && (
                <details className="mt-1">
                  <summary className="cursor-pointer text-xs text-muted-foreground">Umbrales y categorías ({ind.thresholds.length})</summary>
                  <ul className="mt-1 grid gap-1 md:grid-cols-2 text-[11px] text-muted-foreground">
                    {ind.thresholds.map((t) => (
                      <li key={t.label}>
                        <span className="font-medium">{t.label}</span>: {t.min === -Infinity ? "−∞" : t.min} a {t.max === Infinity ? "+∞" : t.max} → {t.classification}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              <p className="mt-2 text-[11px] italic text-muted-foreground">{ind.notes}</p>
            </div>
          ))}
        </div>
      </SectionCard>

      {/* Comparación gratuita vs pagada */}
      <SectionCard title="Comparación de fuentes: gratuitas vs pagadas" description="El observatorio prioriza fuentes abiertas y oficiales. Las pagadas se evalúan sin activarlas.">
        <div className="overflow-x-auto enso-scroll">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="py-2 pr-3 font-medium">Fuente</th>
                <th className="py-2 pr-3 font-medium">Modelo</th>
                <th className="py-2 pr-3 font-medium">Licencia</th>
                <th className="py-2 pr-3 font-medium">Cobertura</th>
                <th className="py-2 pr-3 font-medium">Calidad</th>
                <th className="py-2 font-medium">Beneficio esperado</th>
              </tr>
            </thead>
            <tbody>
              {SOURCE_TABLE.map((r, i) => (
                <tr key={i} className="border-b last:border-0">
                  <td className="py-2 pr-3 font-medium">{r.name}</td>
                  <td className="py-2 pr-3">{r.model}</td>
                  <td className="py-2 pr-3">{r.license}</td>
                  <td className="py-2 pr-3">{r.coverage}</td>
                  <td className="py-2 pr-3">{r.quality}</td>
                  <td className="py-2 text-muted-foreground">{r.benefit}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground">
          Decisión: el observatorio opera exclusivamente con fuentes abiertas y oficiales. No se
          adquieren ni activan fuentes pagadas.
        </p>
      </SectionCard>

      {/* Limitaciones */}
      <SectionCard title="Limitaciones y manejo de incertidumbre">
        <ul className="space-y-2 text-xs text-muted-foreground">
          <li>• Los datos preliminares pueden revisarse en publicaciones posteriores.</li>
          <li>• La latencia varía por fuente (días a semanas); se reporta el mes de referencia y la fecha de corte.</li>
          <li>• El campo grilleado de los mapas es una síntesis coherente; los productos oficiales (OISST, GODAS) ofrecen mayor detalle.</li>
          <li>• La cobertura de boyas TAO/TRITON es irregular; los huecos se preservan.</li>
          <li>• El observatorio no es un servicio oficial de alerta; remite a ENFEN, SENAMHI, INDECI y CENEPRED.</li>
          <li>• Las categorías de intensidad reproducen la metodología ENFEN; ante duda, prima la publicación oficial.</li>
        </ul>
      </SectionCard>
    </div>
  );
}

const SOURCE_TABLE = [
  { name: "NOAA / CPC (RONI, ENSO Advisory)", model: "Gratuito", license: "Dominio público", coverage: "Cuenca, global", quality: "Operacional", benefit: "Estado oficial de cuenca; índice vigente." },
  { name: "NOAA / PSL (Niño 1+2, 3.4, SOI)", model: "Gratuito", license: "Dominio público", coverage: "Series mensuales 1950+", quality: "Reanálisis/observación", benefit: "Histórico largo y reproducible." },
  { name: "NOAA / CPC (GODAS, u850)", model: "Gratuito", license: "Dominio público", coverage: "Pacífico ecuatorial", quality: "Asimilación", benefit: "Subsuperficie y viento de bajo nivel." },
  { name: "ENFEN / IMARPE (ICEN, alerta)", model: "Gratuito", license: "Institucional abierto", coverage: "Costero Perú", quality: "Oficial", benefit: "Estado oficial costero del Perú." },
  { name: "PMEL TAO/TRITON", model: "Gratuito", license: "Dominio público", coverage: "Boyas ecuatoriales", quality: "In situ", benefit: "Validación in situ; cobertura irregular." },
  { name: "Copernicus CDS (ERA5, OISST)", model: "Gratuito (registro)", license: "CC BY 4.0", coverage: "Global", quality: "Reanálisis", benefit: "Alternativa sólida; requiere registro." },
  { name: "Proveedores comerciales (ej. meteorológicos privados)", model: "Pagado", license: "Suscripción", coverage: "Variable", quality: "Variable", benefit: "No se adopta; las fuentes abiertas cubren los requisitos." },
];
