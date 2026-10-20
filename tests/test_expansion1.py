import copy
import json
import unittest
from unittest.mock import AsyncMock,patch
from app.pbandai_public import parse_search,fetch_catalog
from app.public_retailer_pages import parse_product,product_url
from app.marketplaces.ebay_search_plan import DetailRotation,discovery_plan,GAME_QUERIES
from app.scan_capacity import shopify_scan_capacity

def bandai(code='N9065181002'):
    return {'productCode':code,'areaCode':'US','displayStatus':'On',
        'productName':{'en':'ONE PIECE CARD GAME OP-17 Booster Box'},
        'fixedListPrice':{'amount':120,'currency':'USD'},'saleStatus':'End',
        'flags':['PRE_ORDER_CLOSED'],'productImages':[]}

def payload(rows,total=None):
    return {'productResults':{'totalCount':len(rows) if total is None else total,'products':rows}}

URL='https://www.gamestop.com/toys-games/trading-cards/products/pokemon-trading-card-game-perfect-order-elite-trainer-box/438990.html'
def product():
    return {'@type':'Product','url':URL,'name':'Pokemon Perfect Order Elite Trainer Box',
        'offers':[{'@type':'Offer','seller':{'name':'GameStop'},'price':'84.99','priceCurrency':'USD',
                   'availability':'https://schema.org/InStock'}]}
def html(row):return '<script type="application/ld+json">'+json.dumps(row)+'</script>'

class BandaiTests(unittest.TestCase):
    def test_observed_closed_product(self):
        r=parse_search(payload([bandai()]))['products'][0]
        self.assertEqual(r['price'],'120');self.assertFalse(r['availability_known'])
        self.assertEqual(r['availability_state'],'UNKNOWN')
    def test_lottery_and_open_are_not_stock(self):
        r=bandai();r.update(saleStatus='On',flags=['CHANCE_TO_BUY_DRAWING','PRE_ORDER'])
        x=parse_search(payload([r]))['products'][0]
        self.assertTrue(x['lottery']);self.assertFalse(x['availability_known'])
    def test_wrong_region_currency_and_invalid_price(self):
        for field,value in [('areaCode','JP'),('displayStatus','Off')]:
            row=bandai();row[field]=value;self.assertEqual(parse_search(payload([row]))['rejected'],1)
        for amount in [0,True,'NaN','Infinity',None]:
            row=bandai();row['fixedListPrice']['amount']=amount
            self.assertEqual(parse_search(payload([row]))['rejected'],1)
        row=bandai();row['fixedListPrice']['currency']='JPY'
        self.assertEqual(parse_search(payload([row]))['rejected'],1)
    def test_count_alone_never_product(self):
        with self.assertRaises(ValueError):parse_search({'productResults':{'totalCount':100}})
    def test_duplicate_product_rejected(self):
        self.assertEqual(parse_search(payload([bandai(),bandai()]))['rejected'],1)
    def test_same_count_replacement_visible(self):
        a=parse_search(payload([bandai('FIRST')]))
        b=parse_search(payload([bandai('SECOND')]))
        self.assertEqual(a['total_count'],b['total_count'])
        self.assertNotEqual(a['products'][0]['id'],b['products'][0]['id'])

class CatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_pages_no_first_page_baseline(self):
        pages=[parse_search(payload([bandai(str(i)) for i in range(100)],101)),
               parse_search(payload([bandai('last')],101))]
        with patch('app.pbandai_public.fetch_page',AsyncMock(side_effect=pages)),patch('app.pbandai_public.asyncio.sleep',AsyncMock()):
            result=await fetch_catalog(None)
        self.assertEqual(len(result['products']),101);self.assertTrue(result['complete'])
    async def test_incomplete_and_changed_catalog_fail(self):
        for pages in [[parse_search(payload([bandai()],101))],
                      [parse_search(payload([bandai(str(i)) for i in range(100)],101)),parse_search(payload([bandai('last')],102))]]:
            with patch('app.pbandai_public.fetch_page',AsyncMock(side_effect=pages)),patch('app.pbandai_public.asyncio.sleep',AsyncMock()):
                with self.assertRaises(ValueError):await fetch_catalog(None)

class PublicPageTests(unittest.TestCase):
    def test_exact_direct_offer_price_only(self):
        result=parse_product('gamestop',URL,html(product()))
        self.assertEqual(result['price'],'84.99');self.assertFalse(result['availability_known'])
    def test_wrong_product_or_duplicate(self):
        row=product();row['url']=URL.replace('438990','438991')
        with self.assertRaises(ValueError):parse_product('gamestop',URL,html(row))
        with self.assertRaises(ValueError):parse_product('gamestop',URL,html([product(),product()]))
    def test_other_seller_and_conditional_price(self):
        for key,value in [('seller',{'name':'Other Seller'}),('priceSpecification',{'price':1}),
                          ('priceCurrency','EUR'),('price','NaN'),('@type','AggregateOffer')]:
            row=product();row['offers'][0][key]=value
            with self.assertRaises(ValueError):parse_product('gamestop',URL,html(row))
    def test_multiple_offers(self):
        row=product();row['offers'].append(copy.deepcopy(row['offers'][0]))
        with self.assertRaises(ValueError):parse_product('gamestop',URL,html(row))
    def test_urls_reject_unrelated_hosts_and_search(self):
        for url in ['http://www.gamestop.com/products/438990.html',
                    'https://www.gamestop.com.evil.test/products/438990.html',
                    'https://user@www.gamestop.com/products/438990.html',
                    'https://www.gamestop.com/search?q=pokemon']:
            with self.assertRaises(ValueError):product_url('gamestop',url)

