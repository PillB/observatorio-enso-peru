"""Política de Privacidad y Términos de Uso, en castellano y en inglés: salen de las plantillas CC0 de General Legal
adaptadas al sitio (scripts/legal/), y se enlazan desde el pie de página y el sitemap."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "public"
PAGES = {"privacidad.html": "Política de Privacidad", "terminos.html": "Términos de Uso",
         "privacy.html": "Privacy Policy", "terms.html": "Terms of Use"}


def test_pages_match_their_sources():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "legal" / "build.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("name,title", PAGES.items())
def test_page_keeps_its_credit_and_strict_csp(name, title):
    html = (PUBLIC / name).read_text(encoding="utf-8")
    assert f"<h1>{title}</h1>" in html
    # General Legal pide conservar su nota al pie aunque la licencia (CC0) no lo exija.
    assert "This template was prepared and made publicly available by General Legal" in html
    assert "script-src 'self'" in html and not re.search(r"<script\b", html)
    assert not re.search(r'\sstyle="', html), "la CSP de la página bloquea estilos en línea"
    ids = set(re.findall(r'\sid="([^"]+)"', html))
    for target in re.findall(r'href="#([^"]+)"', html):
        assert target in ids, f"{name}: el enlace #{target} no lleva a ninguna parte"
    for other in re.findall(r'href="([a-z]+\.html)"', html):
        assert (PUBLIC / other).exists(), f"{name}: {other} no existe"


@pytest.mark.parametrize("name", PAGES)
def test_pages_describe_this_site(name):
    """Lo que no aplica a un sitio público peruano sin cuentas, pagos ni publicidad ya no está en el texto."""
    html = (PUBLIC / name).read_text(encoding="utf-8")
    for gone in ("JAMS", "DecisionLayer", "arbitra", "headquartered in the United States", "U.S.-based company",
                 "Payment processors", "Interest-based advertising", "non-commercial purposes", "All rights reserved",
                 "Complaint Assistance Unit", "18 years old"):
        assert gone not in html, f"{name}: {gone!r}"


def test_footer_and_sitemap_link_every_page():
    index = (PUBLIC / "index.html").read_text(encoding="utf-8")
    sitemap = (PUBLIC / "sitemap.xml").read_text(encoding="utf-8")
    for name in PAGES:
        assert f'href="{name}"' in index
        assert f"https://pillb.github.io/observatorio-enso-peru/{name}</loc>" in sitemap
