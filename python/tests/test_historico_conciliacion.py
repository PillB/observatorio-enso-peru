"""Conciliación de las cifras con la población y la superficie de su área (``enso.historico.conciliacion``).

Los casos son filas reales del catálogo (sus cifras de la fuente), armadas con ``registro.make``.
"""

from __future__ import annotations

import copy
import csv
import io
import json
import zipfile
from pathlib import Path

import pytest
import yaml

from conftest import FIX
from enso.historico import conciliacion as CO, desinventar
from enso.historico.enso import EnsoCalendar
from enso.historico.indicadores import summarize
from enso.historico.registro import make
from enso.historico.territorio import territory
from tools import build_historico as B

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "public" / "assets" / "historico"


@pytest.fixture(scope="module")
def cal() -> EnsoCalendar:
    return EnsoCalendar.from_files(FIX / "igp-icen.txt", FIX / "cpc-oni.txt")


@pytest.fixture(scope="module")
def T():
    return territory()


def rec(T, cal, code, day, sid, origin="desinventar", danger="Huayco/Alud", cite="El Comercio 01/01/2000", **imp):
    return make(T, cal, code=code, day=day, precision="dia", danger=danger, origin=origin, source_id=sid,
                url="https://example.org", cite=cite, license="-", description="Texto de la fuente.", impacts=imp)


def write(tmp_path, entries) -> Path:
    p = tmp_path / "conciliaciones.yaml"
    p.write_text(yaml.safe_dump({"conciliaciones": entries}, allow_unicode=True), encoding="utf-8")
    return p


def test_population_by_event_year(T):
    # Estimaciones del INEI de 1990-2005, censo 2017 y proyecciones 2018-2022; la de 1990 antes.
    assert T.population_at("210404", 1983) == T.population_at("210404", 1990)
    assert T.population_at("", 2017) > 31_000_000
    # 2017: el censo o la proyección de 2018, la mayor (el censo omitió a casi todo San Antonio de Huarochirí).
    assert T.series["150716"][2017] == 1021 and T.population_at("150716", 2017) == T.series["150716"][2018]
    # Entre 2005 y 2017, la mayor de las dos: no se sabe cuándo se fue la gente de Santiago de Quirahuara.
    s = T.series["090614"]
    assert T.population_at("090614", 2010) == max(s[2005], s[2017], s[2018])
    assert T.population_at("090614", 2026) == s[2022]
    # Una provincia suma sus distritos; antes de crearse, un distrito no suma (su gente estaba en otro).
    dists = [c for c in T.series if c.startswith("1607")]
    assert T.population_at("1607", 2020) == sum(T.population_at(c, 2020) for c in dists)
    assert T.population_at("1607", 1995) == sum(T.series[c][1995] for c in dists if 1995 in T.series[c])
    assert T.surface("15") > T.surface("1501") > T.surface("150101") > 0


