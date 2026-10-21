@echo off
rem Observatorio ENSO Peru: descargar e instalar la ultima version del kit. Doble clic para ejecutar.
rem Corre desde una copia en %TEMP%: esta carpeta se borra o se reemplaza mientras corre, y
rem cmd vuelve a leer el .cmd (y no deja borrar su carpeta actual) mientras lo ejecuta.
if defined ENSO_LANZADOR goto run
set "ENSO_LANZADOR=%~dp0"
copy /y "%~f0" "%TEMP%\observatorio-enso-%~nx0" >nul 2>&1 && cd /d "%TEMP%" && "%TEMP%\observatorio-enso-%~nx0" %*
:run
set "H=%ENSO_LANZADOR%"
set "ENSO_LANZADOR="
set "S=%H%collector\instalar.ps1"
if not exist "%S%" set "S=%H%..\collector\instalar.ps1"
if not exist "%S%" set "S=%H%..\instalar.ps1"
if not exist "%S%" set "S=%H%..\..\instalar.ps1"
rem exit /b en su propia linea: asi devuelve el codigo de PowerShell.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%S%" -Actualizar -Pausa %*
exit /b %ERRORLEVEL%
