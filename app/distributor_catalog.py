"""Public distributor product evidence, with exact packaging and no stock inference."""
import json
import re
import unicodedata
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit
from html.parser import HTMLParser
from app.distributor_msrp import Text, extract, validate_url

SEEDS={
 'phd':'https://www.phdgames.com/blog-tcgs/',
 'acd':'https://www.acdd.com/products/collectible-card-games/',
 'gts':'https://gtsdistribution.com/pc_combined_results.asp?faceted_search_terms=Category~04552AD14A72447B95ECFC368E1CB6BD',
}
def norm(value):
    s=unicodedata.normalize('NFKD',str(value)).encode('ascii','ignore').decode().lower()
    s=re.sub(r'\b(?:trading card game|card game|tcg|ccg)\b',' ',s)
    s=re.sub(r'^\s*(?:pre[ -]?order)\s*[:\-]?\s*','',s)
    s=re.sub(r'\b(?:factory sealed|sealed)\b',' ',s)
    s=s.replace('booster display box','booster box').replace('booster display','booster box').replace('core booster box','booster box')
    return ' '.join(re.findall(r'[a-z0-9]+',s))

def packaging(title):
    s=norm(title)
    if re.search(r'\b(?:assortment|assorted|protector|acrylic|empty|sleeves|binder|playmat)\b',s):return None
    if re.search(r'\bcase\b',s):return 'CASE'
    if re.search(r'\b(?:lot|set of|two|three|four|[2-9]\d*)\s+(?:of\s+)?(?:booster\s+)?(?:boxes|bundles|decks)\b',s):return None
    if 'booster bundle' in s:return 'BOOSTER BUNDLE'
    if 'elite trainer box' in s:return 'ELITE TRAINER BOX'
    if 'booster box' in s or re.search(r'\b(?:play|collector|draft|set) booster (?:box|display)\b',s):return 'BOOSTER BOX'
    if 'sleeved booster' in s:return 'SLEEVED BOOSTER PACK'
    if 'booster pack' in s:return 'BOOSTER PACK'
    if 'collector box' in s or 'collection box' in s:return 'COLLECTION BOX'
    if 'starter deck' in s:return 'STARTER DECK'
    if 'commander deck' in s:return 'COMMANDER DECK'
    return None

def date_value(value):
    if not value:return None
    for fmt in ('%B %d, %Y','%m/%d/%Y','%m/%d/%y','%Y%m%d','%Y-%m-%d','%Y-%m-%dT%H:%M:%SZ'):
        try:return datetime.strptime(str(value).strip(),fmt).date().isoformat()
        except ValueError:pass
    return None

def money(value):
    try:
        d=Decimal(str(value))
        return str(d) if d.is_finite() and 0<d<Decimal('1000000') else None
    except (InvalidOperation,ValueError):return None

class Links(HTMLParser):
    def __init__(self):super().__init__();self.urls=[]
    def handle_starttag(self,t,a):
        if t=='a':self.urls.append(dict(a).get('href',''))

def record(source,sku,title,value,release,source_kind,codes=None,case_quantity=None,case_code=None):
    typ=packaging(title); price=money(value); release=date_value(release)
    problems=[]
    if not typ:problems.append('PACKAGING_UNVERIFIED')
    if not price:problems.append('MSRP_UNAVAILABLE')
    if not release:problems.append('RELEASE_DATE_UNVERIFIED')
    # Parenthetical assortment/count prices are not presumed to be whole displays.
    if source_kind=='ACD' and re.search(r'\(\s*\d+\s*\)',title):problems.append('UNIT_BASIS_UNVERIFIED')
    now=datetime.now(timezone.utc)
    return dict(source=source,sku=str(sku),name=title,name_key=norm(title),product_type=typ,
        amount=price,currency='USD',region='US',product_family='GLOBAL_STANDARD',
        release_date=release,release_date_source=source,release_date_verified=bool(release),
        source_kind=source_kind,gtins=codes or [],case_quantity=case_quantity,case_gtin=case_code,
        captured_at=now.isoformat(),expires_at=(now+timedelta(days=7)).isoformat(),
        ready=not problems,issues=problems)

