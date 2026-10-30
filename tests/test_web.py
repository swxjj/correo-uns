import io
import json
import zipfile
from fastapi.testclient import TestClient
import pytest
from correo.web import create_app
from correo.store import DEFAULT
from conftest import FakePOP,FakeSMTP


@pytest.fixture
def web(tmp_path,vault):
    app=create_app(tmp_path/'web',start_worker=False,vault=vault)
    with TestClient(app,base_url='http://127.0.0.1:8765',headers={'X-CSRF-Token':app.state.token},raise_server_exceptions=False) as client:
        yield app,client


def test_origin_csrf_host_guards(web):
    app,c=web
    assert c.get('/').status_code==200
    assert c.post('/api/sync',headers={'Origin':'https://evil.example'}).status_code==403
    assert c.post('/api/sync',headers={'X-CSRF-Token':'wrong'}).status_code==403
    assert c.get('/api/config',headers={'Host':'evil.example'}).status_code==403
    assert c.get('/',headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
    assert c.get('/',headers={'Origin':'null'}).status_code==403
    assert c.options('/api/sync',headers={'Origin':'https://evil.example'}).status_code==403
    assert c.get('/api/config').headers['cache-control']=='no-store'
    assert c.get('/').headers['x-frame-options']=='DENY'


def test_configuration_tls_and_no_uidl_auto_guard(web,monkeypatch,sample):
    app,c=web
    cfg={**DEFAULT,'address':'alumno@alu.uns.edu.ar','pop_user':'alumno@alu.uns.edu.ar','smtp_user':'alumno@alu.uns.edu.ar'}
    assert c.put('/api/config',json={**cfg,'pop_tls':'none'}).status_code==422
    assert c.put('/api/config',json=cfg).status_code==200
    assert c.put('/api/config',json={**cfg,'auto':True}).status_code==400
    monkeypatch.setattr(app.state.service,'pop',lambda cfg:FakePOP([('a',sample)]))
    assert c.post('/api/test/pop').status_code==200
    assert c.put('/api/config',json={**cfg,'auto':True}).status_code==200


def test_password_not_in_configuration_backup_or_validation(web):
    app,c=web
    password='unique-secret-value-123'
    response=c.put('/api/credentials/pop',json={'password':password,'persist':False})
    assert response.status_code==200
    assert password not in response.text
    assert password not in c.get('/api/config').text
    assert password not in c.put('/api/credentials/pop',json={'password':[password]}).text
    data=c.post('/api/backup').content
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert all(password.encode() not in z.read(name) for name in z.namelist())
    assert c.delete('/api/credentials/pop').status_code==200
    assert not c.get('/api/config').json()['credentials']['pop']


def test_full_http_workflow(web,sample,monkeypatch):
    app,c=web
    cfg={**DEFAULT,'address':'alumno@alu.uns.edu.ar','pop_user':'alumno@alu.uns.edu.ar','smtp_user':'alumno@alu.uns.edu.ar'}
    assert c.put('/api/config',json=cfg).status_code==200
    monkeypatch.setattr(app.state.service,'pop',lambda cfg:FakePOP([('ficticio',sample)]))
    app.state.service.sync()
    rows=c.get('/api/messages').json();assert len(rows)==1
    ident=rows[0]['id'];detail=c.get('/api/messages/'+ident).json()
    assert 'Álvaro' in detail['body'] and detail['has_html']
    html=c.get('/api/messages/'+ident+'/html')
    assert '<script' not in html.text and 'img-src' in html.text
    att=c.get('/api/messages/'+ident+'/attachment/0')
    assert att.content==b'archivo ficticio\x00\xff' and 'attachment;' in att.headers['content-disposition']
    assert c.patch('/api/messages/'+ident,json={'unread':False,'starred':True}).status_code==200
    reply=c.post('/api/messages/'+ident+'/reply?all=true').json()
    assert reply['draft']['in_reply_to']=='<ejemplo@example.test>'
    assert 'alumno@alu.uns.edu.ar' not in reply['draft']['cc']
    assert 'docente@example.test' in reply['draft']['cc']
    d=reply['draft'];d['to']='destino@example.test';d['cc']='';d['bcc']='privado@example.test'
    assert c.put('/api/drafts/'+reply['id'],json=d).status_code==200
    assert c.post('/api/drafts/'+reply['id']+'/attachments',files=[('files',('..\\secreto.txt',b'example','text/plain'))]).status_code==200
    assert len(c.get('/api/messages/'+reply['id']).json()['attachments'])==1
    smtp=FakeSMTP();monkeypatch.setattr(app.state.service,'smtp',lambda cfg:smtp)
    result=c.post('/api/drafts/'+reply['id']+'/send')
    assert result.status_code==200 and result.json()['state']=='accepted'
    assert b'Bcc:' not in smtp.data_bytes
    assert len(c.get('/api/messages?folder=sent').json())==1
    assert c.post('/api/drafts/'+reply['id']+'/send').status_code==400
    assert c.put('/api/drafts/'+reply['id'],json=d).status_code==400
    backup=c.post('/api/backup').content
    app.state.store.save(sample)
    restored=c.post('/api/restore',files={'file':('copia.zip',backup,'application/zip')})
    assert restored.status_code==200,restored.text
    assert 'protegidos' in restored.json()['message']
    assert len(c.get('/api/messages').json())==1
    assert not any(c.get('/api/config').json()['credentials'].values())


def test_header_injection_blocked(web):
    app,c=web
    assert c.post('/api/drafts',json={'subject':'hola\r\nBcc: evil@example.test'}).status_code==422


def test_attachment_remove_and_original(web):
    app,c=web
    d=c.post('/api/drafts',json={'subject':'Borrador'}).json()
    ident=d['id']
    assert c.post('/api/drafts/'+ident+'/attachments',files={'files':('f.txt',b'x')}).status_code==200
    assert c.delete('/api/drafts/'+ident+'/attachments/0').status_code==200
    assert c.get('/api/messages/'+ident).json()['attachments']==[]
    assert c.get('/api/messages/'+ident+'/eml').headers['content-type']=='application/octet-stream'


def test_desktop_exit_requires_idle_operation_and_csrf(web):
    import threading
    app,c=web
    assert c.post('/api/quit').status_code==400
    app.state.exit_requested=threading.Event()
    assert 'Salir de Correo UNS' in c.get('/').text
    assert c.post('/api/quit',headers={'X-CSRF-Token':'wrong'}).status_code==403
    app.state.service.operation.acquire()
    assert c.post('/api/quit').status_code==400
    assert not app.state.exit_requested.is_set()
    app.state.service.operation.release()
    assert c.post('/api/quit').status_code==200
    assert app.state.exit_requested.is_set()
    assert app.state.service.stop.is_set()
    assert app.state.service.operation.locked()
