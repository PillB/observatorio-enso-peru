"""Construye ``enso/data/aguas.json.gz``: ríos, quebradas, lagunas, nevados y abras con nombre, por distrito, para
ubicar un evento que nombra uno de ellos («desborde del río Chiguata», «huaico en la quebrada Pedregal») cuando la
fuente no nombra un centro poblado.

Fuentes, todas públicas, del geoportal de la Infraestructura de Datos Espaciales del Perú (IDEP, de la PCM; su
robots.txt responde 404, sin reglas), de la Carta Nacional 1:100 000 del IGN:

- ``PERU_100K/13`` «Río Lineal»: los tramos con nombre (unos 48 600 de 235 000), ríos y quebradas.
- ``PERU_100K/14`` «Lago y Laguna»: los polígonos con nombre (unos 10 300 de 27 500).
- ``PERU_100K/0`` «Toponimia»: nevados, volcanes y abras con nombre (puntos), y lagunas que la capa 14 no nombra.

Cómo se arma cada entrada: los tramos de un mismo nombre se densifican (un punto cada ``STEP_KM``) y cada punto se
asigna al distrito vigente que lo contiene (límites del INDECI, ``enso.limites``). Por distrito y nombre, el
**punto** es el del tramo más cercano al centro de esos puntos (siempre sobre el cauce) y el **radio** la distancia
de él al punto más lejano del tramo en el distrito: un río que cruza el distrito de punta a punta tiene un radio
grande y ``enso.aguas`` no lo usa como punto, solo para la cuenca. Un río y una quebrada del mismo nombre en un
distrito se tratan como un solo curso (el IGN llama «Río» a un tramo y «Quebrada» al de más arriba). La **cuenca**
es la unidad hidrográfica de la ANA (``cuencas.json.gz``) donde cae la mayor parte del tramo, con esa fracción.

Formato: ``{"source", "scale", "fields", "districts": {UBIGEO: [[nombre, clase, x, y, radio_km, largo_km,
cuenca, fracción], …]}, "alias": {UBIGEO: [[fila, otro nombre], …]}, "stats"}``; clase = curso | laguna | nevado |
volcan | abra; x, y en grados × 10⁴. «alias»: los otros nombres que la Carta da a un rasgo («Río Chili (Sumbay)»,
«Río Salla o Cotacucho»), que el buscador también reconoce.

Uso:
    python -m tools.build_aguas [--dir CARPETA] [--keep CARPETA]

``--keep`` guarda las páginas bajadas; ``--dir`` las usa en vez de bajarlas. El archivo ya está en el repositorio:
esto solo hace falta para una versión nueva.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import httpx

from enso.aguas import PREFIX, water_key
from enso.fetch import UA
from enso.reach import Robots
from tools.build_limites import SCALE

IGN = "https://www.idep.gob.pe/geoportal/rest/services/DATOS_GEOESPACIALES/PERU_100K/MapServer"
#: Capa: (URL, filtro, campos, orden, registros por página, simplificación en grados).
LAYERS = {
    "rios": (f"{IGN}/13", "NOMBRE IS NOT NULL AND NOMBRE <> ''", "OBJECTID_1,NOMBRE,RASGO_PRIN", "OBJECTID_1", 1000,
             0.0003),
    "lagunas": (f"{IGN}/14", "NOMBRE IS NOT NULL AND NOMBRE <> ''", "OBJECTID,NOMBRE,RASGO_PRIN", "OBJECTID", 1000,
                0.0003),
    "toponimia": (f"{IGN}/0", "Nombre <> 'Nombre no registrado' AND Entidad IN ('Nevado','Volcan','Abra','Laguna',"
                  "'Lago')", "OBJECTID,Nombre,Entidad", "OBJECTID", 1000, 0),
}
SOURCE = ("IGN, Carta Nacional 1:100 000: {} (vía IDEP, PCM), "
          "https://www.idep.gob.pe/geoportal/rest/services/DATOS_GEOESPACIALES/PERU_100K/MapServer")
LAYER_NAMES = {"rios": "Río Lineal (capa 13)", "lagunas": "Lago y Laguna (capa 14)", "toponimia": "Toponimia (capa 0)"}
DATA = Path(__file__).resolve().parents[1] / "enso" / "data"
OUT = DATA / "aguas.json.gz"
FIELDS = ["nombre", "clase", "x", "y", "radio_km", "largo_km", "cuenca", "fraccion_cuenca"]
#: Un punto cada tanto a lo largo de un cauce (un tramo recto de la Carta tiene solo sus dos extremos).
STEP_KM = 0.4
#: Radio mínimo de un punto de toponimia o de un cauce corto (la Carta es 1:100 000: 1 mm son 100 m).
MIN_RADIUS_KM = {"curso": 0.5, "laguna": 0.3, "nevado": 2.0, "volcan": 2.0, "abra": 0.5}
#: Celdas de la grilla para buscar el distrito de un punto (unidades de SCALE: 1 000 = 0,1°).
CELL = 1000


def _query(where: str, fields: str, order: str, offset: int, page: int, simplify: float) -> dict:
    q = {"where": where, "outFields": fields, "returnGeometry": "true", "outSR": "4326", "orderByFields": order,
         "resultOffset": offset, "resultRecordCount": page, "f": "json"}
    if simplify:
        q.update(maxAllowableOffset=simplify, geometryPrecision=5)
    return q


def download(client: httpx.Client, keep: Path | None = None, pause: float = 1.0) -> dict[str, list[dict]]:
    """Las tres capas, por páginas, si el robots.txt del IDEP lo permite. ``keep`` guarda cada página."""
    robots = Robots(client)
    out: dict[str, list[dict]] = {}
    for name, (url, where, fields, order, size, simplify) in LAYERS.items():
        if robots.allowed(url + "/query") is not True:
            raise SystemExit(f"El robots.txt de {httpx.URL(url).host} no permite (o no se sabe si permite) {url}")
        total = client.get(url + "/query", params={"where": where, "returnCountOnly": "true", "f": "json"},
                           timeout=120).raise_for_status().json()["count"]
        feats: list[dict] = []
        while len(feats) < total:
            params = _query(where, fields, order, len(feats), size, simplify)
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


#: Cómo escribe el IGN la clase al comienzo del nombre (sin tildes y en minúsculas), con sus erratas.
_CLASS_WORD = [
    (re.compile(r"^(?:rio|roo|ro|ri0)\b\.?\s*"), "Río "),
    (re.compile(r"^(?:(?:quebrada|quebrda|querbrada|quebarada|quebrad|qda|q)\b\.?|quebrada(?=[a-z]{3})|qda\.|q\.)"
                r"\s*"), "Quebrada "),
    (re.compile(r"^lagunas\b\.?\s*"), "Lagunas "),
    (re.compile(r"^(?:(?:laguna|laguan|lag)\b\.?|laguna(?=[a-z]{3}))\s*"), "Laguna "),
    (re.compile(r"^lago\b\.?\s*"), "Lago "),
    (re.compile(r"^riachuelo\b\.?\s*"), "Riachuelo "),
    (re.compile(r"^arroyo\b\.?\s*"), "Arroyo "),
    (re.compile(r"^estero\b\.?\s*"), "Estero "),
    (re.compile(r"^canal\b\.?\s*"), "Canal "),
    (re.compile(r"^volcan\b\.?\s*"), "Volcán "),
    (re.compile(r"^nevado\b\.?\s*"), "Nevado "),
    (re.compile(r"^abra\b\.?\s*"), "Abra "),
]


def _fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def display(name: str, join: bool = False) -> str:
    """El nombre del IGN legible: espacios simples, la clase bien escrita y con tilde, y mayúsculas de nombre
    propio si venía todo en mayúsculas o en minúsculas («RÍo  Napo» → «Río Napo», «QUEBRADA SECA» → «Quebrada
    Seca», «Qda.Honda» → «Quebrada Honda»). Corrige las erratas de la Carta que cambian la clave del nombre:
    «¥» por «ñ» («Le¥a»), «R¡o», comillas y signos sueltos, mayúsculas con tilde dentro de una palabra
    («GavilÁn»), palabras pegadas («RioTirutaña», «JancoJanco»: con ``join``, «Jancojanco»)."""
    from enso.lugares import title

    name = str(name or "").replace(">", " ").replace("¥", "ñ").replace("¡", "í")
    name = re.sub(r"[\"“”]", "", name)
    name = re.sub(r"(?<=[^\W\d_])[,;](?=[^\W\d_])", "", name)  # «M,achuyoc», «Bal;con»
    name = re.sub(r"(?<=[a-zñáéíóú])([ÁÉÍÓÚÑ])", lambda m: m.group(1).lower(), name)
    name = re.sub(r"^I(?=(?:Laguna|Quebrada|Rio|Río)\b)", "", name)  # «ILaguna nocunca»
    name = re.sub(r"^(Rio|Río|Quebrada|Qda|Laguna)(?=[A-Z])", r"\1 ", name)  # «RioTirutaña»
    name = re.sub(r"(?<=[a-zñáéíóú])([A-Z])(?=[a-zñáéíóú])", (lambda m: m.group(1).lower()) if join else r" \1", name)
    name = re.sub(r"(?<=\w) (De|Del) (?=\w)", lambda m: " " + m.group(1).lower() + " ", name)
    name = re.sub(r"^[^\w¿]+", "", " ".join(name.split())).strip(" .,-")
    folded = _fold(name)
    for pat, word in _CLASS_WORD:
        m = pat.match(folded)
        if m:
            name, folded = word + name[m.end():].strip(" .,-"), word.lower() + folded[m.end():].strip(" .,-")
            break
    rest = name.split(" ", 1)[1] if " " in name and name.split(" ", 1)[0] in {w.strip() for _, w in _CLASS_WORD} \
        else name
    if rest.isupper() or rest.islower():
        name = title(name)
        name = re.sub(r"^Rio\b", "Río", re.sub(r"^Volcan\b", "Volcán", name))
    return name.strip()


#: Lo que no es otro nombre del mismo cuerpo de agua cuando va entre paréntesis.
_NOT_ALIAS = frozenset({"mina"})


def names(raw: str) -> tuple[str, list[str]]:
    """(nombre, otros nombres) de un nombre del IGN que trae más de uno: «Río Chili (Sumbay)», «Quebrada Quemadal/
    Gramadal», «Río Salla o Cotacucho», «Nevado Misti (Ver Volcán Misti)» (una referencia a otro rasgo de la Carta:
    el nombre sin la clase cuenta, la clase no) o «San Salvador, Contamana» (el lugar después de la coma no es
    parte del nombre)."""
    raw = re.sub(r"\s+", " ", str(raw or "")).strip()
    alts = [m.group(1) for m in re.finditer(r"\(([^()]*)(?:\)|$)", raw)]
    main = re.sub(r"\([^()]*(?:\)|$)", " ", raw)
    main = main.split(", ")[0]
    parts = re.split(r"\s*/\s*|\s+[oO]\s+", main)
    main, alts = parts[0], parts[1:] + alts
    out = []
    for a in alts:
        a = re.sub(r"^\s*ver\s+(?:tambi[eé]n\s+)?(?:cerro\s+)?", "", a, flags=re.I)
        a = display(a)
        k = water_key(a)
        if len(k) >= 3 and k not in _NOT_ALIAS and a not in out:
            out.append(a)
    if re.search(r"[a-zñáéíóú][A-Z][a-zñáéíóú]", main):  # «Río JancoJanco»: también «Jancojanco»
        joined = _once(display(main, join=True))
        if not re.search(r"^(?:rio|quebrad|laguna)[a-z]|[a-z](?:quebrad|laguna)", water_key(joined)):
            out.append(joined)  # no «Ríoparcotica» ni «Quebrada Unchuquebrada Unchu»
    main = _once(display(main))
    if re.search(r"(\w)\1{3,}", main):  # «Vvvvvvvvvvvv»
        return "", []
    return main, list(dict.fromkeys(a for a in out if water_key(a) != water_key(main)))


def _once(name: str) -> str:
    """«Quebrada Unchu Quebrada Unchu» (el nombre repetido en la Carta) → «Quebrada Unchu»."""
    m = re.fullmatch(r"((?:Río|Quebrada|Laguna|Lagunas|Nevado|Volcán|Abra) .+?) \1", name, flags=re.I)
    return m.group(1) if m else name


def _clase(layer: str, kind: str) -> str:
    kind = unicodedata.normalize("NFKD", kind or "").encode("ascii", "ignore").decode().lower()
    if layer == "rios":
        return "curso"
    if layer == "lagunas" or kind in ("laguna", "lago"):
        return "laguna"
    return {"nevado": "nevado", "volcan": "volcan", "abra": "abra"}.get(kind, "")


def _densify(path: list[list[float]]) -> list[tuple[float, float]]:
    """Los vértices de una línea y puntos intermedios cada ``STEP_KM`` como mucho."""
    out: list[tuple[float, float]] = []
    for (x0, y0), (x1, y1) in zip(path, path[1:]):
        d = _km(y0, x0, y1, x1)
        n = max(1, math.ceil(d / STEP_KM))
        out += [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(n)]
    if path:
        out.append(tuple(path[-1]))
    return out


class _Grid:
    """El distrito vigente que contiene un punto, buscando solo los distritos cuya caja toca la celda."""

    def __init__(self, lim):
        from enso.limites import _in_bbox, _in_polys

        self._in_bbox, self._in_polys = _in_bbox, _in_polys
        self.lim = lim
        self.cells: dict[tuple[int, int], list[str]] = defaultdict(list)
        for code, d in lim.levels[6].items():
            x0, y0, x1, y1 = d["bbox"]
            for i in range(x0 // CELL, x1 // CELL + 1):
                for j in range(y0 // CELL, y1 // CELL + 1):
                    self.cells[(i, j)].append(code)

    def district(self, x: int, y: int) -> str:
        for code in self.cells.get((x // CELL, y // CELL), ()):
            d = self.lim.levels[6][code]
            if self._in_bbox(x, y, d["bbox"]) and self._in_polys(x, y, d["polys"]):
                return code
        return ""


def _ring_points(geom: dict) -> list[tuple[float, float]]:
    return [tuple(p) for ring in geom.get("rings") or [] for p in ring]


def collect(src: dict[str, list[dict]], lim=None) -> tuple[dict[tuple[str, str, str], dict], Counter]:
    """{(distrito, clase, clave): {"pts": [(x, y), …], "names": Counter, "alias": [nombre, …], "len": km}} y las
    cuentas."""
    from enso.limites import limits

    grid = _Grid(lim or limits())
    stats: Counter = Counter()
    acc: dict[tuple[str, str, str], dict] = {}

    def add(code: str, clase: str, k: str, name: str, pts: list[tuple[int, int]], length: float,
            alias: list[str]) -> None:
        e = acc.setdefault((code, clase, k), {"pts": [], "names": Counter(), "alias": [], "len": 0.0})
        e["pts"] += pts
        e["names"][name] += len(pts)
        e["alias"] += [a for a in alias if a not in e["alias"]]
        e["len"] += length

    for f in src["rios"]:
        a, g = f["attributes"], f.get("geometry") or {}
        name, alias = names(a.get("NOMBRE"))
        name = _with_class(name, a.get("RASGO_PRIN"))
        k = water_key(name)
        if len(k) < 3 or not g.get("paths"):
            stats["cauces sin nombre útil o sin geometría"] += 1
            continue
        by_district: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for path in g["paths"]:
            for lon, lat in _densify(path):
                x, y = round(lon * SCALE), round(lat * SCALE)
                code = grid.district(x, y)
                if code:
                    by_district[code].append((x, y))
        if not by_district:
            stats["cauces fuera del Perú"] += 1
        for code, pts in by_district.items():
            add(code, "curso", k, name, pts, len(pts) * STEP_KM, alias)
        stats["tramos de cauce"] += 1
    for f in src["lagunas"]:
        a, g = f["attributes"], f.get("geometry") or {}
        name, alias = names(a.get("NOMBRE"))
        name = _with_class(name, a.get("RASGO_PRIN"))
        k = water_key(name)
        pts = _ring_points(g)
        if len(k) < 3 or not pts:
            stats["lagunas sin nombre útil o sin geometría"] += 1
            continue
        lon = sum(p[0] for p in pts) / len(pts)
        lat = sum(p[1] for p in pts) / len(pts)
        # Una laguna en el límite de dos distritos: en cada uno, la parte de su orilla (y su centro) que cae en él.
        by_district: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for x, y in [(lon, lat)] + pts:
            p = (round(x * SCALE), round(y * SCALE))
            code = grid.district(*p)
            if code:
                by_district[code].append(p)
        if not by_district:
            stats["lagunas fuera del Perú"] += 1
        for code, in_district in by_district.items():
            add(code, "laguna", k, name, in_district, 0, alias)
        stats["lagunas"] += 1
    for f in src["toponimia"]:
        a, g = f["attributes"], f.get("geometry") or {}
        clase = _clase("toponimia", a.get("Entidad"))
        name, alias = names(a.get("Nombre"))
        if clase in ("nevado", "volcan", "abra") and not PREFIX.match(water_key_prefix(name)):
            name = {"nevado": "Nevado", "volcan": "Volcán", "abra": "Abra"}[clase] + " " + name
        elif clase == "laguna" and not PREFIX.match(water_key_prefix(name)):
            name = "Laguna " + name
        k = water_key(name)
        if not clase or len(k) < 3 or g.get("y") is None:
            stats["toponimia sin clase, nombre útil o punto"] += 1
            continue
        x, y = round(g["x"] * SCALE), round(g["y"] * SCALE)
        code = grid.district(x, y)
        if not code:
            stats["toponimia fuera del Perú"] += 1
            continue
        if clase == "laguna" and (code, "laguna", k) in acc:
            stats["toponimia: laguna que la capa 14 ya tiene"] += 1
            continue
        add(code, clase, k, name, [(x, y)], 0, alias)
        stats[f"toponimia: {clase}"] += 1
    return acc, stats


#: La clase que da la Carta (RASGO_PRIN) para un nombre que no la lleva («Korihuala» en la capa de lagunas).
_RASGO = {"rio": "Río", "quebrada": "Quebrada", "laguna": "Laguna", "lago": "Lago", "estero": "Estero",
          "arroyo": "Arroyo"}


def _with_class(name: str, rasgo: str) -> str:
    word = _RASGO.get(_fold(rasgo or ""))
    if not name or not word or PREFIX.match(water_key_prefix(name)):
        return name
    return f"{word} {name}"


def water_key_prefix(name: str) -> str:
    from enso.lugares import name_key

    return name_key(name)


def summarize(acc: dict[tuple[str, str, str], dict], basins=None) -> tuple[dict[str, list], dict[str, list]]:
    """{UBIGEO: [[nombre, clase, x, y, radio_km, largo_km, cuenca, fracción], …]} y {UBIGEO: [[fila, otro nombre],
    …]}."""
    from enso.lugares import basins as load_basins

    basins = basins or load_basins()
    out: dict[str, list] = defaultdict(list)
    alias: dict[str, list] = defaultdict(list)
    for (code, clase, k), e in sorted(acc.items()):
        pts = sorted(set(e["pts"]))
        mx = sum(p[0] for p in pts) / len(pts)
        my = sum(p[1] for p in pts) / len(pts)
        lat0 = my / SCALE
        kx, ky = 111.32 * math.cos(math.radians(lat0)) / SCALE, 110.57 / SCALE
        # El punto del cauce más cercano al centro: siempre sobre el agua, aunque el río haga una curva.
        rx, ry = min(pts, key=lambda p: ((p[0] - mx) * kx) ** 2 + ((p[1] - my) * ky) ** 2)
        radius = max(math.hypot((p[0] - rx) * kx, (p[1] - ry) * ky) for p in pts)
        radius = round(max(radius, MIN_RADIUS_KM[clase]), 1)
        # La cuenca: la de la mayoría de los puntos (hasta 40, repartidos a lo largo del tramo).
        sample = pts[:: max(1, len(pts) // 40)]
        votes = Counter((basins.at(p[1] / SCALE, p[0] / SCALE) or {}).get("code", "") for p in sample)
        basin, n = votes.most_common(1)[0]
        share = round(n / len(sample), 2) if basin else 0
        name = e["names"].most_common(1)[0][0]
        alias[code] += [[len(out[code]), a] for a in e["alias"] if water_key(a) != k]
        out[code].append([name, clase, rx, ry, radius, round(e["len"], 1), basin, share])
    return dict(sorted(out.items())), {k: v for k, v in sorted(alias.items()) if v}


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
    acc, stats = collect(src)
    districts, alias = summarize(acc)
    data = {"source": {k: SOURCE.format(LAYER_NAMES[k]) for k in LAYERS}, "scale": SCALE, "fields": FIELDS,
            "districts": districts, "alias": alias, "stats": dict(sorted(stats.items()))}
    OUT.write_bytes(gzip.compress(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode(), 9, mtime=0))
    n = sum(len(v) for v in districts.values())
    by_class = Counter(row[1] for rows in districts.values() for row in rows)
    print(f"{OUT}: {n} nombres en {len(districts)} distritos ({dict(by_class)}), {OUT.stat().st_size // 1024} KB")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
