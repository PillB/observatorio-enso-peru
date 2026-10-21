"""Corrida programada del recolector, su tarea programada, la verificación y el kit."""

from __future__ import annotations

import json
import os
import re
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


def _all_sources_down(monkeypatch):
    def down(req):
        raise httpx.ConnectError("Temporary failure in name resolution")

    real = httpx.Client
    monkeypatch.setattr(pc.httpx, "Client", lambda **kw: real(**{"transport": httpx.MockTransport(down), **kw}))


def test_nothing_answered_keeps_the_copy_and_pushes_a_heartbeat(home, peru_network, remote, monkeypatch):
    assert svc.run(root=home) == svc.EXIT_OK
    good = remote_index(remote)
    assert remote_file(remote, pc.HEARTBEAT)["result"] == "ok"
    _all_sources_down(monkeypatch)
    assert svc.run(root=home) == svc.EXIT_NO_SOURCES
    assert "solo el latido" in svc.read_state(home)["detail"]
    assert remote_index(remote) == good  # la última copia buena sigue ahí
    hb = remote_file(remote, pc.HEARTBEAT)
    assert hb["schema"] == "enso-relay-heartbeat/1" and hb["result"] == "sin-fuentes"
    assert hb["reachable"].startswith("0/") and hb["failures"] and hb["collector"]["runner"]


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
    sched.install_cron(str(root / ".venv/bin/python"), root, ["21:00", "21:30"])
    assert store[0] == "0 5 * * * otra-cosa" and not any("vieja" in line for line in store)
    assert store[1].startswith("0 21 * * * cd ") and f"'{root / 'python'}'" in store[1]
    assert store[-1].startswith("@reboot sleep 300 && ")
    st = sched.status_cron()
    assert st["installed"] and st["program"] == str(root / ".venv/bin/python") and st["times"] == ["21:00", "21:30"]
    assert sched.remove_cron() and store == ["0 5 * * * otra-cosa"]


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
