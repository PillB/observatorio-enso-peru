# Evaluación ejecutiva y técnica — automatización ENSO

**Fecha de corte:** 7 de agosto de 2026

**Rama local:** `codex/enso-reliability-round4`

**Producción evaluada:** `https://pillb.github.io/observatorio-enso-peru/`
**Veredicto:** `PARTIALLY_IMPLEMENTED`

## 1. Blurb para la Vicepresidencia

Sí, es técnicamente viable obtener información más frecuente que la mensual, pero no para todos los indicadores con la misma cadencia. NOAA/NCEI ofrece TSM diaria OISST; NOAA/CPC publica TSM semanal de Niño 1+2 y Niño 3.4; IMARPE emite boletines costeros diarios y semanales; y TAO/TRITON aporta observaciones diarias de viento superficial y profundidad de la isoterma de 20 °C. La automatización usa ERDDAP, archivos ASCII/CSV, APIs WordPress y, cuando no existe una interfaz estructurada, descubrimiento y extracción defensiva de PDF. La mejora está implementada y probada en una rama local, pero aún no está desplegada. El principal riesgo pendiente es validar la ejecución completa en GitHub Actions y Pages.

## 2. Informe ejecutivo de una página

### Conclusión ejecutiva

El observatorio sí puede incorporar información más reciente que los reportes mensuales. La disponibilidad, sin embargo, depende de la naturaleza de cada variable. La TSM admite observaciones diarias y semanales; D20 y viento cuentan con observaciones diarias de estaciones TAO/TRITON, pero estas no son sustitutos científicos de los índices regionales mensuales; SOI y RONI conservan su cadencia operacional mensual; y los estados oficiales cambian únicamente cuando NOAA/CPC o ENFEN publican un nuevo pronunciamiento.

### Qué información puede actualizarse con mayor frecuencia

| Variable | Mejor cadencia verificada | Fuente preferida | Técnica | Estado actual del repositorio |
|---|---:|---|---|---|
| TSM Niño 1+2 / 3.4 rápida | Diaria, preliminar | NOAA/NCEI OISST v2.1 | ERDDAP `griddap`, subconjunto regional | Implementada localmente; no desplegada |
| TSM Niño 1+2 / 3.4 publicada | Semanal | NOAA/CPC OISST | ASCII de ancho fijo | Implementada; producción aún usa snapshot anterior |
| TSM litoral peruano | Diaria / semanal, cuando IMARPE publica | BDO / BS‑TLP de IMARPE | Índice oficial → PDF → texto nativo | Adaptador local; acceso SIOFEN bloqueado desde este entorno |
| D20 | Diaria por estación; mensual regional | PMEL TAO / GODAS | ERDDAP / OPeNDAP | PMEL local; GODAS existente |
| Viento | Diario superficial por estación; mensual a 850 hPa | PMEL TAO / CPC | ERDDAP / ASCII | PMEL local; CPC existente |
| SOI | Mensual | NOAA/CPC | ASCII, sección estandarizada | Corregido localmente |
| RONI | Mensual, media móvil trimestral oficial | NOAA/CPC | ASCII directo | Implementado |
| ICEN | Según publicación ENFEN | ENFEN/IMARPE | WordPress → informe PDF con evidencia | Derivación local incorrecta retirada; extracción directa aún puede quedar sin valor |
| Estado oficial costero | Por comunicado | ENFEN | API WordPress; PDF como respaldo | Implementado localmente |
| Estado oficial de cuenca | Mensual | NOAA/CPC | HTML oficial | Implementado |

### Cómo se automatiza

La arquitectura separa tres capas: observaciones rápidas para conciencia situacional; índices operacionales con su metodología propia; y clasificaciones oficiales. Cada adquisición valida HTTPS, dominio final, tamaño, MIME, firma de archivo, esquema, unidades, fecha, región y checksum. Los reintentos son finitos, con backoff y `Retry-After`; un fallo conserva el último registro histórico, pero suprime cualquier afirmación de actualidad. Para documentos, la ruta es texto nativo, extracción determinista, OCR bajo revisión y LLM solo como último recurso sin publicación automática de cifras críticas.

### Situación actual del repositorio

La rama local incorpora OISST diario, PMEL diario, descubrimiento WordPress ENFEN, validación PDF, BDO/BS‑TLP, frescura por fuente, ledger de adquisición, publicación coherente y supresión del ICEN fabricado. Pasan **558 pruebas; 2 se omiten por dependencias opcionales**. El sitio público, en cambio, continúa en el snapshot anterior: muestra ENFEN como fallback de mayo de 2026, ICEN estimado `+0,83 °C`, TSM mensual de mayo y no muestra OISST diario.

