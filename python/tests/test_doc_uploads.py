"""Consola de documentos: la API de subida (``functions/_lib/doc-uploads.js``) y la revisión del archivo en el
navegador (``public/admin/documentos.js``), con ``node --test``."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tests.test_geo_console import ROOT, _need_node

JS = Path(__file__).parent / "js"


def test_upload_api_with_node():
    node = _need_node()
    r = subprocess.run([node, "--test", str(JS / "doc_uploads.test.mjs")], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
    assert re.search(r"# fail 0", r.stdout) and not re.search(r"# skipped [1-9]", r.stdout), r.stdout[-2000:]


def test_documents_page_is_private_and_reuses_the_console_session():
    page = (ROOT / "public" / "admin" / "documentos.html").read_text(encoding="utf-8")
    assert 'name="robots" content="noindex' in page and "connect-src 'self'" in page
    js = (ROOT / "public" / "admin" / "documentos.js").read_text(encoding="utf-8")
    assert "../api/docs/" in js and "../api/geo/" in js and "innerHTML" not in js
    # Los enlaces a las fuentes se abren sin enviar la dirección de la consola.
    assert "noopener noreferrer" in js
