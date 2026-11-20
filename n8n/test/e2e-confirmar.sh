#!/usr/bin/env bash
# Prueba de punta a punta del flujo «correo de confirmación» con n8n de verdad (Docker): importa el flujo con un
# secreto de prueba y una credencial de Gmail falsa, lo publica, arranca n8n y le manda lo mismo que manda el sitio
# (functions/_lib/boletin-subs.js): asunto y HTML en base64, con tildes. Comprueba que el secreto se exige y que
# «Armar correo» decodifica el pedido y llega a «Enviar por Gmail» (que falla con la credencial falsa: no se manda
# nada). Un pedido mal formado sí debe quedar en «Armar correo».
#
#   n8n/test/e2e-confirmar.sh <imagen de n8n> <carpeta de trabajo>
set -euo pipefail

IMG=$1
WORK=$(mkdir -p "$2" && cd "$2" && pwd)
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
NPORT=${N8N_TEST_PORT:-5679}
chmod 777 "$WORK"
NAME="enso-confirmar-$$"
trap 'docker logs "$NAME" > "$WORK/n8n.log" 2>&1 || true; docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT

cp "$ROOT/n8n/dist/enso-n8n-boletin-confirmar.json" "$WORK/confirmar.json"
cat > "$WORK/credenciales.json" <<'JSON'
[{"id":"EnsoGmailCred001","name":"Gmail boletín ENSO","type":"gmailOAuth2","data":{"clientId":"x","clientSecret":"y","oauthTokenData":{"access_token":"falso","refresh_token":"falso","token_type":"Bearer","expiry_date":1}}},
 {"id":"EnsoBolHook0001","name":"Boletín: secreto del sitio","type":"httpHeaderAuth","data":{"name":"X-Enso-Secret","value":"secreto-de-prueba"}}]
JSON
ID=$(jq -r '.id' "$WORK/confirmar.json")

run() { docker run --rm --network host -u root -v "$WORK:/w" -e N8N_USER_FOLDER=/w/n8n-home --entrypoint sh "$IMG" -c "$1"; }
run "n8n import:credentials --input=/w/credenciales.json && n8n import:workflow --input=/w/confirmar.json && \
  (n8n publish:workflow --id=$ID 2>/dev/null || n8n update:workflow --id=$ID --active=true)"
docker run -d --name "$NAME" --network host -u root -v "$WORK:/w" -e N8N_USER_FOLDER=/w/n8n-home \
  -e N8N_PORT="$NPORT" -e N8N_LISTEN_ADDRESS=0.0.0.0 -e NO_PROXY=127.0.0.1,localhost --entrypoint sh "$IMG" -c "n8n start" >/dev/null
URL="http://127.0.0.1:$NPORT/webhook/enso-boletin-confirmar"
for _ in $(seq 1 90); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL" || true)
  case "$code" in 000|404|5??) ;; *) break ;; esac
  sleep 2
done

# El mismo cuerpo que arma el sitio, con el código del sitio.
node --input-type=module -e "
import { shortMail } from '$ROOT/functions/_lib/boletin-subs.js';
const m = shortMail({ title: 'Confirme su suscripción', lead: 'Recibimos un pedido: añádase al boletín de El Niño.', button: 'Confirmar mi suscripción', href: 'https://enso-peru.pages.dev/#/boletin?confirmar=x', note: 'Si no lo pidió, ignórelo.' });
const b64 = (s) => Buffer.from(s, 'utf8').toString('base64');
process.stdout.write(JSON.stringify({ to: 'prueba@example.com', enc: 'base64', subject_b64: b64('Confirme su suscripción al Boletín El Niño · Perú'), html_b64: b64(m.html) }));
" > "$WORK/pedido.json"
post() { curl -s -o "$WORK/$1.out" -w '%{http_code}' -X POST "$URL" -H 'content-type: application/json' ${2:+-H "X-Enso-Secret: $2"} --data-binary "@$WORK/$3"; }
echo '{"to":"prueba@example.com","subject_b64":"<b>","html_b64":"x"}' > "$WORK/malo.json"

c=$(post sin-secreto "" pedido.json); echo "sin secreto: $c"; [ "$c" = 403 ] || [ "$c" = 401 ]
c=$(post falso "otro" pedido.json); echo "secreto falso: $c"; [ "$c" = 403 ] || [ "$c" = 401 ]
c=$(post bueno "secreto-de-prueba" pedido.json); echo "pedido del sitio: $c $(head -c 200 "$WORK/bueno.out")"
c=$(post malo "secreto-de-prueba" malo.json); echo "pedido mal formado: $c"
sleep 3
docker rm -f "$NAME" >/dev/null 2>&1 || true
# Las ejecuciones guardadas (n8n guarda las fallidas): la buena pasó «Armar correo»; la mala no.
sudo python3 - "$WORK/n8n-home/.n8n/database.sqlite" <<'PY'
import sqlite3, sys
db = sqlite3.connect(sys.argv[1])
rows = [r[0] for r in db.execute("SELECT d.data FROM execution_data d JOIN execution_entity e ON e.id = d.executionId ORDER BY e.id")]
print(f"{len(rows)} ejecuciones guardadas")
invalid = [r for r in rows if "Pedido de confirmación inválido" in r]
gmail = [r for r in rows if "Enviar por Gmail" in r and "Pedido de confirmación inválido" not in r and "Confirme su suscripción al Boletín El Niño · Perú" in r]
assert len(invalid) == 1, f"solo el pedido mal formado debe fallar en «Armar correo» (fallaron {len(invalid)})"
assert gmail, "el pedido del sitio debe llegar a «Enviar por Gmail» con el asunto decodificado"
print("✓ «Armar correo» decodifica el pedido del sitio y llega a Gmail; el mal formado se rechaza")
PY
