import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from app.registered_games import registered_identity
from app.riot_schedule import PRODUCTS, epoch, embeds

class IdentityTests(unittest.TestCase):
    def test_reported_cookie(self):
        self.assertEqual(registered_identity({'title':'Age of Heroes and Kingdoms Booster Display [BS3–BS4]'}),'CookieRun: Braverse')
    def test_reported_final_fantasy(self):
        self.assertEqual(registered_identity({'title':'Legacy Collection: Booster Display Master Case','store_name':'Nova Break'}),'Final Fantasy TCG')
        self.assertIsNone(registered_identity({'title':'Legacy Collection: Booster Display Master Case'}))
    def test_product_taxonomy_and_conflicts(self):
        self.assertEqual(registered_identity({'title':'Legacy Collection Booster Display','vendor':'Final Fantasy TCG'}),'Final Fantasy TCG')
        self.assertIsNone(registered_identity({'title':'Legacy Collection Booster Display','tags':['Final Fantasy TCG','CookieRun Braverse']}))
        self.assertIsNone(registered_identity({'title':'MTG Final Fantasy Booster Box','vendor':'Final Fantasy TCG'}))
    def test_known_products_not_admin_candidates(self):
        from app.tcg_discovery_admin import candidate_from_event
        from app.tcg_identity import NEW_TCG
        for title,store in [('Age of Heroes and Kingdoms Booster Display [BS3–BS4]','Wulf Gaming'),('Legacy Collection: Booster Display Master Case','Nova Break')]:
            self.assertIsNone(candidate_from_event(dict(product_name=title,store_name=store,game=NEW_TCG)))

class ScheduleTests(unittest.TestCase):
    def test_retail_and_drawing_separate(self):
        self.assertEqual([p['release'] for p in PRODUCTS],[None,None,None,'2026-12-04'])
        self.assertEqual(len(embeds()),4)
        self.assertTrue(all(e.image.url.startswith('https://cmsassets.rgpub.io/') for e in embeds()))
    def test_dst(self):
        for value in ['2026-10-27T09:00:00','2026-11-13T09:00:00']:
            self.assertEqual(datetime.fromtimestamp(epoch(value),ZoneInfo('America/New_York')).hour,12)

class ImportTests(unittest.IsolatedAsyncioTestCase):
    async def test_import_never_uses_registration_as_release(self):
        from unittest.mock import AsyncMock, patch
        from types import SimpleNamespace
        from app.riot_schedule import import_catalog
        catalog=SimpleNamespace(add=AsyncMock(return_value={'release':{'id':1}}),
            add_source=AsyncMock(return_value={'source':{'id':2}}),confirm=AsyncMock())
        runtime=SimpleNamespace(store=SimpleNamespace(catalog=catalog,save_image=AsyncMock()),cache={})
        content=' '.join(p['title'] for p in PRODUCTS)+' October 27, 9:00 AM PT October 30, 9:00 AM PT November 13, 9:00 AM PT November 16, 9:00 AM PT December 4'
        page={'blades':[{'type':'articleRichText','richText':{'body':content}}]}
        with patch('app.riot_schedule.fetch',new=AsyncMock(return_value='html')),patch('app.riot_schedule.next_page',return_value=page):
            await import_catalog(runtime,123,456)
        self.assertEqual([c.kwargs['release_date'] for c in catalog.confirm.call_args_list],[None,None,None,'2026-12-04'])
        self.assertEqual(runtime.store.save_image.await_count,4)
        catalog.add.reset_mock()
        with patch('app.riot_schedule.fetch',new=AsyncMock(return_value='html')),patch('app.riot_schedule.next_page',return_value={'blades':[]}):
            with self.assertRaises(ValueError):await import_catalog(runtime,123,456)
        catalog.add.assert_not_called()
