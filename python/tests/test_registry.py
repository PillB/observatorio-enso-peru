"""Registro único de fuentes: reglas de canales, validación y archivo al día."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from enso import registry
from enso.reach import classify
from tools import build_registry, probe_sources

SIOFEN = (Path(__file__).parent / "fixtures" / "sources" / "siofen-icen.html").read_bytes()

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
    # Sin medición: Actions y n8n (salvo una fuente que no va por n8n; GODAS solo se lee desde Actions).
    assert all(s["channels"] == (["actions"] if s.get("n8n") is False else ["actions", "n8n"])
               for s in reg["sources"][1:] if s["url"] != url and s["id"] != "cpc-godas-d20")
    assert registry.validate(reg) == []


def test_godas_is_read_only_from_actions():
    """GODAS tiene lector propio (rangos de bytes de GRIB): n8n no lo copia, y un geobloqueo no lo deja sin canal."""
    from enso import observatory

    u = observatory.SOURCE_BY_ID["cpc-godas-d20"].urls[0]
    for reach in ({}, {u: {"us": US_403, "peru": PE_OK}}):
        g = next(s for s in registry.build(reach=reach)["sources"] if s["id"] == "cpc-godas-d20")
        assert g["channels"] == ["actions"] and g["by_url"][u]["channels"] == ["actions"]


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
    assert classify(403, b"<script src='/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1'>") == "challenge"
    assert classify(200, b"<html><div class='cf-turnstile'></div></html>") == "challenge"
    # Como en n8n, con un 2xx solo cuenta una página HTML (un fragmento sin <html> es XML).
    assert classify(200, b"<div class='cf-turnstile'></div>") == "ok"
    assert classify(503, b"down") == "http-5xx"
    assert classify(404, b"") == "http-4xx"
    assert classify(None, b"", "ConnectTimeout: timed out") == "timeout"
    assert classify(None, b"", "ConnectError: [Errno -2] Name or service not known") == "dns"
    assert classify(None, b"", "ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED]") == "tls"
    assert classify(None, b"", "RemoteProtocolError: Server disconnected") == "connect"


def test_classify_reads_headers_and_the_n8n_markers():
    """Como n8n/lib/classify.js (revisión del 22 de octubre de 2026, gap 42)."""
    assert classify(403, b"", headers={"CF-Mitigated": "challenge"}) == "challenge"
    assert classify(403, b"", headers=httpx.Headers({"cf-mitigated": "challenge"})) == "challenge"
    assert classify(200, b"<html><script src='/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1'></script></html>") \
        == "challenge"
    assert classify(200, b"<html><h1>Verify you are human</h1></html>") == "challenge"
    # Con un 2xx, las marcas cuentan en una página HTML de menos de 40 KB (un formulario con reCAPTCHA no es una
    # verificación); con 403, 5xx u otro código de error, siempre. 429, 401, 407, 404 y 410 se deciden por el código,
    # como en n8n.
    big = b"<html><form><div class='g-recaptcha'></div></form>" + b"x" * 46000
    assert classify(200, big) == "ok" and classify(403, big) == "challenge" and classify(503, big) == "challenge"
    assert classify(500, big) == "challenge" and classify(451, big) == "challenge"
    assert [classify(c, big, headers={"cf-mitigated": "challenge"}) for c in (429, 401, 407, 404, 410)] == ["http-4xx"] * 5
    assert classify(200, b"<html><div class='h-captcha'></div></html>") == "challenge"
    assert classify(200, b"<html><script src='https://js.hcaptcha.com/1/api.js'></script></html>") == "challenge"
    # Las marcas de n8n que faltaban: Imperva, Akamai, AWS WAF, DataDome, el consentimiento de Google, el bloqueo
    # por país.
    for page in (b"Request unsuccessful. Incapsula incident ID: 1", b"Reference&#32;&#35;18.1", b"aws-waf-token",
                 b"captcha-delivery.com", b"Before you continue to Google", "no está disponible en tu país".encode()):
        assert classify(200, b"<html><body>" + page + b"</body></html>") == "challenge", page
    assert classify(405, b"", headers={"x-amzn-waf-action": "captcha"}) == "challenge"
    assert classify(301, b"") == "http-4xx"  # una redirección que no se siguió, como en n8n
    # El script de detección de Cloudflare va en páginas normales: no es una verificación.
    for jsd in (b"/cdn-cgi/challenge-platform/scripts/jsd/main.js", b"/cdn-cgi/challenge-platform/h/b/scripts/jsd/1a2b/main.js"):
        assert classify(200, b"<html><body>Noticias<script>a.src='" + jsd + b"'</script></body></html>") == "ok"


def test_judge_counts_the_expected_type():
    from enso.reach import judge

    page = b"<!DOCTYPE html><html><body>" + b"x" * 2000 + b"</body></html>"
    assert judge(200, page, "text/html", "pdf") == ("empty", "html", "se esperaba un PDF y llegó html")
    assert judge(200, page, "text/html", "html")[0] == "ok"
    assert judge(200, b"%PDF-1.7 hcaptcha", "application/pdf", "pdf")[0] == "ok"  # un PDF no es una verificación
    assert judge(200, b"<rss><channel><title>t</title></channel></rss>", "", "rss") == ("empty", "rss", "feed sin entradas")
    assert judge(200, b"{\"a\": ", "application/json", "json")[2] == "JSON inválido"
    assert judge(202, b"", "", "json")[0] == "challenge"
    assert judge(None, b"", "", "pdf", "ConnectTimeout: timed out")[0] == "timeout"


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
    assert got["by_url"][feed["url"]] == {"status": "robots-disallowed", "channels": ["actions"], "robots": "disallowed",
                                          "reader": True}
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
    assert [r.source(f"https://{h}/x") for h in ("a.pe", "b.pe", "c.pe", "d.pe", "f.pe")] == [
        "rules", "absent", "absent", "unreachable", "unreachable"]


def test_robots_challenge_or_429_is_unreachable_not_allow_all():
    """Revisión del 22 de octubre de 2026 (gap 8): una verificación de Cloudflare con 403, o un 429, en lugar de
    robots.txt no es «no hay robots.txt»: no se sabe, y no se pide nada al servidor."""
    from enso.reach import Robots

    asked = []
    bodies = {"cf.pe": (403, {"cf-mitigated": "challenge", "content-type": "text/html"}, SIOFEN),
              "page.pe": (403, {"content-type": "text/html"}, SIOFEN), "rate.pe": (429, {}, b""),
              "plain.pe": (403, {}, b"Forbidden"),
              # Un robots.txt que nombra un complemento de CAPTCHA es un archivo de reglas, no una verificación.
              "wp.pe": (200, {"content-type": "text/plain"}, b"User-agent: *\nDisallow: /wp-content/plugins/hcaptcha/\n"),
              # Un 404 de un servidor con el script de detección de Cloudflare: no hay robots.txt.
              "jsd.pe": (404, {"content-type": "text/html"},
                         b"<html><body>404<script src='/cdn-cgi/challenge-platform/scripts/jsd/main.js'></script></body></html>"),
              # Ni lo hay con un 404 o un 410 cuya página de error trae un formulario con reCAPTCHA o Turnstile.
              "wp404.pe": (404, {"content-type": "text/html"},
                           b"<html><body><h1>No encontrado</h1><form><div class='g-recaptcha'></div></form>" + b"x" * 18000
                           + b"</body></html>"),
              "gone.pe": (410, {"content-type": "text/html"}, b"<html><body><div class='cf-turnstile'></div></body></html>"),
              # Una verificación con 401 o 407 sí es una verificación; sin marcas, un 401 es «no hay robots.txt».
              "auth.pe": (401, {"content-type": "text/html"}, b"<html><body>Checking your browser</body></html>"),
              "auth2.pe": (401, {}, b"Unauthorized"),
              # Un robots.txt servido como text/html que nombra una marca es un archivo de reglas.
              "html.pe": (200, {"content-type": "text/html; charset=UTF-8"},
                          b"User-agent: *\nDisallow: /cdn-cgi/challenge-platform/\n")}

    def handler(req):
        asked.append((req.url.host, req.extensions.get("timeout")))
        code, headers, body = bodies[req.url.host]
        return httpx.Response(code, headers=headers, content=body)

    r = Robots(httpx.Client(transport=httpx.MockTransport(handler)), timeout=15.0)
    for host in ("cf.pe", "page.pe"):
        assert r.allowed(f"https://{host}/x") is None and r.failure(f"https://{host}/x") == "challenge", host
        assert r.source(f"https://{host}/x") == "unreachable"
    assert r.allowed("https://rate.pe/x") is None and r.source("https://rate.pe/x") == "unreachable"
    assert r.allowed("https://plain.pe/x") is True and r.source("https://plain.pe/x") == "absent"
    assert r.allowed("https://wp.pe/feed/") is True and r.allowed("https://wp.pe/wp-content/plugins/hcaptcha/a.js") is False
    assert r.allowed("https://jsd.pe/x") is True and r.source("https://jsd.pe/x") == "absent"
    for host in ("wp404.pe", "gone.pe", "auth2.pe"):
        assert r.allowed(f"https://{host}/x") is True and r.source(f"https://{host}/x") == "absent", host
    assert r.allowed("https://auth.pe/x") is None and r.failure("https://auth.pe/x") == "challenge"
    assert r.allowed("https://html.pe/feed/") is True and r.allowed("https://html.pe/cdn-cgi/challenge-platform/a") is False
    assert r.source("https://html.pe/x") == "rules"
    # Un pedido por servidor, con el plazo corto de robots.txt.
    assert len(asked) == len(bodies) and all(t["read"] == 15.0 for _, t in asked)


def test_robots_txt_has_a_short_timeout_by_default():
    """Revisión: el plazo corto de robots.txt valía solo para quien lo pedía; el recolector del Perú esperaba los 40 s
    de su cliente por cada robots.txt colgado. Un cliente que no es de httpx (el de plazo corto de scrape_ladder)
    usa el suyo."""
    from enso.reach import ROBOTS_TIMEOUT_S, Robots

    asked = []

    def handler(req):
        asked.append(req.extensions.get("timeout"))
        return httpx.Response(200, text="User-agent: *\nAllow: /\n")

    client = httpx.Client(timeout=40.0, transport=httpx.MockTransport(handler))
    assert Robots(client).allowed("https://a.pe/x") is True and asked[-1]["read"] == ROBOTS_TIMEOUT_S
    assert Robots(client, timeout=None).allowed("https://a.pe/x") is True and asked[-1]["read"] == 40.0

    class Short:
        def get(self, url, **kw):
            assert "timeout" not in kw
            return client.get(url, timeout=5.0, **kw)

    assert Robots(Short()).allowed("https://a.pe/x") is True and asked[-1]["read"] == 5.0


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


def test_probe_imports_the_n8n_validation_report_as_it_comes_out(tmp_path):
    """El informe del flujo de validación de n8n (JSON de n8n.yml o CSV bajado de n8n) entra tal cual con
    --import: antes solo se aceptaba enso-reachability-vantage/1, que nada producía."""
    out = tmp_path / "reach.json"
    rows = [{"resultado": "RESUMEN: 1/2", "id": "resumen", "url": "", "alcance": ""},
            {"resultado": "FALLA", "veredicto": "dns", "alcance": "dns", "bloqueo": "", "http": "", "bytes": 0,
             "id": "enfen", "url": "https://enfen.gob.pe/x", "nota": "ENOTFOUND", "medido": "2026-10-21T03:00:00.000Z"},
            {"resultado": "OK", "veredicto": "ok", "alcance": "ok", "bloqueo": "", "http": 200, "bytes": 512,
             "id": "dhn", "url": "https://www.dhn.mil.pe/y", "nota": "", "medido": "2026-10-21T03:00:01.000Z"},
            {"resultado": "FALLA", "veredicto": "timeout", "alcance": "timeout", "bloqueo": "", "http": "", "bytes": 0,
             "id": "igp", "url": "https://www.igp.gob.pe/z", "nota": "aborted", "medido": "2026-10-21T03:00:02.000Z"}]
    report = tmp_path / "validacion-actions.json"
    report.write_text(json.dumps(rows))
    assert probe_sources.main(["--no-probe", "--import", str(report), "--import-vantage", "n8n-actions-azure",
                               "--out", str(out)]) == 0
    got = json.loads(out.read_text())["urls"]
    assert got["https://enfen.gob.pe/x"]["actions"]["n8n-actions-azure"] == {
        "class": "dns", "at": "2026-10-21T03:00:00+00:00", "detail": "ENOTFOUND", "bytes": 0, "vantage": "n8n-actions-azure"}
    assert got["https://www.dhn.mil.pe/y"]["actions"]["n8n-actions-azure"]["http"] == 200
    # El corte «aborted» del nodo HTTP de n8n sigue sin contar como medición.
    assert registry.unmeasured(got["https://www.igp.gob.pe/z"]["actions"]["n8n-actions-azure"])

    csv_file = tmp_path / "validacion-fuentes-n8n.csv"
    keys = list(rows[1])
    csv_file.write_text(",".join(keys) + "\n" + "\n".join(",".join(str(r.get(k, "")) for k in keys) for r in rows) + "\n")
    out2 = tmp_path / "reach2.json"
    assert probe_sources.main(["--no-probe", "--import", str(csv_file), "--import-vantage", "n8n-aws",
                               "--out", str(out2)]) == 0
    got = json.loads(out2.read_text())["urls"]
    assert got["https://www.dhn.mil.pe/y"]["n8n"]["n8n-aws"]["http"] == 200
    assert got["https://enfen.gob.pe/x"]["n8n"]["n8n-aws"]["class"] == "dns"


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


def test_the_registry_says_who_reads_each_peru_only_page():
    """La tabla de avisos del SENAMHI no es una copia muerta: da el nivel a los avisos (enso.senamhi_avisos)."""
    import importlib

    from enso import senamhi_avisos
    from tools import peru_collector

    by_url = {s["url"]: s for s in registry.build(reach={})["sources"]}
    table = by_url[senamhi_avisos.URL]
    assert table["parser"] == "enso.senamhi_avisos:parse" and table["hazards"] == ["lluvias"]
    mod, fn = table["parser"].split(":")
    assert getattr(importlib.import_module(mod), fn) is senamhi_avisos.parse
    # Las demás páginas del recolector siguen sin intérprete, y lo dicen.
    others = [by_url[u] for urls in peru_collector.SOURCES.values() for u in urls
              if u in by_url and "se archiva desde el Perú" in by_url[u].get("notes", "") and u != senamhi_avisos.URL]
    assert others and all(not s.get("parser") and "sin intérprete" in s["notes"] for s in others)


def test_architecture_model_counts_the_peru_pages_the_registry_has():
    """El diagrama dice cuántas páginas guarda el Perú y cuántas baja también n8n: deben ser las del registro."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    model = json.loads((root / "docs" / "arquitectura.json").read_text(encoding="utf-8"))
    node = next(n for n in model["full"]["nodes"] if n["id"] == "peru-archive-pages")
    current = json.loads((root / "registry" / "sources.json").read_text(encoding="utf-8"))  # con lo medido
    pages = [s for s in current["sources"] if "se archiva desde el Perú" in s.get("notes", "")]
    n8n = [s for s in pages if "n8n" in (s.get("channels") or [])]
    assert int(re.search(r"(\d+) URL de la lista fija", node["details_es"])[1]) == len(pages)
    assert int(re.search(r"Las otras (\d+)", node["details_es"])[1]) == len(n8n)


