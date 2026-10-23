import ast
import asyncio
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import unittest
from unittest.mock import AsyncMock, Mock, patch
import discord


class ReleaseDayTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_role_send_and_duplicate_claim(self):
        path=Path(__file__).resolve().parents[1]/'app/release_catalog/calendar_runtime.py'
        tree=ast.parse(path.read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='CalendarRuntime')
        fn=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='announce')
        ns=dict(os=os,asyncio=asyncio,ZoneInfo=ZoneInfo,discord=discord,LOG=logging.getLogger('test'),
            CatalogError=ValueError,due=lambda *a:True,announcement_embed=lambda *a:discord.Embed(title='Release'),product_image_file=lambda *a:None)
        exec(compile(ast.Module(body=[fn],type_ignores=[]),str(path),'exec'),ns)
        role=Mock(id=123,mention='<@&123>',mentionable=True)
        role.is_default.return_value=False
        channel=Mock(id=1554313587802251284)
        channel.guild.get_role.return_value=role
        channel.send=AsyncMock(return_value=SimpleNamespace(id=99))
        runtime=SimpleNamespace(channel=AsyncMock(return_value=channel),audience=AsyncMock(return_value=[42]),
            store=SimpleNamespace(claim=AsyncMock(side_effect=['receipt',None]),delivered=AsyncMock()))
        cfg=dict(guild_id=1,announcement_channel_id=channel.id,timezone='America/New_York')
        entry=dict(game='Riftbound',id=2)
        with patch.dict(os.environ,{'LOTUS_RELEASE_DAY_GAME_ROLE_PINGS':'true'}):
            await ns['announce'](runtime,cfg,entry,datetime.now(timezone.utc))
            await ns['announce'](runtime,cfg,entry,datetime.now(timezone.utc))
        channel.send.assert_awaited_once()
        self.assertEqual(channel.send.call_args.kwargs['content'],'<@42>')
        self.assertFalse(channel.send.call_args.kwargs['allowed_mentions'].roles)
        self.assertFalse(channel.send.call_args.kwargs['allowed_mentions'].everyone)
        runtime.store.delivered.assert_awaited_once_with('receipt','SENT',99)
