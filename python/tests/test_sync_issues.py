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
    assert res == {"created": 0, "updated": 0, "closed": 1, "noted": 1}
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
    assert res == {"created": 1, "updated": 1, "closed": 1, "noted": 1}
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
