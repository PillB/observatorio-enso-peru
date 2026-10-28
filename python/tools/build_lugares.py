"""Construye ``enso/data/lugares.json.gz`` (centros poblados por distrito) y ``enso/data/cuencas.json.gz``
(unidades hidrográficas de la ANA), las referencias para ubicar un evento más fino que su distrito.

Fuentes, todas públicas, del geoportal de la Infraestructura de Datos Espaciales del Perú (IDEP, de la PCM;
su robots.txt responde 404, sin reglas):

- ``CENTROS_POBLADOS_DISPERSOS/0``: centros poblados del Censo 2017 del INEI (unos 81 000), con su código
  de 10 dígitos (UBIGEO + 4) y población.
- ``CENTROS_POBLADOS/3``: centros poblados del IGN y del INEI (unos 137 000), con su categoría (caserío,
  anexo, barrio…): trae las capitales y pueblos que la capa del censo no tiene.
- ``CENTROS_POBLADOS_DISPERSOS/1``: centros poblados de la Secretaría de Demarcación (SDOT-PCM), con su
  categoría legal: nombres oficiales de los pueblos más grandes.
- ``INSTITUCIONALES/ANA_WMS/7``: las 231 unidades hidrográficas principales de la ANA (cuencas e
  intercuencas, códigos Pfafstetter, R.M. N° 033-2008-AG).

Cada centro poblado se guarda en el distrito **vigente** que contiene su punto (límites del INDECI, ver
``tools.build_limites``), si ese distrito es el de su código o uno de la misma provincia (los códigos son de
2017 y los distritos creados después heredan sus centros poblados). Si el punto cae en otra provincia, solo se
guarda en el distrito de su código cuando está a 1 km o menos de él; si no, se descarta (``fuera``). Si el INEI y
el IGN ubican el mismo código a más de 5 km, el punto lleva un radio de 5 km (``radio``).

Formato de ``lugares.json.gz``: ``{"source", "scale", "fields", "districts": {UBIGEO: [[nombre, x, y,
categoría, código, población, capa, radio], …]}, "stats"}``, con coordenadas en enteros (grados × 10⁴).
``cuencas.json.gz``: ``{"source", "scale", "units": {código Pfafstetter: {name, level, area_km2, bbox, polys}},
"districts": {UBIGEO: [[código, fracción del distrito], …]}}``.

Uso:
    python -m tools.build_lugares [--dir CARPETA] [--keep CARPETA]

``--keep`` guarda las páginas bajadas; ``--dir`` las usa en vez de bajarlas. Los archivos ya están en el
repositorio: esto solo hace falta para una versión nueva.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import time
from collections import Counter
from pathlib import Path

import httpx

from enso.fetch import UA
from enso.reach import Robots
from tools.build_limites import SCALE, _bbox, _rings

IDEP = "https://www.idep.gob.pe/geoportal/rest/services"
#: Capa, campos y orden de cada fuente (el servicio ordena por OBJECTID para paginar sin saltos).
LAYERS = {
    "inei": (f"{IDEP}/DATOS_GEOESPACIALES/CENTROS_POBLADOS_DISPERSOS/MapServer/0",
             "OBJECTID,cod_dist,cod_ccpp,nom_ccpp,pob_total", "OBJECTID"),
    "ign": (f"{IDEP}/DATOS_GEOESPACIALES/CENTROS_POBLADOS/MapServer/3",
            "OBJECTID,NOM_POBLAD,FUENTE,CÓDIGO,CAT_POBLAD,CATEGORIA", "OBJECTID"),
    "sdot": (f"{IDEP}/DATOS_GEOESPACIALES/CENTROS_POBLADOS_DISPERSOS/MapServer/1",
             "OBJECTID,ubigeo,cen_pob,codcp_inei,categoria,pob", "OBJECTID"),
    "ana": (f"{IDEP}/INSTITUCIONALES/ANA_WMS/MapServer/7",
            "OBJECTID_1,CODIGO,NOMBRE,NIVEL1,NIVEL2,NIVEL3,NIVEL4,NIVEL5,NOMB_UH_N4,AREA_KM2", "OBJECTID_1"),
}
SOURCES = {
    "inei": "INEI, Censos Nacionales 2017, centros poblados (vía IDEP, PCM)",
    "ign": "IGN e INEI, centros poblados (vía IDEP, PCM)",
    "sdot": "Secretaría de Demarcación y Organización Territorial (SDOT-PCM), centros poblados (vía IDEP)",
    "ana": "ANA, unidades hidrográficas del Perú, metodología Pfafstetter (R.M. N° 033-2008-AG; vía IDEP, PCM)",
}
PAGE = {"inei": 2000, "ign": 2000, "sdot": 2000, "ana": 50}
DATA = Path(__file__).resolve().parents[1] / "enso" / "data"
OUT_PLACES = DATA / "lugares.json.gz"
OUT_BASINS = DATA / "cuencas.json.gz"
FIELDS = ["nombre", "x", "y", "categoria", "codigo", "poblacion", "capa", "radio_km"]
#: Tolerancia: un centro poblado de otra provincia se acepta en el distrito de su código hasta esta distancia.
TOLERANCE_KM = 1.0
#: Si el INEI y el IGN ubican el mismo código más lejos que esto, el punto es dudoso: radio de 5 km.
DISAGREE_KM = 5.0
#: Simplificación de las cuencas (unidades de SCALE: 20 ≈ 220 m).
BASIN_TOL = 20
#: Categorías del IGN (CAT_POBLAD) que valen como categoría del lugar.
CATEGORIES = {"CASERÍO": "caserío", "ANEXO": "anexo", "UNID. AGROPECUARIA": "unidad agropecuaria",
              "PUEBLO": "pueblo", "BARRIO O CUARTEL": "barrio", "CIUDAD": "ciudad", "CAMPO MINERO": "campo minero",
              "PP.JJ.AA.HH.": "asentamiento humano", "COOP. AGRARIA": "cooperativa agraria", "VILLA": "villa",
              "URBANIZACION": "urbanización", "ASOCIACION DE VIVIENDA": "asociación de vivienda", "OTROS": ""}


def _query(url: str, fields: str, order: str, offset: int, page: int, geometry_offset: float = 0) -> dict:
    q = {"where": "1=1", "outFields": fields, "returnGeometry": "true", "outSR": "4326", "orderByFields": order,
         "resultOffset": offset, "resultRecordCount": page, "f": "json"}
    if geometry_offset:
        q.update(maxAllowableOffset=geometry_offset, geometryPrecision=5)
    return q


def download(client: httpx.Client, keep: Path | None = None, pause: float = 1.0) -> dict[str, list[dict]]:
    """Las cuatro capas, por páginas, si el robots.txt del IDEP lo permite. ``keep`` guarda cada página."""
    robots = Robots(client)
    out: dict[str, list[dict]] = {}
    for name, (url, fields, order) in LAYERS.items():
        if robots.allowed(url + "/query") is not True:
            raise SystemExit(f"El robots.txt de {httpx.URL(url).host} no permite (o no se sabe si permite) {url}")
        total = client.get(url + "/query", params={"where": "1=1", "returnCountOnly": "true", "f": "json"},
                           timeout=120).raise_for_status().json()["count"]
        feats: list[dict] = []
        while len(feats) < total:
            params = _query(url, fields, order, len(feats), PAGE[name], 0.0005 if name == "ana" else 0)
            for attempt in range(4):
                try:
                    r = client.get(url + "/query", params=params, timeout=300).raise_for_status()
                    page = r.json()
                    if "error" in page:
                        raise httpx.HTTPError(str(page["error"]))
                    break
                except (httpx.HTTPError, ValueError):
                    if attempt == 3:
                        raise
                    time.sleep(5 * (attempt + 1))
            got = page.get("features") or []
            if not got:
                raise SystemExit(f"{name}: página vacía en {len(feats)} de {total}")
            if keep:
                keep.mkdir(parents=True, exist_ok=True)
                (keep / f"{name}-{len(feats):06d}.json").write_bytes(r.content)
            feats += got
            time.sleep(pause)
        out[name] = feats
        print(f"{name}: {len(feats)} de {total}")
    return out


def read_pages(folder: Path) -> dict[str, list[dict]]:
    return {name: [f for p in sorted(folder.glob(f"{name}-*.json"))
                   for f in json.loads(p.read_text(encoding="utf-8"))["features"]] for name in LAYERS}


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return math.hypot((lat1 - lat2) * 110.57, (lon1 - lon2) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2)))


def _clean(name) -> str:
    return " ".join(str(name or "").split()).strip(" .,-")


def _code(v) -> str:
    v = str(v or "").strip()
    return v if len(v) == 10 and v.isdigit() else ""


def places(src: dict[str, list[dict]], lim=None) -> tuple[dict[str, list], Counter]:
    """{UBIGEO vigente: [[nombre, x, y, categoría, código, población, capa, radio], …]} y las cuentas."""
    from enso.limites import limits

    lim = lim or limits()
    stats: Counter = Counter()
    merged: dict[str, dict] = {}
    for f in src["inei"]:
        a, g = f["attributes"], f.get("geometry") or {}
        code, name = _code(a.get("cod_ccpp")), _clean(a.get("nom_ccpp"))
        if not code or not name or not g.get("y"):
            stats["inei sin código, nombre o punto"] += 1
            continue
        merged[code] = {"name": name, "lat": g["y"], "lon": g["x"], "cat": "", "code": code,
                        "pop": a.get("pob_total") or 0, "layer": "inei", "radius": 0.0}
    for f in src["ign"]:
        a, g = f["attributes"], f.get("geometry") or {}
        code, name = _code(a.get("CÓDIGO")), _clean(a.get("NOM_POBLAD"))
        if not name or not g.get("y"):
            stats["ign sin nombre o punto"] += 1
            continue
        cat = "capital de distrito" if (a.get("CATEGORIA") or "").strip() == "Capital de Distrito" else \
            CATEGORIES.get((a.get("CAT_POBLAD") or "").strip(), "")
        if code in merged:
            p = merged[code]
            if p["layer"] == "inei":
                d = _km(p["lat"], p["lon"], g["y"], g["x"])
                stats["inei e ign, mismo código"] += 1
                if d > DISAGREE_KM:
                    p["radius"] = DISAGREE_KM
                    stats[f"inei e ign a más de {DISAGREE_KM:g} km"] += 1
                if not p["cat"]:
                    p["cat"] = cat
                if name.upper() != p["name"].upper():
                    p.setdefault("aliases", set()).add(name)
            continue
        key = code or f"ign-{a['OBJECTID']}"
        merged[key] = {"name": name, "lat": g["y"], "lon": g["x"], "cat": cat, "code": code, "pop": 0,
                       "layer": "ign", "radius": 0.0}
    for f in src["sdot"]:
        a = f["attributes"]
        code = _code(a.get("codcp_inei"))
        if code in merged and a.get("categoria"):
            merged[code]["cat"] = merged[code]["cat"] or str(a["categoria"]).strip().lower()
            if _clean(a.get("cen_pob")).upper() != merged[code]["name"].upper():
                merged[code].setdefault("aliases", set()).add(_clean(a.get("cen_pob")))
    out: dict[str, list] = {}
    for key, p in merged.items():
        x, y = round(p["lon"] * SCALE), round(p["lat"] * SCALE)
        here = lim.containing(6, x, y)
        coded = p["code"][:6]
        homes = []
        if here and (not coded or here[:4] == coded[:4]):
            homes.append(here)
            if coded and coded != here and coded in lim.levels[6] and \
                    lim._edge(x, y, lim.levels[6][coded]["polys"])[0] <= TOLERANCE_KM:
                homes.append(coded)
        elif coded in lim.levels[6] and lim._edge(x, y, lim.levels[6][coded]["polys"])[0] <= TOLERANCE_KM:
            homes.append(coded)
        if not homes:
            stats["fuera de su provincia (descartado)" if here else "fuera del Perú (descartado)"] += 1
            continue
        stats["en el distrito de su código" if coded in homes[:1] else
              "sin código (IGN)" if not coded else "en otro distrito de su provincia"] += 1
        for name in [p["name"], *sorted(p.get("aliases", ()))]:
            row = [name, x, y, p["cat"], p["code"], p["pop"], p["layer"], p["radius"]]
            for home in homes:
                out.setdefault(home, []).append(row)
    for rows in out.values():
        rows.sort(key=lambda r: (r[4] or "~", r[0]))
    return out, stats


def basins(src: dict[str, list[dict]]) -> dict[str, dict]:
    """{código Pfafstetter: {nombre, nivel, bbox, polys}} de las unidades hidrográficas de la ANA."""
    out: dict[str, dict] = {}
    for f in src["ana"]:
        a, g = f["attributes"], f.get("geometry") or {}
        code = str(a.get("CODIGO") or "").strip()
        if not code or not g.get("rings"):
            continue
        # El servicio responde anillos sueltos (formato Esri): exteriores en sentido horario, huecos al revés.
        polys: list[list[list]] = []
        for ring in g["rings"]:
            area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:]))
            if area <= 0 or not polys:  # horario (área negativa en x-y): un borde exterior
                polys.append([ring])
            else:
                polys[-1].append(ring)
        rings = _rings({"type": "MultiPolygon", "coordinates": polys}, BASIN_TOL)
        if rings:
            prev = out.get(code)
            if prev:
                rings = prev["polys"] + rings
            out[code] = {"name": _clean(a.get("NOMBRE")), "level": len(code), "area_km2": round(a.get("AREA_KM2") or 0),
                         "bbox": _bbox(rings), "polys": rings}
    return out


def district_basins(units: dict[str, dict], lim=None, grid: int = 24) -> dict[str, list]:
    """{UBIGEO: [[código de cuenca, fracción del distrito], …]}, de mayor a menor, midiendo en una grilla de
    ``grid`` × ``grid`` puntos sobre la caja de cada distrito (los que caen dentro del distrito)."""
    from enso.limites import _in_bbox, _in_polys, limits

    lim = lim or limits()
    out: dict[str, list] = {}
    for code, d in lim.levels[6].items():
        x0, y0, x1, y1 = d["bbox"]
        hits: Counter = Counter()
        for i in range(grid):
            for j in range(grid):
                x, y = x0 + (i + 0.5) * (x1 - x0) / grid, y0 + (j + 0.5) * (y1 - y0) / grid
                if not _in_polys(x, y, d["polys"]):
                    continue
                for b, u in units.items():
                    if _in_bbox(x, y, u["bbox"]) and _in_polys(x, y, u["polys"]):
                        hits[b] += 1
                        break
        total = sum(hits.values())
        if total:
            out[code] = [[b, round(n / total, 2)] for b, n in hits.most_common() if n / total >= 0.02]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", type=Path, help="páginas ya bajadas")
    ap.add_argument("--keep", type=Path, help="carpeta donde guardar las páginas bajadas")
    a = ap.parse_args(argv)
    if a.dir:
        src = read_pages(a.dir)
    else:
        with httpx.Client(headers={"User-Agent": UA}) as client:
            src = download(client, a.keep)
    by_district, stats = places(src)
    data = {"source": {k: SOURCES[k] + ", " + LAYERS[k][0] for k in ("inei", "ign", "sdot")}, "scale": SCALE,
            "fields": FIELDS, "districts": dict(sorted(by_district.items())), "stats": dict(sorted(stats.items()))}
    OUT_PLACES.write_bytes(gzip.compress(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode(), 9, mtime=0))
    units = basins(src)
    shares = district_basins(units)
    OUT_BASINS.write_bytes(gzip.compress(json.dumps(
        {"source": SOURCES["ana"] + ", " + LAYERS["ana"][0], "scale": SCALE, "units": dict(sorted(units.items())),
         "districts": dict(sorted(shares.items()))},
        ensure_ascii=False, separators=(",", ":")).encode(), 9, mtime=0))
    n = sum(len(v) for v in by_district.values())
    print(f"{OUT_PLACES}: {n} nombres en {len(by_district)} distritos, {OUT_PLACES.stat().st_size // 1024} KB")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    print(f"{OUT_BASINS}: {len(units)} unidades hidrográficas, {OUT_BASINS.stat().st_size // 1024} KB; "
          f"{sum(1 for v in shares.values() if v[0][1] >= 0.8)} de {len(shares)} distritos con 80 % o más en una")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
