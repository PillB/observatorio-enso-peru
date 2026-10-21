<#
.SYNOPSIS
  Recolector del Observatorio ENSO Perú en Windows: instalar, verificar,
  probar, recolectar ahora, actualizar o desinstalar.

.DESCRIPTION
  Instalar (sin opciones):
    1. Busca Python 3.11 o más reciente y Git; si faltan, los instala con winget.
    2. Copia el kit a %LOCALAPPDATA%\ObservatorioENSO\recolector (o -Destino).
    3. Crea el entorno .venv e instala python\requirements.txt.
    4. Pide el token de GitHub y lo guarda en .env (solo lo lee este usuario).
    5. Registra la tarea programada: 21:00 de Lima, reintentos cada 30 min
       hasta las 23:30, al iniciar sesión y al despertar el equipo.
    6. Ejecuta la verificación y ofrece probar la tarea de punta a punta.
  Volver a ejecutarlo es seguro: conserva el token y actualiza el resto.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File collector\instalar.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File collector\instalar.ps1 -Verificar -ProbarTarea
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File collector\instalar.ps1 -Desinstalar
#>
[CmdletBinding()]
param(
    [string]$Token = '',
    [string]$Destino = '',
    [ValidatePattern('^([01]?\d|2[0-3]):[0-5]\d$')]
    [string]$Hora = '21:00',
    [switch]$SinTarea,
    [switch]$SinVerificar,
    [switch]$NoInteractivo,
    [switch]$Verificar,
    [switch]$ProbarTarea,
    [switch]$RecolectarAhora,
    [switch]$Actualizar,
    [switch]$Desinstalar,
    [switch]$Pausa,
    [string]$Solo = '',
    [string]$Omitir = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$HoraGiven = $PSBoundParameters.ContainsKey('Hora')

# La salida de Python llega por una tubería: que viaje y se lea en UTF-8. Si no,
# en una consola en español «Verificación» se ve como «Verificaci¾n».
$env:PYTHONIOENCODING = 'utf-8'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false }
catch { Write-Verbose "Sin consola: la salida queda con su codificación ($($_.Exception.Message))" }

$TaskName = 'Observatorio ENSO - recolector Peru'
$OldTaskName = 'ENSO recolector Peru'
$Repo = 'PillB/observatorio-enso-peru'
$KitUrl = "https://github.com/$Repo/releases/download/recolector-kit/recolector-peru.zip"
$KitRoot = Split-Path -Parent $PSScriptRoot
if (-not $Destino) {
    # Corre desde una instalación (sus lanzadores): esa es la carpeta, aunque
    # se haya instalado con -Destino en otro lugar.
    $installed = (Test-Path (Join-Path $KitRoot '.venv')) -or (Test-Path (Join-Path $KitRoot '.env'))
    if ($installed -and (Test-Path (Join-Path $KitRoot 'kit.json'))) { $Destino = $KitRoot }
    else { $Destino = Join-Path $env:LOCALAPPDATA 'ObservatorioENSO\recolector' }
}
$Destino = [IO.Path]::GetFullPath($Destino)
$VenvPy = Join-Path $Destino '.venv\Scripts\python.exe'
$VenvPyw = Join-Path $Destino '.venv\Scripts\pythonw.exe'
$EnvFile = Join-Path $Destino '.env'
$StartMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Observatorio ENSO'

function Write-Step([string]$Message) { Write-Host ''; Write-Host "== $Message" -ForegroundColor Cyan }
function Write-Info([string]$Message) { Write-Host "   $Message" }
function Write-Warn([string]$Message) { Write-Host "   AVISO: $Message" -ForegroundColor Yellow }
function Exit-WithError([string]$Message, [string]$Hint = '') {
    Write-Host ''
    Write-Host "ERROR: $Message" -ForegroundColor Red
    if ($Hint) { Write-Host "Qué hacer: $Hint" -ForegroundColor Yellow }
    throw [System.OperationCanceledException]::new($Message)
}

function Read-YesNo([string]$Question, [bool]$Default = $true) {
    if ($NoInteractivo) { return $Default }
    $suffix = if ($Default) { '[S/n]' } else { '[s/N]' }
    $answer = Read-Host "$Question $suffix"
    if (-not $answer) { return $Default }
    return $answer.Trim().ToLower().StartsWith('s')
}

