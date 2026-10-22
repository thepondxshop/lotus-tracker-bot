"""Read public Riot HTML data only. Never execute page scripts or enter drawings."""
import asyncio
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin

NEWS='https://playriftbound.com/en-us/news/announcements/'
FAQ=NEWS+'product-drawing-faq/'
CATALOG='https://merch.riotgames.com/en-us/category/riftbound/'

class HTML(HTMLParser):
    def __init__(self):
        super().__init__();self.scripts=[];self.text=[];self.current=None
    def handle_starttag(self,tag,attrs):
        if tag=='script':self.current=[dict(attrs),'']
    def handle_data(self,data):
        if self.current is not None:self.current[1]+=data
        else:self.text.append(data)
    def handle_endtag(self,tag):
        if tag=='script' and self.current is not None:self.scripts.append(self.current);self.current=None

def plain(value):
    p=HTML();p.feed(str(value or ''));return ' '.join(' '.join(p.text).split())

def allowed_url(url):
    if not isinstance(url,str):return False
    try:
        p=urlsplit(url)
        return p.scheme=='https' and not p.username and not p.password and p.port in (None,443) and not p.query and not p.fragment and (
            (p.hostname=='playriftbound.com' and p.path.startswith('/en-us/news/announcements/')) or
            (p.hostname=='merch.riotgames.com' and (p.path=='/en-us/category/riftbound/' or re.fullmatch(r'/en-us/product/[a-z0-9-]+/',p.path))))
    except ValueError:return False

def walk(value):
    if isinstance(value,dict):
        yield value
        for v in value.values():yield from walk(v)
    elif isinstance(value,list):
        for v in value:yield from walk(v)

def next_page(body):
    p=HTML();p.feed(body)
    rows=[json.loads(s) for attrs,s in p.scripts if attrs.get('id')=='__NEXT_DATA__']
    if len(rows)!=1:raise ValueError('RIOT_NEWS_SCHEMA_MISSING')
    page=rows[0].get('props',{}).get('pageProps',{}).get('page')
    if not isinstance(page,dict) or page.get('locale')!='en-us':raise ValueError('RIOT_NEWS_REGION_OR_SCHEMA')
    return page

def article(body,url):
    if not allowed_url(url) or not url.startswith(NEWS):raise ValueError('RIOT_NEWS_URL')
    page=next_page(body)
    if str(page.get('url','')).rstrip('/')!=url.rstrip('/'):raise ValueError('RIOT_ARTICLE_IDENTITY')
    blades=page.get('blades',[])
    heads=[b for b in blades if b.get('type')=='articleMasthead']
    if len(heads)!=1:raise ValueError('RIOT_ARTICLE_MASTHEAD')
    head=heads[0];texts=[]
    for b in blades:
        if b.get('type')=='articleRichText':texts.append(plain(b.get('richText',{}).get('body')))
        elif b.get('type')=='articleRichTextAccordion':
            for group in b.get('groups',[]):texts.append(plain(group.get('label'))+' '+plain(group.get('content',{}).get('body')))
    title=plain(head.get('title'));content='\n'.join(texts)
    if not title or not content:raise ValueError('RIOT_ARTICLE_EMPTY')
    # Preserve schedule text; never convert a calendar window into stock evidence.
    schedule=[s for s in texts if re.search(r'registration (?:opens|goes live)|registration closes|sign.up window',s,re.I)]
    return dict(url=url,title=title,published_at=head.get('publishDate'),
        fingerprint=hashlib.sha256((title+'\n'+content).encode()).hexdigest(),
        kind='DRAWING_ANNOUNCEMENT' if re.search(r'\bdrawing\b',title+' '+content,re.I) else 'OFFICIAL_ANNOUNCEMENT',
        schedule_text='\n'.join(schedule)[:1200],stock_verified=False)

def article_links(body):
    page=next_page(body);result=[]
    for node in walk(page.get('blades',[])):
        action=node.get('action',{})
        if not isinstance(action,dict) or action.get('type')!='weblink':continue
        raw=action.get('payload',{}).get('url','')
        url=urljoin(NEWS,raw)
        if allowed_url(url) and url.startswith(NEWS) and url.rstrip('/')!=NEWS.rstrip('/') and url not in result:result.append(url)
    return result[:100]

