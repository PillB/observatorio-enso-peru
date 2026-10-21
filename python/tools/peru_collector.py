"""Recolector desde el Perú: descarga las fuentes peruanas que no responden
a servidores fuera del país y las publica en la rama ``data-peru``.

SENAMHI, ANA e IMARPE no responden a GitHub Actions (tiempo de espera o
HTTP 403) y el portal del ENFEN no resuelve desde allí. Este programa corre
en una máquina dentro del Perú (o en cualquier lugar donde esas fuentes sí
respondan), guarda cada respuesta original y la sube a la rama
``data-peru``. La actualización diaria la usa como canal «desde Perú»
(ver ``enso.fetch.Relay``) antes de recurrir al Internet Archive.

Uso:
  python -m tools.peru_collector --probe            # ¿qué responde desde esta máquina?
  python -m tools.peru_collector --once --push      # una recolección y subida
  python -m tools.peru_collector --daemon --push    # todos los días a las 21:00 (Lima)
  ... --dispatch                                    # y luego actualizar el sitio en el momento

La subida (y ``--dispatch``) usa un token de GitHub de grano fino con
permiso «Contents: read and write» solo sobre este repositorio, en la
variable ``GITHUB_TOKEN``.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from enso.feeds import FormatChanged, peru  # noqa: E402
from enso.fetch import UA  # noqa: E402
from enso.observatory import ENFEN_BASE, _clean_wpdm, _communique_urls  # noqa: E402

LIMA = ZoneInfo("America/Lima")
REPO = os.environ.get("ENSO_REPO", "PillB/observatorio-enso-peru")
BRANCH = os.environ.get("ENSO_RELAY_BRANCH", "data-peru")
MAX_BYTES = 8_000_000
HEARTBEAT = "heartbeat.json"
#: Registro de fuentes (rama principal del repositorio; copia en el kit).
REGISTRY_PATH = "registry/sources.json"
REGISTRY_SCHEMA = "enso-source-registry/1"
PERU_CHANNEL = "peru-server"
MAX_REGISTRY_SOURCES = 200
MAX_FOLLOW = 20

#: Fuentes que se recolectan desde el Perú. Las URL deben coincidir con las
#: del catálogo del pipeline para que la actualización diaria las encuentre.
SOURCES: dict[str, list[str]] = {
    "enfen": [
        "https://enfen.imarpe.gob.pe/wp-json/wp/v2/posts?per_page=10&search=comunicado",
        "https://enfen.imarpe.gob.pe/comunicados/",
        # Réplica de la DHN: responde desde fuera, pero sus PDF piden una
        # verificación humana a servidores en la nube.
        "https://www.dhn.mil.pe/portal/comunicados-oficiales-enfen",
    ],
    "senamhi": [
        "https://www.senamhi.gob.pe/?p=fenomeno-el-nino",
        "https://www.senamhi.gob.pe/?p=aviso-meteorologico",
        "https://www.senamhi.gob.pe/?p=boletines",
        "https://www.senamhi.gob.pe/mapas/mapa-estaciones-2/",
    ],
    "ana": [
        "https://snirh.ana.gob.pe/",
        "https://snirh.ana.gob.pe/onrh/",
    ],
    "imarpe": [
        "https://www.imarpe.gob.pe/",
        "https://www.imarpe.gob.pe/imarpe/index.php?id_seccion=I0178070000000000000000",
    ],
}


def log(msg: str) -> None:
    print(f"{datetime.now(LIMA):%Y-%m-%d %H:%M:%S} {msg}", flush=True)


# --- Registro de fuentes ---------------------------------------------------------

def _valid_registry(data: object) -> dict:
    return data if isinstance(data, dict) and data.get("schema") == REGISTRY_SCHEMA else {}


def load_registry(token: str = "") -> tuple[dict, str]:
    """El registro de fuentes y de dónde salió. Primero el del repositorio en
    GitHub (con el token, así el equipo sigue los cambios sin reinstalar y
    funciona aunque el repositorio sea privado); si no, la copia del kit o del
    repositorio local. Sin registro, se recolecta solo ``SOURCES``."""
    override = os.environ.get("ENSO_REGISTRY_FILE", "").strip()
    if token and not override and not os.environ.get("ENSO_RELAY_REMOTE"):
        ref = os.environ.get("ENSO_REGISTRY_REF", "").strip()
        try:
            r = httpx.get(f"https://api.github.com/repos/{REPO}/contents/{REGISTRY_PATH}",
                          params={"ref": ref} if ref else None, timeout=30, follow_redirects=True,
                          headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.raw+json",
                                   "User-Agent": UA})
            data = _valid_registry(r.json()) if r.status_code == 200 else {}
            if data:
                return data, "github"
        except (httpx.HTTPError, ValueError):
            pass
    # ENSO_REGISTRY_FILE fija el archivo (pruebas, o para no consultar GitHub).
    path, origin = ((Path(override), "archivo") if override else
                    (Path(__file__).resolve().parents[2] / REGISTRY_PATH, "kit"))  # la instalación o el repo
    try:
        data = _valid_registry(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        data = {}
    return (data, origin) if data else ({}, "")


def peru_sources(registry: dict) -> list[dict]:
    """Entradas del registro para este equipo: canal «peru-server» (las geobloqueadas)."""
    out = []
    for src in registry.get("sources") or []:
        if not isinstance(src, dict) or PERU_CHANNEL not in (src.get("channels") or []):
            continue
        if str(src.get("url") or "").startswith(("https://", "http://")):
            out.append(src)
    return out[:MAX_REGISTRY_SOURCES]


def robots_disallowed(registry: dict) -> set[str]:
    """URL que el registro marca «robots-disallowed»: el robots.txt del servidor
    pide no automatizarlas y no las pide nadie, tampoco este equipo."""
    out: set[str] = set()
    for src in registry.get("sources") or []:
        geo = src.get("geoblock") if isinstance(src, dict) else None
        if isinstance(geo, dict) and geo.get("status") == "robots-disallowed":
            out.update(u for u in [src.get("url"), *(src.get("alt_urls") or [])] if isinstance(u, str))
    return out


def plan(registry: dict) -> tuple[dict[str, list[str]], dict[str, dict]]:
    """Qué descargar: ``SOURCES`` (menos lo que robots.txt no permite) más las
    fuentes «peru-server» del registro (por grupo, sin repetir URL), y las
    reglas ``follow`` de cada URL."""
    blocked = robots_disallowed(registry)
    groups = {g: [u for u in urls if u not in blocked] for g, urls in SOURCES.items()}
    known = {u for urls in groups.values() for u in urls}
    follow: dict[str, dict] = {}
    for src in peru_sources(registry):
        url = src["url"]
        if isinstance(src.get("follow"), dict):
            follow[url] = src["follow"]
        if url in known:
            continue
        group = re.sub(r"[^a-z0-9-]+", "-", str(src.get("group") or src.get("id") or "registro").lower()).strip("-")
        groups.setdefault(group[:40] or "registro", []).append(url)
        known.add(url)
    return groups, follow


def follow_links(client: httpx.Client, page: dict, rule: dict, seen: set[str]) -> list[dict]:
    """Regla ``follow`` del registro: baja hasta ``max`` enlaces de la página
    que coinciden con ``pattern`` (p. ej. los PDF de un listado)."""
    body = page.get("body") or b""
    if page.get("status") != 200 or not body:
        return []
    try:
        pattern = re.compile(str(rule.get("pattern") or ""))
        limit = max(0, min(int(rule.get("max") or 4), MAX_FOLLOW))
    except (re.error, TypeError, ValueError):
        return []
    if not pattern.pattern:
        return []
    text = body.decode("utf-8", "replace").replace("\\/", "/")  # JSON escapa las barras
    links: list[str] = []
    for m in pattern.finditer(text):
        if len(links) >= limit:
            break
        url = urljoin(page["url"], html.unescape(m.group(1) if m.groups() else m.group(0)))
        if url.startswith(("https://", "http://")) and url not in seen:
            seen.add(url)
            links.append(url)
    out = []
    for url in links:
        r = fetch(client, url)
        r["parent"] = page["url"]
        out.append(r)
    return out


def fetch(client: httpx.Client, url: str) -> dict:
    started = time.monotonic()
    err = ""
    for attempt in range(3):
        try:
            r = client.get(url)
            body = r.content
            return {"url": url, "status": r.status_code, "content_type": r.headers.get("content-type", ""),
                    "bytes": len(body), "elapsed_s": round(time.monotonic() - started, 1),
                    "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "body": body if len(body) <= MAX_BYTES else b""}
        except httpx.HTTPError as exc:
            err = f"{type(exc).__name__}: {exc}"[:200]
            time.sleep(3 * (attempt + 1))
    return {"url": url, "status": None, "error": err, "elapsed_s": round(time.monotonic() - started, 1),
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "body": b""}


def _pdf_link(html: str) -> str | None:
    got = peru.LISTING_RE.search(html) or re.search(r"href=[\"']([^\"']*\?wpdmdl=\d+[^\"']*)", html)
    return got.group(1) if got else None


def enfen_documents(client: httpx.Client, pages: list[dict]) -> list[dict]:
    """Del listado del ENFEN: el PDF del comunicado más reciente y del
    anterior, y las páginas de descarga de los dos números siguientes (los
    mismos sondeos que hace la actualización diaria). Cuando una URL es una
    página de descarga, también baja el PDF que enlaza y lo registra con la
    URL de la página como alias, para que la actualización diaria lo
    encuentre con la misma URL que pide."""
    listing = []
    for p in pages:
        if p.get("status") == 200 and p["body"]:
            try:
                text = p["body"].decode("utf-8", errors="replace")
                if text.lstrip().startswith("["):
                    listing = [i for i in peru.parse_enfen_wp_posts(text).data if i.get("url")]
                else:
                    listing = peru.parse_enfen_listing(text).data
            except (FormatChanged, ValueError):
                continue
            if listing:
                break
    oficial = [i for i in listing if i.get("kind", "oficial") == "oficial"]
    targets = [_clean_wpdm(u) for i in oficial[:2] for u in _communique_urls(i)]
    if oficial:
        y, n = oficial[0]["year"], oficial[0]["number"]
        for k in (1, 2):
            targets += [f"{peru.DHN_BASE}/Archivos/oceanografia/enfen/comunicado-oficial/{n + k:02d}-{y}.pdf",
                        f"{ENFEN_BASE}/download/comunicado-oficial-enfen-n-{n + k:02d}-{y}/"]
    targets = list(dict.fromkeys(targets))
    out = []
    for url in targets:
        r = fetch(client, url)
        out.append(r)
        body = r["body"]
        if r.get("status") == 200 and body and body[:5] != b"%PDF-":
            link = _pdf_link(body.decode("utf-8", "replace"))
            if link and _clean_wpdm(link) != url:
                pdf = fetch(client, _clean_wpdm(link))
                pdf["aliases"] = [url]
                out.append(pdf)
    return out


def _log_fetch(r: dict) -> None:
    log(f"{r.get('status')!s:>4} {r.get('bytes', 0):>9} B {r['elapsed_s']:>5}s {r['url']} {r.get('error', '')}")


def collect(out: Path) -> dict:
    """Descarga todo en ``out`` (index.json + files/). Devuelve el índice."""
    files = out / "files"
    files.mkdir(parents=True, exist_ok=True)
    entries = []
    registry, origin = load_registry(os.environ.get("GITHUB_TOKEN", "").strip())
    groups, follow = plan(registry)
    if registry:
        log(f"registro de fuentes ({origin}): {len(peru_sources(registry))} para este equipo")
    for url in sorted(robots_disallowed(registry) & {u for urls in SOURCES.values() for u in urls}):
        log(f"no se pide {url}: su robots.txt no lo permite (registro)")
    with httpx.Client(timeout=40.0, follow_redirects=True, headers={"User-Agent": UA}) as client:
        results = {}
        for group, urls in groups.items():
            results[group] = [fetch(client, u) for u in urls]
            for r in results[group]:
                _log_fetch(r)
        docs = enfen_documents(client, results["enfen"])
        for r in docs:
            _log_fetch(r)
        results["enfen-docs"] = docs
        seen = {r["url"] for rs in results.values() for r in rs}
        linked = [d for rs in list(results.values()) for r in rs if r["url"] in follow
                  for d in follow_links(client, r, follow[r["url"]], seen)]
        for r in linked:
            _log_fetch(r)
        if linked:
            results["enlaces"] = linked
    for group, rs in results.items():
        for r in rs:
            body = r.pop("body", b"")
            if body and r.get("status") == 200:
                sha = hashlib.sha256(body).hexdigest()
                ext = ".pdf" if body[:5] == b"%PDF-" else ".json" if body.lstrip()[:1] in (b"[", b"{") else ".html"
                name = f"files/{sha[:16]}{ext}"
                (out / name).write_bytes(body)
                r.update({"file": name, "sha256": sha})
            r["group"] = group
            entries.append(r)
    index = {
        "schema": "enso-relay/1",
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "collector": {"host": socket.gethostname(), "tz": "America/Lima"},
        "registry": {"origin": origin or "ninguno", "generated_at": registry.get("generated_at"),
                     "peru_server": len(peru_sources(registry))},
        "entries": entries,
        "summary": {g: f"{sum(1 for e in entries if e['group'] == g and e.get('status') == 200)}/"
                       f"{sum(1 for e in entries if e['group'] == g)}" for g in results},
    }
    (out / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8")
    return index


def heartbeat(idx: dict, result: str) -> dict:
    """Latido de una corrida. Se sube siempre que GitHub responde, aunque
    ninguna fuente lo haga: así el sitio distingue «el recolector no corre»
    (latido viejo) de «las instituciones no responden ni desde el Perú»
    (latido reciente con ``result`` = ``sin-fuentes``)."""
    entries = idx.get("entries") or []
    ok = sum(1 for e in entries if e.get("status") == 200)
    return {
        "schema": "enso-relay-heartbeat/1",
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "result": result,
        "reachable": f"{ok}/{len(entries)}",
        "summary": idx.get("summary") or {},
        "failures": [{k: e[k] for k in ("url", "status", "error") if e.get(k) is not None}
                     for e in entries if e.get("status") != 200][:40],
        "collector": idx.get("collector") or {},
    }


def push_heartbeat(hb: dict, token: str) -> None:
    """Sube solo el latido y deja intacta la última copia buena."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / HEARTBEAT).write_text(json.dumps(hb, indent=1, ensure_ascii=False), encoding="utf-8")
        push(Path(tmp), token, replace=False,
             message=f"relay: latido {hb['at']} ({hb['result']}, {hb['reachable']} fuentes)")


