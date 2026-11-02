"""Demo isolated from real account: python -m tools.demo. All network mail clients replaced."""
from email.message import EmailMessage
from email import policy
from pathlib import Path
import uvicorn
import argparse
from correo.web import create_app
from correo.store import DEFAULT, Store
from correo.auth import WebSettings
from correo.accounts import write_allowlist
from correo.service import Service
from email.parser import BytesParser


class MemoryVault:
    def __init__(self): self.session={}
    def get(self,k): return self.session.get(k)
    def put(self,k,v,persist=False): self.session[k]=v; return False
    def forget(self,k): self.session.pop(k,None)


def make_app(web=False,port=8876):
    root=Path('output/demo-beta' if web else 'output/demo-data').resolve()
    address='perez.123456@alu.uns.edu.ar' if web else 'alumno@alu.uns.edu.ar'
    cfg={**DEFAULT,'address':address,'display_name':'Estudiante de prueba','pop_user':address,'smtp_user':address}
    Store(root).save_config(cfg)
    if web:write_allowlist(root,['gomez.234567@alu.uns.edu.ar'])
    app=create_app(root,start_worker=False,vault=MemoryVault(),web=WebSettings(f'http://127.0.0.1:{port}') if web else None)
    store=app.state.store
    if web:app.state.auth.probe=lambda protocol,cfg,password:(password=='demo-correo','')
    message=EmailMessage(policy=policy.SMTP)
    message['From']='Cátedra de Física <fisica@example.test>'
    message['To']='alumno@alu.uns.edu.ar'
    message['Cc']='Compañero <companero@example.test>'
    message['Subject']='Información sobre la próxima evaluación'
    message['Date']='Thu, 29 Oct 2026 11:00:00 -0300'
    message['Message-ID']='<ficticio@example.test>'
    message.set_content('Hola:\n\nLa inscripción a la próxima evaluación está abierta.\nEste es un mensaje ficticio para probar la aplicación.\n\nSaludos,\nCátedra de Física')
    message.add_alternative('<p>Hola, <strong>inscripción abierta</strong>.</p><script>alert(1)</script><img src="https://tracking.invalid/pixel">',subtype='html')
    message.add_attachment('Programa de ejemplo: mecánica y termodinámica.'.encode(),maintype='application',subtype='octet-stream',filename='programa.txt')
    raw=message.as_bytes()
    class POP:
        def __init__(self,payload=raw):self.payload=payload
        def uidl(self):return b'+OK',[b'1 demo-uidl'],0
        def retr(self,n):return b'+OK',self.payload.split(b'\r\n')[:-1],len(self.payload)
        def close(self):pass
    class SMTP:
        def mail(self,a):return 250,b'OK'
        def rcpt(self,a):return 250,b'OK'
        def data(self,raw):return 250,b'SIMULATED'
        def close(self):pass
    app.state.service.pop=lambda c:POP()
    app.state.service.smtp=lambda c:SMTP()
    def guest_service(store,vault):
        service=Service(store,vault)
        other=BytesParser(policy=policy.default).parsebytes(raw)
        other.replace_header('To',store.config()['address'])
        other.replace_header('Subject','Mensaje ficticio del buzón invitado')
        payload=other.as_bytes(policy=policy.SMTP)
        service.pop=lambda c:POP(payload)
        service.smtp=lambda c:SMTP()
        if not store.listing('inbox'):service.sync()
        return service
    if app.state.accounts:app.state.accounts.service_factory=guest_service
    if not store.known('demo') and not store.listing('inbox'):
        app.state.service.sync()
    @app.middleware('http')
    async def demo_banner(request,call_next):
        response=await call_next(request)
        if request.url.path=='/':
            body=b''.join([chunk async for chunk in response.body_iterator])
            body=body.replace('Archivo personal · En esta PC'.encode(),'DEMOSTRACIÓN · Sin correo real'.encode())
            body=body.replace('Beta privada'.encode(),'DEMOSTRACIÓN · Sin correo real'.encode())
            body=body.replace('<h1>Correo UNS</h1>'.encode(),'<h1>Correo UNS · Demo</h1>'.encode())
            from fastapi.responses import Response
            headers=dict(response.headers);headers.pop('content-length',None)
            return Response(body,headers=headers,media_type='text/html')
        return response
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--web',action='store_true');parser.add_argument('--port',type=int,default=8876);args=parser.parse_args()
    print(f'DEMOSTRACIÓN: POP3 y SMTP simulados. http://127.0.0.1:{args.port}',flush=True)
    if args.web:print('Login ficticio: apellido perez · LU 123456 · contraseña demo-correo',flush=True)
    if args.web:print('Invitado ficticio: apellido gomez · LU 234567 · contraseña demo-correo',flush=True)
    uvicorn.run(make_app(args.web,args.port),host='127.0.0.1',port=args.port,access_log=False,log_level='critical',proxy_headers=False)
