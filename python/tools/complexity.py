"""Techo de complejidad ciclomática (McCabe) para todo el Python y el JavaScript del repositorio, con trinquete.

Cada función nueva debe tener complejidad <= ``CEILING`` (10, el límite de NIST SP 500-235 «Structured Testing»,
§2.5). Las que ya lo pasaban cuando se puso el techo están en ``config/complexity-baseline.json`` con su número de
entonces, y ese número solo puede bajar:

* una función nueva (o que antes cumplía) por encima del techo falla;
* una función de la lista que creció falla;
* una que bajó, quedó dentro del techo o ya no existe también falla, hasta que ``--update`` baje o borre su línea
  (si no, la lista guardaría un margen que otra edición podría volver a gastar sin que nadie lo vea).

La medida es v(G) = 1 + decisiones, contadas como manda NIST SP 500-235 §4.1: cada operador booleano con
cortocircuito suma uno (``and``/``or``; ``&&``, ``||``, ``??``), igual que ``if``/``elif``, cada bucle, cada
``except``/``catch``, ``assert``, la expresión condicional, cada ``for`` e ``if`` de una comprensión, cada ``case``
cuyo patrón puede no casar (no ``_`` ni una captura) y cada guarda. Las funciones anidadas y las lambdas se miden aparte (como hace ESLint con las funciones
flecha); ``else``, ``finally`` y ``with`` no suman (no son decisiones). Python: ``ast`` de la biblioteca estándar
(sin dependencias: ``ruff`` C901/mccabe no cuenta ``and``/``or`` ni las comprensiones, y ``radon`` pierde los
métodos de una clase definida dentro de una función; ver docs/complejidad.md). JavaScript: la regla ``complexity``
de ESLint (variante clásica) desde ``scripts/lint/complexity.mjs``, con las versiones fijadas en
``scripts/lint/package-lock.json``.

Uso (desde python/):
    python -m tools.complexity                 # revisa; 0 = bien, 1 = algo que corregir, 2 = no pudo medir
    python -m tools.complexity --update        # baja o borra líneas de la lista (nunca agrega ni sube)
    python -m tools.complexity --rebaseline    # reescribe la lista entera (solo al cambiar de versión de ESLint
                                               # o de la regla de Python; el diff se justifica en el PR)
    python -m tools.complexity --python-only   # sin Node ni ESLint (las líneas de JS de la lista no se juzgan)
    python -m tools.complexity --report 20     # además, las 20 funciones más complejas

El JavaScript necesita ``npm ci --prefix scripts/lint`` (una vez). En GitHub Actions, el job «lint» de ci.yml.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CEILING = 10
#: Versión de la regla de conteo de Python de este archivo: se sube al cambiar qué cuenta, y obliga a ``--rebaseline``.
PY_METRIC = "ast-nist-2"
BASELINE_REL = "config/complexity-baseline.json"
JS_TOOL_REL = "scripts/lint"
PY_SUFFIXES = (".py",)
JS_SUFFIXES = (".js", ".mjs", ".cjs")
#: Código generado o de prueba congelada: no se escribe a mano (``n8n/dist`` sale de ``n8n/build.mjs``).
EXCLUDED_PREFIXES = ("n8n/dist/", "python/tests/fixtures/")
SKIPPED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache", ".ruff_cache", ".wrangler"}
#: Cuerpos de nodos Code de n8n: n8n los corre dentro de una función, así que se miden como una.
N8N_CODE_PREFIX = "n8n/nodes/"
REBASELINE_SHOWN = 40
FIX_HINT = (
    "Divida la función: saque cada rama o caso a una función con nombre, use una tabla (dict u objeto) en vez de "
    "una cadena de if/elif, o devuelva antes (cláusulas de guarda). Ver docs/complejidad.md."
)


class ToolError(RuntimeError):
    """No se pudo medir (falta Node o ESLint, un archivo no se analiza, la lista está rota): sale con 2."""


@dataclass(frozen=True)
class Fn:
    path: str
    name: str
    line: int
    score: int

    @property
    def key(self) -> str:
        return f"{self.path}::{self.name}"


# --------------------------------------------------------------------------------------------------- medición: Python

_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
_ONE = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.Assert, ast.IfExp)


def _irrefutable(p: ast.pattern) -> bool:
    """Un patrón que siempre casa (``_``, ``x``, ``(_ as y)``): probarlo no es una decisión."""
    return isinstance(p, ast.MatchAs) and (p.pattern is None or _irrefutable(p.pattern))


def _decisions(node: ast.AST) -> int:
    """Lo que suma un nodo por sí mismo (sin contar sus hijos)."""
    if isinstance(node, _ONE):
        return 1
    if isinstance(node, ast.BoolOp):
        return len(node.values) - 1
    if isinstance(node, ast.comprehension):
        return 1 + len(node.ifs)
    if isinstance(node, ast.Match):
        # Cada caso cuyo patrón puede no casar es una decisión; el comodín o una captura no deciden nada (con
        # guarda, la decisión es solo la guarda, que se cuenta en su match_case). Python rechaza un patrón
        # irrefutable sin guarda que no sea el último, así que esto cubre el «case _:» final.
        return sum(not _irrefutable(c.pattern) for c in node.cases)
    if isinstance(node, ast.match_case):
        return 1 if node.guard is not None else 0
    if isinstance(node, ast.MatchOr):
        return len(node.patterns) - 1
    return 0


def _evaluated_where_defined(node: ast.AST) -> list[ast.AST]:
    """Lo que una función o clase anidada evalúa en el ámbito que la contiene: decoradores, valores por omisión, bases."""
    if isinstance(node, ast.ClassDef):
        return [*node.decorator_list, *node.bases, *node.keywords]
    args = node.args
    out = [*args.defaults, *(d for d in args.kw_defaults if d is not None)]
    return out if isinstance(node, ast.Lambda) else [*node.decorator_list, *out]


def _body(fn: ast.AST) -> list[ast.AST]:
    return [fn.body] if isinstance(fn, ast.Lambda) else list(fn.body)


def py_score(fn: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> int:
    """v(G) de una función: 1 + decisiones de su propio cuerpo (las funciones y clases anidadas no cuentan aquí)."""
    total, stack = 1, _body(fn)
    while stack:
        node = stack.pop()
        if isinstance(node, _SCOPES):
            stack.extend(_evaluated_where_defined(node))
            continue
        total += _decisions(node)
        stack.extend(ast.iter_child_nodes(node))
    return total


def _py_units(tree: ast.AST):
    """(nombre calificado, nodo) de cada función, en orden de fuente: Clase.metodo, externa.interna, f.<lambda>."""
    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                name = prefix + ("<lambda>" if isinstance(child, ast.Lambda) else child.name)
                yield name, child
                yield from walk(child, name + ".")
            elif isinstance(child, ast.ClassDef):
                yield from walk(child, prefix + child.name + ".")
            else:
                yield from walk(child, prefix)
    yield from walk(tree, "")


def measure_python(root: Path, paths: list[str]) -> list[Fn]:
    out, errors = [], []
    for rel in paths:
        try:
            tree = ast.parse((root / rel).read_bytes(), filename=rel)
        except (SyntaxError, ValueError) as e:
            errors.append(f"{rel}:{getattr(e, 'lineno', 1) or 1}: no se pudo analizar: {e}")
            continue
        units = sorted(_py_units(tree), key=lambda u: (u[1].lineno, u[1].col_offset))
        out.extend(Fn(rel, name, node.lineno, py_score(node)) for name, node in units)
    if errors:
        raise ToolError("Python que no se pudo medir:\n  " + "\n  ".join(errors))
    return out


# ----------------------------------------------------------------------------------------------- medición: JavaScript

def js_versions(root: Path) -> dict[str, str]:
    mods = root / JS_TOOL_REL / "node_modules"
    try:
        return {m: json.loads((mods / m / "package.json").read_text(encoding="utf-8"))["version"] for m in ("eslint", "espree")}
    except (OSError, ValueError, KeyError) as e:
        raise ToolError(
            f"ESLint no está instalado en {JS_TOOL_REL}/node_modules ({e}). Instálelo con las versiones fijadas:\n"
            f"  npm ci --prefix {JS_TOOL_REL}\n"
            "o mida solo Python con --python-only (las líneas de JavaScript de la lista no se juzgan)."
        ) from None


def measure_js(root: Path, paths: list[str]) -> list[Fn]:
    node = shutil.which("node")
    if not node:
        raise ToolError("No se encontró «node» (Node 22 o más nuevo) en el PATH; o use --python-only.")
    js_versions(root)
    files = [{"path": p, "wrap": p.startswith(N8N_CODE_PREFIX)} for p in paths]
    proc = subprocess.run([node, str(root / JS_TOOL_REL / "complexity.mjs")], cwd=root, input=json.dumps(files),
                          capture_output=True, text=True, encoding="utf-8", timeout=600)
    if proc.returncode:
        raise ToolError(f"scripts/lint/complexity.mjs salió con {proc.returncode}:\n{proc.stderr.strip()[-3000:]}")
    try:
        res = json.loads(proc.stdout)
    except ValueError as e:
        raise ToolError(f"scripts/lint/complexity.mjs no devolvió JSON ({e}): {proc.stdout[:500]!r}") from None
    if res["errors"]:
        lines = [f"{e['path']}:{e['line']}: {e['message']}" for e in res["errors"]]
        raise ToolError("JavaScript que no se pudo medir:\n  " + "\n  ".join(lines))
    fns = sorted(res["functions"], key=lambda f: (f["path"], f["line"]))
    return [Fn(f["path"], f["name"], max(1, f["line"]), f["score"]) for f in fns]


# ----------------------------------------------------------------------------------------------------------- archivos

def _git_files(root: Path) -> list[str] | None:
    if not (root / ".git").exists():
        return None
    proc = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                          capture_output=True)
    if proc.returncode:
        raise ToolError(f"git ls-files falló: {proc.stderr.decode('utf-8', 'replace').strip()}")
    return [p for p in proc.stdout.decode("utf-8").split("\0") if p and (root / p).is_file()]


def _walk_files(root: Path) -> list[str]:
    out = []
    for d, dirs, names in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in SKIPPED_DIRS)
        out.extend(Path(d, n).relative_to(root).as_posix() for n in names)
    return out


def source_files(root: Path) -> tuple[list[str], list[str]]:
    """(Python, JavaScript) del repositorio: lo que sigue git (también lo nuevo sin commit), o todo el árbol sin git."""
    files = _git_files(root)
    files = _walk_files(root) if files is None else files
    keep = sorted(p for p in files if not p.startswith(EXCLUDED_PREFIXES) and "node_modules/" not in p)
    return [p for p in keep if p.endswith(PY_SUFFIXES)], [p for p in keep if p.endswith(JS_SUFFIXES)]


def number_duplicates(fns: list[Fn]) -> list[Fn]:
    """Dos funciones del mismo archivo con el mismo nombre (un getter y su setter, dos callbacks de map): «#2», «#3»."""
    seen: dict[str, int] = {}
    out = []
    for f in fns:
        n = seen[f.key] = seen.get(f.key, 0) + 1
        out.append(f if n == 1 else Fn(f.path, f"{f.name} #{n}", f.line, f.score))
    return out


