import ast
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
from app import member_xp as xp
from app import affiliate_registry as ar
from app.marketplaces.ebay_capacity import settings, SearchPages
from app.major_retailers.retry_policy import remaining

class XPTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,21,tzinfo=timezone.utc)
        self.row=dict(last_message_id=1,last_awarded_at=None,last_content_hash=None,day=self.now.date(),daily_xp=0)
    def test_levels(self):
        self.assertEqual([xp.level(n) for n in (0,99,100,399,400)], [0,0,1,1,2])
    def test_content(self):
        for value in ('hi','aaaaaaaaaaaaaaaa','!this is a command','https://example.com'):
            self.assertIsNone(xp.content_key(value))
        self.assertEqual(xp.content_key('Hello everyone today'),xp.content_key(' HELLO  everyone today '))
    def test_cooldown_boundary(self):
        self.row['last_awarded_at']=self.now-timedelta(seconds=59)
        self.assertEqual(xp.award_amount(self.row,'new',2,self.now),0)
        self.row['last_awarded_at']=self.now-timedelta(seconds=60)
        self.assertEqual(xp.award_amount(self.row,'new',2,self.now),10)
    def test_duplicate_and_old_message(self):
        self.assertEqual(xp.award_amount(self.row,'new',1,self.now),0)
        self.row['last_content_hash']='new'
        self.assertEqual(xp.award_amount(self.row,'new',2,self.now),0)
    def test_daily_cap_and_reset(self):
        self.row['daily_xp']=200
        self.assertEqual(xp.award_amount(self.row,'new',2,self.now),0)
        self.row['day']=self.now.date()-timedelta(days=1)
        self.assertEqual(xp.award_amount(self.row,'new',2,self.now),10)
    def test_message_filter(self):
        m=SimpleNamespace(guild=object(),author=SimpleNamespace(bot=False),webhook_id=None,channel=SimpleNamespace(id=123),content='Hello everyone today')
        with patch.dict('os.environ',LOTUS_XP_CHANNEL_IDS='123'):
            self.assertTrue(xp.eligible_message(m))
            m.author.bot=True;self.assertFalse(xp.eligible_message(m))
            m.author.bot=False;m.guild=None;self.assertFalse(xp.eligible_message(m))
    def test_main_wiring(self):
        source=Path('main.py').read_text()
        ast.parse(source)
        self.assertIn('await install_member_xp(self, self.database_ready)',source)

class ListenerTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_listener(self):
        store=SimpleNamespace(award=AsyncMock())
        await xp.MemberXP(None,store,False).on_message(None)
        store.award.assert_not_called()
    async def test_listener_awards(self):
        store=SimpleNamespace(award=AsyncMock())
        m=SimpleNamespace(id=3,guild=SimpleNamespace(id=1),author=SimpleNamespace(id=2,bot=False),webhook_id=None,channel=SimpleNamespace(id=123),content='Hello everyone today')
        with patch.dict('os.environ',LOTUS_XP_CHANNEL_IDS='123'):
            await xp.MemberXP(None,store,True).on_message(m)
        store.award.assert_awaited_once_with(1,2,3,xp.content_key(m.content))

class AffiliateTests(unittest.TestCase):
    def row(self):
        return dict(product_url='https://shop.example/products/one?variant=1',affiliate_url='https://shop.example/products/one?ref=approved',provider='direct',store_name='Store',approved=True,discord_approved=True,expires_at='2099-01-01T00:00:00Z')
    def test_exact_match_and_variant(self):
        r=self.row()
        with patch.object(ar,'load',return_value=ar.validate([r])):
            self.assertEqual(ar.lookup(r['product_url'],'Store'),(r['affiliate_url'],True))
            self.assertFalse(ar.lookup(r['product_url'].replace('=1','=2'),'Store')[1])
            self.assertFalse(ar.lookup(r['product_url'],'Other')[1])
    def test_approval_required(self):
        r=self.row();r['discord_approved']=False
        with self.assertRaises(ValueError):ar.validate([r])
    def test_expired_link_not_used(self):
        r=self.row();r['expires_at']='2000-01-01T00:00:00Z'
        with patch.object(ar,'load',return_value=ar.validate([r])):
            self.assertEqual(ar.lookup(r['product_url'],'Store'),(r['product_url'],False))
    def test_invalid_url(self):
        for u in ('http://shop.example','https://user:pass@shop.example','https://shop.example:123/x','https://shop.example/a b',None):
            self.assertFalse(ar.valid_url(u))
    def test_duplicate(self):
        with self.assertRaises(ValueError):ar.validate([self.row(),self.row()])
    def test_unapproved_host(self):
        r=self.row();r['affiliate_url']='https://elsewhere.example/x'
        with self.assertRaises(ValueError):ar.validate([r])

