import re
import threading
import time
from fastapi.testclient import TestClient
import pytest
from correo.auth import WebSettings,COOKIE,PRE_COOKIE,login_address,IDLE_SECONDS,MAX_SECONDS
from correo.web import create_app
from correo.store import secret_key

ORIGIN='https://correo-beta.example.test'


@pytest.fixture
def beta(store,vault):
    cfg=store.config();cfg.update(address='perez.123456@alu.uns.edu.ar',pop_user='perez.123456@alu.uns.edu.ar',smtp_user='perez.123456@alu.uns.edu.ar');store.save_config(cfg)
    app=create_app(store.root,start_worker=False,vault=vault,web=WebSettings(ORIGIN,'demo.trycloudflare.com'))
    app.state.auth.probe=lambda *args:(True,'')
    with TestClient(app,base_url=ORIGIN,raise_server_exceptions=False) as client:yield app,client


def bootstrap(client):
    page=client.get('/')
    assert page.status_code==200
    return re.search(r'name="csrf-token" content="([^"]+)"',page.text).group(1)


def login(client,password='ficticia',surname='Pérez',lu='123456'):
    csrf=bootstrap(client)
    response=client.post('/api/auth/login',json={'surname':surname,'lu':lu,'password':password},headers={'Origin':ORIGIN,'X-CSRF-Token':csrf})
    return response


def authorized_headers(client):return {'X-CSRF-Token':bootstrap(client),'Origin':ORIGIN}


def test_address_format():
    assert login_address(' Pérez ','012345')=='perez.012345@alu.uns.edu.ar'
    for name,lu in [('x@y','1'),('perez','../a'),('','123')]:
        with pytest.raises(ValueError):login_address(name,lu)


@pytest.mark.parametrize('origin',['http://example.test','https://x.test/path','https://a@x.test','https://x.test?x=y','https://x.test#x'])
def test_insecure_origins_refused(origin):
    with pytest.raises(ValueError):WebSettings(origin)


def test_no_data_without_session(beta,sample):
    app,c=beta;info=app.state.store.save(sample)
    assert 'Ingresar al correo' in c.get('/').text
    for path in ('config','messages','status','auth/me',f'messages/{info["id"]}',f'messages/{info["id"]}/eml',f'messages/{info["id"]}/html',f'messages/{info["id"]}/attachment/0'):
        response=c.get('/api/'+path,headers={'X-CSRF-Token':app.state.token})
        assert response.status_code==401,path
        assert response.headers['cache-control']=='no-store, private'
    assert c.post('/api/backup',headers={'Origin':ORIGIN}).status_code==401


def test_login_both_services_parallel_and_cookies(beta):
    app,c=beta;barrier=threading.Barrier(2);calls=[]
    def probe(protocol,cfg,password):
        assert cfg['address']=='perez.123456@alu.uns.edu.ar' and password=='ficticia'
        calls.append(protocol);barrier.wait(timeout=3)
        return True,''
    app.state.auth.probe=probe
    response=login(c)
    assert response.status_code==200,response.text
    assert set(calls)=={'pop','smtp'}
    cookie=response.headers.get_list('set-cookie')[0]
    assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=strict' in cookie
    assert 'ficticia' not in cookie and 'perez' not in cookie
    headers=authorized_headers(c)
    assert c.get('/api/config',headers=headers).status_code==200
    assert 'Cerrar sesión' in c.get('/').text


def test_pop_failure_denies_even_if_smtp_ok(beta):
    app,c=beta;app.state.auth.probe=lambda p,*args:(p=='smtp','SECRET')
    response=login(c)
    assert response.status_code==401 and 'SECRET' not in response.text
    assert c.get('/api/messages').status_code==401
    assert not app.state.auth.sessions and not app.state.vault.session


def test_smtp_failure_allows_read_but_blocks_send(beta,sample):
    app,c=beta;app.state.auth.probe=lambda p,*args:(p=='pop','SECRET')
    response=login(c)
    assert response.status_code==200 and not response.json()['smtp_available']
    headers=authorized_headers(c)
    assert c.get('/api/messages',headers=headers).status_code==200
    d=c.post('/api/drafts',json={'body':'Prueba'},headers=headers).json()
    assert c.post('/api/drafts/'+d['id']+'/send',headers=headers).status_code==403
    assert 'SECRET' not in response.text


def test_other_account_never_probes(beta):
    app,c=beta;calls=[];app.state.auth.probe=lambda *a:calls.append(a)
    assert login(c,surname='otro').status_code==401
    assert not calls


def test_rate_limit_global_does_not_reset_with_new_cookie(beta):
    app,c=beta
    for i in range(5):assert login(c,surname='otro').status_code==401
    response=login(c,surname='otro')
    assert response.status_code==429 and response.headers['retry-after']=='300'


def test_login_csrf_origin_and_host(beta):
    app,c=beta;csrf=bootstrap(c);body={'surname':'perez','lu':'123456','password':'ficticia'}
    for headers in ({'Origin':ORIGIN},{'Origin':'https://evil.test','X-CSRF-Token':csrf},{'X-CSRF-Token':csrf},{'Origin':ORIGIN,'X-CSRF-Token':csrf,'Sec-Fetch-Site':'cross-site'}):
        assert c.post('/api/auth/login',json=body,headers=headers).status_code==403
    assert c.get('/',headers={'Host':'evil.test'}).status_code==403
    assert c.get('/',headers={'Host':'demo.trycloudflare.com'}).status_code==200


