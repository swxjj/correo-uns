import hashlib
import json
import poplib
import smtplib
import ssl
import threading
import time
from email.utils import getaddresses
from .store import account, secret_key, now, atomic
from .mime import addresses, build_message, content


class UserError(Exception):
    pass


def close_client(client):
    # A failed TLS handshake can leave an invalid socket on Windows. Cleanup must
    # neither mask certificate errors nor keep the operation lock held.
    try:
        client.close()
    except Exception:
        pass


def explain(exc):
    # Never echo protocol replies: they can contain credentials or message content.
    if isinstance(exc, UserError):
        return str(exc)
    if isinstance(exc, ssl.SSLCertVerificationError):
        return 'El certificado TLS no es válido para este servidor. Revisá el nombre y la fecha de Windows; no se desactivó la verificación.'
    if isinstance(exc, (poplib.error_proto, smtplib.SMTPAuthenticationError)):
        return 'El servidor rechazó la operación o la autenticación. Revisá usuario, contraseña y disponibilidad de STARTTLS.'
    if isinstance(exc, (TimeoutError, OSError, smtplib.SMTPServerDisconnected)):
        return 'La conexión falló o agotó el tiempo de espera. Revisá Internet, servidor y puerto; volvé a intentar más tarde.'
    if isinstance(exc, smtplib.SMTPException):
        return 'El servidor SMTP rechazó la operación. Revisá la configuración y los destinatarios.'
    return 'No se pudo completar la operación. Revisá la configuración y el espacio disponible en disco.'


