#!/bin/zsh
# Source checkout fallback. The distributed .app needs no Python installation.
set -eu
cd -- "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  python_path=''
  for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; assert sys.version_info >= (3,11)' >/dev/null 2>&1; then
      python_path="$candidate"
      break
    fi
  done
  if [[ -z "$python_path" ]]; then
    print 'Para usar el código fuente instalá Python 3.11 o superior desde python.org. La aplicación .app ya lo incluye.'
    read '?Presioná Enter para cerrar.'
    exit 1
  fi
  "$python_path" -m venv .venv
fi
if ! .venv/bin/python -c 'import fastapi, uvicorn, bleach, multipart, keyring, rumps, certifi' >/dev/null 2>&1; then
  print 'Preparando Correo UNS (solo la primera vez)…'
  if ! .venv/bin/python -m pip install -r requirements-macos.txt; then
    print 'No se pudo completar la instalación. Revisá Internet y volvé a abrir.'
    read '?Presioná Enter para cerrar.'
    exit 1
  fi
fi
exec .venv/bin/python -m tools.macos_entry
