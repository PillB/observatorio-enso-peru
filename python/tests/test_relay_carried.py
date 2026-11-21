"""Copias que un recolector (n8n, Perú) arrastra de una corrida anterior, en las fuentes de datos (no noticias).

n8n (``n8n/lib/relay.js`` ``buildSnapshot``, ``carry_hours`` = 72) y el recolector del Perú
(``peru_collector.carry_forward``, ``CARRY_HOURS`` = 72) conservan la última copia buena de una URL que esta vez
falló o no se pidió, con ``carried: true`` y ``last_attempt``. Antes de este cambio solo los feeds de avisos lo
mostraban (``upstreamDown``); un índice ENSO leído de una copia arrastrada salía como «Vía n8n», con un
``relay-channel`` de nivel info que nadie lee."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from enso import freshness
from enso import observatory as obs
from enso.fetch import Relay, Response

FIX = Path(__file__).parent / "fixtures" / "sources"
ONI = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"


def _relay(tmp_path: Path, kind: str | None, entry: dict, body: bytes) -> Relay:
    (tmp_path / "files").mkdir(parents=True, exist_ok=True)
    (tmp_path / "files" / "0123456789abcdef.txt").write_bytes(body)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (tmp_path / "index.json").write_text(json.dumps({
        "schema": "enso-relay/1", "collected_at": now, "collector": {"kind": kind} if kind else {"host": "pe"},
        "entries": [{"url": ONI, "status": 200, "file": "files/0123456789abcdef.txt",
                     "sha256": hashlib.sha256(body).hexdigest(), "content_type": "text/plain", **entry}]}),
        encoding="utf-8")
    return Relay(tmp_path)


def _ago(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")


def test_relay_marks_carried_copies_and_reads_both_collector_formats(tmp_path):
    body = (FIX / "cpc-oni.txt").read_bytes()
    fresh = _relay(tmp_path / "a", "n8n", {"fetched_at": _ago(1)}, body).get(ONI)
    assert fresh and not fresh.carried and fresh.upstream_down is None

    n8n = _relay(tmp_path / "b", "n8n", {"fetched_at": _ago(30), "carried": True,
                                         "last_attempt": {"at": _ago(1), "verdict": "server_error", "status": 503}},
                 body).get(ONI)
    assert n8n.carried and n8n.upstream_down["status"] == 503 and n8n.upstream_down["verdict"] == "server_error"

    # Recolector del Perú: ``class``/``error`` en lugar de ``verdict``.
    peru = _relay(tmp_path / "c", None, {"fetched_at": _ago(30), "carried": True,
                                         "last_attempt": {"at": _ago(1), "class": "timeout",
                                                          "error": "ConnectTimeout: timed out"}}, body).get(ONI)
    assert peru.channel == "relay-peru" and peru.carried and peru.upstream_down["verdict"] == "timeout"

    # «no se pidió esta noche»: arrastrada, pero el servidor no falló (antes salía {"status": None, …}, que es
    # verdadero y contaba como caída en ``hazard_down``).
    unasked = _relay(tmp_path / "d", None, {"fetched_at": _ago(48), "carried": True,
                                            "last_attempt": {"note": "no se pidió esta noche"}}, body).get(ONI)
    assert unasked.carried and unasked.upstream_down is None

    # El recolector del Perú la tenía en su lista pero no la pidió (plazo agotado o servidor ya caído): en
    # ``carry_forward`` queda ``{"at", "error": "no se pidió: …"}``, sin ``status``. Tampoco es el servidor fallando.
    for why in ("no se pidió: la corrida pasó su plazo de 30 min",
                "no se pidió: el servidor no respondió a las URL anteriores"):
        skipped = _relay(tmp_path / f"e{len(why)}", None, {"fetched_at": _ago(30), "carried": True,
                                                           "last_attempt": {"at": _ago(1), "error": why}},
                         body).get(ONI)
        assert skipped.carried and skipped.upstream_down is None


class _Prev:
    state: dict = {}
    base = None

    def get(self, name, carry=False, tries=1):
        return None


class _Fetch:
    def __init__(self, resp):
        self.resp = resp

    def get(self, urls, **kw):
        return self.resp


def _resp(channel: str, hours: float, carried: bool, down: dict | None = None) -> Response:
    return Response(ONI, (FIX / "cpc-oni.txt").read_bytes(), channel, 200, "text/plain", archived_at=_ago(hours),
                    carried=carried, upstream_down=down)


def test_carried_copy_with_the_server_down_is_a_warning_once_per_source():
    src = obs.SOURCE_BY_ID["cpc-oni"]
    log = obs.EventLog()
    acq = obs.acquire(src, _Fetch(_resp("relay-n8n", 50, True, {"status": 503, "verdict": "server_error",
                                                                "at": _ago(1)})), None, _Prev(), log)
    assert acq.ok and acq.relay_carried and acq.upstream_down["status"] == 503
    ev = [e for e in log.events if e.source == "cpc-oni" and e.stage == "fetch"]
    assert [(e.severity, e.code) for e in ev] == [("warning", "relay-carried-copy")]  # sin relay-channel además
    assert "503" in ev[0].message and "2.1 días" in ev[0].message
    fields = obs._relay_fields(acq)
    assert fields["relayCarried"] and fields["upstreamDown"]["status"] == 503 and fields["copyAt"] == acq.archived_at


def test_fresh_or_unrequested_carried_copies_stay_info():
    src = obs.SOURCE_BY_ID["cpc-oni"]
    log = obs.EventLog()
    acq = obs.acquire(src, _Fetch(_resp("relay-n8n", 2, False)), None, _Prev(), log)
    assert not acq.relay_carried and obs._relay_fields(acq) == {}  # lo publicado de siempre no cambia
    assert [(e.severity, e.code) for e in log.events if e.stage == "fetch"] == [("info", "relay-channel")]

    log = obs.EventLog()
    obs.relay_event(src, _resp("relay-peru", 30, True), log)
    assert [(e.severity, e.code) for e in log.events] == [("info", "relay-channel")]
    assert "esta vez no se pidió" in log.events[0].message


def test_carried_copy_older_than_the_cadence_warns_even_if_not_requested():
    src = obs.SOURCE_BY_ID["cpc-wksst"]  # semanal
    assert src.cadence_days == 7
    log = obs.EventLog()
    obs.relay_event(src, _resp("relay-peru", 8 * 24, True), log)
    assert [(e.severity, e.code) for e in log.events] == [("warning", "relay-carried-copy")]
    log = obs.EventLog()
    obs.relay_event(src, _resp("relay-manual", 30 * 24, True), log)  # subida a mano: el documento no cambia
    obs.relay_event(src, _resp("direct", 0, False), log)
    assert log.events == []


def test_freshness_shows_the_carried_copy_without_degrading_each_series():
    """El estado lo mide el periodo del dato (``stale-*``, ``late-*``); la copia arrastrada se ve en el ítem, y la
    incidencia es una por fuente (``relay-carried-copy``), no una ``late-*`` por cada serie del CPC."""
    series = {"oni": {"label": "ONI", "source": "cpc-oni", "periodKind": "season", "sloDays": 80,
                      "latest": {"period": "2026-09", "value": -0.5, "stale": False, "carried": False}}}
    meta = {"cpc-oni": {"channel": "relay-n8n", "retrievedAt": "2026-11-21T04:00:00+00:00", "relayCarried": True,
                        "copyAt": "2026-11-19T03:52:36+00:00", "upstreamDown": {"status": 503}}}
    item = freshness._series_item("oni", series["oni"], date(2026, 11, 21), meta)
    assert item["relayCarried"] and item["copyAt"].startswith("2026-11-19") and item["upstreamDown"]["status"] == 503
    plain = freshness._series_item("oni", series["oni"], date(2026, 11, 21), {"cpc-oni": {"channel": "relay-n8n"}})
    assert item["state"] == plain["state"] and "relayCarried" not in plain


def test_unrequested_peru_carry_does_not_count_as_a_hazard_feed_down(tmp_path):
    body = (FIX / "cpc-oni.txt").read_bytes()
    r = _relay(tmp_path, None, {"fetched_at": _ago(30), "carried": True,
                                "last_attempt": {"note": "no se pidió esta noche"}}, body).get(ONI)
    st = {"id": "x", "ok": True, "checkedAt": _ago(0), **({"upstreamDown": r.upstream_down} if r.upstream_down else {})}
    assert not obs.hazard_down(st)