# --- Revisión del 22 de octubre de 2026: robots.txt, red de Actions, rutas de los informes y mediciones viejas ----

def _rec(cls: str, vantage: str, at: str = "2026-10-21T04:00:00+00:00", **kw) -> dict:
    return {"class": cls, "at": at, "vantage": vantage, **kw}


def _official_urls(n: int) -> list[str]:
    return [s["url"] for s in registry.build(reach={})["sources"] if s["kind"] == "dataset"][:n]


def test_robots_verdict_per_url():
    """Gap 1: n8n pedía URL cuyo robots.txt nadie pudo leer. by_url dice qué se sabe de cada una."""
    a, b, c, d, e, f = _official_urls(6)
    reach = {
        a: {"actions": {"github-actions": _rec("http-5xx", "github-actions", robots="unreachable",  # el feed del INDECI
                                               detail="robots.txt sin respuesta")}},
        b: {"peru": {"peru-server": _rec("robots", "peru-server", robots="disallowed")},
            "actions": {"github-actions": _rec("ok", "github-actions", robots="allowed")}},
        c: {"actions": {"github-actions": _rec("ok", "github-actions", robots="allowed")}},
        d: {"actions": {"github-actions": _rec("http-403", "github-actions", robots="absent")}},
        # El recolector del Perú lee robots.txt antes de cada pedido: si la pidió, robots.txt lo permite.
        e: {"actions": {"github-actions": _rec("dns", "github-actions")}, "peru": {"peru-server": _rec("ok", "peru-server")}},
        # …pero no si la omitió porque robots.txt no respondió.
        f: {"peru": {"peru-server": _rec("timeout", "peru-server", detail="robots.txt sin respuesta (timeout): no se pide")},
            "n8n": {"n8n-aws": _rec("ok", "n8n-aws")}},
    }
    reg = registry.build(reach=reach)
    assert registry.validate(reg) == []
    got = registry.url_robots(reg)
    assert [got[u] for u in (a, b, c, d, e, f)] == ["unknown", "disallowed", "allowed", "allowed", "allowed", "unknown"]
    by = {u: r for s in reg["sources"] for u, r in s["by_url"].items()}
    assert by[b]["status"] == "robots-disallowed" and by[b]["channels"] == []
    assert by[a]["channels"] == ["actions", "n8n"]  # robots.txt sin leer no cambia los canales: n8n la salta
    # Un registro de antes de este dato no dice nada (el pipeline sigue como antes).
    for s in reg["sources"]:
        for r in s["by_url"].values():
            r.pop("robots")
    assert registry.url_robots(reg) == {}
    assert any("robots no válido" in x for x in registry.validate(reg))


