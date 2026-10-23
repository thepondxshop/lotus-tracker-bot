import ast
import os
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,Mock,patch
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app import member_xp as xp,case_identity as cases,registered_games as games
from app.community_support import phase,can_close,CommunitySupport,CloseView,TicketView
from app.game_lifecycle import candidate_text,safe_source,disabled,_disabled

def message(channel=99,content='This is a useful chat message',**kwargs):
    c=NS(id=channel,name='general',parent_id=None,category_id=None)
    m=NS(guild=NS(id=1,get_channel=Mock()),channel=c,author=NS(id=2,bot=False,mention='<@2>',roles=[]),
         webhook_id=None,content=content,id=123)
    for k,v in kwargs.items():setattr(m,k,v)
    return m

class XPPolicyTests(unittest.TestCase):
    def test_level_costs_and_boundaries(self):
        for lv in range(1,100):
            floor=xp.level_floor(lv)
            self.assertEqual(xp.level(floor),lv)
            self.assertEqual(xp.level(floor+lv*100-1),lv)
            self.assertEqual(xp.level(floor+lv*100),lv+1)
        self.assertEqual(xp.level_floor(6)-xp.level_floor(5),500)
    def test_random_range_cooldown_and_no_old_daily_cap(self):
        now=datetime.now(timezone.utc)
        row=dict(enabled=True,last_message_id=1,last_awarded_at=now-timedelta(seconds=60),last_content_hash='old',day=now.date(),daily_xp=999)
        with patch.object(xp.secrets,'randbelow',return_value=0):self.assertEqual(xp.award_amount(row,'new',2,now),10)
        with patch.object(xp.secrets,'randbelow',return_value=10):self.assertEqual(xp.award_amount(row,'new',2,now),20)
        self.assertEqual(xp.award_amount(row,'new',2,now-timedelta(seconds=1)),0)
        self.assertEqual(xp.award_amount(row,'old',2,now),0)
        self.assertEqual(xp.award_amount(row,'new',1,now),0)
        self.assertEqual(xp.award_amount(dict(row,enabled=False),'new',2,now),0)
    def test_all_chat_except_excluded_and_threads(self):
        self.assertTrue(xp.chat_allowed(message()))
        for cid in xp.EXCLUDED_CHANNELS:
            self.assertFalse(xp.chat_allowed(message(cid),{cid:True}))
            m=message();m.channel.parent_id=cid;self.assertFalse(xp.chat_allowed(m))
        m=message();m.channel.name='ticket-000001';self.assertFalse(xp.chat_allowed(m))
        m=message();m.channel.parent=NS(name='ticket-000001');self.assertFalse(xp.chat_allowed(m))
        self.assertFalse(xp.chat_allowed(message(),{99:False}))
    def test_commands_bots_and_webhooks(self):
        for content in ['/level','!help whatever','https://example.com']:
            self.assertFalse(xp.eligible_message(message(content=content),{99}))
        self.assertFalse(xp.eligible_message(message(webhook_id=3),{99}))
        self.assertFalse(xp.eligible_message(message(author=NS(bot=True)),{99}))

class XPCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_wrong_channel_redirect(self):
        i=NS(channel_id=99,response=NS(send_message=AsyncMock()))
        cog=xp.MemberXP(Mock(),Mock(),True)
        self.assertFalse(await cog.interaction_check(i))
        self.assertTrue(i.response.send_message.call_args.kwargs['ephemeral'])
        i.channel_id=xp.COMMANDS_CHANNEL;self.assertTrue(await cog.interaction_check(i))
    async def test_public_level_and_leaderboard(self):
        i=NS(guild_id=1,user=NS(id=2,mention='<@2>'),response=NS(defer=AsyncMock()),followup=NS(send=AsyncMock()))
        store=NS(rank=AsyncMock(return_value={'xp':145,'rank':1}),leaders=AsyncMock(return_value=[{'user_id':2,'xp':145}]))
        cog=xp.MemberXP(Mock(),store,True)
        await cog.show_level(i)
        self.assertFalse(i.response.defer.call_args.kwargs['ephemeral'])
        self.assertNotIn('ephemeral',i.followup.send.call_args.kwargs)
        for n in (10,15,20):
            await xp.MemberXP.leaderboard.callback(cog,i,n)
            store.leaders.assert_awaited_with(1,n)
            self.assertFalse(i.response.defer.call_args.kwargs['ephemeral'])
    async def test_actual_listener_single_level_notice(self):
        channel=NS(send=AsyncMock())
        m=message();m.guild.get_channel.return_value=channel
        store=NS(award=AsyncMock(return_value=(15,90,105)))
        bot=NS(get_context=AsyncMock(return_value=NS(valid=False)))
        cog=xp.MemberXP(bot,store,True)
        await cog.on_message(m)
        self.assertIn('Level 2',channel.send.call_args.args[0])
        store.award.assert_awaited_once()
        store.award.return_value=0
        await cog.on_message(m);channel.send.assert_awaited_once()
        bot.get_context.return_value.valid=True
        await cog.on_message(m);self.assertEqual(store.award.await_count,2)
    async def test_leaderboard_database_limits_and_guild_isolation(self):
        engine=create_async_engine('sqlite+aiosqlite:///:memory:')
        try:
            async with engine.begin() as c:
                await c.execute(text('CREATE TABLE lotus_member_xp(guild_id INTEGER,user_id INTEGER,xp INTEGER,enabled BOOLEAN)'))
                for n in range(25):await c.execute(text('INSERT INTO lotus_member_xp VALUES(1,:u,:x,1)'),dict(u=n,x=n+1))
                await c.execute(text('INSERT INTO lotus_member_xp VALUES(2,999,99999,1)'))
                await c.execute(text('INSERT INTO lotus_member_xp VALUES(1,888,99999,0)'))
            store=xp.XPStore(engine)
            for n in (10,15,20):
                rows=await store.leaders(1,n);self.assertEqual(len(rows),n);self.assertEqual(rows[0]['user_id'],24)
            with self.assertRaises(ValueError):await store.leaders(1,100)
        finally:await engine.dispose()

class TicketTests(unittest.IsolatedAsyncioTestCase):
    def test_reminder_boundaries(self):
        self.assertIsNone(phase(43199,0));self.assertEqual(phase(43200,0),'12')
        self.assertIsNone(phase(43200,12));self.assertEqual(phase(72000,12),'20')
        self.assertIsNone(phase(72000,20));self.assertEqual(phase(86400,20),'close')
        self.assertIsNone(phase(10,0))
    def test_close_authorization(self):
        m=NS(id=2,guild_permissions=NS(manage_channels=False),roles=[])
        self.assertTrue(can_close(m,2));self.assertFalse(can_close(m,3))
        with patch.dict(os.environ,{'LOTUS_SUPPORT_ROLE_IDS':'45'}):
            m.roles=[NS(id=45)];self.assertTrue(can_close(m,3))
    async def test_persistent_buttons(self):
        self.assertTrue(TicketView(Mock()).is_persistent())
        self.assertTrue(CloseView(Mock()).is_persistent())
    async def test_free_role_only_new_humans(self):
        role=NS(id=3,managed=False,is_default=lambda:False,permissions=NS(administrator=False))
        m=NS(bot=False,guild=NS(get_role=lambda rid:role),roles=[],add_roles=AsyncMock())
        with patch('app.config.SUBSCRIPTION_ROLES',{'Free':'3','Premium':'4'}):
            await CommunitySupport(Mock(),None).on_member_join(m)
            m.add_roles.assert_awaited_once()
            m.bot=True;await CommunitySupport(Mock(),None).on_member_join(m);m.add_roles.assert_awaited_once()
        m.bot=False;m.add_roles.reset_mock()
        with patch('app.config.SUBSCRIPTION_ROLES',{'Free':'3','Premium':'3'}):
            await CommunitySupport(Mock(),None).on_member_join(m);m.add_roles.assert_not_awaited()

    async def test_open_private_channel_and_persist_before_confirmation(self):
        from app.community_support import OPEN_CHANNEL
        class Tx:
            async def __aenter__(self):return conn
            async def __aexit__(self,*args):return False
        result=Mock();result.mappings.return_value.first.return_value=None
        conn=NS(execute=AsyncMock(return_value=result),scalar=AsyncMock(return_value=27))
        engine=NS(begin=lambda:Tx())
        default=Mock(id=1);bot_member=Mock(id=2);owner=Mock(id=3,bot=False,mention='<@3>')
        channel=NS(id=50,mention='<#50>',send=AsyncMock())
        guild=NS(id=12,default_role=default,me=bot_member,create_text_channel=AsyncMock(return_value=channel),get_role=lambda rid:None)
        i=NS(guild=guild,user=owner,channel_id=OPEN_CHANNEL,channel=NS(category=None),response=NS(defer=AsyncMock()),followup=NS(send=AsyncMock()))
        cog=CommunitySupport(Mock(),engine)
        await cog.open_ticket(i)
        self.assertEqual(guild.create_text_channel.call_args.args[0],'ticket-000027')
        overwrites=guild.create_text_channel.call_args.kwargs['overwrites']
        self.assertFalse(overwrites[default].view_channel)
        self.assertTrue(overwrites[owner].view_channel)
        self.assertTrue(any("state='OPEN'" in str(call.args[0]) for call in conn.execute.call_args_list))
        channel.send.assert_awaited_once()
        self.assertIn('<#50>',i.followup.send.call_args.args[0])

    async def test_existing_ticket_never_creates_duplicate(self):
        from app.community_support import OPEN_CHANNEL
        class Tx:
            async def __aenter__(self):return conn
            async def __aexit__(self,*args):return False
        result=Mock();result.mappings.return_value.first.return_value={'channel_id':50}
        conn=NS(execute=AsyncMock(return_value=result))
        guild=NS(id=12,create_text_channel=AsyncMock())
        i=NS(guild=guild,user=NS(id=3,bot=False),channel_id=OPEN_CHANNEL,response=NS(defer=AsyncMock()),followup=NS(send=AsyncMock()))
        await CommunitySupport(Mock(),NS(begin=lambda:Tx())).open_ticket(i)
        guild.create_text_channel.assert_not_awaited()
        self.assertIn('<#50>',i.followup.send.call_args.args[0])

