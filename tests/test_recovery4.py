import unittest
from unittest.mock import patch, AsyncMock
from urllib.parse import urlsplit, parse_qs
from app import shopify_adapter as adapter, shopify_pacing as pacing
from lotus_readiness_check import safe_reason


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.domain = 'recovery-test.example'
        pacing._STATES.clear()
        for name in ('_RECOVERY_COLLECTION_PAGES', '_RECOVERY_COLLECTION_DEEP_PAGES',
                     '_RECOVERY_COLLECTION_EMPTY_UNTIL', '_GENERAL_FEED_CURSOR',
                     '_GENERAL_FEED_LAST_ATTEMPT_AT', '_HEAD_LAST_ATTEMPT'):
            getattr(adapter, name).clear()

    async def run_scan(self, fetch, recovery=False, batch=None):
        obj = adapter.ShopifyAdapter(self.domain)
        session = AsyncMock()
        with patch.object(adapter.aiohttp, 'ClientSession', return_value=session), \
             patch.object(obj, '_get_json', side_effect=fetch), \
             patch.object(obj, '_discover_priority_collections', AsyncMock(return_value=[])), \
             patch.object(adapter, '_recovery_collection', return_value=[(0,'pokemon','Pokemon')]), \
             patch.object(adapter, 'classify_game', return_value='Pokemon'), \
             patch.object(adapter, 'shopify_cooldown_remaining', return_value=0), \
             patch.object(pacing, 'recovering', return_value=recovery), \
             patch.object(pacing, 'general_due', return_value=not recovery):
            await obj.fetch_products(on_batch=batch or AsyncMock())
        return obj

    async def test_actual_recovery_alternates_head_and_deep_one_request(self):
        pages=[]
        async def fetch(session,url,**kw):
            page=int(parse_qs(urlsplit(url).query)['page'][0]);pages.append(page)
            return {'products':[{'id':page*1000+i,'title':'Pokemon Booster Box'} for i in range(250)]}
        for _ in range(6):
            before=len(pages);obj=await self.run_scan(fetch,True)
            self.assertEqual(len(pages)-before,1)
            self.assertTrue(obj.diagnostics['limited_coverage'])
        self.assertEqual(pages,[1,2,1,3,1,4])

    async def test_processing_failure_does_not_advance(self):
        async def fetch(*a,**kw):return {'products':[{'id':1,'title':'Pokemon'}]*250}
        with self.assertRaises(RuntimeError):
            await self.run_scan(fetch,True,AsyncMock(side_effect=RuntimeError('db failed')))
        self.assertEqual(adapter._RECOVERY_COLLECTION_PAGES.get((self.domain,'pokemon'),1),1)

    async def test_short_head_is_not_requested_twice(self):
        calls=[]
        async def fetch(session,url,**kw):
            calls.append(kw['purpose']);return {'products':[{'id':1,'title':'Pokemon Booster Box'}]}
        obj=await self.run_scan(fetch)
        self.assertEqual(calls,['GENERAL_HEAD'])
        self.assertTrue(obj.diagnostics['general_sweep_complete'])
        self.assertEqual(obj.diagnostics['general_pages_successful'],1)

    async def test_full_head_continues_deep_cursor(self):
        calls=[]
        async def fetch(session,url,**kw):
            calls.append(kw['purpose'])
            return {'products':[{'id':i+1,'title':'Pokemon'} for i in range(250)] if len(calls)==1 else []}
        await self.run_scan(fetch)
        self.assertEqual(calls,['GENERAL_HEAD','GENERAL_PRODUCTS_PAGE_2'])

    def test_cap_and_short_deep_return_to_head(self):
        key=(self.domain,'pokemon')
        for page,count in ((20,250),(3,10)):
            adapter._record_collection_page(*key,page,count,True)
            self.assertEqual(adapter._RECOVERY_COLLECTION_PAGES[key],1)
            self.assertEqual(adapter._RECOVERY_COLLECTION_DEEP_PAGES[key],2)

    def test_short_head_clears_deep_cursor(self):
        key=(self.domain,'pokemon');adapter._RECOVERY_COLLECTION_DEEP_PAGES[key]=15
        adapter._record_collection_page(*key,1,12,True)
        self.assertNotIn(key,adapter._RECOVERY_COLLECTION_DEEP_PAGES)
        self.assertEqual(adapter._RECOVERY_COLLECTION_PAGES[key],1)


class ReadinessTests(unittest.TestCase):
    def test_reasons_redact_credentials_and_urls(self):
        self.assertEqual(safe_reason('PUBLIC_PAGE_HTTP_403'),'PUBLIC_PAGE_HTTP_403')
        for text in ('failed https://example.com/?key=PRIVATE','Authorization: Bearer PRIVATE','token=PRIVATE'):
            self.assertNotIn('PRIVATE',safe_reason(text))
        self.assertLessEqual(len(safe_reason('x'*500)),400)
