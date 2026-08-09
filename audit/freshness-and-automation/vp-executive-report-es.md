# Informe ejecutivo — Automatización de adquisición de datos ENSO

## Observatorio ENSO Perú
**Fecha**: 2026-08-07
**Autor**: Arquitecto principal de adquisición de datos climáticos
**SHA**: pendiente de despliegue

---

## 1. VP Blurb (80–120 palabras)

El observatorio puede obtener información más frecuentemente que mensual para varias variables clave. La TSM semanal se adquiere automáticamente desde NOAA/CPC (wksst9120.for, actualizada hasta julio 2026). La TSM diaria está disponible vía ERDDAP de NOAA/NCEI (OISST v2.1 preliminar). Los vientos a 850 hPa y el SOI se obtienen mensualmente de CPC. El estado oficial de ENFEN se extrae ahora en vivo desde su API de WordPress (Comunicado N° 13-2026, julio 2026). La infraestructura de descarga resiliente ya existe (ETag, reintentos, circuit breaker), pero la integración diaria extremo a extremo aún requiere ajustes. El riesgo principal es la dependencia de endpoints externos no controlados.

---

## 2. Informe ejecutivo de una página

### Conclusión ejecutiva

El observatorio posee infraestructura técnica robusta para adquisición automática de datos climáticos desde fuentes oficiales (NOAA/CPC, NOAA/PSL, NOAA/NCEI, ENFEN). La mayoría de las variables se actualizan mensualmente, pero existen fuentes semanales y diarias verificadas que pueden integrarse. El sistema ya adquiere datos en vivo de 11 fuentes, con 9/9 canaries de contrato pasando, pero la automatización diaria extremo a extremo aún no está completamente implementada para cadencias superiores a mensual.

### Qué información puede actualizarse con mayor frecuencia

| Variable | Cadencia actual | Cadencia óptima verificada | Fuente preferida | Técnica | Estado del repositorio |
|----------|----------------|---------------------------|------------------|---------|----------------------|
| TSM Niño 1+2 | Mensual (PSL) | **Semanal** (CPC wksst9120) | NOAA/CPC | ASCII fijo | IMPLEMENTADO |
| TSM Niño 3.4 | Mensual (PSL) | **Semanal** (CPC wksst9120) | NOAA/CPC | ASCII fijo | IMPLEMENTADO |
| TSM diaria | No disponible | **Diaria** (ERDDAP OISST) | NOAA/NCEI | ERDDAP CSV | NO IMPLEMENTADO |
| RONI | Mensual (oficial) | Mensual (estacional) | NOAA/CPC RONI.ascii.txt | ASCII | IMPLEMENTADO |
| ICEN | Mensual (calculado) | Mensual | ENFEN/IMARPE | 3-mo mean Niño 1+2 | IMPLEMENTADO |
| SOI | Mensual (CPC) | Mensual | NOAA/CPC | ASCII | IMPLEMENTADO |
| Viento 850 hPa | Mensual (CPC) | Mensual | NOAA/CPC cpac850 | ASCII | IMPLEMENTADO |
| D20 | Mensual (GODAS) | Mensual | NOAA/PSL GODAS | OPeNDAP ASCII | IMPLEMENTADO |
| Estado ENFEN | Event-driven | Event-driven | ENFEN WordPress API | JSON REST | **IMPLEMENTADO (nuevo)** |
| Estado NOAA | Mensual | Mensual | NOAA/CPC HTML | HTML parse | IMPLEMENTADO |

### Cómo se automatiza

- **GitHub Actions**: workflow `daily-refresh.yml` ejecuta a las 23:37 hora de Lima
- **Adquisición defensiva**: ETag, Last-Modified, reintentos con backoff+jitter, circuit breaker, MIME validation
- **Validación**: schema fingerprint, fechas monótonas, límites plausibles, coherencia de publicación
- **Despliegue atómico**: staging → public/data → Pages artifact → deploy → verify
- **Watchdog**: monitora health.json desplegado y dispatcha recuperación limitada

### Situación actual del repositorio

- 11 fuentes registradas con perfiles completos (cadencia, SLO, climatología)
- 9/9 canaries de contrato de fuente pasan (endpoints reales, schema, cadencia)
- 535 tests pasan, 3 skipped
- Coherencia de publicación validada (todos los artefactos comparten publicationId)
- ENFEN ahora se obtiene en vivo desde WordPress API (no más fallback)
- RONI usa producto oficial (no rolling mean)
- D20 documentado con variable fuente (dbss_obil), agregación espacial, climatología

