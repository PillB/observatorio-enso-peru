"""Techo de complejidad ciclomática con trinquete (``tools.complexity``, docs/complejidad.md).

Las pruebas no comparan la herramienta consigo misma: la medida se compara con valores contados a mano sobre el
grafo de control de cada fragmento (NIST SP 500-235 §4.1) y, en el repositorio entero, con radon donde las dos
definiciones coinciden; el trinquete se prueba en copias temporales donde se agrega, agranda, achica, renombra o
borra una función de verdad y se mira la salida, el código de salida y el archivo de la lista.

El JavaScript necesita ``npm ci --prefix scripts/lint``. Sin eso, sus pruebas se saltan con el motivo a la vista,
salvo con ``COMPLEXITY_REQUIRE_JS=1`` (el job «lint» de ci.yml), donde fallan.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import textwrap
from pathlib import Path

import pytest

from tools import complexity as C

REPO = C.ROOT
REQUIRE_JS = os.environ.get("COMPLEXITY_REQUIRE_JS") == "1"


def _js_ready() -> str | None:
    """Motivo por el que no se puede medir JavaScript aquí, o None."""
    if not shutil.which("node"):
        return "no hay node en el PATH"
    try:
        C.js_versions(REPO)
    except C.ToolError:
        return "ESLint no está instalado (npm ci --prefix scripts/lint)"
    return None


def need_js():
    why = _js_ready()
    if why and REQUIRE_JS:
        pytest.fail(f"COMPLEXITY_REQUIRE_JS=1 y {why}")
    if why:
        pytest.skip(why)


def ifs(name: str, score: int, indent: str = "") -> str:
    """Una función con v(G) = ``score`` exacto: ``score - 1`` if independientes (cada uno, una decisión)."""
    body = "".join(f"{indent}    if x == {i}:\n{indent}        return {i}\n" for i in range(score - 1))
    return f"{indent}def {name}(x):\n{body}{indent}    return -1\n"


def scores_py(src: str) -> dict[str, int]:
    tree = ast.parse(textwrap.dedent(src))
    return {f.name: f.score for f in C.number_duplicates(
        [C.Fn("m.py", name, node.lineno, C.py_score(node)) for name, node in C._py_units(tree)])}


# ------------------------------------------------------------------------------------------------ la medida: Python

# Cada valor sale de contar las decisiones del grafo de control a mano: v(G) = decisiones + 1 (McCabe 1976).
HAND_COUNTED_PY = [
    # if (1) + and (1) + or (1): los dos operadores con cortocircuito son ramas (NIST SP 500-235 §4.1).
    ("def f(a, b, c):\n    if a and b or c:\n        return 1\n    return 0\n", {"f": 4}),
    # for de la comprensión (1) + su if (1).
    ("def f(xs):\n    return [x for x in xs if x]\n", {"f": 3}),
    # Dos generadores con dos filtros: 2 + 2.
    ("def f(a, b):\n    return {(x, y) for x in a if x for y in b if y}\n", {"f": 5}),
    ("def f(a):\n    return 1 if a else 2\n", {"f": 2}),
    # La función anidada es otra función: su if no cuenta en la externa.
    ("def f(a):\n    def g(b):\n        if b:\n            return 1\n    if a:\n        return g(a)\n",
     {"f": 2, "f.g": 2}),
    # Dos except (2); else y finally no son decisiones.
    ("def f(a):\n    try:\n        g(a)\n    except ValueError:\n        pass\n    except KeyError:\n        pass\n"
     "    else:\n        pass\n    finally:\n        pass\n", {"f": 3}),
    # Tres casos con comodín final: dos decisiones.
    ("def f(x):\n    match x:\n        case 1:\n            return 1\n        case 2:\n            return 2\n"
     "        case _:\n            return 3\n", {"f": 3}),
    # «1 | 2» prueba dos patrones (dos decisiones); «y» es una captura, que siempre casa: ahí solo decide la guarda.
    # Sin comodín final no hay caso por omisión que descontar. Total 3 decisiones.
    ("def f(x):\n    match x:\n        case 1 | 2:\n            return 1\n        case y if y > 5:\n            return 2\n",
     {"f": 4}),
    # El comodín con guarda tampoco prueba nada por sí mismo: case 1 (1) + guarda (1).
    ("def f(x, ok):\n    match x:\n        case 1:\n            return 1\n        case _ if ok:\n            return 2\n",
     {"f": 3}),
    # Las bases y los argumentos de una clase se evalúan donde se define la clase: el ternario es de f.
    ("def f(a):\n    class K(A if a else B, metaclass=M or N):\n        pass\n    return K\n", {"f": 3}),
    # for (1) + while (1); el else del for no decide nada.
    ("def f(xs):\n    for x in xs:\n        pass\n    else:\n        pass\n    while xs:\n        xs.pop()\n", {"f": 3}),
    ("def f(a):\n    with open(a) as fh:\n        return fh.read()\n", {"f": 1}),
    # assert es un raise condicional (1), y el and de adentro otra rama (1).
    ("def f(a, b):\n    assert a and b\n", {"f": 3}),
    # La lambda es una función aparte; el valor por omisión y el decorador se evalúan donde se define: en f.
    ("def f(xs, d=None):\n    @deco(a or b)\n    def g(k=x or y):\n        return k\n"
     "    return sorted(xs, key=lambda v: v or 0)\n", {"f": 3, "f.g": 1, "f.<lambda>": 2}),
    # Métodos de una clase definida dentro de una función (radon 6.0.1 no los ve).
    ("def f():\n    class K:\n        def m(self, x):\n            if x:\n                return 1\n    return K\n",
     {"f": 1, "f.K.m": 2}),
    # Getter y setter con el mismo nombre: el segundo lleva «#2».
    ("class P:\n    @property\n    def x(self):\n        return 1\n    @x.setter\n    def x(self, v):\n"
     "        if v:\n            pass\n", {"P.x": 1, "P.x #2": 2}),
    ("async def f(xs):\n    async for x in xs:\n        if x:\n            break\n", {"f": 3}),
]


@pytest.mark.parametrize("src,expected", HAND_COUNTED_PY, ids=[f"py{i}" for i in range(len(HAND_COUNTED_PY))])
def test_python_complexity_is_the_hand_counted_cyclomatic_number(src, expected):
    assert scores_py(src) == expected


#: Lo que radon 6.0.1 cuenta distinto a propósito: suma el else de bucles y try, no mira dentro de assert, mete las
#: lambdas en la función que las contiene, cuenta match a su manera y no ve los métodos de clases dentro de funciones.
RADON_DIVERGES = (ast.Assert, ast.Lambda, ast.Match, ast.ClassDef)


def _own_nodes(fn):
    stack = list(fn.body)
    while stack:
        n = stack.pop()
        yield n
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stack.extend(ast.iter_child_nodes(n))


def _radon_comparable(fn) -> bool:
    loops = (ast.For, ast.AsyncFor, ast.While, ast.Try)
    return not any(isinstance(n, RADON_DIVERGES) or (isinstance(n, loops) and n.orelse) for n in _own_nodes(fn))


def _radon_functions(R, text: str):
    """Cada función de radon (también métodos y funciones anidadas), una sola vez."""
    stack = [b for b in R.cc_visit(text) if not getattr(b, "is_method", False)]
    while stack:
        b = stack.pop()
        if hasattr(b, "closures"):
            stack.extend(b.closures)
            yield b
        else:
            stack.extend(b.methods)


def _comparable_pairs(R, text: str):
    """(función de radon, nodo de ast) de cada función donde las dos definiciones coinciden."""
    nodes = {n.lineno: n for n in ast.walk(ast.parse(text)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return [(b, nodes[b.lineno]) for b in _radon_functions(R, text) if _radon_comparable(nodes[b.lineno])]


def _radon():
    if REQUIRE_JS or os.environ.get("CI"):
        import radon.complexity as R  # en CI está en requirements-dev.txt: si falta, que falle

        return R
    return pytest.importorskip("radon.complexity")


def test_python_complexity_agrees_with_radon_wherever_both_definitions_coincide():
    """Oráculo independiente: radon 6.0.1 en todo el Python del repositorio, fuera de ``RADON_DIVERGES``."""
    R = _radon()
    compared, disagree = 0, []
    for rel in C.source_files(REPO)[0]:
        pairs = _comparable_pairs(R, (REPO / rel).read_text(encoding="utf-8"))
        compared += len(pairs)
        disagree += [f"{rel}:{b.lineno} {b.name}: radon {b.complexity}, tools.complexity {C.py_score(fn)}"
                     for b, fn in pairs if C.py_score(fn) != b.complexity]
    assert compared > 1500, f"solo {compared} funciones comparables: la prueba ya no compara casi nada"
    assert not disagree, "\n".join(disagree[:20])


# -------------------------------------------------------------------------------------------- la medida: JavaScript

HAND_COUNTED_JS = """\
export function a(x, y = 1) { return x?.y ?? y; }
export function b(x) { switch (x) { case 1: return 1; case 2: return 2; default: return 3; } }
export function c(x, y, z) { try { f(); } catch (e) { g(); } finally { h(); } return x && y || z; }
export function d(xs) { return `${xs.map((v) => (v ? 1 : 2)).join('')}`; }
export function e(o, xs) { o.a ||= 1; o.b ??= 2; for (const k in o) {} for (const v of xs) {} do {} while (o); }
export class Tour { show(s) { if (s) return 1; return 0; } get open() { return this.x || 0; } }
const handlers = { click: (ev) => (ev ? 1 : 0) };
export class Panel { size = window.x ?? 3; static { if (globalThis.y) Panel.z = 1; } }
el.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') close(); });
"""
# a: valor por omisión (1) + ?. (1) + ?? (1). b: dos case sin default. c: catch + && + ||. d: 1 (el ternario es de la
# flecha del template, que no se atribuye a d: lizard 1.25 sí lo hacía). e: ||= ??= for-in for-of do-while.
HAND_COUNTED_JS_SCORES = {
    "a": 4, "b": 3, "c": 4, "d": 1, "d.(map callback)": 2, "e": 6, "Tour.show": 2, "Tour.get open": 2,
    "click": 2, "(addEventListener 'keydown' callback)": 2,
    "Panel.size (field initializer)": 2, "Panel.(static block)": 2,
}


def _js_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "lint").symlink_to(REPO / C.JS_TOOL_REL, target_is_directory=True)
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    return tmp_path


def test_javascript_complexity_is_the_hand_counted_cyclomatic_number(tmp_path):
    need_js()
    root = _js_repo(tmp_path, {"web/m.js": HAND_COUNTED_JS})
    got = {f.name: f.score for f in C.measure_js(root, ["web/m.js"])}
    assert got == HAND_COUNTED_JS_SCORES


def test_an_n8n_code_node_body_is_measured_as_the_function_n8n_runs(tmp_path):
    """Un nodo Code de n8n tiene «return» en el nivel superior: se mide envuelto, como lo corre n8n."""
    need_js()
    node = "const xs = $input.all();\nif (!xs.length) return [];\nreturn xs.filter((x) => x.json.ok && x.json.v);\n"
    root = _js_repo(tmp_path, {"n8n/nodes/n.js": node})
    got = {(f.name, f.line): f.score for f in C.measure_js(root, ["n8n/nodes/n.js"])}
    assert got == {("(n8n Code node)", 1): 2, ("(n8n Code node).(filter callback)", 3): 2}


def test_a_javascript_file_that_does_not_parse_stops_the_check_and_names_the_line(tmp_path):
    need_js()
    root = _js_repo(tmp_path, {"web/bad.js": "export function f() {\n  return 1 +;\n}\n"})
    with pytest.raises(C.ToolError, match=r"web/bad\.js:2: no se pudo analizar"):
        C.measure_js(root, ["web/bad.js"])


def test_an_eslint_that_parses_with_another_espree_stops_the_check(tmp_path):
    """Los nombres salen del espree fijado y los números del que trae ESLint: si npm instala dos versiones, las
    posiciones podrían no casar y una función podría quedar con el número de otra. Se planta un espree anidado."""
    need_js()
    lint = tmp_path / "scripts" / "lint"
    mods = lint / "node_modules"
    mods.mkdir(parents=True)
    shutil.copyfile(REPO / C.JS_TOOL_REL / "complexity.mjs", lint / "complexity.mjs")
    real = REPO / C.JS_TOOL_REL / "node_modules"
    for entry in real.iterdir():
        if entry.name != "eslint":
            (mods / entry.name).symlink_to(entry, target_is_directory=entry.is_dir())
    shutil.copytree(real / "eslint", mods / "eslint", symlinks=True)
    nested = mods / "eslint" / "node_modules" / "espree"
    shutil.copytree(real / "espree", nested, symlinks=True)
    meta = json.loads((nested / "package.json").read_text(encoding="utf-8"))
    meta["version"] = "11.9.9"
    (nested / "package.json").write_text(json.dumps(meta), encoding="utf-8")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "m.js").write_text("export function f(x) { return x ? 1 : 2; }\n", encoding="utf-8")
    with pytest.raises(C.ToolError, match=r"ESLint usa espree 11\.9\.9 y package\.json fija"):
        C.measure_js(tmp_path, ["web/m.js"])


def test_an_eslint_disable_comment_cannot_switch_the_measure_off(tmp_path):
    need_js()
    src = "/* eslint-disable complexity */\n" + "export function f(x) {\n" + "".join(
        f"  if (x === {i}) return {i};\n" for i in range(11)) + "  return -1;\n}\n"
    root = _js_repo(tmp_path, {"web/m.js": src})
    assert [(f.name, f.score) for f in C.measure_js(root, ["web/m.js"])] == [("f", 12)]


# ------------------------------------------------------------------------------------------------------ el trinquete

def mini_repo(tmp_path: Path, code: str, baseline: dict[str, int] | None = None, **extra) -> Path:
    (tmp_path / "pkg").mkdir(parents=True)
    (tmp_path / "pkg" / "mod.py").write_text(code, encoding="utf-8")
    (tmp_path / "config").mkdir()
    if baseline is not None:
        C.write_baseline(tmp_path / C.BASELINE_REL, baseline, {"python": C.PY_METRIC, **extra})
    return tmp_path


def check(root: Path, capsys, *args: str) -> tuple[int, str, str]:
    code = C.main(["--root", str(root), "--python-only", *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def saved(root: Path) -> dict[str, int]:
    return json.loads((root / C.BASELINE_REL).read_text(encoding="utf-8"))["functions"]


def test_a_new_function_over_the_ceiling_fails_and_says_where_how_much_and_what_to_do(tmp_path, capsys):
    root = mini_repo(tmp_path, "x = 1\n\n" + ifs("big", 12), {})
    code, _, err = check(root, capsys)
    assert code == 1
    assert "[NUEVA] pkg/mod.py:3 big: complejidad 12 > techo 10" in err
    assert "Divida la función" in err and "docs/complejidad.md" in err


def test_the_ceiling_itself_is_allowed(tmp_path, capsys):
    root = mini_repo(tmp_path, ifs("edge", C.CEILING), {})
    code, out, _ = check(root, capsys)
    assert code == 0 and "0 pasan el techo 10" in out


def test_update_never_grandfathers_a_new_offender(tmp_path, capsys):
    root = mini_repo(tmp_path, ifs("big", 11), {})
    before = (root / C.BASELINE_REL).read_bytes()
    code, _, err = check(root, capsys, "--update")
    assert code == 1 and "Nada se escribió" in err and "pkg/mod.py:1 big" in err
    assert (root / C.BASELINE_REL).read_bytes() == before


def test_a_listed_function_may_not_grow(tmp_path, capsys):
    root = mini_repo(tmp_path, ifs("old", 16), {"pkg/mod.py::old": 15})
    code, _, err = check(root, capsys)
    assert code == 1 and "[CRECIÓ] pkg/mod.py:1 old: complejidad 16, creció desde 15" in err
    assert check(root, capsys, "--update")[0] == 1 and saved(root) == {"pkg/mod.py::old": 15}


def test_a_listed_function_at_its_listed_number_passes(tmp_path, capsys):
    root = mini_repo(tmp_path, ifs("old", 15), {"pkg/mod.py::old": 15})
    assert check(root, capsys)[0] == 0


def test_an_improved_function_must_lower_the_list_and_then_cannot_grow_back(tmp_path, capsys):
    root = mini_repo(tmp_path, ifs("old", 13), {"pkg/mod.py::old": 15})
    code, _, err = check(root, capsys)
    assert code == 1 and "[BAJÓ] pkg/mod.py:1 old: complejidad 13, bajó desde 15" in err and "--update" in err
    assert check(root, capsys, "--update")[0] == 0 and saved(root) == {"pkg/mod.py::old": 13}
    assert check(root, capsys)[0] == 0
    (root / "pkg" / "mod.py").write_text(ifs("old", 14), encoding="utf-8")
    assert check(root, capsys)[0] == 1  # el margen que se ganó no se puede volver a gastar


def test_a_function_back_under_the_ceiling_leaves_the_list(tmp_path, capsys):
    root = mini_repo(tmp_path, ifs("old", 10), {"pkg/mod.py::old": 15})
    code, _, err = check(root, capsys)
    assert code == 1 and "[CUMPLE] pkg/mod.py:1 old: complejidad 10, ya dentro del techo" in err
    assert check(root, capsys, "--update")[0] == 0 and saved(root) == {}


def test_a_removed_function_leaves_the_list(tmp_path, capsys):
    root = mini_repo(tmp_path, ifs("other", 3), {"pkg/mod.py::gone": 20})
    code, _, err = check(root, capsys)
    assert code == 1 and "[NO EXISTE] pkg/mod.py gone: está en la lista (20) y ya no existe" in err
    assert check(root, capsys, "--update")[0] == 0 and saved(root) == {}


def test_a_renamed_listed_function_is_carried_by_update_only_when_unambiguous(tmp_path, capsys):
    root = mini_repo(tmp_path, ifs("new_name", 20), {"pkg/mod.py::old_name": 20})
    code, _, err = check(root, capsys)
    assert code == 1 and "Parece la función «old_name»" in err and "¿ahora «new_name»?" in err
    assert check(root, capsys, "--update")[0] == 0 and saved(root) == {"pkg/mod.py::new_name": 20}
    # Un renombre que además creció no es un renombre: --update se niega.
    root2 = mini_repo(tmp_path / "b", ifs("new_name", 21), {"pkg/mod.py::old_name": 20})
    assert check(root2, capsys, "--update")[0] == 1 and saved(root2) == {"pkg/mod.py::old_name": 20}


def test_two_lookalike_renames_in_one_file_are_not_guessed(tmp_path, capsys):
    root = mini_repo(tmp_path, ifs("x1", 20) + ifs("x2", 20), {"pkg/mod.py::a": 20, "pkg/mod.py::b": 20})
    code, _, err = check(root, capsys)
    assert code == 1 and "Parece la función" not in err and "¿ahora" not in err
    assert check(root, capsys, "--update")[0] == 1
    assert saved(root) == {"pkg/mod.py::a": 20, "pkg/mod.py::b": 20}


def test_two_listed_lookalikes_and_one_candidate_is_not_a_rename_either(tmp_path, capsys):
    """Dos de la lista con el mismo número y una sola función nueva con ese número: ¿cuál de las dos es? No se adivina."""
    root = mini_repo(tmp_path, ifs("x1", 20), {"pkg/mod.py::a": 20, "pkg/mod.py::b": 20})
    code, _, err = check(root, capsys)
    assert code == 1 and "Parece la función" not in err and "¿ahora" not in err
    assert check(root, capsys, "--update")[0] == 1
    assert saved(root) == {"pkg/mod.py::a": 20, "pkg/mod.py::b": 20}


def test_rebaseline_rewrites_the_measured_language_and_keeps_the_other_with_its_tool_versions(tmp_path, capsys):
    """--python-only --rebaseline (cambio de PY_METRIC sin Node): Python se mide de nuevo (lo nuevo entra, lo que bajó
    baja, lo que ya no existe sale) y las líneas de JavaScript quedan, con las versiones de ESLint con que se midieron."""
    code = ifs("big", 11) + ifs("old", 12)
    root = mini_repo(tmp_path, code, {"pkg/mod.py::gone": 30, "pkg/mod.py::old": 25, "web/app.js::render": 40},
                     eslint="10.14.0", espree="11.2.0")
    p = root / C.BASELINE_REL
    data = json.loads(p.read_text(encoding="utf-8"))
    data["tools"]["python"] = "ast-nist-0"  # la regla de antes
    p.write_text(json.dumps(data), encoding="utf-8")
    assert check(root, capsys)[0] == 2
    rc, out, _ = check(root, capsys, "--rebaseline")
    assert rc == 0 and "Agregadas 1, subidas 0" in out and "pkg/mod.py::big: - -> 11" in out
    after = json.loads(p.read_text(encoding="utf-8"))
    assert after["functions"] == {"pkg/mod.py::big": 11, "pkg/mod.py::old": 12, "web/app.js::render": 40}
    assert after["tools"] == {"eslint": "10.14.0", "espree": "11.2.0", "python": C.PY_METRIC}
    assert check(root, capsys)[0] == 0


def test_rebaseline_repairs_a_list_written_for_another_ceiling(tmp_path, capsys):
    """El mensaje de un «ceiling» distinto manda a --rebaseline: tiene que poder leer esa lista."""
    root = mini_repo(tmp_path, ifs("mid", 12), {})
    p = root / C.BASELINE_REL
    data = json.loads(p.read_text(encoding="utf-8"))
    data.update(ceiling=15, functions={"pkg/mod.py::other": 13})
    p.write_text(json.dumps(data), encoding="utf-8")
    code, _, err = check(root, capsys)
    assert code == 2 and "«ceiling» es 15" in err and "--rebaseline" in err
    assert check(root, capsys, "--rebaseline")[0] == 0
    assert json.loads(p.read_text(encoding="utf-8"))["ceiling"] == C.CEILING
    assert saved(root) == {"pkg/mod.py::mid": 12}
    assert check(root, capsys)[0] == 0


def test_report_lists_the_worst_functions_first(tmp_path, capsys):
    root = mini_repo(tmp_path, ifs("small", 3) + ifs("worst", 14) + ifs("mid", 9), {"pkg/mod.py::worst": 14})
    code, out, _ = check(root, capsys, "--report", "2")
    assert code == 0
    assert out.splitlines()[:3] == ["Las 2 funciones más complejas:", "    14  pkg/mod.py:7 worst",
                                    "     9  pkg/mod.py:35 mid"]


def test_python_only_does_not_judge_the_javascript_lines(tmp_path, capsys):
    root = mini_repo(tmp_path, ifs("f", 2), {"web/app.js::render": 40})
    assert check(root, capsys)[0] == 0
    assert check(root, capsys, "--update")[0] == 0 and saved(root) == {"web/app.js::render": 40}


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d["functions"].update({"pkg/mod.py::f": 7}), "no es un entero mayor que el techo"),
    (lambda d: d.update(ceiling=15), "«ceiling» es 15"),
    (lambda d: d.update(functions={"z.py::b": 30, "a.py::a": 30}), "no están ordenadas"),
    (lambda d: d["tools"].update(python="ast-nist-0"), "otra versión de la herramienta"),
])
def test_a_broken_or_foreign_list_stops_the_check_with_exit_2(tmp_path, capsys, mutate, needle):
    root = mini_repo(tmp_path, ifs("f", 2), {})
    p = root / C.BASELINE_REL
    data = json.loads(p.read_text(encoding="utf-8"))
    mutate(data)
    p.write_text(json.dumps(data), encoding="utf-8")
    code, _, err = check(root, capsys)
    assert code == 2 and needle in err


def test_python_that_does_not_parse_stops_the_check_and_names_the_line(tmp_path, capsys):
    root = mini_repo(tmp_path, "def f(:\n    pass\n", {})
    code, _, err = check(root, capsys)
    assert code == 2 and "pkg/mod.py:1: no se pudo analizar" in err


def test_in_github_actions_each_finding_is_an_annotation_on_its_line(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    root = mini_repo(tmp_path, ifs("big", 11), {})
    code, out, _ = check(root, capsys)
    assert code == 1 and "::error file=pkg/mod.py,line=1,title=complexity (new)::pkg/mod.py:1 big: complejidad 11" in out


def test_javascript_without_eslint_installed_is_a_setup_error_not_a_pass(tmp_path, capsys):
    root = mini_repo(tmp_path, ifs("f", 2), {})
    code = C.main(["--root", str(root)])
    err = capsys.readouterr().err
    assert code == 2 and "npm ci --prefix scripts/lint" in err


# ---------------------------------------------------------------------------------------------- el repositorio real

def _copy_python(dst: Path) -> None:
    for rel in C.source_files(REPO)[0]:
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, dst / rel)
    (dst / "config").mkdir()
    shutil.copyfile(REPO / C.BASELINE_REL, dst / C.BASELINE_REL)


def test_the_repository_is_within_its_baseline():
    """La misma revisión que el job «lint»: falla aquí, en local, antes del push."""
    if _js_ready() and not REQUIRE_JS:
        assert C.run(REPO, python_only=True) == 0
    else:
        need_js()
        assert C.run(REPO) == 0


def test_a_synthetic_over_ceiling_function_in_a_copy_of_the_repository_fails(tmp_path, capsys):
    """Prueba de que la revisión del repositorio de arriba no pasa por vacía: en una copia, una función de 11 en
    un módulo real la hace fallar, y la deja pasar con 10."""
    _copy_python(tmp_path)
    target = tmp_path / "python" / "enso" / "drift.py"
    original = target.read_text(encoding="utf-8")
    assert check(tmp_path, capsys)[0] == 0
    target.write_text(original + "\n\n" + ifs("synthetic_branchy", 11), encoding="utf-8")
    code, _, err = check(tmp_path, capsys)
    assert code == 1 and "[NUEVA] python/enso/drift.py:" in err and "synthetic_branchy: complejidad 11 > techo 10" in err
    target.write_text(original + "\n\n" + ifs("synthetic_branchy", 10), encoding="utf-8")
    assert check(tmp_path, capsys)[0] == 0


def test_the_complexity_tool_obeys_its_own_ceiling():
    listed = json.loads((REPO / C.BASELINE_REL).read_text(encoding="utf-8"))["functions"]
    own = [k for k in listed if k.startswith(("python/tools/complexity.py", "python/tests/test_complexity.py",
                                              "scripts/lint/complexity.mjs"))]
    assert own == []


def test_every_tracked_source_file_is_found_without_git_too():
    """Las copias temporales de estas pruebas no tienen git: recorrer el árbol debe ver todo lo que ve git."""
    tracked = C._git_files(REPO)
    if tracked is None:
        pytest.skip("no es una copia de git")
    found = set(C._walk_files(REPO))
    assert [p for p in tracked if p.endswith(C.PY_SUFFIXES + C.JS_SUFFIXES) and p not in found] == []


GENERATED = ("n8n/dist/", "python/tests/fixtures/")  # escrito aquí, no tomado de C: la prueba no se mide a sí misma


def test_the_scope_is_every_language_file_but_generated_code():
    py, js = C.source_files(REPO)
    assert {"python/enso/observatory.py", "python/tools/complexity.py"} <= set(py)
    assert {"n8n/build.mjs", "n8n/lib/classify.js", "n8n/nodes/analizar.js", "functions/_lib/ab.js",
            "public/assets/js/app.js", ".github/scripts/watchdog.cjs"} <= set(js)
    assert [p for p in py + js if p.startswith(GENERATED) or "node_modules/" in p] == []


@pytest.mark.parametrize("use_git", [False, True], ids=["tree-walk", "git"])
def test_generated_vendored_and_ignored_files_are_out_of_scope_and_new_files_are_in(tmp_path, use_git):
    """Hoy no hay .py ni .js en fixtures ni en n8n/dist, así que el repositorio real no prueba la exclusión: aquí sí.
    Con git, un archivo nuevo sin commit cuenta (se revisa antes del commit) y uno ignorado no."""
    files = ["pkg/new.py", "web/app.mjs", "n8n/dist/w.js", "python/tests/fixtures/capturada.py",
             "python/tests/fixtures/source.js", "scripts/lint/node_modules/eslint/x.js", "web/node_modules/y.cjs"]
    for rel in files + ["tmp/scratch.py"]:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x = 1\n", encoding="utf-8")
    expected_py = ["pkg/new.py", "tmp/scratch.py"]
    if use_git:
        if not shutil.which("git"):
            pytest.skip("no hay git")
        import subprocess
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        (tmp_path / ".gitignore").write_text("tmp/\n", encoding="utf-8")
        expected_py = ["pkg/new.py"]
    assert C.source_files(tmp_path) == (expected_py, ["web/app.mjs"])
