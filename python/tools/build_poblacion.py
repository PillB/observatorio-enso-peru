"""Población oficial del INEI por distrito (``data/historico/ref/poblacion-inei.csv``), para medir cada cifra de
personas contra la población de su área en el año del evento (``Territory.population_at``):

- ``poblacion_1990`` a ``poblacion_2005``: las estimaciones y proyecciones al 30 de junio de cada año del Boletín
  Especial N° 16, «Perú: Proyecciones de población por años calendario según departamentos, provincias y distritos
  (período 1990-2005)» (INEI, enero de 2002, Lib0467), hechas con los censos de 1981 y 1993 y la ENDES 2000, con los
  límites de abril de 2001. Un distrito se une por su ubigeo si el nombre es el de hoy (o lo empieza: el libro corta
  los largos), por ``RENAMED``, o por su nombre en el mismo departamento si se recodificó al crearse una provincia
  (Datem del Marañón, 2005; Putumayo, 2014); los creados después de 2001 quedan vacíos (su población estaba en la
  del distrito del que se separaron);
- ``poblacion_2017_censada`` y ``poblacion_2017``: la población censada y la total (censada más la omitida) del censo
  de 2017, del anexo de «Perú: Estimaciones y proyecciones de la población total por provincia y distrito, 2017»
  (INEI, Lib1673);
- ``poblacion_2018`` a ``poblacion_2022``: las proyecciones al 30 de junio del Boletín Especial N° 27, «Perú:
  Proyecciones de población total según departamento, provincia y distrito, 2018-2022» (INEI, Lib1860), que trae
  también los distritos creados en 2020 y 2021 (vacíos los años antes de su creación).

Reemplaza la población 2020 de ``data/historico/ref/distritos.csv`` (``ubigeo-peru-aumentado``), que se calculaba como
densidad × superficie y se aleja de la oficial en algunos distritos hasta 7 veces (San Antonio, Huarochirí: 43 991
frente a 5 948; Ananea: 4 944 frente a 11 551).

Los tres libros son PDF y se leen con ``pdftotext -layout`` (poppler): en los de 2017 y 2018-2022 cada fila es
«UBIGEO NOMBRE cifra cifra…», con espacio de miles y dos espacios o más entre columnas («Creado 2021» en los años sin
el distrito); en el de 1990-2005, «DD PP DI NOMBRE» y seis o cinco cifras sin separador, en tres tablas (1990-1995,
1996-2000 y 2001-2005). Los totales nacionales de cada año coinciden con los del INEI. La página del INEI no tiene
robots.txt; se piden con 5 s entre pedidos.

Uso:
    python -m tools.build_poblacion [--cache CARPETA]
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import subprocess
import time
import unicodedata
from pathlib import Path

import httpx

from enso.fetch import UA

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "historico" / "ref" / "poblacion-inei.csv"
BOOKS = {
    "proyecciones1990": "https://www.inei.gob.pe/media/MenuRecursivo/publicaciones_digitales/Est/Lib0467/Libro.pdf",
    "censo2017": "https://www.inei.gob.pe/media/MenuRecursivo/publicaciones_digitales/Est/Lib1673/libro.pdf",
    "proyecciones2018": "https://www.inei.gob.pe/media/MenuRecursivo/publicaciones_digitales/Est/Lib1860/libro.pdf",
}
PAUSE_S = 5.0
YEARS_1990 = list(range(1990, 2006))
YEARS_2018 = list(range(2018, 2023))
COLUMNS = ["ubigeo", "nombre", *(f"poblacion_{y}" for y in YEARS_1990), "poblacion_2017_censada", "poblacion_2017",
           *(f"poblacion_{y}" for y in YEARS_2018)]
#: Una fila de distrito de los libros de 2017 y 2018-2022: el ubigeo, el nombre (con su nota, «KUMPIRUSHIATO 11/») y
#: las columnas, separadas por dos espacios o más.
_ROW = re.compile(r"^[ \t]*(\d{6})[ \t]+(\S.*?)[ \t]{2,}(\S.*?)[ \t]*$", re.M)
_CELL = re.compile(r"^(?:\d{1,3}(?: \d{3})*|Creado \d{4})$")
#: Una fila del libro de 1990-2005: «DD PP DI NOMBRE» y cinco o seis cifras en la misma línea.
_ROW_1990 = re.compile(r"^[ \t]*(\d\d)[ \t]+(\d\d)[ \t]+(\d\d)[ \t]+(\S.*?)[ \t]{2,}((?:\d+[ \t]+){4,5}\d+)[ \t]*$", re.M)
#: Distritos que cambiaron de nombre después de 2001 (ubigeo de hoy: nombre en el libro de 1990-2005).
RENAMED = {"010201": "LA PECA", "110301": "NAZCA", "150121": "MAGDALENA VIEJA", "230402": "CHUCATAMANI"}


def parse(text: str, ncols: int) -> dict[str, tuple[str, list]]:
    """{ubigeo de distrito: (nombre, [cifras o None])} de una tabla del INEI de ``ncols`` columnas (los departamentos y
    las provincias terminan en 00 y no se guardan)."""
    out = {}
    for m in _ROW.finditer(text):
        code = m.group(1)
        cells = re.split(r"[ \t]{2,}", m.group(3))
        if code.endswith("00") or len(cells) != ncols or not all(_CELL.match(c) for c in cells):
            continue
        vals = [None if c.startswith("Creado") else int(c.replace(" ", "")) for c in cells]
        out.setdefault(code, (re.sub(r"\s+\d+/$", "", m.group(2).strip()), vals))
    return out


def parse_1990(text: str) -> dict[str, tuple[str, list[int]]]:
    """{ubigeo de distrito: (nombre, [población de 1990 a 2005])} del Boletín Especial N° 16: cada distrito sale en tres
    tablas seguidas (1990-1995, 1996-2000, 2001-2005), en ese orden."""
    parts: dict[str, list] = {}
    for m in _ROW_1990.finditer(text):
        code = m.group(1) + m.group(2) + m.group(3)
        if code.endswith("00"):
            continue
        parts.setdefault(code, [m.group(4).strip(), []])[1].append([int(x) for x in m.group(5).split()])
    return {code: (name, [v for block in blocks[:3] for v in block]) for code, (name, blocks) in parts.items()
            if [len(b) for b in blocks[:3]] == [6, 5, 5]}


def _fold(name: str) -> str:
    s = unicodedata.normalize("NFD", name or "")
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in s if unicodedata.category(c) != "Mn").lower())


def _same(a: str, b: str) -> bool:
    a, b = _fold(a), _fold(b)
    return bool(a) and bool(b) and (a.startswith(b) or b.startswith(a))


def match_1990(old: dict[str, tuple[str, list[int]]], names: dict[str, str]) -> dict[str, list[int]]:
    """{ubigeo de hoy: población 1990-2005}: por ubigeo y nombre, por ``RENAMED`` o por nombre en el departamento."""
    out = {code: old[code][1] for code, name in names.items()
           if code in old and (_same(old[code][0], name) or RENAMED.get(code) == old[code][0])}
    used = set(out)
    for code, name in names.items():
        if code in out:
            continue
        cands = [c for c, (n, _) in old.items() if c[:2] == code[:2] and c not in used and c not in names and _same(n, name)]
        if len(cands) == 1:
            out[code] = old[cands[0]][1]
            used.add(cands[0])
    return out


def _text(name: str, cache: Path) -> str:
    pdf = cache / f"{name}.pdf"
    if not pdf.exists():
        r = httpx.get(BOOKS[name], headers={"User-Agent": UA}, timeout=120, follow_redirects=True)
        r.raise_for_status()
        pdf.write_bytes(r.content)
        time.sleep(PAUSE_S)
    return subprocess.run(["pdftotext", "-layout", str(pdf), "-"], check=True, capture_output=True,
                          text=True).stdout


def build(cache: Path) -> list[list]:
    census = parse(_text("censo2017", cache), 2)
    proj = parse(_text("proyecciones2018", cache), len(YEARS_2018))
    names = {code: (proj.get(code) or census.get(code))[0] for code in set(census) | set(proj)}
    old = match_1990(parse_1990(_text("proyecciones1990", cache)), names)
    rows = []
    for code in sorted(names):
        vals = [*old.get(code, [None] * len(YEARS_1990)), *census.get(code, ("", [None] * 2))[1],
                *proj.get(code, ("", [None] * len(YEARS_2018)))[1]]
        rows.append([code, names[code], *("" if v is None else v for v in vals)])
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", type=Path, default=ROOT / ".cache" / "inei")
    args = ap.parse_args(argv)
    args.cache.mkdir(parents=True, exist_ok=True)
    rows = build(args.cache)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(COLUMNS)
    w.writerows(rows)
    OUT.write_text(buf.getvalue(), encoding="utf-8")
    col = {c: i for i, c in enumerate(COLUMNS)}
    print(f"{len(rows)} distritos → {OUT}")
    for c in COLUMNS[2:]:
        print(f"  {c}: {sum(1 for r in rows if r[col[c]] != '')} distritos, {sum(int(r[col[c]] or 0) for r in rows):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
