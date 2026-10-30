"""Check configured mail TLS without reading credentials, logging in or sending mail."""
import json
import poplib
import smtplib
import ssl
from correo.paths import data_root
from correo.tls import context as tls_context
from correo.service import close_client,connection_error,explain


def main():
    path=data_root()/'config.json'
    cfg=json.loads(path.read_text('utf-8'))
    for protocol in ('pop','smtp'):
        client=None
        stage='conexión y saludo'
        try:
            ctx=tls_context()
            host,port=cfg[protocol+'_host'],cfg[protocol+'_port']
            if protocol=='pop':
                if cfg['pop_tls']=='ssl':client=poplib.POP3_SSL(host,port,timeout=15,context=ctx)
                else:
                    client=poplib.POP3(host,port,timeout=15)
                    stage='negociación STARTTLS';client.stls(context=ctx)
            else:
                if cfg['smtp_tls']=='ssl':client=smtplib.SMTP_SSL(host,port,timeout=15,context=ctx)
                else:
                    client=smtplib.SMTP(host,port,timeout=15)
                    client.ehlo();stage='negociación STARTTLS';client.starttls(context=ctx)
                stage='saludo EHLO con TLS';client.ehlo()
            print(protocol.upper()+': conexión TLS y certificado correctos. No se probó usuario ni contraseña.')
        except Exception as exc:
            print(explain(exc) if isinstance(exc,ssl.SSLCertVerificationError) else connection_error(protocol.upper(),stage,exc))
        finally:
            if client:close_client(client)


if __name__=='__main__':main()
