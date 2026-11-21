"""Ensayo de producción antes de fusionar el PR #133 (21 de noviembre de 2026): lo que haría la primera corrida diaria.

Se corrió ``python -m enso.observatory`` contra las fuentes en vivo, con ``--previous`` en la publicación en vivo
(https://enso-peru.pages.dev/data) y las copias de data-peru y data-n8n, una vez con la rama y otra con main, sobre las
mismas respuestas (el listado de la DHN llegó idéntico a las dos: sha256 d247487d…). La única diferencia que abriría
issues era de la rama: el listado completo de avisos especiales de la DHN (583 avisos desde 2015) trae 7 avisos de
viento antiguos que nunca tuvieron fecha, y el parser nuevo convertía cada uno en ``FeedError``. El feed oficial de
oleaje y vientos caía entero (main publica sus 576 avisos con fecha), el sitio mostraba «Alertas: atrasado», la
corrida de las 04:37 UTC abría ``hazard-feed-down`` (más de 6 h después de la de la fusión) y a los dos días
``degraded-persistent`` (estado ``unreadable``).

El fixture ``fixtures/dhn/avisos-especiales-2026-11-21.html.gz`` es esa respuesta tal como llegó (gzip del cuerpo,
https://www.dhn.mil.pe/portal/avisos-especiales, 2 395 590 bytes, sha256 d247487ddc7764e7…). Los 7 avisos sin fecha
se identificaron leyendo el texto de la página: sus enlaces ``pdf-aviso-especial/<id>`` son los de ``SIN_FECHA``."""

from __future__ import annotations

import gzip
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from enso import hazardparse as H
from enso import news as N
from enso import observatory as obs
from enso import persistent
from enso.feedparse import FeedError

PAGE = Path(__file__).parent / "fixtures" / "dhn" / "avisos-especiales-2026-11-21.html.gz"
URL = "https://www.dhn.mil.pe/portal/avisos-especiales"
#: Avisos de viento del listado sin «Callao, <fecha>» ni vigencia (leídos a mano en la página): N° 19 (2023), 05, 04,
#: 12, 11, 07 y 63 (2015–2022).
SIN_FECHA = {"4900", "3843", "2841", "1674", "1673", "1666", "1631"}
DATE_RE = re.compile(r"Callao,?\s*\d{1,2} de \w+(?: del?)? \d{4}")
VALID_RE = re.compile(r"\(V[ÁA]LIDO[^)]*\)", re.I)


def _body() -> bytes:
    return gzip.decompress(PAGE.read_bytes())


def _ids(items: list[dict]) -> list[str]:
    return [i["link"].rpartition("#")[2] for i in items]


def _sin_fecha(text: str, ids: set[str]) -> str:
    """La página con los avisos ``ids`` sin su fecha de emisión ni su vigencia (como los 7 antiguos)."""
    chunks = text.split('class="position-relative"')
    for k, c in enumerate(chunks):
        if set(re.findall(r"pdf-aviso-especial/(\d+)", c)) & ids:
            chunks[k] = VALID_RE.sub("", DATE_RE.sub("Callao", c))
    return 'class="position-relative"'.join(chunks)


def test_listado_real_completo_publica_los_avisos_con_fecha_y_omite_los_7_antiguos():
    body = _body()
    every = set(re.findall(rb"pdf-aviso-especial/(\d+)", body))
    p = H.parse(body, URL, "dhn-avisos")
    got = _ids(p.items)
    # 587 enlaces en la página; 4 bloques no son avisos (sin «AVISO ESPECIAL … N°» y tipo): 583 avisos, 7 sin fecha.
    assert len(every) == 587
    assert len(got) == 576 == 583 - len(SIN_FECHA)
    assert SIN_FECHA <= {x.decode() for x in every}
    assert not SIN_FECHA & set(got)


def test_listado_real_completo_fechas_y_nota_de_los_omitidos():
    p = H.parse(_body(), URL, "dhn-avisos")
    got = _ids(p.items)
    assert all(i["published"] for i in p.items)
    assert p.repairs == ["7 avisos especiales antiguos sin fecha legible omitidos (N° 19, 05, 04, 12, 11, 07, 63)"]
    # El más reciente, leído en la página: «Callao, 17 de noviembre 2026», válido del 19 al 21 de noviembre.
    assert got[0] == "5368"
    assert p.items[0]["published"].startswith("2026-11-17")
    assert "válido del 19 al 21 de noviembre del 2026" in p.items[0]["title"]


@pytest.mark.parametrize("pos", [9, 10])
def test_aviso_reciente_sin_fecha_sigue_siendo_cambio_de_formato(pos):
    """Un cambio de formato llega primero a los avisos nuevos: uno sin fecha entre los 10 primeros es FeedError. El
    del puesto 11 también, porque es «NN-AA» (los de 2024 en adelante siempre traen fecha); el borde de
    ``DHN_UNDATED_RECENT`` con un aviso viejo está en ``test_ready_drift_guards.py``."""
    text = _body().decode("utf-8")
    ids = _ids(H.parse(text.encode(), URL, "dhn-avisos").items)
    raw_order = list(dict.fromkeys(re.findall(r"pdf-aviso-especial/(\d+)", text)))
    assert ids[:11] == raw_order[:11]  # los 11 primeros bloques son avisos: el puesto del listado es el de ``ids``
    mutated = _sin_fecha(text, {ids[pos]}).encode()
    with pytest.raises(FeedError, match=rf"-\d\d \(el {pos + 1}\.° del listado\) no tiene una fecha"):
        H.parse(mutated, URL, "dhn-avisos")