def walk_json(x,depth=0):
    if depth>35:return
    if isinstance(x,dict):
        if 'sku' in x and 'prices' in x and 'name' in x:yield x
        for v in x.values():yield from walk_json(v,depth+1)
    elif isinstance(x,list):
        for v in x:yield from walk_json(v,depth+1)
    elif isinstance(x,str) and x[:1] in ('{','['):
        try:yield from walk_json(json.loads(x),depth+1)
        except (ValueError,RecursionError):pass

def acd_products(html):
    decoder=json.JSONDecoder();found={}
    for m in re.finditer(r'self\.__next_f\.push\(',html):
        try:chunk,_=decoder.raw_decode(html[m.end():]);payload=chunk[1]
        except (ValueError,IndexError,TypeError):continue
        if not isinstance(payload,str):continue
        for line in re.finditer(r'(?:^|\n)[0-9a-f]+:',payload):
            try:root,_=decoder.raw_decode(payload[line.end():])
            except ValueError:continue
            for p in walk_json(root):found[p['sku']]=p
    return list(found.values())

def parse(url,html):
    validate_url(url);host=urlsplit(url).hostname.removeprefix('www.');rows=[];links=[]
    reader=Links();reader.feed(html)
    if host=='acdd.com':
        for p in acd_products(html):
            fields={f.get('name'):f.get('value') for f in p.get('customFields',[])}
            retail=(p.get('prices') or {}).get('retailPrice') or {}
            if retail.get('currencyCode')!='USD':continue
            source=urljoin(url,p.get('path',''))
            code=fields.get('upc_code')
            codes=[code] if code and re.fullmatch(r'\d{12,14}',code) else []
            rows.append(record(source,p['sku'],p['name'],retail.get('value'),fields.get('release_date'),'ACD',codes))
    elif host=='gtsdistribution.com':
        m=re.search(r'var\s+productResults\s*=\s*',html)
        try:doc,_=json.JSONDecoder().raw_decode(html[m.end():]) if m else ({},0)
        except ValueError:doc={}
        for p in doc.get('products',[]):
            vals={money(u.get('SRetailPrice')) for u in p.get('uomPrice',[]) if u.get('isDefault') is True or u.get('IsDefault') is True}
            vals.discard(None);price=next(iter(vals)) if len(vals)==1 else None
            title=p.get('name','');typ=packaging(title);codes=[];case_code=None
            fields=p.get('searchfields') or {};config=' '.join(str(f.get('value','')) for f in fields.values() if 'config' in str(f.get('label','')).lower())
            cq=re.search(r'\b(\d+)\s+(?:boxes|displays)\s*(?:/|per\s+)\s*case\b',config,re.I)
            for label,code in re.findall(r'UPC\s*\(([^)]+)\)\s*:\s*(\d{12,14})',str(p.get('opt5','')),re.I):
                label=label.lower()
                if label in {'case','cs'}:case_code=code
                if typ=='BOOSTER BOX' and label in {'display','dsp'}:codes.append(code)
                elif typ=='CASE' and label in {'case','cs'}:codes.append(code)
                elif typ in {'BOOSTER PACK','SLEEVED BOOSTER PACK'} and label in {'pack','ea','each'}:codes.append(code)
            source=urljoin(url,p.get('link',''))
            rows.append(record(source,p.get('sku',''),title,price,p.get('release_date_display') or p.get('release_date'),'GTS',codes,int(cq[1]) if cq else None,case_code))
    elif host=='phdgames.com':
        # Only dated article pages: listing excerpts are incomplete and may mix SKUs.
        if re.fullmatch(r'/\d{4}/\d{2}/\d{2}/[^/]+/?',urlsplit(url).path):
            for p in extract(url,html)['observations']:
                if p.get('state')!='PUBLIC_MSRP_OBSERVED':continue
                rows.append(record(url,p['sku'],p.get('title_context') or '',p['msrp'],p.get('release_date_text'),'PHD'))
        for link in reader.urls:
            link=urljoin(url,link).split('#')[0]
            if urlsplit(link).hostname in {'www.phdgames.com','phdgames.com'} and re.fullmatch(r'/\d{4}/\d{2}/\d{2}/[^/]+/?',urlsplit(link).path):links.append(link)
    return rows,list(dict.fromkeys(links))
