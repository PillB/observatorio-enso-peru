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


def test_robots_disallowed_sources_get_no_channel():
    u = "https://censis.example.pe/api/ultimo-sismo"
    gb = registry.geoblock(u, {u: {"us": {"class": "robots", "at": "2026-10-21T01:00:00+00:00", "vantage": "github-actions"}}})
    assert gb["status"] == "robots-disallowed"
    assert registry.channels_for(gb["status"]) == []
    reg = registry.build(reach={})
    i = next(n for n, x in enumerate(reg["sources"]) if x["kind"] != "feed")  # una fuente oficial
    url = reg["sources"][i]["url"]
    reg = registry.build(reach={url: {"us": {"class": "robots", "at": "x", "vantage": "github-actions"}}})
    assert reg["sources"][i]["channels"] == [] and registry.validate(reg) == []
    reg["sources"][i + 1]["channels"] = []
    assert any("canales" in e for e in registry.validate(reg))


def test_news_feeds_barred_by_robots_are_read_like_a_feed_reader():
    """Decisión del 21 de octubre de 2026: un feed de noticias que robots.txt no permite se lee solo desde
    Actions (como mucho una vez al día); una fuente oficial o página en esa situación sigue sin canales."""
    reg = registry.build(reach={})
    feed = next(x for x in reg["sources"] if x["kind"] == "feed" and x["id"].startswith("news-gnews"))
    reg = registry.build(reach={feed["url"]: {"us": {"class": "robots", "at": "x", "vantage": "github-actions"}}})
    got = next(x for x in reg["sources"] if x["id"] == feed["id"])
    assert got["by_url"][feed["url"]] == {"status": "robots-disallowed", "channels": ["actions"], "reader": True}
    assert got["channels"] == ["actions"] and registry.validate(reg) == []
    assert registry.reader_urls(reg) == {feed["url"]}
    assert registry.url_channels(reg)[feed["url"]] == ["actions"]
    got["by_url"][feed["url"]]["channels"] = ["actions", "n8n"]  # n8n no: correría varias veces al día
    assert any("reader" in e for e in registry.validate(reg))
    other = next(x for x in reg["sources"] if x["kind"] != "feed")
    other["by_url"][other["url"]]["reader"] = True
    assert any(other["id"] in e and "reader" in e for e in registry.validate(reg))


def test_robots_parser():
    import httpx

    from enso.reach import Robots

    bodies = {"a.pe": (200, "User-agent: *\nDisallow: /api/\n"), "b.pe": (404, ""), "c.pe": (403, ""),
              "d.pe": (200, "<html><div class='cf-turnstile'></div></html>"),
              "e.pe": (200, "<!DOCTYPE html><html><body>Página no encontrada</body></html>"), "f.pe": (503, "")}

    def handler(req):
        code, text = bodies[req.url.host]
        return httpx.Response(code, text=text)

    r = Robots(httpx.Client(transport=httpx.MockTransport(handler)))
    assert r.allowed("https://a.pe/api/x") is False
    assert r.allowed("https://a.pe/productos") is True
    assert r.allowed("https://b.pe/anything") is True
    assert r.allowed("https://c.pe/anything") is True  # 4xx: se permite (RFC 9309)
    assert r.allowed("https://d.pe/anything") is None  # una verificación en lugar de robots.txt
    assert r.failure("https://d.pe/x") == "challenge"
    # Una página HTML en lugar de robots.txt (un «no encontrado» con 200, o la portada a la que
    # redirige, como portal.indeci.gob.pe) no tiene reglas: se permite todo (RFC 9309 §2.3.1.1).
    assert r.allowed("https://e.pe/emergencias/feed/") is True and r.failure("https://e.pe/x") == ""
    assert r.allowed("https://f.pe/anything") is None and r.failure("https://f.pe/x") == "http-5xx"


def test_data_files_are_expected_as_text():
    """Los archivos de datos de CPC (``sstoi.indices``, ``soi``…) no son páginas HTML."""
    reg = registry.build()
    data = [s for s in reg["sources"] if "/data/indices/" in s["url"]]
    assert data and all(s["expect"] == "text" for s in data), [(s["id"], s["expect"]) for s in data if s["expect"] != "text"]


