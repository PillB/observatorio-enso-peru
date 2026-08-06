# Despliegue — Observatorio ENSO Perú

> Formal Spanish. Instrucciones de despliegue para GitHub Pages con
> subpath, comandos de build y refresco de datos.

## 1. Requisitos

- Node.js 20+ y Bun (recomendado) o npm.
- Python 3.10+ para el pipeline.
- Cuenta GitHub con Pages habilitado.

## 2. Desarrollo local

```bash
# Frontend (puerto 3000, ruta /)
bun install
bun run dev
# Abrir http://localhost:3000

# Pipeline Python (offline, degrada graceful)
cd python
pip install -r requirements.txt
python -m enso.cli run --offline
python -m pytest -q
```

## 3. Build estático para GitHub Pages

GitHub Pages sirve el repositorio bajo un subpath
`https://<usuario>.github.io/<repo>/`. El frontend debe configurar el
`basePath`.

### 3.1 Configuración

En `next.config.ts`:

```typescript
const isPages = process.env.GITHUB_PAGES === 'true';
const repo = process.env.GITHUB_REPOSITORY?.split('/')[1] ?? '';
module.exports = {
  basePath: isPages ? `/${repo}` : '',
  output: 'export', // requiere App Router estático
  // ...
};
```

### 3.2 Comandos

```bash
# Variables para Pages
export GITHUB_PAGES=true
export GITHUB_REPOSITORY="usuario/obs-enso-peru"
export NEXT_PUBLIC_BASE_PATH="/obs-enso-peru"

bun run build
# Output: ./out  (directorio estático)
```

### 3.3 Helper de asset_url

El pipeline Python proporciona un helper para construir URLs relativas
al subpath:

```python
from enso.pipeline import asset_url
asset_url("/obs-enso-peru", "data/nino12.csv")
# → "/obs-enso-peru/data/nino12.csv"
```

El test `test_github_pages_subpath.py` verifica el contrato.

## 4. Workflow de despliegue (CI)

`.github/workflows/deploy-pages.yml`:

1. Instala Bun/Node.
2. Construye el sitio estático (o copia `public/` como respaldo).
3. Sube el artefacto y lo publica en GitHub Pages.
4. Añade `.nojekyll` para evitar procesamiento Jekyll.

Configuración en GitHub: **Settings → Pages → Source: GitHub Actions**.

## 5. Refresco de datos

### 5.1 Pipeline diario

`.github/workflows/pipeline.yml` se ejecuta:

- Diariamente a las **13:17 UTC** (fuera de la hora en punto).
- Bajo demanda (`workflow_dispatch`).
- En PRs que tocan `python/`.

Produce `python/out/{manifest,status,sources,*.csv}` y los sube como
artefactos. En schedule, commitea los outputs a la rama `data`.

### 5.2 Servir datos al frontend

Opción A (recomendada): el frontend se sirve estático y los CSV se
sirven desde `public/data/` (commiteados en la rama `data` o
descargados en build time).

Opción B: el frontend consulta la API route `/api/data` que lee los CSV
del sistema de archivos (en entornos con backend).

### 5.3 Sincronización Python ↔ TS

La validación en PR (`validate.yml`) verifica la paridad de
identificadores entre `python/enso/sources.py` y `src/lib/enso/sources.ts`,
y entre `python/enso/methodology.py` y `src/lib/enso/methodology.ts`.

## 6. Despliegue alternativo (Vercel / Netlify)

Para despliegue con backend (API routes funcionales):

- Vercel: `vercel --prod` (detecta Next.js automáticamente).
- Netlify: instalar `@netlify/plugin-nextjs` y desplegar.

En estos entornos no se requiere `basePath` ni `output: 'export'`.

## 7. Variables de entorno

| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `GITHUB_PAGES` | Activa configuración Pages | `true` |
| `GITHUB_REPOSITORY` | Repo (para basePath) | `usuario/obs-enso-peru` |
| `NEXT_PUBLIC_BASE_PATH` | Subpath público | `/obs-enso-peru` |

**No** se requieren tokens para el despliegue Pages (el pipeline no usa
APIs pagadas). Si se añade un modelo LLM en servidor, su API key se
maneja como secreto del repositorio.

## 8. Verificación post-despliegue

- Abrir `https://<usuario>.github.io/<repo>/` y verificar que el
  dashboard carga.
- Verificar que las descargas CSV funcionan (ruta
  `/<repo>/data/<indicator>.csv`).
- Verificar que el asistente responde en modo determinista.
- Verificar que `status.json` es accesible y muestra `dataVersion`
  actual.

## 9. Rollback

Si un despliegue falla:

1. Revertir el commit en `main` (frontend) o `data` (datos).
2. GitHub Actions re-desplegará automáticamente.
3. Para datos: el pipeline preserva el último válido en `python/cache/`
   y lo sirve marcado `stale`. Ver `docs/operaciones-recuperacion.md`.
