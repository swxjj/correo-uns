"""Menu actions must preserve in-flight mail and stop the server on exit."""
from types import SimpleNamespace
import sys
import threading
import time

import pytest
from correo.desktop import run


@pytest.mark.parametrize('busy', [False, True])
def test_menu_exit_preserves_active_operation(monkeypatch, busy):
    operation = threading.Lock()
    if busy:
        operation.acquire()
    stop = threading.Event()
    service = SimpleNamespace(operation=operation, stop=stop)
    state = {'quit': False, 'alerts': [], 'opened': []}
    class Server:
        started = False
        should_exit = False
        def run(self, sockets):
            self.started = True
            while not self.should_exit:
                time.sleep(.01)
    server = Server()
    class Item:
        def __init__(self, title, callback):
            self.title, self.callback = title, callback
    class App:
        def __init__(self, name, title, quit_button, menu):
            assert title == '✉ UNS' and quit_button is None
            self.menu = menu
        def run(self):
            self.menu[-1].callback(None)
            if busy:
                assert not stop.is_set()
                assert not server.should_exit
                assert not state['quit']
                assert state['alerts']
                operation.release()
                self.menu[-1].callback(None)
            assert state['quit'] and stop.is_set()
    def quit_app():
        state['quit'] = True
    class Timer:
        def __init__(self, callback, interval):
            pass
        def start(self):
            pass
        def stop(self):
            pass
    monkeypatch.setitem(sys.modules, 'rumps', SimpleNamespace(
        App=App, MenuItem=Item, Timer=Timer, quit_application=quit_app,
        alert=lambda *args: state['alerts'].append(args)))
    monkeypatch.setattr('webbrowser.open', state['opened'].append)
    run(server, object(), SimpleNamespace(state=SimpleNamespace(service=service)), 18765)
    assert state['opened'] == ['http://127.0.0.1:18765']
