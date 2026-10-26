"""Sincroniza las incidencias de una corrida con issues de GitHub.

Cada incidencia relevante de ``run-report.json`` (avisos, errores y
críticos, salvo los esperados) se agrupa por su huella (fuente + etapa +
código). Por cada huella:

* si no hay un issue abierto, se crea uno con la etiqueta
  ``incidente-datos`` y la huella en un comentario HTML oculto;
* si ya existe, se actualiza su cuerpo (última vez vista, número de
  corridas) sin añadir comentarios, para no generar ruido;
* los issues abiertos cuya huella ya no aparece se cierran con un
  comentario que indica la corrida en que dejó de ocurrir;
* salvo los de ``STICKY`` (un cambio de formato): que ya no aparezca no
  dice que los valores estén bien, así que se comentan una sola vez (marca
  oculta ``enso-gone`` en el cuerpo) y los cierra una persona. Si vuelve a
  aparecer con el issue aún abierto, se comenta (editar el cuerpo no le
  avisa a nadie) y esa corrida el cuerpo lleva la marca ``enso-again``.

Con ``--dry-run`` solo lee los issues abiertos e imprime lo que haría.

Uso (en GitHub Actions):
    GITHUB_TOKEN=... GITHUB_REPOSITORY=owner/repo \\
    python -m tools.sync_issues --report public/data/run-report.json --run-url URL
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

LABEL = "incidente-datos"
#: Incidencias esperadas que no requieren seguimiento.
IGNORE = {"archive-channel", "carried-forward", "probe-found"}
#: Incidencias que no se cierran solas: alguien tiene que revisar los valores publicados.
STICKY = {"format-drift"}
FP_RE = re.compile(r"<!-- enso-fp:([0-9a-f]+) -->")
COUNT_RE = re.compile(r"<!-- enso-count:(\d+) -->")
CODE_RE = re.compile(r"\*\*Código:\*\* `([^`]+)`")
GONE = "<!-- enso-gone -->"
AGAIN_RE = re.compile(r"\n?<!-- enso-again:[^ ]* -->")


def relevant(events: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for e in events:
        if e["severity"] == "info" or e["code"] in IGNORE:
            continue
        out.setdefault(e["fingerprint"], []).append(e)
    return out


def body_for(fp: str, evs: list[dict], pub: str, run_url: str, count: int, first_seen: str, again: bool = False) -> str:
    e = evs[0]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"**Fuente:** `{e['source']}` · **Etapa:** `{e['stage']}` · **Código:** `{e['code']}` · **Severidad:** {e['severity']}",
        "",
        "**Detalle de la última corrida:**",
        "",
        *[f"> {x['message']}" for x in evs[:5]],
        "",
        f"- Primera vez: {first_seen}",
        f"- Última vez: {now} (publicación `{pub}`)",
        f"- Corridas con esta incidencia: {count}",
        f"- Corrida: {run_url}" if run_url else "",
        "",
        ("Este issue lo abre automáticamente el flujo diario. Un cambio de formato no se cierra solo: ciérrelo después "
         "de revisar que los valores publicados sean coherentes." if e["code"] in STICKY else
         "Este issue lo abre y cierra automáticamente el flujo diario. Se cierra solo cuando la incidencia deja de aparecer."),
        f"<!-- enso-fp:{fp} -->",
        f"<!-- enso-count:{count} -->",
        f"<!-- enso-first:{first_seen} -->",
        f"<!-- enso-again:{pub} -->" if again else None,
    ]
    return "\n".join(l for l in lines if l is not None)


class GitHub:
    def __init__(self, repo: str, token: str):
        self.repo = repo
        self.c = httpx.Client(base_url="https://api.github.com", timeout=30, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "observatorio-enso-peru-incidents",
        })

    def req(self, method: str, path: str, **kw):
        r = self.c.request(method, f"/repos/{self.repo}{path}", **kw)
        r.raise_for_status()
        return r.json() if r.content else None

    def ensure_label(self) -> None:
        try:
            self.req("GET", f"/labels/{LABEL}")
        except httpx.HTTPStatusError:
            self.req("POST", "/labels", json={"name": LABEL, "color": "b60205",
                                              "description": "Incidencia detectada por la actualización diaria de datos"})

    def open_issues(self) -> list[dict]:
        out, page = [], 1
        while True:
            batch = self.req("GET", "/issues", params={"labels": LABEL, "state": "open", "per_page": 100, "page": page})
            out += [i for i in batch if "pull_request" not in i]
            if len(batch) < 100:
                return out
            page += 1


def code_of(issue: dict) -> str:
    """Código de la incidencia de un issue abierto por este flujo (del cuerpo o, si no, del título)."""
    m = CODE_RE.search(issue.get("body") or "")
    return m.group(1) if m else (issue.get("title") or "").rpartition(": ")[2]


def sync(gh: GitHub, report: dict, run_url: str, dry: bool = False) -> dict:
    groups = relevant(report.get("events", []))
    pub = report.get("publicationId", "")
    existing = {}
    for i in gh.open_issues():
        m = FP_RE.search(i.get("body") or "")
        if m:
            existing[m.group(1)] = i
    created = updated = closed = noted = again = 0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    plan = print if dry else (lambda *a: None)
    for fp, evs in groups.items():
        e = evs[0]
        title = f"[datos] {e['source']}: {e['code']}"
        if fp in existing:
            n, body0 = existing[fp]["number"], existing[fp].get("body") or ""
            cm = COUNT_RE.search(body0)
            first = re.search(r"<!-- enso-first:([^ ]+) -->", body0)
            back = code_of(existing[fp]) in STICKY and GONE in body0
            body = body_for(fp, evs, pub, run_url, (int(cm.group(1)) if cm else 1) + 1, first.group(1) if first else today,
                            again=back)
            if back:
                # Ya no se veía y vuelve, con el issue abierto: un comentario avisa a quien lo sigue; el cuerpo no.
                plan(f"comentar #{n} {title} (volvió a aparecer)")
                if not dry:
                    gh.req("POST", f"/issues/{n}/comments", json={"body": "\n".join([
                        f"El cambio de formato volvió a detectarse en la publicación `{pub}`:", "",
                        *[f"> {x['message']}" for x in evs[:5]], "", run_url]).strip()})
                again += 1
            plan(f"actualizar #{n} {title}")
            if not dry:
                gh.req("PATCH", f"/issues/{n}", json={"body": body})
            updated += 1
        else:
            plan(f"abrir {title} ({e['severity']}): {e['message'][:200]}")
            if not dry:
                gh.req("POST", "/issues", json={"title": title, "body": body_for(fp, evs, pub, run_url, 1, today), "labels": [LABEL]})
            created += 1
    for fp, issue in existing.items():
        if fp in groups:
            continue
        n, body0 = issue["number"], issue.get("body") or ""
        if code_of(issue) in STICKY:
            # Que hoy no aparezca no dice que los valores estén bien: se avisa una vez y lo cierra una persona.
            # Si vuelve a aparecer, body_for rehace el cuerpo sin la marca y el aviso vale para la próxima vez.
            if GONE in body0:
                continue
            plan(f"comentar #{n} {issue.get('title')} (ya no aparece; queda abierto)")
            if not dry:
                gh.req("POST", f"/issues/{n}/comments", json={"body": (
                    f"El cambio de formato ya no se detectó en la publicación `{pub}`, pero este issue no se cierra "
                    "solo: revise que los valores publicados de la fuente sean coherentes y ciérrelo a mano.\n\n"
                    f"{run_url}")})
                gh.req("PATCH", f"/issues/{n}", json={"body": f"{AGAIN_RE.sub('', body0)}\n{GONE}"})
            noted += 1
            continue
        plan(f"cerrar #{n} {issue.get('title')}")
        if not dry:
            gh.req("POST", f"/issues/{n}/comments",
                   json={"body": f"La incidencia ya no apareció en la publicación `{pub}`. Se cierra automáticamente.\n\n{run_url}"})
            gh.req("PATCH", f"/issues/{n}", json={"state": "closed", "state_reason": "completed"})
        closed += 1
    return {"created": created, "updated": updated, "closed": closed, "noted": noted, "again": again}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--run-url", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("GITHUB_TOKEN y GITHUB_REPOSITORY son necesarios", file=sys.stderr)
        return 2
    gh = GitHub(repo, token)
    if not args.dry_run:
        gh.ensure_label()
    res = sync(gh, report, args.run_url, args.dry_run)
    print(json.dumps(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
