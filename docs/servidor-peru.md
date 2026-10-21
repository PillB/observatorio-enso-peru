# Recolector desde el Perú (mini servidor)

SENAMHI, ANA e IMARPE no responden a GitHub Actions y el portal del ENFEN
no resuelve desde allí (ver [catálogo de fuentes](catalogo-fuentes.md)).
El recolector (`python/tools/peru_collector.py`) corre en una computadora
en el Perú que sí llega a esas fuentes, guarda cada respuesta original y la
sube a la rama `data-peru`. La actualización diaria la usa como canal
«relay-peru»: cuando una URL no responde, toma la copia que el recolector
bajó de esa misma URL, comprueba su sha256 y su antigüedad, y la marca en
el registro de fuentes y en el sitio («vía recolector en el Perú»).

**En resumen:** crear un [token de GitHub](#1-token-de-github), descargar
el [kit](#2-descargar-el-kit) (un .zip de unos 175 KB), copiarlo a la
computadora en el Perú y hacer doble clic en `INSTALAR` y luego en
`VERIFICAR`. Funciona en Windows 10/11, macOS 12 o más reciente y Linux
(Raspberry Pi incluida).

## Cómo encaja en el día

| Hora (Lima) | Qué pasa |
|---|---|
| 21:00 | La tarea programada descarga el listado y los PDF del ENFEN (incluidos los sondeos de los dos números siguientes) y las páginas de SENAMHI, ANA e IMARPE, y sube la copia a `data-peru` |
| 21:00 + unos minutos | Pide a GitHub la actualización del sitio en el momento (`--dispatch`) |
| 21:30 a 23:30 | Reintentos cada 30 minutos, solo si la de las 21:00 falló |
| Al encender o iniciar sesión | Si esa noche no hubo copia (equipo apagado o sin internet), la recolecta en ese momento |
| 23:37 | Corrida diaria del sitio; usa la copia si la fuente sigue sin responder desde GitHub |

Si la última copia tiene más de 36 horas, la corrida diaria registra la
incidencia `relay-stale` y abre un issue. Copias de más de 7 días no se
usan. Si la rama `data-peru` no existe, el sitio funciona igual que antes.

Las páginas de SENAMHI, ANA e IMARPE quedan guardadas para construir y
probar sus lectores; todavía no alimentan indicadores del sitio.

## Lo que necesita la computadora

| | |
|---|---|
| Sistema | Windows 10 u 11, macOS 12 o más reciente, o Linux (Debian, Ubuntu, Raspberry Pi OS) |
| Internet | Una conexión **en el Perú** (casa u oficina). Sin VPN hacia otro país |
| Encendida | A las 21:00, o que se encienda después: la recolección se recupera sola |
| Python 3.11+ y Git | El instalador los busca y, si faltan, los instala (winget en Windows; herramientas de Apple o Homebrew en macOS) |
| Espacio | Unos 300 MB |
| Cuenta | La del usuario habitual; no hace falta abrir puertos ni crear cuentas en la nube |

Antes de dejarla funcionando, `VERIFICAR` comprueba que las fuentes
peruanas respondan desde esa conexión: es lo único que no se puede saber
desde afuera.

## 1. Token de GitHub

Lo crea quien mantiene el sitio (la cuenta dueña del repositorio) y se lo
pasa a quien instala, por un canal privado:

1. GitHub → foto de perfil → **Settings** → **Developer settings** →
   **Personal access tokens** → **Fine-grained tokens** →
   **Generate new token**.
2. Nombre: `recolector-peru`. Vencimiento: **1 año** (anotar la fecha).
3. **Repository access** → *Only select repositories* →
   `PillB/observatorio-enso-peru`.
4. **Permissions** → **Repository permissions** → **Contents: Read and
   write**. Ningún otro permiso. Alcanza para subir a `data-peru` y para
   pedir la actualización del sitio.
5. **Generate token** y copiarlo (empieza con `github_pat_`). GitHub no lo
   vuelve a mostrar.

El token nunca se guarda en el repositorio ni aparece en los registros.
Para renovarlo: crear uno nuevo igual, ejecutar `INSTALAR` en la
computadora del recolector, responder «n» a «¿Mantenerlo?» y pegar el
nuevo; luego borrar el viejo en GitHub. La corrida diaria del sitio abre un
issue `relay-token-expiring` 21 días antes del vencimiento, y la
computadora muestra un aviso en el escritorio.

## 2. Descargar el kit

El kit tiene todo lo que la computadora necesita: el programa, sus
dependencias (`python/requirements.txt`), la configuración, los
instaladores, los lanzadores de doble clic, la verificación y este manual.

- **Última versión:** [recolector-peru.zip](https://github.com/PillB/observatorio-enso-peru/releases/download/recolector-kit/recolector-peru.zip)
  ([sha256](https://github.com/PillB/observatorio-enso-peru/releases/download/recolector-kit/recolector-peru.zip.sha256)).
  Lo publica el flujo `recolector-kit` en cada cambio de `main` que toca
  el recolector, después de probarlo en Windows, macOS y Linux. Si el
  repositorio pasa a ser privado, este enlace pide iniciar sesión en
  GitHub: compartir el .zip directamente (`ACTUALIZAR` sigue funcionando,
  porque descarga con el token).
- **Antes de que exista esa versión** (o para una rama): en GitHub →
  Actions → `recolector-kit` → la corrida → *Artifacts* →
  `recolector-peru`; o armarlo desde el repositorio:
  `cd python && python -m tools.collector_kit --out ../dist`.

Se puede pasar a la computadora por correo, WhatsApp o USB. Para comprobar
que llegó entero, comparar su huella con el archivo `.sha256`:
`Get-FileHash recolector-peru.zip` (PowerShell) o
`shasum -a 256 recolector-peru.zip` (Terminal de macOS).

| En el kit | Para qué |
|---|---|
| `LEEME.txt` | Los pasos de esta página, en corto |
| `INSTALAR-Windows.cmd`, `INSTALAR-Mac.command` | Instalar o reinstalar (es seguro repetirlo; conserva el token) |
| `VERIFICAR-Windows.cmd`, `VERIFICAR-Mac.command` | Revisar todo y decir qué hacer con cada problema |
| `otras-acciones/` | `PROBAR-TAREA`, `RECOLECTAR-AHORA`, `ACTUALIZAR`, `DESINSTALAR` (Windows y Mac) |
| `collector/instalar.ps1`, `collector/instalar.sh` | Los instaladores que llaman los lanzadores |
| `collector/Dockerfile`, `docker-compose.yml`, `enso-collector.service`, `.timer` | Para [Docker y systemd](#otras-formas-de-correrlo) |
| `python/` | El recolector, la tarea, la verificación y `requirements.txt` |
| `config/`, `docs/servidor-peru.md`, `LICENSE` | Configuración, este manual y la licencia |
| `kit.json` | Versión y sha256 de cada archivo (la verificación detecta archivos faltantes o modificados) |

## 3. Instalar

El instalador hace seis pasos y muestra cada uno: Python, Git, archivos,
entorno de Python con sus dependencias, token y tarea programada. Al final
ejecuta la verificación y ofrece **probar la tarea programada**: la
dispara como lo hará el sistema a las 21:00, recolecta, sube una copia y
muestra el resultado. Si esa prueba da `OK`, quedó todo listo.

### Windows

1. Clic derecho en `recolector-peru.zip` → **Propiedades** → marcar
   **Desbloquear** → Aceptar. Después, clic derecho → **Extraer todo**.
2. Doble clic en `INSTALAR-Windows.cmd`. Si aparece «Windows protegió su
   PC»: **Más información** → **Ejecutar de todas formas**.
3. Si falta Python o Git, responder `S`: se instalan con winget (Windows
   puede pedir permiso).
4. Pegar el token cuando lo pida (clic derecho o Ctrl+V; no se ve) y Enter.
5. Responder `S` a «¿Probar ahora la tarea programada?».

Queda instalado en `%LOCALAPPDATA%\ObservatorioENSO\recolector`, con
accesos en el menú Inicio → **Observatorio ENSO** (Verificar, Probar la
tarea, Recolectar ahora, Registro, Actualizar, Desinstalar).

**Sin sesión iniciada:** de forma normal la tarea corre cuando el usuario
tiene la sesión iniciada (aunque la pantalla esté bloqueada). Para que
corra también después de un reinicio sin que nadie inicie sesión (por
ejemplo, tras las actualizaciones de Windows), ejecutar `INSTALAR` con
clic derecho → **Ejecutar como administrador**, desde la cuenta de uso
habitual. No usar otra cuenta de administrador: la instalación quedaría en
el perfil de esa otra cuenta.

### macOS

1. Doble clic en `recolector-peru.zip` para descomprimirlo.
2. Abrir **Terminal**, escribir `bash` y un espacio, arrastrar
   `INSTALAR-Mac.command` a la ventana y presionar Enter. (El doble clic
   también funciona; si macOS dice que no puede comprobar el desarrollador:
   **Ajustes del Sistema → Privacidad y seguridad → Abrir igualmente**.)
3. Si aparece la instalación de las «herramientas de línea de comandos»
   (trae Git), aceptarla y, cuando termine, repetir el paso 2.
4. Si falta Python 3.11+, el instalador lo instala con Homebrew o abre la
   página de python.org: instalar el paquete y repetir el paso 2.
5. Pegar el token (Cmd+V; no se ve) y Enter. Responder `S` a la prueba.

Queda instalado en `~/Library/Application Support/ObservatorioENSO/recolector`
con un agente de launchd (`io.github.pillb.observatorio-enso.recolector`).
macOS puede avisar «Se añadió un ítem en segundo plano (python)»: es esta
tarea. Para revisar después: doble clic en `VERIFICAR-Mac.command`.

En una MacBook, la tarea no corre con la tapa cerrada sin corriente; corre
al despertar. Para un horario fijo, en **Ajustes del Sistema → Batería →
Opciones** activar «Evitar el reposo automático con el adaptador de
corriente», o programar el encendido: `sudo pmset repeat wakeorpoweron MTWRFSU 20:55:00`.

### Linux o Raspberry Pi

```bash
unzip recolector-peru.zip && bash recolector-peru/collector/instalar.sh
```

Queda en `~/.local/share/observatorio-enso/recolector` con líneas en el
`crontab` del usuario (marcadas `observatorio-enso-recolector`), incluida
una al encender (`@reboot`). Si faltan Python o el módulo venv:
`sudo apt install git python3 python3-venv`. Si dice «no se pudo leer el
crontab», el usuario no tiene permiso para usar cron (`/etc/cron.allow` o
`/etc/cron.deny`): el instalador no toca el crontab ni, al desinstalar,
borra la carpeta hasta que `crontab -l` funcione.

### Opciones

Los lanzadores llaman a `collector/instalar.ps1` (Windows) o
`collector/instalar.sh` (macOS y Linux), que aceptan:

| Windows | macOS y Linux | Qué hace |
|---|---|---|
| *(ninguna)* | *(ninguna)* | Instalar o reinstalar |
| `-Verificar` | `--verificar` | Solo verificar |
| `-ProbarTarea` | `--probar-tarea` | Verificar y disparar la tarea programada (sube una copia real) |
| `-RecolectarAhora` | `--recolectar-ahora` | Recolectar y subir ahora, mostrando el avance |
| `-Actualizar` | `--actualizar` | Descargar la última versión del kit, comprobar su sha256 e instalarla conservando el token |
| `-Desinstalar` | `--desinstalar` | Quitar la tarea y la carpeta de instalación |
| `-Token github_pat_...` | `--token github_pat_...` | Dar el token sin preguntarlo (queda en el historial de la terminal: preferir que lo pida) |
| `-Destino CARPETA` | `--destino CARPETA` | Otra carpeta de instalación: nueva o vacía, porque `DESINSTALAR` la borra entera (una carpeta con otros archivos se rechaza) |
| `-Hora 21:00` | `--hora 21:00` | Otra hora de Lima para la recolección |
| `-SinTarea`, `-SinVerificar`, `-NoInteractivo` | `--sin-tarea`, `--sin-verificar`, `--no-interactivo` | Para instalaciones automáticas |
| `-Solo a,b`, `-Omitir a,b` | `--solo a,b`, `--omitir a,b` | Elegir comprobaciones de la verificación |

Ejemplo en PowerShell: `powershell -ExecutionPolicy Bypass -File collector\instalar.ps1 -ProbarTarea`.

## 4. Verificar

`VERIFICAR` revisa todo lo que la recolección necesita y, para cada
problema, dice qué hacer. Cada línea empieza con `OK`, `AVISO` (funciona,
pero conviene revisar), `FALLA` (no va a funcionar) o `INFO`. El informe
queda en la carpeta `logs` de la instalación
(`verificacion-AAAAMMDD-HHMMSS.txt`) para enviarlo a quien mantiene el
sitio; nunca incluye el token.

| Comprobación | Qué revisa |
|---|---|
| `python` | Python 3.11 o más reciente, dentro del entorno de la instalación |
| `dependencias` | httpx, PyYAML, pypdf y, en Windows y macOS, truststore |
| `zona-horaria` | Datos de America/Lima; avisa si el equipo usa otra zona |
| `codigo` | El recolector carga y cada archivo coincide con `kit.json` |
| `git` | Git instalado y respondiendo |
| `internet` | GitHub responde, sin portal cautivo ni reloj desfasado; antigüedad de la última copia en `data-peru` |
| `token` | Presente, aceptado por GitHub, fecha de vencimiento, archivo `.env` privado |
| `escritura` | El token puede subir al repositorio (`git push --dry-run`: no sube nada) |
| `fuentes` | ENFEN, SENAMHI, ANA e IMARPE responden desde esta conexión |
| `tarea` | La tarea programada existe, está habilitada y apunta a esta instalación |
| `ultima-corrida` | Resultado de la última recolección y fallas seguidas |
| `disco` | Espacio libre |

`PROBAR-TAREA` (o `-ProbarTarea` / `--probar-tarea`) agrega la prueba de
punta a punta: dispara la tarea programada con el mismo entorno que tendrá
a las 21:00 (sin consola, sin las variables de la terminal), espera hasta
15 minutos y muestra si recolectó y subió. No pide la actualización del
sitio. Es la prueba que detecta los problemas que solo aparecen cuando
nadie está mirando.

## Cómo funciona cada día

- **La tarea** corre `python -m tools.collector_service --programado`. En
  Windows es el Programador de tareas (con `pythonw.exe`, sin ventana; se
  despierta el equipo si está suspendido y recupera la corrida perdida al
  encender); en macOS, el agente de launchd (al despertar y al iniciar
  sesión); en Linux, cron.
- **Una copia por noche:** cada disparo comprueba en `estado.json` si ya
  hay copia de las 21:00 de hoy (hora de Lima, aunque el equipo tenga otra
  zona). Si la hay, termina sin hacer nada; si no, recolecta. Así los
  reintentos y la recuperación al encender no repiten trabajo.
- **Antes de recolectar** comprueba el token con GitHub y anota su
  vencimiento. **Después**, si ninguna fuente respondió, sube solo el
  latido (abajo): la última copia buena se conserva en `data-peru`.
- **Lo que sube:** `index.json` (cada URL con su estado, tamaño, hora y
  sha256, más un diagnóstico del equipo: versión del kit, sistema, Python,
  Git, fallas previas, vencimiento del token), los archivos originales en
  `files/` y `heartbeat.json`. Se puede ver en GitHub, rama `data-peru`.
- **El latido** (`heartbeat.json`) se sube en cada corrida que llega a
  GitHub, aunque ninguna fuente responda: hora, resultado (`ok` o
  `sin-fuentes`), cuántas fuentes respondieron, cuáles fallaron y por qué.
  Con él el sitio distingue «el equipo no corre» (latido viejo:
  `relay-stale`) de «las instituciones no responden ni desde el Perú»
  (latido reciente: `relay-sources-down`).
- **Protecciones:** un candado impide dos corridas a la vez; una corrida
  colgada se corta a los 45 minutos; git corre sin ventanas de contraseña
  ni ayudantes de credenciales (el token no termina en el Llavero ni en el
  Administrador de credenciales) y corta una subida trabada.
- **Registro:** `logs/recolector.log` (rota a los 2 MB y guarda 5),
  `estado.json` (último intento, resultado, motivo y qué hacer),
  `logs/launchd.log` (macOS) o `logs/cron.log` (Linux) para errores de
  arranque, y `logs/instalacion-*.txt`.

## Alarmas

| Dónde | Cuándo | Qué hacer |
|---|---|---|
| Escritorio de la computadora | Dos fallas seguidas (un aviso por día) | Abrir `VERIFICAR` y seguir las indicaciones |
| Escritorio de la computadora | El token vence en menos de 21 días | [Renovar el token](#1-token-de-github) |
| Issue `relay-stale` en GitHub | La última copia y el último latido tienen más de 36 horas: el equipo no está corriendo | Pedir que ejecuten `VERIFICAR` y envíen el informe |
| Issue `relay-sources-down` en GitHub | El equipo funciona, pero hace más de 36 horas que ninguna fuente peruana le responde | Nada en el equipo: son SENAMHI, ANA, IMARPE o el ENFEN. `heartbeat.json` dice qué respondió cada una. El sitio usa la última copia buena hasta 7 días |
| Issue `relay-token-expiring` en GitHub | El token vence en menos de 21 días | Renovarlo y ejecutar `INSTALAR` con el nuevo |
| Issue `relay-missing` en GitHub | `data-peru` existe pero su `index.json` no se puede leer | Ver la última subida del recolector |

Los issues se cierran solos cuando el problema desaparece
([operaciones](operaciones.md)).

## Si algo falla

Primero, `VERIFICAR`: casi todos los problemas aparecen ahí con su
solución. Los más frecuentes:

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `fuentes`: ninguna responde | La conexión no está en el Perú, hay una VPN o las fuentes bloquean esa red | Probar otra conexión en el Perú; desactivar la VPN |
| `fuentes`: el ENFEN no responde, el resto sí | Caída momentánea del ENFEN | Repetir más tarde |
| `token`: GitHub lo rechazó | Vencido, revocado o mal copiado | Crear uno nuevo y ejecutar `INSTALAR` |
| `escritura`: sin permiso | Al token le falta *Contents: Read and write* o el repositorio | Editar el token en GitHub |
| Errores de certificado (`CERTIFICATE_VERIFY_FAILED`, `SSL`) | Fecha y hora del equipo mal, o un antivirus/proxy que inspecciona HTTPS | Activar la hora automática; ejecutar `INSTALAR` otra vez (instala truststore). En Windows, si falla solo la subida: `git config --global http.sslBackend schannel` |
| `internet`: respuesta inesperada | Portal de acceso (wifi de hotel u oficina) o proxy | Abrir un navegador, aceptar el portal y repetir |
| `tarea`: no hay tarea, o apunta a una carpeta que no existe | Se instaló con `-SinTarea`, o se movió la carpeta | Ejecutar `INSTALAR` |
| `PROBAR-TAREA`: la tarea no arrancó (Windows) | Sin sesión iniciada, o la tarea quedó deshabilitada | Ejecutar `INSTALAR` como administrador (ver [Windows](#windows)) |
| `PROBAR-TAREA`: la tarea no arrancó (macOS) | El agente no se cargó (por ejemplo, instalado por SSH) | Ejecutar `INSTALAR` con la sesión gráfica iniciada |
| `PROBAR-TAREA` falla pero `RECOLECTAR-AHORA` funciona | La tarea no ve el proxy o los certificados de la terminal | Ejecutar `INSTALAR` desde esa misma terminal (los copia a `.env`) |
| «Windows protegió su PC» | Archivo descargado de internet | **Más información → Ejecutar de todas formas**, o desbloquear el .zip antes de extraer |
| macOS: «no se puede abrir» | Archivo descargado de internet | Usar el método de Terminal (`bash` + arrastrar el archivo) |
| Linux: «Falta el módulo venv» | Debian y Ubuntu lo separan | `sudo apt install python3-venv` |
| `zona-horaria`: el equipo no usa la hora de Lima | Equipo con otra zona | Funciona igual; si la zona cambia de horario (verano), ejecutar `INSTALAR` otra vez |
| `ultima-corrida`: «ya hay una recolección en curso» | Otra corrida está trabajando | Esperar; un candado de más de 2 horas se descarta solo |
| Dos computadoras recolectando | Ambas suben; gana la última y la otra reintenta | Dejar una sola instalada |

Si sigue sin funcionar, enviar a quien mantiene el sitio el último
`logs/verificacion-*.txt` y `logs/recolector.log`.

## Mantenimiento

- **Actualizar:** `otras-acciones/ACTUALIZAR` descarga la última versión
  del kit, comprueba su sha256 y la instala conservando el token. También
  se puede descargar el .zip nuevo y ejecutar `INSTALAR`.
- **Renovar el token:** ver [Token de GitHub](#1-token-de-github).
- **Cambiar de computadora:** `DESINSTALAR` en la vieja (quita la tarea y
  el token) e `INSTALAR` en la nueva.
- **Fuentes:** el equipo baja la lista base (`SOURCES` en
  `peru_collector.py`) más las fuentes del registro
  (`registry/sources.json`) con el canal `peru-server`, que son las
  geobloqueadas: solo las que no responden desde fuera del Perú pasan por
  este equipo. Lee el registro de GitHub en cada corrida (con el token),
  así que un cambio en el registro llega sin reinstalar; si GitHub no
  responde, usa la copia del kit. Una regla `follow` baja además los
  documentos enlazados (por ejemplo, los PDF de un listado), hasta `max`.
  Lo que el registro marca `robots-disallowed` (el robots.txt del servidor
  no permite la ruta) no se pide, aunque esté en la lista base.
  Todo se guarda tal cual: el análisis se hace en GitHub Actions, así que
  corregir un lector nunca exige actualizar este equipo. Las URL deben
  coincidir con las que pide el pipeline (se buscan por URL y alias).
- **Historial:** la rama `data-peru` guarda solo la última copia; el
  historial de git conserva las anteriores y la rama `data-archive`
  archiva lo que se usó.

## Seguridad

- El token solo puede escribir el contenido de este repositorio. Se guarda
  en `.env` dentro de la instalación, legible solo por el usuario
  (permisos 600 en macOS y Linux; en Windows, permisos solo para ese
  usuario). No va en variables de entorno, ni en los registros, ni en los
  informes, ni en los gestores de credenciales del sistema.
- La computadora no abre puertos ni recibe conexiones: solo descarga de
  las fuentes y sube a GitHub.
- Las fuentes ven en el User-Agent la dirección del sitio publicado si el
  kit la trae (`contact_url` en `kit.json`, cuando el sitio no está en
  GitHub Pages), o la del repositorio. Una línea `ENSO_CONTACT_URL=...` en
  `.env` la reemplaza.
- `kit.json` permite detectar archivos del programa modificados; la
  actualización comprueba el sha256 del kit antes de instalarlo.
- Si la computadora se pierde o se comparte, revocar el token en GitHub
  (Settings → Developer settings → Fine-grained tokens).

## Otras formas de correrlo

| Opción | Costo | A favor | En contra |
|---|---|---|---|
| **Computadora en el Perú** con el kit (PC, laptop, Mac o Raspberry Pi en casa u oficina) — recomendado | Luz (una Raspberry Pi consume ~5 W) | IP peruana residencial: es lo que las fuentes aceptan; sin cuentas en la nube | Depende de que el equipo esté encendido; se recupera al encender |
| Oracle Cloud Always Free (región Santiago, Bogotá o São Paulo) | Gratis | Siempre encendido | No hay región en Lima; una IP de centro de datos fuera del Perú puede estar bloqueada igual. Usar solo si `VERIFICAR` da `OK` en `fuentes` desde allí. La región de la capa gratuita se fija al crear la cuenta |
| AWS Local Zone Lima | De pago (no entra en la capa gratuita) | IP en Lima | Costo mensual; también es IP de centro de datos |
| Ejecutor propio de GitHub Actions en el Perú | Gratis | Integra con Actions | **No recomendado**: en un repositorio público, cualquier PR podría ejecutar código en esa máquina |

Google Cloud ofrece su máquina gratuita solo en regiones de EE. UU., que
tienen el mismo problema que GitHub Actions.

Para probar el acceso sin instalar nada (desde una copia del repositorio):

```bash
cd python && pip install -r requirements.txt
python -m tools.peru_collector --probe
```

### Docker (cualquier sistema)

```bash
echo "GITHUB_TOKEN=github_pat_..." > collector/.env
docker compose -f collector/docker-compose.yml up -d --build
docker compose -f collector/docker-compose.yml logs -f   # ver la próxima hora de recolección
```

La imagen usa la hora de Lima y se reinicia sola. Para probar una vez:
`docker compose -f collector/docker-compose.yml run --rm enso-collector --once --push`.

### Linux o Raspberry Pi con systemd

Alternativa al instalador (que usa cron), con el servicio a nivel de sistema:

```bash
sudo useradd --system --create-home enso
sudo git clone https://github.com/PillB/observatorio-enso-peru /opt/observatorio-enso-peru
sudo python3 -m venv /opt/observatorio-enso-peru/.venv
sudo /opt/observatorio-enso-peru/.venv/bin/pip install -r /opt/observatorio-enso-peru/python/requirements.txt
echo "GITHUB_TOKEN=github_pat_..." | sudo tee /etc/enso-collector.env && sudo chmod 600 /etc/enso-collector.env
sudo cp /opt/observatorio-enso-peru/collector/enso-collector.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now enso-collector.timer
systemctl list-timers enso-collector.timer      # próxima corrida
sudo systemctl start enso-collector.service     # probar ahora
journalctl -u enso-collector.service -n 50      # registro
```

El temporizador usa la zona `America/Lima` aunque el equipo tenga otra, y
`Persistent=true` recupera la corrida si estaba apagado a las 21:00.

## Para quien mantiene el código

| Archivo | Qué hace |
|---|---|
| `python/tools/peru_collector.py` | Descarga y sube (`--probe`, `--once`, `--daemon`; lo usan Docker y systemd) |
| `python/tools/collector_service.py` | La corrida programada: `.env`, registro, candado, horario, comprobación del token, alarmas, `estado.json` |
| `python/tools/collector_schedule.py` | Horas locales de los disparos, agente de launchd, crontab; estado y disparo de la tarea en los tres sistemas |
| `python/tools/collector_check.py` | La verificación |
| `python/tools/collector_kit.py` | Arma el kit (zip reproducible, `kit.json`, finales de línea y permisos) |
| `collector/instalar.ps1`, `collector/instalar.sh`, `collector/lanzadores/` | Instaladores y lanzadores de doble clic |
| `.github/workflows/recolector-kit.yml` | Arma el kit, revisa los scripts, instala y prueba la tarea en Windows, macOS y Linux; publica la versión `recolector-kit` desde `main` |

Códigos de salida de `collector_service`: 0 correcto (o nada que hacer),
1 ninguna fuente respondió, 2 falta configuración (token), 3 GitHub
rechazó el token o no responde, 4 la subida falló, 5 otra corrida en
curso, 6 corrida colgada, 9 error inesperado.
