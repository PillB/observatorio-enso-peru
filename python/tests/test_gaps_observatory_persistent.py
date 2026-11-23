"""Huecos de cobertura que dejaban vivas dos mutaciones (``enso.observatory`` y ``enso.persistent``).

* ``test_bsobp_exception_keeps_the_published_bulletins``: si la lectura del historial de boletines del IMARPE
  (``imarpe_bsobp.acquire``) lanza una excepción, ``_acquire_bsobp`` anota ``bsobp-exception`` y publica lo que ya
  estaba publicado (``prev_bs``). Ninguna prueba recorría esa rama: devolver ``None`` (la página perdería un año de
  boletines) sobrevivía. La publicación anterior es la semilla real de boletines del repositorio, escrita como
  ``imarpe-bsobp.json`` en un directorio local que ``PreviousPublication`` lee como si fuera el sitio.
* ``test_unseen_feed_does_not_duplicate_the_group_incidence_of_checked_feeds``: un feed escalado que esta corrida no
  revisó (omitido) va a ``regroup``; si su estado (``relay``) ya tiene la incidencia ``feeds-relay`` por un feed que sí
  se revisó, ``_log_regroup`` no debe anotar una segunda ``feeds-relay`` (dos incidencias con la misma clave para un
  solo issue). Ninguna prueba tenía a la vez un feed revisado y otro no revisado en el mismo estado escalado, así que
  quitar el ``if state in groups: continue`` sobrevivía.
* ``test_only_unseen_feeds_still_get_their_group_incidence``: control del anterior; sin feeds revisados en ese estado,
  la incidencia ``feeds-relay`` sí sale desde ``regroup`` (la guardia no debe tragarse todo).
* ``test_unseen_feed_below_threshold_stays_silent``: (agregada en la verificación) un feed degradado que aún no escaló
  y esta corrida no revisó conserva su cuenta pero no abre incidencia; repetir la incidencia de todo lo no revisado
  (``if old.get("escalated")`` -> ``if True`` en ``_carry_unseen``) sobrevivía.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from enso import observatory as obs
from enso import persistent as P
from enso.feeds import imarpe_bsobp

TODAY = date(2026, 11, 21)
T0 = datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc)
PLAN = {"https://www.gob.pe/a.rss": ["actions", "n8n"], "https://www.gob.pe/b.rss": ["actions", "n8n"]}


def test_bsobp_exception_keeps_the_published_bulletins(tmp_path, monkeypatch):
    published = imarpe_bsobp.from_seed(date(2026, 11, 14))  # lo publicado la semana anterior (semilla real)
    assert published["bulletins"]  # la semilla trae boletines: perderlos se notaría
    (tmp_path / "imarpe-bsobp.json").write_text(json.dumps(published), encoding="utf-8")
    prev = obs.PreviousPublication(str(tmp_path))

    def boom(*_a, **_k):
        raise RuntimeError("respuesta inesperada del repositorio")

    monkeypatch.setattr(imarpe_bsobp, "acquire", boom)
    log = obs.EventLog()
    out = obs._acquire_bsobp(fetcher=None, fixtures=None, offline=False, only=None, prev=prev, log=log,
                             today=TODAY, needs=None)
    assert out == published  # lo ya publicado, tal cual (no None ni vacío)
    codes = [(e.severity, e.source, e.code) for e in log.events]
    assert codes == [("error", imarpe_bsobp.SOURCE, "bsobp-exception")]
    assert log.events[0].message == "RuntimeError: respuesta inesperada del repositorio"


def _feed(fid, url):
    return SimpleNamespace(id=fid, url=url, stale_days=7, official=False)


def _st(fid, **kw):
    return {"id": fid, "name": fid.upper(), "ok": True, "active": True, "items": 5,
            "latest": "2026-11-01T00:00:00+00:00", "checkedAt": T0.isoformat(), "error": "", **kw}


A = _feed("gobpe-a", "https://www.gob.pe/a.rss")
B = _feed("gobpe-b", "https://www.gob.pe/b.rss")


def _escalated_pair():
    """Cuatro corridas diarias con los dos feeds solo por n8n: el umbral de relay (3 días, 3 corridas) se pasa en la
    cuarta (T0 + 3 días = 3 días, 4 corridas)."""
    state = None
    for i in range(4):
        feeds = [(A, _st("gobpe-a", channel="relay-n8n")), (B, _st("gobpe-b", channel="relay-n8n"))]
        state = P.update(state, T0 + timedelta(days=i), obs.EventLog(), feeds=feeds, plan=PLAN)
    assert state["escalated"] == ["feed:gobpe-a", "feed:gobpe-b"]
    return state


def _relay_events(log):
    return [e for e in log.events if e.code == P.CODE and e.source == "feeds-relay"]


def test_unseen_feed_does_not_duplicate_the_group_incidence_of_checked_feeds():
    state = _escalated_pair()
    log = obs.EventLog()
    feeds = [(A, _st("gobpe-a", channel="relay-n8n")), (B, _st("gobpe-b", ok=False, omitted=True))]
    out = P.update(state, T0 + timedelta(days=4), log, feeds=feeds, plan=PLAN)
    assert out["entities"]["feed:gobpe-b"]["runs"] == 4  # el omitido conserva su cuenta sin sumar
    events = _relay_events(log)
    assert len(events) == 1  # una sola incidencia feeds-relay: la de los feeds revisados
    assert "(1; relay:" in events[0].message and "GOBPE-A" in events[0].message


def test_only_unseen_feeds_still_get_their_group_incidence():
    state = _escalated_pair()
    log = obs.EventLog()
    feeds = [(A, _st("gobpe-a", ok=False, omitted=True)), (B, _st("gobpe-b", ok=False, omitted=True))]
    P.update(state, T0 + timedelta(days=4), log, feeds=feeds, plan=PLAN)
    events = _relay_events(log)
    assert len(events) == 1
    assert "gobpe-a: degradado (relay)" in events[0].message and "gobpe-b: degradado (relay)" in events[0].message
    assert "no se revisó en esta corrida" in events[0].message


def test_unseen_feed_below_threshold_stays_silent():
    # Una sola corrida por relay: 1 corrida y 0 días, lejos del umbral de relay (3 días, 3 corridas): no escaló.
    feeds = [(A, _st("gobpe-a", channel="relay-n8n"))]
    state = P.update(None, T0, obs.EventLog(), feeds=feeds, plan=PLAN)
    assert state["escalated"] == []
    log = obs.EventLog()
    out = P.update(state, T0 + timedelta(days=1), log, feeds=[(A, _st("gobpe-a", ok=False, omitted=True))], plan=PLAN)
    assert out["entities"]["feed:gobpe-a"]["runs"] == 1  # conserva su cuenta sin sumar
    assert [e for e in log.events if e.code == P.CODE] == []
