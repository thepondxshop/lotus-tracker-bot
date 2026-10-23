import ast
import asyncio
from pathlib import Path
import unittest
from app.accessory_routes import accessory_destination, accessory_event, merchandise_event, normalize_accessory_event


class AccessoryTests(unittest.TestCase):
    def test_domestic_and_global(self):
        for title in ('One Piece Playmat', 'Pokemon Sleeves', 'Riftbound Deck Case',
                      'Pokemon Binder', 'Acrylic Case Pokemon Elite Trainer Box', 'Card Storage Case'):
            for region, expected in [('US', 1562959977377955860), ('JP', 1562960120152064010), ('CA', 1562960120152064010)]:
                with self.subTest(title=title, region=region):
                    e = dict(product_name=title, product_type='Case', region=region)
                    self.assertEqual(accessory_destination(e, {})['channel_id'], expected)
                    self.assertEqual(normalize_accessory_event(e)['product_category'], 'ACCESSORY')

    def test_sealed_products_stay(self):
        for title in ('One Piece Booster Box Case', 'Pokemon Booster Bundle',
                      'Riftbound Starter Deck with Sleeves'):
            self.assertIsNone(accessory_destination(dict(product_name=title), {}))

    def test_toys_blocked_even_with_game(self):
        e = dict(product_name='MegaHouse: Mega Cat Project - One Piece, Nyan Piece Nyan! ver. Luffy vs Marines',
                 product_type='Toys And Collectible', game='One Piece')
        self.assertTrue(merchandise_event(e))
        self.assertFalse(accessory_event(e))
        # Execute the real worker entry; a blocked toy must never reach enrichment or send.
        source = Path(__file__).resolve().parents[1] / 'app' / 'worker.py'
        tree = ast.parse(source.read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'route_event_to_discord')
        namespace = {}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), 'exec'), namespace)
        self.assertFalse(asyncio.run(namespace[fn.name](None, e)))

    def test_invalid_config_never_falls_back(self):
        e = dict(product_name='Pokemon Playmat', region='US')
        self.assertIsNone(accessory_destination(e, {'CHANNEL_ACCESSORIES_DROPS':'invalid'})['channel_id'])

    def test_bad_retailer_type_does_not_hide_cards(self):
        self.assertFalse(merchandise_event(dict(product_name='Pokemon Booster Box', product_type='Toys and Collectibles')))

    def test_stale_case_reference_removed(self):
        e = dict(product_name='Pokemon Deck Case', product_type='Case', reference_evidence={'amount':'999'})
        self.assertNotIn('reference_evidence', normalize_accessory_event(e))
        self.assertIn('reference_evidence', e)
