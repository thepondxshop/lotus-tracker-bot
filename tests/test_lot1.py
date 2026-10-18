import copy
import unittest
from datetime import datetime, timezone
from app.marketplaces.ebay_live_policy import lot_status, assess, review_diagnostics
from app.marketplaces.ebay_snapshot import apply_151_snapshot
from lotus_ebay_setup import PRESET
NOW = datetime(2026,10,18,tzinfo=timezone.utc)

def item():
    return {'title':'Pokemon 151 Booster Bundle English Sealed - 6 Booster Packs',
        'gtin':'820650853210','lotSize':0,'conditionId':'1000',
        'localizedAspects':[{'name':'Language','value':'English'},{'name':'Configuration','value':'Box'}],
        'itemLocation':{'country':'US'},'seller':{'username':'fixture','feedbackScore':100,'feedbackPercentage':'99'},
        'buyingOptions':['FIXED_PRICE'],'price':{'value':'100','currency':'USD'},
        'estimatedAvailabilities':[{'estimatedAvailabilityStatus':'IN_STOCK'}],
        'itemWebUrl':'https://www.ebay.com/itm/123456789012'}

class LotTests(unittest.TestCase):
    def test_single_bundle_zero_omitted_and_one(self):
        t=apply_151_snapshot(copy.deepcopy(PRESET))
        for v in (None,0,'0',1,'1'):
            i=item();i['lotSize']=v
            self.assertTrue(assess(i,t,NOW)['eligible'])
    def test_missing_identifier_still_blocks(self):
        i=item();i.pop('gtin')
        self.assertEqual(assess(i,PRESET,NOW)['reason'],'GTIN_MISSING')
    def test_two_boxes_and_numeric_lots(self):
        for title in ('Pokemon 151 Booster Bundle (English, Sealed, Two Boxes)',
                      'Pokemon 151 Lot of 2x Booster Bundles','Pokemon 151 booster bundle lot of 10',
                      'Pokemon 151 Booster Bundles x2'):
            i=item();i['title']=title
            self.assertEqual(lot_status(i,PRESET),'MULTI_UNIT_LOT')
    def test_invalid_and_multiple(self):
        for v in (-1,True,1.5,'unknown'):
            self.assertEqual(lot_status(dict(item(),lotSize=v),PRESET),'LOT_SIZE_INVALID')
        self.assertEqual(lot_status(dict(item(),lotSize=2),PRESET),'MULTI_UNIT_LOT')
    def test_pack_counts(self):
        for value,reason in [('2x6','MULTI_UNIT_LOT'),('12','PACK_COUNT_UNVERIFIED'),('6',None)]:
            i=item();i['localizedAspects'].append({'name':'Number of Packs','value':value})
            self.assertEqual(lot_status(i,PRESET),reason)
    def test_expensive_single_bundle(self):
        i=item();i['price']['value']='174.99';t=apply_151_snapshot(copy.deepcopy(PRESET))
        self.assertFalse(assess(i,t,NOW)['eligible'])
        d=review_diagnostics(i,t,NOW)
        self.assertIsNone(d['lot_blocker']);self.assertFalse(d['price_only_meets_threshold'])
        self.assertEqual(d['item_price_threshold'],'108.67')
    def test_diagnostics_do_not_bypass_identity(self):
        i=item();i.pop('gtin');t=apply_151_snapshot(copy.deepcopy(PRESET))
        d=review_diagnostics(i,t,NOW)
        self.assertTrue(d['price_only_meets_threshold'])
        self.assertEqual(d['assessment'],'GTIN_MISSING')
        self.assertFalse(assess(i,t,NOW)['eligible'])
    def test_empty_box_remains_excluded(self):
        i=item();i['title']='Empty Pokemon 151 Booster Bundle Box'
        self.assertEqual(assess(i,PRESET,NOW)['reason'],'EXCLUDED_PRODUCT')
