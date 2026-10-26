"""La documentación escrita a mano dice lo que hace el código.

- Cada código que el pipeline registra como aviso, error o crítico abre un issue (``tools.sync_issues``): tiene
  su fila en la tabla de docs/operaciones.md, solo o por su familia (``stale-*``, ``late-*``, ``informe-*``), con
  qué hacer, salvo los esperados de ``sync_issues.IGNORE``.
- El README enlaza cada docs/*.md.
- Lo que dicen los documentos y el sitio sobre el ENFEN, el IMARPE y la DHN coincide con el código y el registro.
- La guía de Cloudflare nombra cada vínculo o secreto que leen las Functions.

Revisión del 22 de octubre de 2026: ocho códigos nuevos abrían issues sin decir qué hacer, tres documentos no
tenían enlace desde el README y el catálogo daba al IMARPE por inalcanzable.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Optional

from tools.sync_issues import IGNORE

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / "python"
DOCS = ROOT / "docs"
#: Carpetas (bajo python/) donde se registran incidencias. Un paquete nuevo que llame a ``log.add`` va aquí.
SCAN = ("enso", "tools")
RELEVANT = {"warning", "error", "critical"}
#: Llamadas cuyo código no es un literal, con de dónde sale: ``i.code`` son los ``Issue(...)`` de reports.py (e
#: ``i['code']``, los mismos del informe publicado que se vuelven a registrar), y ``code`` en observatory.py son los
#: avisos de un lector (``meta["events"]``, como los de feeds/godas.py), que se registran como advertencias: todos se
#: recogen aparte.
DYNAMIC = {("enso/reports.py", "i.code"), ("enso/reports.py", "i['code']"), ("enso/observatory.py", "code")}


def _severities(node: ast.expr) -> Optional[set[str]]:
    """Severidades posibles de la llamada; ``None`` si es una variable (se cuenta como relevante)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        a, b = _severities(node.body), _severities(node.orelse)
        return None if a is None or b is None else a | b
    return None


