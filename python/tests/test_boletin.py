"""Boletín de eventos de El Niño (enso/boletin.py) con la publicación real del 10 de noviembre de 2026."""

from __future__ import annotations

import copy
import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from enso import boletin as B

FIX = Path(__file__).parent / "fixtures" / "boletin"
NOW = datetime(2026, 11, 10, 15, 31, 50, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def inputs():
    feed = json.loads((FIX / "feed-alertas-2026-11-10.json").read_text(encoding="utf-8"))
    off = json.loads((FIX / "oficial-2026-11-10.json").read_text(encoding="utf-8"))
    esc = json.loads((FIX / "escenario-distritos-2026-11-10.json").read_text(encoding="utf-8"))
    return feed, off, esc


@pytest.fixture(scope="module")
def doc(inputs):
    feed, off, esc = inputs
    return B.build(feed, off["official"], esc, NOW, None, off["freshness"])


def test_levels_are_the_institutions_and_never_invented(doc, inputs):
    feed = inputs[0]
    items = {i["id"]: i for i in feed["groups"][0]["items"]}
    for e in doc["events"]:
        src = items[e["id"]]
        assert e["rank"] == ((src.get("severity") or {}).get("rank") or 0)
        assert e["level"] == ((src.get("severity") or {}).get("label") or None)
    # Un departamento rojo tiene al menos un aviso rojo vigente o próximo que lo toca.
    by = {e["key"]: e for e in doc["events"]}
    for s in doc["segments"]:
        ranks = [by[k]["rank"] for k in s["events"]]
        assert s["rank"] == (max(ranks) if ranks else -1)


def test_only_el_nino_hazards_enter_and_the_rest_are_counted(doc):
    for e in doc["events"]:
        assert e["phase"] in ("vigente", "en-curso", "proxima", "cancelado")
        assert not {"sismo", "volcan", "incendio", "frio"} & set(e["hazards"])
    assert doc["counts"]["otrosAvisos"] >= 2  # el volcán Sabancaya y el peligro de incendios en Loreto
    assert not any("Sabancaya" in e["title"] for e in doc["events"])


def test_counts_add_up_to_25_departments(doc):
    c = doc["counts"]
    assert c["rojo"] + c["naranja"] + c["amarillo"] + c["sinNivel"] + c["verde"] == 25
    assert len(doc["segments"]) == 25
    assert [s["position"] for s in doc["segments"]] == list(range(1, 26))


def test_order_follows_the_published_rule(doc):
    segs = doc["segments"]
    key = lambda s: (-s["rank"], not s["now"], -s["eventsAtTop"], -s["eventsActive"], -s["reports"])
    assert [key(s) for s in segs] == sorted(key(s) for s in segs)
    # Tumbes y Piura, con aviso rojo, quebradas, oleaje y daños reportados, entre los tres primeros.
    top3 = [s["name"] for s in segs[:3]]
    assert "Tumbes" in top3 and "Piura" in top3


def test_enso_block_quotes_enfen_and_its_own_probabilities(doc):
    e = doc["enso"]["enfen"]
    assert e["status"] == "Alerta de El Niño Costero" and e["number"] == "19-2026"
    p = next(p for p in doc["enso"]["probabilities"] if p["region"] == "nino12")
    assert [(x["category"], x["pct"]) for x in p["summer"]] == [("calida_extraordinaria", 65), ("calida_fuerte", 30)]
    assert p["informe"] == 19 and p["page"] == 31
    assert "65 % de El Niño extraordinario" in doc["headline"][0]["text"]


def test_no_probability_without_a_valid_official_table(inputs):
    feed, off, esc = inputs
    o = copy.deepcopy(off)
    o["freshness"]["items"]["enfen-probabilities"]["state"] = "vencido"
    d = B.build(feed, o["official"], esc, NOW, None, o["freshness"])
    assert d["enso"]["probabilities"] == []
    assert "%" not in d["headline"][0]["text"]
    o["official"]["enfen"]["stale"] = True
    d = B.build(feed, o["official"], esc, NOW, None, o["freshness"])
    assert "ya debió salir" in d["headline"][0]["text"] and d["enso"]["outlook"] == []


def test_scenario_counts_match_cenepred_table(doc, inputs):
    esc = inputs[2]
    muy = sum(1 for row in esc["districts"].values() if min(r[0] for r in row if r) == 0)
    assert doc["scenario"]["muyAlto"] == muy
    assert doc["scenario"]["id"] == "102"


def test_duplicate_senamhi_aviso_relayed_by_indeci_counts_once():
    now = NOW
    base = {"kind": "pronostico", "hazards": ["lluvias"], "date": "2026-11-10T10:00:00Z",
            "valid": {"from": "2026-11-10T05:00:00Z", "until": "2026-11-12T04:59:00Z"},
            "aviso": {"num": 462, "year": 2026, "cancelled": False}}
    a = {**base, "id": "a", "institution": "INDECI", "title": "Aviso meteorológico N° 462 del SENAMHI",
         "severity": {"rank": 3, "label": "Rojo"}, "geo": {"places": [{"code": "24", "level": "departamento"}]}}
    b = {**base, "id": "b", "institution": "SENAMHI", "title": "SENAMHI: lluvias en la costa",
         "severity": {"rank": 3, "label": "Rojo"}, "geo": {"places": [{"code": "20", "level": "departamento"}]}}
    feed = {"groups": [{"id": "alertas", "items": [a, b]}]}
    d = B.build(feed, {}, None, now)
    assert len(d["events"]) == 1
    e = d["events"][0]
    assert e["institution"] == "SENAMHI" and e["alsoBy"] == ["INDECI"] and set(e["deps"]) == {"24", "20"}


def test_same_content_keeps_the_edition_and_a_change_makes_a_new_one(doc, inputs):
    feed, off, esc = inputs
    later = NOW + timedelta(minutes=30)
    same = B.build(feed, off["official"], esc, later, doc, off["freshness"])
    assert same["edition"] == doc["edition"] == 1 and same["editionAt"] == doc["editionAt"]
    assert not same["alert"] or same["changes"] == doc["changes"]
    prev = copy.deepcopy(doc)
    prev["state"]["deps"]["24"] = 1          # Tumbes estaba en amarillo
    prev["state"]["enfen"]["status"] = "Vigilancia de El Niño Costero"
    k = next(iter(prev["state"]["events"]))
    rank = prev["state"]["events"].pop(k)["rank"]
    new = B.build(feed, off["official"], esc, NOW, prev, off["freshness"])
    assert new["edition"] == 2 and new["alert"]
    rules = [c["rule"] for c in new["changes"]]
    assert "enfen-estado" in rules and "departamento-sube" in rules and "aviso-nuevo" in rules
    tumbes = next(c for c in new["changes"] if c.get("dep") == "24")
    assert tumbes["tier"] == "inmediata" and tumbes["text"].startswith("Tumbes sube de amarillo a rojo")
    assert new["changes"][0]["tier"] == "inmediata"
    assert [r["edition"] for r in new["recent"]] == [2, 1]
    assert rank >= 0


def test_minor_changes_go_to_the_digest(inputs, doc):
    feed, off, esc = inputs
    prev = copy.deepcopy(doc)
    low = next(s for s in doc["segments"] if s["rank"] == 1)
    prev["state"]["deps"][low["code"]] = -1
    for k in low["events"]:
        prev["state"]["events"].pop(k, None)
    for code, r in list(prev["state"]["deps"].items()):
        if code != low["code"]:
            prev["state"]["deps"][code] = next(s["rank"] for s in doc["segments"] if s["code"] == code)
    new = B.build(feed, off["official"], esc, NOW, prev, off["freshness"])
    mine = [c for c in new["changes"] if c.get("dep") == low["code"]]
    assert mine and all(c["tier"] == "resumen" for c in mine)


def test_cancelled_aviso_that_was_sent_is_announced():
    now = NOW
    it = {"id": "x", "institution": "SENAMHI", "kind": "pronostico", "title": "SENAMHI: lluvias, nivel 4",
          "hazards": ["lluvias"], "date": "2026-11-10T10:00:00Z", "severity": {"rank": 3, "label": "Nivel 4"},
          "valid": {"from": "2026-11-10T05:00:00Z", "until": "2026-11-12T04:59:00Z"},
          "aviso": {"num": 5, "year": 2026, "cancelled": False},
          "geo": {"places": [{"code": "24", "level": "departamento"}]}}
    feed = {"groups": [{"id": "alertas", "items": [it]}]}
    first = B.build(feed, {}, None, now)
    it2 = copy.deepcopy(it)
    it2["aviso"]["cancelled"] = True
    second = B.build({"groups": [{"id": "alertas", "items": [it2]}]}, {}, None, now, first)
    rules = {c["rule"]: c for c in second["changes"]}
    assert rules["aviso-cancelado"]["tier"] == "inmediata"
    assert rules["departamento-baja"]["tier"] == "resumen"
    assert second["counts"]["verde"] == 25


def test_upcoming_aviso_is_shown_as_expected_not_current():
    it = {"id": "p", "institution": "SENAMHI", "kind": "pronostico", "title": "SENAMHI · aviso de precipitaciones, nivel 3: Piura",
          "hazards": [], "date": "2026-11-10T10:00:00Z", "severity": {"rank": 2, "label": "Nivel 3"},
          "valid": {"from": "2026-11-11T05:00:00Z", "until": "2026-11-12T04:59:00Z"},
          "geo": {"places": [{"code": "20", "level": "departamento"}]}}
    d = B.build({"groups": [{"id": "alertas", "items": [it]}]}, {}, None, NOW)
    piura = d["segments"][0]
    assert piura["name"] == "Piura" and piura["rank"] == 2 and piura["now"] is False
    assert piura["since"] == "2026-11-11T05:00:00Z"
    assert piura["hazards"] == ["lluvias intensas"]  # del título: «precipitaciones»
    assert d["counts"]["avisosProximos"] == 1
    assert "desde mié 11 nov, 00:00" in next(h for h in d["headline"] if h["id"] == "avisos")["text"]


def test_empty_feed_is_all_green_and_says_it_is_not_safety():
    d = B.build(None, None, None, NOW)
    assert d["counts"]["verde"] == 25 and d["edition"] == 1
    assert "no quiere decir que no haya peligro" in d["headline"][0]["text"].lower()


def test_email_is_self_contained_and_escapes_text(doc):
    h = doc["email"]["html"]
    assert "<script" not in h.lower() and "<svg" not in h.lower() and "<img" not in h.lower()
    assert h.count('role="img"') == 1  # el mosaico
    assert all(f">{a}<" in h for a in B.ABBR.values())
    assert "<!--cambios-->" in h and "#/boletin" in h and "wa.me/?text=" in h
    evil = copy.deepcopy(doc)
    evil["headline"][0]["text"] = '<img src=x onerror=alert(1)>'
    assert "<img src=x" not in B.email_html(evil, "https://x/")
    assert doc["email"]["subject"].startswith("Boletín El Niño N° 1: ")
    assert "Tumbes" in doc["email"]["text"] and "#/boletin" in doc["whatsapp"]
    assert len(doc["whatsapp"]) < 1000


def test_tile_map_has_every_department_once():
    assert sorted(B.TILES) == sorted(B.DEP_NAMES)
    assert len(set(B.TILES.values())) == 25


def test_csv_files_are_safe_for_spreadsheets(doc):
    rows = list(csv.DictReader(io.StringIO(B.csv_segments(doc))))
    assert len(rows) == 25 and rows[0]["posicion"] == "1"
    ev = list(csv.DictReader(io.StringIO(B.csv_events(doc))))
    assert len(ev) == len(doc["events"])
    assert not any(re.match(r"^[=+\-@]", r["titulo"]) for r in ev)


def test_rules_listed_in_the_bulletin_cover_every_rule_the_code_emits():
    src = Path(B.__file__).read_text(encoding="utf-8")
    emitted = set(re.findall(r'"rule": "([a-z-]+)"', src)) - {"inicial", "resumen", "duplicado"}
    listed = {r["rule"] for r in B.RULES}
    tier_digest = {"enfen-comunicado", "noaa-estado", "escenario-nuevo", "departamento-baja"}
    assert emitted - listed <= tier_digest  # las de resumen van juntas en la fila «resumen»


def test_pipeline_publishes_the_bulletin(tmp_path):
    from enso import observatory

    out = tmp_path / "data"
    observatory.run(out, None, fixtures=Path(__file__).parent / "fixtures" / "sources")
    b = json.loads((out / "boletin.json").read_text(encoding="utf-8"))
    dash = json.loads((out / "dashboard.json").read_text(encoding="utf-8"))
    assert b["publicationId"] == dash["publicationId"] and b["schema"] == B.SCHEMA
    assert (out / "boletin-correo.html").read_text(encoding="utf-8").startswith("<!doctype html>")
    assert (out / "csv" / "boletin-departamentos.csv").exists() and (out / "csv" / "boletin-avisos.csv").exists()
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert "boletin.json" in man["files"] and "boletin-correo.html" in man["files"]
