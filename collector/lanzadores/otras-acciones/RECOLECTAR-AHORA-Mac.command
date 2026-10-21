#!/bin/bash
# Observatorio ENSO Perú: recolectar y subir una copia ahora.
# Doble clic para ejecutar (o en Terminal: bash RECOLECTAR-AHORA-Mac.command).
# Todo va entre llaves para que bash lo lea completo antes de ejecutarlo.
{
  here="$(cd "$(dirname "$0")" && pwd)"
  for s in "$here/collector/instalar.sh" "$here/../collector/instalar.sh" "$here/../instalar.sh" "$here/../../instalar.sh"; do
    [ -f "$s" ] && break
  done
  bash "$s" --recolectar-ahora --pausa "$@"
  exit $?
}
