"""Genera ``registry/sources.json`` (registro único de fuentes) y lo valida.

Uso:
    python -m tools.build_registry [--check]   # --check: falla si el archivo no está al día
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from enso import registry  # noqa: E402


def render(reg: dict) -> str:
    return json.dumps(reg, ensure_ascii=False, indent=1) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", type=Path, default=registry.REGISTRY)
    a = ap.parse_args(argv)
    old = json.loads(a.out.read_text(encoding="utf-8")) if a.out.exists() else None
    reg = registry.build()
    if old and {k: v for k, v in old.items() if k != "generated_at"} == {k: v for k, v in reg.items() if k != "generated_at"}:
        reg["generated_at"] = old["generated_at"]  # sin cambios: no se reescribe la fecha
    errs = registry.validate(reg)
    for e in errs:
        print(f"[error] {e}")
    if a.check:
        if old is None or render(old) != render(reg):
            print(f"{a.out} no está al día: corre python -m tools.build_registry")
            return 1
        return 1 if errs else 0
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(render(reg), encoding="utf-8")
    by: dict[str, int] = {}
    for s in reg["sources"]:
        by[s["geoblock"]["status"]] = by.get(s["geoblock"]["status"], 0) + 1
    robots: dict[str, int] = {}
    for v in registry.url_robots(reg).values():
        robots[v] = robots.get(v, 0) + 1
    print(f"{a.out}: {len(reg['sources'])} fuentes; " + ", ".join(f"{k} {v}" for k, v in sorted(by.items()))
          + "; robots.txt por URL: " + ", ".join(f"{k} {v}" for k, v in sorted(robots.items())))
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
