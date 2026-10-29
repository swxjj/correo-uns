import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import threading
import uuid
import zipfile
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from .mime import metadata

DEFAULT = dict(address='', display_name='', pop_host='mail.alu.uns.edu.ar', pop_port=110, pop_tls='starttls', pop_user='', smtp_host='mail.alu.uns.edu.ar', smtp_port=25, smtp_tls='starttls', smtp_user='', auto=False, interval=5)


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic(path, data):
    path = Path(path)
    tmp = path.with_name(path.name+'.tmp')
    with open(tmp, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def account(config):
    # Mailbox identity is independent of TLS/port so fixing transport doesn't redownload everything.
    return hashlib.sha256(json.dumps([config['address'].lower(), config['pop_host'].lower(), config['pop_user']], ensure_ascii=False).encode()).hexdigest()


def secret_key(config, protocol):
    return hashlib.sha256(json.dumps([config['address'].lower(), protocol, config[protocol+'_host'].lower(), config[protocol+'_port'], config[protocol+'_tls'], config[protocol+'_user']]).encode()).hexdigest()


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root/'messages').mkdir(exist_ok=True)
        self.initialize()

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.root/'index.sqlite3', timeout=30)
        conn.row_factory = sqlite3.Row
        conn.create_function('casefold',1,lambda value: (value or '').casefold())
        conn.execute('PRAGMA synchronous=FULL')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self):
        with self.lock, self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, account TEXT, uidl TEXT, folder TEXT, subject TEXT, sender TEXT, recipients TEXT, date TEXT, body TEXT, unread INTEGER, starred INTEGER, archived INTEGER, state TEXT, created TEXT, UNIQUE(account,uidl))')
        self.reconcile()

    def config(self):
        with self.lock:
            p = self.root/'config.json'
            return {**DEFAULT, **(json.loads(p.read_text('utf-8')) if p.exists() else {})}

    def save_config(self, config):
        with self.lock:
            atomic(self.root/'config.json', json.dumps(config, ensure_ascii=False).encode())

    def path(self, ident, suffix='.eml'):
        if not ident or any(c not in 'abcdef0123456789' for c in ident) or len(ident) != 32:
            raise ValueError('Identificador de mensaje inválido.')
        return self.root/'messages'/(ident+suffix)

    def info(self, ident):
        with self.lock:
            return json.loads(self.path(ident, '.json').read_text('utf-8'))

    def raw(self, ident):
        with self.lock:
            return self.path(ident).read_bytes()

    def index(self, info, raw):
        meta = metadata(raw)
        row = {k:info.get(k) for k in ['id','account','uidl','folder','unread','starred','archived','state','created']}
        row.update(meta)
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO messages ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')', list(row.values()))

    def save(self, raw, **info):
        with self.lock:
            info = {**dict(id=uuid.uuid4().hex, account='', uidl=None, folder='inbox', unread=1, starred=0, archived=0, state='', created=now()), **info}
            # Sidecar is the durable commit marker; index can always be reconstructed from it.
            atomic(self.path(info['id']), raw)
            atomic(self.path(info['id'], '.json'), json.dumps(info, ensure_ascii=False).encode())
            self.index(info, raw)
            return info

    def update(self, ident, **changes):
        with self.lock:
            info = self.info(ident)
            info.update(changes)
            atomic(self.path(ident,'.json'), json.dumps(info, ensure_ascii=False).encode())
            self.index(info, self.raw(ident))
            return info

    def reconcile(self):
        with self.lock:
            for p in (self.root/'messages').glob('*.json'):
                info = json.loads(p.read_text('utf-8'))
                if info.get('state') == 'sending':
                    info['state'] = 'uncertain'
                    atomic(p, json.dumps(info, ensure_ascii=False).encode())
                elif info.get('state') == 'preparing':
                    info['state'] = 'failed'
                    atomic(p, json.dumps(info, ensure_ascii=False).encode())
                if info['id'] != p.stem:
                    raise ValueError('El identificador no coincide con el archivo de metadatos.')
                self.index(info, self.raw(info['id']))

    def known(self, acct):
        with self.lock, self.db() as db:
            return {r[0] for r in db.execute('SELECT uidl FROM messages WHERE account=? AND uidl IS NOT NULL', (acct,))}

    def listing(self, folder, query=''):
        where, args = 'folder=?', [folder]
        if folder == 'archive':
            where, args = 'folder="inbox" AND archived=1', []
        elif folder == 'inbox':
            where += ' AND archived=0'
        if query:
            where += ' AND (instr(casefold(subject),casefold(?))>0 OR instr(casefold(sender),casefold(?))>0 OR instr(casefold(body),casefold(?))>0)'
            args += [query]*3
        with self.lock, self.db() as db:
            return [dict(r) for r in db.execute('SELECT id,subject,sender,recipients,date,unread,starred,archived,state,created FROM messages WHERE '+where+' ORDER BY created DESC', args)]

    def backup(self):
        with self.lock:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
                z.writestr('manifest.json', json.dumps({'format':'correo-uns-v1','created':now()}))
                # SQLite online backup works even if journaling policy changes later.
                temp = self.root/'backup.sqlite3'
                try:
                    with self.db() as src, closing(sqlite3.connect(temp)) as dst:
                        with dst:
                            src.backup(dst)
                    z.write(temp,'index.sqlite3')
                finally:
                    temp.unlink(missing_ok=True)
                if (self.root/'config.json').exists():
                    z.write(self.root/'config.json','config.json')
                for p in (self.root/'messages').glob('*.json'):
                    # Uncommitted .eml files (interrupted before their sidecar) are
                    # redownloaded by UIDL and must not make a backup unrestorable.
                    z.write(p,'messages/'+p.name)
                    original=p.with_suffix('.eml')
                    z.write(original,'messages/'+original.name)
            return buf.getvalue()

    def restore(self, data):
        staging = self.root.parent/('CorreoUNS-restaurar-'+uuid.uuid4().hex)
        staging.mkdir()
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                entries = z.infolist()
                if len(entries)>100000 or sum(x.file_size for x in entries)>4*1024**3:
                    raise ValueError('La copia excede el límite de 4 GB o 100.000 archivos.')
                names = [x.filename for x in entries]
                if len(names) != len(set(names)):
                    raise ValueError('La copia contiene entradas duplicadas.')
                for entry in entries:
                    name = entry.filename
                    if name not in ('manifest.json','config.json','index.sqlite3'):
                        if not (name.startswith('messages/') and len(name.split('/'))==2 and Path(name).suffix in ('.eml','.json')):
                            raise ValueError('La copia contiene rutas no permitidas.')
                        stem = Path(name).stem
                        if len(stem)!=32 or any(c not in '0123456789abcdef' for c in stem):
                            raise ValueError('La copia contiene nombres inválidos.')
                    dest = staging/name
                    dest.parent.mkdir(exist_ok=True)
                    with z.open(entry) as src, open(dest,'wb') as dst:
                        shutil.copyfileobj(src,dst)
            if json.loads((staging/'manifest.json').read_text())['format'] != 'correo-uns-v1':
                raise ValueError('Formato de copia no reconocido.')
            # Rebuild from originals rather than trusting executable SQLite schema in a supplied backup.
            (staging/'index.sqlite3').unlink(missing_ok=True)
            candidate = Store(staging)
            cfg = candidate.config()
            cfg['auto'] = False
            candidate.save_config({k:cfg[k] for k in DEFAULT})
            for p in (staging/'messages').glob('*.eml'):
                if not p.with_suffix('.json').exists():
                    raise ValueError('Faltan metadatos de un mensaje en la copia.')
            preserved = self.root.parent/('CorreoUNS-anterior-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
            with self.lock:
                os.replace(self.root, preserved)
                try:
                    os.replace(staging, self.root)
                except BaseException:
                    os.replace(preserved,self.root)
                    raise
            return str(preserved)
        finally:
            if staging.exists():
                if staging.resolve().parent != self.root.resolve().parent or not staging.name.startswith('CorreoUNS-restaurar-'):
                    raise ValueError('Ruta temporal de restauración inesperada; no se eliminará.')
                shutil.rmtree(staging)
