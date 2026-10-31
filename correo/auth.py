"""Single-owner web sessions. Passwords never enter cookies, files or logs."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import re
import secrets
import threading
import time
import unicodedata
from urllib.parse import urlsplit
from .service import Service, close_client, explain
from .store import secret_key

COOKIE = 'correo_session'
PRE_COOKIE = 'correo_pre'
IDLE_SECONDS = 30*60
MAX_SECONDS = 8*60*60


@dataclass(frozen=True)
class WebSettings:
    origin: str
    upstream_host: str = ''

    def __post_init__(self):
        url=urlsplit(self.origin)
        local=url.scheme=='http' and url.hostname=='127.0.0.1'
        if not (url.scheme=='https' or local) or not url.hostname or url.username or url.password or url.query or url.fragment or url.path:
            raise ValueError('El origen debe ser una URL HTTPS sin ruta, o http://127.0.0.1:puerto para pruebas locales.')
        if self.upstream_host and not re.fullmatch(r'[a-z0-9-]+\.trycloudflare\.com',self.upstream_host):
            raise ValueError('El túnel debe usar un host trycloudflare.com válido.')

    @property
    def secure(self): return self.origin.startswith('https://')

    def host_allowed(self,host):
        return host in {urlsplit(self.origin).netloc,self.upstream_host} or bool(re.fullmatch(r'127\.0\.0\.1(?::\d{1,5})?',host))


class OverlayVault:
    """Web login passwords stay in memory without modifying saved OS credentials."""
    def __init__(self,base): self.base,self.session=base,{}
    def get(self,key): return self.session.get(key) or self.base.get(key)
    def put(self,key,password,persist=False):
        if persist:return self.base.put(key,password,True)
        self.session[key]=password
        return False
    def forget(self,key):
        self.session.pop(key,None)
        self.base.forget(key)


def login_address(surname,lu):
    surname=''.join(c for c in unicodedata.normalize('NFD',surname.strip().lower()) if not unicodedata.combining(c))
    if not re.fullmatch(r'[a-z][a-z-]{0,79}',surname) or not re.fullmatch(r'\d{1,12}',lu):
        raise ValueError('Ingresá el apellido como figura en tu dirección institucional y la LU solo con números.')
    return surname+'.'+lu+'@alu.uns.edu.ar'


class Auth:
    def __init__(self,store,vault,settings,clock=time.monotonic):
        self.store,self.vault,self.settings,self.clock=store,vault,settings,clock
        self.sessions={};self.pre={};self.attempts=deque()
        self.lock=threading.RLock();self.login_lock=threading.Lock()
        self.probe=self.check_protocol

    def clean(self):
        now=self.clock()
        self.sessions={k:v for k,v in self.sessions.items() if now-v['seen']<IDLE_SECONDS and now-v['created']<MAX_SECONDS}
        self.pre={k:v for k,v in self.pre.items() if now-v['created']<600}
        if not self.sessions:self.vault.session.clear()

    @staticmethod
    def digest(value):return hashlib.sha256(value.encode()).hexdigest()

    def bootstrap(self):
        with self.lock:
            self.clean()
            if len(self.pre)>=256:self.pre.pop(next(iter(self.pre)))
            raw=secrets.token_urlsafe(32);entry={'csrf':secrets.token_urlsafe(32),'created':self.clock()}
            self.pre[self.digest(raw)]=entry
            return raw,entry

    def session(self,raw,touch=True):
        with self.lock:
            self.clean();entry=self.sessions.get(self.digest(raw or ''))
            if entry and touch:entry['seen']=self.clock()
            return entry

    def login_csrf(self,raw,token):
        with self.lock:
            self.clean();entry=self.pre.get(self.digest(raw or ''))
            return bool(entry and token.isascii() and secrets.compare_digest(entry['csrf'],token))

    def check_protocol(self,protocol,cfg,password):
        class CandidateVault:
            def get(self,key):return password
        candidate=Service(self.store,CandidateVault())
        client=None
        try:
            client=candidate.pop(cfg) if protocol=='pop' else candidate.smtp(cfg)
            return True,''
        except Exception as exc:return False,explain(exc)
        finally:
            if client:close_client(client)

    def login(self,surname,lu,password,old_cookie=''):
        with self.lock:
            now=self.clock()
            while self.attempts and now-self.attempts[0]>=300:self.attempts.popleft()
            if len(self.attempts)>=5:return None,429,'Demasiados intentos. Esperá cinco minutos antes de volver a probar.'
            self.attempts.append(now)
        try:address=login_address(surname,lu)
        except ValueError:return None,401,'No se pudo validar el acceso. Revisá apellido, LU y contraseña.'
        cfg=self.store.config()
        if not cfg.get('address') or not secrets.compare_digest(address,cfg['address'].lower()):
            return None,401,'No se pudo validar el acceso. Revisá apellido, LU y contraseña.'
        if not self.login_lock.acquire(blocking=False):return None,429,'Ya hay una validación en curso. Esperá a que termine.'
        try:
            # Identity is fixed server-side, never taken from editable browser fields.
            cfg={**cfg,'pop_user':address,'smtp_user':address}
            with ThreadPoolExecutor(max_workers=2) as pool:
                pop=pool.submit(self.probe,'pop',cfg,password)
                smtp=pool.submit(self.probe,'smtp',cfg,password)
                pop_ok,pop_error=pop.result();smtp_ok,smtp_error=smtp.result()
            if not pop_ok:
                return None,401,'No se pudo validar el acceso POP3. Revisá la contraseña o intentá más tarde si el servicio de la UNS no está disponible.'
            with self.lock:
                self.clean()
                self.sessions.pop(self.digest(old_cookie or ''),None)
                if len(self.sessions)>=16:self.sessions.pop(next(iter(self.sessions)))
                now=self.clock();raw=secrets.token_urlsafe(32)
                entry={'csrf':secrets.token_urlsafe(32),'created':now,'seen':now,'smtp':smtp_ok,'warning':'' if smtp_ok else 'Ingresaste con POP3. SMTP no pudo autenticarse; podés leer y guardar borradores, pero el envío está deshabilitado. Volvé a iniciar sesión para probarlo nuevamente.'}
                self.sessions[self.digest(raw)]=entry
                self.vault.session[secret_key(cfg,'pop')]=password
                if smtp_ok:self.vault.session[secret_key(cfg,'smtp')]=password
                self.attempts.clear()
            return (raw,entry),200,''
        finally:self.login_lock.release()

    def logout(self,cookie):
        with self.lock:
            self.sessions.pop(self.digest(cookie or ''),None)
            self.clean()
