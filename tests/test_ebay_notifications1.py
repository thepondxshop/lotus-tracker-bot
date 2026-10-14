import asyncio
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from app.marketplaces.ebay_notifications import (Settings, ConfigurationError, install,
    signature_header, verify_payload, VerificationUnavailable, PATH)

# Public test vector from eBay/event-notification-nodejs-sdk, Apache-2.0.
# Copyright 2021 eBay Inc. See EBAY_SDK_LICENSE.txt and README_EBAY_NOTIFY1.md.
FIXTURE=json.loads(Path(__file__).with_name('ebay_sdk_fixture.json').read_text())
ENDPOINT='https://lotus-bot-identity-production.up.railway.app'+PATH
TOKEN='a'*64

class Keys:
    def __init__(self,fail=False):self.fail=fail;self.calls=0
    async def start(self):pass
    async def close(self):pass
    async def get(self,kid):
        self.calls+=1
        if self.fail:raise VerificationUnavailable()
        return FIXTURE['response']

class NotificationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.keys=Keys()
        self.app=web.Application(client_max_size=16384)
        install(self.app,Settings(ENDPOINT,TOKEN),self.keys)
        self.client=TestClient(TestServer(self.app))
        await self.client.start_server()
    async def asyncTearDown(self):await self.client.close()
    async def test_challenge_exact_url_and_order(self):
        r=await self.client.get(PATH+'?challenge_code=abc')
        self.assertEqual(r.status,200)
        self.assertEqual((await r.json())['challengeResponse'],hashlib.sha256(('abc'+TOKEN+ENDPOINT).encode()).hexdigest())
    async def test_missing_or_repeated_challenge(self):
        for query in ('','?challenge_code=','?challenge_code=a&challenge_code=b'):
            self.assertEqual((await self.client.get(PATH+query)).status,400)
    async def test_official_signed_notification_and_duplicate(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            for _ in range(2):
                r=await self.client.post(PATH,json=FIXTURE['message'],headers={'X-EBAY-SIGNATURE':FIXTURE['signature']})
                self.assertEqual(r.status,204)
        self.assertNotIn('test_user',output.getvalue())
        self.assertNotIn(FIXTURE['message']['notification']['data']['userId'],output.getvalue())
    async def test_unsigned_no_key_lookup(self):
        r=await self.client.post(PATH,json=FIXTURE['message'])
        self.assertEqual(r.status,412)
        self.assertEqual(self.keys.calls,0)
    async def test_tampered_payload(self):
        message=json.loads(json.dumps(FIXTURE['message']))
        message['notification']['data']['username']='tampered'
        r=await self.client.post(PATH,json=message,headers={'X-EBAY-SIGNATURE':FIXTURE['signature']})
        self.assertEqual(r.status,412)
    async def test_api_outage_not_acknowledged(self):
        self.keys.fail=True
        r=await self.client.post(PATH,json=FIXTURE['message'],headers={'X-EBAY-SIGNATURE':FIXTURE['signature']})
        self.assertEqual(r.status,503)
    async def test_oversized(self):
        r=await self.client.post(PATH,data=b'x'*20000,headers={'X-EBAY-SIGNATURE':FIXTURE['signature']})
        self.assertEqual(r.status,413)
    async def test_wrong_topic(self):
        message=json.loads(json.dumps(FIXTURE['message']));message['metadata']['topic']='OTHER'
        r=await self.client.post(PATH,json=message,headers={'X-EBAY-SIGNATURE':FIXTURE['signature']})
        self.assertEqual(r.status,400)
    async def test_invalid_header(self):
        r=await self.client.post(PATH,json=FIXTURE['message'],headers={'X-EBAY-SIGNATURE':'bad'})
        self.assertEqual(r.status,412)

class ConfigurationTest(unittest.TestCase):
    def test_config(self):
        env={'EBAY_DELETION_ENDPOINT':ENDPOINT,'EBAY_DELETION_VERIFICATION_TOKEN':TOKEN,
             'EBAY_PRODUCTION_CLIENT_ID':'test','EBAY_PRODUCTION_CLIENT_SECRET':'test'}
        with patch.dict(os.environ,env,clear=True):
            self.assertEqual(Settings.from_env().mode,'PREVIEW_ONLY')
            for name,value in [('EBAY_DATA_RETENTION_MODE','PERSISTENT'),('EBAY_DELETION_ENDPOINT','http://localhost/a'),('EBAY_DELETION_VERIFICATION_TOKEN','short')]:
                with patch.dict(os.environ,{name:value}):
                    with self.assertRaises(ConfigurationError):Settings.from_env()
    def test_algorithm_mismatch(self):
        h,s=signature_header(FIXTURE['signature']);h['digest']='SHA256'
        with self.assertRaises(ValueError):verify_payload(b'{}',FIXTURE['message'],h,s,FIXTURE['response'])
    def test_existing_identity_routes_survive(self):
        from lotus_bot_auth import create_app
        with patch.dict(os.environ,{},clear=True):app=create_app()
        paths={r.resource.canonical for r in app.router.routes()}
        self.assertTrue({'/','/health',PATH,'/ebay/health'}.issubset(paths))

class PreviewTest(unittest.IsolatedAsyncioTestCase):
    async def test_preview_output_redacted(self):
        from app.marketplaces.ebay import EbayPreview
        response=MagicMock()
        response.status=200
        session=MagicMock()
        session.get.return_value.__aenter__=AsyncMock(return_value=response)
        session.get.return_value.__aexit__=AsyncMock(return_value=False)
        session_context=MagicMock()
        session_context.__aenter__=AsyncMock(return_value=session)
        session_context.__aexit__=AsyncMock(return_value=False)
        data={'itemSummaries':[{'itemId':'test-id','title':'Private listing title',
              'itemWebUrl':'https://www.ebay.com/itm/123','price':{'value':'25','currency':'USD'}}]}
        with patch('app.marketplaces.ebay.aiohttp.ClientSession',return_value=session_context), \
             patch.object(EbayPreview,'token',new=AsyncMock(return_value='test-token')), \
             patch('app.marketplaces.ebay.response_json',new=AsyncMock(return_value=data)):
            result=await EbayPreview('production').search('cards')
        self.assertEqual(result['accepted'],1)
        self.assertEqual(result['state'],'SEARCH_RESPONSE_VALIDATED')
        self.assertNotIn('candidates',result)
        self.assertNotIn('Private listing title',json.dumps(result))
        self.assertNotIn('test-id',json.dumps(result))
        self.assertFalse(result['live_pipeline_enabled'])

if __name__=='__main__':unittest.main()
