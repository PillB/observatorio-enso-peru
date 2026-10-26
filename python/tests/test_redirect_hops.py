"""Barrido de robots.txt del 26 de octubre de 2026: cada redirección se sigue a mano y su destino pasa por la
misma regla de robots.txt que la URL pedida, en la corrida diaria, las sondas, la captura de pruebas y las
herramientas que bajan datos. También el Internet Archive, cuyo robots.txt nadie leía."""

from __future__ import annotations

import httpx
import pytest

from enso.fetch import Fetcher, archive_prefix
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