def test_reachability_is_kept_per_network():
    """«No responde a GitHub» no es «geobloqueado»: si n8n la alcanza, la recolecta n8n."""
    u = "https://enfen.imarpe.gob.pe/wp-json/wp/v2/posts"
    dns = {"class": "dns", "at": "2026-10-21T02:37:00+00:00", "vantage": "github-actions"}
    ok_n8n = {"class": "ok", "at": "2026-10-21T02:30:00+00:00", "vantage": "n8n-gcp"}
    gb = registry.geoblock(u, {u: {"actions": {"github-actions": dns}, "n8n": {"n8n-gcp": ok_n8n}}})
    assert gb["status"] == "open" and gb["open_from"] == ["n8n"]
    assert registry.channels_for(gb["status"], gb["open_from"], ["actions", "n8n"]) == ["n8n"]
    # Una medición ruidosa en la misma red no tapa la que respondió.
    noisy = {"class": "timeout", "at": "2026-10-21T03:00:00+00:00", "vantage": "n8n-actions-azure"}
    ok_gh = {"class": "ok", "at": "2026-10-21T00:04:00+00:00", "vantage": "github-actions"}
    gb = registry.geoblock(u, {u: {"actions": {"github-actions": ok_gh, "n8n-actions-azure": noisy}}})
    assert gb["status"] == "open" and registry.channels_for(gb["status"], gb["open_from"], ["actions"]) == ["actions", "n8n"]
    # Sin respuesta desde ninguna red de EE. UU. y sí desde el Perú: geobloqueada.
    pe = {"class": "ok", "at": "2026-10-21T01:00:00+00:00", "vantage": "peru-server"}
    gb = registry.geoblock(u, {u: {"actions": {"github-actions": dns}, "n8n": {"n8n-gcp": {**ok_n8n, "class": "timeout"}},
                                   "peru": {"peru-server": pe}}})
    assert gb["status"] == "geoblocked" and registry.channels_for(gb["status"]) == ["peru-server"]
    assert registry.vantage_group("n8n-actions-azure") == "actions" and registry.vantage_group("n8n-aws") == "n8n"


def test_probe_imports_measurements_from_other_networks(tmp_path):
    out = tmp_path / "reach.json"
    out.write_text(json.dumps({"schema": "enso-reachability/1", "urls": {
        "https://a.pe/x": {"us": {"class": "ok", "at": "2026-10-20T00:00:00+00:00", "vantage": "github-actions"}}}}))
    n8n = tmp_path / "n8n.json"
    n8n.write_text(json.dumps({"schema": "enso-reachability-vantage/1", "vantage": "n8n-aws", "results": [
        {"url": "https://a.pe/x", "class": "timeout", "at": "2026-10-21T00:00:00+00:00", "vantage": "n8n-aws"},
        {"url": "https://b.pe/y", "class": "bogus"}]}))
    assert probe_sources.main(["--no-probe", "--import", str(n8n), "--out", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["schema"] == "enso-reachability/2"
    assert set(data["urls"]["https://a.pe/x"]) == {"actions", "n8n"} and "https://b.pe/y" not in data["urls"]
    gb = registry.geoblock("https://a.pe/x", registry.load_reachability(out))
    assert gb["status"] == "open" and gb["open_from"] == ["actions"]


def test_alternate_urls_carry_their_own_format():
    """El listado de ENFEN y la réplica de la DHN son páginas HTML aunque la URL principal sea la API JSON."""
    enfen = next(s for s in registry.build()["sources"] if s["id"] == "enfen-comunicados")
    assert enfen["expect"] == "json" and enfen["alt_expect"] == ["html"] * len(enfen["alt_urls"])


def test_robots_longest_rule_wins():
    """RFC 9309: «Allow: /» y luego «Disallow: /api/» (IGP) prohíbe /api/; urllib.robotparser lo permitía."""
    from enso.reach import RobotRules

    igp = RobotRules("User-Agent: *\nAllow: /\nDisallow: /api/\nCrawl-delay: 1\n\nUser-agent: Googlebot\nAllow: /\n",
                     "Observatorio-ENSO-Peru")
    assert igp.allowed("https://ultimosismo.igp.gob.pe/") and not igp.allowed("https://ultimosismo.igp.gob.pe/api/ultimo-sismo")
    assert igp.crawl_delay == 1.0
    emsc = RobotRules("User-agent: *\nDisallow: /fdsnws/event/1/query*\n")
    assert not emsc.allowed("https://www.seismicportal.eu/fdsnws/event/1/query?format=json")
    own = RobotRules("User-agent: *\nDisallow: /\n\nUser-agent: observatorio-enso-peru\nDisallow: /privado\n",
                     "Observatorio-ENSO-Peru")
    assert own.allowed("https://a.pe/feed") and not own.allowed("https://a.pe/privado/x")  # su propio grupo manda
    anchored = RobotRules("User-agent: *\nDisallow: /\nAllow: /feed$\n")
    assert anchored.allowed("https://a.pe/feed") and not anchored.allowed("https://a.pe/feed/2")


def test_peru_collector_urls_keep_their_type_in_the_registry():
    """Los JSON y XML que solo responden desde el Perú (IDESEP, CENEPRED) no se esperan como HTML:
    n8n y el recolector rechazarían la respuesta buena."""
    from tools import peru_collector

    sources = registry.build(reach={})["sources"]
    by_url = {s["url"]: s for s in sources}
    known = set(by_url) | {u for s in sources for u in s.get("alt_urls", [])}
    assert {u for urls in peru_collector.SOURCES.values() for u in urls} <= known
    assert {u: by_url[u]["expect"] for u in peru_collector.EXPECT} == peru_collector.EXPECT
