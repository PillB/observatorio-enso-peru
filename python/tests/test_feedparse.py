"""Lector tolerante de feeds y ubicación de noticias en el Perú."""

from datetime import datetime, timezone

import pytest

from enso import feedparse as F
from enso.geo import gazetteer

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title>Diario</title><link>https://diario.pe/</link>
{items}
</channel></rss>"""
ITEM = "<item><title>{t}</title><link>{l}</link><pubDate>{d}</pubDate><description>{s}</description></item>"


def rss(*items: str, wrap: str = RSS) -> bytes:
    return wrap.format(items="\n".join(items)).encode("utf-8")


def one(title="Lluvias en Piura", link="https://diario.pe/a", date="Tue, 20 Oct 2026 10:00:00 -0500", summ="Resumen."):
    return ITEM.format(t=title, l=link, d=date, s=summ)


def test_clean_feed_has_no_repairs():
    p = F.parse(rss(one()), now=NOW)
    assert p.format == "rss2.0" and p.repairs == [] and len(p.items) == 1
    assert p.items[0]["published"] == "2026-10-20T15:00:00+00:00"


@pytest.mark.parametrize("body,repair", [
    (b"\xef\xbb\xbf" + rss(one()), None),
    (b"\n\n<br />\n<b>Warning</b>: Cannot modify header information in feed.php\n" + rss(one()), "texto antes del XML"),
    (rss(one()) + b"\n<!-- cache 0.2s --><script>x()</script>", "texto después del XML"),
    (rss(one(title="Huaico&nbsp;en Chosica &mdash; reporte")), "entidades HTML"),
    (rss(one(title="Agua & desagüe en Tumbes")), "& sin escapar"),
    (rss(one(title="Friaje\x0b en Puno")), "caracteres de control"),
])
def test_common_defects_are_repaired(body, repair):
    p = F.parse(body, now=NOW)
    assert len(p.items) == 1 and p.items[0]["title"]
    if repair:
        assert repair in p.repairs
    assert "&nbsp;" not in p.items[0]["title"] and "&mdash;" not in p.items[0]["title"]


def test_entities_inside_cdata_are_left_alone():
    p = F.parse(rss(one(summ="<![CDATA[<p>Lluvias &nbsp; y huaicos & más</p>]]>")), now=NOW)
    assert p.repairs == [] and "huaicos & más" in p.items[0]["summary"]


def test_wrong_declared_encoding_is_read_as_windows_1252():
    body = rss(one(title="Huánuco: crecida del río")).replace(b'encoding="UTF-8"', b'encoding="UTF-8"')
    body = body.decode().encode("cp1252")
    p = F.parse(body, now=NOW)
    assert p.items[0]["title"] == "Huánuco: crecida del río"
    assert any("windows-1252" in r for r in p.repairs)


def test_latin1_declared_encoding():
    body = rss(one(title="Áncash")).decode().replace('encoding="UTF-8"', 'encoding="ISO-8859-1"').encode("latin-1")
    assert F.parse(body, now=NOW).items[0]["title"] == "Áncash"


def test_truncated_feed_keeps_complete_items():
    full = rss(one(link="https://d.pe/1"), one(link="https://d.pe/2"), one(link="https://d.pe/3"))
    cut = full[: full.rfind(b"<item>") + 40]
    p = F.parse(cut, now=NOW)
    assert [i["link"] for i in p.items] == ["https://d.pe/1", "https://d.pe/2"]
    assert any("recuperadas una por una" in r for r in p.repairs)


def test_one_broken_item_does_not_sink_the_feed():
    p = F.parse(rss(one(link="https://d.pe/1"), "<item><title>Roto <b>sin cerrar</title><link>https://d.pe/x</link></item>",
                    one(link="https://d.pe/2")), now=NOW)
    assert [i["link"] for i in p.items] == ["https://d.pe/1", "https://d.pe/2"]


def test_relative_links_guid_and_feedburner():
    p = F.parse(rss(
        one(link="/noticias/lluvias-123"),
        "<item><title>Sin link</title><guid>https://diario.pe/guid-1</guid></item>",
        "<item><title>Solo guid interno</title><guid isPermaLink=\"false\">abc-1</guid></item>",
        '<item xmlns:feedburner="http://rssnamespace.org/feedburner/ext/1.0"><title>FB</title>'
        "<link>https://feeds.feedburner.com/x/1</link><feedburner:origLink>https://diario.pe/real</feedburner:origLink></item>",
        "<item><title>Protocolo relativo</title><link>//diario.pe/b</link></item>",
    ), now=NOW)
    links = [i["link"] for i in p.items]
    assert links == ["https://diario.pe/noticias/lluvias-123", "https://diario.pe/guid-1", "https://diario.pe/real",
                     "https://diario.pe/b"]


def test_duplicate_links_are_dropped():
    assert len(F.parse(rss(one(), one()), now=NOW).items) == 1


def test_atom_and_rss1_and_jsonfeed():
    atom = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>A</title>
    <link rel="alternate" href="https://a.pe/"/><entry><title>Heladas en Puno</title><link href="/n/1"/>
    <updated>2026-10-20T08:00:00-05:00</updated><summary>Texto</summary><category term="Puno"/></entry></feed>"""
    p = F.parse(atom, now=NOW)
    assert p.format == "atom" and p.items[0]["link"] == "https://a.pe/n/1" and p.items[0]["categories"] == ["Puno"]
    rdf = b"""<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title>R</title></channel>
    <item><title>Oleaje</title><link>https://r.pe/1</link><dc:date>2026-10-19T10:00:00Z</dc:date></item></rdf:RDF>"""
    p = F.parse(rdf, now=NOW)
    assert p.format == "rss1" and p.items[0]["published"] == "2026-10-19T10:00:00+00:00"
    js = b'{"version":"https://jsonfeed.org/version/1.1","title":"J","items":[{"url":"https://j.pe/1",' \
         b'"title":"Sequ\\u00eda en Tacna","date_published":"2026-10-18T10:00:00-05:00","tags":["Tacna"]}]}'
    p = F.parse(js, now=NOW)
    assert p.format == "jsonfeed" and p.items[0]["title"] == "Sequía en Tacna"


