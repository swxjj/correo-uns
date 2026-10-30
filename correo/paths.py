"""One shared data location for the CLI and the macOS application."""
import os
from pathlib import Path
import sys


def data_root():
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'CorreoUNS'
    return Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'CorreoUNS'