def test_researched_routes_and_restore(tmp_path, T, cal):
    rows = [
        # Santa Rosa (Pallasca, 1 578 habitantes): «unos ochenta mil pobladores … quedaron aislados».
        rec(T, cal, "021510", "2008-02-20", "43412", Afectados=80000),
        # «Ola de frío en Junín» ubicada en el distrito de Junín.
        rec(T, cal, "120501", "2015-07-01", "44966", danger="Helada/Friaje", Afectados=37035, Fallecidos=24),
        # Puno 1983: el total del departamento y una de sus provincias.
        rec(T, cal, "21", "1982-12-03", "28595", danger="Sequias", Damnificados=852010),
        rec(T, cal, "2102", "1982-12-03", "28602", danger="Sequias", Damnificados=131092),
        rec(T, cal, "210503", "1982-12-03", "28592", danger="Sequias", Damnificados=852000),
        # Caleta Cruz: «200800» afectados por 200 viviendas.
        rec(T, cal, "240103", "2015-03-28", "46143", Afectados=200800, ViviendasAfectadas=200),
    ]
    path = write(tmp_path, [
        {"id": "desinventar-43412", "ruta": "cifra-de-area", "area": "02", "motivo": "m", "evidencia": "e"},
        {"id": "desinventar-44966", "ruta": "homonimo", "ubigeo": "12", "motivo": "m", "evidencia": "e"},
        {"id": "desinventar-28595", "ruta": "consolidado", "partes": ["desinventar-28602"], "motivo": "m",
         "evidencia": "e"},
        {"id": "desinventar-28592", "ruta": "duplicado", "de": "desinventar-28595", "motivo": "m", "evidencia": "e"},
        {"id": "desinventar-46143", "ruta": "transcripcion", "cifras": {"Afectados": 800}, "motivo": "m",
         "evidencia": "e"},
    ])
    source = copy.deepcopy(rows)
    stats = CO.apply(rows, T, path)
    assert stats == {"cifra-de-area": 1, "homonimo": 1, "consolidado": 1, "duplicado": 1, "transcripcion": 1}
    by = {r["Id"]: r for r in rows}
    santa = by["desinventar-43412"]
    assert santa["AreaCifras"] == "02" and santa["Afectados"] == 80000 and "Conciliación del observatorio" in \
        santa["Descripción"]
    junin = by["desinventar-44966"]
    assert junin["Ubigeo"] == "12" and junin["NivelUbigeo"] == "departamento" and junin["Distrito"] == ""
    # El punto pasa a la capital del departamento (Huancayo), no se queda en el distrito homónimo.
    assert junin["CifrasFuente"] == "Ubigeo=120501" and junin["PrecisionGeo"] == "capital-departamento"
    assert (junin["Latitud"], junin["Longitud"]) == T.point("12")[:2] != T.point("120501")[:2]
    assert by["desinventar-28595"]["Damnificados"] == 852010 - 131092
    assert by["desinventar-28592"]["Damnificados"] == "" and \
        by["desinventar-28592"]["CifrasFuente"] == "Damnificados=852000"
    assert by["desinventar-46143"]["Afectados"] == 800
    assert CO.inconsistent(rows, T) == []
    # Se deshace todo (también el UBIGEO) y se vuelve a hacer igual.
    done = copy.deepcopy(rows)
    assert CO.restore(rows, T) == 5
    keep = ("Latitud", "Longitud", "PrecisionGeo", "PuntoFuente", "Confianza")
    for r, s in zip(rows, source):
        assert {k: str(v or "") for k, v in r.items() if k not in keep} == \
            {k: str(v or "") for k, v in s.items() if k not in keep}, r["Id"]
    CO.apply(rows, T, path)
    assert [{k: str(v) for k, v in r.items()} for r in rows] == [{k: str(v) for k, v in r.items()} for r in done]


def test_researched_entries_are_checked(tmp_path, T, cal):
    rows = [rec(T, cal, "021510", "2008-02-20", "43412", Afectados=80000)]
    with pytest.raises(SystemExit, match="no contiene"):
        CO.apply(rows, T, write(tmp_path, [{"id": "desinventar-43412", "ruta": "cifra-de-area", "area": "15"}]))
    with pytest.raises(SystemExit, match="sin fila"):
        CO.apply(rows, T, write(tmp_path, [{"id": "desinventar-1", "ruta": "transcripcion", "cifras": {}}]))
    with pytest.raises(SystemExit, match="ruta desconocida"):
        CO.apply(rows, T, write(tmp_path, [{"id": "desinventar-43412", "ruta": "omitir"}]))
    with pytest.raises(SystemExit, match="no son de daños"):
        CO.apply(rows, T, write(tmp_path, [{"id": "desinventar-43412", "ruta": "transcripcion",
                                            "cifras": {"Ubigeo": "15"}}]))
    # Un tope investigado debe pasar la población: si no, la conciliación sobra.
    with pytest.raises(SystemExit, match="no pasa la población"):
        CO.cap([rec(T, cal, "021510", "2008-02-20", "1", Afectados=10)], T,
               write(tmp_path, [{"id": "desinventar-1", "ruta": "tope-poblacion"}]), auto=False)


