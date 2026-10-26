"""Barrido de robots.txt del 26 de octubre de 2026: cada redirección se sigue a mano y su destino pasa por la
misma regla de robots.txt que la URL pedida, en la corrida diaria, las sondas, la captura de pruebas y las
herramientas que bajan datos. También el Internet Archive, cuyo robots.txt nadie leía."""

from __future__ import annotations

import httpx
import pytest

from enso.fetch import FetchError, Fetcher, archive_prefix
from enso.reach import RobotRules, Robots, get_checked

ALLOW_ALL = "User-agent: *\nAllow: /\n"


def _net(robots: dict[str, tuple[int, str]], routes: dict[str, httpx.Response], asked: list[str]):
    """Red simulada: robots.txt por servidor (404 si no se dice), las rutas dadas y 200 en lo demás."""
    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        asked.append(url)
        if req.url.path == "/robots.txt":
            code, text = robots.get(req.url.host, (404, ""))
            return httpx.Response(code, text=text)
        if url in routes:
            return routes[url]
        if req.url.host == "web.archive.org":
            return httpx.Response(200, json=[["urlkey", "timestamp", "original"]] if "/cdx/" in url else {})
        return httpx.Response(200, text="<html>" + "x" * 600 + "</html>", headers={"content-type": "text/html"})
    return httpx.MockTransport(handler)


def _fetcher(transport, **kw) -> Fetcher:
    f = Fetcher(retries=1, polite_delay=0, allow_archive=False, robots=True, **kw)
    f.client = httpx.Client(transport=transport, follow_redirects=False)
    f.robots.client = f.client
    return f


def _to(url: str) -> httpx.Response:
    return httpx.Response(302, headers={"location": url})


def test_paths_compare_with_percent_encoding_normalized():
    """RFC 9309 §2.2.2: los PDF del COEN van con tildes en el nombre; con y sin ``%XX``, la misma ruta."""
    r = RobotRules("User-agent: *\nDisallow: /wp-content/uploads/Señal\nDisallow: /a%7eb\n")
    for path in ("/wp-content/uploads/Señal.pdf", "/wp-content/uploads/Se%C3%B1al.pdf",
                 "/wp-content/uploads/Se%c3%b1al.pdf", "/a~b", "/a%7Eb"):
        assert r.allowed("https://x.example" + path) is False, path
    assert RobotRules("User-agent: *\nDisallow: /x%2Fy\n").allowed("https://x.example/x/y")  # %2F es reservado


def test_the_daily_fetcher_checks_each_redirect_target():
    page = "https://a.example/datos/"
    for robots, target, followed in (
            ({"a.example": (200, "User-agent: *\nDisallow: /privado/\n")}, "https://a.example/privado/x", False),
            ({"b.example": (200, "User-agent: *\nDisallow: /\n")}, "https://b.example/x", False),
            ({"b.example": (503, "")}, "https://b.example/x", False),  # robots.txt sin respuesta: no se pide
            ({"b.example": (200, ALLOW_ALL)}, "https://b.example/x", True)):
        asked: list[str] = []
        f = _fetcher(_net(robots, {page: _to(target)}, asked))
        if followed:
            assert f.get([page]).url == target and asked[-1] == target  # la URL efectiva, como antes
        else:
            with pytest.raises(Exception):
                f.get([page])
            assert target not in asked, target
            assert f._down.get("a.example", 0) == 0  # una redirección que no se siguió no es un fallo del servidor


def test_a_redirect_into_a_registry_url_uses_the_probe_reading():
    """Como un pedido directo: si el destino es una URL del registro asignada a Actions, vale la lectura de la sonda
    aunque su robots.txt no responda en la corrida."""
    page, target = "http://c.example/feed", "https://c.example/feed"
    asked: list[str] = []
    f = _fetcher(_net({"c.example": (503, "")}, {page: _to(target)}, asked),
                 plan={page: ["actions"], target: ["actions"]}, robots_known={page: "allowed", target: "allowed"})
    assert f.get([page]) is not None and asked[-1] == target


def test_without_robots_the_fetcher_still_follows_redirects():
    page, target = "https://a.example/x", "https://b.example/y"
    asked: list[str] = []
    f = Fetcher(retries=1, polite_delay=0, allow_archive=False)
    f.client = httpx.Client(transport=_net({}, {page: _to(target)}, asked), follow_redirects=False)
    assert f.get([page]) is not None and asked == [page, target]


def test_the_internet_archive_follows_its_robots_txt():
    page = "https://a.example/caido"
    down = httpx.Response(503)
    for rule, wants_cdx in (("User-agent: *\nDisallow: /cdx/\n", False), (ALLOW_ALL, True)):
        asked: list[str] = []
        f = _fetcher(_net({"web.archive.org": (200, rule)}, {page: down}, asked))
        f.allow_archive = True
        with pytest.raises(Exception):
            f.get([page])
        assert any("/cdx/" in u for u in asked) is wants_cdx, rule
        asked.clear()
        assert archive_prefix(f, "https://a.example/download/") is None
        assert any("/cdx/" in u for u in asked) is wants_cdx, rule
    # Sin respuesta del robots.txt del archivo (no está en el registro): no se le pide nada en la corrida.
    asked = []
    f = _fetcher(_net({"web.archive.org": (503, "")}, {page: down}, asked))
    f.allow_archive = True
    with pytest.raises(Exception):
        f.get([page])
    assert [u for u in asked if "web.archive.org" in u and not u.endswith("/robots.txt")] == []


def test_godas_range_requests_check_redirects_too():
    grib = "https://ftp.cpc.ncep.noaa.gov/godas/monthly/godas.M.202609.grb"
    elsewhere = "https://mirror.example/private/godas.M.202609.grb"
    asked: list[str] = []
    f = _fetcher(_net({"mirror.example": (200, "User-agent: *\nDisallow: /private/\n")}, {grib: _to(elsewhere)}, asked))
    with pytest.raises(httpx.HTTPError, match="redirige a"):
        f._request(grib, headers={"Range": "bytes=0-9"})
    assert elsewhere not in asked


