"""Correo de alertas a las direcciones de ALERT_EMAILS: solo lo que cambió en la corrida."""

from __future__ import annotations

from tools import alert_email as A

SINCE = "2026-10-22T06:00:00Z"


def _issue(n, title, created, state="open", closed=None, updated=None, body=""):
    return {"number": n, "title": title, "created_at": created, "state": state, "closed_at": closed,
            "updated_at": updated or created, "body": body, "html_url": f"https://github.com/o/r/issues/{n}"}


NEW = _issue(40, "[datos] imarpe-bsobp: bsobp-unreadable", "2026-10-22T06:05:00Z",
             body="**Fuente:** x\n\n> Boletín semanal IMARPE N° 43-2026: el PDF no se pudo bajar.\n\n<!-- enso-fp:abc -->")
OLD_SAME = _issue(30, "[datos] cpc: stale", "2026-10-20T06:05:00Z", updated="2026-10-22T06:06:00Z",
                  body="> sigue atrasado\n<!-- enso-fp:def -->")
CLOSED = _issue(31, "[datos] enfen: unreachable", "2026-10-19T06:05:00Z", state="closed",
                closed="2026-10-22T06:07:00Z", updated="2026-10-22T06:07:00Z")
FAILED_AGAIN = _issue(5, "[datos] La actualización diaria falló", "2026-10-10T06:00:00Z",
                      updated="2026-10-22T06:30:00Z", body="La corrida falló.\n\n<!-- enso-fp:run-failed -->")


def test_recipients_are_parsed_deduplicated_and_validated():
    assert A.recipients("a@x.pe, b@y.com;A@x.pe  no-es-correo\nc@z.org") == ["a@x.pe", "b@y.com", "c@z.org"]
    assert A.recipients("") == [] and A.recipients(None) == []


def test_only_changes_in_this_run_are_mailed():
    ch = A.changes([NEW, OLD_SAME, CLOSED, FAILED_AGAIN, {"pull_request": {}, "created_at": SINCE}], SINCE)
    assert [i["number"] for i in ch["new"]] == [40]
    assert [i["number"] for i in ch["resolved"]] == [31]
    assert [i["number"] for i in ch["again"]] == [5]  # una incidencia común que sigue igual no se repite


def test_compose_names_each_issue_with_its_detail_and_link():
    subject, body = A.compose(A.changes([NEW, CLOSED, FAILED_AGAIN], SINCE), "o/r", "https://run")
    assert subject == "[Observatorio ENSO] 1 incidencia nueva, 1 que se repite, 1 resuelta"
    assert "Boletín semanal IMARPE N° 43-2026: el PDF no se pudo bajar." in body
    assert "https://github.com/o/r/issues/40" in body and "Corrida: https://run" in body
    assert "enso-fp" not in body
    assert A.compose(A.changes([OLD_SAME], SINCE), "o/r", "") is None


class _SMTP:
    sent = []

    def __init__(self, host, port, timeout=None, **kw):
        self.host, self.port, self.calls = host, port, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, u, p):
        self.calls.append(("login", u))

    def send_message(self, msg):
        _SMTP.sent.append((self, msg))


def test_send_uses_bcc_and_starttls():
    _SMTP.sent.clear()
    A.send("asunto", "cuerpo", ["a@x.pe", "b@y.com"], {"SMTP_HOST": "smtp.x", "SMTP_PORT": "587",
                                                     "SMTP_USERNAME": "bot@x.pe", "SMTP_PASSWORD": "p"}, smtp_cls=_SMTP)
    s, msg = _SMTP.sent[0]
    assert s.calls == ["starttls", ("login", "bot@x.pe")]
    assert msg["Bcc"] == "a@x.pe, b@y.com" and msg["From"] == "bot@x.pe" and msg["Subject"] == "asunto"


def test_without_addresses_or_smtp_nothing_is_sent(capsys):
    assert A.main(["--since", SINCE], env={}) == 0
    assert "ALERT_EMAILS vacía" in capsys.readouterr().out
    assert A.main(["--since", SINCE], env={"ALERT_EMAILS": "a@x.pe"}) == 0
    assert "falta el secreto SMTP_HOST" in capsys.readouterr().out


def test_send_failure_is_a_warning_not_a_failed_run(monkeypatch, capsys):
    monkeypatch.setattr(A, "fetch_issues", lambda *a: [NEW])

    def boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(A, "send", boom)
    env = {"ALERT_EMAILS": "a@x.pe", "SMTP_HOST": "smtp.x", "GITHUB_REPOSITORY": "o/r", "GITHUB_TOKEN": "t"}
    assert A.main(["--since", SINCE], env=env) == 0
    assert "::warning::No se pudo enviar" in capsys.readouterr().out


def test_failure_issue_closed_later_in_the_same_job_is_mailed_as_resolved():
    # El paso del correo va al final del job: el cierre de «La actualización diaria falló» de esta corrida
    # (después de ALERT_SINCE) sale como resuelto, no queda sin aviso.
    closed_now = _issue(5, "[datos] La actualización diaria falló", "2026-10-10T06:00:00Z", state="closed",
                        closed="2026-10-22T06:40:00Z", updated="2026-10-22T06:40:00Z",
                        body="La corrida falló.\n\n<!-- enso-fp:run-failed -->")
    ch = A.changes([closed_now], SINCE)
    assert [i["number"] for i in ch["resolved"]] == [5] and not ch["again"]
    assert A.compose(ch, "o/r", "")[0] == "[Observatorio ENSO] 1 resuelta"


def test_silent_collector_reminders_and_returning_format_drift_are_mailed_again():
    """El vigilante recuerda una vez al día un recolector callado, y un cambio de formato que vuelve con el issue
    abierto se comenta: los dos llegan también a quien no sigue el repositorio en GitHub."""
    silent = _issue(7, "[datos] El recolector del Perú no da señales (data-peru)", "2026-10-20T06:00:00Z",
                    updated="2026-10-22T06:20:00Z", body="El último latido…\n\n<!-- enso-fp:collector-silent-data-peru -->")
    back = _issue(8, "[datos] cpc-roni: format-drift", "2026-10-15T06:00:00Z", updated="2026-10-22T06:21:00Z",
                  body="> huella cambió\n<!-- enso-fp:0a1b2c3d4e -->\n<!-- enso-again:20261022T0600Z-ab -->")
    gone = _issue(9, "[datos] cpc-oni: format-drift", "2026-10-15T06:00:00Z", updated="2026-10-22T06:22:00Z",
                  body="> huella cambió\n<!-- enso-fp:1a1b2c3d4e -->\n<!-- enso-gone -->")
    ch = A.changes([silent, back, gone], SINCE)
    assert [i["number"] for i in ch["again"]] == [7, 8]  # el «ya no se detectó» no es una repetición
    # Un recordatorio de un día anterior no vuelve a mandar correo.
    assert not A.changes([{**silent, "updated_at": "2026-10-21T06:20:00Z"}], SINCE)["again"]
