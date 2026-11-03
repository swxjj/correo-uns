from email.message import EmailMessage
from html.parser import HTMLParser
from correo.mime import content
from correo.reader import reading_content


def test_html_only_structure_text_and_exact_link():
    result=reading_content('\n','<h1>Inscripción</h1><p>Hola, <strong>Álvaro</strong>.</p><ul><li>Primer paso</li></ul><table><tr><th>Fecha</th><td>Mañana</td></tr></table><a href="https://example.test/verify?t=FAKE%2B&amp;x=%2F">Confirmar</a>')
    assert '<h1>Inscripción</h1>' in result['markup']
    assert '<div class="table-scroll"><table>' in result['markup']
    assert 'data-link="0"' in result['markup'] and 'href=' not in result['markup']
    assert result['links'][0]['url']=='https://example.test/verify?t=FAKE%2B&x=%2F'
    assert 'Álvaro' in result['text'] and 'Primer paso' in result['text'] and 'Mañana' in result['text']
    assert result['derived_text']


def test_plain_text_preserves_whitespace_and_links_without_html_injection():
    text='Hola <script>\n\n  Alineado\nhttps://example.test/verify?t=FAKE&x=2.'
    result=reading_content(text,'')
    assert result['text']==text and not result['derived_text']
    assert '&lt;script&gt;' in result['markup'] and 'data-link="0"' in result['markup']
    assert '</button>.' in result['markup']


def test_unusable_html_falls_back_to_available_plain_text():
    result=reading_content('Contenido disponible','<style>Invisible</style><script>bad()</script>')
    assert result['markup']=='<pre>Contenido disponible</pre>'


def test_sender_cannot_create_resources_or_controls():
    result=reading_content('', '''<head><style>LEAK_STYLE</style></head><script>LEAK_SCRIPT</script>
    <svg><a href="https://bad.test">LEAK_SVG</a></svg><template>LEAK_TEMPLATE</template>
    <form><input value="LEAK_FORM">LEAK_FORM</form><iframe src="https://bad.test">LEAK_FRAME</iframe>
    <p style="position:fixed;background:url(https://bad.test)" onclick="bad()">Legible</p>
    <img src="https://tracker.test/pixel" alt="Descripción"><a href="javascript:alert(1)">Sin destino</a>
    <button data-link="0">Control falso</button><a href="https://example.test">Destino real</a>''')
    assert 'LEAK_' not in result['markup'] and 'LEAK_' not in result['text']
    assert 'Legible' in result['markup'] and 'Descripción' in result['markup']
    class Audit(HTMLParser):
        def handle_starttag(self,tag,attrs):
            assert tag not in ('script','style','img','iframe','form','input','svg','template','link','meta')
            assert all(k in ('class','type','data-link') for k,v in attrs)
    Audit().feed(result['markup'])
    assert result['markup'].count('data-link=')==1


def test_malformed_html_remains_inert():
    source='<table><svg/onload=alert(1)><a href="javascript:alert(2)">bad</a></svg></table><p><b>Hola</p><img/src=x onerror=alert(3)>'
    markup=reading_content('',source)['markup']
    assert 'onload' not in markup and 'onerror' not in markup and 'javascript:' not in markup
    assert '<img' not in markup and '<svg' not in markup


def test_alternatives_choose_last_supported_nonempty_body():
    msg=EmailMessage();msg.set_content('Alternativa vieja')
    msg.add_alternative('Alternativa nueva',subtype='plain')
    msg.add_alternative('<p>Versión HTML</p>',subtype='html')
    msg.add_alternative('\n',subtype='plain')
    _,plain,html,_=content(msg.as_bytes())
    assert plain.strip()=='Alternativa nueva' and html.strip()=='<p>Versión HTML</p>'


def test_related_uses_selected_root_and_keeps_attachment():
    msg=EmailMessage();msg.make_related();msg.set_param('start','<root>')
    other=EmailMessage();other.set_content('No es el cuerpo',subtype='html');other['Content-ID']='<other>'
    root=EmailMessage();root.set_content('<p>Cuerpo correcto</p>',subtype='html');root['Content-ID']='<root>'
    image=EmailMessage();image.set_content(b'fake-image',maintype='image',subtype='png');image['Content-ID']='<logo>'
    for part in (other,root,image):msg.attach(part)
    _,plain,html,atts=content(msg.as_bytes())
    assert 'Cuerpo correcto' in html and 'No es el cuerpo' not in html
    assert len(atts)==1 and atts[0]['data']==b'fake-image'


def test_saved_message_rereads_without_touching_original_or_flags(store,vault):
    from fastapi.testclient import TestClient
    from correo.web import create_app
    msg=EmailMessage();msg.set_content('\n');msg.add_alternative('<p>Ya recibido</p><a href="https://example.test">Ver</a>',subtype='html')
    saved=store.save(msg.as_bytes());ident=saved['id'];raw=store.raw(ident)
    store.update(ident,unread=False,starred=True,archived=True)
    app=create_app(store.root,start_worker=False,vault=vault)
    with TestClient(app,base_url='http://127.0.0.1',headers={'X-CSRF-Token':app.state.token}) as client:
        data=client.get('/api/messages/'+ident).json()
        assert 'Ya recibido' in data['reading']['markup']
        assert client.get('/reader.css').status_code==200
    assert store.raw(ident)==raw
    info=store.info(ident)
    assert info['starred'] and info['archived'] and not info['unread']