def test_get_checked_reports_the_refused_hop():
    asked: list[str] = []
    client = httpx.Client(transport=_net({"b.example": (200, "User-agent: *\nDisallow: /\n")},
                                         {"https://a.example/x": _to("https://b.example/y")}, asked))
    r, hop, verdict = get_checked(client, "https://a.example/x", Robots(client))
    assert (r.status_code, hop, verdict) == (302, "https://b.example/y", False) and "https://b.example/y" not in asked


@pytest.mark.parametrize("location", ["https:a.example/y", "https://xn--zz.example/y", "https://xn--ls8h.la/",
                                      "//xn--zz/y"])
def test_a_location_httpx_cannot_build_is_a_server_error(monkeypatch, location):
    """``Location: https:servidor/ruta`` (protocolo sin ``//`` y ruta sin ``/``) o un servidor «xn--…» que idna no
    decodifica: httpx falla con ``InvalidURL`` o ``idna.IDNAError``, que no son un ``HTTPError``, al armar el pedido
    siguiente aunque no siga redirecciones. Era un error de quien pide y cortaba la corrida entera del recolector del
    Perú, de la sonda y de la actualización diaria; ahora es un error del servidor."""
    from tools import peru_collector as pc
    from tools import probe_sources

    bad, good = "https://a.example/x", "https://a.example/ok.xml"
    asked: list[str] = []
    rss = httpx.Response(200, text="<rss><channel><item><title>t</title></item></channel></rss>",
                         headers={"content-type": "application/rss+xml"})
    transport = _net({"a.example": (200, ALLOW_ALL)}, {bad: _to(location), good: rss}, asked)
    client = httpx.Client(transport=transport)
    with pytest.raises(httpx.RemoteProtocolError, match="Location no válido"):
        get_checked(client, bad, Robots(client))
    monkeypatch.setattr(pc.time, "sleep", lambda s: None)
    got = pc.fetch(pc.Session(client), bad, "rss")
    assert got["class"] == "connect" and "Location no válido" in got["error"]
    with pytest.raises(FetchError) as err:  # la actualización diaria: un intento fallido más, no la corrida cortada
        _fetcher(transport).get([bad])
    assert [a["url"] for a in err.value.attempts if a.get("error")] == [bad]
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(**{**kw, "transport": transport}))
    recs = probe_sources.probe([bad, good], "github-actions", expect={bad: "rss", good: "rss"})
    assert recs[bad]["class"] == "connect" and recs[good]["class"] == "ok"


def test_the_weekly_probe_does_not_store_allowed_for_a_url_behind_a_refused_hop(monkeypatch):
    from tools import probe_sources

    page, target = "https://a.example/datos.json", "https://a.example/intranet/datos.json"
    asked: list[str] = []
    transport = _net({"a.example": (200, "User-agent: *\nDisallow: /intranet/\n")}, {page: _to(target)}, asked)
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(**{**kw, "transport": transport}))
    rec = probe_sources.probe([page], "github-actions", expect={page: "json"})[page]
    assert rec["class"] == "robots" and rec["robots"] == "disallowed" and target in rec["detail"]
    assert target not in asked


def test_feed_probe_and_fixture_capture_check_redirects(monkeypatch, tmp_path):
    from tools import capture_sources, probe_feeds

    page, target = "https://a.example/feed/", "https://b.example/privado/feed.xml"
    asked: list[str] = []
    transport = _net({"b.example": (200, "User-agent: *\nDisallow: /privado/\n")}, {page: _to(target)}, asked)
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(**{**kw, "transport": transport}))
    status, body, _, final, note = probe_feeds.Probe().get(page)
    assert status is None and final == target and "robots.txt" in note and target not in asked
    client = real(transport=transport, follow_redirects=True)
    res = capture_sources._get(client, page, Robots(client))
    assert res["redirect_blocked"] == target and res["robots"] == "disallowed" and target not in asked


def test_fixture_history_follows_the_archive_robots_txt(tmp_path, monkeypatch):
    from tools import capture_sources

    asked: list[str] = []
    transport = _net({"web.archive.org": (200, "User-agent: *\nDisallow: /\n")}, {}, asked)
    client = httpx.Client(transport=transport, follow_redirects=True)
    monkeypatch.setattr(capture_sources, "HISTORY", [("x", "https://a.example/", "month")])
    index: list = []
    capture_sources.capture_history(client, tmp_path, index, 4)
    assert asked == ["https://web.archive.org/robots.txt"]


def test_data_builders_stop_on_robots_txt(monkeypatch):
    from tools import build_ubigeo, godas_d20_climatology as clim

    asked: list[str] = []
    client = httpx.Client(transport=_net({"raw.githubusercontent.com": (200, "User-agent: *\nDisallow: /\n")}, {}, asked))
    with pytest.raises(SystemExit, match="--src"):
        build_ubigeo._download(client)
    assert asked == ["https://raw.githubusercontent.com/robots.txt"]
    asked.clear()
    client = httpx.Client(transport=_net({"raw.githubusercontent.com": (404, "")}, {}, asked))
    assert set(build_ubigeo._download(client)) == set(build_ubigeo.FILES)
    # GODAS: el GRIB y cada redirección.
    asked.clear()
    client = httpx.Client(transport=_net({"ftp.cpc.ncep.noaa.gov": (200, "User-agent: *\nDisallow: /godas/\n")}, {},
                                         asked))
    with pytest.raises(SystemExit, match="no permite"):
        clim.fetch_month(client, 2026, 9, robots=Robots(client))
    assert asked == ["https://ftp.cpc.ncep.noaa.gov/robots.txt"]
    asked.clear()
    grib, elsewhere = "https://ftp.cpc.ncep.noaa.gov/godas/monthly/godas.M.202609.grb", "https://m.example/g.grb"
    client = httpx.Client(transport=_net({"m.example": (503, "")}, {grib: _to(elsewhere)}, asked))
    with pytest.raises(SystemExit, match="no respondió"):
        clim.fetch_month(client, 2026, 9, robots=Robots(client))
    assert elsewhere not in asked


