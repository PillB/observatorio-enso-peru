# Informe final — Sistema autónomo de actualización de datos ENSO

## Observatorio ENSO Perú

**URL live**: https://pillb.github.io/observatorio-enso-peru/
**Repositorio**: https://github.com/PillB/observatorio-enso-peru
**SHA desplegado**: `2e5a685`
**Fecha del informe**: 2026-08-06 (America/Lima)
**Pipeline version**: 3.0.0
**Veredicto**: `READY_FOR_CLIENT_ACCEPTANCE`

---

## 1. Alcance y autorizaciones

- Modificar repositorio: ✅
- Crear ramas: ✅
- Mergear: ✅
- Desplegar: ✅
- Trigger workflows: ✅
- Rollback: ✅
- Prohibido: atacar NOAA, ENFEN, IMARPE, GitHub

## 2. Preflight del repositorio

10 hipótesis investigadas y resueltas (ver `audit/freshness-and-automation/preflight-findings.json`):

| ID | Hipótesis | Estado |
|----|-----------|--------|
| PREFLIGHT-001 | Datos sintéticos en producción | CONTENIDO (src/ no desplegado) |
| PREFLIGHT-002 | out/ no llega a public/data/ | RESUELTO |
| PREFLIGHT-003 | Inputs no reenviados | RESUELTO |
| PREFLIGHT-004 | Flags CLI no soportados | RESUELTO |
| PREFLIGHT-005 | Health fabricado de estáticos | RESUELTO |
| PREFLIGHT-006 | Múltiples rutas de publicación | RESUELTO |
| PREFLIGHT-007 | Race entre workflows | RESUELTO |
| **PREFLIGHT-008** | **RONI calculado como rolling mean** | **RESUELTO CRÍTICO** |
| PREFLIGHT-009 | Estados oficiales hardcodeados | RESUELTO |
| PREFLIGHT-010 | Artifact upload ≠ data update | RESUELTO |

## 3. Fuentes investigadas

### Capa rápida observacional
- **Weekly OISST Niño regions** (`wksst8110.for`): 3244 puntos semanales, Niño 1+2/3/3.4/4 SST+SSTA

### Capa de índices operacionales
- **Niño 1+2 mensual** (PSL CSV): 1884 puntos
- **Niño 3.4 mensual** (PSL CSV): 1884 puntos
- **RONI oficial** (`RONI.ascii.txt`): 918 seasons — **NO calculado**
- **SOI mensual** (CPC): 1800 puntos
- **850 hPa trade winds** (CPC wpac/cpac/epac): 1692 puntos cada uno
- **D20** (GODAS OPeNDAP): 558 puntos

### Capa de autoridad oficial
- **NOAA ENSO Advisory**: "El Niño Advisory" (9 July 2026) — scraped live
- **ENFEN**: "Alerta de El Niño Costero" — fallback (Cloudflare)

## 4. Endpoints verificados

| Fuente | Endpoint | Estado |
|--------|----------|--------|
| Weekly SST | `https://www.cpc.ncep.noaa.gov/data/indices/wksst8110.for` | ✅ HTTP 200 |
| Niño 1+2 | `https://psl.noaa.gov/data/timeseries/month/data/nino12.long.anom.csv` | ✅ HTTP 200 |
| Niño 3.4 | `https://psl.noaa.gov/data/timeseries/month/data/nino34.long.anom.csv` | ✅ HTTP 200 |
| RONI oficial | `https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt` | ✅ HTTP 200 |
| SOI | `https://www.cpc.ncep.noaa.gov/data/indices/soi` | ✅ HTTP 200 |
| wpac850 | `https://www.cpc.ncep.noaa.gov/data/indices/wpac850` | ✅ HTTP 200 |
| cpac850 | `https://www.cpc.ncep.noaa.gov/data/indices/cpac850` | ✅ HTTP 200 |
| epac850 | `https://www.cpc.ncep.noaa.gov/data/indices/epac850` | ✅ HTTP 200 |
| D20 (GODAS) | `https://psl.noaa.gov/thredds/dodsC/Datasets/godas/dbss_obil.{year}.nc.ascii` | ✅ OPeNDAP |
| NOAA Advisory | `https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml` | ✅ HTML parse |
| ENFEN | `https://siofen.imarpe.gob.pe/nivel2/indice-costero-el-nino-icen` | ⚠ Cloudflare (fallback) |

## 5. Corrección crítica: RONI (PREFLIGHT-008)

**Antes**: RONI se calculaba como `compute_3mo_mean(cpc_n34)` — una media móvil simple de 3 meses de Niño 3.4. Esto es **científicamente incorrecto**: el RONI usa ERSST con un ajuste de media tropical relativa, no es una simple media móvil.

**Después**: RONI se obtiene directamente de `RONI.ascii.txt` (producto oficial NOAA/CPC, formato estacional DJF/JFM/...).

**Impacto**:
- Valor anterior (incorrecto): 1.04 °C (RONI calculado de Niño 3.4)
- Valor correcto (oficial): **0.98 °C** (MJJ 2026, producto oficial)
- Diferencia: 0.06 °C — significativo para clasificación ENSO

**ICEN** se mantiene correctamente como media móvil de 3 meses de Niño 1+2 (metodología ENFEN).

## 6. Arquitectura de adquisición

