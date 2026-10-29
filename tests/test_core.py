import io
import json
import os
import poplib
import smtplib
import ssl
import threading
import zipfile
from unittest.mock import Mock
import pytest
from correo.store import Store,account,secret_key
from correo.mime import content,sanitized_html,build_message,parse,safe_name
from correo.service import UserError,explain
from correo.secrets import Secrets
from conftest import FakePOP,FakeSMTP


def draft(store):
    d={'to':'destino@example.test','cc':'copia@example.test','bcc':'oculto@example.test','subject':'Envío de prueba','body':'Solo ficticio','in_reply_to':'<original@example.test>','references':'<original@example.test>'}
    return store.save(build_message(store.config(),d,[]),folder='drafts',draft=d)


def test_incremental_uidl_no_delete(service,store,sample,monkeypatch):
    first=FakePOP([('a',sample),('b',sample)])
    monkeypatch.setattr(service,'pop',lambda c:first)
    service.sync();service.sync()
    assert first.downloads==2 and first.closed
    assert len(store.listing('inbox'))==2
    assert service.status['error']==''
    assert store.known(account(store.config()))=={'a','b'}


def test_interruption_after_first_message(service,store,sample,monkeypatch):
    client=FakePOP([('a',sample),('b',sample)],fail_at=2)
    monkeypatch.setattr(service,'pop',lambda c:client)
    service.sync()
    assert len(store.listing('inbox'))==1 and service.status['error']
    client.fail_at=None
    service.sync()
    assert len(store.listing('inbox'))==2 and client.downloads==3


def test_crash_between_sidecar_and_index(service,store,sample,monkeypatch):
    client=FakePOP([('persistido',sample)])
    monkeypatch.setattr(service,'pop',lambda c:client)
    original=store.index
    monkeypatch.setattr(store,'index',Mock(side_effect=OSError('disk interrupted')))
    service.sync()
    assert store.known(account(store.config()))==set()
    monkeypatch.setattr(store,'index',original)
    recovered=Store(store.root)
    assert len(recovered.listing('inbox'))==1
    service.store=recovered
    service.sync()
    assert client.downloads==1


def test_crash_before_commit_marker(store,sample,monkeypatch):
    import correo.store as mod
    original=mod.atomic
    def interrupted(path,data):
        if str(path).endswith('.json'): raise OSError('simulated')
        original(path,data)
    monkeypatch.setattr(mod,'atomic',interrupted)
    with pytest.raises(OSError):store.save(sample,id='a'*32,uidl='a',account='acct')
    assert not store.known('acct')
    monkeypatch.setattr(mod,'atomic',original)
    recovered=Store(store.root)
    assert not recovered.listing('inbox')
    recovered.save(sample,id='a'*32,uidl='a',account='acct')
    assert len(recovered.listing('inbox'))==1


def test_no_uidl(service,sample,monkeypatch):
    client=FakePOP([('a',sample)],uidl=False)
    monkeypatch.setattr(service,'pop',lambda c:client)
    service.sync()
    assert service.status['uidl'] is False and 'UIDL' in service.status['error']
    assert client.downloads==0


def test_lock_prevents_concurrent_downloads(service):
    service.operation.acquire()
    try:
        with pytest.raises(UserError):service.sync()
        with pytest.raises(UserError):service.start_sync()
    finally:service.operation.release()


def test_account_scoped_uidl(store,sample):
    store.save(sample,uidl='1',account='first')
    store.save(sample,uidl='1',account='second')
    assert len(store.listing('inbox'))==2


def test_mime_international_attachments(sample):
    msg,plain,html,atts=content(sample)
    assert str(msg['Subject'])=='Información: inscripción y evaluación'
    assert 'Álvaro' in plain and len(atts)==1
    assert '/' not in atts[0]['name'] and '\\' not in atts[0]['name']
    assert atts[0]['part'].get_payload(decode=True)==b'archivo ficticio\x00\xff'


def test_html_sanitized(sample):
    result=sanitized_html(content(sample)[2])
    for bad in ('<script','<img','<form','<input','<svg','href=','style=','onload=','https://'):
        assert bad not in result


