# Pipeline Python — Observatorio ENSO Perú

Adquisición, normalización y emisión de series ENSO (costero y de cuenca)
para el Observatorio ENSO Perú. Espejo de la capa de datos TypeScript
(`src/lib/enso/`) con los mismos identificadores de fuente e indicadores.

## Requisitos

- Python ≥ 3.10
- Dependencias: `httpx`, `pandas`, `pydantic`, `beautifulsoup4`, `xarray`,
  `netcdf4`, `pypdf`, `pytest`, `pytest-asyncio`.

```bash
pip install -r requirements.txt
```

## Estructura

```
python/
├── enso/
│   ├── __init__.py        # Exporta modelos, fuentes, indicadores
│   ├── models.py          # Pydantic: SourceRef, IndicatorDef, Series, …
│   ├── sources.py         # Registro de fuentes (espejo de sources.ts)
│   ├── methodology.py     # Definiciones de indicadores (espejo de methodology.ts)
│   ├── fetchers.py        # Fetcher base + PSL/CPC/ENFEN con reintentos y caché
│   ├── normalize.py       # Conversión de longitud, verificación de signos
│   ├── derived.py         # ICEN, RONI, categorías, percentiles
│   ├── pipeline.py        # Orquestador idempotente
│   └── cli.py             # CLI: fetch / run / validate
├── fixtures/              # Fixtures sintéticos para tests
├── tests/                 # Contratos pytest (TDD)
├── requirements.txt
└── README.md
```

## Uso

### Ejecutar el pipeline completo

```bash
cd python
python -m enso.cli run
```

Produce `python/out/manifest.json`, `python/out/status.json`,
`python/out/sources.json` y un CSV por indicador con cabeceras de
metadatos + checksum.

### Descargar un único indicador

```bash
python -m enso.cli fetch --indicator nino12
python -m enso.cli fetch --indicator icen
```

### Validar artefactos

```bash
python -m enso.cli validate
```

### Modo offline

Sin red, el pipeline usa el caché local y degrada de forma graceful:
nunca fabrica valores, preserva el último conjunto válido y lo marca
como `stale` (obsoleto).

```bash
python -m enso.cli run --offline
```

## Tests

```bash
cd python
python -m pytest -q
```

Los tests son **contratos**: codifican las propiedades requeridas del
pipeline (no fabrication de valores, preservación de NaN, convención de
signos de viento/D20, separación costero/cuenca, no-existencia de
«SOI costero», defensa contra prompt injection, paridad CSV↔serie, etc.).

## Convenciones

- **Longitud**: las conversiones 0..360 ↔ -180..180 son idempotentes;
  270°E ≡ 90°O.
- **Viento zonal a 850 hPa**: u > 0 ⇒ hacia el este (componente del
  oeste / westerly); u < 0 ⇒ hacia el oeste (componente del este /
  easterly). Distinto de superficie (10 m) y del valor observado.
- **D20**: anomalía positiva ⇒ termoclina más profunda; negativa ⇒ más
  somera.
- **NaN**: los huecos se preservan a través del cálculo de ICEN (media
  móvil de 3 meses); nunca se rellenan con valores fabricados.
- **Preliminar vs final**: la marca fluye desde la fuente hasta el CSV y
  el estado consolidado; una revisión actualiza la marca a `final`.

## Degradación y recuperación

Ante fallos de red o de esquema:

1. El fetcher reintenta con backoff exponencial + jitter (hasta
   `max_retries`).
2. Si persiste, devuelve el caché marcado `from_cache=True`.
3. Si no hay caché, el pipeline registra el fallo en el manifiesto y
   preserva el último CSV válido (marcado `stale=True`).
4. Nunca se fabrican valores ausentes.

## Licencia y atribución

Datos de NOAA (dominio público, Gobierno de EE. UU.) y de ENFEN/IMARPE,
SENAMHI, IGP (datos abiertos institucionales, atribución requerida). Ver
`docs/atribucion-licencias.md`.
