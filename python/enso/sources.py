"""Registro de fuentes — espejo de ``src/lib/enso/sources.ts``.

Mantiene los mismos identificadores y URLs verificadas para que el frontend
y el pipeline Python sean consistentes. NO modificar sin sincronizar ambos.
"""

from __future__ import annotations

from typing import Optional

from .models import SourceRef, SourceStatus

SOURCES: list[SourceRef] = [
    SourceRef(
        id="noaa-cpc-enso-discussion",
        institution="NOAA / Climate Prediction Center (CPC)",
        product="ENSO Diagnostic Discussion — ENSO Alert System",
        url="https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml",
        retrievalDate="2026-07-09",
        format="HTML (informe mensual)",
        updateFrequency="Mensual (segundo jueves)",
        latency="Días",
        license="Dominio público (trabajo del Gobierno de EE. UU.)",
        attribution="NOAA / CPC",
        status=SourceStatus.VERIFIED,
        notes=(
            "Fuente oficial del estado de alerta ENSO de cuenca. La discusión "
            "de julio 2026 indica «El Niño Advisory» vigente. Se extrae el "
            "estado de alerta textual; los valores numéricos provienen de "
            "RONI/Niño 3.4."
        ),
        fallbackSourceId="noaa-cpc-enso-evolution-pdf",
    ),
    SourceRef(
        id="noaa-cpc-reroni",
        institution="NOAA / CPC",
        product="Relative Oceanic Niño Index (RONI) / ONI v5",
        url="https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/",
        retrievalDate="2026-07-09",
        format="HTML + datos tabulares",
        updateFrequency="Mensual",
        latency="Semanas",
        license="Dominio público (Gobierno de EE. UU.)",
        attribution="NOAA / CPC",
        status=SourceStatus.VERIFIED,
        notes=(
            "RONI es el índice operacional actual de NOAA/CPC para monitoreo "
            "y predicción de ENSO; adapta la línea base para reducir el sesgo "
            "por el calentamiento secular de la TSM. Región Niño 3.4 "
            "(5°S–5°N, 120–170°O). No confundir con el ONI heredado basado "
            "en ERSST.v5 con base 1971–2000."
        ),
        fallbackSourceId="noaa-psl-nino34-ersst",
    ),
    SourceRef(
        id="noaa-cpc-enso-evolution-pdf",
        institution="NOAA / CPC",
        product="ENSO: Recent Evolution, Current Status and Predictions (PDF)",
        url="https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/lanina/enso_evolution-status-fcsts-web.pdf",
        retrievalDate="2026-08-02",
        format="PDF semanal",
        updateFrequency="Semanal (lunes)",
        latency="1–2 días",
        license="Dominio público (Gobierno de EE. UU.)",
        attribution="NOAA / CPC",
        status=SourceStatus.VERIFIED,
        notes=(
            "Resumen semanal de evolución y pronóstico ENSO. Respaldado en "
            "la discusión mensual oficial."
        ),
        fallbackSourceId="noaa-cpc-enso-discussion",
    ),
    SourceRef(
        id="noaa-psl-nino34-ersst",
        institution="NOAA / Physical Sciences Laboratory (PSL)",
        product="Niño 3.4 SST Index — ERSST v5",
        url="https://psl.noaa.gov/data/timeseries/month/Nino34_CPC",
        retrievalDate="2026-08-02",
        format="CSV / texto estándar PSL / NetCDF",
        updateFrequency="Mensual",
        latency="Semanas",
        license="Dominio público (Gobierno de EE. UU.)",
        attribution="NOAA / PSL (ERSST v5)",
        status=SourceStatus.VERIFIED,
        notes=(
            "Anomalías de TSM promediadas en Niño 3.4 (5°N–5°S, 170–120°W) "
            "con climatología 1981–2010, mensual desde 1950/01. Serie "
            "histórica para comparación de eventos. La climatología oficial "
            "de NOAA/CPC para ONI usa base móvil de 30 años; PSL publica "
            "base 1981–2010."
        ),
        fallbackSourceId="noaa-psl-nino12-anom",
    ),
    SourceRef(
        id="noaa-psl-nino12-anom",
        institution="NOAA / Physical Sciences Laboratory (PSL)",
        product="Niño 1+2 SST Anomaly (long record)",
        url="https://psl.noaa.gov/data/timeseries/month/data/nino12.long.anom.csv",
        retrievalDate="2026-08-02",
        format="CSV",
        updateFrequency="Mensual",
        latency="Semanas",
        license="Dominio público (Gobierno de EE. Uu.)",
        attribution="NOAA / PSL",
        status=SourceStatus.VERIFIED,
        notes=(
            "Anomalía mensual de TSM en la región Niño 1+2 (0–10°S, "
            "90–80°W), frente a Ecuador y el norte del Perú. Insumo de la "
            "componente costera. Complementa el ICEN de ENFEN."
        ),
        fallbackSourceId="noaa-psl-nino34-ersst",
    ),
    SourceRef(
        id="noaa-psl-soi",
        institution="NOAA / PSL",
        product="Southern Oscillation Index (Tahiti – Darwin)",
        url="https://psl.noaa.gov/data/timeseries/month/data/soi.long.data",
        retrievalDate="2026-08-02",
        format="Texto",
        updateFrequency="Mensual",
        latency="Semanas",
        license="Dominio público (Gobierno de EE. Uu.)",
        attribution="NOAA / PSL (estaciones Tahiti y Darwin)",
        status=SourceStatus.VERIFIED,
        notes=(
            "SOI convencional: anomalía estandarizada de la diferencia de "
            "presión superficial media entre Tahiti y Darwin. Índice de "
            "escala de cuenca. El observatorio NO define un «SOI costero»; "
            "ver metodología."
        ),
        fallbackSourceId="noaa-cpc-enso-discussion",
    ),
    SourceRef(
        id="noaa-cpc-godas",
        institution="NOAA / CPC — Global Ocean Data Assimilation System (GODAS)",
        product="D20 (profundidad de la isoterma de 20 °C) — Pacífico ecuatorial",
        url="https://www.cpc.ncep.noaa.gov/products/GODAS/",
        retrievalDate="2026-08-02",
        format="NetCDF / gráficos",
        updateFrequency="Semanal",
        latency="1–2 semanas",
        license="Dominio público (Gobierno de EE. UU.)",
        attribution="NOAA / CPC (GODAS)",
        status=SourceStatus.VERIFIED,
        notes=(
            "D20 como proxy de la profundidad de la termoclina en el "
            "Pacífico ecuatorial. Anomalía positiva ⇒ termoclina más "
            "profunda (típico de El Niño de cuenca). Se confirma la "
            "convención antes de aplicar."
        ),
        fallbackSourceId="pmel-tao-triton",
    ),
    SourceRef(
        id="noaa-cpc-u850",
        institution="NOAA / CPC — NCEP/NCAR Reanalysis",
        product="Anomalía del viento zonal a 850 hPa — Pacífico ecuatorial",
        url="https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_update/usswanim.shtml",
        retrievalDate="2026-08-02",
        format="HTML / datos derivados",
        updateFrequency="Semanal",
        latency="Días",
        license="Dominio público (Gobierno de EE. UU.)",
        attribution="NOAA / CPC (NCEP/NCAR Reanalysis)",
        status=SourceStatus.VERIFIED,
        notes=(
            "Componente zonal u a 850 hPa. Convención: u > 0 ⇒ flujo hacia "
            "el este (componente del oeste / westerly); u < 0 ⇒ flujo hacia "
            "el oeste (componente del este / easterly). Se distingue valor "
            "observado de anomalía y viento de superficie (10 m) de bajo "
            "nivel (850 hPa)."
        ),
        fallbackSourceId="pmel-tao-triton",
    ),
    SourceRef(
        id="pmel-tao-triton",
        institution="NOAA / PMEL — TAO/TRITON",
        product="Array de boyas ecuatoriales (TSM, viento, subsuperficie)",
        url="https://www.pmel.noaa.gov/tao/drupal/disdel/",
        retrievalDate="2026-08-02",
        format="NetCDF / datos de boya",
        updateFrequency="Diaria (con vacíos)",
        latency="Variable",
        license="Dominio público (Gobierno de EE. UU.)",
        attribution="NOAA / PMEL (TAO/TRITON)",
        status=SourceStatus.VERIFIED,
        notes=(
            "Observaciones in situ. Útil para validación y respaldo. "
            "Cobertura irregular; los huecos se preservan, no se rellenan "
            "con valores fabricados."
        ),
        fallbackSourceId="noaa-cpc-godas",
    ),
    SourceRef(
        id="enfen-imarpe-icen",
        institution="ENFEN / IMARPE (SIOFEN)",
        product="Índice Costero El Niño (ICEN) y estado de alerta costera",
        url="https://siofen.imarpe.gob.pe/nivel2/indice-costero-el-nino-icen",
        retrievalDate="2026-08-02",
        format="HTML / panel",
        updateFrequency="Mensual",
        latency="Semanas",
        license="Datos abiertos institucionales (atribución requerida)",
        attribution="Comisión Multisectorial ENFEN / IMARPE",
        status=SourceStatus.VERIFIED,
        notes=(
            "ICEN = media móvil de 3 meses de las anomalías mensuales de "
            "TSM en Niño 1+2 (90–80°O, 10°S–0°). Estado «Alerta de El Niño "
            "Costero» activo desde el 13 de febrero de 2026. La "
            "categorización por intensidad reproduce la metodología ENFEN "
            "documentada; cualquier duda se remite a la publicación oficial."
        ),
        fallbackSourceId="senamhi-fenomeno-el-nino",
    ),
    SourceRef(
        id="senamhi-fenomeno-el-nino",
        institution="SENAMHI Perú",
        product="Seguimiento del Fenómeno El Niño",
        url="https://www.senamhi.gob.pe/?p=fenomeno-el-nino",
        retrievalDate="2026-08-02",
        format="HTML",
        updateFrequency="Variable",
        latency="Días a semanas",
        license="Datos abiertos institucionales (atribución requerida)",
        attribution="SENAMHI Perú",
        status=SourceStatus.VERIFIED,
        notes=(
            "Divulgación oficial peruana del estado ENFEN y contexto "
            "regional. Respaldado por ENFEN/IMARPE."
        ),
        fallbackSourceId="enfen-imarpe-icen",
    ),
    SourceRef(
        id="igp-indices-clim",
        institution="Instituto Geofísico del Perú (IGP)",
        product="Índices climáticos (ENFEN, IGP)",
        url="http://met.igp.gob.pe/variabclim/indices.html",
        retrievalDate="2026-08-02",
        format="HTML",
        updateFrequency="Variable",
        latency="Variable",
        license="Datos abiertos institucionales (atribución requerida)",
        attribution="IGP Perú",
        status=SourceStatus.VERIFIED,
        notes=(
            "Validación cruzada de índices costeros y pronósticos "
            "estacionales para Perú."
        ),
        fallbackSourceId="enfen-imarpe-icen",
    ),
]


SOURCE_BY_ID: dict[str, SourceRef] = {s.id: s for s in SOURCES}


def get_source(source_id: str) -> Optional[SourceRef]:
    """Devuelve la fuente con el identificador dado, o ``None``."""
    return SOURCE_BY_ID.get(source_id)
