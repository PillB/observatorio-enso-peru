"""Feeds de noticias que responden pero ya no publican: de ``feed-inactive`` (info) a ``feed-stale`` (aviso).

En noviembre de 2026 cinco feeds llevaban semanas como ``feed-inactive`` (solo ``info``, que no abre issue): Nacional
Callao TV, RPP · Huancavelica, Altavoz · tema Huancavelica, Noticias SER y Peru Reports. Ninguno era un error del
lector: el feed, la página del medio y la API de WordPress decían la misma última fecha. Cuatro medios publican a
rachas (su ``stale_days`` estaba mal puesto) y el dominio de Noticias SER pasó a publicar guías de finanzas (se quitó).
Lo que faltaba era que un feed callado mucho más de lo esperable avise una vez, sin que lo hagan los que solo publican
a rachas. Fixture: el feed real de Nacional Callao TV del 21-11-2026 (diez entradas, del 18-03 al 22-10-2026).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from enso import news as N
from enso import observatory as obs
from enso.fetch import Fetcher

CALLAO = (Path(__file__).parent / "fixtures" / "news-stale" / "nacional-callao-tv-20261121.xml").read_bytes()


def test_longest_gap_days_sorts_dedups_and_refuses_what_it_cannot_compare():
    assert N.longest_gap_days(["2026-10-22T18:47:03+00:00", "2026-03-18T10:00:00+00:00", "2026-06-26T00:00:00+00:00"]) \
        == 118  # sin ordenar: se ordena; 18-03 → 26-06 son 99 días y 26-06 → 22-10, 118 (días completos)
    assert N.longest_gap_days(["2026-10-22T00:00:00+00:00", "2026-10-22T00:00:00+00:00"]) is None  # una sola fecha
    assert N.longest_gap_days([]) is None and N.longest_gap_days(["2026-10-22T00:00:00+00:00"]) is None
    assert N.longest_gap_days(["2026-10-22T00:00:00", "2026-10-01T00:00:00+00:00"]) is None  # con y sin zona
    assert N.longest_gap_days(["no es fecha", "2026-10-01T00:00:00+00:00"]) is None


def test_the_real_feed_reports_its_longest_gap():
    parsed = N.parse_any(CALLAO, base_url="https://nacionalcallaotv.pe/feed/", default_tz=N.LIMA,
                         now=datetime(2026, 11, 21, tzinfo=timezone.utc), adapter="feed")
    dates = [e["published"] for e in parsed.items]
    assert len(dates) == 10 and all(dates)  # todas con fecha: el lector no pierde entradas nuevas
    assert max(dates) == "2026-10-22T18:47:03+00:00"
    assert N.longest_gap_days(dates) == 111  # 26-06 → 15-10-2026


def _st(latest, gap=None, ok=True):
    return {"ok": ok, "latest": latest, **({"longestGapDays": gap} if gap is not None else {})}


NOW = datetime(2026, 11, 21, 2, 0, tzinfo=timezone.utc)


def test_a_daily_outlet_silent_for_twice_its_window_is_stale():
    f = N.FEED_BY_ID["andina"]  # stale_days=7, publica a toda hora
    assert obs.feed_stale(f, _st("2026-11-08T00:00:00+00:00", gap=0), NOW) is None  # 13 días: aún inactivo
    assert obs.feed_stale(f, _st("2026-11-07T00:00:00+00:00", gap=0), NOW) == {"days": 14, "after": 14}


def test_an_outlet_that_publishes_in_bursts_waits_for_its_longest_gap():
    f = N.FEED_BY_ID["rpp-huancavelica"]  # stale_days=30; huecos de hasta 70 días en su feed
    assert obs.feed_stale(f, _st("2026-10-19T01:15:49+00:00", gap=70), NOW) is None  # 33 días
    assert obs.feed_stale(f, _st("2026-09-12T00:00:00+00:00", gap=70), NOW) is None  # 70 días: su hueco más largo
    assert obs.feed_stale(f, _st("2026-09-11T00:00:00+00:00", gap=70), NOW) == {"days": 71, "after": 71}
    # Sin hueco conocido (una sola entrada), basta el doble de stale_days.
    assert obs.feed_stale(f, _st("2026-09-21T00:00:00+00:00"), NOW) == {"days": 61, "after": 60}


def test_a_dead_feed_warns_even_if_it_was_silent_for_years_before():
    f = N.FEED_BY_ID["rpp-huancavelica"]
    assert obs.feed_stale(f, _st("2026-05-24T00:00:00+00:00", gap=900), NOW)["after"] == 181


def test_quiet_official_alerts_failed_or_undated_feeds_are_not_stale():
    assert obs.feed_stale(N.FEED_BY_ID["igp-cenvul-alertas"], _st("2026-06-01T16:54:00Z", gap=37), NOW) is None
    assert obs.feed_stale(N.FEED_BY_ID["andina"], _st("2026-01-01T00:00:00+00:00", ok=False), NOW) is None
    assert obs.feed_stale(N.FEED_BY_ID["andina"], _st(None), NOW) is None
    assert obs.feed_stale(N.FEED_BY_ID["andina"], _st("2026-01-01T00:00:00"), NOW) is None  # sin zona: no compara
    assert obs.feed_stale(None, _st("2026-01-01T00:00:00+00:00"), NOW) is None


def _run(tmp_path, monkeypatch, now, prev=(), status=200):
    feed = N.FEED_BY_ID["nacional-callao-tv"]
    monkeypatch.setattr(N, "FEEDS", [feed])
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(**{**kw, "transport": httpx.MockTransport(
        lambda req: httpx.Response(status, content=CALLAO if status == 200 else b"",
                                   headers={"content-type": "application/rss+xml"}))}))
    site = tmp_path / "site"
    (site / "news").mkdir(parents=True)
    (site / "news" / "feeds.json").write_text(json.dumps({"feeds": list(prev)}), encoding="utf-8")
    fetcher = Fetcher(polite_delay=0)
    log = obs.EventLog()
    got = obs.acquire_news(fetcher, None, obs.PreviousPublication(str(site), fetcher), log, now, None)
    return {s["id"]: s for s in got["feeds"]["feeds"]}["nacional-callao-tv"], log


def test_pipeline_keeps_a_bursty_outlet_as_info(tmp_path, monkeypatch):
    st, log = _run(tmp_path, monkeypatch, datetime(2027, 1, 10, 12, tzinfo=timezone.utc))  # 79 días: > 60
    assert st["ok"] and not st["active"] and st["longestGapDays"] == 111
    assert [e.severity for e in log.events if e.code == "feed-inactive"] == ["info"]
    assert not [e for e in log.events if e.code == "feed-stale"]


def test_pipeline_escalates_once_per_feed_when_silence_beats_its_history(tmp_path, monkeypatch):
    st, log = _run(tmp_path, monkeypatch, datetime(2027, 3, 1, 12, tzinfo=timezone.utc))  # 129 días: > 2×60, > 111
    warn = [e for e in log.events if e.code == "feed-stale"]
    assert len(warn) == 1 and warn[0].severity == "warning" and warn[0].source == "news-nacional-callao-tv"
    assert "2026-10-22" in warn[0].message and "129 días" in warn[0].message and "a los 120" in warn[0].message
    assert not [e for e in log.events if e.code == "feed-inactive"]  # el aviso reemplaza la «info», no se suma


def test_a_stale_feed_that_fails_one_day_keeps_its_issue_open(tmp_path, monkeypatch):
    # Nacional Callao TV a veces responde con la verificación de Imunify360: ese día no hay fecha que medir, pero el
    # issue no debe cerrarse y reabrirse. La publicación anterior lo marcó «stale».
    prev = {"id": "nacional-callao-tv", "name": "Nacional Callao TV", "ok": True, "active": False,
            "latest": "2026-10-22T18:47:03+00:00", "longestGapDays": 111, "checkedAt": "2027-02-28T12:00:00+00:00",
            "stale": {"days": 128, "after": 120}}
    st, log = _run(tmp_path, monkeypatch, datetime(2027, 3, 1, 12, tzinfo=timezone.utc), prev=[prev], status=503)
    assert not st["ok"] and st["stale"] == {"days": 129, "after": 120, "latest": "2026-10-22T18:47:03+00:00",
                                         "longestGapDays": 111}
    warn = [e for e in log.events if e.code == "feed-stale"]
    assert len(warn) == 1 and warn[0].source == "news-nacional-callao-tv" and "hoy no respondió" in warn[0].message
    # Sin la marca de la corrida anterior, una caída es solo una caída.
    st, log = _run(tmp_path / "b", monkeypatch, datetime(2027, 3, 1, 12, tzinfo=timezone.utc),
                   prev=[{k: v for k, v in prev.items() if k != "stale"}], status=503)
    assert "stale" not in st and not [e for e in log.events if e.code == "feed-stale"]


def test_a_feed_back_to_publishing_drops_the_mark(tmp_path, monkeypatch):
    prev = {"id": "nacional-callao-tv", "ok": True, "latest": "2026-06-26T00:00:00+00:00", "stale": {"days": 1, "after": 1}}
    st, log = _run(tmp_path, monkeypatch, datetime(2026, 11, 21, 12, tzinfo=timezone.utc), prev=[prev])
    assert st["active"] and "stale" not in st and not [e for e in log.events if e.code == "feed-stale"]


def test_noticias_ser_domain_now_publishes_finance_guides_and_is_not_read():
    # Desde el 17-04-2026 www.noticiasser.pe publica guías de tarjetas, seguros e inversiones (143 entradas, todas en
    # la categoría «general»): no son las noticias de la Asociación SER. Si vuelve, que sea con evidencia nueva.
    assert "noticias-ser" not in N.FEED_BY_ID
    assert not any("noticiasser.pe" in f.url for f in N.FEEDS)


def test_two_failed_days_in_a_row_keep_the_issue_open(tmp_path, monkeypatch):
    # El estado de una caída no trae ``latest``: la marca guarda la fecha y el hueco medidos, o el issue se cerraría
    # al segundo día de caída y se reabriría al volver el feed.
    prev = {"id": "nacional-callao-tv", "name": "Nacional Callao TV", "ok": True, "active": False,
            "latest": "2026-10-22T18:47:03+00:00", "longestGapDays": 111, "checkedAt": "2027-02-28T12:00:00+00:00",
            "stale": {"days": 128, "after": 120}}
    day1, _ = _run(tmp_path, monkeypatch, datetime(2027, 3, 1, 12, tzinfo=timezone.utc), prev=[prev], status=503)
    day2, log = _run(tmp_path / "b", monkeypatch, datetime(2027, 3, 2, 12, tzinfo=timezone.utc), prev=[day1], status=503)
    warn = [e for e in log.events if e.code == "feed-stale"]
    assert len(warn) == 1 and warn[0].source == "news-nacional-callao-tv" and "2026-10-22" in warn[0].message
    assert day2["stale"]["days"] == 130 and day2["stale"]["after"] == 120
    # Y cuando el feed vuelve sin entradas nuevas, sigue siendo el mismo aviso.
    day3, log = _run(tmp_path / "c", monkeypatch, datetime(2027, 3, 3, 12, tzinfo=timezone.utc), prev=[day2])
    assert [e.source for e in log.events if e.code == "feed-stale"] == ["news-nacional-callao-tv"]
