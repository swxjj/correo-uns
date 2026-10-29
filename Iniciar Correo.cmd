@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Primero ejecuta Instalar.cmd.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m correo
if errorlevel 1 pause
