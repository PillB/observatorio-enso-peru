# Workflow Design

**Date**: 2026-08-06T08:53:10.610680+00:00

## Architecture

### Reusable workflow
`_refresh-build-deploy.yml` is called by:
- `daily-refresh.yml` (schedule: 23:37 America/Lima)
- Manual dispatch
- Repository dispatch (enso-refresh)
- Watchdog recovery

### Concurrency
All workflows use group: `enso-production-publication` with `cancel-in-progress: false`.

### Pipeline steps
1. Checkout
2. Setup Python
3. Install dependencies
4. Run unified acquisition (staging → publication)
5. Run pytest (scientific tests)
6. Validate publication coherence
7. Setup Pages
8. Upload artifact
9. Deploy to Pages
10. Verify live deployment

### CLI options
- `--staging-dir`: Directory for staging artifacts
- `--publication-dir`: Directory for publication
- `--dry-run`: No publication
- `--source`: Specific source only
- `--force-refresh`: Bypass conditional cache
- `--offline`: Cache only, no network
- `--max-source-failures`: Maximum allowed failures

### Watchdog
`freshness-watchdog.yml` runs every 6 hours:
- Fetches live health.json
- Checks age and source status
- Dispatches recovery if >30h old and <3 consecutive failures
- Maximum: 1 rerun + 1 source-specific retry
