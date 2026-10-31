import argparse
import os
from pathlib import Path
import socket
import threading
import time
import webbrowser
import uvicorn
from .web import create_app
from .paths import data_root
from .auth import WebSettings


def main():
    parser = argparse.ArgumentParser(description='Correo UNS local')
    parser.add_argument('--data',type=Path,help='Carpeta de datos alternativa (para pruebas)')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--desktop',action='store_true',help='Aplicación de barra de menús en macOS')
    parser.add_argument('--web',action='store_true',help='Beta web con login obligatorio para la cuenta configurada')
    parser.add_argument('--origin',help='Origen público HTTPS exacto (sin ruta) para la beta web')
    parser.add_argument('--tunnel-host',default='',help='Host exacto del Quick Tunnel de esta sesión')
    args = parser.parse_args()
    if (args.origin or args.tunnel_host) and not args.web:parser.error('--origin y --tunnel-host requieren --web')
    if args.desktop and args.web:parser.error('--desktop y --web son modos separados')
    try:web=WebSettings(args.origin or f'http://127.0.0.1:{args.port}',args.tunnel_host) if args.web else None
    except ValueError as exc:parser.error(str(exc))
    def failure(message):
        print(message)
        if args.desktop:
            import rumps
            rumps.alert('Correo UNS', message)
    # Bind before loading data. A second process cannot access the archive concurrently.
    sock = socket.socket()
    if os.name=='nt':
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
    else:
        # Allow an immediate restart after HTTP connections enter TIME_WAIT.
        # The listening socket and archive lock still exclude a second instance.
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    try:
        sock.bind(('127.0.0.1',args.port))
    except OSError:
        failure('No se pudo iniciar: el puerto está ocupado. Cerrá la otra instancia de Correo UNS y volvé a intentar.')
        return 1
    sock.listen(128)
    # OS file lock also prevents different ports/processes opening the same archive.
    root = args.data or data_root()
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    lock = open(root.parent/(root.name+'.lock'),'a+b')
    lock.seek(0)
    if os.fstat(lock.fileno()).st_size==0:
        lock.write(b'0'); lock.flush()
    lock.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        failure('El archivo local ya está abierto por otra instancia. Cerrala antes de continuar.')
        sock.close(); lock.close()
        return 1
    try:app = create_app(root,web=web)
    except ValueError as exc:
        failure(str(exc));sock.close();lock.close();return 1
    config = uvicorn.Config(app,host='127.0.0.1',port=args.port,access_log=False,log_level='critical',proxy_headers=False,log_config=None)
    server = uvicorn.Server(config)
    if not args.no_browser and not args.desktop:
        def open_browser():
            while not server.started and not server.should_exit:
                time.sleep(.2)
            if server.started:
                webbrowser.open(web.origin if web else f'http://127.0.0.1:{args.port}')
        threading.Thread(target=open_browser,daemon=True).start()
    print(f'Correo UNS: http://127.0.0.1:{args.port}\nDatos: {root}\nMantené esta ventana abierta. Para salir, presioná Ctrl+C.')
    if web:print('Beta con login · Dirección de acceso: '+web.origin)
    try:
        if args.desktop:
            from .desktop import run
            run(server, sock, app, args.port, open_browser=not args.no_browser)
        else:
            server.run(sockets=[sock])
    finally:
        sock.close(); lock.close()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
