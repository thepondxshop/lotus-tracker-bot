import ast,asyncio,json,time
from pathlib import Path
from types import SimpleNamespace
from collections import defaultdict
from unittest.mock import patch
import unittest
from app import shopify_pacing as pacing
from app.tcg_identity import has_fusion_world_identity,title_identity,FUSION_WORLD_GAME

class PacingTests(unittest.TestCase):
    def setUp(self):pacing._STATES.clear()
    def test_collection_success_never_clears_general_block(self):
        with patch.object(pacing.time,'monotonic',return_value=100):pacing.throttled('test','GENERAL_HEAD')
        for n in range(40):
            with patch.object(pacing.time,'monotonic',return_value=200+n*60):pacing.succeeded('test','PRIORITY_COLLECTION')
        self.assertTrue(pacing.recovering('test'));self.assertTrue(pacing.general_blocked('test'))
    def test_backoff_and_atomic_probe_reservation(self):
        for now,expected in ((0,900),(900,1800),(2700,3600),(6300,3600)):
            with patch.object(pacing.time,'monotonic',return_value=now):
                pacing.throttled('test','GENERAL_HEAD')
                self.assertEqual(pacing._STATES['test'].general_retry_at,now+expected)
        with patch.object(pacing.time,'monotonic',return_value=9900):
            self.assertTrue(pacing.begin_general_attempt('test'))
            self.assertFalse(pacing.begin_general_attempt('test'))
    def test_valid_general_success_releases_endpoint_block(self):
        pacing.throttled('test','GENERAL_HEAD');pacing.succeeded('test','GENERAL_PRODUCTS_PAGE_1')
        self.assertFalse(pacing.general_blocked('test'))
    def test_collection_throttle_keeps_legacy_recovery(self):
        with patch.object(pacing.time,'monotonic',return_value=0):pacing.throttled('test','PRIORITY_COLLECTION')
        for n in range(21):
            with patch.object(pacing.time,'monotonic',return_value=1+n*60):pacing.succeeded('test','PRIORITY_COLLECTION')
        self.assertFalse(pacing.general_blocked('test'));self.assertFalse(pacing.recovering('test'))

class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_request_defers_and_validates_probe_payload(self):
        pacing._STATES.clear()
        tree=ast.parse((Path(__file__).resolve().parents[1]/'app/shopify_adapter.py').read_text())
        method=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='_request')
        class Response:
            status=200;headers={}
            body='{"products": []}'
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def text(self):return self.body
        response=Response();calls=[]
        def get(*args,**kw):calls.append(args);return response
        class RequestError(Exception):
            def __init__(self,*args,**kwargs):super().__init__(*args)
        ns=dict(asyncio=asyncio,json=json,time=time,shopify_pacing=pacing,shopify_cooldown_remaining=lambda d:0,
                _DOMAIN_LAST_REQUEST_AT={},SHOPIFY_REQUEST_DELAY_SECONDS=0,
                _thepondx_signature_headers=lambda u:{},operator_request_headers=lambda u,d:{},record_response=lambda **kw:{},
                ShopifyHTTPError=RequestError,ShopifyRateLimitError=RequestError)
        exec(compile(ast.Module(body=[method],type_ignores=[]),'adapter','exec'),ns)
        obj=SimpleNamespace(domain='test',diagnostics=defaultdict(int),_domain_lock=lambda:asyncio.Lock())
        pacing.throttled('test','GENERAL_HEAD')
        self.assertIsNone(await ns['_request'](obj,SimpleNamespace(get=get),'https://test/products.json',purpose='GENERAL_HEAD',expect_json=True,required=True))
        self.assertEqual(calls,[])
        pacing._STATES['test'].general_retry_at=0;response.body='{"error": "not products"}'
        await ns['_request'](obj,SimpleNamespace(get=get),'https://test/products.json',purpose='GENERAL_HEAD',expect_json=True,required=True)
        self.assertTrue(pacing.general_blocked('test'))
        pacing._STATES['test'].general_retry_at=0;response.body='{"products": []}';ns['_DOMAIN_LAST_REQUEST_AT'].clear()
        await ns['_request'](obj,SimpleNamespace(get=get),'https://test/products.json',purpose='GENERAL_HEAD',expect_json=True,required=True)
        self.assertFalse(pacing.general_blocked('test'));self.assertEqual(len(calls),2)

class ProbePlanTests(unittest.TestCase):
    def test_probe_replaces_collection_and_stays_partial(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'app/shopify_adapter.py').read_text())
        fetch=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='fetch_products')
        assignment=next(n for n in ast.walk(fetch) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='priority_collections' for t in n.targets))
        # Compile the actual async selection expression, with a failing collection selector.
        asyncfn=ast.AsyncFunctionDef(name='select_probe',args=ast.arguments(posonlyargs=[],args=[],kwonlyargs=[],kw_defaults=[],defaults=[]),body=[assignment,ast.Return(value=ast.Name(id='priority_collections',ctx=ast.Load()))],decorator_list=[])
        def forbidden(*args):raise AssertionError('Probe must replace collection request')
        ns=dict(general_probe=True,recovery=True,self=SimpleNamespace(domain='test'),_recovery_collection=forbidden)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[asyncfn],type_ignores=[])),'adapter','exec'),ns)
        self.assertEqual(asyncio.run(ns['select_probe']()),[])
        branch=next(n for n in ast.walk(fetch) if isinstance(n,ast.If) and isinstance(n.test,ast.Name) and n.test.id=='general_probe')
        ns=dict(general_probe=True,run_general=False,self=SimpleNamespace(domain='test',diagnostics={}))
        exec(compile(ast.Module(body=[branch],type_ignores=[]),'adapter','exec'),ns)
        self.assertTrue(ns['run_general']);self.assertTrue(ns['self'].diagnostics['limited_coverage'])

class IdentityTests(unittest.TestCase):
    def test_reported_title(self):
        title='DRAGON BALL SUPER TCG: FUSION WORLD 09 BOOSTER BOX (FB09)'
        self.assertTrue(has_fusion_world_identity(title))
        self.assertEqual(title_identity(title),FUSION_WORLD_GAME)
    def test_masters_and_bare_codes_remain_separate(self):
        for title in ('DRAGON BALL SUPER TCG: MASTERS: ULTRA BOUT SET 5 BOOSTER PACK (B32)','FB09 Booster Box','Dragon Ball Super TCG Booster Box'):
            self.assertFalse(has_fusion_world_identity(title))