### Principales brechas

Faltan ejecutar GitHub Actions con acceso real, revisar el PDF ENFEN actual, validar el despliegue y confirmar navegación móvil real. SIOFEN presentó 403/Cloudflare y DSpace devolvió una página HTML de error con estado aparente 200 en este entorno; ambos casos quedan detectados, no eludidos. Las grillas OISST todavía no alimentan un mapa real: el código local retira el mapa sintético hasta disponer de una grilla coherente.

### Arquitectura recomendada

Usar GitHub Actions y Pages para artefactos compactos, conservar historia normalizada y evidencia en artefactos/ramas de datos, y reservar almacenamiento externo para grillas grandes. Una sola promoción atómica debe generar `publicationId`, `sourceSnapshotId`, versión de esquema, SHA y políticas en todos los JSON.

### Nivel de confianza y siguientes pasos

Confianza alta en NOAA OISST/CPC y WordPress ENFEN; media en PMEL por latencia variable; media-baja en SIOFEN por bloqueo operacional. Siguiente paso: ejecutar la rama en CI, revisar hallazgos, desplegar mediante PR autorizado y validar SHA/publicación, móvil, descargas, consola y red. Hasta entonces no corresponde afirmar automatización completa.

## 3. Matriz de fuentes y cadencias

| Fuente | Producto / rol | Último período probado | Acceso | Selección | Limitación |
|---|---|---|---|---|---|
| NOAA/NCEI OISST preliminar | TSM/anomalía diaria, 0,25° | 2026-08-06 | ERDDAP CSV | PRIMARY rápida | Preliminar; climatología 1971–2000 |
| NOAA/NCEI OISST final | TSM/anomalía diaria, 0,25° | 2026-07-22 | ERDDAP CSV | EQUIVALENT_FALLBACK | Rezago de control de calidad |
| NOAA/CPC `wksst9120.for` | Niño 1+2 y 3.4 semanal | 2026-07-29 | ASCII | LOWER_CADENCE_FALLBACK | No sustituye ICEN/RONI |
| IMARPE BDO | Rango TSM de estaciones costeras | válido 2026-07-07 | PDF oficial | DOCUMENT_FALLBACK | Índice bloqueado por Cloudflare aquí |
| IMARPE BS‑TLP | TSM litoral semanal | edición 23, 2026-06-10 | PDF oficial | DOCUMENT_FALLBACK | Descubrimiento menos estable |
| PMEL `pmelTaoDyIso` | D20 diario por estación | 2026-07-02/03 | ERDDAP CSV | CORROBORATION_ONLY | Cobertura cambiante; no es promedio GODAS |
| PMEL `pmelTaoDyW` | Viento superficial diario | catálogo hasta 2026-07-03 | ERDDAP CSV | CORROBORATION_ONLY | No equivale a 850 hPa |
| CPC RONI | Índice relativo oficial | MJJ 2026: 0,98 °C | ASCII | PRIMARY | Cadencia mensual; revisable |
| CPC SOI | SOI estandarizado | 2026-07: −2,4 | ASCII | PRIMARY | Archivo contiene dos secciones; ya se selecciona la estandarizada |
| CPC `cpac850` | Viento real 850 hPa | 2026-07: −2,4 m/s | ASCII | PRIMARY | No es anomalía |
| ENFEN WordPress | Estado oficial costero | 2026-07-17, comunicado 13 | JSON REST | PRIMARY | Filtrar noticias de la categoría |
| ENFEN PDF | ICEN/estado con página | según informe | PDF | DOCUMENT_FALLBACK | Publicar ICEN solo si valor, unidad y período son explícitos |
| NOAA ENSO Discussion | Estado oficial de cuenca | 2026-07-09 | HTML | PRIMARY | Próxima emisión programada por la autoridad |

## 4. Matriz de implementación actual

