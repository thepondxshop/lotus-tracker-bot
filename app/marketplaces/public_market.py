"""Published Pokemon pricing; source timestamps, exact reviewed bindings, no stock inference."""
import asyncio
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import aiohttp

CATALOG='https://downloads.s3.cardmarket.com/productCatalog/productList/products_nonsingles_6.json'
GUIDE='https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_6.json'
BIND=('product_url','product_name','product_type','game','product_family','currency','region')
EU=set('AT BE BG HR CY CZ DE DK EE ES FI FR GR HU IE IT LT LU LV MT NL PL PT RO SE SI SK'.split())
# Broad Box Set and mixed-product categories require more evidence and remain preview-only.
TYPES={52:'BOOSTER PACK',53:'BOOSTER BOX',54:'STARTER DECK',1013:'STARTER DECK',1014:'TIN',1016:'ELITE TRAINER BOX',1083:'BLISTER'}
VARIANTS={'normal','holofoil','reverse-holofoil','1st-edition','1st-edition-holofoil','unlimited','unlimited-holofoil'}
_references=[]

def now(): return datetime.now(timezone.utc)
def stamp(v):
    d=datetime.fromisoformat(v.replace('Z','+00:00'))
    if d.tzinfo is None: raise ValueError('TIMEZONE_REQUIRED')
    return d

def money(v):
    if isinstance(v,bool):raise ValueError('INVALID_PRICE')
    n=Decimal(str(v))
    if not n.is_finite() or not 0<n<Decimal('1e9'):raise ValueError('INVALID_PRICE')
    return str(n)

def card_url(k):
    if not isinstance(k,str) or not re.fullmatch(r'[A-Za-z0-9.]+-[A-Za-z0-9]+',k):raise ValueError('INVALID_CARD_ID')
    return 'https://api.tcgdex.net/v2/en/cards/'+k

def row(**r):
    d=stamp(r['source_updated_at']);r['amount']=money(r['amount'])
    r.update(kind='MARKET_PUBLISHED',sample_count=None,stock_verified=False,
        expires_at=(d+timedelta(hours=72)).isoformat(),fresh=d<=now()<d+timedelta(hours=72))
    return r

def card_rows(d,k):
    url=card_url(k)
    if d.get('id')!=k or not d.get('name'):raise ValueError('SOURCE_IDENTITY_MISMATCH')
    out=[]
    for market,currency in [('tcgplayer','USD'),('cardmarket','EUR')]:
        p=d.get('pricing',{}).get(market,{})
        if not p:continue
        if p.get('unit')!=currency:raise ValueError('CURRENCY_MISMATCH')
        fields=[(v,'marketPrice',p[v].get('marketPrice')) for v in sorted(VARIANTS) if isinstance(p.get(v),dict)] if market=='tcgplayer' else [('normal','avg7',p.get('avg7'))]
        for variant,field,value in fields:
            if value is None:continue
            out.append(row(provider='tcgdex',marketplace=market,source=url,source_id=k,
                source_name=d['name'],variant=variant,source_field=field,amount=value,currency=currency,
                source_updated_at=p['updated'],aggregate_scope='PROVIDER_LANGUAGE_CONDITION_AGGREGATE'))
    return out

def sealed_rows(c,g):
    for d,key in [(c,'products'),(g,'priceGuides')]:
        if d.get('version')!=1 or not isinstance(d.get(key),list) or len(d[key])>500000:raise ValueError('SCHEMA_INVALID')
        if stamp(d['createdAt'])>now():raise ValueError('FUTURE_SOURCE')
    lookup={};seen=set();out=[]
    for r in g['priceGuides']:
        k=r.get('idProduct')
        if type(k)!=int or k<=0 or k in lookup:raise ValueError('DUPLICATE_PRICE_ID')
        lookup[k]=r
    for p in c['products']:
        k=p.get('idProduct')
        if type(k)!=int or k<=0 or k in seen:raise ValueError('DUPLICATE_PRODUCT_ID')
        seen.add(k);r=lookup.get(k)
        if not r or p.get('idCategory') not in TYPES:continue
        if r.get('idCategory')!=p['idCategory']:raise ValueError('CATEGORY_CONFLICT')
        # Zero/no-trade values are absence of a usable price, never free products.
        field='avg7' if r.get('avg7') is not None else 'avg'
        try:value=money(r.get(field))
        except (ValueError,ArithmeticError):continue
        out.append(row(provider='cardmarket',marketplace='cardmarket',source=GUIDE,source_id=str(k),
            source_name=p['name'],category_id=p['idCategory'],variant='sealed',source_field=field,
            amount=value,currency='EUR',source_updated_at=g['createdAt'],catalog_source=CATALOG,
            aggregate_scope='PROVIDER_LANGUAGE_AGGREGATE'))
    return out

