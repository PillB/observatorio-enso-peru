# ARCHIVED — Next.js Frontend (NOT DEPLOYED)

**Status**: ARCHIVED — This directory is NOT part of the production deployment.

**Canonical frontend**: `public/index.html` (static HTML/JS deployed to GitHub Pages)

**Reason for archiving**: The Next.js application under `src/` was the original
frontend during development, but the production site at
https://pillb.github.io/observatorio-enso-peru/ is served from `public/`.

**What this means**:
- Changes to `src/` do NOT affect the live site
- TypeScript errors in `src/` do NOT affect production
- The `src/` directory is retained for reference and potential future migration
- All production fixes must be applied to `public/index.html`

**Do not** modify `src/` expecting production changes.
**Do not** run `bun run build` expecting a production artifact.

The canonical deployment path is:
```
public/ → GitHub Pages artifact → https://pillb.github.io/observatorio-enso-peru/
```