def test_firecrawl_only_after_a_browser_run_that_touched_no_forbidden_path(monkeypatch, tmp_path):
    """Firecrawl carga la página en nombre del observatorio y nada revisa lo que pide después: sin el navegador
    propio (``--no-browser``) no se le pasa la página."""
    from tools import scrape_ladder as L

    called: list[str] = []
    monkeypatch.setattr(L, "DELAY_S", 0)
    monkeypatch.setenv("FIRECRAWL_API_KEY", "k")
    monkeypatch.setattr(L, "firecrawl_step", lambda client, url, *a: called.append(url) or {"found": False, "class": "ok"})
    client = httpx.Client(transport=_net({}, {}, []))
    rep = L.run([{"id": "x", "url": "https://a.example/", "expect": "naranja"}], tmp_path, browser_ok=False, client=client)
    assert called == [] and rep["results"][0]["answer"] == "not-found"


def _relay_copy(root, url: str, body: bytes, kind: str = "peru"):
    import hashlib
    import json
    from datetime import datetime, timezone

    from enso.fetch import Relay

    (root / "files").mkdir(parents=True)
    sha = hashlib.sha256(body).hexdigest()
    (root / "files" / f"{sha[:16]}.html").write_bytes(body)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (root / "index.json").write_text(json.dumps({"schema": "enso-relay/1", "collected_at": now,
                                                 "collector": {"kind": kind}, "entries": [
        {"url": url, "status": 200, "content_type": "text/html", "file": f"files/{sha[:16]}.html", "sha256": sha,
         "fetched_at": now}]}), encoding="utf-8")
    return Relay(root)


def test_a_refused_hop_is_not_captured_by_the_archive_nor_read_from_relays(tmp_path):
    """El Internet Archive y el recolector del Perú seguirían la misma redirección: tras un salto prohibido no se pide
    una captura nueva ni se usa la copia de un recolector. Uno cuyo robots.txt no respondió sí deja usar la copia."""
    from enso.observatory import archived_copy

    page = "https://a.example/comunicados/"
    for target, rule, relay_ok in (
            ("https://a.example/privado/comunicados/", (200, "User-agent: *\nDisallow: /privado/\n"), False),
            ("https://b.example/comunicados/", (503, ""), True)):
        asked: list[str] = []
        host = "a.example" if "a.example" in target else "b.example"
        f = _fetcher(_net({host: rule, "web.archive.org": (200, ALLOW_ALL)}, {page: _to(target)}, asked),
                     relay=_relay_copy(tmp_path / host, page, b"<html>" + b"x" * 600 + b"</html>"))
        f.allow_archive = f.allow_save = True
        if relay_ok:
            assert f.get([page], save=True).channel == "relay-peru"
        else:
            with pytest.raises(Exception):
                f.get([page], save=True)
        assert not any("/save/" in u for u in asked) and target not in asked
        asked.clear()
        assert archived_copy(f, [page], [], save=True) is None and not any("/save/" in u for u in asked)
        assert any("/cdx/" in u and "a.example" in u for u in asked)  # el archivo se lee; lo que no se pide es capturar


def test_after_a_refused_hop_a_manual_upload_still_counts(tmp_path):
    """Una persona que subió el PDF en la consola de documentos lo bajó ella, en su navegador: tras un salto prohibido
    vale su copia (``relay-manual``) y no la de un recolector, que siguió la redirección."""
    page, target = "https://a.example/informe.pdf", "https://a.example/privado/informe.pdf"
    body = b"<html>" + b"x" * 600 + b"</html>"
    for kind, channel in (("peru", None), ("n8n", None), ("manual", "relay-manual")):
        asked: list[str] = []
        f = _fetcher(_net({"a.example": (200, "User-agent: *\nDisallow: /privado/\n")}, {page: _to(target)}, asked),
                     relay=[_relay_copy(tmp_path / kind, page, body, kind)])
        if channel:
            assert f.get([page]).channel == channel
        else:
            with pytest.raises(Exception) as exc:
                f.get([page])
            last = exc.value.attempts[-1]
            # El motivo queda en el intento del salto, que es el que muestra el estado del feed (``acquire_news``).
            assert last["error"].startswith("RobotsHop") and "copias de los recolectores" in last["note"]
        assert target not in asked


def test_max_seconds_covers_the_whole_redirect_chain(monkeypatch):
    from enso import fetch as F

    clock = [0.0]
    monkeypatch.setattr(F.time, "monotonic", lambda: clock[0])

    def handler(req):
        clock[0] += 0.8  # cada salto tarda 0,8 s en llegar
        n = int(req.url.path.strip("/h") or 0)
        return _to(f"https://a.example/h{n + 1}") if n < 3 else httpx.Response(200, text="ok")

    f = Fetcher(retries=1, polite_delay=0, allow_archive=False, max_seconds=1.0)
    f.client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    with pytest.raises(F.TooSlow):
        f._request("https://a.example/h0")


def test_a_slow_hop_robots_txt_does_not_eat_the_request_time(monkeypatch):
    """``max_seconds`` es para el servidor que responde: leer el robots.txt de otro servidor al seguir una redirección
    no lo gasta. Un salto que llega pasado el plazo no se pide."""
    from enso import fetch as F

    clock = [0.0]
    monkeypatch.setattr(F.time, "monotonic", lambda: clock[0])
    asked: list[str] = []

    def handler(req):
        asked.append(str(req.url))
        if req.url.path == "/robots.txt":
            clock[0] += 0.9  # el robots.txt del destino tarda
            return httpx.Response(404)
        clock[0] += 0.3
        return _to("https://b.example/feed") if req.url.host == "a.example" else httpx.Response(200, text="ok")

    f = _fetcher(httpx.MockTransport(handler), max_seconds=1.0)
    assert f._request("https://a.example/feed").text == "ok"
    asked.clear()
    f.max_seconds, f.robots = 0.5, None

    def slow(req):
        clock[0] += 0.6
        return _to("https://b.example/feed") if req.url.host == "a.example" else httpx.Response(200, text="ok")

    f.client = httpx.Client(transport=httpx.MockTransport(lambda r: asked.append(str(r.url)) or slow(r)),
                            follow_redirects=False)
    with pytest.raises(F.TooSlow):
        f._request("https://a.example/feed")
    assert asked == ["https://a.example/feed"]


