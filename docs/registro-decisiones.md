# Registro de decisiones y fallos — Observatorio ENSO Perú

> Formal Spanish. Bitácora de decisiones de diseño, investigación y
> fallos encontrados, con fecha y justificación.

## Formato

Cada entrada:

```
### [YYYY-MM-DD] Tipo: Título
- Contexto: ...
- Decisión / Hallazgo / Fallo: ...
- Justificación: ...
- Impacto: ...
```

Tipos: `Investigación`, `Decisión`, `Fallo`, `Recuperación`.

---

## 2026-07-09 — Investigación: estado ENSO de cuenca vigente

- **Contexto**: se necesitaba determinar el estado operacional actual de
  ENSO de cuenca.
- **Hallazgo**: NOAA/CPC ENSO Diagnostic Discussion (9 jul 2026)
  indica «El Niño Advisory» vigente. El índice operacional actual es el
  RONI (no el ONI heredado).
- **Justificación**: investigación directa vía web-search de la fuente
  oficial NOAA/CPC.
- **Impacto**: el observatorio usa RONI como índice operacional de
  cuenca y cita textualmente «El Niño Advisory».

## 2026-07-09 — Investigación: estado ENSO costero vigente

- **Contexto**: se necesitaba determinar el estado operacional actual de
  El Niño Costero.
- **Hallazgo**: ENFEN/IMARPE mantiene «Alerta de El Niño Costero»
  activa desde el 13 de febrero de 2026. El ICEN es el índice oficial
  costero.
- **Justificación**: investigación directa de siofen.imarpe.gob.pe y
  confirmación cruzada con SENAMHI e IGP.
- **Impacto**: el observatorio cita textualmente la alerta ENFEN y usa
  ICEN como índice costero.

## 2026-08-02 — Decisión: separación estricta costero vs cuenca

- **Contexto**: discusión sobre si derivar costero desde cuenca o
  viceversa.
- **Decisión**: mantener ambos como conceptos **separados**. No inferir
  uno del otro.
- **Justificación**: el caso 2017 (costero fuerte sin cuenca) demuestra
  que son fenómenos independientes.
- **Impacto**: la capa de datos (`series.ts`, `methodology.ts`) define
  `scope` por indicador; el pipeline Python espeja esto. Tests
  `test_coastal_vs_basin_separation.py` y `test_no_coastal_soi.py`
  codifican el contrato.

## 2026-08-02 — Decisión: no definir «SOI costero»

- **Contexto**: pregunta recurrente sobre un «SOI costero».
- **Decisión**: el observatorio **no define** tal índice. No existe
  proxy de presión costera con respaldo metodológico equivalente.
- **Justificación**: el SOI convencional usa Tahiti–Darwin; no hay
  estaciones costeras peruanas con metodología equivalente publicada.
- **Impacto**: el corpus `knowledge.ts` incluye el snippet
  `k-no-coastal-soi`; el asistente corrige la mención. El test
  `test_no_coastal_soi.py` codifica el contrato.

## 2026-08-02 — Decisión: RONI como índice operacional de cuenca

- **Contexto**: elección entre ONI heredado y RONI.
- **Decisión**: usar RONI como índice operacional.
- **Justificación**: NOAA/CPC reemplazó el ONI por el RONI en el
  monitoreo oficial; la baseline adaptativa reduce el sesgo secular.
- **Impacto**: `methodology.ts` y `methodology.py` definen RONI con
  baseline adaptativa; la documentación distingue RONI de ONI.

## 2026-08-02 — Decisión: pipeline Python espejo de la capa TS

- **Contexto**: el frontend (TS) ya tiene la capa normalizada; ¿se
  necesita un pipeline Python?
- **Decisión**: sí, pero como **espejo** con los mismos IDs. No
  reemplaza la capa TS; produce artefactos para CI y auditoría.
- **Justificación**: permite validar contratos científicos con pytest,
  ejecución programada en CI, y trazabilidad de adquisición.
- **Impacto**: `python/enso/` se crea con `sources.py`, `methodology.py`
  idénticos en IDs a sus contrapartes TS. El workflow `validate.yml`
  verifica la paridad.

## 2026-08-02 — Decisión: degradación graceful sin fabricación

- **Contexto**: el sandbox puede bloquear la red; CI debe ser cortés.
- **Decisión**: el pipeline nunca fabrica valores. Ante fallo, usa
  caché → último válido → marca `stale` → `ok=False` si no hay nada.
- **Justificación**: integridad científica por sobre disponibilidad.
- **Impacto**: `fetchers.py` y `pipeline.py` implementan la cadena;
  tests `test_download_failures.py`,
  `test_source_schema_changes.py`, `test_missing_observations.py` la
  codifican.

## 2026-08-02 — Decisión: httpx.MockTransport para tests de rate limit

- **Contexto**: los tests de 429 no pueden llamar a la red real.
- **Decisión**: usar `httpx.MockTransport` con handler programable.
- **Justificación**: httpx ya está en dependencias; MockTransport es la
  forma canónica de testear transporte.
