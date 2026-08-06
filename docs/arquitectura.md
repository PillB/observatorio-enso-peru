# Arquitectura — Observatorio ENSO Perú

> Documento de arquitectura del sistema. Formal Spanish. Pública para
> colaboradores y revisores.

## 1. Visión general

El Observatorio ENSO Perú es una plataforma de monitoreo de los
indicadores ENSO **costero** y **de cuenca** relevantes para Perú. Está
compuesta por:

1. **Frontend** Next.js 16 (App Router), ruta única `/`, multivista por
   estado. Servido en puerto 3000 en desarrollo.
2. **Capa de datos normalizada** en TypeScript (`src/lib/enso/`): fuente
   única de verdad para todas las vistas, descargas CSV y el asistente.
3. **Pipeline Python** (`python/enso/`): adquisición, normalización y
   emisión de artefactos CSV/JSON espejo de la capa TS. No renderiza en
   el navegador; se ejecuta en CI.
4. **Asistente conversacional** con grounding determinista: sólo usa
   datos del proyecto y un corpus curado; nunca memoria del modelo.
5. **CI/CD** GitHub Actions: pipeline diario, validación en PR, deploy
   Pages.
6. **Documentación** formal en `docs/`.

## 2. Principios arquitectónicos

### 2.1 Fuente única de verdad

Toda visualización, tabla, descarga y respuesta del asistente se deriva
de la capa de datos normalizada en `src/lib/enso/series.ts`. El pipeline
Python espeja esta capa (`python/enso/`) con los mismos identificadores
de fuente e indicadores, garantizando consistencia entre ambos stacks.

### 2.2 Separación costero vs cuenca

El observatorio mantiene los conceptos **El Niño Costero** (frente a
Ecuador y norte del Perú, monitoreado con ICEN sobre Niño 1+2) y **El
Niño de cuenca** (Pacífico central, monitoreado con RONI sobre Niño 3.4)
como entidades independientes. Un evento puede ocurrir sin el otro (caso
paradigmático: 2017, costero fuerte sin cuenca). **Nunca se infiere uno
del otro.**

### 2.3 No fabricación de valores

Cuando un dato no está disponible, el observatorio muestra «Sin datos» y
**nunca** sustituye el valor por uno fabricado. Los datos preliminares
se marcan explícitamente y pueden revisarse en publicaciones posteriores.

### 2.4 Grounding determinista

El asistente no usa memoria del modelo como fuente factual. Todo valor
citable tiene un identificador de evidencia (`EVID-<indicator>`), un mes
de validez y una URL de fuente. La misma pregunta produce la misma
evidencia.

### 2.5 Defensa contra prompt injection

Las instrucciones incrustadas en informes, CSV, metadatos o preguntas
del usuario se ignoran. El motor de grounding no añade indicadores a
partir de texto inyectado, no revela instrucciones ocultas y no ejecuta
comandos.

### 2.6 Degradación graceful

El pipeline Python está diseñado para funcionar sin red (sandbox
restringido, CI cortés): usa caché local, preserva el último conjunto
válido y marca los datos como obsoletos (`stale`). Nunca interrumpe la
publicación por un fallo transitorio de una fuente.

## 3. Capas

### 3.1 Frontend (`src/`)

- `src/app/page.tsx` — dashboard SPA, multivista por estado.
- `src/components/enso/` — vistas: Overview, SstView, WindsView,
  ThermoclineView, SoiView, HistoricalView, MapsView, DownloadsView,
  MethodologyView, SourcesView, ChatView.
- `src/app/api/` — rutas API: `/api/data`, `/api/status`, `/api/chat`.

### 3.2 Capa de datos (`src/lib/enso/`)

- `sources.ts` — registro de fuentes (URLs, licencia, estado de
  verificación).
- `methodology.ts` — definiciones científicas de indicadores (región,
  nivel, climatología, umbrales, signos).
- `series.ts` — generador determinista de series normalizadas.
- `derived.ts` — categorías (ICEN, RONI, SOI, D20, viento), percentiles,
  estado consolidado.
