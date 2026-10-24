import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from app import registered_games as games
from app.distributor_references import game_matches
from app.collection_priority import explicit_tcg
from app.marketplaces.ebay_search_plan import GAME_QUERIES
from app.game_lifecycle import SOURCES

GAME='Beyblade X TCG — Blader League'

class Game178Tests(unittest.TestCase):
    def config(self,env):
        path=Path(__file__).resolve().parents[1]/'app/config.py'
        spec=importlib.util.spec_from_file_location('isolated_config178',path)
        module=importlib.util.module_from_spec(spec)
        with patch.dict(os.environ,env,clear=True):spec.loader.exec_module(module)
        return module
    def test_supplied_roles_and_pending_beyblade(self):
        c=self.config({})
        self.assertEqual(c.GAME_ROLES['World of Tanks TCG'],'1563315646324940840')
        self.assertEqual(c.GAME_ROLES['Vibes TCG'],'1563315709277114501')
        self.assertEqual(c.GAME_ROLES['Shadowverse Evolve'],'1563315730743693362')
        self.assertIsNone(c.GAME_ROLES[GAME])
    def test_configurable_roles(self):
        c=self.config({'ROLE_WORLD_OF_TANKS':'123','ROLE_BEYBLADE_X':'456'})
        self.assertEqual(c.GAME_ROLES['World of Tanks TCG'],'123')
        self.assertEqual(c.GAME_ROLES[GAME],'456')
    def test_unused_emojis_and_menu_capacity(self):
        c=self.config({})
        data={name:emoji for name,emoji,_ in c.GAME_DATA}
        self.assertEqual(data['Shadowverse Evolve'],'🔮')
        self.assertEqual(data[GAME],'🌪️')
        for game in ('Shadowverse Evolve',GAME):
            self.assertEqual(sum(e==data[game] for e in data.values()),1)
        self.assertLessEqual(len(data),24)  # Leave space for one generic option.
    def test_physical_tcg_formats(self):
        for title in ('Beyblade X Trading Card Game Booster Box',
                      'Blader League Booster Display',
                      'BEYBLADE X TCG Starter Deck',
                      'Blader League TCG Playmat'):
            self.assertEqual(games.registered_identity({'title':title}),GAME)
            self.assertTrue(game_matches(GAME,title))
        self.assertIn(GAME,games.GAMES)
    def test_toys_and_bare_announcements_not_inventory(self):
        for title in ('Beyblade X Launcher','Beyblade X Xtreme Battle Set',
                      'Beyblade X TCG Booster Box with Launcher','Beyblade X Stadium',
                      'Beyblade X Booster','Blader League coming in 2027',
                      'Beyblade X digital code card','Blader League Plush Figure'):
            self.assertIsNone(games.registered_identity({'title':title}),title)
            self.assertFalse(game_matches(GAME,title),title)
    def test_discovery_and_official_source(self):
        self.assertIn((GAME,'Beyblade X Blader League TCG'),GAME_QUERIES)
        self.assertTrue(explicit_tcg('blader-league'))
        self.assertIn({'game':GAME,'url':'https://bladerleague.com/news','identity':'blader league'},SOURCES)
    def test_older_family_rules_are_not_reindexed(self):
        self.assertEqual(games.explicit_family({'title':'Horo Beat HB-BP01 Booster Box'}),'JP')
        self.assertEqual(games.explicit_family({'title':'Wuthering Waves TCG English Booster Box'}),'UNKNOWN')
    def test_version(self):
        from app.version import VERSION,RELEASE_KIND
        self.assertEqual(VERSION,'1.7.8')
        self.assertEqual(RELEASE_KIND,'patch')

if __name__=='__main__':unittest.main()
