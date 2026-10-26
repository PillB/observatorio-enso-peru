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


def test_architecture_annexes_detail_every_box_and_stay_in_sync():
    """Los anexos A1 a A10 (docs/arquitectura-anexos.json): cada caja del completo está en exactamente uno, cada
    caja del simplificado enlaza al menos uno, los SVG (español e inglés), el explorador y el texto están al día,
    y nada de lo que va al sitio nombra el repositorio (el despliegue en Cloudflare lo rechazaría)."""
    import re

    from conftest import ROOT
    from tools import architecture as A
    from tools.prepare_site import REPO_HOST

    model = json.loads(A.MODEL.read_text(encoding="utf-8"))
    annexes = A.load_annexes()
    assert annexes, "faltan los anexos"
    ids = [a["id"] for a in annexes]
    assert ids == [f"a{i + 1}" for i in range(len(annexes))]
    full_ids = {n["id"] for n in model["full"]["nodes"]}
    covers = [c for a in annexes for c in a["covers"]]
    assert sorted(covers) == sorted(full_ids), "cada caja del completo va en exactamente un anexo"
    simple_ids = {n["id"] for n in model["simple"]["nodes"]}
    linked = {s for a in annexes for s in a["simple"]}
    assert linked == simple_ids, "cada caja del simplificado enlaza al menos un anexo"
    icons = set(A.ICONS)
    for a in annexes:
        nodes = {n["id"] for n in a["nodes"]}
        assert len(nodes) == len(a["nodes"]), f"{a['id']}: ids repetidos"
        cols = {c["id"] for c in a["columns"]}
        for n in a["nodes"]:
            assert n["col"] in cols and n["icon"] in icons and n["group"] in A.GROUP_VAR, (a["id"], n["id"])
            assert n["what_es"] and n["what_en"] and n["name_es"] and n["name_en"], (a["id"], n["id"])
            assert set(n.get("see", [])) <= set(ids) - {a["id"]}, (a["id"], n["id"])
        for e in a["edges"]:
            assert e["from"] in nodes and e["to"] in nodes and e["from"] != e["to"], (a["id"], e)
            assert e["label_es"] and e["label_en"] and bool(e.get("explain_es")) == bool(e.get("explain_en")), (a["id"], e)
        for f in a.get("fails", []):
            assert all(f[k] for k in ("if_es", "then_es", "if_en", "then_en")), (a["id"], f)
    out = A.outputs(model, annexes)
    assert len(out) == 4 + 2 * len(annexes)
    for key, (svg, paths) in out.items():
        for p in paths:
            assert p.read_text(encoding="utf-8") == svg, f"{p.relative_to(ROOT.parent)}: corre python -m tools.architecture"
        assert svg.startswith("<svg") and "<script" not in svg and "<foreignObject" not in svg
        assert REPO_HOST.lower() not in svg.lower(), key
    for a in annexes:
        for lang in ("es", "en"):
            svg = out[a["id"] + ("-en" if lang == "en" else "")][0]
            assert len(re.findall(r'data-node="', svg)) == len(a["nodes"])
            assert len(re.findall(r'data-edge="', svg)) == len(a["edges"])
            assert 'data-annex="full"' in svg, "cada anexo vuelve al completo"
            for n in a["nodes"]:
                for s in n.get("see", []):
                    assert f'data-annex="{s}"' in svg
    for key in ("full", "simple", "full-en", "simple-en"):
        for a in annexes:
            assert f'data-annex="{a["id"]}"' in out[key][0], f"{key}: falta la etiqueta {a['id']}"
    for d in A.ANNEX_DIRS:
        assert sorted(p.name for p in d.glob("*.svg")) == sorted(A.annex_file(a["id"], l) for a in annexes for l in ("es", "en"))
    page = A.EXPLORER.read_text(encoding="utf-8")
    assert page == A.render_explorer(model, annexes), "public/arquitectura.html: corre python -m tools.architecture"
    assert "<script>" not in page and "Content-Security-Policy" in page
    assert REPO_HOST.lower() not in page.lower()
    doc = A.DOC.read_text(encoding="utf-8")
    for a in annexes:
        assert f"](anexos/{a['id']}.svg)" in doc and f"#### Anexo {a['id'].upper()} · " in doc
    standalone = A.render_standalone(model, annexes)
    assert standalone.count("<template data-file=") == len(out) and "<script src=" not in standalone


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
            assert bool(n.get("details_es")) == bool(n.get("details_en")), f"{n['id']}: detalle en un solo idioma"
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
    assert doc == A.render_doc(model, doc, A.load_annexes()), "docs/arquitectura.md: corre python -m tools.architecture"
    for n in model["full"]["nodes"]:
        assert f"| **{n['name_es']}** |" in doc, f"{n['id']}: la caja no está en el texto de docs/arquitectura.md"
    # Las cuentas escritas a mano en el texto siguen al modelo.
    nf, ef = len(model["full"]["nodes"]), len(model["full"]["edges"])
    for found in re.findall(r"(\d+) (?:cajas|partes) y (\d+) conexiones", doc):
        assert found == (str(nf), str(ef)), f"docs/arquitectura.md dice {found}; el modelo tiene {nf} cajas y {ef} conexiones"
    assert f"{len(model['simple']['nodes'])} cajas para explicar" in doc


