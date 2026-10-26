"""Las restricciones de robots.txt de una medición que no pasa las pruebas, sobre el registro de la rama principal.

Uso (lo corre la sonda semanal, probe-sources.yml, cuando el registro medido no pasa las pruebas):
    python -m tools.registry_restrict BASE_SOURCES BASE_REACH --report ARCHIVO

Compara el registro medido (``registry/sources.json``) con el de la rama principal (``BASE_SOURCES``) y busca las
URL que restringe por robots.txt (``registry.restrictions``). n8n pide sin leer robots.txt lo que el registro de la
rama principal da por permitido, así que esas restricciones no esperan a que alguien arregle las pruebas. Si hay,
escribe en ``registry/reachability.json`` la de la rama principal (``BASE_REACH``) con las mediciones nuevas de esas
URL (y de las que, si no, dejarían de estar restringidas: ``restrict``), regenera ``registry/sources.json`` y anota la
lista en ARCHIVO (Markdown, para el issue). Así lo que llega a la rama principal solo quita pedidos. Sin
restricciones no cambia nada ni escribe ARCHIVO.

Sale con 1 si el registro que resulta no es válido (``registry.validate``): entonces no se escribe en la rama
principal.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from enso import registry  # noqa: E402
from tools import build_registry  # noqa: E402


def _by_url(reg: dict) -> dict[str, dict]:
    return {u: r for s in (reg or {}).get("sources") or [] for u, r in (s.get("by_url") or {}).items()
            if isinstance(u, str) and isinstance(r, dict)}


def _relaxed(b: dict, r: dict) -> bool:
    """``r`` pide más que ``b``: un canal nuevo, ya no ``robots-disallowed``, un robots menos estricto o sin su
    ``hop``."""
    rank = {"disallowed": 2, "unknown": 1}
    return bool(set(r.get("channels") or []) - set(b.get("channels") or [])
                or (b.get("status") == "robots-disallowed" and r.get("status") != "robots-disallowed")
                or rank.get(r.get("robots"), 0) < rank.get(b.get("robots"), 0)
                or (b.get("hop") and r.get("hop") != b["hop"]))


def restrict(base_sources: dict, base_reach: dict, measured_reach: dict, measured: dict) -> tuple[dict, dict]:
    """Las URL que la medición restringe (``registry.restrictions``) y la ``reachability.json`` de la rama principal
    con las mediciones nuevas de esas URL (``{}`` si no hay ninguna).

    ``registry.build`` cuenta ``STALE_DAYS`` desde la medición más reciente: con las de esta semana, lo de la rama
    principal de más de ``STALE_DAYS`` (un robots.txt en contra, un ``hop``) dejaría de contar. Por eso, hasta que no
    quede ninguna, llevan también su medición nueva las URL que así quedarían menos restringidas que en la rama
    principal (la de esta semana, que es la que vale). Las demás quedan como en la rama principal, aunque la medición
    las restrinja (o las restrinja menos): un robots.txt que no respondió esta semana no abre lo que la rama
    principal tiene prohibido."""
    found = registry.restrictions(base_sources, measured)
    if not found:
        return found, {}
    new, before = measured_reach.get("urls") or {}, _by_url(base_sources)
    urls = dict(base_reach.get("urls") or {})
    take = set(found)
    while True:
        urls.update({u: new[u] for u in take if u in new})
        after = _by_url(registry.build(urls))
        more = {u for u, r in after.items() if u in before and u in new and u not in take and _relaxed(before[u], r)}
        if not more:
            break
        take |= more
    return found, {**base_reach, "schema": measured_reach.get("schema", base_reach.get("schema")),
                   "updated_at": measured_reach.get("updated_at", base_reach.get("updated_at")),
                   "urls": dict(sorted(urls.items()))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base_sources", type=Path)
    ap.add_argument("base_reach", type=Path)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--registry", type=Path, default=registry.REGISTRY)
    ap.add_argument("--reach", type=Path, default=registry.REACHABILITY)
    a = ap.parse_args(argv)

    def load(p: Path) -> dict:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() and p.stat().st_size else {}

    found, reach = restrict(load(a.base_sources), load(a.base_reach), load(a.reach), load(a.registry))
    if not found:
        print("La medición no restringe ninguna URL por robots.txt.")
        return 0
    a.reach.write_text(json.dumps(reach, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    reg = registry.build(registry.load_reachability(a.reach))
    errs = registry.validate(reg)
    a.registry.write_text(build_registry.render(reg), encoding="utf-8")
    for e in errs:
        print(f"[error] {e}")
    lines = [f"- `{u}`: {'; '.join(why)}" for u, why in sorted(found.items())]
    note = "" if not errs else ("\n\nEl registro con solo esas mediciones no es válido (`registry.validate`): "
                                "no se escribió en la rama principal.")
    a.report.write_text(f"URL que la medición restringe por robots.txt ({len(found)}):\n\n" + "\n".join(lines)
                        + note + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
