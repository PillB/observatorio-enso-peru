# Windows: crea una tarea diaria a las 21:00 (la hora del equipo debe ser la de Lima).
# Ejecutar en PowerShell dentro de la carpeta del repositorio, después de
# instalar Python 3.12 y las dependencias (ver docs/servidor-peru.md).
$repo = (Resolve-Path ".").Path
$py = Join-Path $repo ".venv\Scripts\python.exe"
$action = New-ScheduledTaskAction -Execute $py `
  -Argument "-m tools.peru_collector --once --push --dispatch" `
  -WorkingDirectory (Join-Path $repo "python")
$trigger = New-ScheduledTaskTrigger -Daily -At 21:00
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName "ENSO recolector Peru" -Action $action -Trigger $trigger -Settings $settings `
  -Description "Observatorio ENSO Peru: recolecta fuentes peruanas y las sube a GitHub" -Force
# El token se guarda como variable de entorno del usuario:
#   [Environment]::SetEnvironmentVariable("GITHUB_TOKEN", "github_pat_...", "User")