def test_a_redirect_to_another_protocol_is_not_followed():
    """Un 302 a ``ftp://`` no se sigue (httpx tampoco puede): queda la respuesta 3xx, sin leer un robots.txt que no
    existe ni anotar un salto que el registro no aceptaría."""
    from enso.reach import next_hop

    asked: list[str] = []
    page = "https://a.example/feed.xml"
    net = _net({}, {page: _to("ftp://ftp.a.example/pub/feed.xml")}, asked)
    r, hop, verdict = get_checked(httpx.Client(transport=net), page, Robots(httpx.Client(transport=net)))
    assert (r.status_code, hop, verdict) == (302, None, True) and asked == [page]
    assert next_hop(httpx.Response(302, headers={"location": "mailto:x@a.example"},
                                   request=httpx.Request("GET", page))) is None
    f = _fetcher(net)
    assert f._request(page).status_code == 302


def test_a_redirect_into_a_reader_feed_reads_its_robots_txt():
    """Los feeds de lector solo se piden con el lector (una vez cada 20 h, sin robots.txt): una redirección desde
    otro feed que lleva a uno de ellos pasa por robots.txt."""
    page, reader = "https://feeds.example/rss", "https://sinrodeoscajamarca.com/feed/"
    asked: list[str] = []
    f = _fetcher(_net({"sinrodeoscajamarca.com": (200, "User-agent: *\nDisallow: /\n")}, {page: _to(reader)}, asked),
                 plan={reader: ["actions"]}, robots_known={reader: "disallowed"})
    with pytest.raises(Exception):
        f.get([page])
    assert reader not in asked and "https://sinrodeoscajamarca.com/robots.txt" in asked


def test_next_hop_resolves_locations_like_httpx():
    req = httpx.Request("GET", "https://a.example/dir/page?x=1")
    for loc, want in (("http:///login", "http://a.example/login"), ("https://", "https://a.example"),
                      ("../b", "https://a.example/b"), ("//c.example/d", "https://c.example/d"),
                      ("https://e.example/f", "https://e.example/f")):
        from enso.reach import next_hop
        assert next_hop(httpx.Response(302, headers={"location": loc}, request=req)) == want, loc
    assert next_hop(httpx.Response(200, request=req)) is None


def test_the_observatory_own_services_still_follow_redirects(monkeypatch):
    """La consola de lugares y el servicio de extracción son del observatorio: sus redirecciones se siguen sin
    robots.txt. Las del mismo servidor (o de http a https) no cortan las correcciones de lugares ni la extracción,
    con su token; a otro servidor httpx no lleva el token, como debe."""
    from enso import geo_overrides as GO, reports as R

    def handler(req):
        if req.url.path in ("/hook", "/api/geo/overrides"):
            return httpx.Response(308 if req.method == "POST" else 301,
                                  headers={"location": str(req.url.copy_with(path="/v2" + req.url.path))})
        if req.method == "POST":
            if req.headers.get("authorization") != "Bearer secreto":
                return httpx.Response(401)
            return httpx.Response(200, json={"data": {"number": 18}, "model": "m"})
        return httpx.Response(200, json=[])

    client = _fetcher(httpx.MockTransport(handler)).client  # como el de la corrida: sin seguir redirecciones

    class Log:
        def add(self, *a):
            raise AssertionError(a)

    assert GO.fetch_overrides(client, None, Log(), url="https://example.org/api/geo/overrides") == ([], "consola")
    monkeypatch.setenv(R.LLM_URL_ENV, "https://example.org/hook")
    monkeypatch.setenv(R.LLM_TOKEN_ENV, "secreto")
    assert "transport" not in R.llm_extract(client, "enfen-informe", "texto", url="u")


def test_an_unanswered_hop_robots_txt_does_not_keep_the_old_reading():
    """La lectura guardada de una URL (``robots_read``) es la de su propio robots.txt: si lo que no respondió fue el
    del destino de su redirección, no se arrastra y el registro no la deja ``allowed`` (n8n seguiría el salto)."""
    from datetime import datetime, timedelta, timezone

    from enso import registry
    from tools import probe_sources

    url, now = "https://a.example/feed.xml", datetime(2026, 10, 26, tzinfo=timezone.utc)
    data = {"urls": {}}
    probe_sources._put(data, url, {"class": "ok", "robots": "allowed", "at": (now - timedelta(days=7)).isoformat(),
                                   "vantage": "github-actions"})
    probe_sources._put(data, url, {"class": "http-5xx", "http": 302, "robots": "unreachable",
                                   "hop": "https://cdn.b.example/feed.xml", "at": now.isoformat(),
                                   "vantage": "github-actions"})
    assert "robots_read" not in data["urls"][url]["actions"]["github-actions"]
    assert registry.robots_verdict(url, data["urls"], now) == "unknown"


def test_the_registry_names_the_hop_whose_robots_txt_did_not_answer():
    """n8n lee el robots.txt de la URL antes de pedirla y sigue las redirecciones: el registro le dice a qué destino
    lleva, para que lea también el de ese destino."""
    from datetime import datetime, timezone

    from enso import registry

    reg = registry.build(reach={})
    src = next(s for s in reg["sources"] if s.get("kind") == "feed" and not s.get("alt_urls"))
    url, hop = src["url"], "https://cdn.example/feed.xml"
    at = datetime(2026, 10, 26, tzinfo=timezone.utc).isoformat()
    reach = {url: {"actions": {"github-actions": {"class": "http-5xx", "http": 302, "robots": "unreachable",
                                                  "hop": hop, "at": at, "vantage": "github-actions"}}}}
    reg = registry.build(reach=reach)
    entry = next(s for s in reg["sources"] if s["url"] == url)["by_url"][url]
    assert entry["hop"] == hop and entry["robots"] == "unknown"
    assert not registry.validate(reg)
    assert "hop" not in next(s for s in registry.build(reach={})["sources"] if s["url"] == url)["by_url"][url]


