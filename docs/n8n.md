# Recolector en n8n (canal alternativo, AWS)

El n8n de un colega (licenciado, en AWS us-east) descarga las fuentes que
**no** están geobloqueadas y publica las copias en la rama `data-n8n`. Es un
segundo canal fuera de GitHub Actions: si una fuente no responde a Actions
pero sí a n8n, la actualización diaria usa la copia de n8n (canal
«relay-n8n»). Las fuentes geobloqueadas siguen yendo solo por el
[recolector del Perú](servidor-peru.md).

```
registro de fuentes ──► n8n (AWS) ──► rama data-n8n ──┐
(registry/sources.json)  descarga y clasifica          ├─► actualización diaria ─► sitio
                        servidor del Perú ─► data-peru ─┘   (directo › relay más reciente › Internet Archive)
```

Hay dos flujos, en `n8n/dist/`:

| Archivo | Para qué | Credenciales |
|---|---|---|
| `enso-n8n-validacion.json` | Comprobar qué fuentes responden **desde ese n8n**. Descarga cada fuente del registro una vez y devuelve un informe (también en CSV) | Ninguna |
| `enso-n8n-recolector.json` | Recolectar todos los días a las 22:50 (Lima) y publicar en `data-n8n` | Token de GitHub |
| `enso-n8n-vigilante.json` | Cada 6 horas, revisar que el sitio publicado esté al día (`data/manifest.json`, `generatedAt` de menos de 30 h); si no, la ejecución falla y avisa | Ninguna |
| `enso-n8n-extractor.json` | Respaldo con OpenAI para leer los informes del ENFEN cuando su formato cambia: el pipeline lo llama por un webhook con token y recibe una propuesta en JSON para revisión | OpenAI del colega y un token propio |

Probados de punta a punta con n8n **2.44** y **1.123** (CI: `.github/workflows/n8n.yml`).

## Qué mide y cómo decide

Cada respuesta pasa por el mismo clasificador (`n8n/lib/classify.js`) en
n8n, en GitHub Actions y en `n8n/tools/probe.mjs`:

| Veredicto | Significa |
|---|---|
| `ok` | Llegó lo esperado (un feed con entradas, un PDF, texto, JSON, HTML) |
| `blocked` | La fuente respondió con un bloqueo: 403, 429, verificación «soy humano», CAPTCHA, Cloudflare, Imperva, AWS WAF, 202 anti-robots. La columna `bloqueo` dice cuál. **Nunca se evade**: se anota y la fuente se lee por otro canal |
| `timeout`, `connection`, `dns`, `tls` | No hubo respuesta (tiempo agotado, conexión cortada, el nombre no resuelve, certificado inválido) |
| `not_found`, `server_error`, `http_error` | 404/410, 5xx, otros códigos |
| `wrong_type`, `empty`, `parse_error` | Respondió, pero no con lo esperado (p. ej. HTML en lugar de un feed) |

`alcance` traduce el veredicto a las clases del registro
(`python/enso/reach.py`: `ok`, `challenge`, `http-403`, `timeout`,
`connect`, `dns`…), para comparar con las mediciones desde Actions y desde
el Perú.

Cada URL pasa sola por el nodo HTTP (bucle «Una por una»): si n8n recibe
muchas a la vez, lanza todas las peticiones y lee los cuerpos al final, y
las respuestas grandes se cortan por inactividad («aborted»).

Las fallas pasajeras (tiempo agotado, conexión cortada, 5xx, 429) se
reintentan una vez a los 30 s. En la misma segunda pasada se bajan los
documentos que el registro indica seguir (`follow`) y los PDF de los
comunicados del ENFEN deducidos de sus listados (los dos últimos y los dos
números siguientes), con el mismo criterio que el pipeline.

## Paso 1 — Validar (unos 15 minutos, sin credenciales)

Lo hace el colega que administra el n8n:

