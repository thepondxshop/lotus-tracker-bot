import unittest
from datetime import datetime, timezone
from app.marketplaces.ebay_live_policy import gtin_status, assess
from app.marketplaces.ebay_snapshot import apply_151_snapshot
from lotus_ebay_setup import PRESET
import copy

NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)

def fixture():
    return {'title': 'Pokemon 151 Booster Bundle English Sealed',
            'conditionId': '1000',
            'localizedAspects': [{'name': 'UPC', 'value': '820650853210'},
                {'name': 'Language', 'value': 'English'}, {'name': 'Configuration', 'value': 'Box'}],
            'itemLocation': {'country': 'US'},
            'seller': {'username': 'synthetic', 'feedbackScore': 100, 'feedbackPercentage': '99'},
            'buyingOptions': ['FIXED_PRICE'], 'price': {'value': '100', 'currency': 'USD'},
            'estimatedAvailabilities': [{'estimatedAvailabilityStatus': 'IN_STOCK'}],
            'itemWebUrl': 'https://www.ebay.com/itm/123456789012'}

class GtinTests(unittest.TestCase):
    def test_missing_and_placeholder(self):
        for value in (None, '', 'Does not apply', 'N/A'):
            self.assertEqual(gtin_status({'gtin': value}, PRESET)['reason'], 'GTIN_MISSING')
    def test_padding_and_format(self):
        for value in ('820650853210', '00820650853210', '0 820650853210', '820-650-853210'):
            self.assertEqual(gtin_status({'gtin': value}, PRESET)['reason'], 'GTIN_MATCH')
    def test_distinct_rejections(self):
        for value, reason in [('999999999999', 'GTIN_MISMATCH'), ('000000000000', 'GTIN_INVALID'),
                              ('UPC 820650853210', 'GTIN_INVALID')]:
            self.assertEqual(gtin_status({'gtin': value}, PRESET)['reason'], reason)
    def test_conflicting_fields_block(self):
        i = fixture(); i['gtin'] = '999999999999'
        self.assertEqual(assess(i, PRESET, NOW)['reason'], 'GTIN_CONFLICT')
    def test_invalid_explicit_field_blocks_fallback(self):
        i = fixture(); i['gtin'] = 'not a barcode'
        self.assertEqual(assess(i, PRESET, NOW)['reason'], 'GTIN_INVALID')
    def test_no_title_or_search_inference(self):
        i = {'title': '820650853210', 'search_gtin': '820650853210'}
        self.assertEqual(gtin_status(i, PRESET)['reason'], 'GTIN_MISSING')
    def test_aspect_fallback_through_actual_assessment(self):
        t = copy.deepcopy(PRESET)
        t = apply_151_snapshot(t)
        self.assertTrue(assess(fixture(), t, NOW)['eligible'])
        i = fixture(); i['seller']['feedbackScore'] = 0
        self.assertEqual(assess(i, t, NOW)['reason'], 'SELLER_EVIDENCE_INSUFFICIENT')
        i = fixture(); i['price']['value'] = '120'
        self.assertFalse(assess(i, t, NOW)['eligible'])
        i = fixture(); i['localizedAspects'][1]['value'] = 'Japanese'
        self.assertEqual(assess(i, t, NOW)['reason'], 'ASPECT_MISMATCH')
    def test_equivalent_codes_are_not_conflicts(self):
        i = fixture(); i['gtin'] = '00820650853210'
        self.assertEqual(gtin_status(i, PRESET)['reason'], 'GTIN_MATCH')

if __name__ == '__main__':
    unittest.main()
