import ast
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from app.price_policy import market_age_status, case_destination, classify
from test_msrp1 import event, ref

class Case30Tests(unittest.TestCase):
    def test_day_boundary(self):
        r=dict(ref('MARKET_SOLD'),release_date='2026-09-18')
        e=event()
        self.assertEqual(market_age_status(e,r,datetime.fromisoformat('2026-10-18T03:59:59+00:00')),'BEFORE_MARKET_DAY_30')
        self.assertEqual(market_age_status(e,r,datetime.fromisoformat('2026-10-18T04:00:00+00:00')),'ELIGIBLE')
    def test_missing_unverified_and_future_release(self):
        for changes in ({'release_date_verified':False},{'release_date_source':''},{'release_date':'bad'},{'release_date':'2099-01-01'}):
            r=ref('MARKET_SOLD');r.update(changes)
            self.assertNotEqual(market_age_status(event(),r),'ELIGIBLE')
    def test_singles_not_delayed(self):
        self.assertEqual(market_age_status(event(product_type='Single Card'),{}),'ELIGIBLE')
    def test_msrp_still_active_before_day_30(self):
        e=event();e['reference_evidence']['release_date']='2099-01-01'
        self.assertEqual(classify(e),'BELOW_MSRP')
    def test_market_gate_actual_policy(self):
        e=event('90','MARKET_SOLD');e['reference_evidence']['release_date']='2099-01-01'
        self.assertEqual(classify(e),'NO_VERIFIED_DECREASE')
        e['reference_evidence']['release_date']='2020-01-01'
        self.assertEqual(classify(e),'DEAL')
    def test_all_case_types_and_regions(self):
        for t in ('RESTOCK','DISCOVERED','PREORDER_LIVE','PRICE_DROP','DEAL'):
            for region in ('US','JP','GB'):
                e=event(event_type=t,region=region,product_type='Case')
                self.assertEqual(case_destination(e,{'CHANNEL_CASE_SEALED_DEALS':'1541943138476621955'})['channel_id'],1541943138476621955)
    def test_no_box_redirect_or_increase(self):
        self.assertIsNone(case_destination(event()))
        self.assertIsNone(case_destination(event(product_type='Case',event_type='PRICE_INCREASE')))
        self.assertIsNone(case_destination(event(product_type='Case'),{})['channel_id'])
    def test_actual_override_before_channel_resolution(self):
        tree=ast.parse(Path('app/worker.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='route_event_to_discord')
        text=ast.unparse(node)
        self.assertLess(text.index('case_route = case_destination(event)'),text.index("regional_id = destination['channel_id']"))
        self.assertIn('destination = case_route',text)