@pytest.mark.parametrize('name',['../../x.exe','C:\\Windows\\x.txt','CON','NUL.txt','..','a\x00b','a:stream'])
def test_safe_attachment_names(name):
    result=safe_name(name)
    assert result and '/' not in result and '\\' not in result and ':' not in result
    assert result.split('.')[0].upper() not in ('CON','NUL')


def test_search_and_local_flags(store,sample):
    saved=store.save(sample)
    assert len(store.listing('inbox','ÁLVARO'))==1
    assert len(store.listing('inbox','INSCRIPCIÓN'))==1
    store.update(saved['id'],unread=0,starred=1,archived=1)
    assert not store.listing('inbox')
    assert store.listing('archive')[0]['starred']==1
    # Delete only the derived index, then reconstruct all local state.
    (store.root/'index.sqlite3').unlink()
    rebuilt=Store(store.root)
    assert rebuilt.listing('archive')[0]['unread']==0


def test_send_bcc_response_headers(service,store,monkeypatch):
    d=draft(store);smtp=FakeSMTP()
    monkeypatch.setattr(service,'smtp',lambda c:smtp)
    result=service.send(d['id'])
    assert result['state']=='accepted'
    sent=parse(smtp.data_bytes)
    assert 'Bcc' not in sent and b'oculto@example.test' not in smtp.data_bytes
    assert ('RCPT','oculto@example.test') in smtp.calls
    assert sent['In-Reply-To']=='<original@example.test>'
    assert store.listing('sent')[0]['state']=='accepted'
    assert store.info(result['id'])['bcc']=='oculto@example.test'
    with pytest.raises(UserError):service.send(d['id'])


def test_uncertain_never_resends(service,store,monkeypatch):
    d=draft(store);smtp=FakeSMTP('uncertain')
    monkeypatch.setattr(service,'smtp',lambda c:smtp)
    result=service.send(d['id'])
    assert result['state']=='uncertain'
    assert store.listing('outbox')[0]['state']=='uncertain'
    with pytest.raises(UserError):service.send(d['id'])
    assert sum(c[0]=='DATA' for c in smtp.calls)==1


@pytest.mark.parametrize('outcome',['data_rejected','rcpt_rejected'])
def test_definite_rejection(service,store,monkeypatch,outcome):
    d=draft(store);smtp=FakeSMTP(outcome)
    monkeypatch.setattr(service,'smtp',lambda c:smtp)
    with pytest.raises(UserError):service.send(d['id'])
    assert store.listing('outbox')[0]['state']=='failed'
    assert not store.listing('sent')
    if outcome=='rcpt_rejected':assert smtp.data_bytes is None


def test_crash_during_send_reconciled(store,sample):
    store.save(sample,folder='outbox',state='sending')
    recovered=Store(store.root)
    assert recovered.listing('outbox')[0]['state']=='uncertain'


def test_auth_failure_no_secret_echo(service,monkeypatch):
    monkeypatch.setattr(service,'pop',Mock(side_effect=poplib.error_proto(b'-ERR private-password')))
    service.sync()
    assert 'private-password' not in service.status['error']
    assert 'autenticación' in service.status['error']


def test_tls_mandatory_no_fallback(service,store,vault,monkeypatch):
    cfg=store.config();vault.put(secret_key(cfg,'pop'),'sensitive')
    client=Mock();client.stls.side_effect=ssl.SSLCertVerificationError('bad cert')
    factory=Mock(return_value=client)
    monkeypatch.setattr(poplib,'POP3',factory)
    with pytest.raises(ssl.SSLCertVerificationError):service.pop(cfg)
    client.user.assert_not_called();client.pass_.assert_not_called();client.close.assert_called_once()
    context=client.stls.call_args.kwargs['context']
    assert context.check_hostname and context.verify_mode==ssl.CERT_REQUIRED
    assert factory.call_count==1


def test_smtp_diagnostic_never_sends(service,monkeypatch):
    smtp=FakeSMTP();monkeypatch.setattr(service,'smtp',lambda c:smtp)
    assert 'No se envió' in service.diagnostic('smtp')
    assert smtp.calls==[('CLOSE',None)]


