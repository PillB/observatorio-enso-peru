"""Revisión antes del despliegue de la identidad de las notas (clave ``news-identity``).

La decisión: una nota es (feed, enlace canónico); un titular nuevo en el mismo enlace es una corrección que se
muestra como la última versión (``latest_versions`` / ``cluster``). Cada prueba toma una forma en que esa decisión
podía fallar y la contrasta con el histórico real de data-archive (``sources/news/items.jsonl.gz`` al 21-11-2026,
commit bc23c34f) o con las respuestas crudas archivadas del mismo día:

1. Un enlace que no identifica la nota (FIRMS enlaza todos sus resúmenes al mismo mapa): el grupo mostraba el
   resumen más antiguo de las dos semanas (191 focos, 7-8 de noviembre) y ocultaba el de hoy (79, 20-21).
2. La misma nota por dos feeds con distinto último titular (26 enlaces en data-archive): el grupo mostraba el que
   vio primero, con el titular viejo.
3. Titular que vuelve (A → B → A, El Comercio con el conteo de la ONPE): ``new_lines`` no agrega A otra vez, así
   que sin la lectura de hoy se mostraba B.
4. El USGS corrigió la hora del sismo us6000u1kt un segundo hacia atrás al revisar la magnitud: los avisos, que
   ordenan por fecha, mostraban la magnitud vieja.
5. La ventana de 14 días se mide con la fecha de la nota, no con la de la corrección (una revisión de un sismo de
   hace tres semanas no es noticia de hoy), con el borde exacto.
6. Una página que el medio reescribe cada día (el «temblor hoy» de El Comercio) se muestra en su última versión y
   su copia apunta al día (UTC) en que se vio esa versión, aunque en Lima fuera la noche anterior.
7. La codificación de la consulta no separa la misma nota, y lo que distingue dos avisos se conserva.
8. Un enlace que el feed puso a dos titulares en una misma lectura (una portada) no junta esas notas.

Las líneas de ``ROWS`` son copias de data-archive, solo con los campos que usan los grupos (sin el resumen).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from enso import archive, news as N, sourcefeed

ROWS = [
    {"id": "030c4c5c1dcbf0ac", "first_seen": "2026-10-21T19:48:16+00:00", "published": "2026-10-11T13:42:59Z", "region": "peru", "feed": "usgs-sismos", "kind": "organismo", "outlet": "USGS · sismos de magnitud 4 o más (Perú y alrededores)", "relevance": "impacto", "hazards": ["sismo"], "title": "Sismo de magnitud 5.2 a 18 km al SSE de Camaná, Perú", "link": "https://earthquake.usgs.gov/earthquakes/eventpage/us6000u1kt", "departments": ["04"]},
    {"id": "2fc841e6cac89813", "first_seen": "2026-10-23T02:53:13+00:00", "published": "2026-10-11T13:42:58Z", "region": "peru", "feed": "usgs-sismos", "kind": "organismo", "outlet": "USGS · sismos de magnitud 4 o más (Perú y alrededores)", "relevance": "impacto", "hazards": ["sismo"], "title": "Sismo de magnitud 5.3 a 28 km al SSO de Camaná, Perú", "link": "https://earthquake.usgs.gov/earthquakes/eventpage/us6000u1kt", "departments": ["04"]},
    {"id": "a4a07878dc3ff17b", "first_seen": "2026-11-07T04:33:36+00:00", "published": "2026-11-06T20:54:32+00:00", "region": "peru", "feed": "elcomercio-peru", "kind": "diario", "outlet": "El Comercio · Perú (regiones)", "relevance": "impacto", "hazards": ["sismo"], "title": "Temblor hoy, 6 de noviembre: revisa dónde se registraron los últimos sismos y magnitud según IGP", "link": "https://elcomercio.pe/peru/temblor-en-peru-hoy-revisa-donde-se-registraron-los-ultimos-sismos-y-magnitud-segun-igp-tdpe-noticia/"},
    {"id": "1ff2b1baf1804c3b", "first_seen": "2026-11-08T11:34:43+00:00", "published": "2026-11-08T02:30:00+00:00", "region": "peru", "feed": "elcomercio", "kind": "diario", "outlet": "El Comercio", "relevance": "impacto", "hazards": ["sismo"], "title": "Temblor en Perú hoy, sábado 7 de noviembre: IGP informó dónde fue el sismo y de cuánta magnitud", "link": "https://elcomercio.pe/peru/temblor-en-peru-hoy-revisa-donde-se-registraron-los-ultimos-sismos-y-magnitud-segun-igp-tdpe-noticia/"},
    {"id": "0efce28293e4cfca", "first_seen": "2026-11-09T04:15:47+00:00", "published": "2026-11-08T02:30:00+00:00", "region": "peru", "feed": "elcomercio-peru", "kind": "diario", "outlet": "El Comercio · Perú (regiones)", "relevance": "impacto", "hazards": ["sismo"], "title": "Sismos reportados en Perú este 7 de noviembre", "link": "https://elcomercio.pe/peru/temblor-en-peru-hoy-revisa-donde-se-registraron-los-ultimos-sismos-y-magnitud-segun-igp-tdpe-noticia/"},
    {"id": "c1d6c7c6723b7a70", "first_seen": "2026-11-09T13:21:48+00:00", "published": "2026-11-08T21:13:49+00:00", "region": "peru", "feed": "gnews-peru", "kind": "agregador", "outlet": "El Comercio Perú", "relevance": "enso", "hazards": ["enso"], "title": "Lluvias de El Niño ponen en riesgo a 21 bypasses de Lima: conoce cuáles podrían inundarse", "link": "https://news.google.com/rss/articles/CBMi2AFBVV95cUxORnMyNkxMUUZuTVRJQ0JzZzM5MW9QZmJCY2UwVGROTzF6MWNVMmpVOUlFQm5pU2hZXzdvUzhleW8tZjVTT3paaU1ac2pfaTVvU01hcERBTHc0MnlJVDI1c3pVM1FBUWsyYnFiazd1ZUgtYjBBRHFvQWtHNjJXeVVBRjV4aWZCdlNSRC15cFlYQ3RlODhmT29aZklHd1dYb3oyREVLVXpHSWtQdlZVMmFBSjFMdDhLTHZvczhKOUZ0YjVtdGtwUUQ0ZFVpY0lRU0tLTzd5UHJ2TjjSAewBQVVfeXFMTldBZzczbXRuaGxEZDlkZUtrX296c2Q0clBObzZkODJXUDE1aGR4ODRsTXRRRE1VWUR1N25KREpDWDFHX1VWbm1vU3M2VGYxQWZleHV6UUFWa2I3TDhacTNxZEtfamdGNTRFOUhod2pRMHFmTkJuUE8zcEcxbjhodFVyVU04YWgyVnpSTDhDTEVHenpEdUhKZ0NXRXdRT0VaX3JUM3JxWWdZcURMQ2lTUk80S0lRaUlWSTlzUVl2NDhfX2ZWX1E0eWIta3hrSTl0eE13X21GVE42UEZsNUdsTTYyMDNFeXQ2YUhiUWo?oc=5", "departments": ["15"]},
    {"id": "ed8358c7b6b546e0", "first_seen": "2026-11-11T02:10:10+00:00", "published": "2026-11-11T02:10:12+00:00", "region": "peru", "feed": "rpp-piura", "kind": "radio", "outlet": "RPP Noticias · Piura", "relevance": "impacto", "hazards": ["lluvias"], "title": "Piura: vecinos de El Bosque denuncian aguas servidas tras fuertes lluvias desde hace una semana [VIDEO]", "link": "https://rpp.pe/rotafono/servicios-publicos/piura-vecinos-de-el-bosque-denuncian-aguas-servidas-tras-fuertes-lluvias-desde-hace-una-semana-fenomeno-el-nino-tuberias-rotas-eps-grau-video-noticia-1717118", "departments": ["20"]},
    {"id": "00a703dcffdd168c", "first_seen": "2026-11-14T11:48:08+00:00", "published": "2026-11-08T21:20:52+00:00", "region": "peru", "feed": "gnews-07", "kind": "agregador", "outlet": "El Comercio Perú", "relevance": "enso", "hazards": ["enso"], "title": "Lluvias de El Niño ponen en riesgo a 21 bypasses de Lima: ¿cuáles podrían inundarse?", "link": "https://news.google.com/rss/articles/CBMi2AFBVV95cUxORnMyNkxMUUZuTVRJQ0JzZzM5MW9QZmJCY2UwVGROTzF6MWNVMmpVOUlFQm5pU2hZXzdvUzhleW8tZjVTT3paaU1ac2pfaTVvU01hcERBTHc0MnlJVDI1c3pVM1FBUWsyYnFiazd1ZUgtYjBBRHFvQWtHNjJXeVVBRjV4aWZCdlNSRC15cFlYQ3RlODhmT29aZklHd1dYb3oyREVLVXpHSWtQdlZVMmFBSjFMdDhLTHZvczhKOUZ0YjVtdGtwUUQ0ZFVpY0lRU0tLTzd5UHJ2TjjSAewBQVVfeXFMTldBZzczbXRuaGxEZDlkZUtrX296c2Q0clBObzZkODJXUDE1aGR4ODRsTXRRRE1VWUR1N25KREpDWDFHX1VWbm1vU3M2VGYxQWZleHV6UUFWa2I3TDhacTNxZEtfamdGNTRFOUhod2pRMHFmTkJuUE8zcEcxbjhodFVyVU04YWgyVnpSTDhDTEVHenpEdUhKZ0NXRXdRT0VaX3JUM3JxWWdZcURMQ2lTUk80S0lRaUlWSTlzUVl2NDhfX2ZWX1E0eWIta3hrSTl0eE13X21GVE42UEZsNUdsTTYyMDNFeXQ2YUhiUWo?oc=5", "departments": ["15"]},
    {"id": "e71952ffd00ae743", "first_seen": "2026-11-17T02:12:05+00:00", "published": "2026-11-16T22:37:12+00:00", "region": "peru", "feed": "rpp", "kind": "radio", "outlet": "RPP Noticias", "relevance": "impacto", "hazards": ["lluvias", "inundacion"], "title": "Piura: vecinos de El Bosque reportan aguas sucias tras fuertes lluvias desde hace 15 días [VIDEO]", "link": "https://rpp.pe/rotafono/servicios-publicos/piura-vecinos-de-el-bosque-denuncian-aguas-servidas-tras-fuertes-lluvias-desde-hace-una-semana-fenomeno-el-nino-tuberias-rotas-eps-grau-video-noticia-1717118", "departments": ["20"]},
    {"id": "c8a5f7b011b53bca", "first_seen": "2026-11-17T13:52:31+00:00", "published": "2026-11-17T10:20:30+00:00", "region": "peru", "feed": "gnews-peru", "kind": "agregador", "outlet": "radio uno 93.7", "relevance": "enso", "hazards": ["enso", "calor"], "title": "Tacna soportará temperaturas de hasta 30 grados y radiación UV de 14 unidades por influencia del Niño costero", "link": "https://news.google.com/rss/articles/CBMi3wFBVV95cUxNOUNtZWw1ZnB6aFFKNWlvTjIxdzI3N1BENTIxa2ctTktpSDY4WExTM0RWVkRmU2tDVVBPa3Z6RElNTk1lSmo1TjhzTmR2RHhCUHRORGwzUTJ1M3RrVG1jeEZpVHRkdUxoaUpmMWNaN3h0cU5QcTVBSTcybTc4M1VBMFh3SDFDZmh2QTdxR0tkcG5HMGJYd2lIaFJiX3VtcDlwRUlQNmhJTmNxOGVhbE5zNHlnLU1XOHA5N0wwM1FrWWxmWm5RRXZGOXFaWm91bWo5WGtXV29PY19OZkhucmJZ?oc=5", "departments": ["23"]},
    {"id": "53ceafb85fe71c44", "first_seen": "2026-11-18T13:27:51+00:00", "published": "2026-11-17T10:20:30+00:00", "region": "peru", "feed": "gnews-23", "kind": "agregador", "outlet": "radio uno 93.7", "relevance": "enso", "hazards": ["enso", "calor"], "title": "Niño Costero: Tacna soportará temperaturas de hasta 30 grados y radiación UV de 14 unidades", "link": "https://news.google.com/rss/articles/CBMi3wFBVV95cUxNOUNtZWw1ZnB6aFFKNWlvTjIxdzI3N1BENTIxa2ctTktpSDY4WExTM0RWVkRmU2tDVVBPa3Z6RElNTk1lSmo1TjhzTmR2RHhCUHRORGwzUTJ1M3RrVG1jeEZpVHRkdUxoaUpmMWNaN3h0cU5QcTVBSTcybTc4M1VBMFh3SDFDZmh2QTdxR0tkcG5HMGJYd2lIaFJiX3VtcDlwRUlQNmhJTmNxOGVhbE5zNHlnLU1XOHA5N0wwM1FrWWxmWm5RRXZGOXFaWm91bWo5WGtXV29PY19OZkhucmJZ?oc=5", "departments": ["23"]},
    {"id": "a517a049f820ab6c", "first_seen": "2026-11-19T13:53:56+00:00", "published": "2026-11-19T05:59:00Z", "region": "peru", "feed": "firms-focos", "kind": "organismo", "outlet": "NASA FIRMS · focos de calor (VIIRS, NOAA-20)", "relevance": "impacto", "hazards": ["incendio"], "title": "NASA FIRMS · 353 focos de calor en el Perú (18 y 19 de noviembre): Ucayali (150), Loreto (38), San Martín (24) y 16 departamentos más", "link": "https://firms.modaps.eosdis.nasa.gov/map/#d:24hrs;@-75.0,-9.4,5.6z", "departments": ["25", "16", "22", "10", "08", "12", "01", "21", "09", "11", "05", "02", "13", "19", "04", "17", "06", "07", "15"]},
    {"id": "2077c1273b996863", "first_seen": "2026-11-19T21:54:57+00:00", "published": "2026-11-19T18:36:00Z", "region": "peru", "feed": "firms-focos", "kind": "organismo", "outlet": "NASA FIRMS · focos de calor (VIIRS, NOAA-20)", "relevance": "impacto", "hazards": ["incendio"], "title": "NASA FIRMS · 839 focos de calor en el Perú (18 y 19 de noviembre): Ucayali (331), Loreto (130), San Martín (59) y 18 departamentos más", "link": "https://firms.modaps.eosdis.nasa.gov/map/#d:24hrs;@-75.0,-9.4,5.6z", "departments": ["25", "16", "22", "10", "12", "08", "17", "01", "09", "05", "21", "19", "02", "06", "11", "13", "04", "14", "07", "15", "03"]},
    {"id": "8562e61a096e5318", "first_seen": "2026-11-20T13:36:32+00:00", "published": "2026-11-20T07:20:00Z", "region": "peru", "feed": "firms-focos", "kind": "organismo", "outlet": "NASA FIRMS · focos de calor (VIIRS, NOAA-20)", "relevance": "impacto", "hazards": ["incendio"], "title": "NASA FIRMS · 564 focos de calor en el Perú (19 y 20 de noviembre): Ucayali (202), Loreto (92), Huánuco (48) y 18 departamentos más", "link": "https://firms.modaps.eosdis.nasa.gov/map/#d:24hrs;@-75.0,-9.4,5.6z", "departments": ["25", "16", "10", "08", "22", "12", "17", "05", "09", "06", "01", "19", "04", "21", "03", "13", "02", "14", "07", "11", "20"]},
    {"id": "74fec1e0af630af0", "first_seen": "2026-11-21T13:03:06+00:00", "published": "2026-11-21T07:03:00Z", "region": "peru", "feed": "firms-focos", "kind": "organismo", "outlet": "NASA FIRMS · focos de calor (VIIRS, NOAA-20)", "relevance": "impacto", "hazards": ["incendio"], "title": "NASA FIRMS · 79 focos de calor en el Perú (20 y 21 de noviembre): Ucayali (30), Cusco (13), Huánuco (12) y 10 departamentos más", "link": "https://firms.modaps.eosdis.nasa.gov/map/#d:24hrs;@-75.0,-9.4,5.6z", "departments": ["25", "08", "10", "22", "13", "03", "11", "06", "04", "09", "16", "20", "21"]}
]

UTC = timezone.utc


def _rows(feed: str = "", link_part: str = "") -> list[dict]:
    return [dict(r, summary="") for r in ROWS if (not feed or r["feed"] == feed) and link_part in r["link"]]


def _shown(items: list[dict], now: datetime, **kw) -> list[dict]:
    return [link for g in N.cluster(items, now, **kw) for link in g["links"]]


def test_firms_shows_only_the_latest_daily_summary():
    firms = _rows("firms-focos")
    assert len(firms) == 4
    assert len({r["link"] for r in firms}) == 1, "cuatro resúmenes, un solo mapa"
    groups = N.cluster(firms, datetime(2026, 11, 21, 13, 25, tzinfo=UTC))
    newest = max(firms, key=lambda r: r["first_seen"])
    assert newest["id"] == "74fec1e0af630af0"  # 79 focos (20 y 21 de noviembre), leído el 21-11
    assert [(g["title"], g["count"]) for g in groups] == [(newest["title"], 1)]
    assert groups[0]["first"] == newest["published"]
    # El histórico y la clave siguen guardando cada día: el resumen de un día no es corrección del anterior.
    assert len({N.identity_key(r) for r in firms}) == 4


def test_the_same_link_in_two_feeds_shows_its_newest_title():
    pairs = {"bypasses": "CBMi2AFBVV95cUxORnMyNkxMUUZuTVRJQ", "el-bosque": "piura-vecinos-de-el-bosque",
             "tacna": "CBMi3wFBVV95cUxNOUNtZWw1ZnB6aFFKN"}
    now = datetime(2026, 11, 21, 13, 25, tzinfo=UTC)
    for name, part in pairs.items():
        rows = _rows(link_part=part)
        assert len({r["feed"] for r in rows}) == 2 and len({r["title"] for r in rows}) == 2, name
        newest = max(rows, key=lambda r: r["first_seen"])
        shown = _shown(rows, now)
        assert [s["title"] for s in shown] == [newest["title"]], name
    # La región separa: la misma nota leída por un feed del mundo sale también en «Mundo».
    rows = _rows(link_part=pairs["tacna"])
    world = dict(rows[0], region="mundo", feed="gnews-world", id="otro")
    regions = sorted(g["region"] for g in N.cluster(rows + [world], now))
    assert regions == ["mundo", "peru"]


# Titulares reales del mismo enlace en las respuestas crudas de El Comercio (sources/news-elcomercio):
# 2026-10-26-3fab6cae5789.xml «revisa aquí», 2026-11-06-7fe3610b9440.xml «sigue aquí», 2026-11-09-e612a142c05a.xml
# otra vez «revisa aquí».
ONPE_LINK = "https://elcomercio.pe/elecciones/resultados-en-piura-de-las-elecciones-regionales-y-municipales-2026-noticia/"
ONPE_A = "Resultados ONPE en región Piura al 99.563 %: revisa aquí el conteo oficial de las Elecciones Regionales y Municipales 2026"
ONPE_B = "Resultados ONPE en región Piura al 99.563 %: sigue aquí el conteo oficial de las Elecciones Regionales y Municipales 2026"


def _onpe(title: str, seen: str) -> dict:
    return {"id": N.item_id(ONPE_LINK, title) + seen[:10], "feed": "elcomercio", "region": "peru", "kind": "diario",
            "outlet": "El Comercio", "relevance": "impacto", "hazards": [], "title": title, "summary": "",
            "link": ONPE_LINK, "first_seen": seen, "published": "2026-10-27T00:00:00+00:00"}


def test_a_headline_that_comes_back_is_shown_as_the_feed_carries_it_today():
    a1, b, a3 = _onpe(ONPE_A, "2026-10-26T02:04:00+00:00"), _onpe(ONPE_B, "2026-11-06T02:11:00+00:00"), \
        _onpe(ONPE_A, "2026-11-09T02:12:00+00:00")
    hist = [a1]
    hist += N.new_lines(hist, [b])
    assert N.new_lines(hist, [a3]) == [], "el titular ya visto no agrega otra línea (el histórico no crece)"
    now = datetime(2026, 11, 9, 3, 0, tzinfo=UTC)
    assert [s["title"] for s in _shown(hist, now, current=[a3])] == [ONPE_A]
    # Sin la lectura de hoy (un feed caído) vale la última vista; y si hoy trae B, B.
    assert [s["title"] for s in _shown(hist, now)] == [ONPE_B]
    assert [s["title"] for s in _shown(hist, now, current=[b])] == [ONPE_B]
    # La lectura de hoy de otro feed no cambia esta nota.
    other = dict(a3, feed="elcomercio-peru")
    assert [s["title"] for s in _shown(hist, now, current=[other])] == [ONPE_B]


def test_usgs_revision_with_an_earlier_time_wins_in_the_alerts():
    rows = _rows("usgs-sismos")
    old, new = sorted(rows, key=lambda r: r["first_seen"])
    assert "5.2" in old["title"] and "5.3" in new["title"] and new["published"] < old["published"]
    # Dentro de la ventana de avisos (7 días desde la fecha del sismo, 11-10-2026).
    now = datetime(2026, 10, 14, 0, 0, tzinfo=UTC)
    shown = [a for a in sourcefeed.alerts(rows, now) if a["url"].endswith("/us6000u1kt")]
    assert [a["title"] for a in shown] == [new["title"]]
    assert [s["title"] for s in _shown(rows, now)] == [new["title"]]


def test_the_window_counts_from_the_story_date_not_the_revision():
    # «Temblor hoy» de El Comercio: la versión del 09-11 conserva la fecha de publicación 2026-11-08T02:30:00.
    rows = _rows(link_part="temblor-en-peru-hoy-revisa-donde")
    latest = max(rows, key=lambda r: r["first_seen"])
    pub = datetime.fromisoformat(latest["published"])
    edge = pub + timedelta(days=14)  # since == published: entra (``>=``)
    assert [s["id"] for s in _shown(rows, edge)] == [latest["id"]]
    assert _shown(rows, edge + timedelta(seconds=1)) == []
    # La corrección vista hoy de un sismo de hace tres semanas no vuelve a la lista.
    usgs = _rows("usgs-sismos")
    assert _shown(usgs, datetime(2026, 11, 1, 0, 0, tzinfo=UTC)) == []


def test_a_rewritten_daily_page_shows_its_last_version_and_its_copy_day(tmp_path):
    rows = _rows(link_part="temblor-en-peru-hoy-revisa-donde")
    assert len({N.canonical_link(r["link"]) for r in rows}) == 1
    latest = max(rows, key=lambda r: r["first_seen"])
    assert (len(rows), latest["id"], latest["first_seen"]) == (3, "0efce28293e4cfca", "2026-11-09T04:15:47+00:00")
    shown = _shown(rows, datetime(2026, 11, 10, 0, 0, tzinfo=UTC))
    assert [s["id"] for s in shown] == [latest["id"]]
    # 04:15 UTC es el 08-11 a las 23:15 en Lima: la copia es la página del día UTC, que es donde el archivo la pone.
    assert shown[0]["archive"].endswith("/news/2026-11-09.html#0efce28293e4cfca")
    pages = _archive_pages(tmp_path, rows)
    assert 'id="0efce28293e4cfca"' in pages["2026-11-09.html"]
    assert 'id="0efce28293e4cfca"' not in pages.get("2026-11-08.html", "")


def _archive_pages(tmp_path, rows: list[dict]) -> dict[str, str]:
    """Las páginas del archivo por día que escribe el sitio para esas notas."""
    archive.write_news_days(archive.Writer(tmp_path), rows, N.FEED_BY_ID, {}, set(), date(2026, 11, 21))
    return {p.name: p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.html")}


def test_query_encoding_does_not_split_a_story_and_keeps_what_tells_two_apart():
    # Enlace real de los avisos del SENAMHI en GeoSINPAD (data-archive): la consulta es lo que distingue un aviso.
    base = "https://geosinpad.indeci.gob.pe/indeci/rest/services/Ent_Tecnico_Cientificas/SENAMHI/MapServer/4/query"
    real = base + "?where=NUM_AVISO%3D1663&outFields=*&returnGeometry=false&f=html"
    same = base + "?where=NUM_AVISO=1663&outFields=%2A&returnGeometry=false&f=html&utm_source=x"
    other = base + "?where=NUM_AVISO%3D1664&outFields=*&returnGeometry=false&f=html"
    assert N.canonical_link(real) == N.canonical_link(same)
    assert N.canonical_link(real) != N.canonical_link(other)
    # «+» y «%2B» no son lo mismo en una consulta (espacio y signo más).
    assert N.canonical_link("https://a.pe/b?q=a+b") != N.canonical_link("https://a.pe/b?q=a%2Bb")


def test_one_link_on_two_headlines_in_one_read_keeps_both_in_the_groups():
    seen = "2026-11-20T02:00:00+00:00"
    one = {"id": "p1", "feed": "elcomercio", "region": "peru", "kind": "diario", "outlet": "El Comercio",
           "relevance": "impacto", "hazards": ["lluvias"], "summary": "", "link": "https://elcomercio.pe/",
           "first_seen": seen, "published": seen, "title": "Lluvias intensas en Piura inundan calles de Castilla"}
    two = dict(one, id="p2", title="Lluvias intensas en Piura inundan calles de Sullana")
    shown = _shown([one, two], datetime(2026, 11, 20, 3, 0, tzinfo=UTC))
    assert sorted(s["id"] for s in shown) == ["p1", "p2"]


def _usgs_only(monkeypatch):
    """Un solo feed, el del USGS, que responde con la copia archivada del 17-10-2026."""
    from pathlib import Path

    import httpx

    from enso.fetch import Fetcher

    one = N.FEED_BY_ID["usgs-sismos"]
    monkeypatch.setattr(N, "FEEDS", [one])
    body = (Path(__file__).parent / "fixtures" / "sources" / one.fixture).read_bytes()
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(**{**kw, "transport": httpx.MockTransport(
        lambda req: httpx.Response(200, content=body, headers={"content-type": "application/json"}))}))
    return Fetcher(polite_delay=0)


def _previous_site(tmp_path, rows: list[dict]):
    """La publicación anterior y la copia de data-archive con esas líneas en el histórico."""
    import gzip
    import json

    text = "".join(json.dumps(r) + "\n" for r in rows)
    site = tmp_path / "site"
    (site / "news").mkdir(parents=True)
    (site / "news" / "items.jsonl").write_text(text, encoding="utf-8")
    (site / "news" / "feeds.json").write_text(json.dumps({"history": {"items": len(rows)}}), encoding="utf-8")
    backup = tmp_path / "history"
    backup.mkdir()
    (backup / "items.jsonl.gz").write_bytes(gzip.compress(text.encode()))
    return site, backup


def test_the_pipeline_passes_todays_read_to_the_groups(tmp_path, monkeypatch):
    """``acquire_news`` da a ``cluster`` lo leído hoy: con el histórico 5,2 → 5,3 del sismo us6000u1kt (los dos
    titulares reales de data-archive) y el feed de hoy (la copia del USGS del 17-10, que trae 5,2), se muestra 5,2.
    La secuencia es construida (en la realidad 5,2 llegó primero y 5,3 después); lo que se prueba es el cableado."""
    from enso import observatory as obs

    fetcher = _usgs_only(monkeypatch)
    old, new = sorted(_rows("usgs-sismos"), key=lambda r: r["first_seen"])
    old = dict(old, first_seen="2026-10-12T02:00:00+00:00")
    new = dict(new, first_seen="2026-10-14T02:00:00+00:00", revises=old["id"])
    site, backup = _previous_site(tmp_path, [old, new])
    now = datetime(2026, 10, 17, 5, 28, tzinfo=UTC)
    got = obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), obs.EventLog(), now, None, backup)
    assert "5.2" in old["title"]
    assert len([i for i in got["items"] if i["link"].endswith("/us6000u1kt")]) == 2, "hoy no agrega línea"
    shown = [link for g in got["clusters"]["clusters"] for link in g["links"] if link["url"].endswith("/us6000u1kt")]
    assert [s["title"] for s in shown] == [old["title"]]


def test_a_shared_link_seen_in_todays_read_keeps_both_headlines():
    """La portada que ayer tenía un solo titular y hoy dos (el de ayer, que ``new_lines`` no repite, y uno nuevo):
    el histórico no muestra el enlace compartido (cada lectura guardó un titular); solo lo leído hoy lo muestra."""
    yesterday, today = "2026-11-19T02:00:00+00:00", "2026-11-20T02:00:00+00:00"
    x = {"id": "p1", "feed": "elcomercio", "region": "peru", "kind": "diario", "outlet": "El Comercio",
         "relevance": "impacto", "hazards": ["lluvias"], "summary": "", "link": "https://elcomercio.pe/",
         "first_seen": yesterday, "published": yesterday, "title": "Lluvias intensas en Piura inundan calles de Castilla"}
    y = dict(x, id="p2", first_seen=today, published=today, title="Huaico en Chosica bloquea la Carretera Central")
    read = [dict(x, first_seen=today), y]
    hist = [x] + N.new_lines([x], read)
    assert [h["id"] for h in hist] == ["p1", "p2"], "el titular de ayer no se repite"
    assert N._shared_links(hist) == set()
    shown = _shown(hist, datetime(2026, 11, 20, 3, 0, tzinfo=UTC), current=read)
    assert sorted(s["id"] for s in shown) == ["p1", "p2"]


# Titular real de la copia archivada de gnews-peru (tests/fixtures/sources/news-gnews-peru.xml); la corrección
# es construida: lo que se prueba es qué lectura vale cuando la corrida junta la de hoy y la guardada.
GNEWS_OLD = "Evalúan acciones del Ejecutivo y planes de prevención frente al fenómeno de El Niño"
GNEWS_NEW = "Congreso evalúa acciones del Ejecutivo y planes de prevención frente al fenómeno de El Niño"


def test_a_reader_feed_correction_is_shown_the_day_it_arrives(tmp_path, monkeypatch):
    """Google Noticias se lee como «reader»: a lo leído hoy, ``acquire_news`` suma las notas guardadas de la lectura
    anterior (``restored``), con el titular de ayer. La corrección que llega hoy se muestra hoy, no al día
    siguiente (antes, el titular de la lectura guardada pasaba por el de hoy)."""
    import json
    from pathlib import Path

    import httpx

    from enso import observatory as obs
    from enso.fetch import Fetcher

    feed = N.FEED_BY_ID["gnews-peru"]
    monkeypatch.setattr(N, "FEEDS", [feed])
    body = {"b": (Path(__file__).parent / "fixtures" / "sources" / feed.fixture).read_bytes()}
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(**{**kw, "transport": httpx.MockTransport(
        lambda req: httpx.Response(200, content=body["b"], headers={"content-type": "application/rss+xml"}))}))
    fetcher = Fetcher(polite_delay=0, plan={feed.url: ["actions"]})
    site = tmp_path / "site"
    (site / "news").mkdir(parents=True)
    (site / "news" / "items.jsonl").write_text("", encoding="utf-8")
    state = tmp_path / "cache" / "reader-state.json"

    def run(now):
        return obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), obs.EventLog(), now,
                                None, reader={feed.url}, reader_state=state)

    def shown(got):
        return [lk["title"] for g in got["clusters"]["clusters"] for lk in g["links"] if "Ejecutivo y planes" in lk["title"]]

    t1 = datetime(2026, 10, 21, 5, 28, tzinfo=UTC)
    first = run(t1)
    assert shown(first) == [GNEWS_OLD]
    (site / "news" / "items.jsonl").write_text(first["jsonl"], encoding="utf-8")
    (site / "news" / "feeds.json").write_text(json.dumps(first["feeds"]), encoding="utf-8")
    assert body["b"].count(GNEWS_OLD.encode()) >= 1
    body["b"] = body["b"].replace(GNEWS_OLD.encode(), GNEWS_NEW.encode())
    second = run(t1 + timedelta(hours=24))
    assert [i["title"] for i in second["items"] if i.get("revises")] == [GNEWS_NEW]
    assert shown(second) == [GNEWS_NEW]


# Las otras dos copias de la nota de El Bosque en data-archive: por Google Noticias, una de geniostv.pe y otra de
# RPP con el titular corregido (otro enlace que el de rpp.pe).
EL_BOSQUE_GNEWS = [
    {"id": "8d004181918f7b64", "first_seen": "2026-11-11T12:11:31+00:00", "published": "2026-11-11T02:33:01+00:00", "region": "peru", "feed": "gnews-22", "kind": "agregador", "outlet": "geniostv.pe", "relevance": "impacto", "hazards": ["lluvias"], "title": "Piura: vecinos de El Bosque denuncian aguas servidas tras fuertes lluvias desde hace una semana [VIDEO]", "link": "https://news.google.com/rss/articles/CBMi1wFBVV95cUxQMEFaQ21la3YzUDdfWlZHMlRmbGJCakw0MEVlLUNPYVBabUJiU3hxNldhMm5CbmlLcGR6T1gtOVhUd0tjMmZOZEExVkpVT3hpVmhSallaaUdMVGFpeXJWeXEzRnZwWnpWZUNhdHd5ZEMyV0FhTHJaM3BtbWxReGJVLWd3ZEFrQVpBNU5HanpQOHJZSVJSb2VORk9qaFE4OEQ0UW1RQlRJS1llWTRTN0tJRWd2MXUxWURyNkRpM1BYWk1IZkE1ZDlDNThCYXFLVHVBaEQzY0JXYw?oc=5", "departments": ["20"]},
    {"id": "4da395b1530f7f03", "first_seen": "2026-11-17T13:52:31+00:00", "published": "2026-11-16T22:37:33+00:00", "region": "peru", "feed": "gnews-20", "kind": "agregador", "outlet": "RPP Noticias", "relevance": "impacto", "hazards": ["lluvias"], "title": "Piura: vecinos de El Bosque reportan aguas sucias tras fuertes lluvias desde hace 15 días [VIDEO]", "link": "https://news.google.com/rss/articles/CBMipwJBVV95cUxNUFlQUFhzR1h4UGs0SzdGZUgwbkRXdnFyWUx3UGhvZ0dLbnE3bEl2Z2huY0Itak9kc3JnbGxqMlJTbHp5NENtSnZuNmgtLTh2NGNrS1Z5a2hJTTY5ZUxIdzVweGMySTVYX0Faa2xqMGNrYS1qcEw0NGRpQ1Z3M2FEaTIyYjBaaWtxc080aElyODZaMHMtVWQweTl0WkFLazNTQURYN29FQzdidGNsSlhBVnpCVXNhS3B2QVpUZ1lvaFJvWUQ5VS1wMmxpaXpqd2g3cTdfR2pSMDFKWWFyc19IQzNKaV9BUjc3TDVCYktFU0RzSHFia0NjUEJVUlk4MUp4b2l2clhlQ0Z5dHZyalo0eWRQaUh0VjZSckVTWnlfRWUzY3VZdEZJ?oc=5", "departments": ["20"]},
]


def test_the_same_outlet_and_headline_by_another_link_is_listed_once():
    """El grupo de El Bosque en data-archive: RPP por su feed (dos versiones en el mismo enlace, ``rpp-piura`` y
    ``rpp``) y por Google Noticias con el titular nuevo, y geniostv.pe. Se ve cada medio una vez: geniostv.pe con su
    titular y RPP con el último."""
    rows = _rows(link_part="piura-vecinos-de-el-bosque") + [dict(r, summary="") for r in EL_BOSQUE_GNEWS]
    groups = N.cluster(rows, datetime(2026, 11, 21, 13, 25, tzinfo=UTC))
    assert len(groups) == 1
    assert [(lk["outlet"], lk["id"]) for lk in groups[0]["links"]] == [("geniostv.pe", "8d004181918f7b64"),
                                                                     ("RPP Noticias", "e71952ffd00ae743")]
    assert groups[0]["count"] == 2
