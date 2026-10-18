import copy
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from sqlalchemy.ext.asyncio import create_async_engine
from app.distributor_catalog import parse,record,SEEDS
from app.distributor_references import install,matched
from app.deal_references import enrich
from app.price_policy import classify
from app.distributor_sync import ensure,save,load_cache,state,refresh
from app.marketplaces.ebay_identity import multi_field_identity
from app.marketplaces.ebay_live_policy import assess
from app.marketplaces.ebay_snapshot import apply_151_snapshot
from lotus_ebay_setup import PRESET

NOW=datetime.now(timezone.utc)
def row(**kw):
    r=record('https://www.phdgames.com/2026/10/15/test/','SKU123','Pokemon Test Booster Box','100',(NOW+timedelta(days=10)).date().isoformat(),'PHD');r.update(kw);return r

def event(**kw):
    e=dict(event_type='DEAL',product_url='https://example.com/test',product_name='Pokemon Test Booster Box',product_type='Booster Box',game='Pokemon',currency='USD',region='US',product_family='GLOBAL_STANDARD',in_stock=True,price='95');e.update(kw);return e

class CatalogTests(unittest.TestCase):
    def tearDown(self):install([],[])
    def test_phd_articles_only_and_sku_separation(self):
        html='<h2>Pokemon Test Booster Box</h2><p>Publisher: Pokemon</p><p>Item Code: SKU123</p><p>MSRP: $100.00</p><p>Releases November 1, 2026</p><h2>Pokemon Test Booster Bundle</h2><p>Publisher: Pokemon</p><p>Item Code: SKU456</p><p>MSRP: $25.00</p><p>Releases November 2, 2026</p>'
        rows,_=parse('https://www.phdgames.com/2026/10/15/test/',html)
        self.assertEqual([r['amount'] for r in rows],['100.00','25.00']);self.assertEqual([r['release_date'] for r in rows],['2026-11-01','2026-11-02'])
        self.assertEqual(parse(SEEDS['phd'],html)[0],[])
    def test_acd_embedded_json_not_base_price(self):
        product=dict(sku='ABC',name='Pokemon Test Booster Box',path='/test/',prices={'basePrice':{'value':40,'currencyCode':'USD'},'retailPrice':{'value':100,'currencyCode':'USD'}},customFields=[{'name':'release_date','value':'20261101'}])
        payload='1:'+json.dumps({'data':json.dumps({'products':[product]})})
        html='<script>self.__next_f.push('+json.dumps([1,payload])+')</script>'
        rows,_=parse(SEEDS['acd'],html);self.assertEqual(rows[0]['amount'],'100');self.assertTrue(rows[0]['ready'])
        product['name']='Pokemon Starter Deck Assortment (6)';payload='1:'+json.dumps(product)
        rows,_=parse(SEEDS['acd'],'self.__next_f.push('+json.dumps([1,payload])+')');self.assertFalse(rows[0]['ready'])
    def test_gts_unit_and_case_codes(self):
        p=dict(sku='ABC',name='Pokemon Test Booster Box',link='pc_product_detail.asp?key=ABC',release_date_display='11/01/2026',uomPrice=[{'isDefault':True,'SRetailPrice':100,'price':50}],opt5='UPC (ea): 123456789012~UPC (dsp): 123456789029~UPC (cs): 123456789036',searchfields={'x':{'label':'Configurations','value':'12 boxes/case'}})
        rows,_=parse(SEEDS['gts'],'var productResults = '+json.dumps({'products':[p]}))
        self.assertEqual(rows[0]['gtins'],['123456789029']);self.assertEqual(rows[0]['case_quantity'],12);self.assertEqual(rows[0]['amount'],'100')
    def test_enrichment_reaches_actual_policy(self):
        install([row()],[])
        with patch('app.deal_references.load',return_value=[]):e=enrich(event())
        self.assertEqual(classify(e),'BELOW_MSRP');self.assertEqual(e['reference_evidence']['references'][0]['source_sku'],'SKU123')
    def test_exact_sku_and_wrong_packaging(self):
        e=event(product_name='Pokemon Alternate Test Booster Box')
        install([row()],[dict(e,sku='SKU123')]);self.assertEqual(len(matched(e)),1)
        e['product_type']='Booster Bundle';self.assertEqual(matched(e),[])
    def test_sku_does_not_override_multiple_boxes(self):
        for title in ('Pokemon Test Two Booster Boxes', 'Pokemon Test Set of 2 Booster Boxes', 'Pokemon Test Lot of Booster Boxes'):
            e=event(product_name=title)
            install([row()],[dict(e,sku='SKU123')])
            self.assertEqual(matched(e),[])
    def test_search_rotation_covers_both_result_sets(self):
        import ast
        source=Path(__file__).resolve().parents[1]/'app/marketplaces/ebay_live.py'
        tree=ast.parse(source.read_text())
        selection=next(n.value for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='selected' for t in n.targets))
        code=compile(ast.Expression(selection),'<selection>','eval')
        visited={0:set(),1:set()}
        for index in range(1,81,2):
            visited[((index-1)//2)%2].update(eval(code,{'index':index,'targets':[{}],'candidates':list(range(20))}))
        self.assertEqual(visited,{0:set(range(20)),1:set(range(20))})
    def test_no_cross_region_currency_or_fuzzy(self):
        install([row()],[])
        for changes in ({'currency':'CAD'},{'region':'JP'},{'product_family':'JP'},{'product_name':'Pokemon Different Booster Box'}):self.assertEqual(matched(event(**changes)),[])
    def test_conflict_expiry_and_no_stock_inference(self):
        install([row(),row(amount='99')],[]);self.assertEqual(matched(event()),[])
        install([row(expires_at=(NOW-timedelta(seconds=1)).isoformat())],[]);self.assertEqual(matched(event()),[])
        install([row()],[])
        with patch('app.deal_references.load',return_value=[]):e=enrich(event(in_stock=False))
        self.assertEqual(classify(e),'NO_VERIFIED_DECREASE')
    def test_case_calculation_and_no_game_wide_assumption(self):
        e=event(product_name='Pokemon Test Booster Box Sealed Case 12 Boxes',product_type='CASE',price='1100')
        install([row(case_quantity=12)],[]);refs=matched(e);self.assertEqual(refs[0]['amount'],'1200')
        e['reference_evidence']=refs[0];self.assertEqual(classify(e),'BELOW_MSRP')
        install([row(case_quantity=None)],[]);self.assertEqual(matched(e),[])
    def test_after_30_never_msrp(self):
        install([row(release_date='2020-01-01')],[])
        with patch('app.deal_references.load',return_value=[]):e=enrich(event(price='1'))
        self.assertEqual(classify(e),'NO_VERIFIED_DECREASE')

class PersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_database_persistence_and_upsert(self):
        with tempfile.TemporaryDirectory() as d:
            url='sqlite+aiosqlite:///'+str(Path(d)/'evidence.db');engine=create_async_engine(url)
            await ensure(engine);await save(engine,'phd',[row()],{'state':'OK'});await save(engine,'phd',[row(amount='101')],{'state':'OK'})
            await engine.dispose();engine=create_async_engine(url);rows=await load_cache(engine)
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['amount'],'101');self.assertEqual((await state(engine,'phd'))['state'],'OK')
            await engine.dispose();install([],[])
    async def test_refresh_persists_and_loads_retailer_matches(self):
        from sqlalchemy import text
        engine=create_async_engine('sqlite+aiosqlite:///:memory:');await ensure(engine)
        async with engine.begin() as c:
            for sql in (
                'CREATE TABLE stores(id INTEGER,region TEXT)',
                'CREATE TABLE products(id INTEGER,name TEXT,game TEXT,product_type TEXT,product_family TEXT)',
                'CREATE TABLE store_products(product_id INTEGER,store_id INTEGER,url TEXT,sku TEXT,currency TEXT,last_seen_at TEXT)',
                "INSERT INTO stores VALUES(1,'US')",
                "INSERT INTO products VALUES(1,'Pokemon Alternate Test Booster Box','Pokemon','Booster Box','GLOBAL_STANDARD')",
                "INSERT INTO store_products VALUES(1,1,'https://example.com/test','SKU123','USD','2026-10-18')",
            ):await c.execute(text(sql))
        product=dict(sku='SKU123',name='Pokemon Test Booster Box',path='/test/',prices={'retailPrice':{'value':100,'currencyCode':'USD'}},customFields=[{'name':'release_date','value':(NOW+timedelta(days=10)).date().isoformat()}])
        html='self.__next_f.push('+json.dumps([1,'1:'+json.dumps(product)])+')'
        async def fake(session,url):return (html,'OK') if url==SEEDS['acd'] else (None,'HTTP_429')
        results=await refresh(engine,fetcher=fake)
        self.assertEqual(next(r for r in results if r['source']=='acd')['coverage'],'FIRST_CATALOG_PAGE_ONLY')
        self.assertEqual(matched(event(product_name='Pokemon Alternate Test Booster Box'))[0]['amount'],'100')
        await engine.dispose();install([],[])
    async def test_phd_throttling_keeps_unprocessed_queue(self):
        engine=create_async_engine('sqlite+aiosqlite:///:memory:');await ensure(engine)
        urls=['https://www.phdgames.com/2026/10/15/product-'+str(i)+'/' for i in range(3)]
        async def fake(session,url):
            if url==SEEDS['phd']:return ''.join('<a href="'+u+'">item</a>' for u in urls),'OK'
            return None,'HTTP_429'
        with patch('app.distributor_sync.asyncio.sleep'):
            await refresh(engine,fetcher=fake)
        self.assertEqual(set((await state(engine,'phd'))['queue']),set(urls))
        await engine.dispose();install([],[])
    async def test_refresh_http_failure_isolated_and_persisted(self):
        engine=create_async_engine('sqlite+aiosqlite:///:memory:');await ensure(engine)
        async def fake(session,url):return None,'HTTP_429'
        result=await refresh(engine,fetcher=fake)
        self.assertEqual(len(result),3);self.assertTrue(all(r['state']=='HTTP_429' and r['requests']==1 for r in result))
        self.assertEqual(await refresh(engine,fetcher=fake),[])
        await engine.dispose();install([],[])

class EbayIdentityTests(unittest.TestCase):
    def fixture(self):
        t=apply_151_snapshot(copy.deepcopy(PRESET));t['reviewed']=True
        i=dict(itemId='v1|123456789012|0',title='Pokemon TCG Scarlet & Violet 151 Booster Bundle Sealed English - 6 Booster Packs',conditionId='1000',
            localizedAspects=[{'name':'Language','value':'English'},{'name':'Configuration','value':'Box'},{'name':'Game','value':'Pokémon TCG'}],
            itemLocation={'country':'US'},seller={'username':'test','feedbackScore':100,'feedbackPercentage':'99'},buyingOptions=['FIXED_PRICE'],
            price={'value':'100','currency':'USD'},estimatedAvailabilities=[{'estimatedAvailabilityStatus':'IN_STOCK'}],itemWebUrl='https://www.ebay.com/itm/123456789012')
        return i,t
    def test_missing_gtin_multifield_reaches_price(self):
        i,t=self.fixture();r=assess(i,t,datetime(2026,10,16,12,tzinfo=timezone.utc));self.assertTrue(r['eligible']);self.assertEqual(r['identity_method'],'MULTI_FIELD_151')
        i['price']['value']='174.99';self.assertFalse(assess(i,t,datetime(2026,10,16,12,tzinfo=timezone.utc))['eligible'])
    def test_title_only_and_incomplete_aspects_fail(self):
        i,t=self.fixture();i['localizedAspects']=[];self.assertFalse(multi_field_identity(i,t))
    def test_conflicting_gtin_never_overridden(self):
        i,t=self.fixture();i['gtin']='999999999999';self.assertEqual(assess(i,t)['reason'],'GTIN_MISMATCH')
    def test_lot_stock_and_seller_still_block(self):
        for change in ({'title':'Pokemon 151 Booster Bundle English Sealed Two Boxes - 6 Booster Packs'},{'estimatedAvailabilities':[]},{'seller':{'username':'test','feedbackScore':1,'feedbackPercentage':'99'}}):
            i,t=self.fixture();i.update(change);self.assertFalse(assess(i,t,datetime(2026,10,16,12,tzinfo=timezone.utc))['eligible'])
    def test_not_other_targets(self):
        i,t=self.fixture();t['id']='different';self.assertFalse(multi_field_identity(i,t))
