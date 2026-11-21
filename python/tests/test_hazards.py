"""Fuentes oficiales de peligros sin RSS (enso.hazardparse), sobre sus respuestas reales.

Las capturas son de GitHub Actions del 21 de octubre de 2026 (tools.scrape_ladder y
tools.probe_feeds); ver tests/fixtures/sources/index.json.
"""

from __future__ import annotations

import json
import re
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
    # El epicentro, con la incertidumbre del cálculo (10 km si es automático, 5 km si lo revisó un sismólogo).
    (pt,) = camana["detail"]["points"]
    assert pt["kind"] == "epicentro" and pt["radiusKm"] in (5, 10) and isinstance(pt["mag"], (int, float))
    assert -18.6 < pt["lat"] < -15 and -74.5 < pt["lon"] < -71


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
    assert sab["detail"]["points"] == [{"name": "Volcán Sabancaya", "lat": -15.787, "lon": -71.857, "kind": "volcan",
                                        "source": "https://volcano.si.edu/volcano.cfm?vn=354006"}]


_CENVUL = {"boletines": "https://cenvul.igp.gob.pe/productos/boletines-vulcanologicos",
           "alertas": "https://cenvul.igp.gob.pe/productos/alertas-vulcanologicas"}


@pytest.mark.parametrize("page", sorted(_CENVUL))
def test_cenvul_reads_the_same_page_in_either_locale(page):
    """El CENVUL sirve, al azar, la misma página con fechas en inglés o en castellano (según la instancia de Nuxt que
    atiende; ``Accept-Language`` no influye). Las capturas ``-es`` son las variantes castellanas del mismo día que las
    inglesas (data-archive, 21-10-2026: boletines 05ad440e3d22, alertas 1f833c01d948). Antes solo se leía la inglesa:
    la castellana salía «sin entradas con fecha» y sus 10 alertas se fundían en 2 (el enlace llevaba la fecha)."""
    url = _CENVUL[page]
    en = H.parse_cenvul((FIX / f"news-igp-cenvul-{page}.html").read_bytes(), url)
    es = H.parse_cenvul((FIX / f"news-igp-cenvul-{page}-es.html").read_bytes(), url)
    assert en.items and all(i["published"] for i in en.items)
    key = lambda p: [(i["title"], i["link"], i["published"]) for i in p.items]  # noqa: E731
    assert key(es) == key(en)
    assert not any("no se pudo leer" in r for r in es.repairs + en.repairs)
    if page == "alertas":
        assert len(es.items) == 10 and es.items[0]["published"] == "2026-06-01T16:54:00Z"  # 11:54:00 a. m. de Lima


@pytest.mark.parametrize("raw, hm, want", [
    ("Monday, June 1, 2026", "11:54:00 AM", "2026-06-01T16:54:00Z"),
    ("lunes, 1 de junio de 2026", "11:54:00 a.\u00a0m.", "2026-06-01T16:54:00Z"),
    ("lunes, 1 de junio de 2026", "2:40:00 p. m.", "2026-06-01T19:40:00Z"),
    ("lunes, 1 de junio de 2026", "12:05:00 a. m.", "2026-06-01T05:05:00Z"),
    ("martes, 1 de setiembre de 2026", "", "2026-09-01T17:00:00Z"),
    ("1 de septiembre de 2026", "21:15", "2026-09-02T02:15:00Z"),
    ("lunes, 31 de junio de 2026", "", None),
    ("2026-06-01", "", None),
])
def test_cenvul_card_dates(raw, hm, want):
    assert H._card_date(raw, hm) == want


