"""Two synthetic accounts exercise every private route and worker boundary."""
from concurrent.futures import ThreadPoolExecutor
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
import io
import json
import re
import threading
import zipfile
from fastapi.testclient import TestClient
import pytest
from correo.accounts import read_allowlist,write_allowlist,users_root
from correo.accounts import lock_archive
from correo.auth import WebSettings
from correo.service import UserError
from correo.store import secret_key
from correo.web import create_app
from conftest import FakePOP,FakeSMTP

ORIGIN='https://beta.example.test'
OWNER='perez.123456@alu.uns.edu.ar'
GUEST='gomez.234567@alu.uns.edu.ar'
PASSWORDS={OWNER:'owner-ficticio',GUEST:'guest-ficticio'}


def csrf(client):
    return re.search(r'name="csrf-token" content="([^"]+)"',client.get('/').text).group(1)


def login(client,guest=False,password=None):
    address=GUEST if guest else OWNER
    return client.post('/api/auth/login',json={'surname':'gomez' if guest else 'perez','lu':'234567' if guest else '123456','password':password or PASSWORDS[address]},headers={'Origin':ORIGIN,'X-CSRF-Token':csrf(client)})


def headers(client):return {'Origin':ORIGIN,'X-CSRF-Token':csrf(client)}


def message(subject,body='Texto ficticio privado'):
    m=EmailMessage(policy=policy.SMTP);m['From']='fixture@example.test';m['To']='fixture@example.test';m['Subject']=subject;m.set_content(body)
    m.add_alternative('<p>'+body+'</p>',subtype='html')
    m.add_attachment(body.encode(),maintype='application',subtype='octet-stream',filename='fixture.txt')
    return m.as_bytes()


@pytest.fixture
def multi(store,vault):
    store.save_config({**store.config(),'address':OWNER,'pop_user':OWNER,'smtp_user':OWNER})
    write_allowlist(store.root,[GUEST])
    app=create_app(store.root,start_worker=False,vault=vault,web=WebSettings(ORIGIN))
    app.state.auth.probe=lambda p,c,password:(password==PASSWORDS[c['address']],'')
    with TestClient(app,base_url=ORIGIN,raise_server_exceptions=False) as owner, TestClient(app,base_url=ORIGIN,raise_server_exceptions=False) as guest:
        yield app,owner,guest


def signed_in(multi):
    app,owner,guest=multi
    assert login(owner).status_code==200
    assert login(guest,True).status_code==200
    return app,owner,guest,headers(owner),headers(guest)


def test_no_guest_archive_until_successful_pop_auth(multi):
    app,owner,guest=multi;root=app.state.accounts.archive_root(GUEST)
    assert not root.exists()
    assert login(guest,True,password='incorrecta').status_code==401
    assert not root.exists() and app.state.accounts.existing(GUEST) is None
    assert login(guest,True).status_code==200
    assert root.is_dir() and root.parent.parent==users_root(app.state.store.root)


def test_config_identity_and_passwords_are_separate(multi):
    app,owner,guest,oh,gh=signed_in(multi)
    for client,h,address in ((owner,oh,OWNER),(guest,gh,GUEST)):
        cfg=client.get('/api/config',headers=h).json()['config']
        assert cfg['address']==cfg['pop_user']==cfg['smtp_user']==address
        assert client.get('/api/auth/me',headers=h).json()['address']==address
        context=app.state.accounts.existing(address)
        assert context.vault.get(secret_key(cfg,'pop'))==PASSWORDS[address]
        assert context.vault.get(secret_key(cfg,'smtp'))==PASSWORDS[address]
    assert app.state.accounts.existing(OWNER).store.root!=app.state.accounts.existing(GUEST).store.root


def test_list_and_search_never_include_other_account(multi):
    app,owner,guest,oh,gh=signed_in(multi)
    app.state.store.save(message('OwnerOnlyUnique'))
    app.state.accounts.existing(GUEST).store.save(message('GuestOnlyUnique'))
    assert [m['subject'] for m in owner.get('/api/messages',headers=oh).json()]==['OwnerOnlyUnique']
    assert [m['subject'] for m in guest.get('/api/messages',headers=gh).json()]==['GuestOnlyUnique']
    assert guest.get('/api/messages?q=OwnerOnlyUnique',headers=gh).json()==[]
    assert owner.get('/api/messages?q=GuestOnlyUnique',headers=oh).json()==[]


