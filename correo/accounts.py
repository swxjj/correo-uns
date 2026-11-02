"""Server-side account allowlist and isolated archives for invited users."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import threading
from .store import Store, DEFAULT, atomic
from .service import Service, UserError


def users_root(owner_root):
    root=Path(owner_root)
    # A sibling: restoring the owner's archive must never move guest archives.
    return root.parent/(root.name+'-usuarios')


def normalize_address(value):
    if not isinstance(value,str):raise ValueError('La dirección de una invitación debe ser texto.')
    value=value.strip().lower()
    if not re.fullmatch(r'[a-z][a-z-]{0,79}\.\d{1,12}@alu\.uns\.edu\.ar',value):
        raise ValueError('Usá una dirección institucional con el formato apellido.LU@alu.uns.edu.ar.')
    return value


def read_allowlist(owner_root):
    path=users_root(owner_root)/'access.json'
    if not path.exists():return []
    data=json.loads(path.read_text('utf-8'))
    if not isinstance(data,dict) or data.get('format')!=1 or not isinstance(data.get('allowed'),list):raise ValueError('Formato de lista de acceso inválido.')
    return sorted(set(normalize_address(value) for value in data['allowed']))


def write_allowlist(owner_root,values):
    values=sorted(set(normalize_address(value) for value in values))
    root=users_root(owner_root);root.mkdir(parents=True,exist_ok=True,mode=0o700)
    atomic(root/'access.json',json.dumps({'format':1,'allowed':values},ensure_ascii=False).encode())


@dataclass
class Account:
    address: str
    store: Store
    vault: object
    service: Service
    guest: bool=False
    active: bool=False
    archive_lock: object=None


def lock_archive(root):
    root=Path(root);root.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    handle=open(root.parent/(root.name+'.lock'),'a+b')
    try:
        if os.fstat(handle.fileno()).st_size==0:handle.write(b'0');handle.flush()
        handle.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise UserError('El archivo de esta cuenta ya está abierto en otra instancia. Cerrala antes de ingresar.') from None
    return handle


class EmptyVault:
    def get(self,key):return None
    def put(self,*args,**kwargs):return False
    def forget(self,key):pass


class Accounts:
    def __init__(self,store,vault,service,guest_vault_factory):
        self.owner=Account(store.config()['address'].lower(),store,vault,service)
        self.items={self.owner.address:self.owner}
        self.lock=threading.RLock()
        self.guest_vault_factory=guest_vault_factory
        self.service_factory=Service
        self.workers=False

    def allowed(self,address):
        if address==self.owner.address:return True
        try:return address in read_allowlist(self.owner.store.root)
        except (OSError,ValueError,TypeError):return False

    def archive_root(self,address):
        address=normalize_address(address)
        if address==self.owner.address:return self.owner.store.root
        digest=hashlib.sha256(address.encode()).hexdigest()
        return users_root(self.owner.store.root)/'mailboxes'/digest

    def config_for(self,address):
        if not self.allowed(address):return None
        if address==self.owner.address:return self.owner.store.config()
        cfg={**DEFAULT,**{key:value for key,value in self.owner.store.config().items() if key.startswith(('pop_','smtp_'))}}
        path=self.archive_root(address)/'config.json'
        if path.exists():
            prefs=json.loads(path.read_text('utf-8'))
            cfg.update({key:prefs[key] for key in ('display_name','auto','interval') if key in prefs})
        cfg.update(address=address,pop_user=address,smtp_user=address)
        return cfg

    def existing(self,address):
        with self.lock:return self.items.get(address)

    def ensure(self,address):
        with self.lock:
            cfg=self.config_for(address)
            if cfg is None:raise PermissionError('La cuenta no está habilitada.')
            if address in self.items:
                item=self.items[address]
                if item.guest:item.store.save_config(cfg)
                return item
            handle=lock_archive(self.archive_root(address))
            try:
                store=Store(self.archive_root(address));store.save_config(cfg)
                vault=self.guest_vault_factory()
                item=Account(address,store,vault,self.service_factory(store,vault),guest=True,archive_lock=handle)
            except BaseException:
                handle.close();raise
            self.items[address]=item
            if self.workers:self.start_item(item)
            return item

    def start_item(self,item):
        if not item.service.thread:
            item.service.start(enabled=(lambda:item.active and self.allowed(item.address)) if item.guest else None)

    def start(self):
        with self.lock:
            self.workers=True
            for item in self.items.values():self.start_item(item)

    def stop(self):
        with self.lock:
            self.workers=False
            for item in self.items.values():
                item.service.stop.set()
                if item.archive_lock:item.archive_lock.close()

    def clear_inactive(self,active):
        with self.lock:
            for address,item in self.items.items():
                item.active=address in active
                if not item.active:item.vault.session.clear()


class AccountProxy:
    """Route helpers resolve only a context verified by the auth middleware."""
    def __init__(self,context,attribute):
        object.__setattr__(self,'_context',context)
        object.__setattr__(self,'_attribute',attribute)

    def _target(self):
        account=self._context.get()
        if account is None:raise RuntimeError('Falta el contexto autenticado de la cuenta.')
        return getattr(account,self._attribute)

    def __getattr__(self,name):return getattr(self._target(),name)
    def __setattr__(self,name,value):setattr(self._target(),name,value)
