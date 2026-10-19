import ast
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from app.distributor_catalog import packaging,record
from app.distributor_references import install,validated_rows,matched,status
from app.case_identity import personal_case_format,normalize_case_event,shipping_case_event
from app.marketplaces.price_sources import tcgplayer_prices,cardmarket_prices,cardmarket_url
from app.marketplaces.sold_import import reference
from app.marketplaces.launch_status import local_status
from app.tcg_identity import title_identity,has_fusion_world_identity,FUSION_WORLD_GAME,NEW_TCG

NOW=datetime.now(timezone.utc)

def document(market='ebay',currency='USD',region='US'):
    hosts={'ebay':'ebay.com','mercari_us':'mercari.com','buyee_jp':'buyee.jp','tcgplayer':'tcgplayer.com','cardmarket':'cardmarket.com'}
    src='https://'+hosts[market]+'/reviewed-sales'
    identity=dict(product_id='exact-card-123',language='English',condition='Near Mint',finish='Normal',unit='Single Card',quantity=1,currency=currency,region=region)
    return dict(reviewed=True,marketplace=market,source=src,
        product=dict(product_url='https://shop.example/products/exact-card',game='Pokemon',product_family='GLOBAL_STANDARD',currency=currency,region=region,product_type='Single Card',product_name='Exact Card 123'),
        identity=identity,sales=[dict(sale_id=str(i),identity=identity,reviewed=True,price_basis='ACTUAL_SOLD_ITEM',amount=str(100+i),sold_at=(NOW-timedelta(days=1)).isoformat(),source=src) for i in range(5)])

class PackagingTests(unittest.TestCase):
    def test_formats_and_lots(self):
        for title,expected in [('MTG Hobbit Scene Box','SCENE BOX'),('MTG Hobbit Gift Bundle','GIFT BUNDLE'),('MTG Hobbit Bundle','BUNDLE'),('Pokemon Ditto Premium Collection Box','COLLECTION BOX'),('Pokemon Delta Reign Sleeved Booster Pack','SLEEVED BOOSTER PACK')]:
            self.assertEqual(packaging(title),expected)
        for title in ('MTG Hobbit 3x Play Booster Pack Lot','MTG Reality Fracture Play Booster Pack x3','MTG Hobbit Scene Box Set of 2','MTG Hobbit Bundle + Collector Pack','Pokemon card case','MTG Starter Deck Display'):
            self.assertIsNone(packaging(title),title)
    def test_display_case_and_personal_cases(self):
        title='One Piece TCG: [OP-19] TITLE TBA - Display Case [English] (Pre-Order)'
        self.assertIsNone(personal_case_format(title))
        e=normalize_case_event(dict(product_name=title,product_type='Accessory Case',reference_evidence={'amount':'999'}))
        self.assertTrue(shipping_case_event(e));self.assertNotIn('reference_evidence',e)
        for title in ('One Piece OP-19 Acrylic Display Case','Dragon Ball Card Case and Sleeves','Pokemon Briefcase Collection','Empty Booster Display Case'):
            self.assertIsNotNone(personal_case_format(title),title)
    def test_report_uses_revalidated_records(self):
        row=record('https://gtsdistribution.com/item','TEST','Pokemon Starter Deck','101.94','2026-12-01','GTS')
        self.assertTrue(row['ready']);install([row],[])
        checked=validated_rows()
        self.assertFalse(checked[0]['ready']);self.assertIn('PRICE_UNIT_UNVERIFIED',checked[0]['issues'])
        self.assertEqual(status()['ready'],0);self.assertTrue(row['ready'])
    def test_sleeved_pack_generic_retail_type(self):
        row=record('https://www.phdgames.com/2026/10/01/test/','TEST','Pokemon Delta Reign Sleeved Booster Pack','4.49','2026-12-01','PHD')
        e=dict(product_url='https://shop.example/item',product_name=row['name'],product_type='Booster Pack',game='Pokemon',currency='USD',region='US',product_family='GLOBAL_STANDARD',sku='TEST')
        install([row],[e]);self.assertEqual(len(matched(e)),1)
        e['product_name']='Pokemon Delta Reign Booster Pack'
        self.assertEqual(matched(e),[])

class FusionTests(unittest.TestCase):
    def test_reported_title(self):
        title='Bandai Dragon Ball Super Card Game FB01 24Pk Box'
        self.assertTrue(has_fusion_world_identity(title));self.assertEqual(title_identity(title),FUSION_WORLD_GAME)
        from app.shopify_adapter import classify_game
        self.assertEqual(classify_game({'title':title,'product_type':'Booster Box'}),FUSION_WORLD_GAME)
    def test_bare_codes_masters_other_games(self):
        for title in ('FB01 24Pk Box','Bandai FB01 Box','Dragon Ball Super Card Game Masters FB01 Box','Pokemon FB01 Booster Box'):
            self.assertFalse(has_fusion_world_identity(title),title)
        self.assertEqual(title_identity('Pokemon Dragon Ball Super Card Game FB01 Box'),NEW_TCG)
    def test_existing_review_gate_suppresses(self):
        import re,unicodedata
        from app.config import GAME_DATA
        tree=ast.parse(Path('app/tcg_discovery_admin.py').read_text())
        ns=dict(title_identity=title_identity,NEW_TCG=NEW_TCG,GAME_DATA=GAME_DATA,re=re,unicodedata=unicodedata)
        funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'_name_key','_registered','candidate_from_event'}]
        exec(compile(ast.Module(body=funcs,type_ignores=[]),'review','exec'),ns)
        self.assertIsNone(ns['candidate_from_event']({'game':NEW_TCG,'product_name':'Bandai Dragon Ball Super Card Game FB01 24Pk Box'}))

