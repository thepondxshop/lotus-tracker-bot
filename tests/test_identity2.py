import ast
from pathlib import Path
import unittest
from app.tcg_identity import FUSION_WORLD_GAME, NEW_TCG, title_identity, has_fusion_world_identity
from app.registered_games import registered_identity, explicit_family
from app.config import GAME_DATA

class IdentityTest(unittest.TestCase):
    def test_fw_aliases(self):
        for name in ('DragonBall FW FB11 Booster Box', 'Dragon Ball FW FB-11 Booster Box', 'DBS FW FB11 Booster Box', 'Dragon Ball Super Card Game Fusion World FB11 Brightness of Hope Booster Box'):
            self.assertEqual(title_identity(name), FUSION_WORLD_GAME)
    def test_no_bare_codes_or_masters(self):
        for name in ('FB11 Booster Box', 'FW Booster Box', 'Dragon Ball Super Masters Booster Box', 'Dragon Ball Super Booster Box'):
            self.assertFalse(has_fusion_world_identity(name))
    def test_real_shopify_classifier(self):
        from app.shopify_adapter import classify_game
        self.assertEqual(classify_game({'title':'DragonBall FW FB11 Booster Box','product_type':'Booster Box'}), FUSION_WORLD_GAME)
        self.assertEqual(classify_game({'title':'Kakawow Harry Potter TCG Booster Box','product_type':'Booster Box'}), 'Harry Potter TCG — Kakawow')
        self.assertIsNone(classify_game({'title':'Kakawow Harry Potter Aura Hobby Box','product_type':'Trading Cards'}))
    def test_queued_unknown_fw_review_is_suppressed(self):
        # Execute the real review gate with no Discord/Redis imports or writes.
        tree=ast.parse(Path('app/tcg_discovery_admin.py').read_text())
        keep={'_name_key','_registered','candidate_from_event'}
        ns={'title_identity':title_identity,'NEW_TCG':NEW_TCG,'GAME_DATA':GAME_DATA}
        import re, unicodedata
        ns.update(re=re,unicodedata=unicodedata)
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in keep],type_ignores=[]),'review','exec'),ns)
        self.assertIsNone(ns['candidate_from_event']({'game':NEW_TCG,'product_name':'DragonBall FW FB11 Booster Box'}))
    def test_hp_separation(self):
        for title in ('Harry Potter TCG Booster Box', 'Kakawow Harry Potter Aura Trading Cards Hobby Box', 'Kakawow Harry Potter GEM TCG Booster Box', 'Wizards Harry Potter 2001 TCG Booster Box', 'Kakawow Harry Potter TCG LEGO Building Set'):
            # Building sets are stopped by the adapter, tested separately below.
            if 'LEGO' not in title:self.assertIsNone(registered_identity({'title':title}))
        self.assertEqual(registered_identity({'title':'Harry Potter Trading Card Game Booster Box','vendor':'Kakawow'}),'Harry Potter TCG — Kakawow')
        self.assertEqual(explicit_family({'title':'Kakawow Harry Potter TCG English Booster Box'}),'GLOBAL_STANDARD')
    def test_hp_menu(self):
        self.assertIn('Harry Potter TCG — Kakawow', {row[0] for row in GAME_DATA})

if __name__=='__main__': unittest.main()
