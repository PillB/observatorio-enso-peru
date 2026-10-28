"""El sitio preparado para otro servidor no remite al repositorio."""

import shutil
from pathlib import Path

import pytest

from tools.prepare_site import REPO_HOST, prepare

PUBLIC = Path(__file__).resolve().parents[2] / "public"


@pytest.fixture
def site(tmp_path):
    d = tmp_path / "site"
    shutil.copytree(PUBLIC, d, ignore=shutil.ignore_patterns("data"))
    return d


def test_rewrites_address_and_hides_repo(site):
    prepare(site, "https://observatorio-enso.pages.dev", hide_repo=True, cloudflare=True)
    for f in site.rglob("*"):
        if f.is_file() and f.suffix in {".html", ".js", ".txt", ".xml", ".webmanifest"}:
            text = f.read_text(encoding="utf-8")
            assert "pillb.github.io" not in text, f
            assert REPO_HOST not in text, f
    index = (site / "index.html").read_text(encoding="utf-8")
    assert '<link rel="canonical" href="https://observatorio-enso.pages.dev/">' in index
    assert 'content="https://observatorio-enso.pages.dev/og-image.png"' in index
    assert 'href="/assets/css/app.css"' in (site / "404.html").read_text(encoding="utf-8")
    for legal in ("privacy.html", "terms.html"):
        assert f'<link rel="canonical" href="https://observatorio-enso.pages.dev/{legal}">' in (site / legal).read_text(encoding="utf-8")
    assert "Sitemap: https://observatorio-enso.pages.dev/sitemap.xml" in (site / "robots.txt").read_text()
    headers = (site / "_headers").read_text()
    assert "Access-Control-Allow-Origin: *" in headers
    # Las copias de páginas de terceros nunca ejecutan nada en el dominio del sitio.
    assert "/data/archive/*\n  Content-Security-Policy: sandbox; default-src 'none'" in headers


def test_subpath_and_repo_kept_by_default(site):
    prepare(site, "https://example.org/enso/", hide_repo=False, cloudflare=False)
    assert 'href="/enso/assets/css/app.css"' in (site / "404.html").read_text(encoding="utf-8")
    assert REPO_HOST in (site / "index.html").read_text(encoding="utf-8")
    assert not (site / "_headers").exists()


def test_rejects_plain_http(site):
    with pytest.raises(ValueError):
        prepare(site, "http://example.org/", hide_repo=True, cloudflare=False)


def test_code_leak_fails(site):
    (site / "assets" / "extra.js").write_text("// https://github.com/PillB/observatorio-enso-peru", encoding="utf-8")
    with pytest.raises(RuntimeError, match="extra.js"):
        prepare(site, "https://observatorio-enso.pages.dev/", hide_repo=True, cloudflare=False)
