"""Corrida programada del recolector del Perú en un equipo de escritorio.

Envuelve ``tools.peru_collector`` para que la tarea programada de Windows,
macOS o Linux funcione sin nadie mirando:

* toma el token de ``<raíz>/.env`` si no está en el entorno;
* escribe un registro rotativo en ``<raíz>/logs/recolector.log`` y nunca
  muestra el token;
* no corre dos veces a la vez (candado) y corta una corrida colgada; el
  candado de una corrida que ya no está (el equipo se apagó, o launchd la
  detuvo al reinstalar) no frena a la siguiente;
* con ``--programado`` solo recolecta si falta la copia de la última hora
  programada (21:00 de Lima por defecto). Así la tarea puede dispararse
  varias veces (21:00, reintentos cada 30 minutos, al iniciar sesión o al
  despertar el equipo) y sube una sola copia por día, y recupera la
  recolección perdida si el equipo estuvo apagado;
* comprueba el token con GitHub antes de recolectar y anota su vencimiento;
* no sube nada si ninguna fuente respondió (la última copia buena se
  conserva en la rama ``data-peru``);
* guarda el resultado en ``<raíz>/estado.json`` (lo lee la verificación) y
  agrega un diagnóstico del equipo al ``index.json`` que se sube;
* tras dos fallas seguidas muestra un aviso en el escritorio (uno por día).

``<raíz>`` es la carpeta que contiene ``python/`` (la del repositorio o la
de la instalación del kit), o ``ENSO_HOME``.

Uso:
  python -m tools.collector_service                # recolectar y subir ahora
  python -m tools.collector_service --programado   # lo que corre la tarea programada
  python -m tools.collector_service --estado       # última corrida
"""

from __future__ import annotations

import argparse
import io
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator, Optional
from zoneinfo import ZoneInfo

