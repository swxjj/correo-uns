from email.message import EmailMessage
from email import policy
import pytest
from correo.store import Store, DEFAULT
from correo.service import Service


class MemorySecrets:
    def __init__(self):
        self.values = {}
    def get(self,key): return self.values.get(key)
    def put(self,key,password,persist=False): self.values[key]=password; return False
    def forget(self,key): self.values.pop(key,None)


@pytest.fixture
def vault(): return MemorySecrets()


@pytest.fixture
def store(tmp_path):
    s=Store(tmp_path/'data')
    s.save_config({**DEFAULT,'address':'alumno@alu.uns.edu.ar','display_name':'Álvaro Pérez','pop_user':'alumno@alu.uns.edu.ar','smtp_user':'alumno@alu.uns.edu.ar'})
    return s


@pytest.fixture
def service(store,vault): return Service(store,vault)


@pytest.fixture
def sample():
    m=EmailMessage(policy=policy.SMTP)
    m['From']='Cátedra de Física <fisica@example.test>'
    m['To']='alumno@alu.uns.edu.ar, Compañero <companero@example.test>'
    m['Cc']='docente@example.test'
    m['Subject']='Información: inscripción y evaluación'
    m['Message-ID']='<ejemplo@example.test>'
    m['Date']='Thu, 29 Oct 2026 11:00:00 -0300'
    m.set_content('¡Hola Álvaro! La inscripción está abierta.\nSaludos, Cátedra.')
    m.add_alternative('<html><body onload="alert(1)"><script>alert(2)</script><p>Inscripción</p><img src="https://tracker.example/pixel"><form action="https://bad.example"><input></form><svg onload="alert(3)"></svg><a href="javascript:alert(1)">enlace</a><div style="background:url(https://bad.example)">Texto</div></body></html>',subtype='html')
    m.add_attachment(b'archivo ficticio\x00\xff',maintype='application',subtype='octet-stream',filename='../../evaluación.txt')
    return m.as_bytes()


class FakePOP:
    def __init__(self,messages,uidl=True,fail_at=None):
        self.messages=messages; self.supports_uidl=uidl; self.fail_at=fail_at; self.downloads=0; self.closed=False
    def uidl(self):
        import poplib
        if not self.supports_uidl: raise poplib.error_proto(b'-ERR unsupported')
        return b'+OK',[f'{i} {uid}'.encode() for i,(uid,raw) in enumerate(self.messages,1)],0
    def retr(self,number):
        self.downloads+=1
        if self.fail_at==number: raise ConnectionResetError('simulated')
        return b'+OK',self.messages[number-1][1].split(b'\r\n')[:-1],0
    def close(self): self.closed=True
    def dele(self,*args): raise AssertionError('DELE prohibited')


class FakeSMTP:
    def __init__(self,outcome='accepted'):
        self.outcome=outcome; self.calls=[]; self.data_bytes=None
    def mail(self,sender): self.calls.append(('MAIL',sender)); return 250,b'OK'
    def rcpt(self,recipient): self.calls.append(('RCPT',recipient)); return (550,b'NO') if self.outcome=='rcpt_rejected' else (250,b'OK')
    def data(self,raw):
        import smtplib
        self.calls.append(('DATA',None)); self.data_bytes=raw
        if self.outcome=='uncertain': raise smtplib.SMTPServerDisconnected('simulated')
        if self.outcome=='data_rejected': raise smtplib.SMTPDataError(550,b'rejected')
        return 250,b'OK'
    def close(self): self.calls.append(('CLOSE',None))
