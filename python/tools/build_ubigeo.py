"""Construye ``enso/data/ubigeo.json``: departamentos, provincias y distritos del Perú.

Fuente: códigos UBIGEO del INEI con nombres, capitales y coordenadas,
compilados por Jesús M. Castagnetto (licencia MIT,
https://github.com/jmcastagnetto/ubigeo-peru-aumentado, DOI 10.5281/zenodo.4589185).

Se contrasta con los límites vigentes del INDECI (``enso/data/limites-ign.json.gz``, ver
``tools.build_limites``): una fila de la fuente que no es un distrito se quita (``NOT_DISTRICTS``), un distrito
vigente que la fuente aún no trae se agrega con su ley de creación (``NEW_DISTRICTS``), y un distrito sin
coordenadas de su capital en la fuente recibe un punto interior de su polígono, marcado ``"point": "interior"``
(no es la capital: es un punto dentro del distrito, lejos de sus bordes).

Uso:
    python -m tools.build_ubigeo [--src DIR]   # DIR con los tres CSV ya descargados
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
from pathlib import Path

import httpx

from enso.fetch import UA
from enso.reach import Robots, get_checked

BASE = "https://raw.githubusercontent.com/jmcastagnetto/ubigeo-peru-aumentado/main/"
FILES = {"dep": "ubigeo_departamento.csv", "prov": "ubigeo_provincia.csv", "dist": "ubigeo_distrito.csv"}
OUT = Path(__file__).resolve().parents[1] / "enso" / "data" / "ubigeo.json"

# Nombres oficiales con tildes (el CSV los trae en mayúsculas sin tildes).
DEP_NAMES = {
    "AMAZONAS": "Amazonas", "ANCASH": "Áncash", "APURIMAC": "Apurímac", "AREQUIPA": "Arequipa",
    "AYACUCHO": "Ayacucho", "CAJAMARCA": "Cajamarca", "CALLAO": "Callao", "CUSCO": "Cusco",
    "HUANCAVELICA": "Huancavelica", "HUANUCO": "Huánuco", "ICA": "Ica", "JUNIN": "Junín",
    "LA LIBERTAD": "La Libertad", "LAMBAYEQUE": "Lambayeque", "LIMA": "Lima", "LORETO": "Loreto",
    "MADRE DE DIOS": "Madre de Dios", "MOQUEGUA": "Moquegua", "PASCO": "Pasco", "PIURA": "Piura",
    "PUNO": "Puno", "SAN MARTIN": "San Martín", "TACNA": "Tacna", "TUMBES": "Tumbes", "UCAYALI": "Ucayali",
}

SMALL = {"de", "del", "la", "las", "los", "el", "y", "en"}


def title(name: str) -> str:
    words = name.lower().split()
    return " ".join(w if (i and w in SMALL) else w[:1].upper() + w[1:] for i, w in enumerate(words))


def _norm(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


#: Palabras que ninguna capital trae con tilde (apellidos de próceres, ríos).
ACCENT_SUPPLEMENT = {
    "convencion": "convención", "sanchez": "sánchez", "carrion": "carrión", "roman": "román", "purus": "purús",
    "maranon": "marañón", "boqueron": "boquerón", "pierola": "piérola", "valcarcel": "valcárcel", "galvez": "gálvez", "belaunde": "belaúnde",
    "huanuco": "huánuco", "junin": "junín", "rimac": "rímac", "apurimac": "apurímac", "peru": "perú", "simon": "simón",
    "bolivar": "bolívar", "mendez": "méndez", "ramirez": "ramírez", "perez": "pérez", "gonzalez": "gonzález",
    "lopez": "lópez", "jimenez": "jiménez", "fernandez": "fernández", "rodriguez": "rodríguez", "martinez": "martínez",
}


def accent_map(capitals: list[str]) -> dict[str, str]:
    """Forma con tildes de cada palabra, tomada de las capitales (que la fuente sí trae con tildes):
    «MORROPON» → «Morropón», «HUAROCHIRI» → «Huarochirí», «MARTIN» → «Martín»."""
    from collections import Counter

    forms: dict[str, Counter] = {}
    for cap in capitals:
        for w in re.findall(r"[^\W\d_]+", cap or ""):
            forms.setdefault(_norm(w), Counter())[w.lower()] += 1
    out = {}
    for k, c in forms.items():
        accented = [(n, f) for f, n in c.items() if _norm(f) == k and f != k]
        plain = c.get(k, 0)
        if accented:
            n, f = max(accented)
            if n >= plain:
                out[k] = f
    for k, f in ACCENT_SUPPLEMENT.items():
        out.setdefault(k, f)
    return out


def display(name: str, capital: str, accents: dict[str, str] | None = None) -> str:
    """Usa la capital (que trae tildes) cuando coincide con el nombre; si no, pone las tildes palabra por palabra."""
    if capital and _norm(capital) == _norm(name):
        return capital
    out = title(name)
    if accents:
        out = re.sub(r"[^\W\d_]+", lambda m: _keep_case(m.group(0), accents.get(_norm(m.group(0)))), out)
    return out


def _keep_case(word: str, accented: str | None) -> str:
    if not accented:
        return word
    return accented[:1].upper() + accented[1:] if word[:1].isupper() else accented


#: Filas con el código antiguo de un distrito que pasó a otra provincia: Putumayo y Teniente Manuel Clavero
#: eran de Maynas hasta que en 2014 se creó la provincia de Putumayo (160801 y 160803 en la misma fuente).
LEGACY = {"160109", "160114"}


def _fill_codes(rows: list[dict], provs: list[dict]) -> None:
    """Distritos recientes sin código INEI en la fuente ("NA"): provincia por nombre y siguiente número libre.

    Esos códigos no son oficiales: se marcan con ``provisional`` para que nadie los tome por un UBIGEO del INEI."""
    rows[:] = [r for r in rows if r["inei"] not in LEGACY]
    prov_code = {(r["departamento"], r["provincia"]): r["inei"][:4] for r in provs}
    used = {r["inei"] for r in rows}
    for r in rows:
        if not r["inei"].isdigit():
            p4 = prov_code[(r["departamento"], r["provincia"])]
            n = 1 + max(int(c[4:]) for c in used if c.startswith(p4))
            r["inei"] = f"{p4}{n:02d}"
            r["provisional"] = True
            used.add(r["inei"])
        for k in ("capital", "latitude", "longitude"):
            if r.get(k) == "NA":
                r[k] = ""


#: Filas de la fuente que no son distritos.
NOT_DISTRICTS = {
    # Centro poblado del distrito de Lurigancho; la Ley N° 30888 (2018) solo declaró de interés nacional crear el
    # distrito. Ni el INDECI ni el RENIEC tienen ese código.
    "150144": "Santa María de Huachipa",
}
#: Distritos vigentes que la fuente aún no trae, con el código del INDECI (GEOSINPAD) y su ley de creación.
NEW_DISTRICTS = [
    {"ubigeo": "130112", "name": "Alto Trujillo", "capital": "Alto Trujillo", "law": "Ley N° 31644 (2022)"},
]


def _limits() -> dict:
    import gzip

    path = Path(__file__).resolve().parents[1] / "enso" / "data" / "limites-ign.json.gz"
    return json.loads(gzip.decompress(path.read_bytes()))


def interior_point(polys: list[list[list[int]]], scale: int) -> tuple[float, float]:
    """(lat, lon) de un punto bien adentro del polígono más grande (el de mayor distancia al borde)."""
    from tools.build_peru_map import _area, interior

    rings = [[(p[0][i], p[0][i + 1]) for i in range(0, len(p[0]), 2)] for p in polys]
    x, y = interior(max(rings, key=_area), 24)
    return round(y / scale, 4), round(x / scale, 4)


def reconcile(data: dict, limits: dict) -> dict:
    """Quita lo que no es distrito, agrega los distritos nuevos y da un punto interior a los que no tienen
    coordenadas, con los límites del INDECI."""
    dists = [d for d in data["districts"] if d["ubigeo"] not in NOT_DISTRICTS]
    have = {d["ubigeo"] for d in dists}
    for n in NEW_DISTRICTS:
        if n["ubigeo"] not in have:
            dists.append({"ubigeo": n["ubigeo"], "name": n["name"], "capital": n["capital"], "lat": None, "lon": None})
    for d in dists:
        poly = limits["districts"].get(d["ubigeo"])
        if poly:
            d.pop("provisional", None)  # el INDECI tiene el distrito con ese código: ya no es provisional
        if d.get("lat") is None and poly:
            d["lat"], d["lon"] = interior_point(poly["polys"], limits["scale"])
            d["point"] = "interior"
    data["districts"] = sorted(dists, key=lambda d: d["ubigeo"])
    return data


def build(src: dict[str, str]) -> dict:
    rows = {k: list(csv.DictReader(io.StringIO(v))) for k, v in src.items()}
    _fill_codes(rows["dist"], rows["prov"])
    accents = accent_map([r["capital"] for k in ("dep", "prov", "dist") for r in rows[k]])
    deps = [{"ubigeo": r["inei"][:2], "name": DEP_NAMES[r["departamento"]], "capital": r["capital"],
             "iso": r["iso_3166_2"], "lat": round(float(r["latitude"]), 4), "lon": round(float(r["longitude"]), 4)}
            for r in rows["dep"]]
    provs = [{"ubigeo": r["inei"][:4], "name": display(r["provincia"], r["capital"], accents), "capital": r["capital"],
              "lat": round(float(r["latitude"]), 4), "lon": round(float(r["longitude"]), 4)}
             for r in rows["prov"]]
    dists = [{"ubigeo": r["inei"], "name": display(r["distrito"], r["capital"], accents), "capital": r["capital"],
              "lat": round(float(r["latitude"]), 4) if r["latitude"] not in ("", "NA") else None,
              "lon": round(float(r["longitude"]), 4) if r["longitude"] not in ("", "NA") else None,
              **({"provisional": True} if r.get("provisional") else {})}
             for r in rows["dist"]]
    return {"source": "INEI vía github.com/jmcastagnetto/ubigeo-peru-aumentado (MIT)",
            "departments": deps, "provinces": provs, "districts": dists}


def _download(client: httpx.Client) -> dict[str, str]:
    """Los tres CSV, si el robots.txt del servidor (y el de cada redirección) lo permite, como todo lo que pide
    el proyecto (barrido de robots.txt del 26 de octubre de 2026)."""
    robots = Robots(client)
    out = {}
    for k, f in FILES.items():
        url = BASE + f
        allowed = robots.allowed(url)
        r, hop, verdict = get_checked(client, url, robots) if allowed is True else (None, url, allowed)
        if hop:
            why = "no permite" if verdict is False else f"no respondió ({robots.failure(hop) or 'sin respuesta'}) y no se sabe si permite"
            raise SystemExit(f"El robots.txt de {httpx.URL(hop).host} {why} {hop}: no se pide. Bajar a mano los tres "
                             f"CSV de {BASE} y pasarlos con --src.")
        out[k] = r.raise_for_status().text
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", type=Path)
    a = ap.parse_args(argv)
    if a.src:
        src = {k: (a.src / f).read_text(encoding="utf-8") for k, f in FILES.items()}
    else:
        with httpx.Client(headers={"User-Agent": UA}, timeout=60) as client:
            src = _download(client)
    data = reconcile(build(src), _limits())
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{OUT}: {len(data['departments'])} departamentos, {len(data['provinces'])} provincias, "
          f"{len(data['districts'])} distritos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
