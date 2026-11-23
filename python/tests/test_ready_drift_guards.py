"""Antes de desplegar: las guardias nuevas de deriva contra todas las copias reales de ``data-archive``.

Se pasó cada copia archivada (8995 de feeds de ``data-archive`` y 129 del relevo n8n, más las 60 de series) por
``news._read_feed`` y ``observatory.acquire`` del commit anterior a las guardias y de 4c6f977e. Lo único que cambió
de bien a mal fueron **las nueve copias de los avisos especiales de la DHN**, todas: el listado real trae 583 avisos y
siete de 2023 (de viento, N° 04 a 19 y 63, numerados sin «-AA») no dicen ni el año; ``parse_dhn_avisos`` lanzaba
``FeedError`` por el primero y el feed entero quedaba «ilegible» (escala a issue a los 2 días y el sitio perdía los
avisos de oleaje). La copia de las pruebas estaba recortada a 30 avisos, todos con fecha, y no lo mostraba.

* ``news-dhn-avisos-20261119-full-undated.html`` es la copia real del 19-11-2026 recortada a los 12 avisos más
  recientes, los siete sin fecha (en sus posiciones relativas) y el último del listado: la cabecera y el pie, intactos.
* La raíz de un feed se compara como elemento entero: ``<feed`` también es el comienzo de ``<feedburner:info>`` y
  ``</feed`` el de ``</feedburner:origLink>``.
* El estado ``empty`` escala a los max(3, ``stale_days``) días con tope de 14 y al menos 3 corridas; el simulacro del
  PTWC no cuenta (en ``data-archive`` duró 16 días: sin la exención habría abierto un issue). La única copia vacía de
  un feed no exento es la del PTWC en Atom del 24-10-2026 (un mensaje N° 2 sin ``<entry>``), que duró un día.
"""

from __future__ import annotations

import dataclasses
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from enso import hazardparse as H
from enso import news as N
from enso import observatory as obs
from enso import persistent as P
from enso.feedparse import FeedError, mostly_cp1252, text_of, truncated

FIX = Path(__file__).parent / "fixtures" / "sources"

DHN_URL = "https://www.dhn.mil.pe/portal/avisos-especiales"
FULL = (FIX / "news-dhn-avisos-20261119-full-undated.html").read_bytes()
MARK = b'class="position-relative"'


def _cards(body: bytes) -> tuple[bytes, list[bytes]]:
    head, *cards = body.split(MARK)
    return head, cards


def _join(head: bytes, cards: list[bytes]) -> bytes:
    return MARK.join([head, *cards])


HEAD, CARDS = _cards(FULL)
# Al recortar la copia quedaron, en orden: 12 tarjetas recientes (N° 24-26 … 41-26), las siete de 2023 sin año
# (N° 19, 05, 04, 12, 11, 07, 63) y la última del listado (N° 01, con «Callao, …»): se eligen por posición, no con el
# lector bajo prueba.
LEGACY = CARDS[12:19]
DATED = CARDS[:12] + CARDS[19:]


@pytest.fixture
def share_off(monkeypatch):
    """La copia recortada tiene 7 avisos viejos sin fecha en 20 (en la página real son 7 de 583): la regla de la
    proporción (``DHN_UNDATED_SHARE``, probada con la página completa en ``test_ready_prod_dryrun.py``) la haría
    fallar. Estas pruebas miran las otras reglas, así que la apagan."""
    monkeypatch.setattr(H, "DHN_UNDATED_SHARE", 1)


def test_fixture_is_the_real_listing_shape():
    # 20 tarjetas: 12 recientes, 7 de 2023 sin año y la última del listado (hechas a mano al recortar la copia).
    assert len(CARDS) == 20 and len(LEGACY) == 7 and len(DATED) == 13
    assert b"AVISO ESPECIAL DE VIENTO NRO 24-26" in CARDS[0] and b"NRO. 41-26" in CARDS[11]
    assert all(not re.search(rb"NRO\.? \d+-\d\d", c[:2000]) for c in LEGACY)


def test_full_dhn_listing_with_legacy_undated_avisos_is_read(share_off):
    p = H.parse(FULL, DHN_URL, "dhn-avisos")
    # 13 = 20 tarjetas - 7 sin fecha; antes: FeedError por el N° 19 y el feed entero ilegible.
    assert len(p.items) == 13
    assert all(i["published"] for i in p.items)
    assert p.items[0]["title"].startswith("DHN · aviso especial de viento N° 24-26")
    assert p.repairs == ["7 avisos especiales antiguos sin fecha legible omitidos (N° 19, 05, 04, 12, 11, 07, 63)"]