def test_cenvul_unknown_date_format_is_a_format_error():
    """Si el CENVUL cambia otra vez la forma de la fecha, el feed falla por formato (``formatError``, y la incidencia de
    fuente caída si dura) en vez de publicar tarjetas sin fecha como si respondiera bien."""
    body = (FIX / "news-igp-cenvul-alertas.html").read_bytes()
    body = re.sub(rb"(Fecha de publicaci\xc3\xb3n : </span>) [^<]+", rb"\1 2026-06-01", body)
    with pytest.raises(FeedError, match="fechas de otra forma"):
        H.parse_cenvul(body, _CENVUL["alertas"])
    one = (FIX / "news-igp-cenvul-alertas.html").read_bytes().replace(b"Monday, June 1, 2026", b"1/6/2026", 1)
    p = H.parse_cenvul(one, _CENVUL["alertas"])
    assert "1 tarjetas con una fecha que no se pudo leer" in p.repairs


@pytest.mark.parametrize("name", sorted(H.VOLCANO_POINTS))
def test_volcano_summits_lie_in_the_province_the_igp_names(name):
    """Las cumbres (catálogo del Smithsonian) caen en la provincia (o el departamento) que el sitio dice para cada
    volcán: dos fuentes independientes que coinciden."""
    from enso.geo import gazetteer
    from enso.limites import locate

    from enso.limites import limits

    lat, lon, _ = H.VOLCANO_POINTS[name]
    where = H.VOLCANOES[name]
    gz, lim = gazetteer(), limits()
    m = re.match(r"las? provincias? de (.+) \((.+)\)$|el departamento de (.+)$", where)
    want = [gz.from_admin("", p, m.group(2)) for p in m.group(1).split(" y ")] if m.group(1) else \
        [gz.from_admin("", "", m.group(3))]
    assert all(want), (name, want)
    x, y = lon * lim.scale, lat * lim.scale
    # Una cumbre suele ser un límite: dentro de una de las áreas nombradas, o a menos de 0,5 km de una.
    near = [w for w in want if lim.containing(len(w), x, y, w) == w or lim._edge(x, y, lim.levels[len(w)][w]["polys"])[0] < 0.5]
    assert near, (name, want, locate(lat, lon))


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
           "<pubDate>Tue, 20 Oct 2026 16:00:00 +0000</pubDate></item>"
           "<item><title>REPORTE PRELIMINAR N.º 0942 – 20/10/2026 / COEN – INDECI / 12:00 HORAS SIMULACRO DE SISMO EN EL "
           "DISTRITO DE ATE – LIMA</title><link>https://portal.indeci.gob.pe/emergencias/c/</link>"
           "<pubDate>Tue, 20 Oct 2026 17:00:00 +0000</pubDate></item></channel></rss>").encode()
    p = H.parse(rss, "https://portal.indeci.gob.pe/emergencias/feed/", "indeci-coen")
    assert [i["title"] for i in p.items] == ["Huaico en los distritos de Chosica y Lurigancho (Lima)"]
    assert any("no naturales" in r for r in p.repairs) and any("simulacro" in r for r in p.repairs)


def test_arcgis_warnings_from_indeci_copy_of_senamhi():
    found, status = _collect("senamhi-quebradas", "senamhi-hidrologicos")
    q = [i for i in found if i["feed"] == "senamhi-quebradas"]
    assert {i["title"].split(":")[0] for i in q} == {
        f"SENAMHI · aviso de activación de quebradas por lluvias, nivel {n}" for n in (2, 3, 4)}
    # Cada polígono de la capa es una quebrada: se cuentan por distrito (antes, 3 806 quebradas se titulaban «distritos»).
    n4 = next(i for i in q if "nivel 4" in i["title"])
    assert "80 quebradas en 10 distritos de Piura" in n4["title"] and n4["departments"] == ["20"]
    areas = n4["detail"]["areas"]
    assert len(areas) == 10 and sum(a["n"] for a in areas) == 80 and all(a["code"].startswith("20") for a in areas)
    assert areas[0] == {"code": "200201", "name": "Ayabaca", "n": 17}
    assert "f=html" in n4["link"] and "FECHA%3DDATE" in n4["link"]  # la consulta en vivo, legible en el navegador
    n3 = next(i for i in q if "nivel 3" in i["title"])
    assert sum(a["n"] for a in n3["detail"]["areas"]) == 805  # todas ubicadas (Providencia, Luya, incluida)
    assert {"code": "010515", "name": "Providencia", "n": 3} in n3["detail"]["areas"]
    h = [i for i in found if i["feed"] == "senamhi-hidrologicos"]
    assert h and all(i["departments"] for i in h)
    borja = next(i for i in h if "N° 1656" in i["title"])
    assert "río Marañón, estación Borja" in borja["title"] and "(nivel naranja)" in borja["title"]
    assert borja["published"].startswith("2026-10-20")
    assert borja["detail"]["points"] == [{"name": "Estación Borja", "lat": -4.4702, "lon": -77.5477, "kind": "estacion",
                                          "river": "río Marañón", "basin": {"code": "49877", "name": "Intercuenca 49877"}}]


