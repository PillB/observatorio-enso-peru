"""``tools.drift_audit`` sobre un archivo de prueba en git: encuentra la reescritura de PSL y la página archivada."""

from __future__ import annotations

import shutil
import subprocess

from conftest import FIX
from tools import drift_audit


def test_audit_finds_rewrite_and_archived_block_page(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    d = repo / "sources" / "psl-ersst6-nino34"
    d.mkdir(parents=True)
    shutil.copy(FIX.parent / "drift" / "psl-nina34-20261106.data", d / "2026-11-06-a.txt")
    shutil.copy(FIX.parent / "drift" / "psl-nina34-20261118.data", d / "2026-11-18-b.txt")
    (repo / "sources" / "news-ciifen").mkdir()
    shutil.copy(FIX / "blocked" / "imunify360-soltv-piura-20261119.html", repo / "sources" / "news-ciifen" / "x.xml")
    for cmd in (["init", "-q"], ["add", "-A"],
                ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "a"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True)
    monkeypatch.setattr(drift_audit, "ROOT", repo)
    found = drift_audit.audit("HEAD")
    kinds = sorted(f["kind"] for f in found)
    assert kinds == ["archived-block-page", "history-rewritten"]
    assert next(f for f in found if f["kind"] == "archived-block-page")["block"] == "imunify360"