def push(snapshot: Path, token: str, *, replace: bool = True, message: str = "") -> None:
    """Reemplaza el contenido de la rama ``data-peru`` con la nueva copia
    (el historial de git conserva las anteriores). Con ``replace=False``
    solo agrega o reemplaza los archivos de ``snapshot`` (el latido)."""
    remote = os.environ.get("ENSO_RELAY_REMOTE") or f"https://x-access-token:{token}@github.com/{REPO}.git"
    # Sin ayudantes de credenciales (guardarían el token en el llavero o en el
    # administrador de credenciales de Windows) ni ventanas que pidan clave:
    # en una tarea programada nadie las contestaría. Una subida trabada se corta.
    base = ["git", "-c", "credential.helper=", "-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=60"]
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "repo"

        def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
            try:
                res = subprocess.run([*base, *args], cwd=work if work.exists() else tmp,
                                     capture_output=True, text=True, env=env, timeout=900)
            except subprocess.TimeoutExpired:
                raise RuntimeError(f"git {args[0]} falló: sin respuesta en 15 minutos") from None
            if check and res.returncode != 0:
                # No mostrar el token en los mensajes de error.
                raise RuntimeError(f"git {args[0]} falló: {res.stderr.replace(token, '***')[:400]}")
            return res

        ls = git("ls-remote", "--exit-code", "--heads", remote, BRANCH, check=False)
        if ls.returncode not in (0, 2):  # 2: la rama no existe todavía; otro código: red o permisos
            raise RuntimeError(f"git ls-remote falló: {ls.stderr.replace(token, '***')[:400]}")
        exists = ls.returncode == 0
        if exists:
            git("clone", "--depth", "1", "--branch", BRANCH, remote, str(work))
        else:
            work.mkdir()
            git("init", "-q", "-b", BRANCH)
            git("remote", "add", "origin", remote)
        git("config", "user.name", "enso-peru-collector")
        git("config", "user.email", "enso-peru-collector@users.noreply.github.com")
        for p in work.iterdir() if replace else ():
            if p.name != ".git":
                shutil.rmtree(p) if p.is_dir() else p.unlink()
        shutil.copytree(snapshot, work, dirs_exist_ok=True)
        git("add", "-A")
        if git("diff", "--cached", "--quiet", check=False).returncode == 0:
            log("sin cambios respecto de la copia anterior")
            return
        if not message:
            idx = json.loads((snapshot / "index.json").read_text(encoding="utf-8"))
            message = f"relay: fuentes peruanas {idx['collected_at']} ({idx['summary']})"
        git("commit", "-q", "-m", message)
        git("push", "-q", "origin", f"HEAD:{BRANCH}")
        log(f"subido a {REPO}@{BRANCH}")


