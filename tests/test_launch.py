"""Verify the supported launcher, including the Windows archive lock."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0))
        return s.getsockname()[1]


def test_launcher_loopback_and_second_instance(tmp_path):
    first_port,second_port=free_port(),free_port()
    root=tmp_path/'launcher'
    command=[sys.executable,'-m','correo','--no-browser','--data',str(root)]
    first=subprocess.Popen(command+['--port',str(first_port)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    try:
        deadline=time.monotonic()+20
        ready=False
        while time.monotonic()<deadline:
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{first_port}',timeout=1) as r:
                    ready=r.status==200
                if ready:break
            except OSError:time.sleep(.1)
        assert ready
        second=subprocess.run(command+['--port',str(second_port)],capture_output=True,timeout=15)
        assert second.returncode==1
        assert b'Traceback' not in second.stdout+second.stderr
        assert b'otra instancia' in second.stdout
        same_port=subprocess.run(command+['--port',str(first_port)],capture_output=True,timeout=15)
        assert same_port.returncode==1 and b'puerto' in same_port.stdout
    finally:
        first.terminate();first.communicate(timeout=10)


def test_immediate_restart_same_port(tmp_path):
    port = free_port()
    command = [sys.executable, '-m', 'correo', '--no-browser', '--data',
               str(tmp_path / 'restart'), '--port', str(port)]
    for _ in range(2):
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 20
            ready = False
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}', timeout=1) as response:
                        ready = response.status == 200
                    if ready:
                        break
                except OSError:
                    time.sleep(.1)
            assert ready
        finally:
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=10)
