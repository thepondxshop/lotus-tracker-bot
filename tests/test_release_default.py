import ast
import asyncio
import json
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone
from sqlalchemy import BigInteger, Boolean, Integer, String, Text, DateTime, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

ROOT=Path(__file__).resolve().parents[1]
def load_nodes(file, names, ns):
    tree=ast.parse((ROOT/'app/release_catalog'/file).read_text())
    nodes=[n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),file,'exec'),ns)
    return ns

class PreferenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        ns=dict(globals(),utcnow=lambda:datetime.now(timezone.utc),CatalogError=ValueError)
        load_nodes('calendar_store.py',{'Base','Settings','Preference','ReleaseDefaultApplied','CalendarStore'},ns)
        self.ns=ns
        self.engine=create_async_engine('sqlite+aiosqlite:///:memory:')
        async with self.engine.begin() as c:await c.run_sync(ns['Base'].metadata.create_all)
        self.sessions=async_sessionmaker(self.engine,expire_on_commit=False)
        self.store=ns['CalendarStore'](NS(engine=self.engine,sessions=self.sessions),NS(ensure=AsyncMock()))
        self.store.ready=True
    async def asyncTearDown(self):await self.engine.dispose()
    async def test_default_on_and_filter_only_preserves_default(self):
        self.assertEqual((await self.store.preference(1,7))['announcements'],['__ALL__'])
        await self.store.save_preference(1,7,games=['Pokemon'])
        self.assertEqual((await self.store.preference(1,7))['announcements'],['__ALL__'])
    async def test_saved_off_and_selected_games_survive(self):
        await self.store.save_preference(1,7,announcements=[])
        await self.store.save_preference(1,7,games=['Pokemon'])
        self.assertEqual((await self.store.preference(1,7))['announcements'],[])
        await self.store.save_preference(1,8,announcements=['Riftbound'])
        self.assertEqual(await self.store.announcement_preferences(1),{7:[],8:['Riftbound']})
    async def test_activation_once_preserves_later_admin_disable(self):
        await self.store.enable_release_default_once(1,1554313587802251284)
        async with self.sessions() as s,s.begin():
            row=await s.get(self.ns['Settings'],1)
            self.assertTrue(row.announcements_enabled)
            self.assertEqual(row.announcement_channel_id,1554313587802251284)
            row.announcements_enabled=False
        await self.store.enable_release_default_once(1,1554313587802251284)
        async with self.sessions() as s:self.assertFalse((await s.get(self.ns['Settings'],1)).announcements_enabled)

class AudienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_optout_roles_access_and_bots(self):
        ns=dict(globals(),can_access=lambda m,c:m.eligible,CatalogError=ValueError)
        load_nodes('calendar_runtime.py',{'CalendarRuntime'},ns)
        members=[NS(id=i,bot=i==5,eligible=i!=6,roles=[NS(id=123)] if i!=7 else []) for i in range(1,8)]
        guild=NS(chunked=True,members=members)
        channel=NS(guild=guild,permissions_for=lambda m:NS(view_channel=True))
        obj=NS(store=NS(announcement_preferences=AsyncMock(return_value={2:[],3:['Other'],4:['Pokemon']})))
        import sys
        with patch.dict(sys.modules,{'app.config':NS(GAME_ROLES={'Pokemon':123}),'app.helpers':NS(safe_int=int)}):
            result=await ns['CalendarRuntime'].audience(obj,{'guild_id':1},{'game':'Pokemon'},channel)
        self.assertEqual(result,[1,4])