def test_the_peru_collector_hop_reaches_the_registry():
    from tools import probe_sources

    idx = {"collected_at": "2026-10-26T05:00:00+00:00", "entries": [
        {"url": "https://a.example/datos.json", "status": 302, "skipped": "robots-sin-respuesta", "class": "timeout",
         "hop": "https://b.example/datos.json", "error": "redirige a https://b.example/datos.json: robots.txt sin respuesta"}]}
    rec = probe_sources.from_peru_index(idx)["https://a.example/datos.json"]
    assert rec["hop"] == "https://b.example/datos.json" and rec["robots"] == "unreachable"


def _feed_url():
    from enso import registry

    src = next(s for s in registry.build(reach={})["sources"] if s.get("kind") == "feed" and not s.get("alt_urls"))
    return src["url"]


def _entry(reach, url, now=None):
    from enso import registry

    reg = registry.build(reach=reach, now=now)
    return next(s for s in reg["sources"] if s["url"] == url)["by_url"][url]


def test_a_hop_is_not_left_allowed_by_another_network_reading():
    """Que el recolector del Perú (o n8n) leyera el robots.txt de la URL no cubre el del destino de su redirección:
    con ``hop``, ``robots`` queda ``unknown`` y n8n lee el del destino antes de pedirla."""
    url, hop = _feed_url(), "https://cdn.example/feed.xml"
    reach = {url: {"actions": {"github-actions": {"class": "timeout", "http": 302, "robots": "unreachable", "hop": hop,
                                                  "at": "2026-10-19T09:00:00+00:00", "vantage": "github-actions"}},
                   "peru": {"peru-server": {"class": "http-4xx", "http": 404, "robots": "allowed",
                                            "at": "2026-10-26T05:00:00+00:00", "vantage": "peru-server"}}}}
    e = _entry(reach, url)
    assert e["hop"] == hop and e["robots"] == "unknown"


def test_an_old_hop_or_one_reached_since_does_not_stay_in_the_registry():
    """Una medición del Perú que nadie repite (la URL ya se abrió) no deja su ``hop`` para siempre: cuenta hasta
    ``STALE_DAYS`` y solo si después ninguna red alcanzó la URL."""
    from datetime import datetime, timezone

    url, hop = _feed_url(), "https://cdn.example/feed.xml"
    now = datetime(2026, 10, 26, tzinfo=timezone.utc)
    peru = {"peru-server": {"class": "http-5xx", "http": 302, "robots": "unreachable", "hop": hop,
                            "at": "2026-06-01T05:00:00+00:00", "vantage": "peru-server"}}
    ok = {"github-actions": {"class": "ok", "http": 200, "robots": "allowed", "at": "2026-10-26T09:00:00+00:00",
                             "vantage": "github-actions"}}
    assert "hop" not in _entry({url: {"peru": peru, "actions": ok}}, url, now)
    peru["peru-server"]["at"] = "2026-10-20T05:00:00+00:00"  # reciente, pero la URL respondió después
    e = _entry({url: {"peru": peru, "actions": ok}}, url, now)
    assert "hop" not in e and e["robots"] == "allowed"
    ok["github-actions"]["at"] = "2026-10-19T09:00:00+00:00"  # el salto sin respuesta es lo último que se midió
    assert _entry({url: {"peru": peru, "actions": ok}}, url, now)["hop"] == hop


def test_robots_restrictions_between_two_registries():
    from enso import registry

    def reg(**by_url):
        return {"sources": [{"by_url": by_url}]}

    a, b, c, d = (f"https://{h}.example/f" for h in "abcd")
    old = reg(**{a: {"status": "open", "robots": "allowed"}, b: {"status": "open", "robots": "allowed"},
                 c: {"status": "open", "robots": "unknown"}})
    new = reg(**{a: {"status": "robots-disallowed", "robots": "disallowed"},
                 b: {"status": "open", "robots": "unknown", "hop": "https://cdn.example/f"},
                 c: {"status": "open", "robots": "unknown"}, d: {"status": "robots-disallowed", "robots": "disallowed"}})
    got = registry.restrictions(old, new)
    assert set(got) == {a, b}  # c ya era unknown; d no estaba (nadie la pedía)
    assert got[a] == ["robots.txt no permite la ruta"] and len(got[b]) == 2
    assert registry.restrictions(new, new) == {} and registry.restrictions(new, old) == {}
    # Un salto nuevo en una que robots.txt ya prohibía no quita pedidos: nadie la pedía.
    gone = reg(**{a: {"status": "robots-disallowed", "robots": "disallowed", "channels": []}})
    back = reg(**{a: {"status": "open", "robots": "unknown", "channels": ["n8n"], "hop": "https://cdn.example/f"}})
    assert registry.restrictions(gone, back) == {}


