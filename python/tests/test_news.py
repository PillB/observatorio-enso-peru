"""Noticias: lectura de RSS/Atom, relevancia, agrupación, histórico de solo anexar y CSV."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

import pytest

from enso import news as N

NOW = datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc)

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>Medio</title>
<item><title>ENFEN mantiene la alerta de El Ni&#241;o costero</title><link>https://medio.pe/a</link>
<pubDate>Fri, 16 Oct 2026 21:10:00 -0500</pubDate><description><![CDATA[<p>El ENFEN mantuvo la <b>alerta</b> de El Ni\xc3\xb1o costero. Se esperan lluvias.</p>]]></description></item>
<item><title>Resultados del f\xc3\xbatbol</title><link>https://medio.pe/b</link><pubDate>Fri, 16 Oct 2026 10:00:00 GMT</pubDate></item>
<item><title>Sin enlace</title></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Blog</title>
<entry><title>El Ni\xc3\xb1o costero: ENFEN mantiene la alerta</title><link rel="alternate" href="https://otro.pe/x"/>
<updated>2026-10-17T02:00:00Z</updated><summary>La comisi\xc3\xb3n multisectorial mantuvo el estado de alerta.</summary></entry>
</feed>"""


def test_parse_rss_and_atom():
    r = N.parse_feed(RSS)
    assert [i["link"] for i in r] == ["https://medio.pe/a", "https://medio.pe/b"]
    assert r[0]["title"] == "ENFEN mantiene la alerta de El Niño costero"
    assert r[0]["published"] == "2026-10-17T02:10:00+00:00"
    assert r[0]["summary"].startswith("El ENFEN mantuvo la alerta") and "<" not in r[0]["summary"]
    a = N.parse_feed(ATOM)
    assert a[0]["link"] == "https://otro.pe/x" and a[0]["published"] == "2026-10-17T02:00:00+00:00"


