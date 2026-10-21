#!/usr/bin/env bash
# Recolector del Observatorio ENSO Perú en macOS y Linux (Raspberry Pi incluida):
# instalar, verificar, probar, recolectar ahora, actualizar o desinstalar.
#
# Instalar (sin opciones):
#   1. Comprueba git (en macOS ofrece las herramientas de Apple) y Python 3.11+.
#   2. Copia el kit a ~/Library/Application Support/ObservatorioENSO/recolector
#      (macOS) o ~/.local/share/observatorio-enso/recolector (Linux), o --destino.
#   3. Crea el entorno .venv e instala python/requirements.txt.
#   4. Pide el token de GitHub y lo guarda en .env (permisos 600).
#   5. Programa la tarea: agente de launchd (macOS) o crontab (Linux), a las
#      21:00 de Lima, reintentos cada 30 min hasta las 23:30 y al encender.
#   6. Ejecuta la verificación y ofrece probar la tarea de punta a punta.
# Volver a ejecutarlo es seguro: conserva el token y actualiza el resto.
#
# Uso: bash collector/instalar.sh [opciones]   (o doble clic en INSTALAR-Mac.command)
#   --token TOKEN        token de GitHub (si no, se pide sin mostrarlo)
#   --destino CARPETA    carpeta de instalación
#   --hora HH:MM         hora de Lima de la recolección (21:00)
#   --sin-tarea          no programar la tarea
#   --sin-verificar      no ejecutar la verificación al final
#   --no-interactivo     no preguntar nada (usa las respuestas por defecto)
#   --verificar          solo verificar una instalación existente
#   --probar-tarea       verificar y disparar la tarea programada
#   --recolectar-ahora   recolectar y subir una copia ahora
#   --actualizar         descargar el kit más reciente e instalarlo
#   --desinstalar        quitar la tarea y la carpeta de instalación
#   --solo LISTA / --omitir LISTA   comprobaciones de la verificación (ver collector_check)

set -u

REPO="PillB/observatorio-enso-peru"
KIT_URL="https://github.com/$REPO/releases/download/recolector-kit/recolector-peru.zip"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
KIT_ROOT="$(cd "$HERE/.." && pwd -P)"
OS="$(uname -s)"
MARKER=".instalacion-recolector"
LAUNCHD_LABEL="io.github.pillb.observatorio-enso.recolector"
if [ -f "$KIT_ROOT/$MARKER" ] || { [ -f "$KIT_ROOT/kit.json" ] && { [ -d "$KIT_ROOT/.venv" ] || [ -f "$KIT_ROOT/.env" ]; }; }; then
  # Corre desde una instalación (sus lanzadores): esa es la carpeta, aunque
  # se haya instalado con --destino en otro lugar.
  DEST="$KIT_ROOT"
elif [ "$OS" = "Darwin" ]; then
  DEST="$HOME/Library/Application Support/ObservatorioENSO/recolector"
else
  DEST="${XDG_DATA_HOME:-$HOME/.local/share}/observatorio-enso/recolector"
fi
TOKEN=""
HORA="21:00"
HORA_GIVEN=0
MODE="instalar"
SIN_TAREA=0
SIN_VERIFICAR=0
NO_INTERACTIVO=0
TOKEN_RE='^(github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{30,})$'

say() { printf '   %s\n' "$*"; }
step() { printf '\n\033[36m== %s\033[0m\n' "$*"; }
warn() { printf '   \033[33mAVISO: %s\033[0m\n' "$*"; }
die() {
  printf '\n\033[31mERROR: %s\033[0m\n' "$1"
  [ -n "${2:-}" ] && printf '\033[33mQué hacer: %s\033[0m\n' "$2"
  exit 1
}
ask_yes_no() {  # pregunta [por defecto s|n]
  local default="${2:-s}" answer=""
  if [ "$NO_INTERACTIVO" = 1 ] || [ ! -r /dev/tty ]; then [ "$default" = s ]; return; fi
  if [ "$default" = s ]; then printf '%s [S/n] ' "$1"; else printf '%s [s/N] ' "$1"; fi
  read -r answer </dev/tty || answer=""
  [ -z "$answer" ] && { [ "$default" = s ]; return; }
  case "$answer" in [sSyY]*) return 0 ;; *) return 1 ;; esac
}

# Lanzadores de doble clic: que la ventana no se cierre antes de leer el resultado.
pause_at_exit() {
  [ -z "${ENSO_SIN_PAUSA:-}" ] && [ -r /dev/tty ] && { printf '\nPresione Enter para cerrar esta ventana. '; read -r _ </dev/tty; }
}

