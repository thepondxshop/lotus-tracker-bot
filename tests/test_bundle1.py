import asyncio
import contextlib
import io
import json
import sys
import types
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from app.collection_priority import tcg_candidate, choose
from app.store_signing_status import signing_status, onboarding_note
from app.dispatch_observability import primary_confirmed, traced_dispatch

class BundleTest(unittest.TestCase):
    def test_unrelated_and_mixed(self):
        for x in ['warhammer-pre-orders','board-games','miniatures-new-arrivals','jigsaw-puzzles']:
            self.assertFalse(tcg_candidate(x))
        for x in ['pre-order','kickstarter-pre-order','pokemon-preorders','warhammer-magic-the-gathering','new-tcg-model-kits']:
            self.assertTrue(tcg_candidate(x))
        self.assertTrue(tcg_candidate('warhammer','Magic the Gathering cards'))
    def test_discovery_score(self):
        from app.shopify_adapter import _collection_score
        self.assertEqual(_collection_score("warhammer-pre-orders"),0)
        self.assertGreater(_collection_score("pokemon-preorders"),0)

    def test_recovery_filter(self):
        chosen=choose('test',[(0,'warhammer-pre-orders',''),(0,'pokemon','')],{},{},100)
        self.assertEqual(chosen[0][1],'pokemon')
    def test_signing_states(self):
        module=types.SimpleNamespace(allowed_stores=lambda:set(),operator_request_headers=lambda *args:{})
        with patch.dict(sys.modules,lotus_bot_auth=module):
            self.assertEqual(signing_status('example.com')['state'],'NOT_ALLOWLISTED')
            self.assertIn('LOTUS_BOT_AUTH_STORES',onboarding_note('example.com'))
            module.allowed_stores=lambda:{'example.com'}
            self.assertEqual(signing_status('example.com')['state'],'SIGNING_DISABLED')
            module.operator_request_headers=lambda *args:{'Signature':'secret','Signature-Input':'secret'}
            self.assertEqual(signing_status('example.com')['state'],'HEADERS_READY')
            self.assertNotIn('secret',onboarding_note('example.com'))
            module.operator_request_headers=lambda *args:1/0
            self.assertEqual(signing_status('example.com')['state'],'CONFIG_ERROR')
    def test_primary_timing(self):
        at=datetime(2026,10,13,20,tzinfo=timezone.utc)
        message=types.SimpleNamespace(id=12,channel=types.SimpleNamespace(id=34),created_at=at)
        event={'_lotus_enqueued_at':at.timestamp()-4,'store_name':'Fixture'}
        async def send(): primary_confirmed(message,event)
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            asyncio.run(traced_dispatch(send(),event,timeout=1))
        row=json.loads(output.getvalue().split(' | ',1)[1])
        self.assertEqual(row['enqueue_to_primary_seconds'],4)
        self.assertEqual(row['channel_id'],'34')
        self.assertGreaterEqual(row['dispatch_to_primary_seconds'],0)
        for invalid in [True,float('nan'),at.timestamp()+1,None]:
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                primary_confirmed(message,{'_lotus_enqueued_at':invalid})
            self.assertIsNone(json.loads(output.getvalue().split(' | ',1)[1])['enqueue_to_primary_seconds'])

if __name__=='__main__': unittest.main()
