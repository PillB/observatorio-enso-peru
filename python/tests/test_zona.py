"""Mi zona: las funciones de la página (``node --test``) y que la sección esté en la navegación."""

import re
import subprocess

from test_geo_console import JS, _need_node
from test_geo_console import ROOT


def test_zona_page_functions_with_node():
    r = subprocess.run([_need_node(), "--test", str(JS / "zona.test.mjs")], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


def test_zona_is_a_route_in_the_navigation():
    app = (ROOT / "public/assets/js/app.js").read_text(encoding="utf-8")
    assert "VIEWS.zona" in app
    nav = (ROOT / "public/assets/js/sitio.js").read_text(encoding="utf-8")
    assert re.search(r"\['zona', 'Mi zona',", nav)
