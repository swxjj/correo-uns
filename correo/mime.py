import re
from email import policy
from email.parser import BytesParser
from email.message import EmailMessage
from email.utils import getaddresses, formataddr, make_msgid, formatdate
import bleach
from html.parser import HTMLParser
from urllib.parse import urlsplit


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
    attachments = []
    def visit(part):
        if part.get_content_disposition() == 'attachment' or part.get_filename() or part.get_content_maintype() != 'text':
            if part.is_multipart() and not (part.get_content_disposition() == 'attachment' or part.get_filename() or part.get_content_type()=='message/rfc822'):
                children = list(part.iter_parts())
                values = [visit(child) for child in children]
                if part.get_content_subtype() == 'alternative':
                    return tuple(next((v[i] for v in reversed(values) if v[i].strip()), '') for i in (0,1))
                if part.get_content_subtype() == 'related':
                    start = part.get_param('start')
                    root = next((i for i,c in enumerate(children) if start and c.get('Content-ID') == start), 0)
                    return values[root] if values else ('','')
                return tuple('\n'.join(v[i] for v in values if v[i].strip()) for i in (0,1))
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
            return (value,'') if part.get_content_type() == 'text/plain' else ('',value)
        return '',''
    plain, html = visit(msg)
    return msg, plain, html, attachments


def metadata(raw):
    msg, plain, html, _ = content(raw)
    return dict(subject=str(msg.get('Subject', '(Sin asunto)')), sender=str(msg.get('From', '')), recipients=str(msg.get('To', '')), date=str(msg.get('Date', '')), body=plain or bleach.clean(html, tags=[], strip=True))


def sanitized_html(html):
    # No URLs, CSS, images, forms, SVG or active elements. The iframe also has a CSP and empty sandbox.
    return bleach.clean(html, tags=['p','br','div','span','b','strong','i','em','u','s','blockquote','pre','code','ul','ol','li','table','thead','tbody','tr','th','td','h1','h2','h3','hr','a'], attributes={'a':['title']}, protocols=[], strip=True)


def message_links(plain, html):
    """Extract explicit web links without visiting them or relaxing the HTML sandbox."""
    links, seen = [], set()

    def add(url, label=''):
        url = url.strip()
        if not url or re.search(r'[\s\x00-\x1f\x7f\\]', url): return
        try:
            parsed = urlsplit(url)
            if parsed.scheme.lower() not in ('https', 'http') or not parsed.hostname or parsed.username is not None or parsed.password is not None: return
            parsed.port  # Reject invalid ports before handing the URL to a browser.
            host = parsed.hostname.encode('idna').decode('ascii')
            if not re.fullmatch(r'[a-zA-Z0-9.:-]+', host): return
        except (ValueError, UnicodeError): return
        if url in seen: return
        seen.add(url)
        links.append({'url': url, 'label': ' '.join(label.split())[:200] or 'Abrir enlace', 'host': host})

    class Parser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.blocked = []
            self.url, self.words = None, []

        def handle_starttag(self, tag, attrs):
            if tag in ('script', 'style', 'head', 'template', 'svg', 'math', 'iframe', 'object'):
                self.blocked.append(tag)
            if self.blocked: return
            attrs = dict(attrs)
            if tag == 'a':
                self.finish()
                self.url, self.words = attrs.get('href'), []
            elif tag == 'img' and self.url:
                self.words.append(attrs.get('alt', ''))

        def handle_endtag(self, tag):
            if self.blocked:
                if tag == self.blocked[-1]: self.blocked.pop()
                return
            if tag == 'a': self.finish()

        def handle_data(self, data):
            if self.url and not self.blocked: self.words.append(data)

        def finish(self):
            if self.url: add(self.url, ''.join(self.words))
            self.url, self.words = None, []

    parser = Parser()
    parser.feed(html)
    parser.finish()
    for match in re.finditer(r'https?://[^\s<>"\x00-\x1f\x7f]+', plain, re.IGNORECASE):
        add(match.group().rstrip('.,;!'))
    return links


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
