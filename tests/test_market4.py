import copy
import csv
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
from types import SimpleNamespace
from contextlib import asynccontextmanager
from app.marketplaces.ebay_evidence import evidence_record, comparison, config_hash
from app.marketplaces.ebay_live_policy import assess, load_targets
from lotus_ebay_setup import PRESET, save, main, COLUMNS

NOW=datetime(2026,10,16,tzinfo=timezone.utc)
def sale(i=0):
    return {'listing_id':str(900000000000+i),'sold_at':NOW.isoformat(),'item_price':'100',
            'currency':'USD','gtin':'820650853210','condition_id':'1000','language':'English',
            'configuration':'Box','quantity':'1','price_kind':'SOLD_AUCTION',
            'source_kind':'EBAY_SOLD_LISTING','exact_match':'true'}
def target():
    t=copy.deepcopy(PRESET)
    t['sold_records']=[evidence_record(sale(i),t,NOW) for i in range(5)]
    return t
def item():
    return {'itemId':'v1|123456789012|0','title':'Pokemon 151 Booster Bundle English Sealed',
        'gtin':'820650853210','conditionId':'1000',
        'localizedAspects':[{'name':'Language','value':'English'},{'name':'Configuration','value':'Box'}],
        'itemLocation':{'country':'US'},'seller':{'username':'synthetic','feedbackScore':100,'feedbackPercentage':'99'},
        'buyingOptions':['FIXED_PRICE'],'price':{'value':'90','currency':'USD'},'shippingOptions':[],
        'estimatedAvailabilities':[{'estimatedAvailabilityStatus':'IN_STOCK'}],
        'itemWebUrl':'https://www.ebay.com/itm/123456789012'}
class PolicyTests(unittest.TestCase):
    def test_no_zip_and_exact_threshold(self):
        t=target();self.assertNotIn('destination_zip',t)
        r=assess(item(),t,NOW);self.assertTrue(r['eligible']);self.assertIsNone(r['shipping'])
        self.assertEqual(r['comparison_basis'],'ITEM_ONLY')
        i=item();i['price']['value']='90.01';self.assertFalse(assess(i,t,NOW)['eligible'])
    def test_shipping_does_not_become_zero_or_change_basis(self):
        i=item();i['shippingOptions']=[{'shippingCostType':'FIXED','shippingCost':{'value':'25','currency':'USD'}}]
        r=assess(i,target(),NOW);self.assertTrue(r['eligible']);self.assertEqual(r['shipping'],'25')
        self.assertNotIn('current_total',r)
    def test_auction_boundaries_and_route(self):
        i=item();i.update(buyingOptions=['AUCTION'],reservePriceMet=True,minimumPriceToBid={'value':'90','currency':'USD'})
        for seconds,expected in [(600,True),(601,False),(0,False)]:
            i['itemEndDate']=(NOW+timedelta(seconds=seconds)).isoformat()
            r=assess(i,target(),NOW);self.assertEqual(r['eligible'],expected)
            if expected:self.assertEqual(r['destination_variable'],'CHANNEL_EBAY_AUCTIONS')
    def test_missing_stale_and_duplicates(self):
        t=target();t['sold_records']=[t['sold_records'][0]]*20
        self.assertEqual(comparison(t,NOW)['sample_count'],1)
        self.assertFalse(comparison(target(),NOW+timedelta(days=15))['ready'])
        self.assertFalse(assess(item(),PRESET,NOW)['eligible'])
    def test_hidden_offer_and_wrong_product_rejected(self):
        for change in ({'price_kind':'ASKING'},{'price_kind':'SOLD_BEST_OFFER_HIDDEN'},
                       {'price_kind':'SOLD_BEST_OFFER_ACTUAL'},{'quantity':'20'},{'language':'Japanese'}):
            row=sale();row.update(change)
            with self.assertRaises(ValueError):evidence_record(row,PRESET,NOW)
    def test_actual_best_offer_accepted(self):
        row=sale();row.update(price_kind='SOLD_BEST_OFFER_ACTUAL',source_kind='EBAY_PRODUCT_RESEARCH')
        self.assertTrue(evidence_record(row,PRESET,NOW)['reviewed'])
    def test_evidence_bound_to_identity(self):
        t=target();t['gtin']='999999999999';self.assertFalse(comparison(t,NOW)['ready'])
    def test_lots_blocked(self):
        for title in ['Pokemon 151 booster bundle lot of 2','2x Pokemon 151 booster bundle','Pokemon 151 2 booster bundles']:
            i=item();i['title']=title;self.assertFalse(assess(i,target(),NOW)['eligible'])
    def test_loader_and_atomic_save_preserve_other_target(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'targets.json';t=target();save(p,[t]);save(p,[t])
            self.assertEqual(load_targets(p)[0]['id'],t['id']);self.assertEqual(len(list(Path(d).glob('*.backup-*'))),1)
    def test_hash_changes_on_evidence_edit(self):
        a=target();b=copy.deepcopy(a);b['sold_records'][0]['item_price']='101'
        self.assertNotEqual(config_hash([a]),config_hash([b]))
    def test_invalid_csv_never_changes_target(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'targets.json';save(p,[PRESET]);original=p.read_text()
            c=Path(d)/'sales.csv'
            with c.open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=COLUMNS);w.writeheader();r=sale();r['quantity']='2';w.writerow(r)
            with patch('sys.argv',['setup','--targets',str(p),'--import-sold',str(c),'--confirm-reviewed']):
                with self.assertRaises(SystemExit):main()
            self.assertEqual(p.read_text(),original)

    def test_csv_success_and_repeat_are_idempotent(self):
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'targets.json';save(p,[PRESET]);c=Path(d)/'sales.csv'
            with c.open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=COLUMNS);w.writeheader()
                for i in range(5):
                    row=sale(i);row['sold_at']=datetime.now(timezone.utc).isoformat();w.writerow(row)
            for _ in range(2):
                with patch('sys.argv',['setup','--targets',str(p),'--import-sold',str(c),'--confirm-reviewed']),redirect_stdout(io.StringIO()):main()
            t=load_targets(p)[0];self.assertEqual(len(t['sold_records']),5)
            self.assertTrue(comparison(t)['ready']);self.assertEqual(comparison(t)['amount'],'100')