@dataclass
class Measurement:
    fns: list[Fn]
    tools: dict[str, str]
    langs: tuple[str, ...]


def measure(root: Path, python_only: bool = False) -> Measurement:
    py, js = source_files(root)
    fns = number_duplicates(measure_python(root, py))
    tools = {"python": PY_METRIC}
    if not python_only:
        tools.update(js_versions(root))
        fns += number_duplicates(measure_js(root, js))
    return Measurement(fns, tools, ("py",) if python_only else ("py", "js"))


def lang_of(key: str) -> str:
    return "js" if key.split("::", 1)[0].endswith(JS_SUFFIXES) else "py"


# -------------------------------------------------------------------------------------------------------------- lista

def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ToolError(f"No existe {path}. Créela con: python -m tools.complexity --rebaseline") from None
    except ValueError as e:
        raise ToolError(f"{path} no es JSON válido: {e}") from None


def load_baseline(path: Path) -> dict:
    data = _read_json(path)
    problems = _baseline_problems(data)
    if problems:
        raise ToolError(f"{path} está mal formada:\n  " + "\n  ".join(problems))
    return data


def _baseline_problems(data) -> list[str]:
    if not isinstance(data, dict) or not isinstance(data.get("functions"), dict):
        return ["falta el objeto «functions»"]
    out = []
    if data.get("ceiling") != CEILING:
        out.append(f"«ceiling» es {data.get('ceiling')!r} y el techo del código es {CEILING}: se cambia en el código "
                   "(tools/complexity.py) y luego --rebaseline, no a mano en la lista")
    for k, v in data["functions"].items():
        if "::" not in k:
            out.append(f"{k!r}: la clave debe ser «ruta::función»")
        if not isinstance(v, int) or isinstance(v, bool) or v <= CEILING:
            out.append(f"{k}: {v!r} no es un entero mayor que el techo ({CEILING}); las que cumplen no van en la lista")
    if list(data["functions"]) != sorted(data["functions"]):
        out.append("las claves no están ordenadas (escriba la lista con --update o --rebaseline, no a mano)")
    return out


