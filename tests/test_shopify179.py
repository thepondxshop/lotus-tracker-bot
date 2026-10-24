import asyncio
import unittest
from unittest.mock import patch
from app.shopify_request_gate import RequestGate

class Clock:
    def __init__(self):self.now=1000.0
    def __call__(self):return self.now
    async def sleep(self,n):self.now+=n

class GateTests(unittest.IsolatedAsyncioTestCase):
    async def test_cross_store_starts_are_spaced(self):
        c=Clock();g=RequestGate(clock=c,sleep=c.sleep);starts=[]
        async def one():
            await g.acquire();starts.append(c())
        await asyncio.gather(*(one() for _ in range(43)))
        self.assertTrue(all(b-a>=.349 for a,b in zip(starts,starts[1:])))
    async def test_one_store_cannot_trigger_shared_hold(self):
        c=Clock();g=RequestGate(clock=c,sleep=c.sleep)
        for _ in range(50):g.throttled('one')
        self.assertEqual(g.blocked_until,0)
    async def test_burst_hold_and_recovery(self):
        c=Clock();g=RequestGate(clock=c,sleep=c.sleep)
        for i in range(5):g.throttled(str(i))
        self.assertEqual(g.blocked_until,1060)
        self.assertGreaterEqual(await g.acquire(),60)
        g.products_succeeded();c.now+=300
        for _ in range(20):g.products_succeeded()
        self.assertEqual(g.interval,.75)
    async def test_old_throttles_expire(self):
        c=Clock();g=RequestGate(clock=c,sleep=c.sleep)
        for i in range(10):
            g.throttled(str(i));c.now+=16
        self.assertEqual(g.blocked_until,0)
    async def test_hold_extension_rechecked_after_sleep(self):
        c=Clock();g=RequestGate(clock=c,sleep=c.sleep);g.blocked_until=c()+60
        calls=[]
        async def sleep(n):
            await c.sleep(n);calls.append(n)
            if len(calls)==1:g.blocked_until=c()+30
        g.sleep=sleep
        self.assertEqual(await g.acquire(),90)
    async def test_cancelled_wait_releases_lock(self):
        c=Clock();event=asyncio.Event()
        async def sleep(n):await event.wait()
        g=RequestGate(clock=c,sleep=sleep);g.blocked_until=c()+60
        task=asyncio.create_task(g.acquire());await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertFalse(g.lock.locked())

class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_adapter_waits_before_signing_and_honors_retry_after(self):
        from app import shopify_adapter as a
        from app import shopify_request_gate as gate_module
        import random
        events=[]
        class Response:
            status=429
            headers={'Retry-After':'120'}
            async def text(self):return 'Too many requests'
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
        class Session:
            def get(self,*args,**kwargs):events.append('request');return Response()
        async def gate():events.append('gate');return 2.0
        def sign(*args):events.append('sign');return {}
        domain='regression179.example'
        adapter=a.ShopifyAdapter(domain)
        with patch.object(gate_module,'acquire',gate), patch.object(gate_module,'throttled') as throttled, patch.object(a,'_thepondx_signature_headers',sign), patch.object(a,'operator_request_headers',return_value={}), patch.object(random,'uniform',return_value=7):
            result=await adapter._request(Session(),'https://'+domain+'/products.json',purpose='PRIORITY_COLLECTION',expect_json=True,required=False)
        self.assertIsNone(result)
        self.assertEqual(events,['gate','sign','request'])
        self.assertEqual(adapter.diagnostics['http_429'],1)
        self.assertEqual(adapter.diagnostics['requests_attempted'],1)
        self.assertEqual(adapter.diagnostics['cooldown_remaining_seconds'],127)
        throttled.assert_called_once_with(domain)
        self.assertGreater(a.shopify_cooldown_remaining(domain),126)
        # An existing store cooldown must not reach the shared gate or network.
        with patch.object(gate_module,'acquire') as gate_mock:
            await adapter._request(Session(),'https://'+domain+'/products.json',purpose='PRIORITY_COLLECTION',expect_json=True,required=False)
            gate_mock.assert_not_called()
        self.assertEqual(events,['gate','sign','request'])

if __name__=='__main__':unittest.main()
