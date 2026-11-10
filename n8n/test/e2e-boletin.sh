#!/usr/bin/env bash
# Prueba de punta a punta del flujo del boletín con n8n de verdad: un sitio falso sirve data/boletin.json (armado
# con python/enso/boletin.py, con el corte de ahora), y el flujo se corre dos veces:
#   1. «send» = false (como se importa): arma el correo del primer boletín y no lo manda.
#   2. «send» = true con una credencial de Gmail falsa: llega al nodo de Gmail, que falla al autenticarse, y
#      «Guardar estado» no corre (un envío fallido no se da por hecho).
# Nunca se manda un correo de verdad.
#
#   n8n/test/e2e-boletin.sh <imagen de n8n | local> <carpeta de trabajo>
# «local» usa el n8n de PATH (npm i n8n) en lugar de Docker.
set -euo pipefail

IMG=$1
WORK=$(mkdir -p "$2" && cd "$2" && pwd)
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PORT=${FAKE_SITE_PORT:-8791}
chmod 777 "$WORK"
mkdir -p "$WORK/site/data"

python3 - "$ROOT" "$WORK/site/data/boletin.json" <<'PY'
import json, sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, sys.argv[1] + "/python")
from enso import boletin as B
now = datetime.now(timezone.utc).replace(microsecond=0)
iso = lambda d: d.isoformat().replace("+00:00", "Z")
feed = {"generatedAt": iso(now), "groups": [{"id": "alertas", "sources": [{"ok": True}], "items": [
    {"id": "alert-1", "institution": "SENAMHI", "kind": "pronostico", "title": "SENAMHI · aviso de precipitaciones, nivel 4: Tumbes",
     "date": iso(now - timedelta(hours=2)), "hazards": ["lluvias"], "url": "https://www.senamhi.gob.pe/",
     "severity": {"rank": 3, "label": "Nivel 4", "scaleLabel": "SENAMHI"},
     "valid": {"from": iso(now - timedelta(hours=1)), "until": iso(now + timedelta(hours=20))},
     "geo": {"places": [{"code": "24", "level": "departamento", "name": "Tumbes", "confidence": 0.97}]}}]}]}
official = {"enfen": {"status": "Alerta de El Niño Costero", "number": "19-2026", "issued": "2026-10-30", "stale": False}}
doc = B.build(feed, official, None, now, None, None, site="https://enso-peru.pages.dev/")
open(sys.argv[2], "w", encoding="utf-8").write(json.dumps({"publicationId": "e2e"} | doc, ensure_ascii=False))
PY

python3 -m http.server "$PORT" --bind 127.0.0.1 -d "$WORK/site" > "$WORK/site.log" 2>&1 &
SITE=$!
trap 'kill $SITE 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do curl -sf "http://127.0.0.1:$PORT/data/boletin.json" >/dev/null && break; sleep 0.3; done

flow() {  # $1: send (true/false), $2: archivo de salida
  jq --arg site "http://127.0.0.1:$PORT/" --argjson send "$1" '
    (.nodes[] | select(.name == "Configuración") | .parameters.assignments.assignments) |=
      map(if .name == "site" then .value = $site elif .name == "send" then .value = $send
          elif .name == "to" then .value = "prueba@example.com" elif .name == "bcc" then .value = "a@example.com, b@example.com" else . end)
  ' "$ROOT/n8n/dist/enso-n8n-boletin.json" > "$2"
}
cat > "$WORK/credenciales.json" <<'JSON'
[{"id":"EnsoGmailCred001","name":"Gmail boletín ENSO","type":"gmailOAuth2","data":{"clientId":"x","clientSecret":"y","oauthTokenData":{"access_token":"falso","refresh_token":"falso","token_type":"Bearer","expiry_date":1}}}]
JSON

if [ "$IMG" = local ]; then
  n8n() { (cd "$WORK" && N8N_USER_FOLDER="$WORK/n8n-home" GENERIC_TIMEZONE=America/Lima sh -c "$(echo "$1" | sed "s#/w/#$WORK/#g")"); }
else
  n8n() { docker run --rm --network host -u root -v "$WORK:/w" -e N8N_USER_FOLDER=/w/n8n-home -e GENERIC_TIMEZONE=America/Lima --entrypoint sh "$IMG" -c "$1"; }
fi

flow false "$WORK/simulacro.json"
n8n "n8n import:credentials --input=/w/credenciales.json && n8n import:workflow --input=/w/simulacro.json"
n8n "n8n execute --id=EnsoBoletin00001 --rawOutput > /w/simulacro.out" > "$WORK/simulacro.log" 2>&1 || {
  tail -40 "$WORK/simulacro.log"; tail -60 "$WORK/simulacro.out"; exit 1; }
sed -n '/^{/,$p' "$WORK/simulacro.out" > "$WORK/simulacro-run.json"
jq -e '.data.resultData.runData["Decidir envío"][0].data.main[0][0].json
  | .kind == "Primer boletín" and .send == false and .simulate == true and .to == "prueba@example.com"
    and .bcc == "a@example.com,b@example.com" and (.subject | startswith("Boletín El Niño N° 1"))
    and (.html | contains("Tumbes")) and (.html | contains("<!--cambios-->"))' "$WORK/simulacro-run.json"
jq -e '.data.resultData.runData | has("Enviar por Gmail") | not' "$WORK/simulacro-run.json"
echo "✓ simulacro: el correo se arma y no se manda"

flow true "$WORK/envio.json"
n8n "n8n import:workflow --input=/w/envio.json"
if n8n "n8n execute --id=EnsoBoletin00001 --rawOutput > /w/envio.out" > "$WORK/envio.log" 2>&1; then
  sed -n '/^{/,$p' "$WORK/envio.out" > "$WORK/envio-run.json" || true
  # Algunas versiones terminan con código 0 aunque un nodo falle: el error queda en la ejecución.
  jq -e '.data.resultData.error != null and (.data.resultData.lastNodeExecuted == "Enviar por Gmail")' "$WORK/envio-run.json" \
    || { echo "Se esperaba que Gmail fallara con la credencial falsa"; tail -40 "$WORK/envio.out"; exit 1; }
else
  grep -q "Enviar por Gmail" "$WORK/envio.out" "$WORK/envio.log" || { tail -40 "$WORK/envio.log"; tail -40 "$WORK/envio.out"; exit 1; }
fi
! grep -q "Enviado:" "$WORK/envio.out"
echo "✓ envío: llega a Gmail con «send» = true y no guarda estado si Gmail falla"