def write_baseline(path: Path, functions: dict[str, int], tools: dict[str, str]) -> None:
    data = {
        "_doc": ("Funciones que ya pasaban el techo de complejidad ciclomática cuando se puso, con su número: solo "
                 "puede bajar. La escribe python -m tools.complexity --update (desde python/); ver docs/complejidad.md."),
        "ceiling": CEILING,
        "tools": dict(sorted(tools.items())),
        "functions": dict(sorted(functions.items())),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------------------------------------- veredicto

@dataclass(frozen=True)
class Finding:
    kind: str  # new | grown | lowered | fixed | gone
    key: str
    path: str
    line: int
    message: str

    @property
    def blocking_update(self) -> bool:
        """Lo que ``--update`` no puede resolver: solo se arregla cambiando el código."""
        return self.kind in ("new", "grown")


def _renames(gone: dict[str, int], new: dict[str, Fn]) -> dict[str, str]:
    """Funciones de la lista que solo cambiaron de nombre: la misma ruta y el mismo número, sin otra candidata."""
    out = {}
    for g, score in gone.items():
        path = g.split("::", 1)[0]
        cands = [k for k, f in new.items() if f.path == path and f.score == score]
        rivals = [x for x, s in gone.items() if x.split("::", 1)[0] == path and s == score]
        if len(cands) == 1 and len(rivals) == 1:
            out[g] = cands[0]
    return out


def judge(m: Measurement, baseline: dict[str, int]) -> tuple[list[Finding], dict[str, str]]:
    """Hallazgos (ordenados por archivo y línea) y los renombres que ``--update`` puede trasladar."""
    current = {f.key: f for f in m.fns}
    base = _judged(baseline, m)
    new = _new_offenders(current, base)
    gone = {k: v for k, v in base.items() if k not in current}
    renames = _renames(gone, new)
    found = [_new_finding(f, renames) for f in new.values()]
    found += [_gone_finding(k, b, renames) for k, b in gone.items()]
    found += [_drift_finding(current[k], b) for k, b in base.items() if k in current]
    return sorted(filter(None, found), key=lambda x: (x.path, x.line, x.key)), renames


def _new_offenders(current: dict[str, Fn], base: dict[str, int]) -> dict[str, Fn]:
    return {k: f for k, f in current.items() if f.score > CEILING and k not in base}


def _judged(baseline: dict[str, int], m: Measurement) -> dict[str, int]:
    """Las líneas de la lista de los lenguajes medidos (con --python-only, las de JavaScript no se juzgan)."""
    return {k: v for k, v in baseline.items() if lang_of(k) in m.langs}


def _new_finding(f: Fn, renames: dict[str, str]) -> Finding:
    was = next((g for g, n in renames.items() if n == f.key), None)
    if was:
        return Finding("new", f.key, f.path, f.line, (
            f"{f.path}:{f.line} {f.name}: complejidad {f.score} > techo {CEILING}. Parece la función «{was.split('::')[1]}» "
            f"de la lista con otro nombre (mismo archivo, mismo número): --update traslada la línea."))
    return Finding("new", f.key, f.path, f.line, (
        f"{f.path}:{f.line} {f.name}: complejidad {f.score} > techo {CEILING} (función nueva o que antes cumplía; "
        f"la lista no admite funciones nuevas). {FIX_HINT}"))


def _gone_finding(key: str, b: int, renames: dict[str, str]) -> Finding:
    path, name = key.split("::", 1)
    where = f" (¿ahora «{renames[key].split('::', 1)[1]}»?)" if key in renames else ""
    return Finding("gone", key, path, 0, (
        f"{path} {name}: está en la lista ({b}) y ya no existe{where}. Bórrela con --update."))


def _drift_finding(f: Fn, b: int) -> Finding | None:
    if f.score > b:
        return Finding("grown", f.key, f.path, f.line, (
            f"{f.path}:{f.line} {f.name}: complejidad {f.score}, creció desde {b} (lista) y el techo es {CEILING}. "
            f"Una función de la lista no puede crecer: deje el cambio en {b} o menos. {FIX_HINT}"))
    if f.score <= CEILING:
        return Finding("fixed", f.key, f.path, f.line, (
            f"{f.path}:{f.line} {f.name}: complejidad {f.score}, ya dentro del techo {CEILING} (la lista dice {b}). "
            "Bien: bórrela de la lista con --update."))
    if f.score < b:
        return Finding("lowered", f.key, f.path, f.line, (
            f"{f.path}:{f.line} {f.name}: complejidad {f.score}, bajó desde {b} (techo {CEILING}). "
            f"Bien: baje la lista con --update para que no se pueda volver a subir."))
    return None


def updated(baseline: dict[str, int], m: Measurement, renames: dict[str, str]) -> dict[str, int]:
    """La lista con cada función bajada a su número actual, sin las que cumplen o no existen, y con los renombres."""
    current = {f.key: f.score for f in m.fns}
    out = {}
    for k, b in baseline.items():
        if lang_of(k) not in m.langs:
            out[k] = b
            continue
        k2 = renames.get(k, k)
        score = current.get(k2)
        if score is not None and score > CEILING:
            out[k2] = min(b, score)
    return out


# ---------------------------------------------------------------------------------------------------------- interfaz

def _annotate(f: Finding) -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        line = f",line={f.line}" if f.line else ""
        msg = f.message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::error file={f.path}{line},title=complexity ({f.kind})::{msg}")


def _print_findings(found: list[Finding]) -> None:
    labels = {"new": "NUEVA", "grown": "CRECIÓ", "lowered": "BAJÓ", "fixed": "CUMPLE", "gone": "NO EXISTE"}
    for f in found:
        print(f"[{labels[f.kind]}] {f.message}", file=sys.stderr)
        _annotate(f)


def _report(m: Measurement, n: int) -> None:
    worst = sorted(m.fns, key=lambda f: (-f.score, f.key))[:n]
    print(f"Las {len(worst)} funciones más complejas:")
    for f in worst:
        print(f"  {f.score:4d}  {f.path}:{f.line} {f.name}")


def _summary(m: Measurement, baseline: dict[str, int]) -> str:
    by = {lang: [f for f in m.fns if lang_of(f.key) == lang] for lang in m.langs}
    parts = ", ".join(f"{len(v)} de {'Python' if k == 'py' else 'JavaScript'}" for k, v in by.items())
    over = sum(f.score > CEILING for f in m.fns)
    return (f"{len(m.fns)} funciones medidas ({parts}); {over} pasan el techo {CEILING}, todas en la lista "
            f"({len(baseline)} líneas) y ninguna creció. Herramientas: {m.tools}.")


def _tool_mismatch(saved: dict, m: Measurement) -> list[str]:
    out = []
    for name, version in m.tools.items():
        if saved.get(name) != version:
            out.append(f"{name}: la lista se midió con {saved.get(name)!r} y ahora hay {version!r}")
    return out


def _run_update(path: Path, data: dict, m: Measurement, found: list[Finding], renames: dict[str, str]) -> int:
    blocking = [f for f in found if f.blocking_update and f.key not in renames.values()]
    if blocking:
        _print_findings(blocking)
        print(f"\n--update no agrega ni sube funciones: corrija las {len(blocking)} de arriba. Nada se escribió.",
              file=sys.stderr)
        return 1
    new = updated(data["functions"], m, renames)
    write_baseline(path, new, {**data.get("tools", {}), **m.tools})
    print(f"{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}: {len(data['functions'])} -> {len(new)} "
          f"líneas, suma {sum(data['functions'].values())} -> {sum(new.values())}.")
    return 0


def _run_rebaseline(path: Path, m: Measurement, old: dict[str, int], old_tools: dict[str, str]) -> int:
    new = {f.key: f.score for f in m.fns if f.score > CEILING}
    keep = {k: v for k, v in old.items() if lang_of(k) not in m.langs}
    # Con --python-only las líneas de JavaScript se conservan, y con ellas las versiones de ESLint con que se midieron:
    # sin eso, la siguiente revisión completa saldría con 2 («la lista se midió con None»).
    tools = m.tools if "js" in m.langs else {**old_tools, **m.tools}
    write_baseline(path, {**keep, **new}, tools)
    _print_rebaseline(len(keep) + len(new), old, new)
    return 0


def _print_rebaseline(total: int, old: dict[str, int], new: dict[str, int]) -> None:
    added = sorted(set(new) - set(old))
    raised = sorted(k for k in new if k in old and new[k] > old[k])
    print(f"Lista reescrita: {total} líneas. Agregadas {len(added)}, subidas {len(raised)}: "
          "justifíquelas en el PR (solo valen por un cambio de versión de la herramienta o de la regla).")
    shown = (added + raised)[:REBASELINE_SHOWN]
    for k in shown:
        print(f"  {k}: {old.get(k, '-')} -> {new[k]}")
    if len(added + raised) > len(shown):
        print(f"  … y {len(added + raised) - len(shown)} más (git diff {BASELINE_REL})")


def _rebaseline_source(path: Path) -> dict:
    """La lista anterior sin validar: --rebaseline es justo lo que arregla una lista de otro techo (CEILING cambió)."""
    old = _read_json(path) if path.exists() else {}
    return {"functions": old.get("functions") or {}, "tools": old.get("tools") or {}}


def run(root: Path = ROOT, *, update: bool = False, rebaseline: bool = False, python_only: bool = False,
        report: int = 0, baseline_path: Path | None = None) -> int:
    path = baseline_path or root / BASELINE_REL
    m = measure(root, python_only=python_only)
    if report:
        _report(m, report)
    if rebaseline:
        old = _rebaseline_source(path)
        return _run_rebaseline(path, m, old["functions"], old["tools"])
    data = load_baseline(path)
    mismatch = _tool_mismatch(data.get("tools", {}), m)
    if mismatch:
        raise ToolError("La lista se midió con otra versión de la herramienta, y los números no se comparan:\n  "
                        + "\n  ".join(mismatch)
                        + "\nSi la subida es a propósito: python -m tools.complexity --rebaseline, y justifique el diff.")
    found, renames = judge(m, data["functions"])
    if update:
        return _run_update(path, data, m, found, renames)
    if found:
        _print_findings(found)
        fixable = all(not f.blocking_update for f in found)
        tail = "Todo se resuelve con: python -m tools.complexity --update" if fixable else FIX_HINT
        print(f"\n{len(found)} problema(s) de complejidad. {tail}", file=sys.stderr)
        return 1
    print(_summary(m, data["functions"]))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--update", action="store_true", help="baja o borra líneas de la lista (nunca agrega ni sube)")
    mode.add_argument("--rebaseline", action="store_true", help="reescribe la lista entera (cambio de herramienta)")
    ap.add_argument("--python-only", action="store_true", help="sin Node ni ESLint")
    ap.add_argument("--report", type=int, default=0, metavar="N", help="muestra las N funciones más complejas")
    ap.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    try:
        return run(args.root.resolve(), update=args.update, rebaseline=args.rebaseline,
                   python_only=args.python_only, report=args.report)
    except ToolError as e:
        print(f"complexity: no se pudo medir: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