class RotationTests(unittest.TestCase):
    def test_details_rotate_after_cache_expiry(self):
        plan=DetailRotation();rows=[{'itemId':str(i),'seller':'never retain'} for i in range(10)]
        plan.put('key',rows,now=0)
        self.assertEqual([r['itemId'] for r in plan.take('key')],['0','1','2'])
        self.assertIsNone(plan.get('key',now=300))
        plan.put('key',rows,now=300)
        self.assertEqual([r['itemId'] for r in plan.take('key')],['3','4','5'])
        self.assertNotIn('seller',str(plan.cache))
    def test_small_results_no_duplicate_detail(self):
        plan=DetailRotation();plan.put('x',[{'itemId':'1'},{'itemId':'1'}],now=0)
        self.assertEqual(len(plan.take('x')),1)
    def test_discovery_covers_games_and_pages(self):
        self.assertEqual(len({discovery_plan(i)[0] for i in range(len(GAME_QUERIES))}),len(GAME_QUERIES))
        self.assertEqual(discovery_plan(2*len(GAME_QUERIES))[1]['offset'],'100')
        self.assertEqual(discovery_plan(len(GAME_QUERIES))[1]['sort'],'price')
    def test_cache_bounded(self):
        plan=DetailRotation(maximum=2)
        for i in range(5):plan.put(i,[{'itemId':str(i)}],now=0);plan.take(i)
        self.assertEqual(len(plan.cache),2);self.assertEqual(len(plan.cursors),2)

class ShopifyTests(unittest.TestCase):
    def test_capacity_defaults_and_bounds(self):
        self.assertEqual(shopify_scan_capacity({}),8)
        self.assertEqual(shopify_scan_capacity({'SHOPIFY_MAX_CONCURRENT_STORES':'99'}),12)
        self.assertEqual(shopify_scan_capacity({'SHOPIFY_MAX_CONCURRENT_STORES':'bad'}),8)
        self.assertEqual(shopify_scan_capacity({'SHOPIFY_MAX_CONCURRENT_STORES':'4'}),4)

class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_bandai_actual_adapter_normalizes_unknown_stock(self):
        import os
        os.environ.setdefault('DATABASE_URL','sqlite+aiosqlite:///:memory:')
        from app.major_retailers import build_major_retailer_adapter
        from app.major_retailers.pipeline import _candidate_events
        from datetime import datetime, timezone
        row=parse_search(payload([bandai()]))['products'][0]
        adapter=build_major_retailer_adapter('premium_bandai')
        with patch('app.pbandai_public.fetch_catalog',AsyncMock(return_value={
                'products':[row],'rejected':0,'pages':1,'total_count':1})):
            products=await adapter.discover_products()
        self.assertEqual(len(products),1)
        item=products[0].to_normalized_dict(adapter.capabilities)
        self.assertFalse(item['platform_data']['availability_known'])
        self.assertEqual(item['product_type'],'Booster Box')
        self.assertEqual(_candidate_events(old=None,item=item,baseline_seed=True,now=datetime.now(timezone.utc)),[])
        events=_candidate_events(old=None,item=item,baseline_seed=False,now=datetime.now(timezone.utc))
        self.assertEqual(events,[{'event_type':'PAGE_LIVE'}])
    async def test_actual_ebay_worker_checks_three_details(self):
        from app.marketplaces import ebay_live
        from types import SimpleNamespace
        target={'id':'test','gtin':'820650853210','required_terms':['151'],'comparison_mode':'ITEM_ONLY'}
        closed=iter([False,True]);bot=SimpleNamespace(is_closed=lambda:next(closed))
        store=SimpleNamespace(pool=SimpleNamespace(fetchval=AsyncMock(return_value=False)),epoch=AsyncMock(return_value=0))
        leader=SimpleNamespace(fetchval=AsyncMock(return_value=1))
        api=SimpleNamespace(get=AsyncMock(side_effect=[{'itemSummaries':[{'itemId':str(i)} for i in range(3)]}]+[{'itemId':str(i)} for i in range(3)]))
        with patch.object(ebay_live,'Browse',return_value=api),patch.object(ebay_live,'cleanup',AsyncMock()),\
             patch.object(ebay_live,'load_targets',return_value=[target]),patch.object(ebay_live,'config_hash',return_value='test'),\
             patch.object(ebay_live,'assess',return_value={'eligible':False,'reason':'NOT_A_DEAL'}),\
             patch.object(ebay_live,'gtin_status',return_value={'reason':'GTIN_MISSING'}),\
             patch('app.marketplaces.ebay_live_policy.review_diagnostics',return_value={
                 'benchmark_ready':True,'item_price_threshold':'10','price_only_meets_threshold':False}),\
             patch.object(ebay_live.ebay_shadow,'record',AsyncMock()),\
             patch.object(ebay_live.ebay_shadow,'record_cycle',AsyncMock()) as record,\
             patch.object(ebay_live.asyncio,'sleep',AsyncMock()):
            await ebay_live.loop(bot,store,leader,'SHADOW')
        self.assertEqual(api.get.await_count,4)
        self.assertEqual(record.call_args.args[6],3)

if __name__=='__main__':unittest.main()