class Service:
    def __init__(self, store, secrets):
        self.store, self.secrets = store, secrets
        self.operation = threading.Lock()
        self.status = dict(running=False, progress='', last_update=None, error='', uidl=None, downloaded=0, next_attempt=None)
        try:
            self.status['last_update'] = json.loads((store.root/'sync.json').read_text('utf-8')).get('last_update')
        except (OSError,ValueError):
            pass
        self.stop = threading.Event()
        self.thread = None
        self.failures = 0
        self.next_due = time.monotonic()+300

    def password(self, config, protocol):
        password = self.secrets.get(secret_key(config, protocol))
        if not password:
            raise UserError('Ingresá la contraseña de '+protocol.upper()+' en Configuración. Podés usarla solo durante esta sesión.')
        return password

    def pop(self, config):
        if not config['address'] or not config['pop_user']:
            raise UserError('Completá la dirección de correo y el usuario POP3 en Configuración.')
        context = ssl.create_default_context()
        client = None

        try:
            if config['pop_tls'] == 'ssl':
                client = poplib.POP3_SSL(config['pop_host'], config['pop_port'], timeout=25, context=context)
            else:
                client = poplib.POP3(config['pop_host'], config['pop_port'], timeout=25)

                client.stls(context=context)

            client.user(config['pop_user'])

            client.pass_(self.password(config,'pop'))
            return client
        except BaseException:
            if client:
                close_client(client)
            raise

    def smtp(self, config):
        if not config['address'] or not config['smtp_user']:
            raise UserError('Completá la dirección de correo y el usuario SMTP en Configuración.')
        client = None

        try:
            context = ssl.create_default_context()
            if config['smtp_tls'] == 'ssl':
                client = smtplib.SMTP_SSL(config['smtp_host'], config['smtp_port'], timeout=25, context=context)
            else:
                client = smtplib.SMTP(config['smtp_host'], config['smtp_port'], timeout=25)

                client.ehlo()

                client.starttls(context=context)

            client.ehlo()

            client.login(config['smtp_user'], self.password(config,'smtp'))
            return client
        except BaseException:
            if client:
                close_client(client)
            raise

    def uidls(self, client):
        try:
            rows = client.uidl()[1]
        except poplib.error_proto:
            self.status['uidl'] = False
            raise UserError('El servidor no ofrece UIDL. No se descargará ni se activará la actualización automática: sin identificadores estables no podemos asegurar que no haya duplicados. Usá un cliente que admita otra estrategia o consultá a la UNS.')
        result = []
        for row in rows:
            number, uid = row.split()
            result.append((int(number),uid.decode('ascii')))
        if len({u for _,u in result}) != len(result) or len({n for n,_ in result}) != len(result):
            raise UserError('El servidor devolvió identificadores UIDL duplicados. Se detuvo la descarga.')
        self.status['uidl'] = True
        return result

    def diagnostic(self, protocol):
        if not self.operation.acquire(blocking=False):
            raise UserError('Hay otra operación en curso. Esperá a que termine.')
        client = None
        try:
            cfg = self.store.config()
            client = self.pop(cfg) if protocol=='pop' else self.smtp(cfg)
            if protocol=='pop':
                self.uidls(client)
            return 'Conexión TLS y autenticación '+protocol.upper()+' correctas.' + (' UIDL disponible; no se descargaron mensajes.' if protocol=='pop' else ' No se envió ningún mensaje.')
        finally:
            if client:
                close_client(client)
            self.operation.release()

    def sync(self, already_acquired=False):
        if not already_acquired and not self.operation.acquire(blocking=False):
            raise UserError('Hay otra operación en curso. Esperá a que termine.')
        client = None
        self.status.update(running=True, error='', downloaded=0, progress='Conectando de forma segura…')
        try:
            cfg = self.store.config()
            client = self.pop(cfg)
            listing = self.uidls(client)
            known = self.store.known(account(cfg))
            pending = [(n,u) for n,u in listing if u not in known]
            for i,(number,uid) in enumerate(pending,1):
                self.status['progress'] = f'Descargando {i} de {len(pending)} mensajes nuevos…'
                raw = b'\r\n'.join(client.retr(number)[1])+b'\r\n'
                ident = hashlib.sha256((account(cfg)+'\0'+uid).encode()).hexdigest()[:32]
                self.store.save(raw, id=ident, account=account(cfg), uidl=uid)
                self.status['downloaded'] = i
            self.status.update(last_update=now(), progress=f'Actualizado. {len(pending)} mensajes nuevos.', error='')
            self.failures = 0
        except Exception as exc:
            self.failures += 1
            self.status['error'] = explain(exc)
        finally:
            if client:
                # No DELE, and closing the socket never enters a deletion transaction.
                close_client(client)
            self.status['running'] = False
            delay = max(self.store.config()['interval']*60, min(3600, 60*2**min(self.failures,6)))
            self.next_due = time.monotonic()+delay
            self.status['next_attempt'] = time.time()+delay
            try:
                with self.store.lock:
                    atomic(self.store.root/'sync.json', json.dumps({'last_update':self.status['last_update']}).encode())
            except OSError:
                self.status['error'] = 'No se pudo guardar el estado de actualización. Revisá el espacio y los permisos de la carpeta de datos.'
            self.operation.release()

    def start_sync(self):
        if not self.operation.acquire(blocking=False):
            raise UserError('Hay otra operación en curso. Esperá a que termine.')
        self.status['running'] = True
        threading.Thread(target=self.sync,kwargs={'already_acquired':True},daemon=True).start()

    def start(self):
        self.next_due = time.monotonic()+self.store.config()['interval']*60
        def loop():
            while not self.stop.wait(1):
                if self.store.config()['auto'] and self.status['uidl'] is not False and time.monotonic() >= self.next_due:
                    try:
                        self.sync()
                    except UserError:
                        self.next_due = time.monotonic()+60
        self.thread = threading.Thread(target=loop,daemon=True)
        self.thread.start()

    def send(self, draft_id):
        if not self.operation.acquire(blocking=False):
            raise UserError('Hay otra operación en curso. Esperá a que termine.')
        client = None
        attempt = None
        data_started = False
        try:
            info = self.store.info(draft_id)
            if info['folder'] != 'drafts':
                raise UserError('Solo se pueden enviar borradores.')
            for row in self.store.listing('outbox')+self.store.listing('sent'):
                other = self.store.info(row['id'])
                if other.get('draft_id')==draft_id and other['state'] in ('sending','uncertain','accepted'):
                    raise UserError('Este borrador ya tiene un envío aceptado o incierto. Revisá Envíos pendientes y Enviados; no se reenviará automáticamente.')
            draft = info['draft']
            recipients = list(dict.fromkeys(addresses(draft.get('to',''))+addresses(draft.get('cc',''))+addresses(draft.get('bcc',''))))
            if not recipients:
                raise UserError('Agregá al menos un destinatario.')
            cfg = self.store.config()
            attachments = [(a['name'],a['data']) for a in content(self.store.raw(draft_id))[3]]
            raw = build_message(cfg,draft,attachments)
            attempt = self.store.save(raw, folder='outbox', state='preparing', unread=0, draft_id=draft_id, bcc=draft.get('bcc',''))
            client = self.smtp(cfg)
            code,_ = client.mail(cfg['address'])
            if code != 250:
                raise UserError('SMTP rechazó el remitente. No se envió el mensaje.')
            for recipient in recipients:
                code,_ = client.rcpt(recipient)
                if code not in (250,251):
                    raise UserError('SMTP rechazó un destinatario. Se canceló el envío completo antes de transmitir el mensaje.')
            self.store.update(attempt['id'], state='sending')
            data_started = True
            code,_ = client.data(raw)
            if code != 250:
                data_started = False
                raise UserError('SMTP no aceptó el mensaje. Podés corregir el borrador y volver a intentar.')
            # Persist acceptance before QUIT; errors after this cannot undo server acceptance.
            self.store.update(attempt['id'], folder='sent', state='accepted')
            return dict(message='El servidor SMTP aceptó el mensaje. Esto no confirma su entrega final.', id=attempt['id'], state='accepted')
        except Exception as exc:
            if isinstance(exc, smtplib.SMTPDataError):
                data_started = False
            state = 'uncertain' if data_started else 'failed'
            if attempt:
                self.store.update(attempt['id'],state=state)
            if state=='uncertain':
                return dict(message='Resultado incierto: la conexión se interrumpió durante el envío. El servidor podría haber aceptado el mensaje. No vuelvas a enviarlo hasta comprobarlo con el destinatario o con la UNS. No habrá reintento automático.',state=state,id=attempt['id'])
            raise UserError(explain(exc)) from None
        finally:
            if client:
                close_client(client)
            self.operation.release()