CHECK_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --token) TOKEN="${2:-}"; shift ;;
    --destino) DEST="${2:-}"; shift ;;
    --hora) HORA="${2:-}"; HORA_GIVEN=1; shift ;;
    --sin-tarea) SIN_TAREA=1 ;;
    --sin-verificar) SIN_VERIFICAR=1 ;;
    --no-interactivo) NO_INTERACTIVO=1 ;;
    --verificar) MODE="verificar" ;;
    --probar-tarea) MODE="probar" ;;
    --recolectar-ahora) MODE="recolectar" ;;
    --actualizar) MODE="actualizar" ;;
    --desinstalar) MODE="desinstalar" ;;
    --pausa) trap 'pause_at_exit' EXIT ;;
    --solo|--omitir) CHECK_ARGS+=("$1" "${2:-}"); shift ;;
    -h|--ayuda|--help) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "opción desconocida: $1" "bash $0 --ayuda" ;;
  esac
  shift
done
case "$HORA" in
  [01][0-9]:[0-5][0-9]|2[0-3]:[0-5][0-9]) ;;
  *) die "--hora debe ser HH:MM (por ejemplo 21:00)" ;;
esac
[ -n "$DEST" ] || die "--destino necesita una carpeta"
# Ruta absoluta: in_python cambia de carpeta antes de llamar a $VPY.
case "$DEST" in /*) ;; *) DEST="$PWD/${DEST#./}" ;; esac
VPY="$DEST/.venv/bin/python"
ENV_FILE="$DEST/.env"

py_ok() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; }
py_version() { "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null; }

find_python() {
  local c p
  for c in python3.13 python3.12 python3.14 python3.11 \
           /opt/homebrew/bin/python3 /usr/local/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 \
           python3; do
    p="$(command -v "$c" 2>/dev/null)" || continue
    if py_ok "$p"; then PYTHON="$p"; return 0; fi
  done
  return 1
}

ensure_git() {
  if git --version >/dev/null 2>&1; then say "git: $(command -v git) ($(git --version | sed 's/git version //'))"; return; fi
  if [ "$OS" = "Darwin" ]; then
    xcode-select --install >/dev/null 2>&1
    die "Falta git. Se abrió el instalador de las herramientas de desarrollo de Apple." \
        "Aceptar la instalación (unos minutos) y volver a ejecutar INSTALAR."
  fi
  die "Falta git." "sudo apt install git   (o el gestor de paquetes de su sistema) y volver a ejecutar."
}

ensure_python() {
  PYTHON=""
  if ! find_python; then
    if [ "$OS" = "Darwin" ] && command -v brew >/dev/null 2>&1 && ask_yes_no "No se encontró Python 3.11+. ¿Instalar Python 3.12 con Homebrew?" s; then
      brew install python@3.12 || warn "Homebrew no pudo instalar Python."
      find_python || true
    fi
  fi
  if [ -z "$PYTHON" ]; then
    if [ "$OS" = "Darwin" ]; then
      open "https://www.python.org/downloads/macos/" >/dev/null 2>&1 || true
      die "No se encontró Python 3.11 o más reciente." \
          "Instalar Python 3.12 desde python.org (se abrió la página) y volver a ejecutar INSTALAR."
    fi
    die "No se encontró Python 3.11 o más reciente." "sudo apt install python3 python3-venv   y volver a ejecutar."
  fi
  say "Python $(py_version "$PYTHON"): $PYTHON"
}

copy_kit() {
  local src dst f launchers
  mkdir -p "$DEST" || die "No se puede crear $DEST"
  src="$KIT_ROOT"
  dst="$(cd "$DEST" && pwd -P)"
  if [ "$src" = "$dst" ]; then say "Se usa la carpeta actual."; return; fi
  [ -f "$src/python/tools/peru_collector.py" ] || die "No se encuentra el código del recolector junto a este instalador ($src)." \
      "Descomprimir el kit completo y ejecutar INSTALAR desde esa carpeta."
  require_free_dest
  printf '%s\n' "Carpeta del recolector del Observatorio ENSO. DESINSTALAR la borra entera: no guardar aquí otros archivos." \
    > "$DEST/$MARKER"
  rm -rf "$DEST/python/enso" "$DEST/python/tools" "$DEST/config" "$DEST/registry" "$DEST/collector" "$DEST/otras-acciones"
  mkdir -p "$DEST/python" "$DEST/docs"
  cp "$src/python/requirements.txt" "$DEST/python/"
  cp -R "$src/python/enso" "$src/python/tools" "$DEST/python/"
  cp -R "$src/config" "$src/collector" "$DEST/"
  # Los lanzadores van en la raíz: en el kit ya están ahí; en una copia del
  # repositorio, en collector/lanzadores (y el LEEME, en collector/).
  launchers="$src"
  [ -d "$src/otras-acciones" ] || launchers="$src/collector/lanzadores"
  [ -d "$launchers/otras-acciones" ] && cp -R "$launchers/otras-acciones" "$DEST/"
  [ -d "$src/registry" ] && cp -R "$src/registry" "$DEST/"
  cp "$src/docs/servidor-peru.md" "$DEST/docs/"
  [ -f "$src/LEEME.txt" ] || cp "$src/collector/LEEME.txt" "$DEST/" 2>/dev/null
  for f in "$src/LEEME.txt" "$src/LICENSE" "$src/kit.json" "$launchers"/*.command "$launchers"/*.cmd; do
    [ -f "$f" ] && cp "$f" "$DEST/"
  done
  find "$DEST" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
  # Un zip abierto con «python -m zipfile» (ACTUALIZAR), una memoria USB o una
  # carpeta en la nube pierden el permiso de ejecución de los lanzadores.
  chmod +x "$DEST"/*.command "$DEST"/otras-acciones/*.command "$DEST"/collector/*.sh 2>/dev/null || true
  if [ "$OS" = "Darwin" ]; then xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true; fi
  say "Archivos copiados a $DEST"
}

make_venv() {
  local want have req out
  want="$(py_version "$PYTHON")"
  have=""
  [ -x "$VPY" ] && have="$(py_version "$VPY")"
  if [ "$have" != "$want" ]; then
    rm -rf "$DEST/.venv"
    if ! out="$("$PYTHON" -m venv "$DEST/.venv" 2>&1)"; then
      case "$out" in
        *ensurepip*|*python3-venv*) die "Falta el módulo venv de Python." "sudo apt install python3-venv   (o python${want}-venv) y volver a ejecutar." ;;
        *) die "No se pudo crear el entorno de Python: $out" ;;
      esac
    fi
  fi
  req="$DEST/python/requirements.txt"
  if ! out="$("$VPY" -m pip install --disable-pip-version-check --no-input -q -r "$req" 2>&1)"; then
    # Con un proxy o antivirus que inspecciona HTTPS, pip necesita los certificados del sistema.
    out="$("$VPY" -m pip install --disable-pip-version-check --no-input -q -r "$req" --use-feature=truststore 2>&1)" ||
      die "No se pudieron instalar las dependencias: $(printf '%s' "$out" | tail -n 8)" "Revisar la conexión a internet y volver a ejecutar."
  fi
  say "Entorno listo: $VPY"
}

env_value() {  # clave
  [ -f "$ENV_FILE" ] || return 0
  sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" | head -n 1 | tr -d '"'"'"'\r'
}

read_token() {
  local t i
  [ -r /dev/tty ] || die "No hay token y no se puede preguntar." "Usar --token o ejecutar en una Terminal."
  say "Pegue el token de GitHub (empieza con github_pat_). No se verá al pegarlo; luego Enter."
  for i in 1 2 3; do
    printf '   Token: '
    IFS= read -r -s t </dev/tty || t=""
    printf '\n'
    t="$(printf '%s' "$t" | tr -d '[:space:]')"
    if [[ "$t" =~ $TOKEN_RE ]]; then NEW_TOKEN="$t"; return 0; fi
    warn "Eso no parece un token de GitHub (github_pat_... o ghp_...). Intente de nuevo ($i/3)."
  done
  die "No se recibió un token válido." "Crear el token como indica docs/servidor-peru.md y volver a ejecutar."
}

save_env() {  # token hora
  local tmp="$ENV_FILE.tmp"
  (
    umask 077
    {
      echo "# Recolector ENSO Peru: configuracion local. No compartir este archivo."
      [ -n "$1" ] && echo "GITHUB_TOKEN=$1"
      echo "ENSO_COLLECT_AT=$2"
      # Proxy, certificados y contacto de esta terminal: la tarea programada no los hereda.
      for v in HTTPS_PROXY HTTP_PROXY NO_PROXY https_proxy http_proxy no_proxy SSL_CERT_FILE ENSO_CONTACT_URL; do
        eval "val=\${$v:-}"
        # shellcheck disable=SC2154
        if [ -n "$val" ] && ! grep -q "^$v=" "$ENV_FILE" 2>/dev/null; then echo "$v=$val"; fi
      done
      if [ -f "$ENV_FILE" ]; then
        grep -Ev '^[[:space:]]*(GITHUB_TOKEN|ENSO_COLLECT_AT)[[:space:]]*=|^# Recolector ENSO|^[[:space:]]*$' "$ENV_FILE" || true
      fi
    } >"$tmp"
  ) || die "No se pudo escribir $ENV_FILE"
  mv "$tmp" "$ENV_FILE" && chmod 600 "$ENV_FILE"
}

in_python() { (cd "$DEST/python" && ENSO_HOME="$DEST" "$VPY" "$@"); }

require_installed() {
  [ -x "$VPY" ] || die "El recolector no está instalado en $DEST." "Ejecutar primero INSTALAR."
}

do_install() {
  local current tail at saved code
  printf '\033[32mObservatorio ENSO Perú: instalación del recolector\033[0m\n'
  say "Carpeta de instalación: $DEST"

  step "1/6 Git"
  ensure_git
  step "2/6 Python"
  ensure_python
  step "3/6 Archivos"
  copy_kit
  mkdir -p "$DEST/logs"
  step "4/6 Entorno de Python y dependencias"
  make_venv

  step "5/6 Token de GitHub"
  at="$HORA"
  saved="$(env_value ENSO_COLLECT_AT)"
  [ -n "$saved" ] && [ "$HORA_GIVEN" = 0 ] && at="$saved"
  current="$(env_value GITHUB_TOKEN)"
  NEW_TOKEN=""
  if [ -n "$TOKEN" ]; then
    TOKEN="$(printf '%s' "$TOKEN" | tr -d '[:space:]')"
    [[ "$TOKEN" =~ $TOKEN_RE ]] || die "El token indicado no tiene el formato de GitHub."
    NEW_TOKEN="$TOKEN"
  elif [ -n "$current" ]; then
    tail="${current: -4}"
    if ask_yes_no "Ya hay un token guardado (termina en …$tail). ¿Mantenerlo?" s; then NEW_TOKEN="$current"; else read_token; fi
  elif [ "$NO_INTERACTIVO" = 0 ]; then
    read_token
  else
    warn "Sin token: la recolección no podrá subir copias. Ejecutar INSTALAR otra vez para agregarlo."
  fi
  save_env "$NEW_TOKEN" "$at"
  [ -n "$NEW_TOKEN" ] && say "Token guardado en $ENV_FILE (solo lo puede leer este usuario)."

  step "6/6 Tarea programada"
  if [ "$SIN_TAREA" = 1 ]; then
    say "Omitida (--sin-tarea)."
  elif [ "$OS" != "Darwin" ] && ! command -v crontab >/dev/null 2>&1; then
    warn "No hay cron en este equipo: la tarea no se programó. Ver «Linux con systemd» en docs/servidor-peru.md."
  else
    in_python -m tools.collector_schedule instalar --python "$VPY" --hora "$at" ||
      die "No se pudo programar la tarea." "Volver a ejecutar INSTALAR; si sigue, enviar la salida a quien mantiene el sitio."
    [ "$OS" = "Darwin" ] && say "macOS puede mostrar «Se añadió un ítem en segundo plano» (python): es esta tarea."
  fi

  code=0
  if [ "$SIN_VERIFICAR" = 0 ]; then
    step "Verificación"
    in_python -m tools.collector_check; code=$?
    if [ "$SIN_TAREA" = 0 ] && [ -n "$NEW_TOKEN" ] && [ "$NO_INTERACTIVO" = 0 ] &&
       ask_yes_no "¿Probar ahora la tarea programada? Recolecta y sube una copia real (1 a 5 minutos)." s; then
      in_python -m tools.collector_check --solo tarea --probar-tarea; code=$?
    fi
  fi
  printf '\n\033[32mInstalación terminada.\033[0m\n'
  say "Registro diario: $DEST/logs/recolector.log"
  say "Para revisar más adelante: doble clic en VERIFICAR-Mac.command (en esta carpeta o en $DEST)."
  return $code
}

sha256_check() {  # carpeta archivo.sha256
  if command -v shasum >/dev/null 2>&1; then (cd "$1" && shasum -a 256 -c "$2" >/dev/null)
  else (cd "$1" && sha256sum -c "$2" >/dev/null); fi
}

# Solo se borra una carpeta que es claramente una instalación del recolector.
# Una carpeta es del recolector si la instalación la marcó, o si tiene el kit
# completo (kit.json y el código). Un .venv o un kit.json sueltos no bastan:
# DESINSTALAR la borra entera.
is_install() {
  case "$1" in ""|/|"$HOME"|"$HOME/") return 1 ;; esac
  [ -f "$1/$MARKER" ] || { [ -f "$1/kit.json" ] && [ -f "$1/python/tools/collector_service.py" ]; }
}

looks_like_install() { is_install "$DEST"; }

same_dir() {
  local a b
  a=$(cd "$1" 2>/dev/null && pwd -P) && b=$(cd "$2" 2>/dev/null && pwd -P) && [ "$a" = "$b" ]
}

# Carpeta de la instalación a la que apunta la tarea programada (nada si no hay
# tarea o no se sabe): ENSO_HOME en el agente de launchd o en la línea del crontab.
task_root() {
  local v=""
  if [ "$OS" = "Darwin" ]; then
    local plist="$HOME/Library/LaunchAgents/$LAUNCHD_LABEL.plist"
    [ -f "$plist" ] && v=$(/usr/libexec/PlistBuddy -c 'Print :EnvironmentVariables:ENSO_HOME' "$plist" 2>/dev/null)
  elif command -v crontab >/dev/null 2>&1; then
    v=$(crontab -l 2>/dev/null | grep 'observatorio-enso-recolector' \
      | sed -nE "s/.*ENSO_HOME=('[^']*'|[^ ']+) .*/\1/p" | head -n 1 | tr -d "'")
  fi
  case "$v" in /*) printf '%s\n' "$v" ;; esac
}

# Instalar solo en una carpeta nueva, vacía (o con solo logs/) o que ya es del recolector.
dest_is_free() {
  [ -d "$DEST" ] || return 0
  looks_like_install && return 0
  case "$DEST" in ""|/|"$HOME"|"$HOME/") return 1 ;; esac
  local f
  for f in "$DEST"/* "$DEST"/.[!.]* "$DEST"/..?*; do
    [ -e "$f" ] || [ -L "$f" ] || continue
    [ "$f" = "$DEST/logs" ] || return 1
  done
}

require_free_dest() {
  dest_is_free || die "La carpeta $DEST ya tiene otros archivos y no es una instalación del recolector." \
    "Elegir una carpeta nueva o vacía con --destino: DESINSTALAR borra la carpeta entera."
}

# Con el repositorio privado la descarga pública da 404: se pide con el token, por la API.
download_with_token() {  # carpeta
  local token api name url py=python3
  [ -x "$VPY" ] && py="$VPY"
  token="$(sed -n 's/^[[:space:]]*GITHUB_TOKEN[[:space:]]*=[[:space:]]*//p' "$ENV_FILE" 2>/dev/null | head -1 | tr -d '"'"'"'\r')"
  [ -n "$token" ] || return 1
  say "Descarga pública no disponible; se usa el token."
  api="$(curl -fsSL -H "Authorization: Bearer $token" -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$REPO/releases/tags/recolector-kit")" || return 1
  for name in recolector-peru.zip recolector-peru.zip.sha256; do
    url="$(printf '%s' "$api" | "$py" -c 'import json,sys; n=sys.argv[1]; print(next(a["url"] for a in json.load(sys.stdin)["assets"] if a["name"]==n))' "$name" 2>/dev/null)" || return 1
    curl -fsSL -H "Authorization: Bearer $token" -H "Accept: application/octet-stream" -o "$1/$name" "$url" || return 1
  done
}