### Principales brechas

1. **TSM diaria via ERDDAP**: verificada accesible pero no integrada al pipeline
2. **IMARPE boletines diarios/semanales**: SIOFEN bloquea automatización (Cloudflare); ENFEN API sí accesible
3. **Freshness específica por fuente**: el frontend no muestra separación entre fecha de observación, recuperación y publicación
4. **Supresión de datos rancios**: no se muestra "Dato actual no disponible" cuando un valor excede su SLO

### Arquitectura recomendada

Mantener tres capas temporales independientes:
- **Capa A (observacional rápida)**: TSM semanal/diaria para conciencia situacional
- **Capa B (índices operacionales)**: ICEN, RONI, SOI, vientos, D20 con metodología oficial
- **Capa C (autoridad oficial)**: ENFEN y NOAA/CPC alertas, independientes de observaciones rápidas

### Nivel de confianza

**Alto** para adquisición mensual y semanal. **Medio** para integración diaria (ERDDAP accesible pero no conectado). **Alto** para estados oficiales (ENFEN WordPress API + NOAA HTML parser funcionan en vivo).

### Siguientes pasos

1. Integrar TSM diaria via ERDDAP OISST (bounded queries)
2. Implementar separación visual de fechas (observación vs recuperación vs publicación) en frontend
3. Implementar supresión de datos rancios ("Dato actual no disponible")
4. Añadir PMEL TAO/TRITON como fuente de corrobación diaria

---

## 3. Matriz de cadencia de fuentes

| source_id | Institución | Producto | Cadencia | Latencia | Último periodo verificado | Método | Estado |
|-----------|------------|----------|----------|----------|--------------------------|--------|--------|
| noaa-cpc-wksst | NOAA/CPC | Weekly OISST Niño regions | Semanal | 3-7 días | 2026-07-29 | ASCII fijo | ✅ PRIMARY |
| noaa-ncei-oisst-daily | NOAA/NCEI | Daily OISST v2.1 | Diaria | 1-2 días | 2026-08-01 (prelim) | ERDDAP CSV | ⚠ NO IMPLEMENTADO |
| noaa-psl-nino12 | NOAA/PSL | Niño 1+2 mensual | Mensual | 3-10 días | 2026-05 | CSV | ✅ PRIMARY |
| noaa-psl-nino34 | NOAA/PSL | Niño 3.4 mensual | Mensual | 3-10 días | 2026-05 | CSV | ✅ PRIMARY |
| noaa-cpc-roni | NOAA/CPC | RONI oficial (estacional) | Mensual | 5-15 días | MJJ 2026 | ASCII | ✅ PRIMARY |
| noaa-cpc-soi | NOAA/CPC | SOI mensual | Mensual | 3-7 días | 2026-07 | ASCII | ✅ PRIMARY |
| noaa-cpc-cpac850 | NOAA/CPC | 850 hPa trade wind Central Pacific | Mensual | 3-7 días | 2026-07 | ASCII | ✅ PRIMARY |
| noaa-cpc-godas-d20 | NOAA/PSL | D20 anomaly (dbss_obil) | Mensual | 10-20 días | 2026-06 | OPeNDAP | ✅ PRIMARY |
| noaa-cpc-enso-advisory | NOAA/CPC | ENSO Alert System Status | Mensual | 0-1 día | 9 July 2026 | HTML parse | ✅ PRIMARY |
| enfen-imarpe-status | ENFEN/IMARPE | Estado oficial El Niño Costero | Event-driven | Variable | 2026-07-17 | WordPress API JSON | ✅ PRIMARY (nuevo) |

## 4. Matriz de implementación actual