| Capacidad | Estado | Evidencia |
|---|---|---|
| OISST diario | `IMPLEMENTED_NOT_LIVE_VERIFIED` | `python/enso/rapid_sources.py`; pruebas y respuesta real analizada |
| Niño semanal | `IMPLEMENTED_AND_LIVE_VERIFIED` | parser CPC; producción tiene artefacto semanal |
| BDO / BS‑TLP | `PARTIALLY_IMPLEMENTED` | `document_sources.py`; descubrimiento/PDF probado con fixtures; red SIOFEN bloqueada |
| ENFEN directo | `IMPLEMENTED_NOT_LIVE_VERIFIED` | selección semántica entre 10 posts y evidencia de comunicado 13 |
| RONI | `IMPLEMENTED_AND_LIVE_VERIFIED` | producto directo; MJJ 0,98 |
| SOI | `IMPLEMENTED_NOT_LIVE_VERIFIED` | parser de sección estandarizada y negativos concatenados |
| Viento CPC / PMEL | `PARTIALLY_IMPLEMENTED` | CPC operacional; PMEL de corroboración local |
| D20 GODAS / PMEL | `PARTIALLY_IMPLEMENTED` | GODAS mensual; PMEL estación local |
| ICEN | `PARTIALLY_IMPLEMENTED` | derivación incorrecta retirada; publicación directa puede quedar no disponible |
| Reintentos, tamaño, MIME, dominio | `IMPLEMENTED_NOT_LIVE_VERIFIED` | clientes y pruebas de fallos |
| Frescura por fuente / supresión stale | `IMPLEMENTED_NOT_LIVE_VERIFIED` | perfiles, `health.json`, frontend `Dato actual no disponible` |
| Ledger y coherencia de publicación | `IMPLEMENTED_NOT_LIVE_VERIFIED` | `acquisition-ledger.json`, IDs/hash comunes, validador |
| Watchdog / Pages atómico | `IMPLEMENTED_NOT_LIVE_VERIFIED` | workflows locales; no se ejecutaron remotamente |
| Mapas reales OISST | `NOT_IMPLEMENTED` | mapa sintético retirado; falta publicar celdas reales |
| CSV / chat / tarjetas | `PARTIALLY_IMPLEMENTED` | consumo canónico mejorado; falta despliegue y prueba live |

## 5. Brechas confirmadas e hipótesis H1–H10

| Hipótesis | Resultado | Evidencia |
|---|---|---|
| H1 Fetcher resiliente | `PARTIALLY_CONFIRMED` | `fetchers.py` y `defensive_acquisition.py` contienen ETag, cache, backoff, jitter, hash y fallback; el orquestador unificado aún no reutiliza toda la cache condicional |
| H2 inputs no llegan | `REJECTED` | `_refresh-build-deploy.yml` mapea inputs |
| H3 CLI sin opciones | `REJECTED` | CLI soporta source, force, dry-run y directorios; `force` aún no cambia toda la estrategia de cache |
| H4 salida distinta de Pages | `REJECTED` | staging se promueve a `public/data` |
| H5 ICEN rolling simple | `CONFIRMED` en producción; corregido localmente | `_compute_icen` eliminado; `icen.csv` obsoleto se retira |
| H6 RONI rolling simple | `REJECTED` | descarga directa `RONI.ascii.txt` |
| H7 alerta costera hardcodeada | `PARTIALLY_CONFIRMED` en producción | producción usa fallback; rama usa WordPress estructurado |
| H8 watchdog solo edad global | `PARTIALLY_CONFIRMED` | workflow mejorado, pendiente ejecución remota |
| H9 recuperación suprimida | `REJECTED` localmente | fallos críticos ya no usan supresión |
| H10 monitor solo registry | `REJECTED` localmente | canarios OISST, CPC, PMEL, ENFEN y SIOFEN hacen probes acotados |

## 6. Recomendación de arquitectura

Opción A — construir todo el artefacto Pages desde fuentes vivas: simple, pero reproduce menos historia y puede agotar tiempo de ejecución. Opción B — persistir historia compacta y evidencia, luego construir Pages: mejor rollback y reproducibilidad. Opción C — grillas grandes en almacenamiento externo y resúmenes en Pages: evita crecimiento del repositorio. Se recomienda **B+C**: índices, salud y evidencia compactos en Git/artefactos; grillas inmutables fuera del repositorio; un único build de Pages.

## 7. Capacidades que se preservan

Se conservan los perfiles de fuente, reintentos acotados, backoff/jitter, `Retry-After`, circuit breaker, ETag/Last‑Modified, cache atómica, SHA‑256, validación de contenido y último válido. Las correcciones son incrementales: selección SOI, límites de documentos, fuentes rápidas y coherencia de publicación.

## 8. Adaptadores y fallbacks

