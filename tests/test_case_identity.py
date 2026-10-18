import ast
from pathlib import Path
import unittest
from app.case_identity import personal_case_format,normalize_case_event,shipping_case_event
from app.price_policy import case_destination,destination

TITLES=[
'Pokemon U-Treasure - Monster Ball Accessory Case (Case Only) [Pre-Order Dec 2026]',
'One Piece Card Game Official Sleeve & Card Case - Uta',
'DRAGON BALL SUPER CARD GAME FUSION WORLD - Official Card Case 01 - Son Goku',
'Dragon Ball Super Card Game Fusion World Official Card Case and Sleeve - Set 03 Gogeta',
'One Piece Card Game Official Card Case Limited Edition + 10 Don !! Special Card',
'Pokemon Card Game Glory of Team Rocket Attache Case Set',
]
class CaseTests(unittest.TestCase):
    def test_screenshot_products_never_shipping_cases(self):
        for title in TITLES:
            e=dict(product_name=title,product_type='Case',event_type='PRICE_DROP',price='40',old_price='41',currency='USD',region='JP')
            self.assertFalse(shipping_case_event(e),title)
            self.assertIsNone(case_destination(e))
            self.assertEqual(destination(e,{'CHANNEL_GLOBAL_PRICE_DROPS':'123'})['channel_id'],123)
    def test_briefcase_collection_and_accessories(self):
        self.assertEqual(personal_case_format(TITLES[-1]),('Collection Box','SEALED'))
        for title in TITLES[:-1]:self.assertEqual(personal_case_format(title)[1],'ACCESSORY')
        self.assertEqual(personal_case_format('Pokemon attaché case set'),('Collection Box','SEALED'))
    def test_real_case_retains_route(self):
        for title in ('One Piece Booster Box Sealed Case 12 Boxes','Magic: The Gathering - Fallout Commander Deck Case'):
            e=dict(product_name=title,product_type='Case',event_type='RESTOCK')
            self.assertEqual(case_destination(e,{'CHANNEL_CASE_SEALED_DEALS':'1541943138476621955'})['channel_id'],1541943138476621955)
    def test_stale_case_reference_dropped_without_mutation(self):
        e=dict(product_name=TITLES[-1],product_type='Case',reference_evidence={'kind':'MSRP','amount':'999'})
        new=normalize_case_event(e)
        self.assertNotIn('reference_evidence',new);self.assertIn('reference_evidence',e)
        self.assertEqual(new['product_type'],'Collection Box')
    def test_actual_adapter_precedes_generic_case_match(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'app/shopify_adapter.py').read_text())
        methods=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'infer_product_type','infer_product_category'}]
        ns={'personal_case_format':personal_case_format}
        exec(compile(ast.Module(body=methods,type_ignores=[]),'adapter','exec'),ns)
        for title in TITLES:
            typ,cat=personal_case_format(title)
            self.assertEqual(ns['infer_product_type'](title,'Case'),typ)
            self.assertEqual(ns['infer_product_category'](title,'Case'),cat)
    def test_worker_corrects_before_enrichment(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'app/worker.py').read_text())
        route=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='route_event_to_discord')
        assignments=[n for n in route.body if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name)]
        names=[n.value.func.id for n in assignments]
        self.assertLess(names.index('normalize_case_event'),names.index('enrich'))
    def test_price_increase_stays_unrouted(self):
        e=dict(product_name=TITLES[-1],product_type='Case',event_type='PRICE_INCREASE',price='42',old_price='41',currency='USD',region='JP')
        self.assertIsNone(destination(e)['channel_id']);self.assertIsNone(case_destination(e))
