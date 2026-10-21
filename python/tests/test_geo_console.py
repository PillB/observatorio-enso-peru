"""Consola de lugares: la API (con ``node --test``), las cuentas y un recorrido en el navegador."""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

from tools import geo_users

ROOT = Path(__file__).resolve().parents[2]
JS = Path(__file__).parent / "js"


def _node() -> str | None:
    node = shutil.which("node")
    if not node:
        return None
    v = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v")
    major, minor = (int(x) for x in v.split(".")[:2])
    return node if (major, minor) >= (22, 5) else None  # node:sqlite


def _need_node() -> str:
    node = _node()
    if not node:
        if os.environ.get("CI"):
            pytest.fail("las pruebas de la consola necesitan Node 22.5 o más nuevo")
        pytest.skip("requiere Node 22.5 o más nuevo")
    return node


def test_api_with_node():
    node = _need_node()
    env = dict(os.environ, GEO_TEST_PY_HASH=geo_users.hash_password("clave-de-prueba"))
    r = subprocess.run([node, "--test", str(JS / "geo_console.test.mjs")], capture_output=True, text=True, env=env, timeout=300)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
    assert re.search(r"# fail 0", r.stdout) and not re.search(r"# skipped [1-9]", r.stdout), r.stdout[-2000:]


def test_accounts_hash_only_and_stay_out_of_the_repo(tmp_path):
    users, issued = geo_users.build(10, "pablo")
    assert len(users) == 11 and len(issued) == 11
    assert users["pablo"]["role"] == "admin" and users["revisor10"]["role"] == "tester"
    for name, _, pw in issued:
        assert len(pw) == 16 and pw not in json.dumps(users)
        assert geo_users.verify(pw, users[name]["hash"])
    # Agregar cuentas conserva las existentes; renovar cambia solo la pedida.
    more, new = geo_users.build(12, "pablo", keep=users, renew=("revisor03",))
    assert {n for n, _, _ in new} == {"revisor11", "revisor12", "revisor03"}
    assert more["revisor01"] == users["revisor01"] and more["revisor03"] != users["revisor03"]
    assert geo_users.main(["--out", str(ROOT / "python" / "tmp-claves")]) == 2
    assert not (ROOT / "python" / "tmp-claves").exists()
    assert geo_users.main(["--out", str(tmp_path), "--testers", "2"]) == 0
    rows = list(csv.DictReader(open(tmp_path / "contrasenas-consola-PRIVADO.csv", encoding="utf-8")))
    assert [r["usuario"] for r in rows] == ["pablo", "revisor01", "revisor02"]
    assert oct((tmp_path / "GEO_USERS.json").stat().st_mode)[-3:] == "600"


def test_public_site_does_not_link_the_console_or_the_repo():
    admin = (ROOT / "public" / "admin" / "index.html").read_text(encoding="utf-8")
    assert 'name="robots" content="noindex' in admin
    for f in (ROOT / "public" / "admin").iterdir():
        assert "github.com" not in f.read_text(encoding="utf-8").lower(), f
    for f in ("index.html", "sitemap.xml", "robots.txt"):
        assert "admin/" not in (ROOT / "public" / f).read_text(encoding="utf-8"), f


# --- Recorrido en el navegador -----------------------------------------------------------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def console(request):
    d = request.config.getoption("--site-dir")
    if not d:
        pytest.skip("requiere --site-dir")
    site = Path(d).resolve()
    if not (site / "data" / "geo" / "items.json").exists():
        pytest.fail(f"{site}/data/geo/items.json no existe: genere la publicación antes")
    node = _need_node()
    users = {"revisor01": {"hash": geo_users.hash_password("clave-revisor-1"), "role": "tester"}}
    port = _free_port()
    proc = subprocess.Popen([node, str(JS / "dev-server.mjs"), "--site", str(site), "--port", str(port)],
                            env=dict(os.environ, GEO_USERS=json.dumps(users)), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield f"http://localhost:{port}/"
    proc.terminate()
    proc.wait(10)


@pytest.mark.browser
def test_reviewer_logs_in_corrects_a_place_and_sees_the_history(console, browser):
    pw = pytest.importorskip("playwright.sync_api")
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, locale="es-PE")
    try:
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(console + "admin/")
        expect = pw.expect
        expect(page.get_by_role("heading", name="Ingresar")).to_be_visible()
        page.get_by_label("Usuario").fill("revisor01")
        page.get_by_label("Contraseña").fill("mala")
        page.get_by_role("button", name="Ingresar").click()
        expect(page.get_by_role("alert").first).to_contain_text("incorrectos")
        page.get_by_label("Contraseña").fill("clave-revisor-1")
        page.get_by_role("button", name="Ingresar").click()
        expect(page.get_by_text("revisor01")).to_be_visible()
        expect(page.get_by_role("tab", name=re.compile("Por revisar"))).to_have_attribute("aria-selected", "true")
        page.get_by_role("tab", name=re.compile("^Todas")).click()
        first = page.locator(".gc-item").first
        expect(first).to_be_visible()
        title = first.locator("h2").inner_text()
        first.get_by_role("button", name="Corregir…").click()
        # El editor parte de los lugares que la nota ya tiene (en la publicación en vivo, casi siempre alguno):
        # se quitan para que la corrección sea solo Miraflores.
        remove = first.locator('.gc-chosen button[aria-label^="Quitar"]')
        while remove.count():
            remove.first.click()
        first.get_by_label("Departamento", exact=True).select_option(label="Lima")
        first.get_by_label("Provincia", exact=True).select_option(label="Lima")
        first.get_by_label("Distrito", exact=True).select_option(label="Miraflores")
        first.get_by_role("button", name="Agregar").click()
        first.get_by_label("Nota (opcional)").fill("prueba automática")
        first.get_by_role("button", name="Guardar corrección").click()
        card = page.locator(".gc-item", has_text=title).first
        expect(card.locator(".gc-fix")).to_contain_text("Miraflores")
        expect(card.locator(".gc-fix")).to_contain_text("próxima actualización")
        card.get_by_role("button", name="Historial").click()
        expect(card.locator(".gc-history")).to_contain_text("revisor01")
        page.get_by_role("tab", name=re.compile("Corregidas")).click()
        expect(page.locator(".gc-item")).to_have_count(1)
        page.get_by_role("tab", name="Registro de cambios").click()
        expect(page.locator(".gc-audit-row").first).to_contain_text("corrigió")
        page.get_by_role("button", name="Salir").click()
        expect(page.get_by_role("heading", name="Ingresar")).to_be_visible()
        assert not errors, errors
        # La lista pública que lee el pipeline ya trae la corrección, sin nombres.
        pub = page.request.get(console + "api/geo/overrides").json()
        assert pub["overrides"][0]["places"] == ["150122"] and "revisor01" not in json.dumps(pub)
    finally:
        ctx.close()