def test_population_cap(T, cal):
    # Santiago de Quirahuara 2025 (SINPAD 232514): 546 afectados y 26 damnificados para 311 habitantes; las 314
    # viviendas caben en los 822 que tuvo en 2005 (las casas se quedan cuando la gente se va).
    r = rec(T, cal, "090614", "2025-03-28", "232514", origin="sinpad", danger="Lluvias intensas", Afectados=546,
            Damnificados=26, Desplazados=56, ViviendasDestruidas=2, ViviendasAfectadas=312)
    assert CO.inconsistent([r], T) == [r["Id"]]
    assert CO.cap([r], T) == 1
    assert r["Afectados"] + r["Damnificados"] == T.population_at("090614", 2025)
    assert r["CifrasFuente"] == "Afectados=546" and r["Conciliacion"] == "tope-poblacion"
    assert CO.inconsistent([r], T) == []
    # Los damnificados solos pasan la población: se quedan en ella y los afectados en 0.
    big = rec(T, cal, "021510", "2008-02-20", "9", Afectados=500, Damnificados=5000, Evacuados=5000)
    CO.cap([big], T)
    pop = T.population_at("021510", 2008)
    assert (big["Damnificados"], big["Afectados"], big["Evacuados"]) == (pop, 0, pop)


def test_identical_figures_count_once(T, cal):
    # Colán, 20 de febrero de 2017: dos fichas del SINPAD con la misma evaluación.
    imp = dict(Afectados=2147, Damnificados=953, ViviendasDestruidas=2, ViviendasAfectadas=523)
    a = rec(T, cal, "200504", "2017-02-20", "00082062", origin="sinpad", danger="Lluvias intensas", **imp)
    b = rec(T, cal, "200504", "2017-02-20", "00083459", origin="sinpad", danger="Lluvias intensas", **imp)
    # Dos familias de Huaraz con una vivienda y 8 personas cada una: puede ser casualidad.
    c = rec(T, cal, "020101", "2017-03-18", "00084916", origin="sinpad", danger="Lluvias intensas", Afectados=8,
            ViviendasAfectadas=1)
    d = rec(T, cal, "020101", "2017-03-18", "00084924", origin="sinpad", danger="Lluvias intensas", Afectados=8,
            ViviendasAfectadas=1)
    # DesInventar repite el total de la nota en cada lugar (Huaraz, El Comercio 18/02/2013).
    e = rec(T, cal, "020101", "2013-02-17", "45098", cite="El Comercio 18/02/2013", Afectados=400, ViviendasAfectadas=80)
    f = rec(T, cal, "020101", "2013-02-17", "45500", cite="El Comercio 18/02/2013", Afectados=400, ViviendasAfectadas=80)
    rows = [b, a, c, d, f, e]
    assert CO.duplicates(rows) == 2
    assert a["ImpactoEnTotales"] == "si" and b["ImpactoEnTotales"] == "no" and b["Afectados"] == 2147
    assert "sinpad-00082062" in b["Descripción"] and b["CifrasFuente"] == "ImpactoEnTotales=si"
    assert c["ImpactoEnTotales"] == d["ImpactoEnTotales"] == "si"
    assert e["ImpactoEnTotales"] == "si" and f["ImpactoEnTotales"] == "no"
    CO.restore(rows, T)
    assert all(r["ImpactoEnTotales"] == "si" and not r["Conciliacion"] for r in rows)


def test_same_day_overlap(T, cal):
    # Cocas, 15 de marzo de 2017: la ficha del distrito (704 + 142) y la de algunas de sus localidades (108 + 42).
    big = rec(T, cal, "090406", "2017-03-15", "00085243", origin="sinpad", danger="Lluvias intensas", Afectados=704,
              Damnificados=142)
    part = rec(T, cal, "090406", "2017-03-15", "00084581", origin="sinpad", danger="Lluvias intensas", Afectados=108,
               Damnificados=42)
    rows = [part, big]
    CO.cap(rows, T)
    assert CO.inconsistent(rows, T) != []  # cada una cabe, juntas no
    assert CO.overlaps(rows, T) == 1
    assert part["ImpactoEnTotales"] == "no" and CO.inconsistent(rows, T) == []


