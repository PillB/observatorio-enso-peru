"""Avisa por correo, a las direcciones configuradas, de las incidencias que se abrieron o cerraron en esta corrida.

Los issues de incidencias (etiqueta ``incidente-datos``) ya le llegan por correo a quien sigue el repositorio en
GitHub. Este aviso es para otras personas: las direcciones de la variable del repositorio ``ALERT_EMAILS``
(separadas por comas, punto y coma o espacios), sin cuenta de GitHub.

Se manda un solo correo por corrida, y solo si algo cambió desde ``--since`` (el inicio del job):

* incidencias nuevas (issue abierto en la corrida), con su detalle y enlace;
* incidencias resueltas (issue cerrado en la corrida);
* «La actualización diaria falló» o «El sitio publicado está desactualizado» que vuelven a ocurrir (comentario
  nuevo en su issue abierto).

Una incidencia que sigue igual que ayer no manda correo (no se repite cada día).

El correo sale por SMTP con los secretos ``SMTP_HOST``, ``SMTP_PORT`` (465: TLS directo; otro: STARTTLS),
``SMTP_USERNAME`` y ``SMTP_PASSWORD``; el remitente es la variable ``ALERT_FROM`` (o ``SMTP_USERNAME``). Sin
direcciones o sin ``SMTP_HOST`` no hace nada. Un fallo al enviar se anota en la corrida y no la detiene.

Uso (en GitHub Actions):
    GITHUB_TOKEN=... GITHUB_REPOSITORY=owner/repo ALERT_EMAILS=a@x.pe,b@y.pe SMTP_HOST=... \\
    python -m tools.alert_email --since 2026-10-22T00:00:00Z --run-url URL
"""

from __future__ import annotations

import argparse
import os
import re
import smtplib
import ssl
import sys
from email.message import EmailMessage
from typing import Optional

import httpx

LABEL = "incidente-datos"
#: Issues fijos que se reabren con comentarios en vez de cerrarse (la corrida falló, el sitio está atrasado).
RECURRING = re.compile(r"<!-- enso-fp:(run-failed|site-stale) -->")
_EMAIL = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


def recipients(raw: Optional[str]) -> list[str]:
    """Direcciones válidas de ``ALERT_EMAILS``, sin repetir; las que no parecen correo se ignoran."""
    out = []
    for a in re.split(r"[,;\s]+", raw or ""):
        a = a.strip()
        if a and _EMAIL.match(a) and a.lower() not in {x.lower() for x in out}:
            out.append(a)
    return out


def changes(issues: list[dict], since: str) -> dict:
    """Clasifica los issues de incidencias que cambiaron desde ``since`` (ISO 8601, UTC)."""
    new, resolved, again = [], [], []
    for i in issues:
        if "pull_request" in i:
            continue
        if (i.get("created_at") or "") >= since:
            new.append(i)
        elif i.get("state") == "closed" and (i.get("closed_at") or "") >= since:
            resolved.append(i)
        elif i.get("state") == "open" and RECURRING.search(i.get("body") or "") and (i.get("updated_at") or "") >= since:
            again.append(i)
    return {"new": new, "resolved": resolved, "again": again}


def _detail(body: str) -> str:
    """Primera línea del detalle del issue (lo que dice la incidencia), sin los comentarios ocultos."""
    quoted = [l[2:].strip() for l in (body or "").splitlines() if l.startswith("> ")]
    text = quoted[0] if quoted else re.sub(r"<!--.*?-->", "", body or "", flags=re.S).strip().split("\n")[0]
    return text[:600]


