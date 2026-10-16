import unittest
import copy
from test_gtin1 import fixture, NOW
from app.marketplaces.ebay_live_policy import assess, gtin_status
from app.marketplaces.ebay_snapshot import apply_151_snapshot
from lotus_ebay_setup import PRESET

class CatalogGtinTests(unittest.TestCase):
    def test_catalog_only_reaches_pricing(self):
        i = fixture()
        i['localizedAspects'] = i['localizedAspects'][1:]
        i['product'] = {'gtins': ['00820650853210']}
        t = apply_151_snapshot(copy.deepcopy(PRESET))
        self.assertTrue(assess(i, t, NOW)['eligible'])
        self.assertEqual(gtin_status(i, t)['identifier_sources'], ['product.gtins'])
        i['price']['value'] = '120'
        self.assertFalse(assess(i, t, NOW)['eligible'])
    def test_conflict_with_listing_is_not_overridden(self):
        i = fixture(); i['product'] = {'gtins': ['999999999999']}
        self.assertEqual(assess(i, PRESET, NOW)['reason'], 'GTIN_CONFLICT')
    def test_distinct_catalog_codes_require_review(self):
        i = {'product': {'gtins': ['820650853210', '999999999999']}}
        self.assertEqual(gtin_status(i, PRESET)['reason'], 'GTIN_CONFLICT')
    def test_catalog_absence_remains_blocked(self):
        for p in ({}, {'gtins': []}, {'gtins': ['Does not apply']}):
            self.assertEqual(gtin_status({'product': p}, PRESET)['reason'], 'GTIN_MISSING')
    def test_wrong_catalog_code(self):
        self.assertEqual(gtin_status({'product': {'gtins': ['999999999999']}}, PRESET)['reason'], 'GTIN_MISMATCH')
    def test_malformed_catalog_is_not_accepted(self):
        for codes in ('820650853210', {'value': '820650853210'}, [True], [['820650853210']]):
            i = fixture(); i['product'] = {'gtins': codes}
            self.assertEqual(gtin_status(i, PRESET)['reason'], 'GTIN_INVALID')
    def test_equivalent_catalog_codes(self):
        i = {'product': {'gtins': ['820650853210', '00820650853210']}}
        self.assertEqual(gtin_status(i, PRESET)['reason'], 'GTIN_MATCH')
