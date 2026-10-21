@echo off
rem Observatorio ENSO Peru: recolectar y subir una copia ahora. Doble clic para ejecutar.
setlocal
set "S=%~dp0collector\instalar.ps1"
if not exist "%S%" set "S=%~dp0..\collector\instalar.ps1"
if not exist "%S%" set "S=%~dp0..\instalar.ps1"
if not exist "%S%" set "S=%~dp0..\..\instalar.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%S%" -RecolectarAhora -Pausa %* & exit /b
