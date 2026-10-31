@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Primero ejecuta Instalar.cmd.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m tools.start_web_beta --origin https://correo-uns-beta.vercel.app
if errorlevel 1 pause
