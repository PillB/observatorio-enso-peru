"""Mide desde dónde responde cada URL del registro y actualiza ``registry/reachability.json``.

Corre en GitHub Actions (vantage «github-actions»), lee el ``index.json`` del
recolector del Perú (rama ``data-peru``) y el del flujo de n8n (rama
``data-n8n``), y puede importar lo medido por el flujo de validación de n8n
(``--import``, formato enso-reachability-vantage/1). Cada medición se guarda
por red (``actions``, ``n8n``, ``peru``) y punto de medición, y el registro
decide con todas qué fuentes están geobloqueadas y quién recolecta cada una.

Uso:
    python -m tools.probe_sources [--vantage github-actions] [--peru-index ruta/index.json]
        [--n8n-index ruta/index.json] [--import n8n-reach.json ...] [--no-probe] [--only id ...]
"""

from __future__ import annotations

import argparse
import json
import os
import re
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
from enso.reach import Robots, classify  # noqa: E402

#: El contacto que ven las fuentes (como en enso.fetch): el sitio publicado o el repositorio.
CONTACT = os.environ.get("ENSO_CONTACT_URL") or "https://github.com/PillB/observatorio-enso-peru"
UA = f"Mozilla/5.0 (compatible; Observatorio-ENSO-Peru/4.0; source-probe; +{CONTACT})"


def probe(urls: list[str], vantage: str, timeout: float = 25.0) -> dict[str, dict]:
    client = httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": UA})
    robots = Robots(client)
    locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
    last: dict[str, float] = {}

    def one(url: str) -> tuple[str, dict]:
        host = urlparse(url).netloc
        allowed = robots.allowed(url)
        if not allowed:
            # RFC 9309: ruta prohibida, o robots.txt inalcanzable (no se pide nada al servidor).
            cls = "robots" if allowed is False else (robots.failure(url) or "connect")
            return url, {"class": cls, "http": None, "bytes": 0, "ms": 0,
                         "detail": "robots.txt no permite la ruta" if allowed is False else "robots.txt sin respuesta",
                         "robots": "disallowed" if allowed is False else "unreachable",
                         "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "vantage": vantage}
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
                     "robots": "allowed",
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


def from_n8n_index(index: dict) -> dict[str, dict]:
    """Lo que el recolector de n8n intentó en su última corrida (rama ``data-n8n``, enso-relay/1).

    n8n clasifica cada respuesta con las mismas clases (``reach``). Una copia conservada de una corrida
    anterior (``carried``) no es una medición de hoy: cuenta su último intento, que falló."""
    col = index.get("collector") or {}
    label = re.sub(r"[^a-z0-9]+", "-", str(col.get("egress") or col.get("host") or "").lower()).strip("-")
    vantage = "n8n" if label in ("", "n8n") else label if label.startswith("n8n") else f"n8n-{label}"
    at = index.get("collected_at")
    out = {}
    for e in index.get("entries", []):
        last = e.get("last_attempt") if e.get("carried") else None
        if last:
            status, err = last.get("status"), " ".join(str(last.get(k) or "") for k in ("block", "note")).strip()
            cls = classify(status, b"", err or ("sin respuesta" if status is None else ""))
            rec = {"class": cls, "http": status, "bytes": 0, "at": last.get("at") or at, "detail": err}
        else:
            cls = e.get("reach") if e.get("reach") in registry.CLASSES else classify(
                e.get("status"), b"x" * int(e.get("bytes") or 0), str(e.get("note") or e.get("block") or ""))
            rec = {"class": cls, "http": e.get("status"), "bytes": e.get("bytes"), "at": e.get("fetched_at") or at,
                   "detail": str(e.get("note") or e.get("block") or "")}
        for u in [e.get("url"), *(e.get("aliases") or [])]:
            if u:
                out[u] = rec | {"vantage": vantage}
    return out


def from_vantage_file(data: dict) -> list[dict]:
    """Mediciones hechas en otra parte (n8n…) en formato enso-reachability-vantage/1: [{url, class, at, vantage…}]."""
    if data.get("schema") != "enso-reachability-vantage/1":
        raise SystemExit(f"formato no reconocido: {data.get('schema')}")
    out = []
    for r in data.get("results", []):
        if r.get("url") and r.get("class") in registry.CLASSES:
            out.append({k: r.get(k) for k in ("url", "class", "http", "bytes", "ms", "detail", "at", "robots")
                        if r.get(k) is not None} | {"vantage": r.get("vantage") or data.get("vantage") or "n8n"})
    return out


def _put(data: dict, url: str, rec: dict) -> None:
    rec = {k: v for k, v in rec.items() if k != "url"}
    groups = registry._groups(data["urls"].get(url) or {})
    groups.setdefault(registry.vantage_group(rec["vantage"]), {})[rec["vantage"]] = rec
    data["urls"][url] = groups


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vantage", default="github-actions")
    ap.add_argument("--peru-index", type=Path)
    ap.add_argument("--n8n-index", type=Path, help="index.json de la rama data-n8n (lo que n8n bajó)")
    ap.add_argument("--import", dest="imports", type=Path, nargs="*", default=[],
                    help="archivos enso-reachability-vantage/1 (p. ej. la validación de n8n)")
    ap.add_argument("--no-probe", action="store_true", help="solo importar mediciones")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--out", type=Path, default=registry.REACHABILITY)
    a = ap.parse_args(argv)
    reg = registry.build(reach={})
    urls = sorted({u for s in reg["sources"] if not a.only or s["id"] in a.only for u in [s["url"], *s.get("alt_urls", [])]})
    data = json.loads(a.out.read_text(encoding="utf-8")) if a.out.exists() else {"urls": {}}
    data["urls"] = {u: registry._groups(e) for u, e in data.get("urls", {}).items()}
    measured = {} if a.no_probe else probe(urls, a.vantage)
    for url, rec in measured.items():
        _put(data, url, {**rec, "vantage": a.vantage})
    if a.peru_index and a.peru_index.exists():
        for url, rec in from_peru_index(json.loads(a.peru_index.read_text(encoding="utf-8"))).items():
            _put(data, url, rec)
    if a.n8n_index and a.n8n_index.exists():
        for url, rec in from_n8n_index(json.loads(a.n8n_index.read_text(encoding="utf-8"))).items():
            _put(data, url, rec)
    for f in a.imports:
        for rec in from_vantage_file(json.loads(f.read_text(encoding="utf-8"))):
            _put(data, rec["url"], rec)
    data["schema"] = registry.REACH_SCHEMA
    data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["urls"] = dict(sorted(data["urls"].items()))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    counts: dict[str, int] = defaultdict(int)
    for rec in measured.values():
        counts[rec["class"]] += 1
    print(f"{len(measured)} URL medidas desde {a.vantage}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
