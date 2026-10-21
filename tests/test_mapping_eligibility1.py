import unittest
from lotus_market_mapping_scan import build_report,excluded_kind

class EligibilityTests(unittest.TestCase):
    def test_reported_pollution(self):
        for title,typ,reason in [
            ('09/10/2026 Thu Pokemon TCG League & Trade & Pokemon Go Meet Up at 6:30 pm - Thurs Tournament','Single Card','EVENT_NOT_MARKET_PRODUCT'),
            ('Pokemon Funitto Mascot 7 (Random Selection) - Single Pack','Misc','MERCHANDISE_NOT_MARKET_PRODUCT'),
            ('Tomy Club Mocchi Nintendo Super Mario Plush Toy Yoshi Egg Plushie','Plushies','MERCHANDISE_NOT_MARKET_PRODUCT'),
            ('TAB Display - Acrylic Case Pokemon Elite Trainer Box Case – 6MM','Elite Trainer Box','ACCESSORY_NOT_MARKET_PRODUCT'),
            ('Caja de mazo Alcove Charizard X Pokemon - Ultra Pro','TCG Product','ACCESSORY_NOT_MARKET_PRODUCT')]:
            with self.subTest(title=title):
                row=dict(game='Pokemon',product_name=title,product_type=typ,currency='USD',region='US')
                self.assertEqual(excluded_kind(row),reason)
                self.assertEqual(build_report([row],[])['counts'],{reason:1})
    def test_real_products_retained(self):
        for title in ['Professor Juniper Premium Tournament Collection','Pikachu League Promo 001/100','151 Elite Trainer Box','One Piece Booster Box Case','Pokemon Booster Pack']:
            self.assertIsNone(excluded_kind(dict(product_name=title,product_type='TCG Product')))
