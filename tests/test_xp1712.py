import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
from app import member_xp as xp

class ProgressTests(unittest.IsolatedAsyncioTestCase):
    def test_all_boundaries_through_300(self):
        floor=0
        for lv in range(301):
            if lv:
                floor += lv*100 + (lv*50 if lv%10==0 else 0)
            cost=(lv+1)*100 + ((lv+1)*50 if (lv+1)%10==0 else 0)
            self.assertEqual(xp.level_floor(lv),floor)
            self.assertEqual(xp.level(floor),lv)
            self.assertEqual(xp.level(floor+cost-1),lv)
            self.assertEqual(xp.level(floor+cost),lv+1)
        self.assertEqual(xp.level(0),0)
        self.assertEqual(xp.level_floor(10),6000)
        self.assertEqual(xp.level_floor(20),22500)
        self.assertEqual(xp.level_floor(250),3300000)
        self.assertEqual(xp.level_floor(300),4747500)
    def test_milestone_cost_does_not_carry_forward(self):
        self.assertEqual([xp.level_cost(n) for n in (9,10,11,19,20,21)],
                         [900,1500,1100,1900,3000,2100])
    async def test_zero_level_progress_and_existing_total(self):
        store=NS(rank=AsyncMock(return_value={'xp':0,'rank':1}))
        cog=xp.MemberXP(Mock(),store,True)
        i=NS(guild_id=1,user=NS(id=2,mention='<@2>'),response=NS(defer=AsyncMock()),followup=NS(send=AsyncMock()))
        await cog.show_level(i)
        self.assertIn('0/100 XP',i.followup.send.call_args.args[0])
        store.rank.return_value={'xp':145,'rank':1}
        await cog.show_level(i)
        self.assertIn('45/200 XP',i.followup.send.call_args.args[0])
    async def test_milestone_progress_display(self):
        store=NS(rank=AsyncMock(return_value={'xp':5500,'rank':1}))
        cog=xp.MemberXP(Mock(),store,True)
        i=NS(guild_id=1,user=NS(id=2,mention='<@2>'),response=NS(defer=AsyncMock()),followup=NS(send=AsyncMock()))
        await cog.show_level(i)
        self.assertIn('1000/1500 XP toward level 10',i.followup.send.call_args.args[0])
        store.rank.return_value={'xp':6000,'rank':1}
        await cog.show_level(i)
        self.assertIn('0/1100 XP toward level 11',i.followup.send.call_args.args[0])
    def test_reward_range_supports_300(self):
        parameter=next(p for p in xp.MemberXP.xpreward.parameters if p.name=='at_level')
        self.assertEqual(parameter.max_value,300)

if __name__=='__main__':unittest.main()
