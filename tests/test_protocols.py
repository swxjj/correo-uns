"""Real sockets and TLS, confined to loopback; no university servers or real mail."""
import socketserver
import ssl
import threading
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
import pytest
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from correo.store import secret_key
from correo.service import UserError
from correo.mime import build_message


@pytest.fixture(scope='module')
def tls_files(tmp_path_factory):
    folder=tmp_path_factory.mktemp('tls')
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(days=1)).not_valid_after(datetime.now(timezone.utc)+timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),critical=False).sign(key,hashes.SHA256()))
    certfile=folder/'cert.pem';keyfile=folder/'key.pem'
    certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    return certfile,keyfile


@contextmanager
def server(protocol,tls_files,sample,mode='starttls',auth=True,uidl=True,uncertain=False):
    state={'commands':[],'data':[]}
    ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain(*map(str,tls_files))
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            sock=self.request
            def send(value): sock.sendall(value.encode()+b'\r\n')
            def read():
                result=b''
                while not result.endswith(b'\r\n'):
                    chunk=sock.recv(1)
                    if not chunk:return b''
                    result+=chunk
                return result[:-2]
            try:
                if mode=='ssl':sock=ctx.wrap_socket(sock,server_side=True)
                send('+OK mock POP3' if protocol=='pop' else '220 localhost mock SMTP')
                encrypted=mode=='ssl'
                while True:
                    line=read()
                    if not line:return
                    command=line.decode('ascii','replace').split(' ',1)[0].upper()
                    state['commands'].append(command)
                    if command in ('STLS','STARTTLS'):
                        send('+OK begin TLS' if protocol=='pop' else '220 begin TLS')
                        sock=ctx.wrap_socket(sock,server_side=True);encrypted=True
                    elif command in ('EHLO','HELO'):
                        send('250-localhost\r\n250-STARTTLS\r\n250 AUTH PLAIN')
                    elif command=='CAPA':send('+OK capabilities\r\nSTLS\r\nUSER\r\nUIDL\r\n.')
                    elif command=='USER':
                        assert encrypted
                        send('+OK user')
                    elif command=='PASS':send('+OK welcome' if auth else '-ERR authentication rejected')
                    elif command=='AUTH':
                        assert encrypted
                        send('235 authenticated' if auth else '535 authentication rejected')
                    elif command=='UIDL':send('+OK list\r\n1 stable-1\r\n.' if uidl else '-ERR unsupported')
                    elif command=='RETR':
                        sock.sendall(b'+OK message\r\n'+sample.replace(b'\r\n.',b'\r\n..')+b'.\r\n')
                    elif command in ('MAIL','RCPT'):send('250 accepted')
                    elif command=='DATA':
                        send('354 continue')
                        lines=[]
                        while True:
                            item=read()
                            if item==b'.':break
                            if item.startswith(b'..'):item=item[1:]
                            lines.append(item)
                        state['data'].append(b'\r\n'.join(lines)+b'\r\n')
                        if uncertain:return
                        send('250 queued')
                    elif command=='QUIT':send('+OK bye' if protocol=='pop' else '221 bye');return
                    else:send('-ERR command' if protocol=='pop' else '500 command')
            except (ssl.SSLError,ConnectionError,OSError):
                pass
            finally:sock.close()
    class TCP(socketserver.ThreadingTCPServer):
        allow_reuse_address=True
        daemon_threads=True
    srv=TCP(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=srv.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
    try:yield srv.server_address[1],state
    finally:srv.shutdown();srv.server_close();thread.join(timeout=2)


def configure(service,vault,protocol,port,mode='starttls',host='localhost'):
    cfg=service.store.config()
    cfg.update({protocol+'_host':host,protocol+'_port':port,protocol+'_tls':mode})
    service.store.save_config(cfg)
    vault.put(secret_key(cfg,protocol),'ficticia')
    return cfg


def trust(monkeypatch,tls_files):
    original=ssl.create_default_context
    monkeypatch.setattr('correo.service.tls_context',lambda:original(cafile=str(tls_files[0])))


@pytest.mark.parametrize('mode',['starttls','ssl'])
def test_pop_real_tls_incremental(service,vault,tls_files,sample,monkeypatch,mode):
    trust(monkeypatch,tls_files)
    with server('pop',tls_files,sample,mode=mode) as (port,state):
        configure(service,vault,'pop',port,mode)
        service.sync();service.sync()
        assert not service.status['error'],service.status['error']
        assert len(service.store.listing('inbox'))==1
        assert state['commands'].count('RETR')==1
        assert 'DELE' not in state['commands']
        if mode=='starttls':assert state['commands'].index('STLS')<state['commands'].index('USER')


@pytest.mark.parametrize('mode',['starttls','ssl'])
def test_smtp_real_tls_diagnostic_and_send(service,vault,tls_files,sample,monkeypatch,mode):
    trust(monkeypatch,tls_files)
    with server('smtp',tls_files,sample,mode=mode) as (port,state):
        cfg=configure(service,vault,'smtp',port,mode)
        assert 'No se envió' in service.diagnostic('smtp')
        assert not state['data']
        d={'to':'to@example.test','bcc':'hidden@example.test','body':'Ficticio con tildes: evaluación'}
        saved=service.store.save(build_message(cfg,d,[]),folder='drafts',draft=d)
        result=service.send(saved['id'])
        assert result['state']=='accepted' and len(state['data'])==1
        assert b'Bcc:' not in state['data'][0] and b'hidden@example.test' not in state['data'][0]


def test_certificate_rejected_before_credentials(service,vault,tls_files,sample):
    with server('pop',tls_files,sample) as (port,state):
        configure(service,vault,'pop',port)
        service.sync()
        assert 'certificado' in service.status['error']
        assert 'USER' not in state['commands'] and 'PASS' not in state['commands']


def test_hostname_rejected(service,vault,tls_files,sample,monkeypatch):
    trust(monkeypatch,tls_files)
    with server('pop',tls_files,sample) as (port,state):
        configure(service,vault,'pop',port,host='127.0.0.1')
        service.sync()
        assert 'certificado' in service.status['error']
        assert 'USER' not in state['commands']


def test_auth_failure_real_server(service,vault,tls_files,sample,monkeypatch):
    trust(monkeypatch,tls_files)
    with server('smtp',tls_files,sample,auth=False) as (port,state):
        configure(service,vault,'smtp',port)
        import smtplib
        with pytest.raises(UserError,match='SMTP 535'):service.diagnostic('smtp')
        assert not state['data']


def test_uncertain_real_socket_disconnect(service,vault,tls_files,sample,monkeypatch):
    trust(monkeypatch,tls_files)
    with server('smtp',tls_files,sample,uncertain=True) as (port,state):
        cfg=configure(service,vault,'smtp',port)
        d={'to':'to@example.test','body':'Simulación'}
        saved=service.store.save(build_message(cfg,d,[]),folder='drafts',draft=d)
        result=service.send(saved['id'])
        assert result['state']=='uncertain' and len(state['data'])==1
        with pytest.raises(UserError):service.send(saved['id'])
        assert len(state['data'])==1
