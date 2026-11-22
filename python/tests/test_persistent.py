"""Degradación persistente (enso.persistent, ``degraded-persistent``): la cuenta pasa de una publicación a la siguiente,
escala una vez pasado el umbral de la cadencia y se cierra sola al volver a estar bien."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from conftest import FIX
from enso import observatory as obs
from enso import persistent as P
from tools import sync_issues as S

T0 = datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc)
PLAN = {"https://www.gob.pe/a.rss": ["actions", "n8n"], "https://www.gob.pe/b.rss": ["actions", "n8n"],
        "https://enfen.imarpe.gob.pe/comunicados/": ["peru-server"], "https://n8n-only/feed": ["n8n"]}


def _src(sid="cpc-oni", cadence=31):
    return SimpleNamespace(id=sid, institution="NOAA", product="ONI", cadence_days=cadence)


def _acq(ok=True, channel="direct", url="https://www.gob.pe/a.rss", carried=False):
    return SimpleNamespace(ok=ok, channel=channel, url=url, carried=carried, error="" if ok else "HTTP 503")


def _feed(fid, url, stale_days=7, official=False):
    return SimpleNamespace(id=fid, url=url, stale_days=stale_days, official=official)


def _st(fid, **kw):
    base = {"id": fid, "name": fid.upper(), "ok": True, "active": True, "items": 5, "latest": "2026-11-01T00:00:00+00:00",
            "checkedAt": T0.isoformat(), "error": ""}
    return {**base, **kw}


def _runs(n, step_h=24, start=T0, **kw):
    """n corridas seguidas, cada una con la cuenta de la anterior; devuelve (estado, log de la última)."""
    state = None
    for i in range(n):
        log = obs.EventLog()
        now = start + timedelta(hours=step_h * i)
        args = {k: (v(now) if callable(v) else v) for k, v in kw.items()}
        state = P.update(state, now, log, plan=PLAN, official=lambda f: getattr(f, "official", False), **args)
    return state, log


def _codes(log):
    return [(e.source, e.severity) for e in log.events if e.code == P.CODE]


def test_unplanned_relay_escalates_once_past_its_threshold_and_closes_when_healthy():
    srcs = [(_src(), _acq(channel="relay-n8n"))]
    st, log = _runs(3, sources=srcs)
    assert st["entities"]["source:cpc-oni"]["runs"] == 3 and not _codes(log)  # 2 días: el umbral es de 14 (31 d)
    st, log = _runs(15, sources=srcs)
    assert _codes(log) == [("cpc-oni", "warning")]
    rec = st["entities"]["source:cpc-oni"]
    assert rec["escalated"] and rec["since"] == T0.isoformat() and rec["thresholdDays"] == 14
    # Vuelve directo: una corrida buena no basta (el issue sigue abierto); con 24 h y 2 corridas buenas sale del
    # estado y la incidencia deja de aparecer (sync_issues la cierra).
    log = obs.EventLog()
    st2 = P.update(st, T0 + timedelta(days=15), log, sources=[(_src(), _acq())], plan=PLAN)
    assert st2["entities"]["source:cpc-oni"]["okRuns"] == 1 and _codes(log) == [("cpc-oni", "warning")]
    assert "se cierra si sigue bien" in log.events[0].message
    log = obs.EventLog()
    st3 = P.update(st2, T0 + timedelta(days=16), log, sources=[(_src(), _acq())], plan=PLAN)
    assert "source:cpc-oni" not in st3["entities"] and not _codes(log)


def test_flapping_keeps_counting_instead_of_resetting():
    """Una corrida con copia de n8n y otra directa (gob.pe, 20 y 21-11-2026): la cuenta no vuelve a cero."""
    bad, good = [(_src(cadence=7), _acq(channel="relay-n8n"))], [(_src(cadence=7), _acq())]
    st, log = None, None
    for i in range(16):  # dos corridas por día, 12 h entre ellas, alternando
        log = obs.EventLog()
        st = P.update(st, T0 + timedelta(hours=12 * i), log, sources=bad if i % 2 == 0 else good, plan=PLAN)
    rec = st["entities"]["source:cpc-oni"]
    assert rec["since"] == T0.isoformat() and rec["runs"] == 8 and rec["escalated"]
    assert _codes(log) == [("cpc-oni", "warning")]


def test_relay_that_the_registry_assigns_to_the_peru_collector_is_not_degraded():
    srcs = [(_src("enfen-comunicados", 14), _acq(channel="relay-peru", url="https://enfen.imarpe.gob.pe/comunicados/"))]
    st, log = _runs(20, sources=srcs)
    assert st["entities"] == {} and not _codes(log)


def test_carried_source_is_tracked_but_not_escalated_twice():
    """Una fuente que falla ya escala con unreachable/format-changed: aquí solo se cuenta."""
    st, log = _runs(20, sources=[(_src(cadence=7), _acq(ok=False, carried=True))])
    rec = st["entities"]["source:cpc-oni"]
    assert rec["state"] == "carried" and rec["runs"] == 20 and not rec["escalated"] and not _codes(log)


def test_two_runs_on_the_same_day_do_not_reach_a_day_threshold():
    st, log = _runs(6, step_h=1, sources=[(_src(cadence=1), _acq(channel="archive"))])
    assert st["entities"]["source:cpc-oni"]["runs"] == 6 and not _codes(log)


def test_media_feeds_are_grouped_by_state_official_feeds_get_their_own_issue():
    feeds = [(_feed("gobpe-a", "https://www.gob.pe/a.rss"), _st("gobpe-a", channel="relay-n8n")),
             (_feed("gobpe-b", "https://www.gob.pe/b.rss"), _st("gobpe-b", channel="relay-n8n")),
             (_feed("senamhi-x", "https://www.gob.pe/a.rss", official=True), _st("senamhi-x", channel="relay-n8n")),
             (_feed("onu", "https://n8n-only/feed"), _st("onu", channel="relay-n8n"))]  # el registro lo da a n8n
    st, log = _runs(4, feeds=feeds)
    assert sorted(_codes(log)) == [("feeds-relay", "warning"), ("news-senamhi-x", "warning")]
    group = next(e for e in log.events if e.source == "feeds-relay")
    assert "(2; relay:" in group.message and "GOBPE-A" in group.message and "ONU" not in group.message
    assert "feed:onu" not in st["entities"]


def test_official_feed_down_is_left_to_hazard_feed_down():
    feeds = [(_feed("ciifen", "https://x/feed", official=True), _st("ciifen", ok=False, error="HTTP 500"))]
    st, log = _runs(10, feeds=feeds)
    assert st["entities"]["feed:ciifen"]["state"] == "down" and not _codes(log)


def test_days_in_a_state_covered_elsewhere_do_not_escalate_the_next_state_at_once():
    """Un feed oficial caído tres días (issue de hazard-feed-down) que en la cuarta corrida llega solo por n8n: no es
    un «relay» persistente; si alterna caído y relay, las corridas de relay sí se suman."""
    f = _feed("senamhi-x", "https://www.gob.pe/a.rss", official=True)
    state = None
    for i in range(4):
        log = obs.EventLog()
        st = _st("senamhi-x", ok=False, error="HTTP 503") if i < 3 else _st("senamhi-x", channel="relay-n8n")
        state = P.update(state, T0 + timedelta(days=i), log, feeds=[(f, st)], plan=PLAN,
                         official=lambda x: getattr(x, "official", False))
    rec = state["entities"]["feed:senamhi-x"]
    assert rec["state"] == "relay" and rec["escRuns"] == 1 and not rec["escalated"] and not _codes(log)
    state = None
    for i in range(8):
        log = obs.EventLog()
        st = _st("senamhi-x", ok=False, error="HTTP 503") if i % 2 else _st("senamhi-x", channel="relay-n8n")
        state = P.update(state, T0 + timedelta(days=i), log, feeds=[(f, st)], plan=PLAN,
                         official=lambda x: getattr(x, "official", False))
        if i == 6:
            assert _codes(log) == [("news-senamhi-x", "warning")]  # 4 corridas de relay en 6 días


def test_undated_entries_are_unreadable_and_empty_layers_are_fine():
    feeds = [(_feed("cenvul", "https://x/c", official=True), _st("cenvul", items=3, latest=None, active=False)),
             (_feed("capa", "https://x/l", official=True), _st("capa", items=0, latest=None, active=False))]
    st, log = _runs(3, feeds=feeds)
    assert st["entities"]["feed:cenvul"]["state"] == "unreadable" and "feed:capa" not in st["entities"]
    assert _codes(log) == [("news-cenvul", "warning")]


def test_reader_feed_carried_counts_from_its_last_read():
    """Un feed «lector» se lee cada 20 h: entre lecturas no cuenta; si la lectura no se renueva, cuenta desde ella."""
    last = (T0 - timedelta(days=5)).isoformat()
    feeds = [(_feed("gnews", "https://news.google/x"), _st("gnews", carried=True, checkedAt=last))]
    st, log = _runs(3, feeds=feeds)
    assert st["entities"]["feed:gnews"]["since"] == last and _codes(log) == [("feeds-carried", "warning")]
    fresh = lambda now: [(_feed("gnews", "https://news.google/x"),  # noqa: E731
                          _st("gnews", carried=True, checkedAt=(now - timedelta(hours=20)).isoformat()))]
    st, log = _runs(3, feeds=fresh)
    assert st["entities"] == {}


def test_inactive_counts_from_when_it_went_stale():
    feeds = [(_feed("radio", "https://x/r", stale_days=7), _st("radio", active=False, latest="2026-10-01T00:00:00+00:00"))]
    st, log = _runs(3, feeds=feeds)
    assert st["entities"]["feed:radio"]["since"] == "2026-10-08T00:00:00+00:00"
    # El feed que deja de publicar ya escala con su propio código (``feed-stale``, con la cadencia medida del feed):
    # aquí se cuenta, pero no abre una segunda incidencia.
    assert _codes(log) == []


def test_an_unobserved_run_keeps_the_count_and_the_open_issue():
    srcs = [(_src(), _acq(channel="relay-n8n"))]
    st, _ = _runs(16, sources=srcs)
    assert st["entities"]["source:cpc-oni"]["escalated"]
    log = obs.EventLog()
    st2 = P.update(st, T0 + timedelta(days=16), log, sources=[], feeds=None, plan=PLAN)  # --only / sin noticias
    assert st2["entities"]["source:cpc-oni"]["runs"] == 16 and _codes(log) == [("cpc-oni", "warning")]
    # Fuera del catálogo, o sin revisar por más de forgetDays, se olvida.
    st3 = P.update(st, T0 + timedelta(days=16), obs.EventLog(), sources=[], catalog=set())
    assert st3["entities"] == {}
    st4 = P.update(st, T0 + timedelta(days=60), obs.EventLog(), sources=[])
    assert st4["entities"] == {}


def test_omitted_feed_is_not_observed():
    feeds = [(_feed("gobpe-a", "https://www.gob.pe/a.rss"), _st("gobpe-a", channel="relay-n8n"))]
    st, _ = _runs(4, feeds=feeds)
    log = obs.EventLog()
    st2 = P.update(st, T0 + timedelta(days=4), log, feeds=[(feeds[0][0], _st("gobpe-a", ok=False, omitted=True))],
                   plan=PLAN)
    assert st2["entities"]["feed:gobpe-a"]["runs"] == 4 and _codes(log) == [("feeds-relay", "warning")]


def test_unreadable_previous_state_is_noted():
    log = obs.EventLog()
    P.update(None, T0, log, sources=[], prev_state="unreachable")
    assert [e.code for e in log.events] == ["degraded-unchecked"]


def test_override_can_silence_or_tighten_a_state():
    cfg = json.loads(P.RULES_PATH.read_text(encoding="utf-8"))
    cfg["overrides"] = {"source:cpc-oni": {"relay": None}, "source:cpc-soi": {"relay": {"minDays": 1, "maxDays": 1, "minRuns": 2}}}
    srcs = [(_src(), _acq(channel="relay-n8n")), (_src("cpc-soi"), _acq(channel="relay-n8n"))]
    st, log = _runs(3, sources=srcs, cfg=cfg)
    assert _codes(log) == [("cpc-soi", "warning")]


def test_rules_file_is_coherent():
    cfg = P.rules()
    states = set(cfg["states"])
    for kind, lst in cfg["escalate"].items():
        assert set(lst) <= states, kind
    assert "down" not in cfg["escalate"]["official-feed"]  # hazard-feed-down ya lo escala
    assert not {"carried", "failed"} & set(cfg["escalate"]["source"])  # unreachable/format-changed ya lo escalan
    for s in cfg["states"].values():
        assert s["minDays"] <= s["maxDays"] and s["minRuns"] >= 1


def test_sync_issues_opens_and_closes_it_automatically():
    assert P.CODE not in S.IGNORE and P.CODE not in S.STICKY
    ev = obs.Event("warning", "feeds-relay", "validate", P.CODE, "2 feeds …").as_dict()
    assert S.relevant([ev]) == {ev["fingerprint"]: [ev]}
    assert "Se cierra solo" in S.body_for(ev["fingerprint"], [ev], "pub", "", 1, "2026-11-20")


# ---------------------------------------------------------------------------
# En la publicación completa (capturas, sin red)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def pub(tmp_path_factory):
    out = tmp_path_factory.mktemp("pubdeg") / "data"
    obs.run(out, None, fixtures=FIX)
    return out


def test_publication_carries_the_count_to_the_next_run(pub, tmp_path):
    man = json.loads((pub / "manifest.json").read_text(encoding="utf-8"))
    assert P.FILE in man["files"]
    first = json.loads((pub / P.FILE).read_text(encoding="utf-8"))
    # Las capturas traen al ENFEN por el Internet Archive y feeds inactivos: primera corrida, nada escala aún.
    assert first["entities"]["source:enfen-comunicados"]["state"] == "archive" and first["escalated"] == []
    prev = tmp_path / "prev"
    shutil.copytree(pub, prev)
    old = {"kind": "source", "id": "igp-icen", "state": "carried", "since": "2026-10-01T00:00:00+00:00",
           "stateSince": "2026-10-01T00:00:00+00:00", "runs": 9, "lastAt": "2026-10-30T00:00:00+00:00"}
    gone = {"kind": "source", "id": "fuente-retirada", "state": "relay", "since": "2026-10-01T00:00:00+00:00",
            "runs": 3, "lastAt": "2026-10-30T00:00:00+00:00", "escalated": True}
    (prev / P.FILE).write_text(json.dumps({**first, "entities": {"source:igp-icen": old,
                                                                "source:fuente-retirada": gone}}), encoding="utf-8")
    fx = tmp_path / "fx"
    shutil.copytree(FIX, fx, ignore=shutil.ignore_patterns("history"))
    (fx / "igp-icen.txt").unlink()
    idx = json.loads((fx / "index.json").read_text(encoding="utf-8"))
    idx["entries"] = [e for e in idx["entries"] if e.get("file") != "igp-icen.txt"]
    (fx / "index.json").write_text(json.dumps(idx), encoding="utf-8")
    out = tmp_path / "data"
    obs.run(out, str(prev), fixtures=fx)
    now = json.loads((out / P.FILE).read_text(encoding="utf-8"))["entities"]
    assert now["source:igp-icen"]["runs"] == 10 and now["source:igp-icen"]["since"] == old["since"]
    assert "source:fuente-retirada" not in now  # ya no está en el catálogo
