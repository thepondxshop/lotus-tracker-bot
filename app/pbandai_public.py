"""Public US search contract observed October 20, 2026. No stock inference."""
import asyncio
import json
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit

URL = 'https://p-bandai.com/api/search'
PARAMS = {'keyword':'', '_f_productStatuses':'Waiting,On,End',
          '_f_categories':'04-011', 'sortType':'NewArrival', 'includeAggs':'false'}

def parse_search(data):
    block = data.get('productResults') if isinstance(data, dict) else None
    if not isinstance(block, dict): raise ValueError('PRODUCT_RESULTS_MISSING')
    total, rows = block.get('totalCount'), block.get('products')
    if type(total) is not int or total < 0 or not isinstance(rows, list):
        raise ValueError('INVALID_SEARCH_SCHEMA')
    if len(rows) > 200: raise ValueError('OVERSIZED_PRODUCT_PAGE')
    output, rejected, seen = [], 0, set()
    for row in rows:
        try:
            if not isinstance(row, dict): raise ValueError()
            code = row.get('productCode')
            if not isinstance(code,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',code): raise ValueError()
            if row.get('areaCode') != 'US' or row.get('displayStatus') != 'On': raise ValueError()
            title = row.get('productName',{}).get('en')
            price = row.get('fixedListPrice',{})
            if not isinstance(title,str) or not title.strip() or len(title)>1000: raise ValueError()
            if price.get('currency') != 'USD' or isinstance(price.get('amount'),bool): raise ValueError()
            amount = Decimal(str(price.get('amount')))
            if not amount.is_finite() or not 0 < amount < 10000000: raise ValueError()
            flags = row.get('flags',[])
            if not isinstance(flags,list) or not all(isinstance(f,str) for f in flags): raise ValueError()
            status = row.get('saleStatus')
            if status not in {'On','End','Waiting'}: raise ValueError()
            image = None
            images = row.get('productImages',[])
            if isinstance(images,list) and images and isinstance(images[0],dict):
                candidate=urljoin('https://p-bandai.com/',str(images[0].get('fileUrl','')))
                p=urlsplit(candidate)
                if p.scheme=='https' and p.hostname=='p-bandai.com' and not p.username and not p.password and p.path.startswith('/files/'):
                    image=candidate
            item={'id':code, 'title':title.strip(), 'url':'https://p-bandai.com/us/item/'+code,
                  'price':str(amount), 'currency':'USD', 'image_url':image,
                  'sale_status':status, 'flags':flags[:30],
                  'order_start':row.get('saleStartExpectedDt'), 'order_end':row.get('saleEndExpectedDt'),
                  'availability_known':False, 'availability_state':'UNKNOWN',
                  'lottery':'CHANCE_TO_BUY_DRAWING' in flags}
            if code in seen: raise ValueError('DUPLICATE_PRODUCT_ID')
            seen.add(code); output.append(item)
        except (ValueError, TypeError, AttributeError, InvalidOperation): rejected+=1
    return {'total_count':total,'products':output,'rejected':rejected,'raw_count':len(rows)}

async def fetch_page(session, *, offset=0, limit=100):
    params={**PARAMS,'offset':str(max(0,int(offset))),'limit':str(max(1,min(100,int(limit))))}
    async with session.get(URL,params=params,headers={'X-G1-Area-Code':'us',
            'User-Agent':'LotusTracker/1.6 (+https://thepondx.com)', 'Accept':'application/json'},
            allow_redirects=False) as response:
        if response.status != 200:
            # Never retry a blocked response or log response bodies/credentials.
            raise ValueError('PREMIUM_BANDAI_HTTP_'+str(response.status))
        body=bytearray()
        async for chunk in response.content.iter_chunked(16384):
            body.extend(chunk)
            if len(body)>4*1024*1024: raise ValueError('RESPONSE_TOO_LARGE')
    return parse_search(json.loads(body))

async def fetch_catalog(session):
    """Bounded full US card-category sweep; reject truncation before baseline."""
    products, ids, total = [], set(), None
    rejected=0
    for page in range(10):
        if page: await asyncio.sleep(1.5)
        result=await fetch_page(session,offset=page*100)
        if total is None: total=result['total_count']
        elif total != result['total_count']: raise ValueError('CATALOG_CHANGED_DURING_SWEEP')
        rejected+=result['rejected']
        for item in result['products']:
            if item['id'] in ids: raise ValueError('DUPLICATE_CATALOG_PAGE')
            ids.add(item['id']); products.append(item)
        if (page+1)*100 >= total:
            return {'products':products,'total_count':total,'rejected':rejected,'pages':page+1,'complete':True}
        if result['raw_count'] != 100: raise ValueError('INCOMPLETE_CATALOG_PAGE')
    raise ValueError('CATALOG_EXCEEDS_1000_PRODUCTS')
