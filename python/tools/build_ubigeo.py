"""Construye ``enso/data/ubigeo.json``: departamentos, provincias y distritos del Perú.

Fuente: códigos UBIGEO del INEI con nombres, capitales y coordenadas,
compilados por Jesús M. Castagnetto (licencia MIT,
https://github.com/jmcastagnetto/ubigeo-peru-aumentado, DOI 10.5281/zenodo.4589185).

Uso:
    python -m tools.build_ubigeo [--src DIR]   # DIR con los tres CSV ya descargados
"""

from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path

import httpx

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


def display(name: str, capital: str) -> str:
    """Usa la capital (que trae tildes) cuando coincide con el nombre."""
    return capital if capital and _norm(capital) == _norm(name) else title(name)


def _fill_codes(rows: list[dict], provs: list[dict]) -> None:
    """Distritos recientes sin código INEI en la fuente ("NA"): provincia por nombre y siguiente número libre."""
    prov_code = {(r["departamento"], r["provincia"]): r["inei"][:4] for r in provs}
    used = {r["inei"] for r in rows}
    for r in rows:
        if not r["inei"].isdigit():
            p4 = prov_code[(r["departamento"], r["provincia"])]
            n = 1 + max(int(c[4:]) for c in used if c.startswith(p4))
            r["inei"] = f"{p4}{n:02d}"
            used.add(r["inei"])
        for k in ("capital", "latitude", "longitude"):
            if r.get(k) == "NA":
                r[k] = ""


def build(src: dict[str, str]) -> dict:
    rows = {k: list(csv.DictReader(io.StringIO(v))) for k, v in src.items()}
    _fill_codes(rows["dist"], rows["prov"])
    deps = [{"ubigeo": r["inei"][:2], "name": DEP_NAMES[r["departamento"]], "capital": r["capital"],
             "iso": r["iso_3166_2"], "lat": round(float(r["latitude"]), 4), "lon": round(float(r["longitude"]), 4)}
            for r in rows["dep"]]
    provs = [{"ubigeo": r["inei"][:4], "name": display(r["provincia"], r["capital"]), "capital": r["capital"],
              "lat": round(float(r["latitude"]), 4), "lon": round(float(r["longitude"]), 4)}
             for r in rows["prov"]]
    dists = [{"ubigeo": r["inei"], "name": display(r["distrito"], r["capital"]), "capital": r["capital"],
              "lat": round(float(r["latitude"]), 4) if r["latitude"] not in ("", "NA") else None,
              "lon": round(float(r["longitude"]), 4) if r["longitude"] not in ("", "NA") else None}
             for r in rows["dist"]]
    return {"source": "INEI vía github.com/jmcastagnetto/ubigeo-peru-aumentado (MIT)",
            "departments": deps, "provinces": provs, "districts": dists}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", type=Path)
    a = ap.parse_args(argv)
    if a.src:
        src = {k: (a.src / f).read_text(encoding="utf-8") for k, f in FILES.items()}
    else:
        src = {k: httpx.get(BASE + f, timeout=60).raise_for_status().text for k, f in FILES.items()}
    data = build(src)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{OUT}: {len(data['departments'])} departamentos, {len(data['provinces'])} provincias, "
          f"{len(data['districts'])} distritos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