def test_the_probe_writes_only_the_robots_restrictions_when_its_registry_fails(tmp_path):
    """La sonda semanal cuyo registro no pasa las pruebas no escribe la medición en main, pero sí lo que restringe
    por robots.txt: la ``reachability.json`` de main con solo las mediciones nuevas de esas URL."""
    import json

    from enso import registry
    from tools import build_registry, registry_restrict

    url = _feed_url()
    base_reach = {"schema": registry.REACH_SCHEMA, "updated_at": "2026-10-19T09:00:00+00:00", "urls": {}}
    ok = {"class": "ok", "http": 200, "robots": "allowed", "vantage": "github-actions"}
    feeds = [s["url"] for s in registry.build(reach={})["sources"] if s.get("kind") == "feed" and s["url"] != url]
    other = feeds[0]
    for u in (url, other):
        base_reach["urls"][u] = {"actions": {"github-actions": {**ok, "at": "2026-10-19T09:00:00+00:00"}}}
    measured = json.loads(json.dumps(base_reach))
    measured["updated_at"] = "2026-10-26T09:00:00+00:00"
    measured["urls"][url]["actions"]["github-actions"] = {"class": "robots", "robots": "disallowed", "http": None,
                                                          "at": "2026-10-26T09:00:00+00:00", "vantage": "github-actions"}
    measured["urls"][other]["actions"]["github-actions"] = {"class": "dns", "http": None, "robots": "allowed",
                                                            "at": "2026-10-26T09:00:00+00:00", "vantage": "github-actions"}
    paths = {k: tmp_path / f"{k}.json" for k in ("base_sources", "base_reach", "reach", "registry")}
    base = registry.build(reach=base_reach["urls"])
    paths["base_sources"].write_text(build_registry.render(base), encoding="utf-8")
    paths["base_reach"].write_text(json.dumps(base_reach), encoding="utf-8")
    paths["reach"].write_text(json.dumps(measured), encoding="utf-8")
    paths["registry"].write_text(build_registry.render(registry.build(reach=measured["urls"])), encoding="utf-8")
    report = tmp_path / "report.md"
    assert registry_restrict.main([str(paths["base_sources"]), str(paths["base_reach"]), "--report", str(report),
                                   "--registry", str(paths["registry"]), "--reach", str(paths["reach"])]) == 0
    written = json.loads(paths["reach"].read_text(encoding="utf-8"))
    assert written["urls"][url] == measured["urls"][url] and written["urls"][other] == base_reach["urls"][other]
    reg = json.loads(paths["registry"].read_text(encoding="utf-8"))
    by_url = {u: r for s in reg["sources"] for u, r in s["by_url"].items()}
    assert by_url[url]["status"] == "robots-disallowed" and by_url[other]["status"] == "open"  # el dns no llega
    assert f"`{url}`" in report.read_text(encoding="utf-8") and other not in report.read_text(encoding="utf-8")
    # Sin restricciones no se toca nada ni se escribe el informe.
    report.unlink()
    paths["reach"].write_text(json.dumps(base_reach), encoding="utf-8")
    paths["registry"].write_text(paths["base_sources"].read_text(encoding="utf-8"), encoding="utf-8")
    assert registry_restrict.main([str(paths["base_sources"]), str(paths["base_reach"]), "--report", str(report),
                                   "--registry", str(paths["registry"]), "--reach", str(paths["reach"])]) == 0
    assert not report.exists() and json.loads(paths["reach"].read_text(encoding="utf-8")) == base_reach


def test_the_restricted_registry_does_not_age_out_what_main_still_restricts(tmp_path):
    """``build`` cuenta ``STALE_DAYS`` desde la medición más reciente: si la sonda lleva semanas sin pasar las pruebas,
    las mediciones de main tienen más de 45 días frente a las de esta semana. Las URL que así dejarían de estar
    restringidas (un feed de lector, un ``hop``) llevan también su medición nueva y no se liberan en main."""
    import json

    from enso import registry
    from tools import registry_restrict

    srcs = registry.build(reach={})["sources"]
    feeds = [s["url"] for s in srcs if s.get("kind") == "feed" and not s.get("alt_urls")]
    reader = next(u for u in feeds if registry.urlparse(u).hostname in registry.READER_HOSTS)
    hopped, newly = [u for u in feeds if registry.urlparse(u).hostname not in registry.READER_HOSTS
                     and not registry.public_peru(u)][:2]
    t0, t1 = "2026-09-07T09:00:00+00:00", "2026-10-26T09:00:00+00:00"  # 49 días

    def reach(at):
        return {"schema": registry.REACH_SCHEMA, "updated_at": at, "urls": {
            reader: {"actions": {"github-actions": {"class": "robots", "robots": "disallowed", "http": None, "at": at,
                                                    "vantage": "github-actions"}}},
            hopped: {"actions": {"github-actions": {"class": "timeout", "http": 302, "robots": "unreachable",
                                                    "hop": "https://cdn.example/f.xml", "at": at,
                                                    "vantage": "github-actions"}},
                     "peru": {"peru-server": {"class": "ok", "http": 200, "robots": "allowed",
                                              "at": "2026-09-01T05:00:00+00:00", "vantage": "peru-server"}}},
            newly: {"actions": {"github-actions": {"class": "ok", "http": 200, "robots": "allowed", "at": at,
                                                   "vantage": "github-actions"}}}}}

    base_reach, measured_reach = reach(t0), reach(t1)
    measured_reach["urls"][newly]["actions"]["github-actions"] = {"class": "robots", "robots": "disallowed",
                                                                  "http": None, "at": t1, "vantage": "github-actions"}
    base, measured = registry.build(base_reach["urls"]), registry.build(measured_reach["urls"])
    found, written = registry_restrict.restrict(base, base_reach, measured_reach, measured)
    assert set(found) == {newly}
    by_url = {u: r for s in registry.build(written["urls"])["sources"] for u, r in s["by_url"].items()}
    assert by_url[newly]["status"] == "robots-disallowed"
    assert by_url[reader]["status"] == "robots-disallowed" and by_url[reader].get("reader") is True
    assert by_url[hopped]["hop"] == "https://cdn.example/f.xml" and by_url[hopped]["robots"] == "unknown"
    before = {u: r for s in base["sources"] for u, r in s["by_url"].items()}
    assert not [u for u, r in by_url.items() if u in before and registry_restrict._relaxed(before[u], r)]
    json.dumps(written)  # se escribe tal cual en reachability.json


