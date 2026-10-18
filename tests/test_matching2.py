import unittest
from datetime import datetime, timezone, timedelta
from app.marketplaces.ebay_identity import multi_field_identity
from app.marketplaces.ebay_live_policy import seller_diagnostics, review_diagnostics
from app.distributor_catalog import record, norm
from app.distributor_references import install, matched, type_key

class MatchingTests(unittest.TestCase):
    def tearDown(self):install([],[])
    def fixture(self):
        t={'id':'pokemon-151-bundle-en','reviewed':True,'game':'Pokemon','gtin':'820650853210','quantity':1,'aspects':{'Language':'English','Configuration':'Box'}}
        i={'conditionId':'1000','title':'Pokemon TCG Scarlet & Violet 151 Booster Bundle - 6 Packs - Brand New - Sealed','localizedAspects':[{'name':'Language','value':'English'},{'name':'Configuration','value':'Box'},{'name':'Game','value':'Pokémon TCG'}]}
        return i,t
    def test_english_aspect_without_title(self):
        i,t=self.fixture();self.assertTrue(multi_field_identity(i,t))
    def test_conflicting_and_missing_language(self):
        i,t=self.fixture();i['localizedAspects'][0]['value']='Japanese';self.assertFalse(multi_field_identity(i,t))
        i,t=self.fixture();i['localizedAspects'].append({'name':'Language','value':'Japanese'});self.assertFalse(multi_field_identity(i,t))
        i,t=self.fixture();i['localizedAspects']=i['localizedAspects'][1:];self.assertFalse(multi_field_identity(i,t))
    def test_foreign_title_still_blocks(self):
        i,t=self.fixture();i['title']+=' Japanese';self.assertFalse(multi_field_identity(i,t))
    def test_missing_seller_fields(self):
        r=seller_diagnostics({});self.assertFalse(r['eligible']);self.assertIn('FEEDBACK_SCORE_MISSING',r['blockers']);self.assertIn('SELLER_IDENTIFIER_MISSING',r['blockers'])
    def test_low_seller_fields(self):
        r=seller_diagnostics({'seller':{'username':'private','feedbackScore':99,'feedbackPercentage':'97.9'}})
        self.assertEqual(r['blockers'],['FEEDBACK_SCORE_BELOW_MINIMUM','FEEDBACK_PERCENTAGE_BELOW_MINIMUM']);self.assertNotIn('private',str(r))
    def test_invalid_and_boundary_seller(self):
        self.assertTrue(seller_diagnostics({'seller':{'username':'private','feedbackScore':100,'feedbackPercentage':98}})['eligible'])
        self.assertIn('FEEDBACK_SCORE_INVALID',seller_diagnostics({'seller':{'username':'private','feedbackScore':'bad','feedbackPercentage':99}})['blockers'])
    def test_packaging_aliases(self):
        for t in ('BOOSTER_BOX','booster-box','Booster Display Box','Collector Booster Box'):
            self.assertEqual(type_key(t),'BOOSTER BOX')
    def test_persisted_name_keys_are_recomputed(self):
        r=record('https://www.phdgames.com/2026/10/15/test/','ABC','Pokemon Test Booster Display Box','100',(datetime.now(timezone.utc)+timedelta(days=10)).date().isoformat(),'PHD')
        r['name_key']='old name key';install([r],[])
        e={'product_name':'Pre-order: Pokemon Test Booster Box Sealed','product_type':'BOOSTER_BOX','game':'Pokemon','region':'US','currency':'USD','product_family':'GLOBAL_STANDARD','product_url':'https://example.com/test'}
        self.assertEqual(matched(e)[0]['amount'],'100')
        for title in ('Pokemon Test Collector Booster Box','Pokemon Test Booster Box 36 Packs','Pokemon Test Booster Box Japanese','Pokemon Test Booster Box Two Boxes'):
            self.assertEqual(matched(dict(e,product_name=title)),[])
    def test_collector_and_quantities_not_erased(self):
        self.assertNotEqual(norm('Pokemon Test Booster Box'),norm('Pokemon Test Collector Booster Box'))
        self.assertNotEqual(norm('Pokemon Test Booster Box 24 packs'),norm('Pokemon Test Booster Box 36 packs'))
