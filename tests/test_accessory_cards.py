import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('accessory_fix',ROOT/'app/accessory_routes.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class CardRoutingTests(unittest.TestCase):
    def test_all_reported_singles_override_stale_accessory(self):
        names=['Vegeta (FB11-043)','Vegeta (FB11-042)','Haru/Maki',
               'Son Gohan : Future (FB11-031)','Android 18','Entrusted Sword',
               'Trunks : Youth (FB11-018)','Son Goten (FB11-014)',
               'Son Goku (FB11-010)','Son Goku (FB11-008)','Son Goku (FB11-007)',
               'Gotenks','Great Saiyaman 2 (FB11-004)']
        for name in names:
            with self.subTest(name=name):
                e=dict(product_name=name+' [Brightness of Hope Release Event Cards]',
                       product_type='Accessory',product_category='ACCESSORY',region='US',
                       reference_evidence={'amount':999})
                fixed=m.normalize_accessory_event(e)
                self.assertEqual(fixed['product_type'],'Single Card')
                self.assertEqual(fixed['product_category'],'SINGLE')
                self.assertIsNone(m.accessory_destination(fixed))
                self.assertNotIn('reference_evidence',fixed)
                self.assertIn('reference_evidence',e)
    def test_both_screenshots(self):
        for name in ['One Piece Card Game - BCGF 25-26 Official Playmat & Card Limited Edition Vol. 5',
                     'One Piece Card Game Sound Loader - Ace & Sabo Edition + Bonus Cards [Pre-Order Mar 2026]']:
            e=dict(product_name=name,product_type='Accessory',product_category='ACCESSORY',region='JP')
            fixed=m.normalize_accessory_event(e)
            self.assertEqual(fixed['product_category'],'COLLECTION')
            self.assertIsNone(m.accessory_destination(fixed))
    def test_description_contents(self):
        e=dict(product_name='One Piece Playmat Set',description='<p>Includes 1 exclusive promo card.</p>')
        self.assertFalse(m.accessory_event(e))
        self.assertEqual(m.normalize_accessory_event(e)['product_category'],'COLLECTION')
    def test_real_accessories_and_negatives(self):
        for name in ['Pokemon sleeves','One Piece deck box','Riftbound playmat',
                     'Vegeta FB11-043 Playmat','Acrylic Case Pokemon Elite Trainer Box',
                     'Playmat with card sleeves','Playmat & card protectors',
                     'Playmat without promo card','Playmat - card not included']:
            with self.subTest(name=name):
                self.assertTrue(m.accessory_event(dict(product_name=name)))
    def test_single_type_overrides_category(self):
        e=dict(product_name='Pikachu',product_type='Single Card',product_category='ACCESSORY')
        self.assertIsNone(m.accessory_destination(e))
    def test_sealed_and_merchandise(self):
        self.assertFalse(m.accessory_event(dict(product_name='Booster Box Case')))
        self.assertTrue(m.merchandise_event(dict(product_name='Pokemon Plush')))
    def test_version(self):
        spec=importlib.util.spec_from_file_location('release_version',ROOT/'app/version.py')
        v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
        self.assertRegex(v.VERSION,r'^\d+\.\d+\.\d+$')
        self.assertIn(v.RELEASE_KIND,{'patch','regular','major'})
        self.assertTrue(v.RELEASE_NOTES)
        self.assertIn(v.VERSION,v.announcement())
        if v.RELEASE_KIND != 'major':self.assertNotIn('@everyone',v.announcement())