def _architecture():
    from tools import architecture as A

    model = json.loads(A.MODEL.read_text(encoding="utf-8"))
    return A, model, A.load_annexes()


def test_architecture_evidence_resolves():
    """Cada caja y cada conexión de los diagramas dice en qué parte del código está, y eso existe: el archivo, el
    símbolo de Python (``ruta.py#nombre``, ``#Clase.método``; nunca líneas, que se corren sin que nadie lo note),
    las líneas de un archivo que no es Python y las conexiones del completo que cita el simplificado. Lo mismo
    con las evidencias de los anexos, si las tienen. ``python -m tools.architecture --check`` hace la misma
    revisión."""
    A, model, annexes = _architecture()
    for part in ("full", "simple"):
        need = model[part]["edges"] + (model[part]["nodes"] if part == "full" else [])
        assert all(x.get("evidence") for x in need), [x.get("id") or (x["from"], x["to"]) for x in need if not x.get("evidence")]
    assert A.check_evidence(model, annexes) == []


def test_architecture_counts_come_from_the_code():
    """Los números que escribe el modelo salen del código (catálogos y listas fijas) y se cuentan aquí. Lo que sale
    de una medición (canales por URL, estados, cuántas responden) no se escribe en el modelo: cambia cada lunes y
    está en registry/ y en el sitio (Metodología y Noticias)."""
    import re

    from enso import news, observatory, registry
    from tools import peru_collector

    A, model, annexes = _architecture()
    full = {n["id"]: n for n in model["full"]["nodes"]}
    simple = {n["id"]: n for n in model["simple"]["nodes"]}
    edge = {(e["from"], e["to"]): e for e in model["full"]["edges"]}
    annex = {a["id"]: a for a in annexes}

    feeds = news.FEEDS
    covers = [f for f in feeds if f.covers]
    google = [f for f in feeds if "news.google.com" in f.url]
    rest = [f for f in feeds if not f.covers and f not in google]
    gov = [f for f in rest if f.kind == "gobierno"]
    radio = [f for f in rest if f.kind == "radio"]
    world = [f for f in rest if f.region == "mundo" and f not in gov + radio]
    regional = [f for f in rest if f.department and f not in gov + radio + world]
    national = [f for f in rest if f not in gov + radio + world + regional]
    pages = [s for s in registry.build(reach={})["sources"] if "se archiva desde el Perú" in s.get("notes", "")]
    enfen = observatory.SOURCE_BY_ID["enfen-comunicados"]
    expected = {
        "sources": len(observatory.SOURCES),
        "noaa": sum(1 for s in observatory.SOURCES if s.institution.startswith("NOAA")),
        "enfen-urls": len(enfen.urls),
        "feeds": len(feeds), "covers": len(covers), "google": len(google), "rest": len(rest),
        "not-covers": len(feeds) - len(covers),
        "gov": len(gov), "national": len(national), "regional": len(regional),
        "departments": len({f.department for f in regional}), "radio": len(radio),
        "rpp": sum(1 for f in radio if f.id.startswith("rpp")), "world": len(world),
        "g-department": sum(1 for f in google if f.kind == "agregador" and f.department),
        "g-national": sum(1 for f in google if f.kind == "agregador" and not f.department and f.region != "mundo"),
        "g-world": sum(1 for f in google if f.region == "mundo"),
        "g-outlets": sum(1 for f in google if f.kind != "agregador"),
        "pages": len(pages), "fixed-list": sum(len(u) for u in peru_collector.SOURCES.values()),
    }
    checks = [
        (full["publication-data"]["what_es"], r"estado de las (\d+) fuentes", "sources"),
        (full["publication-data"]["what_en"], r"status of the (\d+) sources", "sources"),
        (edge[("official-parse", "builder")]["explain_es"], r"datos de las (\d+) fuentes", "sources"),
        (edge[("official-parse", "builder")]["explain_en"], r"data of the (\d+) sources", "sources"),
        (full["registry-builder"]["what_es"], r"\((\d+) feeds, (?:\d+) fuentes ENSO", "feeds"),
        (full["registry-builder"]["what_es"], r"(\d+) fuentes ENSO", "sources"),
        (full["registry-builder"]["what_es"], r"(\d+) páginas del Perú", "pages"),
        (full["registry-builder"]["what_en"], r"\((\d+) feeds, ", "feeds"),
        (full["registry-builder"]["what_en"], r"(\d+) ENSO sources", "sources"),
        (full["registry-builder"]["what_en"], r"(\d+) Peru pages", "pages"),
        (full["noaa"]["what_es"], r"(\d+) productos de NOAA", "noaa"),
        (full["noaa"]["what_en"], r"(\d+) NOAA products", "noaa"),
        (edge[("noaa", "fetch")]["label_es"], r"(\d+) productos", "noaa"),
        (edge[("noaa", "fetch")]["label_en"], r"(\d+) products", "noaa"),
        (simple["s-fuentes"]["what_es"], r"(\d+) productos de NOAA", "noaa"),
        (simple["s-fuentes"]["what_en"], r"(\d+) NOAA products", "noaa"),
        (full["peru-official"]["details_es"], r"^(\d+) URL del ENFEN", "enfen-urls"),
        (full["peru-official"]["details_en"], r"^(\d+) ENFEN URLs", "enfen-urls"),
        (full["hazard-alerts"]["name_es"], r"\((\d+) fuentes\)", "covers"),
        (full["hazard-alerts"]["name_en"], r"\((\d+) sources\)", "covers"),
        (full["hazard-alerts"]["details_es"], r"Son (\d+) de los", "covers"),
        (full["hazard-alerts"]["details_es"], r"de los (\d+) feeds", "feeds"),
        (full["hazard-alerts"]["details_en"], r"These are (\d+) of the", "covers"),
        (full["hazard-alerts"]["details_en"], r"of the (\d+) feeds", "feeds"),
        (edge[("hazard-alerts", "fetch")]["label_es"], r"(\d+) fuentes de alertas", "covers"),
        (edge[("hazard-alerts", "fetch")]["label_en"], r"(\d+) alert sources", "covers"),
        (full["news-collect"]["what_es"], r"Lee los (\d+) feeds", "feeds"),
        (full["news-collect"]["what_en"], r"Reads the (\d+) feeds", "feeds"),
        (full["news-collect"]["details_es"], r"las (\d+) fuentes figuran", "covers"),
        (full["write-publication"]["details_es"], r"las (\d+) fuentes de alertas", "covers"),
        (full["write-publication"]["details_en"], r"the (\d+) alert sources", "covers"),
        (simple["s-fuentes"]["what_es"], r"(\d+) servicios de alertas", "covers"),
        (simple["s-fuentes"]["what_en"], r"(\d+) alert services", "covers"),
        (full["news-feeds"]["name_es"], r"(\d+) feeds de noticias", "rest"),
        (full["news-feeds"]["name_en"], r"(\d+) news feeds", "rest"),
        (edge[("news-feeds", "fetch")]["label_es"], r"(\d+) feeds de noticias", "rest"),
        (edge[("news-feeds", "fetch")]["label_en"], r"(\d+) news feeds", "rest"),
        (full["news-feeds"]["what_es"], r"del Estado \((\d+),", "gov"),
        (full["news-feeds"]["what_es"], r"nacionales \((\d+)\)", "national"),
        (full["news-feeds"]["what_es"], r"de (\d+) departamentos", "departments"),
        (full["news-feeds"]["what_es"], r"departamentos \((\d+)\)", "regional"),
        (full["news-feeds"]["what_es"], r"radios \((\d+),", "radio"),
        (full["news-feeds"]["what_es"], r"(\d+) de RPP", "rpp"),
        (full["news-feeds"]["what_es"], r"internacionales \((\d+)\)", "world"),
        (full["news-feeds"]["what_en"], r"government \((\d+),", "gov"),
        (full["news-feeds"]["what_en"], r"national media \((\d+)\)", "national"),
        (full["news-feeds"]["what_en"], r"in (\d+) departments", "departments"),
        (full["news-feeds"]["what_en"], r"departments \((\d+)\)", "regional"),
        (full["news-feeds"]["what_en"], r"radio stations \((\d+),", "radio"),
        (full["news-feeds"]["what_en"], r"(\d+) from RPP", "rpp"),
        (full["news-feeds"]["what_en"], r"international outlets \((\d+)\)", "world"),
        (full["news-google"]["name_es"], r"(\d+) búsquedas", "google"),
        (full["news-google"]["name_en"], r"(\d+) searches", "google"),
        (edge[("news-google", "fetch")]["explain_es"], r"estos (\d+) feeds", "google"),
        (edge[("news-google", "fetch")]["explain_en"], r"these (\d+) feeds", "google"),
        (full["news-google"]["what_es"], r"por departamento \((\d+)\)", "g-department"),
        (full["news-google"]["what_es"], r"nacionales \((\d+)\)", "g-national"),
        (full["news-google"]["what_es"], r"mundial \((\d+)\)", "g-world"),
        (full["news-google"]["what_es"], r"sin feed propio \((\d+),", "g-outlets"),
        (full["news-google"]["what_en"], r"per department \((\d+)\)", "g-department"),
        (full["news-google"]["what_en"], r"national \((\d+)\)", "g-national"),
        (full["news-google"]["what_en"], r"worldwide \((\d+)\)", "g-world"),
        (full["news-google"]["what_en"], r"own feed \((\d+),", "g-outlets"),
        (simple["s-noticias"]["what_es"], r"^(\d+) feeds", "not-covers"),
        (simple["s-noticias"]["what_en"], r"^(\d+) feeds", "not-covers"),
        (model["walkthrough"][0]["text_es"], r"(\d+) servicios de alertas", "covers"),
        (model["walkthrough"][0]["text_es"], r"(\d+) feeds de noticias", "not-covers"),
        (model["walkthrough"][0]["text_en"], r"(\d+) hazard-alert services", "covers"),
        (model["walkthrough"][0]["text_en"], r"(\d+) news feeds", "not-covers"),
        (full["peru-archive-pages"]["details_es"], r"(\d+) URL de la lista fija", "pages"),
        (full["peru-archive-pages"]["details_en"], r"(\d+) URLs on the Peru collector's fixed list", "pages"),
        (edge[("peru-archive-pages", "peru-collector")]["explain_es"], r"las (\d+) páginas de su lista fija", "pages"),
        (edge[("peru-archive-pages", "peru-collector")]["explain_en"], r"these (\d+) fixed-list pages", "pages"),
        (annex["a1"]["nodes"][12]["what_es"], r"(\d+) páginas del Perú", "pages"),
        (annex["a1"]["nodes"][12]["what_en"], r"(\d+) Peru pages", "pages"),
        (annex["a2"]["nodes"][14]["what_es"], r"Las (\d+) páginas de su lista fija", "pages"),
        (annex["a2"]["nodes"][14]["what_en"], r"The (\d+) pages on its fixed list", "pages"),
        (full["peru-collector"]["details_es"], r"(\d+) URL de su lista fija", "fixed-list"),
        (full["peru-collector"]["details_en"], r"(\d+) URLs on its fixed list", "fixed-list"),
    ]
    for text, pattern, key in checks:
        found = re.search(pattern, text)
        assert found, f"el modelo ya no dice {pattern!r}: {text[:120]}…"
        assert int(found[1]) == expected[key], f"{pattern!r}: el modelo dice {found[1]}, el código da {expected[key]} ({key})"


