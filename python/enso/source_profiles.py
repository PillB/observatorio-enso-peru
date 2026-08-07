"""Perfil de fuentes y registro de cadencias para el Observatorio ENSO Perú.

Define SourceProfile para cada fuente oficial, con metadatos de cadencia,
ventana de publicación, SLO de frescura, y nivel de autoridad.

Tres capas temporales:
  - RAPID_OBSERVATIONAL: observaciones rápidas (diarias/semanales)
  - OPERATIONAL_INDEX: índices operacionales (mensuales/estacionales)
  - OFFICIAL_AUTHORITY: comunicados oficiales (event-driven)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AuthorityLevel(str, Enum):
    RAPID_OBSERVATIONAL = "rapid_observational"
    OPERATIONAL_INDEX = "operational_index"
    OFFICIAL_AUTHORITY = "official_authority"


class OperationalRisk(str, Enum):
    LOW_STRUCTURED = "LOW_STRUCTURED_OPERATIONAL"
    MEDIUM_IRREGULAR = "MEDIUM_IRREGULAR_OR_LEGACY"
    HIGH_HTML = "HIGH_HTML_OR_DASHBOARD"
    HIGH_DOCUMENT = "HIGH_DOCUMENT_ONLY"
    EXPERIMENTAL = "EXPERIMENTAL"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class SourceProfile:
    """Contrato versionado de una fuente científica."""
    source_id: str
    institution: str
    product: str
    canonical_url: str
    access_url: str
    access_method: str  # 'csv', 'ascii', 'opendap_ascii', 'html_parse'
    format: str
    authority_level: AuthorityLevel
    supported_metric_ids: tuple[str, ...]
    region: str
    units: str
    climatology: str
    temporal_resolution: str  # 'daily', 'weekly', 'monthly', 'seasonal'
    expected_cadence: str  # 'daily', 'weekly', 'monthly'
    expected_release_window: str  # descripción humana
    typical_lag: str  # '1-2 days', '2-5 days'
    freshness_slo: str  # '7 days', '45 days'
    stale_after: str  # '14 days', '60 days'
    revision_window: str
    preliminary_policy: str
    license: str
    attribution: str
    request_budget: int  # max requests per run
    timeout: float  # seconds
    max_retries: int
    fallback_source_ids: tuple[str, ...] = ()
    operational_risk: OperationalRisk = OperationalRisk.LOW_STRUCTURED
    last_verified_at: str = ""
    unresolved_limitations: str = ""


# ----------------------------------------------------------------------------
# Registro de fuentes verificadas
# ----------------------------------------------------------------------------
SOURCES: dict[str, SourceProfile] = {
    # --- Capa rápida observacional ---
    "noaa-cpc-wksst": SourceProfile(
        source_id="noaa-cpc-wksst",
        institution="NOAA / CPC",
        product="Weekly OISST Niño region SST/SSTA",
        canonical_url="https://www.cpc.ncep.noaa.gov/data/indices/",
        access_url="https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for",
        access_method="ascii",
        format="fixed_width",
        authority_level=AuthorityLevel.RAPID_OBSERVATIONAL,
        supported_metric_ids=("nino12_weekly", "nino34_weekly"),
        region="Niño 1+2, Niño 3, Niño 3.4, Niño 4",
        units="degC",
        climatology="1991-2020 baseline",
        temporal_resolution="weekly",
        expected_cadence="weekly",
        expected_release_window="Lunes (actualización semanal)",
        typical_lag="3-7 days",
        freshness_slo="14 days",
        stale_after="21 days",
        revision_window="1-2 weeks",
        preliminary_policy="Latest 1-2 weeks may be preliminary",
        license="Public domain (NOAA)",
        attribution="NOAA/CPC OISST v2.1",
        request_budget=5,
        timeout=30.0,
        max_retries=3,
        operational_risk=OperationalRisk.LOW_STRUCTURED,
    ),

    # --- Capa de índices operacionales ---
    "noaa-psl-nino12": SourceProfile(
        source_id="noaa-psl-nino12",
        institution="NOAA / PSL",
        product="Niño 1+2 monthly SST anomaly",
        canonical_url="https://psl.noaa.gov/data/timeseries/month/data/nino12.long.anom.csv",
        access_url="https://psl.noaa.gov/data/timeseries/month/data/nino12.long.anom.csv",
        access_method="csv",
        format="csv",
        authority_level=AuthorityLevel.OPERATIONAL_INDEX,
        supported_metric_ids=("nino12",),
        region="Niño 1+2 (90°W-80°W, 10°S-0°)",
        units="degC",
        climatology="1991-2020",
        temporal_resolution="monthly",
        expected_cadence="monthly",
        expected_release_window="Primera semana del mes siguiente",
        typical_lag="3-10 days",
        freshness_slo="45 days",
        stale_after="60 days",
        revision_window="1-3 months",
        preliminary_policy="Latest month may be preliminary",
        license="Public domain (NOAA)",
        attribution="NOAA/PSL",
        request_budget=5,
        timeout=30.0,
        max_retries=3,
        operational_risk=OperationalRisk.LOW_STRUCTURED,
    ),
    "noaa-psl-nino34": SourceProfile(
        source_id="noaa-psl-nino34",
        institution="NOAA / PSL",
        product="Niño 3.4 monthly SST anomaly",
        canonical_url="https://psl.noaa.gov/data/timeseries/month/data/nino34.long.anom.csv",
        access_url="https://psl.noaa.gov/data/timeseries/month/data/nino34.long.anom.csv",
        access_method="csv",
        format="csv",
        authority_level=AuthorityLevel.OPERATIONAL_INDEX,
        supported_metric_ids=("nino34",),
        region="Niño 3.4 (170°W-120°W, 5°S-5°N)",
        units="degC",
        climatology="1991-2020",
        temporal_resolution="monthly",
        expected_cadence="monthly",
        expected_release_window="Primera semana del mes siguiente",
        typical_lag="3-10 days",
        freshness_slo="45 days",
        stale_after="60 days",
        revision_window="1-3 months",
        preliminary_policy="Latest month may be preliminary",
        license="Public domain (NOAA)",
        attribution="NOAA/PSL",
        request_budget=5,
        timeout=30.0,
        max_retries=3,
        operational_risk=OperationalRisk.LOW_STRUCTURED,
    ),
    "noaa-cpc-roni": SourceProfile(
        source_id="noaa-cpc-roni",
        institution="NOAA / CPC",
        product="RONI — Relative Oceanic Niño Index (official)",
        canonical_url="https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/",
        access_url="https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt",
        access_method="ascii",
        format="ascii_seasonal",
        authority_level=AuthorityLevel.OPERATIONAL_INDEX,
        supported_metric_ids=("roni",),
        region="Niño 3.4 (170°W-120°W, 5°S-5°N) with tropical-mean adjustment",
        units="degC",
        climatology="1991-2020 (relative to tropical mean 15°S-15°N)",
        temporal_resolution="seasonal (overlapping 3-month: DJF, JFM, ...)",
        expected_cadence="monthly (with 3-month overlap)",
        expected_release_window="Primera quincena del mes siguiente",
        typical_lag="5-15 days",
        freshness_slo="60 days",
        stale_after="75 days",
        revision_window="1-3 months",
        preliminary_policy="Latest 1-2 seasons may be preliminary",
        license="Public domain (NOAA)",
        attribution="NOAA/CPC RONI (Huang et al. baseline adaptativa)",
        request_budget=5,
        timeout=30.0,
        max_retries=3,
        fallback_source_ids=("noaa-psl-nino34",),
        operational_risk=OperationalRisk.LOW_STRUCTURED,
        unresolved_limitations="RONI no es una media móvil simple de Niño 3.4; "
        "usa ERSST con ajuste de media tropical relativa. No debe计算 "
        "como rolling mean de Niño 3.4.",
    ),
    "noaa-cpc-soi": SourceProfile(
        source_id="noaa-cpc-soi",
        institution="NOAA / CPC",
        product="Monthly SOI (Tahiti-Darwin standardized)",
        canonical_url="https://www.cpc.ncep.noaa.gov/data/indices/",
        access_url="https://www.cpc.ncep.noaa.gov/data/indices/soi",
        access_method="ascii",
        format="ascii_monthly",
        authority_level=AuthorityLevel.OPERATIONAL_INDEX,
        supported_metric_ids=("soi",),
        region="Tahiti-Darwin (escala de cuenca)",
        units="dimensionless (standardized)",
        climatology="Climatología estándar CPC",
        temporal_resolution="monthly",
        expected_cadence="monthly",
        expected_release_window="Primera semana del mes siguiente",
        typical_lag="3-7 days",
        freshness_slo="45 days",
        stale_after="60 days",
        revision_window="1-3 months",
        preliminary_policy="Latest month may be preliminary",
        license="Public domain (NOAA)",
        attribution="NOAA/CPC SOI",
        request_budget=5,
        timeout=30.0,
        max_retries=3,
        operational_risk=OperationalRisk.LOW_STRUCTURED,
    ),
    "noaa-cpc-wpac850": SourceProfile(
        source_id="noaa-cpc-wpac850",
        institution="NOAA / CPC",
        product="850 hPa trade wind index — Western Pacific (135°E-180°W)",
        canonical_url="https://www.cpc.ncep.noaa.gov/data/indices/",
        access_url="https://www.cpc.ncep.noaa.gov/data/indices/wpac850",
        access_method="ascii",
        format="ascii_monthly",
        authority_level=AuthorityLevel.OPERATIONAL_INDEX,
        supported_metric_ids=("u850_wpac",),
        region="Western Pacific 135°E-180°W, 5°S-5°N",
        units="m/s (actual wind, not anomaly)",
        climatology="N/A (original data)",
        temporal_resolution="monthly",
        expected_cadence="monthly",
        expected_release_window="Primera semana del mes siguiente",
        typical_lag="3-7 days",
        freshness_slo="45 days",
        stale_after="60 days",
        revision_window="1-3 months",
        preliminary_policy="Latest month may be preliminary",
        license="Public domain (NOAA)",
        attribution="NOAA/CPC 850 hPa trade wind indices",
        request_budget=5,
        timeout=30.0,
        max_retries=3,
        operational_risk=OperationalRisk.LOW_STRUCTURED,
    ),
    "noaa-cpc-cpac850": SourceProfile(
        source_id="noaa-cpc-cpac850",
        institution="NOAA / CPC",
        product="850 hPa trade wind index — Central Pacific (175°W-140°W)",
        canonical_url="https://www.cpc.ncep.noaa.gov/data/indices/",
        access_url="https://www.cpc.ncep.noaa.gov/data/indices/cpac850",
        access_method="ascii",
        format="ascii_monthly",
        authority_level=AuthorityLevel.OPERATIONAL_INDEX,
        supported_metric_ids=("u850_cpac",),
        region="Central Pacific 175°W-140°W, 5°S-5°N",
        units="m/s (actual wind, not anomaly)",
        climatology="N/A (original data)",
        temporal_resolution="monthly",
        expected_cadence="monthly",
        expected_release_window="Primera semana del mes siguiente",
        typical_lag="3-7 days",
        freshness_slo="45 days",
        stale_after="60 days",
        revision_window="1-3 months",
        preliminary_policy="Latest month may be preliminary",
        license="Public domain (NOAA)",
        attribution="NOAA/CPC 850 hPa trade wind indices",
        request_budget=5,
        timeout=30.0,
        max_retries=3,
        operational_risk=OperationalRisk.LOW_STRUCTURED,
    ),
    "noaa-cpc-epac850": SourceProfile(
        source_id="noaa-cpc-epac850",
        institution="NOAA / CPC",
        product="850 hPa trade wind index — Eastern Pacific (135°W-120°W)",
        canonical_url="https://www.cpc.ncep.noaa.gov/data/indices/",
        access_url="https://www.cpc.ncep.noaa.gov/data/indices/epac850",
        access_method="ascii",
        format="ascii_monthly",
        authority_level=AuthorityLevel.OPERATIONAL_INDEX,
        supported_metric_ids=("u850_epac",),
        region="Eastern Pacific 135°W-120°W, 5°S-5°N",
        units="m/s (actual wind, not anomaly)",
        climatology="N/A (original data)",
        temporal_resolution="monthly",
        expected_cadence="monthly",
        expected_release_window="Primera semana del mes siguiente",
        typical_lag="3-7 days",
        freshness_slo="45 days",
        stale_after="60 days",
        revision_window="1-3 months",
        preliminary_policy="Latest month may be preliminary",
        license="Public domain (NOAA)",
        attribution="NOAA/CPC 850 hPa trade wind indices",
        request_budget=5,
        timeout=30.0,
        max_retries=3,
        operational_risk=OperationalRisk.LOW_STRUCTURED,
    ),
    "noaa-cpc-godas-d20": SourceProfile(
        source_id="noaa-cpc-godas-d20",
        institution="NOAA / PSL (GODAS)",
        product="D20 anomaly (dbss_obil isothermal layer depth) — Niño 3.4",
        canonical_url="https://psl.noaa.gov/thredds/dodsC/Datasets/godas/dbss_obil.YYYY.nc",
        access_url="https://psl.noaa.gov/thredds/dodsC/Datasets/godas/",
        access_method="opendap_ascii",
        format="opendap_ascii_grid",
        authority_level=AuthorityLevel.OPERATIONAL_INDEX,
        supported_metric_ids=("d20",),
        region="Niño 3.4 (5°S-5°N, 170°W-120°W) — area average",
        units="m (anomaly vs 1991-2020)",
        climatology="1991-2020 (computed from GODAS annual files)",
        temporal_resolution="monthly",
        expected_cadence="monthly",
        expected_release_window="Mediados del mes siguiente",
        typical_lag="10-20 days",
        freshness_slo="60 days",
        stale_after="75 days",
        revision_window="1-3 months",
        preliminary_policy="Latest 1-2 months may be preliminary",
        license="Public domain (NOAA)",
        attribution="NOAA/NCEP GODAS",
        request_budget=60,
        timeout=120.0,
        max_retries=3,
        operational_risk=OperationalRisk.MEDIUM_IRREGULAR,
    ),

    # --- Capa de autoridad oficial ---
    "noaa-cpc-enso-advisory": SourceProfile(
        source_id="noaa-cpc-enso-advisory",
        institution="NOAA / CPC",
        product="ENSO Alert System Status (official)",
        canonical_url="https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml",
        access_url="https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml",
        access_method="html_parse",
        format="html",
        authority_level=AuthorityLevel.OFFICIAL_AUTHORITY,
        supported_metric_ids=("basin_official_status",),
        region="Pacific ecuatorial (cuenca)",
        units="text (El Niño Advisory / La Niña Advisory / ENSO-Neutral / Watch)",
        climatology="N/A",
        temporal_resolution="monthly (second Thursday of each month)",
        expected_cadence="monthly",
        expected_release_window="Segundo jueves de cada mes",
        typical_lag="0-1 day after publication",
        freshness_slo="45 days",
        stale_after="60 days",
        revision_window="N/A (superseded by next discussion)",
        preliminary_policy="Official upon publication",
        license="Public domain (NOAA)",
        attribution="NOAA/CPC ENSO Diagnostic Discussion",
        request_budget=3,
        timeout=30.0,
        max_retries=3,
        operational_risk=OperationalRisk.HIGH_HTML,
    ),
    "enfen-imarpe-status": SourceProfile(
        source_id="enfen-imarpe-status",
        institution="ENFEN / IMARPE",
        product="Estado oficial El Niño Costero",
        canonical_url="https://siofen.imarpe.gob.pe/nivel2/indice-costero-el-nino-icen",
        access_url="https://siofen.imarpe.gob.pe/nivel2/indice-costero-el-nino-icen",
        access_method="html_parse",
        format="html",
        authority_level=AuthorityLevel.OFFICIAL_AUTHORITY,
        supported_metric_ids=("coastal_official_status",),
        region="Costa peruana",
        units="text (Alerta / Vigilancia / Normal)",
        climatology="N/A",
        temporal_resolution="event-driven",
        expected_cadence="event-driven",
        expected_release_window="Tras reunión del comité ENFEN",
        typical_lag="Variable",
        freshness_slo="90 days",
        stale_after="120 days",
        revision_window="N/A (superseded by next comunicado)",
        preliminary_policy="Official upon publication",
        license="Atribución requerida (ENFEN/IMARPE)",
        attribution="ENFEN/IMARPE SIOFEN",
        request_budget=2,
        timeout=15.0,
        max_retries=2,
        fallback_source_ids=(),
        operational_risk=OperationalRisk.HIGH_HTML,
        unresolved_limitations="El sitio SIOFEN está protegido por Cloudflare y puede "
        "bloquear peticiones automatizadas. Fallback a config/enfen-status.json "
        "(actualización manual). El estado oficial debe verificarse directamente "
        "en siofen.imarpe.gob.pe.",
    ),
}


def get_source(source_id: str) -> Optional[SourceProfile]:
    """Devuelve el SourceProfile para un source_id dado."""
    return SOURCES.get(source_id)


def all_source_ids() -> tuple[str, ...]:
    """Devuelve todos los source_ids registrados."""
    return tuple(SOURCES.keys())


def sources_for_metric(metric_id: str) -> tuple[str, ...]:
    """Devuelve los source_ids que soportan un metric_id dado."""
    return tuple(
        sid for sid, prof in SOURCES.items()
        if metric_id in prof.supported_metric_ids
    )