def test_old_robots_record_is_dropped_like_in_geoblock():
    """Revisión: un «robots» de más de STALE_DAYS junto a una medición más reciente de su red dejaba la URL abierta
    con robots «disallowed», y validate() rechazaba el registro (fallaba la sonda semanal y el kit)."""
    url = "http://met.igp.gob.pe/datos/ICEN.txt"
    reach = {url: {"actions": {"github-actions": _rec("robots", "github-actions", "2026-08-01T04:00:00+00:00",
                                                      robots="disallowed"),
                               "n8n-actions-azure": _rec("ok", "n8n-actions-azure", "2026-10-20T04:00:00+00:00")}}}
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    reg = registry.build(reach=reach, now=now)
    assert registry.validate(reg) == []
    by = next(s for s in reg["sources"] if s["id"] == "igp-icen")["by_url"][url]
    assert by == {"status": "open", "channels": ["actions", "n8n"], "robots": "unknown"}
    assert registry.robots_verdict(url, reach, now) == "unknown" and registry.robots_verdict(url, reach) == "disallowed"
    # Reciente, cuenta: sin canales y «disallowed».
    reach[url]["actions"]["github-actions"]["at"] = "2026-10-19T04:00:00+00:00"
    reg = registry.build(reach=reach, now=now)
    by = next(s for s in reg["sources"] if s["id"] == "igp-icen")["by_url"][url]
    assert by == {"status": "robots-disallowed", "channels": [], "robots": "disallowed"} and registry.validate(reg) == []


