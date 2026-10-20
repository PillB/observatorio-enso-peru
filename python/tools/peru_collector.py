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


def collect(out: Path) -> dict:
    """Descarga todo en ``out`` (index.json + files/). Devuelve el índice."""
    files = out / "files"
    files.mkdir(parents=True, exist_ok=True)
    entries = []
    with httpx.Client(timeout=40.0, follow_redirects=True, headers={"User-Agent": UA}) as client:
        results = {}
        for group, urls in SOURCES.items():
            results[group] = [fetch(client, u) for u in urls]
            for r in results[group]:
                log(f"{r.get('status')!s:>4} {r.get('bytes', 0):>9} B {r['elapsed_s']:>5}s {r['url']} {r.get('error', '')}")
        docs = enfen_documents(client, results["enfen"])
        for r in docs:
            log(f"{r.get('status')!s:>4} {r.get('bytes', 0):>9} B {r['elapsed_s']:>5}s {r['url']} {r.get('error', '')}")
        results["enfen-docs"] = docs
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
        "entries": entries,
        "summary": {g: f"{sum(1 for e in entries if e['group'] == g and e.get('status') == 200)}/"
                       f"{sum(1 for e in entries if e['group'] == g)}" for g in results},
    }
    (out / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8")
    return index


def push(snapshot: Path, token: str) -> None:
    """Reemplaza el contenido de la rama ``data-peru`` con la nueva copia
    (el historial de git conserva las anteriores)."""
    remote = os.environ.get("ENSO_RELAY_REMOTE") or f"https://x-access-token:{token}@github.com/{REPO}.git"
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "repo"

        def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
            res = subprocess.run(["git", *args], cwd=work if work.exists() else tmp,
                                 capture_output=True, text=True)
            if check and res.returncode != 0:
                # No mostrar el token en los mensajes de error.
                raise RuntimeError(f"git {args[0]} falló: {res.stderr.replace(token, '***')[:400]}")
            return res

        exists = subprocess.run(["git", "ls-remote", "--exit-code", "--heads", remote, BRANCH],
                                capture_output=True, text=True).returncode == 0
        if exists:
            git("clone", "--depth", "1", "--branch", BRANCH, remote, str(work))
        else:
            work.mkdir()
            git("init", "-q", "-b", BRANCH)
            git("remote", "add", "origin", remote)
        git("config", "user.name", "enso-peru-collector")
        git("config", "user.email", "enso-peru-collector@users.noreply.github.com")
        for p in work.iterdir():
            if p.name != ".git":
                shutil.rmtree(p) if p.is_dir() else p.unlink()
        shutil.copytree(snapshot, work, dirs_exist_ok=True)
        git("add", "-A")
        if git("diff", "--cached", "--quiet", check=False).returncode == 0:
            log("sin cambios respecto de la copia anterior")
            return
        idx = json.loads((snapshot / "index.json").read_text(encoding="utf-8"))
        git("commit", "-q", "-m", f"relay: fuentes peruanas {idx['collected_at']} ({idx['summary']})")
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
        if do_push:
            token = os.environ.get("GITHUB_TOKEN", "").strip()
            if not token:
                log("falta GITHUB_TOKEN: no se sube nada")
                return 2
            push(snap, token)
            if do_dispatch:
                dispatch(token)
    ok = sum(1 for e in idx["entries"] if e.get("status") == 200)
    return 0 if ok else 1


def next_run(at: str, now: datetime | None = None) -> datetime:
    h, m = (int(x) for x in at.split(":"))
    now = now or datetime.now(LIMA)
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return target if target > now else target + timedelta(days=1)


def probe() -> int:
    """Muestra qué fuentes responden desde esta máquina, sin subir nada."""
    with httpx.Client(timeout=25.0, follow_redirects=True, headers={"User-Agent": UA}) as client:
        ok = 0
        for group, urls in SOURCES.items():
            for u in urls:
                r = fetch(client, u)
                good = r.get("status") == 200 and r.get("bytes", 0) > 500
                ok += good
                print(f"{'OK ' if good else 'NO '} {group:8} {r.get('status')!s:>4} {r.get('bytes', 0):>9} B "
                      f"{r['elapsed_s']:>5}s {u} {r.get('error', '')}", flush=True)
    total = sum(len(v) for v in SOURCES.values())
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
