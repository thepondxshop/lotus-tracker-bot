import unittest
from unittest.mock import patch
from app.marketplaces import public_market as pm

class UnitsTests(unittest.TestCase):
    def test_reported_catalog_packages(self):
        cases=[('151 Booster Bundle',53,'BOOSTER BUNDLE'),('Pokémon Card 151 Booster Box',53,'BOOSTER BOX'),('151 Elite Trainer Box',1016,'ELITE TRAINER BOX'),('151: Arcanine Mini Tin',1014,'TIN'),('151 10 Elite Trainer Box Case',1016,None),('Pokémon Card 151 Booster Box Case',53,None),('151 Booster Bundle Display',53,None),('151: Mini Tin Display',1014,None),('151: Costco 5-Pack Mini Tin Bundle',1014,None)]
        for name,category,expected in cases:
            with self.subTest(name=name):self.assertEqual(pm.sealed_format(name,category),expected)
    def mapping(self,name,category,typ):
        return dict(reviewed=True,accept_provider_aggregate=True,product_url='https://shop.example/product',product_name=name,product_type=typ,game='Pokemon',product_family='GLOBAL_STANDARD',currency='EUR',region='DE',quantity=1,packaging_verified=True,event_identity={'variant_id':'1'},provider='cardmarket',marketplace='cardmarket',source_id='1',source_name=name,variant='sealed',category_id=category,release_date_verified=True,release_date='2026-01-01',release_date_source='https://publisher.example/release')
    def test_case_cannot_be_approved_as_etb(self):
        with self.assertRaises(ValueError):pm.validate(self.mapping('151 10 Elite Trainer Box Case',1016,'Elite Trainer Box'))
    def test_bundle_not_box(self):
        m=self.mapping('151 Booster Bundle',53,'Booster Box')
        with self.assertRaises(ValueError):pm.validate(m)
        m['product_type']='Booster Bundle';self.assertEqual(pm.validate(m),m)
    def test_old_mapping_revalidated_during_authorization(self):
        import tempfile,json,os
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'LOTUS_MARKET_MAPPINGS_FILE':d+'/m.json'}):
            m=self.mapping('151 10 Elite Trainer Box Case',1016,'Elite Trainer Box')
            Path(d+'/m.json').write_text(json.dumps([m]))
            self.assertFalse(pm.authorized({'kind':'MARKET_PUBLISHED','sample_count':None,'mapping_hash':pm.digest(m)},m))

if __name__=='__main__':unittest.main()
