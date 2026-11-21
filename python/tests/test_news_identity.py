"""Identidad de las notas: la misma nota con otro enlace o titular no se repite en el histórico, y una corrección
del titular se muestra en su última versión (``news.canonical_link``, ``news.new_lines``, ``news.latest_versions``).

Las copias son respuestas reales de data-archive (``fixtures/news-identity``):

- ``pro-y-contra-2026-11-10-{https,http-www}.xml``: el mismo feed el mismo día, una vez con enlaces
  ``https://proycontra.com.pe/…`` y otra con ``http://www.proycontra.com.pe/…`` (el servidor arma los enlaces con
  el esquema y el servidor del pedido). Antes, cada variante entraba al histórico como otra nota: la nota
  «Defensora ambiental…» quedó cuatro veces.
- ``usgs-sismos-2026-10-{21,23}.json``: el USGS revisó el sismo ``us6000u1kt`` (magnitud 5,2 a 18 km al SSE de
  Camaná → 5,3 a 28 km al SSO). Antes, el grupo mostraba la primera versión.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from conftest import ROOT

from enso import news as N

FIX = ROOT / "tests" / "fixtures" / "news-identity"


def _collect(fid: str, body: bytes, now: datetime) -> list[dict]:
    feed = N.FEED_BY_ID[fid]
    found, status, _ = N.collect(lambda url: (200, body, "", ""), now, feeds=[feed])
    assert status[0]["ok"], status[0]
    return found


def _paths(xml: bytes) -> list[str]:
    """Las rutas de los enlaces de cada <item>, leídas con una expresión aparte (no con el lector del sitio)."""
    return re.findall(r"<item>.*?<link>https?://(?:www\.)?proycontra\.com\.pe(/[^<]+)</link>", xml.decode("utf-8", "replace"), re.S)


def test_canonical_link_joins_server_variants_and_keeps_what_identifies():
    same = ["https://proycontra.com.pe/noticias/x", "http://www.proycontra.com.pe/noticias/x",
            "HTTPS://WWW.ProyContra.com.pe:443/noticias/x/", "https://proycontra.com.pe/noticias/x?utm_source=fb&fbclid=1"]
    assert len({N.canonical_link(u) for u in same}) == 1
    assert N.canonical_link(same[1]) == "https://proycontra.com.pe/noticias/x"
    # Lo que distingue una nota de otra se conserva.
    assert N.canonical_link("https://www.dhn.mil.pe/portal/avisos-especiales#5355") != \
        N.canonical_link("https://www.dhn.mil.pe/portal/avisos-especiales#5356")
    assert N.canonical_link("https://news.google.com/rss/articles/CBMiAbC?oc=5") != \
        N.canonical_link("https://news.google.com/rss/articles/CBMiabc?oc=5")  # base64: distingue mayúsculas
    assert N.canonical_link("https://www.gdacs.org/report.aspx?eventtype=WF&eventid=1032724") != \
        N.canonical_link("https://www.gdacs.org/report.aspx?eventtype=WF&eventid=1032725")
    assert N.canonical_link("https://a.pe:8443/x") != N.canonical_link("https://a.pe/x")
    assert N.canonical_link("") == "" and N.canonical_link("mailto:a@b.pe") == "mailto:a@b.pe"


def _proycontra_path(link: str) -> str:
    """El enlace sin esquema ni servidor (la parte que no cambia entre las dos copias)."""
    return re.sub(r"^https?://(www\.)?proycontra\.com\.pe", "", link)


def _proycontra_copies() -> tuple[list[dict], list[dict]]:
    """Las dos copias del mismo día leídas por el lector del sitio: casi las mismas notas, con otros id."""
    a_xml = (FIX / "pro-y-contra-2026-11-10-https.xml").read_bytes()
    b_xml = (FIX / "pro-y-contra-2026-11-10-http-www.xml").read_bytes()
    common = set(_paths(a_xml)) & set(_paths(b_xml))
    assert len(common) >= 40, "las dos copias traen casi las mismas notas"
    a = _collect("pro-y-contra", a_xml, datetime(2026, 11, 10, 6, 0, tzinfo=timezone.utc))
    b = _collect("pro-y-contra", b_xml, datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc))
    assert a and b and {i["id"] for i in a}.isdisjoint({i["id"] for i in b}), "los id cambian con el enlace"
    return a, b


def _repeated(a: list[dict], b: list[dict]) -> tuple[set[str], list[dict]]:
    """Las rutas de la primera copia y las notas de la segunda que ya estaban en la primera."""
    in_a = {_proycontra_path(i["link"]) for i in a}
    return in_a, [i for i in b if _proycontra_path(i["link"]) in in_a]


def _assert_only_new_stories_added(added: list[dict], in_a: set[str]) -> None:
    """Lo agregado es solo lo que no estaba en la primera copia, y nada como corrección."""
    assert not added or all(_proycontra_path(i["link"]) not in in_a for i in added)
    assert not any(i.get("revises") for i in added)


def _cluster_links(items: list[dict], now: datetime) -> list[str]:
    """Los enlaces que muestran los grupos de esas notas."""
    return [link["url"] for g in N.cluster(items, now) for link in g["links"]]


def test_same_feed_with_other_scheme_and_host_adds_nothing():
    a, b = _proycontra_copies()
    hist = N.new_lines([], a)
    skipped: list[dict] = []
    added = N.new_lines(hist, b, skipped=skipped)
    in_a, again = _repeated(a, b)
    assert again, "hay notas relevantes en las dos copias"
    assert {i["id"] for i in skipped} == {i["id"] for i in again}
    _assert_only_new_stories_added(added, in_a)
    # El grupo muestra una sola vez cada nota aunque el histórico viejo tenga las dos copias.
    links = _cluster_links(a + b, datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc))
    assert len(links) == len({N.canonical_link(u) for u in links})


def test_usgs_revision_is_kept_and_the_latest_is_shown():
    raw1 = (FIX / "usgs-sismos-2026-10-21.json").read_bytes()
    raw2 = (FIX / "usgs-sismos-2026-10-23.json").read_bytes()
    mag = _usgs_mags(raw1, raw2)
    assert (mag["old"], mag["new"]) == (5.2, 5.3)
    t1, t2 = datetime(2026, 10, 21, 20, 0, tzinfo=timezone.utc), datetime(2026, 10, 23, 3, 0, tzinfo=timezone.utc)
    first, second = _collect("usgs-sismos", raw1, t1), _collect("usgs-sismos", raw2, t2)
    hist = N.new_lines([], first)
    added = N.new_lines(hist, second)
    old, rev = _usgs_versions(hist, added)
    assert len(rev) == 1 and rev[0]["revises"] == old["id"] and "5.3" in rev[0]["title"]
    # Una segunda revisión remite a la primera versión, no a la anterior.
    third = dict(rev[0], id="otro", title=rev[0]["title"].replace("5.3", "5.4"), first_seen="2026-10-24T03:00:00+00:00")
    assert N.new_lines(hist + added, [third])[0]["revises"] == old["id"]
    shown = _shown_usgs_links(hist + added, t2)
    assert len(shown) == 1 and "5.3" in shown[0]["title"]


def _usgs_mags(raw1: bytes, raw2: bytes) -> dict[str, float]:
    """La magnitud del sismo us6000u1kt en cada copia, leída del GeoJSON sin el lector del sitio."""
    return {name: next(f["properties"]["mag"] for f in json.loads(r)["features"] if f["id"] == "us6000u1kt")
            for name, r in (("old", raw1), ("new", raw2))}


def _usgs_versions(hist: list[dict], added: list[dict]) -> tuple[dict, list[dict]]:
    """La línea original del sismo us6000u1kt y las que se agregaron después para él."""
    old = next(i for i in hist if i["link"].endswith("/us6000u1kt"))
    return old, [i for i in added if i["link"].endswith("/us6000u1kt")]


def _shown_usgs_links(items: list[dict], now: datetime) -> list[dict]:
    """Los enlaces al sismo us6000u1kt que muestran los grupos."""
    return [link for g in N.cluster(items, now) for link in g["links"] if link["url"].endswith("/us6000u1kt")]


def test_a_link_that_does_not_identify_the_story_keeps_every_entry():
    # FIRMS: el resumen del día siempre enlaza al mismo mapa (``link_is_id=False``).
    link = "https://firms.modaps.eosdis.nasa.gov/map/#d:24hrs;@-75.0,-9.4,5.6z"
    d1 = {"id": "a", "feed": "firms-focos", "link": link, "title": "77 focos (20 y 21 de octubre)", "first_seen": "2026-10-21T19:48:16+00:00"}
    d2 = {"id": "b", "feed": "firms-focos", "link": link, "title": "119 focos (21 y 22 de octubre)", "first_seen": "2026-10-22T09:37:22+00:00"}
    assert N.new_lines([d1], [d2]) == [d2]
    assert N.latest_versions([d1, d2]) == [d1, d2]
    # Un feed que en una misma lectura pone el mismo enlace a dos titulares: ahí el enlace tampoco identifica.
    e1 = {"id": "c", "feed": "elcomercio", "link": "https://elcomercio.pe/", "title": "Nota uno", "first_seen": "2026-10-21T19:48:16+00:00"}
    e2 = dict(e1, id="d", title="Nota dos")
    assert N.new_lines([], [e1, e2]) == [e1, e2]
    assert N.latest_versions([e1, e2]) == [e1, e2]


def test_same_title_with_other_spacing_is_the_same_story_and_flip_flops_are_bounded():
    base = {"feed": "elcomercio", "link": "https://elcomercio.pe/x-noticia/", "first_seen": "2026-10-21T00:00:00+00:00"}
    a = dict(base, id="1", title="Lluvias en Piura")
    a_ws = dict(base, id="2", title="Lluvias en  piura ", first_seen="2026-10-22T00:00:00+00:00")
    b = dict(base, id="3", title="Lluvias intensas en Piura", first_seen="2026-10-23T00:00:00+00:00")
    a_again = dict(base, id="4", title="Lluvias en Piura", link="http://www.elcomercio.pe/x-noticia", first_seen="2026-10-24T00:00:00+00:00")
    hist = [a]
    for f in (a_ws, b, a_again):
        hist += N.new_lines(hist, [f])
    assert [h["id"] for h in hist] == ["1", "3"], "dos titulares distintos, dos líneas; las repeticiones no"
    assert hist[1]["revises"] == "1"


def test_old_history_copies_of_a_retitled_story_show_once_with_the_latest_title():
    # Tres líneas reales del histórico (data-archive, 21-11-2026): Gestión cambió dos veces el titular de la misma
    # nota. El primero y el último no se parecen lo bastante para caer en el mismo grupo (``_similar``), así que
    # la nota salía en dos grupos, y en uno con el titular viejo.
    rows = N.read_jsonl((FIX / "gestion-titulares-2026.jsonl").read_text(encoding="utf-8"))
    assert len(rows) == 3 and len({N.canonical_link(r["link"]) for r in rows}) == 1
    groups = N.cluster(rows, datetime(2026, 10, 27, 0, 0, tzinfo=timezone.utc))
    shown = [link for g in groups for link in g["links"]]
    latest = max(rows, key=lambda r: r["first_seen"])
    assert [s["id"] for s in shown] == [latest["id"]]
    assert groups[0]["title"] == latest["title"]


def test_tracking_params_are_matched_whole_and_identity_is_per_feed():
    # Solo los nombres exactos de ``_TRACKING_RE``: «campana» (contiene «amp») o «pref» (contiene «ref») son parte
    # de la dirección de la nota y separan dos notas distintas.
    assert N.canonical_link("https://a.pe/nota?campana=1") != N.canonical_link("https://a.pe/nota?campana=2")
    assert N.canonical_link("https://a.pe/nota?pref=1") != N.canonical_link("https://a.pe/nota?pref=2")
    assert N.canonical_link("https://a.pe/nota?ref=portada") == N.canonical_link("https://a.pe/nota")
    # La misma nota en dos feeds sigue siendo dos líneas (cada feed tiene su estado y su archivo del día); los
    # grupos (``cluster``) las juntan.
    a = {"id": "1", "feed": "elcomercio", "link": "https://elcomercio.pe/x", "title": "Lluvias en Piura",
         "first_seen": "2026-10-21T00:00:00+00:00"}
    b = dict(a, id="2", feed="elcomercio-peru", title="Lluvias intensas en Piura")
    assert N.new_lines([a], [b]) == [b]
    assert N.latest_versions([a, b]) == [a, b]
