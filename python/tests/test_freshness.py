"""Vigencia de cada dato del sitio: estado según el calendario de cada institución."""

from __future__ import annotations

from datetime import date, datetime, timezone

from enso import freshness as FR

NOW = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)
TODAY = NOW.date()


def _s(period, source="cpc-sstoi", kind="month", stale=False, carried=False):
    return {"label": source, "source": source, "periodKind": kind, "sloDays": 50,
            "latest": {"period": period, "value": 1.0, "stale": stale, "carried": carried}}


def _build(series=None, weekly=None, official=None, feed=None, feeds=None, today=TODAY, meta=None):
    return FR.build(series or {}, weekly, official or {}, meta or {}, feed, feeds, today, NOW)


def test_monthly_series_calendar():
    f = _build({"a": _s("2026-09"), "b": _s("2026-08"), "c": _s("2026-07", stale=True)})
    st = {k: v["state"] for k, v in f["items"].items() if k in "abc"}
    assert st == {"a": "al-dia", "b": "atrasado", "c": "vencido"}  # agosto debía estar hacia el 10 de octubre
    assert f["items"]["a"]["expectedNext"] == "2026-11-10"


def test_icen_and_seasonal_indices_lag_more():
    f = _build({"icen": _s("2026-08", "igp-icen"), "roni": _s("2026-08", "cpc-roni", kind="season")})
    assert f["items"]["icen"]["state"] == "al-dia" and f["items"]["icen"]["expectedNext"] == "2026-11-15"
    assert f["items"]["roni"]["state"] == "al-dia" and f["items"]["roni"]["expectedNext"] == "2026-11-10"
    late = _build({"icen": _s("2026-08", "igp-icen")}, today=date(2026, 11, 25))
    assert late["items"]["icen"]["state"] == "atrasado"


def test_carried_value_is_late_even_if_recent():
    f = _build({"a": _s("2026-09", carried=True)})
    assert f["items"]["a"]["state"] == "atrasado"


def test_official_communique_and_weekly():
    off = {"enfen": {"status": "Alerta", "number": "18-2026", "issued": "2026-10-16", "nextIssue": "2026-10-30"},
           "noaa": {"status": "x", "issued": "2026-09-11", "nextIssue": "2026-10-08"}}
    wk = {"nino12": {"latest": {"date": "2026-10-06"}}}
    f = _build(official=off, weekly=wk)
    assert f["items"]["enfen"]["state"] == "al-dia"
    assert f["items"]["noaa"]["state"] == "atrasado"  # la discusión del 8 de octubre no llegó
    assert f["items"]["weekly"]["state"] == "atrasado"  # la semana siguiente debía estar el 18 (+2 de margen)
    assert f["items"]["enfen-probabilities"]["state"] == "sin-dato"
    assert f["views"]["costero"]["worst"] == "atrasado" and f["views"]["pacifico"]["worst"] == "atrasado"


def test_informe_of_an_older_communique_is_late():
    off = {"enfen": {"status": "Alerta", "number": "18-2026", "issued": "2026-10-16", "nextIssue": "2026-10-30",
                     "informe": {"number": 17, "communique": "17-2026", "dataTo": "2026-09-25",
                                 "probabilities": [{"region": "nino12"}],
                                 "icenProvisional": {"period": "2026-08", "icen": 3.97}}}}
    f = _build(official=off)
    assert f["items"]["enfen-probabilities"]["state"] == "atrasado"
    assert f["items"]["icen-provisional"]["observed"] == "2026-08"


def test_alerts_and_news():
    feed = {"groups": [{"id": "alertas", "items": [{"date": "2026-10-21T17:00:00Z"}],
                        "sources": [{"ok": True}, {"ok": False}]}]}
    feeds = [{"ok": True, "latest": "2026-10-21T10:00:00+00:00"}, {"ok": False, "error": "omitido: robots"}]
    f = _build(feed=feed, feeds=feeds)
    assert f["items"]["alerts"]["state"] == "atrasado" and f["items"]["alerts"]["sourcesOk"] == 1
    assert f["items"]["news"]["state"] == "al-dia" and f["items"]["news"]["sourcesTotal"] == 1


def test_late_items_become_incidents():
    class Log:
        events = []

        def add(self, *a):
            self.events.append(a)

    log = Log()
    FR.log_late(_build({"a": _s("2026-08"), "b": _s("2026-09")}), log)
    assert [e[3] for e in log.events] == ["late-a"]
