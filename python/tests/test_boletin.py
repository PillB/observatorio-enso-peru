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
    assert piura["since"] == "2026-11-11T05:00:00+00:00"  # fechas normalizadas a ISO 8601 con zona
    assert piura["hazards"] == ["lluvias intensas"]  # del título: «precipitaciones»
    assert d["counts"]["avisosProximos"] == 1
    assert "desde mié 11 nov, 00:00" in next(h for h in d["headline"] if h["id"] == "avisos")["text"]


def test_an_expected_aviso_that_starts_makes_a_new_edition():
    it = {"id": "p", "institution": "SENAMHI", "kind": "pronostico", "title": "SENAMHI · aviso de precipitaciones, nivel 3: Piura",
          "hazards": [], "date": "2026-11-10T10:00:00Z", "severity": {"rank": 2, "label": "Nivel 3"},
          "valid": {"from": "2026-11-11T05:00:00Z", "until": "2026-11-12T04:59:00Z"},
          "geo": {"places": [{"code": "20", "level": "departamento"}]}}
    feed = {"groups": [{"id": "alertas", "items": [it]}]}
    before = B.build(feed, {}, None, NOW)
    after = B.build(feed, {}, None, NOW + timedelta(hours=16), before)
    assert after["segments"][0]["now"] is True
    assert after["edition"] == before["edition"] + 1
    (c,) = after["changes"]
    assert c["rule"] == "aviso-empieza" and c["tier"] == "inmediata" and after["alert"] is True
    assert B.build(feed, {}, None, NOW + timedelta(hours=17), after)["edition"] == after["edition"]


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
    assert (out / "boletin.xml").read_text(encoding="utf-8").startswith("<?xml")


# --- Revisión de noviembre de 2026 (docs/boletin-revision.md): prueba de estrés, correo adaptable, suscripción ------

def _item(**k):
    base = {"id": "x1", "institution": "SENAMHI", "kind": "pronostico", "title": "Lluvias", "date": "2026-11-10T15:00:00Z",
            "hazards": ["lluvias"], "severity": {"rank": 3, "label": "Nivel 4"},
            "valid": {"from": "2026-11-10T14:00:00Z", "until": "2026-11-10T20:00:00Z"},
            "geo": {"places": [{"code": "24", "level": "departamento", "name": "Tumbes", "confidence": 0.9}]},
            "url": "https://www.senamhi.gob.pe/"}
    base.update(k)
    return {"groups": [{"id": "alertas", "items": [base]}]}


@pytest.mark.parametrize("feed, official, esc, prev", [
    (None, None, None, None),
    ({"groups": None}, None, None, None),
    ({"groups": [{"id": "alertas", "items": [{"kind": None}, {"geo": {"places": [{"code": None}]}}, {"severity": {"rank": "3"}}]}]}, None, None, None),
    (_item(date="no", valid={"from": "x", "until": "2026-13-40"}), None, None, None),
    ({}, {"enfen": {"status": "Alerta"}}, None, None),
    ({}, {"enfen": {"status": "Alerta", "number": None, "issued": "2026"}}, None, None),
    ({}, None, None, {"schema": B.SCHEMA, "state": "x", "edition": "abc"}),
    ({}, None, None, {"schema": B.SCHEMA, "state": {"deps": {"24": "x"}, "events": []}, "edition": 3}),
    ({}, None, None, {"schema": B.SCHEMA, "state": {"deps": {"24": 3}}, "edition": "tres", "recent": "x"}),
    ({}, None, {"districts": {"240101": "x", "2401": [[None]], "999999": [[0]]}}, None),
    ({}, {"enfen": {"status": "A", "number": "1", "informe": {"probabilities": [{"region": "nino12", "summer": {"x": 5, "neutro": True, "calida_fuerte": 300}}]}}}, None, None),
])
def test_broken_inputs_never_take_the_bulletin_down(feed, official, esc, prev):
    """Lo que llegue roto (una fuente, el boletín anterior, el ENFEN) se descarta: nunca una excepción, que dejaría el
    sitio sin boletín (boletin-exception) y el correo sin enviar."""
    d = B.build(feed, official, esc, NOW, prev)
    assert d["edition"] >= 1 and len(d["segments"]) == 25
    assert "None" not in d["headline"][0]["text"] and "N° None" not in d["email"]["html"]
    B.csv_events(d), B.csv_segments(d), B.atom_feed(d, "https://x/")


def test_links_from_sources_are_http_only_and_dates_are_iso():
    d = B.build(_item(url="javascript:alert(1)", document="data:text/html,x"), {}, None, NOW)
    assert d["events"][0]["url"] is None
    assert "javascript:" not in json.dumps(d)
    d = B.build(_item(valid={"from": "2026-11-10 14:00:00+00:00", "until": "2026-11-10T20:00:00Z"}), {}, None, NOW)
    assert d["events"][0]["from"] == "2026-11-10T14:00:00+00:00"  # Safari no entiende la fecha con espacio


