"""Convert reviewed actual-sale records to existing exact-product market references.
No scraping, seller details, asking-price averages or inferred unit conversions.
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import hashlib, json, re
from urllib.parse import urlsplit
from app.deal_references import _BIND
from app.marketplaces.foundation import MINIMUM_TIERS
from app.marketplaces.price_sources import positive

HOSTS={'ebay':{'ebay.com'},'mercari_us':{'mercari.com'},'buyee_jp':{'buyee.jp'},
       'tcgplayer':{'tcgplayer.com'},'cardmarket':{'cardmarket.com'}}
CURRENCIES={'ebay':'USD','mercari_us':'USD','buyee_jp':'JPY','tcgplayer':'USD','cardmarket':'EUR'}

def timestamp(v):
    d=datetime.fromisoformat(str(v).replace('Z','+00:00'))
    if d.tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
    return d

def source_url(url,market):
    p=urlsplit(str(url))
    if (p.scheme!='https' or (p.hostname or '').removeprefix('www.') not in HOSTS[market]
        or p.username or p.password or p.port not in (None,443)):
        raise ValueError('SOURCE_URL_MISMATCH')
    return str(url)

def reference(document,now=None):
    now=now or datetime.now(timezone.utc)
    if not isinstance(document,dict) or document.get('reviewed') is not True:raise ValueError('REVIEW_REQUIRED')
    market=document.get('marketplace')
    if market not in MINIMUM_TIERS:raise ValueError('UNSUPPORTED_MARKET')
    product=document.get('product',{})
    if any(not isinstance(product.get(k),str) or not product[k].strip() or product[k]=='UNKNOWN' for k in _BIND):
        raise ValueError('EXACT_RETAIL_PRODUCT_BINDING_REQUIRED')
    if product['currency']!=CURRENCIES[market]:raise ValueError('CURRENCY_MISMATCH')
    identity=document.get('identity')
    fields=('product_id','language','condition','finish','unit','quantity','currency','region')
    if not isinstance(identity,dict) or any(identity.get(k) in (None,'','UNKNOWN') for k in fields):raise ValueError('EXACT_SALE_IDENTITY_REQUIRED')
    if (isinstance(identity['quantity'],bool) or not isinstance(identity['quantity'],int) or identity['quantity']<1
        or identity['currency']!=product['currency'] or identity['region']!=product['region']):raise ValueError('UNIT_OR_REGION_MISMATCH')
    rows=document.get('sales')
    if not isinstance(rows,list) or not 5<=len(rows)<=500:raise ValueError('REQUIRE_5_TO_500_ACTUAL_SALES')
    seen={};times=[]
    for row in rows:
        if not isinstance(row,dict) or row.get('identity')!=identity:raise ValueError('SALE_IDENTITY_MISMATCH')
        if row.get('price_basis')!='ACTUAL_SOLD_ITEM' or row.get('reviewed') is not True:raise ValueError('ACTUAL_SOLD_ITEM_PRICE_REQUIRED')
        # Hidden accepted offers must not use the crossed-out asking price.
        if row.get('hidden_offer') is True:raise ValueError('HIDDEN_OFFER_PRICE_NOT_ACCEPTED')
        value=positive(row.get('amount'));sale_id=str(row.get('sale_id',''))
        if value is None or not re.fullmatch(r'[A-Za-z0-9:_-]{1,128}',sale_id):raise ValueError('SALE_ID_AND_PRICE_REQUIRED')
        source_url(row.get('source'),market)
        at=timestamp(row.get('sold_at'))
        if not 0<=(now-at).total_seconds()<=14*86400:raise ValueError('SALE_OUTSIDE_LAST_14_DAYS')
        key=hashlib.sha256((market+':'+sale_id).encode()).hexdigest()
        fact=(Decimal(value),at.isoformat())
        if key in seen and seen[key]!=fact:raise ValueError('CONFLICTING_DUPLICATE_SALE')
        seen[key]=fact;times.append(at)
    if len(seen)<5:raise ValueError('INSUFFICIENT_DISTINCT_SALES')
    source=source_url(document.get('source'),market)
    expiry=min(now+timedelta(days=7),min(times)+timedelta(days=14))
    if expiry<=now:raise ValueError('BENCHMARK_ALREADY_EXPIRED')
    out=dict(product,reviewed=True,kind='MARKET_SOLD',scope='EXACT_PRODUCT',confidence='HIGH',
        amount=str(sum(v[0] for v in seen.values())/len(seen)),source=source,
        captured_at=now.isoformat(),expires_at=expiry.isoformat(),sample_count=len(seen),
        marketplace=market,comparison_basis='ITEM_ONLY',sample_unit='DISTINCT_ACTUAL_SALES',
        import_method='REVIEWED_SOLD_IMPORT1',sale_record_hashes=sorted(seen),
        sale_identity=identity)
    if document.get('release_date_verified') is True:
        from datetime import date
        date.fromisoformat(document['release_date'])
        if not str(document.get('release_date_source','')).startswith('https://'):raise ValueError('RELEASE_SOURCE_REQUIRED')
        out.update({k:document[k] for k in ('release_date','release_date_source','release_date_verified')})
    return out
