"""Revisión antes de desplegar (#133): el techo de complejidad, el job «lint», ``hazard-feed-down``, la auditoría de
deriva y los issues que no se cierran solos, probados como los vería quien los usa.

Cada prueba que arregla algo falló con el código de 4c6f977e (dicho en su docstring, con la mutación que la mata):

* el trinquete solo comparaba el código con la lista, no la lista con la de la rama base: subir una línea a mano (o
  correr ``--rebaseline`` sin cambio de herramienta) pasaba el job «lint» con 0;
* la segunda corrida del mismo día (40 min después) dejaba de avisar ``hazard-feed-down`` y sync_issues cerraba el
  issue de una fuente oficial de avisos que seguía caída;
* la auditoría de deriva se caía (sin JSON, con 1 = «encontró algo») con un lector que lanza otra excepción que
  ValueError/KeyError (``cpc-godas-d20`` con ``[]``: AttributeError), pasaba con 0 sobre un archivo sin copias en la
  semana, y una lista de revisados mal formada salía con una traza.

Las demás muestran que la decisión aguanta (saltos de línea CRLF, BOM, el arreglo urgente que sigue el mensaje al pie
de la letra, el issue de la auditoría que sync_issues no toca, el reloj adelantado).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from conftest import FIX
from test_block_pages import _hazard_run
from test_complexity import ifs, mini_repo
from test_sync_issues import FakeGitHub, _event, _issue
from tools import complexity as C
from tools import drift_audit as A
from tools import sync_issues as S

REPO = C.ROOT
GIT = ["-c", "user.email=t@t", "-c", "user.name=t"]


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *GIT, *args], check=True, capture_output=True)


def _committed(root: Path) -> Path:
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    return root


def _check(root: Path, capsys, *args: str) -> tuple[int, str]:
    code = C.main(["--root", str(root), "--python-only", *args])
    return code, capsys.readouterr().err


def _edit_baseline(root: Path, **changes: int) -> None:
    p = root / C.BASELINE_REL
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["functions"] = dict(sorted({**doc["functions"], **changes}.items()))
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# ------------------------------------------------------------------------------ trinquete: la lista contra la base

def test_a_hand_raised_baseline_line_passes_the_old_gate_and_fails_against_the_base_branch(tmp_path, capsys):
    """Una función de la lista crece de 15 a 17 y alguien sube su línea a mano a 17: el código coincide con la lista,
    así que sin ``--base-ref`` sale 0 (el agujero de 4c6f977e); con ``--base-ref HEAD`` sale 1 y nombra la línea.
    Mutación que la mata: ``v > before[k]`` → ``v > before[k] + 5`` en ``_raised``."""
    root = _committed(mini_repo(tmp_path, ifs("old", 15), {"pkg/mod.py::old": 15}))
    (root / "pkg" / "mod.py").write_text(ifs("old", 17), encoding="utf-8")
    _edit_baseline(root, **{"pkg/mod.py::old": 17})
    assert _check(root, capsys)[0] == 0  # lo que el job «lint» hacía: el código coincide con la lista
    code, err = _check(root, capsys, "--base-ref", "HEAD")
    assert code == 1 and "pkg/mod.py::old: 15 -> 17 (subió)" in err and "Divida la función" in err


def test_a_hand_added_line_fails_but_a_rename_carried_by_update_does_not(tmp_path, capsys):
    """Agregar a mano una función nueva de 12 falla; renombrar una de la lista (``--update`` traslada la línea: la
    vieja ya no existe, mismo archivo, mismo número) no es una subida. Mutación: quitar ``g not in measured`` deja
    pasar el canje; quitar ``_take_rename`` hace fallar el renombre."""
    root = _committed(mini_repo(tmp_path, ifs("old", 14), {"pkg/mod.py::old": 14}))
    (root / "pkg" / "mod.py").write_text(ifs("renamed", 14), encoding="utf-8")
    assert _check(root, capsys, "--update")[0] == 0
    assert _check(root, capsys, "--base-ref", "HEAD")[0] == 0
    # El canje: «old» sigue existiendo (en 10), su línea se borra y la holgura se le da a una función nueva de 12.
    (root / "pkg" / "mod.py").write_text(ifs("old", 10) + "\n\n" + ifs("fresh", 12), encoding="utf-8")
    p = root / C.BASELINE_REL
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["functions"] = {"pkg/mod.py::fresh": 12}
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    code, err = _check(root, capsys, "--base-ref", "HEAD")
    assert code == 1 and "pkg/mod.py::fresh: agregada con 12" in err


def test_a_rebaseline_after_a_real_tool_change_is_not_blocked(tmp_path, capsys):
    """``--rebaseline`` por un cambio de la regla (``PY_METRIC``) puede subir líneas: es la salida documentada, y la
    lista guarda la versión, que el revisor ve en el diff. Mutación: no mirar ``_tooling`` la bloquea."""
    root = _committed(mini_repo(tmp_path, ifs("old", 15), {"pkg/mod.py::old": 12}))
    p = root / C.BASELINE_REL
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["tools"] = {"python": "ast-nist-1"}
    p.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    _git(root, "commit", "-qam", "lista medida con la regla anterior")
    assert _check(root, capsys)[0] == 2  # otra versión: hay que rebaselinear
    assert _check(root, capsys, "--rebaseline")[0] == 0
    assert _check(root, capsys, "--base-ref", "HEAD")[0] == 0


def test_a_shallow_clone_without_the_base_commit_cannot_check_and_says_how_to_fix_it(tmp_path, capsys):
    """``actions/checkout`` trae un solo commit por omisión: sin HEAD^1 no se sabe si la lista subió, y eso es 2
    («no pudo medir»), nunca 0. Un clon sin la lista en la base (el PR que la agrega) no tiene con qué comparar."""
    root = _committed(mini_repo(tmp_path, ifs("old", 15), {"pkg/mod.py::old": 15}))
    code, err = _check(root, capsys, "--base-ref", "HEAD^1")
    assert code == 2 and "fetch-depth: 2" in err
    (root / C.BASELINE_REL).rename(tmp_path / "aside.json")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "sin lista")
    (tmp_path / "aside.json").rename(root / C.BASELINE_REL)
    assert _check(root, capsys, "--base-ref", "HEAD")[0] == 0


def test_the_lint_job_fetches_the_base_commit_and_checks_against_it():
    """El job «lint» usa la comparación y trae el commit con que compara (``refs/pull/N/merge``: HEAD^1 es la base)."""
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    lint = ci.split("\n  lint:\n", 1)[1].split("\n  test:\n", 1)[0]
    assert "fetch-depth: 2" in lint and "python -m tools.complexity --report 15 --base-ref HEAD^1" in lint


def test_the_check_writes_nothing_so_lint_and_test_jobs_cannot_race(tmp_path, capsys):
    """El job «lint» y ``test_complexity`` en el job «test» corren a la vez (y en local, en paralelo): la revisión
    sin ``--update`` no escribe la lista ni otro archivo."""
    root = _committed(mini_repo(tmp_path, ifs("old", 15) + "\n\n" + ifs("big", 12), {"pkg/mod.py::old": 15}))
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert _check(root, capsys, "--base-ref", "HEAD")[0] == 1
    after = {p: p.read_bytes() for p in root.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert after == before


# --------------------------------------------------------------------------------- la medida no depende del archivo

def test_crlf_and_a_bom_do_not_change_any_score_of_a_real_module(tmp_path):
    """Un checkout en Windows (``core.autocrlf``) o un editor que agrega BOM: mismas funciones, mismas líneas, mismos
    números que en LF en un módulo real del pipeline (invariante; el conteo no puede depender del salto de línea)."""
    rel = "python/enso/observatory.py"
    lf = C.measure_python(REPO, [rel])
    text = (REPO / rel).read_text(encoding="utf-8")
    (tmp_path / "python" / "enso").mkdir(parents=True)
    (tmp_path / rel).write_bytes(b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8"))
    assert len(lf) > 100 and C.measure_python(tmp_path, [rel]) == lf


# ------------------------------------------------------------------------- un arreglo urgente sigue el mensaje

def _observatory_copy(tmp_path: Path) -> tuple[Path, Path]:
    rel = "python/enso/observatory.py"
    (tmp_path / "python" / "enso").mkdir(parents=True)
    shutil.copyfile(REPO / rel, tmp_path / rel)
    listed = json.loads((REPO / C.BASELINE_REL).read_text(encoding="utf-8"))
    (tmp_path / "config").mkdir()
    C.write_baseline(tmp_path / C.BASELINE_REL, {k: v for k, v in listed["functions"].items() if k.startswith(rel)},
                     {"python": C.PY_METRIC})
    return tmp_path, tmp_path / rel


ANCHOR = "    if reader and reader_state is not None:\n"


def test_an_urgent_branch_in_acquire_news_fails_and_the_literal_fix_from_the_message_passes(tmp_path, capsys):
    """Quien agrega con prisa una rama a ``acquire_news`` (157, listada) lee CRECIÓ con la línea, el número y qué
    hacer; si hace lo que dice (sacar la rama a una función con nombre, llamada sin ``if``), pasa sin tocar la
    lista. Así se comprobó que «sin override» no deja a un arreglo urgente sin salida."""
    root, target = _observatory_copy(tmp_path)
    src = target.read_text(encoding="utf-8")
    assert src.count(ANCHOR) == 1 and _check(root, capsys)[0] == 0
    branch = "    if fixtures is not None and raw_dir is None:\n        log.add('info', 'news', 'fetch', 'hotfix', 'x')\n"
    target.write_text(src.replace(ANCHOR, branch + ANCHOR), encoding="utf-8")
    code, err = _check(root, capsys)
    listed = json.loads((root / C.BASELINE_REL).read_text(encoding="utf-8"))["functions"]
    was = listed["python/enso/observatory.py::acquire_news"]
    assert code == 1 and f"acquire_news: complejidad {was + 2}, creció desde {was}" in err
    assert "saque cada rama o caso a una función con nombre" in err
    helper = ("\n\ndef _hotfix(fixtures, raw_dir, log) -> None:\n"
              "    if fixtures is not None and raw_dir is None:\n        log.add('info', 'news', 'fetch', 'hotfix', 'x')\n")
    target.write_text(src.replace(ANCHOR, "    _hotfix(fixtures, raw_dir, log)\n" + ANCHOR) + helper, encoding="utf-8")
    assert _check(root, capsys)[0] == 0


# --------------------------------------------------------------- hazard-feed-down: la racha, no la corrida anterior

def test_the_second_run_of_the_same_day_keeps_the_hazard_feed_down_warning(tmp_path, monkeypatch):
    """CIIFEN caído desde el 19 a las 04:40; la corrida anterior fue 40 min antes de esta (00:20 → 01:00 del 20).
    Con 4c6f977e (6 h entre esta corrida y la anterior) no avisaba, y sync_issues cerraba el issue de una fuente que
    seguía caída. Mutación: medir desde ``before['checkedAt']`` en vez de ``since`` la hace fallar."""
    st, log = _hazard_run(tmp_path, monkeypatch, prev_ok=False, prev_at="2026-11-20T00:20:00+00:00",
                          prev_extra={"downSince": "2026-11-19T04:40:00+00:00"})
    assert [e.source for e in log.events if e.code == "hazard-feed-down"] == ["news-ciifen"]
    assert st["downSince"] == "2026-11-19T04:40:00+00:00"  # la racha sigue para la próxima corrida


def test_a_new_outage_seen_twice_forty_minutes_apart_still_waits_six_hours(tmp_path, monkeypatch):
    """El primer día de una caída, dos corridas a 40 min (sin ``downSince`` previo: publicación anterior a este
    cambio o primera caída) no son «dos corridas caídas»; la racha empieza en la anterior."""
    st, log = _hazard_run(tmp_path, monkeypatch, prev_ok=False, prev_at="2026-11-20T00:20:00+00:00")
    assert not [e for e in log.events if e.code == "hazard-feed-down"]
    assert st["downSince"] == "2026-11-20T00:20:00+00:00"


def test_a_clock_ahead_in_the_previous_run_never_counts_as_six_hours(tmp_path, monkeypatch):
    """Reloj adelantado (o publicaciones fuera de orden): la anterior dice 05:00 y esta corrida es a las 01:00. Una
    diferencia negativa no es una caída larga."""
    _, log = _hazard_run(tmp_path, monkeypatch, prev_ok=False, prev_at="2026-11-20T05:00:00+00:00")
    assert not [e for e in log.events if e.code == "hazard-feed-down"]


def test_down_since_starts_on_the_first_down_run_and_ends_when_the_feed_answers():
    from enso import observatory as obs

    down = {"ok": False, "error": "HTTP 500", "checkedAt": "2026-11-20T04:40:00+00:00"}
    ok = {"ok": True, "checkedAt": "2026-11-19T04:40:00+00:00"}
    assert obs._down_since(down, ok) == "2026-11-20T04:40:00+00:00"
    assert obs._down_since(down, {**down, "checkedAt": "2026-11-19T04:40:00+00:00"}) == "2026-11-19T04:40:00+00:00"
    assert obs._down_since(ok, down) is None
    # Un feed que no se pidió no empieza ni sigue una racha (``omitted``: tiempo agotado o servidor ya caído).
    assert obs._down_since({**down, "omitted": "deadline"}, down) is None


def test_the_issue_of_a_feed_still_down_survives_the_second_run_of_the_day(tmp_path, monkeypatch):
    """De punta a punta: el issue abierto ayer por ``hazard-feed-down`` sigue abierto tras la corrida de 40 min."""
    _, log = _hazard_run(tmp_path, monkeypatch, prev_ok=False, prev_at="2026-11-20T00:20:00+00:00",
                         prev_extra={"downSince": "2026-11-19T04:40:00+00:00"})
    events = [e.as_dict() for e in log.events]
    ev = next(e for e in events if e["code"] == "hazard-feed-down")
    gh = FakeGitHub([_issue(7, ev)])
    res = S.sync(gh, {"events": events, "publicationId": "pub-2"}, "")
    assert res["closed"] == 0 and gh.issues[7]["state"] == "open"


# ------------------------------------------------------------------------------------- sync_issues: cierres a mano

def test_the_drift_audit_issue_is_never_closed_by_the_daily_sync():
    """El issue que abre drift-audit.yml lleva ``enso-fp:drift-audit`` (no hexadecimal): la sincronización diaria,
    que cierra lo que no ve, no lo reconoce como suyo; lo cierra quien revisa y anota en drift_audit_known.json."""
    audit_issue = {"number": 3, "title": "[datos] La auditoría semanal de deriva encontró algo", "state": "open",
                   "body": "x\n\n<!-- enso-fp:drift-audit -->"}
    gh = FakeGitHub([audit_issue])
    S.sync(gh, {"events": [], "publicationId": "pub-2"}, "")
    assert gh.issues[3]["state"] == "open" and gh.writes(3) == []


def test_a_sticky_issue_gets_one_note_says_how_to_close_it_and_the_docs_agree():
    """Un ``series-regressed`` solo aparece el día del cambio: al día siguiente el issue recibe un comentario (uno
    solo, aunque pasen semanas) que dice que se cierra a mano, y docs/operaciones.md dice lo mismo."""
    ev = _event("cpc-oni", "series-regressed")
    gh = FakeGitHub([_issue(5, ev)])
    for pub in ("pub-2", "pub-3", "pub-4"):
        S.sync(gh, {"events": [], "publicationId": pub}, "")
    comments = [c for m, p, c in gh.calls if m == "POST" and p == "/issues/5/comments"]
    assert gh.issues[5]["state"] == "open" and len(comments) == 1 and "ciérrelo a mano" in comments[0]["body"]
    ops = (REPO / "docs" / "operaciones.md").read_text(encoding="utf-8")
    assert "`series-shrunk`, `series-regressed`, `series-missing`" in ops and "no se cierran solos" in ops


# ------------------------------------------------------------------------------------------- auditoría de deriva

def _archive(tmp_path: Path, files: dict[str, bytes]) -> Path:
    repo = tmp_path / "repo"
    for rel, body in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_bytes(body)
    return _committed(repo)


IMUNIFY = (FIX / "blocked" / "imunify360-soltv-piura-20261119.html").read_bytes()


def test_a_reader_that_raises_another_exception_is_a_finding_not_a_crashed_audit(tmp_path, monkeypatch, capsys):
    """El lector real de GODAS (``cpc-godas-d20``) con un JSON que es una lista lanza AttributeError. En la corrida
    diaria eso es un error ``exception`` de la fuente; en la auditoría de 4c6f977e tumbaba todo (traza, sin JSON,
    salida 1) y escondía la página de Imunify360 de la misma semana. Mutación: volver a capturar solo
    ``(FormatChanged, ValueError, KeyError)``."""
    monkeypatch.setattr(A, "ROOT", _archive(tmp_path, {
        "sources/cpc-godas-d20/2026-11-20-aaaa.json": b"[]",
        "sources/news-ciifen/2026-11-20-bbbb.xml": IMUNIFY}))
    monkeypatch.setattr(A, "KNOWN", tmp_path / "none.json")
    out = tmp_path / "found.json"
    assert A.main(["--ref", "HEAD", "--json", str(out)]) == 1
    found = {(f["kind"], f["file"].split("/")[1]) for f in json.loads(out.read_text(encoding="utf-8"))}
    assert found == {("unreadable", "cpc-godas-d20"), ("archived-block-page", "news-ciifen")}
    assert "AttributeError" in capsys.readouterr().out


def test_a_week_without_any_archived_copy_is_could_not_audit(tmp_path, monkeypatch, capsys):
    """Si la corrida diaria deja de archivar, la semana no tiene copias: eso es 2 («no pudo auditar»), no 0 («nada
    nuevo»). Con ``--source`` de una fuente mensual, una semana sin copias sí es normal. Mutación: quitar
    ``require_copies_in_window`` devuelve 0."""
    monkeypatch.setattr(A, "ROOT", _archive(tmp_path, {"sources/news-ciifen/2020-01-01-aaaa.xml": IMUNIFY}))
    monkeypatch.setattr(A, "KNOWN", tmp_path / "none.json")
    assert A.main(["--ref", "HEAD", "--days", "7"]) == 2
    assert "no está llegando a data-archive" in capsys.readouterr().err
    assert A.main(["--ref", "HEAD", "--days", "7", "--source", "news-ciifen"]) == 0


@pytest.mark.parametrize("text", ["{", '{"about": "sin findings"}', '{"findings": [{"file": "x"}]}'])
def test_a_malformed_reviewed_list_is_could_not_audit(tmp_path, monkeypatch, capsys, text):
    monkeypatch.setattr(A, "ROOT", _archive(tmp_path, {"sources/news-ciifen/2026-11-20-aaaa.xml": IMUNIFY}))
    bad = tmp_path / "known.json"
    bad.write_text(text, encoding="utf-8")
    monkeypatch.setattr(A, "KNOWN", bad)
    assert A.main(["--ref", "HEAD"]) == 2 and "mal formado" in capsys.readouterr().err


def test_a_depth_one_fetch_of_the_archive_still_audits_and_warns(tmp_path, monkeypatch, capsys):
    """El fallback del job (``git fetch --depth=1``) sobre un archivo de dos commits: la auditoría corre, encuentra
    la reescritura de PSL de la semana y avisa que ordena por nombre."""
    drift_fix = FIX.parent / "drift"
    repo = _archive(tmp_path, {"sources/psl-ersst6-nino34/2026-11-06-a.txt":
                               (drift_fix / "psl-nina34-20261106.data").read_bytes()})
    (repo / "sources/psl-ersst6-nino34/2026-11-18-b.txt").write_bytes((drift_fix / "psl-nina34-20261118.data").read_bytes())
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "b")
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth=1", f"file://{repo}", str(shallow)], check=True,
                   env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"})
    monkeypatch.setattr(A, "ROOT", shallow)
    assert [f["kind"] for f in A.audit("HEAD", since="2026-11-15")] == ["history-rewritten"]
    assert "no tiene historia" in capsys.readouterr().err



# ------------------------------------------------------------------------- relay-carried-copy: el borde de la edad

def _relay_codes(age: timedelta | None, carried: bool = True, down: dict | None = None) -> list[str]:
    from types import SimpleNamespace

    from enso import observatory as obs

    src = next(s for s in obs.SOURCES if s.id == "cpc-oni")
    now = datetime(2026, 11, 21, 4, 37, tzinfo=timezone.utc)
    at = (now - age).isoformat() if age is not None else "sin-fecha"
    log = obs.EventLog()
    obs.relay_event(src, SimpleNamespace(channel="relay-n8n", archived_at=at, carried=carried, upstream_down=down),
                    log, now)
    return [e.code for e in log.events], src.cadence_days


def test_a_carried_relay_copy_warns_just_past_the_source_cadence_not_at_it():
    """Una copia que n8n conserva sin que el servidor fallara: ``relay-channel`` (info) hasta la cadencia de la
    fuente inclusive, ``relay-carried-copy`` un segundo después. Sin fecha legible, aviso; un reloj adelantado
    (copia «del futuro») no la vuelve vieja; con el servidor caído, aviso a cualquier edad."""
    cadence = _relay_codes(timedelta(0))[1]
    at_edge = timedelta(days=cadence)
    assert _relay_codes(at_edge)[0] == ["relay-channel"]
    assert _relay_codes(at_edge + timedelta(seconds=1))[0] == ["relay-carried-copy"]
    assert _relay_codes(None)[0] == ["relay-carried-copy"]
    assert _relay_codes(timedelta(hours=-3))[0] == ["relay-channel"]
    assert _relay_codes(timedelta(hours=1), down={"status": 500, "at": "2026-11-21T04:00:00Z"})[0] == ["relay-carried-copy"]
    # La copia de la última corrida del recolector (no arrastrada) nunca es «carried», aunque sea vieja.
    assert _relay_codes(at_edge * 3, carried=False)[0] == ["relay-channel"]


# ------------------------------------------------------------------------ degraded-persistent: bordes del umbral

def test_degraded_persistent_escalates_exactly_at_its_threshold_and_recovers_exactly_at_24_hours():
    """Fuente de cadencia 3 días que solo llega por n8n: umbral = min(14, max(3, 1,0 × 3)) = 3 días y 3 corridas
    (``degradacion.json``, estado ``relay``). Tres corridas: T0, T0+36 h y T0+72 h − 1 s no escalan; T0+72 h sí.
    Vuelve directo: a las 23 h 59 min de la primera corrida buena sigue abierto; a las 24 h y 2 corridas, cerrado."""
    from types import SimpleNamespace

    from enso import observatory as obs
    from enso import persistent as P

    t0 = datetime(2026, 11, 1, 4, 37, tzinfo=timezone.utc)
    src = SimpleNamespace(id="sx", institution="I", product="P", cadence_days=3)
    relay = SimpleNamespace(ok=True, channel="relay-n8n", url="https://x/a", carried=False, error="")
    direct = SimpleNamespace(**{**vars(relay), "channel": "direct"})

    def run(state, at, acq):
        log = obs.EventLog()
        return P.update(state, at, log, sources=[(src, acq)], plan={}), [e for e in log.events if e.code == P.CODE]

    s1, _ = run(None, t0, relay)
    s2, _ = run(s1, t0 + timedelta(hours=36), relay)
    _, early = run(s2, t0 + timedelta(hours=72) - timedelta(seconds=1), relay)
    s3, warn = run(s2, t0 + timedelta(hours=72), relay)
    assert early == [] and [e.source for e in warn] == ["sx"] and s3["entities"]["source:sx"]["thresholdDays"] == 3
    ok1 = t0 + timedelta(hours=96)
    s4, still = run(s3, ok1, direct)
    _, almost = run(s4, ok1 + timedelta(hours=24) - timedelta(minutes=1), direct)
    s5, closed = run(s4, ok1 + timedelta(hours=24), direct)
    assert len(still) == 1 and len(almost) == 1 and closed == [] and "source:sx" not in s5["entities"]


# --------------------------------------------------------------- verificación adversaria: lo que la primera pasada dejó

def _raise_by_hand(root: Path) -> None:
    """La función de la lista crece de 15 a 17 y su línea se sube a mano (lo que ``--base-ref`` debe atrapar)."""
    (root / "pkg" / "mod.py").write_text(ifs("old", 17), encoding="utf-8")
    _edit_baseline(root, **{"pkg/mod.py::old": 17})


def _set_tools(root: Path, **tools: str) -> None:
    p = root / C.BASELINE_REL
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["tools"] = {**doc["tools"], **tools}
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def test_an_extra_key_in_the_tools_field_does_not_switch_off_the_base_comparison(tmp_path, capsys):
    """Con la primera versión de ``--base-ref``, cualquier diferencia en el campo «tools» de la lista contaba como
    cambio de herramienta: agregar a mano ``"x": "1"`` (que ``_tool_mismatch`` no mira, porque no se mide) apagaba la
    comparación y la subida a mano salía con 0, también en el job «lint» con ESLint. Ahora cuenta la versión medida.
    Mutación: volver a comparar el campo «tools» de la lista (``return m.langs`` en ``_unchanged_langs``)."""
    root = _committed(mini_repo(tmp_path, ifs("old", 15), {"pkg/mod.py::old": 15}))
    _raise_by_hand(root)
    _set_tools(root, x="1")
    assert _check(root, capsys)[0] == 0  # el código coincide con la lista y la clave de más no se mide
    code, err = _check(root, capsys, "--base-ref", "HEAD")
    assert code == 1 and "pkg/mod.py::old: 15 -> 17 (subió)" in err


def test_a_javascript_tool_change_does_not_let_python_lines_go_up(tmp_path, capsys):
    """Un cambio de ESLint justifica rebaselinear el JavaScript, no subir líneas de Python: con ``--python-only`` (y
    en el job completo, si ESLint cambió de verdad) la versión de ESLint escrita en la lista no abre la puerta a una
    línea de Python subida a mano."""
    root = _committed(mini_repo(tmp_path, ifs("old", 15), {"pkg/mod.py::old": 15}))
    _raise_by_hand(root)
    _set_tools(root, eslint="0.0.1")
    code, err = _check(root, capsys, "--base-ref", "HEAD")
    assert code == 1 and "pkg/mod.py::old: 15 -> 17 (subió)" in err


def test_a_base_with_another_ceiling_is_a_tool_change_and_lets_the_list_be_rewritten(tmp_path, capsys):
    """El límite que el informe declara: si la base tenía otro techo (un PR que cambia ``CEILING`` y rebaselinea), la
    lista puede subir sin que ``--base-ref`` lo frene; el revisor lo ve en el diff de tools/complexity.py. Mutación:
    no mirar el techo de la base (``if False``) bloquea ese --rebaseline."""
    root = mini_repo(tmp_path, ifs("old", 15), {"pkg/mod.py::old": 15})
    p = root / C.BASELINE_REL
    doc = json.loads(p.read_text(encoding="utf-8"))
    p.write_text(json.dumps({**doc, "ceiling": 12}, indent=1) + "\n", encoding="utf-8")
    _committed(root)
    p.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    _raise_by_hand(root)
    assert _check(root, capsys, "--base-ref", "HEAD")[0] == 0


def test_a_feed_down_for_exactly_six_hours_is_a_warning(tmp_path, monkeypatch):
    """«Al menos 6 h» (docs/operaciones.md): la racha empezó a las 19:00 y esta corrida es a la 01:00 del día
    siguiente, 6 h justas. Mutación: ``>= 6`` → ``> 6`` la hace fallar."""
    st, log = _hazard_run(tmp_path, monkeypatch, prev_ok=False, prev_at="2026-11-20T00:20:00+00:00",
                          prev_extra={"downSince": "2026-11-19T19:00:00+00:00"})
    assert st["checkedAt"].startswith("2026-11-20T01:00:00")
    assert [e.source for e in log.events if e.code == "hazard-feed-down"] == ["news-ciifen"]


def test_a_reviewed_list_that_is_not_an_object_is_could_not_audit(tmp_path, monkeypatch, capsys):
    """Una lista JSON en vez del objeto (``[]["findings"]``: TypeError) también es 2, no una traza. Mutación: no
    capturar TypeError en ``known``."""
    monkeypatch.setattr(A, "ROOT", _archive(tmp_path, {"sources/news-ciifen/2026-11-20-aaaa.xml": IMUNIFY}))
    bad = tmp_path / "known.json"
    bad.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(A, "KNOWN", bad)
    assert A.main(["--ref", "HEAD"]) == 2 and "mal formado" in capsys.readouterr().err


def test_a_copy_archived_on_the_first_day_of_the_window_counts(tmp_path, monkeypatch, capsys):
    """La ventana de ``--days`` incluye su primer día (drift-audit.yml: «--days 7 con ">=" cubre 8 días»): una sola
    copia de ese día basta para que la auditoría corra. Mutación: ``>=`` → ``>`` en ``require_copies_in_window``."""
    first = (date.today() - timedelta(days=7)).isoformat()  # la misma cuenta que main (hora local)
    monkeypatch.setattr(A, "ROOT", _archive(tmp_path, {f"sources/news-ciifen/{first}-aaaa.xml": IMUNIFY}))
    monkeypatch.setattr(A, "KNOWN", tmp_path / "none.json")
    assert A.main(["--ref", "HEAD", "--days", "7"]) == 1  # corrió y encontró la página de bloqueo
    assert "archived-block-page" in capsys.readouterr().out


def test_only_the_language_whose_measured_tool_changed_is_let_go():
    """Las versiones vienen de lo medido: ESLint 8 → 9 libera las líneas de JavaScript y deja juzgadas las de Python;
    la regla de Python nueva, al revés; las dos iguales, se juzgan ambas. Mutación: mapear toda versión a «py»."""
    def langs(old_tools: dict, now_tools: dict) -> tuple:
        m = C.Measurement([], now_tools, ("py", "js"))
        return C._unchanged_langs({"ceiling": C.CEILING, "tools": old_tools}, m)

    same = {"python": C.PY_METRIC, "eslint": "9.0.0"}
    assert langs(same, same) == ("py", "js")
    assert langs({**same, "eslint": "8.57.0"}, same) == ("py",)
    assert langs({**same, "python": "ast-nist-1"}, same) == ("js",)
    assert langs({}, same) == ()  # una lista sin versiones (de antes de guardarlas): se rebaselineó


def test_python_only_does_not_judge_javascript_lines_against_the_base_either(tmp_path, capsys):
    """Sin ESLint no se sabe si su versión cambió, así que las líneas de JavaScript no se comparan con la base (como
    tampoco con el código); el job «lint», con ESLint, sí las compara. Mutación: quitar ``_only_langs``."""
    root = _committed(mini_repo(tmp_path, ifs("old", 15), {"pkg/mod.py::old": 15, "web/app.js::draw": 12}))
    _edit_baseline(root, **{"web/app.js::draw": 14})
    assert _check(root, capsys, "--base-ref", "HEAD")[0] == 0
