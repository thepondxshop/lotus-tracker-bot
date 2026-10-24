import ast
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace
from app import version
from app.release_announcements import deliver_once

class PolicyTests(unittest.TestCase):
    def test_new_games_force_major(self):
        with patch.object(version,'RELEASE_KIND','patch'),patch.object(version,'NEW_GAMES',('New Game',)):
            self.assertEqual(version.release_kind(),'major')
            self.assertTrue(version.announcement().startswith('@everyone\n'))
    def test_regular_and_patch_without_games_do_not_ping(self):
        for kind in ('patch','regular'):
            with patch.object(version,'RELEASE_KIND',kind),patch.object(version,'NEW_GAMES',()):
                self.assertEqual(version.release_kind(),kind)
                self.assertNotIn('@everyone',version.announcement())
    def test_manual_major_and_invalid(self):
        with patch.object(version,'RELEASE_KIND','major'),patch.object(version,'NEW_GAMES',()):
            self.assertTrue(version.announcement().startswith('@everyone\n'))
        with patch.object(version,'RELEASE_KIND','invalid'):
            with self.assertRaises(ValueError):version.announcement()
    def test_sender_uses_same_policy_and_preview_suppresses_mentions(self):
        source=(Path(__file__).resolve().parents[1]/'app/release_announcements.py').read_text()
        ast.parse(source)
        self.assertIn('kind = release_kind()',source)
        self.assertIn("kind == 'major' and not perms.mention_everyone",source)
        self.assertIn("everyone=kind=='major'",source)
        self.assertIn('allowed_mentions=discord.AllowedMentions.none()',source)
        self.assertNotIn('RELEASE_KIND',source)

class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_reservation_blocks_duplicate(self):
        send=AsyncMock();mark=AsyncMock()
        await deliver_once(AsyncMock(return_value=False),send,mark)
        send.assert_not_awaited();mark.assert_not_awaited()
    async def test_success_and_uncertain_delivery(self):
        mark=AsyncMock()
        await deliver_once(AsyncMock(return_value=True),AsyncMock(return_value=SimpleNamespace(id=123)),mark)
        mark.assert_awaited_once_with(123)
        mark.reset_mock()
        result=await deliver_once(AsyncMock(return_value=True),AsyncMock(side_effect=TimeoutError),mark)
        self.assertIn('uncertain',result);mark.assert_not_awaited()

if __name__=='__main__':unittest.main()
