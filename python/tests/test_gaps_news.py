"""Huecos de cobertura en ``enso.news`` que dejaban vivas mutaciones plausibles (cada prueba nombra la suya).

- ``_foreign_outlet``: un medio extranjero (``.uy``, ``.cl``, ``.com.ar``) en una búsqueda peruana de Google
  Noticias se descarta solo si la nota no nombra al Perú. Copias reales ``sources/news-gnews-04.xml`` y
  ``sources/news-gnews-peligros-nacional.xml``: «Sismo en Perú en directo…» de Uruguay Al Día y «Riesgo para el
  agua potable por El Niño en Perú» de Identidad Correntina son del Perú. Mutación: quitar ``not named_peru``.
- ``_published``: una fecha del futuro se reemplaza por la de la lectura y se cuenta en ``futureDates``.
  Mutación: quitar el incremento.
- ``_history_index``: la corrección remite al ``id`` de la primera versión del histórico, aunque haya copias
  viejas sin ``revises`` (tres líneas reales de Gestión, ``news-identity/gestion-titulares-2026.jsonl``) o
  aunque el histórico empiece por una línea que ya es corrección (USGS, ``news-identity/usgs-sismos-*``).
  Mutaciones: ``setdefault`` por asignación; quitar el ``h.get("revises") or``.
- ``_geo_hint``: las categorías de un medio regional son sus secciones y no ubican la nota (copia real
  ``sources/news-soltv-piura.xml``, departamento 20). Mutación: quitar ``not f.department``.
- ``_note_channel``: una copia arrastrada por el recolector dice que el servidor no responde
  (``upstreamDown``). Mutación: no copiar ``upstreamDown``.
- ``_entry_text``: con ``max_age_days``, una entrada sin fecha se descarta (no se sabe si es de hace años).
  Mutación: dejar pasar las entradas sin fecha.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from conftest import FIX, ROOT

from enso import news as N

IDENT = ROOT / "tests" / "fixtures" / "news-identity"
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def _collect(feed: N.Feed, body: bytes, now: datetime = NOW, via: dict | None = None):
    got = (200, body, "", "") + ((via,) if via is not None else ())
    found, status, _ = N.collect(lambda url: got, now, feeds=[feed])
    return found, status[0]


def _raw_item(xml: str, source_host: str) -> tuple[str, str]:
    """Titular y URL del medio del <item> de ``source_host``, leídos con una expresión aparte (no con el lector)."""
    m = re.search(r"<item>(?:(?!</item>).)*?<title>([^<]*)</title>(?:(?!</item>).)*?<source url=\"(https?://[^\"]*"
                  + re.escape(source_host) + r")\"", xml, re.DOTALL)
    assert m, source_host
    return m.group(1), m.group(2)


def test_foreign_outlet_that_names_peru_is_kept():
    for fid, host, word in (("gnews-04", "uruguayaldia.com.uy", "Sismo en Perú en directo"),
                            ("gnews-peligros-nacional", "identidadcorrentina.com.ar", "Riesgo para el agua potable"),
                            ("gnews-peligros-nacional", "laconexion.cl", "influenza aviar en Perú")):
        xml = (FIX / f"news-{fid}.xml").read_text(encoding="utf-8")
        title, outlet_url = _raw_item(xml, host)
        # El dominio es de otro país y el titular nombra al Perú: es una nota sobre el Perú.
        assert N.FOREIGN_TLD_RE.search(outlet_url) and "Perú" in title and word in title
        found, st = _collect(N.FEED_BY_ID[fid], xml.encode("utf-8"))
        assert st["ok"]
        assert any(word in i["title"] for i in found), (fid, host)


def test_foreign_outlet_that_does_not_name_peru_is_dropped():
    # Contraparte: el Jaén de España (diariojaen.es) en la búsqueda del Jaén de Cajamarca no entra.
    xml = (FIX / "news-gnews-06.xml").read_text(encoding="utf-8")
    title, outlet_url = _raw_item(xml, "diariojaen.es")
    assert N.FOREIGN_TLD_RE.search(outlet_url) and "Perú" not in title
    found, st = _collect(N.FEED_BY_ID["gnews-06"], xml.encode("utf-8"))
    assert st["ok"] and not any("diariojaen" in i["outlet"].lower() or "Diario Jaén" in i["outlet"] for i in found)


def _rss(items: str) -> bytes:
    return f"<?xml version='1.0'?><rss version='2.0'><channel><title>t</title>{items}</channel></rss>".encode()


def test_future_date_is_replaced_and_counted():
    # NOW = 21-10-2026 12:00 UTC: el límite es NOW + 2 h = 14:00 UTC. La nota de las 15:00 UTC viene del futuro
    # (1 fecha futura) y la de las 11:00 UTC no: futureDates = 1, y la futura toma la hora de la lectura.
    feed = N.Feed("t", "T", "peru", "https://t.pe/feed", scope="hazard")
    rss = _rss("<item><title>Huaico en Chosica</title><link>https://t.pe/1</link>"
               "<pubDate>Wed, 21 Oct 2026 15:00:00 +0000</pubDate></item>"
               "<item><title>Huaico en Matucana</title><link>https://t.pe/2</link>"
               "<pubDate>Wed, 21 Oct 2026 11:00:00 +0000</pubDate></item>")
    st, items, _ = N._read_feed(feed, lambda url: (200, rss, "", ""), NOW)
    assert st["futureDates"] == 1
    by_title = {i["title"]: i["published"] for i in items}
    assert by_title["Huaico en Chosica"] == "2026-10-21T12:00:00+00:00"
    assert by_title["Huaico en Matucana"].startswith("2026-10-21T11:00:00")


def test_undated_entry_is_dropped_when_the_feed_has_an_age_limit():
    # max_age_days=30: lo más antiguo admitido es el 21-09-2026. La nota sin fecha no se puede fechar: fuera.
    feed = N.Feed("t", "T", "peru", "https://t.pe/feed", scope="hazard", max_age_days=30)
    rss = _rss("<item><title>Huaico en Surco</title><link>https://t.pe/3</link></item>")
    st, items, _ = N._read_feed(feed, lambda url: (200, rss, "", ""), NOW)
    assert st["ok"] and items == []
    # Sin límite de antigüedad la misma entrada sí entra (la regla es solo para feeds con ``max_age_days``).
    st, items, _ = N._read_feed(N.Feed("t", "T", "peru", "https://t.pe/feed", scope="hazard"),
                                lambda url: (200, rss, "", ""), NOW)
    assert [i["title"] for i in items] == ["Huaico en Surco"]


def test_revision_points_to_the_first_version_among_old_copies_without_revises():
    # Tres líneas reales de Gestión con el mismo enlace y tres titulares, sin ``revises`` (anteriores a esa
    # marca). La primera por first_seen es 4172f224356ff9af (21-10 19:48): una cuarta versión remite a ella.
    rows = N.read_jsonl((IDENT / "gestion-titulares-2026.jsonl").read_text(encoding="utf-8"))
    assert [r["id"] for r in rows] == ["4172f224356ff9af", "a776740e2736b9a9", "6919b95fc0956ba7"]
    assert not any(r.get("revises") for r in rows)
    fourth = dict(rows[-1], id="cuarta", title="MMG acelera Sulfobamba en Las Bambas", first_seen="2026-10-27T00:00:00+00:00")
    added = N.new_lines(rows, [fourth])
    assert len(added) == 1 and added[0]["revises"] == "4172f224356ff9af"


def test_revision_follows_revises_when_history_starts_with_a_correction():
    # Histórico recortado: solo queda la línea corregida del sismo us6000u1kt (magnitud 5,3), que remite a la
    # primera (5,2). Otra corrección (5,4) también remite a la primera, no a la línea que quedó.
    t1, t2 = datetime(2026, 10, 21, 20, 0, tzinfo=timezone.utc), datetime(2026, 10, 23, 3, 0, tzinfo=timezone.utc)
    feed = N.FEED_BY_ID["usgs-sismos"]
    first, _ = _collect(feed, (IDENT / "usgs-sismos-2026-10-21.json").read_bytes(), t1)
    second, _ = _collect(feed, (IDENT / "usgs-sismos-2026-10-23.json").read_bytes(), t2)
    hist = N.new_lines([], first)
    old = next(i for i in hist if i["link"].endswith("/us6000u1kt"))
    rev = next(i for i in N.new_lines(hist, second) if i["link"].endswith("/us6000u1kt"))
    assert rev["revises"] == old["id"] and rev["id"] != old["id"]
    third = dict(rev, id="otro", title=rev["title"].replace("5.3", "5.4"), first_seen="2026-10-24T03:00:00+00:00")
    third.pop("revises")
    assert N.new_lines([rev], [third])[0]["revises"] == old["id"]


def test_regional_outlet_categories_are_not_a_place_hint():
    # Sol TV Piura cubre el departamento 20: sus categorías («Noticias», «Piura», «Nacional») son secciones.
    feed = N.FEED_BY_ID["soltv-piura"]
    assert feed.department == "20"
    xml = (FIX / feed.fixture).read_text(encoding="utf-8")
    assert len(re.findall(r"<category>", xml)) >= 10  # la copia trae categorías en sus entradas
    found, st = _collect(feed, xml.encode("utf-8"))
    assert st["ok"] and found
    assert not any("categories" in (i.get("geoHint") or {}) for i in found)


def test_national_outlet_categories_are_a_place_hint():
    # Contraparte sintética (no hay copia real de un medio nacional con categorías): sin ``department`` las
    # categorías sí se guardan como pista de lugar.
    feed = N.Feed("t", "T", "peru", "https://t.pe/feed", scope="hazard")
    rss = _rss("<item><title>Huaico en Chosica</title><link>https://t.pe/1</link><category>Lima</category>"
               "<pubDate>Wed, 21 Oct 2026 11:00:00 +0000</pubDate></item>")
    _, items, _ = N._read_feed(feed, lambda url: (200, rss, "", ""), NOW)
    assert items and items[0]["geoHint"]["categories"] == ["Lima"]


def test_carried_copy_reports_upstream_down():
    # n8n arrastró su copia del 19-11 porque el servidor respondió HTTP 500 (CENVUL, 20-11-2026).
    feed = N.FEED_BY_ID["soltv-piura"]
    body = (FIX / feed.fixture).read_bytes()
    via = {"channel": "n8n", "copyAt": "2026-11-19T03:52:36+00:00", "upstreamDown": {"status": 500}}
    _, st = _collect(feed, body, via=via)
    assert st["channel"] == "n8n" and st["copyAt"] == "2026-11-19T03:52:36+00:00"
    assert st["upstreamDown"] == {"status": 500}
    _, fresh = _collect(feed, body, via={"channel": "n8n", "copyAt": "2026-11-19T03:52:36+00:00"})
    assert "upstreamDown" not in fresh


def test_foreign_outlet_is_kept_in_a_world_feed():
    # La Tercera (latercera.cl) pasa FOREIGN_TLD_RE (``.cl`` al final) y el titular no nombra al Perú: en una
    # búsqueda peruana se descartaría; en una del mundo es justo lo que se busca y entra (1 nota de 1).
    item = ("<item><title>El Niño costero eleva el mar frente a Chile</title><link>https://news.google.com/x/1</link>"
            "<pubDate>Wed, 21 Oct 2026 11:00:00 +0000</pubDate>"
            "<source url=\"https://www.latercera.cl\">La Tercera</source></item>")
    title = "El Niño costero eleva el mar frente a Chile"
    assert N.FOREIGN_TLD_RE.search("https://www.latercera.cl") and not N.PERU_WORD_RE.search(title)
    feed = N.Feed("t", "T", "mundo", "https://news.google.com/rss/search?q=x", scope="enso")
    st, items, _ = N._read_feed(feed, lambda url: (200, _rss(item), "", ""), NOW)
    assert st["ok"] and [i["title"] for i in items] == [title]
