"""Incidencias de la corrida ↔ issues de GitHub (tools.sync_issues), con un GitHub de mentira."""

from __future__ import annotations

import json

from tools import sync_issues as S


class FakeGitHub:
    """Issues abiertos en memoria; anota cada escritura."""

    def __init__(self, issues: list[dict]):
        self.issues = {i["number"]: dict(i) for i in issues}
        self.calls: list[tuple[str, str, dict]] = []

    def open_issues(self) -> list[dict]:
        return [dict(i) for i in self.issues.values() if i.get("state", "open") == "open"]

    def req(self, method: str, path: str, **kw):
        self.calls.append((method, path, kw.get("json") or {}))
        if method == "POST" and path == "/issues":
            n = max(self.issues, default=0) + 1
            self.issues[n] = {"number": n, "state": "open", **kw["json"]}
            return self.issues[n]
        if method == "PATCH":
            self.issues[int(path.rsplit("/", 1)[1])].update(kw["json"])
        return None

    def writes(self, number: int) -> list[str]:
        return [m for m, p, _ in self.calls if p.startswith(f"/issues/{number}")]


def _event(source: str, code: str, stage: str = "parse", severity: str = "warning") -> dict:
    from enso.observatory import Event

    return Event(severity, source, stage, code, f"{source}: {code}").as_dict()


def _issue(number: int, ev: dict, count: int = 3) -> dict:
    return {"number": number, "title": f"[datos] {ev['source']}: {ev['code']}", "state": "open",
            "body": S.body_for(ev["fingerprint"], [ev], "pub-1", "", count, "2026-10-20")}


DRIFT = _event("cpc-roni", "format-drift")
STALE = _event("relay-peru", "relay-stale", stage="fetch")


def test_format_drift_stays_open_until_a_person_closes_it():
    """Revisión: el issue de un cambio de formato se cerraba en la corrida siguiente, antes de que alguien revisara
    los valores. Ahora se comenta una sola vez y queda abierto; un aviso común se cierra como siempre."""
    gh = FakeGitHub([_issue(29, DRIFT), _issue(30, STALE)])
    res = S.sync(gh, {"publicationId": "pub-2", "events": []}, "https://run/2")
    assert res == {"created": 0, "updated": 0, "closed": 1, "noted": 1, "again": 0}
    assert gh.issues[29]["state"] == "open" and gh.issues[30]["state"] == "closed"
    comment = next(j["body"] for m, p, j in gh.calls if p == "/issues/29/comments")
    assert "pub-2" in comment and "ciérrelo a mano" in comment and "https://run/2" in comment
    assert S.GONE in gh.issues[29]["body"]
    # La corrida siguiente no vuelve a comentar ni lo cierra.
    gh.calls.clear()
    assert S.sync(gh, {"publicationId": "pub-3", "events": []}, "")["noted"] == 0
    assert gh.calls == [] and gh.issues[29]["state"] == "open"
    # Si el cambio vuelve a aparecer, el cuerpo se rehace sin la marca: la próxima vez que deje de verse, se avisa.
    S.sync(gh, {"publicationId": "pub-4", "events": [DRIFT]}, "")
    assert S.GONE not in gh.issues[29]["body"] and "<!-- enso-count:4 -->" in gh.issues[29]["body"]
    gh.calls.clear()
    S.sync(gh, {"publicationId": "pub-5", "events": []}, "")
    assert gh.writes(29) == ["POST", "PATCH"] and gh.issues[29]["state"] == "open"
    assert "enso-again" not in gh.issues[29]["body"]


