"""El clasificador de alcance de Python (``enso.reach``) da la misma clase que el de n8n (``n8n/lib/classify.js``):
la tabla de ``fixtures/reach-parity.json`` la corre también ``n8n/test/lib.test.mjs``."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from enso.reach import classify, header, judge

FIXTURES = Path(__file__).parent / "fixtures"
TABLE = json.loads((FIXTURES / "reach-parity.json").read_text(encoding="utf-8"))["cases"]
REPO = Path(__file__).resolve().parents[2]


def _body(row: dict) -> bytes:
    if row.get("body_file"):
        return (FIXTURES / row["body_file"]).read_bytes()
    return (row.get("body", "") + "x" * row.get("pad", 0)).encode("utf-8")


@pytest.mark.parametrize("row", TABLE, ids=[r["name"] for r in TABLE])
def test_python_gives_the_class_n8n_gives(row):
    body, headers = _body(row), row.get("headers") or {}
    got = judge(row["status"], body, header(headers, "content-type"), row.get("expect"), headers=headers)[0]
    assert got == row["reach"]
    if not row.get("expect") and row["status"] != 202:
        # Sin tipo esperado, la clase de la respuesta sola es la misma (la que guardan las demás mediciones).
        assert classify(row["status"], body, headers=headers) == row["reach"]


def test_table_covers_the_cases_that_diverged():
    """Las divergencias de la revisión del 22 de octubre de 2026 (gap 42) están en la tabla."""
    names = " ".join(r["name"] for r in TABLE)
    for case in ("cf-mitigated y cuerpo mínimo", "challenge-platform", "45 KB con g-recaptcha",
                 "HTML donde se esperaba un PDF"):
        assert case in names


@pytest.mark.skipif(shutil.which("node") is None, reason="sin node")
def test_node_runs_the_same_table():
    r = subprocess.run(["node", "--test", "--test-name-pattern=tabla compartida", "n8n/test/lib.test.mjs"],
                       cwd=REPO, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert "# pass 1" in r.stdout