def dispatch(token: str) -> None:
    """Pide a GitHub la actualización del sitio ahora (evento «enso-refresh»)."""
    r = httpx.post(f"https://api.github.com/repos/{REPO}/dispatches",
                   headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                   json={"event_type": "enso-refresh", "client_payload": {"from": "peru-collector"}}, timeout=30)
    if r.status_code != 204:
        raise RuntimeError(f"dispatch rechazado: HTTP {r.status_code} {r.text[:200]}")
    log("actualización del sitio solicitada")


def run_once(do_push: bool, keep: Path | None, do_dispatch: bool = False) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "snapshot"
        idx = collect(snap)
        log(f"resumen: {idx['summary']}")
        if keep:
            shutil.copytree(snap, keep, dirs_exist_ok=True)
        ok = sum(1 for e in idx["entries"] if e.get("status") == 200)
        token = os.environ.get("GITHUB_TOKEN", "").strip()
        if do_push and not token:
            log("falta GITHUB_TOKEN: no se sube nada")
            return 2
        if do_push and not ok:
            # Una copia vacía reemplazaría a la última buena en data-peru: solo el latido.
            log("ninguna fuente respondió: solo se sube el latido")
            try:
                push_heartbeat(heartbeat(idx, "sin-fuentes"), token)
            except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
                log(f"tampoco se pudo subir el latido: {exc}")
            return 1
        if do_push:
            (snap / HEARTBEAT).write_text(json.dumps(heartbeat(idx, "ok"), indent=1, ensure_ascii=False),
                                          encoding="utf-8")
            push(snap, token)
            if do_dispatch:
                dispatch(token)
    return 0 if ok else 1