# Llama a un programa externo sin que su salida de errores (pip, git, winget
# escriben avisos ahí) detenga el script en PowerShell 5.1.
function Invoke-Native([string]$Exe, [string[]]$Arguments, [string]$WorkDir = '') {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    if ($WorkDir) { Push-Location $WorkDir }
    try {
        $output = & $Exe @Arguments 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    } catch {
        $output = @("$_")
        $code = 9009
    } finally {
        if ($WorkDir) { Pop-Location }
        $ErrorActionPreference = $previous
    }
    return [pscustomobject]@{ Code = $code; Output = (@($output) -join "`n") }
}

# Corre un programa mostrando su salida en vivo; devuelve el código de salida.
function Invoke-Visible([string]$Exe, [string[]]$Arguments, [string]$WorkDir) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    Push-Location $WorkDir
    try {
        & $Exe @Arguments | Out-Host
        return [int]$LASTEXITCODE
    } finally {
        Pop-Location
        $ErrorActionPreference = $previous
    }
}

function Invoke-Live([string]$Exe, [string[]]$Arguments) {
    return Invoke-Visible $Exe $Arguments (Join-Path $Destino 'python')
}

function Sync-SessionPath {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($machine, $user) | Where-Object { $_ }) -join ';'
}

function Test-Python([string]$Exe, [string[]]$Prefix) {
    # Sin comillas dobles: PowerShell 5.1 las pierde al pasar argumentos a programas externos.
    $probe = 'import sys; print(''%d.%d|%s'' % (sys.version_info[0], sys.version_info[1], sys.executable))'
    $r = Invoke-Native $Exe ($Prefix + @('-c', $probe))
    if ($r.Code -ne 0) { return $null }
    $line = $r.Output -split "`n" | Where-Object { $_ -match '^3\.\d+\|' } | Select-Object -First 1
    if (-not $line) { return $null }
    $parts = $line.Trim() -split '\|', 2
    $minor = [int]($parts[0] -split '\.')[1]
    # El Python de Microsoft Store guarda los archivos de AppData en una carpeta virtual: no sirve para la tarea.
    if ($minor -lt 11 -or $parts[1] -like '*\WindowsApps\*') { return $null }
    return [pscustomobject]@{ Version = $parts[0]; Path = $parts[1] }
}

function Find-Python {
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in '3.13', '3.12', '3.14', '3.11') { $candidates += [pscustomobject]@{ Exe = 'py'; Prefix = @("-$v") } }
    }
    foreach ($name in 'python', 'python3') {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cmd -and $cmd.Source -notlike '*\WindowsApps\*') { $candidates += [pscustomobject]@{ Exe = $cmd.Source; Prefix = @() } }
    }
    $paths = @("$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", "$env:ProgramFiles\Python3*\python.exe")
    foreach ($p in Get-ChildItem $paths -ErrorAction SilentlyContinue | Sort-Object FullName -Descending) {
        $candidates += [pscustomobject]@{ Exe = $p.FullName; Prefix = @() }
    }
    foreach ($c in $candidates) {
        $found = Test-Python $c.Exe $c.Prefix
        if ($found) { return $found }
    }
    return $null
}

function Find-Git {
    $cmd = Get-Command git -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) { return $cmd.Source }
    foreach ($p in "$env:ProgramFiles\Git\cmd\git.exe", "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe") {
        if (Test-Path $p) { return $p }
    }
    return $null
}

