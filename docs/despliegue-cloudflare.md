# Publicar el sitio en Cloudflare Pages, sin enlace al repositorio

El flujo diario (`observatory.yml`) puede publicar el sitio en GitHub Pages
(como hasta ahora) o en Cloudflare Pages. Con Cloudflare:

- la dirección es `https://<proyecto>.pages.dev/` (o un dominio propio), no
  `pillb.github.io/...`;
- el sitio publicado no enlaza al repositorio: el paso
  `tools/prepare_site.py --hide-repo` quita los enlaces de GitHub del pie de
  página, de «Fuentes y metodología» y de la URL canónica, y **detiene la
  publicación** si el código del sitio vuelve a mencionar el repositorio;
- las fuentes consultadas ven la dirección del sitio como contacto en el
  User-Agent, en vez del repositorio;
- el despliegue no crea «deployments» de GitHub (no se pasa `gitHubToken`).

Todo lo demás no cambia: el pipeline, las pruebas, el recolector del Perú
(ramas `data-peru` y `data-archive`), el vigilante y las incidencias siguen
en GitHub Actions. Si una prueba falla no se despliega y queda la
publicación anterior, igual que con GitHub Pages.

## Por qué Cloudflare Pages

| | Cloudflare Pages (subida directa) | Cloudflare Workers (archivos estáticos) | Netlify Free | Vercel Hobby |
|---|---|---|---|---|
| Tráfico y solicitudes de archivos estáticos | Sin límite publicado | Sin límite para archivos estáticos | Plan por créditos mensuales; al agotarlos el sitio se pausa | 100 GB/mes; solo uso no comercial |
| Despliegues | 500/mes | Sin límite práctico | Consumen créditos | 100/día |
| Archivos | 20 000 por sitio, 25 MiB cada uno | 20 000 por versión, 25 MiB cada uno | — | — |
| Necesita conectar el repositorio | No (se sube desde Actions con `wrangler`) | No | No (CLI) | No (CLI) |
| Dirección gratuita | `<proyecto>.pages.dev` | `<nombre>.<cuenta>.workers.dev` (muestra el subdominio de la cuenta) | `<sitio>.netlify.app` | `<proyecto>.vercel.app` |