@pytest.mark.parametrize('route',['','/eml','/html','/attachment/0'])
def test_foreign_message_identifiers_are_inaccessible_in_both_directions(multi,route):
    app,owner,guest,oh,gh=signed_in(multi)
    own=app.state.store.save(message('owner'))['id']
    other=app.state.accounts.existing(GUEST).store.save(message('guest'))['id']
    assert guest.get('/api/messages/'+own+route,headers=gh).status_code==404
    assert owner.get('/api/messages/'+other+route,headers=oh).status_code==404


def test_foreign_flags_reply_draft_attachments_and_send_are_blocked(multi):
    app,owner,guest,oh,gh=signed_in(multi)
    mail=app.state.store.save(message('owner'))['id']
    draft=owner.post('/api/drafts',json={'subject':'OwnerDraft'},headers=oh).json()['id']
    assert guest.patch('/api/messages/'+mail,json={'unread':False},headers=gh).status_code==404
    assert guest.post('/api/messages/'+mail+'/reply',headers=gh).status_code==404
    assert guest.put('/api/drafts/'+draft,json={'subject':'attack'},headers=gh).status_code==404
    assert guest.post('/api/drafts/'+draft+'/attachments',files={'files':('x.txt',b'x')},headers=gh).status_code==404
    assert guest.delete('/api/drafts/'+draft+'/attachments/0',headers=gh).status_code==404
    assert guest.post('/api/drafts/'+draft+'/send',headers=gh).status_code==400
    assert app.state.store.info(mail)['unread']==1


def test_cannot_select_owner_via_query_header_body_or_csrf(multi):
    app,owner,guest,oh,gh=signed_in(multi)
    app.state.store.save(message('owner'))
    assert guest.get('/api/messages?account='+OWNER,headers={**gh,'X-Account':OWNER}).json()==[]
    assert guest.get('/api/config',headers=oh).status_code==403
    cfg=guest.get('/api/config',headers=gh).json()['config']
    assert guest.put('/api/config',json={**cfg,'address':OWNER,'pop_user':OWNER,'smtp_user':OWNER},headers=gh).status_code==400
    assert owner.get('/api/config',headers=gh).status_code==403


def test_guest_drafts_and_smtp_use_guest_identity_and_only_guest_credentials(multi,monkeypatch):
    app,owner,guest,oh,gh=signed_in(multi)
    context=app.state.accounts.existing(GUEST);smtp=FakeSMTP();captured=[]
    def connect(cfg):
        captured.append((cfg['smtp_user'],context.vault.get(secret_key(cfg,'smtp'))))
        return smtp
    monkeypatch.setattr(context.service,'smtp',connect)
    draft=guest.post('/api/drafts',json={'to':'fixture@example.test','subject':'GuestDraft','body':'Ficticio'},headers=gh).json()['id']
    assert guest.post('/api/drafts/'+draft+'/send',headers=gh).json()['state']=='accepted'
    raw=BytesParser(policy=policy.default).parsebytes(smtp.data_bytes)
    assert str(raw['From'])==GUEST and captured==[(GUEST,PASSWORDS[GUEST])]
    assert owner.get('/api/messages?folder=sent',headers=oh).json()==[]
    assert len(guest.get('/api/messages?folder=sent',headers=gh).json())==1


def test_parallel_downloads_keep_their_store_uidl_and_password(multi,monkeypatch):
    app,owner,guest,oh,gh=signed_in(multi);barrier=threading.Barrier(2)
    for address in (OWNER,GUEST):
        context=app.state.accounts.existing(address)
        def pop(cfg,ctx=context,expected=address):
            assert cfg['address']==expected
            assert ctx.vault.get(secret_key(cfg,'pop'))==PASSWORDS[expected]
            barrier.wait(timeout=3)
            return FakePOP([('same-uidl',message('OwnerOnly' if expected==OWNER else 'GuestOnly'))])
        monkeypatch.setattr(context.service,'pop',pop)
    with ThreadPoolExecutor(2) as pool:list(pool.map(lambda a:app.state.accounts.existing(a).service.sync(),(OWNER,GUEST)))
    assert [x['subject'] for x in owner.get('/api/messages',headers=oh).json()]==['OwnerOnly']
    assert [x['subject'] for x in guest.get('/api/messages',headers=gh).json()]==['GuestOnly']
    assert app.state.service.status['downloaded']==1


