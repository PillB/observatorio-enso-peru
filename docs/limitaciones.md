# Limitaciones — Observatorio ENSO Perú

> Formal Spanish. Documentación honesta de las limitaciones del
> observatorio.

## 1. No es un servicio oficial de alerta

El observatorio es un servicio de **monitoreo y divulgación científica**.
No es un servicio oficial de alerta ni de pronóstico. Para emergencias y
alertas oficiales en Perú, consultar:

- **INDECI** (Instituto Nacional de Defensa Civil).
- **CENEPRED** (Centro Nacional de Estimación, Prevención y Reducción
  del Riesgo de Desastres).
- **SENAMHI** (Servicio Nacional de Meteorología e Hidrología).
- **Comisión Multisectorial ENFEN**.

No se emiten afirmaciones deterministas sobre desastres.

## 2. Latencia de los datos

Los datos no son en tiempo real:

- PSL Niño 1+2/3.4/SOI: latencia de semanas.
- CPC RONI: latencia de semanas.
- ENFEN ICEN: latencia de semanas.
- GODAS / u850: latencia de días a 1–2 semanas.

La frescura de cada indicador se documenta en `status.json`. Un
indicador con `freshness_hours > 72` se marca `stale`.

## 3. Cobertura histórica y discontinuidades

- **RONI vs ONI**: el RONI (baseline adaptativa) y el ONI heredado
  (base fija 1971–2000) **no son directamente comparables**. El RONI es
  el índice operacional actual.
- **ICEN**: la metodología ENFEN vigente puede diferir de metodologías
  históricas; series muy largas pueden tener discontinuidades.
- **D20 / u850**: provienen de reanálisis/asimilación (GODAS,
  NCEP/NCAR); su incertidumbre aumenta hacia el pasado.
- **TAO/TRITON**: cobertura irregular; los huecos se preservan, no se
  rellenan.

## 4. Calidad de los datos preliminares

Los datos preliminares (últimos 1–2 meses) pueden revisarse en
publicaciones posteriores. Se marcan explícitamente
(`flag=preliminary`). El observatorio no garantiza que un dato
preliminar coincida con el dato final.

## 5. No hay «SOI costero»

El observatorio **no define** un «SOI costero»: no existe un proxy de
presión costera con definición ni respaldo metodológico equivalente al
SOI convencional. La condición costera se monitorea con TSM Niño 1+2 e
ICEN. Cualquier mención a «SOI costero» se corrige.

## 6. No se infiere costero desde cuenca (ni viceversa)

El Niño Costero y el El Niño de cuenca se mantienen como conceptos
**separados**. El observatorio no infiere uno del otro. El caso 2017
(costero fuerte sin cuenca) es paradigmático.

## 7. Inferencia del asistente

El asistente:

- Usa **sólo** datos del proyecto, metadatos/metodología del proyecto y
  el corpus curado. No usa memoria del modelo como fuente factual.
- **No fabrica** valores ausentes: si no hay dato, dice «Sin datos».
- **No ejecuta** instrucciones inyectadas (prompt injection).
- **No revela** instrucciones ocultas ni credenciales.

La calidad de las respuestas depende del modo de inferencia (determinista
vs LLM). El modo determinista es el baseline garantizado.

## 8. Dependencia de fuentes externas

El observatorio depende de la disponibilidad de las fuentes públicas.
Ante fallos:

- El pipeline usa caché y preserva el último válido.
- Los datos se marcan `stale`.
- El servicio no se interrumpe, pero la frescura puede degradarse.

## 9. Sin pronósticos

El observatorio **no emite pronósticos**. Los pronósticos oficiales de
ENSO están disponibles en NOAA/CPC y ENFEN. El observatorio puede
enlazarlos pero no reproducirlos como propios.

## 10. Accesibilidad

- Los gráficos declaran `role="img"` y `aria-label`.
- Se respeta `prefers-reduced-motion`.
- La configuración es mobile-first.
- WebGPU es opcional; el modo determinista siempre está disponible.

## 11. Idioma

Toda la interfaz y documentación está en **español formal**,
comprensible internacionalmente y apta para Perú. No hay traducciones
oficiales a otros idiomas.

## 12. Cobertura geográfica

El observatorio cubre:

- **Costero**: Niño 1+2 (frente a Ecuador y norte del Perú).
- **Cuenca**: Niño 3.4 (Pacífico central ecuatorial).
- **Atmósfera**: SOI (Tahiti–Darwin), u850 (Pacífico ecuatorial).
- **Subsuperficie**: D20 (Pacífico ecuatorial).

No cubre:

- Otras regiones (Atlántico, Índico).
- Otras variables (salinidad, corriente, olas, etc.) salvo mención
  explícita con salvedades.
- Pronósticos estacionales regionales (se remite a SENAMHI/IGP).

## 13. Limitaciones del pipeline Python

- Requiere Python 3.10+.
- Algunas dependencias (`xarray`, `netcdf4`) pueden no estar
  disponibles en todos los entornos; los tests se saltan con razón en
  ese caso.
- No descarga datos si la red está bloqueada; degrada a caché/último
  válido.
- No implementa OCR de PDFs escaneados (sólo extrae texto embebido con
  pypdf).

## 14. Limitaciones del despliegue Pages-only

- Sin backend: las API routes no funcionan en Pages estático. El
  asistente opera en modo determinista o con inferencia local en el
  navegador (WebLLM/Transformers.js).
- `basePath` al nombre del repositorio es obligatorio.
- Los datos del pipeline se sirven como archivos estáticos desde
  `public/data/` o desde la rama `data`.
