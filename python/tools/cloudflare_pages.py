"""Crea, si falta, el proyecto de Cloudflare Pages del observatorio e imprime
su dirección pública (``https://<subdominio>.pages.dev/``). En GitHub Actions
escribe además ``url`` y ``branch`` (la rama de producción del proyecto, a la
que hay que desplegar para que no quede como vista previa) en
``$GITHUB_OUTPUT``.

Lee ``CLOUDFLARE_API_TOKEN`` (permiso «Cloudflare Pages: Edit» de la cuenta)
y ``CLOUDFLARE_ACCOUNT_ID`` del entorno. El despliegue en sí lo hace
``wrangler pages deploy`` en el flujo diario; este paso solo garantiza que el
proyecto exista y averigua su subdominio, que Cloudflare puede alterar si el
nombre ya está tomado por otra cuenta.

También revisa (solo nombres, nunca valores) que el entorno de producción
tenga lo que pide la suscripción al boletín (``functions/_lib/boletin-subs.js``)
y avisa en el registro si falta algo o si solo está en «Preview». Si en el
entorno de este paso hay secretos ``BOLETIN_*`` (secretos de GitHub Actions),
los copia al entorno de producción del proyecto antes de desplegar: así se
pueden cargar desde GitHub en vez de desde el panel de Cloudflare.

Uso:
    python -m tools.cloudflare_pages --project observatorio-enso
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx

API = "https://api.cloudflare.com/client/v4/accounts/{account}/pages/projects"


def ensure_project(client: httpx.Client, account: str, project: str, branch: str) -> tuple[str, str]:
    """Devuelve la dirección pública y la rama de producción del proyecto."""
    base = API.format(account=account)
    r = client.get(f"{base}/{project}")
    if r.status_code == 404:
        r = client.post(base, json={"name": project, "production_branch": branch})
        if r.status_code >= 400:
            raise RuntimeError(f"no se pudo crear el proyecto «{project}»: HTTP {r.status_code} {_errors(r)}")
        print(f"proyecto «{project}» creado en Cloudflare Pages", file=sys.stderr)
    elif r.status_code in (401, 403):
        raise RuntimeError(f"Cloudflare rechazó el token (HTTP {r.status_code}): revise que tenga el permiso "
                           f"«Account · Cloudflare Pages · Edit» y que CLOUDFLARE_ACCOUNT_ID sea correcto. {_errors(r)}")
    elif r.status_code != 200:
        raise RuntimeError(f"Cloudflare respondió HTTP {r.status_code}: {_errors(r)}")
    result = r.json().get("result") or {}
    subdomain = result.get("subdomain")
    if not subdomain:
        raise RuntimeError("Cloudflare no devolvió el subdominio del proyecto")
    production = result.get("production_branch") or branch
    if production != branch:
        print(f"aviso: la rama de producción del proyecto es «{production}»; se despliega a esa rama", file=sys.stderr)
    return f"https://{subdomain}/", production


# Lo que la suscripción al boletín necesita en producción (ver functions/_lib/boletin-subs.js).
BOLETIN_SYNC = ("BOLETIN_SECRET", "BOLETIN_LIST_TOKEN", "BOLETIN_MAIL_WEBHOOK", "BOLETIN_MAIL_WEBHOOK_SECRET")


def boletin_report(project: dict) -> list[str]:
    """Avisos (solo nombres) sobre la configuración de producción que pide la suscripción al boletín."""
    cfgs = project.get("deployment_configs") or {}
    prod, prev = cfgs.get("production") or {}, cfgs.get("preview") or {}
    have = {k for k, v in (prod.get("env_vars") or {}).items() if v is not None}
    in_preview = {k for k, v in (prev.get("env_vars") or {}).items() if v is not None}
    need = ["BOLETIN_SECRET", "BOLETIN_LIST_TOKEN"]
    if not {"RESEND_API_KEY", "BOLETIN_FROM"} <= have:
        need += ["BOLETIN_MAIL_WEBHOOK", "BOLETIN_MAIL_WEBHOOK_SECRET"]
    out = []
    for name in need:
        if name not in have:
            where = " (está en «Preview», no en «Production»)" if name in in_preview else ""
            out.append(f"falta {name} en el entorno de producción de Cloudflare Pages{where}: la suscripción al boletín queda apagada")
    if "GEO_DB" not in (prod.get("d1_databases") or {}):
        out.append("falta el vínculo D1 GEO_DB en el entorno de producción")
    return out


def sync_secrets(client: httpx.Client, account: str, project: str, values: dict[str, str]) -> dict:
    """Copia secretos al entorno de producción (los demás quedan como están) y devuelve el proyecto actualizado."""
    body = {"deployment_configs": {"production": {"env_vars": {k: {"type": "secret_text", "value": v} for k, v in values.items()}}}}
    r = client.patch(f"{API.format(account=account)}/{project}", json=body)
    if r.status_code >= 400:
        raise RuntimeError(f"no se pudieron guardar {', '.join(values)} en Cloudflare: HTTP {r.status_code} {_errors(r)}")
    return r.json().get("result") or {}


def check_boletin(client: httpx.Client, account: str, project: str, env: dict) -> list[str]:
    """Copia los secretos BOLETIN_* que vengan en ``env`` (sin espacios de más) y devuelve los avisos."""
    values = {k: env[k].strip() for k in BOLETIN_SYNC if (env.get(k) or "").strip()}
    if values:
        result = sync_secrets(client, account, project, values)
        print(f"copiados a producción desde GitHub: {', '.join(values)}", file=sys.stderr)
    else:
        r = client.get(f"{API.format(account=account)}/{project}")
        result = (r.json().get("result") or {}) if r.status_code == 200 else {}
    return boletin_report(result)


def _errors(r: httpx.Response) -> str:
    try:
        return "; ".join(e.get("message", "") for e in r.json().get("errors", []))[:300]
    except ValueError:
        return r.text[:300]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--project", required=True)
    ap.add_argument("--production-branch", default="main")
    args = ap.parse_args(argv)
    token, account = os.environ.get("CLOUDFLARE_API_TOKEN"), os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if not token or not account:
        print("ERROR: faltan los secretos CLOUDFLARE_API_TOKEN y/o CLOUDFLARE_ACCOUNT_ID", file=sys.stderr)
        return 1
    try:
        with httpx.Client(timeout=30, headers={"Authorization": f"Bearer {token}"}) as c:
            url, branch = ensure_project(c, account, args.project, args.production_branch)
            try:
                warnings = check_boletin(c, account, args.project, os.environ)
            except (RuntimeError, httpx.HTTPError, ValueError) as e:
                warnings = [f"no se pudo revisar la configuración del boletín: {e}"]
    except (RuntimeError, httpx.HTTPError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    for w in warnings:
        # Anotación visible en el resumen de la ejecución de GitHub Actions; no detiene el despliegue.
        print(f"::warning title=Boletín::{w}" if os.environ.get("GITHUB_ACTIONS") else f"aviso: {w}", file=sys.stderr)
    print(url)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"url={url}\nbranch={branch}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
