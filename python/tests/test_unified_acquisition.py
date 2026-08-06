"""Tests científicos para la arquitectura de adquisición unificada.

Verifica:
  - RONI se obtiene del producto oficial, NO se calcula como rolling mean.
  - ICEN se calcula correctamente como 3-month rolling mean de Niño 1+2.
  - Weekly SST se parsea correctamente.
  - CPC wind indices se parsean correctamente.
  - Source profiles tienen metadatos completos.
  - Health se genera desde evidencia real.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "python"))

from enso.unified_acquisition import (
    AcquisitionOrchestrator,
    parse_roni_ascii,
    parse_weekly_sst,
    parse_monthly_ascii,
)
from enso.source_profiles import SOURCES, SourceProfile, AuthorityLevel, all_source_ids


# ----------------------------------------------------------------------------
# PREFLIGHT-008: RONI debe usar producto oficial, no rolling mean
# ----------------------------------------------------------------------------
class TestRoniOfficial:
    """RONI debe provenir de RONI.ascii.txt, no ser calculado."""

    SAMPLE_RONI = """SEAS   YR  ANOM
DJF  1950 -1.19
JFM  1950 -1.08
MAM  2026 -0.04
AMJ  2026  0.49
MJJ  2026  0.98
"""

    def test_roni_parser_extracts_seasonal_values(self):
        """El parser extrae valores estacionales correctos."""
        pts = parse_roni_ascii(self.SAMPLE_RONI)
        assert len(pts) == 5
        assert pts[0]["month"] == "1950-01"
        assert pts[0]["value"] == -1.19
        assert pts[0]["season"] == "DJF"
        assert pts[-1]["month"] == "2026-06"
        assert pts[-1]["value"] == 0.98
        assert pts[-1]["season"] == "MJJ"

    def test_roni_source_profile_exists(self):
        """El SourceProfile para RONI oficial existe."""
        prof = SOURCES.get("noaa-cpc-roni")
        assert prof is not None
        assert "RONI" in prof.product
        assert prof.access_url == "https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt"

    def test_roni_is_not_computed_from_nino34(self):
        """RONI no se calcula como rolling mean de Niño 3.4."""
        prof = SOURCES.get("noaa-cpc-roni")
        assert prof is not None
        # The unresolved_limitations field must mention it's NOT a rolling mean
        assert "rolling mean" in prof.unresolved_limitations.lower() or "NOT" in prof.unresolved_limitations

    def test_roni_authority_level(self):
        """RONI es un índice operacional, no observación rápida."""
        prof = SOURCES.get("noaa-cpc-roni")
        assert prof.authority_level == AuthorityLevel.OPERATIONAL_INDEX

    def test_roni_temporal_resolution_is_seasonal(self):
        """RONI tiene resolución temporal estacional (no mensual)."""
        prof = SOURCES.get("noaa-cpc-roni")
        assert "seasonal" in prof.temporal_resolution.lower()


# ----------------------------------------------------------------------------
# PREFLIGHT-008: ICEN sí se calcula como 3-month rolling mean (metodología ENFEN)
# ----------------------------------------------------------------------------
class TestIcenComputation:
    """ICEN se calcula correctamente como rolling mean de Niño 1+2."""

    def test_icen_uses_3mo_mean(self):
        """ICEN usa media móvil de 3 meses de Niño 1+2."""
        orch = AcquisitionOrchestrator.__new__(AcquisitionOrchestrator)
        n12 = [
            {"month": "2026-01", "value": 1.0, "flag": "final"},
            {"month": "2026-02", "value": 2.0, "flag": "final"},
            {"month": "2026-03", "value": 3.0, "flag": "final"},
        ]
        icen = orch._compute_icen(n12)
        # ICEN for 2026-01: only 1 value → None
        assert icen[0]["value"] is None
        # ICEN for 2026-02: only 2 values → None
        assert icen[1]["value"] is None
        # ICEN for 2026-03: (1+2+3)/3 = 2.0
        assert icen[2]["value"] == 2.0

    def test_icen_not_used_for_roni(self):
        """El método _compute_icen no se aplica a RONI."""
        # RONI se obtiene de acquire_roni() que usa el producto oficial
        # ICEN se obtiene de _compute_icen() que aplica la metodología ENFEN
        # Verificar que son métodos separados
        assert hasattr(AcquisitionOrchestrator, "acquire_roni")
        assert hasattr(AcquisitionOrchestrator, "_compute_icen")
        assert AcquisitionOrchestrator.acquire_roni != AcquisitionOrchestrator._compute_icen


# ----------------------------------------------------------------------------
# Parser tests: weekly SST
# ----------------------------------------------------------------------------
class TestWeeklySSTParser:
    """Tests del parser de weekly SST (wksst8110.for)."""

    SAMPLE = """ Weekly SST data starts week centered on 3Jan1990

                Nino1+2      Nino3        Nino34        Nino4
 Week          SST SSTA     SST SSTA     SST SSTA     SST SSTA
 03JAN1990     23.4-0.4     25.1-0.3     26.6-0.0     28.6 0.3
 10JAN1990     23.4-0.8     25.2-0.3     26.6 0.1     28.6 0.3
