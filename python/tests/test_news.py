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
    assert N.relevance(gen, "Senamhi: lluvias intensas en Piura", "") is None  # medio general: exige término ENSO
    assert N.relevance(gen, "La Niña podría llegar en 2027", "") == "enso"
    assert N.relevance(haz, "Flood alert in Peru", "Heavy rain in Piura") == "impacto"
    assert N.relevance(haz, "Flood alert in Spain", "") is None  # feed del mundo: debe mencionar el Perú


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
