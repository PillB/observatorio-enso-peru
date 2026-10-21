"""Corrida programada del recolector, su tarea programada, la verificación y el kit."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from tools import collector_check as chk
from tools import collector_kit as kit
from tools import collector_schedule as sched
from tools import collector_service as svc
from tools import peru_collector as pc

from test_relay import _peru_only

LIMA = svc.LIMA
REPO_ROOT = Path(__file__).resolve().parents[2]
TOKEN = "github_pat_11ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def lima(*args) -> datetime:
    return datetime(*args, tzinfo=LIMA)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Una instalación vacía en una carpeta temporal, sin variables del equipo."""
    for v in ("GITHUB_TOKEN", "ENSO_RELAY_REMOTE", "ENSO_COLLECT_AT", "ENSO_DISPATCH"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("ENSO_REGISTRY_FILE", str(tmp_path / "sin-registro.json"))
    monkeypatch.setattr(svc, "notify", lambda title, text: True)
    monkeypatch.setattr(pc.time, "sleep", lambda s: None)
    return tmp_path


@pytest.fixture
def peru_network(monkeypatch):
    real = httpx.Client
    monkeypatch.setattr(pc.httpx, "Client", lambda **kw: real(**{"transport": httpx.MockTransport(_peru_only), **kw}))


@pytest.fixture
def remote(tmp_path, monkeypatch):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    monkeypatch.setenv("ENSO_RELAY_REMOTE", str(bare))
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    return bare


def remote_index(bare: Path) -> dict:
    out = subprocess.run(["git", "--git-dir", str(bare), "show", f"{pc.BRANCH}:index.json"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


# --- Horario ---------------------------------------------------------------------

def test_an_early_trigger_counts_for_its_slot():
    """Un disparo que arranca a las 20:59:58 es la copia de las 21:00: los reintentos no la repiten."""
    early = {"last_success": lima(2026, 10, 20, 20, 59).isoformat()}
    assert not svc.is_due(early, lima(2026, 10, 20, 21, 30))
    assert not svc.is_due(early, lima(2026, 10, 20, 20, 59))
    assert svc.is_due({"last_success": lima(2026, 10, 20, 20, 50).isoformat()}, lima(2026, 10, 20, 21, 30))
    assert svc.is_due(early, lima(2026, 10, 21, 21, 0))


def test_last_slot_has_grace_and_rolls_back_a_day():
    assert svc.last_slot(lima(2026, 10, 20, 20, 0)) == lima(2026, 10, 19, 21, 0)
    # Una tarea que arranca unos segundos antes de la hora cuenta como la de hoy.
    assert svc.last_slot(lima(2026, 10, 20, 20, 57)) == lima(2026, 10, 20, 21, 0)
    assert svc.last_slot(lima(2026, 10, 21, 8, 0), "21:00") == lima(2026, 10, 20, 21, 0)
    assert svc.last_slot(datetime(2026, 10, 21, 2, 0, tzinfo=timezone.utc)) == lima(2026, 10, 20, 21, 0)


def test_due_once_per_day_and_catches_up_after_power_off():
    assert svc.is_due({}, lima(2026, 10, 20, 21, 0))
    done_yesterday = {"last_success": lima(2026, 10, 19, 21, 2).isoformat()}
    assert svc.is_due(done_yesterday, lima(2026, 10, 20, 21, 0))
    done_tonight = {"last_success": lima(2026, 10, 20, 21, 2).isoformat()}
    assert not svc.is_due(done_tonight, lima(2026, 10, 20, 23, 30))  # reintentos de la noche
    assert not svc.is_due(done_tonight, lima(2026, 10, 21, 8, 0))  # al iniciar sesión al día siguiente
    # Equipo apagado toda la noche: al encenderlo a la mañana, recolecta.
    assert svc.is_due(done_yesterday, lima(2026, 10, 21, 8, 0))
    # Una recolección manual a la tarde no reemplaza la de las 21:00.
    assert svc.is_due({"last_success": lima(2026, 10, 20, 15, 0).isoformat()}, lima(2026, 10, 20, 21, 0))


def test_collect_at_rejects_garbage(monkeypatch):
    monkeypatch.setenv("ENSO_COLLECT_AT", "9pm")
    assert svc.collect_at() == "21:00"
    monkeypatch.setenv("ENSO_COLLECT_AT", "20:30")
    assert svc.collect_at() == "20:30"


def test_trigger_times_follow_lima_in_any_time_zone():
    assert sched.local_times("21:00", LIMA) == ["21:00", "21:30", "22:00", "22:30", "23:00", "23:30"]
    assert sched.local_times("21:00", ZoneInfo("UTC"))[:2] == ["02:00", "02:30"]
    madrid = sched.local_times("21:00", ZoneInfo("Europe/Madrid"), day=datetime(2026, 7, 1).date())
    assert madrid[0] == "04:00"  # verano en Madrid: UTC+2
    assert sched.local_times("23:00", LIMA)[-1] == "01:30"  # cruza la medianoche


# --- Configuración y registro ---------------------------------------------------------

def test_env_file_parsing(tmp_path):
    f = tmp_path / ".env"
    f.write_bytes(b"\xef\xbb\xbf# comentario\r\nGITHUB_TOKEN=\"abc\"\r\nexport ENSO_COLLECT_AT='20:30'\r\n\r\nMAL\r\n")
    assert svc.read_env_file(f) == {"GITHUB_TOKEN": "abc", "ENSO_COLLECT_AT": "20:30"}
    assert svc.read_env_file(tmp_path / "no-existe") == {}


def test_env_file_wins_over_a_stale_environment_token(home, monkeypatch):
    (home / ".env").write_text(f"GITHUB_TOKEN={TOKEN}\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_viejo_de_la_instalacion_anterior_000000")
    origin = svc.load_env(home)
    assert svc.os.environ["GITHUB_TOKEN"] == TOKEN
    assert origin["GITHUB_TOKEN"] == ".env" and origin["ignored:GITHUB_TOKEN"] == "entorno"


def test_log_hides_the_token_and_rotates(home, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    log = svc.paths(home)["log"]
    log.parent.mkdir()
    log.write_text("x" * (svc.LOG_MAX_BYTES + 1), encoding="utf-8")
    with svc.logging_to_file(home) as path:
        print(f"git push https://x-access-token:{TOKEN}@github.com/repo.git")
    assert path == log and log.with_name("recolector.log.1").exists()
    assert TOKEN not in log.read_text(encoding="utf-8") and "***" in log.read_text(encoding="utf-8")
    assert TOKEN not in capsys.readouterr().out


def test_lock_blocks_a_second_run_and_expires(home):
    with svc.run_lock(home):
        with pytest.raises(svc.Problem) as busy:
            with svc.run_lock(home):
                pass
        assert busy.value.code == svc.EXIT_BUSY
    assert not svc.paths(home)["lock"].exists()
    lock = svc.paths(home)["lock"]
    lock.write_text("123", encoding="utf-8")
    old = (datetime.now() - svc.LOCK_STALE - timedelta(minutes=1)).timestamp()
    svc.os.utime(lock, (old, old))
    with svc.run_lock(home):  # candado de una corrida que murió: se reemplaza
        pass


# --- Corridas ------------------------------------------------------------------------

def test_missing_token_fails_fast_and_alerts_after_two(home, monkeypatch):
    alerts = []
    monkeypatch.setattr(svc, "notify", lambda title, text: alerts.append(title) or True)
    assert svc.run(root=home) == svc.EXIT_CONFIG
    s = svc.read_state(home)
    assert s["result"] == "falla" and "GITHUB_TOKEN" in s["detail"] and s["hint"]
    assert not alerts
    assert svc.run(root=home) == svc.EXIT_CONFIG
    assert svc.read_state(home)["consecutive_failures"] == 2 and len(alerts) == 1
    svc.run(root=home)
    assert len(alerts) == 1  # un aviso por día


def test_scheduled_run_collects_pushes_and_then_skips(home, peru_network, remote):
    assert svc.run(scheduled=True, root=home) == svc.EXIT_OK
    s = svc.read_state(home)
    assert s["result"] == "ok" and s["consecutive_failures"] == 0 and s["summary"]["enfen"] == "2/3"
    idx = remote_index(remote)
    assert idx["collector"]["runner"].startswith("collector_service") and idx["collector"]["python"]
    # El siguiente disparo de la noche no vuelve a recolectar.
    calls = []
    real_collect = pc.collect
    pc.collect = lambda out: calls.append(out) or real_collect(out)
    try:
        assert svc.run(scheduled=True, root=home) == svc.EXIT_OK
    finally:
        pc.collect = real_collect
    assert not calls and svc.read_state(home)["last_check"]


def remote_file(bare: Path, name: str) -> dict:
    out = subprocess.run(["git", "--git-dir", str(bare), "show", f"{pc.BRANCH}:{name}"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def _all_sources_down(monkeypatch, how: str = "dns"):
    def down(req):
        if how == "vacio":  # responden 200 sin contenido: nada que guardar
            return httpx.Response(200, content=b"")
        if how == "enorme":  # responden 200 con más de MAX_BYTES: tampoco se guarda
            return httpx.Response(200, content=b"x" * (pc.MAX_BYTES + 1))
        raise httpx.ConnectError("Temporary failure in name resolution")

    real = httpx.Client
    monkeypatch.setattr(pc.httpx, "Client", lambda **kw: real(**{"transport": httpx.MockTransport(down), **kw}))


@pytest.mark.parametrize("how", ["dns", "vacio", "enorme"])
def test_nothing_answered_keeps_the_copy_and_pushes_a_heartbeat(home, peru_network, remote, monkeypatch, how):
    assert svc.run(root=home) == svc.EXIT_OK
    good = remote_index(remote)
    assert remote_file(remote, pc.HEARTBEAT)["result"] == "ok"
    _all_sources_down(monkeypatch, how)
    assert svc.run(root=home) == svc.EXIT_NO_SOURCES
    assert "solo el latido" in svc.read_state(home)["detail"]
    assert remote_index(remote) == good  # la última copia buena sigue ahí
    hb = remote_file(remote, pc.HEARTBEAT)
    assert hb["schema"] == "enso-relay-heartbeat/1" and hb["result"] == "sin-fuentes"
    assert hb["reachable"].startswith("0/") and hb["failures"] and hb["collector"]["runner"]
    assert all(f.get("error") for f in hb["failures"])  # vacía, demasiado grande o sin conexión


def test_nothing_answered_and_no_github_either(home, remote, monkeypatch):
    _all_sources_down(monkeypatch)
    monkeypatch.setenv("ENSO_RELAY_REMOTE", str(remote.parent / "no-existe.git"))
    assert svc.run(root=home) == svc.EXIT_NO_SOURCES
    assert "tampoco se pudo subir el latido" in svc.read_state(home)["detail"]
    branches = subprocess.run(["git", "--git-dir", str(remote), "branch"], capture_output=True, text=True).stdout
    assert pc.BRANCH not in branches


def test_run_once_does_not_push_an_empty_copy(home, remote, monkeypatch):
    """La misma protección en la corrida de Docker y systemd: solo el latido."""
    _all_sources_down(monkeypatch)
    pushed, beats = [], []
    monkeypatch.setattr(pc, "push", lambda snap, token, **kw: pushed.append(snap))
    monkeypatch.setattr(pc, "push_heartbeat", lambda hb, token: beats.append(hb))
    assert pc.run_once(True, None) == 1 and not pushed
    assert beats and beats[0]["result"] == "sin-fuentes"


def test_force_flag_from_the_check_runs_once_without_dispatch(home, peru_network, remote, monkeypatch):
    dispatched = []
    monkeypatch.setattr(pc, "dispatch", lambda token: dispatched.append(token))
    monkeypatch.delenv("ENSO_RELAY_REMOTE")
    monkeypatch.setattr(svc, "github_preflight", lambda token, repo: {"expires_at": None})
    monkeypatch.setattr(pc, "push", lambda snap, token: None)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    svc.write_state({"last_success": now, "result": "ok"}, home)
    svc.paths(home)["force"].write_text(json.dumps({"created": now, "dispatch": False}), encoding="utf-8")
    assert svc.run(scheduled=True, root=home) == svc.EXIT_OK
    assert svc.read_state(home)["trigger"] == "prueba" and not dispatched
    assert not svc.paths(home)["force"].exists()
    svc.run(scheduled=True, root=home)  # sin pedido: ya está hecho, no recolecta ni pide nada
    assert not dispatched


def test_task_test_ignores_a_run_already_in_progress_and_rekicks(home, monkeypatch):
    """macOS: launchd corre la tarea al instalarla e ignora el disparo mientras sigue en curso."""
    monkeypatch.setattr(svc, "collect_and_push", lambda **kw: (_ for _ in ()).throw(
        svc.Problem(svc.EXIT_GITHUB, "GitHub rechazó el token")))
    p = svc.paths(home)
    p["lock"].write_text("123", encoding="utf-8")  # la corrida de la instalación sigue trabajando
    clock = {"t": 1000.0, "sleeps": 0}

    def sleep(sec):
        clock["t"] += sec
        clock["sleeps"] += 1
        if clock["sleeps"] == 2 and p["lock"].exists():  # termina después de que la prueba la espera
            p["lock"].unlink()
            svc.write_state({"last_attempt": "2026-10-21T01:37:56+00:00", "trigger": "programada",
                             "result": "falla", "exit_code": 3}, home)

    monkeypatch.setattr(chk, "time", type("T", (), {"time": staticmethod(lambda: clock["t"]),
                                                    "sleep": staticmethod(sleep)}))
    kicks = []

    def kick(python, root):
        kicks.append(clock["t"])
        if len(kicks) > 1:  # el primer disparo se pierde
            svc.run(scheduled=True, root=root)
        return True

    monkeypatch.setattr(chk.sched, "kick", kick)
    r = chk.test_scheduled_run({"root": home}, wait_min=5, emit=lambda line: None)
    assert r.level == chk.FAIL and "rechazó el token" in r.title, r
    state = svc.read_state(home)
    assert state["trigger"] == "prueba" and state["exit_code"] == svc.EXIT_GITHUB
    assert len(kicks) == 2 and not p["force"].exists()


def test_forced_run_that_finds_another_run_keeps_the_request(home, monkeypatch):
    p = svc.paths(home)
    p["lock"].write_text("123", encoding="utf-8")
    p["force"].write_text(json.dumps({"created": datetime.now(timezone.utc).isoformat(), "id": "abc"}),
                          encoding="utf-8")
    assert svc.run(scheduled=True, root=home) == svc.EXIT_BUSY
    assert json.loads(p["force"].read_text(encoding="utf-8"))["id"] == "abc"


def test_a_run_without_upload_does_not_count_for_tonight(home, peru_network, monkeypatch):
    """--sin-subir no deja copia en data-peru: la tarea de la noche igual debe recolectar."""
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    assert svc.run(do_push=False, root=home) == svc.EXIT_OK
    s = svc.read_state(home)
    assert s["result"] == "ok" and "last_success" not in s
    assert svc.is_due(s, datetime.now(timezone.utc), "00:00")


def test_push_failure_is_explained(home, peru_network, remote, monkeypatch):
    def rejected(snap, token):
        raise RuntimeError("git push falló: remote: Permission to PillB/observatorio-enso-peru.git denied. 403")

    monkeypatch.setattr(pc, "push", rejected)
    assert svc.run(root=home) == svc.EXIT_PUSH
    assert "Contents" in svc.read_state(home)["hint"]


def test_push_never_uses_credential_helpers_or_prompts(home, peru_network, remote, monkeypatch, tmp_path):
    calls = []
    real = subprocess.run

    def spy(cmd, *a, **kw):
        if cmd and cmd[0] == "git":
            calls.append((cmd, kw.get("env") or {}))
        return real(cmd, *a, **kw)

    monkeypatch.setattr(pc.subprocess, "run", spy)
    out, _ = tmp_path / "snap", pc.collect(tmp_path / "snap")
    pc.push(out, TOKEN)
    assert calls and all("credential.helper=" in c for c, _ in calls)
    assert all(env.get("GIT_TERMINAL_PROMPT") == "0" for _, env in calls)


# --- GitHub ---------------------------------------------------------------------------

def test_token_expiry_header_formats():
    assert svc.parse_token_expiry("2027-10-20 17:00:00 UTC") == datetime(2027, 10, 20, 17, tzinfo=timezone.utc)
    assert svc.parse_token_expiry("2027-10-20 12:00:00 -0500") == datetime(2027, 10, 20, 17, tzinfo=timezone.utc)
    assert svc.parse_token_expiry("") is None and svc.parse_token_expiry("nunca") is None


def test_preflight_reads_expiry_and_explains_rejections():
    def gh(req):
        if req.headers["authorization"] == f"Bearer {TOKEN}":
            return httpx.Response(200, json={"full_name": "x"},
                                  headers={"github-authentication-token-expiration": "2027-01-02 03:04:05 UTC"})
        return httpx.Response(401, json={"message": "Bad credentials"})

    client = httpx.Client(transport=httpx.MockTransport(gh))
    assert svc.github_preflight(TOKEN, "o/r", client)["expires_at"].startswith("2027-01-02T03:04:05")
    with pytest.raises(svc.Problem) as bad:
        svc.github_preflight("github_pat_otro", "o/r", client)
    assert bad.value.code == svc.EXIT_GITHUB and "token" in bad.value.hint.lower()


def test_expiring_token_raises_a_desktop_alert(monkeypatch):
    alerts = []
    monkeypatch.setattr(svc, "notify", lambda title, text: alerts.append(text) or True)
    soon = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    state = {"result": "ok", "token_expires_at": soon}
    svc.alert(state)
    assert alerts and "Vence en" in alerts[0] and state["last_notified"]


# --- Tarea programada -------------------------------------------------------------------

def test_launchd_agent_runs_scheduled_at_lima_times_and_at_load(tmp_path):
    import plistlib

    root = tmp_path / "Application Support" / "recolector"
    data = plistlib.loads(sched.launchd_plist("/x/.venv/bin/python", root, ["21:00", "21:30"]))
    assert data["ProgramArguments"] == ["/x/.venv/bin/python", "-m", "tools.collector_service", "--programado"]
    assert data["StartCalendarInterval"] == [{"Hour": 21, "Minute": 0}, {"Hour": 21, "Minute": 30}]
    assert data["RunAtLoad"] and data["WorkingDirectory"] == str(root / "python")
    assert data["EnvironmentVariables"]["ENSO_HOME"] == str(root)


def test_cron_lines_quote_paths_and_replace_old_ones(tmp_path, monkeypatch):
    root = tmp_path / "con espacio" / "recolector"
    store = ["0 5 * * * otra-cosa", f"0 1 * * * vieja {sched.CRON_TAG}"]
    monkeypatch.setattr(sched, "_crontab_read", lambda: list(store))
    monkeypatch.setattr(sched, "_crontab_write", lambda lines: store.__setitem__(slice(None), lines))
    monkeypatch.setattr(sched.shutil, "which", lambda name: f"/usr/bin/{name}")
    sched.install_cron(str(root / ".venv/bin/python"), root, ["21:00", "21:30"])
    assert store[0] == "0 5 * * * otra-cosa" and not any("vieja" in line for line in store)
    assert store[1].startswith("0 21 * * * cd ") and f"'{root / 'python'}'" in store[1]
    assert store[-1].startswith("@reboot sleep 300 && ")
    st = sched.status_cron()
    assert st["installed"] and st["program"] == str(root / ".venv/bin/python") and st["times"] == ["21:00", "21:30"]
    assert sched.remove_cron() and store == ["0 5 * * * otra-cosa"]


@pytest.mark.skipif(os.name == "nt", reason="PATH de cron y launchd (macOS y Linux)")
def test_the_task_finds_the_git_the_installer_used(tmp_path, monkeypatch):
    """cron corre con PATH=/usr/bin:/bin: un git en otra carpeta (linuxbrew,
    /opt/local) no se encontraría al subir la copia."""
    import plistlib

    git_dir = tmp_path / "otro git" / "bin"
    git_dir.mkdir(parents=True)
    (git_dir / "git").write_text("#!/bin/sh\necho 'git version 9'\n", encoding="utf-8")
    (git_dir / "git").chmod(0o755)
    monkeypatch.setattr(sched.shutil, "which", lambda name: str(git_dir / name) if name == "git" else None)
    root = tmp_path / "recolector"
    assert sched.task_path().split(":")[0] == str(git_dir) and "/usr/bin" in sched.task_path().split(":")
    data = plistlib.loads(sched.launchd_plist("/x/.venv/bin/python", root, ["21:00"]))
    assert data["EnvironmentVariables"]["PATH"] == sched.task_path()
    cmd = sched.cron_command(sys.executable, root)
    assert f"PATH={shlex.quote(sched.task_path())} ENSO_HOME=" in cmd
    # El mismo «PATH=…» que va en la línea de cron, con el entorno mínimo de cron.
    r = subprocess.run(["/bin/sh", "-c", f"PATH={shlex.quote(sched.task_path())} sh -c 'git --version'"],
                       env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True)
    assert r.stdout.strip() == "git version 9", r.stderr


# --- Verificación ------------------------------------------------------------------

def test_check_reports_and_saves(home, monkeypatch, capsys):
    monkeypatch.setattr(svc, "ROOT", home)
    monkeypatch.setattr(svc, "use_system_certificates", lambda: False)
    code = chk.main(["--solo", "python,disco,ultima-corrida", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["ok"] and {r["id"] for r in out["results"]} == {"python", "disco", "ultima-corrida"}
    report = Path(out["report"])
    assert report.parent == home / "logs" and "RESULTADO" in report.read_text(encoding="utf-8")


def test_check_explains_missing_token(home):
    r = chk.check_token({"root": home, "origin": {}})
    assert r.level == chk.FAIL and "token" in r.hint.lower()


def test_check_sources_verdicts(monkeypatch):
    monkeypatch.setattr(chk, "_probe", lambda url: {"url": url, "ok": False, "why": "ConnectError", "bytes": 0, "s": 1.0})
    assert chk.check_sources({}).level == chk.FAIL
    monkeypatch.setattr(chk, "_probe", lambda url: {"url": url, "ok": "senamhi" in url or "ana" in url,
                                                     "why": "HTTP 200", "bytes": 900, "s": 1.0})
    assert chk.check_sources({}).level == chk.WARN  # el ENFEN no responde
    monkeypatch.setattr(chk, "_probe", lambda url: {"url": url, "ok": True, "why": "HTTP 200", "bytes": 900, "s": 1.0})
    assert chk.check_sources({}).level == chk.OK


def test_check_flags_tampered_or_missing_kit_files(home):
    (home / "config" / "threshold-policies").mkdir(parents=True)
    (home / "config" / "threshold-policies" / "expert-grd-image-v1.yaml").write_text("x", encoding="utf-8")
    (home / "a.py").write_text("bueno", encoding="utf-8")
    import hashlib

    manifest = {"files": {"a.py": hashlib.sha256(b"bueno").hexdigest()}}
    (home / "kit.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert chk.check_code({"root": home}).level == chk.OK
    (home / "a.py").write_text("editado", encoding="utf-8")
    assert chk.check_code({"root": home}).level == chk.WARN
    (home / "a.py").unlink()
    assert chk.check_code({"root": home}).level == chk.FAIL


def test_check_last_run_levels(home):
    ctx = {"root": home}
    assert chk.check_last_run(ctx).level == chk.INFO
    now = datetime.now(timezone.utc)
    svc.write_state({"last_attempt": now.isoformat(), "last_success": now.isoformat(), "result": "ok"}, home)
    assert chk.check_last_run(ctx).level == chk.OK
    svc.write_state({"last_attempt": now.isoformat(), "last_success": (now - timedelta(days=3)).isoformat(),
                     "result": "falla", "detail": "x", "hint": "y", "consecutive_failures": 6}, home)
    r = chk.check_last_run(ctx)
    assert r.level == chk.FAIL and r.hint == "y"


# --- Kit -------------------------------------------------------------------------------

def test_kit_is_complete_reproducible_and_runs_alone(tmp_path):
    a, sha_a = kit.build(tmp_path / "a")
    b, sha_b = kit.build(tmp_path / "b")
    assert sha_a == sha_b  # reproducible
    with zipfile.ZipFile(a) as z:
        names = set(z.namelist())
        root = "recolector-peru/"
        for must in ("INSTALAR-Windows.cmd", "INSTALAR-Mac.command", "VERIFICAR-Windows.cmd", "VERIFICAR-Mac.command",
                     "LEEME.txt", "kit.json", "python/requirements.txt", "python/tools/peru_collector.py",
                     "collector/instalar.ps1", "collector/instalar.sh", "docs/servidor-peru.md",
                     "otras-acciones/DESINSTALAR-Windows.cmd", "config/threshold-policies/expert-grd-image-v1.yaml"):
            assert root + must in names, must
        assert not any("__pycache__" in n or "/tests/" in n or n.endswith(".env") for n in names)
        cmd = z.read(root + "VERIFICAR-Windows.cmd")
        assert b"\r\n" in cmd and b"\n" not in cmd.replace(b"\r\n", b"")
        assert z.read(root + "collector/instalar.ps1").startswith(kit.BOM)
        assert b"\r" not in z.read(root + "collector/instalar.sh")
        assert (z.getinfo(root + "INSTALAR-Mac.command").external_attr >> 16) & 0o111
        manifest = json.loads(z.read(root + "kit.json"))
        assert set(manifest["files"]) == {n.removeprefix(root) for n in names} - {"kit.json"}
        z.extractall(tmp_path / "x")
    # El código del kit carga solo, sin el repositorio.
    code = ("import sys; sys.path.insert(0, sys.argv[1]); "
            "import tools.peru_collector, tools.collector_service, tools.collector_check, tools.collector_schedule")
    r = subprocess.run([sys.executable, "-I", "-c", code, str(tmp_path / "x" / "recolector-peru" / "python")],
                       capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 0, r.stderr


def _github_glob(pattern: str) -> re.Pattern:
    """Filtro de rutas de GitHub Actions: ``*`` no cruza «/», ``**`` sí (también ninguna carpeta)."""
    rx = re.escape(pattern).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    return re.compile(rx + r"\Z")


def test_every_kit_file_rebuilds_the_kit():
    """Un cambio en cualquier archivo del kit tiene que volver a probarlo y publicarlo."""
    import yaml

    wf = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "recolector-kit.yml").read_text(encoding="utf-8"))
    on = wf.get("on", wf.get(True))  # YAML 1.1 lee «on» como True
    push, pr = on["push"]["paths"], on["pull_request"]["paths"]
    assert push == pr
    globs = [_github_glob(g) for g in pr]
    missing = [rel for rel in (src.relative_to(REPO_ROOT).as_posix() for src in kit.kit_files(REPO_ROOT).values())
               if not any(g.match(rel) for g in globs)]
    assert missing == []
    assert not _github_glob("python/tools/collector_*.py").match("python/tools/sub/collector_x.py")


def test_kit_carries_the_site_contact_and_env_file_wins(tmp_path, home, monkeypatch):
    monkeypatch.setenv("ENSO_CONTACT_URL", "https://observatorio.example.pe/")
    zpath, _ = kit.build(tmp_path / "k")
    with zipfile.ZipFile(zpath) as z:
        manifest = json.loads(z.read("recolector-peru/kit.json"))
    assert manifest["contact_url"] == "https://observatorio.example.pe/"
    (home / "kit.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.delenv("ENSO_CONTACT_URL")
    svc.use_kit_defaults(home)
    assert svc.os.environ["ENSO_CONTACT_URL"] == "https://observatorio.example.pe/"
    monkeypatch.setenv("ENSO_CONTACT_URL", "https://otro.example/")  # puesto en .env por quien instala
    svc.use_kit_defaults(home)
    assert svc.os.environ["ENSO_CONTACT_URL"] == "https://otro.example/"


@pytest.mark.parametrize("reply,level", [
    # Repositorio privado y token vencido: GitHub contesta, la conexión está bien.
    (lambda req: httpx.Response(401 if "authorization" in req.headers else 404,
                                headers={"x-github-request-id": "AB12:3"}, json={"message": "Not Found"}), "OK"),
    # Un portal de wifi contesta cualquier cosa con su página.
    (lambda req: httpx.Response(200, text="<html>Acepte las condiciones</html>"), "FAIL"),
])
def test_internet_check_with_a_private_repo_or_a_captive_portal(home, monkeypatch, reply, level):
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.setattr(chk, "_client", lambda timeout=20.0: httpx.Client(transport=httpx.MockTransport(reply)))
    results = chk.check_internet({"root": home})
    assert results[0].level == getattr(chk, level), results


def test_internet_check_dates_the_copy_from_its_index_not_the_heartbeat_commit(home, monkeypatch):
    """Una corrida sin fuentes sube solo el latido: el último commit es reciente,
    pero la copia que usa el sitio sigue siendo la de hace dos días."""
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    now = datetime.now(timezone.utc)
    iso = lambda h: (now - timedelta(hours=h)).isoformat(timespec="seconds")  # noqa: E731
    files = {"index.json": {"schema": "enso-relay/1", "collected_at": iso(50), "entries": []},
             "heartbeat.json": {"schema": "enso-relay-heartbeat/1", "at": iso(1), "result": "sin-fuentes",
                                "reachable": "0/11"}}
    broken = set()

    def reply(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path.endswith("/branches/data-peru"):
            return httpx.Response(200, json={"commit": {"commit": {"committer": {"date": iso(1)},
                                                                   "message": "latido: sin fuentes"}}})
        if "/contents/" in path:
            assert req.url.params["ref"] == "data-peru" and "raw" in req.headers["accept"]
            name = path.rsplit("/", 1)[-1]
            if name in broken:
                return httpx.Response(502)
            return httpx.Response(200, json=files[name]) if name in files else httpx.Response(404)
        return httpx.Response(200, json={"full_name": chk.repo()}, headers={"date": now.strftime("%a, %d %b %Y %H:%M:%S GMT")})

    monkeypatch.setattr(chk, "_client", lambda timeout=20.0: httpx.Client(transport=httpx.MockTransport(reply)))
    results = chk.check_internet({"root": home})
    copy = next(r for r in results if r.title.startswith("última copia"))
    assert copy.level == chk.WARN and "hace 50 h" in copy.title and "index.json" in copy.detail
    beat = next(r for r in results if r.title.startswith("último latido"))
    assert "ninguna fuente respondió" in beat.title and "relay-sources-down" in beat.hint
    # Si index.json no se pudo leer, se usa la fecha del commit.
    broken.add("index.json")
    copy = next(r for r in chk.check_internet({"root": home}) if r.title.startswith("última copia"))
    assert copy.level == chk.INFO and "hace 1 h" in copy.title and "commit" in copy.detail
    # Sin index.json (la primera corrida no alcanzó ninguna fuente) no hay copia, por reciente que sea el commit.
    broken.clear()
    files.pop("index.json")
    results = chk.check_internet({"root": home})
    assert not any(r.title.startswith("última copia") for r in results)
    assert any(r.level == chk.WARN and "ninguna copia" in r.title for r in results)
    assert any(r.title.startswith("último latido") and r.level == chk.WARN for r in results)


def test_launchers_only_use_options_the_installers_know():
    ps1 = (REPO_ROOT / "collector" / "instalar.ps1").read_text(encoding="utf-8-sig")
    sh = (REPO_ROOT / "collector" / "instalar.sh").read_text(encoding="utf-8")
    params = set(re.findall(r"\[(?:switch|string)\]\$(\w+)", ps1))
    for f in (REPO_ROOT / "collector" / "lanzadores").rglob("*.cmd"):
        for flag in re.findall(r'"%S%" ((?:-\w+ )*)', f.read_text(encoding="ascii"))[0].split():
            assert flag[1:] in params, (f.name, flag)
    for f in (REPO_ROOT / "collector" / "lanzadores").rglob("*.command"):
        for flag in re.findall(r"--[a-z-]+", f.read_text(encoding="utf-8")):
            assert re.search(rf"^\s+{flag}\)", sh, re.M), (f.name, flag)


def find_bash() -> str | None:
    """bash de Git en Windows: el de System32 es WSL y sin una distro instalada no corre nada."""
    if os.name != "nt":
        return shutil.which("bash")
    git = shutil.which("git")
    if git:
        for base in Path(git).resolve().parents[:2]:
            for rel in ("bin/bash.exe", "usr/bin/bash.exe"):
                if (base / rel).exists():
                    return str(base / rel)
    return None


def test_install_script_is_valid_bash():
    bash = find_bash()
    if not bash:
        pytest.skip("no hay bash en este equipo")
    r = subprocess.run([bash, "-n", str(REPO_ROOT / "collector" / "instalar.sh")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(os.name == "nt", reason="instalar.sh es para macOS y Linux")
def test_uninstall_keeps_the_folder_when_the_task_cannot_be_removed(tmp_path, monkeypatch):
    """Borrar la carpeta con la tarea todavía puesta dejaría una tarea que falla cada noche."""
    dest = _install(tmp_path / "instalacion")
    (dest / "python").mkdir()
    fake = dest / ".venv" / "bin" / "python"
    fake.parent.mkdir(parents=True)
    fake.write_text("#!/bin/sh\necho 'ERROR: crontab no aceptó los cambios' >&2\nexit 1\n", encoding="utf-8")
    fake.chmod(0o755)
    env = {**os.environ, "HOME": str(tmp_path), "ENSO_SIN_PAUSA": "1"}
    r = subprocess.run(["bash", str(REPO_ROOT / "collector" / "instalar.sh"), "--desinstalar", "--no-interactivo",
                        "--destino", str(dest)], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode != 0 and dest.is_dir(), r.stdout + r.stderr
    assert "no se borró" in r.stdout + r.stderr


@pytest.mark.skipif(os.name == "nt", reason="instalar.sh es para macOS y Linux")
def test_install_from_a_repository_checkout_brings_the_launchers(tmp_path):
    """En el repositorio los lanzadores están en collector/lanzadores; instalados van en la raíz."""
    dest = tmp_path / "desde el repo"
    env = {**os.environ, "ENSO_SIN_PAUSA": "1"}  # --sin-tarea: no toca nada fuera de dest (y usa la caché de pip)
    r = subprocess.run(["bash", str(REPO_ROOT / "collector" / "instalar.sh"), "--no-interactivo", "--sin-tarea",
                        "--sin-verificar", "--destino", str(dest)], capture_output=True, text=True, env=env, timeout=600)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    for name in ("VERIFICAR-Mac.command", "VERIFICAR-Windows.cmd", "INSTALAR-Mac.command", "LEEME.txt",
                 "otras-acciones/DESINSTALAR-Mac.command", "otras-acciones/ACTUALIZAR-Windows.cmd"):
        assert (dest / name).is_file(), name
    assert os.access(dest / "otras-acciones" / "DESINSTALAR-Mac.command", os.X_OK)
    assert (dest / ".instalacion-recolector").is_file()


@pytest.mark.skipif(os.name == "nt", reason="instalar.sh es para macOS y Linux")
def test_installer_stops_when_the_kit_cannot_be_copied(tmp_path):
    """Instalar no tiene «set -e»: una copia que falla (disco lleno) debe parar
    antes del entorno de Python y de la tarea, y dejar la instalación en uso intacta."""
    real_cp = shutil.which("cp")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "cp").write_text(
        f"#!/bin/sh\nfor a in \"$@\"; do case \"$a\" in */config) echo 'cp: No space left on device' >&2; exit 1 ;; esac; done\n"
        f"exec '{real_cp}' \"$@\"\n", encoding="utf-8")
    (bin_dir / "cp").chmod(0o755)
    # Una instalación en uso: la tarea programada la sigue corriendo si la copia nueva falla.
    dest = _install(tmp_path / "recolector")
    for rel in ("python/tools/collector_service.py", "config/threshold-policies/a.yaml", "collector/instalar.sh"):
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / rel).write_text("anterior\n", encoding="utf-8")
    def code():  # sin la marca (se reescribe) ni el registro de la instalación
        return {p.relative_to(dest): p.read_bytes() for p in dest.rglob("*")
                if p.is_file() and p.name != sched.MARKER and "logs" not in p.relative_to(dest).parts}
    before = code()
    env = {**os.environ, "HOME": str(tmp_path), "ENSO_SIN_PAUSA": "1", "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(["bash", str(REPO_ROOT / "collector" / "instalar.sh"), "--no-interactivo", "--sin-tarea",
                        "--sin-verificar", "--destino", str(dest)], capture_output=True, text=True, env=env, timeout=120)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "No se pudieron copiar" in out and "quedó como estaba" in out, out
    assert not (dest / ".venv").exists() and not (dest / ".instalando").exists()
    assert code() == before


@pytest.mark.skipif(os.name == "nt", reason="instalar.sh es para macOS y Linux")
def test_installer_never_takes_over_or_deletes_someone_elses_folder(tmp_path):
    """Con --destino en una carpeta ajena (un proyecto con su .venv), instalar
    se niega antes de tocar nada y desinstalar no la borra."""
    dest = tmp_path / "mi-proyecto"
    (dest / "config").mkdir(parents=True)
    (dest / "config" / "ajustes.yaml").write_text("mio: 1\n", encoding="utf-8")
    (dest / "python").mkdir()
    (dest / "kit.json").write_text("{}", encoding="utf-8")
    fake = dest / ".venv" / "bin" / "python"
    fake.parent.mkdir(parents=True)
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")  # quitar la tarea «funciona»
    fake.chmod(0o755)
    before = sorted(p.relative_to(dest) for p in dest.rglob("*"))
    env = {**os.environ, "HOME": str(tmp_path), "ENSO_SIN_PAUSA": "1"}
    script = str(REPO_ROOT / "collector" / "instalar.sh")
    r = subprocess.run(["bash", script, "--no-interactivo", "--sin-verificar", "--sin-tarea", "--destino", str(dest)],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode != 0 and "no es una instalación del recolector" in r.stdout + r.stderr, r.stdout + r.stderr
    r = subprocess.run(["bash", script, "--desinstalar", "--no-interactivo", "--destino", str(dest)],
                       capture_output=True, text=True, env=env, timeout=60)
    assert "no parece una instalación" in r.stdout + r.stderr, r.stdout + r.stderr
    assert sorted(p.relative_to(dest) for p in dest.rglob("*")) == before


@pytest.mark.skipif(os.name == "nt", reason="instalar.sh es para macOS y Linux")
@pytest.mark.parametrize("stuck", [False, True])
def test_uninstall_without_python_on_macos_checks_legacy_loaded_agents(tmp_path, stuck):
    """Sin .venv, DESINSTALAR en macOS quita el agente con launchctl; uno cargado
    con «load» (sin sesión gráfica) solo se ve en «launchctl list»."""
    label = "io.github.pillb.observatorio-enso.recolector"
    dest = tmp_path / "instalacion"
    dest.mkdir()
    (dest / ".instalacion-recolector").write_text("recolector\n", encoding="utf-8")
    plist = tmp_path / "Library" / "LaunchAgents" / f"{label}.plist"
    plist.parent.mkdir(parents=True)
    plist.write_text("<plist/>", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "launchctl.log"
    (bin_dir / "uname").write_text("#!/bin/sh\necho Darwin\n", encoding="utf-8")
    listed = f"echo '123\t0\t{label}'" if stuck else "echo '-\t0\tcom.apple.otro'"
    (bin_dir / "launchctl").write_text(
        f"#!/bin/sh\necho \"$1\" >> '{log}'\ncase \"$1\" in\n  print) exit 113 ;;\n"
        f"  list) echo 'PID\tStatus\tLabel'; {listed} ;;\n  *) exit {5 if stuck else 0} ;;\nesac\n", encoding="utf-8")
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    env = {**os.environ, "HOME": str(tmp_path), "ENSO_SIN_PAUSA": "1", "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(["bash", str(REPO_ROOT / "collector" / "instalar.sh"), "--desinstalar", "--no-interactivo",
                        "--destino", str(dest)], capture_output=True, text=True, env=env, timeout=60)
    assert log.read_text().split()[:2] == ["bootout", "unload"]
    if stuck:
        assert r.returncode != 0 and dest.exists() and plist.exists(), r.stdout + r.stderr
    else:
        assert r.returncode == 0 and not dest.exists() and not plist.exists(), r.stdout + r.stderr


@pytest.mark.skipif(sys.platform != "linux", reason="el respaldo sin Python usa cron (Linux)")
@pytest.mark.parametrize("message, deleted", [("no crontab for pablo", True),
                                               ("You (pablo) are not allowed to use this program", False)])
def test_uninstall_without_python_reads_the_crontab_before_rewriting_it(tmp_path, message, deleted):
    """Sin .venv, DESINSTALAR quita las líneas con crontab directamente: un
    crontab ilegible no se reescribe vacío ni se da por quitado."""
    dest = tmp_path / "instalacion"
    dest.mkdir()
    (dest / ".instalacion-recolector").write_text("recolector\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "crontab.log"
    fake = bin_dir / "crontab"
    fake.write_text(f"#!/bin/sh\necho \"$*\" >> '{log}'\n[ \"$1\" = -l ] && {{ echo '{message}' >&2; exit 1; }}\n"
                    "cat >/dev/null\n", encoding="utf-8")
    fake.chmod(0o755)
    env = {**os.environ, "HOME": str(tmp_path), "ENSO_SIN_PAUSA": "1", "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(["bash", str(REPO_ROOT / "collector" / "instalar.sh"), "--desinstalar", "--no-interactivo",
                        "--destino", str(dest)], capture_output=True, text=True, env=env, timeout=60)
    assert dest.exists() is not deleted, r.stdout + r.stderr
    assert "-" not in log.read_text().split(), "no debe reescribir el crontab"
    assert (r.returncode == 0) is deleted


@pytest.mark.parametrize("stderr, lines", [
    ("no crontab for pablo\n", []),                                   # cronie, Debian
    ("crontab: no crontab for pablo\n", []),                          # macOS
    ("crontab: can't open 'pablo': No such file or directory\n", []),  # busybox
    ("You (pablo) are not allowed to use this program (crontab)\n", None),
    ("crontab: your UID isn't in the passwd file. bailing out.\n", None),
])
def test_unreadable_crontab_is_not_read_as_empty(tmp_path, monkeypatch, stderr, lines):
    """Leer el crontab como vacío por un error haría que instalar borre las
    líneas ajenas y que desinstalar borre la carpeta con la tarea puesta."""
    writes = []
    monkeypatch.setattr(sched.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(sched.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", stderr))
    monkeypatch.setattr(sched, "_crontab_write", writes.append)
    if lines is not None:
        assert sched._crontab_read() == lines and sched.remove_cron() is False
        return
    with pytest.raises(RuntimeError, match="no se pudo leer el crontab"):
        sched.install_cron(str(tmp_path / ".venv/bin/python"), tmp_path, ["21:00"])
    with pytest.raises(RuntimeError):
        sched.remove_cron()
    assert writes == []
    assert not sched.status_cron()["installed"] and "no se pudo leer" in sched.status_cron()["detail"]
    monkeypatch.setattr(sched, "remove", sched.remove_cron)
    assert sched.main(["quitar"]) == 1


@pytest.mark.parametrize("refuses", [False, True])
def test_launchd_agent_is_gone_before_reporting_it_removed(tmp_path, monkeypatch, refuses):
    """Si launchd no suelta el agente, el plist se queda y quitar falla:
    borrar la carpeta dejaría un agente que falla cada noche."""
    plist = tmp_path / "LaunchAgents" / f"{sched.LAUNCHD_LABEL}.plist"
    plist.parent.mkdir()
    plist.write_bytes(b"<plist/>")
    loaded = [True]
    calls = []

    def launchctl(*args):
        calls.append(args[0])
        if args[0] == "print":
            return subprocess.CompletedProcess(args, 0 if loaded[0] else 113, "", "")
        if args[0] == "list":
            return subprocess.CompletedProcess(args, 0, "PID\tStatus\tLabel\n-\t0\tcom.apple.otro\n", "")
        if refuses:
            return subprocess.CompletedProcess(args, 5, "", "Boot-out failed: 5: Input/output error")
        if not loaded[0]:
            return subprocess.CompletedProcess(args, 3, "", "Boot-out failed: 3: No such process")
        loaded[0] = False
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(sched, "launchd_path", lambda: plist)
    monkeypatch.setattr(sched, "_launchctl", launchctl)
    monkeypatch.setattr(sched.os, "getuid", lambda: 501, raising=False)
    monkeypatch.setattr(sched.time, "sleep", lambda s: None)
    if refuses:
        with pytest.raises(RuntimeError, match="sigue con el agente.*Input/output"):
            sched.remove_launchd()
        assert plist.exists() and calls[:2] == ["bootout", "unload"]
    else:
        assert sched.remove_launchd() and not plist.exists()
        assert sched.remove_launchd() is False  # ya no estaba: nada que quitar


def test_uninstall_where_cron_was_never_available(monkeypatch, capsys):
    """Sin crontab el instalador sigue sin tarea; desinstalar no debe quedar bloqueado por eso."""
    monkeypatch.setattr(sched.shutil, "which", lambda name: None)
    monkeypatch.setattr(sched.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("crontab")))
    monkeypatch.setattr(sched, "remove", sched.remove_cron)
    assert sched.main(["quitar"]) == 0 and "No había tarea" in capsys.readouterr().out


def _install(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / sched.MARKER).write_text("recolector\n", encoding="utf-8")
    return root


@pytest.mark.parametrize("owner, removed", [("otra", False), ("borrada", True), ("esta", True), (None, True)])
def test_removing_the_task_leaves_another_install_running(tmp_path, monkeypatch, capsys, owner, removed):
    """La tarea es una por usuario y la toma la última instalación: desinstalar
    otra carpeta no la quita mientras la instalación a la que apunta siga ahí."""
    here = _install(tmp_path / "esta")
    roots = {"otra": _install(tmp_path / "otra"), "borrada": tmp_path / "borrada", "esta": here, None: None}
    calls = []
    monkeypatch.setattr(sched, "ROOT", here)
    monkeypatch.setattr(sched, "task_root", lambda: roots[owner])
    monkeypatch.setattr(sched, "remove", lambda: calls.append("remove") or True)
    assert sched.main(["quitar"]) == 0
    assert bool(calls) is removed
    assert ("no se tocó" in capsys.readouterr().out) is not removed


def test_task_root_reads_the_install_folder_from_cron_and_launchd(tmp_path, monkeypatch):
    root = tmp_path / "mi recolector"
    py = str(root / ".venv" / "bin" / "python")
    monkeypatch.setattr(sched.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(sched, "_crontab_read", lambda: ["0 7 * * * otra cosa", *sched.cron_lines(py, root, ["21:00"])])
    assert sched._cron_root() == root
    monkeypatch.setattr(sched, "_crontab_read", lambda: ["0 7 * * * otra cosa"])
    assert sched._cron_root() is None
    plist = tmp_path / "agente.plist"
    plist.write_bytes(sched.launchd_plist(py, root, ["21:00"]))
    monkeypatch.setattr(sched, "launchd_path", lambda: plist)
    assert sched._launchd_root() == root


def test_task_test_starts_an_agent_loaded_without_a_gui_session(monkeypatch):
    """Un agente cargado con «load» (por SSH) no está en gui/<uid>: kickstart falla y se usa «start»."""
    calls = []
    monkeypatch.setattr(sched, "_launchctl", lambda *a: calls.append(a[0]) or subprocess.CompletedProcess(
        a, 113 if a[0] == "kickstart" else 0, "", ""))
    monkeypatch.setattr(sched.os, "getuid", lambda: 501, raising=False)
    assert sched.kick_launchd() and calls == ["kickstart", "start"]


def test_check_warns_when_the_task_runs_another_install(home, monkeypatch):
    other = home / "otra"
    monkeypatch.setattr(sched, "status", lambda: {"kind": "cron", "installed": True, "program": sys.executable})
    monkeypatch.setattr(sched, "owner_elsewhere", lambda root: other)
    r = chk.check_schedule({"root": home})
    assert r.level == chk.WARN and str(other) in r.title


@pytest.mark.skipif(sys.platform != "linux", reason="el respaldo sin Python usa cron (Linux)")
@pytest.mark.parametrize("case", ["otra", "ajena", "borrada", "esta"])
def test_uninstall_never_takes_the_task_from_the_install_in_use(tmp_path, case):
    """Con un --destino equivocado (otra instalación, una carpeta ajena), las
    líneas del crontab de la instalación en uso se quedan; las de esta carpeta,
    o las de una carpeta ya borrada, se quitan."""
    here, other, foreign = _install(tmp_path / "esta"), _install(tmp_path / "otra"), tmp_path / "mi-proyecto"
    foreign.mkdir()
    (foreign / "notas.txt").write_text("mio\n", encoding="utf-8")
    owner = {"otra": other, "ajena": other, "borrada": tmp_path / "borrada", "esta": here}[case]
    dest = {"ajena": foreign, "borrada": tmp_path / "borrada"}.get(case, here)
    tab, log = tmp_path / "crontab.txt", tmp_path / "crontab.log"
    mine = sched.cron_lines(str(owner / ".venv" / "bin" / "python"), owner, ["21:00"])
    tab.write_text("\n".join(["0 7 * * * otra cosa", *mine]) + "\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "crontab").write_text(
        f"#!/bin/sh\ncase \"$1\" in\n  -l) cat '{tab}' ;;\n  -) cat > '{tab}'; echo escrito >> '{log}' ;;\nesac\n",
        encoding="utf-8")
    (bin_dir / "crontab").chmod(0o755)
    env = {**os.environ, "HOME": str(tmp_path), "ENSO_SIN_PAUSA": "1", "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(["bash", str(REPO_ROOT / "collector" / "instalar.sh"), "--desinstalar", "--no-interactivo",
                        "--destino", str(dest)], capture_output=True, text=True, env=env, timeout=60)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    kept = case in ("otra", "ajena")
    assert (tab.read_text(encoding="utf-8").count("observatorio-enso-recolector") == len(mine)) is kept, out
    assert log.exists() is not kept and "otra cosa" in tab.read_text(encoding="utf-8")
    assert ("es de la instalación en" in out) is kept, out
    assert other.is_dir() and foreign.joinpath("notas.txt").is_file()
    assert here.exists() is (case in ("ajena", "borrada"))


@pytest.mark.skipif(sys.platform != "darwin", reason="lee el agente con PlistBuddy (macOS)")
def test_uninstall_on_macos_leaves_the_agent_of_the_install_in_use(tmp_path):
    here, other = _install(tmp_path / "esta"), _install(tmp_path / "otra")
    plist = tmp_path / "Library" / "LaunchAgents" / f"{sched.LAUNCHD_LABEL}.plist"
    plist.parent.mkdir(parents=True)
    plist.write_bytes(sched.launchd_plist(str(other / ".venv" / "bin" / "python"), other, ["21:00"]))
    bin_dir, log = tmp_path / "bin", tmp_path / "launchctl.log"
    bin_dir.mkdir()
    (bin_dir / "launchctl").write_text(f"#!/bin/sh\necho \"$1\" >> '{log}'\n", encoding="utf-8")
    (bin_dir / "launchctl").chmod(0o755)
    env = {**os.environ, "HOME": str(tmp_path), "ENSO_SIN_PAUSA": "1", "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(["bash", str(REPO_ROOT / "collector" / "instalar.sh"), "--desinstalar", "--no-interactivo",
                        "--destino", str(here)], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0 and "es de la instalación en" in r.stdout + r.stderr, r.stdout + r.stderr
    assert not here.exists() and other.is_dir() and plist.exists() and not log.exists()


@pytest.mark.skipif(os.name == "nt", reason="instalar.sh es para macOS y Linux")
def test_installer_resolves_a_relative_destination(tmp_path):
    """--destino ./carpeta: in_python cambia de carpeta antes de usar la ruta del .venv."""
    env = {**os.environ, "ENSO_SIN_PAUSA": "1"}
    r = subprocess.run(["bash", str(REPO_ROOT / "collector" / "instalar.sh"), "--no-interactivo", "--sin-verificar",
                        "--sin-tarea", "--destino", "./relativa"], capture_output=True, text=True, env=env,
                       cwd=tmp_path, timeout=600)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert f"Carpeta de instalación: {tmp_path / 'relativa'}" in r.stdout
    r = subprocess.run(["bash", str(tmp_path / "relativa" / "VERIFICAR-Mac.command"), "--solo", "python"],
                       capture_output=True, text=True, env=env, cwd=tmp_path, timeout=120)
    assert "Python 3." in r.stdout, r.stdout[-2000:] + r.stderr[-2000:]


def test_schedule_cli_reports_a_failed_removal(monkeypatch, capsys):
    monkeypatch.setattr(sched, "remove", lambda: (_ for _ in ()).throw(RuntimeError("crontab no aceptó los cambios")))
    assert sched.main(["quitar"]) == 1
    assert "crontab no aceptó" in capsys.readouterr().err


def test_windows_launchers_return_the_installer_exit_code():
    """«powershell ... & exit /b» en la misma línea devolvía 0 aunque el instalador fallara."""
    for f in (REPO_ROOT / "collector" / "lanzadores").rglob("*.cmd"):
        lines = f.read_text(encoding="ascii").splitlines()
        assert "& exit /b" not in "\n".join(lines), f.name
        assert lines[-2].startswith("powershell.exe ") and lines[-1] == "exit /b %ERRORLEVEL%", f.name


def test_launchers_that_replace_their_folder_run_from_a_temp_copy():
    """cmd relee el .cmd mientras corre y no deja borrar su carpeta actual."""
    for name in ("DESINSTALAR-Windows.cmd", "ACTUALIZAR-Windows.cmd"):
        text = (REPO_ROOT / "collector" / "lanzadores" / "otras-acciones" / name).read_text(encoding="ascii")
        assert 'cd /d "%TEMP%"' in text and '"%TEMP%\\observatorio-enso-%~nx0" %*' in text, name
        assert text.index("goto run") < text.index("copy /y") < text.index(":run"), name


def test_site_run_warns_before_the_collector_token_expires(tmp_path):
    """La corrida diaria abre un issue «relay-token-expiring» 21 días antes."""
    from enso import observatory as obs

    def relay_with(expires):
        root = tmp_path / f"relay-{expires[:10]}"
        root.mkdir()
        (root / "index.json").write_text(json.dumps({
            "schema": "enso-relay/1", "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "collector": {"host": "pc-lima", "token_expires_at": expires}, "entries": []}), encoding="utf-8")
        log = obs.EventLog()
        obs.load_relay(root, log)
        return [e.code for e in log.events]

    soon = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    later = (datetime.now(timezone.utc) + timedelta(days=200)).isoformat()
    assert "relay-token-expiring" in relay_with(soon)
    assert "relay-token-expiring" not in relay_with(later)
