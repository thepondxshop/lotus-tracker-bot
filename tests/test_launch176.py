import os
import sys
import unittest
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch,Mock
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app import riot_drawing_notices as notices
from app import member_xp as xp
import lotus_launch_audit as audit

def at(value):return datetime.fromtimestamp(notices.epoch(value),timezone.utc)
def body():
    return '\n'.join(p['title']+'\nDrawing registration opens: '+('October 27, 9:00 AM PT' if p['opens'].startswith('2026-10') else 'November 13, 9:00 AM PT')+
        '\nDrawing registration closes: '+('October 30, 9:00 AM PT' if p['closes'].startswith('2026-10') else 'November 16, 9:00 AM PT')
        for p in notices.PRODUCTS if p['opens'])

class DrawingPolicyTests(unittest.TestCase):
    def test_boundaries_and_no_late_opening(self):
        p=notices.PRODUCTS[0];start=at(p['opens']);end=at(p['closes'])
        self.assertFalse(notices.due_notices(start-timedelta(seconds=1)))
        self.assertEqual(notices.due_notices(start)[0]['kind'],'OPENING')
        self.assertFalse(notices.due_notices(start+timedelta(minutes=30)))
        self.assertEqual(notices.due_notices(end-timedelta(minutes=60))[0]['kind'],'CLOSING_SOON')
        self.assertEqual(notices.due_notices(end)[0]['kind'],'CLOSED')
        self.assertFalse(notices.due_notices(end+timedelta(minutes=30)))
    def test_dst_and_product_separation(self):
        self.assertEqual(at('2026-10-27T09:00:00').hour,16)
        self.assertEqual(at('2026-11-13T09:00:00').hour,17)
        rows=notices.due_notices(at('2026-11-13T09:00:00'))
        self.assertEqual(len(rows),2)
        self.assertEqual(len({r['key'] for r in rows}),2)
        self.assertFalse(any(r['product']['release'] for r in rows))
    def test_product_scoped_changed_dates(self):
        source=body()
        self.assertTrue(notices.verified_section(source,notices.PRODUCTS[0]))
        self.assertFalse(notices.verified_section(source.replace('October 27','October 28'),notices.PRODUCTS[0]))
        self.assertFalse(notices.verified_section(source,dict(notices.PRODUCTS[0],opens='2026-11-13T09:00:00')))

class DrawingDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine=create_async_engine('sqlite+aiosqlite:///:memory:')
        self.now=at(notices.PRODUCTS[0]['opens'])
    async def asyncTearDown(self):await self.engine.dispose()
    async def invoke(self,mode='LIVE',send=None,source=None):
        with patch.object(notices,'fetch',AsyncMock(return_value='page')),patch.object(notices,'next_page',return_value={'blades':[{'type':'articleRichText','richText':{'body':source or body()}}]}),patch.object(notices,'plain',side_effect=lambda s:s),patch.object(notices,'send',send or AsyncMock(return_value=NS(id=55))),patch.dict(os.environ,{'LOTUS_RIOT_DRAWING_NOTICES':'true'}):
            async with self.engine.connect() as conn:await notices.tick(conn,None,NS(id=1),mode,self.now)
    async def test_receipt_survives_new_connection(self):
        send=AsyncMock(return_value=NS(id=55))
        await self.invoke(send=send);await self.invoke(send=send)
        send.assert_awaited_once()
    async def test_uncertain_send_not_replayed(self):
        send=AsyncMock(side_effect=TimeoutError())
        await self.invoke(send=send);await self.invoke(send=send)
        send.assert_awaited_once()
        async with self.engine.connect() as c:self.assertEqual(await c.scalar(text('SELECT state FROM lotus_riot_drawing_delivery')),'UNRESOLVED')
    async def test_shadow_does_not_consume_live_receipt(self):
        send=AsyncMock(return_value=NS(id=55))
        await self.invoke(mode='SHADOW',send=send)
        send.assert_not_awaited()
        await self.invoke(send=send);send.assert_awaited_once()
    async def test_source_change_blocks(self):
        send=AsyncMock()
        await self.invoke(send=send,source=body().replace('October 27','October 28'))
        send.assert_not_awaited()
    async def test_embed_has_image_and_no_mentions(self):
        channel=NS(send=AsyncMock())
        await notices.send(channel,notices.due_notices(self.now)[0])
        kwargs=channel.send.call_args.kwargs
        self.assertTrue(kwargs['embed'].image.url)
        self.assertIn('has not been verified',kwargs['embed'].description)
        self.assertFalse(kwargs['allowed_mentions'].roles)
        self.assertFalse(kwargs['allowed_mentions'].users)