def test_arcgis_ravines_without_districts_count_by_department():
    """La consulta de antes (sin NOMBDIST, captura del 21 de octubre de 2026): solo cuántas quebradas por
    departamento, sin distritos."""
    body = (FIX / "history" / "news-senamhi-quebradas-20261021030936.json").read_bytes()
    items = H.parse(body, N.FEED_BY_ID["senamhi-quebradas"].url, "arcgis").items
    n3 = next(i for i in items if "nivel 3" in i["title"])
    assert "12 quebradas de Piura y Cajamarca" in n3["title"] and "areas" not in n3


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


def test_alerts_carry_the_detail_the_map_draws():
    """Lo que el mapa de alertas dibuja más fino que un distrito: el centro poblado que nombra un reporte del COEN
    (sin el PDF, del texto del RSS), las estaciones y los distritos con quebradas."""
    from enso import sourcefeed
    from enso.lugares import inside_district

    found, _ = _collect("indeci-coen", "senamhi-hidrologicos", "senamhi-quebradas")
    by_title = {i["title"]: i for i in found}
    cabana = sourcefeed._detail(by_title["Vientos fuertes en el distrito de Cabana (Puno)"])
    (p,) = cabana["points"]
    assert (p["name"], p["kind"], p["district"], p["evidence"]) == ("Añaville", "centro-poblado", "211102",
                                                                     "centro poblado de anaville")
    assert inside_district("211102", p["lat"], p["lon"]) and p["basin"]["name"]
    cur = sourcefeed._detail(by_title["Incendio forestal en el distrito de Curahuasi (Apurímac)"])
    assert cur["points"][0]["name"] == "San Antonio de Matibamba"  # el reporte escribe «San Antonio Matibamba»
    # «centro poblado y distrito de Sitajara»: la capital no es más fina que el distrito.
    assert sourcefeed._detail(by_title["Descenso de temperatura en el distrito de Sitajara (Tacna)"]) is None
    river = next(i for i in found if i["feed"] == "senamhi-hidrologicos")
    assert sourcefeed._detail(river)["points"][0]["kind"] == "estacion"
    ravines = next(i for i in found if i["feed"] == "senamhi-quebradas")
    assert sourcefeed._detail(ravines)["areas"]