def test_full_dhn_listing_keeps_the_feed_ok_for_persistent(share_off):
    st, found, _ = N._read_feed(N.FEED_BY_ID["dhn-avisos"], lambda u: (200, FULL, "text/html", None),
                                datetime(2026, 11, 19, 17, tzinfo=timezone.utc), {})
    assert st["ok"] and not st.get("formatError") and st["items"] == 13
    assert P.feed_state(st, N.FEED_BY_ID["dhn-avisos"], {}, datetime(2026, 11, 19, 17, tzinfo=timezone.utc),
                        P.rules()) == (None, None)
    assert found  # los avisos vigentes de noviembre llegan al sitio


@pytest.mark.parametrize("pos, loud", [(H.DHN_UNDATED_RECENT, True), (H.DHN_UNDATED_RECENT + 1, False)])
def test_legacy_undated_aviso_among_the_recent_ones_is_loud(pos, loud, share_off):
    # Una tarjeta sin fecha en la posición 10 (de las que el sitio muestra) es un cambio; en la 11, un aviso viejo.
    assert H.DHN_UNDATED_RECENT == 10
    cards = DATED[: pos - 1] + [LEGACY[0]] + DATED[pos - 1:]
    body = _join(HEAD, cards)
    if loud:
        with pytest.raises(FeedError, match=r"N° 19 \(el 10\.° del listado\) no tiene una fecha"):
            H.parse(body, DHN_URL, "dhn-avisos")
    else:
        assert len(H.parse(body, DHN_URL, "dhn-avisos").items) == len(DATED)


def test_current_numbering_without_a_date_is_loud_even_when_old():
    # La tarjeta 12 (N° 41-26) sin su vigencia ni «Callao, …»: está fuera de las 10 recientes y es 1 de 20, pero un
    # aviso «NN-AA» siempre trae fecha. Sin las siete viejas, para que sea el único sin fecha.
    cards = DATED[:]
    i = 11
    assert b"NRO. 41-26" in cards[i] and i + 1 > H.DHN_UNDATED_RECENT
    cut = re.sub(rb"\(V\xc3\xa1lido[^)]*\)", b"", cards[i])
    cut = re.sub(rb"Callao,?\s*\d{1,2} de \w+(?: del?)? \d{4}", b"", cut)
    assert cut != cards[i]
    cards[i] = cut
    with pytest.raises(FeedError, match=r"N° 41-26 \(el 12\.° del listado\) no tiene una fecha .*1 de 13 avisos"):
        H.parse(_join(HEAD, cards), DHN_URL, "dhn-avisos")


# La proporción de avisos sin fecha (más de 1 de cada 20) se prueba con la página real completa en
# ``test_ready_prod_dryrun.py`` (29 de 583 pasan, 30 no).


# --- truncated(): la raíz como elemento entero --------------------------------------------------------------------
RSS = (FIX / "news-rpp-peru-actualidad.xml").read_bytes()
ATOM = (FIX / "news-ptwc-mensajes.xml").read_bytes()


def test_feedburner_rss_that_closes_is_not_truncated():
    assert b"</rss>" in RSS and truncated(RSS, "feed") == ""
    fb = RSS.replace(b"<channel>", b'<channel><feedburner:info uri="rpp/peru"/>', 1)
    assert fb != RSS
    # Antes: «<feed» en la cabecera (de <feedburner:info>) y sin «</feed» al final → «no cierra (</feed>)».
    assert truncated(fb, "feed") == ""


def test_cut_atom_with_feedburner_links_is_truncated():
    assert b"</entry>" in ATOM and truncated(ATOM, "feed") == ""
    cut = ATOM.replace(b"</entry>", b"<feedburner:origLink>https://x.pe/1</feedburner:origLink></entry>")
    cut = cut[: cut.rindex(b"</feed")]
    # Antes: «</feed» de </feedburner:origLink> se tomaba por el cierre y la copia cortada pasaba por entera.
    assert truncated(cut, "feed") == "el documento no cierra (</feed>): llegó cortado"


# --- empty: cuándo escala ------------------------------------------------------------------------------------------
EMPTY_ATOM = (FIX / "news-ptwc-mensajes-20261024-sin-entry.xml").read_bytes()
EXERCISE = (FIX / "news-ptwc-wepa40-test-pacwave26.txt").read_bytes()
T0 = datetime(2026, 10, 24, 13, tzinfo=timezone.utc)


def _escalated_after(f, body: bytes, days: int) -> bool:
    """Corridas diarias desde T0 con la misma respuesta: ¿el feed escaló en la corrida del día ``days``?"""
    state = None
    for d in range(days + 1):
        now = T0 + timedelta(days=d)
        st, _, _ = N._read_feed(f, lambda u: (200, body, "", None), now, {})
        st["id"], st["name"] = f.id, f.name
        state = P.update(state, now, obs.EventLog(), feeds=[(f, st)], plan={})
    return f"feed:{f.id}" in state["escalated"]


