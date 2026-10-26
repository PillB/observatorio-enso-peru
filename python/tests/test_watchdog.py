"""Vigilante (.github/workflows/watchdog.yml): la lógica de .github/scripts/watchdog.cjs con ``node --test`` y el
flujo que la corre."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
JS = Path(__file__).parent / "js"


def test_watchdog_module_with_node():
    node = shutil.which("node")
    if not node:
        if os.environ.get("CI"):
            pytest.fail("la prueba del vigilante necesita Node")
        pytest.skip("requiere Node")
    # TAP explícito: desde Node 23 el informe por omisión es otro y no tendría «# fail 0».
    r = subprocess.run([node, "--test", "--test-reporter=tap", str(JS / "watchdog.test.mjs")], capture_output=True,
                       text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
    assert re.search(r"# fail 0", r.stdout) and not re.search(r"# skipped [1-9]", r.stdout), r.stdout[-2000:]


def test_watchdog_reads_the_heartbeats_and_still_mails_last():
    """Revisión: el vigilante solo miraba la antigüedad del sitio; sin «contents: read» (el permiso del job reemplaza
    al del flujo) no podía leer heartbeat.json de data-peru ni de data-n8n. El correo de alertas sigue al final."""
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "watchdog.yml").read_text(encoding="utf-8"))
    job = wf["jobs"]["check"]
    assert job["permissions"] == {"actions": "write", "issues": "write", "contents": "read"}
    steps = job["steps"]
    script = next(i for i, s in enumerate(steps) if s.get("uses", "").startswith("actions/github-script"))
    checkout = steps[script - 1]
    assert checkout["uses"].startswith("actions/checkout") and ".github/scripts" in checkout["with"]["sparse-checkout"]
    assert "require('./.github/scripts/watchdog.cjs')" in steps[script]["with"]["script"]
    assert (ROOT / ".github" / "scripts" / "watchdog.cjs").exists()
    assert steps[script]["env"]["MAX_AGE_HOURS"] == "30" and "SITE_URL" in steps[script]["env"]
    assert steps[-1]["name"] == "Email the configured addresses" and "tools.alert_email" in steps[-1]["run"]


def test_watchdog_heartbeat_limit_matches_the_pipeline():
    from enso import observatory as obs

    js = (ROOT / ".github" / "scripts" / "watchdog.cjs").read_text(encoding="utf-8")
    assert f"const HEARTBEAT_MAX_HOURS = {obs.RELAY_STALE_HOURS};" in js