def test_validate_requires_disallowed_robots_to_match_the_status():
    reg = registry.build(reach={})
    s = next(x for x in reg["sources"] if x["kind"] == "dataset")
    s["by_url"][s["url"]]["robots"] = "disallowed"  # sin robots-disallowed
    assert any("robots no válido" in e for e in registry.validate(reg))
    s["by_url"][s["url"]]["robots"] = "quizás"
    assert any("robots no válido" in e for e in registry.validate(reg))


def test_actions_network_counts_the_pipeline_measurement():
    """Gap 3: el ok de otro día de n8n en un ejecutor de Actions tapaba la verificación de hoy al pipeline."""
    u = "https://www.imarpe.gob.pe/"
    gh = _rec("challenge", "github-actions", "2026-10-21T04:48:14+00:00", http=403)
    azure = _rec("ok", "n8n-actions-azure", "2026-10-21T02:35:37+00:00")
    gb = registry.geoblock(u, {u: {"actions": {"github-actions": gh, "n8n-actions-azure": azure}}})
    assert "actions" not in gb["open_from"] and gb["actions"]["vantage"] == "github-actions"
    assert gb["status"] == "suspected-geoblock"
    # Con respuesta desde el Perú y sin n8n que responda: geobloqueada, la pide el Perú.
    gb = registry.geoblock(u, {u: {"actions": {"github-actions": gh, "n8n-actions-azure": azure},
                                   "n8n": {"n8n-aws": _rec("timeout", "n8n-aws")},
                                   "peru": {"peru-server": _rec("ok", "peru-server")}}})
    assert gb["status"] == "geoblocked" and registry.channels_for(gb["status"]) == ["peru-server"]
    # Sin medición del pipeline cuenta la de n8n en Actions.
    gb = registry.geoblock(u, {u: {"actions": {"n8n-actions-azure": azure}}})
    assert gb["open_from"] == ["actions"]


