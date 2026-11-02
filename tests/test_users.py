import sys
from tools.users import main
from correo.accounts import read_allowlist,users_root


def test_local_invitation_and_listing_do_not_change_owner_config(store,monkeypatch,capsys):
    before=(store.root/'config.json').read_bytes()
    monkeypatch.setattr(sys,'argv',['users','--data',str(store.root),'add','--surname','Gómez','--lu','234567'])
    assert main()==0
    assert read_allowlist(store.root)==['gomez.234567@alu.uns.edu.ar']
    assert (store.root/'config.json').read_bytes()==before
    monkeypatch.setattr(sys,'argv',['users','--data',str(store.root),'list','--paths'])
    assert main()==0
    assert 'gomez.234567@alu.uns.edu.ar' in capsys.readouterr().out


def test_local_revocation_preserves_archive(store,monkeypatch):
    monkeypatch.setattr(sys,'argv',['users','--data',str(store.root),'add','--surname','gomez','--lu','234567'])
    assert main()==0
    marker=users_root(store.root)/'mailboxes'/'preserved';marker.parent.mkdir();marker.write_text('ficticio')
    monkeypatch.setattr(sys,'argv',['users','--data',str(store.root),'remove','--surname','gomez','--lu','234567'])
    assert main()==0
    assert read_allowlist(store.root)==[] and marker.read_text()=='ficticio'


def test_invalid_invitation_does_not_write_allowlist(store,monkeypatch):
    monkeypatch.setattr(sys,'argv',['users','--data',str(store.root),'add','--surname','../x','--lu','123'])
    assert main()==1
    assert read_allowlist(store.root)==[]
