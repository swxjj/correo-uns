import argparse
import os
from pathlib import Path
import socket
import threading
import time
import webbrowser
import uvicorn
from .web import create_app


def main():
    parser = argparse.ArgumentParser(description='Correo UNS local')
    parser.add_argument('--data',type=Path,help='Carpeta de datos alternativa (para pruebas)')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--no-browser',action='store_true')
    args = parser.parse_args()
    # Bind before loading data. A second process cannot access the archive concurrently.
    sock = socket.socket()
    if os.name=='nt':
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
    try:
        sock.bind(('127.0.0.1',args.port))
    except OSError:
        print('No se pudo iniciar: el puerto está ocupado. Cerrá la otra instancia de Correo UNS y volvé a intentar.')
        return 1
    sock.listen(128)
    # OS file lock also prevents different ports/processes opening the same archive.
    root = args.data or Path(os.environ.get('LOCALAPPDATA',Path.home()))/'CorreoUNS'
    root.mkdir(parents=True,exist_ok=True)
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
        print('El archivo local ya está abierto por otra instancia. Cerrala antes de continuar.')
        sock.close(); lock.close()
        return 1
    app = create_app(root)
    config = uvicorn.Config(app,host='127.0.0.1',port=args.port,access_log=False,log_level='critical',proxy_headers=False)
    server = uvicorn.Server(config)
    if not args.no_browser:
        def open_browser():
            while not server.started and not server.should_exit:
                time.sleep(.2)
            if server.started:
                webbrowser.open(f'http://127.0.0.1:{args.port}')
        threading.Thread(target=open_browser,daemon=True).start()
    print(f'Correo UNS: http://127.0.0.1:{args.port}\nDatos: {root}\nMantené esta ventana abierta. Para salir, presioná Ctrl+C.')
    try:
        server.run(sockets=[sock])
    finally:
        sock.close(); lock.close()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