def test_old_measurements_do_not_stick():
    """Una medición de más de STALE_DAYS no cuenta si su red tiene otra más reciente."""
    u = "https://a.gob.pe/datos.txt"
    now = datetime(2026, 10, 21, 5, tzinfo=timezone.utc)
    old = (now - timedelta(days=registry.STALE_DAYS + 5)).isoformat()
    reach = {u: {"actions": {"github-actions": _rec("ok", "github-actions", now.isoformat())},
                 "n8n": {"n8n-gcp": _rec("ok", "n8n-gcp", old), "n8n-aws": _rec("timeout", "n8n-aws", now.isoformat())}}}
    gb = registry.geoblock(u, reach, now)
    assert gb["n8n"]["vantage"] == "n8n-aws" and "n8n-gcp" not in gb["from"]
    assert registry.channels_for(gb["status"], gb["open_from"], ["actions", "n8n"]) == ["actions"]
    assert registry.geoblock(u, reach)["open_from"] == ["actions", "n8n"]  # sin fecha de referencia cuenta todo
    # La única medición de una red cuenta aunque sea vieja.
    alone = {u: {"n8n": {"n8n-gcp": _rec("ok", "n8n-gcp", old)}}}
    assert registry.geoblock(u, alone, now)["open_from"] == ["n8n"]
    # build cuenta los días desde la medición más reciente, no desde el reloj: el registro no cambia solo.
    url = _official_urls(1)[0]
    reach = {url: reach[u]}
    s = next(x for x in registry.build(reach=reach)["sources"] if x["url"] == url)
    assert s["by_url"][url]["channels"] == ["actions"]
    later = registry.build(reach=reach, now=now + timedelta(days=400))
    assert next(x for x in later["sources"] if x["url"] == url)["geoblock"]["status"] == "open"


