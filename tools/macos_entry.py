"""Entry point for the self-contained macOS application."""
import os
import sys

# Private mail archive, including files created during restore.
os.umask(0o077)
from correo.__main__ import main

if __name__ == '__main__':
    sys.argv.insert(1, '--desktop')
    try:
        raise SystemExit(main())
    except Exception:
        import rumps
        rumps.alert('Correo UNS', 'No se pudo abrir la aplicación. Revisá el espacio disponible y los permisos de la carpeta de datos. Tus mensajes permanecen en Library/Application Support/CorreoUNS.')
        raise SystemExit(1)