function Install-WithWinget([string]$Id, [string]$Name, [string[]]$Extra) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { return $false }
    if (-not (Read-YesNo "No se encontró $Name. ¿Instalarlo ahora con winget?" $true)) { return $false }
    Write-Info "Instalando $Name (puede tardar unos minutos y pedir permiso de Windows)..."
    $r = Invoke-Native 'winget' (@('install', '-e', '--id', $Id, '--silent', '--accept-package-agreements', '--accept-source-agreements') + $Extra)
    if ($r.Code -ne 0) { Write-Warn "winget terminó con código $($r.Code): $($r.Output -split "`n" | Select-Object -Last 3)" }
    Sync-SessionPath
    return $true
}

function Read-EnvFile {
    if (Test-Path $EnvFile) { return @(Get-Content $EnvFile -Encoding UTF8) }
    return @()
}

function Get-EnvValue([string[]]$Lines, [string]$Key) {
    foreach ($line in $Lines) {
        if ($line -match "^\s*$Key\s*=\s*(.*)$") { return $Matches[1].Trim().Trim('"').Trim("'") }
    }
    return ''
}

function Test-TokenFormat([string]$Value) {
    return $Value -match '^(github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{30,})$'
}

function Read-Token {
    Write-Info 'Pegue el token de GitHub (empieza con github_pat_). No se verá al pegarlo.'
    Write-Info 'Para pegar: clic derecho o Ctrl+V, y luego Enter.'
    for ($i = 0; $i -lt 3; $i++) {
        $secure = Read-Host '   Token' -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr).Trim() }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
        if (Test-TokenFormat $plain) { return $plain }
        Write-Warn 'Eso no parece un token de GitHub (github_pat_... o ghp_...). Intente de nuevo.'
    }
    Exit-WithError 'No se recibió un token válido.' 'Crear el token como indica docs\servidor-peru.md y volver a ejecutar el instalador.'
}

function Save-EnvFile([string]$TokenValue, [string]$At) {
    $keep = @(Read-EnvFile | Where-Object { $_ -notmatch '^\s*(GITHUB_TOKEN|ENSO_COLLECT_AT)\s*=' -and $_ -notmatch '^# Recolector ENSO' })
    $lines = @('# Recolector ENSO Peru: configuracion local. No compartir este archivo.')
    if ($TokenValue) { $lines += "GITHUB_TOKEN=$TokenValue" }
    $lines += "ENSO_COLLECT_AT=$At"
    # Proxy, certificados y contacto de esta consola: la tarea programada no los hereda.
    foreach ($v in 'HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY', 'SSL_CERT_FILE', 'ENSO_CONTACT_URL') {
        $val = [Environment]::GetEnvironmentVariable($v)
        if ($val -and -not ($keep | Where-Object { $_ -match "^\s*$v\s*=" })) { $lines += "$v=$val" }
    }
    $lines += @($keep | Where-Object { $_.Trim() })
    [IO.File]::WriteAllLines($EnvFile, [string[]]$lines, (New-Object Text.UTF8Encoding $false))
    # Solo este usuario puede leerlo.
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $r = Invoke-Native 'icacls.exe' @($EnvFile, '/inheritance:r', '/grant:r', "*${sid}:(R,W)")
    if ($r.Code -ne 0) { Write-Warn "No se pudieron restringir los permisos de .env: $($r.Output)" }
}

function Copy-Kit {
    $source = [IO.Path]::GetFullPath($KitRoot).TrimEnd('\')
    if ($source -eq $Destino.TrimEnd('\')) { Write-Info 'Se usa la carpeta actual.'; return }
    if (-not (Test-Path (Join-Path $KitRoot 'python\tools\peru_collector.py'))) {
        Exit-WithError "No se encuentra el código del recolector junto a este instalador ($KitRoot)." 'Descomprimir el kit completo y ejecutar INSTALAR desde esa carpeta.'
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $Destino 'python'), (Join-Path $Destino 'docs') | Out-Null
    foreach ($d in 'python\enso', 'python\tools', 'config', 'registry', 'collector', 'otras-acciones') {
        $target = Join-Path $Destino $d
        if (Test-Path $target) { Remove-Item -Recurse -Force $target }
    }
    $items = @('python\requirements.txt', 'python\enso', 'python\tools', 'config', 'registry', 'collector', 'otras-acciones',
        'docs\servidor-peru.md', 'LEEME.txt', 'LICENSE', 'kit.json')
    foreach ($rel in $items) {
        $src = Join-Path $KitRoot $rel
        if (Test-Path $src) { Copy-Item -Path $src -Destination (Join-Path $Destino $rel) -Recurse -Force }
    }
    Get-ChildItem -Path $KitRoot -File | Where-Object { $_.Extension -in '.cmd', '.command' } |
        Copy-Item -Destination $Destino -Force
    Get-ChildItem -Path $Destino -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
    # Quita la marca «descargado de internet» para que Windows no bloquee los scripts.
    Get-ChildItem -Path $Destino -Recurse -File | Unblock-File -ErrorAction SilentlyContinue
    Write-Info "Archivos copiados a $Destino"
}

function Install-Venv($Python) {
    $reuse = $false
    if (Test-Path $VenvPy) {
        $current = Test-Python $VenvPy @()
        $reuse = [bool]($current -and $current.Version -eq $Python.Version)
    }
    if (-not $reuse) {
        if (Test-Path (Join-Path $Destino '.venv')) { Remove-Item -Recurse -Force (Join-Path $Destino '.venv') }
        $r = Invoke-Native $Python.Path @('-m', 'venv', (Join-Path $Destino '.venv'))
        if ($r.Code -ne 0) { Exit-WithError "No se pudo crear el entorno de Python: $($r.Output)" 'Reinstalar Python 3.12 desde python.org y repetir.' }
    }
    $req = Join-Path $Destino 'python\requirements.txt'
    $pipArgs = @('-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '-q', '-r', $req)
    $r = Invoke-Native $VenvPy $pipArgs
    if ($r.Code -ne 0) {
        # Con un antivirus que analiza HTTPS, pip necesita los certificados del sistema.
        $r = Invoke-Native $VenvPy ($pipArgs + @('--use-feature=truststore'))
    }
    if ($r.Code -ne 0) {
        Exit-WithError "No se pudieron instalar las dependencias:`n$(($r.Output -split "`n" | Select-Object -Last 8) -join "`n")" 'Revisar la conexión a internet y volver a ejecutar el instalador.'
    }
    Write-Info "Entorno listo: $VenvPy"
}