1. Descargar `n8n/dist/enso-n8n-validacion.json` del repositorio (o pedírselo a Pablo).
2. En n8n: **Workflows → Create Workflow → ⋯ (arriba a la derecha) → Import from File** y elegir el archivo.
3. Pulsar **Execute workflow** (o **Test workflow**). Tarda unos 15 minutos: baja las URL de a una y las del Perú (SENAMHI, ANA) esperan 40 s y 60 s antes de darse por perdidas.
4. Abrir el nodo **Informe**: la primera fila es el resumen (`RESUMEN: N/M fuentes responden desde este n8n`), luego una fila por URL, primero las que fallaron.
5. Abrir el nodo **Informe CSV** y descargar `validacion-fuentes-n8n.csv`. Enviárselo a Pablo.

Con ese archivo se actualiza el registro: lo que responde desde AWS queda en
los canales `actions` y `n8n`; lo que no responde desde ninguna red de EE. UU.
(GitHub Actions en Azure, n8n en AWS), en `peru-server`. Los canales se deciden
por URL (`by_url` en `registry/sources.json`): el portal del ENFEN no resuelve
desde Azure ni desde AWS y lo pide el servidor del Perú, mientras que su réplica
en la DHN la piden Actions y n8n. Desde entonces, la medición semanal
(`probe-sources.yml`) también lee lo que bajó el recolector de n8n en la rama
`data-n8n`.

## Paso 2 — Token de GitHub (Pablo)

GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate new token:

- **Resource owner**: PillB. **Repository access**: Only select repositories → `observatorio-enso-peru`.
- **Permissions → Repository permissions → Contents: Read and write**. Nada más.
- **Expiration**: 1 año. Anotar la fecha.

El token se pega solo en la credencial de n8n (paso 3). No va en el flujo ni
en el repositorio. Con «Contents: read and write» n8n puede leer el
registro y escribir en `data-n8n`; aunque el repositorio pase a privado,
sigue funcionando (todo va por la API, nada por `raw.githubusercontent.com`).

## Paso 3 — Credencial en n8n (colega)

1. **Credentials → Add credential → GitHub API** (la credencial «GitHub API» de n8n, de tipo *Access Token*).
2. **Github Server**: `https://api.github.com` · **User**: `PillB` · **Access Token**: el token del paso 2.
3. Nombre: `GitHub ENSO (n8n)`. Guardar. n8n prueba la credencial al guardar; debe quedar en verde.
4. Opcional: copiar el id de la credencial (la parte final de la URL al abrirla) y enviárselo a Pablo. Con él, `N8N_GITHUB_CRED_ID=<id> node n8n/build.mjs` genera flujos que ya la traen elegida, y las reimportaciones no piden volver a elegirla.

## Paso 4 — Importar y probar el recolector (colega)

1. Importar `n8n/dist/enso-n8n-recolector.json` como en el paso 1.
2. Los nodos que hablan con GitHub (Leer registro, Leer copia anterior, Crear blobs, Crear árbol, Crear commit, Leer rama, Publicar, Avisar al sitio) muestran un aviso de credencial: abrir cada uno y elegir `GitHub ENSO (n8n)` en **Credential for GitHub API**.
3. Revisar el nodo **Configuración** (es el único que se edita en la interfaz):

   | Campo | Valor por defecto | Para qué |
   |---|---|---|
   | `repo` | `PillB/observatorio-enso-peru` | Repositorio |
   | `api` | `https://api.github.com` | API de GitHub |
   | `data_branch` | `data-n8n` | Rama donde se publican las copias (se crea sola) |
   | `registry_ref`, `registry_path` | `main`, `registry/sources.json` | De dónde se lee el registro. Si no se puede leer, se usa la copia incluida en el flujo |
   | `scope` | `n8n` | `n8n`: solo las fuentes que el registro asigna a n8n; `todas`: también mide las del servidor del Perú. Las que `robots.txt` prohíbe no se piden nunca: ni las que no tienen canales ni los feeds `reader` (solo Actions, una vez al día) |
   | `host_label`, `egress` | `n8n-aws`, `aws-us-east-1` | Se anotan en cada copia |
   | `carry_hours` | `72` | Si una URL falla, se conserva su última copia válida hasta estas horas |
   | `max_file_mb` | `8` | Respuestas más grandes no se guardan |
   | `contact` | URL del repositorio | Contacto en el User-Agent. Cambiar por la URL del sitio cuando esté en su dominio |
   | `only` | vacío | Para pruebas: solo las fuentes cuyo id contiene este texto o cuyo grupo es este |

