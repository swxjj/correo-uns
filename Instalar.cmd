@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto error
)
".venv\Scripts\python.exe" -m pip install --index-url https://pypi.org/simple -r requirements-lock.txt
if errorlevel 1 goto error
echo Instalacion completada. Abri Iniciar Correo.cmd.
pause
exit /b 0
:error
echo No se pudo instalar. Necesitas Python 3.11 o superior y acceso a PyPI.
pause
exit /b 1