def test_hectares_beyond_the_surface(T, cal):
    # «Valles de Lambayeque»: 36 000 ha de caña y pastos en Monsefú (4 494 ha).
    r = rec(T, cal, "140108", "1997-09-08", "35906", danger="Sequias", HectareasCultivo=36000)
    assert CO.inconsistent([r], T) == [r["Id"]]
    assert CO.surfaces([r], T) == 1
    assert r["AreaCifras"] == "1401" and T.surface("1401") * 100 >= 36000 and CO.inconsistent([r], T) == []


def test_figures_of_a_larger_area_count_there_only(T, cal):
    r = rec(T, cal, "021510", "2008-02-20", "43412", Afectados=80000, Fallecidos=2)
    r["AreaCifras"] = "02"
    years = range(2000, 2016)
    at = lambda level, k="Afectados": summarize([r], years, set(), level=level)["impactos"].get(k, 0)
    assert at(6) == at(4) == 0 and at(2) == at(None) == 80000
    assert at(6, "Fallecidos") == 2  # los fallecidos son del lugar


def test_roads_are_metres_in_desinventar():
    # «7 kms de la Carretera Marginal inundadas» (San Hilarión, 1996) tiene kmvias = 7000.
    assert desinventar._km("7000") == 7 and desinventar._km("2500") == 2.5 and desinventar._km("0") is None
    rows = [{"Origen": "desinventar", "KmVias": "50000"}, {"Origen": "sinpad", "KmVias": "3"}]
    manifest: dict = {}
    B.migrate(rows, manifest)
    B.migrate(rows, manifest)  # una sola vez
    assert rows[0]["KmVias"] == 50 and rows[1]["KmVias"] == "3"
    assert manifest["migraciones"] == ["kmvias-desinventar-metros"]


def test_every_researched_entry_has_its_reason_and_evidence():
    entries = CO.load()
    assert len(entries) >= 90
    for e in entries:
        assert str(e.get("motivo") or "").strip() and str(e.get("evidencia") or "").strip(), e["id"]
        assert e["ruta"] != "cifra-de-area" or e.get("area"), e["id"]


def test_published_catalog_is_reconciled():
    with zipfile.ZipFile(OUT / "eventos.zip") as z:
        rows = list(csv.DictReader(io.TextIOWrapper(z.open("eventos.csv"), encoding="utf-8-sig")))
    T = territory()
    assert CO.inconsistent(rows, T) == []
    done = [r for r in rows if r["Conciliacion"]]
    assert len(done) > 400
    assert all(r["Descripción"].rstrip().endswith("]") and "[Conciliación del observatorio:" in r["Descripción"]
               for r in done)
    assert all(not r["AreaCifras"] or r["Ubigeo"].startswith(r["AreaCifras"]) for r in rows)
    # Ningún kilómetro de vías de DesInventar en metros (el mayor quedó en 1 762,5 km).
    assert max(float(r["KmVias"] or 0) for r in rows) < 10_000
    with open(OUT / "conciliaciones.csv", encoding="utf-8-sig", newline="") as f:
        log = list(csv.DictReader(f))
    assert list(log[0]) == CO.LOG_COLUMNS
    assert {r["Id"] for r in log} == {r["Id"] for r in done}
    assert all(r["Motivo"] and r["Nota"] for r in log)
    assert (OUT / "conciliaciones.csv").read_bytes() == (ROOT / "data" / "historico" / "conciliaciones.csv").read_bytes()
    summary = json.loads((OUT / "resumen.json").read_text(encoding="utf-8"))
    assert sum(summary["conciliacion"].values()) == len(done) + sum(1 for r in done if ";" in r["Conciliacion"])
    ev = json.loads((OUT / "eventos.json").read_text(encoding="utf-8"))
    assert len(ev["areaCifras"]) == sum(1 for r in rows if r["AreaCifras"])
