"""Mide desde dónde responde cada URL del registro y actualiza ``registry/reachability.json``.

Corre en GitHub Actions (vantage «github-actions»), lee el ``index.json`` del
recolector del Perú (rama ``data-peru``) y el del flujo de n8n (rama
``data-n8n``), y puede importar lo medido por el flujo de validación de n8n
(``--import``: su informe tal como sale, en JSON como lo guarda ``n8n.yml`` o en
CSV como lo baja n8n, o el formato enso-reachability-vantage/1). Cada medición se guarda
por red (``actions``, ``n8n``, ``peru``) y punto de medición, y el registro
decide con todas qué fuentes están geobloqueadas y quién recolecta cada una.
Las URL que ya no están en el registro se olvidan cuando su última medición
tiene más de ``PRUNE_DAYS`` días.

Uso:
    python -m tools.probe_sources [--vantage github-actions] [--peru-index ruta/index.json]
        [--n8n-index ruta/index.json] [--import validacion.json|.csv ...] [--import-vantage n8n-aws]
        [--no-probe] [--only id ...]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from enso import registry  # noqa: E402
# El User-Agent y los certificados del pipeline: hay servidores que deciden por el User-Agent (GDACS respondió
# 403 a «Mozilla/5.0 (compatible; …)» y 200 a curl desde el mismo ejecutor) y otros que no envían su certificado
# intermedio (repositorio.imarpe.gob.pe): la sonda mide lo que verá el pipeline.
from enso.fetch import UA, ssl_context  # noqa: E402
from enso.reach import ROBOTS_TIMEOUT_S, Robots, classify, judge  # noqa: E402

#: Días tras los que se olvida una URL que ya no está en el registro, contados desde la medición más reciente
#: del archivo: los PDF que n8n siguió y los feeds retirados no crecen reachability.json para siempre, y una
#: fuente que vuelve pronto conserva su historia.
PRUNE_DAYS = 30


def probe(urls: list[str], vantage: str, timeout: float = 25.0,
          expect: dict[str, str] | None = None) -> dict[str, dict]:
    """Mide cada URL desde ``vantage``, con robots.txt leído antes (RFC 9309) y el mismo clasificador que n8n y
    el Perú (``enso.reach.judge``). ``expect``: lo que se espera de cada URL; otro formato, o un feed sin
    entradas, cuenta como ``empty``. Sin él, lo que dice el registro: así la medición desde el Perú
    (``peru_collector.probe_registry``) juzga igual que la de Actions, y una respuesta que no sirve en ninguna red
    no pasa por geobloqueada. ``robots`` dice qué se leyó: ``allowed`` (reglas que la permiten), ``absent`` (no hay
    robots.txt: un 4xx), ``disallowed`` o ``unreachable``."""
    if expect is None:
        expect = _expects(registry.build(reach={}))
    client = httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": UA}, verify=ssl_context())
    robots = Robots(client, timeout=min(timeout, ROBOTS_TIMEOUT_S))
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
                status, body, headers, err = r.status_code, r.content, r.headers, ""
            except httpx.HTTPError as exc:
                status, body, headers, err = None, b"", None, f"{type(exc).__name__}: {exc}"[:200]
            finally:
                last[host] = time.monotonic()
        cls, _, why = judge(status, body, headers.get("content-type", "") if headers else "",
                            (expect or {}).get(url), err, headers)
        return url, {"class": cls, "http": status, "bytes": len(body),
                     "ms": int((time.monotonic() - started) * 1000), "detail": err or why,
                     "robots": "absent" if robots.source(url) == "absent" else "allowed",
                     "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "vantage": vantage}

    with ThreadPoolExecutor(max_workers=12) as ex:
        return dict(ex.map(one, urls))


def from_peru_index(index: dict) -> dict[str, dict]:
    """Lo que midió el recolector del Perú (formato enso-relay/1): cada URL que
    pidió, con la clase que le dio (antirobots o formato inesperado no cuentan
    como respuesta), y en ``probes`` las URL del registro que solo midió. Una
    copia conservada de otra noche (``carried``) cuenta por lo que pasó esta
    noche (``last_attempt``), y una URL que no se pidió no es una medición
    salvo que traiga su clase: la de robots.txt cuando la prohíbe (``robots``)
    o cuando no responde (``timeout``…, como en ``probe``); el plazo o un
    servidor caído no la traen. El recolector lee robots.txt antes de cada
    pedido: lo que pidió lleva ``robots: allowed``, lo omitido porque robots.txt
    no respondió ``unreachable`` y lo que prohíbe ``disallowed``."""
    out = {}
    at = index.get("collected_at") or index.get("at")
    for url, rec in (index.get("probes") or {}).items():
        if isinstance(rec, dict) and rec.get("class") in registry.CLASSES:
            out[url] = {**rec, "vantage": rec.get("vantage") or "peru-server"}
    for e in index.get("entries", []):
        if e.get("carried"):
            last = e.get("last_attempt") or {}
            if last.get("class") not in registry.CLASSES:
                continue
            e = {"status": last.get("status"), "bytes": 0, "fetched_at": last.get("at"), "class": last["class"],
                 "error": last.get("error", ""), "url": e.get("url")}
        elif e.get("skipped") and e.get("class") not in registry.CLASSES:
            continue
        cls = e.get("class") if e.get("class") in registry.CLASSES else \
            classify(e.get("status"), b"x" * int(e.get("bytes") or 0), e.get("error", ""))
        unread = e.get("skipped") == "robots-sin-respuesta" or str(e.get("error") or "").startswith("robots.txt sin respuesta")
        rec = {"class": cls, "http": e.get("status"), "bytes": e.get("bytes"), "at": e.get("fetched_at") or at,
               "vantage": "peru-server", "detail": e.get("error", ""),
               "robots": "disallowed" if cls == "robots" else "unreachable" if unread else "allowed"}
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


def _iso(at) -> str | None:
    """«2026-10-21T03:00:00.000Z» (n8n) como las demás mediciones, «2026-10-21T03:00:00+00:00»: el registro
    compara las fechas como texto."""
    try:
        return datetime.fromisoformat(str(at).replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        return None


def from_n8n_report(rows: list, vantage: str) -> list[dict]:
    """El informe del flujo «ENSO · Validación de fuentes desde n8n» (nodo Informe): una fila por URL con
    ``alcance`` (la clase del registro, ``reachClass`` en n8n/lib/classify.js), ``http``, ``bytes`` y ``medido``.
    La primera fila es el resumen. Sirve igual leído del JSON o del CSV (allí todo llega como texto)."""
    out = []
    for r in rows:
        if not isinstance(r, dict) or r.get("id") == "resumen" or not r.get("url") or r.get("alcance") not in registry.CLASSES:
            continue
        rec = {"url": r["url"], "class": r["alcance"], "at": _iso(r.get("medido")),
               "detail": str(r.get("nota") or r.get("bloqueo") or "") or None}  # como from_n8n_index: «aborted» se reconoce
        for k in ("http", "bytes"):
            v = r.get(k)
            if isinstance(v, int) or (isinstance(v, str) and v.isdigit()):
                rec[k] = int(v)
        out.append({k: v for k, v in rec.items() if v is not None} | {"vantage": vantage})
    if not out:
        raise SystemExit("formato no reconocido: el informe de n8n no trae filas con url y alcance")
    return out


def read_import(path: Path, vantage: str) -> list[dict]:
    """Un archivo de --import: el informe de validación de n8n (JSON o CSV) o enso-reachability-vantage/1."""
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".csv":
        import csv
        import io
        return from_n8n_report(list(csv.DictReader(io.StringIO(text))), vantage)
    data = json.loads(text)
    return from_n8n_report(data, vantage) if isinstance(data, list) else from_vantage_file(data, vantage)


def from_vantage_file(data: dict, vantage: str = "n8n") -> list[dict]:
    """Mediciones hechas en otra parte (n8n…) en formato enso-reachability-vantage/1: [{url, class, at, vantage…}]."""
    if data.get("schema") != "enso-reachability-vantage/1":
        raise SystemExit(f"formato no reconocido: {data.get('schema')}")
    out = []
    for r in data.get("results", []):
        if r.get("url") and r.get("class") in registry.CLASSES:
            out.append({k: r.get(k) for k in ("url", "class", "http", "bytes", "ms", "detail", "at", "robots")
                        if r.get(k) is not None} | {"vantage": r.get("vantage") or data.get("vantage") or vantage})
    return out


def _put(data: dict, url: str, rec: dict) -> None:
    rec = {k: v for k, v in rec.items() if k != "url"}
    groups = registry._groups(data["urls"].get(url) or {})
    groups.setdefault(registry.vantage_group(rec["vantage"]), {})[rec["vantage"]] = rec
    data["urls"][url] = groups


def prune(data: dict, keep: set[str]) -> list[str]:
    """Quita de ``data["urls"]`` las URL fuera de ``keep`` (el registro) cuya medición más reciente tiene más de
    ``PRUNE_DAYS`` días respecto de la más reciente del archivo. Devuelve las quitadas."""
    newest = registry.newest_at(data["urls"])
    if newest is None:
        return []
    cutoff = newest - timedelta(days=PRUNE_DAYS)
    gone = [u for u, e in data["urls"].items() if u not in keep
            and (registry.newest_at({u: e}) or newest) < cutoff]
    for u in gone:
        del data["urls"][u]
    return gone


def _expects(reg: dict) -> dict[str, str]:
    """Lo que el registro espera de cada URL (``expect`` y ``alt_expect``)."""
    out = {}
    for s in reg["sources"]:
        alts = s.get("alt_urls", [])
        for u, e in zip([s["url"], *alts], [s["expect"], *(s.get("alt_expect") or [None] * len(alts))]):
            if e:
                out.setdefault(u, e)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vantage", default="github-actions")
    ap.add_argument("--peru-index", type=Path)
    ap.add_argument("--n8n-index", type=Path, help="index.json de la rama data-n8n (lo que n8n bajó)")
    ap.add_argument("--import", dest="imports", type=Path, nargs="*", default=[],
                    help="informe de la validación de n8n (JSON o CSV) o archivos enso-reachability-vantage/1")
    ap.add_argument("--import-vantage", default="n8n",
                    help="desde dónde corrió esa validación, p. ej. n8n-aws o n8n-actions-azure (n8n.yml)")
    ap.add_argument("--no-probe", action="store_true", help="solo importar mediciones")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--out", type=Path, default=registry.REACHABILITY)
    a = ap.parse_args(argv)
    reg = registry.build(reach={})
    every = {u for s in reg["sources"] for u in [s["url"], *s.get("alt_urls", [])]}
    urls = sorted({u for s in reg["sources"] if not a.only or s["id"] in a.only for u in [s["url"], *s.get("alt_urls", [])]})
    data = json.loads(a.out.read_text(encoding="utf-8")) if a.out.exists() else {"urls": {}}
    data["urls"] = {u: registry._groups(e) for u, e in data.get("urls", {}).items()}
    measured = {} if a.no_probe else probe(urls, a.vantage, expect=_expects(reg))
    for url, rec in measured.items():
        _put(data, url, {**rec, "vantage": a.vantage})
    if a.peru_index and a.peru_index.exists():
        for url, rec in from_peru_index(json.loads(a.peru_index.read_text(encoding="utf-8"))).items():
            _put(data, url, rec)
    if a.n8n_index and a.n8n_index.exists():
        for url, rec in from_n8n_index(json.loads(a.n8n_index.read_text(encoding="utf-8"))).items():
            _put(data, url, rec)
    for f in a.imports:
        for rec in read_import(f, a.import_vantage):
            _put(data, rec["url"], rec)
    gone = prune(data, every)  # con todo el registro, no solo --only
    data["schema"] = registry.REACH_SCHEMA
    data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["urls"] = dict(sorted(data["urls"].items()))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    counts: dict[str, int] = defaultdict(int)
    for rec in measured.values():
        counts[rec["class"]] += 1
    print(f"{len(measured)} URL medidas desde {a.vantage}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    if gone:
        print(f"{len(gone)} URL fuera del registro olvidadas (sin medir en {PRUNE_DAYS} días)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