def test_dhn_swell_and_wind_warnings_read_every_title_format():
    found, status = _collect("dhn-avisos")
    assert status["dhn-avisos"]["ok"] and found
    swell = next(i for i in found if "N° 42-26" in i["title"])
    assert swell["title"].startswith("DHN · aviso especial de oleaje N° 42-26: oleaje fuerte en el litoral norte, centro y sur")
    assert "oleaje" in swell["hazards"] and {"24", "20", "23"} <= set(swell["departments"])  # Tumbes, Piura, Tacna
    assert not swell["summary"].startswith("La Marina")  # sin la fórmula de saludo
    wind = next(i for i in found if "N° 22-26" in i["title"])
    assert "brisa fuerte (hasta 24 nudos) entre Cerro Azul y Ático" in wind["title"] and "viento" in wind["hazards"]
    assert all(i["link"].startswith("https://www.dhn.mil.pe/portal/avisos-especiales#") for i in found)
    # Formatos anteriores a 2025: sin tipo en el título, que va entre corchetes, y «Nº» en vez de «NRO.»
    old = ('<a href="https://www.dhn.mil.pe/portal/avisos-especiales">x</a><section id="avisos-especiales">'
           '<div class="position-relative"><a href="https://www.dhn.mil.pe/portal/pdf-aviso-especial/118">PDF</a>'
           '<div class="accordion-title"><span class="pe-2">AVISO ESPECIAL Nº 118</span> <span>[Vientos]</span></div>'
           '<div class="accordion-content"><h4>La Marina de Guerra del Perú a través de la Dirección de Hidrografía y '
           'Navegación, informa a la opinión pública que se presentará viento fuerte (hasta 25 nudos).</h4>'
           '<div>Callao, 3 de setiembre del 2021</div></div></div></section>').encode()
    p = H.parse(old, "https://www.dhn.mil.pe/portal/avisos-especiales", "dhn-avisos")
    assert [i["title"] for i in p.items] == ["DHN · aviso especial de viento N° 118: viento fuerte (hasta 25 nudos)"]
    assert p.items[0]["published"].startswith("2021-09-03") and p.items[0]["summary"].startswith("Se presentará")


def test_alerts_group_lists_sources_that_did_not_answer():
    from enso import sourcefeed
    status = [{"id": "senamhi-telegram", "ok": False, "error": "ConnectTimeout"},
              {"id": "indeci-coen", "ok": True, "latest": "2026-10-21T03:02:00Z"},
              {"id": "andina", "ok": True}]  # no es una fuente de alertas
    feed = sourcefeed.build({}, {}, None, {}, news_items=[], now=NOW, feed_status=status)
    g = feed["groups"][0]
    assert g["id"] == "alertas" and g["items"] == []  # el grupo aparece aunque no haya avisos
    assert [(s["id"], s["ok"]) for s in g["sources"]] == [("senamhi-telegram", False), ("indeci-coen", True)]


def test_firms_hotspots_are_counted_by_department_in_peru_only():
    found, status = _collect("firms-focos")
    assert status["firms-focos"]["ok"] and len(found) == 1
    f = found[0]
    assert f["title"].startswith("NASA FIRMS · 259 focos de calor en el Perú (19 y 20 de octubre): Huánuco (47), Ucayali (38)")
    assert "incendio" in f["hazards"] and {"10", "25", "03"} <= set(f["departments"])
    assert "quema agrícola" in f["summary"]  # un foco de calor no siempre es un incendio forestal
    cells = f["detail"]["points"]
    assert sum(c["n"] for c in cells) == 259 and all(c["kind"] == "focos" for c in cells)
    assert cells == sorted(cells, key=lambda c: -c["n"])  # las celdas con más focos primero
    head = b"latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,confidence,version,bright_ti5,frp,daynight\n"
    bolivia = head + b"-16.5,-68.15,330,0.4,0.4,2026-10-20,1800,N20,nominal,2.0NRT,290,5,D\n"
    p = H.parse(bolivia, "x", "firms")
    assert p.items == [] and "sin focos de calor en el Perú" in p.repairs[-1]
    feed = N.FEED_BY_ID["firms-focos"]
    st, items, _ = N._read_feed(feed, lambda url: (200, bolivia, "", ""), NOW)
    assert st["ok"] and not st["error"] and not items  # sin focos no es una falla


