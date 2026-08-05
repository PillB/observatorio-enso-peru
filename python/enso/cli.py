"""CLI del pipeline ENSO.

Uso::

    python -m enso.cli fetch --indicator nino12
    python -m enso.cli run
    python -m enso.cli validate
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .fetchers import FetchError, get_fetcher_class
from .methodology import INDICATOR_BY_ID
from .pipeline import DATA_VERSION, Pipeline
from .sources import SOURCE_BY_ID, SOURCES


def _indicator_to_source(indicator_id: str) -> str:
    ind = INDICATOR_BY_ID.get(indicator_id)
    if ind is None:
        raise SystemExit(f"indicator '{indicator_id}' desconocido")
    return ind.sourceId


def cmd_fetch(args: argparse.Namespace) -> int:
    """Descarga un único indicador y muestra el resultado."""
    source_id = _indicator_to_source(args.indicator)
    cls = get_fetcher_class(source_id)
    if cls is None:
        print(f"[fetch] no fetcher registrado para {source_id}", file=sys.stderr)
        return 2
    fetcher = cls(cache_dir=args.cache_dir)
    try:
        result = fetcher.fetch(allow_network=not args.offline)
    except FetchError as e:
        print(f"[fetch] fallo: {e}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "source_id": result.source_id,
                "sha256": result.sha256,
                "from_cache": result.from_cache,
                "preliminary": result.preliminary,
                "fetched_at": result.fetched_at,
                "bytes": len(result.content),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Ejecuta el pipeline completo."""
    pipe = Pipeline(
        out_dir=args.out_dir,
        cache_dir=args.cache_dir,
        allow_network=not args.offline,
    )
    run = pipe.run()
    print(
        json.dumps(
            {
                "ok": run.ok,
                "data_version": run.data_version,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "indicators": [
                    {
                        "id": r.indicator_id,
                        "ok": r.ok,
                        "stale": r.stale,
                        "from_cache": r.from_cache,
                        "last_month": r.last_month,
                        "last_value": r.last_value,
                        "error": r.error,
                    }
                    for r in run.results
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if run.ok else 1


def cmd_validate(args: argparse.Namespace) -> int:
    """Valida los artefactos producidos por el pipeline."""
    out_dir = Path(args.out_dir)
    errors: list[str] = []

    # Manifiesto.
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.exists():
        errors.append(f"falta {manifest_path}")
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("data_version") != DATA_VERSION:
                errors.append(
                    f"versión de datos mismatch: {manifest.get('data_version')} != {DATA_VERSION}"
                )
            for ind in manifest.get("indicators", []):
                if not ind.get("ok") and not ind.get("stale"):
                    errors.append(f"indicador {ind.get('id')} fallo sin fallback stale")
        except json.JSONDecodeError as e:
            errors.append(f"manifest.json inválido: {e}")

    # sources.json debe listar todas las SOURCES.
    sources_path = out_dir / "sources.json"
    if not sources_path.exists():
        errors.append(f"falta {sources_path}")
    else:
        try:
            srcs = json.loads(sources_path.read_text(encoding="utf-8"))
            ids = {s["id"] for s in srcs}
            for s in SOURCES:
                if s.id not in ids:
                    errors.append(f"source {s.id} ausente de sources.json")
        except json.JSONDecodeError as e:
            errors.append(f"sources.json inválido: {e}")

    # status.json.
    status_path = out_dir / "status.json"
    if not status_path.exists():
        errors.append(f"falta {status_path}")

    if errors:
        for e in errors:
            print(f"[validate] {e}", file=sys.stderr)
        return 1
    print("[validate] OK")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="enso.cli",
        description="Pipeline del Observatorio ENSO Perú",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="No usar la red; sólo caché (degradación graceful).",
    )
    parser.add_argument(
        "--out-dir", default="out", help="Directorio de salida (default: out)."
    )
    parser.add_argument(
        "--cache-dir", default="cache", help="Directorio de caché (default: cache)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="Descarga un único indicador.")
    p_fetch.add_argument(
        "--indicator",
        required=True,
        choices=list(INDICATOR_BY_ID.keys()),
        help="Identificador del indicador.",
    )
    # Permite --offline también después del subcomando (ergonómico).
    p_fetch.add_argument("--offline", action="store_true",
                         help="No usar la red; sólo caché.")
    p_fetch.set_defaults(func=cmd_fetch)

    p_run = sub.add_parser("run", help="Ejecuta el pipeline completo.")
    p_run.add_argument("--offline", action="store_true",
                       help="No usar la red; sólo caché.")
    p_run.set_defaults(func=cmd_run)

    p_val = sub.add_parser("validate", help="Valida los artefactos producidos.")
    p_val.set_defaults(func=cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # Si el subcomando tiene su propio --offline, combina con el global.
    sub_offline = getattr(args, "offline", False)
    if hasattr(args, "offline") and args.__dict__.get("offline") is False:
        # argparse ya combinó; no necesitamos hacer nada.
        pass
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
