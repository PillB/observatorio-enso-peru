"""Escenario de riesgo por distrito del CENEPRED (``tools.build_escenario_distritos``): el lector de Excel y las
reglas con libros de juguete, y el archivo publicado entero contra el catálogo de distritos."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from enso import cenepred_escenario as E
from enso.feeds import FormatChanged
from tools import build_escenario_distritos as T

ROOT = Path(__file__).resolve().parents[2]
PUB = ROOT / "public" / "assets"


def _xlsx(sheets: dict[str, list[list]]) -> bytes:
    """Un .xlsx mínimo: textos compartidos, un texto en línea y números, como los escribe Excel."""
    shared: list[str] = []

    def cell(ref: str, v) -> str:
        if v is None:
            return ""
        if isinstance(v, str) and v.startswith("inline:"):
            return f'<c r="{ref}" t="inlineStr"><is><t>{v[7:]}</t></is></c>'
        if isinstance(v, str):
            if v not in shared:
                shared.append(v)
            return f'<c r="{ref}" t="s"><v>{shared.index(v)}</v></c>'
        return f'<c r="{ref}"><v>{v}</v></c>'

    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        names = list(sheets)
        for n, name in enumerate(names, 1):
            rows = "".join(f'<row r="{i}">' + "".join(cell(f"{chr(65 + j)}{i}", v) for j, v in enumerate(r)) + "</row>"
                           for i, r in enumerate(sheets[name], 1))
            z.writestr(f"xl/worksheets/sheet{n}.xml", f"<worksheet {ns}><sheetData>{rows}</sheetData></worksheet>")
        z.writestr("xl/workbook.xml", f"<workbook {ns} {rel}><sheets>" + "".join(
            f'<sheet name="{name}" sheetId="{n}" r:id="rId{n}"/>' for n, name in enumerate(names, 1)) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(
                       f'<Relationship Id="rId{n}" Target="worksheets/sheet{n}.xml"/>' for n in range(1, len(names) + 1))
                   + "</Relationships>")
        z.writestr("xl/sharedStrings.xml", f"<sst {ns}>" + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>")
    return buf.getvalue()


MM = [["UBIGEO", "NOMBDIST", "nriesg_mm", "pob_smm", "viv_smm", "eess_smm", "iiee_smm", "vias_smm"],
      ["010101", "A", "Muy Alto", 120, 40, 1, 2, 3.14159],
      ["inline:150101", "B", "Bajo", None, None, 0, 0, 0],
      [None, None, None, None, None, None, None, None]]
INU = [["UBIGEO", "NOMBDIST", "pob_sinu", "nriesg_inu", "viv_sinu", "eess_sinu", "iiee_sinu", "vias_sinu"],
       ["010101", "A", 5, "Medio", 2, 0, 0, 0],
       [200101, "C", 9, "muy alto", 3, 1, 1, 12]]


def _zip(mm=MM, inu=INU) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Tablas/Dist_Riesgo_MMasa.xlsx", _xlsx({"BD_ERMMasa": mm, "Diccionario de datos": [["Campo"]]}))
        z.writestr("Tablas/Dist_Riesgo_Inundacion.xlsx", _xlsx({"BD_ERInund": inu}))
        z.writestr("Tablas/leeme.txt", "x")
    return buf.getvalue()


def test_reads_sheets_by_name_with_shared_inline_and_numeric_cells():
    book = E.sheets(_xlsx({"BD_ERMMasa": MM}))
    assert book["BD_ERMMasa"][0][:3] == ["UBIGEO", "NOMBDIST", "nriesg_mm"]
    assert book["BD_ERMMasa"][1][3] == 120 and isinstance(book["BD_ERMMasa"][1][3], int)
    assert book["BD_ERMMasa"][2][0] == "150101"
    assert book["BD_ERMMasa"][1][7] == pytest.approx(3.14159)


def test_rows_keep_the_level_and_the_exposure_as_published():
    t = E.read_tables(_zip())
    assert t["mm"] == {"010101": [0, 120, 40, 1, 2, 3.1], "150101": [3, 0, 0, 0, 0, 0]}
    # Las columnas se buscan por nombre, no por posición; un ubigeo numérico recupera su cero; «muy alto» es «Muy Alto».
    assert t["inu"] == {"010101": [2, 5, 2, 0, 0, 0], "200101": [0, 9, 3, 1, 1, 12]}


def test_a_district_missing_from_one_table_is_null_there():
    doc = E.build({"id": "7", "mes_inicio_vigencia": "2027-01-01", "mes_fin_vigencia": "2027-03-01",
                   "mes_elaboracion": "2026-10-01", "id_documento": "99"}, E.read_tables(_zip()))
    assert doc["districts"]["150101"] == [[3, 0, 0, 0, 0, 0], None]
    assert doc["districts"]["200101"][0] is None
    assert doc["scenario"] == {"id": "7", "from": "2027-01", "until": "2027-03", "prepared": "2026-10"}
    assert doc["table"].endswith("/7_tabla.zip") and doc["document"].endswith("/documento/99")
    assert doc["levels"] == E.RISK_LEVELS and list(doc["hazards"]) == ["mm", "inu"]


@pytest.mark.parametrize("bad, why", [
    ([MM[0], ["010101", "A", "Altísimo", 1, 1, 1, 1, 1]], "nivel de riesgo inesperado"),
    ([MM[0], MM[1], MM[1]], "repetido"),
    ([MM[0], ["10x", "A", "Alto", 1, 1, 1, 1, 1]], "ubigeo inesperado"),
    ([["UBIGEO", "nriesg_mm"], ["010101", "Alto"]], "cambió el formato"),
])
def test_stops_instead_of_guessing_when_the_format_changes(bad, why):
    with pytest.raises(FormatChanged, match=why):
        E.read_tables(_zip(mm=bad))


def test_stops_when_a_hazard_sheet_is_missing():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.xlsx", _xlsx({"BD_ERMMasa": MM}))
    with pytest.raises(FormatChanged, match="BD_ERInund"):
        E.read_tables(buf.getvalue())


def test_the_tool_picks_the_requested_scenario_or_todays_and_stops_on_an_unknown_one():
    sc = [{"id": "102", "mes_inicio_vigencia": "2026-11-01", "mes_fin_vigencia": "2027-01-01", "mes_elaboracion": "2026-10-01"},
          {"id": "103", "mes_inicio_vigencia": "2027-01-01", "mes_fin_vigencia": "2027-03-01", "mes_elaboracion": "2026-10-01"},
          {"id": "40", "mes_inicio_vigencia": "2022-05-01", "mes_fin_vigencia": "2022-07-01", "mes_elaboracion": "2022-05-01"}]
    from datetime import date

    assert T.pick(sc, today=date(2026, 11, 10))["id"] == "102"
    assert T.pick(sc, "103")["id"] == "103"
    with pytest.raises(SystemExit):
        T.pick(sc, "999")
    with pytest.raises(SystemExit):
        T.pick([])


def test_main_builds_offline_from_a_saved_folder(tmp_path):
    (tmp_path / "lista.json").write_text(json.dumps({"data": [
        {"id": "7", "mes_inicio_vigencia": "2027-01-01", "mes_fin_vigencia": "2027-03-01", "mes_elaboracion": "2026-10-01",
         "id_documento": "99"}]}), encoding="utf-8")
    (tmp_path / "7_tabla.zip").write_bytes(_zip())
    out = tmp_path / "out"
    with pytest.raises(SystemExit, match="no es un ZIP"):  # una página en lugar del ZIP detiene la herramienta
        (tmp_path / "bad").mkdir()
        (tmp_path / "bad" / "lista.json").write_text((tmp_path / "lista.json").read_text(), encoding="utf-8")
        (tmp_path / "bad" / "7_tabla.zip").write_bytes(b"<!doctype html><html>Iniciar sesi\xc3\xb3n</html>")
        T.main(["--tablas", str(tmp_path / "bad"), "--sin-red", "--out", str(out)])
    assert T.main(["--tablas", str(tmp_path), "--sin-red", "--out", str(out)]) == 0
    doc = json.loads((out / "escenario-distritos.json").read_text(encoding="utf-8"))
    assert len(doc["districts"]) == 3


def test_published_scenario_covers_every_district_of_the_catalogue_with_both_hazards():
    doc = json.loads((PUB / "capas/escenario-distritos.json").read_text(encoding="utf-8"))
    names = json.loads((PUB / "historico/resumen.json").read_text(encoding="utf-8"))["nombres"]["distrito"]
    assert doc["levels"] == E.RISK_LEVELS and doc["fields"] == E.FIELDS
    assert doc["url"] == E.PAGE and doc["table"].startswith("https://sigrid.cenepred.gob.pe/sigridv3/storage/")
    sc = doc["scenario"]
    assert sc["prepared"] <= sc["from"] <= sc["until"]
    assert not set(names) - set(doc["districts"]), "todos los distritos del catálogo están en el escenario"
    for code, pair in doc["districts"].items():
        assert len(code) == 6 and code.isdigit() and len(pair) == 2
        for row in pair:
            assert row is not None and row[0] in (0, 1, 2, 3) and len(row) == 6
            assert all(isinstance(v, (int, float)) and v >= 0 for v in row[1:])
    # Solo agregados por distrito: ningún nombre ni dato de personas.
    assert set(doc) == {"source", "url", "table", "document", "scenario", "generatedBy", "levels", "hazards", "fields",
                        "note", "districts"}