def test_backup_restore_consistent_preserves_current(store,sample):
    original=store.save(sample)
    store.update(original['id'],starred=1)
    backup=store.backup()
    store.save(sample)
    preserved=store.restore(backup)
    assert os.path.isdir(preserved)
    assert len(Store(preserved).listing('inbox'))==2
    assert len(store.listing('inbox'))==1 and store.listing('inbox')[0]['starred']==1
    assert store.raw(original['id'])==sample
    assert not store.config()['auto']


def test_restore_traversal_rejected_preserves_current(store,sample):
    store.save(sample)
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as z:
        z.writestr('../escape','bad')
    with pytest.raises(ValueError):store.restore(data.getvalue())
    assert len(store.listing('inbox'))==1


def test_corrupt_backup_preserves_current(store,sample):
    store.save(sample)
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as z:
        z.writestr('manifest.json','{"format":"correo-uns-v1"}')
        z.writestr('messages/'+'a'*32+'.json','{"id":"'+'a'*32+'","folder":"inbox"}')
    with pytest.raises(FileNotFoundError):store.restore(data.getvalue())
    assert len(store.listing('inbox'))==1


def test_session_fallback_no_files(tmp_path):
    vault=Secrets();vault.available=False
    assert not vault.put('key','secret-session-value',persist=True)
    assert vault.get('key')=='secret-session-value'
    assert not list(tmp_path.iterdir())


def test_windows_credential_roundtrip():
    import uuid
    if os.name!='nt':pytest.skip('Windows only')
    vault=Secrets();key='test-'+uuid.uuid4().hex
    try:
        saved=vault.put(key,'clave-ficticia-á',persist=True)
        if not saved:pytest.skip('Credential Manager unavailable: session fallback verified separately')
        vault.session.clear()
        assert vault.get(key)=='clave-ficticia-á'
    finally:vault.forget(key)


def test_forwarded_message_attachment_not_merged_into_body():
    from email.message import EmailMessage
    inner=EmailMessage();inner['Subject']='Adjunto internacional: física';inner.set_content('Cuerpo del adjunto')
    outer=EmailMessage();outer.set_content('Solo cuerpo principal');outer.add_attachment(inner,filename='correo.eml')
    msg,plain,html,atts=content(outer.as_bytes())
    assert 'Cuerpo del adjunto' not in plain
    assert len(atts)==1 and atts[0]['size']>0
    assert str(parse(atts[0]['data'])['Subject'])=='Adjunto internacional: física'


def test_last_sync_persists(service,store,sample,vault,monkeypatch):
    from correo.service import Service
    monkeypatch.setattr(service,'pop',lambda c:FakePOP([('a',sample)]))
    service.sync()
    restarted=Service(Store(store.root),vault)
    assert restarted.status['last_update']==service.status['last_update']


def test_automatic_sync_and_backoff(service,store,sample,monkeypatch):
    import time
    store.save_config({**store.config(),'auto':True,'interval':1})
    called=threading.Event()
    def factory(cfg):
        called.set()
        return FakePOP([('a',sample)])
    monkeypatch.setattr(service,'pop',factory)
    service.start();service.next_due=0
    try:
        assert called.wait(4)
        deadline=time.monotonic()+3
        while service.status['running'] and time.monotonic()<deadline:time.sleep(.01)
        assert len(store.listing('inbox'))==1
        monkeypatch.setattr(service,'pop',Mock(side_effect=OSError('offline')))
        service.sync()
        assert service.next_due-time.monotonic()>110
    finally:
        service.stop.set();service.thread.join(timeout=3)


def test_cleanup_does_not_mask_tls_error_or_hold_lock(service,monkeypatch):
    client=Mock();client.stls.side_effect=ssl.SSLCertVerificationError('invalid');client.close.side_effect=OSError('invalid handle')
    monkeypatch.setattr(poplib,'POP3',lambda *a,**k:client)
    service.sync()
    assert 'certificado' in service.status['error']
    assert service.operation.acquire(blocking=False)
    service.operation.release()


def test_backup_excludes_uncommitted_original(store,sample):
    store.save(sample)
    (store.root/'messages'/('b'*32+'.eml')).write_bytes(sample)
    backup=store.backup()
    store.restore(backup)
    assert len(store.listing('inbox'))==1
    assert not (store.root/'messages'/('b'*32+'.eml')).exists()
