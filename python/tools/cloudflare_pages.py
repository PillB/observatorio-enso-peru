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
    except (RuntimeError, httpx.HTTPError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(url)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"url={url}\nbranch={branch}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
