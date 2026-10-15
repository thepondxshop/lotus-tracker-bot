import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, AsyncMock
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from app.marketplaces.ebay_live_policy import assess, load_targets
from app.marketplaces.ebay_notifications import Settings, install
from app.marketplaces.ebay_live_store import Store

NOW = datetime(2026,10,15,tzinfo=timezone.utc)
def target():
    return {'id':'synthetic-box','reviewed':True,'game':'Pokemon','gtin':'123456789012',
        'condition_id':'1000','required_terms':['example booster box'], 'quantity':1,
        'aspects':{'Language':'English','Configuration':'Box'},'currency':'USD',
        'destination_zip':'10001','tax_rate':'0','costs_reviewed':True,
        'comparison':{'verified':True,'exact_match':True,'basis':'SOLD','source':'synthetic test evidence',
            'sample_count':5,'amount':'100','currency':'USD','as_of':NOW.isoformat(),
            'cost_basis':'ITEM_PLUS_SHIPPING_AND_DESTINATION_TAX','destination_zip':'10001'}}
def item():
    return {'itemId':'v1|123|0','title':'Example Booster Box','gtin':'123456789012','conditionId':'1000',
        'localizedAspects':[{'name':'Language','value':'English'},{'name':'Configuration','value':'Box'}],
        'itemLocation':{'country':'US'},'seller':{'username':'synthetic','feedbackScore':100,'feedbackPercentage':'99'},
        'buyingOptions':['FIXED_PRICE'],'price':{'value':'85','currency':'USD'},
        'shippingOptions':[{'shippingCostType':'FIXED','shippingCost':{'value':'5','currency':'USD'}}],
        'estimatedAvailabilities':[{'estimatedAvailabilityStatus':'IN_STOCK'}],
        'itemWebUrl':'https://www.ebay.com/itm/123'}

