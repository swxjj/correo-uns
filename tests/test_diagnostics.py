import poplib
import smtplib
from unittest.mock import Mock
import pytest
from correo.service import UserError,connection_error


@pytest.mark.parametrize('code',[454,535,534])
def test_smtp_code_without_server_reply(code):
    message=connection_error('SMTP','autenticación AUTH',smtplib.SMTPAuthenticationError(code,b'password=SECRET user=PRIVATE'))
    assert str(code) in message and 'AUTH' in message
    assert 'SECRET' not in message and 'PRIVATE' not in message
    if code==454:assert 'temporalmente' in message


@pytest.mark.parametrize('reply,expected',[(b'-ERR [SYS/TEMP] internal SECRET','temporal'),(b'-ERR [IN-USE] SECRET','ocupado'),(b'-ERR denied SECRET','contraseña PASS')])
def test_pop_classification_without_reply(reply,expected):
    message=connection_error('POP3','contraseña PASS',poplib.error_proto(reply))
    assert expected in message and 'SECRET' not in message


def test_pop_tls_rejection_is_not_password_rejection(service,monkeypatch):
    client=Mock();client.stls.side_effect=poplib.error_proto(b'-ERR SECRET')
    monkeypatch.setattr(poplib,'POP3',lambda *a,**k:client)
    with pytest.raises(UserError,match='negociación STARTTLS') as result:service.pop(service.store.config())
    assert 'todavía no se comprobó' in str(result.value)
    assert 'SECRET' not in str(result.value)
    client.user.assert_not_called();client.pass_.assert_not_called()


def test_pop_pass_rejection_names_stage(service,monkeypatch):
    client=Mock();client.pass_.side_effect=poplib.error_proto(b'-ERR SECRET')
    monkeypatch.setattr(poplib,'POP3',lambda *a,**k:client)
    monkeypatch.setattr(service,'password',lambda *args:'ficticia')
    with pytest.raises(UserError,match='contraseña PASS') as result:service.pop(service.store.config())
    assert 'TLS ya se estableció' in str(result.value)
    assert 'SECRET' not in str(result.value)


def test_uidl_timeout_identifies_authenticated_stage(service):
    client=Mock()
    client.uidl.side_effect=TimeoutError('PRIVATE')
    with pytest.raises(UserError,match='consulta UIDL') as result:
        service.uidls(client)
    assert 'autenticación completada' in str(result.value)
    assert 'PRIVATE' not in str(result.value)


def test_tls_setup_failure_is_not_misreported_as_network(service,monkeypatch):
    import ssl
    monkeypatch.setattr('correo.service.tls_context',Mock(side_effect=PermissionError('PRIVATE')))
    with pytest.raises(UserError,match='preparación de certificados TLS') as result:
        service.pop(service.store.config())
    assert 'PRIVATE' not in str(result.value)
