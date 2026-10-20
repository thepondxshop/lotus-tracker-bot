"""Opt-in public-page alternative for configured exact product watchlists."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import aiohttp
from app.public_retailer_pages import HOSTS, product_url, parse_product
from app.tcg_identity import title_identity, NEW_TCG
from .base import MajorRetailerAdapter, MajorRetailerCapabilityProfile, MajorRetailerProduct, MajorRetailerProbe
from .registry import register_major_retailer_adapter

def watchlist():
    path=os.getenv('PUBLIC_RETAILER_WATCHLIST_FILE','')
    if not path:return {}
    p=Path(path)
    if p.stat().st_size>131072:raise ValueError('WATCHLIST_TOO_LARGE')
    rows=json.loads(p.read_text())
    if not isinstance(rows,list) or len(rows)>40:raise ValueError('WATCHLIST_MAXIMUM_40_URLS')
    result={}
    for row in rows:
        if not isinstance(row,dict):raise ValueError('INVALID_WATCHLIST_ROW')
        key=row.get('retailer');url=product_url(key,row.get('url'))
        result.setdefault(key,[])
        if url not in result[key]:result[key].append(url)
        if len(result[key])>10:raise ValueError('MAXIMUM_TEN_URLS_PER_RETAILER')
    return result

class PublicPageAdapter(MajorRetailerAdapter):
    version='1.6.0-PUBLICPAGE1'
    @property
    def capabilities(self):
        return MajorRetailerCapabilityProfile(discovery=True,price=True,page_live=True)
    async def discover_products(self,*,limit=50):
        from app.shopify_adapter import infer_product_type, infer_product_category
        from app.product_family import detect_product_family
        urls=watchlist().get(self.retailer_key,[])
        if not urls:raise ValueError('PUBLIC_WATCHLIST_REQUIRED')
        products=[]
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5),trust_env=False,
                headers={'User-Agent':'LotusTracker/1.6 (+https://thepondx.com)','Accept':'text/html'}) as session:
            for index,url in enumerate(urls):
                if index:await asyncio.sleep(1.5)
                async with session.get(url,allow_redirects=False) as response:
                    if response.status!=200:raise ValueError('PUBLIC_PAGE_HTTP_'+str(response.status))
                    body=bytearray()
                    async for chunk in response.content.iter_chunked(16384):
                        body.extend(chunk)
                        if len(body)>4*1024*1024:raise ValueError('PAGE_TOO_LARGE')
                row=parse_product(self.retailer_key,url,body.decode('utf-8',errors='replace'))
                game=title_identity(row['title'])
                if not game or game==NEW_TCG:raise ValueError('TRACKED_GAME_IDENTITY_REQUIRED')
                products.append(MajorRetailerProduct(retailer_key=self.retailer_key,
                    external_product_id=hashlib.sha256(url.encode()).hexdigest(),
                    title=row['title'],game=game,url=url,price=float(row['price']),currency='USD',
                    product_type=infer_product_type(row['title']),product_category=infer_product_category(row['title']),
                    product_family=detect_product_family({'title':row['title']}),
                    lifecycle_state='PAGE_LIVE',lifecycle_confidence='HIGH',
                    source_name='PublicProductJSONLD',source_confidence='HIGH',
                    extra={'stock_note':row['note'],'watchlist_only':True}))
        return products
    async def healthcheck(self):
        try:
            rows=await self.discover_products()
            return MajorRetailerProbe(self.retailer_key,bool(rows),'PublicProductJSONLD','HIGH',200,
                'PUBLIC_PAGE_PRICE_VERIFIED_STOCK_UNKNOWN',{'products':len(rows),'stock_verified':False})
        except Exception as error:
            return MajorRetailerProbe(self.retailer_key,False,'PublicProductJSONLD','LOW',None,
                str(error) if isinstance(error,ValueError) else type(error).__name__)

def install():
    # Config errors fail visibly rather than silently weakening source policy.
    for key in watchlist():
        cls=type(key.title().replace('_','')+'PublicPages',(PublicPageAdapter,),{'retailer_key':key})
        register_major_retailer_adapter(key,cls)
