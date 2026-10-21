"""Genera las cuentas de la consola de lugares: contraseñas al azar y el secreto ``GEO_USERS`` con sus hashes.

Las contraseñas se escriben solo en ``--out`` (fuera del repositorio) para repartirlas a cada revisor; el
secreto lleva únicamente hashes PBKDF2-SHA256 (100 000 iteraciones, sal de 16 bytes), el formato que
verifica ``functions/_lib/geo-console.js``. Para cargarlo en Cloudflare:

    npx wrangler pages secret put GEO_USERS --project-name enso-peru < DIR/GEO_USERS.json

o pegar el contenido del archivo en el panel (Pages → proyecto → Settings → Variables and Secrets).

Uso:
    python -m tools.geo_users --out DIR [--testers 10] [--admin pablo] [--keep DIR/GEO_USERS.json]

``--keep`` conserva las cuentas de un secreto anterior y solo agrega o renueva las que se pidan
(``--renew usuario`` cambia la contraseña de esa cuenta).
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

ITERATIONS = 100_000
#: Sin caracteres que se confunden al dictarlos o copiarlos (0/O, 1/l/I).
ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_password(length: int = 16) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def hash_password(password: str, salt: bytes | None = None, iterations: int = ITERATIONS) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations, dklen=32)
    return f"pbkdf2-sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify(password: str, stored: str) -> bool:
    algo, it, salt, dk = stored.split("$")
    got = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(it), dklen=32)
    return algo == "pbkdf2-sha256" and secrets.compare_digest(got, base64.b64decode(dk))


def build(testers: int, admin: str | None, keep: dict | None = None, renew: tuple[str, ...] = ()) -> tuple[dict, list[tuple[str, str, str]]]:
    """(secreto, [(usuario, rol, contraseña)] de las cuentas nuevas o renovadas)."""
    users = dict(keep or {})
    wanted = [(admin, "admin")] if admin else []
    wanted += [(f"revisor{n:02d}", "tester") for n in range(1, testers + 1)]
    issued = []
    for name, role in wanted:
        if name in users and name not in renew:
            continue
        pw = new_password()
        users[name] = {"hash": hash_password(pw), "role": role}
        issued.append((name, role, pw))
    for name in renew:
        if name in users and not any(n == name for n, _, _ in issued):
            pw = new_password()
            users[name] = {"hash": hash_password(pw), "role": users[name].get("role", "tester")}
            issued.append((name, users[name]["role"], pw))
    return users, issued


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, required=True, help="carpeta fuera del repositorio")
    ap.add_argument("--testers", type=int, default=10)
    ap.add_argument("--admin", default="pablo")
    ap.add_argument("--keep", type=Path, help="GEO_USERS.json anterior")
    ap.add_argument("--renew", action="append", default=[], help="usuario cuya contraseña se renueva")
    a = ap.parse_args(argv)
    repo = Path(__file__).resolve().parents[2]
    if a.out.resolve().is_relative_to(repo):
        print("ERROR: --out debe estar fuera del repositorio (las contraseñas no se suben nunca).", file=sys.stderr)
        return 2
    keep = json.loads(a.keep.read_text(encoding="utf-8")) if a.keep else None
    users, issued = build(a.testers, a.admin or None, keep, tuple(a.renew))
    a.out.mkdir(parents=True, exist_ok=True)
    secret = a.out / "GEO_USERS.json"
    secret.write_text(json.dumps(users, indent=1, sort_keys=True), encoding="utf-8")
    pw_file = a.out / "contrasenas-consola-PRIVADO.csv"
    with open(pw_file, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["usuario", "rol", "contraseña"])
        w.writerows(issued)
    for p in (secret, pw_file):
        os.chmod(p, 0o600)
    print(f"{len(users)} cuentas en {secret} (solo hashes); {len(issued)} contraseñas nuevas en {pw_file}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