def test_rain_warning_polygons_are_split_among_departments():
    """La capa SENAMHI_AvisoPP24H: pocos polígonos grandes, cada uno sobre varios departamentos."""
    found, status = _collect("senamhi-lluvias")
    assert status["senamhi-lluvias"]["ok"] and len(found) == 2  # niveles 3 y 2; el nivel 1 (verde) no es un aviso
    n3 = next(i for i in found if ", nivel 3:" in i["title"])
    assert n3["title"].startswith("SENAMHI · aviso de precipitaciones para 24 horas, nivel 3: Piura, Lima")
    assert {"20", "24", "15", "04", "08"} <= set(n3["departments"])  # Piura y Tumbes, Lima, Arequipa y Cusco
    n2 = next(i for i in found if ", nivel 2:" in i["title"])
    assert n2["title"].endswith("y 6 departamentos más") and {"16", "21", "05", "09"} <= set(n2["departments"])
    assert "NIVEL%3D%27Nivel%203%27" in n3["link"] and "f=html" in n3["link"]
    # El polígono del aviso, para dibujarlo: anillos [lon, lat] cerrados, con 2 decimales, dentro del recuadro del Perú.
    for item in (n2, n3):
        rings = [r for sh in item["detail"]["shapes"] for r in sh["rings"]]
        assert rings and sum(len(r) for r in rings) <= 4000
        for r in rings:
            assert len(r) >= 4 and r[0] == r[-1]
            assert all(-82.5 < x < -67.5 and -19.5 < y < 1.5 and round(x, 2) == x for x, y in r)
    only_green = b'{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"NIVEL":"Nivel 1","FECHA":1792540800000},' \
                 b'"geometry":{"type":"Polygon","coordinates":[[[-75,-10],[-74,-10],[-74,-9],[-75,-9],[-75,-10]]]}}]}'
    p = H.parse(only_green, N.FEED_BY_ID["senamhi-lluvias"].url, "arcgis")
    assert p.items == [] and "nivel 2 o más" in p.repairs[-1]


def test_fire_risk_polygons_are_named_by_department():
    found, status = _collect("senamhi-incendios")
    assert status["senamhi-incendios"]["ok"] and len(found) == 1
    f = found[0]
    assert f["title"].startswith("SENAMHI · peligro extremo de incendios forestales (índice FWI > 97): ")
    assert {"15", "11", "04", "23"} <= set(f["departments"])  # Lima, Ica, Arequipa, Tacna
    assert "INTENSIDAD%3D%27EXTREMO%27" in f["link"] and "f=html" in f["link"]
    assert f["detail"]["shapes"][0]["rings"]


# --- Capas de GEOSINPAD: una capa vacía no trae campos ------------------------------
# El 19-21 de noviembre de 2026 la capa del FWI (3) respondió vacía mientras las 2, 4 y 5 traían avisos: en el
# servidor (``where=1=1&returnCountOnly=true`` → 0; FECHA máxima nula) y con el mismo nombre en el listado. Vacía
# no se distingue de una capa renumerada o retirada (el GeoJSON vacío no dice qué capa es): se mira el listado.
LISTING = FIX / "geosinpad-senamhi-mapserver.json"  # MapServer?f=json del 21-11-2026
EMPTY_GEOJSON = b'{"type":"FeatureCollection","features":[]}'


def _fetch_with_listing(listing: bytes | None):
    asked = []

    def fetch(url):
        asked.append(url)
        if url.endswith("/MapServer?f=json"):
            return (200, listing, "", "") if listing is not None else (503, b"", "", "HTTP 503")
        return 200, EMPTY_GEOJSON, "", ""
    return fetch, asked


def test_geosinpad_feeds_name_the_layer_of_their_url():
    """Cada feed de GEOSINPAD apunta a la capa con el nombre que declara (listado real del servidor)."""
    names = {x["id"]: x["name"] for x in json.loads(LISTING.read_bytes())["layers"]}
    geos = [f for f in N.FEEDS if "geosinpad.indeci.gob.pe" in f.url and f.adapter == "arcgis"]
    assert {f.id for f in geos} == {"senamhi-quebradas", "senamhi-hidrologicos", "senamhi-incendios", "senamhi-lluvias"}
    for f in geos:
        lid = int(re.search(r"/MapServer/(\d+)/query", f.url).group(1))
        assert f.layer and names[lid] == f.layer, f.id
    assert N.FEED_BY_ID["senamhi-incendios"].layer == "SDE.SENAMHI_AvisoFWI24H"