class PricePreviewTests(unittest.TestCase):
    def test_tcg_market_only(self):
        data={'success':True,'results':[{'productId':5,'marketPrice':100,'lowPrice':5,'subTypeName':'Normal'},{'productId':6,'marketPrice':999}]}
        rows=tcgplayer_prices(data,['5']);self.assertEqual(rows[0]['amount'],'100');self.assertFalse(rows[0]['alert_eligible']);self.assertIsNone(rows[0]['sample_count'])
        data['results'][0]['marketPrice']=None;self.assertEqual(tcgplayer_prices(data,['5']),[])
    def test_cardmarket_foil_and_currency(self):
        data={'createdAt':'2026-10-18','priceGuides':[{'idProduct':8,'avg7':10,'avg7-foil':25,'low':1}]}
        self.assertEqual(cardmarket_prices(data,['8'])[0]['amount'],'10')
        r=cardmarket_prices(data,['8'],True)[0];self.assertEqual(r['amount'],'25');self.assertEqual(r['currency'],'EUR');self.assertFalse(r['alert_eligible'])
    def test_remote_url_strict(self):
        self.assertTrue(cardmarket_url('https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_1.json'))
        for url in ('https://evil.example/file','https://downloads.s3.cardmarket.com.evil.example/productCatalog/priceGuide/price_guide_1.json','http://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_1.json'):
            with self.assertRaises(ValueError):cardmarket_url(url)

class SoldTests(unittest.TestCase):
    def test_all_five_markets(self):
        for market,currency,region in [('ebay','USD','US'),('mercari_us','USD','US'),('buyee_jp','JPY','JP'),('tcgplayer','USD','US'),('cardmarket','EUR','EU')]:
            r=reference(document(market,currency,region),NOW)
            self.assertEqual(r['amount'],'102');self.assertEqual(r['sample_count'],5);self.assertEqual(r['currency'],currency)
    def test_asking_hidden_and_identity_rejected(self):
        for key,value in [('price_basis','ASKING'),('hidden_offer',True),('identity',{})]:
            d=copy.deepcopy(document());d['sales'][0][key]=value
            with self.assertRaises(ValueError):reference(d,NOW)
    def test_duplicate_and_expiry(self):
        d=document();d['sales']=[d['sales'][0]]*5
        with self.assertRaises(ValueError):reference(d,NOW)
        d=document();d['sales'][0]['sold_at']=(NOW-timedelta(days=15)).isoformat()
        with self.assertRaises(ValueError):reference(d,NOW)
    def test_actual_policy_uses_imported_reference(self):
        from app.deal_references import matched as file_matches
        from app.price_policy import classify
        r=reference(document());e=dict(r,price='91.80',old_price='103',event_type='PRICE_DROP',in_stock=True)
        e['reference_evidence']={'references':file_matches(e,[r])}
        self.assertEqual(classify(e),'DEAL')
        e['price']='91.81';self.assertEqual(classify(e),'PRICE_DROP')
    def test_import_atomic_preserves_other_product_and_rejects_invalid(self):
        import contextlib,io
        import lotus_market_sold_import as cli
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/'sales.json';dest=Path(td)/'references.json'
            other=reference(document());other['product_url']='https://shop.example/other'
            dest.write_text(json.dumps([other]));src.write_text(json.dumps(document()))
            args=['import',str(src),'--apply','--references',str(dest)]
            with patch('sys.argv',args),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(),0)
                self.assertEqual(cli.main(),0)
            saved=dest.read_text();self.assertEqual(len(json.loads(saved)),2)
            bad=document();bad['sales'][0]['price_basis']='ASKING';src.write_text(json.dumps(bad))
            with patch('sys.argv',args),contextlib.redirect_stdout(io.StringIO()):self.assertEqual(cli.main(),1)
            self.assertEqual(dest.read_text(),saved)

class LaunchTests(unittest.TestCase):
    def test_presence_not_live(self):
        r=local_status({'TCGPLAYER_ACCESS_TOKEN':'fake','CHANNEL_TCGPLAYER_INTELLIGENCE':'123','EBAY_TARGETS_FILE':'/no-such-file'})
        self.assertTrue(r['markets']['tcgplayer']['credentials_present'])
        self.assertFalse(r['markets']['tcgplayer']['live_delivery_verified'])
        self.assertEqual(r['markets']['buyee_jp']['minimum_tier'],'Premium+')
        self.assertEqual(r['markets']['tcgplayer']['minimum_tier'],'Premium')
        self.assertIn('targets_error',r['ebay'])

class CycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_cycle_aggregate_has_no_listing_content(self):
        from app.marketplaces.ebay_shadow import record_cycle
        class Store:pool=AsyncMock()
        store=Store()
        await record_cycle(store,'hash','target',False,'SHADOW',5,1,{'SELLER_EVIDENCE_INSUFFICIENT':1})
        args=store.pool.execute.call_args_list[0].args
        payload=json.loads(args[-1]);self.assertEqual(payload['counts'],{'SELLER_EVIDENCE_INSUFFICIENT':1})
        self.assertNotIn('title',payload);self.assertNotIn('seller',payload)

if __name__=='__main__':unittest.main()