class GateTests(unittest.IsolatedAsyncioTestCase):
    async def test_review_hash_and_shadow_gate(self):
        from app.marketplaces.ebay_live import live_gate
        with patch.dict(os.environ,{'EBAY_APPROVED_TARGETS_SHA256':'wrong'}):
            self.assertEqual(await live_gate(None,'right','target',False),'LIVE_REVIEW_HASH_REQUIRED')
        with patch.dict(os.environ,{'EBAY_APPROVED_TARGETS_SHA256':'right'}),patch('app.marketplaces.ebay_shadow.ready',AsyncMock(return_value=False)):
            self.assertEqual(await live_gate(None,'right','target',True),'SHADOW_EVIDENCE_REQUIRED')
        with patch.dict(os.environ,{'EBAY_APPROVED_TARGETS_SHA256':'right'}),patch('app.marketplaces.ebay_shadow.ready',AsyncMock(return_value=True)):
            self.assertIsNone(await live_gate(None,'right','target',False))
    async def test_item_only_actual_delivery_format(self):
        from app.marketplaces.ebay_live import publish
        t=target();now=datetime.now(timezone.utc)
        for row in t['sold_records']:row['sold_at']=now.isoformat()
        r=assess(item(),t,now)
        c=SimpleNamespace(fetchrow=AsyncMock(return_value={'delete_requested':False}),fetchval=AsyncMock(return_value=0),execute=AsyncMock())
        class Store:
            prepare=AsyncMock(return_value=True);ready=AsyncMock(return_value=True)
            @asynccontextmanager
            async def locked(self):yield c
        channel=SimpleNamespace(send=AsyncMock(return_value=SimpleNamespace(id=456)))
        embed=MagicMock();fake=SimpleNamespace(Embed=MagicMock(return_value=embed),AllowedMentions=SimpleNamespace(none=lambda:None))
        with patch.dict('sys.modules',{'discord':fake}),patch('app.marketplaces.ebay_live.allowed_channel',AsyncMock(return_value=channel)),patch.dict(os.environ,{'CHANNEL_EBAY_INTELLIGENCE':'123'}):
            self.assertEqual(await publish(None,Store(),item(),r,0),'DELIVERED')
        self.assertIn('Before shipping, tax',embed.description);self.assertIn('Not quoted',embed.description)
        self.assertNotIn('ZIP',embed.description);channel.send.assert_awaited_once()