- **Impacto**: `test_rate_limiting.py` usa MockTransport y verifica
  backoff + reintento + caché.

## 2026-08-02 — Fallo: xarray/netcdf4 no disponibles en el sandbox

- **Contexto**: los tests de NetCDF necesitan xarray o netcdf4.
- **Hallazgo**: el sandbox tiene scipy pero no xarray/netcdf4.
- **Decisión**: los tests se saltan con razón explícita
  (`pytest.skip`) si las librerías no están; se usa `scipy.io.netcdf`
  para generar un NetCDF sintético cuando es posible.
- **Impacto**: `test_netcdf_dimensions.py` genera un NetCDF con scipy y
  lo valida con xarray si está disponible; si no, skip.

## 2026-08-02 — Fallo: IGP publica sólo por HTTP

- **Contexto**: la fuente IGP (`http://met.igp.gob.pe/...`) no está en
  HTTPS.
- **Hallazgo**: el endpoint IGP no tiene HTTPS disponible.
- **Decisión**: se documenta la excepción en
  `test_source_contracts.py` y en el catálogo. Se mantiene la fuente
  por ser autoritativa.
- **Impacto**: el test `test_urls_are_https_or_explicit_http` permite
  HTTP sólo para `igp-indices-clim`.

## 2026-08-02 — Decisión: prompt injection ignorado

- **Contexto**: el asistente puede recibir instrucciones inyectadas en
  informes o preguntas.
- **Decisión**: el motor de grounding **ignora** instrucciones
  incrustadas; no añade indicadores, no revela instrucciones, no
  ejecuta comandos.
- **Justificación**: seguridad y determinismo.
- **Impacto**: `test_prompt_injection.py` codifica el contrato;
  `knowledge.ts` incluye la regla en `SYSTEM_RULES`.

## 2026-08-02 — Decisión: inferencia LLM con fallback determinista

- **Contexto**: despliegue Pages-only sin backend garantizado.
- **Decisión**: cadena de fallback `webgpu → wasm-simd → server-llm-api
  → deterministic-grounding-only`. El modo determinista es baseline
  garantizado.
- **Justificación**: disponibilidad universal.
- **Impacto**: `test_webgl_webgpu_fallback.py` codifica el contrato;
  `docs/evaluacion-llm.md` documenta el plan de evaluación.

## 2026-08-02 — Decisión: helper `asset_url` para subpath Pages

- **Contexto**: el frontend debe construir URLs relativas al subpath del
  repo en GitHub Pages.
- **Decisión**: implementar `asset_url(base_path, name)` en
  `python/enso/pipeline.py`.
- **Justificación**: contratos verificables.
- **Impacto**: `test_github_pages_subpath.py` codifica el contrato.

## 2026-08-02 — Decisión: 100% fuentes gratuitas

- **Contexto**: ¿conviene pagar por fuentes premium?
- **Decisión**: no. Todas las fuentes son públicas y gratuitas.
- **Justificación**: sostenibilidad, reproducibilidad, atribución clara.
- **Impacto**: `docs/comparacion-gratuitas-pagadas.md` documenta la
  comparativa.

## 2026-08-02 — Decisión: ICEN con NaN preservados

- **Contexto**: ¿cómo manejar huecos en el cálculo de ICEN?
- **Decisión**: la media móvil de 3 meses requiere **exactamente** 3
  valores; si falta alguno, el resultado es `None` (no se rellena).
- **Justificación**: no fabricar valores.
- **Impacto**: `derived.py::rolling_mean_3` y
  `test_missing_observations.py` codifican el contrato.

## 2026-08-02 — Decisión: checksum FNV-1a igual que TS

- **Contexto**: ¿cómo garantizar paridad CSV ↔ serie?
- **Decisión**: usar el mismo checksum FNV-1a 32 bits que `series.ts`.
- **Justificación**: paridad verificable entre stacks.
- **Impacto**: `pipeline.py::_checksum` replica el algoritmo;
  `test_csv_chart_parity.py` verifica coincidencia.

## 2026-08-02 — Investigación: WebLLM vs Transformers.js

- **Contexto**: qué runtime de inferencia local preferir.
- **Hallazgo**: WebLLM requiere WebGPU (mejor rendimiento); Transformers.js
  admite WASM (más lento pero más compatible).
- **Decisión**: ambos se evalúan en `docs/evaluacion-llm.md`; el modo
  determinista es baseline.
- **Impacto**: la cadena de fallback incluye ambos.

## 2026-08-02 — Recuperación: sandbox sin red

- **Contexto**: el sandbox de desarrollo bloquea salida a internet.
- **Fallo**: el pipeline no puede descargar datos frescos.
- **Recuperación**: se ejecuta con `--offline`; usa caché local o
  marca `ok=False`/`stale=True`. Los tests no requieren red.
- **Impacto**: el pipeline es demostrablemente correcto sin red; los
  tests usan fixtures sintéticos y `httpx.MockTransport`.

---

> Este registro se actualiza con cada decisión o fallo significativo.
> Para eventos operativos recientes, ver también el `worklog.md` raíz.