class CapacityTests(unittest.TestCase):
    def test_defaults_and_bounds(self):
        self.assertEqual(settings({}),dict(details=3,interval=135,pages=5))
        self.assertEqual(settings({'LOTUS_EBAY_DETAILS_PER_CYCLE':'999'})['details'],10)
        self.assertEqual(settings({'LOTUS_EBAY_CYCLE_SECONDS':'0'})['interval'],60)
        self.assertEqual(settings({'LOTUS_EBAY_TARGET_PAGES':'bad'})['pages'],5)
    def test_pages_reset_and_isolation(self):
        p=SearchPages(2);self.assertEqual(p.offset('a'),0)
        p.advance('a',100);self.assertEqual(p.offset('a'),100)
        self.assertEqual(p.offset('b'),0)
        p.advance('a',100);self.assertEqual(p.offset('a'),0)
        p.advance('a',100);p.advance('a',50);self.assertEqual(p.offset('a'),0)
    def test_bounded_state(self):
        p=SearchPages()
        for i in range(1100):p.advance(str(i),100)
        self.assertEqual(len(p.cursors),1000)
    def test_fresh_head_between_deep_pages(self):
        p=SearchPages(3);offsets=[]
        for _ in range(7):
            offsets.append(p.offset('key'));p.advance('key',100)
        self.assertEqual(offsets,[0,100,0,200,0,100,0])

class TimingTests(unittest.TestCase):
    def test_timings_no_urls_or_inferred_detection(self):
        from lotus_delivery_latency import summarize
        result=summarize(['LOTUS DELIVERY TIMING | QueueAgeSeconds=2 | DiscordSendSeconds=0.4 | ProductURL=https://private.example',
                          'LOTUS DELIVERY TIMING | QueueAgeSeconds=10 | DiscordSendSeconds=nan'])
        self.assertEqual(result['timings_seconds']['QueueAgeSeconds']['p95'],10)
        self.assertEqual(result['timings_seconds']['DiscordSendSeconds']['samples'],1)
        self.assertNotIn('private',str(result))

class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_deferred_scan_does_not_request_or_write_failure(self):
        import os
        os.environ.setdefault('DATABASE_URL','postgresql+asyncpg://test:test@127.0.0.1:1/test')
        from app.major_retailers import pipeline as p
        runtime=dict(last_error='PREMIUM_BANDAI_HTTP_403',last_scan_at=datetime.now(timezone.utc),consecutive_failures=1)
        with patch.object(p,'ensure_major_pipeline_schema',AsyncMock()),patch.object(p,'_runtime_row',AsyncMock(return_value=runtime)),patch.object(p,'scan_major_retailer',AsyncMock()) as request,patch.object(p,'_update_runtime_scan',AsyncMock()) as update:
            result=await p.run_major_retailer_pipeline_scan('premium_bandai',force_validation=True)
        self.assertTrue(result['deferred']);request.assert_not_called();update.assert_not_called()

class CooldownTests(unittest.TestCase):
    def test_failure_cooldown(self):
        now=datetime.now(timezone.utc)
        r=dict(last_error='SCAN_ERROR:PREMIUM_BANDAI_HTTP_403',last_scan_at=now,consecutive_failures=1)
        self.assertEqual(remaining(r,now),900)
        r['consecutive_failures']=3;self.assertEqual(remaining(r,now),3600)
        self.assertEqual(remaining(r,now+timedelta(hours=2)),0)
    def test_success_and_unrelated(self):
        self.assertEqual(remaining(dict(last_error='HTTP_403',consecutive_failures=0)),0)
        self.assertEqual(remaining(dict(last_error='INVALID_SCHEMA',consecutive_failures=3)),0)
    def test_naive_persisted_timestamp(self):
        now=datetime(2026,10,21,tzinfo=timezone.utc)
        self.assertEqual(remaining(dict(last_error='HTTP_429',consecutive_failures=1,last_scan_at='2026-10-21T00:00:00'),now),900)

if __name__=='__main__':unittest.main()