def test_logout_invalidates_server_session_and_memory(beta):
    app,c=beta;assert login(c).status_code==200;headers=authorized_headers(c)
    old=c.cookies.get(COOKIE)
    assert app.state.vault.session
    assert c.post('/api/auth/logout',headers=headers).status_code==200
    assert not app.state.auth.sessions and not app.state.vault.session
    c.cookies.set(COOKIE,old)
    assert c.get('/api/config',headers=headers).status_code==401


def test_idle_and_absolute_expiry_poll_does_not_extend(beta):
    app,c=beta;now=[100.0];app.state.auth.clock=lambda:now[0]
    assert login(c).status_code==200;headers=authorized_headers(c)
    now[0]+=IDLE_SECONDS-1
    assert c.get('/api/status',headers=headers).status_code==200
    now[0]+=2
    assert c.get('/api/status',headers=headers).status_code==401
    assert login(c).status_code==200;headers=authorized_headers(c)
    for _ in range(17):
        now[0]+=IDLE_SECONDS-1
        response=c.get('/api/config',headers=headers)
    assert response.status_code==401


def test_each_session_has_own_csrf_and_logout_preserves_other(beta):
    app,c=beta;assert login(c).status_code==200;first_headers=authorized_headers(c)
    with TestClient(app,base_url=ORIGIN) as second:
        assert login(second).status_code==200;second_headers=authorized_headers(second)
        assert first_headers['X-CSRF-Token']!=second_headers['X-CSRF-Token']
        assert second.get('/api/config',headers=first_headers).status_code==403
        assert c.post('/api/auth/logout',headers=first_headers).status_code==200
        assert second.get('/api/config',headers=second_headers).status_code==200


def test_remote_admin_changes_blocked(beta):
    app,c=beta;assert login(c).status_code==200;headers=authorized_headers(c)
    cfg=app.state.store.config()
    assert c.put('/api/config',json={**cfg,'smtp_host':'evil.test'},headers=headers).status_code==400
    assert c.put('/api/config',json={**cfg,'display_name':'Nombre visible'},headers=headers).status_code==200
    assert c.post('/api/restore',headers=headers).status_code==403
    assert c.put('/api/credentials/pop',json={'password':'SECRET'},headers=headers).status_code==403
    assert c.post('/api/quit',headers=headers).status_code==403


def test_password_not_written_or_returned(beta):
    app,c=beta;secret='fake-password-never-persisted'
    assert login(c,password=secret).status_code==200
    for path in app.state.store.root.rglob('*'):
        if path.is_file():assert secret.encode() not in path.read_bytes()
    assert secret not in c.get('/api/config',headers=authorized_headers(c)).text


def test_web_requires_configured_owner(tmp_path,vault):
    with pytest.raises(ValueError):create_app(tmp_path,vault=vault,web=WebSettings(ORIGIN))


def test_login_bootstrap_cannot_be_replayed_after_success(beta):
    app,c=beta;csrf=bootstrap(c);pre=c.cookies.get(PRE_COOKIE)
    body={'surname':'perez','lu':'123456','password':'ficticia'}
    headers={'Origin':ORIGIN,'X-CSRF-Token':csrf}
    assert c.post('/api/auth/login',json=body,headers=headers).status_code==200
    c.cookies.set(PRE_COOKIE,pre,path='/api/auth')
    assert c.post('/api/auth/login',json=body,headers=headers).status_code==403


def test_login_preserves_previously_saved_credentials(beta):
    app,c=beta;cfg=app.state.store.config();key=secret_key(cfg,'pop')
    app.state.vault.base.put(key,'old-saved-fixture',True)
    assert login(c,password='new-session-fixture').status_code==200
    assert app.state.vault.get(key)=='new-session-fixture'
    assert app.state.vault.base.get(key)=='old-saved-fixture'
    assert c.post('/api/auth/logout',headers=authorized_headers(c)).status_code==200
    assert app.state.vault.get(key)=='old-saved-fixture'


def test_restarted_backend_does_not_restore_browser_sessions(beta):
    app,c=beta;assert login(c).status_code==200;headers=authorized_headers(c);cookie=c.cookies.get(COOKIE)
    restarted=create_app(app.state.store.root,start_worker=False,vault=app.state.vault.base,web=WebSettings(ORIGIN))
    with TestClient(restarted,base_url=ORIGIN) as client:
        client.cookies.set(COOKIE,cookie)
        assert client.get('/api/messages',headers=headers).status_code==401


def test_external_link_can_open_login_but_not_embed_or_call_api(beta):
    app,c=beta
    navigation={'Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}
    assert c.get('/',headers=navigation).status_code==200
    assert c.get('/',headers={**navigation,'Sec-Fetch-Dest':'iframe'}).status_code==403
    assert c.get('/api/messages',headers=navigation).status_code==403
