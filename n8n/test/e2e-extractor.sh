#!/usr/bin/env bash
# Prueba de punta a punta del extractor con n8n de verdad (Docker) y un
# OpenAI falso: importa credenciales y flujo, lo activa, arranca n8n y le
# hace al webhook las mismas peticiones que el pipeline.
#
#   n8n/test/e2e-extractor.sh <imagen de n8n> <carpeta de trabajo>
set -euo pipefail

IMG=$1
WORK=$(mkdir -p "$2" && cd "$2" && pwd)
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OPORT=${FAKE_OPENAI_PORT:-8790}
NPORT=${N8N_TEST_PORT:-5678}
chmod 777 "$WORK"
NAME="enso-extractor-$$"

node "$ROOT/n8n/test/fake-openai.mjs" --port "$OPORT" > "$WORK/fake-openai.log" 2>&1 &
FAKE=$!
trap 'kill $FAKE 2>/dev/null || true; docker logs "$NAME" > "$WORK/n8n.log" 2>&1 || true; docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT

jq --arg api "http://127.0.0.1:$OPORT/v1" '
  (.nodes[] | select(.name == "Configuración") | .parameters.assignments.assignments) |=
    map(if .name == "api" then .value = $api else . end)
' "$ROOT/n8n/dist/enso-n8n-extractor.json" > "$WORK/extractor.json"
cat > "$WORK/credenciales.json" <<'JSON'
[{"id":"EnsoOpenAiCred01","name":"OpenAI ENSO (n8n)","type":"openAiApi","data":{"apiKey":"sk-prueba"}},
 {"id":"EnsoHookToken01","name":"Token del extractor ENSO","type":"httpHeaderAuth","data":{"name":"Authorization","value":"Bearer token-de-prueba"}}]
JSON

run() {
  docker run --rm --network host -u root -v "$WORK:/w" -e N8N_USER_FOLDER=/w/n8n-home --entrypoint sh "$IMG" -c "$1"
}
run "n8n import:credentials --input=/w/credenciales.json && n8n import:workflow --input=/w/extractor.json && \
  (n8n publish:workflow --id=EnsoExtractor001 2>/dev/null || n8n update:workflow --id=EnsoExtractor001 --active=true)"
docker run -d --name "$NAME" --network host -u root -v "$WORK:/w" -e N8N_USER_FOLDER=/w/n8n-home \
  -e N8N_PORT="$NPORT" -e N8N_LISTEN_ADDRESS=0.0.0.0 -e N8N_LOG_LEVEL=${N8N_LOG_LEVEL:-info} -e NO_PROXY=127.0.0.1,localhost --entrypoint sh "$IMG" -c "n8n start" >/dev/null
URL="http://127.0.0.1:$NPORT/webhook/enso-extraer"
for _ in $(seq 1 90); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL" || true)
  [ "$code" != "000" ] && [ "$code" != "404" ] && break
  sleep 2
done

body() { jq -n --arg text "$1" '{kind: "enfen-informe", schema: {type: "object", properties: {icen: {type: ["number", "null"]}, estado: {type: ["string", "null"]}}}, text: $text, url: "https://enfen.imarpe.gob.pe/x.pdf", published: "2026-10-10"}'; }
post() { curl -s -o "$WORK/$1.json" -w '%{http_code}' -X POST "$URL" -H 'content-type: application/json' ${2:+-H "authorization: $2"} --data-binary "$3"; }

c=$(post sin-token "" "$(body 'ICEN de septiembre: 0,85')"); echo "sin token: $c"; [ "$c" = 403 ] || [ "$c" = 401 ]
c=$(post ok "Bearer token-de-prueba" "$(body 'El ICEN temporal de septiembre es 0,85 (cálido débil).')"); echo "válida: $c $(cat "$WORK/ok.json")"
[ "$c" = 200 ]
jq -e '.data.icen == 0.85 and .data.estado == null and .model == "gpt-prueba-2026" and (.evidence.icen | test("0,85"))' "$WORK/ok.json" >/dev/null
curl -s "http://127.0.0.1:$OPORT/__last" | jq -e '.body.temperature == 0 and .body.response_format.type == "json_object" and (.body.messages[1].content | contains("Publicado: 2026-10-10"))' >/dev/null
c=$(post reintento "Bearer token-de-prueba" "$(body 'FALLA UNA VEZ. ICEN 0,40')"); echo "429 y reintento: $c $(cat "$WORK/reintento.json")"; [ "$c" = 200 ]
jq -e '.data.icen == 0.4' "$WORK/reintento.json" >/dev/null
c=$(post falla "Bearer token-de-prueba" "$(body 'FALLA SIEMPRE')"); echo "OpenAI caído: $c $(cat "$WORK/falla.json")"; [ "$c" = 502 ]
c=$(post mal "Bearer token-de-prueba" '{"kind":"otro","schema":{},"text":"x"}'); echo "petición inválida: $c $(cat "$WORK/mal.json")"; [ "$c" = 400 ]
echo "OK: el extractor responde como espera el pipeline"