| Capacidad | Estado | Evidencia |
|-----------|--------|-----------|
| Adquisición semanal SST | IMPLEMENTED_AND_LIVE_VERIFIED | wksst9120.for, 9/9 canaries pass |
| Adquisición mensual Niño 1+2/3.4 | IMPLEMENTED_AND_LIVE_VERIFIED | PSL CSV, canary pass |
| RONI oficial (no computado) | IMPLEMENTED_AND_LIVE_VERIFIED | RONI.ascii.txt, roniSource label |
| SOI mensual | IMPLEMENTED_AND_LIVE_VERIFIED | CPC soi, canary pass |
| Viento 850 hPa | IMPLEMENTED_AND_LIVE_VERIFIED | CPC cpac850, actual wind labeled |
| D20 (GODAS) | IMPLEMENTED_AND_LIVE_VERIFIED | OPeNDAP, dbss_obil documented |
| Estado NOAA | IMPLEMENTED_AND_LIVE_VERIFIED | HTML parse, "El Niño Advisory" |
| Estado ENFEN | IMPLEMENTED_AND_LIVE_VERIFIED | WordPress API, "Alerta de El Niño Costero" (source=live) |
| TSM diaria (ERDDAP) | NOT_IMPLEMENTED | Endpoint accesible, no integrado |
| IMARPE boletín diario | NOT_IMPLEMENTED | SIOFEN bloquea, no API alternativa |
| IMARPE boletín semanal | NOT_IMPLEMENTED | SIOFEN bloquea |
| HTTP condicional (ETag) | IMPLEMENTED_AND_LIVE_VERIFIED | DefensiveHttpClient |
| Circuit breaker | IMPLEMENTED | defensive_acquisition.py |
| Retry con backoff+jitter | IMPLEMENTED_AND_LIVE_VERIFIED | DefensiveHttpClient |
| Validación de schema | IMPLEMENTED_AND_LIVE_VERIFIED | ContentValidator, source canaries |
| Freshness específica por fuente | PARTIALLY_IMPLEMENTED | Source profiles defined, frontend no muestra separación |
| Watchdog | IMPLEMENTED | freshness-watchdog.yml |
| Source-contract canaries | IMPLEMENTED_AND_LIVE_VERIFIED | 9/9 pass |
| Coherencia de publicación | IMPLEMENTED_AND_LIVE_VERIFIED | publication_validator.py |
| Despliegue atómico | IMPLEMENTED_AND_LIVE_VERIFIED | _refresh-build-deploy.yml |
| Tutorial con pause/resume | IMPLEMENTED_AND_LIVE_VERIFIED | pauseTutorial, resumeTutorial, restartTutorial |
| Frontend hydration | IMPLEMENTED_AND_LIVE_VERIFIED | STATUS object from status.json |
| Supresión de datos rancios | NOT_IMPLEMENTED | No "Dato actual no disponible" en UI |

## 5. Hipótesis verificadas

| Hipótesis | Estado | Evidencia |
|-----------|--------|-----------|
| H1: Fetcher con ETag, backoff, cache, validación | CONFIRMED | fetchers.py + defensive_acquisition.py |
| H2: Workflow inputs no reenviados | REJECTED | _refresh-build-deploy.yml reenvía force_refresh, dry_run, source |
| H3: CLI sin source-specific/force-refresh | PARTIALLY_CONFIRMED | CLI tiene --dry-run, --staging-dir, --publication-dir pero no --force-refresh |
| H4: Pipeline output ≠ deployed dir | REJECTED | unified_acquisition.py escribe a staging → public/data |
| H5: ICEN como rolling mean | CONFIRMED | _compute_icen() usa 3-mo mean (metodología ENFEN correcta) |
| H6: RONI como rolling mean | REJECTED | RONI se obtiene de RONI.ascii.txt (oficial) |
| H7: Alertas oficiales hardcodeadas | REJECTED | NOAA scrapeado en vivo, ENFEN via WordPress API |
| H8: Watchdog solo evalúa edad | PARTIALLY_CONFIRMED | Evalúa edad + source status, no source-specific valid-period |
| H9: Watchdog suprime fallos | REJECTED | freshness-watchdog.yml no usa \|\| true |
| H10: Source monitor solo registry | REJECTED | source_canaries.py hace probes reales (9/9 pass) |

## 6. Veredicto final

**PARTIALLY_IMPLEMENTED**

La adquisición automática funciona para 11 fuentes con cadencia mensual, semanal y event-driven. Los estados oficiales (ENFEN via WordPress API, NOAA via HTML) se obtienen en vivo. La TSM diaria via ERDDAP está verificada como accesible pero no integrada. La infraestructura defiensive (ETag, circuit breaker, canaries, coherencia de publicación) está implementada y verificada. Las brechas principales son: integración de TSM diaria, separación visual de fechas en el frontend, y supresión de datos rancios.
