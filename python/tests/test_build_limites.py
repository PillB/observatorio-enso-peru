"""tools.build_limites respeta el robots.txt de HDX, como todo lo que pide el proyecto.

Revisión del 26 de octubre de 2026: pedía la API del catálogo (``/api/3/action/package_show``), que el robots.txt
de data.humdata.org prohíbe (``Disallow: /api/``).
"""

from __future__ import annotations

import io
import json
import zipfile

import httpx
import pytest

from tools import build_limites as B

GEO = {name: {"type": "FeatureCollection", "features": []} for name, _, _ in B.LEVELS.values()}


def _zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in GEO.items():
            z.writestr(name, json.dumps(data))
    return buf.getvalue()


def _client(routes: dict[str, httpx.Response], asked: list[str]) -> httpx.Client:
    def net(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        asked.append(url)
        return routes.get(url) or httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(net))


def test_a_disallowed_api_is_not_requested_and_the_message_says_how_to_go_on():
    asked: list[str] = []
    client = _client({"https://data.humdata.org/robots.txt": httpx.Response(200, text="User-agent: *\nDisallow: /api/\n")},
                     asked)
    with pytest.raises(SystemExit) as exc:
        B._download(client)
    assert asked == ["https://data.humdata.org/robots.txt"]
    assert "no permite" in str(exc.value) and "--zip" in str(exc.value) and B.DATASET in str(exc.value)


def test_a_robots_txt_that_redirects_brings_its_rules():
    """Barrido de robots.txt del 26 de octubre de 2026: un robots.txt que redirige (a https, a otro nombre) se
    tomaba como «no existe» y se permitía todo (RFC 9309 §2.3.1.2 pide seguir la redirección)."""
    asked: list[str] = []
    moved = "https://www.humdata.org/robots.txt"
    client = _client({"https://data.humdata.org/robots.txt": httpx.Response(301, headers={"location": moved}),
                      moved: httpx.Response(200, text="User-agent: *\nDisallow: /api/\n")}, asked)
    with pytest.raises(SystemExit) as exc:
        B._download(client)
    assert asked == ["https://data.humdata.org/robots.txt", moved] and "no permite" in str(exc.value)


def test_an_unreachable_robots_txt_stops_before_any_request():
    asked: list[str] = []
    client = _client({"https://data.humdata.org/robots.txt": httpx.Response(503)}, asked)
    with pytest.raises(SystemExit) as exc:
        B._download(client)
    assert set(asked) == {"https://data.humdata.org/robots.txt"} and "no respondió" in str(exc.value)


def test_each_redirect_hop_is_checked_against_its_own_robots_txt():
    zip_url = "https://data.humdata.org/dataset/x/resource/y/download/per.geojson.zip"
    s3 = "https://files.example.org/per.geojson.zip"
    meta = {"result": {"resources": [{"name": "per.geojson.zip", "url": zip_url}]}}
    asked: list[str] = []
    routes = {"https://data.humdata.org/robots.txt": httpx.Response(200, text="User-agent: *\nAllow: /\n"),
              B.PACKAGE: httpx.Response(200, json=meta),
              zip_url: httpx.Response(302, headers={"location": s3}),
              "https://files.example.org/robots.txt": httpx.Response(200, text="User-agent: *\nDisallow: /\n")}
    with pytest.raises(SystemExit) as exc:
        B._download(_client(routes, asked))
    assert s3 not in asked and "files.example.org" in str(exc.value)
    # Si el otro servidor lo permite, llegan los tres niveles.
    asked.clear()
    routes["https://files.example.org/robots.txt"] = httpx.Response(404)
    routes[s3] = httpx.Response(200, content=_zip())
    got = B._download(_client(routes, asked))
    assert set(got) == set(B.LEVELS) and asked[-1] == s3


def test_a_zip_downloaded_by_hand_builds_the_same_file(tmp_path, monkeypatch):
    path = tmp_path / "per.geojson.zip"
    path.write_bytes(_zip())
    monkeypatch.setattr(B, "OUT", tmp_path / "limites.json.gz")
    assert B.main(["--zip", str(path)]) == 0 and (tmp_path / "limites.json.gz").exists()