def test_the_restricted_registry_does_not_loosen_what_main_disallows(tmp_path):
    """Una URL que main tiene prohibida por robots.txt y cuyo robots.txt no respondió esta semana (o que redirige a un
    servidor sin respuesta) queda como en main cuando otra URL sí trae una restricción nueva: lo que llega a main
    sin pasar las pruebas solo quita pedidos."""
    from enso import registry
    from tools import registry_restrict

    srcs = registry.build(reach={})["sources"]
    feeds = [s["url"] for s in srcs if s.get("kind") == "feed" and not s.get("alt_urls")
             and registry.urlparse(s["url"]).hostname not in registry.READER_HOSTS and not registry.public_peru(s["url"])]
    closed, newly = feeds[:2]
    t0, t1 = "2026-10-19T09:00:00+00:00", "2026-10-26T09:00:00+00:00"
    old_n8n = {"n8n": {"n8n-aws": {"class": "ok", "http": 200, "robots": "allowed", "at": "2026-10-01T03:00:00+00:00",
                                   "vantage": "n8n-aws"}}}

    def gha(rec, at):
        return {"actions": {"github-actions": {**rec, "at": at, "vantage": "github-actions"}}}

    ok = {"class": "ok", "http": 200, "robots": "allowed"}
    base_reach = {"schema": registry.REACH_SCHEMA, "updated_at": t0, "urls": {
        closed: {**gha({"class": "robots", "robots": "disallowed", "http": None}, t0), **old_n8n},
        newly: gha(ok, t0)}}
    for measured_closed in ({"class": "timeout", "http": None, "robots": "unreachable"},
                            {"class": "timeout", "http": 302, "robots": "unreachable", "hop": "https://cdn.example/f"}):
        measured_reach = {"schema": registry.REACH_SCHEMA, "updated_at": t1, "urls": {
            closed: {**gha(measured_closed, t1), **old_n8n},
            newly: gha({"class": "robots", "robots": "disallowed", "http": None}, t1)}}
        base, measured = registry.build(base_reach["urls"]), registry.build(measured_reach["urls"])
        assert _entry(measured_reach["urls"], closed)["status"] != "robots-disallowed"  # la medición sola lo abriría
        found, written = registry_restrict.restrict(base, base_reach, measured_reach, measured)
        assert set(found) == {newly}
        assert written["urls"][closed] == base_reach["urls"][closed]
        by_url = {u: r for s in registry.build(written["urls"])["sources"] for u, r in s["by_url"].items()}
        assert by_url[closed]["status"] == "robots-disallowed" and by_url[closed]["channels"] == []
        assert by_url[newly]["status"] == "robots-disallowed"


def test_the_restrictions_report_names_what_a_url_asks_more_than_on_main(tmp_path):
    """Revisión: una URL que la medición restringe (un ``hop`` nuevo cuyo robots.txt no respondió desde Actions) lleva
    su medición entera, y el registro la toma por posible geobloqueo: pasa al recolector del Perú. Llega igual a main
    (el recolector lee antes los dos robots.txt), pero el informe del issue lo dice en vez de dar todo por
    restricciones."""
    import json

    from enso import registry
    from tools import build_registry, registry_restrict

    srcs = registry.build(reach={})["sources"]
    url = next(s["url"] for s in srcs if s.get("kind") == "feed" and not s.get("alt_urls")
               and registry.urlparse(s["url"]).hostname not in registry.READER_HOSTS)
    t0, t1 = "2026-10-19T09:00:00+00:00", "2026-10-26T09:00:00+00:00"
    base_reach = {"schema": registry.REACH_SCHEMA, "updated_at": t0, "urls": {url: {"actions": {"github-actions": {
        "class": "ok", "http": 200, "robots": "allowed", "at": t0, "vantage": "github-actions"}}}}}
    measured = {"schema": registry.REACH_SCHEMA, "updated_at": t1, "urls": {url: {"actions": {"github-actions": {
        "class": "timeout", "http": 302, "robots": "unreachable", "hop": "https://cdn.example/f.xml", "at": t1,
        "vantage": "github-actions"}}}}}
    paths = {k: tmp_path / f"{k}.json" for k in ("base_sources", "base_reach", "reach", "registry")}
    base = registry.build(reach=base_reach["urls"])
    paths["base_sources"].write_text(build_registry.render(base), encoding="utf-8")
    paths["base_reach"].write_text(json.dumps(base_reach), encoding="utf-8")
    paths["reach"].write_text(json.dumps(measured), encoding="utf-8")
    paths["registry"].write_text(build_registry.render(registry.build(reach=measured["urls"])), encoding="utf-8")
    report = tmp_path / "report.md"
    assert registry_restrict.main([str(paths["base_sources"]), str(paths["base_reach"]), "--report", str(report),
                                   "--registry", str(paths["registry"]), "--reach", str(paths["reach"])]) == 0
    reg = json.loads(paths["registry"].read_text(encoding="utf-8"))
    got = next(r for s in reg["sources"] for u, r in s["by_url"].items() if u == url)
    was = next(r for s in base["sources"] for u, r in s["by_url"].items() if u == url)
    assert got["hop"] == "https://cdn.example/f.xml" and got["robots"] == "unknown"
    gained = sorted(set(got["channels"]) - set(was["channels"]))
    text = report.read_text(encoding="utf-8")
    assert gained and "piden más que en la rama principal (1;" in text
    assert all(f"canal {c}" in text for c in gained) and text.count(f"`{url}`") == 2
    assert "se pide tras leer su robots.txt y el de https://cdn.example/f.xml" in text

    # Un hop que se resuelve en «prohibido» (sin canales) o que cambia por otro no pide más: no va en esa lista.
    hop_on_main = {"actions": {"github-actions": {**measured["urls"][url]["actions"]["github-actions"], "at": t0}},
                   "n8n": {"n8n-aws": {"class": "ok", "http": 200, "robots": "allowed", "at": "2026-10-10T03:00:00+00:00",
                                       "vantage": "n8n-aws"}}}
    base_reach["urls"][url] = hop_on_main
    base = registry.build(reach=base_reach["urls"])
    assert next(r for s in base["sources"] for u, r in s["by_url"].items() if u == url).get("hop")
    for now in ({"class": "robots", "http": 302, "robots": "disallowed", "hop": "https://cdn.example/f.xml"},
                {"class": "timeout", "http": 302, "robots": "unreachable", "hop": "https://cdn2.example/g.xml"}):
        week = {**measured, "urls": {url: {**hop_on_main, "actions": {"github-actions": {
            **now, "at": t1, "vantage": "github-actions"}}}}}
        paths["base_sources"].write_text(build_registry.render(base), encoding="utf-8")
        paths["base_reach"].write_text(json.dumps(base_reach), encoding="utf-8")
        paths["reach"].write_text(json.dumps(week), encoding="utf-8")
        paths["registry"].write_text(build_registry.render(registry.build(reach=week["urls"])), encoding="utf-8")
        assert registry_restrict.main([str(paths["base_sources"]), str(paths["base_reach"]), "--report", str(report),
                                       "--registry", str(paths["registry"]), "--reach", str(paths["reach"])]) == 0
        text = report.read_text(encoding="utf-8")
        assert f"`{url}`" in text and "piden más que en la rama principal" not in text, text


