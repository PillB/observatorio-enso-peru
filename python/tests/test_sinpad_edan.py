"""Cifras de daños (EDAN) y punto de las fichas del SINPAD desde la capa de emergencias del GEOSINPAD
(``fuentes.sinpad_edan``): la unión, la idempotencia y las cifras contra los totales oficiales del INDECI."""

from __future__ import annotations

import csv
import io
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest

from enso.historico import fuentes as F

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def catalog() -> list[dict]:
    with zipfile.ZipFile(ROOT / "public" / "assets" / "historico" / "eventos.zip") as z:
        return list(csv.DictReader(io.TextIOWrapper(z.open("eventos.csv"), encoding="utf-8-sig")))


def _ms(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)


def _row(**kw) -> dict:
    r = {"Origen": "sinpad", "IdFuente": "101", "Ubigeo": "200101", "Date": "2023-03-10", "PrecisionGeo": "capital-distrito",
         "PuntoFuente": "", "Latitud": -5.19, "Longitud": -80.63, "FuenteCita": "SINPAD (INDECI), emergencia 101",
         "Descripción": "Emergencia por lluvia intensa registrada en el SINPAD con el código 101.", "Afectados": 4,
         "ImpactoReportado": "si"}
    r.update(kw)
    return r


def _doc() -> dict:
    a = {"IDE_SINPAD": 101, "COD_UBIGEO": "200104", "FECHA": _ms("2023-03-11"), "SFALLE": 1, "SLESI": 0,
         "SAFECTA": 120, "SDAMNI": 15, "SAFECTAVIVI": 20, "SINHABIVIVI": 3, "SAREACULTI_AFECTA": 1.5,
         "SAREACULTI_PERDIDO": 0.25, "SCARRE_AFECTA": 70000, "NUM_POSX": -80.61, "NUM_POSY": -5.21}
    return {"features": [{"attributes": a},
                         {"attributes": {**a, "IDE_SINPAD": 202, "FECHA": _ms("2023-03-20")}},
                         {"attributes": {**a, "IDE_SINPAD": 303, "COD_UBIGEO": "140101"}}]}


def test_edan_replaces_the_figures_and_cites_the_layer():
    rows = [_row()]
    got = F.sinpad_edan(rows, _doc())
    r = rows[0]
    assert got == Counter({"unidas": 1, "con cifras de daños": 1, "punto nuevo (desde 2019)": 1})
    assert (r["Fallecidos"], r["Afectados"], r["Damnificados"], r["ViviendasAfectadas"]) == (1, 120, 15, 23)
    assert r["HectareasCultivo"] == 1.75 and r["Heridos"] == "" and "KmVias" not in r  # las vías no se toman
    assert r["FuenteCita"].endswith("; " + F.EDAN_CITE)
    assert r["Descripción"].endswith(f"{F.EDAN_NOTE}: fallecidos 1, personas afectadas 120, damnificados 15, "
                                     "viviendas afectadas o inhabitables 23, hectáreas de cultivo o cobertura natural "
                                     "1,75.")
    assert (r["Latitud"], r["Longitud"], r["PrecisionGeo"]) == (-5.21, -80.61, "coordenada-fuente")


def test_edan_is_idempotent():
    rows = [_row()]
    F.sinpad_edan(rows, _doc())
    once = dict(rows[0])
    F.sinpad_edan(rows, _doc())
    assert rows[0] == once
    assert rows[0]["FuenteCita"].count(F.EDAN_CITE) == 1 and rows[0]["Descripción"].count(F.EDAN_NOTE) == 1


def test_edan_joins_only_the_same_emergency():
    """El código SINPAD se repite entre años y regiones: la fila de la capa debe ser de la misma provincia y de la
    misma fecha (un día de diferencia por la zona horaria)."""
    rows = [_row(IdFuente="202"), _row(IdFuente="303"), _row(IdFuente="404"), _row(Origen="coen")]
    got = F.sinpad_edan(rows, _doc())
    assert got == Counter({"sin par en la capa": 3})
    assert all(r["Afectados"] == 4 and F.EDAN_NOTE not in r["Descripción"] for r in rows)


def test_edan_point_only_for_records_without_one():
    """Antes de 2019 la ficha ya trae el punto de la copia de ArcGIS; un punto ya descartado (``PuntoFuente``) no
    vuelve."""
    old = _row(Date="2018-03-11")
    doc = _doc()
    doc["features"][0]["attributes"]["FECHA"] = _ms("2018-03-11")
    dropped = _row(Date="2018-03-11", PuntoFuente="por-defecto-capital")
    own = _row(Date="2018-03-11", PrecisionGeo="coordenada-fuente", Latitud=-5.1, Longitud=-80.7)
    got = F.sinpad_edan([old, dropped, own], doc)
    assert got["punto nuevo (desde 2019)"] == 0 and got["unidas"] == 3
    assert (old["Latitud"], old["PrecisionGeo"]) == (-5.19, "capital-distrito")
    assert (own["Latitud"], own["Longitud"]) == (-5.1, -80.7)
    after = _row(PuntoFuente="por-defecto-repetido")
    F.sinpad_edan([after], _doc())
    assert after["PrecisionGeo"] == "capital-distrito"


# --- El catálogo ----------------------------------------------------------------------------------------------------

def test_catalog_edan_rows_are_consistent(catalog):
    edan = [r for r in catalog if F.EDAN_CITE in r["FuenteCita"]]
    assert len(edan) > 50_000 and {r["Origen"] for r in edan} == {"sinpad"}
    for r in catalog:
        assert (F.EDAN_NOTE in r["Descripción"]) == (F.EDAN_CITE in r["FuenteCita"]), r["Id"]
    for r in edan:
        assert r["ImpactoReportado"] == "si" and not r["KmVias"], r["Id"]
        assert r["Descripción"].count(F.EDAN_NOTE) == 1, r["Id"]
    # Desde 2019 el portal no trae cifras: la capa las da a la mayoría de las fichas con daños.
    since = [r for r in catalog if r["Origen"] == "sinpad" and r["Date"] >= "2019-01-01"]
    assert sum(r["ImpactoReportado"] == "si" for r in since) > 40_000


def test_nino_costero_2017_matches_indeci(catalog):
    """Fichas del SINPAD de enero a mayo de 2017 contra el balance oficial del INDECI del Niño Costero (agosto de
    2017, citado por El Comercio y ACI Prensa): 162 fallecidos, 500 heridos, 19 desaparecidos y unos 286 000
    damnificados. Un ±10 %: el balance es de una fecha y las fichas siguieron actualizándose."""
    tot = Counter()
    for r in catalog:
        if r["Origen"] == "sinpad" and "2017-01-01" <= r["Date"] <= "2017-05-31":
            for k in ("Fallecidos", "Heridos", "Desaparecidos", "Damnificados"):
                tot[k] += float(r[k] or 0)
    for k, official in {"Fallecidos": 162, "Heridos": 500, "Desaparecidos": 19, "Damnificados": 286_000}.items():
        assert abs(tot[k] - official) <= 0.1 * official, (k, tot[k], official)