def test_architecture_names_the_n8n_flows_and_the_pipeline_secrets():
    """Cada flujo de n8n/dist está en el diagrama completo con su nombre, la caja del colega dice cuántos son, y
    cada secreto que observatory.yml le pasa al paso del pipeline está en la caja de la actualización diaria."""
    import re

    import yaml
    from conftest import ROOT

    A, model, _ = _architecture()
    full = {n["id"]: n for n in model["full"]["nodes"]}
    dist = sorted((ROOT.parent / "n8n" / "dist").glob("*.json"))
    assert dist, "faltan los flujos de n8n/dist"
    names = [json.loads(p.read_text(encoding="utf-8"))["name"] for p in dist]
    for lang in ("es", "en"):
        text = " ".join(str(n.get(f"{k}_{lang}", "")) for n in model["full"]["nodes"] for k in ("name", "what", "meta", "details"))
        for name in names:
            assert name in text, f"el flujo «{name}» no está en el diagrama completo ({lang})"
    colleague = full["n8n-colleague"]
    assert int(re.search(r"(\d+) flujos de n8n/dist", colleague["what_es"])[1]) == len(dist)
    assert int(re.search(r"(\d+) n8n/dist flows", colleague["what_en"])[1]) == len(dist)
    wf = yaml.safe_load((ROOT.parent / ".github" / "workflows" / "observatory.yml").read_text(encoding="utf-8"))
    step = next(s for s in wf["jobs"]["build"]["steps"] if s.get("id") == "pipeline")
    secrets = set(re.findall(r"secrets\.(\w+)", json.dumps(step)))
    assert secrets, "el paso del pipeline ya no recibe secretos: revisar esta prueba"
    for name in secrets:
        for lang in ("es", "en"):
            assert name in full["observatory-workflow"][f"details_{lang}"], f"{name} no está en la actualización diaria ({lang})"


