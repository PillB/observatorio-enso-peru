"""D20 de GODAS: decodificador GRIB1, cálculo de D20 y serie publicada."""

from __future__ import annotations

import json
import struct

import pytest

from enso.feeds import FormatChanged, godas
from conftest import FIX


# ---------------------------------------------------------------------------
# Codificador GRIB1 mínimo para las pruebas (mismo subconjunto que GODAS)
# ---------------------------------------------------------------------------
def _u(v: int, n: int) -> bytes:
    return v.to_bytes(n, "big")


def _s(v: int, n: int) -> bytes:
    return _u(abs(v) | (1 << (8 * n - 1)) if v < 0 else v, n)


def _ibm(x: float) -> bytes:
    if x == 0:
        return b"\0\0\0\0"
    sign = 0x80 if x < 0 else 0
    x = abs(x)
    e = 64
    while x >= 1:
        x /= 16
        e += 1
    while x < 1 / 16:
        x *= 16
        e -= 1
    return bytes([sign | e]) + _u(int(x * 2 ** 24), 3)


def encode(values, ni, nj, lat1, lon1, lat2, lon2, *, depth=5, param=13, nbits=16, dscale=2):
    """``values``: lista fila por fila (j, luego i); ``None`` = tierra (fuera del mapa de bits)."""
    pds = bytearray(28)
    pds[0:3] = _u(28, 3)
    pds[7] = 0x80 | 0x40
    pds[8], pds[9] = param, 160
    pds[10:12] = _u(depth, 2)
    pds[26:28] = _s(dscale, 2)
    gds = bytearray(32)
    gds[0:3] = _u(32, 3)
    gds[5] = 0
    gds[6:8], gds[8:10] = _u(ni, 2), _u(nj, 2)
    gds[10:13], gds[13:16] = _s(int(lat1 * 1000), 3), _s(int(lon1 * 1000), 3)
    gds[17:20], gds[20:23] = _s(int(lat2 * 1000), 3), _s(int(lon2 * 1000), 3)
    gds[27] = 0x40  # barrido por filas, j hacia el norte
    bits = [v is not None for v in values]
    bm = bytearray((len(bits) + 7) // 8)
    for k, b in enumerate(bits):
        if b:
            bm[k >> 3] |= 0x80 >> (k & 7)
    bms = _u(6 + len(bm), 3) + b"\0" + _u(0, 2) + bytes(bm)
    present = [round(v * 10 ** dscale) for v in values if v is not None]
    ref = min(present)
    acc, nacc, packed = 0, 0, bytearray()
    for x in present:
        acc = (acc << nbits) | (x - ref)
        nacc += nbits
        while nacc >= 8:
            nacc -= 8
            packed.append((acc >> nacc) & 0xFF)
    if nacc:
        packed.append((acc << (8 - nacc)) & 0xFF)
    bds = bytearray(11)
    bds[3] = 0
    bds[4:6] = _s(0, 2)
    bds[6:10] = _ibm(float(ref))
    bds[10] = nbits
    bds = bytes(bds) + bytes(packed)
    bds = _u(len(bds), 3) + bds[3:]
    body = bytes(pds) + bytes(gds) + bms + bds + b"7777"
    return b"GRIB" + _u(8 + len(body), 3) + b"\x01" + body


GRID = dict(ni=4, nj=3, lat1=-1.0, lon1=270.0, lat2=1.0, lon2=273.0)


def column_file(temps_by_depth: dict[int, list]) -> bytes:
    return b"".join(encode([None if t is None else t + 273.15 for t in temps], **GRID, depth=d)
                    for d, temps in sorted(temps_by_depth.items()))


def test_decoder_reads_values_and_skips_land():
    vals = [None, 25.5, 24.0, 23.25, 20.0, None, 18.75, 30.0, 26.0, 21.5, None, 19.0]
    msg = encode(vals, **GRID)
    f = godas.decode(msg, range(12))
    assert (f.ni, f.nj, f.lat1, f.lon2) == (4, 3, -1.0, 273.0)
    for k, v in enumerate(vals):
        if v is None:
            assert k not in f.values
        else:
            assert f.values[k] == pytest.approx(v, abs=1e-6)


def test_ibm_float_round_trip():
    for x in (1.0, -2.5, 27315.0, 0.15625, 1e-3):
        assert godas._ibm(_ibm(x)) == pytest.approx(x, rel=1e-6)


def test_pot_records_stop_at_the_requested_depth_and_reject_other_fields():
    depths = [5, 15, 25, 35, 45, 55, 65, 75, 85, 95, 105, 115, 125, 135, 145, 155, 165, 175, 185, 195,
              205, 215, 225, 238, 262, 303, 366]
    raw = b"".join(encode([20.0 + 273.15] * 12, **GRID, depth=d) for d in depths)
    recs = godas.pot_records(raw + b"GRIB")  # un mensaje cortado al final del rango no molesta
    assert [d for d, _ in recs] == depths[:-1]
    with pytest.raises(FormatChanged):
        godas.pot_records(b"<html>403 Forbidden</html>")
    with pytest.raises(FormatChanged):
        godas.pot_records(raw[:len(raw) // 3])  # faltan niveles: no se calcula con un perfil corto


@pytest.mark.parametrize("temps,expected", [
    ([28, 27, 22, 18, 15], 30.0),  # cruza entre 25 y 35 m: 25 + (22-20)/(22-18)·10
    ([19.5, 18, 15], 0.0),  # aflora: el agua de superficie ya está bajo 20 °C
    ([20, 20, 19], 15.0),  # 20 °C exactos: el cruce queda en el último nivel a 20 °C
    ([25, 24, 23], None),  # no cruza en el perfil pedido
])
def test_d20_profile(temps, expected):
    depths = [5, 15, 25, 35, 45][:len(temps)]
    assert godas.d20_profile(depths, temps) == (None if expected is None else pytest.approx(expected))


def test_regional_d20_weights_sea_points_and_counts_outcrop():
    depths = [5, 15, 25, 35, 45, 55, 65, 75, 85, 95, 105, 115, 125, 135, 145, 155, 165, 175, 185, 195,
              205, 215, 225, 238, 262, 303]
    # Columna A: 25 °C hasta 45 m y 15 °C desde 55 m → D20 = 50 m. Columna B: 18 °C → aflora (0 m).
    a = [25.0 if d <= 45 else 15.0 for d in depths]
    b = [18.0] * len(depths)
    cols = {d: [None, a[i], b[i], a[i], a[i], a[i], a[i], a[i], a[i], a[i], a[i], a[i]] for i, d in enumerate(depths)}
    recs = godas.pot_records(column_file(cols))
    regions = {"r": {"lat": (-1.0, 1.0), "lon": (270.0, 273.0)}, "s": {"lat": (-1.0, -1.0), "lon": (272.0, 272.0)}}
    out = godas.regional_d20(recs, regions)
    assert out["r"]["points"] == 11 and out["r"]["outcrop"] == pytest.approx(1 / 11, abs=1e-3)
    # Los pesos cos(lat) de ±1° son casi iguales: (10·50 + 0)/11.
    assert out["r"]["d20"] == pytest.approx(500 / 11, abs=0.05)
    assert out["s"] == {"d20": 0.0, "points": 1, "outcrop": 1.0}


def test_history_file_is_complete_and_plausible():
    h = godas.load_history()
    assert h["base_period"] == "1991–2020"
    for key in godas.REGIONS:
        clim = h["climatology"][key]
        assert len(clim) == 12 and all(0 < c < 250 for c in clim)
        pts = h["monthly"][key]
        assert pts[0]["period"] == "1980-01" and len(pts) >= 12 * 46
        # 1997–98: termoclina muy profunda frente al Perú en diciembre de 1997 y somera en Niño 3.4 a mediados de 1998.
    by = {k: {p["period"]: p["d20"] for p in h["monthly"][k]} for k in godas.REGIONS}
    assert by["d20_nino12"]["1997-12"] - h["climatology"]["d20_nino12"][11] > 50
    assert by["d20_nino34"]["1998-06"] - h["climatology"]["d20_nino34"][5] < -20


def test_build_series_merges_live_months_and_computes_anomalies():
    h = {"base_period": "1991–2020", "climatology": {k: [40.0] * 12 for k in godas.REGIONS},
         "monthly": {k: [{"period": f"2025-{m:02d}", "d20": 40.0 + m, "outcrop": 0.0} for m in range(1, 13)]
                     for k in godas.REGIONS}}
    live = {"months": {"2025-12": {k: {"d20": 100.0, "outcrop": 0.0} for k in godas.REGIONS},
                       "2026-01": {k: {"d20": 95.5, "outcrop": 0.25} for k in godas.REGIONS}}}
    p = godas.build_series(live, h)
    pts = p.data["d20_nino12"]
    assert pts[-1] == {"period": "2026-01", "value": 55.5, "d20": 95.5, "outcrop": 0.25}
    assert pts[-2]["value"] == 60.0  # el mes leído reemplaza al del histórico
    assert p.meta["liveMonths"] == ["2025-12", "2026-01"]


def test_months_to_fetch_starts_at_the_last_history_month():
    from datetime import date

    h = {"monthly": {"x": [{"period": "2026-08"}, {"period": "2026-09"}]}}
    assert godas.months_to_fetch(h, date(2026, 10, 21)) == [(2026, 9), (2026, 10)]
    assert len(godas.months_to_fetch(h, date(2030, 1, 1))) == godas.MAX_LIVE_MONTHS


def test_fixture_feeds_the_grd_signal(tmp_path):
    from enso import observatory as obs

    out = tmp_path / "pub"
    obs.run(out, None, fixtures=FIX, only=["cpc-godas-d20"])
    dash = json.loads((out / "dashboard.json").read_text(encoding="utf-8"))
    sigs = {s["id"]: s for s in dash["grd"]["signals"]}
    live = json.loads((FIX / "cpc-godas-d20.json").read_text(encoding="utf-8"))
    last = max(live["months"])
    for key in ("d20_coastal", "d20_global"):
        s = sigs[key]
        assert s["value"] is not None and s["period"] == last and s["source"] == "cpc-godas-d20"
        assert s["level"] in ("ok", "watch", "alert", "unclassified") and "GODAS" in s["reason"]


# ---------------------------------------------------------------------------
# Lectura en vivo: plan, caídas, meses no leídos, archivos que faltan, plazos, histórico y reutilización
# ---------------------------------------------------------------------------
import threading  # noqa: E402
import time  # noqa: E402
from datetime import date  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

import httpx  # noqa: E402

from enso import observatory as obs  # noqa: E402
from enso.fetch import FetchError, Fetcher  # noqa: E402

TODAY = date(2026, 10, 19)  # lunes; el histórico termina en 2026-09: se piden 2026-09 (entero) y 2026-10
SRC = obs.SOURCE_BY_ID["cpc-godas-d20"]
GOOD = {k: {"d20": 100.0, "points": 10, "outcrop": 0.0} for k in godas.REGIONS}


class _Log(obs.EventLog):
    def triples(self):
        return [(e.severity, e.stage, e.code) for e in self.events]


def _fetcher(handler, **kw):
    f = Fetcher(polite_delay=0, **kw)
    f.client = httpx.Client(transport=httpx.MockTransport(handler))
    return f


@pytest.fixture
def live(monkeypatch):
    """Día fijo y un decodificador falso: el cuerpo «GOOD» se lee; cualquier otro es un GRIB ilegible."""
    monkeypatch.setattr(obs, "_utc_today", lambda: TODAY)
    monkeypatch.setattr(godas, "pot_records", lambda raw: raw)

    def regional(raw):
        if raw != b"GOOD":
            raise FormatChanged("godas: registro POT con otra grilla")
        return GOOD

    monkeypatch.setattr(godas, "regional_d20", regional)


def _acquire(f, prev=None):
    log = _Log()

    class _Prev(obs.PreviousPublication):
        def get(self, name, tries=1):
            return prev if name == "sources/cpc-godas-d20.json" else None

    return obs.acquire(SRC, f, None, _Prev(None), log), log


def _by_month(answers, asked=None):
    def handler(req):
        if asked is not None:
            asked.append((str(req.url), req.headers.get("range")))
        for k, v in answers.items():
            if k in str(req.url):
                return v(req) if callable(v) else v
        return httpx.Response(404)
    return handler


@pytest.mark.parametrize("plan_or_offline", [{godas.BASE + "/": []}, {godas.BASE + "/": ["peru-server"]}, "offline"])
def test_plan_and_offline_mode_make_no_request(live, plan_or_offline):
    asked = []
    kw = {"offline": True} if plan_or_offline == "offline" else {"plan": plan_or_offline}
    acq, log = _acquire(_fetcher(_by_month({}, asked), **kw))
    assert asked == [] and not acq.ok
    assert log.triples() == [("warning", "fetch", "unreachable")]


@pytest.mark.parametrize("status", [503, 500, 429, 403])
def test_server_outage_is_unreachable_not_a_format_change(live, status):
    acq, log = _acquire(_fetcher(lambda req: httpx.Response(status)))
    assert log.triples() == [("warning", "fetch", "unreachable")] and log.worst() != "error"
    # Sin publicación anterior se publica el histórico versionado (el GRD no queda sin D20).
    assert acq.ok and acq.channel == "previous-publication" and acq.data["d20_nino12"][-1]["period"] == "2026-09"


def test_unreadable_grib_is_still_a_format_change(live):
    acq, log = _acquire(_fetcher(lambda req: httpx.Response(206, content=b"junk")))
    assert ("error", "parse", "format-changed") in log.triples() and not acq.ok


@pytest.mark.parametrize("bad", [httpx.Response(403), httpx.Response(206, content=b"junk")])
def test_a_month_that_fails_to_read_is_reported(live, bad):
    acq, log = _acquire(_fetcher(_by_month({"202609": httpx.Response(206, content=b"GOOD"), "202610": bad})))
    assert acq.ok
    ev = [e for e in log.events if e.code == "month-unread"]
    assert len(ev) == 1 and "2026-10" in ev[0].message and ev[0].severity == "warning"


def test_missing_file_for_a_month_that_must_exist_is_reported(live):
    acq, log = _acquire(_fetcher(lambda req: httpx.Response(404)))
    ev = [e for e in log.events if e.code == "unreachable"]
    assert ev and "2026-09" in ev[0].message and "404" in ev[0].message


def test_404_for_a_month_not_yet_published_is_normal(live):
    acq, log = _acquire(_fetcher(_by_month({"202609": httpx.Response(206, content=b"GOOD")})))
    assert acq.ok and log.events == [] and acq.data["d20_nino12"][-1]["period"] == "2026-09"


def test_connection_refused_with_no_previous_publication_publishes_the_history(live):
    def refuse(req):
        raise httpx.ConnectError("refused", request=req)

    acq, log = _acquire(_fetcher(refuse))
    assert acq.ok and acq.data["d20_nino12"][-1]["period"] == "2026-09"
    assert abs(acq.data["d20_nino12"][-1]["value"] - 83.2) < 0.1
    assert [e.code for e in log.events] == ["unreachable"]


class _Trickle(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(206)
        self.send_header("Content-Length", "1000")
        self.end_headers()
        try:
            for _ in range(1000):
                self.wfile.write(b"x")
                self.wfile.flush()
                time.sleep(0.2)
        except OSError:
            pass

    def log_message(self, *a):
        pass


def test_a_trickling_server_is_cut_by_the_request_limit(live, monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Trickle)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(godas, "url", lambda y, m: f"http://127.0.0.1:{srv.server_port}/godas.M.{y}{m:02d}.grb")
    f = Fetcher(timeout=1, max_seconds=1, budget_s=2, polite_delay=0)
    t = time.monotonic()
    try:
        resp = obs._fetch_godas(f, None, TODAY)
        attempts = resp.attempts
    except FetchError as exc:
        attempts = exc.attempts
    finally:
        srv.shutdown()
    assert time.monotonic() - t < 3.5
    assert f._down["127.0.0.1"] >= 2 and any("TooSlow" in (a.get("error") or "") for a in attempts)


def test_months_to_fetch_keeps_the_last_history_month_and_the_newest():
    h = {"monthly": {"x": [{"period": "2026-09"}]}}
    got = godas.months_to_fetch(h, date(2030, 1, 1))
    assert len(got) == godas.MAX_LIVE_MONTHS and got[0] == (2026, 9) and got[-1] == (2030, 1) and (2029, 12) in got


def test_old_history_is_reported(live, monkeypatch):
    monkeypatch.setattr(obs, "_utc_today", lambda: date(2027, 12, 15))
    acq, log = _acquire(_fetcher(lambda req: httpx.Response(206, content=b"GOOD")))
    assert ("warning", "fetch", "history-old") in log.triples()


def test_months_already_read_are_reused_with_a_one_byte_check(live, monkeypatch):
    monkeypatch.setattr(obs, "_utc_today", lambda: date(2027, 1, 15))  # un viernes
    prev = {"data": {k: [{"period": p, "value": 1.0, "d20": 90.0, "outcrop": 0.0} for p in ("2026-09", "2026-10")]
                     for k in godas.REGIONS}}
    asked = []
    acq, log = _acquire(_fetcher(_by_month({"202611": httpx.Response(206, content=b"GOOD"),
                                            "202612": httpx.Response(206, content=b"GOOD"),
                                            "godas.M.2027": httpx.Response(206, content=b"GOOD"),
                                            "godas.M.2026": httpx.Response(206, content=b"x")}, asked)), prev)
    ranges = {u.rsplit(".", 2)[-2][-6:]: r for u, r in asked}
    assert ranges["202609"] == ranges["202610"] == "bytes=0-0"
    assert ranges["202611"] == ranges["202612"] == f"bytes=0-{godas.RANGE_BYTES - 1}"
    pers = [p["period"] for p in acq.data["d20_nino12"]]
    assert "2026-10" in pers and "2026-12" in pers and log.events == []
    body = json.loads(acq.raw)
    assert body["reused"] == ["2026-09", "2026-10"] and all("godas.M." in u for u in body["grib"])


def test_last_history_month_is_only_checked_except_on_mondays(live, monkeypatch):
    monkeypatch.setattr(obs, "_utc_today", lambda: date(2026, 10, 22))  # jueves
    asked = []
    acq, log = _acquire(_fetcher(_by_month({"202609": httpx.Response(206, content=b"x"),
                                            "202610": httpx.Response(404)}, asked)))
    assert dict((u[-10:-4], r) for u, r in asked)["202609"] == "bytes=0-0"
    assert acq.ok and log.events == [] and acq.data["d20_nino12"][-1]["period"] == "2026-09"