def test_concurrent_routes_keep_request_context(multi):
    app,owner,guest,oh,gh=signed_in(multi)
    def request_many(args):
        client,h,address=args
        for i in range(10):
            assert client.get('/api/config',headers=h).json()['config']['address']==address
            draft=client.post('/api/drafts',json={'subject':address+' '+str(i)},headers=h)
            assert draft.status_code==200
        return True
    with ThreadPoolExecutor(2) as pool:
        assert all(pool.map(request_many,[(owner,oh,OWNER),(guest,gh,GUEST)]))
    assert all(x['subject'].startswith(OWNER) for x in owner.get('/api/messages?folder=drafts',headers=oh).json())
    assert all(x['subject'].startswith(GUEST) for x in guest.get('/api/messages?folder=drafts',headers=gh).json())


def test_backup_contains_only_current_archive_and_owner_restore_keeps_guest(multi):
    app,owner,guest,oh,gh=signed_in(multi)
    app.state.store.save(message('OwnerArchiveSecret'))
    other=app.state.accounts.existing(GUEST);other.store.save(message('GuestArchiveSecret'))
    for client,h,own,foreign in ((owner,oh,'OwnerArchiveSecret','GuestArchiveSecret'),(guest,gh,'GuestArchiveSecret','OwnerArchiveSecret')):
        response=client.post('/api/backup',headers=h);assert response.status_code==200
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            payload=b''.join(z.read(name) for name in z.namelist())
            assert own.encode() in payload and foreign.encode() not in payload
            assert 'access.json' not in z.namelist()
    backup=app.state.store.backup();app.state.store.restore(backup)
    assert read_allowlist(app.state.store.root)==[GUEST]
    assert other.store.listing('inbox')[0]['subject']=='GuestArchiveSecret'


def test_logout_revokes_only_its_account_and_password(multi):
    app,owner,guest,oh,gh=signed_in(multi)
    assert guest.post('/api/auth/logout',headers=gh).status_code==200
    assert not app.state.accounts.existing(GUEST).vault.session
    assert app.state.vault.session
    assert owner.get('/api/config',headers=oh).status_code==200
    assert guest.get('/api/config',headers=gh).status_code==401


def test_revocation_ends_guest_sessions_preserving_archive_and_owner(multi):
    app,owner,guest,oh,gh=signed_in(multi)
    context=app.state.accounts.existing(GUEST);context.store.save(message('GuestPreserved'))
    write_allowlist(app.state.store.root,[])
    assert guest.get('/api/messages',headers=gh).status_code==401
    assert not context.active and not context.vault.session
    assert context.store.listing('inbox')[0]['subject']=='GuestPreserved'
    assert owner.get('/api/config',headers=oh).status_code==200


def test_guest_failed_attempts_do_not_lock_owner_login(multi):
    app,owner,guest=multi
    for _ in range(5):assert login(guest,True,password='incorrecta').status_code==401
    assert login(guest,True,password='incorrecta').status_code==429
    assert login(owner).status_code==200


def test_logins_for_different_accounts_can_validate_concurrently(multi):
    app,owner,guest=multi;barrier=threading.Barrier(4)
    def probe(p,c,password):
        barrier.wait(timeout=3)
        return password==PASSWORDS[c['address']],''
    app.state.auth.probe=probe
    with ThreadPoolExecutor(2) as pool:
        a=pool.submit(login,owner);b=pool.submit(login,guest,True)
        assert a.result().status_code==200 and b.result().status_code==200


def test_guest_expiry_clears_only_guest_credentials(multi):
    app,owner,guest=multi;now=[100.0];app.state.auth.clock=lambda:now[0]
    app,owner,guest,oh,gh=signed_in(multi)
    now[0]+=30*60-1
    assert owner.get('/api/config',headers=oh).status_code==200
    now[0]+=2
    assert guest.get('/api/config',headers=gh).status_code==401
    assert not app.state.accounts.existing(GUEST).vault.session
    assert owner.get('/api/config',headers=oh).status_code==200
    assert app.state.vault.session


def test_guest_archive_is_locked_against_another_process(multi):
    app,owner,guest,oh,gh=signed_in(multi)
    with pytest.raises(UserError,match='otra instancia'):
        lock_archive(app.state.accounts.archive_root(GUEST))


