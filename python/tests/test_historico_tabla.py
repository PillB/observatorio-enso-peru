"""La tabla de registros de la Memoria (``public/assets/js/historico-tabla.js``): sus funciones (``node --test``) y que
el CSV del filtro, armado en el navegador con eventos.json, coordenadas.json y detalle/, diga lo mismo que eventos.csv
en cada fila y cada columna."""

import csv
import io
import json
import subprocess
import zipfile

import pytest

from test_geo_console import JS, ROOT, _need_node
from tools import build_historico as B

HIST = ROOT / "public" / "assets" / "historico"


def test_table_functions_with_node():
    r = subprocess.run([_need_node(), "--test", str(JS / "historico-tabla.test.mjs")], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.fixture(scope="module")
def catalogue() -> list[dict]:
    with zipfile.ZipFile(HIST / "eventos.zip") as z:
        return list(csv.DictReader(io.TextIOWrapper(z.open("eventos.csv"), encoding="utf-8-sig")))


def test_browser_csv_matches_the_catalogue(tmp_path, catalogue):
    out = tmp_path / "tabla.csv"
    r = subprocess.run([_need_node(), str(JS / "historico-tabla-csv.mjs"), str(HIST), str(out)], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    raw = out.read_bytes()
    assert raw.startswith("﻿".encode())
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    assert len(rows) == len(catalogue)
    cols = list(rows[0])
    assert cols[:13] == list(B.E.TEAM_COLUMNS)
    assert set(cols) <= set(B.E.COLUMNS)
    # El mismo orden relativo que el catálogo, para que las dos descargas se lean igual.
    assert cols == [c for c in B.E.COLUMNS if c in cols]
    # Una cifra con decimales en cero (4.0 hectáreas) llega al navegador como número y se escribe 4: es el mismo valor.
    same = lambda c, a, b: a == b or (c in B.E.IMPACT_COLUMNS and a != "" and b != "" and float(a) == float(b))
    bad = {}
    for i, (mine, ref) in enumerate(zip(rows, catalogue)):
        for c in cols:
            if not same(c, mine[c], ref[c]):
                bad.setdefault(c, (i, mine[c], ref[c]))
    assert not bad, bad


def test_coordinates_follow_the_catalogue(catalogue):
    C = json.loads((HIST / "coordenadas.json").read_text(encoding="utf-8"))
    assert C == {"generatedAt": C["generatedAt"], **B.coords_payload(catalogue)}
    ev = json.loads((HIST / "eventos.json").read_text(encoding="utf-8"))
    assert C["generatedAt"] == ev["generatedAt"]


def test_coords_payload_with_toy_records():
    recs = [
        {"Ubigeo": "150110", "Latitud": "-11.9", "Longitud": "-77.05", "PrecisionGeo": "capital-distrito"},
        {"Ubigeo": "150110", "Latitud": -11.95123, "Longitud": -77.06789, "PrecisionGeo": "coordenada-fuente"},
        {"Ubigeo": "200101", "Latitud": "-5.2", "Longitud": "-80.6", "PrecisionGeo": "interior-distrito"},
        {"Ubigeo": "20", "Latitud": "", "Longitud": "", "PrecisionGeo": ""},
    ]
    assert B.coords_payload(recs) == {
        "areas": {"150110": ["-11.9", "-77.05"], "200101": ["-5.2", "-80.6", 1]},
        "puntos": {"1": ["-11.95123", "-77.06789"]},
    }


def test_table_is_the_last_section_of_the_memoria():
    js = (ROOT / "public/assets/js/historico.js").read_text(encoding="utf-8")
    assert js.index("${methodSection(D)}") < js.index("${tableSection(D, s)}") < js.index("`;", js.index("${tableSection(D, s)}"))
    assert "fillTable(root, D, s)" in js
