#!/usr/bin/env bash
# Las pruebas que leen el registro y n8n/dist, con lo recién medido (sin navegador: no hace falta). Las corre la
# sonda semanal (probe-sources.yml) antes de escribir en main, y otra vez si main cambió mientras medía.
set -eo pipefail
cd "$(dirname "$0")/../.."
(cd python && python -m tools.build_registry --check && python -m pytest -q -p no:cacheprovider -m "not browser")
node n8n/build.mjs --check
node --test n8n/test/*.test.mjs