@pytest.mark.parametrize("stale, days", [(365, 14), (7, 7), (3, 3), (1, 3)])
def test_empty_feed_escalates_at_max_3_stale_days_capped_14(stale, days):
    # Copia real vacía (PTWC Atom del 24-10-2026) leída como el feed del PTWC con otro ``stale_days``. Umbral:
    # min(14, max(3, 1.0 × stale_days)): 365 → 14 (el real), 7 → 7, 3 → 3, 1 → 3. Las corridas (días + 1) pasan de 3.
    f = dataclasses.replace(N.FEED_BY_ID["ptwc-mensajes"], stale_days=stale)
    assert f.adapter == "feed" and N.FEED_BY_ID["ptwc-mensajes"].stale_days == 365
    assert min(14, max(3, stale)) == days
    assert not _escalated_after(f, EMPTY_ATOM, days - 1)
    assert _escalated_after(f, EMPTY_ATOM, days)


def test_ptwc_exercise_for_16_days_does_not_escalate():
    # PACWAVE26 fue el último mensaje del WEPA40 del 05-11 al 21-11-2026 (16 días en data-archive).
    assert not _escalated_after(N.FEED_BY_ID["ptwc-wepa40"], EXERCISE, 16)


# --- text_of con una página real toda en Latin-1 ------------------------------------------------------------------
def test_text_of_reads_a_real_latin1_feed_without_its_declaration():
    body = (FIX / "news-exitosa.xml").read_bytes()
    assert body.startswith(b'<?xml version="1.0" encoding="iso-8859-1"?>')
    bare = body.replace(b' encoding="iso-8859-1"', b"", 1)
    # La verdad es lo que el propio servidor declara: ISO-8859-1.
    assert mostly_cp1252(bare)
    assert text_of(bare) == bare.decode("iso-8859-1")
    assert "Perú" in text_of(bare)


# --- una errata en el día no tumba el feed ---------------------------------------------------------------------------
def test_impossible_issue_day_falls_back_to_the_validity_date(share_off):
    # «Callao, 31 de noviembre 2026» en el aviso N° 24-26 (el primero): la vigencia del propio título («del 19 al 21
    # de noviembre del 2026») da la fecha. Antes: ValueError, «error inesperado» y el feed entero sin avisos.
    cards = CARDS[:]
    assert cards[0].count(b"Callao, 17 de noviembre 2026") == 1
    cards[0] = cards[0].replace(b"Callao, 17 de noviembre 2026", b"Callao, 31 de noviembre 2026")
    p = H.parse(_join(HEAD, cards), DHN_URL, "dhn-avisos")
    assert len(p.items) == 13
    assert p.items[0]["title"].startswith("DHN · aviso especial de viento N° 24-26")
    assert p.items[0]["published"].startswith("2026-11-19")


def test_impossible_issue_and_validity_days_are_a_feed_error_that_names_the_aviso():
    # Sin ninguna fecha posible es un aviso «NN-AA» sin fecha: FeedError que lo nombra, no un ValueError.
    cards = CARDS[:]
    cards[0] = cards[0].replace(b"Callao, 17 de noviembre 2026", b"Callao, 31 de noviembre 2026")
    cards[0] = cards[0].replace(b"del 19 al 21 de noviembre del 2026", b"del 31 al 21 de noviembre del 2026")
    assert b"del 31 al 21 de noviembre" in cards[0]
    with pytest.raises(FeedError, match=r"N° 24-26 \(el 1\.° del listado\) no tiene una fecha"):
        H.parse(_join(HEAD, cards), DHN_URL, "dhn-avisos")


def test_error_names_the_current_aviso_not_the_first_legacy_one():
    # El N° 41-26 sin fecha movido detrás de las siete viejas (N° 19 primero, posición 12; él queda en la 19): el error
    # nombra al «NN-AA», que es lo que cambió, y no al N° 19, que lleva años así.
    cut = re.sub(rb"\(V\xc3\xa1lido[^)]*\)", b"", CARDS[11])
    cut = re.sub(rb"Callao,?\s*\d{1,2} de \w+(?: del?)? \d{4}", b"", cut)
    assert cut != CARDS[11] and b"NRO. 41-26" in cut
    cards = CARDS[:11] + LEGACY + [cut] + CARDS[19:]
    with pytest.raises(FeedError, match=r"N° 41-26 \(el 19\.° del listado\).*8 de 20 avisos"):
        H.parse(_join(HEAD, cards), DHN_URL, "dhn-avisos")