do_update() {
  local tmp code
  tmp="$(mktemp -d)" || die "No se pudo crear una carpeta temporal."
  say "Descargando $KIT_URL"
  if ! { curl -fsSL -o "$tmp/recolector-peru.zip" "$KIT_URL" && curl -fsSL -o "$tmp/recolector-peru.zip.sha256" "$KIT_URL.sha256"; } &&
     ! download_with_token "$tmp"; then
    rm -rf "$tmp"; die "No se pudo descargar el kit." "Revisar la conexión y repetir."
  fi
  sha256_check "$tmp" recolector-peru.zip.sha256 || { rm -rf "$tmp"; die "El kit descargado no coincide con su sha256."; }
  local py="$VPY"
  [ -x "$py" ] || py="$(command -v python3)"
  "$py" -m zipfile -e "$tmp/recolector-peru.zip" "$tmp" || { rm -rf "$tmp"; die "No se pudo descomprimir el kit."; }
  bash "$tmp/recolector-peru/collector/instalar.sh" --destino "$DEST" --no-interactivo; code=$?
  rm -rf "$tmp"
  return $code
}

do_uninstall() {
  step "Desinstalar el recolector"
  ask_yes_no "Se quitará la tarea programada y la carpeta $DEST (con el token). ¿Continuar?" s || return 0
  # La tarea es una por usuario y la toma la última instalación. Se quita si es
  # de esta carpeta o si la suya ya no está; la de otra instalación en uso,
  # nunca (un --destino equivocado no la deja sin tarea). Si no se sabe de
  # quién es, solo al desinstalar una instalación.
  local removed=1 other
  other=$(task_root)
  if [ -n "$other" ] && is_install "$other" && ! same_dir "$other" "$DEST"; then
    warn "La tarea programada es de la instalación en $other: no se tocó."
  elif [ -z "$other" ] && ! looks_like_install; then
    :
  elif [ -x "$VPY" ] && looks_like_install; then
    in_python -m tools.collector_schedule quitar || removed=0
  elif [ "$OS" = "Darwin" ]; then
    # Como remove_launchd: bootout y, para un agente cargado sin sesión gráfica
    # (con «load»), unload; si launchd lo sigue viendo, no se borra nada.
    local plist="$HOME/Library/LaunchAgents/$LAUNCHD_LABEL.plist"
    launchctl bootout "gui/$(id -u)/$LAUNCHD_LABEL" 2>/dev/null
    [ -f "$plist" ] && launchctl unload "$plist" 2>/dev/null
    sleep 2
    if launchctl print "gui/$(id -u)/$LAUNCHD_LABEL" >/dev/null 2>&1 \
        || launchctl list 2>/dev/null | awk -v l="$LAUNCHD_LABEL" '$NF == l { found = 1 } END { exit !found }'; then
      removed=0
    else
      rm -f "$plist" || removed=0
    fi
  elif command -v crontab >/dev/null 2>&1; then
    # Sin crontab no hay nada que quitar; si no se puede leer, no se reescribe a ciegas.
    local cur
    if cur=$(crontab -l 2>/dev/null); then
      case "$cur" in
        *observatorio-enso-recolector*)
          printf '%s\n' "$cur" | grep -v 'observatorio-enso-recolector' | crontab - || removed=0 ;;
      esac
    else
      case "$(crontab -l 2>&1)" in
        *"no crontab"* | *"No such file"* | *"no such file"*) ;;
        *) removed=0 ;;
      esac
    fi
  fi
  # Sin la tarea quitada, borrar la carpeta dejaría una tarea que falla cada noche.
  [ "$removed" = 1 ] || die "No se pudo quitar la tarea programada; la carpeta $DEST no se borró." \
    "Repetir DESINSTALAR. Si sigue, quitarla a mano (crontab -e en Linux) y luego borrar la carpeta."
  cd "$HOME" || true
  if looks_like_install; then
    rm -rf "$DEST" && say "Carpeta $DEST borrada."
  elif [ -e "$DEST" ]; then
    warn "$DEST no parece una instalación del recolector: no se borró."
  fi
  say "Listo. Si el token ya no se usará, revocarlo en https://github.com/settings/personal-access-tokens"
}

case "$MODE" in
  instalar)
    require_free_dest
    mkdir -p "$DEST/logs" 2>/dev/null
    LOGF="$DEST/logs/instalacion-$(date +%Y%m%d-%H%M%S).txt"
    # Registro de la instalación sin perder la terminal interactiva.
    if [ -d "$DEST/logs" ] && command -v tee >/dev/null 2>&1; then
      do_install 2>&1 | tee "$LOGF"
      exit "${PIPESTATUS[0]}"
    fi
    do_install ;;
  verificar) require_installed; in_python -m tools.collector_check ${CHECK_ARGS[@]+"${CHECK_ARGS[@]}"} ;;
  probar) require_installed; in_python -m tools.collector_check --probar-tarea ${CHECK_ARGS[@]+"${CHECK_ARGS[@]}"} ;;
  recolectar) require_installed; printf 'Recolectando y subiendo la copia ahora (1 a 5 minutos)...\n'; in_python -m tools.collector_service ;;
  actualizar) do_update ;;
  desinstalar) do_uninstall ;;
esac