def test_reports_and_imarpe_repository_are_in_the_registry():
    """Gap 6: el informe técnico, su réplica en la DHN y las búsquedas del repositorio del IMARPE no estaban
    en el registro: nadie medía su alcance ni leía su robots.txt."""
    from enso import reports
    from enso.feeds import imarpe_repo as repo

    comunicados, informes = repo.listing_urls()
    reg = registry.build(reach={})
    plan = registry.url_channels(reg)
    assert {reports.INFORMES_PAGE, reports.DHN_INFORMES_PAGE, comunicados, informes} <= set(plan)
    src = {s["id"]: s for s in reg["sources"]}
    rep = src["imarpe-repositorio-enfen"]
    assert (rep["url"], rep["alt_urls"], rep["method"], rep["expect"], rep["n8n"]) == (
        comunicados, [informes], "api", "json", False)
    assert "NODE_EXTRA_CA_CERTS" in rep["notes"]
    assert src["enfen-informes"]["alt_expect"] == ["html"] and src["enfen-informes"]["expect"] == "html"
    # Lo que pide imarpe_repo es exactamente lo registrado (el pipeline busca el plan por URL exacta).
    asked = []

    class F:
        def get(self, urls, **kw):
            from enso.fetch import FetchError

            asked.extend(urls)
            raise FetchError("x", [])

    repo.communiques(F())
    repo.informes(F())
    assert asked == [comunicados, informes]
    # n8n no verifica su certificado: con Actions bien y n8n «tls», solo Actions; nunca n8n.
    tls = {"actions": {"github-actions": _rec("ok", "github-actions", robots="allowed")},
           "n8n": {"n8n-aws": _rec("tls", "n8n-aws")}}
    reg = registry.build(reach={comunicados: tls, informes: tls})
    rep = next(s for s in reg["sources"] if s["id"] == "imarpe-repositorio-enfen")
    assert rep["channels"] == ["actions"] and registry.validate(reg) == []
    # Si deja de responder a Actions y responde desde el Perú, la pide el Perú (y solo el Perú).
    moved = {"actions": {"github-actions": _rec("challenge", "github-actions", http=403)},
             "peru": {"peru-server": _rec("ok", "peru-server")}}
    reg = registry.build(reach={comunicados: moved})
    rep = next(s for s in reg["sources"] if s["id"] == "imarpe-repositorio-enfen")
    assert rep["by_url"][comunicados]["channels"] == ["peru-server"] and rep["geoblocked"] is True
    rep["by_url"][informes]["channels"] = ["actions", "n8n"]
    rep["channels"] = ["actions", "n8n", "peru-server"]
    assert any("no va por n8n" in e for e in registry.validate(reg))


def test_a_source_that_n8n_cannot_verify_never_goes_to_n8n():
    for status, open_from, measured in (("open", ["n8n"], ["actions", "n8n"]), ("open", None, None), ("unknown", None, None),
                                        ("down", None, None), ("open", ["actions", "n8n"], ["actions", "n8n"])):
        assert registry.channels_for(status, open_from, measured, n8n=False) == ["actions"], status
    assert registry.channels_for("suspected-geoblock", n8n=False) == ["peru-server"]
    assert registry.channels_for("robots-disallowed", n8n=False) == []


def test_icen_is_read_only_over_http():
    """Gap 41: el ICEN por https no responde desde ninguna red (no está geobloqueado): la fuente ya no lo pide."""
    icen = "http://met.igp.gob.pe/datos/ICEN.txt"
    ok = {"actions": {"github-actions": _rec("ok", "github-actions", robots="allowed")}}
    s = next(x for x in registry.build(reach={icen: ok})["sources"] if x["id"] == "igp-icen")
    assert s["url"] == icen and s["alt_urls"] == [] and s["geoblocked"] is False and s["channels"] == ["actions", "n8n"]