def merch_rows(body):
    p=HTML();p.feed(body);segments=[]
    for _,script in p.scripts:
        m=re.fullmatch(r'\s*self\.__next_f\.push\((.*)\)\s*;?\s*',script,re.S)
        if not m:continue
        try:
            chunk=json.loads(m[1])
            if len(chunk)==2 and chunk[0]==1 and isinstance(chunk[1],str):segments.append(chunk[1])
        except (ValueError,TypeError):continue
    grids=[]
    for line in ''.join(segments).splitlines():
        _,sep,raw=line.partition(':')
        if not sep:continue
        try:document=json.loads(raw)
        except ValueError:continue
        grids.extend(n for n in walk(document) if n.get('id')=='product-listing-grid' and 'initialProducts' in n)
    if len(grids)!=1 or not isinstance(grids[0]['initialProducts'],list) or not grids[0]['initialProducts']:
        raise ValueError('RIOT_CATALOG_SCHEMA_OR_EMPTY')
    result=[];seen=set()
    for row in grids[0]['initialProducts']:
        if not isinstance(row,dict):raise ValueError('RIOT_PRODUCT_SCHEMA')
        if row.get('ip',{}).get('slug')!='riftbound':continue
        slug=row.get('slug');title=plain(row.get('title'));pid=row.get('id')
        if not isinstance(slug,str) or not re.fullmatch(r'[a-z0-9-]+',slug) or not isinstance(pid,str) or not title:raise ValueError('RIOT_PRODUCT_IDENTITY')
        if pid in seen or any(x['slug']==slug for x in result):raise ValueError('RIOT_DUPLICATE_PRODUCT')
        seen.add(pid)
        price=row.get('price',{})
        try:
            amount=Decimal(str(price['amount']))
            if not amount.is_finite() or amount<=0 or price.get('currencyCode')!='USD':raise ValueError()
        except (KeyError,InvalidOperation,ValueError,TypeError):raise ValueError('RIOT_PRICE_OR_CURRENCY')
        result.append(dict(id=pid,slug=slug,title=title,url='https://merch.riotgames.com/en-us/product/'+slug+'/',
            price=str(amount),currency='USD',reported_availability=row.get('availability'),
            stock_verified=False,requires_login=row.get('requiresLogin'),is_preorder=row.get('isPreorder'),
            registration_restricted=bool(row.get('externalRegistrationUrl')),
            image_url=next((a['src'] for a in row.get('assets',[]) if isinstance(a,dict) and str(a.get('src','')).startswith('https://cdn.sanity.io/')),None)))
    if not result:raise ValueError('RIOT_NO_RIFTBOUND_PRODUCTS')
    return result

class SourceError(ValueError):
    def __init__(self,status,wait=900):
        self.wait=max(300,wait)
        super().__init__('RIOT_HTTP_'+str(status)+' RETRY_AFTER_SECONDS='+str(self.wait))

async def fetch(session,url,_redirects=0):
    if not allowed_url(url):raise ValueError('RIOT_URL_NOT_ALLOWED')
    async with session.get(url,allow_redirects=False) as response:
        if response.status in (301,302,307,308) and _redirects<2:
            redirected=urljoin(url,response.headers.get('Location',''))
            if not allowed_url(redirected) or urlsplit(redirected).hostname!=urlsplit(url).hostname:raise ValueError('RIOT_REDIRECT_BLOCKED')
            return await fetch(session,redirected,_redirects+1)
        if response.status!=200:
            from email.utils import parsedate_to_datetime
            from datetime import datetime,timezone
            raw=response.headers.get('Retry-After','');wait=900
            try:wait=max(wait,int(raw))
            except ValueError:
                try:wait=max(wait,int((parsedate_to_datetime(raw)-datetime.now(timezone.utc)).total_seconds()))
                except (ValueError,TypeError,OverflowError):pass
            raise SourceError(response.status,wait)
        data=bytearray()
        async for chunk in response.content.iter_chunked(32768):
            data.extend(chunk)
            if len(data)>4*1024*1024:raise ValueError('RIOT_PAGE_TOO_LARGE')
        return data.decode('utf-8',errors='replace')
