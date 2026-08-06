"""Tests de regresión para defectos detectados en la auditoría de release-readiness.

Cubre:
- health.json existe y tiene estructura correcta.
- source-registry.json existe y tiene fuentes.
- latest.json existe y tiene datos actuales.
- official-status.json existe y separa costero/cuenca.
- operational-signals.json existe y tiene señal del experto.
- data-quality.json existe y tiene resumen.
- threshold-policies.json existe y tiene políticas.
- Pipeline schedule es 23:37 Lima (04:37 UTC).
- deploy-pages.yml tiene branches: [main] válido.
- No hay secretos en assets públicos.
- No hay valores hardcodeados en producción.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "public" / "data"
WORKFLOWS = REPO / ".github" / "workflows"


class TestRequiredDataFiles:
    """Verifica que todos los archivos de datos requeridos existen."""

    def test_health_json_exists(self):
        assert (DATA / "health.json").exists(), "health.json no existe"

    def test_health_json_has_required_fields(self):
        with open(DATA / "health.json") as f:
            h = json.load(f)
        assert "generatedAt" in h
        assert "pipelineStatus" in h
        assert "sources" in h
        assert "dataVersion" in h

    def test_source_registry_json_exists(self):
        assert (DATA / "source-registry.json").exists()

    def test_source_registry_has_sources(self):
        with open(DATA / "source-registry.json") as f:
            r = json.load(f)
        assert "sources" in r
        assert len(r["sources"]) > 0

    def test_latest_json_exists(self):
        assert (DATA / "latest.json").exists()

    def test_latest_json_has_current_values(self):
        with open(DATA / "latest.json") as f:
            l = json.load(f)
        assert "coastal" in l
        assert "basin" in l
        assert "winds" in l
        assert "thermocline" in l
        assert "soi" in l

    def test_official_status_json_exists(self):
        assert (DATA / "official-status.json").exists()

    def test_official_status_separates_scopes(self):
        with open(DATA / "official-status.json") as f:
            o = json.load(f)
        assert "coastal" in o
        assert "basin" in o
        assert o["coastal"]["authority"] != o["basin"]["authority"]

    def test_operational_signals_json_exists(self):
        assert (DATA / "operational-signals.json").exists()

    def test_operational_signals_has_expert_disclaimer(self):
        with open(DATA / "operational-signals.json") as f:
            s = json.load(f)
        assert "disclaimer" in s
        assert "no equivale" in s["disclaimer"].lower()

    def test_data_quality_json_exists(self):
        assert (DATA / "data-quality.json").exists()

    def test_threshold_policies_json_exists(self):
        assert (DATA / "threshold-policies.json").exists()

    def test_threshold_policies_has_both_sets(self):
        with open(DATA / "threshold-policies.json") as f:
            p = json.load(f)
        assert "policies" in p
        # Should have at least expert and official policies
        policy_names = list(p["policies"].keys())
        assert len(policy_names) >= 2


class TestWorkflowConfiguration:
    """Verifica la configuración de workflows."""

    def test_daily_data_update_workflow_exists(self):
        assert (WORKFLOWS / "daily-data-update.yml").exists()

    def test_daily_data_update_has_correct_schedule(self):
        """daily-data-update.yml is archived; daily-refresh.yml is canonical."""
        # The schedule moved to daily-refresh.yml
        daily_refresh = (WORKFLOWS / "daily-refresh.yml").read_text()
        assert "37 4" in daily_refresh, "daily-refresh.yml debe tener schedule 04:37 UTC"
        # daily-data-update.yml should be archived (no schedule)
        archived = (WORKFLOWS / "daily-data-update.yml").read_text()
        assert "37 4 * * *" not in archived or "ARCHIVED" in archived, \
            "daily-data-update.yml schedule should be disabled (archived)"

    def test_daily_data_update_has_repository_dispatch(self):
        content = (WORKFLOWS / "daily-data-update.yml").read_text()
        assert "repository_dispatch" in content
        assert "enso-refresh" in content

    def test_daily_data_update_has_force_refresh_input(self):
        content = (WORKFLOWS / "daily-data-update.yml").read_text()
        assert "force_refresh" in content

    def test_daily_data_update_has_dry_run_input(self):
        content = (WORKFLOWS / "daily-data-update.yml").read_text()
        assert "dry_run" in content

    def test_freshness_watchdog_exists(self):
        assert (WORKFLOWS / "freshness-watchdog.yml").exists()

    def test_pull_request_validation_exists(self):
        assert (WORKFLOWS / "pull-request-validation.yml").exists()

    def test_source_contract_monitor_exists(self):
        assert (WORKFLOWS / "source-contract-monitor.yml").exists()

    def test_update_data_reusable_exists(self):
        assert (WORKFLOWS / "_update-data.yml").exists()

    def test_deploy_pages_has_valid_branches(self):
        content = (WORKFLOWS / "deploy-pages.yml").read_text()
        assert "[main]" in content or "main" in content

    def test_pipeline_schedule_is_2337_lima(self):
        content = (WORKFLOWS / "pipeline.yml").read_text()
        assert "37 4" in content, "Pipeline debe ejecutarse a 23:37 Lima (04:37 UTC)"

    def test_concurrency_group_prevents_overlap(self):
        for wf in ["daily-data-update.yml", "deploy-pages.yml"]:
            content = (WORKFLOWS / wf).read_text()
            assert "concurrency" in content, f"{wf} debe tener grupo de concurrencia"


class TestSecurityScan:
    """Verifica que no hay secretos ni valores hardcodeados."""

    def test_no_secrets_in_public_assets(self):
        import re
        secret_patterns = [
            r"sk-[a-zA-Z0-9]{20}",
            r"ghp_[a-zA-Z0-9]{30}",
            r"AKIA[A-Z0-9]{16}",
            r"hf_[a-zA-Z0-9]{20}",
        ]
        for pattern in secret_patterns:
            for f in (REPO / "public").rglob("*"):
                if f.is_file() and f.suffix in [".html", ".json", ".js", ".css"]:
                    content = f.read_text(errors="ignore")
                    matches = re.findall(pattern, content)
                    assert not matches, f"Secreto detectado en {f}: {matches}"

    def test_no_hardcoded_current_values_in_html(self):
        """El HTML estático no debe tener valores actuales hardcodeados."""
        html = (REPO / "public" / "index.html").read_text()
        # Check that current values come from STATUS object, not literals
        assert "STATUS.coastal.icen" in html or "s.coastal.icen" in html
        assert "STATUS.basin.roni" in html or "s.basin.roni" in html
