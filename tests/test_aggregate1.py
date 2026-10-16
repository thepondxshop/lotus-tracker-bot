import copy
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from app.marketplaces.ebay_snapshot import apply_151_snapshot
from app.marketplaces.ebay_evidence import comparison,evaluate_item_only,config_hash
from lotus_ebay_setup import PRESET
NOW=datetime(2026,10,16,3,tzinfo=timezone.utc)
def target():return apply_151_snapshot(copy.deepcopy(PRESET))
class AggregateTests(unittest.TestCase):
    def test_weighted_mean(self):
        r=comparison(target(),NOW)
        self.assertTrue(r['ready']);self.assertEqual(r['sample_count'],73)
        self.assertEqual(r['listing_rows'],9);self.assertEqual(r['item_sales_total'],'8814.38')
        self.assertEqual(Decimal(r['amount']).quantize(Decimal('.01')),Decimal('120.74'))
        self.assertEqual(r['threshold'],'108.67')
    def test_boundary(self):
        self.assertTrue(evaluate_item_only('108.67',target(),False,NOW)['eligible'])
        self.assertFalse(evaluate_item_only('108.68',target(),False,NOW)['eligible'])
    def test_not_blended(self):
        t=target();t['sold_records']=[{'item_price':'99999'}]*100
        self.assertEqual(comparison(t,NOW)['sample_count'],73)
    def test_expiry_and_no_fallback(self):
        t=target();t['sold_records']=[{'item_price':'99999'}]*100
        self.assertEqual(comparison(t,datetime(2026,10,22,4,tzinfo=timezone.utc))['reason'],'AGGREGATE_SNAPSHOT_EXPIRED')
    def test_duplicates_and_identity(self):
        t=target();t['aggregate_snapshot']['rows'].append(t['aggregate_snapshot']['rows'][0])
        self.assertFalse(comparison(t,NOW)['ready'])
        t=target();t['gtin']='123456789012';self.assertFalse(comparison(t,NOW)['ready'])
    def test_future_and_invalid_units(self):
        t=target();t['aggregate_snapshot']['captured_at']='2027-01-01T00:00:00Z'
        self.assertFalse(comparison(t,NOW)['ready'])
        t=target();t['aggregate_snapshot']['rows'][0]['units']=True
        self.assertFalse(comparison(t,NOW)['ready'])
    def test_apply_clears_sales_and_stable_hash(self):
        t=copy.deepcopy(PRESET);t['sold_records']=[{'old':'record'}]
        apply_151_snapshot(t);self.assertEqual(t['sold_records'],[])
        before=config_hash([t]);apply_151_snapshot(t);self.assertEqual(before,config_hash([t]))
    def test_accurate_display_label(self):
        r=evaluate_item_only('100',target(),False,NOW)
        self.assertIn('73 units across 9',r['comparison_label'])
        self.assertIn('visible results only',r['comparison_label'])
