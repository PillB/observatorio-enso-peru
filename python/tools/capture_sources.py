"""Captura de respuestas crudas de las fuentes para pruebas y backtesting.

Descarga cada fuente tal como la publica la institución (sin parsear) y
guarda el cuerpo exacto junto a un índice con URL, fecha, estado HTTP,
tipo de contenido y sha256. Opcionalmente recupera versiones históricas
desde el Internet Archive (Wayback Machine) para probar los parsers con
formatos antiguos.

Uso:
    python -m tools.capture_sources --out tests/fixtures/sources [--history]

Diseñado para ejecutarse en GitHub Actions: el contenedor de desarrollo
no siempre tiene salida de red hacia NOAA/ENFEN.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

UA = "Observatorio-ENSO-Peru/4.0 (fixture-capture; +https://github.com/PillB/observatorio-enso-peru)"

#: Fuentes actuales. Clave = nombre de archivo estable.
CURRENT = {
    "cpc-roni.txt": "https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt",
    "cpc-oni.txt": "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
    "cpc-sstoi.indices": "https://www.cpc.ncep.noaa.gov/data/indices/sstoi.indices",
    "cpc-ersst5.nino.mth.91-20.ascii": "https://www.cpc.ncep.noaa.gov/data/indices/ersst5.nino.mth.91-20.ascii",
    "cpc-wksst9120.for": "https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for",
    "cpc-soi.txt": "https://www.cpc.ncep.noaa.gov/data/indices/soi",
    "cpc-wpac850.txt": "https://www.cpc.ncep.noaa.gov/data/indices/wpac850",
    "cpc-cpac850.txt": "https://www.cpc.ncep.noaa.gov/data/indices/cpac850",
    "cpc-epac850.txt": "https://www.cpc.ncep.noaa.gov/data/indices/epac850",
    "cpc-ensodisc.html": "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml",
    "cpc-godas-heat.html": "https://www.cpc.ncep.noaa.gov/products/GODAS/",
    "psl-nino12.long.anom.csv": "https://psl.noaa.gov/data/timeseries/month/data/nino12.long.anom.csv",
    "psl-nino34.long.anom.csv": "https://psl.noaa.gov/data/timeseries/month/data/nino34.long.anom.csv",
    "enfen-wp-posts-cat28.json": "https://enfen.imarpe.gob.pe/wp-json/wp/v2/posts?per_page=20&categories=28",
    "enfen-wp-posts.json": "https://enfen.imarpe.gob.pe/wp-json/wp/v2/posts?per_page=20",
    "enfen-wp-categories.json": "https://enfen.imarpe.gob.pe/wp-json/wp/v2/categories?per_page=100",
    "enfen-comunicados.html": "https://enfen.imarpe.gob.pe/comunicados/",
    "enfen-home.html": "https://enfen.imarpe.gob.pe/",
    "enfen-gob-home.html": "https://www.enfen.gob.pe/",
    "siofen-icen.html": "https://siofen.imarpe.gob.pe/nivel2/indice-costero-el-nino-icen",
    "igp-icen.txt": "http://met.igp.gob.pe/datos/ICEN.txt",
    "igp-icen-https.txt": "https://met.igp.gob.pe/datos/ICEN.txt",
    "cpc-tahiti.txt": "https://www.cpc.ncep.noaa.gov/data/indices/tahiti",
    "cpc-darwin.txt": "https://www.cpc.ncep.noaa.gov/data/indices/darwin",
    "cpc-weekly-ppt.html": "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/lanina/enso_evolution-status-fcsts-web.pdf",
    "cpc-heat-content.txt": "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ocean/index/heat_content_index.txt",
    "enfen-gobpe.html": "https://www.gob.pe/enfen",
    "bom-soi30.txt": "https://www.bom.gov.au/climate/enso/soi.txt",
    "bom-enso-outlook.html": "https://www.bom.gov.au/climate/enso/outlook/",
}

#: Consultas históricas en Wayback: (prefijo de nombre, URL, granularidad CDX).
HISTORY = [
    ("cpc-ensodisc", "www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml", 6),
    ("cpc-roni", "www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt", 4),
    ("cpc-soi", "www.cpc.ncep.noaa.gov/data/indices/soi", 4),
    ("cpc-cpac850", "www.cpc.ncep.noaa.gov/data/indices/cpac850", 4),
    ("cpc-wksst", "www.cpc.ncep.noaa.gov/data/indices/wksst9120.for", 4),
    ("cpc-wksst8110", "www.cpc.ncep.noaa.gov/data/indices/wksst8110.for", 4),
    ("psl-nino12", "psl.noaa.gov/data/timeseries/month/data/nino12.long.anom.csv", 4),
    ("enfen-comunicados", "enfen.imarpe.gob.pe/comunicados/", 6),
    ("enfen-gob-comunicado", "www.enfen.gob.pe/", 6),
    ("igp-icen", "met.igp.gob.pe/datos/icen.txt", 4),
    ("igp-ICEN", "met.igp.gob.pe/datos/ICEN.txt", 6),
    ("bom-soi", "www.bom.gov.au/climate/enso/soi.txt", 6),
    ("enfen-wp-posts", "enfen.imarpe.gob.pe/wp-json/wp/v2/posts", 6, "prefix"),
    ("siofen-icen", "siofen.imarpe.gob.pe/nivel2/indice-costero-el-nino-icen", 6),
    # Comunicados oficiales en PDF (el formato y la URL cambian con los años).
    ("enfen-pdf-gob", "www.enfen.gob.pe/download/comunicado-oficial-enfen", 6, "prefix"),
    ("enfen-pdf-imarpe", "enfen.imarpe.gob.pe/download/comunicado-oficial-enfen", 6, "prefix"),
]

MAX_BYTES = 2_000_000


def _get(client: httpx.Client, url: str) -> dict:
    started = time.monotonic()
    try:
        for attempt in range(3):
            try:
                r = client.get(url)
                break
            except httpx.ConnectError:
                if attempt == 2:
                    raise
                time.sleep(5 * (attempt + 1))
        body = r.content[:MAX_BYTES]
        return {
            "url": url,
            "final_url": str(r.url),
            "status": r.status_code,
            "content_type": r.headers.get("content-type", ""),
            "last_modified": r.headers.get("last-modified", ""),
            "bytes": len(r.content),
            "truncated": len(r.content) > MAX_BYTES,
            "elapsed_s": round(time.monotonic() - started, 2),
            "body": body,
        }
    except Exception as exc:  # registrar y seguir
        return {"url": url, "status": None, "error": f"{type(exc).__name__}: {exc}", "body": b""}


def _save(out: Path, name: str, res: dict, index: list) -> None:
    body = res.pop("body", b"")
    res["file"] = name if body else None
    res["sha256"] = hashlib.sha256(body).hexdigest() if body else None
    if body:
        (out / name).write_bytes(body)
    res["name"] = name
    index.append(res)
    print(f"{res.get('status')}\t{len(body)}\t{name}\t{res.get('error', '')}")


def capture_current(client: httpx.Client, out: Path, index: list) -> None:
    for name, url in CURRENT.items():
        _save(out, name, _get(client, url), index)


def capture_history(client: httpx.Client, out: Path, index: list, per_source: int) -> None:
    hist = out / "history"
    hist.mkdir(exist_ok=True)
    for entry in HISTORY:
        prefix, url, collapse = entry[:3]
        match = "&matchType=prefix&collapse=urlkey" if len(entry) > 3 else f"&collapse=timestamp:{collapse}"
        cdx = (
            "https://web.archive.org/cdx/search/cdx?output=json&filter=statuscode:200"
            f"{match}&url={url}"
        )
        res = _get(client, cdx)
        rows = []
        try:
            rows = json.loads(res.get("body") or b"[]")[1:]
        except ValueError:
            pass
        # Muestreo uniforme en el tiempo (incluye el más antiguo y el más reciente).
        if len(rows) > per_source:
            step = (len(rows) - 1) / (per_source - 1)
            rows = [rows[round(i * step)] for i in range(per_source)]
        for row in rows:
            ts, original = row[1], row[2]
            snap = f"https://web.archive.org/web/{ts}id_/{original}"
            ext = Path(re.sub(r"[?#].*", "", original)).suffix or ".txt"
            if ext in (".shtml", ".htm", "") or original.endswith("/"):
                ext = ".html"
            name = f"history/{prefix}-{ts}{ext}"
            r = _get(client, snap)
            r["wayback_timestamp"] = ts
            r["original_url"] = original
            _save(out, name, r, index)
            time.sleep(1.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tests/fixtures/sources")
    ap.add_argument("--history", action="store_true")
    ap.add_argument("--per-source", type=int, default=8)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    index: list = []
    with httpx.Client(timeout=45.0, follow_redirects=True, headers={"User-Agent": UA}) as client:
        capture_current(client, out, index)
        if args.history:
            capture_history(client, out, index, args.per_source)
    meta = {"captured_at": datetime.now(timezone.utc).isoformat(), "entries": index}
    (out / "index.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    ok = sum(1 for e in index if e.get("status") == 200)
    print(f"captured {ok}/{len(index)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