def _code(node: ast.expr) -> Optional[list[str]]:
    """Los códigos literales (los dos de un ``a if … else b``) o, si es una f-string que empieza con texto fijo, su
    familia (``late-*``)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant):
        return [f"{node.values[0].value}*"]
    if isinstance(node, ast.IfExp):
        a, b = _code(node.body), _code(node.orelse)
        return a + b if a is not None and b is not None else None
    return None


def _is_log(fn: ast.expr) -> bool:
    """``log.add`` o ``self.log.add`` (``EventLog``), no ``needs.add`` ni ``set.add``."""
    if not (isinstance(fn, ast.Attribute) and fn.attr == "add"):
        return False
    v = fn.value
    return (isinstance(v, ast.Name) and v.id == "log") or (isinstance(v, ast.Attribute) and v.attr == "log")


def logged_codes(relevant_only: bool = True) -> dict[str, list[str]]:
    """{código o familia: [archivo:línea]} de lo que registra el pipeline (por omisión, avisos y peores)."""
    out: dict[str, list[str]] = {}
    for base in SCAN:
        for f in sorted((PY / base).rglob("*.py")):
            rel = f.relative_to(PY).as_posix()
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.Call):
                    continue
                if _is_log(node.func) and len(node.args) == 5:  # add(severidad, fuente, etapa, código, mensaje)
                    sev, code = node.args[0], node.args[3]
                elif isinstance(node.func, ast.Name) and node.func.id == "Issue" and len(node.args) >= 2:
                    sev, code = node.args[0], node.args[1]  # validación del informe técnico (reports.py)
                elif (isinstance(node.func, ast.Attribute) and node.func.attr == "append"
                      and isinstance(node.func.value, ast.Name) and node.func.value.id == "events"
                      and len(node.args) == 1 and isinstance(node.args[0], ast.Tuple) and len(node.args[0].elts) == 3):
                    # (etapa, código, mensaje) de un lector: acquire() lo registra como advertencia.
                    sev, code = ast.Constant("warning"), node.args[0].elts[1]
                else:
                    continue
                sevs = _severities(sev)
                if relevant_only and sevs is not None and not sevs & RELEVANT:
                    continue
                c = _code(code)
                if c is None:
                    assert (rel, ast.unparse(code)) in DYNAMIC, f"{rel}:{node.lineno}: código no literal «{ast.unparse(code)}»"
                    continue
                for one in c:
                    out.setdefault(one, []).append(f"{rel}:{node.lineno}")
    return out


def documented() -> set[str]:
    """Códigos de la primera columna de la tabla de docs/operaciones.md (``stale-*`` y similares son familias)."""
    codes: set[str] = set()
    for line in (DOCS / "operaciones.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("| `"):
            codes |= set(re.findall(r"`([a-z0-9<>*-]+)`", line.split("|")[1]))
    return codes


def covered(code: str, docs: set[str]) -> bool:
    return code in docs or any(d.endswith("*") and code.startswith(d[:-1]) for d in docs)


def test_the_scanner_finds_the_pipeline_codes():
    """Sin esto, un cambio en la forma de las llamadas dejaría pasar la prueba de abajo sin revisar nada."""
    found = logged_codes()
    assert {"unreachable", "no-data", "relay-goal-missed", "manual-download-needed", "informe-unread",
            "informe-probability-sum", "late-*", "stale-*", "bsobp-overdue"} <= set(found), sorted(found)
    assert "relay-ok" not in found and "probe-found" not in found  # informativos


def test_every_warning_or_error_code_has_a_row_in_operaciones():
    docs = documented()
    missing = {c: where for c, where in logged_codes().items() if c not in IGNORE and not covered(c, docs)}
    assert not missing, ("códigos que abren un issue sin fila en la tabla de docs/operaciones.md (agregarla con "
                         f"qué hacer): {json.dumps(missing, ensure_ascii=False, indent=1)}")


def test_operaciones_lists_no_code_the_pipeline_no_longer_logs():
    logged = set(logged_codes(relevant_only=False))
    stale = sorted(d for d in documented() if "*" not in d and "<" not in d and not covered(d, logged))
    assert not stale, f"filas de docs/operaciones.md con códigos que el código ya no registra: {stale}"


def test_readme_links_every_doc():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    linked = set(re.findall(r"\]\(docs/([\w.-]+\.md)(?:#[^)]*)?\)", readme))
    missing = sorted(p.name for p in DOCS.glob("*.md") if p.name not in linked)
    assert not missing, f"README.md no enlaza: {missing}"


def test_enfen_and_imarpe_access_as_the_code_and_registry_say():
    """El catálogo y las limitaciones daban al IMARPE por inalcanzable, al recolector del Perú por fuente de los PDF
    de la DHN (que le pide verificación humana) y decían que se sondean dos números; el sitio daba como único
    respaldo del comunicado el Internet Archive."""
    from enso import observatory as O

    cat = (DOCS / "catalogo-fuentes.md").read_text(encoding="utf-8")
    lim = (DOCS / "limitaciones.md").read_text(encoding="utf-8")
    app = (ROOT / "public" / "assets" / "js" / "app.js").read_text(encoding="utf-8")
    for text, phrase in ((cat, "| IMARPE | HTTP 403 (bloqueo) | No disponible |"), (cat, "también descarga esos PDF"),
                         (cat, "PDF por el recolector del Perú"), (cat, "Se sondean los dos números siguientes"),
                         (lim, "ANA e IMARPE no responden"), (app, "se usa la copia del Internet Archive y se indica")):
        assert phrase not in text, phrase
    reg = json.loads((ROOT / "registry" / "sources.json").read_text(encoding="utf-8"))
    repo = [s for s in reg["sources"] if s["url"].startswith("https://repositorio.imarpe.gob.pe/")]
    assert repo, "el registro ya no tiene las búsquedas del repositorio del IMARPE: revisar estos documentos"
    # Quién pide el repositorio lo decide la sonda de cada lunes: los documentos no lo dan por alcanzable desde
    # Actions si el registro no se lo asigna (ni al revés).
    on_actions = any("actions" in s["channels"] for s in repo)
    flat = {name: " ".join(text.split()) for name, text in (("catalogo-fuentes.md", cat), ("limitaciones.md", lim))}
    reachable = ("su repositorio, a GitHub Actions", "API (`/server/api`) responde a GitHub Actions")
    unreachable = ("el repositorio no responde a GitHub Actions", "API (`/server/api`) no responde a GitHub Actions")
    for name, text in flat.items():
        wrong = [p for p in (unreachable if on_actions else reachable) if p in text]
        assert not wrong, f"{name} dice «{wrong[0]}», pero el registro {'sí' if on_actions else 'no'} asigna el repositorio a Actions"
    for text in (cat, lim):
        assert not re.search(r"IMARPE[^|\n]*\|[^|\n]*\|\s*No disponible", text)
    if "imarpe_repo" in (PY / "enso" / "observatory.py").read_text(encoding="utf-8"):
        for name, text in (("catalogo-fuentes.md", cat), ("limitaciones.md", lim), ("app.js", app)):
            assert "repositorio del IMARPE" in text, name
    assert f"hasta {O.PROBE_AHEAD} números" in cat
    # La regla está en el lector (``_enfen_latest``); ``enfen_latest`` solo agrega la incidencia del repositorio.
    assert "PROBE_AHEAD" in O._enfen_latest.__doc__ and "dos números siguientes" not in O._enfen_latest.__doc__


def test_cloudflare_guide_names_every_function_route_and_binding():
    guide = (DOCS / "despliegue-cloudflare.md").read_text(encoding="utf-8")
    fn = ROOT / "functions"
    names = {n for f in fn.rglob("*.js") for n in re.findall(r"\benv\.([A-Z][A-Z0-9_]*)", f.read_text(encoding="utf-8"))}
    assert {"GEO_DB", "GEO_USERS", "DOCS_GITHUB_TOKEN"} <= names
    assert not sorted(n for n in names if f"`{n}`" not in guide), "vínculos o secretos sin nombrar en la guía"
    routes = sorted(p.name for p in (fn / "api").iterdir() if p.is_dir())
    assert routes and not [r for r in routes if f"`/api/{r}/*`" not in guide], routes
