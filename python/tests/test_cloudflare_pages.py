"""El proyecto de Cloudflare Pages se crea una sola vez y se lee su subdominio."""

import json

import httpx
import pytest

from tools.cloudflare_pages import ensure_project


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_existing_project_returns_its_subdomain():
    calls = []

    def h(req):
        calls.append(req.method)
        return httpx.Response(200, json={"result": {"subdomain": "observatorio-enso-2x9.pages.dev", "production_branch": "main"}})

    assert ensure_project(client(h), "acc", "observatorio-enso", "main") == "https://observatorio-enso-2x9.pages.dev/"
    assert calls == ["GET"]


def test_missing_project_is_created():
    def h(req):
        if req.method == "GET":
            return httpx.Response(404, json={"errors": [{"message": "Project not found"}]})
        body = json.loads(req.content)
        assert body == {"name": "observatorio-enso", "production_branch": "main"}
        return httpx.Response(200, json={"result": {"subdomain": "observatorio-enso.pages.dev"}})

    assert ensure_project(client(h), "acc", "observatorio-enso", "main") == "https://observatorio-enso.pages.dev/"


def test_bad_token_explains_the_permission():
    h = lambda req: httpx.Response(403, json={"errors": [{"message": "Authentication error"}]})
    with pytest.raises(RuntimeError, match="Cloudflare Pages · Edit"):
        ensure_project(client(h), "acc", "observatorio-enso", "main")
