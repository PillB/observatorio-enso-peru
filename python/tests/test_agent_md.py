"""AGENT.md y CLAUDE.md siguen describiendo el repositorio que existe.

AGENT.md manda correr comandos y leer archivos concretos; si uno se renombra o se borra, las instrucciones quedan
apuntando a nada sin que falle nada. Esta prueba lee AGENT.md con expresiones propias (no con código del proyecto) y
comprueba contra el árbol de archivos: cada ruta entre comillas invertidas existe, cada ``python -m tools.X`` es un
módulo de ``python/tools``, cada ``tests/…py`` existe, y CLAUDE.md remite a AGENT.md con su ruta.
"""
from __future__ import annotations

import re

from conftest import ROOT

REPO = ROOT.parent
AGENT = (REPO / "AGENT.md").read_text(encoding="utf-8")
CLAUDE = (REPO / "CLAUDE.md").read_text(encoding="utf-8")

# Rutas de archivos del repositorio citadas entre comillas invertidas (con extensión o terminadas en «/»).
# ``enso/…`` y ``tools/…`` son relativas a ``python/``, como en la documentación del proyecto.
_PATH_RE = re.compile(r"`((?:python|docs|config|scripts|n8n|public|functions|collector|registry|\.github|enso|tools)/[\w./*-]+)`")


def _resolve(rel: str) -> bool:
    base = ROOT if rel.startswith(("enso/", "tools/")) else REPO
    if "*" in rel:
        return any(base.glob(rel))
    return (base / rel).exists()


def test_every_path_agent_md_cites_exists():
    paths = sorted(set(_PATH_RE.findall(AGENT)))
    assert len(paths) >= 15, paths  # si la expresión deja de encontrar rutas, la prueba no probaría nada
    missing = [p for p in paths if not _resolve(p)]
    assert not missing, f"AGENT.md cita rutas que no existen: {missing}"


def test_every_module_and_test_agent_md_runs_exists():
    modules = sorted(set(re.findall(r"python -m (tools\.\w+)", AGENT)))
    tests = sorted(set(re.findall(r"\b(tests/test_\w+\.py)\b", AGENT)))
    assert {"tools.complexity", "tools.drift_sim", "tools.architecture"} <= set(modules), modules
    missing = [m for m in modules if not (ROOT / (m.replace(".", "/") + ".py")).exists()]
    missing += [t for t in tests if not (ROOT / t).exists()]
    assert not missing, f"AGENT.md manda correr algo que no existe: {missing}"


def test_claude_md_points_to_agent_md_with_its_path():
    assert "AGENT.md" in CLAUDE and "/AGENT.md" in CLAUDE
    assert re.search(r"\]\(AGENT\.md\)", CLAUDE), "el enlace relativo a AGENT.md falta"


def test_agent_md_states_the_rules_it_is_required_to_state():
    """Lo que el dueño pidió que AGENT.md diga; cada frase es la regla, no un adorno."""
    for must in ("why that expert would reject", "State every trade-off", "Tautological tests",
                 "Mutation proof", "chore(lint)", "10 or less", "Pre-execution", "fail verbose"):
        assert must.lower() in AGENT.lower(), must