def compose(ch: dict, repo: str, run_url: str) -> Optional[tuple[str, str]]:
    """(asunto, cuerpo) del correo, o ``None`` si no hay nada que avisar."""
    n, r, a = len(ch["new"]), len(ch["resolved"]), len(ch["again"])
    if not (n or r or a):
        return None
    parts = []
    if n:
        parts.append(f"{n} incidencia{'s' if n > 1 else ''} nueva{'s' if n > 1 else ''}")
    if a:
        parts.append(f"{a} que se repite{'n' if a > 1 else ''}")
    if r:
        parts.append(f"{r} resuelta{'s' if r > 1 else ''}")
    subject = f"[Observatorio ENSO] {', '.join(parts)}"
    lines = [f"Cambios en las incidencias de datos de {repo}.", ""]
    for title, items in (("Nuevas", ch["new"]), ("Se repiten", ch["again"]), ("Resueltas", ch["resolved"])):
        if not items:
            continue
        lines += [f"{title}:", ""]
        for i in items:
            lines.append(f"- {i.get('title')}")
            if title != "Resueltas":
                d = _detail(i.get("body") or "")
                if d:
                    lines.append(f"  {d}")
            lines += [f"  {i.get('html_url')}", ""]
    if run_url:
        lines += [f"Corrida: {run_url}", ""]
    lines.append("Este correo lo envía la actualización automática del observatorio. Las direcciones se configuran en "
                 "la variable ALERT_EMAILS del repositorio (Settings → Secrets and variables → Actions → Variables).")
    return subject, "\n".join(lines)


def send(subject: str, body: str, to: list[str], env: dict, smtp_cls=None) -> None:
    host = env["SMTP_HOST"]
    port = int(env.get("SMTP_PORT") or 587)
    user, password = env.get("SMTP_USERNAME") or "", env.get("SMTP_PASSWORD") or ""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = env.get("ALERT_FROM") or user
    msg["To"] = msg["From"]
    msg["Bcc"] = ", ".join(to)  # cada destinatario no ve las direcciones de los demás
    msg.set_content(body)
    ctx = ssl.create_default_context()
    if smtp_cls is None:
        smtp_cls = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
    kw = {"context": ctx} if port == 465 and smtp_cls is smtplib.SMTP_SSL else {}
    with smtp_cls(host, port, timeout=30, **kw) as s:
        if port != 465:
            s.starttls(context=ctx)
        if user:
            s.login(user, password)
        s.send_message(msg)


def fetch_issues(repo: str, token: str, since: str) -> list[dict]:
    out, page = [], 1
    with httpx.Client(base_url="https://api.github.com", timeout=30, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "observatorio-enso-peru-alerts",
    }) as c:
        while True:
            r = c.get(f"/repos/{repo}/issues", params={"labels": LABEL, "state": "all", "since": since,
                                                       "per_page": 100, "page": page})
            r.raise_for_status()
            batch = r.json()
            out += batch
            if len(batch) < 100:
                return out
            page += 1


def main(argv=None, env=None) -> int:
    env = dict(os.environ) if env is None else env
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True, help="inicio del job, ISO 8601 UTC (2026-10-22T00:00:00Z)")
    ap.add_argument("--run-url", default="")
    ap.add_argument("--dry-run", action="store_true", help="muestra el correo sin enviarlo")
    a = ap.parse_args(argv)
    to = recipients(env.get("ALERT_EMAILS"))
    if not to:
        print("ALERT_EMAILS vacía: no se envía correo.")
        return 0
    if not env.get("SMTP_HOST") and not a.dry_run:
        print("::warning::ALERT_EMAILS está configurada pero falta el secreto SMTP_HOST: no se envía el correo de alertas.")
        return 0
    repo, token = env.get("GITHUB_REPOSITORY"), env.get("GITHUB_TOKEN")
    if not repo or not token:
        print("GITHUB_TOKEN y GITHUB_REPOSITORY son necesarios", file=sys.stderr)
        return 2
    try:
        mail = compose(changes(fetch_issues(repo, token, a.since), a.since), repo, a.run_url)
    except httpx.HTTPError as e:
        print(f"::warning::No se pudieron leer los issues de incidencias para el correo: {e}")
        return 0
    if mail is None:
        print("Sin incidencias nuevas, repetidas ni resueltas: no se envía correo.")
        return 0
    if a.dry_run:
        print(f"Para: {', '.join(to)}\nAsunto: {mail[0]}\n\n{mail[1]}")
        return 0
    try:
        send(*mail, to, env)
    except (OSError, smtplib.SMTPException) as e:
        print(f"::warning::No se pudo enviar el correo de alertas a {len(to)} direcciones: {type(e).__name__}: {e}")
        return 0
    print(f"Correo enviado a {len(to)} direcciones: {mail[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
