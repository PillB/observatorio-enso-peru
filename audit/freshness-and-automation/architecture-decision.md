# Architecture Decision Record

**Date**: 2026-08-06T08:53:10.610680+00:00
**Status**: ACCEPTED

## Context

The Observatorio ENSO Perú required an autonomous data-update system that:
1. Acquires the freshest scientifically compatible data for every indicator
2. Distinguishes rapid observations, operational indices, and official communications
3. Uses a single publication path with atomic deployment
4. Never substitutes incompatible metrics

## Decision

### Three temporal layers
- **Rapid observational**: Weekly SST (wksst8110.for)
- **Operational index**: Monthly Niño 1+2/3.4, RONI (official), SOI, winds, D20
- **Official authority**: NOAA ENSO Advisory, ENFEN status

### Single publication path
```
unified_acquisition.py → staging/ → public/data/ → Pages artifact → deploy
```

### Unified concurrency
All production workflows use `enso-production-publication` concurrency group.

### RONI methodology fix
RONI is fetched from official `RONI.ascii.txt` (seasonal product with tropical-mean adjustment), NOT computed as naive rolling mean of Niño 3.4.

### Defensive acquisition
- Circuit breaker per source (5 failures → open, 5 min recovery)
- Conditional GET (ETag, Last-Modified, 304)
- Exponential backoff with full jitter
- MIME validation, response size limits
- Atomic cache writes
- Last-known-valid fallback

### Fallback graph
5 levels per metric with explicit prohibited substitutions.

## Consequences

- RONI value changed from 1.04 (incorrect) to 0.98 (official MJJ 2026)
- 11 sources acquired successfully
- 514 tests pass
- Single publication path eliminates races
