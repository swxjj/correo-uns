import re
from email import policy
from email.parser import BytesParser
from email.message import EmailMessage
from email.utils import getaddresses, formataddr, make_msgid, formatdate
import bleach


def parse(raw):
    return BytesParser(policy=policy.default).parsebytes(raw)


def safe_name(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name or 'adjunto')
    name = name.strip(' .')[:150] or 'adjunto'
    if name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *('COM'+str(i) for i in range(10)), *('LPT'+str(i) for i in range(10))}:
        name = '_' + name
    return name


def content(raw):
    msg = parse(raw)
    plain, html, attachments = [], [], []
    def visit(part):
        if part.get_content_disposition() == 'attachment' or part.get_filename() or part.get_content_maintype() != 'text':
            if part.is_multipart() and not (part.get_content_disposition() == 'attachment' or part.get_filename() or part.get_content_type()=='message/rfc822'):
                for child in part.iter_parts():
                    visit(child)
                return
            data = part.get_payload(decode=True)
            if data is None:
                payload = part.get_payload()
                data = b'\r\n'.join(p.as_bytes(policy=policy.SMTP) for p in payload) if part.get_content_type()=='message/rfc822' and isinstance(payload,list) else part.as_bytes(policy=policy.SMTP)
            attachments.append({'name': safe_name(part.get_filename() or ('mensaje.eml' if part.get_content_type()=='message/rfc822' else 'adjunto')), 'size': len(data), 'part': part, 'data':data})
        elif part.get_content_type() in ('text/plain', 'text/html'):
            try:
                value = part.get_content()
            except (LookupError, UnicodeError):
                value = (part.get_payload(decode=True) or b'').decode('utf-8', 'replace')
            (plain if part.get_content_type() == 'text/plain' else html).append(value)
    visit(msg)
    return msg, '\n'.join(plain), '\n'.join(html), attachments


def metadata(raw):
    msg, plain, html, _ = content(raw)
    return dict(subject=str(msg.get('Subject', '(Sin asunto)')), sender=str(msg.get('From', '')), recipients=str(msg.get('To', '')), date=str(msg.get('Date', '')), body=plain or bleach.clean(html, tags=[], strip=True))


def sanitized_html(html):
    # No URLs, CSS, images, forms, SVG or active elements. The iframe also has a CSP and empty sandbox.
    return bleach.clean(html, tags=['p','br','div','span','b','strong','i','em','u','s','blockquote','pre','code','ul','ol','li','table','thead','tbody','tr','th','td','h1','h2','h3','hr','a'], attributes={'a':['title']}, protocols=[], strip=True)


def addresses(value):
    # Optional CC/CCO fields are empty; newer Python parsers return an empty address.
    if not value.strip():
        return []
    if '\r' in value or '\n' in value:
        raise ValueError('Los destinatarios no pueden contener saltos de línea.')
    result = [addr for _, addr in getaddresses([value])]
    if any(not re.fullmatch(r'[^\s<>@,;]+@[^\s<>@,;]+', a) or not a.isascii() for a in result):
        raise ValueError('Revisá las direcciones. Usá direcciones sin caracteres internacionales en el nombre de cuenta.')
    return list(dict.fromkeys(result))


def build_message(config, draft, attachments, include_bcc=False):
    msg = EmailMessage(policy=policy.SMTP)
    msg['From'] = formataddr((config['display_name'], config['address']))
    for header, field in [('To','to'), ('Cc','cc')]:
        if draft.get(field):
            addresses(draft[field])
            msg[header] = draft[field]
    if include_bcc and draft.get('bcc'):
        msg['Bcc'] = draft['bcc']
    msg['Subject'] = draft.get('subject', '')
    msg['Date'] = formatdate(localtime=True)
    msg['Message-ID'] = make_msgid()
    for header, field in [('In-Reply-To','in_reply_to'), ('References','references')]:
        if draft.get(field):
            msg[header] = draft[field]
    msg.set_content(draft.get('body', ''))
    for name, data in attachments:
        msg.add_attachment(data, maintype='application', subtype='octet-stream', filename=safe_name(name))
    return msg.as_bytes()