def test_architecture_module_table_lists_every_module():
    """La tabla «Pipeline (python/enso/)» de docs/arquitectura.md tiene una fila para cada módulo."""
    from conftest import ROOT

    A, _, _ = _architecture()
    doc = A.DOC.read_text(encoding="utf-8")
    section = doc.split("## Pipeline (`python/enso/`)", 1)[1].split("\n## ", 1)[0]
    table = "\n".join(line for line in section.splitlines() if line.startswith("| `"))
    pkg = ROOT / "enso"
    modules = [p.name for p in pkg.glob("*.py")] + [f"feeds/{p.name}" for p in (pkg / "feeds").glob("*.py")]
    missing = [m for m in modules if not m.endswith("__init__.py") and f"`{m}`" not in table]
    assert not missing, f"docs/arquitectura.md: faltan en la tabla de módulos {missing}"


def test_architecture_fetch_box_names_every_channel():
    """La caja de la descarga en Actions nombra cada canal con que fetch.py puede entregar una respuesta."""
    import ast

    from conftest import ROOT

    A, model, _ = _architecture()
    fetch = next(n for n in model["full"]["nodes"] if n["id"] == "fetch")
    tree = ast.parse((ROOT / "enso" / "fetch.py").read_text(encoding="utf-8"))
    channels = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Response" and len(node.args) > 2:
            channels |= {c.value for c in ast.walk(node.args[2]) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == "channel" for t in node.targets):
            channels |= {c.value for c in ast.walk(node.value)
                         if isinstance(c, ast.Constant) and isinstance(c.value, str) and "-" in c.value}
    assert {"direct", "relay-peru", "relay-manual", "archive"} <= channels, channels
    for lang in ("es", "en"):
        missing = [c for c in sorted(channels) if c not in fetch[f"details_{lang}"]]
        assert not missing, f"la caja «fetch» no nombra los canales {missing} ({lang})"


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
