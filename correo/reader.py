"""Uniform reading markup: no sender CSS, resources, active content or live URLs."""
from html import escape
from html.parser import HTMLParser
import bleach
from .mime import message_links

TAGS = ['p','br','div','span','b','strong','i','em','u','s','blockquote','pre','code',
        'ul','ol','li','table','thead','tbody','tfoot','tr','th','td','h1','h2','h3','h4','hr','a']
BLOCKED = {'script','style','head','template','svg','math','iframe','object','form','noscript'}
VOID = {'br','hr','img','input','meta','link','source','embed','wbr','area','base','col','param'}


class Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocked, self.parts = [], []

    def handle_starttag(self, tag, attrs):
        if tag in BLOCKED: self.blocked.append(tag)
        if self.blocked: return
        if tag == 'img':
            self.parts.append(escape(dict(attrs).get('alt','')))
        else:
            self.parts.append('<'+tag+''.join(' '+k+'="'+escape(v or '',quote=True)+'"' for k,v in attrs)+'>')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag,attrs)
        if tag not in VOID:self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.blocked:
            if tag == self.blocked[-1]:self.blocked.pop()
            return
        self.parts.append('</'+tag+'>')

    def handle_data(self, data):
        if not self.blocked:self.parts.append(escape(data))


def clean_markup(html):
    parser=Visible();parser.feed(html)
    return bleach.clean(''.join(parser.parts),tags=TAGS,attributes={'a':['href']},protocols=['https','http'],strip=True)


def reading_content(plain, html):
    links=message_links(plain,html)
    indexes={link['url']:i for i,link in enumerate(links)}
    class Render(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.markup,self.text,self.anchors=[],[],[]
        def handle_starttag(self,tag,attrs):
            if tag=='a':
                index=indexes.get(dict(attrs).get('href','').strip())
                self.anchors.append(index is not None)
                self.markup.append(f'<button type="button" class="message-link" data-link="{index}">' if index is not None else '<span>')
                return
            if tag=='table':self.markup.append('<div class="table-scroll">')
            self.markup.append('<'+tag+'>')
            if tag in ('p','div','br','li','tr','blockquote','pre','h1','h2','h3','h4'):self.text.append('\n')
            if tag=='li':self.text.append('• ')
        def handle_endtag(self,tag):
            if tag=='a':
                self.markup.append('</button>' if self.anchors and self.anchors.pop() else '</span>');return
            self.markup.append('</'+tag+'>')
            if tag=='table':self.markup.append('</div>')
            if tag in ('p','div','li','tr','blockquote','pre','h1','h2','h3','h4'):self.text.append('\n')
            if tag in ('td','th'):self.text.append('\t')
        def handle_data(self,data):
            self.markup.append(escape(data));self.text.append(data)
    parser=Render();parser.feed(clean_markup(html))
    text=plain if plain.strip() else reflow_text(''.join(parser.text))
    if html.strip() and reflow_text(''.join(parser.text)):
        markup=''.join(parser.markup)
    else:
        # Substitute only URLs already validated by the same link extractor.
        import re
        chunks=[];end=0
        for match in re.finditer(r'https?://[^\s<>"\x00-\x1f\x7f]+',plain,re.IGNORECASE):
            url=match.group().rstrip('.,;!')
            if url not in indexes:continue
            chunks.append(escape(plain[end:match.start()]))
            chunks.append(f'<button type="button" class="message-link" data-link="{indexes[url]}">'+escape(url)+'</button>')
            end=match.start()+len(url)
        chunks.append(escape(plain[end:]))
        markup='<pre>'+''.join(chunks)+'</pre>'
    return {'markup':markup,'text':text or '(Sin texto legible.)','links':links,'derived_text':not bool(plain.strip())}


def reflow_text(text):
    import re
    return re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+','\n\n',text).strip()