- `grounding.ts` — motor de grounding del asistente.
- `knowledge.ts` — corpus curado de conocimiento autorizado.
- `ui.ts` — utilidades de presentación (formateadores, paleta).

### 3.3 Pipeline Python (`python/enso/`)

- `models.py` — modelos pydantic (espejo de los tipos TS).
- `sources.py` / `methodology.py` — registros espejo.
- `fetchers.py` — descargadores con reintentos, HTTP condicional,
  validación, caché, checksum SHA-256.
- `normalize.py` — conversiones de longitud/tiempo, verificación de
  signos.
- `derived.py` — ICEN, RONI, categorías, percentiles.
- `pipeline.py` — orquestador idempotente, manifiesto, estado
  consolidado, helper `asset_url` para subpath Pages.
- `cli.py` — CLI: `fetch`, `run`, `validate`.

### 3.4 CI/CD (`.github/workflows/`)

- `pipeline.yml` — cron diario 13:17 UTC + `workflow_dispatch`: corre
  el pipeline, sube artefactos, commitea a rama `data` en schedule.
- `deploy-pages.yml` — build estático + deploy a GitHub Pages.
- `validate.yml` — en PR: lint + pytest + paridad Python↔TS.

### 3.5 Documentación (`docs/`)

Formal Spanish, comprensiva. Incluye arquitectura, metodología,
catálogo de fuentes, diccionario de datos, definiciones de indicadores,
climatología y umbrales, comparativa gratuitas vs pagadas, evaluación
LLM, despliegue, operaciones y recuperación, limitaciones, atribución y
registro de decisiones.

## 4. Flujo de datos

```
NOAA/PSL ──┐
NOAA/CPC ──┤
ENFEN ─────┼──▶ Pipeline Python (fetchers, normalize, derived)
SENAMHI ───┤           │
IGP ───────┘           ▼
              python/out/{manifest,status,sources,*.csv}
                       │
                       ▼
              Frontend Next.js (src/lib/enso/series.ts)
                       │
                       ├──▶ Vistas (Overview, SstView, …)
                       ├──▶ Descargas CSV (cliente, desde la capa)
                       └──▶ Asistente (grounding.ts → /api/chat)
```

## 5. Modelos de despliegue

- **Desarrollo**: `bun run dev` en puerto 3000, ruta `/`.
- **Producción (GitHub Pages)**: export estático con `basePath` al
  repositorio. Datos del pipeline servidos desde `public/data/` o desde
  la rama `data`.
- **Inferencia LLM**: el asistente usa el SDK `z-ai-web-dev-sdk` vía
  API route. Para Pages-only, se prefiere inferencia local en el
  navegador cuando pasa la evaluación (ver `docs/evaluacion-llm.md`),
  con fallback determinista cuando WebGPU no está disponible.

## 6. Trazabilidad

Cada artefacto del pipeline registra:

- `data_version` (semver).
- `as_of_month` y `as_of_date` (mes y fecha de corte).
- `checksum` FNV-1a por serie (igual que `series.ts`).
- `file_sha256` por CSV.
- `fetched_at`, `etag`, `last_modified`, `preliminary`, `from_cache`.

El manifiesto y el estado consolidado permiten auditoría y rollback
(ver `docs/operaciones-recuperacion.md`).

## 7. Restricciones y convenciones

- No modificar `src/` desde el pipeline: el frontend es la capa de
  presentación; el pipeline produce artefactos.
- Longitudes 0..360 ↔ -180..180 idempotentes; 270°E ≡ 90°O.
- Viento zonal u a 850 hPa: u > 0 ⇒ hacia el este (westerly); u < 0 ⇒
  hacia el oeste (easterly). Distinto de superficie (10 m).
- D20: anomalía positiva ⇒ termoclina más profunda.
- NaN se preserva; no se rellena.
- SOI es de cuenca; **no existe «SOI costero»**.

## 8. Referencias cruzadas

- Metodología científica: `docs/metodologia.md`.
- Catálogo de fuentes: `docs/catalogo-fuentes.md`.
- Diccionario de datos: `docs/diccionario-datos.md`.
- Operaciones y recuperación: `docs/operaciones-recuperacion.md`.
- Limitaciones: `docs/limitaciones.md`.