4. Pulsar **Execute workflow**. Tarda 8 a 12 minutos (las URL se bajan de a una). El nodo **Resumen** debe decir `Copia publicada en PillB/observatorio-enso-peru@data-n8n`.
5. Comprobar en GitHub que existe la rama `data-n8n` con `index.json`, `heartbeat.json` y `files/`.

## Paso 5 — Activar (colega)

- **n8n 1.x**: interruptor **Active** arriba a la derecha.
- **n8n 2.x**: botón **Publish**.

El horario (22:50, hora de Lima) va en el nodo **Cada día 22:50 (Lima)** y la
zona horaria en la configuración del flujo, así que no depende de la zona del
servidor. La actualización diaria del sitio corre a las 23:37 (Lima) y usa
la copia de esa noche.

Recomendado en n8n: **Settings → Error workflow** con un flujo que avise por
correo, para enterarse si el recolector falla. Además, la actualización diaria
registra `relay-n8n-stale` si la última corrida tiene más de 36 horas,
`relay-n8n-sources-down` si n8n corrió pero ninguna fuente le respondió y
`relay-n8n-missing` si la rama `data-n8n` no existe.

## Vigilante del sitio (opcional, recomendado)

GitHub desactiva los flujos programados de un repositorio sin actividad, y
ya pasó sin que nadie lo notara. El vigilante no depende de GitHub: importar
`enso-n8n-vigilante.json`, poner en **Configuración → site** la dirección
del sitio (hoy `https://pillb.github.io/observatorio-enso-peru/`; cambiarla
si se muda a Cloudflare), y activarlo. Cuando falla, avisa el «Error
workflow» de n8n (paso 5).

## Extractor de informes con OpenAI (opcional)

Cuando el lector de los informes y perspectivas del ENFEN encuentra un
formato que no conoce, el pipeline puede pedir una segunda lectura a un
modelo (`python/enso/reports.py`, `llm_extract`; contrato en
[informes-texto.md](informes-texto.md)). El modelo solo **propone**: el
pipeline vuelve a validar con el esquema y deja el resultado para revisión;
nunca se publica solo. Solo se llama cuando el lector falla, así que el costo
es bajo (unos 30 000 tokens por documento).

El flujo: **Webhook** `POST /webhook/enso-extraer` con autenticación por
cabecera → valida el pedido (`kind`, `schema`, `text`; si no, responde 400) →
OpenAI `chat/completions` con temperatura 0 y `response_format: json_object`
→ responde `{data, model, evidence}`. `evidence` trae, para cada valor, la
cita del documento de donde sale. Si OpenAI falla responde 502 y el pipeline
sigue sin la propuesta.

Lo hace el colega:

1. Generar un token largo y aleatorio (por ejemplo `openssl rand -hex 32`).
2. **Credentials → Add credential → Header Auth**: Name `Authorization`,
   Value `Bearer <token>`. Nombre de la credencial: `Token del extractor ENSO`.
3. **Credentials → Add credential → OpenAI**: la clave de OpenAI. Nombre:
   `OpenAI ENSO (n8n)`.
4. Importar `n8n/dist/enso-n8n-extractor.json`. En **Petición del pipeline**
   elegir `Token del extractor ENSO`; en **Preguntar al modelo**, `OpenAI ENSO (n8n)`.
5. En **Configuración**, `model` (por defecto `gpt-4.1-mini`) se puede cambiar
   por otro modelo de chat que admita `json_object`.
6. Activar (n8n 1.x) o publicar (n8n 2.x). La dirección es la **Production
   URL** del nodo Webhook: `https://<servidor-n8n>/webhook/enso-extraer` (no la
   «Test URL»). Debe ser accesible desde internet por HTTPS.

Lo hace Pablo, en GitHub → Settings → Secrets and variables → Actions:

- `ENSO_LLM_EXTRACT_URL` = la Production URL del paso 6.
- `ENSO_LLM_EXTRACT_TOKEN` = el token del paso 1 (sin «Bearer»).

Prueba rápida (debe responder 400 con `«kind» debe ser …`, señal de que el
token y el flujo funcionan):