LIMA = ZoneInfo("America/Lima")
ROOT = Path(os.environ.get("ENSO_HOME") or Path(__file__).resolve().parents[2])
#: Margen para que una tarea que arranca unos segundos antes de la hora no
#: se tome por la del día anterior.
GRACE = timedelta(minutes=5)
#: Un candado más viejo que esto es de una corrida que murió sin soltarlo, aunque su
#: número de proceso siga en uso (``lock_busy``).
LOCK_STALE = timedelta(hours=2)
NOTIFY_AFTER = 2
LOG_MAX_BYTES = 2_000_000
LOG_KEEP = 5
TOKEN_WARN_DAYS = 21
#: Carpetas donde suele estar git cuando la tarea programada no lo tiene en el PATH.
GIT_DIRS = {
    "win32": [r"C:\Program Files\Git\cmd", os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\cmd")],
    "darwin": ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"],
    "linux": ["/usr/local/bin", "/usr/bin", "/home/linuxbrew/.linuxbrew/bin", "/snap/bin"],
}

EXIT_OK, EXIT_NO_SOURCES, EXIT_CONFIG, EXIT_GITHUB, EXIT_PUSH, EXIT_BUSY, EXIT_HUNG, EXIT_STOPPED, EXIT_BUG = \
    0, 1, 2, 3, 4, 5, 6, 7, 9


class Problem(Exception):
    """Falla con código de salida y una indicación de qué hacer."""

    def __init__(self, code: int, message: str, hint: str = ""):
        super().__init__(message)
        self.code, self.hint = code, hint


class Stopped(Exception):
    """El sistema detuvo la corrida (apagado, cierre de sesión o reinstalación)."""


# --- Rutas y configuración ---------------------------------------------------

def paths(root: Optional[Path] = None) -> dict[str, Path]:
    r = Path(root or ROOT)
    return {"root": r, "env": r / ".env", "logs": r / "logs", "log": r / "logs" / "recolector.log",
            "state": r / "estado.json", "lock": r / ".recolector.lock", "force": r / "forzar-proxima.json",
            "kit": r / "kit.json"}


def read_env_file(path: Path) -> dict[str, str]:
    """``CLAVE=valor`` por línea; admite comentarios, comillas, ``export`` y BOM."""
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def load_env(root: Optional[Path] = None) -> dict[str, str]:
    """Carga ``.env``. Sus valores mandan sobre el entorno: el instalador lo
    mantiene, y una variable GITHUB_TOKEN vieja (de la instalación anterior
    en Windows) no debe tapar el token nuevo. Devuelve de dónde salió cada
    clave y, en ``ignored:CLAVE``, las variables de entorno que se taparon."""
    origin = {}
    for k, v in read_env_file(paths(root)["env"]).items():
        if not v:
            continue
        previous = os.environ.get(k, "").strip()
        if previous and previous != v:
            origin[f"ignored:{k}"] = "entorno"
        os.environ[k] = v
        origin[k] = ".env"
    if os.environ.get("GITHUB_TOKEN", "").strip() and "GITHUB_TOKEN" not in origin:
        origin["GITHUB_TOKEN"] = "entorno"
    return origin


def add_git_to_path() -> None:
    if shutil.which("git"):
        return
    extra = [d for d in GIT_DIRS.get(sys.platform, []) if Path(d, "git.exe" if os.name == "nt" else "git").exists()]
    if extra:
        os.environ["PATH"] = os.pathsep.join([*extra, os.environ.get("PATH", "")])


#: Variables de red que la tarea programada no hereda de la terminal; el
#: instalador las copia a ``.env`` si existen al instalar.
NETWORK_VARS = ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy", "SSL_CERT_FILE")


def use_system_proxy() -> None:
    """Pasa a git el proxy configurado en Windows o macOS (httpx ya lo usa;
    git solo mira las variables de entorno)."""
    if any(os.environ.get(v) for v in NETWORK_VARS[:2] + NETWORK_VARS[3:5]):
        return
    import urllib.request

    try:
        proxies = urllib.request.getproxies()
    except Exception:
        return
    for scheme in ("https", "http"):
        if proxies.get(scheme):
            os.environ[f"{scheme.upper()}_PROXY"] = proxies[scheme]
    if proxies.get("no"):
        os.environ["NO_PROXY"] = proxies["no"]


def use_system_certificates() -> bool:
    """Confía en los certificados del sistema (Windows, macOS). Necesario
    cuando un antivirus o un proxy inspecciona HTTPS: sin esto Python solo
    confía en su lista propia y todas las descargas fallan."""
    try:
        import truststore

        truststore.inject_into_ssl()
        return True
    except Exception:
        return False


def hide_console_windows() -> None:
    """Con ``pythonw.exe`` (sin consola) cada llamada a git abriría una
    ventana negra un instante; se crean sin ventana."""
    if os.name != "nt" or getattr(subprocess.Popen.__init__, "_enso_no_window", False):
        return
    original = subprocess.Popen.__init__

    def init(self, *args, **kwargs):
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x08000000  # CREATE_NO_WINDOW
        original(self, *args, **kwargs)

    init._enso_no_window = True  # type: ignore[attr-defined]
    subprocess.Popen.__init__ = init  # type: ignore[method-assign]


def kit_manifest(root: Optional[Path] = None) -> dict:
    try:
        data = json.loads(paths(root)["kit"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def kit_version(root: Optional[Path] = None) -> str:
    manifest = kit_manifest(root)
    if manifest:
        return manifest.get("version", "?")
    try:
        sha = subprocess.run(["git", "-C", str(paths(root)["root"]), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        return f"git-{sha}" if sha else "desarrollo"
    except (OSError, subprocess.SubprocessError):
        return "desarrollo"


def git_version() -> str:
    try:
        out = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=20).stdout
        return out.strip().removeprefix("git version ")
    except (OSError, subprocess.SubprocessError):
        return ""


# --- Registro ------------------------------------------------------------------

class Tee(io.TextIOBase):
    """Escribe en el archivo de registro y, si hay, en la consola; oculta secretos."""

    def __init__(self, file, console, secrets: list[str]):
        self.file, self.console = file, console
        self.secrets = [s for s in secrets if s and len(s) >= 8]

    def scrub(self, s: str) -> str:
        for secret in self.secrets:
            s = s.replace(secret, "***")
        return s

    def write(self, s: str) -> int:
        s = self.scrub(s)
        self.file.write(s)
        if self.console is not None:
            try:
                self.console.write(s)
            except (OSError, ValueError, UnicodeError):
                pass
        return len(s)

    def flush(self) -> None:
        self.file.flush()
        if self.console is not None:
            try:
                self.console.flush()
            except (OSError, ValueError):
                pass


def rotate(log: Path, max_bytes: int = LOG_MAX_BYTES, keep: int = LOG_KEEP) -> None:
    if not log.exists() or log.stat().st_size < max_bytes:
        return
    for i in range(keep - 1, 0, -1):
        src = log.with_name(f"{log.name}.{i}")
        if src.exists():
            os.replace(src, log.with_name(f"{log.name}.{i + 1}"))
    os.replace(log, log.with_name(f"{log.name}.1"))


@contextmanager
def logging_to_file(root: Optional[Path] = None) -> Iterator[Optional[Path]]:
    p = paths(root)
    try:
        p["logs"].mkdir(parents=True, exist_ok=True)
        rotate(p["log"])
        f = open(p["log"], "a", encoding="utf-8")
    except OSError:
        yield None  # carpeta sin permiso de escritura: solo consola
        return
    secrets = [os.environ.get("GITHUB_TOKEN", "").strip()]
    out, err = sys.stdout, sys.stderr
    sys.stdout = Tee(f, out, secrets)
    sys.stderr = Tee(f, err, secrets)
    try:
        yield p["log"]
    finally:
        sys.stdout, sys.stderr = out, err
        f.close()


def log(msg: str) -> None:
    print(f"{datetime.now(LIMA):%Y-%m-%d %H:%M:%S} {msg}", flush=True)


# --- Estado, candado y horario -----------------------------------------------

def read_state(root: Optional[Path] = None) -> dict:
    try:
        return json.loads(paths(root)["state"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(state: dict, root: Optional[Path] = None) -> None:
    target = paths(root)["state"]
    try:
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)
    except OSError as exc:
        log(f"no se pudo guardar {target.name}: {exc}")


def parse_time(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        t = datetime.fromisoformat(s)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def collect_at() -> str:
    at = os.environ.get("ENSO_COLLECT_AT", "21:00").strip()
    if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", at):
        log(f"ENSO_COLLECT_AT={at!r} no es HH:MM; se usa 21:00")
        return "21:00"
    return at


def last_slot(now: datetime, at: str = "21:00") -> datetime:
    """La hora programada (hora de Lima) más reciente que ya llegó."""
    h, m = (int(x) for x in at.split(":"))
    ref = now.astimezone(LIMA) + GRACE
    slot = ref.replace(hour=h, minute=m, second=0, microsecond=0)
    return slot if slot <= ref else slot - timedelta(days=1)


def is_due(state: dict, now: datetime, at: str = "21:00") -> bool:
    """¿Falta la copia de la última hora programada? Una corrida que arrancó
    hasta ``GRACE`` antes de la hora (un disparo adelantado) cuenta como la de
    esa hora; si no, los reintentos de la noche la repetirían."""
    done = parse_time(state.get("last_success"))
    return done is None or done < last_slot(now, at) - GRACE


def pid_alive(pid: int) -> bool:
    """¿Sigue corriendo el proceso ``pid``? Ante la duda, sí: el candado se respeta."""
    if pid <= 0:
        return False
    if os.name == "nt":  # allí os.kill(pid, 0) no pregunta: termina el proceso
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED: existe, es de otro usuario
        try:
            code = wintypes.DWORD()
            return not k32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:  # PermissionError: existe, es de otro usuario
        return True
    return True


def _lock_owner(text: str) -> Optional[int]:
    m = re.match(r"\s*(\d+)\s", text + " ")
    return int(m.group(1)) if m else None


def lock_busy(root: Optional[Path] = None) -> bool:
    """¿Hay una corrida trabajando? El candado guarda el número de proceso de su
    corrida: si esa corrida ya no está (el equipo se apagó, o launchd la detuvo al
    reinstalar), el candado está abandonado aunque sea de hace un minuto. Sin
    número legible (la corrida recién lo crea), cuenta la antigüedad."""
    lock = paths(root)["lock"]
    try:
        owner = _lock_owner(lock.read_text(encoding="utf-8", errors="replace"))
        age = time.time() - lock.stat().st_mtime
    except OSError:
        return False
    if age >= LOCK_STALE.total_seconds():
        return False
    return owner is None or pid_alive(owner)


@contextmanager
def run_lock(root: Optional[Path] = None) -> Iterator[None]:
    lock = paths(root)["lock"]
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                text = lock.read_text(encoding="utf-8", errors="replace")
                age = time.time() - lock.stat().st_mtime
            except OSError:
                continue
            if lock_busy(root):
                raise Problem(EXIT_BUSY, f"ya hay una recolección en curso (candado de hace {age / 60:.0f} min)")
            log(f"candado abandonado de hace {age / 60:.0f} min (su corrida ya no está): se reemplaza")
            try:  # solo si sigue siendo el mismo: otra corrida pudo reemplazarlo recién
                if lock.read_text(encoding="utf-8", errors="replace") == text:
                    lock.unlink()
            except OSError:
                pass
    else:
        raise Problem(EXIT_BUSY, "no se pudo tomar el candado")
    try:
        os.write(fd, f"{os.getpid()} {datetime.now(timezone.utc).isoformat()}".encode())
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def take_force_flag(root: Optional[Path] = None) -> Optional[dict]:
    """Pedido de la verificación para probar la tarea programada (una vez, vigente 1 h)."""
    flag = paths(root)["force"]
    if not flag.exists():
        return None
    try:
        req = json.loads(flag.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        req = {}
    flag.unlink(missing_ok=True)
    created = parse_time(req.get("created"))
    if created and datetime.now(timezone.utc) - created > timedelta(hours=1):
        return None
    return req


# --- GitHub ------------------------------------------------------------------

def parse_token_expiry(header: str) -> Optional[datetime]:
    """``GitHub-Authentication-Token-Expiration`` (p. ej. ``2027-10-20 17:00:00 UTC``
    o ``2027-10-20 12:00:00 -0500``)."""
    m = re.match(r"\s*(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)\s*(UTC|Z|[+-]\d{2}:?\d{2})?", header or "")
    if not m:
        return None
    tz = m.group(3) or "UTC"
    tz = "+00:00" if tz in ("UTC", "Z") else (tz if ":" in tz else f"{tz[:3]}:{tz[3:]}")
    try:
        return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}{tz}")
    except ValueError:
        return None


def github_preflight(token: str, repo: str, client=None) -> dict:
    """Comprueba el token con la API de GitHub. Devuelve ``{"expires_at": ...}``."""
    import httpx

    own = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        r = client.get(f"https://api.github.com/repos/{repo}",
                       headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                "X-GitHub-Api-Version": "2022-11-28"})
    except httpx.HTTPError as exc:
        raise Problem(EXIT_GITHUB, f"sin conexión con GitHub ({type(exc).__name__}: {exc})"[:300],
                      network_hint(exc)) from exc
    finally:
        if own:
            client.close()
    if r.status_code == 401:
        raise Problem(EXIT_GITHUB, "GitHub rechazó el token (vencido, revocado o mal copiado)",
                      "Crear un token nuevo y volver a ejecutar el instalador (docs/servidor-peru.md, «Token de GitHub»).")
    if r.status_code == 404:
        raise Problem(EXIT_GITHUB, f"el token no ve el repositorio {repo}",
                      "En el token, «Repository access» debe incluir ese repositorio.")
    expires = parse_token_expiry(r.headers.get("github-authentication-token-expiration", ""))
    return {"expires_at": expires.isoformat() if expires else None, "status": r.status_code}


def network_hint(exc: BaseException) -> str:
    text = f"{type(exc).__name__} {exc}".lower()
    if "certificate" in text or "ssl" in text:
        return ("Error de certificados: revisar que la fecha y hora del equipo sean correctas; si hay un "
                "antivirus que analiza HTTPS, volver a ejecutar el instalador (instala truststore).")
    if "name resolution" in text or "getaddrinfo" in text or "nodename" in text or "name or service" in text:
        return "No se resuelven nombres (DNS): revisar la conexión a internet del equipo."
    if "timeout" in text or "timed out" in text:
        return "La conexión tardó demasiado: revisar internet; se reintentará en 30 minutos."
    return "Revisar la conexión a internet; se reintentará en la próxima hora programada."


def push_hint(message: str) -> str:
    m = message.lower()
    if "403" in m or "permission" in m or "denied" in m:
        return "El token no tiene permiso de escritura: «Contents: Read and write» sobre el repositorio."
    if "rejected" in m or "fetch first" in m or "non-fast-forward" in m:
        return "Otra máquina subió al mismo tiempo; se reintentará en 30 minutos."
    if "ssl" in m or "certificate" in m:
        return "Error de certificados al subir: revisar fecha y hora del equipo, o el antivirus que analiza HTTPS."
    if "resolve host" in m or "could not resolve" in m:
        return "No se resuelve github.com: revisar internet."
    if "timed out" in m or "timeout" in m:
        return "La subida tardó demasiado; se reintentará."
    return "Ver el registro (logs/recolector.log) y ejecutar la verificación."


# --- Avisos en el escritorio ---------------------------------------------------

_TOAST = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$t = $x.GetElementsByTagName('text')
$t.Item(0).AppendChild($x.CreateTextNode($env:ENSO_NOTIFY_TITLE)) > $null
$t.Item(1).AppendChild($x.CreateTextNode($env:ENSO_NOTIFY_TEXT)) > $null
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($x))
"""


def notify(title: str, text: str) -> bool:
    """Aviso en el escritorio; si no se puede (sin sesión, Linux sin escritorio), no pasa nada."""
    try:
        if sys.platform == "darwin":
            script = f"display notification {json.dumps(text, ensure_ascii=False)} with title {json.dumps(title, ensure_ascii=False)}"
            return subprocess.run(["osascript", "-e", script], capture_output=True, timeout=20).returncode == 0
        if os.name == "nt":
            env = {**os.environ, "ENSO_NOTIFY_TITLE": title, "ENSO_NOTIFY_TEXT": text}
            return subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _TOAST],
                                  env=env, capture_output=True, timeout=30,
                                  creationflags=0x08000000).returncode == 0
        if shutil.which("notify-send"):
            return subprocess.run(["notify-send", title, text], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        pass
    return False


# --- Corrida -----------------------------------------------------------------

def _watchdog(minutes: float, root: Optional[Path]) -> threading.Timer:
    def hung():
        log(f"ERROR la corrida sigue después de {minutes:.0f} min: se corta")
        state = read_state(root)
        state.update(result="falla", exit_code=EXIT_HUNG, detail=f"corrida colgada más de {minutes:.0f} min",
                     consecutive_failures=state.get("consecutive_failures", 0) + 1)
        write_state(state, root)
        paths(root)["lock"].unlink(missing_ok=True)
        sys.stdout.flush()
        os._exit(EXIT_HUNG)

    t = threading.Timer(minutes * 60, hung)
    t.daemon = True
    t.start()
    return t


def collect_and_push(*, do_push: bool, do_dispatch: bool, state: dict, root: Optional[Path] = None) -> dict:
    """Una recolección completa. Devuelve el resultado o lanza ``Problem``."""
    from tools import peru_collector as pc

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    testing_remote = bool(os.environ.get("ENSO_RELAY_REMOTE"))
    info: dict = {"token_expires_at": state.get("token_expires_at")}
    if do_push:
        if not token:
            raise Problem(EXIT_CONFIG, "falta GITHUB_TOKEN: no se puede subir",
                          "Ejecutar el instalador y pegar el token cuando lo pida.")
        if not testing_remote:
            pre = github_preflight(token, pc.REPO)
            info["token_expires_at"] = pre["expires_at"]
    with tempfile.TemporaryDirectory(prefix="enso-relay-") as tmp:
        snap = Path(tmp) / "snapshot"
        idx = pc.collect(snap)
        ok = sum(1 for e in idx["entries"] if pc.usable(e))
        info.update(summary=idx["summary"], ok=ok, total=len(idx["entries"]))
        log(f"resumen: {idx['summary']}")
        idx["collector"].update({
            "runner": "collector_service/1", "kit": kit_version(root),
            "os": platform.platform(terse=True), "python": platform.python_version(), "git": git_version(),
            "consecutive_failures": state.get("consecutive_failures", 0),
            "token_expires_at": info["token_expires_at"],
        })
        if not ok:
            hint = "Si se repite, ejecutar la verificación: puede ser la conexión o un bloqueo de las fuentes."
            if not do_push:
                raise Problem(EXIT_NO_SOURCES, "ninguna fuente respondió", hint)
            # Una copia vacía reemplazaría a la última buena: solo se sube el latido, para que
            # el sitio sepa que el equipo funciona y que son las fuentes las que no responden.
            try:
                pc.push_heartbeat(pc.heartbeat(idx, "sin-fuentes"), token)
            except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
                msg = str(exc).replace(token, "***")[:300]
                log(f"tampoco se pudo subir el latido: {msg}")
                raise Problem(EXIT_NO_SOURCES, f"ninguna fuente respondió y tampoco se pudo subir el latido: {msg}",
                              push_hint(msg)) from exc
            raise Problem(EXIT_NO_SOURCES, "ninguna fuente respondió: se subió solo el latido "
                          "(se conserva la copia anterior)", hint)
        (snap / "index.json").write_text(json.dumps(idx, indent=1, ensure_ascii=False), encoding="utf-8")
        (snap / pc.HEARTBEAT).write_text(json.dumps(pc.heartbeat(idx, "ok"), indent=1, ensure_ascii=False),
                                         encoding="utf-8")
        if do_push:
            try:
                pc.push(snap, token)
            except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
                msg = str(exc).replace(token, "***") if token else str(exc)
                raise Problem(EXIT_PUSH, f"no se pudo subir: {msg}"[:400], push_hint(msg)) from exc
            if do_dispatch and not testing_remote:
                try:
                    pc.dispatch(token)
                except Exception as exc:  # la copia ya está subida; la corrida de las 23:37 la usará
                    info["warning"] = f"no se pudo pedir la actualización del sitio: {exc}"[:300]
                    log(f"AVISO {info['warning']}")
    return info


def _stop(signum, frame):
    raise Stopped(f"el sistema detuvo la corrida (señal {signum}: apagado, cierre de sesión o reinstalación)")


def catch_sigterm() -> Callable[[], object]:
    """launchd (al reinstalar, cerrar la sesión o apagar) y systemd piden terminar con
    SIGTERM: la corrida suelta el candado y anota que se interrumpió, en vez de morir
    a medias. Devuelve con qué dejar el manejador como estaba."""
    if threading.current_thread() is not threading.main_thread():
        return lambda: None
    try:
        previous = signal.signal(signal.SIGTERM, _stop)
    except (ValueError, OSError, AttributeError):
        return lambda: None
    return lambda: signal.signal(signal.SIGTERM, signal.SIG_DFL if previous is None else previous)


def run(*, scheduled: bool = False, do_push: bool = True, do_dispatch: bool = True,
        root: Optional[Path] = None, now: Optional[datetime] = None) -> int:
    state = read_state(root)
    now = now or datetime.now(timezone.utc)
    forced = take_force_flag(root) if scheduled else None
    if forced is not None:
        do_dispatch = bool(forced.get("dispatch", False))
        log("prueba de la tarea programada pedida por la verificación")
    at = collect_at()
    if scheduled and forced is None and not is_due(state, now, at):
        state["last_check"] = now.isoformat(timespec="seconds")
        write_state(state, root)
        log(f"ya hay copia de las {at} (Lima) de hoy: nada que hacer")
        return EXIT_OK
    started = time.monotonic()
    state.update(last_attempt=now.isoformat(timespec="seconds"), trigger="prueba" if forced is not None
                 else "programada" if scheduled else "manual", test_id=(forced or {}).get("id"))
    watchdog = _watchdog(float(os.environ.get("ENSO_RUN_TIMEOUT_MIN", "45")), root)
    restore = catch_sigterm()
    try:
        with run_lock(root):
            write_state({**state, "result": "en curso"}, root)
            info = collect_and_push(do_push=do_push, do_dispatch=do_dispatch, state=state, root=root)
        state.update(result="ok", exit_code=EXIT_OK, detail=info.get("warning", ""), consecutive_failures=0,
                     summary=info.get("summary"), token_expires_at=info.get("token_expires_at"), hint="")
        if do_push:  # sin subir no hay copia en data-peru: la tarea de la noche no debe darla por hecha
            state["last_success"] = now.isoformat(timespec="seconds")
        code = EXIT_OK
        log("listo" + (" (copia subida a GitHub)" if do_push else " (sin subir)"))
    except Problem as p:
        code = p.code
        if code == EXIT_BUSY:  # otra corrida está trabajando: no es una falla
            log(str(p))
            if forced is not None:  # la prueba queda pendiente para la próxima corrida
                paths(root)["force"].write_text(json.dumps(forced), encoding="utf-8")
            return code
        state.update(result="falla", exit_code=code, detail=str(p), hint=p.hint,
                     consecutive_failures=state.get("consecutive_failures", 0) + 1)
        log(f"ERROR {p}" + (f" — {p.hint}" if p.hint else ""))
    except Stopped as exc:  # no es una falla del recolector: no cuenta para las alarmas
        code = EXIT_STOPPED
        state.update(result="interrumpida", exit_code=code, detail=str(exc),
                     hint="Se reintenta sola en la próxima hora programada.")
        log(f"AVISO {exc}")
    except Exception as exc:
        code = EXIT_BUG
        state.update(result="falla", exit_code=code, detail=f"{type(exc).__name__}: {exc}"[:400],
                     hint="Error inesperado: enviar logs/recolector.log a quien mantiene el sitio.",
                     consecutive_failures=state.get("consecutive_failures", 0) + 1)
        log("ERROR inesperado:\n" + traceback.format_exc())
    finally:
        watchdog.cancel()
        restore()
    state["duration_s"] = round(time.monotonic() - started, 1)
    alert(state)
    write_state(state, root)
    return code


def alert(state: dict) -> None:
    """Aviso en el escritorio tras fallas seguidas o con el token por vencer (uno por día)."""
    today = datetime.now(LIMA).date().isoformat()
    if state.get("last_notified") == today:
        return
    title, text = "", ""
    if state.get("result") == "falla" and state.get("consecutive_failures", 0) >= NOTIFY_AFTER:
        title = "Recolector ENSO: no pudo subir la copia"
        text = f"{state.get('detail', '')[:140]}. Abrir VERIFICAR para ver qué hacer."
    exp = parse_time(state.get("token_expires_at"))
    if not title and exp and exp - datetime.now(timezone.utc) < timedelta(days=TOKEN_WARN_DAYS):
        days = max(0, (exp - datetime.now(timezone.utc)).days)
        title = "Recolector ENSO: el token de GitHub vence pronto"
        text = f"Vence en {days} días ({exp:%Y-%m-%d}). Crear uno nuevo y ejecutar INSTALAR otra vez."
        log(f"AVISO {text}")
    if title and notify(title, text):
        state["last_notified"] = today


def status_text(root: Optional[Path] = None) -> str:
    s = read_state(root)
    if not s:
        return "Todavía no hay corridas registradas."
    lines = [f"{k}: {s[k]}" for k in ("last_attempt", "result", "detail", "hint", "last_success",
                                      "consecutive_failures", "summary", "token_expires_at", "duration_s") if s.get(k) not in (None, "")]
    return "\n".join(lines)


def use_kit_defaults(root: Optional[Path] = None) -> None:
    """Contacto que las fuentes ven en el User-Agent: el sitio publicado, si el
    kit lo trae (ENSO_CONTACT_URL en .env manda); si no, el de enso.fetch."""
    contact = kit_manifest(root).get("contact_url")
    if contact:
        os.environ.setdefault("ENSO_CONTACT_URL", contact)


def prepare(root: Optional[Path] = None) -> dict[str, str]:
    """Entorno común de la corrida y de la verificación."""
    origin = load_env(root)
    use_kit_defaults(root)
    add_git_to_path()
    use_system_proxy()
    use_system_certificates()
    hide_console_windows()
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    return origin


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--programado", action="store_true", help="solo si falta la copia de la última hora programada")
    ap.add_argument("--sin-subir", action="store_true", help="recolectar sin subir a GitHub")
    ap.add_argument("--sin-dispatch", action="store_true", help="no pedir la actualización del sitio")
    ap.add_argument("--estado", action="store_true", help="mostrar la última corrida y salir")
    args = ap.parse_args(argv)
    prepare()
    if args.estado:
        print(status_text())
        return 0
    dispatch = not args.sin_dispatch and os.environ.get("ENSO_DISPATCH", "1") != "0"
    with logging_to_file():
        log(f"recolector {kit_version()} · {platform.platform(terse=True)} · Python {platform.python_version()}")
        return run(scheduled=args.programado, do_push=not args.sin_subir, do_dispatch=dispatch)


if __name__ == "__main__":
    sys.exit(main())