@pytest.mark.parametrize("extra, loud", [(22, False), (23, True)])
def test_muchos_avisos_antiguos_sin_fecha_son_cambio_de_formato(extra, loud):
    """Más de 1 de cada 20 avisos sin fecha es un cambio de formato aunque los recientes tengan fecha. Con 583 avisos:
    7 + 22 = 29 sin fecha (29 × 20 = 580 ≤ 583) se toleran; 7 + 23 = 30 (600 > 583) no."""
    text = _body().decode("utf-8")
    ids = _ids(H.parse(text.encode(), URL, "dhn-avisos").items)
    mutated = _sin_fecha(text, set(ids[-extra:])).encode()  # los más antiguos con fecha
    if loud:
        with pytest.raises(FeedError, match="30 de 583 avisos sin fecha"):
            H.parse(mutated, URL, "dhn-avisos")
    else:
        assert len(H.parse(mutated, URL, "dhn-avisos").items) == 576 - extra


def test_listado_real_en_ingles_es_cambio_de_formato():
    """El cambio de idioma que motivó el FeedError (``tools/drift_sim.py``), ahora sobre el listado completo: en el real
    los 7 primeros avisos son de noviembre; los de octubre (puesto 8 en adelante) quedan sin fecha legible."""
    text = _body().decode("utf-8")
    english = re.sub(r"(Callao,?\s*)(\d{1,2}) de octubre(?: del?)? (\d{4})", r"\1October \2, \3", text)
    english = re.sub(r"(V[áa]lido del \d{1,2}(?: de \w+)? al \d{1,2}) de octubre", r"\1 October", english)
    assert english != text
    with pytest.raises(FeedError, match="no tiene una fecha"):
        H.parse(english.encode(), URL, "dhn-avisos")


def test_feed_real_no_cuenta_como_caido_ni_degradado():
    """Por el camino de la corrida (``news._read_feed``): el feed oficial responde bien, no es ``hazard_down`` (no abre
    ``hazard-feed-down``) y no tiene estado de degradación (no abre ``degraded-persistent``)."""
    feed = N.FEED_BY_ID["dhn-avisos"]
    body = _body()
    now = datetime(2026, 11, 21, 17, 21, tzinfo=timezone.utc)
    st, _, _ = N._read_feed(feed, lambda url: (200, body, "text/html; charset=utf-8", ""), now)
    assert st["ok"]
    assert st["items"] == 576
    assert not st.get("formatError")
    assert st["latest"].startswith("2026-11-17")
    assert obs.official_alerts(feed)
    assert not obs.hazard_down(st)


def test_feed_real_no_tiene_estado_de_degradacion():
    feed = N.FEED_BY_ID["dhn-avisos"]
    body = _body()
    now = datetime(2026, 11, 21, 17, 21, tzinfo=timezone.utc)
    st, found, _ = N._read_feed(feed, lambda url: (200, body, "text/html; charset=utf-8", ""), now)
    assert persistent.feed_state(st, feed, {}, now, persistent.rules()) == (None, None)
    assert found
    assert {i["feed"] for i in found} == {"dhn-avisos"}


def test_borde_exacto_de_la_proporcion_es_tolerado():
    """Borde exacto de ``DHN_UNDATED_SHARE`` (1 de cada 20 se tolera, más no): con 583 avisos el borde no es entero, así
    que se quitan los 3 más antiguos con fecha (580 avisos) y quedan 7 + 22 = 29 sin fecha: 29 × 20 = 580, tolerado.
    Con 30 (600 > 580) es cambio de formato. Mata el mutante ``>`` → ``>=`` que el listado de 583 no distingue."""
    text = _body().decode("utf-8")
    ids = _ids(H.parse(text.encode(), URL, "dhn-avisos").items)
    sep = 'class="position-relative"'
    drop = set(ids[-3:])
    chunks = [c for c in text.split(sep) if not set(re.findall(r"pdf-aviso-especial/(\d+)", c)) & drop]
    assert len(chunks) == len(text.split(sep)) - 3
    trimmed = sep.join(chunks)
    p = H.parse(_sin_fecha(trimmed, set(ids[-25:-3])).encode(), URL, "dhn-avisos")
    assert len(p.items) == 580 - 29
    assert p.repairs[0].startswith("29 avisos especiales antiguos sin fecha legible omitidos")
    with pytest.raises(FeedError, match="30 de 580 avisos sin fecha"):
        H.parse(_sin_fecha(trimmed, set(ids[-26:-3])).encode(), URL, "dhn-avisos")
