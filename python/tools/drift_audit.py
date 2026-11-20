"""Auditoría de deriva sobre las copias crudas de ``data-archive``: vuelve a leer cada versión archivada de cada fuente
con su lector actual y las compara de a pares con la guardia de regresión (``enso.drift``); además busca páginas de
verificación antirobots archivadas como si fueran la fuente (``fetch.block_page``).

Sirve para repetir la auditoría de noviembre de 2026 (docs/auditoria-deriva-fuentes.md) después de cambiar un lector
o una firma de bloqueo: lo que hoy pasaría inadvertido aparece en la salida. No pide nada a la red.

Uso (desde python/, con la rama traída: ``git fetch origin data-archive``):
    python -m tools.drift_audit [--ref origin/data-archive] [--source cpc-oni] [--days 8] [--json salida.json]

``--days N``: solo cuenta las copias archivadas en los últimos N días (por la fecha del nombre, ``AAAA-MM-DD-…``); así
la corrida semanal (``.github/workflows/drift-audit.yml``) avisa lo nuevo y no lo ya revisado. Sale con 1 si encontró
algo.
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


def _git(*args: str, binary: bool = False):
    out = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=True)
    return out.stdout if binary else out.stdout.decode("utf-8", "replace")


def audit(ref: str, only: set[str] | None = None) -> list[dict]:
    files = _git("ls-tree", "-r", "--name-only", ref, "sources").split()
    found: list[dict] = []
    for path in files:  # páginas de verificación archivadas como fuente (feeds de noticias incluidos)
        if path.endswith((".xml", ".json", ".txt", ".html")):
            body = _git("show", f"{ref}:{path}", binary=True)
            mark = block_page(body)
            if mark and not path.endswith(".html"):
                found.append({"kind": "archived-block-page", "file": path, "block": mark})
    for src in SOURCES:
        if only and src.id not in only:
            continue
        # Los PDF guardados junto al listado del ENFEN (comunicados, informes) son documentos, no la fuente.
        versions = sorted(f for f in files if f.startswith(f"sources/{src.id}/") and not f.endswith(".pdf"))
        prev = None
        for path in versions:
            body = _git("show", f"{ref}:{path}", binary=True)
            try:
                data = src.parse(Response(src.urls[0], body, "archive", 200)).data
            except (FormatChanged, ValueError, KeyError) as exc:
                found.append({"kind": "unreadable", "file": path, "error": f"{type(exc).__name__}: {exc}"[:300]})
                continue
            if prev is not None:
                for code, msg in drift.compare(prev[1], data, src.id):
                    found.append({"kind": code, "file": path, "previous": prev[0], "message": msg})
            prev = (path, data)
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ref", default="origin/data-archive")
    ap.add_argument("--source", action="append", help="solo esta fuente (se puede repetir)")
    ap.add_argument("--days", type=int, help="solo las copias de los últimos N días")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    found = audit(a.ref, set(a.source) if a.source else None)
    if a.days is not None:
        since = (date.today() - timedelta(days=a.days)).isoformat()
        found = [f for f in found if f["file"].rsplit("/", 1)[-1][:10] >= since]
    for f in found:
        print(f"{f['kind']:22} {f['file']}  {f.get('message') or f.get('block') or f.get('error') or ''}")
    if a.json:
        a.json.write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(found)} hallazgos", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