def test_the_restrictions_report_says_when_an_aged_out_url_is_asked_without_reading_robots_txt(tmp_path):
    """Un robots.txt en contra de más de 45 días deja de contar (``STALE_DAYS``) y la URL queda ``allowed``: n8n y
    la corrida la piden sin volver a leer su robots.txt. El informe lo dice así, no que lo leen antes."""
    import json

    from enso import registry
    from tools import build_registry, registry_restrict

    feeds = [s["url"] for s in registry.build(reach={})["sources"] if s.get("kind") == "feed" and not s.get("alt_urls")
             and registry.urlparse(s["url"]).hostname not in registry.READER_HOSTS and not registry.public_peru(s["url"])]
    aged, newly = feeds[:2]
    t0, t1 = "2026-10-19T09:00:00+00:00", "2026-10-26T09:00:00+00:00"

    def gha(rec, at):
        return {"github-actions": {**rec, "at": at, "vantage": "github-actions"}}

    ok = {"class": "ok", "http": 200, "robots": "allowed"}
    base_reach = {"schema": registry.REACH_SCHEMA, "updated_at": t0, "urls": {
        aged: {"actions": gha(ok, t0), "n8n": {"n8n-aws": {"class": "robots", "http": None, "robots": "disallowed",
                                                            "at": "2026-09-08T03:00:00+00:00", "vantage": "n8n-aws"}}},
        newly: {"actions": gha(ok, t0)}}}
    measured = {"schema": registry.REACH_SCHEMA, "updated_at": t1, "urls": {
        aged: {**base_reach["urls"][aged], "actions": gha(ok, t1)},
        newly: {"actions": gha({"class": "robots", "http": None, "robots": "disallowed"}, t1)}}}
    base = registry.build(reach=base_reach["urls"])
    assert next(r for s in base["sources"] for u, r in s["by_url"].items() if u == aged)["status"] == "robots-disallowed"
    paths = {k: tmp_path / f"{k}.json" for k in ("base_sources", "base_reach", "reach", "registry")}
    paths["base_sources"].write_text(build_registry.render(base), encoding="utf-8")
    paths["base_reach"].write_text(json.dumps(base_reach), encoding="utf-8")
    paths["reach"].write_text(json.dumps(measured), encoding="utf-8")
    paths["registry"].write_text(build_registry.render(registry.build(reach=measured["urls"])), encoding="utf-8")
    report = tmp_path / "report.md"
    assert registry_restrict.main([str(paths["base_sources"]), str(paths["base_reach"]), "--report", str(report),
                                   "--registry", str(paths["registry"]), "--reach", str(paths["reach"])]) == 0
    text = report.read_text(encoding="utf-8")
    line = next(x for x in text.splitlines() if x.startswith(f"- `{aged}`"))
    assert "estado robots-disallowed → open" in line and "se pide sin volver a leer su robots.txt" in line
    assert "tras leer" not in line and "45 días" in text


def test_n8n_reading_of_a_hop_robots_txt_keeps_the_hop():
    """n8n lee el robots.txt del destino (``hop``) de una URL ``unknown``: si lo prohíbe, el registro juzga por ese
    servidor. Sin el ``hop`` en su registro, una URL de una entidad pública del Perú perdía ese «prohibido» por la
    excepción de su propio servidor."""
    from enso import registry
    from tools import probe_sources

    srcs = registry.build(reach={})["sources"]
    url = next(s["url"] for s in srcs if s.get("kind") == "feed" and registry.public_peru(s["url"]))
    hop = "https://storage.example.org/private/feed.xml"
    idx = {"collected_at": "2026-10-26T03:00:00+00:00", "collector": {"egress": "n8n-aws"}, "entries": [],
           "not_requested": [{"url": url, "robots": "disallowed", "hop": hop, "fetched_at": "2026-10-26T03:00:00+00:00"}]}
    rec = probe_sources.from_n8n_index(idx)[url]
    assert rec["class"] == "robots" and rec["hop"] == hop
    reach = {url: {"actions": {"github-actions": {"class": "timeout", "http": 302, "robots": "unreachable", "hop": hop,
                                                  "at": "2026-10-25T09:00:00+00:00", "vantage": "github-actions"}},
                   "n8n": {"n8n-aws": rec}}}
    e = _entry(reach, url)
    assert e["status"] == "robots-disallowed" and e["channels"] == [] and e["robots"] == "disallowed"
    # El informe del flujo de validación (--import) también lo trae.
    rows = [{"url": url, "veredicto": "not_requested", "robots": "disallowed", "hop": hop,
             "medido": "2026-10-26T03:00:00.000Z"}]
    assert probe_sources.from_n8n_report(rows, "n8n-aws")[0]["hop"] == hop


def test_the_crawl_delay_pause_before_a_hop_is_not_server_time(monkeypatch):
    """La pausa del ``Crawl-delay`` de una entidad pública del Perú antes de un salto es del observatorio: no gasta el
    ``max_seconds`` del pedido ni cuenta como un servidor lento."""
    from enso import fetch as F

    clock = [0.0]
    monkeypatch.setattr(F.time, "monotonic", lambda: clock[0])

    def handler(req):
        clock[0] += 0.2
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return _to("https://www.example.gob.pe/feed/") if req.url.path == "/feed" else httpx.Response(200, text="ok")

    f = _fetcher(httpx.MockTransport(handler), max_seconds=1.0)
    monkeypatch.setattr(f.robots, "pace", lambda url: clock.__setitem__(0, clock[0] + 5.0) or 5.0)
    assert f._request("https://www.example.gob.pe/feed").text == "ok"
