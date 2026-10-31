"""Start the authenticated backend first, then a supervised temporary tunnel."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import urlsplit
from correo.auth import WebSettings
from tools.web_deployment import deployment_files,write_deployment

ROOT=Path(__file__).resolve().parent.parent


def stop_process(process):
    if not process or process.poll() is not None:return
    # Windows' venv python.exe can launch a second interpreter process. Killing
    # only the launcher leaves the archive locked, so stop our entire child tree.
    if os.name=='nt':
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    else:process.terminate()
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:process.kill();process.wait()


def cloudflared_binary():
    installed=shutil.which('cloudflared')
    if installed:return installed
    if os.name!='nt':raise RuntimeError('Esta herramienta de beta se prepara primero para Windows.')
    dest=ROOT/'output'/'bin'/'cloudflared-windows-amd64.exe'
    if dest.exists():return str(dest)
    release=json.load(urllib.request.urlopen('https://api.github.com/repos/cloudflare/cloudflared/releases/latest',timeout=30))
    asset=next(a for a in release['assets'] if a['name']==dest.name)
    data=urllib.request.urlopen(asset['browser_download_url'],timeout=60).read()
    if asset.get('digest')!='sha256:'+hashlib.sha256(data).hexdigest():raise RuntimeError('No se pudo verificar el SHA-256 oficial de cloudflared.')
    dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
    return str(dest)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--origin',required=True);parser.add_argument('--port',type=int,default=8875);parser.add_argument('--data',type=Path);parser.add_argument('--publish',action='store_true',help='Publicar el proxy con Vercel CLI, autenticado previamente');args=parser.parse_args()
    settings=WebSettings(args.origin)
    if not settings.secure:parser.error('El túnel público requiere un origen HTTPS.')
    cli=None
    if args.publish:
        cli=shutil.which('vercel') or shutil.which('vercel.cmd')
        if not cli:parser.error('Instalá Vercel CLI e iniciá sesión con vercel login para usar --publish.')
        if not (ROOT/'output'/'vercel-beta'/'.vercel'/'project.json').exists():
            parser.error('Primero ejecutá vercel link dentro de output/vercel-beta y elegí el proyecto existente correo-uns-beta.')
    binary=cloudflared_binary()
    commands=[sys.executable,'-m','correo','--web','--origin',args.origin,'--port',str(args.port),'--no-browser']
    if args.data:commands+=['--data',str(args.data.resolve())]
    # Never expose a legacy process that happens to occupy the target port.
    backend=subprocess.Popen(commands,cwd=ROOT)
    tunnel=None
    try:
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if backend.poll() is not None:raise RuntimeError('El backend no pudo iniciar. Revisá la cuenta configurada y cerrá otras instancias.')
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{args.port}',timeout=1) as response:
                    body=response.read(32768)
                if b'id="login-form"' in body and backend.poll() is None:break
            except OSError:pass
            time.sleep(.2)
        else:raise RuntimeError('No se pudo comprobar el backend con login; no se abrió ningún túnel.')
        tunnel=subprocess.Popen([binary,'tunnel','--url',f'http://127.0.0.1:{args.port}','--http-host-header',f'127.0.0.1:{args.port}','--no-autoupdate','--protocol','http2'],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
        found=threading.Event();url=[None]
        def read_output():
            for line in tunnel.stdout:
                match=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',line)
                if match and url[0] is None:url[0]=match.group(0);found.set()
        threading.Thread(target=read_output,daemon=True).start()
        if not found.wait(60) or tunnel.poll() is not None:raise RuntimeError('No se pudo abrir el túnel temporal. El backend sigue protegido por login.')
        files=deployment_files(url[0]);output=ROOT/'output'/'vercel-beta'
        write_deployment(output,files)
        state={'origin':args.origin,'tunnel':url[0],'port':args.port,'backend_pid':backend.pid,'tunnel_pid':tunnel.pid}
        (ROOT/'output'/'web-beta-runtime.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
        print('Backend con login listo. Origen público: '+args.origin,flush=True)
        print('Destino temporal para el proxy: '+url[0],flush=True)
        print('Archivos mínimos de Vercel: '+str(output),flush=True)
        if args.publish:
            result=subprocess.run([cli,'deploy',str(output),'--prod','--yes'],cwd=ROOT)
            if result.returncode:raise RuntimeError('Vercel no pudo publicar el proxy. No se guardaron credenciales en el proyecto.')
        else:print('Actualizá Vercel con esos archivos. El destino cambia cada vez que se reinicia el túnel.',flush=True)
        print('Dejá esta ventana abierta. Ctrl+C detiene tanto el backend como el túnel.',flush=True)
        while backend.poll() is None and tunnel.poll() is None:time.sleep(.25)
    except KeyboardInterrupt:pass
    except Exception as exc:
        print(str(exc),flush=True);return 1
    finally:
        for process in (tunnel,backend):
            stop_process(process)
    return 0


if __name__=='__main__':raise SystemExit(main())
