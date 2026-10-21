"""Configuración común de pruebas.

Las pruebas usan respuestas reales capturadas de cada fuente
(``tests/fixtures/sources``, incluidas copias históricas del Internet
Archive en ``history/``). No hay datos inventados.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIX = ROOT / "tests" / "fixtures" / "sources"
HIST = FIX / "history"


def pytest_addoption(parser):
    parser.addoption("--site-dir", default=None, help="Carpeta del sitio construido (public/) para pruebas de navegador")


def pytest_configure(config):
    config.addinivalue_line("markers", "browser: recorridos de usuario en Chromium (requieren --site-dir)")


def history(prefix: str) -> list[Path]:
    return sorted(p for p in HIST.glob(f"{prefix}-[0-9]*") if p.stat().st_size > 0)


def read(p: Path) -> str:
    b = p.read_bytes()
    for enc in ("utf-8", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "replace")


@pytest.fixture(scope="session")
def fix() -> Path:
    return FIX


# --- Navegador (pruebas marcadas «browser») -------------------------------------------------
# Una sola instancia de Playwright por sesión: la API síncrona no admite dos a la vez.

@pytest.fixture(scope="session")
def playwright():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(playwright):
    import os

    exe = os.environ.get("PW_CHROMIUM")
    b = playwright.chromium.launch(executable_path=exe) if exe else playwright.chromium.launch()
    yield b
    b.close()

