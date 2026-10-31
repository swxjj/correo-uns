import json
import pytest
from tools.web_deployment import deployment_files,write_deployment


def test_minimal_proxy_upload_has_no_private_data():
    files=deployment_files('https://demo.trycloudflare.com')
    assert {x['file'] for x in files}=={'vercel.json','public/robots.txt'}
    config=json.loads(files[0]['data'])
    assert config['rewrites'][0]=={'source':'/','destination':'https://demo.trycloudflare.com/'}
    assert config['rewrites'][1]['destination']=='https://demo.trycloudflare.com/:path*'
    assert config['outputDirectory']=='public'
    assert any(h['key']=='Vercel-CDN-Cache-Control' and h['value']=='no-store' for h in config['headers'][0]['headers'])


@pytest.mark.parametrize('url',['http://demo.trycloudflare.com','https://evil.example','https://demo.trycloudflare.com/path','https://x@y.trycloudflare.com','https://demo.trycloudflare.com?a=b'])
def test_proxy_refuses_unexpected_upstreams(url):
    with pytest.raises(ValueError):deployment_files(url)


def test_changing_destination_removes_placeholder_but_keeps_link_metadata(tmp_path):
    write_deployment(tmp_path,deployment_files())
    link=tmp_path/'.vercel'/'project.json';link.parent.mkdir();link.write_text('{"projectId":"example"}')
    write_deployment(tmp_path,deployment_files('https://demo.trycloudflare.com'))
    assert not (tmp_path/'public'/'index.html').exists()
    assert (tmp_path/'public'/'robots.txt').exists() and link.exists()
