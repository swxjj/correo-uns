"""Produce a minimal Vercel upload: no mail, Python sources, secrets or archive."""
import json
from pathlib import Path
from urllib.parse import urlsplit
import re
import argparse


def deployment_files(tunnel_origin=None):
    root=Path(__file__).resolve().parent.parent/'deploy'/'vercel'
    config=json.loads((root/'vercel.json').read_text('utf-8'))
    if tunnel_origin:
        url=urlsplit(tunnel_origin)
        if url.scheme!='https' or not re.fullmatch(r'[a-z0-9-]+\.trycloudflare\.com',url.netloc) or url.path or url.query or url.fragment:
            raise ValueError('Usá el origen HTTPS exacto del Quick Tunnel, sin ruta.')
        config['rewrites']=[{'source':'/','destination':tunnel_origin+'/'},{'source':'/:path*','destination':tunnel_origin+'/:path*'}]
    # A local index.html wins over rewrites on Vercel. With a live upstream,
    # publish only robots.txt so '/' always reaches the authenticated backend.
    asset='robots.txt' if tunnel_origin else 'index.html'
    return [{'file':'vercel.json','data':json.dumps(config,ensure_ascii=False),'encoding':'utf-8'}, {'file':'public/'+asset,'data':(root/'public'/asset).read_text('utf-8'),'encoding':'utf-8'}]


def write_deployment(directory,files):
    directory=Path(directory)
    keep={f['file'] for f in files}
    for name in ('public/index.html','public/robots.txt'):
        if name not in keep:(directory/name).unlink(missing_ok=True)
    for file in files:
        path=directory/file['file'];path.parent.mkdir(parents=True,exist_ok=True);path.write_text(file['data'],encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--tunnel');parser.add_argument('--out',default='output/vercel-files.json');parser.add_argument('--directory',default='output/vercel-beta');args=parser.parse_args()
    dest=Path(args.out);dest.parent.mkdir(parents=True,exist_ok=True)
    files=deployment_files(args.tunnel)
    dest.write_text(json.dumps(files,ensure_ascii=False),encoding='utf-8')
    write_deployment(args.directory,files)
    print(str(dest.resolve()))
