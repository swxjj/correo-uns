"""Build a self-contained macOS app and a ZIP without synced-folder metadata."""
from pathlib import Path
import platform
import plistlib
import shutil
import ssl
import subprocess
import sys
import tempfile


def main():
    if sys.platform != 'darwin':
        raise SystemExit('Este paquete debe construirse en macOS.')
    root = Path(__file__).resolve().parent.parent
    output = root / 'output'
    output.mkdir(exist_ok=True)
    # Signing in a synced Documents folder can add Finder/resource metadata.
    with tempfile.TemporaryDirectory(prefix='correo-uns-build-') as directory:
        staging = Path(directory)
        command = [
            sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
            '--windowed', '--onedir', '--name', 'Correo UNS',
            '--osx-bundle-identifier', 'ar.edu.uns.correo.personal',
            '--distpath', str(staging / 'dist'), '--workpath', str(staging / 'build'),
            '--specpath', str(staging), '--paths', str(root),
            '--add-data', f'{root / "correo/static"}:correo/static',
            '--hidden-import', 'keyring.backends.macOS',
            '--hidden-import', 'uvicorn.logging',
            '--hidden-import', 'uvicorn.loops.auto',
            '--hidden-import', 'uvicorn.protocols.http.auto',
            '--hidden-import', 'uvicorn.protocols.websockets.auto',
            '--hidden-import', 'uvicorn.lifespan.on',
            str(root / 'tools/macos_entry.py'),
        ]
        # Some Python distributions ship an additional OpenSSL trust policy.
        # Keep it with the frozen stdlib rather than dropping that policy.
        runtime_policy = Path(ssl.__file__).with_name('codex-rejected-cas.pem')
        if runtime_policy.is_file():
            command[3:3] = ['--add-data', f'{runtime_policy}:.']
        subprocess.run(command, cwd=root, check=True)
        bundle = staging / 'dist/Correo UNS.app'
        plist = bundle / 'Contents/Info.plist'
        info = plistlib.loads(plist.read_bytes())
        info.update(LSUIElement=True, CFBundleShortVersionString='0.2.0',
                    CFBundleVersion='2', NSHighResolutionCapable=True)
        plist.write_bytes(plistlib.dumps(info))
        for attribute in ('com.apple.FinderInfo', 'com.apple.ResourceFork'):
            subprocess.run(['xattr', '-dr', attribute, str(bundle)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(bundle)], check=True)
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)
        archive = output / f'CorreoUNS-macOS-{platform.machine()}.zip'
        subprocess.run(['ditto', '-c', '-k', '--norsrc', '--noextattr', '--keepParent',
                        str(bundle), str(archive)], check=True)
        target = output / 'Correo UNS.app'
        if target.exists():
            shutil.rmtree(target)
        subprocess.run(['ditto', '--noextattr', '--norsrc', str(bundle), str(target)], check=True)
    print(f'Aplicación: {target}\nDistribución: {archive}\nMové la app a Aplicaciones antes de usarla.')


if __name__ == '__main__':
    main()
