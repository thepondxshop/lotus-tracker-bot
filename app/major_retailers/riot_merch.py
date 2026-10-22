"""Official Riot category discovery/price adapter. Stock capability deliberately off."""
import aiohttp
from app.riot_public import CATALOG,fetch,merch_rows
from .base import MajorRetailerAdapter,MajorRetailerCapabilityProfile,MajorRetailerProduct,MajorRetailerProbe
from .registry import major_retailer_adapter

@major_retailer_adapter('riot_merch')
class RiotMerch(MajorRetailerAdapter):
    retailer_key='riot_merch'
    version='1.7.3-RIOT1'
    @property
    def capabilities(self):return MajorRetailerCapabilityProfile(discovery=True,price=True,page_live=True)
    async def discover_products(self,*,limit=50):
        from app.shopify_adapter import infer_product_type,infer_product_category
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20),trust_env=True,headers={'User-Agent':'LotusTracker/1.7.3 (+https://thepondx.com)'}) as session:
            rows=merch_rows(await fetch(session,CATALOG))
        return [MajorRetailerProduct(retailer_key=self.retailer_key,external_product_id=r['id'],title=r['title'],
            game='Riftbound',url=r['url'],price=float(r['price']),currency='USD',
            lifecycle_state='PAGE_LIVE',lifecycle_confidence='HIGH',
            product_type=infer_product_type(r['title']),product_category=infer_product_category(r['title']),
            image_url=r['image_url'],source_name='RiotPublicCategory',source_confidence='HIGH',
            extra={'coverage':'FIRST_PUBLIC_CATEGORY_PAGE','stock_note':'Public catalog only; drawing/account purchase eligibility and checkout stock unverified.',
                   'reported_availability':r['reported_availability']}) for r in rows[:max(1,min(limit,100))]]
    async def healthcheck(self):
        try:
            rows=await self.discover_products()
            return MajorRetailerProbe(self.retailer_key,True,'RiotPublicCategory','HIGH',200,'PAGE_PRICE_ONLY',{'products':len(rows),'stock_verified':False,'coverage':'FIRST_PUBLIC_CATEGORY_PAGE'})
        except Exception as e:return MajorRetailerProbe(self.retailer_key,False,'RiotPublicCategory','LOW',None,str(e) if isinstance(e,ValueError) else type(e).__name__)
