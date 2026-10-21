"""Verificación del recolector en este equipo.

Revisa, en orden, todo lo que la recolección diaria necesita y dice qué
hacer con cada problema:

  python         versión de Python (3.11 o más reciente)
  dependencias   httpx, PyYAML, pypdf (y truststore en Windows y macOS)
  zona-horaria   datos de America/Lima y diferencia con la hora del equipo
  codigo         el recolector carga y los archivos coinciden con los del kit
  git            git instalado (se usa para subir la copia)
  internet       GitHub responde, sin portal cautivo, reloj sin desfase
  token          token presente, aceptado por GitHub, fecha de vencimiento
  escritura      el token puede subir al repositorio (git push --dry-run)
  fuentes        ENFEN, SENAMHI, ANA e IMARPE responden desde este equipo
  tarea          la tarea programada existe y apunta a esta instalación
  ultima-corrida resultado de la última recolección (estado.json)
  disco          espacio libre

Con ``--probar-tarea`` además dispara la tarea programada tal como lo hará
el sistema a las 21:00 (recolecta y sube una copia, sin pedir la
actualización del sitio) y espera su resultado: es la prueba de punta a
punta.

El informe se guarda en ``logs/verificacion-AAAAMMDD-HHMMSS.txt`` para
enviarlo a quien mantiene el sitio. Sale con 1 si hay alguna FALLA.

Uso:
  python -m tools.collector_check
  python -m tools.collector_check --probar-tarea
  python -m tools.collector_check --omitir fuentes,escritura --json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import platform
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import collector_schedule as sched  # noqa: E402
from tools import collector_service as svc  # noqa: E402

OK, WARN, FAIL, INFO = "OK", "AVISO", "FALLA", "INFO"
TAG = {OK: "[  OK  ]", WARN: "[AVISO ]", FAIL: "[FALLA ]", INFO: "[ INFO ]"}
REPO_DEFAULT = "PillB/observatorio-enso-peru"
STALE_HOURS = 36
REPORTS_KEPT = 15


@dataclass
class Result:
    id: str
    level: str
    title: str
    detail: str = ""
    hint: str = ""
    lines: list[str] = field(default_factory=list)


def repo() -> str:
    return os.environ.get("ENSO_REPO", REPO_DEFAULT)


def _scrub(text: str) -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    return text.replace(token, "***") if token else text


# --- Comprobaciones ------------------------------------------------------------

def check_python(ctx: dict) -> Result:
    v = sys.version_info
    bits = struct.calcsize("P") * 8
    detail = f"Python {platform.python_version()} ({bits} bits) · {platform.platform(terse=True)} · {sys.executable}"
    if v < (3, 11):
        return Result("python", FAIL, "Python demasiado antiguo", detail,
                      "Instalar Python 3.12 (python.org) y volver a ejecutar el instalador.")
    if sys.prefix == sys.base_prefix:
        return Result("python", WARN, f"Python {v.major}.{v.minor} fuera del entorno del recolector", detail,
                      "La tarea usa el entorno .venv de la instalación; ejecutar la verificación con el lanzador VERIFICAR.")
    return Result("python", OK, f"Python {v.major}.{v.minor}", detail)


def check_dependencies(ctx: dict) -> Result:
    from importlib import metadata

    wanted = [("httpx", "httpx"), ("yaml", "PyYAML"), ("pypdf", "pypdf")]
    optional = [("truststore", "truststore")] if sys.platform in ("win32", "darwin") else []
    found, missing, missing_opt = [], [], []
    for mod, dist in wanted + optional:
        try:
            importlib.import_module(mod)
            found.append(f"{dist} {metadata.version(dist)}")
        except Exception:
            (missing_opt if (mod, dist) in optional else missing).append(dist)
    if missing:
        return Result("dependencias", FAIL, f"faltan dependencias: {', '.join(missing)}", ", ".join(found),
                      "Volver a ejecutar el instalador (instala python/requirements.txt en .venv).")
    if missing_opt:
        return Result("dependencias", WARN, f"falta {', '.join(missing_opt)}", ", ".join(found),
                      "Sin truststore, un antivirus que analiza HTTPS puede bloquear las descargas. Volver a ejecutar el instalador.")
    return Result("dependencias", OK, "dependencias instaladas", ", ".join(found))


def check_timezone(ctx: dict) -> Result:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        lima = ZoneInfo("America/Lima")
    except ZoneInfoNotFoundError:
        return Result("zona-horaria", FAIL, "faltan los datos de zonas horarias (America/Lima)", "",
                      "Volver a ejecutar el instalador (instala tzdata).")
    now = datetime.now(lima)
    local = now.astimezone()
    times = sched.local_times(svc.collect_at())
    if local.utcoffset() != now.utcoffset():
        off = local.strftime("%z")
        return Result("zona-horaria", WARN, f"el equipo no usa la hora de Lima (UTC{off[:3]}:{off[3:]})",
                      f"Los disparos quedaron a las {times[0]} hora local = {svc.collect_at()} de Lima.",
                      "Si la zona del equipo cambia (por ejemplo, horario de verano), volver a ejecutar el instalador.")
    return Result("zona-horaria", OK, "hora del equipo = hora de Lima (UTC-05:00)",
                  f"Ahora en Lima: {now:%Y-%m-%d %H:%M}. Disparos: {', '.join(times)} y al iniciar sesión.")


def check_code(ctx: dict) -> Result:
    root = ctx["root"]
    try:
        from tools import peru_collector as pc
    except Exception as exc:
        return Result("codigo", FAIL, "el recolector no carga", f"{type(exc).__name__}: {exc}",
                      "Volver a ejecutar el instalador; si sigue, descargar el kit de nuevo.")
    registry, info = pc.load_registry_info(os.environ.get("GITHUB_TOKEN", "").strip())
    groups, _ = pc.plan(registry)
    n = sum(len(v) for v in groups.values())
    detail = (f"{n} URL en {len(groups)} grupos · {pc.describe_registry(info)} · kit {svc.kit_version(root)}"
              f" · carpeta {root}")
    policy = root / "config" / "threshold-policies" / "expert-grd-image-v1.yaml"
    if not policy.exists():
        return Result("codigo", FAIL, "falta la carpeta config/", detail, "Volver a ejecutar el instalador.")
    try:
        manifest = json.loads((root / "kit.json").read_text(encoding="utf-8")).get("files", {})
    except (OSError, ValueError):
        return Result("codigo", OK, "el recolector carga (instalación desde el repositorio)", detail)
    missing, changed = [], []
    for rel, sha in manifest.items():
        p = root / rel
        if not p.is_file():
            missing.append(rel)
        elif hashlib.sha256(p.read_bytes()).hexdigest() != sha:
            changed.append(rel)
    if missing:
        return Result("codigo", FAIL, f"faltan {len(missing)} archivos del kit", detail,
                      "Un antivirus o una copia incompleta los quitó: descargar el kit de nuevo e instalar.",
                      lines=missing[:10])
    if changed:
        return Result("codigo", WARN, f"{len(changed)} archivos difieren del kit", detail,
                      "Si nadie los editó a propósito, volver a instalar desde el kit.", lines=changed[:10])
    return Result("codigo", OK, f"el recolector carga y los {len(manifest)} archivos coinciden con el kit", detail)


def check_git(ctx: dict) -> Result:
    if not shutil.which("git"):
        hint = {"win32": "Instalar Git para Windows (git-scm.com) o volver a ejecutar el instalador, que lo instala con winget.",
                "darwin": "Ejecutar «xcode-select --install» en Terminal y luego el instalador otra vez."}.get(
            sys.platform, "Instalar git (sudo apt install git).")
        return Result("git", FAIL, "git no está instalado", "", hint)
    v = svc.git_version()
    if not v:
        return Result("git", FAIL, "git no responde", shutil.which("git") or "",
                      "En macOS: terminar la instalación de las herramientas de línea de comandos (xcode-select --install).")
    return Result("git", OK, f"git {v}", shutil.which("git") or "")


def _client(timeout: float = 20.0):
    import httpx

    from enso.fetch import UA

    return httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": UA})


def check_internet(ctx: dict) -> list[Result]:
    try:
        import httpx
    except ImportError:
        return [Result("internet", FAIL, "no se puede comprobar (falta httpx)", "", "Volver a ejecutar el instalador.")]
    url = f"https://api.github.com/repos/{repo()}"
    # Con el token, si lo hay: el repositorio puede ser privado (se ve como 404 sin él).
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    t0 = time.time()
    try:
        with _client() as c:
            r = c.get(url, headers=headers)
            if r.status_code == 401 and token:  # token malo: lo explica «token»; aquí importa la conexión
                headers.pop("Authorization")
                r = c.get(url, headers=headers)
            relay_branch = os.environ.get("ENSO_RELAY_BRANCH", "data-peru")
            branch = c.get(f"{url}/branches/{relay_branch}", headers=headers)
            copies: dict = {}
            if branch.status_code == 200:
                raw = {**headers, "Accept": "application/vnd.github.raw+json"}
                for name in ("index.json", "heartbeat.json"):
                    f = c.get(f"{url}/contents/{name}", params={"ref": relay_branch}, headers=raw)
                    copies[name] = (f.status_code, _json_or_none(f))
    except httpx.HTTPError as exc:
        return [Result("internet", FAIL, "no hay conexión con GitHub", _scrub(f"{type(exc).__name__}: {exc}")[:300],
                       svc.network_hint(exc))]
    out = []
    try:
        ok = r.status_code == 200 and r.json().get("full_name", "").lower() == repo().lower()
    except ValueError:
        ok = False
    if r.status_code == 403 and r.headers.get("x-ratelimit-remaining") == "0":
        out.append(Result("internet", WARN, "GitHub responde, pero limitó las consultas de esta red", "",
                          "Esperar una hora y repetir la verificación."))
    elif not ok and r.status_code in (401, 404) and "x-github-request-id" in r.headers:
        out.append(Result("internet", OK, "GitHub responde", f"{(time.time() - t0) * 1000:.0f} ms · el repositorio "
                          "no se ve sin un token válido (ver «token»)"))
    elif not ok:
        out.append(Result("internet", FAIL, "la respuesta de GitHub no es la esperada",
                          f"HTTP {r.status_code}, {r.headers.get('content-type', '')}",
                          "Puede ser un portal de acceso (wifi de hotel) o un proxy: abrir un navegador, aceptar el portal y repetir."))
    else:
        out.append(Result("internet", OK, "GitHub responde", f"{(time.time() - t0) * 1000:.0f} ms"))
    try:
        server = parsedate_to_datetime(r.headers.get("date", ""))
        skew = abs((datetime.now(timezone.utc) - server).total_seconds())
        if skew > 300:
            out.append(Result("internet", WARN, f"el reloj del equipo está desfasado {skew / 60:.0f} minutos", "",
                              "Activar «Establecer la hora automáticamente» en la configuración de fecha y hora."))
    except (TypeError, ValueError):
        pass
    if branch.status_code == 200:
        status, index = copies.get("index.json", (None, None))
        out.extend(relay_copy_results(_json_or_none(branch) or {}, index, copies.get("heartbeat.json", (None, None))[1],
                                      index_missing=status == 404))
    elif branch.status_code == 404 and ok:  # sin acceso al repositorio, 404 no dice nada de la rama
        out.append(Result("internet", INFO, "la rama data-peru todavía no existe (la crea la primera subida)"))
    return out


def _json_or_none(r) -> Optional[dict]:
    try:
        data = r.json() if r.status_code == 200 else None
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _when(value) -> Optional[datetime]:
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _copy_summary(index: Optional[dict], commit: dict) -> str:
    """Qué trajo la copia, por grupo, según su índice. Solo si el índice no se pudo leer, la primera línea del
    último commit, que puede ser un latido y no la copia."""
    if _when((index or {}).get("collected_at")) is not None:
        summary = index.get("summary")
        return " · " + ", ".join(f"{g} {v}" for g, v in summary.items()) if isinstance(summary, dict) and summary else ""
    msg = str(commit.get("message") or "").strip().splitlines()
    if not msg:
        return ""
    return " · " + (msg[0] if len(msg[0]) <= 160 else msg[0][:159] + "…")


def relay_copy_results(branch: dict, index: Optional[dict], beat: Optional[dict],
                       index_missing: bool = False) -> list[Result]:
    """Edad de la última copia en data-peru según ``collected_at`` de su índice.
    No sirve la fecha del último commit: una corrida sin fuentes sube solo el
    latido (un commit nuevo) y conserva la copia anterior, que puede ser vieja.
    Sin index.json (``index_missing``) la rama tiene solo latidos: todavía no
    hay copia. Si el índice no se pudo leer, se usa la fecha del commit."""
    out = []
    commit = (branch.get("commit") or {}).get("commit") or {}
    now = datetime.now(timezone.utc)
    when, stale = None, True
    if index_missing:
        out.append(Result("internet", WARN, "la rama data-peru todavía no tiene ninguna copia (no hay index.json)",
                          ("solo latidos: " if beat else "") + "el sitio no recibe nada de este equipo",
                          "Si las fuentes responden (comprobación «fuentes»), disparar la tarea con PROBAR-TAREA."))
    else:
        when, basis = _when((index or {}).get("collected_at")), "collected_at de index.json"
        if when is None:
            when, basis = _when((commit.get("committer") or {}).get("date")), "fecha del último commit (index.json ilegible)"
        if when is None:
            return out
        age = (now - when).total_seconds() / 3600
        stale = age > STALE_HOURS
        out.append(Result("internet", WARN if stale else INFO,
                          f"última copia en la rama data-peru: hace {age:.0f} h ({when.astimezone(svc.LIMA):%Y-%m-%d %H:%M} Lima)",
                          f"según {basis}" + _copy_summary(index, commit),
                          "El sitio avisa con un issue «relay-stale» pasadas 36 h." if stale else ""))
    beat_at = _when((beat or {}).get("at"))
    if beat_at is not None and (when is None or beat_at > when) and (beat or {}).get("result") == "sin-fuentes":
        hours = (now - beat_at).total_seconds() / 3600
        out.append(Result("internet", WARN if stale else INFO,
                          f"último latido hace {hours:.0f} h: ninguna fuente respondió"
                          + (" y se conservó la copia anterior" if when else ""),
                          f"fuentes que respondieron: {beat.get('reachable', '?')}",
                          "Son las instituciones, no este equipo: el sitio avisa con «relay-sources-down»." if stale else ""))
    return out


def check_token(ctx: dict) -> Result:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    origin = ctx["origin"].get("GITHUB_TOKEN", "")
    env_file = svc.paths(ctx["root"])["env"]
    if not token:
        return Result("token", FAIL, "no hay token de GitHub", f"Se busca en {env_file} y en GITHUB_TOKEN.",
                      "Crear el token (docs/servidor-peru.md, «Token de GitHub») y ejecutar el instalador.")
    notes = [f"origen: {'archivo ' + str(env_file) if origin == '.env' else 'variable de entorno GITHUB_TOKEN'}"]
    level, hints = OK, []
    if ctx["origin"].get("ignored:GITHUB_TOKEN"):
        notes.append("hay otra variable de entorno GITHUB_TOKEN, que se ignora")
        hints.append("Conviene borrar la variable de entorno GITHUB_TOKEN vieja para no confundirlas.")
    if token.startswith("ghp_"):
        level = WARN
        hints.append("Es un token clásico (acceso a todos sus repositorios). Mejor uno de grano fino solo para este repositorio.")
    elif not token.startswith("github_pat_"):
        level = WARN
        hints.append("El token no tiene el formato de GitHub (github_pat_...): revisar que se haya copiado completo.")
    if os.name != "nt" and env_file.exists() and env_file.stat().st_mode & 0o077:
        level = WARN
        hints.append(f"El archivo .env lo pueden leer otros usuarios: chmod 600 \"{env_file}\".")
    if os.environ.get("ENSO_RELAY_REMOTE"):
        return Result("token", INFO, "token presente (destino de prueba ENSO_RELAY_REMOTE)", "; ".join(notes))
    try:
        pre = svc.github_preflight(token, repo())
    except svc.Problem as p:
        return Result("token", FAIL, str(p), "; ".join(notes), p.hint)
    exp = svc.parse_time(pre["expires_at"])
    if exp:
        days = (exp - datetime.now(timezone.utc)).total_seconds() / 86400
        notes.append(f"vence el {exp.astimezone(svc.LIMA):%Y-%m-%d}")
        if days < 0:
            return Result("token", FAIL, "el token venció", "; ".join(notes), "Crear uno nuevo y ejecutar el instalador.")
        if days < svc.TOKEN_WARN_DAYS:
            level = WARN
            hints.append(f"Vence en {days:.0f} días: crear uno nuevo y ejecutar el instalador con el token nuevo.")
    else:
        notes.append("sin fecha de vencimiento informada")
    title = "GitHub acepta el token" + (f" (vence en {days:.0f} días)" if exp else "")
    return Result("token", level, title, "; ".join(notes), " ".join(hints))


def _git(args: list[str], cwd: Path, timeout: int = 90) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    return subprocess.run(["git", "-c", "credential.helper=", *args], cwd=cwd, capture_output=True, text=True,
                          env=env, timeout=timeout)


def check_write(ctx: dict) -> Result:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        return Result("escritura", FAIL, "no se puede comprobar sin token", "", "Ver «token».")
    if not shutil.which("git"):
        return Result("escritura", FAIL, "no se puede comprobar sin git", "", "Ver «git».")
    remote = os.environ.get("ENSO_RELAY_REMOTE") or f"https://x-access-token:{token}@github.com/{repo()}.git"
    with tempfile.TemporaryDirectory(prefix="enso-check-") as tmp:
        work = Path(tmp)
        try:
            _git(["init", "-q"], work)
            _git(["-c", "user.name=verificacion", "-c", "user.email=verificacion@localhost", "commit", "-q",
                  "--allow-empty", "-m", "prueba de permiso (no se sube)"], work)
            r = _git(["push", "--dry-run", "--porcelain", remote, "HEAD:refs/heads/verificacion-recolector"], work)
        except subprocess.TimeoutExpired:
            return Result("escritura", WARN, "no se pudo comprobar: git no respondió en 90 s", "",
                          "Revisar la conexión; si la subida diaria funciona, ignorar.")
    out = _scrub((r.stderr + r.stdout).strip())
    if r.returncode == 0:
        return Result("escritura", OK, "el token puede subir al repositorio",
                      "Prueba con git push --dry-run: no se subió nada.")
    low = out.lower()
    if "403" in low or "permission" in low or "denied" in low:
        return Result("escritura", FAIL, "el token no tiene permiso de escritura", out[:300],
                      "Editar el token en GitHub: Permissions → Repository → Contents: «Read and write».")
    if "401" in low or "authentication failed" in low or "could not read username" in low:
        return Result("escritura", FAIL, "GitHub rechazó el token al subir", out[:300],
                      "Crear un token nuevo y ejecutar el instalador.")
    if "certificate" in low or "ssl" in low:
        return Result("escritura", FAIL, "git no confía en el certificado de github.com", out[:300],
                      "Revisar fecha y hora; en Windows con antivirus que analiza HTTPS: "
                      "git config --global http.sslBackend schannel")
    return Result("escritura", WARN, "no se pudo comprobar el permiso de escritura", out[:300],
                  "Si la subida diaria funciona (ver «ultima-corrida»), ignorar.")


def _probe(url: str, expect: Optional[str] = None) -> dict:
    """Una URL, juzgada como en la recolección (``peru_collector.judge``): una
    página antirobots o un formato distinto del esperado no cuenta."""
    from tools import peru_collector as pc

    t0 = time.time()
    try:
        with _client(25.0) as c:
            r = c.get(url)
        body = r.content
        cls, _, why = pc.judge(r.status_code, body, r.headers.get("content-type", ""), expect)
        ok = cls == "ok"
        if not ok and cls == "challenge":
            why = "pide verificación humana"
        return {"url": url, "ok": ok, "why": f"HTTP {r.status_code}" if ok or not why else why,
                "bytes": len(body), "s": time.time() - t0}
    except Exception as exc:
        return {"url": url, "ok": False, "why": f"{type(exc).__name__}: {exc}"[:120], "bytes": 0, "s": time.time() - t0}


def _robots_verdicts(urls: list[str]) -> dict[str, str]:
    """Las URL que la recolección no pediría por robots.txt (``enso.reach.Robots``,
    RFC 9309), con el motivo. Un robots.txt por servidor, los servidores en paralelo."""
    from enso.reach import Robots

    hosts: dict[str, list[str]] = {}
    for u in urls:
        hosts.setdefault(urlparse(u).netloc.lower(), []).append(u)
    out: dict[str, str] = {}
    with _client(20.0) as c:
        robots = Robots(c)

        def one(host_urls: list[str]) -> None:
            for u in host_urls:
                allowed = robots.allowed(u)
                if allowed is False:
                    out[u] = "robots.txt no lo permite"
                elif allowed is None:
                    out[u] = f"robots.txt sin respuesta ({robots.failure(u) or 'connect'})"

        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(one, hosts.values()))
    return out


def check_sources(ctx: dict) -> Result:
    try:
        import httpx  # noqa: F401

        from tools import peru_collector as pc
    except Exception as exc:
        return Result("fuentes", FAIL, "no se puede comprobar", f"{type(exc).__name__}: {exc}", "Ver «codigo».")
    registry = pc.load_registry(os.environ.get("GITHUB_TOKEN", "").strip())[0]
    groups, _ = pc.plan(registry)
    meta = pc.url_info(registry)
    jobs = [(g, u) for g, urls in groups.items() for u in urls]
    # Lo que robots.txt no permite (o un robots.txt que no responde) no se pide, como en la recolección.
    refused = _robots_verdicts([u for _, u in jobs])

    def one(gu: tuple[str, str]) -> tuple[str, dict]:
        g, u = gu
        if u in refused:
            # Una ruta que robots.txt prohíbe no es una falla del servidor ni del equipo: no se cuenta.
            return g, {"url": u, "ok": False, "why": refused[u], "bytes": 0, "s": 0.0,
                       "skip": refused[u] == "robots.txt no lo permite"}
        return g, _probe(u, meta.get(u, {}).get("expect") or pc.guess_expect(u))

    with ThreadPoolExecutor(max_workers=6) as pool:
        res = list(pool.map(one, jobs))
    lines = [f"{'OK' if r['ok'] else '--' if r.get('skip') else 'NO'}  {g:8} {r['why']:>9} {r['bytes']:>9} B "
             f"{r['s']:5.1f}s  {r['url']}" for g, r in res]
    asked = [(g, r) for g, r in res if not r.get("skip")]
    skipped = len(res) - len(asked)
    by_group = {g: (sum(1 for gg, r in asked if gg == g and r["ok"]), sum(1 for gg, _ in asked if gg == g))
                for g in groups}
    # Un grupo sin URL que pedir es uno cuyo robots.txt no lo permite (aquí o, en el registro, ``plan``).
    summary = ", ".join(f"{g} {a}/{b}" if b else f"{g}: robots.txt no lo permite" for g, (a, b) in by_group.items())
    ok = sum(a for a, _ in by_group.values())
    if not asked:
        return Result("fuentes", WARN, "robots.txt no permite pedir ninguna fuente", summary,
                      "No es una falla del equipo: avisar para revisar la lista de fuentes.", lines)
    if ok == 0:
        return Result("fuentes", FAIL, "ninguna fuente peruana responde desde este equipo", summary,
                      "Este equipo no sirve como recolector desde esta red. Probar con otra conexión en el Perú; "
                      "si hay VPN activa, desactivarla.", lines)
    if by_group.get("enfen", (1, 1))[0] == 0:
        return Result("fuentes", WARN, "el ENFEN no responde desde este equipo", summary,
                      "Puede ser una caída momentánea del ENFEN: repetir más tarde.", lines)
    level = OK if ok * 2 >= len(asked) else WARN
    title = f"{ok}/{len(asked)} fuentes responden" + (
        f" ({skipped} no se piden: su robots.txt no lo permite)" if skipped else "")
    return Result("fuentes", level, title, summary,
                  "" if level == OK else "Varias fuentes no responden: repetir más tarde; si sigue, avisar.", lines)


def check_schedule(ctx: dict) -> Result:
    st = sched.status()
    if not st.get("installed"):
        return Result("tarea", FAIL, "no hay tarea programada", st.get("detail", ""),
                      "Ejecutar el instalador (sin --sin-tarea / -SinTarea).")
    program = st.get("program")
    detail = f"{st.get('kind')}: {program or '?'}"
    if program and not Path(program).exists():
        return Result("tarea", FAIL, "la tarea apunta a una carpeta que ya no existe", detail,
                      "Volver a ejecutar el instalador desde el kit.")
    other = sched.owner_elsewhere(ctx["root"])
    if other:
        return Result("tarea", WARN, f"la tarea programada es de otra instalación ({other})", detail,
                      "Esta carpeta no recolecta. Para usarla, ejecutar INSTALAR desde aquí; si sobra, desinstalarla.")
    if st.get("times"):
        detail += f" · horas locales {', '.join(st['times'])}"
    if st["kind"] == "schtasks":
        detail += f" · próxima: {st.get('next_run', '?')} · última: {st.get('last_run', 'nunca')} (código {st.get('last_result')})"
        if st.get("old_task"):
            return Result("tarea", WARN, f"queda la tarea antigua «{sched.OLD_WINDOWS_TASK}»", detail,
                          "Corre por separado y sin registro: volver a ejecutar el instalador (la quita).")
        if st.get("state") == "Disabled":
            return Result("tarea", FAIL, "la tarea está deshabilitada", detail,
                          "Abrir el Programador de tareas y habilitarla, o ejecutar el instalador.")
        if st.get("logon") == "Interactive":
            return Result("tarea", OK, "tarea programada lista (corre con la sesión iniciada, aunque esté bloqueada)",
                          detail, "Para que corra también sin sesión iniciada: ejecutar INSTALAR como administrador.")
    if st["kind"] == "launchd" and not st.get("loaded"):
        return Result("tarea", FAIL, "el agente de launchd no está cargado", detail,
                      "Volver a ejecutar el instalador, con la sesión del usuario iniciada.")
    return Result("tarea", OK, "tarea programada lista", detail)


def check_last_run(ctx: dict) -> Result:
    s = svc.read_state(ctx["root"])
    if not s.get("last_attempt"):
        return Result("ultima-corrida", INFO, "todavía no hubo recolecciones en este equipo")
    if s.get("result") == "en curso":
        return Result("ultima-corrida", INFO, f"hay una recolección en curso (desde {s['last_attempt']})")
    done = svc.parse_time(s.get("last_success"))
    age = (datetime.now(timezone.utc) - done).total_seconds() / 3600 if done else None
    detail = f"último intento {s.get('last_attempt')} ({s.get('trigger', '?')}): {s.get('result')} {s.get('detail', '')}".strip()
    if s.get("result") == "falla":
        level = FAIL if (age is None or age > STALE_HOURS) else WARN
        return Result("ultima-corrida", level, f"la última recolección falló ({s.get('consecutive_failures', 1)} seguidas)",
                      detail, s.get("hint", ""))
    if age is not None and age > STALE_HOURS:
        return Result("ultima-corrida", WARN, f"la última copia subida es de hace {age:.0f} h", detail,
                      "Revisar que el equipo esté encendido a las 21:00 y que la tarea exista.")
    return Result("ultima-corrida", OK, f"última recolección correcta hace {age:.0f} h" if age is not None else "correcta",
                  f"{detail} · {s.get('summary', '')}")


def check_disk(ctx: dict) -> Result:
    free = shutil.disk_usage(ctx["root"]).free / 1e6
    if free < 50:
        return Result("disco", FAIL, f"quedan {free:.0f} MB libres", "", "Liberar espacio en el disco.")
    if free < 300:
        return Result("disco", WARN, f"quedan {free:.0f} MB libres", "", "Conviene liberar espacio.")
    return Result("disco", OK, f"{free / 1000:.1f} GB libres")


CHECKS: list[tuple[str, Callable[[dict], object]]] = [
    ("python", check_python), ("dependencias", check_dependencies), ("zona-horaria", check_timezone),
    ("codigo", check_code), ("git", check_git), ("internet", check_internet), ("token", check_token),
    ("escritura", check_write), ("fuentes", check_sources), ("tarea", check_schedule),
    ("ultima-corrida", check_last_run), ("disco", check_disk),
]


# --- Prueba de la tarea programada ----------------------------------------------

def test_scheduled_run(ctx: dict, wait_min: float = 15.0, emit: Callable[[str], None] = print) -> Result:
    """Dispara la tarea programada y espera a que termine (como a las 21:00).

    El pedido lleva un id que la corrida anota en estado.json: así no se confunde
    con otra corrida que ya estaba en curso (en macOS, launchd corre la tarea al
    instalarla) y, si el sistema ignora el disparo porque la tarea seguía
    corriendo, se vuelve a disparar cuando termina.
    """
    p = svc.paths(ctx["root"])
    python = sys.executable
    if os.name == "nt" and Path(python).with_name("pythonw.exe").exists():
        python = str(Path(python).with_name("pythonw.exe"))
    deadline = time.time() + wait_min * 60
    if p["lock"].exists():
        emit("Hay una recolección en curso; se espera a que termine antes de la prueba...")
        while p["lock"].exists() and time.time() < deadline:
            time.sleep(3)
    test_id = uuid.uuid4().hex[:12]
    p["force"].write_text(json.dumps({"created": datetime.now(timezone.utc).isoformat(), "dispatch": False,
                                      "id": test_id}), encoding="utf-8")
    if not sched.kick(python, ctx["root"]):
        p["force"].unlink(missing_ok=True)
        return Result("prueba-tarea", FAIL, "el sistema no pudo disparar la tarea", "",
                      "Ver «tarea»; volver a ejecutar el instalador.")
    emit(f"Tarea disparada; esperando su resultado (hasta {wait_min:.0f} min)...")
    kicked, kicks, started = time.time(), 1, False
    while time.time() < deadline:
        time.sleep(3)
        s = svc.read_state(ctx["root"])
        mine = s.get("test_id") == test_id
        started = started or mine or not p["force"].exists()
        if mine and s.get("result") not in (None, "en curso"):
            if s.get("result") == "ok":
                return Result("prueba-tarea", OK, "la tarea programada recolectó y subió la copia",
                              f"{s.get('summary')} · {s.get('duration_s')} s")
            return Result("prueba-tarea", FAIL, f"la tarea programada corrió y falló: {s.get('detail', '')}",
                          f"código {s.get('exit_code')}", s.get("hint", ""), lines=[json.dumps(s, ensure_ascii=False)])
        # Pedido sin tomar y nada corriendo: el disparo se perdió (la tarea seguía en curso).
        if p["force"].exists() and not p["lock"].exists() and time.time() - kicked > 20 and kicks < 4:
            sched.kick(python, ctx["root"])
            kicked, kicks = time.time(), kicks + 1
    p["force"].unlink(missing_ok=True)
    where = {"win32": "Programador de tareas → Biblioteca → la tarea → Historial",
             "darwin": f"{p['logs'] / 'launchd.log'}"}.get(sys.platform, f"{p['logs'] / 'cron.log'}")
    return Result("prueba-tarea", FAIL, "la tarea no terminó a tiempo" if started else "la tarea no arrancó",
                  f"Revisar {where} y {p['log']}.", "Volver a ejecutar el instalador y repetir la prueba.")


# --- Informe -------------------------------------------------------------------

def render_one(r: Result) -> str:
    out = [f"{TAG[r.level]} {r.title}"]
    if r.detail:
        out.append(f"         {r.detail}")
    out += [f"           {line}" for line in r.lines]
    if r.hint:
        out.append(f"         {'Qué hacer' if r.level in (FAIL, WARN) else 'Nota'}: {r.hint}")
    return "\n".join(out)


def render(results: list[Result], header: list[str]) -> str:
    out = [*header, "", *(render_one(r) for r in results)]
    fails = sum(r.level == FAIL for r in results)
    warns = sum(r.level == WARN for r in results)
    out.append("")
    if fails:
        out.append(f"RESULTADO: {fails} falla(s) y {warns} aviso(s). El recolector todavía NO está listo en este equipo.")
    elif warns:
        out.append(f"RESULTADO: listo, con {warns} aviso(s) para revisar.")
    else:
        out.append("RESULTADO: todo en orden. Este equipo está listo para recolectar cada día.")
    return "\n".join(out)


def save_report(text: str, root: Path) -> Optional[Path]:
    logs = svc.paths(root)["logs"]
    try:
        logs.mkdir(parents=True, exist_ok=True)
        path = logs / f"verificacion-{datetime.now(svc.LIMA):%Y%m%d-%H%M%S}.txt"
        path.write_text(text + "\n", encoding="utf-8")
        for old in sorted(logs.glob("verificacion-*.txt"))[:-REPORTS_KEPT]:
            old.unlink(missing_ok=True)
        return path
    except OSError:
        return None


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--omitir", default="", help="comprobaciones a saltar, separadas por comas")
    ap.add_argument("--solo", default="", help="hacer solo estas comprobaciones, separadas por comas")
    ap.add_argument("--probar-tarea", action="store_true", help="disparar la tarea programada y esperar su resultado")
    ap.add_argument("--esperar", type=float, default=15.0, help="minutos de espera de --probar-tarea")
    ap.add_argument("--json", action="store_true", help="salida en JSON")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    origin = svc.prepare()
    ctx = {"root": svc.ROOT, "origin": origin}
    names = {name for name, _ in CHECKS}
    skip = {s.strip() for s in args.omitir.split(",") if s.strip()}
    only = {s.strip() for s in args.solo.split(",") if s.strip()}
    unknown = (skip | only) - names
    if unknown:
        ap.error(f"comprobación desconocida: {', '.join(sorted(unknown))}")
    if only:
        skip |= names - only
    header = [f"Verificación del recolector ENSO Perú · {datetime.now(svc.LIMA):%Y-%m-%d %H:%M} (Lima)",
              f"Equipo: {socket.gethostname()} · {platform.platform(terse=True)} · kit {svc.kit_version(svc.ROOT)}",
              f"Carpeta: {svc.ROOT}"]
    emit = (lambda s: None) if args.json else (lambda s: print(s, flush=True))
    emit("\n".join(header) + "\n")
    results: list[Result] = []
    for name, fn in CHECKS:
        if name in skip:
            continue
        if name == "fuentes":
            emit("Consultando las fuentes peruanas (hasta un minuto)...")
        try:
            got = fn(ctx)
        except Exception as exc:  # una comprobación rota no debe ocultar las demás
            got = Result(name, FAIL, "la comprobación falló", f"{type(exc).__name__}: {exc}"[:300],
                         "Enviar este informe a quien mantiene el sitio.")
        for r in got if isinstance(got, list) else [got]:
            results.append(r)
            emit(render_one(r))
    if args.probar_tarea:
        r = test_scheduled_run(ctx, args.esperar, emit)
        results.append(r)
        emit(render_one(r))
    text = render(results, header)
    report = save_report(_scrub(text), svc.ROOT)
    failed = any(r.level == FAIL for r in results)
    if args.json:
        print(json.dumps({"ok": not failed, "report": str(report) if report else None,
                          "results": [asdict(r) for r in results], "state": svc.read_state(svc.ROOT)},
                         ensure_ascii=False, indent=1))
    else:
        print("\n" + text.rsplit("\n", 1)[1])
        if report:
            print(f"Informe guardado en: {report}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
