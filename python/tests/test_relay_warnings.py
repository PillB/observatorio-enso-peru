"""Avisos de las copias de los recolectores: vencimiento del token y metas que no se guardaron, con su causa."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from enso import observatory as obs


def _relay(root, kind, expires, hb_expires=None):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    root.mkdir()
    collector = {"kind": kind, "host": kind, "token_expires_at": expires}
    (root / "index.json").write_text(json.dumps({
        "schema": "enso-relay/1", "collected_at": now, "collector": collector, "entries": []}), encoding="utf-8")
    if hb_expires is not None:
        (root / "heartbeat.json").write_text(json.dumps({
            "schema": "enso-relay-heartbeat/1", "at": now, "result": "ok", "reachable": "1/1",
            "collector": {**collector, "token_expires_at": hb_expires}}), encoding="utf-8")
    return root


def _days(n):
    return (datetime.now(timezone.utc) + timedelta(days=n)).isoformat(timespec="seconds")


def test_n8n_relay_warns_before_its_github_token_expires(tmp_path):
    for name, expires, warned in (("soon", _days(10), True), ("later", _days(200), False),
                                  ("none", None, False), ("bad", "pronto", False)):
        log = obs.EventLog()
        assert obs.load_n8n_relay(_relay(tmp_path / name, "n8n", expires), log) is not None
        ev = [e for e in log.events if e.code == "relay-token-expiring"]
        assert bool(ev) is warned, name
        if warned:
            assert ev[0].source == "relay-n8n" and ev[0].severity == "warning"
            assert "n8n" in ev[0].message and "docs/n8n.md" in ev[0].message


def test_a_fresh_n8n_heartbeat_has_the_newer_expiry(tmp_path):
    """El latido se sube en cada corrida; si trae un token renovado, ese manda sobre el del index anterior."""
    log = obs.EventLog()
    obs.load_n8n_relay(_relay(tmp_path / "renewed", "n8n", _days(5), hb_expires=_days(300)), log)
    assert "relay-token-expiring" not in [e.code for e in log.events]


def test_peru_relay_still_warns_with_its_own_instructions(tmp_path):
    log = obs.EventLog()
    obs.load_relay(_relay(tmp_path / "peru", "peru", _days(3)), log)
    ev = [e for e in log.events if e.code == "relay-token-expiring"]
    assert ev and ev[0].source == "relay-peru" and "INSTALAR" in ev[0].message


def test_goal_missed_says_why_the_collector_did_not_save_it(tmp_path):
    root = tmp_path / "relay"
    root.mkdir()
    (root / "index.json").write_text(json.dumps({
        "schema": "enso-relay/1", "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "collector": {"host": "pc-lima"}, "entries": [],
        "goals": {"comunicado": True, "informe técnico": False, "boletín": False},
        "goal_detail": {
            "comunicado": {"url": "https://enfen.imarpe.gob.pe/x.pdf", "saved": True},
            "informe técnico": {"url": "https://enfen.imarpe.gob.pe/y.pdf", "saved": False, "class": "challenge",
                                "status": 403}}}), encoding="utf-8")
    log = obs.EventLog()
    obs.load_relay(root, log)
    ev, = [e for e in log.events if e.code == "relay-goal-missed"]
    assert "informe técnico (challenge, HTTP 403, enfen.imarpe.gob.pe)" in ev.message
    # Un kit anterior no manda goal_detail: la meta se nombra sola, como antes.
    assert "enfen.imarpe.gob.pe), boletín; revisar" in ev.message
    assert "comunicado" not in ev.message
