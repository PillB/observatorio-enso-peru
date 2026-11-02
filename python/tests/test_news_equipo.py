"""Las notas en el esquema del equipo de prevención (news_equipo)."""

import csv
import io

from conftest import FIX
from enso import news_equipo as NE
from enso.historico import esquema as E
from enso.historico.enso import EnsoCalendar
from enso.historico.territorio import territory


def _cal():
    return EnsoCalendar.from_files(FIX / "igp-icen.txt", FIX / "cpc-oni.txt")


def _item(**kw):
    base = {"id": "abc123", "first_seen": "2026-02-03T10:00:00+00:00", "published": "2026-02-03T09:00:00+00:00",
            "feed": "andina", "outlet": "Andina", "relevance": "impacto", "hazards": ["huaico"],
            "title": "Huaico en Chosica", "summary": "Un huaico bajó por la quebrada.", "link": "https://example.pe/n1",
            "geo": {"method": "texto", "places": [{"code": "150110", "level": "distrito", "name": "Lurigancho",
                                                    "confidence": 0.9, "method": "texto"}]}}
    return {**base, **kw}


def test_columns_start_with_the_teams_thirteen_in_order():
    assert NE.FIELDS[:13] == E.TEAM_COLUMNS


def test_a_located_hazard_note_becomes_a_row_with_the_team_columns():
    (r,) = NE.rows([_item()], territory(), _cal())
    assert r["Date"] == "2026-02-03" and r["DangerType"] == "Huayco/Alud"
    assert r["Ubigeo"] == "150110" and r["Distrito"] and r["Provincia"] and r["Departamento"] == "Lima"
    assert r["Fuente"] == "https://example.pe/n1" and r["Latitud"] and r["Longitud"]
    assert r["FechaTipo"] == "publicacion" and r["DuraciónEvento"] in ("", None)  # una nota no da la duración


def test_notes_without_a_climate_hazard_or_a_place_have_no_row():
    t, c = territory(), _cal()
    assert not NE.rows([_item(hazards=["sismo"])], t, c)
    assert not NE.rows([_item(hazards=["emergencia"])], t, c)
    assert not NE.rows([_item(geo={"places": []})], t, c)
    assert not NE.rows([_item(feed="firms", hazards=["incendio"])], t, c)


def test_one_row_per_place_and_duplicate_codes_are_dropped():
    places = [{"code": c, "level": "departamento", "name": c, "confidence": 0.9, "method": "campo"} for c in ("24", "20", "24")]
    rows = NE.rows([_item(geo={"method": "campo", "places": places})], territory(), _cal())
    assert [r["Ubigeo"] for r in rows] == ["24", "20"]
    assert {r["NivelUbigeo"] for r in rows} == {"departamento"}


def test_csv_is_safe_for_spreadsheets_and_keeps_ubigeo_as_text():
    out = NE.to_csv([_item(title="=HYPERLINK(1)", summary="")], territory(), _cal())
    assert out.startswith("﻿")
    (r,) = list(csv.DictReader(io.StringIO(out.lstrip("﻿"))))
    assert r["Descripción"].startswith("'=") and r["Ubigeo"] == "150110"
