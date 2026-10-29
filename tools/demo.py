"""Demo isolated from real account: python -m tools.demo. All network mail clients replaced."""
from email.message import EmailMessage
from email import policy
from pathlib import Path
import uvicorn
from correo.web import create_app
from correo.store import DEFAULT


class MemoryVault:
    def __init__(self): self.session={}
    def get(self,k): return self.session.get(k)
    def put(self,k,v,persist=False): self.session[k]=v; return False
    def forget(self,k): self.session.pop(k,None)


def make_app():
    app=create_app(Path('output/demo-data').resolve(),start_worker=False,vault=MemoryVault())
    store=app.state.store
    store.save_config({**DEFAULT,'address':'alumno@alu.uns.edu.ar','display_name':'Estudiante de prueba','pop_user':'alumno@alu.uns.edu.ar','smtp_user':'alumno@alu.uns.edu.ar'})
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
        def uidl(self):return b'+OK',[b'1 demo-uidl'],0
        def retr(self,n):return b'+OK',raw.split(b'\r\n')[:-1],len(raw)
        def close(self):pass
    class SMTP:
        def mail(self,a):return 250,b'OK'
        def rcpt(self,a):return 250,b'OK'
        def data(self,raw):return 250,b'SIMULATED'
        def close(self):pass
    app.state.service.pop=lambda c:POP()
    app.state.service.smtp=lambda c:SMTP()
    if not store.known('demo') and not store.listing('inbox'):
        app.state.service.sync()
    @app.middleware('http')
    async def demo_banner(request,call_next):
        response=await call_next(request)
        if request.url.path=='/':
            body=b''.join([chunk async for chunk in response.body_iterator])
            body=body.replace('Archivo personal · En esta PC'.encode(),'DEMOSTRACIÓN · Sin correo real'.encode())
            from fastapi.responses import Response
            headers=dict(response.headers);headers.pop('content-length',None)
            return Response(body,headers=headers,media_type='text/html')
        return response
    return app


if __name__=='__main__':
    print('DEMOSTRACIÓN: todos los accesos POP3 y SMTP están simulados. http://127.0.0.1:8876')
    uvicorn.run(make_app(),host='127.0.0.1',port=8876,access_log=False,log_level='critical',proxy_headers=False)
