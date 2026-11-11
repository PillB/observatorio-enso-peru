"""Construye las capas de la vista de detalle de los dos mapas (``public/assets/capas/``):

- ``rios-mapa.json``: el trazo de cada río, quebrada o laguna que nombra algún registro de la memoria de desastres,
  solo en el distrito donde lo nombra (la «quebrada Honda» de un distrito no es la de otro), con cuántos registros lo
  nombran y su cuenca. Sale de la Carta Nacional 1:100 000 del IGN (las mismas páginas de la IDEP que lee
  ``tools.build_aguas``, guardadas con ``--keep``) y del catálogo (``public/assets/historico/eventos.zip``, columna
  ``CuerpoAgua``). Los cauces van como líneas y las lagunas como su contorno, simplificados a unos 400 m, en la
  proyección de ``public/assets/peru-map.json``.
- ``manzanas-riesgo.json``: las manzanas que el CENEPRED evaluó con un nivel de riesgo ante El Niño 2026-2027 en
  Piura, Tumbes y Lambayeque (SIGRID, servicio ``sectores/COEN_FEN_2027``, capas 57, 58 y 61): su punto central, su
  distrito, su centro poblado, el nivel y la población y las viviendas del censo 2017 de la manzana. Son datos por
  manzana, no por persona. El robots.txt del SIGRID prohíbe ``/arcgis/``; como es información pública de una entidad
  peruana (Ley N° 27806), el proyecto lo consulta igual, con 5 s entre pedidos (ver docs/memoria-desastres.md).

Las dos se regeneran a mano, no en cada corrida: un río que el catálogo nombre por primera vez se dibuja cuando se
vuelve a correr esto.

Uso:
    python -m tools.build_capas_mapa --aguas CARPETA [--manzanas CARPETA] [--sin-red]

``--aguas``: las páginas de la Carta (``python -m tools.build_aguas --keep CARPETA``). ``--manzanas``: dónde guardar
(o, con ``--sin-red``, leer) las páginas del CENEPRED.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import time
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import httpx

from enso.aguas import water_key
from enso.fetch import UA
from enso.reach import Robots
from tools.build_aguas import _Grid, _densify, _with_class, names, read_pages
from tools.build_limites import SCALE
from tools.build_peru_map import _dp, project

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "public" / "assets" / "capas"
CATALOG = ROOT / "public" / "assets" / "historico" / "eventos.zip"
#: Simplificación de los trazos, en px del mapa (40 px por grado: 0,4 px son unos 1 100 m; se dibujan sobre
#: distritos de varios km).
TOL_PX = 0.15
SIGRID = "https://sigrid.cenepred.gob.pe/arcgis/rest/services/sectores/COEN_FEN_2027/MapServer"
BLOCK_LAYERS = {"57": "Piura", "58": "Tumbes", "61": "Lambayeque"}
BLOCK_FIELDS = "objectid,ubigeo,nomccpp,nriesgo,pob_total,viv_part_p"
#: Niveles del CENEPRED, de mayor a menor (así los escribe la capa).
RISK_LEVELS = ["Muy Alto", "Alto", "Medio", "Bajo"]
PAUSE_S = 5.0


# --- Ríos -----------------------------------------------------------------------------------------------------------

def norm(name: str) -> str:
    """La clave con que el sitio junta los nombres de los registros con su trazo (``historico-detalle.js``,
    ``norm``): sin tildes, en minúsculas y con un espacio entre palabras («Río Rímac» y «Río Rimac» son uno)."""
    s = unicodedata.normalize("NFD", name)
    return " ".join("".join(c for c in s if unicodedata.category(c) != "Mn").lower().split())


def named_in_catalog(path: Path = CATALOG) -> dict[tuple[str, str], dict]:
    """{(distrito, clave de ``water_key``): {"names": Counter de nombres, "clase", "r": registros, "b": cuenca más
    frecuente}} de los cuerpos de agua que nombran los registros (``CuerpoAgua``: «Río Moche», «Quebrada Bicua
    (Cunía)», «A · B»)."""
    out: dict[tuple[str, str], dict] = {}
    basins: dict[tuple[str, str], Counter] = defaultdict(Counter)
    with zipfile.ZipFile(path) as z:
        for r in csv.DictReader(io.TextIOWrapper(z.open("eventos.csv"), encoding="utf-8-sig")):
            if not r["CuerpoAgua"] or len(r["Ubigeo"]) != 6:
                continue
            for part in r["CuerpoAgua"].split(" · "):
                name = re.sub(r"\s*\([^)]*\)$", "", part).strip()
                if name.startswith(("Nevado", "Volcán", "Abra")):
                    continue  # un punto, no un trazo: ya va en la capa de puntos
                k = water_key(name)
                if len(k) < 3:
                    continue
                e = out.setdefault((r["Ubigeo"], k), {"names": Counter(), "clase": "laguna" if name.startswith("Lag") else "curso",
                                                      "r": 0})
                e["names"][name] += 1
                e["r"] += 1
                if r["CuencaCodigo"]:
                    basins[(r["Ubigeo"], k)][r["CuencaCodigo"]] += 1
    for key, e in out.items():
        e["b"] = basins[key].most_common(1)[0][0] if basins[key] else ""
    return out


def _path(pts: list[tuple[float, float]], close: bool = False) -> str:
    """Trazo SVG relativo con un decimal; vacío si al redondear quedan menos de dos puntos (tres en un anillo)."""
    q = []
    for x, y in pts:
        p = (round(x * 10), round(y * 10))
        if not q or q[-1] != p:
            q.append(p)
    if close and len(q) > 1 and q[0] == q[-1]:
        q.pop()
    if len(q) < (3 if close else 2):
        return ""
    rel = " ".join(f"{(b[0] - a[0]) / 10:g} {(b[1] - a[1]) / 10:g}" for a, b in zip(q, q[1:]))
    return f"M{q[0][0] / 10:g} {q[0][1] / 10:g}l{rel}{'z' if close else ''}"


def _preferred(names: Counter) -> str:
    """El nombre con más tildes (la grafía correcta de «Río Rímac» frente a «Río Rimac») y, entre iguales, el más
    usado."""
    return max(names, key=lambda n: (sum(ord(c) > 127 for c in n), names[n], n))


def rivers(src: dict[str, list[dict]], wanted: dict[tuple[str, str], dict], lim=None) -> list[dict]:
    """El trazo de cada río, quebrada o laguna que nombran los registros, juntado por cuenca y nombre: los tramos de
    la Carta con ese nombre que pasan por algún distrito donde un registro lo nombra, enteros (la Carta corta los
    cauces en confluencias y bordes de hoja, de unos metros a unos 50 km). [{"b", "k", "n", "c", "r", "u", "d"}, …],
    de más a menos registros; ``k`` es ``norm`` del nombre, ``u`` los distritos y ``a`` (si hace falta) las otras grafías
    con que lo nombran los registros de esos distritos, normalizadas: la página junta un registro con su trazo por
    distrito y ``norm`` del nombre que trae (historico-detalle.js, ``prepRivers``)."""
    from enso.limites import limits

    grid = _Grid(lim or limits())
    keys = {k for _, k in wanted}
    groups: dict[tuple[str, str], dict] = {}
    gid: dict[tuple[str, str], tuple[str, str]] = {}
    for (code, k), e in wanted.items():
        name = _preferred(e["names"])
        g = (e["b"], norm(name))
        gid[(code, k)] = g
        grp = groups.setdefault(g, {"names": Counter(), "c": e["clase"], "r": 0, "u": set(), "feats": {}, "a": set()})
        grp["names"].update(e["names"])
        grp["a"].update(norm(n) for n in e["names"])
        grp["r"] += e["r"]
        grp["u"].add(code)

    def touched(pts) -> set[str]:
        return {grid.district(round(x * SCALE), round(y * SCALE)) for x, y in pts} - {""}

    for layer, field in (("rios", "paths"), ("lagunas", "rings")):
        for fi, f in enumerate(src[layer]):
            a, g = f["attributes"], f.get("geometry") or {}
            name, alias = names(a.get("NOMBRE"))
            name = _with_class(name, a.get("RASGO_PRIN"))
            ks = {water_key(n) for n in [name, *alias]} & keys
            if not ks or not g.get(field):
                continue
            for pi, part in enumerate(g[field]):
                pts = _densify(part) if layer == "rios" else [tuple(p) for p in part]
                for code in touched(pts):
                    for k in ks:
                        if (code, k) in gid:
                            groups[gid[(code, k)]]["feats"][(layer, fi, pi)] = part
    out = []
    for (b, k), grp in groups.items():
        parts = []
        for (layer, _fi, _pi), part in sorted(grp["feats"].items()):
            xy = [project(x, y) for x, y in part]
            if layer == "rios":
                parts.append(_path(_dp(xy, TOL_PX)))
            else:
                ring = next((r for r in (_dp(xy, t) for t in (TOL_PX, TOL_PX / 4, 0)) if len(r) >= 4), xy)
                parts.append(_path(ring, close=True))
        d = "".join(parts)
        if d:
            row = {"b": b, "k": k, "n": _preferred(grp["names"]), "c": grp["c"], "r": grp["r"], "u": sorted(grp["u"])}
            if grp["a"] - {k}:
                row["a"] = sorted(grp["a"] - {k})
            out.append({**row, "d": d})
    return sorted(out, key=lambda x: (-x["r"], x["b"], x["k"]))


# --- Manzanas en riesgo (CENEPRED) ----------------------------------------------------------------------------------

def download_blocks(client: httpx.Client, folder: Path) -> None:
    robots = Robots(client)
    folder.mkdir(parents=True, exist_ok=True)
    for layer in BLOCK_LAYERS:
        url = f"{SIGRID}/{layer}/query"
        if robots.allowed(url) is not True:
            raise SystemExit(f"{url}: el robots.txt (o una verificación) no deja pedirlo")
        offset = 0
        while True:
            robots.pace(url)
            r = client.get(url, params={"where": "1=1", "outFields": BLOCK_FIELDS, "returnGeometry": "true",
                                        "outSR": "4326", "orderByFields": "objectid", "resultOffset": offset,
                                        "resultRecordCount": 1000, "f": "json"}, timeout=120).raise_for_status()
            page = r.json()
            if "error" in page:
                raise SystemExit(f"{url}: {page['error']}")
            (folder / f"capa{layer}-{offset:05d}.json").write_bytes(r.content)
            got = page.get("features") or []
            offset += len(got)
            time.sleep(PAUSE_S)
            if not page.get("exceededTransferLimit") or not got:
                break
        print(f"capa {layer} ({BLOCK_LAYERS[layer]}): {offset} manzanas")


def _centroid(rings: list[list[list[float]]]) -> tuple[float, float]:
    """Centro del anillo exterior más grande (por área), en grados."""
    best, area = None, -1.0
    for r in rings:
        a = sum(r[i][0] * r[i - 1][1] - r[i - 1][0] * r[i][1] for i in range(len(r))) / 2
        if abs(a) > area:
            best, area = r, abs(a)
    xs, ys = [p[0] for p in best], [p[1] for p in best]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _place(raw) -> str:
    """«SAN PEDRO DE LOS INCAS» → «San Pedro de los Incas»."""
    t = " ".join(str(raw or "").split()).title()
    return re.sub(r"(?<=\s)(De|Del|La|Las|Los|El|Y)(?=\s)", lambda m: m.group(1).lower(), t)


def blocks(folder: Path) -> list[list]:
    """[[lat, lon, ubigeo, centro poblado, nivel (0 = muy alto … 3 = bajo), población, viviendas], …]."""
    out = []
    for p in sorted(folder.glob("capa*.json")):
        for f in json.loads(p.read_text(encoding="utf-8")).get("features") or []:
            a, g = f.get("attributes") or {}, f.get("geometry") or {}
            level = str(a.get("nriesgo") or "").strip().title().replace("Muy alto", "Muy Alto")
            if level not in RISK_LEVELS or not g.get("rings"):
                continue
            lon, lat = _centroid(g["rings"])
            out.append([round(lat, 5), round(lon, 5), str(a.get("ubigeo") or ""), _place(a.get("nomccpp")),
                        RISK_LEVELS.index(level), int(a.get("pob_total") or 0), int(a.get("viv_part_p") or 0)])
    return sorted(out, key=lambda b: (b[2], b[4], -b[5], b[0], b[1]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aguas", type=Path, required=True, help="páginas de la Carta (tools.build_aguas --keep)")
    ap.add_argument("--manzanas", type=Path, help="carpeta de las páginas del CENEPRED")
    ap.add_argument("--sin-red", action="store_true", help="no descargar: usar las páginas de --manzanas")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    wanted = named_in_catalog()
    reaches = rivers(read_pages(a.aguas), wanted)
    doc = {"source": "IGN, Carta Nacional 1:100 000 (vía IDEP, PCM); nombres: memoria de desastres (CuerpoAgua)",
           "generatedBy": "python -m tools.build_capas_mapa", "reaches": reaches}
    path = a.out / "rios-mapa.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{path}: {len(reaches)} ríos, quebradas y lagunas de {len(wanted)} nombres por distrito, "
          f"{path.stat().st_size // 1024} KB")
    if a.manzanas:
        if not a.sin_red:
            with httpx.Client(headers={"User-Agent": UA}) as client:
                download_blocks(client, a.manzanas)
        rows = blocks(a.manzanas)
        doc = {"source": "CENEPRED, SIGRID: escenario de riesgo ante El Niño 2026-2027 (sectores/COEN_FEN_2027, capas "
                         "57, 58 y 61); población y viviendas del censo 2017 (INEI) por manzana",
               "url": SIGRID, "generatedBy": "python -m tools.build_capas_mapa", "levels": RISK_LEVELS,
               "fields": ["lat", "lon", "ubigeo", "centroPoblado", "nivel", "poblacion", "viviendas"], "blocks": rows}
        path = a.out / "manzanas-riesgo.json"
        path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        by = Counter(RISK_LEVELS[b[4]] for b in rows)
        print(f"{path}: {len(rows)} manzanas {dict(by)}, {path.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
