"""Une el histórico de noticias de una corrida con la copia de la rama data-archive (job «archive»).

La copia nunca pierde notas: quedan primero las que ya tenía, en su orden, y al final las de la corrida
que no estaban (por ``id``). Así sirve aunque la corrida haya publicado un histórico incompleto
(«restarted») o no haya podido bajar la copia para sumarle sus notas. Una copia rota se reemplaza por la
de la corrida, con aviso. Si el resultado no cabe (GitHub no acepta archivos de más de 100 MB), queda la
copia anterior y se avisa: hay que dividir el histórico.

Uso: python3 python/tools/merge_history.py <histórico de la corrida .jsonl.gz> <copia .jsonl.gz>
Solo usa la biblioteca estándar: el job «archive» no instala dependencias."""

from __future__ import annotations

import gzip
import io
import json
import os
import sys
import zlib
from pathlib import Path

#: Por debajo de los 100 MB por archivo que acepta GitHub.
LIMIT = 90 * 2**20


def _lines(p: Path) -> list[str]:
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return fh.read().splitlines()


def merge(new: Path, old: Path, limit: int = LIMIT) -> str:
    """Escribe en ``old`` la unión de ``old`` y ``new``; devuelve la línea para el registro del job."""
    try:
        fresh = _lines(new)
    except (OSError, EOFError, zlib.error, UnicodeDecodeError) as exc:
        return f"::warning::El histórico de noticias de esta corrida no se pudo leer ({exc}); queda la copia anterior."
    note = ""
    try:
        kept = _lines(old) if old.exists() else []
    except (OSError, EOFError, zlib.error, UnicodeDecodeError) as exc:
        kept, note = [], f"::warning::La copia del histórico de data-archive estaba rota ({exc}); se reemplaza por la de esta corrida."
    seen: set[str] = set()
    out: list[str] = []

    def add(lines: list[str]) -> None:
        for line in lines:
            try:
                key = json.loads(line).get("id")
            except (ValueError, AttributeError):
                continue
            if isinstance(key, str) and key not in seen:
                seen.add(key)
                out.append(line)

    add(kept)
    before = len(out)
    add(fresh)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as gz:  # mismos datos, mismos bytes
        gz.write("".join(line + "\n" for line in out).encode("utf-8"))
    data = buf.getvalue()
    if len(data) >= limit:
        return (f"::warning::El histórico de noticias comprimido pesaría {len(data)} bytes: no cabe en data-archive y "
                "queda la copia anterior. Hay que dividirlo (docs/operaciones.md).")
    tmp = old.with_name(old.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, old)
    return note or f"Copia del histórico de noticias: {len(out)} notas ({len(out) - before} nuevas)."


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(__doc__.split("\n\n")[-2], file=sys.stderr)
        return 2
    print(merge(Path(args[0]), Path(args[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