Cada métrica sigue `PRIMARY → equivalente autoritativo → misma métrica de menor cadencia → último válido fechado → UNAVAILABLE`. OISST preliminar reconcilia con OISST final y CPC semanal. RONI no cae a Niño 3.4; ICEN no cae a una media móvil del proyecto; PMEL no reemplaza GODAS/CPC; BDO/BS‑TLP permanecen contexto costero documental.

## 9. Frescura y datos vencidos

Se almacenan `retrievedAt`, `sourcePublishedAt`, `validPeriodEnd`, cadencia, latencia, SLO, umbral y revisión. `STALE` conserva el valor histórico, pero entrega `value=null` al estado actual. OISST preliminar puede mostrarse como `PRELIMINARY`; un comunicado mensual no vence por una corrida diaria sin cambios.

## 10. GitHub Actions y Pages

Flujo canónico: adquirir → validar → staging → IDs coherentes → pruebas → validador → artefacto Pages → despliegue → lectura live de `health.json`. Sigue pendiente reutilizar plenamente la cache condicional en el orquestador y emitir `NO_NEW_SOURCE_RELEASE` sin despliegue innecesario.

## 11. Parsing y sanitización

Los PDF requieren dominio permitido, HTTPS, MIME, `%PDF`, EOF, tamaño máximo, apertura completa y texto por página. HTML elimina `script/style`; JSON se valida estructuralmente; CSV verifica encabezados/unidades/duplicados/fechas; fórmulas no llegan a CSV públicos. OCR y LLM quedan en cuarentena y requieren corroboración humana/determinista.

## 12. Pruebas y puertas de fiabilidad

Resultado: **558 passed, 2 skipped**. Incluye 304, 429, `Retry‑After`, 4xx/5xx, timeout, MIME, tamaño, deriva, unidades, fechas futuras, duplicados, fallback, stale, coherencia, CLI, workflows, OISST, PMEL, WordPress, PDF, BDO y móvil estático. La prueba visual live de escritorio confirmó ausencia de overflow horizontal a 1363 px. La ejecución real a 390/320 px quedó bloqueada por falta de control de viewport en el navegador disponible; se añadieron `viewport-fit=cover` y objetivos táctiles de 44 px, pero requieren verificación posterior.

## 13. Correcciones implementadas

- OISST diario final/preliminar con promedio coseno-latitudinal y hash de esquema.
- PMEL D20/viento diario como corroboración con estaciones y calidad explícitas.
- ENFEN: selección del último **comunicado oficial**, no del último post genérico.
- PDF ENFEN y boletines IMARPE con evidencia por página y cuarentena.
- ICEN derivado retirado; SOI estandarizado sin duplicados; negativos CPC reparados.
- Ledger, snapshot hash, versiones y SHA en los artefactos.
- Descargas filtradas por manifiesto; mapa sintético suprimido.
- Ajustes móviles de safe area y objetivos táctiles.

## 14. Commits, PR y despliegue

No se creó commit, PR ni despliegue. `gh` no está disponible y no se pudo establecer autorización para push, revisión, merge, workflow dispatch, producción o rollback. El trabajo permanece sin commit en `codex/enso-reliability-round4` sobre `818a4706`.

## 15. Validación live

La producción carga sin error de aplicación ni overflow horizontal en escritorio. Sigue mostrando snapshot 3.0: ENFEN fallback 2026‑05, ICEN estimado `+0,83 °C`, Niño 1+2/3.4 de mayo, RONI 0,98 y sin observaciones rápidas. El único error de consola observado provino de una extensión del navegador, no del sitio. Por tanto, las correcciones locales **no están live**.

## 16. Riesgos restantes

1. Ejecutar adquisición completa dentro del presupuesto de 30 minutos.
2. Persistir cache condicional entre corridas y evitar publicaciones sin novedad.
3. Resolver acceso lícito/estable a SIOFEN sin eludir Cloudflare.
4. Validar el PDF ENFEN actual y la metodología/climatología ICEN exacta.
5. Publicar una grilla OISST real para mapas.
6. Validar iPhone 13 e iPod touch con navegador real, incluida cache de usuario recurrente.
7. Completar revisión, merge, despliegue y rollback autorizado.

## 17. Veredicto final

**PARTIALLY_IMPLEMENTED** — la arquitectura y los adaptadores principales están implementados y probados localmente, pero no existe evidencia de CI/CD ni despliegue live de esta rama. No se cumple `FULLY_IMPLEMENTED_AND_LIVE_VERIFIED`.
