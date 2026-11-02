import asyncio
from contextvars import ContextVar
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import re
import secrets as random_secrets
import time
from urllib.parse import quote
from email.utils import getaddresses
from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, Response, JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .store import Store, DEFAULT, secret_key
from .secrets import Secrets
from .paths import data_root
from .service import Service, UserError, explain
from .mime import content, sanitized_html, build_message, addresses, safe_name, message_links
from .auth import Auth, OverlayVault, WebSettings, COOKIE, PRE_COOKIE, MAX_SECONDS
from .accounts import Accounts, AccountProxy, EmptyVault

MAX_REQUEST = 64*1024*1024
ASSETS = Path(__file__).parent/'static'


class Config(BaseModel):
    model_config = ConfigDict(extra='forbid')
    address: str = Field(max_length=254)
    display_name: str = Field(default='',max_length=200)
    pop_host: str = Field(default=DEFAULT['pop_host'],min_length=1,max_length=253)
    pop_port: int = Field(default=110,ge=1,le=65535)
    pop_tls: str = 'starttls'
    pop_user: str = Field(max_length=254)
    smtp_host: str = Field(default=DEFAULT['smtp_host'],min_length=1,max_length=253)
    smtp_port: int = Field(default=25,ge=1,le=65535)
    smtp_tls: str = 'starttls'
    smtp_user: str = Field(max_length=254)
    auto: bool = False
    interval: int = Field(default=5,ge=1,le=1440)

    @field_validator('pop_tls','smtp_tls')
    @classmethod
    def tls(cls,value):
        if value not in ('starttls','ssl'):
            raise ValueError('Usá STARTTLS o TLS implícito.')
        return value

    @field_validator('address')
    @classmethod
    def email(cls,value):
        if not value:
            return value
        if addresses(value) != [value]:
            raise ValueError('Ingresá una dirección de correo completa.')
        return value

    @field_validator('pop_host','smtp_host')
    @classmethod
    def host(cls,value):
        if not re.fullmatch(r'[A-Za-z0-9.-]+',value):
            raise ValueError('Nombre de servidor inválido.')
        return value.lower()

    @field_validator('pop_user','smtp_user','display_name')
    @classmethod
    def no_controls(cls,value):
        if any(ord(c)<32 for c in value):
            raise ValueError('El campo contiene caracteres no permitidos.')
        return value


class Password(BaseModel):
    password: str = Field(min_length=1,max_length=1000)
    persist: bool = False


class Draft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    to: str = Field(default='',max_length=10000)
    cc: str = Field(default='',max_length=10000)
    bcc: str = Field(default='',max_length=10000)
    subject: str = Field(default='',max_length=1000)
    body: str = Field(default='',max_length=2000000)
    in_reply_to: str = Field(default='',max_length=2000)
    references: str = Field(default='',max_length=10000)

    @field_validator('to','cc','bcc','subject','in_reply_to','references')
    @classmethod
    def header(cls,value):
        if '\r' in value or '\n' in value:
            raise ValueError('No se permiten saltos de línea en encabezados.')
        return value


class Flags(BaseModel):
    unread: bool | None = None
    starred: bool | None = None
    archived: bool | None = None


class Login(BaseModel):
    model_config = ConfigDict(extra='forbid')
    surname: str = Field(min_length=1,max_length=80)
    lu: str = Field(min_length=1,max_length=12)
    password: str = Field(min_length=1,max_length=1000)