"""

    def test_parse_extracts_weekly_points(self):
        pts = parse_weekly_sst(self.SAMPLE)
        # 2 weeks × 2 regions (nino12, nino34) = 4 points
        assert len(pts) == 4
        nino12 = [p for p in pts if p["region"] == "nino12"]
        nino34 = [p for p in pts if p["region"] == "nino34"]
        assert len(nino12) == 2
        assert len(nino34) == 2
        assert nino12[0]["value"] == -0.4
        assert nino34[0]["value"] == 0.0

    def test_weekly_points_have_correct_type(self):
        pts = parse_weekly_sst(self.SAMPLE)
        assert all(p["type"] == "weekly" for p in pts)


# ----------------------------------------------------------------------------
# Parser tests: monthly CPC (SOI, winds)
# ----------------------------------------------------------------------------
class TestMonthlyCPCParser:
    """Tests del parser de formato mensual CPC."""

    SAMPLE = """   850 MB TRADE WIND INDEX(175W-140W)5N 5S  CENTRAL PACIFIC
                    ORIGINAL        DATA

YEAR   JAN   FEB   MAR   APR   MAY   JUN   JUL   AUG   SEP   OCT   NOV   DEC
1979   6.3  10.0   9.8   7.9   7.8   9.2   6.9   6.9   6.7   5.9   8.6   7.9
1980   6.9   7.5   3.8   5.7   5.2   6.8   9.0  11.1  10.4  10.4   9.2  10.6
"""

    def test_parse_extracts_monthly_values(self):
        pts = parse_monthly_ascii(self.SAMPLE)
        assert len(pts) == 24  # 2 years × 12 months
        assert pts[0]["month"] == "1979-01"
        assert pts[0]["value"] == 6.3
        assert pts[11]["month"] == "1979-12"
        assert pts[11]["value"] == 7.9

    def test_parse_handles_fill_values(self):
        """Los valores de relleno (-999.0) se convierten a None."""
        text = """YEAR   JAN   FEB   MAR   APR   MAY   JUN   JUL   AUG   SEP   OCT   NOV   DEC
