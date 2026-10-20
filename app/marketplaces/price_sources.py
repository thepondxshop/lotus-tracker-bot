"""Read-only native market-price previews. No stock, sold-count, or identity inference."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
import json
import os
import re
import aiohttp


def positive(value):
    if isinstance(value,bool):return None
    try:
        n=Decimal(str(value))
        return str(n) if n.is_finite() and n>0 else None
    except (ValueError,TypeError,InvalidOperation):return None


def ids(values):
    result=list(dict.fromkeys(str(v).strip() for v in values))
    if not result or len(result)>50 or any(not re.fullmatch(r'[1-9][0-9]{0,11}',v) for v in result):
        raise ValueError('Provide 1–50 positive numeric product/SKU IDs')
    return result


def tcgplayer_prices(data, requested, sku=False):
    wanted=set(ids(requested));key='skuId' if sku else 'productId'
    if not isinstance(data,dict) or data.get('success') is not True or not isinstance(data.get('results'),list):
        raise ValueError('TCGPLAYER_RESPONSE_INVALID')
    out=[]
    for row in data['results']:
        if not isinstance(row,dict) or str(row.get(key)) not in wanted:continue
        price=positive(row.get('marketPrice'))
        if price:
            out.append(dict(marketplace='tcgplayer',minimum_tier='Premium',
                identifier=str(row[key]),identifier_type=key,subtype=row.get('subTypeName'),
                amount=price,currency='USD',basis='PUBLISHED_MARKET_PRICE',
                sample_count=None,stock_verified=False,exact_identity_verified=False,
                alert_eligible=False,review_required=True))
    return out


def cardmarket_prices(data, requested, foil=False):
    wanted=set(ids(requested))
    if not isinstance(data,dict) or not isinstance(data.get('priceGuides'),list):
        raise ValueError('CARDMARKET_PRICE_GUIDE_SCHEMA_UNVERIFIED')
    field='avg7-foil' if foil else 'avg7';out=[]
    for row in data['priceGuides']:
        if not isinstance(row,dict) or str(row.get('idProduct')) not in wanted:continue
        value=positive(row.get(field))
        if value:
            out.append(dict(marketplace='cardmarket',minimum_tier='Premium+',
                identifier=str(row['idProduct']),identifier_type='idProduct',foil=foil,
                amount=value,currency='EUR',basis='PUBLISHED_7_DAY_AVERAGE',
                source_field=field,source_created_at=data.get('createdAt'),
                sample_count=None,language='UNVERIFIED',condition='UNVERIFIED',
                stock_verified=False,exact_identity_verified=False,alert_eligible=False,review_required=True))
    return out


async def read_json(response, limit=40_000_000):
    if response.status not in (200,207):
        # No response body or token ever enters exception/log output.
        raise ValueError('SOURCE_HTTP_'+str(response.status))
    body=bytearray()
    async for chunk in response.content.iter_chunked(65536):
        body.extend(chunk)
        if len(body)>limit:raise ValueError('SOURCE_RESPONSE_TOO_LARGE')
    return json.loads(body)


async def tcgplayer_preview(requested, sku=False):
    wanted=ids(requested)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25),
            trust_env=False,cookie_jar=aiohttp.DummyCookieJar()) as session:
        token=os.getenv('TCGPLAYER_ACCESS_TOKEN','').strip()
        if not token:
            client=os.getenv('TCGPLAYER_CLIENT_ID','').strip();secret=os.getenv('TCGPLAYER_CLIENT_SECRET','').strip()
            if not client or not secret:raise ValueError('TCGPLAYER_EXISTING_API_ACCESS_REQUIRED')
            async with session.post('https://api.tcgplayer.com/token',data={
                'grant_type':'client_credentials','client_id':client,'client_secret':secret},allow_redirects=False) as r:
                auth=await read_json(r,65536)
            token=auth.get('access_token')
            if not isinstance(token,str) or not token:raise ValueError('TCGPLAYER_AUTH_RESPONSE_INVALID')
        endpoint='sku' if sku else 'product'
        async with session.get('https://api.tcgplayer.com/pricing/'+endpoint+'/'+','.join(wanted),
                headers={'Authorization':'Bearer '+token,'Accept':'application/json'},allow_redirects=False) as r:
            data=await read_json(r,1_000_000)
    return tcgplayer_prices(data,wanted,sku)


def cardmarket_url(url):
    p=urlsplit(url)
    if (p.scheme!='https' or p.hostname!='downloads.s3.cardmarket.com' or p.username or p.password
            or p.port not in (None,443) or p.query or p.fragment
            or not re.fullmatch(r'/productCatalog/priceGuide/price_guide_[1-9][0-9]*\.json',p.path)):
        raise ValueError('USE_OFFICIAL_CARDMARKET_PRICE_GUIDE_DOWNLOAD_LINK')
    return url


async def cardmarket_preview(url, requested, foil=False):
    url=cardmarket_url(url)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45),
            trust_env=False,cookie_jar=aiohttp.DummyCookieJar()) as session:
        async with session.get(url,allow_redirects=False) as r:data=await read_json(r)
    return cardmarket_prices(data,requested,foil)