El sitio pesa unos 3,5 MB en ~70 archivos y se despliega una vez al día,
muy lejos de esos límites. Pages se eligió porque la subida directa es un
solo comando, el subdominio no revela el nombre de la cuenta y no hay
riesgo de pausa por consumo durante un evento con mucho tráfico (justo
cuando el sitio más importa). Fuentes: [límites de Pages](https://developers.cloudflare.com/pages/platform/limits/),
[subida directa desde CI](https://developers.cloudflare.com/pages/how-to/use-direct-upload-with-continuous-integration/).

## Pasos (una sola vez)

Requieren la cuenta del propietario; nada de esto se puede hacer desde el
repositorio.

1. **Cuenta de Cloudflare.** Crear una cuenta gratuita en
   <https://dash.cloudflare.com/sign-up>. Conviene usar un correo que no
   sea el del perfil público de GitHub si se busca que no se relacionen.
2. **Account ID.** En <https://dash.cloudflare.com/>, abrir *Workers &
   Pages*; el *Account ID* aparece en la columna derecha (también está en
   la URL: `dash.cloudflare.com/<account-id>/...`).
3. **Token de API.** En <https://dash.cloudflare.com/profile/api-tokens>,
   *Create Token* → *Create Custom Token*:
   - Permissions: **Account · Cloudflare Pages · Edit** (solo ese).
   - Account Resources: *Include* → la cuenta propia.
   - (Opcional) TTL sin vencimiento, o anotar la fecha para renovarlo.
   Copiar el token: se muestra una sola vez.
4. **Secretos en GitHub.** En
   <https://github.com/PillB/observatorio-enso-peru/settings/secrets/actions>
   → *New repository secret*:
   - `CLOUDFLARE_API_TOKEN` = el token del paso 3
   - `CLOUDFLARE_ACCOUNT_ID` = el ID del paso 2
5. **Variables en GitHub.** En
   <https://github.com/PillB/observatorio-enso-peru/settings/variables/actions>
   → *New repository variable*:
   - `DEPLOY_TARGET` = `cloudflare`
   - `CLOUDFLARE_PROJECT` = nombre del proyecto (opcional; por omisión
     `observatorio-enso`). Es el subdominio: `observatorio-enso.pages.dev`.
     Evite repetir el nombre exacto del repositorio si quiere que no se
     asocien por búsqueda.
6. **Primera publicación.** En
   <https://github.com/PillB/observatorio-enso-peru/actions/workflows/observatory.yml>
   → *Run workflow* (rama `main`). El flujo crea el proyecto si no existe
   y muestra un aviso con la dirección final, por ejemplo
   `https://observatorio-enso.pages.dev/`. Si el nombre ya estaba tomado,
   Cloudflare añade un sufijo (`observatorio-enso-4xk.pages.dev`).
7. **`SITE_URL`.** Guardar esa dirección (con `/` final) como variable
   `SITE_URL` en la misma página del paso 5. El vigilante la necesita: con
   `DEPLOY_TARGET=cloudflare` y sin `SITE_URL`, el vigilante falla con un
   mensaje que lo pide.
8. **Retirar GitHub Pages.** Cuando el sitio nuevo funcione, en
   <https://github.com/PillB/observatorio-enso-peru/settings/pages> usar
   *Unpublish site*. Mientras siga publicado, `pillb.github.io/observatorio-enso-peru`
   delata el repositorio. Revisar también que el campo *Website* de la
   página principal del repositorio (*About*) esté vacío.

La primera publicación en Cloudflare no encuentra la «publicación anterior»
(el sitio nuevo está vacío), así que en esa corrida no hay respaldo con
los datos del día anterior si una fuente no responde. Desde la segunda
corrida funciona como siempre.

### Dominio propio (opcional)

En Cloudflare: *Workers & Pages* → el proyecto → *Custom domains* → *Set up
a domain*. Si el dominio ya usa los DNS de Cloudflare, se configura solo;
si no, se pide un registro CNAME hacia `<proyecto>.pages.dev`. Después,
cambiar la variable `SITE_URL` al dominio nuevo.

### Volver a GitHub Pages

Borrar la variable `DEPLOY_TARGET` (o ponerla en `github-pages`) y
`SITE_URL`, y volver a activar Pages con origen *GitHub Actions* en
<https://github.com/PillB/observatorio-enso-peru/settings/pages>.

## ¿Y si el repositorio se vuelve privado?

Con Cloudflare, el sitio ya no depende de que el repositorio sea público.
Hacerlo privado oculta el código por completo, pero tiene costos en el
plan gratuito de GitHub:

| Qué | Repositorio público | Repositorio privado (GitHub Free) |
|---|---|---|
| Minutos de Actions | Sin límite | 2 000 min/mes; al agotarlos, **no corre la actualización diaria** hasta el mes siguiente |
| GitHub Pages | Gratis | No disponible (requiere plan de pago) — irrelevante con Cloudflare |
| Recolector del Perú | Token de grano fino con *Contents: write* | Igual; el token ya es privado. Nada cambia |
| Lecturas desde `raw.githubusercontent.com` u otros servicios sin token | Funcionan | Fallan: todo lector externo (por ejemplo n8n) necesita un token |

La operación diaria en sí consume unos 15–20 minutos facturables al día
(cada trabajo se redondea al minuto) más ~4 del vigilante: unos 600–700
min/mes. El problema es el desarrollo: hoy cada push a una rama `claude/**`
lanza `ci`, `probe-feeds`, `device-screens` y a veces `capture-fixtures`
(20–30 min cada uno), y en un día de trabajo intenso eso supera los 2 000
minutos. Recomendación: mantener el repositorio público mientras dure el
desarrollo activo (el sitio igual queda sin enlace hacia él) y hacerlo
privado cuando se estabilice, tras limitar esos flujos a `workflow_dispatch`
o a cambios en sus propias carpetas.

## Pages Functions (consola de administración u otras rutas dinámicas)

El despliegue lleva, además del sitio, la carpeta `functions/` y el archivo
`wrangler.toml` de la raíz del repositorio si existen: `wrangler pages deploy`
los toma del directorio de trabajo, compila las Functions y aplica los
vínculos declarados. Para usarlos:

- `wrangler.toml` en la raíz, con `name` igual al proyecto
  (`CLOUDFLARE_PROJECT`) y `pages_build_output_dir = "./public"`; los
  vínculos van en `[[d1_databases]]` o `[[kv_namespaces]]`. Con ese archivo,
  la configuración del panel de Cloudflare deja de ser editable: el archivo
  manda.
- Las respuestas de las Functions no reciben las cabeceras de `_headers`
  (solo los archivos estáticos); cada Function debe poner las suyas.
- Desplegar Functions y vínculos solo necesita el permiso
  **Cloudflare Pages · Edit**. Crear la base D1 o el espacio KV (una vez,
  con `wrangler d1 create` o desde el panel) necesita **D1 · Edit** o
  **Workers KV Storage · Edit**; conviene hacerlo a mano y no ampliar el
  token del flujo diario.
- Las solicitudes a Functions cuentan contra el plan gratuito de Workers
  (100 000 al día); los archivos estáticos no.

## Referencias en el código

| Archivo | Qué usa |
|---|---|
| `.github/workflows/observatory.yml` | `DEPLOY_TARGET`, `CLOUDFLARE_PROJECT`, `SITE_URL`, secretos `CLOUDFLARE_*` |
| `.github/workflows/watchdog.yml` | `SITE_URL` |
| `python/tools/cloudflare_pages.py` | Crea el proyecto si falta y devuelve su dirección |
| `python/tools/prepare_site.py` | Reescribe la dirección pública y quita los enlaces al repositorio |
| `python/enso/fetch.py` | `ENSO_CONTACT_URL` para el User-Agent (también se puede definir en el recolector del Perú) |