def test_csv_cells_never_start_a_formula():
    d = B.build(_item(title="=HYPERLINK(\"http://x\")", institution="+SENAMHI", geo={"places": [
        {"code": "2401", "level": "provincia", "name": "@Tumbes", "confidence": 0.9}]}), {}, None, NOW)
    for text in (B.csv_events(d), B.csv_segments(d)):
        for row in csv.reader(io.StringIO(text)):
            assert not any(re.match(r"^[=+\-@\t\r]", c) for c in row if not re.match(r"^-?\d", c)), row


def test_quick_reading_fields(doc):
    assert doc["summary"].startswith("19 departamentos en rojo") and "ENFEN" in doc["summary"]
    assert [w["id"] for w in doc["timeline"]] == ["ahora", "24h", "72h", "despues"]
    assert {g["rank"] for g in doc["guidance"]} == {3, 2, 1, -1} and doc["guidanceSource"]
    p = next(x for x in doc["enso"]["probabilities"] if x["region"] == "nino12")
    assert p["other"] == round(sum(x["pct"] for x in p["all"]) - sum(x["pct"] for x in p["summer"]), 1)
    assert doc["enso"]["enfen"]["step"] == 2 and doc["enso"]["enfen"]["phase"] == "nino"
    # «… y Tumbes y otros» era un error de redacción.
    assert not re.search(r" y [A-ZÁÉÍÓÚ][a-záéíóú]+ y otros", " ".join(h["text"] for h in doc["headline"]))
    seg = next(s for s in doc["segments"] if s["code"] == "15")
    assert set(seg["institutions"]) <= set(seg["institutionsAll"])


def test_changes_carry_their_departments_for_subscribers(inputs):
    feed, off, esc = inputs
    first = B.build(feed, off["official"], esc, NOW, None, off["freshness"])
    quiet = B.build({"groups": [{"id": "alertas", "items": []}]}, off["official"], esc, NOW, first, off["freshness"])
    assert quiet["edition"] == 2
    for c in quiet["changes"]:
        assert isinstance(c["deps"], list)
    assert any(c["deps"] for c in quiet["changes"])


def test_email_is_responsive_accessible_and_small(doc):
    h = doc["email"]["html"]
    # Gmail corta los correos de más de 102 KB.
    assert len(h.encode("utf-8")) < 90_000
    assert 'name="viewport"' in h and 'lang="es"' in h and 'name="color-scheme"' in h
    assert "<!--[if mso]>" in h  # ancho fijo para Outlook para Windows
    assert "<!--baja-->" in h and "<!--/baja-->" in h
    # Nada que los clientes de correo quiten o rompan: ni grid, ni flex, ni position, ni degradados, ni SVG.
    style = " ".join(re.findall(r'style="([^"]*)"', h))
    for bad in ("display:grid", "display:flex", "position:", "linear-gradient", "background-image"):
        assert bad not in style, bad
    # Una sola columna fluida: ninguna tabla de contenido con ancho fijo en píxeles mayor que 320.
    no_mso = re.sub(r"<!--\[if mso\]>.*?<!\[endif\]-->", "", h, flags=re.S)
    assert not [w for w in re.findall(r'width="(\d+)"', no_mso) if int(w) > 320]
    assert "max-width:600px" in h
    # El preencabezado no deja asomar el resto del correo.
    assert "&#847;&zwnj;&nbsp;" in h
    # Contraste: el verde del correo cumple 4,5:1 con texto blanco.
    def lum(hx):
        c = [int(hx[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    for r in (3, -1):
        bg = B.LEVELS[r][2]
        assert (1.05) / (lum(bg) + 0.05) >= 4.5, bg


def test_whatsapp_says_how_many_more_and_that_it_is_not_official(doc):
    assert "y 18 departamentos más" in doc["whatsapp"] and "No es una alerta oficial" in doc["whatsapp"]


def test_atom_feed_is_valid_xml(doc):
    import xml.etree.ElementTree as ET

    root = ET.fromstring(B.atom_feed(doc, "https://enso-peru.pages.dev/"))
    ns = {"a": "http://www.w3.org/2005/Atom"}
    assert root.find("a:title", ns).text.startswith("Boletín")
    assert len(root.findall("a:entry", ns)) == len(doc["recent"])


def test_subscription_api_with_node():
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node no está instalado")
    r = subprocess.run([node, "--test", str(Path(__file__).parent / "js" / "boletin-subs.test.mjs")], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
    assert re.search(r"# fail 0", r.stdout), r.stdout[-2000:]
