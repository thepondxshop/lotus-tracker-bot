import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from app import version
from app.release_announcements import deliver_once
from lotus_pokemon_oct15_import import URLS

class ReleaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_once(self):
        reserve=AsyncMock(side_effect=[True,False]); send=AsyncMock(return_value=SimpleNamespace(id=123)); mark=AsyncMock()
        await deliver_once(reserve,send,mark); await deliver_once(reserve,send,mark)
        self.assertEqual(send.await_count,1);mark.assert_awaited_once_with(123)
    async def test_uncertain_not_marked_sent(self):
        mark=AsyncMock()
        result=await deliver_once(AsyncMock(return_value=True),AsyncMock(side_effect=TimeoutError),mark)
        self.assertIn('uncertain',result);mark.assert_not_awaited()
    async def test_save_failure_not_retried(self):
        send=AsyncMock(return_value=SimpleNamespace(id=1))
        result=await deliver_once(AsyncMock(return_value=True),send,AsyncMock(side_effect=RuntimeError))
        self.assertIn('uncertain',result); self.assertEqual(send.await_count,1)
    def test_major_only_mentions(self):
        for kind in ('patch','regular','major'):
            with patch.object(version,'RELEASE_KIND',kind):
                self.assertEqual('@everyone' in version.announcement(),kind=='major')
    def test_urls_exact(self):
        self.assertEqual(len(set(URLS)),10)
        self.assertTrue(URLS[0].endswith('-166'));self.assertTrue(URLS[-1].endswith('-175'))
    def test_main_preserves_ebay_and_registers(self):
        s=(Path(__file__).resolve().parents[1]/'main.py').read_text();ast.parse(s)
        self.assertIn('start_ebay_live(self)',s)
        self.assertIn('register_release_announcements(bot)',s)
        self.assertNotIn('"**Version:** `1.0.6`"',s)
