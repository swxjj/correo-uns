"""Record only installed runtime dependencies, without bundling development tools."""
from importlib.metadata import distribution
from pathlib import Path
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


if __name__=='__main__':
    found={}
    def visit(name):
        dist=distribution(name)
        canonical=canonicalize_name(dist.metadata['Name'])
        if canonical in found:return
        found[canonical]=dist.version
        for text in dist.requires or []:
            req=Requirement(text)
            if not req.marker or req.marker.evaluate({'extra':''}):visit(req.name)
    for package in ('fastapi','uvicorn','bleach','python-multipart'):visit(package)
    Path('requirements-lock.txt').write_text('# Runtime verificado en Windows, Python 3.11\n'+'\n'.join(f'{name}=={version}' for name,version in sorted(found.items()))+'\n',encoding='utf-8')
