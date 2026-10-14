import ast
import asyncio
from datetime import datetime,timezone,timedelta
from pathlib import Path
import unittest
from app.merchandise_guard import building_product
from app.asia_coverage import summarize

class CoverageTest(unittest.TestCase):
    def test_building_identity(self):
        self.assertTrue(building_product('LEGO - Pokemon - Iconic Trainer Moments Poke Ball [72154]'))
        self.assertTrue(building_product('Pokemon item','Building Blocks'))
        self.assertFalse(building_product('Pokemon TCG Booster Box','Sealed'))
        self.assertFalse(building_product('Riftbound Booster Box'))
    def test_real_shopify_classifier(self):
        from app.shopify_adapter import classify_game,is_non_tcg_merchandise
        item=dict(title='LEGO Pokemon Poke Ball [72154]',product_type='LEGO',tags=['Pokemon','TCG'])
        self.assertIsNone(classify_game(item))
        self.assertTrue(is_non_tcg_merchandise(item))
        self.assertEqual(classify_game(dict(title='Pokemon TCG Booster Box',product_type='Booster Box')),'Pokemon')
    def test_queued_lego_stops_before_dispatch(self):
        tree=ast.parse(Path('app/worker.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='route_event_to_discord')
        ns={'building_product':building_product}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'worker','exec'),ns)
        result=asyncio.run(ns['route_event_to_discord'](None,dict(game='Pokemon',product_name='LEGO Pokemon Set')))
        self.assertFalse(result)
    def test_registry_states(self):
        now=datetime(2026,10,14,tzinfo=timezone.utc)
        records=[dict(domain='https://www.plazajapan.com',active=True,product_count=4,last_product_seen=now),dict(domain='meccha-japan.com',active=False,product_count=3,last_product_seen=now),dict(domain='japan-figure.com',active=True,product_count=0,last_product_seen=None),dict(domain='kimstcgstore.com',active=True,product_count=4,last_product_seen=now-timedelta(minutes=10))]
        rows={r['domain']:r for r in summarize(records,now)}
        self.assertEqual(rows['plazajapan.com']['state'],'RECENT_PRODUCT_RECORD')
        self.assertEqual(rows['meccha-japan.com']['state'],'INACTIVE')
        self.assertEqual(rows['japan-figure.com']['state'],'NO_PRODUCT_RECORDS')
        self.assertEqual(rows['kimstcgstore.com']['state'],'STALE_OR_UNKNOWN_PRODUCT_RECORD')
        self.assertEqual(rows['amiami.com']['state'],'NOT_IN_STORE_REGISTRY')

if __name__=='__main__': unittest.main()