def create_app(root=None, start_worker=True, vault=None, web: WebSettings | None=None):
    root = root or data_root()
    store = Store(root)
    vault = vault or Secrets()
    if web:
        cfg=store.config()
        if not cfg['address'].endswith('@alu.uns.edu.ar') or any(cfg[p+'_user']!=cfg['address'] for p in ('pop','smtp')):
            raise ValueError('Configurá primero la cuenta propietaria y ambos usuarios con la dirección institucional completa en el modo local.')
        vault=OverlayVault(vault)
    service = Service(store,vault)
    owner_store,owner_service,owner_vault=store,service,vault
    context=ContextVar('correo_account',default=None)
    accounts=Accounts(store,vault,service,lambda:OverlayVault(EmptyVault())) if web else None
    token = random_secrets.token_urlsafe(32)
    auth=Auth(store,vault,web,accounts=accounts) if web else None
    if web:
        store=AccountProxy(context,'store');service=AccountProxy(context,'service');vault=AccountProxy(context,'vault')

    @asynccontextmanager
    async def lifespan(app):
        if start_worker:
            if accounts:accounts.start()
            else:owner_service.start()
        async def cleanup():
            while True:
                await asyncio.sleep(5)
                with auth.lock:auth.clean()
        task=asyncio.create_task(cleanup()) if auth else None
        yield
        if task:
            task.cancel()
            try:await task
            except asyncio.CancelledError:pass
        if accounts:accounts.stop()
        else:owner_service.stop.set()

    app = FastAPI(title='Correo UNS local',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
    app.state.store,app.state.service,app.state.token,app.state.vault = owner_store,owner_service,token,owner_vault
    app.state.auth=auth
    app.state.accounts=accounts

    def secured(response):
        response.headers.update({'Cache-Control':'no-store, private' if web else 'no-store','CDN-Cache-Control':'no-store','Vercel-CDN-Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY','Cross-Origin-Resource-Policy':'same-origin','Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-src 'self'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'"})
        if web and web.secure:response.headers['Strict-Transport-Security']='max-age=31536000'
        return response

    @app.middleware('http')
    async def protect(request, call_next):
        account_context=None
        host = request.headers.get('host','')
        if not (web.host_allowed(host) if web else re.fullmatch(r'127\.0\.0\.1(?::[0-9]{1,5})?',host)):
            return secured(Response('Host no permitido.',status_code=403))
        origin = request.headers.get('origin')
        expected=web.origin if web else 'http://'+host
        if (origin and origin!=expected) or (web and request.method not in ('GET','HEAD') and origin!=expected):
            return secured(Response('Origen no permitido.',status_code=403))
        external_navigation=bool(web and request.method=='GET' and request.url.path=='/' and request.headers.get('sec-fetch-mode')=='navigate' and request.headers.get('sec-fetch-dest')=='document')
        if request.headers.get('sec-fetch-site') not in (None,'none','same-origin') and not external_navigation:
            return secured(Response('Solicitud externa bloqueada.',status_code=403))
        if request.url.path.startswith('/api/'):
            csrf=request.headers.get('x-csrf-token','')
            if web:
                if request.url.path=='/api/auth/login':
                    if not auth.login_csrf(request.cookies.get(PRE_COOKIE),csrf):
                        return secured(JSONResponse({'detail':'Recargá la página de ingreso antes de volver a intentar.'},status_code=403))
                else:
                    session=auth.session(request.cookies.get(COOKIE),touch=request.url.path not in ('/api/status','/api/auth/me'))
                    if not session:return secured(JSONResponse({'detail':'Tu sesión terminó. Volvé a ingresar.'},status_code=401))
                    account_context=accounts.existing(session['account'])
                    if account_context is None:return secured(JSONResponse({'detail':'Tu sesión terminó. Volvé a ingresar.'},status_code=401))
                    if not csrf.isascii() or not random_secrets.compare_digest(csrf,session['csrf']):return secured(JSONResponse({'detail':'Token de sesión inválido. Recargá la página.'},status_code=403))
                    if request.url.path.endswith('/send') and not session['smtp']:
                        return secured(JSONResponse({'detail':session['warning']},status_code=403))
                    if request.url.path=='/api/restore' or request.url.path=='/api/quit' or (request.url.path.startswith('/api/credentials/') and request.method!='GET'):
                        return secured(JSONResponse({'detail':'Esta operación se administra únicamente en el modo local de Windows.'},status_code=403))
            elif not random_secrets.compare_digest(csrf,token):
                return secured(Response('Sesión inválida. Recargá la aplicación.',status_code=403))
        if request.method not in ('GET','HEAD'):
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                limit=8192 if request.url.path=='/api/auth/login' else MAX_REQUEST
                if size>limit:
                    return secured(Response('El archivo o solicitud supera el límite permitido.',status_code=413))
                chunks.append(chunk)
            request._body = b''.join(chunks)
        handle=context.set(account_context)
        try:response = await call_next(request)
        finally:context.reset(handle)
        return secured(response)

    @app.exception_handler(RequestValidationError)
    async def validation(request,exc):
        # Pydantic's default response echoes submitted input (including passwords).
        if request.url.path=='/api/auth/login':
            return JSONResponse({'detail':'Completá apellido, LU y contraseña con los límites indicados en el formulario.'},status_code=422)
        return JSONResponse({'detail':'Revisá los campos: direcciones completas, puertos de 1 a 65535, TLS seguro e intervalo de 1 a 1440 minutos.'},status_code=422)

    @app.exception_handler(Exception)
    async def failure(request,exc):
        return JSONResponse({'detail':explain(exc)},status_code=400)

    @app.exception_handler(UserError)
    async def user_failure(request,exc):
        return JSONResponse({'detail':str(exc)},status_code=400)

    @app.exception_handler(ValueError)
    async def invalid(request,exc):
        return JSONResponse({'detail':'Los datos o el archivo no son válidos. Revisá el formato y los campos.'},status_code=400)

    @app.exception_handler(FileNotFoundError)
    async def missing(request,exc):
        return JSONResponse({'detail':'No se encontró el mensaje o el archivo solicitado.'},status_code=404)

    @app.get('/',response_class=HTMLResponse)
    def home(request: Request):
        csrf=token
        if web:
            session=auth.session(request.cookies.get(COOKIE))
            if not session:
                raw,entry=auth.bootstrap()
                response=HTMLResponse((ASSETS/'login.html').read_text('utf-8').replace('__CSRF__',entry['csrf']))
                response.set_cookie(PRE_COOKIE,raw,httponly=True,secure=web.secure,samesite='strict',max_age=600,path='/api/auth')
                return response
            csrf=session['csrf']
        return HTMLResponse((ASSETS/'index.html').read_text('utf-8').replace('__CSRF__',csrf).replace('__QUIT_BUTTON__', '<button id="quit">Salir de Correo UNS</button>' if hasattr(app.state,'exit_requested') else '').replace('__LOGOUT_BUTTON__','<button id="logout">Cerrar sesión</button>' if web else ''))

    @app.get('/login.js')
    def login_js():
        return Response((ASSETS/'login.js').read_text('utf-8'),media_type='text/javascript')

    @app.post('/api/auth/login')
    def login(value: Login,request: Request):
        if not auth:raise HTTPException(404)
        result,code,message=auth.login(value.surname,value.lu,value.password,request.cookies.get(COOKIE,''))
        if not result:return JSONResponse({'detail':message},status_code=code,headers={'Retry-After':'300'} if code==429 else {})
        raw,entry=result
        response=JSONResponse({'message':'Ingreso correcto.','smtp_available':entry['smtp'],'warning':entry['warning']})
        response.set_cookie(COOKIE,raw,httponly=True,secure=web.secure,samesite='strict',max_age=MAX_SECONDS,path='/')
        response.delete_cookie(PRE_COOKIE,path='/api/auth',secure=web.secure,httponly=True,samesite='strict')
        with auth.lock:auth.pre.pop(auth.digest(request.cookies.get(PRE_COOKIE,'')),None)
        return response

    @app.get('/api/auth/me')
    def me(request: Request):
        if not auth:return {'enabled':False}
        session=auth.session(request.cookies.get(COOKIE),touch=False)
        return {'enabled':True,'address':session['account'],'smtp_available':session['smtp'],'warning':session['warning']}

    @app.post('/api/auth/logout')
    def logout(request: Request):
        if not auth:raise HTTPException(404)
        auth.logout(request.cookies.get(COOKIE))
        response=JSONResponse({'message':'Sesión cerrada.'})
        response.delete_cookie(COOKIE,path='/',secure=web.secure,httponly=True,samesite='strict')
        return response

    @app.get('/app.js')
    def js():
        return Response((ASSETS/'app.js').read_text('utf-8'),media_type='text/javascript')

    @app.get('/style.css')
    def css():
        return Response((ASSETS/'style.css').read_text('utf-8'),media_type='text/css')

    @app.get('/favicon.ico')
    def favicon():
        return Response(status_code=204)

    @app.get('/api/config')
    def config():
        cfg = store.config()
        return dict(config=cfg,credentials={p:bool(vault.get(secret_key(cfg,p))) for p in ('pop','smtp')},data_folder='Archivo privado en la PC del servidor' if web else str(store.root),web_mode=bool(web))

    @app.put('/api/config')
    def save_config(cfg: Config):
        if not service.operation.acquire(blocking=False):
            raise UserError('Esperá a que termine la operación actual antes de cambiar la configuración.')
        try:
            old = store.config()
            value = cfg.model_dump()
            if web and any(value[k]!=old[k] for k in value if k not in ('display_name','auto','interval')):
                raise UserError('La cuenta y los servidores se administran únicamente desde el modo local de Windows.')
            changed = any(old[k]!=value[k] for k in ('address','pop_host','pop_port','pop_tls','pop_user'))
            if cfg.auto and (changed or service.status['uidl'] is not True):
                raise UserError('Primero guardá sin actualización automática y ejecutá Probar POP3 para verificar UIDL. Después podés activar la actualización automática.')
            store.save_config(value)
            if changed:
                service.status['uidl'] = None
            service.next_due = time.monotonic()+cfg.interval*60
            return {'message':'Configuración guardada.'}
        finally:
            service.operation.release()

    @app.put('/api/credentials/{protocol}')
    def password(protocol: str, value: Password):
        if protocol not in ('pop','smtp'):
            raise HTTPException(404)
        saved = vault.put(secret_key(store.config(),protocol),value.password,value.persist)
        return {'message':'Contraseña guardada en el almacén seguro del sistema.' if saved else 'Contraseña disponible solo durante esta sesión. No quedó guardada de forma persistente.'}

    @app.delete('/api/credentials/{protocol}')
    def forget(protocol: str):
        if protocol not in ('pop','smtp'):
            raise HTTPException(404)
        vault.forget(secret_key(store.config(),protocol))
        return {'message':'Credencial eliminada para la configuración actual.'}

    @app.post('/api/test/{protocol}')
    def diagnostic(protocol: str):
        if protocol not in ('pop','smtp'):
            raise HTTPException(404)
        try:
            return {'message':service.diagnostic(protocol)}
        except Exception as exc:
            raise UserError(explain(exc)) from None

    @app.post('/api/quit')
    def quit_desktop():
        event = getattr(app.state,'exit_requested',None)
        if event is None:
            raise UserError('Para cerrar esta instancia usá Ctrl+C en la Terminal.')
        if not service.operation.acquire(blocking=False):
            raise UserError('Hay una operación en curso. Esperá a que termine antes de salir.')
        # Keep the operation lock until process exit, preventing new mail work.
        service.stop.set()
        event.set()
        return {'message':'Correo UNS se cerró. Ya podés cerrar esta pestaña.'}

    @app.post('/api/sync')
    def sync():
        service.start_sync()
        return {'message':'Actualización iniciada.'}

    @app.get('/api/status')
    def status():
        return service.status

    @app.get('/api/messages')
    def listing(folder: str='inbox', q: str=''):
        return store.listing(folder,q)

    @app.get('/api/messages/{ident}')
    def message(ident: str):
        msg,plain,html,atts = content(store.raw(ident))
        info = store.info(ident)
        return dict(info=info,subject=str(msg.get('Subject','(Sin asunto)')),sender=str(msg.get('From','')),to=str(msg.get('To','')),cc=str(msg.get('Cc','')),date=str(msg.get('Date','')),body=plain if plain.strip() else '(Este mensaje solo contiene HTML. Podés abrir la vista HTML aislada y usar los enlaces del mensaje que aparecen debajo.)',has_html=bool(html),links=message_links(plain,html),attachments=[{'name':a['name'],'size':a['size'],'index':i} for i,a in enumerate(atts)])

    @app.get('/api/messages/{ident}/html',response_class=HTMLResponse)
    def html(ident: str):
        clean = sanitized_html(content(store.raw(ident))[2])
        return '<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'none\'; style-src \'none\'; form-action \'none\'; base-uri \'none\'">'+clean

    @app.get('/api/messages/{ident}/attachment/{index}')
    def attachment(ident: str,index: int):
        atts = content(store.raw(ident))[3]
        if not 0<=index<len(atts):
            raise HTTPException(404)
        att = atts[index]
        return Response(att['data'],media_type='application/octet-stream',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(att['name'])})

    @app.get('/api/messages/{ident}/eml')
    def original(ident: str):
        return Response(store.raw(ident),media_type='application/octet-stream',headers={'Content-Disposition':f'attachment; filename="{ident}.eml"'})

    @app.patch('/api/messages/{ident}')
    def flags(ident: str,value: Flags):
        store.update(ident,**{k:int(v) for k,v in value.model_dump().items() if v is not None})
        return {'message':'Estado local actualizado.'}

    def draft_attachments(ident):
        return [(a['name'],a['data']) for a in content(store.raw(ident))[3]]

    def write_draft(value,ident=None,attachments=None):
        if ident:
            info = store.info(ident)
            if info['folder']!='drafts':
                raise UserError('El mensaje no es un borrador.')
            # An accepted or ambiguous send freezes the source draft to avoid accidental resend/edit confusion.
            for row in store.listing('sent')+store.listing('outbox'):
                other = store.info(row['id'])
                if other.get('draft_id')==ident and other['state'] in ('accepted','uncertain','sending'):
                    raise UserError('Este borrador ya tiene un envío aceptado o incierto. Creá uno nuevo si necesitás escribir otro mensaje.')
            attachments = draft_attachments(ident) if attachments is None else attachments
        else:
            info = {'folder':'drafts','unread':0}
            attachments = attachments or []
        info['draft'] = value.model_dump()
        raw = build_message(store.config(),info['draft'],attachments,include_bcc=True)
        return store.save(raw,**info)

    @app.post('/api/drafts')
    def create_draft(value: Draft):
        return write_draft(value)

    @app.put('/api/drafts/{ident}')
    def edit_draft(ident: str,value: Draft):
        return write_draft(value,ident)

    @app.post('/api/drafts/{ident}/attachments')
    async def add_attachments(ident: str,files: list[UploadFile]=File(...)):
        current = draft_attachments(ident)
        for file in files:
            current.append((safe_name(file.filename),await file.read()))
        if sum(len(data) for _,data in current)>25*1024*1024:
            raise UserError('Los adjuntos del borrador superan el límite de 25 MB.')
        return write_draft(Draft(**store.info(ident)['draft']),ident,current)

    @app.delete('/api/drafts/{ident}/attachments/{index}')
    def remove_attachment(ident: str,index: int):
        current = draft_attachments(ident)
        if not 0<=index<len(current):
            raise HTTPException(404)
        del current[index]
        return write_draft(Draft(**store.info(ident)['draft']),ident,current)

    @app.post('/api/messages/{ident}/reply')
    def reply(ident: str,all: bool=False):
        msg,plain,html,atts = content(store.raw(ident))
        own = store.config()['address'].lower()
        to = [a for _,a in getaddresses([str(msg.get('Reply-To') or msg.get('From',''))]) if a.lower()!=own]
        cc = []
        if all:
            cc = [a for _,a in getaddresses([str(msg.get('To','')),str(msg.get('Cc',''))]) if a.lower()!=own and a not in to]
        subject = str(msg.get('Subject',''))
        refs = (str(msg.get('References',''))+' '+str(msg.get('Message-ID',''))).strip()
        value = Draft(to=', '.join(dict.fromkeys(to)),cc=', '.join(dict.fromkeys(cc)),subject=subject if subject.lower().startswith('re:') else 'Re: '+subject,body='\n\n'+f'El {msg.get("Date", "")}, {msg.get("From", "")} escribió:\n'+'\n'.join('> '+line for line in plain.splitlines()),in_reply_to=str(msg.get('Message-ID','')),references=refs)
        return write_draft(value)

    @app.post('/api/drafts/{ident}/send')
    def send(ident: str):
        return service.send(ident)

    @app.post('/api/backup')
    def backup():
        return Response(store.backup(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="CorreoUNS-respaldo.zip"'})

    @app.post('/api/restore')
    async def restore(file: UploadFile=File(...)):
        if not service.operation.acquire(blocking=False):
            raise UserError('Esperá a que termine la operación en curso antes de restaurar.')
        try:
            # Validate known config fields before replacement. Store validates paths and originals.
            data = await file.read()
            import zipfile,io
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if 'config.json' in z.namelist():
                    Config(**json.loads(z.read('config.json')))
            old_cfg = store.config()
            preserved = store.restore(data)
            new_cfg = store.config()
            for cfg in (old_cfg,new_cfg):
                for p in ('pop','smtp'):
                    vault.forget(secret_key(cfg,p))
            service.status.update(uidl=None,last_update=None,error='',progress='Respaldo restaurado. Volvé a configurar las contraseñas y probá las conexiones.')
            return {'message':'Restauración completada. Las credenciales deben configurarse nuevamente. Datos anteriores protegidos en: '+preserved}
        finally:
            service.operation.release()

    return app
