#!/usr/bin/env bash
# Prueba de punta a punta con n8n de verdad (Docker) y una API de GitHub
# falsa: importa el recolector, lo corre dos veces, baja la rama resultante
# y comprueba con el código del pipeline (enso.fetch.Relay) que se lee.
#
#   n8n/test/e2e.sh <imagen de n8n> <carpeta de trabajo> [filtro de fuentes]
#
# El filtro es el campo «only» de la configuración (un id o un grupo del
# registro, p. ej. «noaa»); vacío corre todas las fuentes.
set -euo pipefail

IMG=$1
WORK=$(mkdir -p "$2" && cd "$2" && pwd)
ONLY=${3:-}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PORT=${FAKE_GITHUB_PORT:-8787}
chmod 777 "$WORK"

node "$ROOT/n8n/test/fake-github.mjs" --port "$PORT" --registry "$ROOT/registry/sources.json" > "$WORK/fake-github.log" 2>&1 &
FAKE=$!
trap 'kill $FAKE 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do curl -sf "http://127.0.0.1:$PORT/__stats" >/dev/null && break; sleep 0.5; done

jq --arg api "http://127.0.0.1:$PORT" --arg only "$ONLY" '
  (.nodes[] | select(.name == "Configuración") | .parameters.assignments.assignments) |=
    map(if .name == "api" then .value = $api elif .name == "only" then .value = $only else . end)
' "$ROOT/n8n/dist/enso-n8n-recolector.json" > "$WORK/recolector.json"
cat > "$WORK/credenciales.json" <<'JSON'
[{"id":"EnsoGithubCred01","name":"GitHub ENSO (n8n)","type":"githubApi","data":{"server":"https://api.github.com","user":"prueba","accessToken":"token-de-prueba"}}]
JSON

PROXY_ARGS=()
if [ -n "${HTTPS_PROXY:-}" ]; then
  # Contenedores de desarrollo con proxy de salida (no hace falta en GitHub Actions).
  PROXY_ARGS=(-e "HTTPS_PROXY=$HTTPS_PROXY" -e "HTTP_PROXY=$HTTPS_PROXY" -e "NO_PROXY=127.0.0.1,localhost")
  if [ -n "${NODE_EXTRA_CA_CERTS:-}" ]; then
    cp "$NODE_EXTRA_CA_CERTS" "$WORK/ca.crt" && chmod 644 "$WORK/ca.crt"
    PROXY_ARGS+=(-e NODE_EXTRA_CA_CERTS=/w/ca.crt)
  fi
fi
n8n() {
  docker run --rm --network host -u root -v "$WORK:/w" -e N8N_USER_FOLDER=/w/n8n-home \
    -e GENERIC_TIMEZONE=America/Lima "${PROXY_ARGS[@]}" --entrypoint sh "$IMG" -c "$1"
}

n8n "n8n import:credentials --input=/w/credenciales.json && n8n import:workflow --input=/w/recolector.json"
for run in 1 2; do
  echo "== corrida $run"
  n8n "n8n execute --id=EnsoRecolector01 --rawOutput" > "$WORK/corrida-$run.log" 2>&1 || {
    grep -v '^    at ' "$WORK/corrida-$run.log" | tail -40; exit 1; }
  sed -n '/^{/,$p' "$WORK/corrida-$run.log" > "$WORK/corrida-$run.json"
  jq -e '.data.resultData.runData.Resumen[0].data.main[0][0].json' "$WORK/corrida-$run.json"
  curl -sf "http://127.0.0.1:$PORT/__stats" | tee "$WORK/stats-$run.json"; echo
done

rm -rf "$WORK/copia" && mkdir -p "$WORK/copia"
curl -sf "http://127.0.0.1:$PORT/__dump?branch=data-n8n&dir=$WORK/copia" >/dev/null
python3 - "$WORK" <<'PY'
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "python"))
from enso.fetch import Relay

work = Path(sys.argv[1])
copia = work / "copia"
relay = Relay(copia)
idx = json.loads((copia / "index.json").read_text(encoding="utf-8"))
hb = json.loads((copia / "heartbeat.json").read_text(encoding="utf-8"))
ok = [e for e in idx["entries"] if e.get("file")]
assert relay.channel == "relay-n8n", relay.channel
assert idx["collector"]["kind"] == "n8n"
assert hb["schema"] == "enso-relay-heartbeat/1", hb
missing = [e["url"] for e in ok if relay.get(e["url"]) is None]
assert not missing, f"el pipeline no lee estas copias: {missing[:5]}"
s1 = json.loads((work / "stats-1.json").read_text())
s2 = json.loads((work / "stats-2.json").read_text())
assert s1["auth_missing"] == 0, "alguna llamada a GitHub salió sin credencial"
second = s2["blobs_created"] - s1["blobs_created"]
print(f"OK: {len(ok)}/{len(idx['entries'])} URL con copia legible por el pipeline; "
      f"latido {hb['result']} {hb['reachable']}; blobs subidos: {s1['blobs_created']} y luego {second}")
print(json.dumps(idx["verdicts"]))
PY
