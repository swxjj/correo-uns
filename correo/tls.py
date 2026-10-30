"""TLS trust for the self-contained macOS application."""
import ssl
import sys


def context():
    if sys.platform == 'darwin':
        import certifi
        # Construct explicitly: packaged apps must not rely on certificate or
        # TLS-debugging file paths inherited from another Python environment.
        step = 'crear contexto'
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            step = 'leer certificados incluidos'
            data = certifi.contents()
            step = 'cargar certificados incluidos'
            ctx.load_verify_locations(cadata=data)
            return ctx
        except OSError as exc:
            exc.tls_step = step
            raise
    return ssl.create_default_context()
