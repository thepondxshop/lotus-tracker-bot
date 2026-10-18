import unittest
from datetime import datetime, timezone, timedelta
from app.price_policy import classify,reference_window_status,qualifying_references
from app.distributor_msrp import extract,validate_url
from test_msrp1 import event,ref

class Strict30Tests(unittest.TestCase):
    def test_exact_switch(self):
        r=ref();r['release_date']='2026-09-18';m=dict(r,kind='MARKET_SOLD')
        before=datetime.fromisoformat('2026-10-18T03:59:59+00:00');after=before+timedelta(seconds=1)
        self.assertEqual(reference_window_status(event(),r,before),'ELIGIBLE')
        self.assertEqual(reference_window_status(event(),m,before),'BEFORE_MARKET_DAY_30')
        self.assertEqual(reference_window_status(event(),r,after),'MSRP_WINDOW_ENDED')
        self.assertEqual(reference_window_status(event(),m,after),'ELIGIBLE')
    def test_no_msrp_fallback_after_cutoff(self):
        e=event('1');e['reference_evidence']['release_date']='2020-01-01'
        self.assertEqual(classify(e),'NO_VERIFIED_DECREASE')
    def test_missing_date_blocks_msrp(self):
        e=event();e['reference_evidence'].pop('release_date')
        self.assertEqual(qualifying_references(e),[])
    def test_preorder_msrp_only(self):
        e=event();e['reference_evidence']['release_date']='2099-01-01'
        self.assertEqual(classify(e),'BELOW_MSRP')
        e['reference_evidence']['kind']='MARKET_SOLD'
        self.assertEqual(qualifying_references(e),[])
    def test_conflicting_dates(self):
        e=event();e['reference_evidence']={'references':[ref(),ref('MARKET_SOLD')]}
        self.assertEqual(qualifying_references(e),[])
    def test_market_boundary_after_release(self):
        self.assertEqual(classify(event('90','MARKET_SOLD')),'DEAL')
        self.assertEqual(classify(event('90.01','MARKET_SOLD')),'NO_VERIFIED_DECREASE')
    def test_two_public_products(self):
        html='<h2>Pokemon Booster Display (36 Packs)</h2><p>Publisher: Pokemon</p><p>Item Code: PKU123</p><p>MSRP: $161.64</p><p>Releases March 27, 2026</p><h2>Pokemon Bundle</h2><p>Publisher: Pokemon</p><p>Item Code: PKU456</p><p>MSRP: $26.94</p>'
        rows=extract('https://www.phdgames.com/example',html)['observations']
        self.assertEqual([r['msrp'] for r in rows],['161.64','26.94'])
        self.assertTrue(all(r['reference_ready'] is False for r in rows))
    def test_no_wholesale_or_conflicting_msrp(self):
        for html in ('<p>SKU: ABC123</p><p>Price: $50.00</p>','<p>SKU: ABC123</p><p>MSRP: $50.00 MSRP: $70.00</p>'):
            self.assertEqual(extract('https://www.acdd.com/example',html)['observations'][0]['state'],'MSRP_MISSING_OR_AMBIGUOUS')
    def test_distributor_urls(self):
        for url in ('http://www.acdd.com/x','https://evil.example/x','https://www.acdd.com@evil.example/x'):
            with self.assertRaises(ValueError):validate_url(url)
