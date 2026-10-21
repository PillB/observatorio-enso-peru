@echo off
rem Observatorio ENSO Peru: verificar y probar la tarea programada (sube una copia real). Doble clic para ejecutar.
setlocal
set "S=%~dp0collector\instalar.ps1"
if not exist "%S%" set "S=%~dp0..\collector\instalar.ps1"
if not exist "%S%" set "S=%~dp0..\instalar.ps1"
if not exist "%S%" set "S=%~dp0..\..\instalar.ps1"
rem exit /b en su propia linea: asi devuelve el codigo de PowerShell.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%S%" -ProbarTarea -Pausa %*
exit /b %ERRORLEVEL%
