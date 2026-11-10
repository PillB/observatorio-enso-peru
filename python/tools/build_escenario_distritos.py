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

Se regenera a mano cuando el CENEPRED publica un escenario nuevo.

Uso:
    python -m tools.build_escenario_distritos --tablas CARPETA [--id N] [--sin-red]

``--tablas``: dónde guardar (o, con ``--sin-red``, leer) la lista y el ZIP. ``--id``: el número del escenario; sin
él, el vigente más reciente de la lista (el de fin de vigencia más lejano).
"""

from __future__ import annotations

import argparse
import io
import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

from enso.fetch import UA
from enso.reach import Robots

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "public" / "assets" / "capas"
PAGE = "https://sigrid.cenepred.gob.pe/sigridv3/escenarios"
LIST_URL = "https://sigrid.cenepred.gob.pe/sigridv3/escenario-trimestral/data-mm"
TABLE_URL = "https://sigrid.cenepred.gob.pe/sigridv3/storage/escenario_trimestral/{id}_tabla.zip"
DOC_URL = "https://sigrid.cenepred.gob.pe/sigridv3/documento/{doc}"
#: Niveles del CENEPRED, de mayor a menor.
RISK_LEVELS = ["Muy Alto", "Alto", "Medio", "Bajo"]
#: Por peligro: cómo empieza la hoja de datos del libro y qué columnas se leen (nivel de riesgo y lo que hay en las
#: áreas de mayor susceptibilidad: personas, viviendas, establecimientos de salud, instituciones educativas, km de vías).
HAZARDS = {
    "mm": {"name": "Movimientos en masa (huaycos y deslizamientos)", "sheet": "BD_ERMMasa",
           "cols": ["nriesg_mm", "pob_smm", "viv_smm", "eess_smm", "iiee_smm", "vias_smm"]},
    "inu": {"name": "Inundaciones", "sheet": "BD_ERInund",
            "cols": ["nriesg_inu", "pob_sinu", "viv_sinu", "eess_sinu", "iiee_sinu", "vias_sinu"]},
}
FIELDS = ["nivel", "personas", "viviendas", "salud", "educativas", "viasKm"]
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "p": "http://schemas.openxmlformats.org/package/2006/relationships"}


# --- Leer un libro de Excel sin dependencias ------------------------------------------------------------------------

def _col(ref: str) -> int:
    """Índice de columna de una celda: «A1» → 0, «AB7» → 27."""
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def sheets(data: bytes) -> dict[str, list[list]]:
    """{hoja: filas} de un .xlsx: cada fila, la lista de sus valores (texto, número o ``None``) por columna."""
    z = zipfile.ZipFile(io.BytesIO(data))
    shared: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).findall("p:Relationship", NS)}
    out: dict[str, list[list]] = {}
    for s in ET.fromstring(z.read("xl/workbook.xml")).find("m:sheets", NS):
        target = rels[s.get(f"{{{NS['r']}}}id")].lstrip("/")
        path = target if target.startswith("xl/") else f"xl/{target}"
        rows: list[list] = []
        for row in ET.fromstring(z.read(path)).iter(f"{{{NS['m']}}}row"):
            vals: list = []
            for c in row.findall("m:c", NS):
                i = _col(c.get("r"))
                vals.extend([None] * (i + 1 - len(vals)))
                v, t = c.find("m:v", NS), c.get("t")
                if t == "inlineStr":
                    vals[i] = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
                elif v is None or v.text is None:
                    vals[i] = None
                elif t == "s":
                    vals[i] = shared[int(v.text)]
                elif t in ("str", "b", "e"):
                    vals[i] = v.text
                else:
                    f = float(v.text)
                    vals[i] = int(f) if f.is_integer() else f
            rows.append(vals)
        out[s.get("name")] = rows
    return out


# --- El escenario -----------------------------------------------------------------------------------------------------

def pick(scenarios: list[dict], wanted: str | None = None) -> dict:
    """El escenario pedido o, sin número, el de fin de vigencia más lejano (y, entre iguales, el de número mayor)."""
    if wanted:
        for s in scenarios:
            if str(s["id"]) == str(wanted):
                return s
        raise SystemExit(f"el escenario {wanted} no está en la lista del SIGRID")
    if not scenarios:
        raise SystemExit("la lista de escenarios del SIGRID está vacía")
    return max(scenarios, key=lambda s: (s["mes_fin_vigencia"], int(s["id"])))


def _num(v) -> float | int:
    if v is None or v == "":
        return 0
    f = float(v)
    return int(f) if f.is_integer() else round(f, 1)


def district_rows(rows: list[list], cols: list[str]) -> dict[str, list]:
    """{ubigeo: [nivel (0 = muy alto … 3 = bajo), personas, viviendas, salud, educativas, km de vías]} de la hoja de
    datos de un peligro. Falla si falta una columna o si un distrito trae un nivel que no es de los cuatro."""
    head = [str(h).strip() if h is not None else "" for h in rows[0]]
    missing = [c for c in ["UBIGEO", *cols] if c not in head]
    if missing:
        raise SystemExit(f"la hoja no trae las columnas {missing}: el CENEPRED cambió el formato")
    ix = {c: head.index(c) for c in ["UBIGEO", *cols]}
    out: dict[str, list] = {}
    for r in rows[1:]:
        r = r + [None] * (len(head) - len(r))
        if r[ix["UBIGEO"]] in (None, ""):
            continue
        u = str(r[ix["UBIGEO"]]).strip().zfill(6)
        if not re.fullmatch(r"\d{6}", u):
            raise SystemExit(f"ubigeo inesperado: {u!r}")
        level = " ".join(str(r[ix[cols[0]]] or "").split()).title()
        if level not in RISK_LEVELS:
            raise SystemExit(f"{u}: nivel de riesgo inesperado {r[ix[cols[0]]]!r}")
        if u in out:
            raise SystemExit(f"{u}: distrito repetido")
        out[u] = [RISK_LEVELS.index(level), *(_num(r[ix[c]]) for c in cols[1:])]
    return out


def read_tables(zip_bytes: bytes) -> dict[str, dict[str, list]]:
    """{peligro: {ubigeo: fila}} de los libros del ZIP del escenario: cada peligro, del libro que trae su hoja."""
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    found: dict[str, dict[str, list]] = {}
    for name in z.namelist():
        if not name.lower().endswith(".xlsx"):
            continue
        book = sheets(z.read(name))
        for key, h in HAZARDS.items():
            if h["sheet"] in book:
                if key in found:
                    raise SystemExit(f"dos libros traen la hoja {h['sheet']}")
                found[key] = district_rows(book[h["sheet"]], h["cols"])
    missing = [h["sheet"] for k, h in HAZARDS.items() if k not in found]
    if missing:
        raise SystemExit(f"el ZIP no trae las hojas {missing}")
    return found


def build(scenario: dict, tables: dict[str, dict[str, list]]) -> dict:
    codes = sorted(set(tables["mm"]) | set(tables["inu"]))
    return {
        "source": "CENEPRED, SIGRID: escenario de riesgo por lluvias con pronóstico trimestral, por movimientos en "
                  "masa y por inundaciones, a nivel distrital",
        "url": PAGE,
        "table": TABLE_URL.format(id=scenario["id"]),
        "document": DOC_URL.format(doc=scenario["id_documento"]) if scenario.get("id_documento") else "",
        "scenario": {"id": str(scenario["id"]), "from": scenario["mes_inicio_vigencia"][:7],
                     "until": scenario["mes_fin_vigencia"][:7], "prepared": scenario["mes_elaboracion"][:7]},
        "generatedBy": "python -m tools.build_escenario_distritos",
        "levels": RISK_LEVELS,
        "hazards": {k: h["name"] for k, h in HAZARDS.items()},
        "fields": FIELDS,
        "note": "Personas, viviendas, establecimientos de salud, instituciones educativas y km de vías en las áreas "
                "de mayor susceptibilidad del distrito, según el CENEPRED. null: el distrito no está en esa tabla.",
        "districts": {u: [tables["mm"].get(u), tables["inu"].get(u)] for u in codes},
    }


def download(client: httpx.Client, folder: Path, wanted: str | None) -> None:
    robots = Robots(client)
    folder.mkdir(parents=True, exist_ok=True)

    def get(url: str) -> httpx.Response:
        if robots.allowed(url) is not True:
            raise SystemExit(f"{url}: el robots.txt (o una verificación) no deja pedirlo")
        robots.pace(url)
        return client.get(url, timeout=180, headers={"X-Requested-With": "XMLHttpRequest"}).raise_for_status()

    r = get(LIST_URL)
    scenarios = r.json().get("data") or []
    (folder / "lista.json").write_bytes(r.content)
    s = pick(scenarios, wanted)
    z = get(TABLE_URL.format(id=s["id"]))
    if not z.content.startswith(b"PK"):
        raise SystemExit(f"{z.url}: no es un ZIP (¿una página de inicio de sesión o de verificación?)")
    (folder / f"{s['id']}_tabla.zip").write_bytes(z.content)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tablas", type=Path, required=True, help="carpeta de la lista y el ZIP del SIGRID")
    ap.add_argument("--id", help="número del escenario (por omisión, el vigente más reciente)")
    ap.add_argument("--sin-red", action="store_true", help="no descargar: usar lo que hay en --tablas")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    if not a.sin_red:
        with httpx.Client(headers={"User-Agent": UA}, follow_redirects=False) as client:
            download(client, a.tablas, a.id)
    scenarios = json.loads((a.tablas / "lista.json").read_text(encoding="utf-8")).get("data") or []
    s = pick(scenarios, a.id)
    doc = build(s, read_tables((a.tablas / f"{s['id']}_tabla.zip").read_bytes()))
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