def test_concurrent_attachment_uploads_keep_their_account(multi):
    app,owner,guest,oh,gh=signed_in(multi)
    od=owner.post('/api/drafts',json={'subject':'own'},headers=oh).json()['id']
    gd=guest.post('/api/drafts',json={'subject':'other'},headers=gh).json()['id']
    def upload(args):
        client,h,ident,payload=args
        return client.post('/api/drafts/'+ident+'/attachments',files={'files':('test.txt',payload)},headers=h)
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(upload,[(owner,oh,od,b'only-owner'),(guest,gh,gd,b'only-guest')]))
    assert all(r.status_code==200 for r in results)
    assert owner.get('/api/messages/'+od+'/attachment/0',headers=oh).content==b'only-owner'
    assert guest.get('/api/messages/'+gd+'/attachment/0',headers=gh).content==b'only-guest'


def test_guest_archive_survives_restart_without_restoring_password(store,vault):
    store.save_config({**store.config(),'address':OWNER,'pop_user':OWNER,'smtp_user':OWNER})
    write_allowlist(store.root,[GUEST])
    ident=None
    for run in range(2):
        app=create_app(store.root,start_worker=False,vault=vault,web=WebSettings(ORIGIN))
        app.state.auth.probe=lambda *args:(True,'')
        with TestClient(app,base_url=ORIGIN) as guest:
            assert app.state.accounts.existing(GUEST) is None
            assert login(guest,True).status_code==200
            h=headers(guest)
            if run==0:
                ident=app.state.accounts.existing(GUEST).store.save(message('PersistedGuest'))['id']
                assert guest.patch('/api/messages/'+ident,json={'starred':True},headers=h).status_code==200
            else:
                result=guest.get('/api/messages/'+ident,headers=h).json()
                assert result['subject']=='PersistedGuest' and result['info']['starred']==1
            assert app.state.store.listing('inbox')==[]


def test_guest_auto_refresh_pauses_after_logout_and_resumes_after_login(multi,monkeypatch):
    import time
    app,owner,guest,oh,gh=signed_in(multi)
    context=app.state.accounts.existing(GUEST)
    context.store.save_config({**context.store.config(),'auto':True,'interval':1})
    called=threading.Event()
    def sync():
        called.set();context.service.next_due=time.monotonic()+60
    monkeypatch.setattr(context.service,'sync',sync)
    assert guest.post('/api/auth/logout',headers=gh).status_code==200
    app.state.accounts.start();context.service.next_due=0
    try:
        assert not called.wait(1.2)
        assert login(guest,True).status_code==200
        assert called.wait(3)
    finally:
        app.state.accounts.stop()
        for item in app.state.accounts.items.values():
            if item.service.thread:item.service.thread.join(timeout=3)


def test_guest_session_limit_does_not_evict_owner(multi):
    app,owner,guest=multi;assert login(owner).status_code==200;oh=headers(owner)
    for _ in range(17):
        client=TestClient(app,base_url=ORIGIN)
        try:assert login(client,True).status_code==200
        finally:client.close()
    assert owner.get('/api/config',headers=oh).status_code==200
    assert sum(s['account']==GUEST for s in app.state.auth.sessions.values())==16


def test_smtp_failure_for_guest_does_not_disable_owner(multi,monkeypatch):
    app,owner,guest=multi
    app.state.auth.probe=lambda p,c,password:(not (p=='smtp' and c['address']==GUEST),'')
    app,owner,guest,oh,gh=signed_in(multi)
    assert owner.get('/api/auth/me',headers=oh).json()['smtp_available'] is True
    assert guest.get('/api/auth/me',headers=gh).json()['smtp_available'] is False
    smtp=FakeSMTP();monkeypatch.setattr(app.state.service,'smtp',lambda cfg:smtp)
    own=owner.post('/api/drafts',json={'to':'fixture@example.test'},headers=oh).json()['id']
    other=guest.post('/api/drafts',json={'to':'fixture@example.test'},headers=gh).json()['id']
    assert owner.post('/api/drafts/'+own+'/send',headers=oh).json()['state']=='accepted'
    assert guest.post('/api/drafts/'+other+'/send',headers=gh).status_code==403


def test_invalid_allowlist_fails_closed_for_guest_without_locking_owner(multi):
    app,owner,guest,oh,gh=signed_in(multi)
    (users_root(app.state.store.root)/'access.json').write_text('[]')
    assert owner.get('/api/config',headers=oh).status_code==200
    assert guest.get('/api/config',headers=gh).status_code==401