function Register-CollectorTask([string]$At) {
    $old = Get-ScheduledTask -TaskName $OldTaskName -ErrorAction SilentlyContinue
    if ($old) {
        $old | Unregister-ScheduledTask -Confirm:$false
        Write-Info "Se quitó la tarea anterior «$OldTaskName»."
    }
    $r = Invoke-Native $VenvPy @('-m', 'tools.collector_schedule', 'horas', '--hora', $At) (Join-Path $Destino 'python')
    $times = @($r.Output -split "`n" | Where-Object { $_ -match '^\d\d:\d\d$' })
    if ($r.Code -ne 0 -or -not $times) { Exit-WithError "No se pudo calcular la hora local: $($r.Output)" }
    $first = [datetime]::ParseExact($times[0], 'HH:mm', [Globalization.CultureInfo]::InvariantCulture)
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)

    $action = New-ScheduledTaskAction -Execute $VenvPyw -Argument '-m tools.collector_service --programado' `
        -WorkingDirectory (Join-Path $Destino 'python')
    $daily = New-ScheduledTaskTrigger -Daily -At $first
    $daily.Repetition = (New-ScheduledTaskTrigger -Once -At $first -RepetitionInterval (New-TimeSpan -Minutes 30) `
            -RepetitionDuration (New-TimeSpan -Hours 3)).Repetition
    $logon = New-ScheduledTaskTrigger -AtLogOn -User $user
    $logon.Delay = 'PT3M'
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
    if ($isAdmin) {
        # S4U: corre aunque nadie haya iniciado sesión (por ejemplo, tras un reinicio por actualizaciones).
        $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType S4U -RunLevel Limited
        $mode = 'aunque no haya sesión iniciada'
    } else {
        $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
        $mode = 'con la sesión de este usuario iniciada (puede estar bloqueada)'
    }
    $description = 'Observatorio ENSO Peru: descarga ENFEN, SENAMHI, ANA e IMARPE y sube la copia a GitHub. Ver docs\servidor-peru.md'
    try {
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($daily, $logon) -Settings $settings `
            -Principal $principal -Description $description -Force | Out-Null
    } catch {
        Write-Warn "Sin disparo al iniciar sesión ($($_.Exception.Message)); se registra solo el horario diario."
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($daily) -Settings $settings `
            -Principal $principal -Description $description -Force | Out-Null
    }
    $info = Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo
    Write-Info "Tarea «$TaskName»: $($times -join ', ') (hora local = $At de Lima) y al iniciar sesión, $mode."
    if ($info.NextRunTime) { Write-Info "Próxima corrida: $($info.NextRunTime)" }
    if (-not $isAdmin) { Write-Info 'Para que corra también sin sesión iniciada, ejecutar INSTALAR con «Ejecutar como administrador».' }
}

