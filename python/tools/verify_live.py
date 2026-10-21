"""Comprueba que el sitio publicado sirve la publicación recién desplegada.

Consulta ``dashboard.json`` y ``manifest.json`` del sitio en vivo (sin
caché) hasta que su ``publicationId`` coincide con el esperado, o falla
al agotar el tiempo. Así un despliegue «verde» que no llegó al público
no pasa inadvertido.
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="URL del sitio, p. ej. https://pillb.github.io/observatorio-enso-peru/")
    ap.add_argument("--expect", required=True, help="publicationId esperado")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args(argv)
    base = args.base.rstrip("/") + "/"
    deadline = time.monotonic() + args.timeout
    last = None
    with httpx.Client(timeout=30, follow_redirects=True, headers={"Cache-Control": "no-cache"}) as c:
        while time.monotonic() < deadline:
            try:
                ids = {}
                for name in ("data/dashboard.json", "data/manifest.json"):
                    r = c.get(base + name, params={"t": int(time.time())})
                    r.raise_for_status()
                    ids[name] = r.json().get("publicationId")
                page = c.get(base, params={"t": int(time.time())})
                page.raise_for_status()
                last = ids
                if all(v == args.expect for v in ids.values()) and "assets/js/app.js" in page.text:
                    print(f"OK: el sitio en vivo sirve la publicación {args.expect}")
                    return 0
            except (httpx.HTTPError, ValueError) as exc:
                last = f"{type(exc).__name__}: {exc}"
            time.sleep(20)
    print(f"ERROR: el sitio en vivo no sirve {args.expect} tras {args.timeout} s (último: {last})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
