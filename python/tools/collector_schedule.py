"""Tarea programada del recolector en cada sistema.

* Windows: el Programador de tareas. La registra ``collector/instalar.ps1``
  (con los cmdlets de PowerShell); aquí solo se consulta y se dispara.
* macOS: un agente de launchd en ``~/Library/LaunchAgents``.
* Linux (Raspberry Pi incluida): líneas en el crontab del usuario.

La tarea se dispara a la hora de Lima indicada (21:00) y luego cada 30
minutos hasta las 23:30, además de al iniciar sesión o al encender. Cada
disparo corre ``tools.collector_service --programado``, que solo recolecta
si todavía falta la copia del día: los disparos extra son reintentos y la
recuperación de una recolección perdida con el equipo apagado.

Uso (lo llaman los instaladores):
  python -m tools.collector_schedule horas [--hora 21:00]   # horas locales de los disparos
  python -m tools.collector_schedule instalar --python RUTA [--hora 21:00]
  python -m tools.collector_schedule quitar
  python -m tools.collector_schedule estado
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

LIMA = ZoneInfo("America/Lima")
ROOT = Path(os.environ.get("ENSO_HOME") or Path(__file__).resolve().parents[2])
WINDOWS_TASK = "Observatorio ENSO - recolector Peru"
#: Nombre que usaba la versión anterior (collector/windows-tarea.ps1).
OLD_WINDOWS_TASK = "ENSO recolector Peru"
LAUNCHD_LABEL = "io.github.pillb.observatorio-enso.recolector"
CRON_TAG = "# observatorio-enso-recolector"
RETRY_EVERY_MIN = 30
RETRY_SPAN_H = 3
COMMAND = ["-m", "tools.collector_service", "--programado"]


def lima_slots(at: str = "21:00") -> list[tuple[int, int]]:
    h, m = (int(x) for x in at.split(":"))
    start = h * 60 + m
    return [divmod((start + k * RETRY_EVERY_MIN) % 1440, 60) for k in range(RETRY_SPAN_H * 60 // RETRY_EVERY_MIN)]


def local_times(at: str = "21:00", tz: Optional[ZoneInfo] = None, day: Optional[date] = None) -> list[str]:
    """Horas locales (HH:MM) de los disparos que caen a ``at`` de Lima y sus reintentos.
    Perú no tiene horario de verano; si el equipo usa otra zona con horario
    de verano, la conversión vale para el día de la instalación (la
    verificación avisa)."""
    day = day or datetime.now(LIMA).date()
    out = []
    for h, m in lima_slots(at):
        t = datetime(day.year, day.month, day.day, h, m, tzinfo=LIMA)
        local = t.astimezone(tz) if tz else t.astimezone()
        out.append(f"{local:%H:%M}")
    return out


def lima_offset_matches() -> bool:
    now = datetime.now(LIMA)
    return now.astimezone().utcoffset() == now.utcoffset()


# --- macOS ---------------------------------------------------------------------

def launchd_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def launchd_plist(python: str, root: Path, times: list[str]) -> bytes:
    return plistlib.dumps({
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [python, *COMMAND],
        "WorkingDirectory": str(root / "python"),
        "StartCalendarInterval": [{"Hour": int(t[:2]), "Minute": int(t[3:])} for t in times],
        # Al iniciar sesión o encender: recupera la recolección perdida.
        "RunAtLoad": True,
        "ProcessType": "Background",
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": str(root / "logs" / "launchd.log"),
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                                 "ENSO_HOME": str(root), "PYTHONUTF8": "1"},
    })


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=60)


def install_launchd(python: str, root: Path, times: list[str]) -> str:
    plist = launchd_path()
    plist.parent.mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    plist.write_bytes(launchd_plist(python, root, times))
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", f"{domain}/{LAUNCHD_LABEL}")
    r = _launchctl("bootstrap", domain, str(plist))
    if r.returncode != 0:  # sin sesión gráfica (por ejemplo, por SSH) o macOS antiguo
        _launchctl("unload", str(plist))
        r = _launchctl("load", "-w", str(plist))
        if r.returncode != 0:
            raise RuntimeError(f"launchctl no cargó el agente: {r.stderr.strip() or r.stdout.strip()}")
    return f"agente de launchd {LAUNCHD_LABEL} ({plist})"


def _launchd_loaded() -> bool:
    if _launchctl("print", f"gui/{os.getuid()}/{LAUNCHD_LABEL}").returncode == 0:
        return True
    # Sin sesión gráfica (por SSH) el agente se cargó con «load»: se ve en «list».
    return any(line.split()[-1:] == [LAUNCHD_LABEL] for line in _launchctl("list").stdout.splitlines())


def remove_launchd() -> bool:
    """Descarga el agente y borra su plist. Si launchd lo sigue teniendo
    cargado es un error: borrar la carpeta dejaría un agente que falla cada noche."""
    plist = launchd_path()
    existed = plist.exists()
    r = _launchctl("bootout", f"gui/{os.getuid()}/{LAUNCHD_LABEL}")
    if existed:
        r = _launchctl("unload", str(plist)) if r.returncode != 0 else r
    for _ in range(20):  # el bootout de un agente en marcha termina al detenerlo
        if not _launchd_loaded():
            break
        time.sleep(0.5)
    else:
        detail = (r.stderr or r.stdout or "").strip()
        raise RuntimeError(f"launchd sigue con el agente {LAUNCHD_LABEL} cargado{': ' + detail if detail else ''}")
    if existed:
        plist.unlink(missing_ok=True)
    return existed or r.returncode == 0


def status_launchd() -> dict:
    plist = launchd_path()
    out = {"kind": "launchd", "installed": plist.exists(), "loaded": False, "program": None, "detail": ""}
    if plist.exists():
        try:
            data = plistlib.loads(plist.read_bytes())
            out["program"] = data.get("ProgramArguments", [None])[0]
            out["times"] = [f"{d['Hour']:02d}:{d['Minute']:02d}" for d in data.get("StartCalendarInterval", [])]
        except (ValueError, KeyError, plistlib.InvalidFileException):
            out["detail"] = "plist ilegible"
    r = _launchctl("print", f"gui/{os.getuid()}/{LAUNCHD_LABEL}")
    if r.returncode == 0:
        out["loaded"] = True
        for line in r.stdout.splitlines():
            k, _, v = line.strip().partition(" = ")
            if k in ("state", "last exit code", "runs"):
                out[k.replace(" ", "_")] = v
    elif out["installed"]:
        out["loaded"] = LAUNCHD_LABEL in _launchctl("list").stdout
    return out


def kick_launchd() -> bool:
    return _launchctl("kickstart", f"gui/{os.getuid()}/{LAUNCHD_LABEL}").returncode == 0


# --- Linux (cron) --------------------------------------------------------------

def cron_command(python: str, root: Path) -> str:
    q = shlex.quote
    return (f"cd {q(str(root / 'python'))} && ENSO_HOME={q(str(root))} {q(python)} {' '.join(COMMAND)}"
            f" >/dev/null 2>>{q(str(root / 'logs' / 'cron.log'))}")


def cron_lines(python: str, root: Path, times: list[str]) -> list[str]:
    cmd = cron_command(python, root)
    lines = [f"{int(t[3:])} {int(t[:2])} * * * {cmd} {CRON_TAG}" for t in times]
    return [*lines, f"@reboot sleep 300 && {cmd} {CRON_TAG}"]


#: Lo que dice ``crontab -l`` cuando el usuario aún no tiene crontab (cronie,
#: Debian, macOS: «no crontab for …»; busybox: «can't open '…': No such file»).
_NO_CRONTAB = ("no crontab for", "no such file")


def _crontab_read() -> list[str]:
    """Las líneas del crontab del usuario; [] si todavía no tiene.

    Cualquier otro fallo (permisos, cron.allow, demonio roto) es un error:
    leerlo como vacío haría que instalar borre las líneas ajenas y que
    desinstalar diga que no había tarea y borre la carpeta igual."""
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=30)
    if r.returncode == 0:
        return r.stdout.splitlines()
    err = (r.stderr or "").strip()
    if any(m in err.lower() for m in _NO_CRONTAB):
        return []
    raise RuntimeError(f"no se pudo leer el crontab (código {r.returncode}): {err or 'sin detalle'}")


def _crontab_write(lines: list[str]) -> None:
    text = "\n".join(lines).strip("\n")
    r = subprocess.run(["crontab", "-"], input=(text + "\n") if text else "", capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"crontab no aceptó los cambios: {r.stderr.strip()}")


def install_cron(python: str, root: Path, times: list[str]) -> str:
    (root / "logs").mkdir(parents=True, exist_ok=True)
    keep = [line for line in _crontab_read() if CRON_TAG not in line]
    _crontab_write([*keep, *cron_lines(python, root, times)])
    return "crontab del usuario (líneas marcadas «observatorio-enso-recolector»)"


def remove_cron() -> bool:
    if not shutil.which("crontab"):
        return False  # sin cron (el instalador avisó y siguió sin tarea): no hay nada que quitar
    lines = _crontab_read()
    keep = [line for line in lines if CRON_TAG not in line]
    if len(keep) != len(lines):
        _crontab_write(keep)
        return True
    return False


def status_cron() -> dict:
    try:
        mine = [line for line in _crontab_read() if CRON_TAG in line]
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        return {"kind": "cron", "installed": False, "detail": f"crontab no disponible: {exc}"}
    program = None
    if mine:
        parts = shlex.split(mine[0].split(" && ", 1)[1].split(" >", 1)[0])
        program = next((p for p in parts if "python" in Path(p).name), None)
    return {"kind": "cron", "installed": bool(mine), "lines": len(mine), "program": program,
            "times": [f"{int(x.split()[1]):02d}:{int(x.split()[0]):02d}" for x in mine if not x.startswith("@")]}


def kick_cron(python: str, root: Path) -> bool:
    """Corre el mismo comando que cron, con un entorno mínimo como el de cron."""
    env = {"HOME": str(Path.home()), "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    subprocess.Popen(["/bin/sh", "-c", cron_command(python, root)], env=env, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


# --- Windows -------------------------------------------------------------------

_PS_STATUS = r"""
$ErrorActionPreference = 'SilentlyContinue'
$out = @{ installed = $false; old_task = [bool](Get-ScheduledTask -TaskName '%(old)s') }
$t = Get-ScheduledTask -TaskName '%(name)s'
if ($t) {
  $i = $t | Get-ScheduledTaskInfo
  $out.installed = $true
  $out.state = "$($t.State)"
  $out.program = $t.Actions[0].Execute
  $out.arguments = $t.Actions[0].Arguments
  $out.workdir = $t.Actions[0].WorkingDirectory
  $out.logon = "$($t.Principal.LogonType)"
  $out.last_result = $i.LastTaskResult
  if ($i.LastRunTime -and $i.LastRunTime.Year -gt 2000) { $out.last_run = $i.LastRunTime.ToString('s') }
  if ($i.NextRunTime) { $out.next_run = $i.NextRunTime.ToString('s') }
  $out.missed = $i.NumberOfMissedRuns
}
$out | ConvertTo-Json -Compress
"""


def status_windows() -> dict:
    script = _PS_STATUS % {"name": WINDOWS_TASK, "old": OLD_WINDOWS_TASK}
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, text=True, timeout=90, creationflags=0x08000000)
        data = json.loads(r.stdout.strip() or "{}")
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"kind": "schtasks", "installed": False, "detail": f"no se pudo consultar: {exc}"}
    return {"kind": "schtasks", **data}


def kick_windows() -> bool:
    r = subprocess.run(["schtasks", "/Run", "/TN", WINDOWS_TASK], capture_output=True, text=True, timeout=60)
    return r.returncode == 0


# --- Comunes -------------------------------------------------------------------

def status() -> dict:
    if os.name == "nt":
        return status_windows()
    if sys.platform == "darwin":
        return status_launchd()
    return status_cron()


def kick(python: str, root: Path = ROOT) -> bool:
    if os.name == "nt":
        return kick_windows()
    if sys.platform == "darwin":
        return kick_launchd()
    return kick_cron(python, root)


def install(python: str, root: Path = ROOT, at: str = "21:00") -> str:
    times = local_times(at)
    if sys.platform == "darwin":
        return install_launchd(python, root, times)
    if os.name == "nt":
        raise RuntimeError("en Windows la tarea la registra collector/instalar.ps1")
    return install_cron(python, root, times)


def remove() -> bool:
    if sys.platform == "darwin":
        return remove_launchd()
    if os.name == "nt":
        raise RuntimeError("en Windows la tarea la quita collector/instalar.ps1 -Desinstalar")
    return remove_cron()


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("accion", choices=["horas", "instalar", "quitar", "estado"])
    ap.add_argument("--hora", default=os.environ.get("ENSO_COLLECT_AT", "21:00"), help="hora de Lima, HH:MM")
    ap.add_argument("--python", default=sys.executable, help="intérprete del entorno virtual")
    args = ap.parse_args(argv)
    try:
        if args.accion == "horas":
            print("\n".join(local_times(args.hora)))
        elif args.accion == "instalar":
            print(f"Tarea programada: {install(args.python, ROOT, args.hora)}")
            print(f"Disparos (hora local): {', '.join(local_times(args.hora))} y al iniciar sesión o encender")
        elif args.accion == "quitar":
            print("Tarea programada quitada." if remove() else "No había tarea programada.")
        else:
            print(json.dumps(status(), ensure_ascii=False, indent=1))
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        # El instalador depende de este código: si la tarea no se quitó, no borra la carpeta.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