def test_registry_does_not_change_when_only_measurement_times_change():
    """Gap 44: cada sonda semanal cambiaba la hora, el tiempo y el tamaño de cada medición en sources.json y en los
    flujos de n8n que lo incluyen, aunque nada cambiara; eso queda en reachability.json."""
    url = _official_urls(1)[0]

    def reach(at: str, ms: int, size: int) -> dict:
        return {url: {"actions": {"github-actions": _rec("ok", "github-actions", at, http=200, ms=ms, bytes=size,
                                                         robots="allowed", detail="")}}}

    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    one = registry.build(reach=reach("2026-10-14T09:20:00+00:00", 120, 5000), now=now)
    two = registry.build(reach=reach("2026-10-21T09:21:00+00:00", 340, 5100), now=now)
    assert one == two
    gb = next(s for s in one["sources"] if s["url"] == url)["geoblock"]
    assert gb["actions"] == {"class": "ok", "http": 200, "robots": "allowed"} and "measured_at" not in gb
    assert gb["from"] == ["github-actions"]


def test_probe_trusts_the_bundled_intermediates_and_reads_headers_robots_and_type(monkeypatch):
    """Gap 7 (la sonda sin el intermedio de Sectigo medía «tls» el repositorio del IMARPE), gap 8 (robots
    «allowed» fijo) y gap 42 (sin cabeceras ni tipo esperado)."""
    seen = {}

    def net(req):
        u = str(req.url)
        if req.url.host == "nada.pe" and req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if u.endswith("/cf"):
            return httpx.Response(403, headers={"cf-mitigated": "challenge"})
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<html><body>" + "x" * 900 + "</body></html>")

    real = httpx.Client

    def client(**kw):
        seen["verify"] = kw.get("verify")
        return real(**{**kw, "transport": httpx.MockTransport(net)})

    monkeypatch.setattr(probe_sources.httpx, "Client", client)
    monkeypatch.setattr(probe_sources.time, "sleep", lambda s: None)
    urls = ["https://a.pe/cf", "https://a.pe/doc.pdf", "https://nada.pe/pagina"]
    got = probe_sources.probe(urls, "github-actions", expect={"https://a.pe/doc.pdf": "pdf"})
    issuers = [dict(x[0] for x in c["subject"]).get("commonName") for c in seen["verify"].get_ca_certs()]
    assert "Sectigo Public Server Authentication CA DV R36" in issuers
    assert got["https://a.pe/cf"]["class"] == "challenge"
    assert got["https://a.pe/doc.pdf"]["class"] == "empty" and "se esperaba un PDF" in got["https://a.pe/doc.pdf"]["detail"]
    assert got["https://nada.pe/pagina"]["class"] == "ok"
    assert [got[u]["robots"] for u in urls] == ["allowed", "allowed", "absent"]
    # El registro toma «absent» (no hay robots.txt) como permitido.
    assert registry.robots_verdict("https://nada.pe/pagina", {"https://nada.pe/pagina": {"github-actions": got[urls[2]]}}) \
        == "allowed"


