"""Portability boundaries: data location and native credential lifecycle."""
import sys
import uuid

import pytest
from correo import paths
from correo.secrets import Secrets


def test_macos_data_location(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.sys, 'platform', 'darwin')
    monkeypatch.setattr(paths.Path, 'home', lambda: tmp_path)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'windows'))
    assert paths.data_root() == tmp_path / 'Library/Application Support/CorreoUNS'


def test_windows_data_location(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.sys, 'platform', 'win32')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    assert paths.data_root() == tmp_path / 'CorreoUNS'


class FakeKeychain:
    def __init__(self):
        self.entries = {}
    def get_password(self, service, key):
        return self.entries.get((service, key))
    def set_password(self, service, key, value):
        self.entries[service, key] = value
    def delete_password(self, service, key):
        self.entries.pop((service, key), None)


def test_native_keychain_persist_session_and_forget():
    pytest.importorskip('keyring')
    vault = Secrets()
    vault.available = True
    vault.keychain = FakeKeychain()
    assert vault.put('ficticia', 'prueba-á', persist=True)
    vault.session.clear()
    assert vault.get('ficticia') == 'prueba-á'
    assert vault.put('ficticia', 'temporal', persist=False) is False
    assert vault.keychain.entries == {}
    assert vault.get('ficticia') == 'temporal'
    vault.forget('ficticia')
    assert vault.get('ficticia') is None


def test_locked_keychain_retains_session_only(monkeypatch):
    pytest.importorskip('keyring')
    vault = Secrets()
    vault.available = True
    vault.keychain = FakeKeychain()
    def denied(*args):
        raise RuntimeError('locked')
    monkeypatch.setattr(vault.keychain, 'set_password', denied)
    assert vault.put('ficticia', 'prueba', persist=True) is False
    assert vault.get('ficticia') == 'prueba'
    vault.session.clear()
    assert vault.get('ficticia') is None


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS only')
def test_macos_keychain_roundtrip():
    pytest.importorskip('keyring')
    vault = Secrets()
    key = 'port-test-' + uuid.uuid4().hex
    try:
        assert vault.put(key, 'credencial-ficticia-á', persist=True)
        vault.session.clear()
        assert vault.get(key) == 'credencial-ficticia-á'
    finally:
        vault.forget(key)
    assert vault.get(key) is None


def test_optional_recipient_fields_are_empty():
    from correo.mime import addresses
    assert addresses('') == []
    assert addresses('   ') == []


def test_macos_tls_ignores_broken_inherited_certificate_path(monkeypatch):
    certifi=pytest.importorskip('certifi')
    from correo import tls
    import ssl
    monkeypatch.setattr(tls.sys,'platform','darwin')
    monkeypatch.setenv('SSL_CERT_FILE','/nonexistent/old-environment/cacert.pem')
    monkeypatch.setenv('SSLKEYLOGFILE','/nonexistent/old-environment/tls.log')
    context=tls.context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    assert context.keylog_filename is None
    assert context.get_ca_certs()
