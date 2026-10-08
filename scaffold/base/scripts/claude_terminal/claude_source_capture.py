"""Bounded public-source download and text extraction. No model or account calls."""
import datetime
import ipaddress
import shutil
import socket
import subprocess
import tempfile
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

LIMIT=8*1024*1024

def public_url(url):
    u=urlsplit(url)
    if u.scheme!='https' or not u.hostname or u.username or u.password:
        raise ValueError('public HTTPS URL required')
    addresses=socket.getaddrinfo(u.hostname,u.port or 443,type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('source address is not public')
    return url

class Redirects(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        public_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

class HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.hidden=0;self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','head'):self.hidden+=1
        if not self.hidden and tag in ('p','div','li','br','h1','h2','h3','tr','section'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style','head') and self.hidden:self.hidden-=1
        if not self.hidden and tag in ('p','div','li','h1','h2','h3','tr','section'):self.parts.append('\n')
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)

def extract(raw,content_type,charset='utf-8'):
    if raw.startswith(b'%PDF-'):
        executable=shutil.which('pdftotext') or '/opt/homebrew/bin/pdftotext'
        with tempfile.TemporaryDirectory(prefix='research-source-') as folder:
            source=Path(folder)/'source.pdf';out=Path(folder)/'source.txt';source.write_bytes(raw)
            subprocess.run([executable,'-layout',str(source),str(out)],check=True,timeout=8,capture_output=True)
            if out.stat().st_size>LIMIT:raise ValueError('extracted text exceeds bound')
            text=out.read_text(encoding='utf-8')
        return text.encode(),'pdf','Poppler pdftotext -layout; page breaks retained; no OCR, figures or layout certification'
    text=raw.decode(charset or 'utf-8')
    if 'html' in content_type.lower():
        parser=HTMLText();parser.feed(text)
        return ''.join(parser.parts).encode(),'html','HTML text nodes excluding head/script/style; no JavaScript, images or layout reconstruction'
    if content_type.lower().startswith('text/'):
        return text.encode(),'txt','Decoded source text, no AI summary'
    raise ValueError('unsupported source content type')

def fetch(url):
    public_url(url);start=time.monotonic()
    # No browser cookies, authentication, environment proxy credentials or retries.
    opener=build_opener(ProxyHandler({}),Redirects())
    request=Request(url,headers={'User-Agent':'Research-Source-Capture/1.0','Accept-Encoding':'identity'})
    with opener.open(request,timeout=12) as response:
        chunks=[];size=0
        while True:
            chunk=response.read(65536)
            if not chunk:break
            size+=len(chunk)
            if size>LIMIT or time.monotonic()-start>18:raise ValueError('source download exceeds bound')
            chunks.append(chunk)
        raw=b''.join(chunks);kind=response.headers.get_content_type();charset=response.headers.get_content_charset()
        metadata={'requested_url':url,'final_url':response.geturl(),'http_status':response.status,
                  'content_type':kind,'bytes':len(raw),'captured_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'boundary':'Separate direct HTTP retrieval, not the WebFetch summary or a claim about identical server responses.'}
    return raw,kind,charset,metadata
