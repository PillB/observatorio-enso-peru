"""Los números que dicen los documentos y los diagramas coinciden con los del código y los datos.

Cada uno de estos números se había desactualizado alguna vez (el sitio pasó de 10 a 11 y a 12 vistas y la
arquitectura seguía diciendo 10): aquí falla la prueba cuando uno deja de coincidir."""

import json
import re

from conftest import ROOT as PY
from enso import observatory as obs
from enso import news as N

REPO = PY.parent
ARCH = [REPO / "docs" / "arquitectura.md", REPO / "docs" / "arquitectura.json", REPO / "docs" / "arquitectura-anexos.json"]


def _text(p):
    return p.read_text(encoding="utf-8")


def test_the_number_of_views_in_the_docs_is_the_number_of_tabs():
    app = _text(REPO / "public" / "assets" / "js" / "sitio.js")  # las pestañas y su agrupación (versiones A y B)
    nav = re.search(r"const NAV = \[(.*?)\];", app, re.S).group(1)
    tabs = len(re.findall(r"\['[^']*', '[^']*', '[^']*'\]", nav))
    for p in ARCH:
        said = {int(n) for n in re.findall(r"\b(\d+) (?:vistas|views)\b", _text(p))}
        assert said <= {tabs}, f"{p.name}: dice {sorted(said)} vistas y el sitio tiene {tabs}"
    assert tabs >= 12


def test_the_number_of_past_disaster_sources_in_the_docs_matches_the_catalogue():
    fuentes = json.loads(_text(REPO / "data" / "historico" / "fuentes.json"))["fuentes"]
    n = sum(1 for f in fuentes if f.get("tipo") != "referencia")  # las referencias territoriales no son fuentes de desastres
    for p in [*ARCH, REPO / "docs" / "catalogo-fuentes.md", REPO / "docs" / "atribucion-licencias.md"]:
        said = {int(x) for x in re.findall(r"\b(\d+) fuentes de (?:desastres pasados|la pestaña «Memoria)", _text(p))}
        said |= {int(x) for x in re.findall(r"desastres pasados \((\d+) fuentes\)", _text(p))}
        assert said <= {n}, f"{p.name}: dice {sorted(said)} fuentes de desastres y el catálogo tiene {n}"


def test_the_number_of_feeds_and_enso_sources_in_the_docs_matches_the_code():
    text = _text(REPO / "docs" / "arquitectura.md")
    m = re.search(r"catálogos del código \((\d+) feeds, (\d+) fuentes ENSO", text)
    assert m, "la tabla del registro ya no dice cuántos feeds y fuentes ENSO junta"
    assert (int(m[1]), int(m[2])) == (len(N.FEEDS), len(obs.SOURCES))