class ProductTests(unittest.TestCase):
    def test_reported_display_and_real_case(self):
        event={'product_name':'Pokémon Mega Evolution: Ascended Heroes Mini Tin Case (10 Tins) (20 Pack) (ENG)','product_type':'Case','reference_evidence':{'bad':1}}
        fixed=cases.normalize_case_event(event)
        self.assertEqual(fixed['product_type'],'Mini Tin Display')
        self.assertNotIn('reference_evidence',fixed)
        self.assertFalse(cases.shipping_case_event(event))
        self.assertFalse(cases.shipping_case_event(fixed))
        self.assertTrue(cases.shipping_case_event({'product_name':'Pokemon Mini Tin Display Case 8 Displays','product_type':'Case'}))
        self.assertTrue(cases.shipping_case_event({'product_name':'Pokemon Booster Box Case','product_type':'Case'}))
    def test_new_game_identity_and_negatives(self):
        for title,expected in [('World of Tanks The Card Game Booster Box','World of Tanks TCG'),('Vibes Pudgy Penguins TCG Booster Box','Vibes TCG'),('Shadowverse Evolve Booster Box','Shadowverse Evolve')]:
            self.assertEqual(games.registered_identity({'title':title}),expected)
        for title in ['World of Tanks Generals Card Game Booster','Vibes Pudgy Penguins Plush','Shadowverse digital code card','World of Tanks Rush board game','Vibes Booster Box']:
            self.assertIsNone(games.registered_identity({'title':title}))

class LifecycleTests(unittest.TestCase):
    def test_article_evidence_not_navigation(self):
        self.assertIsNone(candidate_text('<nav>Vibes ending support</nav><main>Welcome</main>','vibes'))
        self.assertIsNotNone(candidate_text('<main>Vibes TCG will be discontinuing production.</main>','vibes'))
        self.assertIsNone(candidate_text('<main>Vibes is not ending support.</main>','vibes'))
        self.assertIsNone(candidate_text('<main>Another Game is discontinuing production.</main>','vibes'))
    def test_source_and_disable_isolation(self):
        base='https://www.vibes.game/'
        for url in ['http://www.vibes.game/','https://www.vibes.game.evil.test/','https://user@www.vibes.game/','https://www.vibes.game:444/']:
            self.assertFalse(safe_source(url,base))
        self.assertTrue(safe_source(base+'news/',base))
        _disabled.add((1,'Vibes TCG'))
        try:
            self.assertTrue(disabled(1,'Vibes TCG'));self.assertFalse(disabled(2,'Vibes TCG'))
        finally:_disabled.clear()
    def test_main_and_worker_wiring(self):
        root=Path(__file__).resolve().parents[1]
        main=(root/'main.py').read_text();worker=(root/'app/worker.py').read_text()
        ast.parse(main);ast.parse(worker)
        self.assertIn('await install_community_support(self, self.database_ready)',main)
        self.assertIn('await install_game_lifecycle(self, self.database_ready)',main)
        self.assertIn("game_disabled(guild.id,event.get('game'))",worker)

if __name__=='__main__':unittest.main()
