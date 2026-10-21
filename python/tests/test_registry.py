"""Registro único de fuentes: reglas de canales, validación y archivo al día."""

import json

from enso import registry
from enso.reach import classify
from tools import build_registry, probe_sources

US_OK = {"class": "ok", "at": "2026-10-21T01:00:00+00:00", "vantage": "github-actions"}
US_403 = {"class": "http-403", "at": "2026-10-21T01:00:00+00:00", "vantage": "github-actions"}
US_5XX = {"class": "http-5xx", "at": "2026-10-21T01:00:00+00:00", "vantage": "github-actions"}
PE_OK = {"class": "ok", "at": "2026-10-21T02:00:00+00:00", "vantage": "peru-server"}
PE_FAIL = {"class": "timeout", "at": "2026-10-21T02:00:00+00:00", "vantage": "peru-server"}


def test_geoblock_states():
    u = "https://example.gob.pe/x"
    cases = [
        ({}, "unknown"),
        ({"us": US_OK}, "open"),
        ({"us": US_OK, "peru": PE_FAIL}, "open"),
        ({"us": US_403, "peru": PE_OK}, "geoblocked"),
        ({"us": US_5XX, "peru": PE_OK}, "geoblocked"),
        ({"us": US_403, "peru": PE_FAIL}, "down"),
        ({"us": US_403}, "suspected-geoblock"),
        ({"us": US_5XX}, "down"),
    ]
    for reach, want in cases:
        gb = registry.geoblock(u, {u: reach})
        assert gb["status"] == want, (reach, gb)
    gb = registry.geoblock(u, {u: {"us": US_403, "peru": PE_OK}})
    assert gb["from"] == ["github-actions", "peru-server"]
    assert gb["measured_at"] == PE_OK["at"]


def test_peru_server_iff_geoblocked():
    for status in ("open", "unknown", "down"):
        assert "peru-server" not in registry.channels_for(status)
    for status in ("geoblocked", "suspected-geoblock"):
        assert registry.channels_for(status) == ["peru-server"]


def test_build_is_valid_and_routes_by_measurement():
    reg = registry.build(reach={})
    assert reg["schema"] == registry.SCHEMA
    assert registry.validate(reg) == []
    ids = [s["id"] for s in reg["sources"]]
    assert len(ids) == len(set(ids))
    url = reg["sources"][0]["url"]
    reg = registry.build(reach={url: {"us": US_403, "peru": PE_OK}})
    first = reg["sources"][0]
    assert first["geoblocked"] is True and first["channels"] == ["peru-server"]
    assert all(s["channels"] == ["actions", "n8n"] for s in reg["sources"][1:] if s["url"] != url)
    assert registry.validate(reg) == []


def test_validate_catches_mistakes():
    reg = registry.build(reach={})
    bad = json.loads(json.dumps(reg))
    s0, s1 = bad["sources"][0], bad["sources"][1]
    s0["channels"] = ["peru-server"]  # sin geobloqueo medido
    s1["id"] = s0["id"]
    s1["method"] = "crawler"
    bad["sources"].append({**bad["sources"][2], "id": "otra", "url": "ftp://x"})
    errs = "\n".join(registry.validate(bad))
    assert "si y solo si" in errs
    assert "id repetido" in errs
    assert "método" in errs
    assert "URL no válida" in errs


def test_registry_file_is_current():
    assert build_registry.main(["--check"]) == 0, "corre: cd python && python -m tools.build_registry"


def test_classify():
    assert classify(200, b"<rss/>") == "ok"
    assert classify(200, b"  ") == "empty"
    assert classify(403, b"Forbidden") == "http-403"
    assert classify(403, b"<script src='https://challenges.cloudflare.com/x'>") == "challenge"
    assert classify(200, b"<div class='cf-turnstile'></div>") == "challenge"
    assert classify(503, b"down") == "http-5xx"
    assert classify(404, b"") == "http-4xx"
    assert classify(None, b"", "ConnectTimeout: timed out") == "timeout"
    assert classify(None, b"", "ConnectError: [Errno -2] Name or service not known") == "dns"
    assert classify(None, b"", "ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED]") == "tls"
    assert classify(None, b"", "RemoteProtocolError: Server disconnected") == "connect"


def test_peru_index_is_read():
    index = {"schema": "enso-relay/1", "collected_at": "2026-10-21T05:00:00Z", "entries": [
        {"url": "https://www.senamhi.gob.pe/a", "status": 200, "bytes": 5000, "aliases": ["https://senamhi.gob.pe/a"]},
        {"url": "https://www.dhn.mil.pe/b", "status": 403, "bytes": 0},
        {"url": "https://x.gob.pe/c", "status": None, "bytes": 0, "error": "ReadTimeout: timed out"},
    ]}
    got = probe_sources.from_peru_index(index)
    assert got["https://www.senamhi.gob.pe/a"]["class"] == "ok"
    assert got["https://senamhi.gob.pe/a"]["vantage"] == "peru-server"
    assert got["https://www.dhn.mil.pe/b"]["class"] == "http-403"
    assert got["https://x.gob.pe/c"]["class"] == "timeout"
    assert got["https://www.senamhi.gob.pe/a"]["at"] == "2026-10-21T05:00:00Z"
