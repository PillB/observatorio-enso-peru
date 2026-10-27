"""Ajusta el sitio construido a la dirección pública donde se despliega.

El código fuente del sitio (``public/``) usa la dirección de GitHub Pages.
Antes de desplegar en otro servidor (Cloudflare Pages), este paso:

* reescribe la URL canónica, Open Graph, ``robots.txt`` y ``sitemap.xml``
  con la nueva dirección, y las rutas absolutas de ``404.html`` con su ruta;
* con ``--hide-repo``, quita del sitio los enlaces al repositorio de GitHub
  (pie de página, «Acerca de» e incidencias), para que el sitio publicado
  no remita al código;
* con ``--cloudflare``, escribe ``_headers`` con cabeceras de seguridad y
  CORS abierto para los datos (Cloudflare Pages lo lee al desplegar).

Uso:
    python -m tools.prepare_site --site-dir ../public \
        --site-url https://observatorio-enso.pages.dev/ --hide-repo --cloudflare
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_URL = "https://pillb.github.io/observatorio-enso-peru/"
DEFAULT_PATH = "/observatorio-enso-peru/"
REPO_HOST = "github.com/PillB/observatorio-enso-peru"
TEXT_FILES = ("index.html", "404.html", "robots.txt", "sitemap.xml", "manifest.webmanifest")

HEADERS = """\
/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  X-Frame-Options: SAMEORIGIN
  Permissions-Policy: camera=(), microphone=(), payment=(), usb=()

/data/*
  Access-Control-Allow-Origin: *
  Cache-Control: public, max-age=0, must-revalidate

/data/archive/*
  Content-Security-Policy: sandbox; default-src 'none'; style-src 'unsafe-inline'

/admin/*
  X-Robots-Tag: noindex, nofollow
  Cache-Control: no-store
  Referrer-Policy: no-referrer
  Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'
"""


def prepare(site_dir: Path, site_url: str, hide_repo: bool, cloudflare: bool) -> list[str]:
    if not re.match(r"^https://[^/]+(/.*)?$", site_url):
        raise ValueError(f"dirección no válida: {site_url!r} (debe empezar con https://)")
    site_url = site_url.rstrip("/") + "/"
    path = urlsplit(site_url).path or "/"
    changed = []
    for name in TEXT_FILES:
        p = site_dir / name
        if not p.exists():
            continue
        s = orig = p.read_text(encoding="utf-8")
        s = s.replace(DEFAULT_URL, site_url)
        if name == "404.html":
            s = s.replace(f'"{DEFAULT_PATH}', f'"{path}')
        if hide_repo and name == "index.html":
            s = re.sub(r"\s*<!-- repo-links -->.*?<!-- /repo-links -->", "", s, flags=re.S)
        if s != orig:
            p.write_text(s, encoding="utf-8")
            changed.append(name)
    if hide_repo:
        p = site_dir / "assets" / "js" / "content.js"
        s = orig = p.read_text(encoding="utf-8")
        s = re.sub(r"(\n\s*(?:repo|issues|githubSponsors): )'[^']*'", r"\1''", s)
        if s != orig:
            p.write_text(s, encoding="utf-8")
            changed.append("assets/js/content.js")
        leaks = sorted(str(f.relative_to(site_dir)) for f in site_dir.rglob("*")
                       if f.is_file() and f.suffix in {".html", ".js", ".css", ".json", ".xml", ".txt", ".svg", ".webmanifest"}
                       and REPO_HOST.lower() in f.read_text(encoding="utf-8", errors="ignore").lower())
        # Los datos no detienen la publicación (un aviso a tiempo pesa más);
        # el código del sitio sí, porque eso se corrige antes de fusionar.
        data = [x for x in leaks if x.startswith("data/")]
        if data:
            print(f"::warning::los datos publicados mencionan el repositorio: {', '.join(data)}")
        code = [x for x in leaks if not x.startswith("data/")]
        if code:
            raise RuntimeError("el sitio todavía enlaza al repositorio en: " + ", ".join(code))
    if cloudflare:
        (site_dir / "_headers").write_text(HEADERS, encoding="utf-8")
        changed.append("_headers")
    return changed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--site-dir", required=True, type=Path)
    ap.add_argument("--site-url", required=True)
    ap.add_argument("--hide-repo", action="store_true", help="quitar los enlaces al repositorio de GitHub")
    ap.add_argument("--cloudflare", action="store_true", help="escribir _headers para Cloudflare Pages")
    args = ap.parse_args(argv)
    try:
        changed = prepare(args.site_dir, args.site_url, args.hide_repo, args.cloudflare)
    except (ValueError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"sitio preparado para {args.site_url}: {', '.join(changed) or 'sin cambios'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