function Add-StartMenuShortcut {
    try {
        New-Item -ItemType Directory -Force -Path $StartMenu | Out-Null
        $shell = New-Object -ComObject WScript.Shell
        $links = [ordered]@{
            'Verificar el recolector'      = 'VERIFICAR-Windows.cmd'
            'Probar la tarea programada'   = 'otras-acciones\PROBAR-TAREA-Windows.cmd'
            'Recolectar ahora'             = 'otras-acciones\RECOLECTAR-AHORA-Windows.cmd'
            'Actualizar el recolector'     = 'otras-acciones\ACTUALIZAR-Windows.cmd'
            'Desinstalar el recolector'    = 'otras-acciones\DESINSTALAR-Windows.cmd'
        }
        foreach ($name in $links.Keys) {
            $target = Join-Path $Destino $links[$name]
            if (-not (Test-Path $target)) { continue }
            $lnk = $shell.CreateShortcut((Join-Path $StartMenu "$name.lnk"))
            $lnk.TargetPath = $target
            $lnk.WorkingDirectory = $Destino
            $lnk.Save()
        }
        $lnk = $shell.CreateShortcut((Join-Path $StartMenu 'Registro del recolector.lnk'))
        $lnk.TargetPath = Join-Path $Destino 'logs'
        $lnk.Save()
        Write-Info "Accesos directos en el menú Inicio → «Observatorio ENSO»."
    } catch {
        Write-Warn "No se crearon los accesos directos: $($_.Exception.Message)"
    }
}

function Test-Installed {
    if (-not (Test-Path $VenvPy)) {
        Exit-WithError "El recolector no está instalado en $Destino." 'Ejecutar primero INSTALAR-Windows.'
    }
}

function Invoke-Check([string[]]$Extra) {
    Test-Installed
    return Invoke-Live $VenvPy (@('-m', 'tools.collector_check') + $Extra)
}

function Invoke-Update {
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("enso-kit-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        $zip = Join-Path $tmp 'recolector-peru.zip'
        Write-Info "Descargando $KitUrl"
        $ProgressPreference = 'SilentlyContinue'
        try {
            Invoke-WebRequest -Uri $KitUrl -OutFile $zip -UseBasicParsing
            Invoke-WebRequest -Uri "$KitUrl.sha256" -OutFile "$zip.sha256" -UseBasicParsing
        } catch {
            # Con el repositorio privado la descarga pública da 404: se pide con el token, por la API.
            $token = Get-EnvValue (Read-EnvFile) 'GITHUB_TOKEN'
            if (-not $token) { throw }
            Write-Info 'Descarga pública no disponible; se usa el token.'
            $headers = @{ Authorization = "Bearer $token"; Accept = 'application/vnd.github+json'; 'User-Agent' = 'observatorio-enso-recolector' }
            $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/tags/recolector-kit" -Headers $headers -UseBasicParsing
            $headers.Accept = 'application/octet-stream'
            foreach ($pair in @(@('recolector-peru.zip', $zip), @('recolector-peru.zip.sha256', "$zip.sha256"))) {
                $asset = @($release.assets | Where-Object { $_.name -eq $pair[0] })[0]
                if (-not $asset) { Exit-WithError "La versión recolector-kit no tiene $($pair[0])." 'Avisar a quien mantiene el sitio.' }
                Invoke-WebRequest -Uri $asset.url -Headers $headers -OutFile $pair[1] -UseBasicParsing
            }
        }
        $expected = ((Get-Content "$zip.sha256" -Raw).Trim() -split '\s+')[0].ToLower()
        $actual = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
        if ($expected -ne $actual) { Exit-WithError 'El kit descargado no coincide con su sha256.' 'Repetir más tarde.' }
        Expand-Archive -Path $zip -DestinationPath $tmp -Force
        $installer = Join-Path $tmp 'recolector-peru\collector\instalar.ps1'
        $argsList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $installer, '-Destino', $Destino, '-NoInteractivo')
        $code = Invoke-Visible 'powershell.exe' $argsList $tmp
        Write-Info "Actualización terminada (código $code). Ejecute VERIFICAR para comprobar."
        return $code
    } finally {
        Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    }
}

