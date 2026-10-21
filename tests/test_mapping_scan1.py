import unittest
from lotus_market_mapping_scan import build_report,name_key

class MappingScanTests(unittest.TestCase):
    def retailer(self,**kw):
        return dict(dict(game='Pokemon',product_name='151 Elite Trainer Box',product_type='Elite Trainer Box',product_family='GLOBAL_STANDARD',currency='EUR',region='IE',product_url='https://shop.example/151',variant_id='123',store_name='Example',release_date='2026-01-01'),**kw)
    def source(self,**kw):
        return dict(dict(source_id='719691',source_name='151 Elite Trainer Box',category_id=1016,source_field='avg',source_updated_at='2026-10-20T00:00:00+00:00',amount='402.72',fresh=True),**kw)
    def test_exact_candidate_never_implicitly_approved(self):
        r=build_report([self.retailer()],[self.source()]);self.assertEqual(r['candidate_count'],1)
        m=r['candidates'][0]['mapping']
        self.assertFalse(m['reviewed']);self.assertFalse(m['release_date_verified']);self.assertIsNone(m['release_date'])
        self.assertEqual(m['event_identity'],{'variant_id':'123'})
        self.assertFalse(r['live_mappings_modified'])
    def test_us_and_other_currency_not_combined(self):
        for kw in [dict(currency='USD',region='US'),dict(currency='SEK',region='SE'),dict(currency='EUR',region='US')]:
            self.assertEqual(build_report([self.retailer(**kw)],[self.source()])['candidate_count'],0)
    def test_case_source_cannot_match_etb(self):
        r=build_report([self.retailer(product_name='151 10 Elite Trainer Box Case')],[self.source(source_name='151 10 Elite Trainer Box Case')])
        self.assertEqual(r['candidate_count'],0)
    def test_multiple_source_ids_ambiguous(self):
        r=build_report([self.retailer()],[self.source(),self.source(source_id='2')])
        self.assertEqual(r['counts']['AMBIGUOUS_SOURCE_ID'],1)
    def test_stale_source_blocked(self):
        self.assertEqual(build_report([self.retailer()],[self.source(fresh=False)])['counts']['SOURCE_PRICE_STALE'],1)
    def test_no_single_condition_or_edition_guessing(self):
        r=build_report([self.retailer(product_type='Single Card')],[self.source()])
        self.assertEqual(r['candidate_count'],0)
        self.assertNotEqual(name_key('151 Pokemon Center Elite Trainer Box'),name_key('151 Elite Trainer Box'))
        self.assertNotEqual(name_key('151 Booster Bundle'),name_key('151 Booster Box'))
    def test_missing_variant_reported_not_invented(self):
        r=build_report([self.retailer(variant_id=None)],[self.source()])
        self.assertIn('EVENT_VARIANT_IDENTITY_MISSING',r['candidates'][0]['blockers'])
        self.assertEqual(r['candidates'][0]['mapping']['event_identity'],{})
    def test_duplicate_retail_rows_not_duplicate_candidates(self):
        r=build_report([self.retailer(),self.retailer()],[self.source()])
        self.assertEqual(r['candidate_count'],1)
        self.assertEqual(r['counts']['DUPLICATE_RETAIL_ROW'],1)

if __name__=='__main__':unittest.main()
