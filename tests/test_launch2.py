import ast
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock
from app.price_policy import classify, destination, deal_title, PRICE_EVENTS, deal_dedupe_key
from app.deal_references import load, matched, enrich
from app.marketplaces.ebay_listing_review import fingerprint, approved
from app.marketplaces.ebay_live_policy import assess
from app.marketplaces.ebay_evidence import identity_key
from app.international_channels import DESTINATIONS

NOW = datetime.now(timezone.utc)
def event(**kw):
    e = dict(event_type='DEAL', price='90', in_stock=True, currency='USD', region='US',
        product_family='GLOBAL_STANDARD', game='Pokemon', product_type='Booster Bundle',
        product_name='Pokemon 151 Booster Bundle', product_url='https://example.com/products/bundle', source_type='shopify')
    e.update(kw);return e

def ref(kind='MSRP'):
    r = event();r.pop('event_type');r.update(amount='100', kind=kind, scope='EXACT_PRODUCT', confidence='HIGH',
        family='GLOBAL_STANDARD', reviewed=True, source='https://example.com/evidence',
        captured_at=NOW.isoformat(), expires_at=(NOW+timedelta(days=2)).isoformat(), sample_count=10,release_date_verified=True,release_date=(NOW-timedelta(days=40 if kind == "MARKET_SOLD" else 5)).date().isoformat(),release_date_source='https://example.com/release')
    return r

class LaunchTests(unittest.TestCase):
    def test_new_unchanged_restock_deals(self):
        for kind in ('DEAL','STOCK_AVAILABLE','RESTOCK','DISCOVERED','PREORDER_LIVE'):
            for old in (None,'90','100'):
                self.assertEqual(classify(event(event_type=kind,old_price=old,reference_evidence=ref())),'DEAL')
    def test_increase_stock_and_currency(self):
        for change,reason in [({'event_type':'PRICE_INCREASE'},'HISTORY_ONLY'),({'in_stock':False},'NO_VERIFIED_DECREASE'),({'old_currency':'CAD'},'CURRENCY_CHANGED')]:
            self.assertEqual(classify(event(reference_evidence=ref(),**change)),reason)
    def test_market_and_dual(self):
        market=ref('MARKET_SOLD');msrp=ref();msrp['release_date']=market['release_date']
        e=event(reference_evidence={'references':[msrp,market]})
        self.assertEqual(classify(e),'DEAL');self.assertIn('BELOW MARKET',deal_title(e));self.assertNotIn('MSRP',deal_title(e))
        self.assertEqual(destination(e,{'CHANNEL_DEALS':'123'})['channel_id'],123)
    def test_invalid_market_references(self):
        for change in ({'kind':'ASKING'},{'reviewed':False},{'sample_count':True},{'sample_count':4},
                       {'expires_at':(NOW-timedelta(days=1)).isoformat()},{'region':'JP'},{'currency':'JPY'},
                       {'captured_at':(NOW+timedelta(days=1)).isoformat()}):
            r=ref('MARKET_SOLD');r.update(change)
            self.assertNotEqual(classify(event(reference_evidence=r)),'DEAL')
    def test_exact_threshold_and_history_not_reference(self):
        self.assertEqual(classify(event(reference_evidence=ref(),price='90.01')),'BELOW_MSRP')
        self.assertEqual(classify(event(event_type='PRICE_DROP',price='40',old_price='100')),'PRICE_DROP')
    def test_reference_import_and_binding(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'refs.json';p.write_text(json.dumps([ref()]))
            rows=load(p);self.assertEqual(len(matched(event(),rows)),1)
            for k,v in [('product_type','Booster Box'),('currency','CAD'),('region','JP'),('product_name','Different Edition')]:
                self.assertEqual(matched(event(**{k:v}),rows),[])
            bad=ref();bad['kind']='WHOLESALE';p.write_text(json.dumps([bad]))
            with self.assertRaises(ValueError):load(p)
    def test_tiers(self):
        self.assertEqual(DESTINATIONS['tcgplayer'][1],'Premium')
        self.assertEqual(DESTINATIONS['cardmarket'][1],'Premium+')
    def test_actual_worker_routes(self):
        tree=ast.parse(Path('app/worker.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='determine_alert_route')
        ns={'PRICE_EVENTS':PRICE_EVENTS,'classify_price':classify}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'route','exec'),ns)
        self.assertEqual(ns['determine_alert_route'](event(reference_evidence=ref())),'deal')
        self.assertIsNone(ns['determine_alert_route'](event(event_type='PRICE_INCREASE',reference_evidence=ref())))

class DedupeTest(unittest.IsolatedAsyncioTestCase):
    async def test_restock_and_deal_share_key(self):
        tree=ast.parse(Path('app/worker.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='should_suppress_duplicate')
        redis=AsyncMock();redis.set.return_value=True
        ns={'classify_price':classify,'REALTIME_EVENTS':{'RESTOCK'},'get_redis':lambda:redis,'hashlib':hashlib,'deal_dedupe_key':deal_dedupe_key}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'dedupe','exec'),ns)
        await ns['should_suppress_duplicate'](event(event_type='RESTOCK',reference_evidence=ref()))
        a=redis.set.call_args
        await ns['should_suppress_duplicate'](event(reference_evidence=ref()))
        self.assertEqual(a,redis.set.call_args);self.assertEqual(a.kwargs['ex'],120)
        ns['get_redis']=lambda:None
        self.assertTrue(await ns['should_suppress_duplicate'](event(reference_evidence=ref())))

class ReviewTests(unittest.TestCase):
    def fixture(self):
        t={'id':'test','gtin':'820650853210','condition_id':'1000','quantity':1,'aspects':{'Language':'English','Configuration':'Box'},
           'required_terms':['151','booster bundle'],'currency':'USD','comparison_mode':'ITEM_ONLY','game':'Pokemon','sold_records':[]}
        i={'itemId':'v1|123|0','title':'Pokemon 151 booster bundle','conditionId':'1000','itemLocation':{'country':'US'},
           'localizedAspects':[{'name':'Language','value':'English'},{'name':'Configuration','value':'Box'}]}
        r={'item_id':i['itemId'],'identity_key':identity_key(t),'fingerprint':fingerprint(i),'reviewed':True,
           'reviewed_at':NOW.isoformat(),'expires_at':(NOW+timedelta(days=2)).isoformat()}
        t['reviewed_listings']=[r];return i,t
    def test_review_passes_only_missing_identity(self):
        i,t=self.fixture();self.assertTrue(approved(i,t,NOW))
        self.assertEqual(assess(i,t,NOW)['reason'],'SELLER_EVIDENCE_INSUFFICIENT')
        i['gtin']='999999999999';self.assertEqual(assess(i,t,NOW)['reason'],'GTIN_MISMATCH')
    def test_listing_edit_target_edit_expiry(self):
        i,t=self.fixture();self.assertFalse(approved(i,t,NOW+timedelta(days=3)))
        for key,value in [('title','Pokemon 151 booster bundle LOT OF 2'),('itemId','other')]:
            x=copy.deepcopy(i);x[key]=value;self.assertFalse(approved(x,t,NOW))
        t['aspects']['Language']='Japanese';self.assertFalse(approved(i,t,NOW))