class XPSetupTests(unittest.IsolatedAsyncioTestCase):
    async def test_overrides_and_guild_isolation(self):
        cog=xp.MemberXP(None,None,False)
        cog.channel_overrides={1:{5:False,6:True}}
        with patch.dict(os.environ,{'LOTUS_XP_CHANNEL_IDS':'5'}):
            self.assertEqual(cog.channels(1),{6})
            self.assertEqual(cog.channels(2),{5})
    async def test_setup_persists_before_cache(self):
        store=NS(set_channel=AsyncMock())
        cog=xp.MemberXP(None,store,False)
        interaction=NS(guild_id=1,response=NS(defer=AsyncMock()),followup=NS(send=AsyncMock()))
        channel=NS(id=6,guild=NS(id=1),mention='#chat')
        await xp.MemberXP.xpsetup.callback(cog,interaction,channel,True)
        store.set_channel.assert_awaited_once_with(1,6,True)
        self.assertTrue(cog.channel_overrides[1][6])
    async def test_privacy_works_when_awarding_disabled(self):
        store=NS(privacy=AsyncMock())
        cog=xp.MemberXP(None,store,False)
        interaction=NS(guild_id=1,user=NS(id=2),response=NS(defer=AsyncMock()),followup=NS(send=AsyncMock()))
        await xp.MemberXP.xpprivacy.callback(cog,interaction,NS(value='out'))
        store.privacy.assert_awaited_once_with(1,2,False)
    async def test_adjust_rejects_invalid_without_database(self):
        store=xp.XPStore(None)
        for n in (0,10001,-10001,True,'20'):
            with self.assertRaises(ValueError):await store.adjust(1,2,3,n)
    async def test_reward_never_grants_paid_role(self):
        role=Mock(id=99)
        with patch.dict(sys.modules,{'app.config':NS(GAME_ROLES={},SUBSCRIPTION_ROLES={'Premium':'99'})}):
            self.assertFalse(xp.cosmetic_role(NS(),role))
    async def test_reward_revalidates_permissions(self):
        role=Mock(id=99,managed=False)
        role.is_default.return_value=False;role.permissions=NS(value=8)
        with patch.dict(sys.modules,{'app.config':NS(GAME_ROLES={},SUBSCRIPTION_ROLES={})}):
            self.assertFalse(xp.cosmetic_role(NS(),role))
    async def test_reward_threshold_and_existing_role(self):
        cog=xp.MemberXP(None,None,True)
        cog.reward_roles={1:{1:9,2:10,3:11}}
        member=NS(roles=[NS(id=9)],guild=NS(id=1,get_role=lambda rid:NS(id=rid)),add_roles=AsyncMock())
        with patch.object(xp,'cosmetic_role',return_value=True):
            await cog.sync_rewards(member,300)
        member.add_roles.assert_awaited_once()
        self.assertEqual(member.add_roles.call_args.args[0].id,10)

class XPPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine=create_async_engine('sqlite+aiosqlite:///:memory:')
        async with self.engine.begin() as c:
            await c.execute(text('CREATE TABLE lotus_xp_channels(guild_id BIGINT,channel_id BIGINT,enabled BOOLEAN,PRIMARY KEY(guild_id,channel_id))'))
            await c.execute(text('CREATE TABLE lotus_xp_rewards(guild_id BIGINT,level INTEGER,role_id BIGINT,PRIMARY KEY(guild_id,level))'))
        self.store=xp.XPStore(self.engine)
    async def asyncTearDown(self):await self.engine.dispose()
    async def test_channels_persist_disabled_override_and_isolate_guild(self):
        await self.store.set_channel(1,7,True)
        await self.store.set_channel(1,7,False)
        await self.store.set_channel(2,8,True)
        self.assertEqual(await xp.XPStore(self.engine).configured_channels(),{1:{7:False},2:{8:True}})
    async def test_rewards_upsert_and_remove(self):
        await self.store.set_reward(1,3,9)
        await self.store.set_reward(1,3,10)
        self.assertEqual(await xp.XPStore(self.engine).rewards(),{1:{3:10}})
        await self.store.set_reward(1,3,None)
        self.assertEqual(await self.store.rewards(),{})

class AuditTests(unittest.TestCase):
    def test_no_evidence_does_not_claim_ready(self):
        result=audit.summarize([])
        self.assertFalse(result['evidence_present']['launch'])
        self.assertFalse(result['live_delivery_verified'])
    def test_blocks_and_health_are_separate(self):
        result=audit.summarize([
            ('LOTUS LAUNCH CHECK',{'version':'1.7.6','ebay':{'mode':'SHADOW','targets':[{'fixed_launch_blockers':['AGGREGATE_SNAPSHOT_EXPIRED']}]}}),
            ('LOTUS READINESS DATABASE',{'table':'stores','rows':[{'active':True,'platform':'shopify','health_status':'DEGRADED'}]}),
            ('LOTUS READINESS DATABASE',{'table':'major_retailer_runtime','rows':[{'retailer_key':'gamestop','mode':'VALIDATION','last_error':'HTTP_403 secret-url'}]})])
        self.assertEqual(result['shopify']['health_counts'],{'DEGRADED':1})
        self.assertEqual(result['ebay']['blockers'],{'AGGREGATE_SNAPSHOT_EXPIRED':1})
        self.assertEqual(result['major_retailers'][0]['blocker'],'ACCESS_DENIED_403')
        self.assertNotIn('secret-url',str(result))
