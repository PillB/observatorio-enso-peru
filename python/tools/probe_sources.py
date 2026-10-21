"""Mide desde dónde responde cada URL del registro y actualiza ``registry/reachability.json``.

Corre en GitHub Actions (vantage «github-actions», un servidor de EE. UU.
como el de n8n) y también puede leer el ``index.json`` del recolector del
Perú (rama ``data-peru``) para anotar qué respondió desde allí. Con ambas
mediciones el registro decide qué fuentes están geobloqueadas.

Uso:
    python -m tools.probe_sources [--vantage github-actions] [--peru-index ruta/index.json] [--only id ...]
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from enso import registry  # noqa: E402
from enso.reach import classify  # noqa: E402

UA = ("Mozilla/5.0 (compatible; Observatorio-ENSO-Peru/4.0; source-probe; "
      "+https://github.com/PillB/observatorio-enso-peru)")


def probe(urls: list[str], vantage: str, timeout: float = 25.0) -> dict[str, dict]:
    client = httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": UA})
    locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
    last: dict[str, float] = {}

    def one(url: str) -> tuple[str, dict]:
        host = urlparse(url).netloc
        with locks[host]:  # una consulta a la vez por servidor, con pausa de cortesía
            wait = 1.5 - (time.monotonic() - last.get(host, 0))
            if wait > 0:
                time.sleep(wait)
            started = time.monotonic()
            try:
                r = client.get(url)
                status, body, err = r.status_code, r.content[:200_000], ""
            except httpx.HTTPError as exc:
                status, body, err = None, b"", f"{type(exc).__name__}: {exc}"[:200]
            finally:
                last[host] = time.monotonic()
        return url, {"class": classify(status, body, err), "http": status, "bytes": len(body),
                     "ms": int((time.monotonic() - started) * 1000), "detail": err,
                     "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "vantage": vantage}

    with ThreadPoolExecutor(max_workers=12) as ex:
        return dict(ex.map(one, urls))


def from_peru_index(index: dict) -> dict[str, dict]:
    """Lo que el recolector del Perú logró bajar (formato enso-relay/1)."""
    out = {}
    at = index.get("collected_at") or index.get("at")
    for e in index.get("entries", []):
        cls = classify(e.get("status"), b"x" * int(e.get("bytes") or 0), e.get("error", ""))
        rec = {"class": cls, "http": e.get("status"), "bytes": e.get("bytes"), "at": e.get("fetched_at") or at,
               "vantage": "peru-server", "detail": e.get("error", "")}
        for u in [e.get("url"), *(e.get("aliases") or [])]:
            if u:
                out[u] = rec
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vantage", default="github-actions")
    ap.add_argument("--peru-index", type=Path)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--out", type=Path, default=registry.REACHABILITY)
    a = ap.parse_args(argv)
    reg = registry.build(reach={})
    urls = sorted({u for s in reg["sources"] if not a.only or s["id"] in a.only for u in [s["url"], *s.get("alt_urls", [])]})
    data = json.loads(a.out.read_text(encoding="utf-8")) if a.out.exists() else {"schema": registry.REACH_SCHEMA, "urls": {}}
    side = "peru" if a.vantage == "peru-server" else "us"
    for url, rec in probe(urls, a.vantage).items():
        data["urls"].setdefault(url, {})[side] = rec
    if a.peru_index and a.peru_index.exists():
        for url, rec in from_peru_index(json.loads(a.peru_index.read_text(encoding="utf-8"))).items():
            data["urls"].setdefault(url, {})["peru"] = rec
    data["schema"] = registry.REACH_SCHEMA
    data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["urls"] = dict(sorted(data["urls"].items()))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    counts: dict[str, int] = defaultdict(int)
    for u in urls:
        counts[data["urls"][u][side]["class"]] += 1
    print(f"{len(urls)} URL medidas desde {a.vantage}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