class PolicyTest(unittest.TestCase):
    def test_exact_ten_percent_with_shipping(self):
        r=assess(item(),target(),NOW)
        self.assertTrue(r['eligible']);self.assertEqual(r['destination_variable'],'CHANNEL_EBAY_INTELLIGENCE')
    def test_shipping_makes_not_deal(self):
        i=item();i['price']['value']='85.01';self.assertFalse(assess(i,target(),NOW)['eligible'])
    def test_language_pack_and_gtin(self):
        for field,value in [('gtin','888888888888'),('conditionId','3000'),('title','Example single pack')]:
            i=item();i[field]=value;self.assertFalse(assess(i,target(),NOW)['eligible'])
        i=item();i['localizedAspects'][0]['value']='Japanese';self.assertFalse(assess(i,target(),NOW)['eligible'])
    def test_no_asking_or_hidden_offer_comparison(self):
        for change in ({'basis':'ASKING'},{'sample_count':4},{'verified':False},{'as_of':(NOW-timedelta(days=15)).isoformat()}):
            t=target();t['comparison'].update(change);self.assertFalse(assess(item(),t,NOW)['eligible'])
    def test_auction_window_next_bid_and_reserve(self):
        i=item();i.update(buyingOptions=['AUCTION'],minimumPriceToBid={'value':'85','currency':'USD'},reservePriceMet=True,itemEndDate=(NOW+timedelta(seconds=600)).isoformat())
        self.assertEqual(assess(i,target(),NOW)['destination_variable'],'CHANNEL_EBAY_AUCTIONS')
        for remaining in (601,0,-1):
            i['itemEndDate']=(NOW+timedelta(seconds=remaining)).isoformat();self.assertFalse(assess(i,target(),NOW)['eligible'])
        i['itemEndDate']=(NOW+timedelta(seconds=599)).isoformat();i.pop('minimumPriceToBid');self.assertFalse(assess(i,target(),NOW)['eligible'])
        i['minimumPriceToBid']={'value':'85','currency':'USD'};i['reservePriceMet']=False;self.assertFalse(assess(i,target(),NOW)['eligible'])
    def test_unknown_shipping_and_stock_and_foreign(self):
        for change in ({'shippingOptions':[]},{'estimatedAvailabilities':[]},{'itemLocation':{'country':'JP'}},{'itemGroupId':'variants'},{'lotSize':2}):
            i=item();i.update(change);self.assertFalse(assess(i,target(),NOW)['eligible'])
    def test_tax_comparison_destination(self):
        t=target();t['tax_rate']='0.1';self.assertFalse(assess(item(),t,NOW)['eligible'])
        t=target();t['comparison']['destination_zip']='90210';self.assertFalse(assess(item(),t,NOW)['eligible'])
    def test_target_file_checks(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'targets.json';p.write_text(json.dumps([target()]));self.assertEqual(len(load_targets(p)),1)
            p.write_text(json.dumps([target(),target()]));self.assertRaises(ValueError,load_targets,p)
    def test_seller_trust(self):
        i=item();i['seller']['feedbackScore']=2;self.assertFalse(assess(i,target(),NOW)['eligible'])
    def test_seller_digest_consistent_without_raw_data(self):
        with patch.dict(os.environ,{'EBAY_RETENTION_HMAC_KEY':'x'*64}):
            s=Store();self.assertEqual(s.owners({'username':'seller'}),s.owners({'userId':'seller'}))
            self.assertNotIn('seller',s.owners({'username':'seller'}))

class ReceiverTest(unittest.IsolatedAsyncioTestCase):
    async def test_durable_queue_before_ack_and_failure_retries(self):
        class Keys:
            async def start(self):pass
            async def close(self):pass
            async def get(self,k):return {}
        class Retention:
            pool=True
            def __init__(self):self.receive_deletion=AsyncMock()
            async def start(self):pass
            async def close(self):pass
            async def heartbeat(self,mode):pass
        retention=Retention()
        document={'metadata':{'topic':'MARKETPLACE_ACCOUNT_DELETION','schemaVersion':'1.0'},'notification':{'notificationId':'synthetic','data':{'username':'synthetic'}}}
        with patch('app.marketplaces.ebay_live_store.Store',return_value=retention),patch('app.marketplaces.ebay_notifications.signature_header',return_value=({'kid':'test'},b'test')),patch('app.marketplaces.ebay_notifications.verify_payload'):
            app=web.Application();install(app,Settings('https://example.com/ebay/account-deletion','x'*64,'LIVE_REVIEWED'),Keys())
            async with TestClient(TestServer(app)) as client:
                r=await client.post('/ebay/account-deletion',json=document);self.assertEqual(r.status,202)
                retention.receive_deletion.assert_awaited_once_with({'username':'synthetic'})
                retention.receive_deletion.side_effect=RuntimeError('database down')
                r=await client.post('/ebay/account-deletion',json=document);self.assertEqual(r.status,503)
    async def test_invalid_signature_never_queues(self):
        class Keys:
            async def start(self):pass
            async def close(self):pass
        app=web.Application();install(app,Settings('https://example.com/ebay/account-deletion','x'*64),Keys())
        async with TestClient(TestServer(app)) as client:
            r=await client.post('/ebay/account-deletion',json={});self.assertEqual(r.status,412)


class DeliveryTest(unittest.IsolatedAsyncioTestCase):
    async def test_stale_result_never_sends(self):
        import sys
        from contextlib import asynccontextmanager
        from types import SimpleNamespace
        from app.marketplaces.ebay_live import publish
        class Connection:
            async def fetchrow(self,*args):return {'delete_requested':False}
            async def fetchval(self,*args):return 1
            async def execute(self,*args):pass
        class State:
            prepare=AsyncMock(return_value=True)
            ready=AsyncMock(return_value=True)
            @asynccontextmanager
            async def locked(self):yield Connection()
        channel=SimpleNamespace(send=AsyncMock())
        r=assess(item(),target(),NOW)
        with patch.dict(sys.modules,{'discord':SimpleNamespace()}),patch('app.marketplaces.ebay_live.allowed_channel',AsyncMock(return_value=channel)),patch.dict(os.environ,{'CHANNEL_EBAY_INTELLIGENCE':'123'}):
            outcome=await publish(None,State(),item(),r,0)
            self.assertEqual(outcome,'CANCELLED_BEFORE_SEND');channel.send.assert_not_awaited()
    async def test_send_failure_leaves_prepared_for_reconciliation(self):
        import sys
        from contextlib import asynccontextmanager
        from types import SimpleNamespace
        from app.marketplaces.ebay_live import publish
        from unittest.mock import MagicMock
        c=SimpleNamespace(fetchrow=AsyncMock(return_value={'delete_requested':False}),fetchval=AsyncMock(return_value=0),execute=AsyncMock())
        class State:
            prepare=AsyncMock(return_value=True)
            ready=AsyncMock(return_value=True)
            @asynccontextmanager
            async def locked(self):yield c
        channel=SimpleNamespace(send=AsyncMock(side_effect=TimeoutError()))
        now=datetime.now(timezone.utc);t=target();t['comparison']['as_of']=now.isoformat();r=assess(item(),t,now)
        fake=SimpleNamespace(Embed=MagicMock(),AllowedMentions=SimpleNamespace(none=lambda:None))
        with patch.dict(sys.modules,{'discord':fake}),patch('app.marketplaces.ebay_live.allowed_channel',AsyncMock(return_value=channel)),patch.dict(os.environ,{'CHANNEL_EBAY_INTELLIGENCE':'123'}):
            with self.assertRaises(TimeoutError):await publish(None,State(),item(),r,0)
            State.prepare.assert_awaited();c.execute.assert_not_awaited()
    async def test_uncertain_send_is_found_then_deleted(self):
        from app.marketplaces.ebay_live import cleanup
        from contextlib import asynccontextmanager
        from types import SimpleNamespace
        import sys,uuid
        token=uuid.uuid4();record={'id':token,'channel_id':123,'message_id':None,'state':'PREPARED','delete_requested':True,'created_at':datetime.now(timezone.utc)-timedelta(minutes=3)}
        msg=SimpleNamespace(id=456,author=SimpleNamespace(id=789),embeds=[SimpleNamespace(footer=SimpleNamespace(text='Lotus eBay '+str(token)))])
        async def history(**kwargs):yield msg
        delete=AsyncMock();channel=SimpleNamespace(history=history,get_partial_message=lambda mid:SimpleNamespace(delete=delete))
        c=SimpleNamespace(execute=AsyncMock())
        class State:
            pool=SimpleNamespace(fetch=AsyncMock(return_value=[record]))
            @asynccontextmanager
            async def locked(self):yield c
        bot=SimpleNamespace(user=SimpleNamespace(id=789),fetch_channel=AsyncMock(return_value=channel))
        class NotFound(Exception):pass
        with patch.dict(sys.modules,{'discord':SimpleNamespace(NotFound=NotFound)}):
            await cleanup(bot,State())
        delete.assert_awaited_once();c.execute.assert_awaited_once()

if __name__=='__main__':unittest.main()