```
curl -X POST "$ENSO_LLM_EXTRACT_URL" -H "Authorization: Bearer $ENSO_LLM_EXTRACT_TOKEN" \
  -H 'content-type: application/json' -d '{"kind":"prueba","schema":{},"text":"x"}'
```

Sin el token responde 403. La prueba de punta a punta con n8n real y un
OpenAI falso es `n8n/test/e2e-extractor.sh n8nio/n8n:2.44.4 /tmp/ext`.

## Qué publica

Rama `data-n8n`, reemplazada en cada corrida (un commit sin padre: la rama
guarda solo la última copia y el repositorio no crece; lo que el sitio usa
se archiva en `data-archive`):

- `index.json` (`enso-relay/1`): una entrada por URL con `status`, `verdict`, `reach`, `block`, `content_type`, `bytes`, `fetched_at`, `sha256`, `git_blob` y `file`. Las entradas que fallaron también están, con su motivo: es la medición desde AWS.
- `files/<sha256[:16]>.<ext>`: el cuerpo original de cada respuesta válida.
- `heartbeat.json` (`enso-relay-heartbeat/1`, el mismo formato que el recolector del Perú): `result` es `ok` si algo respondió en esta corrida y `sin-fuentes` si nada respondió (n8n funciona, las fuentes no).

Los archivos que no cambiaron desde la corrida anterior no se vuelven a
subir. La primera corrida sube unos 180 archivos (unos 3 minutos, por el
límite de GitHub de 80 escrituras por minuto); las siguientes, solo los que
cambiaron.

## Requisitos del servidor de n8n

- Salida a internet por HTTPS (y HTTP para `met.igp.gob.pe`).
- No hace falta ningún nodo de la comunidad, ni `NODE_FUNCTION_ALLOW_BUILTIN`, ni acceso a variables de entorno desde los nodos.
- Cada corrida maneja unos 15 MB de respuestas. Se recomienda `N8N_DEFAULT_BINARY_DATA_MODE=filesystem` y dejar activa la poda de ejecuciones (`EXECUTIONS_DATA_PRUNE`, activa por defecto).

## Cambios y actualizaciones

Los nodos Code se generan desde `n8n/lib` y `n8n/nodes` y no se editan en
n8n. Para cambiar algo: editar el código, `node --test n8n/test/*.test.mjs`,
`node n8n/build.mjs`, y reimportar: abrir el flujo existente → ⋯ → **Import
from File** → guardar (y volver a activar/publicar). La prueba de punta a
punta con n8n real es `n8n/test/e2e.sh n8nio/n8n:2.44.4 /tmp/e2e noaa`
(necesita Docker; usa una API de GitHub falsa).

## Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| `Credentials not found` o el nodo pide credencial | Paso 4.2: elegir `GitHub ENSO (n8n)` en cada nodo de GitHub |
| `Crear blobs` falla con 401 | El token venció o no es del repositorio correcto: generar otro (paso 2) y actualizar la credencial |
| `Crear blobs` falla con 403 «secondary rate limit» | Demasiadas escrituras seguidas en GitHub. El nodo reintenta 3 veces; si persiste, correr de nuevo una hora después |
| `Publicar` falla con 422 | La rama cambió mientras corría (otra corrida a la vez). Volver a correr |
| Muchas fuentes `timeout` o `connection` | La salida a internet del servidor de n8n (proxy, firewall, NAT) |
| Muchas fuentes grandes con `timeout` y nota `aborted` | Flujo anterior a esta versión: n8n lanzaba todas las descargas y leía los cuerpos al final, y las respuestas grandes se cortaban. Reimportar los flujos actuales (bajan las URL de a una) |
| `enfen.imarpe.gob.pe` con `dns` (`EAI_AGAIN`) | Los servidores de nombres propios del IMARPE responden mal a los resolvedores de AWS y Azure (sí a 1.1.1.1 y 8.8.8.8). El registro deja ese portal al servidor del Perú; n8n ya no lo pide |
| Una fuente `blocked` con `challenge` | Esa institución bloquea a los servidores en la nube. No se evade: si responde desde el Perú, va por el servidor del Perú |
| El informe dice `incluido en el flujo` en `registry` | No se pudo leer el registro desde GitHub (validación: siempre; recolector: revisar credencial y `registry_ref`). Se usó la copia incluida al construir el flujo |