def test_probe_from_peru_judges_the_type_the_registry_expects(monkeypatch):
    """Revisión: la medición desde el Perú (``peru_collector.probe_registry`` llama a probe sin ``expect``) daba «ok»
    a un feed sin entradas o a una página de otro tipo que Actions y n8n miden «empty»: el registro la tomaba por
    geobloqueada."""
    reg = registry.build(reach={})
    feed = next(s for s in reg["sources"] if s["kind"] == "feed" and s["expect"] == "rss" and not s["alt_urls"])["url"]
    data = next(s for s in reg["sources"] if s["expect"] == "json" and s["kind"] == "dataset")["url"]

    def net(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if str(req.url) == feed:
            return httpx.Response(200, headers={"content-type": "application/rss+xml"},
                                  text="<?xml version='1.0'?><rss><channel><title>t</title></channel></rss>")
        return httpx.Response(200, headers={"content-type": "text/xml"},
                              text="<?xml version='1.0'?><ServiceExceptionReport>" + "x" * 900 + "</ServiceExceptionReport>")

    real = httpx.Client
    monkeypatch.setattr(probe_sources.httpx, "Client", lambda **kw: real(**{**kw, "transport": httpx.MockTransport(net)}))
    monkeypatch.setattr(probe_sources.time, "sleep", lambda s: None)
    got = probe_sources.probe([feed, data, "https://fuera.pe/x"], "peru-server", timeout=20.0)
    assert (got[feed]["class"], got[feed]["detail"]) == ("empty", "feed sin entradas")
    assert got[data]["class"] == "empty" and "se esperaba JSON" in got[data]["detail"]
    assert got["https://fuera.pe/x"]["class"] == "ok"  # fuera del registro: cualquier formato
    # Desde todas las redes «empty»: caída, no geobloqueada.
    empty = {"actions": {"github-actions": _rec("empty", "github-actions")}, "n8n": {"n8n-aws": _rec("empty", "n8n-aws")},
             "peru": {"peru-server": got[feed]}}
    assert registry.geoblock(feed, {feed: empty})["status"] == "down"
    # Un ``expect`` explícito (aunque vacío) manda.
    assert probe_sources.probe([feed], "peru-server", expect={})[feed]["class"] == "ok"


def test_peru_index_says_whether_robots_txt_was_read():
    index = {"schema": "enso-relay/1", "collected_at": "2026-10-21T05:00:00Z", "entries": [
        {"url": "https://www.senamhi.gob.pe/a", "status": 200, "bytes": 5000},
        {"url": "https://snirh.ana.gob.pe/", "status": None, "skipped": "robots-sin-respuesta", "class": "timeout",
         "error": "robots.txt sin respuesta (timeout): no se pide nada a este servidor"},
        {"url": "https://www.imarpe.gob.pe/x", "status": None, "skipped": "robots", "class": "robots",
         "error": "robots.txt no permite la ruta: no se pide"},
        {"url": "https://b.gob.pe/y", "status": 200, "carried": True, "fetched_at": "2026-10-20T05:00:00Z",
         "last_attempt": {"at": "2026-10-21T05:00:00Z", "class": "timeout",
                          "error": "robots.txt sin respuesta (timeout): no se pide nada a este servidor"}},
    ]}
    got = probe_sources.from_peru_index(index)
    assert [got[u]["robots"] for u in ("https://www.senamhi.gob.pe/a", "https://snirh.ana.gob.pe/",
                                       "https://www.imarpe.gob.pe/x", "https://b.gob.pe/y")] == [
        "allowed", "unreachable", "disallowed", "unreachable"]
    # Gap 41: el ICEN por https no responde desde el Perú (robots.txt sin respuesta) ni desde EE. UU.: caído, no
    # geobloqueado.
    u = "https://met.igp.gob.pe/datos/ICEN.txt"
    peru = probe_sources.from_peru_index({"collected_at": "2026-10-21T05:00:00Z", "entries": [
        {"url": u, "status": None, "skipped": "robots-sin-respuesta", "class": "timeout",
         "error": "robots.txt sin respuesta (timeout): no se pide nada a este servidor"}]})[u]
    reach = {u: {"actions": {"github-actions": _rec("timeout", "github-actions")},
                 "n8n": {"n8n-aws": _rec("timeout", "n8n-aws")}, "peru": {"peru-server": peru}}}
    assert registry.geoblock(u, reach)["status"] == "down" and registry.robots_verdict(u, reach) == "unknown"


def test_reachability_forgets_old_urls_outside_the_registry(tmp_path):
    """Gap 43: reachability.json no se podaba nunca (311 URL para un registro de 199)."""
    url = _official_urls(1)[0]
    now = datetime.now(timezone.utc)
    old, fresh = (now - timedelta(days=40)).isoformat(timespec="seconds"), (now - timedelta(days=1)).isoformat(timespec="seconds")
    out = tmp_path / "reach.json"
    out.write_text(json.dumps({"schema": registry.REACH_SCHEMA, "urls": {
        "https://www.dhn.mil.pe/Archivos/oceanografia/enfen/comunicado-oficial/17-2026.pdf": {
            "n8n": {"n8n-aws": _rec("challenge", "n8n-aws", old)}},
        "https://www.dhn.mil.pe/Archivos/oceanografia/enfen/comunicado-oficial/20-2026.pdf": {
            "n8n": {"n8n-aws": _rec("challenge", "n8n-aws", fresh)}},
        url: {"actions": {"github-actions": _rec("ok", "github-actions", old)}}}}))
    assert probe_sources.main(["--no-probe", "--out", str(out)]) == 0
    assert set(json.loads(out.read_text())["urls"]) == {
        "https://www.dhn.mil.pe/Archivos/oceanografia/enfen/comunicado-oficial/20-2026.pdf", url}
    # --only mide unas pocas fuentes, pero no olvida las demás del registro.
    other = _official_urls(2)[1]
    data = json.loads(out.read_text())
    data["urls"][other] = {"actions": {"github-actions": _rec("ok", "github-actions", old)}}
    out.write_text(json.dumps(data))
    assert probe_sources.main(["--no-probe", "--only", "ninguna", "--out", str(out)]) == 0
    assert other in json.loads(out.read_text())["urls"]