def test_empty_fire_layer_is_no_warning_when_the_layer_still_matches():
    feed = N.FEED_BY_ID["senamhi-incendios"]
    fetch, asked = _fetch_with_listing(LISTING.read_bytes())
    st, items, _ = N._read_feed(feed, fetch, NOW)
    assert st["ok"] and not items and not st["error"] and st["layerCheck"] == "ok"
    assert asked == [feed.url, "https://geosinpad.indeci.gob.pe/indeci/rest/services/Ent_Tecnico_Cientificas/SENAMHI/MapServer?f=json"]


def test_empty_layer_that_was_renumbered_fails_loudly_and_names_the_new_id():
    listing = json.loads(LISTING.read_bytes())
    for x in listing["layers"]:  # el servidor intercala una capa nueva: FWI pasa de la 3 a la 6
        if x["id"] == 3:
            x["name"] = "SDE.SENAMHI_AvisoHeladas24H"
    listing["layers"].append({"id": 6, "name": "SDE.SENAMHI_AvisoFWI24H", "type": "Feature Layer"})
    fetch, _ = _fetch_with_listing(json.dumps(listing).encode())
    st, items, _ = N._read_feed(N.FEED_BY_ID["senamhi-incendios"], fetch, NOW)
    assert not st["ok"] and st["formatError"] and not items and st["layerCheck"] == "distinta"
    assert "ya no es «SDE.SENAMHI_AvisoFWI24H»" in st["error"] and "está ahora en la capa 6" in st["error"]
    from enso.observatory import hazard_down
    assert hazard_down(st)  # dos corridas así: «hazard-feed-down» (aviso, no info)
    # Retirada: ni en su número ni en otro.
    listing["layers"] = [x for x in listing["layers"] if x["id"] not in (3, 6)]
    fetch, _ = _fetch_with_listing(json.dumps(listing).encode())
    st, _, _ = N._read_feed(N.FEED_BY_ID["senamhi-incendios"], fetch, NOW)
    assert not st["ok"] and "es «inexistente»" in st["error"] and "no figura en el listado" in st["error"]


@pytest.mark.parametrize("listing", [None, b"<html>mantenimiento</html>", b'{"error":{"code":500}}'])
def test_unverifiable_layer_listing_keeps_an_empty_layer_as_no_warnings(listing):
    fetch, _ = _fetch_with_listing(listing)
    st, items, _ = N._read_feed(N.FEED_BY_ID["senamhi-incendios"], fetch, NOW)
    assert st["ok"] and not items and not st["error"] and st["layerCheck"].startswith("no verificado")


def test_layer_is_checked_only_when_empty():
    feed = N.FEED_BY_ID["senamhi-incendios"]
    asked = []

    def fetch(url):
        asked.append(url)
        return 200, (FIX / feed.fixture).read_bytes(), "", ""
    st, items, _ = N._read_feed(feed, fetch, NOW)
    assert st["ok"] and items and asked == [feed.url] and "layerCheck" not in st
    assert N._layer_listing_url("https://x.pe/arcgis/rest/services/A/FeatureServer/0/query?where=1%3D1&f=json") \
        == "https://x.pe/arcgis/rest/services/A/FeatureServer?f=json"
    assert N._layer_listing_url("https://x.pe/feed.xml") is None


