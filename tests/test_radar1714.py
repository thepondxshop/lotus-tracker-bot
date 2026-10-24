import ast
import re
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from app.release_catalog.tcg_scope import non_tcg_reason

BAD=('One Piece: Escape from Egghead Island Dice Game',
     'One Piece: Dawn of Liberation Board Game')
ROOT=Path(__file__).resolve().parents[1]

class ScopeTests(unittest.TestCase):
    def test_reported_and_variant_titles(self):
        for title in BAD+('ONE PIECE BOARD-GAME','Pokemon Dice–Game', 'Gundam Board Games'):
            self.assertEqual(non_tcg_reason(title),'NON_TCG_BOARD_OR_DICE_GAME')
    def test_real_tcg_and_accessories(self):
        for title in ('One Piece OP-14 Booster Box','One Piece Starter Deck ST-14',
                      'Pokemon TCG Dice Set', 'Gundam Card Game Dice Counters',
                      'One Piece Card Game Sleeves', 'Pokemon TCG Pikachu VMAX Premium Figure Collection'):
            self.assertIsNone(non_tcg_reason(title),title)
    def test_actual_ingestion_rejects_before_game_or_description(self):
        tree=ast.parse((ROOT/'app/release_catalog/extraction.py').read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='candidate')
        ns={'non_tcg_reason':non_tcg_reason,'visible':str,'norm':str.lower}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'extraction','exec'),ns)
        for title in BAD:
            self.assertIsNone(ns['candidate']({'name':title,'description':'One Piece trading card game booster'},'https://example.com',{},'DISTRIBUTOR'))

class QueuedTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_delivery_skips_existing_queue_before_network(self):
        tree=ast.parse((ROOT/'app/release_catalog/publisher.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and any(getattr(x,'name',None)=='deliver' for x in n.body))
        fn=next(n for n in cls.body if getattr(n,'name',None)=='deliver')
        ns={'non_tcg_reason':non_tcg_reason}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'publisher','exec'),ns)
        for title in BAD:
            store=NS(refresh=AsyncMock(return_value={'state':'READY','payload':{'facts':{'title':title}}}),delivery=AsyncMock())
            obj=NS(store=store,channel=AsyncMock())
            await ns['deliver'](obj,1,485)
            store.delivery.assert_awaited_once_with(1,485,state='SKIPPED',error='NON_TCG_BOARD_OR_DICE_GAME')
            obj.channel.assert_not_awaited()

if __name__=='__main__':unittest.main()
