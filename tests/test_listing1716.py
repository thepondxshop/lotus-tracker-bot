import copy
import os
import unittest
from unittest.mock import AsyncMock, patch
from app.marketplaces.ebay_live_policy import assess
from app.marketplaces import ebay_listing_alerts as alerts

TARGET={'id':'test','reviewed':True,'game':'Pokemon','gtin':'820650853210','condition_id':'1000',
        'quantity':1,'required_terms':['151','booster bundle'],'excluded_terms':[],
        'aspects':{'Language':'English','Configuration':'Box'},'currency':'USD','comparison_mode':'ITEM_ONLY',
        'aggregate_snapshot':{'expired':True},'sold_records':[]}
ITEM={'itemId':'v1|123456789000|0','title':'Pokemon 151 Booster Bundle English sealed',
      'gtin':'820650853210','conditionId':'1000',
      'localizedAspects':[{'name':'Language','value':'English'},{'name':'Configuration','value':'Box'}],
      'itemLocation':{'country':'US'},'seller':{'username':'test','feedbackScore':1000,'feedbackPercentage':'99.5'},
      'buyingOptions':['FIXED_PRICE'],'estimatedAvailabilities':[{'estimatedAvailabilityStatus':'IN_STOCK'}],
      'price':{'value':'170.99','currency':'USD'},'itemWebUrl':'https://www.ebay.com/itm/123456789000'}

class PolicyTests(unittest.TestCase):
    def test_listing_without_benchmark_deal_still_blocked(self):
        result=assess(ITEM,TARGET,listing_only=True)
        self.assertTrue(result['eligible']);self.assertEqual(result['alert_kind'],'LISTING')
        self.assertNotIn('discount_percent',result)
        self.assertFalse(assess(ITEM,TARGET)['eligible'])

    def test_product_seller_and_stock_gates(self):
        for field,value in [('gtin','123456789012'),('title','Empty box only 151 booster bundle'),
                            ('seller',{'username':'x','feedbackScore':2,'feedbackPercentage':'99'}),
                            ('estimatedAvailabilities',[]),('conditionId','3000'),
                            ('price',{'value':'0','currency':'USD'}),('itemWebUrl','https://evil.example/item')]:
            with self.subTest(field=field):
                item=copy.deepcopy(ITEM);item[field]=value
                self.assertFalse(assess(item,TARGET,listing_only=True)['eligible'])

    def test_lot_and_auction_blocked(self):
        item=copy.deepcopy(ITEM);item['lotSize']=2
        self.assertFalse(assess(item,TARGET,listing_only=True)['eligible'])
        item=copy.deepcopy(ITEM);item['buyingOptions']=['AUCTION']
        self.assertFalse(assess(item,TARGET,listing_only=True)['eligible'])

class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_shadow_never_sends_and_separate_key(self):
        store=AsyncMock();store.ready.return_value=True
        channel=AsyncMock();send=AsyncMock()
        with patch.dict(os.environ,{'EBAY_LISTING_MODE':'SHADOW','CHANNEL_EBAY_MARKETPLACE':'123'}),patch.object(alerts.ebay_shadow,'record',new_callable=AsyncMock) as record:
            state=await alerts.handle(None,store,ITEM,[TARGET],TARGET,1,'SHADOW',channel,send)
            self.assertEqual(state,'LISTING_SHADOW_ELIGIBLE');send.assert_not_awaited()
            self.assertNotEqual(record.call_args.args[1],alerts.config_hash([TARGET]))

    async def test_live_requires_separate_approval_then_shadow(self):
        store=AsyncMock();store.ready.return_value=True
        send=AsyncMock(return_value='DELIVERED');channel=AsyncMock()
        with patch.dict(os.environ,{'EBAY_LISTING_MODE':'LIVE','CHANNEL_EBAY_MARKETPLACE':'123','EBAY_LISTING_APPROVED_SHA256':''}),patch.object(alerts.ebay_shadow,'ready',new_callable=AsyncMock,return_value=False) as ready:
            call=lambda:alerts.handle(None,store,ITEM,[TARGET],TARGET,1,'SHADOW',channel,send)
            self.assertEqual(await call(),'LISTING_APPROVAL_REQUIRED')
            os.environ['EBAY_LISTING_APPROVED_SHA256']=alerts.fingerprint([TARGET])
            self.assertEqual(await call(),'LISTING_SHADOW_REQUIRED');send.assert_not_awaited()
            ready.return_value=True
            self.assertEqual(await call(),'DELIVERED');send.assert_awaited_once()

    async def test_off_and_channel_change(self):
        with patch.dict(os.environ,{'EBAY_LISTING_MODE':'OFF','CHANNEL_EBAY_MARKETPLACE':'123'}):
            self.assertEqual(await alerts.handle(None,None,ITEM,[TARGET],TARGET,1,'SHADOW',None,None),'OFF')
            old=alerts.fingerprint([TARGET]);os.environ['CHANNEL_EBAY_MARKETPLACE']='456'
            self.assertNotEqual(old,alerts.fingerprint([TARGET]))

if __name__=='__main__':unittest.main()

class PublishTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_publisher_label_and_durable_dedupe(self):
        import ast, asyncio, uuid
        from pathlib import Path
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        from contextlib import asynccontextmanager
        from types import SimpleNamespace
        source=Path('app/marketplaces/ebay_live.py').read_text()
        tree=ast.parse(source)
        node=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='publish')
        channel=SimpleNamespace(send=AsyncMock(return_value=SimpleNamespace(id=5)))
        connection=AsyncMock()
        connection.fetchrow.return_value={'delete_requested':False}
        connection.fetchval.return_value=1
        store=AsyncMock();store.prepare.return_value=True;store.ready.return_value=True
        @asynccontextmanager
        async def locked():yield connection
        store.locked=locked
        namespace=dict(asyncio=asyncio,uuid=uuid,os=os,datetime=datetime,timezone=timezone,
                       ZoneInfo=ZoneInfo,allowed_channel=AsyncMock(return_value=channel))
        exec(compile(ast.Module(body=[node],type_ignores=[]),'publisher','exec'),namespace)
        result=assess(ITEM,TARGET,listing_only=True)
        with patch.dict(os.environ,{'CHANNEL_EBAY_MARKETPLACE':'123'}):
            self.assertEqual(await namespace['publish'](None,store,ITEM,result,1),'DELIVERED')
            embed=channel.send.call_args.kwargs['embed']
            self.assertTrue(embed.title.startswith('eBay listing found'))
            self.assertIn('not a verified deal',embed.description)
            self.assertNotIn('Reviewed sold',embed.description)
            store.prepare.return_value=False
            self.assertEqual(await namespace['publish'](None,store,ITEM,result,1),'DEDUPLICATED_OR_SUPPRESSED')
            channel.send.assert_awaited_once()
