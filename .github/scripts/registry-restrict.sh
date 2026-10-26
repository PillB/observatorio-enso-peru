#!/usr/bin/env bash
# Lo que una medición que no pasa las pruebas restringe por robots.txt, sobre el registro de main
# (python/tools/registry_restrict.py). Uso: registry-restrict.sh BASE_SOURCES BASE_REACH INFORME
set -eo pipefail
cd "$(dirname "$0")/../../python"
python -m tools.registry_restrict "$1" "$2" --report "$3"
