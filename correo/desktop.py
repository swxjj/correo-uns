"""macOS menu bar companion for the existing local browser interface."""
import threading
import time
import webbrowser


def run(server, sock, app, port, open_browser=True):
    import rumps

    url = f'http://127.0.0.1:{port}'
    service = app.state.service
    app.state.exit_requested = threading.Event()
    worker = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    worker.start()
    deadline = time.monotonic() + 20
    while not server.started:
        if not worker.is_alive() or time.monotonic() > deadline:
            server.should_exit = True
            rumps.alert('Correo UNS', 'No se pudo iniciar el correo local. Volvé a abrir la aplicación.')
            return
        time.sleep(.1)

    def show(_):
        webbrowser.open(url)

    def quit_app(_):
        # Do not interrupt a download, backup or SMTP transaction.
        if not service.operation.acquire(blocking=False):
            rumps.alert('Correo UNS', 'Hay una operación en curso. Esperá a que termine y volvé a salir.')
            return
        service.stop.set()
        finish_shutdown()

    def finish_shutdown():
        server.should_exit = True
        worker.join(timeout=30)
        if worker.is_alive():
            service.operation.release()
            rumps.alert('Correo UNS', 'El cierre todavía está en curso. Esperá unos segundos.')
            return
        rumps.quit_application()

    menu = rumps.App('CorreoUNS', title='✉ UNS', quit_button=None, menu=[
        rumps.MenuItem('Abrir correo', callback=show),
        None,
        rumps.MenuItem('Salir de Correo UNS', callback=quit_app),
    ])
    def check_exit(_):
        if app.state.exit_requested.is_set():
            finish_shutdown()

    timer = rumps.Timer(check_exit, .5)
    timer.start()
    if open_browser:
        show(None)
    try:
        menu.run()
    finally:
        timer.stop()
        service.stop.set()
        server.should_exit = True
        worker.join(timeout=30)
