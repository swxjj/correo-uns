"""Local administration of the beta allowlist; no password access or mail traffic."""
import argparse
import json
import hashlib
from correo.accounts import read_allowlist,write_allowlist,users_root
from correo.auth import login_address
from correo.paths import data_root
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description='Administrar las cuentas invitadas de la beta')
    parser.add_argument('--data',type=Path,help='Carpeta de la cuenta propietaria')
    parser.add_argument('action',choices=['add','remove','list'])
    parser.add_argument('--surname');parser.add_argument('--lu')
    parser.add_argument('--paths',action='store_true',help='Mostrar rutas de los archivos para mantenimiento local')
    args=parser.parse_args();root=args.data or data_root()
    try:
        cfg=json.loads((root/'config.json').read_text('utf-8'))
        owner=cfg.get('address','').lower()
        if not owner:raise ValueError('Configurá primero la cuenta propietaria en el modo local.')
        allowed=read_allowlist(root)
        if args.action=='list':
            print('Propietario: '+owner)
            if args.paths:print('Archivo: '+str(root))
            for address in allowed:
                print('Invitado: '+address)
                if args.paths:print('Archivo: '+str(users_root(root)/'mailboxes'/hashlib.sha256(address.encode()).hexdigest()))
            return 0
        if not args.surname or not args.lu:parser.error('add y remove requieren --surname y --lu')
        address=login_address(args.surname,args.lu)
        if address==owner:raise ValueError('La cuenta propietaria ya está habilitada y no se modifica desde esta lista.')
        if args.action=='add':allowed.append(address)
        else:allowed=[value for value in allowed if value!=address]
        write_allowlist(root,allowed)
        print(('Cuenta permitida: ' if args.action=='add' else 'Acceso revocado: ')+address)
        print('Archivo local de acceso: '+str(users_root(root)/'access.json'))
        print('No se guardó ninguna contraseña ni se probó la cuenta real.')
        return 0
    except (OSError,ValueError,TypeError) as exc:
        print('No se pudo modificar la lista: '+str(exc))
        return 1


if __name__=='__main__':raise SystemExit(main())
