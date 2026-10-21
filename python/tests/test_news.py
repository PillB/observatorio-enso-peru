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


def test_collect_isolates_bad_feeds_and_slow_hosts():
    """Un feed que explota no tumba a los demás; un servidor caído no se reintenta feed por feed."""
    feeds = [N.Feed("a1", "A1", "peru", "https://a.pe/1"), N.Feed("a2", "A2", "peru", "https://a.pe/2"),
             N.Feed("a3", "A3", "peru", "https://a.pe/3"), N.Feed("b1", "B1", "peru", "https://b.pe/1"),
             N.Feed("c1", "C1", "peru", "https://c.pe/1")]
    calls = []

    def fetch(url):
        calls.append(url)
        if url.startswith("https://a.pe"):
            return None, b"", "", "ConnectTimeout: timed out"
        if url == "https://b.pe/1":
            raise RuntimeError("redirecciones infinitas")
        return 200, RSS, "", ""

    found, status, raw = N.collect(fetch, NOW, feeds=feeds)
    st = {s["id"]: s for s in status}
    assert calls.count("https://a.pe/3") == 0, "tras dos fallos de red seguidos se omite el resto del servidor"
    assert st["a3"]["error"].startswith("omitido") and not st["a3"]["ok"]
    assert "RuntimeError" in st["b1"]["error"]
    assert st["c1"]["ok"] and len(found) == 1 and set(raw) == {"c1"}
    found, status, _ = N.collect(lambda u: (200, RSS, "", ""), NOW, feeds=feeds, deadline=-1)
    assert not found and all("tiempo" in s["error"] for s in status)
    # 429: el servidor pide que se le pida menos; tras dos seguidos no se le piden los demás.
    calls.clear()
    N.collect(lambda u: calls.append(u) or (429, b"", "", "HTTP 429"), NOW, feeds=feeds[:3])
    assert calls == ["https://a.pe/1", "https://a.pe/2"]


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


def test_architecture_diagrams_are_drawn_from_the_model():
    """Los dos diagramas (completo y simplificado) salen de docs/arquitectura.json: los SVG de docs/ y del sitio
    son los que dibuja el generador, cada caja y cada conexión del modelo está en el dibujo con su explicación, y
    el recorrido solo nombra cajas que existen."""
    import re

    from conftest import ROOT
    from tools import architecture as A

    model = json.loads(A.MODEL.read_text(encoding="utf-8"))
    out = A.render_all(model)
    for key, paths in A.OUT.items():
        for p in paths:
            assert p.read_text(encoding="utf-8") == out[key], f"{p.relative_to(ROOT.parent)}: corre python -m tools.architecture"
        svg = out[key]
        assert svg.startswith("<svg") and "<script" not in svg and "<foreignObject" not in svg
        part = model[key]
        ids = {n["id"] for n in part["nodes"]}
        assert len(ids) == len(part["nodes"]), "ids de cajas repetidos"
        for n in part["nodes"]:
            assert f'data-node="{n["id"]}"' in svg
            assert n["what_es"] and n["what_en"]
        for e in part["edges"]:
            assert e["from"] in ids and e["to"] in ids, e
            assert e["label_es"] and e["explain_es"] and e["label_en"] and e["explain_en"]
        assert len(re.findall(r'data-edge="', svg)) == len(part["edges"])
    simple_ids = {n["id"] for n in model["simple"]["nodes"]}
    full_ids = {n["id"] for n in model["full"]["nodes"]}
    for n in model["simple"]["nodes"]:
        assert set(n["covers"]) <= full_ids, n["id"]
    covered = {c for n in model["simple"]["nodes"] for c in n["covers"]}
    assert covered == full_ids, f"cajas del completo sin lugar en el simplificado: {sorted(full_ids - covered)}"
    for step in model["walkthrough"]:
        assert set(step["nodes"]) <= simple_ids, step["title_es"]
    doc = A.DOC.read_text(encoding="utf-8")
    assert doc == A.render_doc(model, doc), "docs/arquitectura.md: corre python -m tools.architecture"


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


def test_equivalent_links_and_url_outlets():
    """Revisión: «?outputType=» y «utm_» no separan la misma nota; « - https://medio.pe/» sale del titular."""
    assert N._norm_link("https://elcomercio.pe/peru/nota/?outputType=amp") == N._norm_link("https://elcomercio.pe/peru/nota")
    assert N._norm_link("https://x.pe/n?utm_source=a&id=3") == N._norm_link("http://www.x.pe/n?id=3") == "x.pe/n?id=3"
    assert N._norm_link("https://x.pe/n?preference=1") == "x.pe/n?preference=1"
    assert N._strip_outlet("Lluvias en Huánuco - https://hbanoticias.pe/", "hbanoticias.pe") == "Lluvias en Huánuco"
    assert N._strip_outlet("Lluvias - https://otro.pe/", "hbanoticias.pe") == "Lluvias - https://otro.pe/"


def test_probe_feeds_respects_robots_txt():
    """Revisión: el sondeo pedía los feeds de Google Noticias que robots.txt no permite (los que el registro lee
    una vez al día solo desde la corrida diaria). Ahora no pide nada que robots.txt no permita, ni a un servidor
    cuyo robots.txt no responde."""
    import httpx

    from enso.reach import Robots
    from tools import probe_feeds as P

    asked = []

    def net(req):
        asked.append(str(req.url))
        if req.url.path == "/robots.txt":
            if req.url.host == "news.google.com":
                return httpx.Response(200, text="User-agent: *\nDisallow: /rss/search\n")
            return httpx.Response(503) if req.url.host == "caido.pe" else httpx.Response(404)
        return httpx.Response(200, text="<rss/>")

    pr = P.Probe()
    pr.client = httpx.Client(transport=httpx.MockTransport(net))
    pr.robots = Robots(pr.client)
    assert pr.get("https://news.google.com/rss/search?q=lluvias")[4] == "omitido: robots.txt no permite la ruta"
    assert pr.get("https://caido.pe/feed/")[4] == "omitido: robots.txt no respondió"
    assert pr.get("https://diario.pe/feed/")[0] == 200
    assert not any("/rss/search" in u or u == "https://caido.pe/feed/" for u in asked)


def test_probe_feeds_only_replaces_what_it_probes(tmp_path, monkeypatch):
    """Revisión: ``--only`` no borra las demás capturas ni el informe, y una corrida sin red falla."""
    import json as _json

    from tools import probe_feeds as P

    cands = tmp_path / "c.json"
    cands.write_text(_json.dumps([{"id": "a", "name": "A"}, {"id": "b", "name": "B"}]), encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.xml").write_text("<rss/>")
    (out / "b.xml").write_text("<rss/>")
    (out / "report.json").write_text(_json.dumps({"results": [{"id": "a", "ok": True}, {"id": "b", "ok": True}]}))
    monkeypatch.setattr(P, "Probe", lambda: None)
    monkeypatch.setattr(P, "safe_probe", lambda pr, c, now, o: {"id": c["id"], "ok": False, "tried": []})
    assert P.main(["--out", str(out), "--candidates", str(cands), "--only", "b"]) == 0  # «a» sigue bien
    assert (out / "a.xml").exists() and not (out / "b.xml").exists()
    rep = _json.loads((out / "report.json").read_text())
    assert [r["id"] for r in rep["results"]] == ["a", "b"] and rep["ok"] == 1
    assert P.main(["--out", str(out), "--candidates", str(cands)]) == 1  # ninguno respondió
