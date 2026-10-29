"""Create a source distribution without data, secrets, caches or virtualenv."""
from pathlib import Path
import zipfile


if __name__=='__main__':
    root=Path(__file__).resolve().parent.parent
    output=root/'output'/'CorreoUNS-v0.1.zip'
    output.parent.mkdir(exist_ok=True)
    files=[root/name for name in ('README.md','VERIFICACION.md','CHANGELOG.md','requirements.txt','requirements-lock.txt','requirements-dev.txt','Instalar.cmd','Iniciar Correo.cmd','.gitignore')]
    for folder in ('correo','tests','tools'):
        files.extend(p for p in (root/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.html','.js','.css'))
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        for path in sorted(files):
            z.write(path,'CorreoUNS/'+path.relative_to(root).as_posix())
    with zipfile.ZipFile(output) as z:
        assert z.testzip() is None
        assert not any('.venv' in name or 'demo-data' in name or name.endswith(('.eml','.sqlite3')) for name in z.namelist())
        for name in z.namelist():
            if name.endswith('.py'):compile(z.read(name).decode('utf-8'),name,'exec')
        print(f'{output}\n{len(z.namelist())} archivos · {output.stat().st_size:,} bytes · ZIP y fuentes verificados')
