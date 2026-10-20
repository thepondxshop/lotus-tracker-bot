import unittest
import tempfile
import os
import json
from pathlib import Path
from datetime import datetime,timedelta,timezone
from unittest.mock import patch,AsyncMock
from app import shopify_adapter as adapter,tcg_identity as identity,case_identity as cases
from app.marketplaces import public_market as pm
from app import price_policy as policy

PIKA='Pikachu VMAX 114/100 PSA 10 Japanese Amazing Volt Tackle TCG'
CASES=['Hundreds Bandai One Piece Card Game Dice and Case Vol.1 TCG Japan Official',
'Pokemon Center Playmat Case CoolxMetal','Pokémon Card Game Pikachu Large Gathering Can Case From Japan',
'Pokemon Card Game Play Mat Case Pikapikachu','POKEMON CARD GAME Damage Counter Case Arceus']

class ScreenshotTests(unittest.TestCase):
    def test_reported_accessories(self):
        for title in CASES:
            with self.subTest(title=title):
                e={'product_name':title,'product_type':'Case','reference_evidence':{'amount':'1000'}}
                corrected=cases.normalize_case_event(e)
                self.assertFalse(cases.shipping_case_event(corrected))
                self.assertEqual(corrected['product_category'],'ACCESSORY')
                self.assertNotIn('reference_evidence',corrected)
                self.assertEqual(adapter.infer_product_type(title),'Accessory Case')
                self.assertIsNone(policy.case_destination(corrected))
    def test_real_sealed_cases_retained(self):
        for title in ['Pokemon Booster Bundle Case','One Piece OP-17 Booster Box Case','MTG Commander Deck Case']:
            self.assertTrue(cases.shipping_case_event({'product_name':title,'product_type':'Case'}))
    def test_pikachu_is_known_single(self):
        self.assertEqual(identity.title_identity(PIKA),'Pokemon')
        self.assertEqual(adapter.classify_game({'title':PIKA}),'Pokemon')
        self.assertEqual(adapter.infer_product_type(PIKA),'Single Card')
        self.assertIsNone(identity.discovery_identity({'title':PIKA,'product_type':'Single Card'}))
        from app.tcg_discovery_admin import candidate_from_event
        self.assertIsNone(candidate_from_event({'game':identity.NEW_TCG,'product_name':PIKA}))
    def test_character_merchandise_not_card(self):
        self.assertFalse(identity.graded_pokemon_title('Pikachu PSA 10 plush'))
        self.assertFalse(identity.graded_pokemon_title('Pikachu 114/100'))
    def test_stationery_suppressed_despite_tags(self):
        title='A4 Clear File Pokémon Denki Choudai!'
        self.assertIsNone(adapter.classify_game({'title':title,'product_type':'TCG Product','tags':['Pokemon','TCG']}))
        self.assertIsNone(identity.discovery_identity({'title':title,'product_type':'Booster Box','tags':'TCG'}))

class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_stationery_stops_before_enrichment(self):
        from app.worker import route_event_to_discord
        with patch('app.deal_references.enrich',side_effect=AssertionError('must not enrich')):
            self.assertFalse(await route_event_to_discord(None,{'product_name':'A4 Clear File Pokémon Denki Choudai!'}))

    async def test_pikachu_worker_repairs_before_enrichment(self):
        from app import worker
        seen=[]
        def enrich(e): seen.append(dict(e));return e
        with patch('app.deal_references.enrich',side_effect=enrich),patch.object(worker,'validate_event_game',return_value=False):
            await worker.route_event_to_discord(None,{'product_name':PIKA,'game':identity.NEW_TCG,'product_type':'TCG Product'})
        self.assertEqual(seen[0]['game'],'Pokemon')
        self.assertEqual(seen[0]['product_type'],'Single Card')

class MarketTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{'LOTUS_MARKET_MAPPINGS_FILE':self.tmp.name+'/map.json','LOTUS_MARKET_CACHE_FILE':self.tmp.name+'/cache.json'})
        self.env.start();self.addCleanup(self.env.stop)
        self.m=dict(product_url='https://shop.example/cards/furret',product_name='Furret 136/189',product_type='Single Card',game='Pokemon',product_family='GLOBAL_STANDARD',currency='USD',region='US',reviewed=True,accept_provider_aggregate=True,quantity=1,packaging_verified=True,event_identity={'condition':'Near Mint','language':'English','variant_id':'123'},provider='tcgdex',marketplace='tcgplayer',source_id='swsh3-136',source_name='Furret',variant='normal')
        self.data={'id':'swsh3-136','name':'Furret','pricing':{'tcgplayer':{'unit':'USD','updated':datetime.now(timezone.utc).isoformat(),'normal':{'marketPrice':10,'lowPrice':1}}}}
        self.event={**{k:self.m[k] for k in pm.BIND},**self.m['event_identity'],'in_stock':True,'event_type':'RESTOCK','price':'9'}
        pm.atomic_write(pm.mapping_path(),[self.m])
    def reference(self):return pm.bind(self.m,pm.card_rows(self.data,'swsh3-136')[0])
    def test_actual_policy_published_threshold_and_label(self):
        self.event['reference_evidence']=self.reference()
        self.assertEqual(policy.classify(self.event),'DEAL')
        self.assertIn('BELOW MARKET',policy.deal_title(self.event))
        self.event['price']='9.01';self.assertFalse(policy.alert_matches(self.event))
    def test_source_old_date_not_fetch_date(self):
        self.data['pricing']['tcgplayer']['updated']=(datetime.now(timezone.utc)-timedelta(days=4)).isoformat()
        with self.assertRaises(ValueError):self.reference()
    def test_price_field_not_low_asking(self):
        self.assertEqual(self.reference()['amount'],'10')
        self.assertIsNone(self.reference()['sample_count'])
    def test_changed_variant_condition_currency_and_mapping(self):
        r=self.reference()
        for k,v in [('variant_id','999'),('condition','Played'),('currency','EUR'),('product_type','Graded Card')]:
            self.assertFalse(pm.authorized(r,dict(self.event,**{k:v})))
        self.m['source_name']='Other';pm.atomic_write(pm.mapping_path(),[self.m])
        self.assertFalse(pm.authorized(r,self.event))
    def test_no_stock_inference(self):
        self.event['reference_evidence']=self.reference();self.event['in_stock']=None
        self.assertFalse(policy.alert_matches(self.event))
    def test_direct_policy_rejects_expiry_extension(self):
        r=self.reference();r['expires_at']=(datetime.now(timezone.utc)+timedelta(days=10)).isoformat()
        self.event['reference_evidence']=r;self.assertFalse(policy.qualifying_references(self.event))
    def test_exact_sealed_id_join_and_duplicate_rejection(self):
        d=datetime.now(timezone.utc).isoformat()
        c={'version':1,'createdAt':d,'products':[{'idProduct':1,'name':'151 Booster Box','idCategory':53}]}
        g={'version':1,'createdAt':d,'priceGuides':[{'idProduct':1,'idCategory':53,'avg7':100,'low':1}]}
        r=pm.sealed_rows(c,g)[0];self.assertEqual(r['amount'],'100');self.assertEqual(r['currency'],'EUR')
        c['products']*=2
        with self.assertRaises(ValueError):pm.sealed_rows(c,g)
    def test_sealed_release_cutoff(self):
        from zoneinfo import ZoneInfo
        today=datetime.now(ZoneInfo('America/New_York')).date()
        m=dict(self.m,provider='cardmarket',marketplace='cardmarket',currency='EUR',region='DE',product_type='Booster Box',source_id='1',source_name='151 Booster Box',variant='sealed',category_id=53,release_date_verified=True,release_date_source='https://publisher.example/release',release_date=(today-timedelta(days=30)).isoformat())
        pm.atomic_write(pm.mapping_path(),[m])
        r=pm.row(provider='cardmarket',marketplace='cardmarket',currency='EUR',source=pm.GUIDE,source_id='1',source_name='151 Booster Box',category_id=53,variant='sealed',source_field='avg7',amount=100,source_updated_at=datetime.now(timezone.utc).isoformat())
        e={**self.event,**{k:m[k] for k in pm.BIND},'price':90,'reference_evidence':pm.bind(m,r)}
        self.assertTrue(policy.alert_matches(e))
        m['release_date']=(today-timedelta(days=29)).isoformat();pm.atomic_write(pm.mapping_path(),[m]);e['reference_evidence']=pm.bind(m,r)
        self.assertFalse(policy.alert_matches(e))
    def test_published_average_fallback_label(self):
        d=datetime.now(timezone.utc).isoformat()
        c={'version':1,'createdAt':d,'products':[{'idProduct':1,'name':'151 Booster Box','idCategory':53}]}
        g={'version':1,'createdAt':d,'priceGuides':[{'idProduct':1,'idCategory':53,'avg7':None,'avg':100,'low':1}]}
        r=pm.sealed_rows(c,g)[0]
        self.assertEqual(r['source_field'],'avg');self.assertEqual(r['amount'],'100')
    def test_graded_mapping_rejected(self):
        with self.assertRaises(ValueError):pm.validate(dict(self.m,product_name=PIKA))
    def test_enrichment_reaches_actual_policy(self):
        from app.deal_references import enrich
        with patch.object(pm,'_references',[self.reference()]),patch('app.deal_references.matched',return_value=[]),patch('app.distributor_references.matched',return_value=[]):
            self.assertEqual(policy.classify(enrich(self.event)),'DEAL')

    def test_ambiguous_foil_blocked_and_url_rejected(self):
        with self.assertRaises(ValueError):pm.validate(dict(self.m,marketplace='cardmarket',currency='EUR',region='DE',variant='reverse-holofoil'))
        with self.assertRaises(ValueError):pm.card_url('../../secret')

class ProbeTests(unittest.TestCase):
    def test_discovery_never_claims_stock(self):
        from lotus_pokemon_center_discovery_probe import parse
        d={'results':[{'hits':[{'objectID':'1','name':'Pokemon','url':'/product/1/test','outOfStock':False}]}]}
        r=parse(d);self.assertFalse(r['stock_verified']);self.assertFalse(r['candidates'][0]['stock_verified'])
        d['results'][0]['hits'][0]['url']='https://evil.example/product/1'
        self.assertEqual(parse(d)['candidates'],[])
    def test_duplicate_search_identity_fails(self):
        from lotus_pokemon_center_discovery_probe import parse
        h={'objectID':'1','name':'Pokemon','url':'/product/1/test'}
        with self.assertRaises(ValueError):parse({'results':[{'hits':[h,h]}]})

if __name__=='__main__' :unittest.main()
