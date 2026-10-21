"""Fuentes oficiales de peligros sin RSS (enso.hazardparse), sobre sus respuestas reales.

Las capturas son de GitHub Actions del 21 de octubre de 2026 (tools.scrape_ladder y
tools.probe_feeds); ver tests/fixtures/sources/index.json.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from conftest import FIX
from enso import hazardparse as H
from enso import news as N
from enso.feedparse import FeedError

NOW = datetime(2026, 10, 21, 3, 30, tzinfo=timezone.utc)


def _collect(*ids):
    feeds = [N.FEED_BY_ID[i] for i in ids]
    by_url = {f.url: f for f in feeds}

    def fetch(url):
        return 200, (FIX / by_url[url].fixture).read_bytes(), "", ""

    found, status, _ = N.collect(fetch, NOW, feeds=feeds)
    return found, {s["id"]: s for s in status}


def test_usgs_quakes_are_in_spanish_and_located_in_peru():
    found, status = _collect("usgs-sismos")
    assert status["usgs-sismos"]["ok"] and found
    for i in found:
        assert i["title"].startswith("Sismo de magnitud ") and i["link"].startswith("https://earthquake.usgs.gov/")
        assert "Ecuador" not in i["title"] and "Chile" not in i["title"]  # el recuadro incluye países vecinos
    camana = next(i for i in found if "Camaná" in i["title"])
    assert camana["departments"] == ["04"]  # la hora va como «UTC−5»: ni Lima ni «peruana» se cuelan


def test_dhn_bulletins_skip_drills_and_old_ones():
    p = H.parse_dhn((FIX / "news-dhn-tsunamis.html").read_bytes())
    assert any("simulacro" in r for r in p.repairs)
    assert not any("simulacro" in (i["title"] + i["summary"]).lower() for i in p.items)
    found, _ = _collect("dhn-tsunamis")
    assert found and len(found) < 20  # 213 boletines en la página; solo los del último mes
    assert all(i["published"] >= "2026-09-21" for i in found)
    assert all("#" in i["link"] for i in found)  # cada boletín tiene su propio enlace


def test_ptwc_messages_count_only_when_they_concern_peru():
    found, status = _collect("ptwc-wepa40", "ptwc-mensajes")
    assert status["ptwc-wepa40"]["items"] == 1 and status["ptwc-mensajes"]["items"] == 1
    assert found == []  # Panamá y Vanuatu: sin mención del Perú


def test_volcano_bulletins_skip_green_alerts_and_name_the_province():
    p = H.parse_cenvul((FIX / "news-igp-cenvul-boletines.html").read_bytes(),
                       "https://cenvul.igp.gob.pe/productos/boletines-vulcanologicos")
    assert any("alerta verde" in r for r in p.repairs)
    assert p.items and all("verde" not in i["title"] for i in p.items)
    found, _ = _collect("igp-cenvul-boletines")
    sab = next(i for i in found if "Sabancaya" in i["title"])
    assert sab["departments"] == ["04"] and "volcan" in sab["hazards"]


def test_senamhi_telegram_posts_link_to_each_message():
    found, status = _collect("senamhi-telegram")
    assert status["senamhi-telegram"]["ok"]
    assert all(i["link"].startswith("https://t.me/Senamhi_Peru/") for i in found)
    assert any("frio" in i["hazards"] for i in found if "nevadas" in i["title"])
    assert not any(i["title"].startswith(("|", "·")) for i in found)


def test_indeci_coen_titles_are_rewritten_and_human_made_events_dropped():
    found, status = _collect("indeci-coen")
    assert status["indeci-coen"]["ok"] and len(found) >= 10
    titles = [i["title"] for i in found]
    assert "Incendio forestal en el distrito de Curahuasi (Apurímac)" in titles
    assert "Lluvias intensas en la región Piura" in titles
    aviso = next(i for i in found if i["title"].startswith("Aviso meteorológico N° 429 del SENAMHI"))
    assert "Vigencia: desde el jueves 22" in aviso["summary"]
    cur = next(i for i in found if "Curahuasi" in i["title"])
    assert cur["departments"] == ["03"] and "incendio" in cur["hazards"]
    assert cur["summary"].startswith("Reporte complementario N° 14630 del COEN-INDECI, 20/10/2026 21:00 h")

    rss = ("<?xml version='1.0'?><rss version='2.0'><channel><title>x</title>"
           "<item><title>REPORTE PRELIMINAR N.º 0940 – 20/10/2026 / COEN – INDECI / 10:00 HORAS INCENDIO URBANO EN EL "
           "DISTRITO DE ATE – LIMA</title><link>https://portal.indeci.gob.pe/emergencias/a/</link>"
           "<pubDate>Tue, 20 Oct 2026 15:00:00 +0000</pubDate></item>"
           "<item><title>REPORTE PRELIMINAR N.º 0941 – 20/10/2026 / COEN – INDECI / 11:00 HORAS HUAICO EN LOS DISTRITOS "
           "DE CHOSICA Y LURIGANCHO – LIMA</title><link>https://portal.indeci.gob.pe/emergencias/b/</link>"
           "<pubDate>Tue, 20 Oct 2026 16:00:00 +0000</pubDate></item></channel></rss>").encode()
    p = H.parse(rss, "https://portal.indeci.gob.pe/emergencias/feed/", "indeci-coen")
    assert [i["title"] for i in p.items] == ["Huaico en los distritos de Chosica y Lurigancho (Lima)"]
    assert any("no naturales" in r for r in p.repairs)


def test_arcgis_warnings_from_indeci_copy_of_senamhi():
    found, status = _collect("senamhi-quebradas", "senamhi-hidrologicos")
    q = [i for i in found if i["feed"] == "senamhi-quebradas"]
    assert {i["title"].split(":")[0] for i in q} == {
        "SENAMHI · aviso de activación de quebradas por lluvias, nivel 2",
        "SENAMHI · aviso de activación de quebradas por lluvias, nivel 3"}
    n3 = next(i for i in q if "nivel 3" in i["title"])
    assert "12 distritos de Piura y Cajamarca" in n3["title"] and set(n3["departments"]) == {"20", "06"}
    assert "f=html" in n3["link"] and "FECHA%3DDATE" in n3["link"]  # la consulta en vivo, legible en el navegador
    h = [i for i in found if i["feed"] == "senamhi-hidrologicos"]
    assert h and all(i["departments"] for i in h)
    borja = next(i for i in h if "N° 1656" in i["title"])
    assert "río Marañón, estación Borja" in borja["title"] and "(nivel naranja)" in borja["title"]
    assert borja["published"].startswith("2026-10-20")


def test_arcgis_errors_and_empty_layers():
    with pytest.raises(FeedError, match="ArcGIS respondió con un error"):
        H.parse(json.dumps({"error": {"code": 400, "message": "Invalid query"}}).encode(), "https://x/MapServer/2/query", "arcgis")
    feed = N.FEED_BY_ID["senamhi-quebradas"]
    empty = json.dumps({"features": []}).encode()
    st, items, _ = N._read_feed(feed, lambda url: (200, empty, "", ""), NOW)
    assert st["ok"] and not items and not st["error"]  # sin avisos vigentes no es una falla
    assert H._ora_day("05-DIC-26").date().isoformat() == "2026-12-05"


def test_max_age_drops_old_and_undated_entries():
    feed = N.Feed("t", "T", "peru", "https://t.pe/feed", scope="hazard", max_age_days=30)
    rss = ("<?xml version='1.0'?><rss version='2.0'><channel><title>t</title>"
           "<item><title>Huaico en Chosica</title><link>https://t.pe/1</link><pubDate>Tue, 20 Oct 2026 15:00:00 +0000</pubDate></item>"
           "<item><title>Huaico en Matucana</title><link>https://t.pe/2</link><pubDate>Mon, 01 Jun 2026 15:00:00 +0000</pubDate></item>"
           "<item><title>Huaico en Surco</title><link>https://t.pe/3</link></item></channel></rss>").encode()
    st, items, _ = N._read_feed(feed, lambda url: (200, rss, "", ""), NOW)
    assert [i["title"] for i in items] == ["Huaico en Chosica"]


def test_alerts_tab_keeps_senamhi_warnings_and_drops_press_notes():
    from enso import sourcefeed
    found, _ = _collect("senamhi-telegram", "indeci-coen")
    titles = [i["title"] for i in found]
    assert any(t.startswith("Aviso del SENAMHI: del 21 al 23 de octubre, se incrementará la velocidad del viento") for t in titles)
    for i in found:
        i.setdefault("first_seen", NOW.isoformat())
    alerts = sourcefeed.alerts(found, NOW)
    tg = [a for a in alerts if a["source"] == "news-senamhi-telegram"]
    assert tg and all(a["title"].startswith(tuple(H.TG_KINDS.values())) for a in tg)  # sin notas de prensa
    rain = next(a for a in tg if "precipitaciones en la costa centro y sur" in a["title"])
    assert rain["hazards"] == ["lluvias"]  # «mochila de emergencia» es un consejo, no otro peligro
    assert all(a["archive"].split("#")[1] for a in alerts)
