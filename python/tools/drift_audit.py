"""Auditoría de deriva sobre las copias crudas de ``data-archive``: vuelve a leer cada versión archivada de cada fuente
con su lector actual y las compara de a pares con la guardia de regresión (``enso.drift``); además busca páginas de
verificación antirobots archivadas como si fueran la fuente (``fetch.block_page``).

Sirve para repetir la auditoría de noviembre de 2026 (docs/auditoria-deriva-fuentes.md) después de cambiar un lector
o una firma de bloqueo: lo que hoy pasaría inadvertido aparece en la salida. No pide nada a la red.

Uso (desde python/, con la rama traída: ``git fetch --depth=1 origin data-archive``):
    python -m tools.drift_audit --ref FETCH_HEAD [--source cpc-oni] [--days 7] [--all] [--json salida.json]

``--days N``: solo las copias archivadas en los últimos N días (por la fecha del nombre, ``AAAA-MM-DD-…``), cada una
comparada con la versión anterior aunque sea más vieja; así la corrida semanal (``.github/workflows/drift-audit.yml``)
avisa lo nuevo y lee poco. Los hallazgos ya revisados (``drift_audit_known.json``: las páginas de Imunify360 de
octubre y noviembre de 2026 y la corrección de PSL del 18-11) no cuentan salvo con ``--all``.

Sale con 0 si no hay nada nuevo, 1 si encontró algo y 2 si no pudo auditar (la ref no existe, una fuente desconocida).
Las versiones del mismo día se ordenan por nombre (fecha y hash), no por hora: el archivo no guarda la hora.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from enso import drift
from enso.feeds import FormatChanged
from enso.fetch import Response, block_page
from enso.observatory import SOURCES

ROOT = Path(__file__).resolve().parents[2]


KNOWN = Path(__file__).with_name("drift_audit_known.json")
#: Copias que se revisan buscando páginas de verificación (los PDF y los ZIP no lo son nunca).
SCANNED = (".xml", ".json", ".txt", ".html", ".csv")


class AuditError(RuntimeError):
    """No se pudo auditar (la ref no existe o git falló): sale con 2, no con 1 («encontró algo»)."""


def _git(*args: str, binary: bool = False):
    out = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True)
    if out.returncode:
        raise AuditError(f"git {' '.join(args)}: {out.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return out.stdout if binary else out.stdout.decode("utf-8", "replace")


class _Blobs:
    """Lee muchos archivos de una ref con un solo ``git cat-file --batch`` (un ``git show`` por copia tardaba
    minutos con 9.000 copias)."""

    def __init__(self, ref: str):
        self.ref = ref
        self.proc = subprocess.Popen(["git", "-C", str(ROOT), "cat-file", "--batch"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE)

    def read(self, path: str) -> bytes:
        self.proc.stdin.write(f"{self.ref}:{path}\n".encode())
        self.proc.stdin.flush()
        head = self.proc.stdout.readline().decode().split()
        if len(head) < 3 or head[1] != "blob":
            raise AuditError(f"no se pudo leer {self.ref}:{path}")
        body = self.proc.stdout.read(int(head[2]))
        self.proc.stdout.read(1)  # salto de línea final
        return body

    def close(self) -> None:
        self.proc.stdin.close()
        self.proc.wait()


def _day(path: str) -> str:
    return path.rsplit("/", 1)[-1][:10]


def known() -> set[tuple[str, str]]:
    """(tipo, archivo) de los hallazgos ya revisados."""
    if not KNOWN.is_file():
        return set()
    return {(k["kind"], k["file"]) for k in json.loads(KNOWN.read_text(encoding="utf-8"))["findings"]}


def audit(ref: str, only: set[str] | None = None, since: str | None = None) -> list[dict]:
    """Hallazgos de las copias de ``ref`` (con ``since``, solo los de copias de ese día en adelante)."""
    files = _git("ls-tree", "-r", "--name-only", ref, "sources").split()
    dirs = {f.split("/")[1] for f in files if f.count("/") >= 2}
    unknown = sorted((only or set()) - dirs - {s.id for s in SOURCES})
    if unknown:
        raise AuditError(f"fuentes desconocidas: {', '.join(unknown)}")
    blobs = _Blobs(ref)
    found: list[dict] = []
    try:
        for path in files:  # páginas de verificación archivadas como fuente (feeds de noticias incluidos)
            if not path.endswith(SCANNED) or (only and path.split("/")[1] not in only) or (since and _day(path) < since):
                continue
            mark = block_page(blobs.read(path))
            if mark:
                found.append({"kind": "archived-block-page", "file": path, "block": mark})
        for src in SOURCES:
            if only and src.id not in only:
                continue
            # Los PDF guardados junto al listado del ENFEN (comunicados, informes) son documentos, no la fuente.
            versions = sorted(f for f in files if f.startswith(f"sources/{src.id}/") and f.endswith(SCANNED))
            if since:  # las de la ventana y, como base, la última anterior
                first = next((i for i, f in enumerate(versions) if _day(f) >= since), len(versions))
                versions = versions[max(0, first - 1):]
            prev = None
            for path in versions:
                try:
                    data = src.parse(Response(src.urls[0], blobs.read(path), "archive", 200)).data
                except (FormatChanged, ValueError, KeyError) as exc:
                    if not since or _day(path) >= since:
                        found.append({"kind": "unreadable", "file": path, "error": f"{type(exc).__name__}: {exc}"[:300]})
                    continue
                if prev is not None:
                    for code, msg in drift.compare(prev[1], data, src.id):
                        found.append({"kind": code, "file": path, "previous": prev[0], "message": msg})
                prev = (path, data)
    finally:
        blobs.close()
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ref", default="origin/data-archive",
                    help="ref de data-archive (FETCH_HEAD después de «git fetch origin data-archive»)")
    ap.add_argument("--source", action="append", help="solo esta fuente (se puede repetir)")
    ap.add_argument("--days", type=int, help="solo las copias de los últimos N días")
    ap.add_argument("--all", action="store_true", help="incluir los hallazgos ya revisados")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    since = (date.today() - timedelta(days=a.days)).isoformat() if a.days is not None else None
    try:
        found = audit(a.ref, set(a.source) if a.source else None, since)
    except AuditError as exc:
        print(f"no se pudo auditar: {exc}", file=sys.stderr)
        return 2
    reviewed = set() if a.all else known()
    skipped = [f for f in found if (f["kind"], f["file"]) in reviewed]
    found = [f for f in found if (f["kind"], f["file"]) not in reviewed]
    for f in found:
        print(f"{f['kind']:22} {f['file']}  {f.get('message') or f.get('block') or f.get('error') or ''}")
    if a.json:
        a.json.write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(found)} hallazgos" + (f" ({len(skipped)} ya revisados no cuentan; --all los muestra)" if skipped else ""),
          file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
