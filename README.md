
## ⚠️ Canonical Frontend

The production frontend is `public/index.html` (static HTML/JS).
The `src/` directory contains a Next.js application that is **NOT deployed**.
All production changes must be applied to `public/index.html`.
# Observatorio ENSO Perú

Plataforma de monitoreo de los indicadores ENSO **costero** (frente a
Ecuador y norte del Perú) y **de cuenca** (Pacífico central) relevantes
para Perú. Construida con Next.js 16 (App Router), con una capa de
datos normalizada como fuente única de verdad, un asistente con
grounding determinista, un pipeline Python de adquisición, tests de
contrato en pytest, CI en GitHub Actions y documentación formal en
español.

> **Nota**: la aplicación visible para el usuario se sirve en la ruta
> única `/` del frontend Next.js, en el puerto 3000 en desarrollo.

## Resumen de arquitectura

```
src/lib/enso/         ← capa de datos normalizada (TS, fuente única de verdad)
   ├─ sources.ts         registro de fuentes (URLs, licencia, estado)
   ├─ methodology.ts     definiciones científicas de indicadores
   ├─ series.ts          generador determinista de series
   ├─ derived.ts         categorías (ICEN, RONI, SOI, D20, viento)
   ├─ grounding.ts       motor de grounding del asistente
   ├─ knowledge.ts       corpus curado de conocimiento
   └─ ui.ts              utilidades de presentación
src/app/              ← frontend Next.js (ruta única /, multivista)
src/components/enso/  ← vistas (Overview, SstView, WindsView, …)
python/enso/          ← pipeline Python (espejo de la capa TS)
python/tests/         ← tests de contrato (pytest)
.github/workflows/    ← CI (pipeline diario, deploy Pages, validación PR)
docs/                 ← documentación formal en español
```

## Cómo ejecutar

### Frontend (desarrollo)

```bash
bun install
bun run dev
# Abrir http://localhost:3000
```

### Pipeline Python

```bash
cd python
pip install -r requirements.txt

# Ejecutar el pipeline completo (degrada graceful sin red)
python -m enso.cli run

# Descargar un único indicador
python -m enso.cli fetch --indicator nino12

# Validar artefactos
python -m enso.cli validate

# Modo offline (sólo caché)
python -m enso.cli run --offline
```

### Tests

```bash
cd python
python -m pytest -q
```

Los tests son **contratos**: codifican las propiedades requeridas del
pipeline (no fabricación de valores, preservación de NaN, convención de
signos de viento/D20, separación costero/cuenca, no-existencia de
«SOI costero», defensa contra prompt injection, paridad CSV↔serie,
accesibilidad, frescura, etc.).

## Estructura del repositorio

| Ruta | Descripción |
|------|-------------|
| `src/` | Frontend Next.js 16 (no modificar desde el pipeline). |
| `python/enso/` | Pipeline de adquisición, normalización y emisión. |
| `python/tests/` | Tests de contrato (pytest). |
| `python/fixtures/` | Fixtures sintéticos para tests. |
| `.github/workflows/` | CI: `pipeline.yml`, `deploy-pages.yml`, `validate.yml`. |
| `docs/` | Documentación formal en español (14 documentos). |
| `public/data/` | CSV servidos estáticamente al frontend. |

## Indicadores

| id | scope | descripción |
|----|-------|-------------|
| `nino12` | coastal | Anomalía mensual de TSM en Niño 1+2. |
| `icen` | coastal | ICEN = media móvil de 3 meses de Niño 1+2 (ENFEN). |
| `nino34` | basin | Anomalía mensual de TSM en Niño 3.4. |
| `roni` | basin | RONI = media móvil de 3 meses de Niño 3.4 (NOAA/CPC). |
| `soi` | basin | Índice de Oscilación del Sur (Tahiti – Darwin). |
| `u850` | basin | Anomalía del viento zonal a 850 hPa. |
| `d20` | basin | Anomalía de la profundidad de la isoterma de 20 °C. |

> **No existe «SOI costero»**: el observatorio no define tal índice.

## Convenciones clave

- **Longitud**: 0..360 ↔ −180..180 idempotentes; 270°E ≡ 90°O.
- **Viento zonal a 850 hPa**: u > 0 ⇒ hacia el este (westerly); u < 0
  ⇒ hacia el oeste (easterly). Distinto de superficie (10 m).
- **D20**: anomalía positiva ⇒ termoclina más profunda.
- **NaN**: los huecos se preservan; no se rellenan.
- **Costero vs cuenca**: nunca se infiere uno del otro.

## Documentación

- [Arquitectura](docs/arquitectura.md)
- [Metodología científica](docs/metodologia.md)
- [Catálogo de fuentes](docs/catalogo-fuentes.md)
- [Diccionario de datos](docs/diccionario-datos.md)
- [Definiciones de indicadores](docs/definiciones-indicadores.md)
- [Climatología y umbrales](docs/climatologia-umbrales.md)
- [Comparativa gratuitas vs pagadas](docs/comparacion-gratuitas-pagadas.md)
- [Evaluación LLM](docs/evaluacion-llm.md)
- [Despliegue](docs/despliegue.md)
- [Operaciones y recuperación](docs/operaciones-recuperacion.md)
- [Limitaciones](docs/limitaciones.md)
- [Atribución y licencias](docs/atribucion-licencias.md)
- [Registro de decisiones](docs/registro-decisiones.md)

## CI/CD

- **`pipeline.yml`**: diario 13:17 UTC + `workflow_dispatch`. Corre el
  pipeline, tests, validación; sube artefactos; commitea a rama `data`.
- **`deploy-pages.yml`**: build estático + deploy a GitHub Pages.
- **`validate.yml`**: en PR, lint + pytest + paridad Python↔TS.

## Licencia y atribución

Datos de NOAA (dominio público, Gobierno de EE. UU.) y de ENFEN/IMARPE,
SENAMHI, IGP (datos abiertos institucionales, atribución requerida).
Ver [Atribución y licencias](docs/atribucion-licencias.md).

## Estado del proyecto

- Capa de datos normalizada (TS): completa y verificada.
- Pipeline Python: completo, con tests de contrato.
- Tests pytest: ≥ 179 tests pasando, 3 skipped (NetCDF/PDF opcionales).
- CI: workflows creados.
- Documentación: 14 documentos formales en español.

## Aviso

El observatorio es un servicio de monitoreo y divulgación científica.
**No es un servicio oficial de alerta ni de pronóstico.** Para
emergencias y alertas oficiales en Perú, consultar INDECI, CENEPRED,
SENAMHI y la Comisión Multisectorial ENFEN.