@pytest.mark.parametrize("body,msg", [
    (b"<!DOCTYPE html><html><head><title>Inicio</title></head><body>Portal</body></html>", "HTML"),
    (b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">]><rss><channel></channel></rss>', "entidades"),
    (b"", "vacía"),
    (b"<rss><channel><title>x</title>", "recuperables"),
    (b'<?xml version="1.0"?><urlset><url><loc>https://x</loc></url></urlset>', "raíz"),
])
def test_unrepairable_inputs_raise(body, msg):
    with pytest.raises(F.FeedError, match=msg):
        F.parse(body, now=NOW)


@pytest.mark.parametrize("text,expected", [
    ("Tue, 20 Oct 2026 10:00:00 -0500", "2026-10-20T15:00:00+00:00"),
    ("Mar, 20 Oct 2026 10:00:00 -0500", "2026-10-20T15:00:00+00:00"),
    ("Mié, 21 Oct 2026 08:00:00 -05:00", "2026-10-21T13:00:00+00:00"),
    ("Tue, 20 Oct 2026 10:00:00 PET", "2026-10-20T15:00:00+00:00"),
    ("20 Oct 2026 10:00 GMT-5", "2026-10-20T15:00:00+00:00"),
    ("20 de octubre de 2026, 3:15 p.m.", "2026-10-20T20:15:00+00:00"),
    ("Martes 20 de Setiembre del 2026", "2026-09-20T05:00:00+00:00"),
    ("2026-10-20 10:00:00", "2026-10-20T15:00:00+00:00"),
    ("2026-10-20T10:00:00Z", "2026-10-20T10:00:00+00:00"),
    ("2026/10/20", "2026-10-20T05:00:00+00:00"),
    ("1792508400", "2026-10-20T15:00:00+00:00"),
    ("Sat, 01 Jan 1900 00:00:00 GMT", None),
    ("mañana", None),
])
def test_dates(text, expected):
    assert F.parse_date(text, F.LIMA, NOW) == expected


# --- Ubicación --------------------------------------------------------------

@pytest.mark.parametrize("text,peru,dep,places", [
    ("Huaico en Chosica deja familias damnificadas", True, None, ["Lurigancho"]),
    ("Lluvias intensas en Piura: desborde del río en Sullana", True, None, ["Sullana"]),
    ("Sullana: alerta por crecida del río Chira", True, None, ["Sullana"]),
    ("Senamhi prevé lluvias en Cusco, Puno y Apurímac", True, None, ["Cusco", "Puno", "Apurímac"]),
    ("Friaje afecta a Madre de Dios", True, None, ["Madre de Dios"]),
    ("Lluvias en San Martín afectan la carretera en Moyobamba", True, None, ["Moyobamba"]),
    ("Llueve en la provincia de Santa, Áncash", True, None, ["Santa"]),
    ("Peru braces for El Niño as Piura floods", False, None, ["Piura"]),
    ("Alcalde evalúa daños por lluvias", True, "21", ["Puno"]),
])
def test_places(text, peru, dep, places):
    tag = gazetteer().tag([text], peru, dep)
    assert tag and [p["name"] for p in tag["places"]] == places


@pytest.mark.parametrize("text,peru", [
    ("Evo Morales habla de El Niño", True),          # apellido, no el distrito de San Martín
    ("Inundación en Florida tras el huracán", False),  # Estados Unidos
    ("Piura floods", False),                           # sin mencionar al Perú en un medio internacional
    ("una mala temporada de lluvias", True),           # palabra común en minúsculas
    ("Pedro Castillo y Santa Rosa", True),             # nombres ambiguos sin respaldo
])
def test_no_false_places(text, peru):
    assert gazetteer().tag([text], peru) is None


def test_gazetteer_covers_every_level():
    g = gazetteer()
    assert len(g.deps) == 25 and len(g.provs) == 196 and len(g.dists) >= 1890
    # Todos los códigos son UBIGEO válidos y cada uno se puede rotular (los distritos nuevos sin código
    # INEI en la fuente reciben el siguiente número libre de su provincia).
    for code in [*g.deps, *g.provs, *g.dists]:
        assert code.isdigit() and len(code) in (2, 4, 6) and g.label(code)["name"]
    assert g.label("180107")["name"] == "San Antonio" and g.label("180107")["province"] == "Mariscal Nieto"
    assert g.label("200601")["province"] == "Sullana"


def test_gobpe_listing_adapter():
    """Las notas de gob.pe (sin RSS) se leen del listado HTML con el mismo formato que un feed."""
    from conftest import FIX

    body = (FIX.parent / "news-probe" / "gobpe-indeci.html").read_bytes()
    p = F.parse(body, "https://www.gob.pe/institucion/indeci/noticias", adapter="gobpe", now=NOW)
    assert p.format == "gobpe-html" and len(p.items) >= 20
    assert all(i["link"].startswith("https://www.gob.pe/institucion/") for i in p.items)
    assert sum("/indeci/" in i["link"] for i in p.items) >= len(p.items) - 2  # gob.pe intercala notas afines
    assert all(i["published"] and i["published"] <= "2026-10-21" for i in p.items)
    assert p.items == sorted(p.items, key=lambda i: i["published"], reverse=True)
    with pytest.raises(F.FeedError):
        F.parse(b"<html><body>Mantenimiento gob.pe</body></html>", adapter="gobpe", now=NOW)
