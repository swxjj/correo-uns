from email.message import EmailMessage

import pytest

from correo.mime import message_links, sanitized_html


def test_verification_link_preserves_token_and_deduplicates():
    url='https://www.example.test/verify?token=FAKE%2Btoken&next=%2Fhome'
    html='<a href="'+url.replace('&','&amp;')+'"><span>Verificá tu correo</span></a>'
    links=message_links('\n',html+html)
    assert links==[{'url':url,'label':'Verificá tu correo','host':'www.example.test'}]
    assert 'href=' not in sanitized_html(html)


@pytest.mark.parametrize('url',[
    'javascript:alert(1)','data:text/html,hi','file:///C:/private',
    '//example.test/token','/api/quit','https://good.test@evil.test/token',
    'https://example.test:bad/token','https://example.test/\nsecret',
    'https://example.test\\@evil.test/token','https://example.test/\x00token',
])
def test_unsafe_links_rejected(url):
    assert not message_links('',f'<a href="{url}">Abrir</a>')


def test_links_from_images_and_plain_text_without_tracking_resources():
    html='<img src="https://tracking.test/pixel"><a href="https://example.test/verify"><img alt="Confirmar cuenta" src="https://tracking.test/button"></a>'
    links=message_links('Alternativa: https://example.test/help.',html)
    assert [x['url'] for x in links]==['https://example.test/verify','https://example.test/help']
    assert links[0]['label']=='Confirmar cuenta'


def test_active_content_does_not_contribute_links():
    assert message_links('', '<template><a href="https://bad.test">Oculto</a></template><svg><a href="https://bad.test">SVG</a></svg><script>"https://bad.test"</script>')==[]


def test_message_api_html_only_links(store):
    from fastapi.testclient import TestClient
    from correo.web import create_app
    from tools.demo import MemoryVault
    msg=EmailMessage()
    msg['Subject']='Verificación ficticia'
    msg.set_content('\n')
    msg.add_alternative('<a href="https://example.test/verify?token=FAKE&amp;x=1">Confirmar</a>',subtype='html')
    saved=store.save(msg.as_bytes())
    app=create_app(store.root,start_worker=False,vault=MemoryVault())
    with TestClient(app,base_url='http://127.0.0.1') as client:
        import re
        token=re.search(r'name="csrf-token" content="([^"]+)"',client.get('/').text).group(1)
        response=client.get('/api/messages/'+saved['id'],headers={'X-CSRF-Token':token})
        assert response.status_code==200
        data=response.json()
        assert data['links'][0]['url']=='https://example.test/verify?token=FAKE&x=1'
        assert 'solo contiene HTML' in data['body']
