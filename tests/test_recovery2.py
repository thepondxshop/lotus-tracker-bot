import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest
from datetime import datetime,timezone,timedelta
from app import collection_priority as cp
from app.distributor_catalog import record,packaging
from app.distributor_references import install,matched

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        cp._PROVEN.clear();cp._TURNS.clear();cp.WAITING.clear()
    def test_logged_comic_feeds_excluded(self):
        for handle in ('all-future-pre-order-comics','august-comic-preorder-catalog','comic-books-incentives-no-preorders','comics-excluding-pre-orders','december-2023-comic-pre-order-catalog','dungeons-dragons-pre-orders'):
            self.assertFalse(cp.tcg_candidate(handle),handle)
    def test_mixed_tcg_and_generic_retained(self):
        for handle in ('comics-and-pokemon-tcg','magic-the-gathering-dungeons-dragons','all-pre-orders-ship-when-complete','new-arrivals'):
            self.assertTrue(cp.tcg_candidate(handle),handle)
    def test_recovery_prefers_explicit_tcg(self):
        rows=[(-200,'all-pre-orders','All Preorders'),(-10,'pokemon','Pokemon'),(-300,'comic-preorders','Comic preorders')]
        self.assertEqual(cp.choose('test',rows,{}, {},100)[0][1],'pokemon')
    def test_deferred_collections_not_requested(self):
        rows=[(0,'pokemon','Pokemon')]
        self.assertEqual(cp.choose('test',rows,{}, {('test','pokemon'):200},100),[])
        self.assertIn('test',cp.WAITING)
    def test_proven_feed_retains_two_of_three_turns(self):
        cp._PROVEN[('test','pokemon')]=100
        rows=[(0,'pokemon','Pokemon'),(0,'one-piece','One Piece')];last={}
        self.assertEqual([cp.choose('test',rows,last,{},101)[0][1] for _ in range(3)],['pokemon','pokemon','one-piece'])
    def test_actual_discovery_ranks_before_cap(self):
        path=Path(__file__).resolve().parents[1]/'app/shopify_adapter.py'
        tree=ast.parse(path.read_text())
        method=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='_discover_priority_collections')
        handles=['generic-preorder-'+str(i) for i in range(20)]+['pokemon','one-piece']
        async def get_text(session,url,**kwargs):return ['sitemap_collections.xml'] if url.endswith('sitemap.xml') else handles
        async def get_json(*args,**kwargs):raise AssertionError('Unexpected fallback request')
        ns={'time':SimpleNamespace(monotonic=lambda:100),'_PRIORITY_COLLECTION_CACHE':{},'SHOPIFY_COLLECTION_CACHE_SECONDS':1800,'shopify_pacing':SimpleNamespace(recovering=lambda d:False),
            '_collection_score':lambda h,t:120 if 'preorder' in h else 10,'normalize_text':lambda x:x,'_xml_locations':lambda x:x,'_collection_handle_from_url':lambda x,d:x,
            'MAX_COLLECTION_SITEMAPS':8,'MAX_COLLECTION_JSON_PAGES':8,'MAX_PRIORITY_COLLECTIONS':12,'collection_priority':cp}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'adapter','exec'),ns)
        obj=SimpleNamespace(domain='test',base_url='https://test',diagnostics={'collections_seen':0,'collection_sitemaps_checked':0},_get_text=get_text,_get_json=get_json)
        rows=asyncio.run(ns['_discover_priority_collections'](obj,None))
        self.assertEqual({r[1] for r in rows[:2]},{'pokemon','one-piece'})
        self.assertEqual(len(rows),12)

class DisplayTests(unittest.TestCase):
    def tearDown(self):install([],[])
    def test_ambiguous_display_units_blocked(self):
        for name in ('Azuki Booster Pack Display','MTG Commander Deck Display','MTG Commander Deck, Collector Edition Display','Pokemon Starter Deck Display'):
            self.assertIsNone(packaging(name),name)
    def test_box_display_remains_supported(self):
        self.assertEqual(packaging('Pokemon Booster Display'),'BOOSTER BOX')
        self.assertEqual(packaging('Pokemon Booster Display Box'),'BOOSTER BOX')
    def test_old_ready_display_cannot_match_sku(self):
        r=record('https://www.phdgames.com/2026/10/15/test/','ABC','Azuki Booster Pack Display','100',(datetime.now(timezone.utc)+timedelta(days=5)).date().isoformat(),'PHD')
        r.update(ready=True,product_type='BOOSTER PACK')
        e=dict(product_url='https://example.com/test',product_name='Azuki Booster Pack',product_type='Booster Pack',game='Azuki',currency='USD',region='US',product_family='GLOBAL_STANDARD')
        install([r],[dict(e,sku='ABC')]);self.assertEqual(matched(e),[])
