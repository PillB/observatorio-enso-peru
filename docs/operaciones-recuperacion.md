# Operaciones y recuperación — Observatorio ENSO Perú

> Formal Spanish. Procedimientos de operación, manejo de fallos de
> fuente, datos obsoletos, preservación del último válido y rollback.

## 1. Modelo operativo

El pipeline Python corre diariamente (13:17 UTC) y produce artefactos
en `python/out/`. El frontend consume estos artefactos (o la capa
normalizada TS). Ante fallos, el sistema degrada de forma graceful:
nunca fabrica valores y preserva el último conjunto válido.

## 2. Ciclo de vida de una corrida

```
[Inicio] → para cada indicador en orden:
            nino12 → nino34 → soi → u850 → d20 → icen → roni
            │
            ├─ fetcher.fetch(allow_network)
            │   ├─ reintenta con backoff exponencial + jitter
            │   ├─ HTTP condicional (ETag / If-Modified-Since)
            │   ├─ valida contenido (SchemaValidationError si no cumple)
            │   └─ escribe caché con SHA-256
            │
            ├─ si fetch OK:
            │   ├─ parsea a MonthlyPoint
            │   ├─ aplica derivaciones (ICEN ← nino12, RONI ← nino34)
            │   ├─ escribe CSV con cabeceras + checksum
            │   └─ guarda último válido
            │
            ├─ si SchemaValidationError:
            │   ├─ NO sobrescribe el caché
            │   ├─ carga último válido
            │   ├─ escribe CSV marcado stale
            │   └─ registra error en manifiesto
            │
            ├─ si FetchError persistente:
            │   ├─ si hay caché: lo usa marcado from_cache=True
            │   ├─ si no hay caché: ok=False, sin serie
            │   ├─ si hay último válido: lo usa marcado stale
            │   └─ registra error en manifiesto
            │
            └─ siguiente indicador
[Fin] → escribe manifest.json + status.json + sources.json
```

## 3. Estados de un indicador en el manifiesto

| `ok` | `stale` | `from_cache` | Significado |
|------|---------|--------------|-------------|
| true | false | false | Fresco: descarga exitosa y validada. |
| true | true | true | Cache: la fuente no respondió pero hay caché local. |
| true | true | false | Stale: fallo de esquema, se preservó el último válido. |
| false | true | false | Fallido sin respaldo: sin red, sin caché, sin último válido. |

## 4. Manejo de fallos por tipo

### 4.1 Timeout / 5xx (transitorio)
- Reintentos con backoff exponencial + jitter (`max_retries=4`).
- Tras agotar reintentos, usa caché si existe; si no, marca `ok=False`.

### 4.2 HTTP 429 (rate limit)
- Backoff con `Retry-After` si está presente; si no, backoff
  exponencial.
- Tras agotar reintentos, usa caché si existe.

### 4.3 HTTP 4xx (cliente, no 429)
- No se reintenta.
- Usa caché si existe; si no, marca `ok=False`.

### 4.4 HTTP 304 (Not Modified)
- Devuelve el caché marcado `from_cache=True` (no es error).

### 4.5 Cambio de esquema
- `SchemaValidationError`: NO se sobrescribe el caché.
- Se carga el último válido y se marca `stale=True`.
- Se registra el fallo en el manifiesto para revisión manual.

### 4.6 Fallo de parseo
- Excepción capturada; se carga el último válido y se marca `stale`.

## 5. Datos obsoletos (stale)

Un indicador se marca `stale=True` si:

- `freshness_hours > STALE_HOURS_THRESHOLD` (72 h), o
- el dato proviene del caché, o
- hubo fallo de esquema/parseo y se preservó el último válido.

El `status.json` incluye un resumen `freshness` con la marca `stale`
visible por indicador. El frontend debe mostrar esta marca al usuario
(p. ej. «Dato preliminar · corte 2026-08-02 · obsoleto»).

## 6. Preservación del último válido

- Ubicación: `python/cache/<indicator>.last_valid.json`.
- Formato: JSON serializado del modelo `Series` (pydantic).
- Se actualiza en cada corrida exitosa.
- Se carga cuando la corrida actual falla.
- El checksum se recalcula al finalizar (defensivo contra placeholders).

## 7. Caché de descargas

- Ubicación: `python/cache/<source_id>.json`.
- Contenido: content (latin-1), ETag, Last-Modified, SHA-256,
  fetched_at, preliminary, notes.
- Se usa para HTTP condicional (If-None-Match / If-Modified-Since).
- NO se sobrescribe ante `SchemaValidationError`.

## 8. Rollback

### 8.1 Rollback de datos

Si una corrida produce datos incorrectos:

1. Revertir el commit en la rama `data` (o en `python/out/`).
2. El pipeline preserva el último válido en `python/cache/`, que se
   reutiliza en la siguiente corrida.
3. Si es necesario, restaurar manualmente el `last_valid.json` desde
   una copia previa.

### 8.2 Rollback de frontend

1. Revertir el commit en `main`.
2. GitHub Actions re-desplegará automáticamente.

### 8.3 Rollback de un indicador específico

Si un único indicador se corrompe:

1. Eliminar `python/cache/<indicator>.last_valid.json`.
2. Eliminar `python/cache/<source_id>.json`.
3. Re-ejecutar el pipeline: intentará descargar fresco; si falla,
   `ok=False` para ese indicador (no afecta a los demás).

## 9. Procedimientos operativos

### 9.1 Verificación diaria

- Revisar el workflow `pipeline` en GitHub Actions.
- Abrir `python/out/manifest.json` y verificar que todos los
  indicadores están `ok=true` o `stale=true` (no `ok=false` sin
  respaldo).
- Si hay `ok=false`: revisar el campo `error` y actuar según §4.

### 9.2 Verificación semanal

- Revisar el workflow `deploy-pages`.
- Verificar que el sitio está accesible.
- Verificar que las descargas CSV funcionan.

### 9.3 Respuesta a cambio de esquema de una fuente

1. El pipeline reporta `SchemaValidationError` en el manifiesto.
2. Investigar el cambio: revisar manualmente el endpoint.
3. Actualizar el fetcher si el cambio es legítimo.
4. Si el cambio es temporal (mantenimiento de la fuente), esperar y
   re-ejecutar; el último válido se preserva mientras tanto.

### 9.4 Respuesta a caída persistente de una fuente

1. El pipeline usa el respaldo declarado (`fallbackSourceId`) sólo si
   se implementa explícitamente; por defecto, preserva el último
   válido.
2. Documentar la caída en `docs/registro-decisiones.md`.
3. Si la caída es definitiva, reemplazar la fuente y actualizar tanto
   `python/enso/sources.py` como `src/lib/enso/sources.ts`.

## 10. Monitoreo y alertas

- GitHub Actions envía notificaciones de fallo al repositorio.
- El `manifest.json` y `status.json` permiten monitoreo programático.
- Se recomienda un check externo que lea `status.json` y alerte si
  algún indicador está `stale > 7 días`.

## 11. Recuperación ante desastre

Si se pierde `python/cache/` y `python/out/`:

1. Re-ejecutar el pipeline: descargará fresco si la red lo permite.
2. Si la red no está disponible, el frontend sigue funcionando con la
   capa normalizada TS (que no depende del pipeline).
3. Los datos históricos pueden regenerarse desde las fuentes públicas.

## 12. Contactos y escalamiento

- **Datos científicos**: revisar `docs/catalogo-fuentes.md` para
  contactar a la institución fuente.
- **Emergencias oficiales**: INDECI, CENEPRED, SENAMHI, ENFEN.
- **El observatorio NO es servicio oficial de alerta**.