def next_run(at: str, now: datetime | None = None) -> datetime:
    h, m = (int(x) for x in at.split(":"))
    now = now or datetime.now(LIMA)
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return target if target > now else target + timedelta(days=1)


def probe() -> int:
    """Muestra qué fuentes responden desde esta máquina, sin subir nada."""
    groups, _ = plan(load_registry(os.environ.get("GITHUB_TOKEN", "").strip())[0])
    with httpx.Client(timeout=25.0, follow_redirects=True, headers={"User-Agent": UA}) as client:
        ok = 0
        for group, urls in groups.items():
            for u in urls:
                r = fetch(client, u)
                good = r.get("status") == 200 and r.get("bytes", 0) > 500
                ok += good
                print(f"{'OK ' if good else 'NO '} {group:8} {r.get('status')!s:>4} {r.get('bytes', 0):>9} B "
                      f"{r['elapsed_s']:>5}s {u} {r.get('error', '')}", flush=True)
    total = sum(len(v) for v in groups.values())
    print(f"\n{ok}/{total} fuentes responden desde esta máquina.")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--probe", action="store_true", help="solo comprobar el acceso")
    mode.add_argument("--once", action="store_true", help="recolectar una vez")
    mode.add_argument("--daemon", action="store_true", help="recolectar todos los días a la hora --at")
    ap.add_argument("--push", action="store_true", help="subir a la rama data-peru (requiere GITHUB_TOKEN)")
    ap.add_argument("--dispatch", action="store_true",
                    default=os.environ.get("ENSO_DISPATCH") == "1",
                    help="tras subir, pedir la actualización del sitio en el momento")
    ap.add_argument("--at", default=os.environ.get("ENSO_COLLECT_AT", "21:00"), help="hora de Lima, HH:MM")
    ap.add_argument("--keep", type=Path, help="guardar también una copia local en esta carpeta")
    args = ap.parse_args(argv)
    if args.probe:
        return probe()
    if args.once:
        return run_once(args.push, args.keep, args.dispatch)
    while True:
        t = next_run(args.at)
        log(f"próxima recolección: {t:%Y-%m-%d %H:%M} (Lima)")
        time.sleep(max(1, (t - datetime.now(LIMA)).total_seconds()))
        try:
            run_once(args.push, args.keep, args.dispatch)
        except Exception as exc:  # seguir funcionando al día siguiente
            log(f"ERROR {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
