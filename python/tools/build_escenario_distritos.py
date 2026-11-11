"""Construye ``public/assets/capas/escenario-distritos.json``: el escenario de riesgo por lluvias del CENEPRED para
cada distrito del país, por movimientos en masa (huaycos y deslizamientos) y por inundaciones.

Sale de la página pública de escenarios del SIGRID (https://sigrid.cenepred.gob.pe/sigridv3/escenarios, «lluvias,
pronóstico trimestral»), que ofrece cada escenario como una descarga sin inicio de sesión:

- la lista de escenarios (``escenario-trimestral/data-mm``): su número, los meses de vigencia, el mes en que se
  elaboró y el documento del SIGRID que lo sustenta;
- ``storage/escenario_trimestral/<número>_tabla.zip``: dos libros de Excel del CENEPRED, uno por peligro, con una
  fila por distrito (hoja ``BD_…``) y su diccionario de datos.

De cada distrito se guardan solo el nivel de riesgo que le dio el CENEPRED y lo que cuenta en las áreas de mayor
susceptibilidad (personas, viviendas, establecimientos de salud, instituciones educativas y km de vías), tal como
vienen: aquí no se calcula ni se corrige nada. Los servicios de mapas del SIGRID (``/arcgis/``) piden hoy un token y
no se usan. Su robots.txt prohíbe ``/sigridv3/storage/``; como es información pública de una entidad peruana (Ley
N° 27806) que la propia página ofrece con un botón, el proyecto la pide igual, con al menos 5 s entre pedidos (ver
docs/memoria-desastres.md). Son tres pedidos por corrida.

La actualización diaria ya lo lee del SIGRID y publica ``data/escenario-distritos.json`` (``enso.cenepred_escenario``,
que tiene el lector y las reglas); este archivo es la copia incluida en el sitio, que «Mi zona» usa si ese falta. Se
regenera a mano de vez en cuando para que la copia no quede muy atrás.

Uso:
    python -m tools.build_escenario_distritos --tablas CARPETA [--id N] [--sin-red]

``--tablas``: dónde guardar (o, con ``--sin-red``, leer) la lista y el ZIP. ``--id``: el número del escenario; sin
él, el que se publicaría hoy (``enso.cenepred_escenario.choose``: el vigente elaborado más recientemente).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path

import httpx

from enso.cenepred_escenario import (  # noqa: F401 — se reexportan para quien los usaba desde aquí
    DOC_URL, FIELDS, HAZARDS, LIST_URL, PAGE, RISK_LEVELS, TABLE_URL, build, district_rows, read_tables, scenarios,
    sheets)
from enso.cenepred_escenario import pick as _pick
from enso.feeds import FormatChanged
from enso.fetch import UA
from enso.reach import Robots

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "public" / "assets" / "capas"


def pick(items: list[dict], wanted: str | None = None, today: date | None = None) -> dict:
    try:
        return _pick(items, wanted, today)
    except FormatChanged as exc:
        raise SystemExit(str(exc)) from exc


def download(client: httpx.Client, folder: Path, wanted: str | None) -> None:
    robots = Robots(client)
    folder.mkdir(parents=True, exist_ok=True)

    def get(url: str) -> httpx.Response:
        if robots.allowed(url) is not True:
            raise SystemExit(f"{url}: el robots.txt (o una verificación) no deja pedirlo")
        robots.pace(url)
        return client.get(url, timeout=180).raise_for_status()

    r = get(LIST_URL)
    (folder / "lista.json").write_bytes(r.content)
    s = pick(scenarios(r.content), wanted)
    z = get(TABLE_URL.format(id=s["id"]))
    if not z.content.startswith(b"PK"):
        raise SystemExit(f"{z.url}: no es un ZIP (¿una página de inicio de sesión o de verificación?)")
    (folder / f"{s['id']}_tabla.zip").write_bytes(z.content)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tablas", type=Path, required=True, help="carpeta de la lista y el ZIP del SIGRID")
    ap.add_argument("--id", help="número del escenario (por omisión, el que se publicaría hoy)")
    ap.add_argument("--sin-red", action="store_true", help="no descargar: usar lo que hay en --tablas")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    try:
        if not a.sin_red:
            with httpx.Client(headers={"User-Agent": UA}, follow_redirects=False) as client:
                download(client, a.tablas, a.id)
        s = pick(scenarios((a.tablas / "lista.json").read_bytes()), a.id)
        doc = build(s, read_tables((a.tablas / f"{s['id']}_tabla.zip").read_bytes()))
    except FormatChanged as exc:
        raise SystemExit(str(exc)) from exc
    a.out.mkdir(parents=True, exist_ok=True)
    path = a.out / "escenario-distritos.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for i, (k, name) in enumerate(doc["hazards"].items()):
        by = Counter(RISK_LEVELS[d[i][0]] for d in doc["districts"].values() if d[i])
        print(f"{name}: {dict(by)}")
    print(f"{path}: escenario {s['id']} ({doc['scenario']['from']} a {doc['scenario']['until']}), "
          f"{len(doc['districts'])} distritos, {path.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
