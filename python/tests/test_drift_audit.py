"""``tools.drift_audit`` sobre un archivo de prueba en git: encuentra la reescritura de PSL y la página archivada."""

from __future__ import annotations

import os
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


def _commit(repo, when: str, msg: str) -> None:
    env = {"GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when}
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", msg],
                   check=True, env={**os.environ, **env})


def test_same_day_copies_are_compared_in_arrival_order(tmp_path, monkeypatch, capsys):
    """Dos corridas del mismo día: la de la mañana archivó el ONI sin la última estación y la de la tarde el archivo
    completo. Sus nombres (``AAAA-MM-DD-<sha>``) ordenan al revés; por nombre, la auditoría comparaba completo →
    recortado y avisaba ``series-regressed`` y nada había retrocedido. Se ordenan por la hora del commit."""
    oni = (FIX / "cpc-oni.txt").read_text(encoding="utf-8")
    repo = tmp_path / "repo"
    d = repo / "sources" / "cpc-oni"
    d.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (d / "2026-11-20-ffffffffffff.txt").write_text(oni.rstrip("\n").rsplit("\n", 1)[0] + "\n", encoding="utf-8")
    _commit(repo, "2026-11-20T11:00:00+00:00", "mañana")
    (d / "2026-11-20-000000000000.txt").write_text(oni, encoding="utf-8")
    _commit(repo, "2026-11-20T20:00:00+00:00", "tarde")
    monkeypatch.setattr(drift_audit, "ROOT", repo)
    times = drift_audit.added_times("HEAD")
    assert drift_audit.ordered(times, times) == ["sources/cpc-oni/2026-11-20-ffffffffffff.txt",
                                                 "sources/cpc-oni/2026-11-20-000000000000.txt"]
    assert drift_audit.audit("HEAD", {"cpc-oni"}) == []
    assert "no tiene historia" not in capsys.readouterr().err
    # Una tercera copia del día, recortada otra vez y archivada después: esa sí retrocede, y se la nombra a ella.
    (d / "2026-11-20-777777777777.txt").write_text(oni.rstrip("\n").rsplit("\n", 1)[0] + "\n# 3\n", encoding="utf-8")
    _commit(repo, "2026-11-20T22:00:00+00:00", "noche")
    found = drift_audit.audit("HEAD", {"cpc-oni"})
    assert [(f["kind"], f["file"].rsplit("/", 1)[1], f["previous"].rsplit("/", 1)[1]) for f in found] == [
        ("series-regressed", "2026-11-20-777777777777.txt", "2026-11-20-000000000000.txt")]


def test_without_history_same_day_copies_fall_back_to_name(tmp_path, monkeypatch, capsys):
    """Una ref de un solo commit (``git fetch --depth=1``): todas las copias empatan y quedan por nombre, con aviso."""
    repo = tmp_path / "repo"
    d = repo / "sources" / "cpc-oni"
    d.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    oni = (FIX / "cpc-oni.txt").read_text(encoding="utf-8")
    (d / "2026-11-20-bbbb.txt").write_text(oni, encoding="utf-8")
    (d / "2026-11-20-aaaa.txt").write_text(oni, encoding="utf-8")
    (d / "2026-11-19-cccc.txt").write_text(oni, encoding="utf-8")
    _commit(repo, "2026-11-20T20:00:00+00:00", "a")
    monkeypatch.setattr(drift_audit, "ROOT", repo)
    times = drift_audit.added_times("HEAD")
    assert drift_audit.ordered(times, times) == ["sources/cpc-oni/2026-11-19-cccc.txt",
                                                 "sources/cpc-oni/2026-11-20-aaaa.txt",
                                                 "sources/cpc-oni/2026-11-20-bbbb.txt"]
    assert drift_audit.audit("HEAD", {"cpc-oni"}) == []
    assert "no tiene historia" in capsys.readouterr().err