function Invoke-Uninstall {
    Write-Step 'Desinstalar el recolector'
    if (-not (Read-YesNo "Se quitará la tarea programada y la carpeta $Destino (con el token). ¿Continuar?" $true)) { return 0 }
    foreach ($name in $TaskName, $OldTaskName) {
        $t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($t) {
            $t | Stop-ScheduledTask -ErrorAction SilentlyContinue
            $t | Unregister-ScheduledTask -Confirm:$false
            Write-Info "Tarea «$name» quitada."
        }
    }
    if (Test-Path $StartMenu) { Remove-Item -Recurse -Force $StartMenu }
    if ([Environment]::GetEnvironmentVariable('GITHUB_TOKEN', 'User')) {
        if (Read-YesNo 'Hay una variable GITHUB_TOKEN de una instalación anterior. ¿Borrarla?' $true) {
            [Environment]::SetEnvironmentVariable('GITHUB_TOKEN', $null, 'User')
        }
    }
    # Solo se borra una carpeta que es claramente una instalación del recolector.
    $ours = (Test-Path (Join-Path $Destino 'python\tools\collector_service.py')) -or (Test-Path (Join-Path $Destino '.venv')) -or
        (Test-Path (Join-Path $Destino 'kit.json'))
    $root = [IO.Path]::GetPathRoot($Destino).TrimEnd('\')
    $protected = @($root, $env:USERPROFILE, $env:LOCALAPPDATA, $env:APPDATA, $env:ProgramFiles) | ForEach-Object { "$_".TrimEnd('\') }
    if ($ours -and ($protected -notcontains $Destino.TrimEnd('\'))) {
        Set-Location $env:TEMP
        try {
            Remove-Item -Recurse -Force $Destino
            Write-Info "Carpeta $Destino borrada."
        } catch {
            # Suele ser otra ventana (VERIFICAR, una consola) abierta en esa carpeta.
            Write-Warn "No se pudo borrar todo $Destino ($($_.Exception.Message))."
            Write-Info 'La tarea ya no correrá. Cerrar las ventanas abiertas en esa carpeta y borrarla a mano.'
            return 1
        }
    } elseif (Test-Path $Destino) {
        Write-Warn "$Destino no parece una instalación del recolector: no se borró."
    }
    Write-Info 'Listo. Si el token ya no se usará, revocarlo en https://github.com/settings/personal-access-tokens'
    return 0
}

function Invoke-Install {
    Write-Host 'Observatorio ENSO Perú: instalación del recolector' -ForegroundColor Green
    Write-Info "Carpeta de instalación: $Destino"

    Write-Step '1/6 Python'
    $python = Find-Python
    if (-not $python) {
        [void](Install-WithWinget 'Python.Python.3.12' 'Python 3.12' @('--scope', 'user'))
        $python = Find-Python
    }
    if (-not $python) {
        Start-Process 'https://www.python.org/downloads/windows/' -ErrorAction SilentlyContinue
        Exit-WithError 'No se encontró Python 3.11 o más reciente.' 'Instalar Python 3.12 desde python.org (se abrió la página) y volver a ejecutar INSTALAR.'
    }
    Write-Info "Python $($python.Version): $($python.Path)"

    Write-Step '2/6 Git'
    $git = Find-Git
    if (-not $git) {
        [void](Install-WithWinget 'Git.Git' 'Git' @())
        $git = Find-Git
    }
    if (-not $git) {
        Start-Process 'https://git-scm.com/download/win' -ErrorAction SilentlyContinue
        Exit-WithError 'No se encontró Git.' 'Instalar Git para Windows (se abrió la página) y volver a ejecutar INSTALAR.'
    }
    Write-Info "Git: $git"

    Write-Step '3/6 Archivos'
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) { $existing | Stop-ScheduledTask -ErrorAction SilentlyContinue }
    New-Item -ItemType Directory -Force -Path (Join-Path $Destino 'logs') | Out-Null
    Copy-Kit

    Write-Step '4/6 Entorno de Python y dependencias'
    Install-Venv $python

    Write-Step '5/6 Token de GitHub'
    $lines = Read-EnvFile
    $at = $Hora
    $savedAt = Get-EnvValue $lines 'ENSO_COLLECT_AT'
    if ($savedAt -and -not $HoraGiven) { $at = $savedAt }
    $current = Get-EnvValue $lines 'GITHUB_TOKEN'
    $legacy = [Environment]::GetEnvironmentVariable('GITHUB_TOKEN', 'User')
    if ($Token) {
        if (-not (Test-TokenFormat $Token.Trim())) { Exit-WithError 'El token indicado no tiene el formato de GitHub.' }
        $newToken = $Token.Trim()
    } elseif ($current) {
        $tail = $current.Substring([Math]::Max(0, $current.Length - 4))
        if (Read-YesNo "Ya hay un token guardado (termina en …$tail). ¿Mantenerlo?" $true) { $newToken = $current }
        else { $newToken = Read-Token }
    } elseif ($legacy -and (Test-TokenFormat $legacy.Trim())) {
        Write-Info 'Se usa el token de la variable GITHUB_TOKEN (instalación anterior) y se pasa al archivo .env.'
        $newToken = $legacy.Trim()
    } elseif (-not $NoInteractivo) {
        $newToken = Read-Token
    } else {
        $newToken = ''
        Write-Warn 'Sin token: la recolección no podrá subir copias. Ejecutar INSTALAR otra vez para agregarlo.'
    }
    Save-EnvFile $newToken $at
    # La variable de la instalación anterior ya no se usa (.env manda); se borra para no confundirlas.
    if ($legacy -and ($legacy.Trim() -eq $newToken -or (Read-YesNo 'Hay una variable GITHUB_TOKEN de la instalación anterior. ¿Borrarla?' $true))) {
        [Environment]::SetEnvironmentVariable('GITHUB_TOKEN', $null, 'User')
        Write-Info 'Se borró la variable de entorno GITHUB_TOKEN (ahora el token está solo en .env).'
    }
    if ($newToken) { Write-Info "Token guardado en $EnvFile (solo lo puede leer este usuario)." }

    Write-Step '6/6 Tarea programada'
    if ($SinTarea) { Write-Info 'Omitida (-SinTarea).' }
    else {
        Register-CollectorTask $at
        Add-StartMenuShortcut
    }

    $code = 0
    if (-not $SinVerificar) {
        Write-Step 'Verificación'
        $code = Invoke-Check @()
        if (-not $SinTarea -and $newToken -and -not $NoInteractivo) {
            if (Read-YesNo '¿Probar ahora la tarea programada? Recolecta y sube una copia real (1 a 5 minutos).' $true) {
                $code = Invoke-Check @('--solo', 'tarea', '--probar-tarea')
            }
        }
    }
    Write-Host ''
    Write-Host 'Instalación terminada.' -ForegroundColor Green
    Write-Info "Registro diario: $(Join-Path $Destino 'logs\recolector.log')"
    Write-Info 'Para revisar más adelante: menú Inicio → Observatorio ENSO → Verificar el recolector.'
    return $code
}

$code = 0
$transcript = $false
try {
    if ($Desinstalar) { $code = Invoke-Uninstall }
    elseif ($Actualizar) { $code = Invoke-Update }
    elseif ($Verificar -or $ProbarTarea) {
        $extra = @()
        if ($ProbarTarea) { $extra += '--probar-tarea' }
        if ($Solo) { $extra += @('--solo', $Solo) }
        if ($Omitir) { $extra += @('--omitir', $Omitir) }
        $code = Invoke-Check $extra
    } elseif ($RecolectarAhora) {
        Test-Installed
        Write-Host 'Recolectando y subiendo la copia ahora (1 a 5 minutos)...' -ForegroundColor Green
        $code = Invoke-Live $VenvPy @('-m', 'tools.collector_service')
    } else {
        New-Item -ItemType Directory -Force -Path (Join-Path $Destino 'logs') | Out-Null
        try {
            Start-Transcript -Path (Join-Path $Destino ("logs\instalacion-{0:yyyyMMdd-HHmmss}.txt" -f (Get-Date))) | Out-Null
            $transcript = $true
        } catch { $transcript = $false }
        $code = Invoke-Install
    }
} catch [System.OperationCanceledException] {
    $code = 1
} catch {
    Write-Host ''
    Write-Host "ERROR inesperado: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace
    Write-Host 'Enviar este mensaje (y la carpeta logs) a quien mantiene el sitio.' -ForegroundColor Yellow
    $code = 1
} finally {
    if ($transcript) { Stop-Transcript | Out-Null }
    # Lanzadores de doble clic: que la ventana no se cierre antes de leer el resultado.
    if ($Pausa -and -not $env:ENSO_SIN_PAUSA) { [void](Read-Host 'Presione Enter para cerrar esta ventana') }
}
exit [int](@($code)[-1])
