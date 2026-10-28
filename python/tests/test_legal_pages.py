"""Privacy Policy y Terms of Use: las plantillas CC0 de General Legal, enlazadas desde el pie y el sitemap."""

import re
from pathlib import Path

import pytest

PUBLIC = Path(__file__).resolve().parents[2] / "public"
PAGES = {"privacy.html": "Privacy Policy", "terms.html": "Terms of Use"}


@pytest.mark.parametrize("name,title", PAGES.items())
def test_page_is_the_template_with_its_credit(name, title):
    html = (PUBLIC / name).read_text(encoding="utf-8")
    assert f"<h1>{title}</h1>" in html
    assert "Observatorio ENSO Perú" in html
    # General Legal pide conservar su nota al pie aunque la licencia (CC0) no lo exija.
    assert 'This template was prepared and made publicly available by General Legal' in html
    assert "script-src 'self'" in html and not re.search(r"<script\b", html)
    assert not re.search(r'\sstyle="', html), "la CSP de la página bloquea estilos en línea"
    ids = set(re.findall(r'\sid="([^"]+)"', html))
    for target in re.findall(r'href="#([^"]+)"', html):
        assert target in ids, f"{name}: el enlace #{target} no lleva a ninguna parte"


def test_terms_keep_one_arbitration_clause():
    html = (PUBLIC / "terms.html").read_text(encoding="utf-8")
    assert "JAMS" in html and "DecisionLayer" not in html and "Select one and delete the other" not in html


def test_footer_and_sitemap_link_both_pages():
    index = (PUBLIC / "index.html").read_text(encoding="utf-8")
    sitemap = (PUBLIC / "sitemap.xml").read_text(encoding="utf-8")
    for name in PAGES:
        assert f'href="{name}"' in index
        assert f"https://pillb.github.io/observatorio-enso-peru/{name}</loc>" in sitemap
