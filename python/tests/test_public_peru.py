"""Entidades públicas del Perú (``.gob.pe``, ``.mil.pe``): su robots.txt no decide qué se pide (decisión del 26 de
octubre de 2026), pero su Crawl-delay se respeta y una verificación antirobots nunca se evade."""

import httpx

from enso import registry
from enso.reach import PUBLIC_PERU_GAP_S, Robots, public_peru

RULES = "User-agent: *\nDisallow: /arcgis/\nCrawl-delay: 5\n"


def _robots(body: str = RULES, status: int = 200, headers: dict | None = None) -> Robots:
    def handler(req):
        return httpx.Response(status, text=body, headers=headers or {"content-type": "text/plain"})
    return Robots(httpx.Client(transport=httpx.MockTransport(handler)))


def test_public_peru_hosts():
    assert public_peru("https://sigrid.cenepred.gob.pe/arcgis/rest/services")
    assert public_peru("https://www.dhn.mil.pe/") and public_peru("https://gob.pe/x")
    assert not public_peru("https://evilgob.pe/") and not public_peru("https://www.pucp.edu.pe/")
    assert not public_peru("https://data.humdata.org/api/3/action/package_show")


def test_disallow_is_overridden_only_for_public_peru():
    r = _robots()
    assert r.allowed("https://sigrid.cenepred.gob.pe/arcgis/rest/services/x") is True
    assert r.overridden("https://sigrid.cenepred.gob.pe/arcgis/rest/services/x")
    assert not r.overridden("https://sigrid.cenepred.gob.pe/sigridv3/")
    assert r.allowed("https://example.org/arcgis/x") is False and not r.overridden("https://example.org/arcgis/x")


def test_unreachable_robots_is_overridden_but_a_challenge_is_not():
    assert _robots("", status=503).allowed("https://snirh.ana.gob.pe/onrh/") is True
    assert _robots("", status=503).allowed("https://example.org/") is None
    challenge = _robots("<html>Just a moment...</html>", status=403, headers={"cf-mitigated": "challenge"})
    assert challenge.allowed("https://www.senamhi.gob.pe/") is None


def test_pace_honours_crawl_delay_between_requests(monkeypatch):
    r = _robots()
    slept = []
    monkeypatch.setattr("enso.reach.time.sleep", slept.append)
    url = "https://sigrid.cenepred.gob.pe/arcgis/x"
    assert r.pace(url) == 0.0
    assert r.pace(url) > 4.9 and slept and slept[-1] > 4.9
    assert r.pace("https://example.org/x") == 0.0  # otros servidores: los pausa cada llamador
    assert _robots("User-agent: *\nCrawl-delay: 600\n").crawl_delay(url) == 600
    lo, hi = PUBLIC_PERU_GAP_S
    big = _robots("User-agent: *\nCrawl-delay: 600\n")
    big.pace(url)
    assert big.pace(url) <= hi + 0.01


def test_registry_ignores_robots_measurements_for_public_peru():
    u = "https://snirh.ana.gob.pe/onrh/"
    rec = {"class": "robots", "at": "2026-10-26T01:00:00+00:00", "vantage": "github-actions", "robots": "disallowed"}
    gb = registry.geoblock(u, {u: {"actions": {"github-actions": rec}}})
    assert gb["status"] != "robots-disallowed" and registry.channels_for(gb["status"]) != []
    assert registry.robots_verdict(u, {u: {"actions": {"github-actions": rec}}}) == "allowed"
    other = "https://example.org/x"
    assert registry.geoblock(other, {other: {"actions": {"github-actions": rec}}})["status"] == "robots-disallowed"


def test_registry_keeps_the_challenge_stop_for_public_peru():
    """Un robots.txt con verificación antirobots en su lugar (como el feed del IMARPE desde Actions) no pasa a
    ``allowed``: el pipeline no lo pide directo y n8n tampoco, como antes."""
    u = "https://www.imarpe.gob.pe/feed/"
    rec = {"class": "challenge", "at": "2026-10-26T16:11:41+00:00", "vantage": "github-actions",
           "detail": "robots.txt sin respuesta", "robots": "unreachable"}
    assert registry.robots_verdict(u, {u: {"actions": {"github-actions": rec}}}) == "unknown"


def test_scrape_ladder_paces_public_peru_gets(monkeypatch):
    from tools import scrape_ladder

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=RULES)
        return httpx.Response(200, text="ok")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    r = Robots(client)
    slept = []
    monkeypatch.setattr("enso.reach.time.sleep", slept.append)
    for _ in range(2):
        resp, blocked, _ = scrape_ladder.get_checked(client, "https://sigrid.cenepred.gob.pe/arcgis/x", r)
        assert resp.status_code == 200 and blocked is None
    assert slept and slept[-1] > 4.9


def test_a_redirect_to_a_non_public_host_keeps_its_disallow():
    """La sonda anota en ``hop`` el destino prohibido de una redirección: cuenta el servidor de ese destino."""
    u = "https://www.senamhi.gob.pe/descarga"
    rec = {"class": "robots", "at": "2026-10-26T01:00:00+00:00", "vantage": "github-actions", "robots": "disallowed",
           "hop": "https://example.org/archivo.zip"}
    reach = {u: {"actions": {"github-actions": rec}}}
    assert registry.geoblock(u, reach)["status"] == "robots-disallowed"
    assert registry.robots_verdict(u, reach) == "disallowed"
    public_hop = {u: {"actions": {"github-actions": {**rec, "hop": "https://otra.gob.pe/x"}}}}
    assert registry.robots_verdict(u, public_hop) == "allowed"