def _fire_run(tmp_path, monkeypatch, listing: bytes, prev: dict):
    """Una corrida de noticias (``acquire_news``) con solo el feed del FWI, que responde vacío."""
    import httpx

    from enso import observatory as obs
    from enso.fetch import Fetcher

    feed = N.FEED_BY_ID["senamhi-incendios"]
    monkeypatch.setattr(N, "FEEDS", [feed])
    real = httpx.Client

    def serve(req):
        body = listing if str(req.url).endswith("/MapServer?f=json") else EMPTY_GEOJSON
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(**{**kw, "transport": httpx.MockTransport(serve)}))
    site = tmp_path / "site"
    (site / "news").mkdir(parents=True)
    (site / "news" / "feeds.json").write_text(json.dumps({"feeds": [{"id": feed.id, **prev}]}), encoding="utf-8")
    fetcher = Fetcher(polite_delay=0)
    log = obs.EventLog()
    now = datetime(2026, 11, 21, 2, 0, tzinfo=timezone.utc)
    got = obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), log, now, None)
    return {s["id"]: s for s in got["feeds"]["feeds"]}[feed.id], log


def test_empty_fire_layer_says_since_when_and_that_the_layer_was_checked(tmp_path, monkeypatch):
    prev = {"ok": True, "items": 0, "error": "", "checkedAt": "2026-11-20T02:00:00+00:00",
            "emptySince": "2026-11-19T02:00:00+00:00"}
    st, log = _fire_run(tmp_path, monkeypatch, LISTING.read_bytes(), prev)
    assert st["ok"] and st["emptySince"] == "2026-11-19T02:00:00+00:00" and st["layerCheck"] == "ok"
    (ev,) = [e for e in log.events if e.code == "feed-inactive"]
    assert ev.severity == "info" and "Vacía desde el 2026-11-19" in ev.message and "sigue siendo la de estos" in ev.message
    # La corrida anterior trajo avisos: la cuenta empieza de nuevo.
    st, _ = _fire_run(tmp_path / "b", monkeypatch, LISTING.read_bytes(), {**prev, "items": 1})
    assert st["emptySince"] == "2026-11-21T02:00:00+00:00"


def test_renumbered_fire_layer_twice_is_a_warning(tmp_path, monkeypatch):
    listing = json.loads(LISTING.read_bytes())
    listing["layers"] = [x for x in listing["layers"] if x["id"] != 3]
    prev = {"ok": False, "items": 0, "error": "la capa 3 del servidor ya no es …", "formatError": True,
            "checkedAt": "2026-11-20T13:00:00+00:00"}
    st, log = _fire_run(tmp_path, monkeypatch, json.dumps(listing).encode(), prev)
    assert not st["ok"] and "emptySince" not in st
    (warn,) = [e for e in log.events if e.code == "hazard-feed-down"]
    assert warn.severity == "warning" and "no figura en el listado" in warn.message


def test_one_listing_request_for_several_empty_layers_of_the_same_service():
    """Varias capas vacías del mismo servicio (o un listado que no responde) cuestan un solo pedido por corrida."""
    geos = [N.FEED_BY_ID[i] for i in ("senamhi-hidrologicos", "senamhi-incendios", "senamhi-lluvias")]
    for listing in (LISTING.read_bytes(), None):
        fetch, asked = _fetch_with_listing(listing)
        _, status, _ = N.collect(fetch, NOW, feeds=geos, host_failures=99)
        assert sum(u.endswith("/MapServer?f=json") for u in asked) == 1
        assert {st["layerCheck"][:5] for st in status} == ({"ok"} if listing else {"no ve"})
        assert all(st["ok"] for st in status)


def test_layer_republished_under_another_schema_is_not_a_move():
    listing = json.loads(LISTING.read_bytes())
    for x in listing["layers"]:
        if x["id"] == 3:
            x["name"] = "GEO.senamhi_avisofwi24h"  # otra base, otras mayúsculas: la misma capa
    fetch, _ = _fetch_with_listing(json.dumps(listing).encode())
    st, _, _ = N._read_feed(N.FEED_BY_ID["senamhi-incendios"], fetch, NOW)
    assert st["ok"] and st["layerCheck"] == "ok"