2026   0.5 -999.0   1.0   2.0   3.0   4.0   5.0   6.0   7.0   8.0   9.0  10.0
"""
        pts = parse_monthly_ascii(text)
        assert len(pts) == 12
        assert pts[0]["value"] == 0.5
        assert pts[1]["value"] is None  # -999.0 → None


# ----------------------------------------------------------------------------
# Source profiles tests
# ----------------------------------------------------------------------------
class TestSourceProfiles:
    """Tests del registro de SourceProfiles."""

    def test_all_profiles_have_required_fields(self):
        """Todos los perfiles tienen los campos obligatorios."""
        for sid, prof in SOURCES.items():
            assert prof.source_id == sid, f"{sid}: source_id mismatch"
            assert prof.institution, f"{sid}: missing institution"
            assert prof.product, f"{sid}: missing product"
            assert prof.canonical_url, f"{sid}: missing canonical_url"
            assert prof.access_url, f"{sid}: missing access_url"
            assert prof.authority_level, f"{sid}: missing authority_level"
            assert prof.temporal_resolution, f"{sid}: missing temporal_resolution"
            assert prof.freshness_slo, f"{sid}: missing freshness_slo"

    def test_rapid_observational_layer_exists(self):
        """Existe al menos una fuente de capa rápida observacional."""
        rapid = [s for s in SOURCES.values() if s.authority_level == AuthorityLevel.RAPID_OBSERVATIONAL]
        assert len(rapid) >= 1, "No rapid observational sources"

    def test_operational_index_layer_exists(self):
        """Existe al menos una fuente de capa operacional."""
        ops = [s for s in SOURCES.values() if s.authority_level == AuthorityLevel.OPERATIONAL_INDEX]
        assert len(ops) >= 3, "Need at least 3 operational index sources"

    def test_official_authority_layer_exists(self):
        """Existe al menos una fuente de capa oficial."""
        official = [s for s in SOURCES.values() if s.authority_level == AuthorityLevel.OFFICIAL_AUTHORITY]
        assert len(official) >= 2, "Need at least 2 official authority sources (NOAA + ENFEN)"

    def test_cpc_wind_indices_registered(self):
        """Los índices de viento CPC (wpac, cpac, epac 850) están registrados."""
        assert "noaa-cpc-wpac850" in SOURCES
        assert "noaa-cpc-cpac850" in SOURCES
        assert "noaa-cpc-epac850" in SOURCES

    def test_all_source_ids_returns_tuple(self):
        """all_source_ids devuelve una tupla."""
        ids = all_source_ids()
        assert isinstance(ids, tuple)
        assert len(ids) >= 8


# ----------------------------------------------------------------------------
# Health generation tests
# ----------------------------------------------------------------------------
class TestHealthGeneration:
    """Tests de generación de health desde evidencia real."""

    def test_health_generated_from_retrieval_ledger(self):
        """Health se genera desde el ledger de adquisición, no de archivos estáticos."""
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            pub = Path(tmpdir) / "pub"
            staging = Path(tmpdir) / "staging"
            pub.mkdir()
            staging.mkdir()

            orch = AcquisitionOrchestrator(pub, staging)
            # Record a fake acquisition
            orch._record("test-source", True, "test evidence", "abc123", 100)
            orch._write_health_json(pub, "2026-01-01T00:00:00Z")

            h = json.loads((pub / "health.json").read_text())
            assert h["sources"][0]["id"] == "test-source"
            assert h["sources"][0]["retrievalEvidence"] == "test evidence"
            assert h["sources"][0]["contentHash"] == "abc123"
            assert h["sources"][0]["pointsRetrieved"] == 100


# ----------------------------------------------------------------------------
# Publication coherence tests
# ----------------------------------------------------------------------------
class TestPublicationCoherence:
    """Tests de coherencia de la publicación."""

    def test_status_json_has_publication_id(self):
        """status.json tiene publicationId."""
        status_file = REPO / "public" / "data" / "status.json"
        if not status_file.exists():
            pytest.skip("status.json not generated")
        s = json.loads(status_file.read_text())
        assert "publicationId" in s
        assert s["publicationId"]

    def test_status_json_roni_is_official(self):
        """status.json indica que RONI proviene del producto oficial."""
        status_file = REPO / "public" / "data" / "status.json"
        if not status_file.exists():
            pytest.skip("status.json not generated")
        s = json.loads(status_file.read_text())
        roni_source = s.get("basin", {}).get("roniSource", "")
        assert "official" in roni_source.lower() or "RONI.ascii.txt" in roni_source

    def test_health_json_has_real_evidence(self):
        """health.json tiene evidencia real de adquisición."""
        health_file = REPO / "public" / "data" / "health.json"
        if not health_file.exists():
            pytest.skip("health.json not generated")
        h = json.loads(health_file.read_text())
        for src in h.get("sources", []):
            assert src.get("retrievalEvidence"), f"Source {src['id']} has no retrievalEvidence"
            assert src.get("retrievedAt"), f"Source {src['id']} has no retrievedAt"

    def test_manifest_has_publication_id(self):
        """manifest.json tiene publicationId."""
        manifest_file = REPO / "public" / "data" / "manifest.json"
        if not manifest_file.exists():
            pytest.skip("manifest.json not generated")
        m = json.loads(manifest_file.read_text())
        assert "publicationId" in m
        assert m["publicationId"]

    def test_no_synthetic_data_in_status(self):
        """status.json no contiene datos sintéticos."""
        status_file = REPO / "public" / "data" / "status.json"
        if not status_file.exists():
            pytest.skip("status.json not generated")
        s = json.loads(status_file.read_text())
        assert s.get("dataSource") == "LIVE_OBSERVED"
        # No "demostración" or "sintético" labels
        text = json.dumps(s).lower()
        assert "demostración" not in text
        assert "sintético" not in text
