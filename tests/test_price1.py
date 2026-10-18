import ast
import copy
from datetime import datetime,timezone,timedelta
from pathlib import Path
import unittest
from app.price_policy import classify,destination,PRICE_EVENTS
from app.marketplaces.opportunity import evaluate

class PriceTest(unittest.TestCase):
    def event(self,**kw):
        e=dict(event_type='PRICE_DROP',price=90,old_price=100,currency='USD',product_family='GLOBAL_STANDARD',region='US',in_stock=True,source_type='shopify')
        e.update(kw); return e
    def ref(self): return dict(amount=100,currency='USD',scope='EXACT_PRODUCT',confidence='HIGH',kind='MSRP',source='Publisher fixture',region='US',family='GLOBAL_STANDARD')
    def test_increase_and_tiny_drop(self):
        self.assertEqual(classify(self.event(event_type='PRICE_INCREASE',price=101)),'HISTORY_ONLY')
        self.assertEqual(classify(self.event(price='99.99')),'PRICE_DROP')
        self.assertEqual(classify(self.event(price='99.999999')),'ROUNDING_ONLY')
        self.assertEqual(classify(self.event(old_currency='CAD')),'CURRENCY_CHANGED')
    def test_deal_boundary_and_evidence(self):
        self.assertEqual(classify(self.event(reference_evidence=self.ref())),'DEAL')
        self.assertEqual(classify(self.event(price='90.01',reference_evidence=self.ref())),'BELOW_MSRP')
        for field,value in [('scope','GAME_DEFAULT'),('currency','JPY'),('family','JP'),('confidence','LOW'),('region','CA')]:
            r=self.ref();r[field]=value
            self.assertEqual(classify(self.event(reference_evidence=r)),'PRICE_DROP')
        self.assertEqual(classify(self.event(in_stock=False,reference_evidence=self.ref())),'PRICE_DROP')
    def test_channels_no_fallback(self):
        env={k:str(i+1) for i,k in enumerate(['CHANNEL_PRICE_DROPS','CHANNEL_GLOBAL_PRICE_DROPS','CHANNEL_DEALS','CHANNEL_GLOBAL_DEALS','CHANNEL_CASE_SEALED_DEALS'])}
        self.assertEqual(destination(self.event(),env)['channel_id'],1)
        self.assertEqual(destination(self.event(region='JP'),env)['channel_id'],2)
        self.assertEqual(destination(self.event(reference_evidence=self.ref()),env)['channel_id'],3)
        r=self.ref();r.update(region='JP',family='JP')
        self.assertEqual(destination(self.event(region='JP',product_family='JP',reference_evidence=r),env)['channel_id'],4)
        self.assertEqual(destination(self.event(product_type='CASE',reference_evidence=self.ref()),env)['channel_id'],5)
        self.assertIsNone(destination(self.event(),{})['channel_id'])
    def test_serialization_preserves_reference(self):
        from app.events import ProductEvent, ProductEventType
        tree=ast.parse(Path('app/event_service.py').read_text())
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'enum_value','serialize_product_event'}]
        ns={'ProductEvent':ProductEvent,'ProductEventType':ProductEventType}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'serialization','exec'),ns)
        e=ProductEvent(event_type=ProductEventType.PRICE_DROP,game='Pokemon',product_name='Fixture',store_name='Fixture',product_url='https://example.com/item',price=90,old_price=100,reference_evidence=self.ref())
        self.assertEqual(ns['serialize_product_event'](e)['reference_evidence'],self.ref())

    def test_actual_worker_route_blocks_increases(self):
        source=Path('app/worker.py').read_text()
        tree=ast.parse(source);node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='determine_alert_route')
        ns={'PRICE_EVENTS':PRICE_EVENTS,'classify_price':classify}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'worker-route','exec'),ns)
        for source in ['shopify','woocommerce','major_retailer','pokemon_center']:
            self.assertIsNone(ns['determine_alert_route'](self.event(event_type='PRICE_INCREASE',source_type=source)))
            self.assertIsNotNone(ns['determine_alert_route'](self.event(source_type=source)))

class AuctionTest(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,13,22,tzinfo=timezone.utc)
        self.row=dict(marketplace='ebay',auction=True,minimum_next_bid=80,currency='USD',observed_at=self.now.isoformat(),ends_at=(self.now+timedelta(minutes=10)).isoformat(),comparison=dict(verified=True,exact_match=True,basis='SOLD',source='Fixture',sample_count=5,as_of=self.now.isoformat(),currency='USD',amount=100),purchase_costs=dict(verified=True,complete=True,fixed=10,tax_rate=0,currency='USD',mode='SHIP_HOME'))
    def test_auction_boundaries(self):
        r=evaluate(self.row,self.now);self.assertTrue(r['eligible']);self.assertEqual(r['maximum_item_bid'],'80.00');self.assertEqual(r['alerts_sent'],0)
        self.row['minimum_next_bid']=80.01;self.assertFalse(evaluate(self.row,self.now)['eligible'])
        self.row['minimum_next_bid']=80
        for minutes in [0,11]:
            self.row['ends_at']=(self.now+timedelta(minutes=minutes)).isoformat();self.assertFalse(evaluate(self.row,self.now)['eligible'])
    def test_evidence_and_vault(self):
        self.row['purchase_costs'].update(mode='KEEP_VAULTED',fixed=0)
        self.assertFalse(evaluate(self.row,self.now)['eligible'])
        self.row['purchase_costs']['vault_eligibility_verified']=True
        self.assertTrue(evaluate(self.row,self.now)['eligible'])
        self.row['comparison']['sample_count']=1
        self.assertFalse(evaluate(self.row,self.now)['eligible'])
    def test_buyee_and_fixed_price(self):
        self.row['marketplace']='buyee_jp';r=evaluate(self.row,self.now)
        self.assertEqual(r['minimum_tier'],'Premium+');self.assertEqual(r['destination_variable'],'CHANNEL_BUYEE_AUCTIONS')
        self.row.update(marketplace='mercari_us',auction=False,price=80)
        self.assertTrue(evaluate(self.row,self.now)['eligible'])
        self.row['purchase_costs']['complete']=False
        self.assertFalse(evaluate(self.row,self.now)['eligible'])

if __name__=='__main__': unittest.main()
