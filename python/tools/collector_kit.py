"""Arma el kit del recolector: un .zip con todo lo que necesita el equipo
del Perú (código, dependencias, configuración, instaladores, lanzadores,
verificación y manual), sin clonar el repositorio.

  python -m tools.collector_kit --out ../dist

Deja ``recolector-peru.zip`` y ``recolector-peru.zip.sha256``. El zip es
reproducible (mismo contenido, mismos bytes): entradas ordenadas, fecha
del último commit, finales de línea normalizados (CRLF para .cmd y .ps1,
LF para .sh y .command) y permisos de ejecución para los scripts de macOS
y Linux. ``kit.json`` lleva la versión y el sha256 de cada archivo; la
verificación lo usa para detectar archivos faltantes o modificados.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[2]
NAME = "recolector-peru"
TOOLS = ["__init__.py", "peru_collector.py", "collector_service.py", "collector_schedule.py", "collector_check.py"]
#: Archivos del repositorio que van al kit (ruta en el repo -> ruta en el kit).
SKIP_PARTS = {"__pycache__", ".pytest_cache"}
CRLF = {".cmd", ".ps1"}
LF = {".sh", ".command", ".py", ".md", ".txt", ".yaml", ".yml", ".service", ".timer", ""}
EXECUTABLE = {".sh", ".command"}
BOM = b"\xef\xbb\xbf"


def kit_files(repo: Path = REPO) -> dict[str, Path]:
    files: dict[str, Path] = {}

    def add_tree(src: Path, dest: str, pattern: str = "*") -> None:
        for p in sorted(src.rglob(pattern)):
            if p.is_file() and not SKIP_PARTS & set(p.parts) and p.suffix not in (".pyc",) and p.name != ".env":
                files[f"{dest}/{p.relative_to(src).as_posix()}"] = p

    files["python/requirements.txt"] = repo / "python" / "requirements.txt"
    add_tree(repo / "python" / "enso", "python/enso")  # código y datos (p. ej. data/ubigeo.json)
    for t in TOOLS:
        files[f"python/tools/{t}"] = repo / "python" / "tools" / t
    add_tree(repo / "config", "config", "*.yaml")
    for p in sorted((repo / "collector").iterdir()):
        if p.is_file() and p.name not in (".env", ".gitignore", "LEEME.txt"):
            files[f"collector/{p.name}"] = p
    add_tree(repo / "collector" / "lanzadores", ".")  # INSTALAR-*, VERIFICAR-*, otras-acciones/
    files["LEEME.txt"] = repo / "collector" / "LEEME.txt"
    files["docs/servidor-peru.md"] = repo / "docs" / "servidor-peru.md"
    files["LICENSE"] = repo / "LICENSE"
    # Registro de fuentes: copia de respaldo (el recolector lee primero el de GitHub).
    if (repo / "registry" / "sources.json").is_file():
        files["registry/sources.json"] = repo / "registry" / "sources.json"
    missing = [str(p) for p in files.values() if not p.is_file()]
    if missing:
        raise FileNotFoundError(f"faltan archivos para el kit: {missing}")
    return {k.removeprefix("./"): v for k, v in files.items()}


def normalized(path: Path, rel: str) -> bytes:
    data = path.read_bytes()
    suffix = Path(rel).suffix.lower()
    if suffix in CRLF:
        text = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        if suffix == ".ps1" and not text.startswith(BOM):  # PowerShell 5.1 lee sin BOM como ANSI
            text = BOM + text
        return text
    if suffix == ".txt":  # el Bloc de notas antiguo necesita el BOM para mostrar los acentos
        text = data.replace(b"\r\n", b"\n")
        return text if text.startswith(BOM) else BOM + text
    if suffix in LF:
        return data.replace(b"\r\n", b"\n")
    return data


def git(*args: str, repo: Path = REPO) -> str:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def version_info(repo: Path = REPO) -> dict:
    commit = git("rev-parse", "HEAD", repo=repo)
    ts = git("log", "-1", "--format=%ct", repo=repo)
    when = datetime.fromtimestamp(int(ts), timezone.utc) if ts.isdigit() else datetime(2026, 1, 1, tzinfo=timezone.utc)
    dirty = bool(git("status", "--porcelain", "--", "python", "collector", "config", "docs", repo=repo))
    version = f"{when:%Y.%m.%d}-{commit[:7] or 'local'}{'-modificado' if dirty else ''}"
    return {"version": version, "commit": commit or None, "date": when}


def build(out: Path, repo: Path = REPO) -> tuple[Path, str]:
    files = kit_files(repo)
    info = version_info(repo)
    blobs = {rel: normalized(src, rel) for rel, src in files.items()}
    manifest = {
        "name": NAME,
        "version": info["version"],
        "commit": info["commit"],
        "repository": "https://github.com/PillB/observatorio-enso-peru",
        "files": {rel: hashlib.sha256(b).hexdigest() for rel, b in sorted(blobs.items())},
    }
    # El sitio publicado, para el User-Agent del recolector (lo fija el flujo
    # cuando el sitio no está en GitHub Pages; ver collector_service.prepare).
    if os.environ.get("ENSO_CONTACT_URL", "").strip():
        manifest["contact_url"] = os.environ["ENSO_CONTACT_URL"].strip()
    blobs["kit.json"] = (json.dumps(manifest, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
    stamp = info["date"].timetuple()[:6]
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{NAME}.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in sorted(blobs):
            zi = zipfile.ZipInfo(f"{NAME}/{rel}", date_time=stamp)
            mode = 0o755 if Path(rel).suffix in EXECUTABLE else 0o644
            zi.external_attr = (0o100000 | mode) << 16
            zi.create_system = 3  # Unix: conserva los permisos al descomprimir en macOS y Linux
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, blobs[rel])
    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    (out / f"{NAME}.zip.sha256").write_text(f"{sha}  {NAME}.zip\n", encoding="utf-8")
    return target, sha


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=REPO / "dist")
    args = ap.parse_args(argv)
    target, sha = build(args.out)
    with zipfile.ZipFile(target) as z:
        n = len(z.namelist())
    print(f"{target} · {n} archivos · {target.stat().st_size / 1024:.0f} KB · versión {version_info()['version']}")
    print(f"sha256 {sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
