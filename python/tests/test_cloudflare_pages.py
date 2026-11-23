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

    assert ensure_project(client(h), "acc", "observatorio-enso", "main") == ("https://observatorio-enso-2x9.pages.dev/", "main")
    assert calls == ["GET"]


def test_missing_project_is_created():
    def h(req):
        if req.method == "GET":
            return httpx.Response(404, json={"errors": [{"message": "Project not found"}]})
        body = json.loads(req.content)
        assert body == {"name": "observatorio-enso", "production_branch": "main"}
        return httpx.Response(200, json={"result": {"subdomain": "observatorio-enso.pages.dev"}})

    assert ensure_project(client(h), "acc", "observatorio-enso", "main") == ("https://observatorio-enso.pages.dev/", "main")


def test_bad_token_explains_the_permission():
    h = lambda req: httpx.Response(403, json={"errors": [{"message": "Authentication error"}]})
    with pytest.raises(RuntimeError, match="Cloudflare Pages · Edit"):
        ensure_project(client(h), "acc", "observatorio-enso", "main")


def test_existing_project_keeps_its_production_branch():
    h = lambda req: httpx.Response(200, json={"result": {"subdomain": "x.pages.dev", "production_branch": "production"}})
    assert ensure_project(client(h), "acc", "x", "main") == ("https://x.pages.dev/", "production")


def _project(prod_vars, preview_vars=None, d1=True):
    prod = {"env_vars": prod_vars}
    if d1:
        prod["d1_databases"] = {"GEO_DB": {"id": "x"}}
    return {"subdomain": "x.pages.dev", "deployment_configs": {"production": prod, "preview": {"env_vars": preview_vars or {}}}}


def test_boletin_report_names_missing_secret_and_preview_mixup():
    from tools.cloudflare_pages import boletin_report

    sec = {"type": "secret_text"}
    ok = {"BOLETIN_SECRET": sec, "BOLETIN_LIST_TOKEN": sec, "BOLETIN_MAIL_WEBHOOK": sec, "BOLETIN_MAIL_WEBHOOK_SECRET": sec}
    assert boletin_report(_project(ok)) == []
    miss = {k: v for k, v in ok.items() if k != "BOLETIN_MAIL_WEBHOOK_SECRET"}
    [w] = boletin_report(_project(miss, {"BOLETIN_MAIL_WEBHOOK_SECRET": sec}))
    assert "falta BOLETIN_MAIL_WEBHOOK_SECRET" in w and "Preview" in w
    # Con Resend no hace falta el webhook.
    resend = {"BOLETIN_SECRET": sec, "BOLETIN_LIST_TOKEN": sec, "RESEND_API_KEY": sec, "BOLETIN_FROM": {"type": "plain_text", "value": "a@b"}}
    assert boletin_report(_project(resend)) == []
    assert any("GEO_DB" in w for w in boletin_report(_project(ok, d1=False)))


def test_check_boletin_copies_github_secrets_without_whitespace():
    from tools.cloudflare_pages import check_boletin

    sent = []

    def h(req):
        if req.method == "PATCH":
            body = json.loads(req.content)
            sent.append(body)
            vars_ = body["deployment_configs"]["production"]["env_vars"]
            return httpx.Response(200, json={"result": _project({k: {"type": "secret_text"} for k in [*vars_, "BOLETIN_SECRET", "BOLETIN_LIST_TOKEN", "BOLETIN_MAIL_WEBHOOK"]})})
        return httpx.Response(200, json={"result": _project({})})

    warnings = check_boletin(client(h), "acc", "x", {"BOLETIN_MAIL_WEBHOOK_SECRET": "  s3cr3t\n", "BOLETIN_SECRET": "", "OTRO": "y"})
    assert sent == [{"deployment_configs": {"production": {"env_vars": {"BOLETIN_MAIL_WEBHOOK_SECRET": {"type": "secret_text", "value": "s3cr3t"}}}}}]
    assert warnings == []
    # Sin secretos en GitHub solo lee y avisa.
    sent.clear()
    warnings = check_boletin(client(h), "acc", "x", {})
    assert sent == [] and any("BOLETIN_MAIL_WEBHOOK_SECRET" in w for w in warnings)