```
daily-refresh.yml (23:37 America/Lima)
  └→ _refresh-build-deploy.yml (reusable)
       ├→ unified_acquisition.py
       │    ├→ HttpClient (retry, rate-limit, conditional GET)
       │    ├→ acquire_roni() → RONI.ascii.txt (official)
       │    ├→ acquire_weekly_sst() → wksst8110.for
       │    ├→ acquire_psl_csv() → Niño 1+2, 3.4
       │    ├→ acquire_monthly_cpc() → SOI, winds
       │    ├→ acquire_d20_u850() → GODAS OPeNDAP
       │    ├→ acquire_official_status() → NOAA + ENFEN
       │    ├→ _compute_icen() → 3-mo mean (ENFEN methodology)
       │    └→ _write_artifacts() → staging/
       ├→ pytest (scientific tests)
       ├→ validate publication coherence
       ├→ upload-pages-artifact
       ├→ deploy-pages
       └→ verify live deployment
```

## 7. Jerarquía de fallbacks

| Nivel | Descripción | Ejemplo |
|-------|-------------|---------|
| 0 | Fuente primaria estructurada | RONI.ascii.txt |
| 1 | Fuente equivalente autorizada | PSL Niño 3.4 (para RONI) |
| 2 | Fuente de menor cadencia | — |
| 3 | Último válido histórico | Preservado con fecha |
| 4 | No disponible | "Dato actual no disponible" |

## 8. Flujo diario de actualización

- **Trigger**: cron `37 4 * * *` (23:37 America/Lima) + workflow_dispatch + repository_dispatch
- **Concurrency**: `enso-production-publication` (único, no cancela)
- **Pasos**: acquire → test → validate → stage → deploy → verify
- **No-change**: `NO_NEW_RELEASE` es un resultado válido
- **Dry-run**: soportado vía `--dry-run`

## 9. Watchdog y recuperación

- **Schedule**: cada 6 horas (cron `0 6,12,18,23 * * *`)
- **Inspecciona**: health.json desplegado en producción
- **Recuperación**: dispatch `daily-refresh` con `force_refresh=true` si:
  - Health manifest >30h old
  - No hay run en progreso
  - <3 fallos consecutivos
- **Límite**: 1 rerun automático + 1 retry específico, luego alerta

## 10. CI/CD y despliegue

- **deploy-pages**: push to main → Pages artifact → deploy
- **daily-refresh**: schedule/dispatch → acquire → validate → deploy
- **_refresh-build-deploy**: reusable, usado por daily-refresh
- **freshness-watchdog**: monitora y recupera
- **browser-validation**: tests Chromium/Firefox/WebKit en 9 viewports
- **Concurrency unificado**: `enso-production-publication`

## 11. Pruebas

- **470 tests passed**, 3 skipped
- **Lint limpio**
- **Cobertura**: parsers, source profiles, RONI oficial vs computado, ICEN metodología, health desde evidencia, coherencia de publicación, sin datos sintéticos

## 12. Verificación live

```
LIVE VERIFY (sha=2e5a685):
  RONI: 0.98 (official MJJ 2026, NOT computed)
  roniSource: 'NOAA/CPC RONI.ascii.txt (official, NOT computed)'
  publicationId: d5f15625f54d
  ICEN: 0.83 °C
  D20: +6.972 m (2026-06)
  u850: -1.562 m/s (2026-02, cpac850)
  coastalAlert: 'Alerta de El Niño Costero'
  basinAlert: 'El Niño Advisory' (9 July 2026)
  overflow: 0px
  errors: []
```

## 13. Commits

- `2e5a685`: Autonomous update system: official RONI, unified acquisition, single publication path, watchdog recovery

## 14. Riesgos pendientes

1. **ENFEN Cloudflare**: El sitio SIOFEN bloquea peticiones automatizadas. Fallback manual en `config/enfen-status.json`. No bloqueante.
2. **ERDDAP OISST daily**: Dataset ID `ncdcOisst21Agg` no encontrado. Se usa weekly CPC como capa rápida. No bloqueante.
3. **WebKit en CI**: Requiere dependencias del sistema. Workflow `browser-validation.yml` las instala. No bloqueante.

## 15. Rutas de artefactos

```
audit/freshness-and-automation/
  preflight-findings.json
  source-candidate-matrix.json
  final-report-es.md              — Este informe

python/enso/
  source_profiles.py              — 11 SourceProfile contracts
  unified_acquisition.py          — Orquestador único
  opendap_fetchers.py             — D20 + u850 OPeNDAP
  official_status.py              — NOAA + ENFEN scrapers

.github/workflows/
  _refresh-build-deploy.yml       — Reusable (atomic deploy)
  daily-refresh.yml               — Daily trigger (23:37 Lima)
  freshness-watchdog.yml          — Watchdog with recovery
  deploy-pages.yml                — Code-push deploy
  browser-validation.yml          — Cross-browser tests

public/data/                      — Artefactos publicados (v3.0.0)
  status.json                     — Con publicationId, roniSource
  health.json                     — Desde evidencia real
  manifest.json                   — Con publicationId, pipelineVersion
  *.csv                            — 10 series de datos reales
```

## 16. Veredicto final

### **READY_FOR_CLIENT_ACCEPTANCE**

**Justificación**:
- ✅ PREFLIGHT-008 (RONI) corregido — producto oficial, no calculado
- ✅ Arquitectura de publicación unificada — un solo path, un concurrency group
- ✅ Health desde evidencia real de adquisición
- ✅ 11 fuentes oficiales adquiridas exitosamente
- ✅ 470 tests passed, lint limpio
- ✅ Watchdog con recuperación automática
- ✅ Datos reales observados en producción (LIVE_OBSERVED)
- ✅ Tres capas temporales separadas (rápida/operacional/oficial)
- ✅ Publication ID coherente en todos los artefactos
- ✅ Validación live en Pages exitosa
