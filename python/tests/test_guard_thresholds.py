"""Los umbrales de las guardias, en su borde: cada prueba falla si el umbral se corre una unidad o se quita la condición.

La revisión adversarial de noviembre de 2026 cambió a mano cada uno (``REWRITE_MIN_POINTS = 1``, sin
``REWRITE_FRACTION``, ``SHRINK_TOLERANCE = 50``, ``k > cutoff`` en lugar de ``>=``, ``official_alerts`` para cualquier
tipo de fuente, ``ensodisc_basis`` solo con el último punto, ``block_page`` de cualquier tamaño) y las pruebas seguían
pasando: los casos reales que tenían quedaban lejos de los bordes. Estas los fijan.
"""

from __future__ import annotations

import copy
from datetime import date
from types import SimpleNamespace

from enso import drift, reach
from enso import observatory as obs
from enso.fetch import block_page


def _monthly(n: int, start: int = 1990) -> list[dict]:
    """``n`` meses seguidos desde enero de ``start`` con valores pequeños distintos."""
    return [{"period": f"{start + i // 12}-{i % 12 + 1:02d}", "value": round((i % 7) * 0.1 - 0.3, 2)} for i in range(n)]


def _codes(prev, cur) -> list[str]:
    return [c for c, _ in drift.compare(prev, cur)]


def _bump(series: list[dict], idx) -> list[dict]:
    out = copy.deepcopy(series)
    for i in idx:
        out[i]["value"] = round(out[i]["value"] + 1.0, 2)
    return out


# --- enso.drift -----------------------------------------------------------------------------------------------

def test_rewrite_needs_at_least_three_old_points():
    """Dos valores antiguos corregidos (5 % de los antiguos, sobre ``REWRITE_FRACTION``) no son una reescritura; tres
    sí. Mata ``REWRITE_MIN_POINTS`` = 1, 2 o 4."""
    s = _monthly(60)  # 36 antiguos, 24 recientes
    assert drift.REWRITE_MIN_POINTS == 3
    assert _codes(s, _bump(s, [0])) == []
    assert _codes(s, _bump(s, [0, 5])) == []
    assert _codes(s, _bump(s, [0, 5, 10])) == ["history-rewritten"]


def test_rewrite_needs_more_than_the_fraction_of_old_points():
    """En una serie larga (476 antiguos), 5 valores corregidos (1 %) no avisan; 10 (2,1 %) sí. Mata quitar la
    condición de ``REWRITE_FRACTION`` (o ponerla en 0)."""
    s = _monthly(500)
    assert _codes(s, _bump(s, range(0, 50, 10))) == []
    assert _codes(s, _bump(s, range(0, 100, 10))) == ["history-rewritten"]


def test_the_cutoff_point_counts_as_recent():
    """El punto ``keys[-RECENT_POINTS]`` es el más viejo de los recientes: revisarlo es normal. Con dos antiguos
    cambiados, cambiar también ese no completa los tres. Mata ``k > cutoff``."""
    s = _monthly(60)
    cutoff = len(s) - drift.RECENT_POINTS
    assert _codes(s, _bump(s, [0, 5, cutoff])) == []
    assert _codes(s, _bump(s, [0, 5, cutoff - 1])) == ["history-rewritten"]


def test_losing_three_points_is_shrunk_two_is_tolerated():
    """Mata ``SHRINK_TOLERANCE`` distinto de 2 (y ``<=`` en lugar de ``<``). Se quitan puntos del principio para no
    mover el último periodo."""
    s = _monthly(60)
    assert drift.SHRINK_TOLERANCE == 2
    assert _codes(s, s[2:]) == []
    assert _codes(s, s[3:]) == ["series-shrunk"]


# --- observatory.official_alerts ------------------------------------------------------------------------------

def _feed(**kw):
    return SimpleNamespace(**{"id": "x", "scope": "hazard", "kind": "gobierno", "covers": ("lluvias",), **kw})


def test_official_alerts_only_for_government_or_agency_hazard_feeds():
    """Un agregador o una radio que cubre peligros no es una fuente oficial: su caída no es ``hazard-feed-down``."""
    assert obs.official_alerts(_feed())
    assert obs.official_alerts(_feed(kind="organismo"))
    for kind in ("agregador", "radio", "diario", "tv", "digital"):
        assert not obs.official_alerts(_feed(kind=kind)), kind
    assert not obs.official_alerts(_feed(scope="local"))
    assert not obs.official_alerts(_feed(covers=()))
    assert obs.official_alerts(_feed(covers=(), id="ciifen"))
    assert not obs.official_alerts(_feed(kind="agregador", id="gdacs"))
    assert not obs.official_alerts(None)


# --- Builder.ensodisc_basis -----------------------------------------------------------------------------------

def _basis_builder(wk=None, mo=None):
    b = obs.Builder({}, obs.EventLog(), date(2026, 11, 20))
    b.data = lambda sid: {"cpc-wksst": wk or {}, "cpc-sstoi": {"anom": mo or {}}}.get(sid)
    return b


def test_ensodisc_basis_also_matches_the_previous_week():
    """La discusión puede citar la semana anterior a la última de su fecha. Mata mirar solo ``[-1]``."""
    wk = {"nino34": [{"date": "2026-11-04", "anom": 3.3}, {"date": "2026-11-11", "anom": 2.6}]}
    b = _basis_builder(wk=wk)
    assert b.ensodisc_basis({"nino34": 3.3}, "2026-11-12") == "traditional-weekly"
    assert b.ensodisc_basis({"nino34": 2.6}, "2026-11-12") == "traditional-weekly"
    assert b.ensodisc_basis({"nino34": 2.9}, "2026-11-12") == "other"


def test_ensodisc_basis_also_matches_the_previous_month():
    mo = {"nino34": [{"period": "2026-09", "value": 2.9}, {"period": "2026-10", "value": 3.4}]}
    b = _basis_builder(mo=mo)
    assert b.ensodisc_basis({"nino34": 2.9}, "2026-11-12") == "traditional-monthly"
    assert b.ensodisc_basis({"nino34": 3.4}, "2026-11-12") == "traditional-monthly"
    assert b.ensodisc_basis({"nino34": 2.5}, "2026-11-12") == "other"


# --- block_page: tamaño -----------------------------------------------------------------------------------------

def _page(size: int, mark: str = "wsidchk") -> bytes:
    head = f"<!DOCTYPE html><html><body><form id='{mark}'></form><p>".encode()
    tail = b"</p></body></html>"
    return head + b"x" * (size - len(head) - len(tail)) + tail


def test_block_page_only_below_small_page():
    """Una marca propia (Imunify360) en una página de ``SMALL_PAGE`` bytes o más no la descarta (un artículo que
    cita la verificación); un byte menos, sí. Mata ``block_page`` y ``classify`` de cualquier tamaño y el borde
    ``<=``."""
    small, big = _page(reach.SMALL_PAGE - 1), _page(reach.SMALL_PAGE)
    assert len(small) == reach.SMALL_PAGE - 1 and len(big) == reach.SMALL_PAGE
    assert block_page(small) == "imunify360"
    assert block_page(big) == ""
    assert reach.classify(200, small, headers={"content-type": "text/html"}) == "challenge"
    assert reach.classify(200, big, headers={"content-type": "text/html"}) == "ok"