@pytest.mark.parametrize("body,msg", [
    (b"<html><body>Bloqueado</body></html>", "HTML"),
    (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss><channel/></rss>', "entidades"),
    (b"<rss><channel><item>", "XML"),
    (b"<?xml version='1.0'?><kml/>", "raíz"),
])
def test_bad_feeds_are_rejected(body, msg):
    with pytest.raises(N.FeedError, match=msg):
        N.parse_feed(body)


def test_relevance():
    gen = N.FEED_BY_ID["elcomercio"]
    haz = N.FEED_BY_ID["gdacs"]
    assert N.relevance(gen, "Senamhi: lluvias intensas en Piura", "") == "impacto"  # peligro en el titular
    assert N.relevance(gen, "Congreso aprueba ley", "durante las lluvias intensas de marzo") is None  # medio general: en el titular
    assert N.relevance(gen, "La Niña podría llegar en 2027", "") == "enso"
    assert N.relevance(haz, "Flood alert in Peru", "Heavy rain in Piura") == "impacto"
    assert N.relevance(haz, "Flood alert in Spain", "") is None  # feed del mundo: debe mencionar el Perú


LOCAL = N.Feed("x", "Diario regional", "peru", "https://x.pe/feed", scope="local", kind="diario", department="20")


@pytest.mark.parametrize("title,summary,expected", [
    # Revisión de 300 entradas: lo que no es un peligro aunque use sus palabras.
    ("Kristen Bell, la Anna de Frozen y su cruzada por la autoestima de las niñas", "de la niña que fue", None),
    ("Israel reconoce que sus soldados dispararon al vehículo de Hind Rajab, la niña palestina", "", None),
    ("Ministerio autorizó a IMARPE la pesca exploratoria de anchoveta blanca", "en el litoral del mar peruano", None),
    ("Convocatoria para la contratación de un(a) Desarrollador(a) de Servicios Climáticos", "Centro del Fenómeno El Niño", None),
    ("SENAMHI: Pronóstico del clima hoy domingo 18 de octubre 2026", "probabilidad de lluvias", None),
    ("Huancavelica: tres integrantes de una familia mueren en accidente vehicular", "la lluvia dejó la vía en mal estado", None),
    ("La Libertad: Gobierno prorrogó por 60 días el estado de emergencia en Pataz", "por la criminalidad y la minería ilegal", None),
    ("Modernizarán infraestructura deportiva de colegio", "techo para protegerse de la radiación y las lluvias", None),
    ("Dengue cobra una nueva víctima en Lambayeque", "la cifra de fallecidos llega a 10", None),
    ("Sedapal refuerza planta La Atarjea para asegurar agua en Lima durante FEN", "", "enso"),
    # Lo que sí: el ENSO y todos los peligros que alerta el observatorio.
    ("Chosica se prepara ante posible activación de quebradas", "", "impacto"),
    ("Sismo de magnitud 5,0 remece Junín", "", "impacto"),
    ("Incendio forestal en Julao fue extinguido", "", "impacto"),
    ("Senamhi alerta ola de calor en la costa norte", "", "impacto"),
    ("Friaje: temperaturas bajarán en la selva", "", "impacto"),
    ("Dengue: casos aumentan tras las lluvias en Piura", "", "impacto"),
    ("Volcán Sabancaya registra explosiones", "", "impacto"),
    ("Piura soporta primeras lluvias", "", "impacto"),
])
def test_relevance_rules(title, summary, expected):
    assert N.relevance(LOCAL, title, summary) == expected


def test_hazard_types():
    assert N.hazards("Huaico en Chosica deja damnificados", "") == ["huaico", "emergencia"]
    assert N.hazards("El Niño costero: lluvias intensas y desbordes en Tumbes") == ["enso", "lluvias", "inundacion"]
    assert N.hazards("Heladas y friaje en Puno", "") == ["frio"]
    assert N.hazards("Dengue en Lambayeque", "") == []


def _collect(bodies):
    def fetch(url):
        fid = next(f.id for f in N.FEEDS if f.url == url)
        return (200, bodies[fid], "", "") if fid in bodies else (503, b"", "", "HTTP 503")
    return N.collect(fetch, NOW)


def test_collect_status_and_clusters():
    found, status, raw = _collect({"elcomercio": RSS, "gestion": ATOM})
    st = {s["id"]: s for s in status}
    assert st["elcomercio"]["ok"] and st["elcomercio"]["items"] == 2 and st["elcomercio"]["relevant"] == 1
    assert st["elcomercio"]["active"] and not st["andina"]["ok"] and st["andina"]["error"] == "HTTP 503"
    assert len(found) == 2 and set(raw) == {"elcomercio", "gestion"}
    groups = N.cluster(found, NOW)
    assert len(groups) == 1, "las dos notas sobre la alerta del ENFEN forman un grupo"
    g = groups[0]
    # El titular del grupo es el de la nota más temprana (Gestión, 02:00 UTC).
    assert g["count"] == 2 and g["outlets"] == ["Gestión", "El Comercio"]
    assert g["title"].startswith("El Niño costero: ENFEN") and g["summary"].endswith(".")
    assert [l["url"] for l in g["links"]] == ["https://otro.pe/x", "https://medio.pe/a"]


def test_history_is_append_only_and_csv_is_safe():
    found, _, _ = _collect({"elcomercio": RSS})
    hist = N.read_jsonl(json.dumps(found[0]) + "\n{roto\n")
    assert len(hist) == 1
    again, _, _ = _collect({"elcomercio": RSS, "gestion": ATOM})
    added = N.new_lines(hist, again)
    assert [a["link"] for a in added] == ["https://otro.pe/x"]
    evil = dict(found[0], id="x", title="=HYPERLINK(\"http://x\")")
    rows = list(csv.DictReader(io.StringIO(N.to_csv(hist + added + [evil]))))
    assert len(rows) == 3 and rows[0]["link"]
    assert all(not r["title"].startswith("=") for r in rows)


def test_architecture_diagram_copies_match():
    """El diagrama del sitio es el mismo que el de docs/."""
    from conftest import ROOT

    docs = (ROOT.parent / "docs" / "arquitectura.svg").read_bytes()
    assert docs == (ROOT.parent / "public" / "assets" / "arquitectura.svg").read_bytes()
    assert docs.lstrip().startswith(b"<svg") and b"<script" not in docs


@pytest.mark.parametrize("feed", N.FEEDS, ids=lambda f: f.id)
def test_real_feed_captures_parse(feed):
    """Cada feed del catálogo, tal como respondió en la captura en vivo (21 de octubre de 2026)."""
    from conftest import FIX

    path = FIX / feed.fixture
    if not path.exists():
        pytest.skip("sin captura de este feed")
    items = N.parse_feed(path.read_bytes(), feed.url, feed.adapter)
    assert items, "el feed no tiene entradas"
    assert all(i["link"].startswith("http") and i["title"] for i in items)
    assert sum(1 for i in items if i["published"]) >= len(items) * 0.9, "faltan fechas"


def test_live_capture_clusters_are_coherent():
    """Sobre las capturas reales: sin notas de redes sociales, sin enlaces repetidos en un grupo y
    titulares sin el « - Medio» de Google Noticias."""
    from conftest import FIX

    bodies = {f.id: (FIX / f.fixture).read_bytes() for f in N.FEEDS if (FIX / f.fixture).exists()}
    found, status, _ = _collect(bodies)
    assert len(found) > 50
    groups = N.cluster(found, NOW)
    assert any(g["count"] >= 3 and g["region"] == "peru" for g in groups)
    for g in groups:
        assert not any(o.lower() in ("facebook", "instagram", "x", "youtube") for o in g["outlets"])
        assert len({l["url"] for l in g["links"]}) == len(g["links"])
        assert not any(g["title"].endswith(f" - {o}") for o in g["outlets"])


@pytest.mark.parametrize("title,expected", [
    ("Un sismo de magnitud 3.5 se sintió esta mañana en la región Pasco", None),
    ("Un sismo de magnitud 4.8 remeció la región Ucayali esta madrugada", "impacto"),
    ("Minedu activa app para reportar emergencias en colegios", None),
    ("Clima en Cusco hoy miércoles 14 de octubre", None),
    ("¡ALERTA ESTE VIERNES! Senamhi advierte FUERTE evento por las próximas 24 HORAS", "impacto"),
    ("Incencios forestales han dejado 12 personas fallecidas, reporta Indeci", "impacto"),
    ("Senamhi alerta por calor extremo y alta radiación UV en Lima", "impacto"),
    ("Vientos de hasta 30 km/h en Palpa, Ica", "impacto"),
])
def test_relevance_edges(title, expected):
    assert N.relevance(LOCAL, title, "") == expected