def mapping_path():return Path(os.getenv('LOTUS_MARKET_MAPPINGS_FILE','/app/app/market-mappings.json'))
def cache_path():return Path(os.getenv('LOTUS_MARKET_CACHE_FILE','/app/app/market-reference-cache.json'))
def digest(m):return hashlib.sha256(json.dumps(m,sort_keys=True).encode()).hexdigest()

def validate(m):
    if m.get('reviewed') is not True or m.get('accept_provider_aggregate') is not True:raise ValueError('REVIEW_REQUIRED')
    if any(not isinstance(m.get(k),str) or not m[k].strip() or m[k]=='UNKNOWN' for k in BIND):raise ValueError('EXACT_IDENTITY_REQUIRED')
    if m['game']!='Pokemon' or not m['product_url'].startswith('https://'):raise ValueError('EXACT_POKEMON_PRODUCT_REQUIRED')
    if type(m.get('quantity'))!=int or m['quantity']!=1 or m.get('packaging_verified') is not True:raise ValueError('EXACT_UNIT_REQUIRED')
    market=m.get('marketplace')
    if not ((market=='tcgplayer' and m['currency']=='USD' and m['region']=='US') or (market=='cardmarket' and m['currency']=='EUR' and m['region'] in EU)):raise ValueError('REGION_CURRENCY_MISMATCH')
    identity=m.get('event_identity')
    if not isinstance(identity,dict) or not identity or any(not isinstance(k,str) or not isinstance(v,str) or not v for k,v in identity.items()):raise ValueError('VARIANT_IDENTITY_REQUIRED')
    if not m.get('source_name') or not isinstance(m.get('source_id'),str):raise ValueError('SOURCE_IDENTITY_REQUIRED')
    if m.get('provider')=='tcgdex':
        if re.search(r'\b(?:PSA|BGS|CGC|SGC)\s*\d|\b(?:graded|slab)\b',m['product_name'],re.I):raise ValueError('GRADED_PRICE_NOT_SUPPORTED')
        card_url(m['source_id'])
        if m['product_type'].upper() not in {'SINGLE','SINGLE CARD'} or m.get('variant') not in VARIANTS:raise ValueError('RAW_SINGLE_REQUIRED')
        if identity.get('condition')!='Near Mint' or identity.get('language')!='English' or not identity.get('variant_id'):raise ValueError('SINGLE_VARIANT_CONDITION_LANGUAGE_REQUIRED')
        if market=='cardmarket' and m['variant']!='normal':raise ValueError('FOIL_AGGREGATE_AMBIGUOUS')
    elif m.get('provider')=='cardmarket':
        if market!='cardmarket' or m.get('variant')!='sealed' or TYPES.get(m.get('category_id'))!=m['product_type'].upper():raise ValueError('SEALED_PACKAGING_MISMATCH')
        if not re.fullmatch('[1-9][0-9]*',m['source_id']):raise ValueError('INVALID_ID')
        if m.get('release_date_verified') is not True or not str(m.get('release_date_source','')).startswith('https://'):raise ValueError('RELEASE_DATE_REQUIRED')
        from datetime import date
        date.fromisoformat(m['release_date'])
    else:raise ValueError('PROVIDER_UNSUPPORTED')
    return m

def mappings():
    p=mapping_path()
    if not p.exists():return []
    if p.stat().st_size>2000000:raise ValueError('MAPPING_FILE_TOO_LARGE')
    ms=json.loads(p.read_text())
    if not isinstance(ms,list) or len(ms)>100:raise ValueError('AT_MOST_100_MAPPINGS')
    return [validate(m) for m in ms]