def test_a_format_drift_that_comes_back_on_an_open_issue_is_commented():
    """Revisión: un cambio de formato que ya no se veía (marca enso-gone) y vuelve con el issue aún abierto solo
    editaba el cuerpo, y editar no le avisa a nadie. Ahora se comenta (una vez por regreso) y el cuerpo de esa
    corrida lleva la marca enso-again; mientras siga apareciendo, no se repite."""
    gh = FakeGitHub([_issue(29, DRIFT)])
    S.sync(gh, {"publicationId": "pub-2", "events": []}, "")
    gh.calls.clear()
    res = S.sync(gh, {"publicationId": "pub-3", "events": [DRIFT]}, "https://run/3")
    assert res == {"created": 0, "updated": 1, "closed": 0, "noted": 0, "again": 1}
    assert [(m, p) for m, p, _ in gh.calls] == [("POST", "/issues/29/comments"), ("PATCH", "/issues/29")]
    comment = gh.calls[0][2]["body"]
    assert "volvió a detectarse" in comment and "pub-3" in comment and DRIFT["message"] in comment
    assert comment.endswith("https://run/3")
    body = gh.issues[29]["body"]
    assert S.GONE not in body and "<!-- enso-again:pub-3 -->" in body and "<!-- enso-count:4 -->" in body
    gh.calls.clear()
    assert S.sync(gh, {"publicationId": "pub-4", "events": [DRIFT]}, "")["again"] == 0
    assert gh.writes(29) == ["PATCH"] and "enso-again" not in gh.issues[29]["body"]
    # Si vuelve y al día siguiente ya no aparece, la marca de regreso no queda en el cuerpo.
    S.sync(gh, {"publicationId": "pub-5", "events": []}, "")
    S.sync(gh, {"publicationId": "pub-6", "events": [DRIFT]}, "")
    S.sync(gh, {"publicationId": "pub-7", "events": []}, "")
    assert gh.issues[29]["body"].endswith(S.GONE) and "enso-again" not in gh.issues[29]["body"]
    # Un aviso común que sigue igual no comenta.
    gh = FakeGitHub([_issue(30, STALE)])
    assert S.sync(gh, {"publicationId": "pub-2", "events": [STALE]}, "")["again"] == 0 and gh.writes(30) == ["PATCH"]


def test_a_new_format_drift_issue_says_it_is_closed_by_hand():
    gh = FakeGitHub([])
    S.sync(gh, {"publicationId": "pub-1", "events": [DRIFT, STALE]}, "")
    drift, stale = (next(i for i in gh.issues.values() if i["title"].endswith(c)) for c in ("format-drift", "relay-stale"))
    assert "no se cierra solo" in drift["body"] and "Se cierra solo cuando" in stale["body"]
    assert S.code_of(drift) == "format-drift" and S.code_of({"title": "[datos] x: format-drift"}) == "format-drift"


def test_dry_run_reads_but_never_writes_and_prints_the_plan(capsys):
    gh = FakeGitHub([_issue(29, DRIFT), _issue(30, STALE), _issue(31, _event("igp-icen", "unreachable", "fetch"))])
    report = {"publicationId": "pub-2", "events": [_event("igp-icen", "unreachable", "fetch"), _event("dhn", "nuevo")]}
    res = S.sync(gh, report, "", dry=True)
    assert res == {"created": 1, "updated": 1, "closed": 1, "noted": 1, "again": 0}
    assert gh.calls == []
    out = capsys.readouterr().out
    assert "abrir [datos] dhn: nuevo" in out and "actualizar #31" in out and "cerrar #30" in out
    assert "comentar #29" in out and "queda abierto" in out


def test_main_dry_run_does_not_create_the_label(tmp_path, monkeypatch, capsys):
    gh = FakeGitHub([_issue(30, STALE)])
    monkeypatch.setattr(S, "GitHub", lambda repo, token: gh)
    gh.ensure_label = lambda: gh.calls.append(("POST", "/labels", {}))
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    report = tmp_path / "run-report.json"
    report.write_text(json.dumps({"publicationId": "pub-2", "events": []}), encoding="utf-8")
    assert S.main(["--report", str(report), "--dry-run"]) == 0
    assert gh.calls == [] and gh.issues[30]["state"] == "open"
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["closed"] == 1


def test_dry_run_shows_a_format_drift_that_comes_back(capsys):
    gh = FakeGitHub([_issue(29, DRIFT)])
    gh.issues[29]["body"] += "\n" + S.GONE
    res = S.sync(gh, {"publicationId": "pub-2", "events": [DRIFT]}, "", dry=True)
    assert res["again"] == 1 and gh.calls == []
    assert "comentar #29 [datos] cpc-roni: format-drift (volvió a aparecer)" in capsys.readouterr().out
