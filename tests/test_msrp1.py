import ast
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from app.price_policy import classify, destination, deal_title, alert_matches, PRICE_EVENTS
from app.case_msrp import calculated_case_amount
NOW=datetime.now(timezone.utc)
def ref(kind='MSRP'):
    return dict(kind=kind, amount='100', scope='EXACT_PRODUCT', confidence='HIGH',currency='USD',family='GLOBAL_STANDARD',region='US',source='https://example.com/product',reviewed=True,sample_count=10,release_date_verified=True,release_date=(NOW-timedelta(days=40 if kind == "MARKET_SOLD" else 5)).date().isoformat(),release_date_source='https://example.com/release',captured_at=NOW.isoformat(),expires_at=(NOW+timedelta(days=2)).isoformat())
def event(price='99.99',kind='MSRP',**kw):
    e=dict(event_type='DEAL',price=price,in_stock=True,currency='USD',region='US',product_family='GLOBAL_STANDARD',product_type='Booster Box',reference_evidence=ref(kind));e.update(kw);return e
def case():
    r=ref();r.update(product_type='CASE',product_url='https://example.com/case',game='One Piece',product_family='GLOBAL_STANDARD',amount='1440')
    c=dict(reviewed=True,captured_at=NOW.isoformat(),expires_at=(NOW+timedelta(days=1)).isoformat())
    unit=dict(c,source='https://example.com/box',amount='120',product_id='SET-BOX',product_name='Specific set box',unit_type='BOOSTER_BOX',game='One Piece',currency='USD',region='US',product_family='GLOBAL_STANDARD')
    contents=dict(c,source='https://example.com/spec',case_product_url=r['product_url'],unit_product_id='SET-BOX',quantity=12)
    r['derivation']=dict(method='UNIT_MSRP_TIMES_CASE_QUANTITY',unit_reference=unit,case_contents=contents);return r
class MsrpTests(unittest.TestCase):
    def test_msrp_boundaries(self):
        for p,c in [('100','NO_VERIFIED_DECREASE'),('100.01','NO_VERIFIED_DECREASE'),('99.99','BELOW_MSRP'),('90.01','BELOW_MSRP'),('90','DEAL'),('89.99','DEAL')]:self.assertEqual(classify(event(p)),c)
    def test_market_threshold(self):
        self.assertEqual(classify(event('90.01','MARKET_SOLD')),'NO_VERIFIED_DECREASE');self.assertEqual(classify(event('90','MARKET_SOLD')),'DEAL')
    def test_labels_dual(self):
        self.assertNotIn('DEAL',deal_title(event()));self.assertIn('DEAL',deal_title(event('90')))
        e=event('95');m=ref('MARKET_SOLD');m['amount']='110';r=ref();r['release_date']=m['release_date'];e['reference_evidence']={'references':[r,m]}
        self.assertEqual(classify(e),'DEAL');self.assertIn('BELOW MARKET',deal_title(e));self.assertNotIn('MSRP',deal_title(e))
    def test_new_unchanged_restock(self):
        for t in ('DISCOVERED','RESTOCK','DEAL','PREORDER_LIVE'):self.assertEqual(classify(event(event_type=t,old_price='99.99')),'BELOW_MSRP')
    def test_history(self):
        self.assertEqual(classify(event('40',event_type='PRICE_DROP',old_price='100',reference_evidence=None)),'PRICE_DROP')
    def test_stock_increase_currency_singles(self):
        for kw in ({'in_stock':False},{'event_type':'PRICE_INCREASE'},{'old_currency':'CAD'},{'product_type':'Single Card'}):self.assertNotIn(classify(event(**kw)),{'DEAL','BELOW_MSRP'})
        self.assertEqual(classify(event('90','MARKET_SOLD',product_type='Single Card')),'DEAL')
    def test_routes(self):
        for region,typ,key in [('US','Booster Box','CHANNEL_DEALS'),('JP','Booster Box','CHANNEL_GLOBAL_DEALS'),('US','CASE','CHANNEL_CASE_SEALED_DEALS')]:
            e=event(region=region,product_type=typ,product_name='Pokemon Booster Box Case' if typ=='CASE' else 'Pokemon Booster Box');e['reference_evidence']['region']=region;self.assertEqual(destination(e,{key:'123'})['channel_id'],123)
    def test_untitled_case_is_not_routed_as_shipping_case(self):
        self.assertIsNone(destination(event(product_type='CASE'),{'CHANNEL_CASE_SEALED_DEALS':'123'})['channel_id'])
    def test_actual_worker_route(self):
        tree=ast.parse(Path('app/worker.py').read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='determine_alert_route');ns={'classify_price':classify,'PRICE_EVENTS':PRICE_EVENTS}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'route','exec'),ns);self.assertEqual(ns['determine_alert_route'](event()),'deal')
    def test_case(self):
        r=case();self.assertEqual(calculated_case_amount(r),1440);e=event('1400',product_type='CASE',reference_evidence=r);self.assertEqual(classify(e),'BELOW_MSRP');e['price']='1296';self.assertEqual(classify(e),'DEAL')
    def test_case_quantity_identity_expiry(self):
        for q in (True,0,-1,1.5,'12'):
            r=case();r['derivation']['case_contents']['quantity']=q
            with self.assertRaises(ValueError):calculated_case_amount(r)
        for k,v in [('unit_product_id','OTHER'),('case_product_url','https://example.com/other'),('expires_at',(NOW-timedelta(days=1)).isoformat())]:
            r=case();r['derivation']['case_contents'][k]=v
            with self.assertRaises(ValueError):calculated_case_amount(r)
    def test_case_conflict(self):
        r=case();r['amount']='2000';self.assertEqual(alert_matches(event('1400',product_type='CASE',reference_evidence=r)),[])