def bind(m,r):
    validate(m)
    if any(m.get(k)!=r.get(k) for k in ('provider','marketplace','source_id','source_name','variant','currency')):raise ValueError('SOURCE_IDENTITY_CHANGED')
    if m['provider']=='cardmarket' and m['category_id']!=r.get('category_id'):raise ValueError('PACKAGING_CHANGED')
    if not stamp(r['source_updated_at'])<=now()<stamp(r['expires_at']):raise ValueError('STALE_PRICE')
    return dict(r,**{k:m[k] for k in BIND},scope='EXACT_PRODUCT',confidence='HIGH',family=m['product_family'],
        mapping_hash=digest(m),event_identity=m['event_identity'],reviewed=True,
        release_date=m.get('release_date'),release_date_source=m.get('release_date_source'),release_date_verified=m.get('release_date_verified',False),
        display_label=m['marketplace']+' published '+('market price' if r['source_field']=='marketPrice' else '7-day average' if r['source_field']=='avg7' else 'average (period unspecified)')+' (provider aggregate)')

def authorized(r,event):
    try:
        if r.get('kind')!='MARKET_PUBLISHED' or r.get('sample_count') is not None:return False
        ms=[m for m in mappings() if digest(m)==r.get('mapping_hash')]
        if len(ms)!=1:return False
        m=ms[0]
        if any(event.get(k)!=m[k] or r.get(k)!=m[k] for k in BIND):return False
        if any(str(event.get(k,''))!=v for k,v in m['event_identity'].items()):return False
        if any(r.get(k)!=m.get(k) for k in ('provider','marketplace','source_id','source_name','variant','release_date','release_date_source')):return False
        if r.get('release_date_verified',False)!=m.get('release_date_verified',False):return False
        expected_source=card_url(m['source_id']) if m['provider']=='tcgdex' else GUIDE
        fields={'marketPrice'} if m['marketplace']=='tcgplayer' else ({'avg7','avg'} if m['provider']=='cardmarket' else {'avg7'})
        start,end=stamp(r['source_updated_at']),stamp(r['expires_at'])
        return r.get('source')==expected_source and r.get('source_field') in fields and start<=now()<end<=start+timedelta(hours=72) and bool(money(r['amount']))
    except (ValueError,TypeError,KeyError,OSError,ArithmeticError):return False

def matched(event):return [dict(r) for r in _references if authorized(r,event)]

def atomic_write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix=path.name+'.')
    try:
        with os.fdopen(fd,'w') as f:json.dump(data,f,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

async def fetch(client,url):
    async with client.get(url,allow_redirects=False) as response:
        if response.status!=200:raise ValueError('HTTP_'+str(response.status))
        body=bytearray()
        async for part in response.content.iter_chunked(65536):
            body.extend(part)
            if len(body)>80000000:raise ValueError('RESPONSE_TOO_LARGE')
        return json.loads(body)

def session():return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60),trust_env=False,cookie_jar=aiohttp.DummyCookieJar(),headers={'User-Agent':'LotusTracker/1.7.0'})

async def refresh():
    global _references
    ms=mappings();out=[];errors=[];memo={}
    if ms:
        async with session() as client:
            for m in ms:
                key=(m['provider'],m['source_id'] if m['provider']=='tcgdex' else 'sealed')
                try:
                    if key not in memo:
                        await asyncio.sleep(1.5)
                        memo[key]=card_rows(await fetch(client,card_url(key[1])),key[1]) if key[0]=='tcgdex' else sealed_rows(await fetch(client,CATALOG),await fetch(client,GUIDE))
                    rows=[r for r in memo[key] if all(r.get(k)==m.get(k) for k in ('source_id','marketplace','variant'))]
                    if len(rows)!=1:raise ValueError('EXACT_PRICE_NOT_FOUND')
                    out.append(bind(m,rows[0]))
                except Exception as e:
                    memo.setdefault(key,[])
                    reason=str(e) if type(e)==ValueError and re.fullmatch('[A-Z0-9_]+',str(e)) else type(e).__name__
                    errors.append({'mapping_hash':digest(m),'reason':reason})
    atomic_write(cache_path(),out);_references=out
    return {'mappings':len(ms),'references':len(out),'errors':errors,'alerts_sent':0,'state':'REFRESHED' if ms else 'EXACT_MAPPINGS_REQUIRED'}

async def worker():
    global _references
    while True:
        try:print('LOTUS PUBLIC MARKET | '+json.dumps(await refresh()),flush=True)
        except Exception as e:
            _references=[]
            print('LOTUS PUBLIC MARKET | '+json.dumps({'state':'REFRESH_FAILED','error':type(e).__name__}),flush=True)
        await asyncio.sleep(21600)

def start(bot):
    task=getattr(bot,'public_market_task',None)
    if task is None or task.done():bot.public_market_task=asyncio.create_task(worker())
